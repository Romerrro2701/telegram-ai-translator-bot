from telegram import Update
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


# ===== УМНЫЙ ПЕРЕВОД =====
def smart_translate(text):

    prompt = f"""
Ты профессиональный переводчик.

Определи язык текста и переведи:

Если русский → переведи на аргентинский испанский (Rioplatense, vos, стиль Буэнос-Айрес)
Если испанский → переведи на русский

ВАЖНО:
- Если перевод на испанский → добавь произношение русскими буквами
- Если перевод на русский → без произношения

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
        return tmp.name


# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет 👋\n\n"
        "Я перевожу текст и голос RU ↔ ES 🇦🇷\n\n"
        "Напиши или отправь голосовое 🎤"
    )


# ===== TEXT =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    user_text = update.message.text.strip()

    if len(user_text) > MAX_LENGTH:
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
        result = smart_translate(user_text)
        add_to_history(user_id, user_text)

    except Exception as e:
        print("OPENAI ERROR:", e)
        result = "Ошибка при обращении к AI 😕"

    await temp.edit_text(result)


# ===== VOICE =====
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.chat.send_action("typing")

    voice = await update.message.voice.get_file()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        await voice.download_to_drive(tmp.name)
        file_path = tmp.name

    try:
        text = speech_to_text(file_path)

        translated = smart_translate(text)

        audio_path = text_to_speech(translated)

        await update.message.reply_voice(
            voice=open(audio_path, "rb"),
            caption=f"📝 {text}\n\n🌍 {translated}"
        )

    except Exception as e:
        print("VOICE ERROR:", e)
        await update.message.reply_text("Ошибка обработки голоса 😕")


# ===== RUN =====
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))

print("Бот запущен 🚀")

app.run_polling()
