import os
import json
import urllib.parse
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    URLInputFile, Update,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, CallbackQuery
)
from upstash_redis import Redis

TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
PROTALK_BOT_ID       = os.getenv("PROTALK_BOT_ID", "23141")
PROTALK_TOKEN        = os.getenv("PROTALK_TOKEN", "")
PROTALK_FUNCTION_ID  = os.getenv("PROTALK_FUNCTION_ID", "609")
YUKASSA_TOKEN        = os.getenv("YUKASSA_PROVIDER_TOKEN", "")

# Upstash REST env vars (вы их добавили): UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
kv = Redis.from_env()

app = FastAPI()
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp  = Dispatcher()

FREE_CREDITS = 3

PACKAGES = {
    3:  {"rub": 90, "amount": 9000, "label": "Пакет: 3 открытки"},
    5:  {"rub": 150, "amount": 15000, "label": "Пакет: 5 открыток"},
    10: {"rub": 300, "amount": 30000, "label": "Пакет: 10 открыток"},
}

OCCASIONS = [
    "🎂 День рождения",
    "💍 Свадьба",
    "👶 Рождение ребёнка",
    "🌸 8 марта",
    "🎓 Завершение учёбы",
]

STYLES = [
    "Акварель",
    "Масло",
    "Неон",
    "Пастель",
    "Винтаж",
    "Минимализм",
]

OCCASION_TEXT_MAP = {
    "День рождения": "день рождения",
    "Свадьба": "свадьбу",
    "Рождение ребёнка": "рождение ребёнка",
    "8 марта": "8 марта",
    "Завершение учёбы": "завершение учёбы",
}

STYLE_HINT_MAP = {
    "Акварель": "в нежном акварельном стиле",
    "Масло": "в стиле классической масляной живописи",
    "Неон": "в ярком неоновом стиле с подсветкой",
    "Пастель": "в мягком пастельном стиле рисунок мелками",
    "Винтаж": "в стиле ретро винтажной открытки",
    "Минимализм": "в современном минималистичном стиле",
}

# Непостоянное состояние диалога (повод/стиль) — ок для шага ввода,
# но «pending» для оплаты держим в Redis.
user_state = {}  # chat_id -> {"occasion": str|None, "style": str|None}


# -------------------- клавиатуры --------------------
def build_occasion_keyboard() -> ReplyKeyboardMarkup:
    # Группируем кнопки по 2 штуки в один ряд
    buttons = [
        [KeyboardButton(text=OCCASIONS[0]), KeyboardButton(text=OCCASIONS[1])],
        [KeyboardButton(text=OCCASIONS[2]), KeyboardButton(text=OCCASIONS[3])]
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите повод",
    )


def build_style_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text=STYLES[0]), KeyboardButton(text=STYLES[1])],
        [KeyboardButton(text=STYLES[2]), KeyboardButton(text=STYLES[3])],
        [KeyboardButton(text=STYLES[4]), KeyboardButton(text=STYLES[5])] 
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите стиль",
    )


def build_packages_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for n in (3, 5, 10):
        p = PACKAGES[n]
        # Выбираем правильное окончание
        word = "открытки" if n == 3 else "открыток"
        
        buttons.append([InlineKeyboardButton(
            text=f"{n} {word} — {p['rub']} руб.",
            callback_data=f"buy:{n}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -------------------- Redis helpers --------------------
def credits_key(chat_id: int) -> str:
    return f"credits:{chat_id}"

def pending_key(chat_id: int) -> str:
    return f"pending:{chat_id}"

def get_credits(chat_id: int) -> int:
    val = kv.get(credits_key(chat_id))
    if val is None:
        kv.set(credits_key(chat_id), str(FREE_CREDITS))
        return FREE_CREDITS
    return int(val)

def add_credits(chat_id: int, amount: int) -> int:
    # incrby работает в Redis; в upstash-redis доступен через команда INCRBY как incrby
    # Если вдруг в вашей версии нет incrby, заменим на get+set.
    try:
        return int(kv.incrby(credits_key(chat_id), amount))
    except Exception:
        cur = get_credits(chat_id)
        new = cur + amount
        kv.set(credits_key(chat_id), str(new))
        return new

def consume_credit(chat_id: int) -> int:
    cur = get_credits(chat_id)
    new = max(cur - 1, 0)
    kv.set(credits_key(chat_id), str(new))
    return new

def save_pending(chat_id: int, payload: dict) -> None:
    kv.set(pending_key(chat_id), json.dumps(payload, ensure_ascii=False))

def pop_pending(chat_id: int) -> dict | None:
    val = kv.get(pending_key(chat_id))
    if not val:
        return None
    kv.delete(pending_key(chat_id))
    return json.loads(val)


# -------------------- генерация --------------------
async def generate_postcard(chat_id: int, message: types.Message, payload: dict):
    occasion = payload["occasion"]
    style = payload["style"]
    name = payload["name"]

    wait_msg = await message.answer("⏳ Рисую открытку, подождите немного...")

    occasion_text = next((v for k, v in OCCASION_TEXT_MAP.items() if k in occasion), "праздник")
    style_hint = STYLE_HINT_MAP.get(style, "")

    prompt = (
        f"Красивая поздравительная открытка на {occasion_text}, "
        f"{style_hint}. Надпись: «{name}, поздравляю!»"
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
            photo=protalk_url,
            caption=f"🎉 Готово! Для: {name}\nПовод: {occasion}\nСтиль: {style}"
        )
        left = consume_credit(chat_id)
        await message.answer(
            f"✅ Списан 1 кредит. Осталось: {left}\n\n"
            f"Хотите ещё одну? Выберите повод:",
            reply_markup=build_occasion_keyboard()
        )
        user_state[chat_id] = {"occasion": None, "style": None}
    except Exception as e:
        await message.answer("❌ Ошибка при генерации. Попробуйте ещё раз.")
        print(f"Error: {e}")
    finally:
        await wait_msg.delete()


# -------------------- handlers -------------------- 
@dp.message(Command("reset"))
async def reset_credits(message: types.Message):
    # Замените 123456789 на ваш реальный Telegram ID!
    if message.chat.id != 128247430:
        return
        
    # Удаляем запись о кредитах пользователя
    kv.delete(credits_key(message.chat.id))
    
    # Бот при следующем запросе сам начислит 3 бесплатные
    await message.answer("🔄 Счетчик сброшен! Теперь снова доступно 3 бесплатных открытки.")




@dp.message(Command("start"))
async def start(message: types.Message):
    chat_id = message.chat.id
    user_state[chat_id] = {"occasion": None, "style": None}
    credits = get_credits(chat_id)
    await message.answer(
        f"Привет! Я делаю поздравления с ИИ 😃🙌🏻\n\n"
        f"🎁 Вам доступно {credits} бесплатных открыток.\n"
        f"Выберите повод:",
        reply_markup=build_occasion_keyboard()
    )

@dp.message(Command("balance"))
async def balance(message: types.Message):
    chat_id = message.chat.id
    credits = get_credits(chat_id)
    await message.answer(f"Осталось кредитов: {credits}")

@dp.message(F.text.in_(OCCASIONS))
async def choose_occasion(message: types.Message):
    chat_id = message.chat.id
    st = user_state.get(chat_id, {"occasion": None, "style": None})
    st["occasion"] = message.text
    st["style"] = None
    user_state[chat_id] = st
    await message.answer("Теперь выберите стиль:", reply_markup=build_style_keyboard())

@dp.message(F.text.in_(STYLES))
async def choose_style(message: types.Message):
    chat_id = message.chat.id
    st = user_state.get(chat_id, {"occasion": None, "style": None})
    if not st.get("occasion"):
        await message.answer("Сначала выберите повод:", reply_markup=build_occasion_keyboard())
        return
    st["style"] = message.text
    user_state[chat_id] = st
    await message.answer("Введите имя получателя:", reply_markup=types.ReplyKeyboardRemove())

@dp.callback_query(F.data.startswith("buy:"))
async def buy_package(query: CallbackQuery):
    chat_id = query.message.chat.id
    _, n_str = query.data.split(":")
    n = int(n_str)
    
    if n not in PACKAGES:
        await query.answer("Неверный пакет", show_alert=True)
        return

    pending = kv.get(pending_key(chat_id))
    if not pending:
        await query.answer("Нет активного запроса. Начните с /start", show_alert=True)
        return

    pkg = PACKAGES[n]
    payload = f"pkg:{n}:{chat_id}"

    await query.answer()  # закрываем «часики»
    
    # ИСПРАВЛЕННАЯ СТРОКА: используем bot.send_invoice
    await bot.send_invoice(
        chat_id=chat_id,
        title=pkg["label"],
        description=f"Покупка {n} кредитов на генерацию открыток.",
        payload=payload,
        provider_token=YUKASSA_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label=pkg["label"], amount=pkg["amount"])],
    )

@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)

@dp.message(F.successful_payment)
async def paid(message: types.Message):
    chat_id = message.chat.id
    invoice_payload = message.successful_payment.invoice_payload  # pkg:N:chatid

    try:
        prefix, n_str, _ = invoice_payload.split(":")
        if prefix != "pkg":
            raise ValueError("bad payload")
        n = int(n_str)
        if n not in PACKAGES:
            raise ValueError("unknown package")
    except Exception:
        await message.answer("Оплата прошла, но пакет не распознан. Напишите /start.")
        return

    new_credits = add_credits(chat_id, n)
    await message.answer(f"✅ Оплата успешна! Начислено {n} кредитов. Теперь доступно: {new_credits}")

    pending = pop_pending(chat_id)
    if pending:
        # Сразу выполняем «ожидающую» генерацию
        await generate_postcard(chat_id, message, pending)
    else:
        await message.answer("Выберите повод для новой открытки:", reply_markup=build_occasion_keyboard())

@dp.message()
async def name_and_route(message: types.Message):
    chat_id = message.chat.id
    st = user_state.get(chat_id, {"occasion": None, "style": None})

    if not st.get("occasion") or not st.get("style"):
        await message.answer("Давайте начнём заново: выберите повод.", reply_markup=build_occasion_keyboard())
        return

    name = message.text.strip()
    if not name:
        await message.answer("Введите имя текстом.")
        return

    payload = {"occasion": st["occasion"], "style": st["style"], "name": name}

    credits = get_credits(chat_id)
    if credits > 0:
        await generate_postcard(chat_id, message, payload)
        return

    # Нет кредитов — предлагаем купить пакет
    save_pending(chat_id, payload)
    await message.answer(
        "У вас закончились бесплатные открытки.\n"
        "Выберите пакет для продолжения:",
        reply_markup=build_packages_keyboard()
    )


# -------------------- FastAPI webhook --------------------
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
    return {"message": "OK"}
