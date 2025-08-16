from .openai_client import chat

SYSTEM = (
    """You are a customer service AI for multi-tenant companies. \n"
    "Return a strict JSON with: {intent, language, entities}. \n"
    "Intents: FAQ_INFO | SCHEDULE | PAYMENT | SMALL_TALK | HUMAN_HANDOFF | OTHER. \n"
    "language is 'pt-PT' or 'en'. Detect from user message. \n"
    "entities can include: date_iso, time_iso, datetime_iso, service_code, service_name, amount, currency, email, name.\n"""
)

def extract(user_text: str) -> dict:
    user = {"role":"user","content":user_text}
    sys = {"role":"system","content":SYSTEM}
    out = chat([sys, user])
    content = out.choices[0].message.content
    import json
    return json.loads(content)