# app/utils/ratelimit.py (novo)
import time

def llm_allowed(conv, cooldown_seconds: int = 25) -> bool:
    try:
        ctx = conv.context or {}
        last = float(ctx.get("last_llm_ts", 0))
        now = time.time()
        if now - last < cooldown_seconds:
            return False
        ctx["last_llm_ts"] = now
        conv.context = ctx
        return True
    except Exception:
        return True
