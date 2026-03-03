# Асинхронная генерация изображений через Callback

## Обзор изменений

Бот теперь использует асинхронную генерацию изображений через Kie.ai callback вместо polling. Это позволяет обойти ограничение Vercel в 10 секунд на выполнение функции.

### Архитектура

1. **Пользователь запрашивает открытку** → бот создает задачу в Kie.ai
2. **Kie.ai начинает генерацию** → возвращает `taskId`
3. **Бот сохраняет контекст в Redis** (chat_id, параметры, caption)
4. **Функция завершается** (<10 сек, Vercel не обрывает)
5. **Kie.ai завершает генерацию** (8-20 сек) → отправляет POST на webhook
6. **Webhook обрабатывает результат** → отправляет открытку пользователю

## Настройка

### 1. Добавить переменную окружения

В настройках Vercel добавьте:

```bash
WEBHOOK_URL=https://your-domain.vercel.app
```

**Важно:** Без протокола `https://` и без trailing slash.

Пример: `WEBHOOK_URL=https://pozdravish-bot.vercel.app`

### 2. Проверить существующие переменные

Убедитесь, что настроены:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
KIE_API_KEY=your_kie_api_key
UPSTASH_REDIS_REST_URL=your_redis_url
UPSTASH_REDIS_REST_TOKEN=your_redis_token
```

### 3. Развернуть изменения

```bash
git pull origin main
# Vercel автоматически задеплоит изменения
```

## Как это работает

### Создание задачи (services.py)

```python
async def create_image_task_async(
    image_prompt: str,
    chat_id: int,
    message_id: int,
    payload: dict,
    caption: str,
) -> str:
    # Создаем задачу с callBackUrl
    request_payload = {
        "model": "z-image",
        "callBackUrl": f"{WEBHOOK_URL}/api/kie-callback",
        "input": {
            "prompt": image_prompt,
            "aspect_ratio": "1:1",
        },
    }
    
    # Отправляем запрос в Kie.ai
    result = await post_to_kie(request_payload)
    task_id = result["data"]["taskId"]
    
    # Сохраняем контекст в Redis с TTL 5 минут
    save_pending_image_task(
        task_id=task_id,
        data={
            "chat_id": chat_id,
            "message_id": message_id,
            "payload": payload,
            "caption_for_db": caption,
        },
        ttl=300,
    )
    
    return task_id
```

### Обработка callback (api/index.py)

```python
@app.post("/api/kie-callback")
async def kie_callback(request: Request):
    payload = await request.json()
    
    task_id = payload["data"]["taskId"]
    state = payload["data"]["state"]
    
    # Получаем сохраненный контекст из Redis
    task_data = get_pending_image_task(task_id)
    
    if state == "success":
        # Скачиваем изображение, накладываем текст, отправляем пользователю
        await process_kie_callback(...)
    
    return {"status": "ok"}
```

### База данных (database.py)

```python
def save_pending_image_task(task_id: str, data: dict, ttl: int = 300):
    """Сохраняем контекст задачи в Redis с автоудалением через 5 минут."""
    key = f"pending_image:{task_id}"
    kv.setex(key, ttl, json.dumps(data))

def get_pending_image_task(task_id: str) -> dict | None:
    """Получаем и удаляем контекст задачи из Redis."""
    key = f"pending_image:{task_id}"
    val = kv.get(key)
    if val:
        kv.delete(key)
        return json.loads(val)
    return None
```

## Таймауты и TTL

- **Vercel timeout**: 10 секунд (hobby plan)
- **Kie.ai генерация**: 8-20 секунд
- **Redis TTL**: 300 секунд (5 минут)
- **HTTP timeout для скачивания**: 30 секунд

## Обработка ошибок

### 1. Kie.ai вернул ошибку

Callback содержит:
```json
{
  "code": 501,
  "data": {
    "state": "fail",
    "failMsg": "Internal server error"
  }
}
```

Бот редактирует waiting message: "❌ Нейросеть не смогла сгенерировать открытку. Ваш кредит не списан."

### 2. Callback не пришел (timeout в Kie.ai)

Пользователь видит сообщение "⏳ Генерирую открытку..." которое не обновляется.

**Решение**: Redis TTL = 300 сек автоматически очистит данные. Кредит не списывается до успешной отправки.

### 3. Redis недоступен

Функция `save_pending_image_task` выбросит исключение → бот покажет ошибку пользователю → кредит не спишется.

### 4. WEBHOOK_URL не настроен

Функция `create_image_task_async` выбросит:
```python
raise Exception("WEBHOOK_URL not configured")
```

## Логирование

Ключевые точки логирования:

```python
logger.info(f"KIE IMAGE: creating async task with z-image, callback={callback_url}")
logger.info(f"KIE IMAGE: task created, taskId={task_id}")
logger.info(f"KIE CALLBACK: received payload code={code}")
logger.info(f"KIE CALLBACK: processing taskId={task_id}, state={state}")
logger.info(f"KIE CALLBACK: postcard sent successfully to chat_id={chat_id}")
```

## Тестирование

### 1. Локально

```bash
# Установить ngrok для webhook
ngrok http 8000

# Установить WEBHOOK_URL в .env
WEBHOOK_URL=https://abc123.ngrok.io

# Запустить бота
python -m uvicorn api.index:app --reload
```

### 2. На Vercel

Просто создайте открытку через бота. Проверьте логи:

```bash
vercel logs --follow
```

Ищите строки с `KIE IMAGE` и `KIE CALLBACK`.

## Откат на polling (если нужно)

Если callback не работает, можно временно вернуться на polling:

1. Откатить коммит: `git revert 4aa6bab`
2. В `services.py` вернуть старую функцию `get_image_from_kie` с polling
3. Увеличить таймауты или использовать хостинг без лимита

## Преимущества нового подхода

✅ Обходит лимит Vercel 10 секунд  
✅ Не тратит время функции на ожидание  
✅ Поддерживает длительную генерацию (до 5 минут)  
✅ Меньше нагрузка на API (нет повторных запросов)  
✅ Кредиты списываются только при успехе  

## Недостатки

⚠️ Требует публичный WEBHOOK_URL  
⚠️ Сложнее отладка (2 этапа вместо 1)  
⚠️ Зависимость от Redis для хранения контекста  

## FAQ

**Q: Что если Kie.ai отправит callback дважды?**  
A: `get_pending_image_task` удаляет данные из Redis при первом вызове. Повторные callback вернут `None` и будут проигнорированы.

**Q: Можно ли использовать другой хостинг вместо Vercel?**  
A: Да, подойдет любой с поддержкой FastAPI и публичным URL. Для AWS Lambda нужно настроить API Gateway.

**Q: Как защитить webhook от подделок?**  
A: Добавить секретный токен в URL или проверять IP адрес Kie.ai (см. документацию Kie.ai).

**Q: Сколько памяти займет контекст в Redis?**  
A: ~500 байт на задачу. При 1000 одновременных генераций = ~500 KB.
