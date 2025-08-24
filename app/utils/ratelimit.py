# app/utils/ratelimit.py
from datetime import datetime, timedelta

def llm_allowed(conv, cooldown_seconds=25) -> bool:
    """
    Evita chamar LLM em todas as mensagens.
    Lê/atualiza conv.context["last_llm"].
    """
    try:
        ctx = conv.context or {}
        last = ctx.get("last_llm")
        now = datetime.utcnow()
        if last:
            # last armazenado como ISO
            try:
                last_dt = datetime.fromisoformat(last.replace("Z",""))
            except Exception:
                last_dt = now - timedelta(days=1)
            if (now - last_dt) < timedelta(seconds=int(cooldown_seconds)):
                return False
        # Autoriza e marca agora
        ctx["last_llm"] = now.isoformat() + "Z"
        conv.context = ctx
        conv.state = conv.state or "ACTIVE"
        conv._sa_instance_state.session.commit()
        return True
    except Exception:
        # Se algo falhar, deixa passar (melhor responder do que bloquear)
        return True
