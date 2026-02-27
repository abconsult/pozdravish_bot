import os
import io
import json
import aiohttp
import urllib.parse
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    URLInputFile, Update,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, CallbackQuery, BufferedInputFile
)
from upstash_redis import Redis
from PIL import Image, ImageDraw, ImageFont

TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
PROTALK_BOT_ID       = os.getenv("PROTALK_BOT_ID", "23141")
PROTALK_TOKEN        = os.getenv("PROTALK_TOKEN", "")
PROTALK_FUNCTION_ID  = os.getenv("PROTALK_FUNCTION_ID", "609")
YUKASSA_TOKEN        = os.getenv("YUKASSA_PROVIDER_TOKEN", "")

# Upstash REST env vars
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

FONTS_LIST = [
    "Lobster",
    "Caveat",
    "Pacifico",
    "Comfortaa",
]

# Соответствие названия на кнопке реальному имени файла
FONTS_FILES = {
    "Lobster": "Lobster-Regular.ttf",
    "Caveat": "Caveat-Regular.ttf",
    "Pacifico": "Pacifico-Regular.ttf",
    "Comfortaa": "Comfortaa-Regular.ttf",
}


OCCASION_TEXT_MAP = {
    "День рождения": "день рождения",
    "Свадьба": "свадьбу",
    "Рождение ребёнка": "рождение ребёнка",
    "8 марта": "праздник 8 марта",
    "Завершение учёбы": "завершение учёбы",
}

STYLE_PROMPT_MAP = {
    "Акварель": (
        "Акварельный фон для дизайна. Тематика: {occasion}. "
        "По краям холста легкие полупрозрачные мазки и брызги краски. "
        "В самом центре большое абсолютно пустое пространство. "
        "Без букв, без слов, без текста. Empty center, watercolor background, pure empty space, no text."
    ),
    "Масло": (
        "Классическая живопись маслом на холсте, фон для дизайна. Тематика: праздник {occasion}. "
        "Богатая текстура мазков, выразительные цвета только по краям композиции. "
        "В центре - большой однотонный пустой участок. "
        "Строго без надписей и букв, без физических рамок для картин. "
        "Oil painting background, blank empty center, no words, zero text, no picture frames, borderless."
    ),
    "Неон": (
        "Киберпанк неоновый фон. Тематика: праздник {occasion}. "
        "Светящиеся элементы по контуру изображения на тёмном фоне. "
        "В центре - абсолютно темная пустая зона без элементов. "
        "Никаких неоновых вывесок, никаких букв и символов. Neon background, blank dark center, no text."
    ),
    "Пастель": (
        "Фон нарисованный сухой пастелью, мягкие мелки. Тематика: праздник {occasion}. "
        "Мягкие переходы цвета по краям изображения. "
        "В центре полностью пустая светлая бумага для надписи. "
        "Никакого текста. Pastel drawing background, blank paper center, no text, no words."
    ),
    "Винтаж": (
        "Старинный винтажный фон в стиле советских почтовых открыток. Тематика: праздник {occasion}. "
        "Пожелтевшая бумага, ретро-орнаменты и флористика только по углам и краям. "
        "В центре - пустое место. "
        "Без каллиграфии, без букв. Vintage retro background, empty blank center, no text, no letters."
    ),
    "Минимализм": (
        "Ультра-минималистичный фон. Тематика: праздник {occasion}. "
        "Очень мало деталей, много пустого пространства. "
        "Только пара аккуратных тематических элементов по краям. "
        "Строго без текста, чистый фон. Minimalist background, lots of negative space, no text."
    ),
}


user_state = {}  # chat_id -> {"occasion": str|None, "style": str|None}

# -------------------- клавиатуры --------------------
def build_occasion_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text=OCCASIONS[0]), KeyboardButton(text=OCCASIONS[1])],
        [KeyboardButton(text=OCCASIONS[2]), KeyboardButton(text=OCCASIONS[3])],
        [KeyboardButton(text=OCCASIONS[4])]
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите повод",
    )

def build_font_keyboard() -> ReplyKeyboardMarkup:
    # Делаем кнопки по 2 в ряд
    buttons = [
        [KeyboardButton(text=FONTS_LIST[0]), KeyboardButton(text=FONTS_LIST[1])],
        [KeyboardButton(text=FONTS_LIST[2]), KeyboardButton(text=FONTS_LIST[3])]
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите шрифт",
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
    
    # Берем нужный промпт для стиля (или минимализм по умолчанию)
    prompt_template = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["Минимализм"])
    prompt = prompt_template.format(occasion=occasion_text)

    protalk_url = (
        "https://api.pro-talk.ru/api/v1.0/run_function_get"
        f"?function_id={PROTALK_FUNCTION_ID}"
        f"&bot_id={PROTALK_BOT_ID}"
        f"&bot_token={PROTALK_TOKEN}"
        f"&prompt={urllib.parse.quote(prompt)}"
        f"&output=image"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(protalk_url) as response:
                if response.status != 200:
                    raise Exception(f"API Error: HTTP {response.status}")
                image_bytes = await response.read()

        img = Image.open(io.BytesIO(image_bytes))
        draw = ImageDraw.Draw(img)
        
        # Формируем текст в зависимости от повода
        if occasion_text == "день рождения":
            text_to_draw = f"С Днём Рождения,\n{name}!"
        elif occasion_text == "свадьбу":
            text_to_draw = f"{name},\nс днём свадьбы!"
        elif occasion_text == "рождение ребёнка":
            text_to_draw = f"{name},\nс новорожденным!"
        elif occasion_text == "праздник 8 марта":
            text_to_draw = f"{name},\nс 8 Марта!"
        elif occasion_text == "завершение учёбы":
            text_to_draw = f"{name},\nс завершением учёбы!"
        else:
            text_to_draw = f"{name},\nпоздравляю!"
        
        # Достаем шрифт из payload
        chosen_font_name = payload.get("font", "Lobster")
        font_filename = FONTS_FILES.get(chosen_font_name, "Lobster-Regular.ttf")


        # Загружаем выбранный шрифт с базовым размером
            font_size = 100 # базовый, крупный размер
        try:
            font_path = os.path.join(os.path.dirname(__file__), "..", font_filename)
            font = ImageFont.truetype(font_path, font_size)
            
            # Проверяем, помещается ли текст (ширина картинки - 1024)
            # Оставляем отступы по краям по 100px (1024 - 200 = 824px для текста)
            while True:
                # Получаем ширину текста
                bbox = draw.textbbox((0, 0), greeting_text, font=font, align="center")
                text_width = bbox[2] - bbox[0]
                
                if text_width <= 824 or font_size <= 40: # если влезло или уже слишком мелко
                    break
                    
                # Уменьшаем шрифт и пробуем снова
                font_size -= 5
                font = ImageFont.truetype(font_path, font_size)
                
        except IOError:
            font = ImageFont.load_default()

        except IOError:
            font = ImageFont.load_default()

        # Центрируем текст
        bbox = draw.textbbox((0, 0), text_to_draw, font=font, align="center")
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (img.width - text_width) / 2
        y = (img.height - text_height) / 2

        # Указываем цвет текстовой надписи
        text_color = (200, 30, 30) # Красный по умолчанию
        if occasion_text == "рождение ребёнка" or occasion_text == "праздник 8 марта":
            text_color = (219, 112, 147) # Розовый
        elif occasion_text == "свадьбу":
            text_color = (218, 165, 32) # Золотистый

        # Рисуем тень (для лучшей читаемости)
        draw.multiline_text((x+2, y+2), text_to_draw, font=font, fill=(50, 50, 50), align="center")
        # Рисуем сам текст
        draw.multiline_text((x, y), text_to_draw, font=font, fill=text_color, align="center")

        # Сохраняем готовую картинку
        output_buffer = io.BytesIO()
        img.save(output_buffer, format="JPEG", quality=90)
        final_image_bytes = output_buffer.getvalue()

        photo = BufferedInputFile(final_image_bytes, filename="postcard.jpg")
        
        await message.answer_photo(
            photo=photo,
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
        print(f"Error in generate_postcard: {e}")
    finally:
        await wait_msg.delete()

# -------------------- handlers -------------------- 
@dp.message(Command("reset"))
async def reset_credits(message: types.Message):
    if message.chat.id != 128247430:
        return
    kv.delete(credits_key(message.chat.id))
    await message.answer("🔄 Счетчик сброшен! Теперь снова доступно 3 бесплатные открытки.")


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
    st = user_state.get(chat_id, {"occasion": None, "style": None, "font": None})
    if not st.get("occasion"):
        await message.answer("Сначала выберите повод:", reply_markup=build_occasion_keyboard())
        return
    st["style"] = message.text
    user_state[chat_id] = st
    # ВМЕСТО ввода имени, теперь просим выбрать шрифт:
    await message.answer("Отлично! Теперь выберите шрифт надписи:", reply_markup=build_font_keyboard())

@dp.message(F.text.in_(FONTS_LIST))
async def choose_font(message: types.Message):
    chat_id = message.chat.id
    st = user_state.get(chat_id, {"occasion": None, "style": None, "font": None})
    
    if not st.get("style"):
        await message.answer("Сначала выберите стиль:", reply_markup=build_style_keyboard())
        return
        
    st["font"] = message.text
    user_state[chat_id] = st
    # Вот ТЕПЕРЬ просим ввести имя  
    await message.answer("Напишите имя получателя открытки:", reply_markup=types.ReplyKeyboardRemove())

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

    await query.answer() 
    
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
    invoice_payload = message.successful_payment.invoice_payload

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
        await generate_postcard(chat_id, message, pending)
    else:
        await message.answer("Выберите повод для новой открытки:", reply_markup=build_occasion_keyboard())

@dp.message()
async def name_and_route(message: types.Message):
    chat_id = message.chat.id
    st = user_state.get(chat_id, {"occasion": None, "style": None, "font": None})

    if not st.get("occasion") or not st.get("style") or not st.get("font"):
        await message.answer("Давайте начнём заново: выберите повод.", reply_markup=build_occasion_keyboard())
        return

    name = message.text.strip()
    if not name:
        await message.answer("Введите имя текстом.")
        return

    # Добавляем "font" в payload
    payload = {"occasion": st["occasion"], "style": st["style"], "font": st["font"], "name": name}

    credits = get_credits(chat_id)
    if credits > 0:
        await generate_postcard(chat_id, message, payload)
        return

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
