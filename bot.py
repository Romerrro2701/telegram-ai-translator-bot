from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

import os
from dotenv import load_dotenv
import json
import time
import tempfile
import asyncio
from openai import OpenAI


# ===== ENV =====
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = OpenAI()


# ===== CONFIG =====
HISTORY_FILE = "user_history.json"

COOLDOWN = 5
MAX_LENGTH = 500
MAX_TOKENS = 400

last_request_time = {}
user_history = {}
dialog_mode = set()


# ===== KEYBOARD =====
def get_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🟢 Начать диалог"],
            ["🔴 Остановить диалог"]
        ],
        resize_keyboard=True
    )


# ===== JSON =====
def load_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)


def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f)


user_history = load_json(HISTORY_FILE)


# ===== HISTORY =====
def add_to_history(user_id, text):
    if user_id not in user_history:
        user_history[user_id] = []

    user_history[user_id].insert(0, text)
    user_history[user_id] = user_history[user_id][:5]

    save_json(HISTORY_FILE, user_history)


# ===== TRANSLATE =====
def smart_translate(text):
    prompt = f"""
Ты профессиональный переводчик.

Если русский → аргентинский испанский (vos, Буэнос-Айрес)
Если испанский → русский

ВАЖНО:
- ll и y → всегда "ш"
- только русские буквы в произношении

Формат:

🇷🇺 Русский:
...

🇦🇷 Аргентинский:
...

🔊 Произношение:
... (только если испанский)

Текст:
{text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=MAX_TOKENS,
    )

    return response.choices[0].message.content


# ===== EXTRACT CLEAN TEXT =====
def extract_translation(text):
    if "🇦🇷" in text:
        return text.split("🇦🇷")[1].split("🔊")[0].strip()
    elif "🇷🇺" in text:
        return text.split("🇷🇺")[1].strip()
    return text


# ===== STT =====
def speech_to_text(file_path):
    with open(file_path, "rb") as audio:
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=audio
        )
    return transcript.text


# ===== TTS =====
def text_to_speech(text):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        audio = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text
        )
        tmp.write(audio.content)
        tmp.flush()
        return tmp.name


# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет 👋\n\n"
        "Я перевожу текст и голос RU ↔ ES 🇦🇷\n\n"
        "Нажми кнопку или отправь сообщение 🎤",
        reply_markup=get_keyboard()
    )


# ===== TEXT =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    text = update.message.text.strip()

    # кнопки
    if text == "🟢 Начать диалог":
        dialog_mode.add(update.effective_user.id)
        await update.message.reply_text("🟢 Режим диалога включен", reply_markup=get_keyboard())
        return

    if text == "🔴 Остановить диалог":
        dialog_mode.discard(update.effective_user.id)
        await update.message.reply_text("🔴 Режим диалога выключен", reply_markup=get_keyboard())
        return

    if len(text) > MAX_LENGTH:
        await update.message.reply_text("Слишком длинный текст 🙃")
        return

    now = time.time()

    if user_id in last_request_time:
        if now - last_request_time[user_id] < COOLDOWN:
            await update.message.reply_text("⏳ Подожди пару секунд")
            return

    last_request_time[user_id] = now

    await update.message.chat.send_action("typing")
    temp = await update.message.reply_text("Перевожу...")

    try:
        result = await asyncio.to_thread(smart_translate, text)

        if not result or len(result.strip()) < 5:
            raise Exception("Empty response")

        add_to_history(user_id, text)

        await temp.edit_text(result)

        # ✅ возвращаем кнопки
        await update.message.reply_text("Готово 👌", reply_markup=get_keyboard())

    except Exception as e:
        print("OPENAI ERROR:", e)

        await temp.edit_text("❌ Ошибка перевода\nПопробуй ещё раз")
        await update.message.reply_text("Попробуй снова", reply_markup=get_keyboard())


# ===== VOICE =====
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.chat.send_action("typing")

    voice = await update.message.voice.get_file()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        await voice.download_to_drive(tmp.name)
        file_path = tmp.name

    try:
        text = await asyncio.to_thread(speech_to_text, file_path)

        if not text or len(text.strip()) < 2:
            raise Exception("STT empty")

        translated_full = await asyncio.to_thread(smart_translate, text)

        if not translated_full or len(translated_full.strip()) < 5:
            raise Exception("Translation empty")

        clean_text = extract_translation(translated_full)

        audio_path = await asyncio.to_thread(text_to_speech, clean_text)

        await update.message.reply_voice(
            voice=open(audio_path, "rb"),
            caption=translated_full,
            reply_markup=get_keyboard()
        )

        # ✅ удаляем файлы
        os.remove(file_path)
        os.remove(audio_path)

    except Exception as e:
        print("VOICE ERROR:", e)

        await update.message.reply_text(
            "❌ Ошибка обработки голоса",
            reply_markup=get_keyboard()
        )


# ===== RUN =====
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))

print("Бот запущен 🚀")

app.run_polling()
