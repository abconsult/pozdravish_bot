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
    send_url = f"https://api.pro-talk.ru/api/v1.0/ask/{PROTALK_TOKEN}"

    payload_send = {
        "bot_id": int(PROTALK_BOT_ID),
        "chat_id": bot_chat_id,
        "message": meta_prompt
    }

    fallback = f"С праздником, {name}! 🎉"

    logger.info(f"Sending text generation request to ProTalk: URL={send_url}, payload={json.dumps(payload_send, ensure_ascii=False)}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(send_url, json=payload_send) as resp:
                if resp.status != 200:
                    logger.error(f"ProTalk /ask error: HTTP {resp.status}")
                    return fallback
                
                data = await resp.json()
                logger.info(f"ProTalk text generation response: {json.dumps(data, ensure_ascii=False)}")

                # The ProTalk /ask API returns the result in the 'done' field
                text = data.get("done", "")
                if text:
                    return text.strip()
                else:
                    logger.warning("ProTalk returned empty 'done' message in synchronous call")
                    return fallback

    except Exception as e:
        logger.error(f"Error fetching greeting text: {e}", exc_info=True)
        return fallback


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> str:
    """Wrap text to fit within max_width based on the given font."""
    lines = []
    # Split by explicit newlines first
    for paragraph in text.split('\n'):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
            
        current_line = words[0]
        for word in words[1:]:
            # Check if adding the next word exceeds width
            test_line = current_line + " " + word
            bbox = draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            
            if width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        lines.append(current_line)
        
    return '\n'.join(lines)

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
        occasion_text = OCCASION_TEXT_MAP.get(occasion) or OCCASION_TEXT_MAP.get(occasion.strip())
        if not occasion_text:
             for key, val in OCCASION_TEXT_MAP.items():
                 if key in occasion or occasion in key or key.split(" ")[-1] in occasion:
                     occasion_text = val
                     break

        if not occasion_text:
             logger.error(f"Failed to map occasion exact match: '{occasion}'. Using default.")
             occasion_text = "праздник"

    prompt_template = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["Минимализм"])
    image_prompt = prompt_template.format(occasion=occasion_text)
    image_prompt += " Strictly no text, no words, no letters, blank center."

    image_url = (
        "https://api.pro-talk.ru/api/v1.0/run_function_get"
        f"?function_id={PROTALK_FUNCTION_ID}"
        f"&bot_id={PROTALK_BOT_ID}"
        f"&bot_token={PROTALK_TOKEN}"
        f"&prompt={urllib.parse.quote(image_prompt)}"
        f"&output=image"
    )

    logger.info(f"Sending image generation request to ProTalk: prompt='{image_prompt}'")

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
            if is_custom:
                text_to_draw = f"{text_input},\nс праздником: {occasion_text}!"
            elif occasion_text == "день рождения":
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

        # Max text area (e.g. 80% of image width, 80% of image height)
        max_text_width = int(img.width * 0.8)
        max_text_height = int(img.height * 0.8)

        font_size = 100
        try:
            font_path = os.path.join(os.path.dirname(__file__), "..", font_filename)
            font = ImageFont.truetype(font_path, font_size)

            # First try wrapping the text at this font size
            wrapped_text = wrap_text(text_to_draw, font, max_text_width, draw)

            while True:
                bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, align="center")
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                
                if (text_width <= max_text_width and text_height <= max_text_height) or font_size <= 20:
                    break
                
                # Reduce font size and re-wrap
                font_size -= 5
                font = ImageFont.truetype(font_path, font_size)
                wrapped_text = wrap_text(text_to_draw, font, max_text_width, draw)
                
            text_to_draw = wrapped_text

        except IOError:
            font = ImageFont.load_default()
            wrapped_text = wrap_text(text_to_draw, font, max_text_width, draw)
            text_to_draw = wrapped_text

        bbox = draw.multiline_textbbox((0, 0), text_to_draw, font=font, align="center")
        text_width  = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (img.width  - text_width)  / 2
        y = (img.height - text_height) / 2

        text_color = (200, 30, 30)
        if occasion_text in ("рождение ребёнка", "8 марта"):
            text_color = (219, 112, 147)
        elif occasion_text == "свадьбу":
            text_color = (218, 165, 32)
        elif is_custom:
             text_color = (50, 100, 200) # Blue-ish for custom occasions

        draw.multiline_text((x + 2, y + 2), text_to_draw, font=font, fill=(50, 50, 50), align="center")
        draw.multiline_text((x, y),          text_to_draw, font=font, fill=text_color,  align="center")

        output_buffer = io.BytesIO()
        img.save(output_buffer, format="JPEG", quality=90)
        final_image_bytes = output_buffer.getvalue()

        photo = BufferedInputFile(final_image_bytes, filename="postcard.jpg")

        await message.answer_photo(photo=photo, caption=f"{greeting_caption}")

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
