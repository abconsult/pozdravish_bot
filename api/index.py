import logging
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Update
from bot.config import TELEGRAM_BOT_TOKEN
from bot.handlers import register_handlers

# Настраиваем логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Инициализируем бота и диспетчер
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp  = Dispatcher()

# Регистрируем все обработчики сообщений
register_handlers(dp, bot)

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        update_dict = await request.json()
        update = Update(**update_dict)
        await dp.feed_update(bot=bot, update=update)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "Pozdravish Bot is running"}
