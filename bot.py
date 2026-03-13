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


# ===== Загрузка переменных =====
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_KEY")

import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ===== Конфиг =====
MODES_FILE = "user_modes.json"
LIMITS_FILE = "user_limits.json"
HISTORY_FILE = "user_history.json"

COOLDOWN = 10
MAX_LENGTH = 500
MAX_TOKENS = 300
DAILY_LIMIT = 30

last_request_time = {}


# ===== Загрузка JSON =====

def load_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)


def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f)


user_modes = load_json(MODES_FILE)
user_limits = load_json(LIMITS_FILE)
user_history = load_json(HISTORY_FILE)


# ===== История =====

def add_to_history(user_id, text):

    if user_id not in user_history:
        user_history[user_id] = []

    user_history[user_id].insert(0, text)

    user_history[user_id] = user_history[user_id][:5]

    save_json(HISTORY_FILE, user_history)


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)

    if user_id not in user_history or not user_history[user_id]:
        await update.message.reply_text("История пустая.")
        return

    text = "🕓 Последние переводы\n\n"

    for i, phrase in enumerate(user_history[user_id], 1):
        text += f"{i}️⃣ {phrase}\n"

    await update.message.reply_text(text)


# ===== Лимиты =====

def check_daily_limit(user_id):

    today = time.strftime("%Y-%m-%d")

    if user_id not in user_limits:
        user_limits[user_id] = {"date": today, "count": 0}

    if user_limits[user_id]["date"] != today:
        user_limits[user_id] = {"date": today, "count": 0}

    if user_limits[user_id]["count"] >= DAILY_LIMIT:
        return False

    user_limits[user_id]["count"] += 1

    save_json(LIMITS_FILE, user_limits)

    return True


# ===== Кнопки =====

def get_keyboard(mode):

    if mode == "formal":
        switch = InlineKeyboardButton("😎 Разговорно", callback_data="casual")
    else:
        switch = InlineKeyboardButton("🎩 Формально", callback_data="formal")

    regenerate = InlineKeyboardButton("🔁 Перевести заново", callback_data="regen")
    copy = InlineKeyboardButton("📋 Скопировать", callback_data="copy")

    return InlineKeyboardMarkup([
        [regenerate, copy],
        [switch]
    ])


# ===== OpenAI =====

def generate_translation(text, mode):

    style_instruction = (
        "Сделай перевод формальным."
        if mode == "formal"
        else "Сделай перевод разговорным, естественным для Аргентины, используй vos."
    )

    prompt = f"""
Пользователь написал текст на русском.

1) Повтори русский текст.
2) Переведи на аргентинский испанский.
3) Напиши произношение русскими буквами (с аргентинским акцентом).

{style_instruction}

Текст: {text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=MAX_TOKENS,
    )

    return response.choices[0].message.content


# ===== /start =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    mode = user_modes.get(user_id, "formal")

    mode_text = "🎩 Формальный" if mode == "formal" else "😎 Разговорный"

    text = (
        "Привет 👋\n\n"
        "Я перевожу русский текст на аргентинский испанский 🇦🇷\n\n"
        f"Текущий режим: {mode_text}\n\n"
        "Просто отправь фразу."
    )

    await update.message.reply_text(text, reply_markup=get_keyboard(mode))


# ===== Переключение режима =====

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    action = query.data

    if action in ["formal", "casual"]:

        user_modes[user_id] = action
        save_json(MODES_FILE, user_modes)

        mode_text = "🎩 Формальный" if action == "formal" else "😎 Разговорный"

        await query.edit_message_text(
            "Режим переключён ✅\n\n"
            f"Теперь: {mode_text}\n\n"
            "Отправь новый текст.",
            reply_markup=get_keyboard(action),
        )


# ===== Сообщения =====

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

        seconds_passed = now - last_request_time[user_id]

        if seconds_passed < COOLDOWN:

            seconds_left = int(COOLDOWN - seconds_passed)

            await update.message.reply_text(
                f"⏳ Подожди ещё {seconds_left} сек."
            )

            return

    # лимит
    if not check_daily_limit(user_id):

        await update.message.reply_text(
            "🚫 Ты достиг дневного лимита (30 запросов).\n"
            "Попробуй снова завтра 😉"
        )

        return

    last_request_time[user_id] = now

    mode = user_modes.get(user_id, "formal")
    mode_label = "🎩 Формально" if mode == "formal" else "😎 Разговорно"

    await update.message.chat.send_action("typing")

    temp_message = await update.message.reply_text("Перевожу...")

    try:

        result = generate_translation(user_text, mode)

        answer = f"""
{mode_label}

━━━━━━━━━━━━━━

{result}

━━━━━━━━━━━━━━
"""

    except Exception:

        answer = (
            "Ошибка при обращении к AI 😕\n"
            "Проверь API ключ или лимиты."
        )

    await temp_message.edit_text(
        answer,
        reply_markup=get_keyboard(mode),
    )


# ===== Запуск =====

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("history", history))

app.add_handler(CallbackQueryHandler(button_handler))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Бот с OpenAI запущен 🚀")

app.run_polling()