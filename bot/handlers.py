import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, CallbackQuery, BufferedInputFile

from bot.config import ADMIN_ID, OCCASIONS, STYLES, FONTS_LIST, PACKAGES, YUKASSA_TOKEN
from bot.database import (
    kv, credits_key, get_credits, set_user_state, get_user_state,
    add_credits, pending_key, pop_pending, save_pending
)
from bot.keyboards import (
    build_occasion_keyboard, build_style_keyboard,
    build_font_keyboard, build_packages_keyboard, build_text_mode_keyboard
)
from bot.services import generate_postcard

def register_handlers(dp: Dispatcher, bot: Bot):
    @dp.message(Command("reset"))
    async def reset_credits(message: types.Message):
        if message.chat.id != ADMIN_ID:
            return
        kv.delete(credits_key(message.chat.id))
        await message.answer("🔄 Счетчик сброшен! Теперь снова доступно 3 бесплатные открытки.")

    @dp.message(Command("start"))
    async def start(message: types.Message):
        chat_id = message.chat.id
        set_user_state(chat_id, {"occasion": None, "style": None, "font": None, "text_mode": None})
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
        st = get_user_state(chat_id)
        st["occasion"] = message.text
        st["style"] = None
        set_user_state(chat_id, st)
        await message.answer("Теперь выберите стиль:", reply_markup=build_style_keyboard())

    @dp.message(F.text.in_(STYLES))
    async def choose_style(message: types.Message):
        chat_id = message.chat.id
        st = get_user_state(chat_id)
        if not st.get("occasion"):
            await message.answer("Сначала выберите повод:", reply_markup=build_occasion_keyboard())
            return
        st["style"] = message.text
        set_user_state(chat_id, st)

        preview_path = os.path.join(os.path.dirname(__file__), "..", "fonts_preview.jpg")
        try:
            with open(preview_path, "rb") as f:
                preview_bytes = f.read()
            await message.answer_photo(
                photo=BufferedInputFile(preview_bytes, filename="fonts_preview.jpg"),
                caption="Отлично! Теперь выберите шрифт для надписи:",
                reply_markup=build_font_keyboard()
            )
        except FileNotFoundError:
            await message.answer("Отлично! Теперь выберите шрифт для надписи:", reply_markup=build_font_keyboard())

    @dp.message(F.text.in_(FONTS_LIST))
    async def choose_font(message: types.Message):
        chat_id = message.chat.id
        st = get_user_state(chat_id)

        if not st.get("style"):
            await message.answer("Сначала выберите стиль:", reply_markup=build_style_keyboard())
            return

        st["font"] = message.text
        st["text_mode"] = None
        set_user_state(chat_id, st)
        
        await message.answer("Как напишем поздравление?", reply_markup=build_text_mode_keyboard())

    @dp.message(F.text.in_(["✨ Сгенерировать ИИ", "✏️ Написать свой текст"]))
    async def choose_text_mode(message: types.Message):
        chat_id = message.chat.id
        st = get_user_state(chat_id)

        if not st.get("font"):
            await message.answer("Сначала выберите шрифт:", reply_markup=build_font_keyboard())
            return

        mode = "ai" if message.text == "✨ Сгенерировать ИИ" else "custom"
        st["text_mode"] = mode
        set_user_state(chat_id, st)

        if mode == "ai":
            await message.answer("Напишите имя получателя открытки:", reply_markup=types.ReplyKeyboardRemove())
        else:
            await message.answer("Отправьте текст поздравления (лучше 2-3 короткие строки):", reply_markup=types.ReplyKeyboardRemove())

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
    async def text_input_and_route(message: types.Message):
        chat_id = message.chat.id
        st = get_user_state(chat_id)

        if not st.get("occasion") or not st.get("style") or not st.get("font") or not st.get("text_mode"):
            await message.answer("Давайте начнём заново: выберите повод.", reply_markup=build_occasion_keyboard())
            return

        text_input = message.text.strip()
        if not text_input:
            await message.answer("Пожалуйста, отправьте текст.")
            return

        payload = {
            "occasion": st["occasion"], 
            "style": st["style"], 
            "font": st["font"], 
            "text_mode": st["text_mode"],
            "text_input": text_input
        }

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
