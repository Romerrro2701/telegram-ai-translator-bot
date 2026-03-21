from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import os
from dotenv import load_dotenv
import json
import time
from openai import OpenAI


# ===== ENV =====
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = OpenAI()  # ключ берётся из Railway


# ===== CONFIG =====
HISTORY_FILE = "user_history.json"

COOLDOWN = 5
MAX_LENGTH = 500
MAX_TOKENS = 400
DAILY_LIMIT = 50

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


# ===== KEYBOARD =====
def get_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔁 Перевести заново", callback_data="regen"),
            InlineKeyboardButton("📋 Скопировать", callback_data="copy"),
        ]
    ])


# ===== OPENAI =====
def generate_translation(text):

    prompt = f"""
Ты профессиональный переводчик русского на аргентинский испанский.

Важно:
- Используй аргентинский диалект Rioplatense.
- Используй местоимение VOS вместо TÚ.
- Используй аргентинские формы глаголов: querés, podés, tenés, decís.
- Используй лексику Аргентины (che, bueno, dale если уместно).

Структура ответа:

🇷🇺 Русский:
{text}

🇦🇷 Аргентинский:
...

🔊 Произношение:
...
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=MAX_TOKENS,
    )

    return response.choices[0].message.content


# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "Привет 👋\n\n"
        "Я перевожу русский текст на аргентинский испанский 🇦🇷\n\n"
        "Просто отправь фразу."
    )

    await update.message.reply_text(text)


# ===== BUTTONS =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    action = query.data

    if action == "regen":

        if user_id not in user_history or not user_history[user_id]:
            await query.answer("Нет текста для повторного перевода")
            return

        text = user_history[user_id][0]

        result = generate_translation(text)

        await query.edit_message_text(
            result,
            reply_markup=get_keyboard()
        )

    elif action == "copy":

        await query.answer(
            "Текст можно скопировать долгим нажатием 👆",
            show_alert=True
        )


# ===== MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    user_text = update.message.text.strip()

    if len(user_text) > MAX_LENGTH:
        await update.message.reply_text("Слишком длинный текст 🙃")
        return

    add_to_history(user_id, user_text)

    now = time.time()

    # cooldown
    if user_id in last_request_time:
        if now - last_request_time[user_id] < COOLDOWN:
            await update.message.reply_text("⏳ Подожди пару секунд")
            return

    last_request_time[user_id] = now

    await update.message.chat.send_action("typing")

    temp = await update.message.reply_text("Перевожу...")

    try:
        result = generate_translation(user_text)

    except Exception as e:
        print("OPENAI ERROR:", e)
        result = "Ошибка при обращении к AI 😕"

    await temp.edit_text(
        result,
        reply_markup=get_keyboard()
    )


# ===== RUN =====
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Бот запущен 🚀")

app.run_polling()
