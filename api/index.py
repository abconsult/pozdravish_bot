import os
import urllib.parse
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import URLInputFile, Update

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PROTALK_BOT_ID = os.getenv("PROTALK_BOT_ID", "")
PROTALK_TOKEN = os.getenv("PROTALK_TOKEN", "")
PROTALK_FUNCTION_ID = os.getenv("PROTALK_FUNCTION_ID", "")

app = FastAPI()
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для создания открыток. 🎨\n"
        "Напиши мне имя человека, которого хочешь поздравить!"
    )

@dp.message()
async def generate_postcard(message: types.Message):
    wait_msg = await message.answer("⏳ Рисую открытку, подождите пару секунд...")
    target_name = message.text
    
    prompt = f"Поздравительная открытка на день рождения, красивая надпись: С днем рождения, {target_name}!"
    safe_prompt = urllib.parse.quote(prompt)
    
    protalk_url = (
        f"https://api.pro-talk.ru/api/v1.0/run_function_get"
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
            caption=f"🎉 Готово! Открытка для: {target_name}"
        )
    except Exception as e:
        await message.answer("❌ Произошла ошибка при генерации. Попробуйте еще раз.")
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
