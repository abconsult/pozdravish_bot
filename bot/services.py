import io
import os
import uuid
import json
import aiohttp
import asyncio
import urllib.parse
import logging
from PIL import Image, ImageDraw, ImageFont
from aiogram import types
from aiogram.types import BufferedInputFile

from bot.config import (
    PROTALK_FUNCTION_ID, PROTALK_BOT_ID, PROTALK_TOKEN, 
    OCCASION_TEXT_MAP, STYLE_PROMPT_MAP, FONTS_FILES
)
from bot.database import consume_credit, set_user_state, record_generation
from bot.keyboards import build_occasion_keyboard

logger = logging.getLogger(__name__)

async def get_greeting_text_from_protalk(name: str, occasion: str) -> str:
    meta_prompt = (
        f"Напиши короткое красивое поздравление на русском языке. "
        f"Получатель: {name}. Повод: {occasion}. "
        f"Стиль: тёплый, искренний, 2-3 предложения максимум. "
        f"Ответь ТОЛЬКО текстом поздравления, без кавычек и пояснений. Не используй списки или нумерацию."
    )

    bot_chat_id = f"ask{uuid.uuid4().hex[:8]}"
    send_url = "https://us1.api.pro-talk.ru/api/v1.0/send_message_async"
    poll_url = "https://us1.api.pro-talk.ru/api/v1.0/get_last_reply"

    payload_send = {
        "bot_id": int(PROTALK_BOT_ID),
        "bot_token": PROTALK_TOKEN,
        "bot_chat_id": bot_chat_id,
        "message": meta_prompt
    }

    payload_poll = {
        "bot_id": int(PROTALK_BOT_ID),
        "bot_token": PROTALK_TOKEN,
        "bot_chat_id": bot_chat_id
    }

    fallback = f"С праздником, {name}! 🎉"

    try:
        async with aiohttp.ClientSession() as session:
            # Отправляем сообщение на генерацию (асинхронно)
            async with session.post(send_url, json=payload_send) as resp:
                if resp.status != 200:
                    logger.error(f"ProTalk send_message_async error: HTTP {resp.status}")
                    return fallback

            # Опрашиваем сервер, пока не получим ответ (до 15 попыток ~15 сек)
            for _ in range(15):
                await asyncio.sleep(1)
                async with session.post(poll_url, json=payload_poll) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data.get("message", "")
                        if text:
                            return text.strip()
            
            logger.warning("ProTalk polling timeout reached")
            return fallback

    except Exception as e:
        logger.error(f"Error fetching greeting text: {e}", exc_info=True)
        return fallback


async def generate_postcard(chat_id: int, message: types.Message, payload: dict):
    occasion = payload["occasion"]
    style = payload["style"]
    text_mode = payload.get("text_mode", "ai")
    text_input = payload["text_input"]

    wait_msg = await message.answer("⏳ Рисую открытку, подождите...")

    is_custom = occasion.startswith("✏️ ")
    if is_custom:
        occasion_text = occasion.replace("✏️ ", "").strip()
    else:
        # No string slicing or replacing. Just a direct exact match with the key in config.py
        occasion_text = OCCASION_TEXT_MAP.get(occasion, "праздник")
        if occasion_text == "праздник":
             logger.error(f"Failed to map occasion exact match: '{occasion}'. Using default.")

    prompt_template = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["Минимализм"])
    # Добавляем жесткие инструкции, чтобы ИИ не генерировал случайные символы на фоне открытки
    image_prompt = prompt_template.format(occasion=occasion_text)
    image_prompt += ". ВАЖНО: На картинке не должно быть никакого текста, букв, надписей, слов или водяных знаков. Оставь в центре картинки фон чистым."

    image_url = (
        "https://api.pro-talk.ru/api/v1.0/run_function_get"
        f"?function_id={PROTALK_FUNCTION_ID}"
        f"&bot_id={PROTALK_BOT_ID}"
        f"&bot_token={PROTALK_TOKEN}"
        f"&prompt={urllib.parse.quote(image_prompt)}"
        f"&output=image"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async def fetch_image():
                async with session.get(image_url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Image API Error: HTTP {resp.status}")
                    return await resp.read()

            if text_mode == "ai":
                image_bytes, greeting_caption = await asyncio.gather(
                    fetch_image(),
                    get_greeting_text_from_protalk(text_input, occasion_text),
                )
            else:
                image_bytes = await fetch_image()
                greeting_caption = "Ваша открытка готова! ✨"

        img = Image.open(io.BytesIO(image_bytes))
        draw = ImageDraw.Draw(img)

        if text_mode == "ai":
            # На открытке пишем только краткое имя и повод
            if occasion_text == "день рождения":
                text_to_draw = f"С Днём Рождения,\n{text_input}!"
            elif occasion_text == "свадьбу":
                text_to_draw = f"{text_input},\nс днём свадьбы!"
            elif occasion_text == "рождение ребёнка":
                text_to_draw = f"{text_input},\nс новорожденным!"
            elif occasion_text == "8 марта":
                text_to_draw = f"{text_input},\nс 8 Марта!"
            elif occasion_text == "завершение учёбы":
                text_to_draw = f"{text_input},\nс завершением учёбы!"
            else:
                text_to_draw = f"{text_input},\nпоздравляю!"
        else:
            text_to_draw = text_input

        chosen_font_name = payload.get("font", "Lobster")
        font_filename = FONTS_FILES.get(chosen_font_name, "Lobster-Regular.ttf")

        font_size = 100
        try:
            font_path = os.path.join(os.path.dirname(__file__), "..", font_filename)
            font = ImageFont.truetype(font_path, font_size)

            while True:
                bbox = draw.textbbox((0, 0), text_to_draw, font=font, align="center")
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                if (text_width <= 824 and text_height <= 800) or font_size <= 30:
                    break
                font_size -= 5
                font = ImageFont.truetype(font_path, font_size)

        except IOError:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text_to_draw, font=font, align="center")
        text_width  = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (img.width  - text_width)  / 2
        y = (img.height - text_height) / 2

        text_color = (200, 30, 30)
        if occasion_text in ("рождение ребёнка", "8 марта"):
            text_color = (219, 112, 147)
        elif occasion_text == "свадьбу":
            text_color = (218, 165, 32)

        draw.multiline_text((x + 2, y + 2), text_to_draw, font=font, fill=(50, 50, 50), align="center")
        draw.multiline_text((x, y),          text_to_draw, font=font, fill=text_color,  align="center")

        output_buffer = io.BytesIO()
        img.save(output_buffer, format="JPEG", quality=90)
        final_image_bytes = output_buffer.getvalue()

        photo = BufferedInputFile(final_image_bytes, filename="postcard.jpg")

        # Подпись к фото теперь - это большое красивое поздравление от ИИ
        await message.answer_photo(photo=photo, caption=f"{greeting_caption}")

        # Metrics & Billing
        left = consume_credit(chat_id)
        record_generation()

        await message.answer(
            f"✅ Списан 1 кредит. Осталось: {left}\n\n"
            f"Хотите ещё одну? Выберите повод:",
            reply_markup=build_occasion_keyboard(),
        )
        set_user_state(chat_id, {"occasion": None, "style": None, "font": None, "text_mode": None})

    except Exception as e:
        logger.error(f"Error in generate_postcard: {e}", exc_info=True)
        await message.answer("❌ Ошибка при генерации. Попробуйте ещё раз.")
    finally:
        await wait_msg.delete()
