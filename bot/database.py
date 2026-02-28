import json
from upstash_redis import Redis
from bot.config import FREE_CREDITS

kv = Redis.from_env()

def state_key(chat_id: int) -> str:
    return f"state:{chat_id}"

def get_user_state(chat_id: int) -> dict:
    val = kv.get(state_key(chat_id))
    if val:
        try:
            return json.loads(val) if isinstance(val, str) else val
        except json.JSONDecodeError:
            pass
    return {"occasion": None, "style": None, "font": None, "text_mode": None}

def set_user_state(chat_id: int, state: dict) -> None:
    kv.set(state_key(chat_id), json.dumps(state, ensure_ascii=False))

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
    return json.loads(val) if isinstance(val, str) else val
