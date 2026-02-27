import os
import urllib.parse
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import URLInputFile, Update, ReplyKeyboardMarkup, KeyboardButton

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PROTALK_BOT_ID = os.getenv("PROTALK_BOT_ID", "23141")
PROTALK_TOKEN = os.getenv("PROTALK_TOKEN", "")
PROTALK_FUNCTION_ID = os.getenv("PROTALK_FUNCTION_ID", "609")

app = FastAPI()
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# --- Константы для логики выбора ---
OCCASIONS = [
    "🎂 День рождения",
    "💍 Свадьба",
    "👶 Рождение ребёнка",
    "🌸 8 марта",
]

STYLES = [
    "Акварель",
    "Неон",
    "Пастельный акварельный",
    "Ретро винтаж",
    "Минимализм",
]

# Простое хранение состояния в памяти
user_state = {}  # chat_id -> {"occasion": str | None, "style": str | None}


def build_occasion_keyboard() -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text=txt)] for txt in OCCASIONS]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите повод"
    )


def build_style_keyboard() -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text=txt)] for txt in STYLES]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите стиль"
    )


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    user_state[chat_id] = {"occasion": None, "style": None}
    await message.answer(
        "Привет! Я бот для создания открыток. 🎨\n"
        "Сначала выберите повод:",
        reply_markup=build_occasion_keyboard()
    )


# 1. Выбор повода
@dp.message(F.text.in_(OCCASIONS))
async def choose_occasion(message: types.Message):
    chat_id = message.chat.id
    state = user_state.get(chat_id, {"occasion": None, "style": None})
    state["occasion"] = message.text
    state["style"] = None
    user_state[chat_id] = state
    await message.answer(
        "Отлично! Теперь выберите стиль оформления:",
        reply_markup=build_style_keyboard()
    )


# 2. Выбор стиля
@dp.message(F.text.in_(STYLES))
async def choose_style(message: types.Message):
    chat_id = message.chat.id
    state = user_state.get(chat_id)
    if not state or not state.get("occasion"):
        user_state[chat_id] = {"occasion": None, "style": None}
        await message.answer(
            "Сначала выберите повод:",
            reply_markup=build_occasion_keyboard()
        )
        return
    state["style"] = message.text
    user_state[chat_id] = state
    await message.answer(
        "Теперь напишите имя человека, для которого делаем открытку:",
        reply_markup=types.ReplyKeyboardRemove()
    )


# 3. Имя + генерация открытки
@dp.message()
async def generate_postcard(message: types.Message):
    chat_id = message.chat.id
    state = user_state.get(chat_id)

    if not state or not state.get("occasion") or not state.get("style"):
        user_state[chat_id] = {"occasion": None, "style": None}
        await message.answer(
            "Давайте начнём заново. Выберите повод:",
            reply_markup=build_occasion_keyboard()
        )
        return

    target_name = message.text.strip()
    if not target_name:
        await message.answer("Пожалуйста, отправьте имя текстом.")
        return

    occasion = state["occasion"]
    style = state["style"]

    wait_msg = await message.answer("⏳ Рисую открытку, подождите пару секунд...")

    if "День рождения" in occasion:
        occasion_text = "день рождения"
    elif "Свадьба" in occasion:
        occasion_text = "свадьбу"
    elif "Рождение ребёнка" in occasion:
        occasion_text = "рождение ребёнка"
    elif "8 марта" in occasion:
        occasion_text = "8 марта"
    else:
        occasion_text = "праздник"

    style_hint = {
        "Акварель": "в нежном акварельном стиле",
        "Неон": "в ярком неоновом стиле с подсветкой",
        "Пастельный акварельный": "в мягком пастельном акварельном стиле",
        "Ретро винтаж": "в стиле ретро винтажной открытки",
        "Минимализм": "в современном минималистичном стиле"
    }.get(style, "")

    prompt = (
        f"Красивая поздравительная открытка на {occasion_text}, "
        f"{style_hint}. Надпись: «{target_name}, поздравляю!»"
    )
    safe_prompt = urllib.parse.quote(prompt)

    protalk_url = (
        "https://api.pro-talk.ru/api/v1.0/run_function_get"
        f"?function_id={PROTALK_FUNCTION_ID}"
        f"&bot_id={PROTALK_BOT_ID}"
        f"&bot_token={PROTALK_TOKEN}"
        f"&prompt={safe_prompt}"
        f"&output=image"
    )

    try:
        image_from_url = URLInputFile(protalk_url)
        await message.answer_photo(
            photo=image_from_url,
            caption=(
                f"🎉 Готово! Открытка для: {target_name}\n\n"
                f"Повод: {occasion}\n"
                f"Стиль: {style}"
            )
        )
        user_state[chat_id] = {"occasion": None, "style": None}
        await message.answer(
            "Хотите ещё одну открытку? Выберите новый повод:",
            reply_markup=build_occasion_keyboard()
        )
    except Exception as e:
        await message.answer("❌ Произошла ошибка при генерации. Попробуйте ещё раз.")
        print(f"Error: {e}")
    finally:
        await wait_msg.delete()


@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        update_dict = await request.json()
        update = Update(**update_dict)
        await dp.feed_update(bot=bot, update=update)
    except Exception as e:
        print(f"Error processing update: {e}")
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Telegram Bot API is running on Vercel!"}
