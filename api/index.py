import os
import urllib.parse
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    URLInputFile, Update,
    ReplyKeyboardMarkup, KeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from upstash_redis import Redis

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PROTALK_BOT_ID     = os.getenv("PROTALK_BOT_ID", "23141")
PROTALK_TOKEN      = os.getenv("PROTALK_TOKEN", "")
PROTALK_FUNCTION_ID = os.getenv("PROTALK_FUNCTION_ID", "609")
YUKASSA_TOKEN      = os.getenv("YUKASSA_PROVIDER_TOKEN", "")

# Цена в копейках (99 руб. = 9900)
BASE_PRICE_KOPECKS = 9900

app = FastAPI()
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp  = Dispatcher()
kv  = Redis.from_env()  # читает UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN

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

OCCASION_TEXT_MAP = {
    "День рождения": "день рождения",
    "Свадьба":           "свадьбу",
    "Рождение ребёнка": "рождение ребёнка",
    "8 марта":          "8 марта",
}

STYLE_HINT_MAP = {
    "Акварель":              "в нежном акварельном стиле",
    "Неон":                   "в ярком неоновом стиле с подсветкой",
    "Пастельный акварельный": "в мягком пастельном акварельном стиле",
    "Ретро винтаж":          "в стиле ретро винтажной открытки",
    "Минимализм":             "в современном минималистичном стиле",
}

# Состояние в памяти (повод, стиль, имя, флаг оплаты)
user_state: dict = {}


# ---------------------------------------------------------------------------
# Хелперы: клавиатуры
# ---------------------------------------------------------------------------
def build_occasion_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t)] for t in OCCASIONS],
        resize_keyboard=True, one_time_keyboard=True,
        input_field_placeholder="Выберите повод"
    )

def build_style_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t)] for t in STYLES],
        resize_keyboard=True, one_time_keyboard=True,
        input_field_placeholder="Выберите стиль"
    )


# ---------------------------------------------------------------------------
# Хелперы: скидки + Upstash Redis
# ---------------------------------------------------------------------------
def get_discount(count: int) -> tuple[int, str]:
    """
    count — число УЖЕ совершённых покупок (без текущей).
    Возвращает: (процент скидки, описание).
    """
    if count == 0:
        return 0,  ""
    elif count == 1:
        return 10, "🎁 Скидка 10% за 2-ю покупку"
    elif count < 5:
        return 15, "🌟 Скидка 15% постоянного клиента"
    else:
        return 20, "⭐ Скидка 20% VIP-клиента"

def apply_discount(base: int, pct: int) -> int:
    return int(base * (1 - pct / 100))

def get_purchase_count(chat_id: int) -> int:
    val = kv.get(f"purchases:{chat_id}")
    return int(val) if val else 0

def increment_purchase_count(chat_id: int) -> int:
    return kv.incr(f"purchases:{chat_id}")


# ---------------------------------------------------------------------------
# Хелпер: генерация открытки
# ---------------------------------------------------------------------------
async def generate_postcard(message: types.Message, state: dict):
    chat_id     = message.chat.id
    occasion    = state.get("occasion", "")
    style       = state.get("style", "")
    target_name = state.get("name", "")

    wait_msg = await message.answer("⏳ Рисую открытку, подождите пару секунд...")

    occasion_text = next((v for k, v in OCCASION_TEXT_MAP.items() if k in occasion), "праздник")
    style_hint    = STYLE_HINT_MAP.get(style, "")

    prompt = (
        f"Красивая поздравительная открытка на {occasion_text}, "
        f"{style_hint}. Надпись: «{target_name}, поздравляю!»"
    )
    protalk_url = (
        "https://api.pro-talk.ru/api/v1.0/run_function_get"
        f"?function_id={PROTALK_FUNCTION_ID}"
        f"&bot_id={PROTALK_BOT_ID}"
        f"&bot_token={PROTALK_TOKEN}"
        f"&prompt={urllib.parse.quote(prompt)}"
        f"&output=image"
    )

    try:
        await message.answer_photo(
            photo=URLInputFile(protalk_url),
            caption=(
                f"🎉 Готово! Открытка для: {target_name}\n\n"
                f"Повод: {occasion}\n"
                f"Стиль: {style}"
            )
        )
        user_state[chat_id] = {"occasion": None, "style": None, "name": None, "paid": False}
        await message.answer(
            "Хотите ещё одну открытку? Выберите повод:",
            reply_markup=build_occasion_keyboard()
        )
    except Exception as e:
        await message.answer("❌ Ошибка при генерации. Деньги не списаны повторно.")
        print(f"Error: {e}")
    finally:
        await wait_msg.delete()


# ---------------------------------------------------------------------------
# Обработчики Telegram
# ---------------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    user_state[chat_id] = {"occasion": None, "style": None, "name": None, "paid": False}
    await message.answer(
        "Привет! Я создаю уникальные открытки с ИИ. 🎨\n\n"
        "💳 Стоимость одной открытки: 99 руб.\n"
        "🎁 Постоянным покупателям скидки до 20%!\n\n"
        "Сначала выберите повод:",
        reply_markup=build_occasion_keyboard()
    )


# 1. Выбор повода
@dp.message(F.text.in_(OCCASIONS))
async def choose_occasion(message: types.Message):
    chat_id = message.chat.id
    state = user_state.get(chat_id, {})
    state.update({"occasion": message.text, "style": None, "name": None, "paid": False})
    user_state[chat_id] = state
    await message.answer("Отлично! Теперь выберите стиль:", reply_markup=build_style_keyboard())


# 2. Выбор стиля
@dp.message(F.text.in_(STYLES))
async def choose_style(message: types.Message):
    chat_id = message.chat.id
    state = user_state.get(chat_id, {})
    if not state.get("occasion"):
        user_state[chat_id] = {"occasion": None, "style": None, "name": None, "paid": False}
        await message.answer("Сначала выберите повод:", reply_markup=build_occasion_keyboard())
        return
    state.update({"style": message.text, "name": None, "paid": False})
    user_state[chat_id] = state
    await message.answer(
        "Напишите имя человека, для которого делаем открытку:",
        reply_markup=types.ReplyKeyboardRemove()
    )


# 3. Получаем имя → выставляем счёт ЮКассы
@dp.message()
async def ask_payment(message: types.Message):
    chat_id = message.chat.id
    state = user_state.get(chat_id, {})

    # Незаполненное состояние
    if not state.get("occasion") or not state.get("style"):
        user_state[chat_id] = {"occasion": None, "style": None, "name": None, "paid": False}
        await message.answer("Давайте начнём заново:", reply_markup=build_occasion_keyboard())
        return

    target_name = message.text.strip()
    if not target_name:
        await message.answer("Пожалуйста, напишите имя текстом.")
        return

    state["name"] = target_name
    user_state[chat_id] = state

    # Считаем покупки и начисляем скидку
    purchase_count = get_purchase_count(chat_id)
    discount_pct, discount_label = get_discount(purchase_count)
    final_price = apply_discount(BASE_PRICE_KOPECKS, discount_pct)

    if discount_pct > 0:
        price_info = (
            f"\n\n{discount_label}\n"
            f"💰 Цена: {final_price // 100} ₽ "
            f"(вместо {BASE_PRICE_KOPECKS // 100} ₽)"
        )
    else:
        price_info = f"\n\n💰 Цена: {BASE_PRICE_KOPECKS // 100} ₽"

    await message.answer_invoice(
        title="Поздравительная открытка 🎨",
        description=(
            f"Повод: {state['occasion']}\n"
            f"Стиль: {state['style']}\n"
            f"Для: {target_name}"
            f"{price_info}"
        ),
        payload=f"postcard_{chat_id}",
        provider_token=YUKASSA_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label="Открытка", amount=final_price)],
    )


# 4. Telegram спрашивает: готовы принять платёж?
@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


# 5. Успешная оплата → генерация открытки
@dp.message(F.successful_payment)
async def payment_done(message: types.Message):
    chat_id   = message.chat.id
    state     = user_state.get(chat_id, {})
    charge_id = message.successful_payment.provider_payment_charge_id

    new_count = increment_purchase_count(chat_id)
    print(f"✅ Оплата от {chat_id}, транзакция: {charge_id}, всего покупок: {new_count}")

    await generate_postcard(message, state)


# ---------------------------------------------------------------------------
# FastAPI маршруты
# ---------------------------------------------------------------------------
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
