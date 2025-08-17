# app/nlp/intent_extractor.py
import json, re
from .openai_client import chat

SYSTEM = (
    "You are a customer service AI for multi-tenant companies.\n"
    "Return ONLY a strict JSON with: {\"intent\",\"language\",\"entities\"}.\n"
    "Intents: FAQ_INFO | SCHEDULE | PAYMENT | SMALL_TALK | HUMAN_HANDOFF | OTHER.\n"
    "language must be 'pt-PT' or 'en'. Auto-detect from user message.\n"
    "entities may include: date_iso, time_iso, datetime_iso, service_code, "
    "service_name, amount, currency, email, name.\n"
    "If unsure, intent='SMALL_TALK'. Do not include any extra text.\n"
)

_ALLOWED_INTENTS = {
    "FAQ_INFO","SCHEDULE","PAYMENT","SMALL_TALK","HUMAN_HANDOFF","OTHER"
}

def _safe_default():
    return {"intent":"SMALL_TALK","language":"pt-PT","entities":{}}

def _coerce_result(d: dict) -> dict:
    if not isinstance(d, dict): return _safe_default()
    intent = str(d.get("intent","SMALL_TALK")).upper()
    if intent not in _ALLOWED_INTENTS:
        intent = "SMALL_TALK"
    lang = d.get("language") or "pt-PT"
    # normaliza linguagem
    lang = "pt-PT" if str(lang).lower().startswith("pt") else "en"
    ents = d.get("entities") or {}
    if not isinstance(ents, dict): ents = {}
    return {"intent": intent, "language": lang, "entities": ents}

def _extract_json_from_text(text: str):
    """tenta apanhar o primeiro bloco { ... } para salvar quando o modelo fala demais"""
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None

def extract(user_text: str) -> dict:
    user = {"role":"user","content":user_text}
    sys = {"role":"system","content":SYSTEM}
    try:
        out = chat([sys, user], temperature=0)
        content = out.choices[0].message.content or ""
        # tenta JSON direto
        try:
            return _coerce_result(json.loads(content))
        except Exception:
            # tenta resgatar JSON embutido
            maybe = _extract_json_from_text(content)
            if maybe:
                return _coerce_result(maybe)
            # último recurso: fallback seguro
            return _safe_default()
    except Exception as e:
        # nunca deixar o webhook cair por causa de NLU
        print("NLU error:", repr(e), flush=True)
        return _safe_default()
