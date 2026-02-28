import io
import os
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
        f"Ответь ТОЛЬКО текстом поздравления, без кавычек и пояснений."
    )

    # Use the proper text completion API for ProTalk, not the function runner
    # Function 609 is only for images.
    protalk_url = (
        "https://api.pro-talk.ru/api/v1.0/completion"
    )
    
    payload = {
        "bot_id": PROTALK_BOT_ID,
        "bot_token": PROTALK_TOKEN,
        "messages": [
            {"role": "user", "content": meta_prompt}
        ]
    }

    fallback = f"С праздником, {name}! 🎉"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(protalk_url, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"ProTalk text API returned status: {resp.status}")
                    return fallback

                result = await resp.json()
                
                # Extract text based on standard ChatCompletions format
                try:
                    if "choices" in result and len(result["choices"]) > 0:
                        text = result["choices"][0]["message"]["content"]
                        return text.strip() or fallback
                    elif "response" in result:
                        return str(result["response"]).strip() or fallback
                    else:
                        logger.error(f"Unexpected response format from ProTalk: {result}")
                        return fallback
                except Exception as e:
                    logger.error(f"Failed to parse ProTalk text response: {e}", exc_info=True)
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
        occasion_text = next((v for k, v in OCCASION_TEXT_MAP.items() if k in occasion), "праздник")

    prompt_template = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["Минимализм"])
    image_prompt = prompt_template.format(occasion=occasion_text)

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
                if text_width <= 824 or font_size <= 40:
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
