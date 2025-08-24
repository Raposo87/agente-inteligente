# app/nlp/responder.py
from .openai_client import chat

SYSTEM_PT = (
    "És um assistente de atendimento de uma empresa.\n"
    "Responde de forma clara, útil, amigável e concisa em pt-PT.\n"
    "Se tiveres dados da empresa (horários, morada, serviços), usa-os como fonte de verdade.\n"
    "Se a pergunta não estiver nos dados, responde com conhecimento geral, sem inventar factos sensíveis.\n"
    "Mantém um tom profissional, direto e acolhedor.\n"
)

SYSTEM_EN = (
    "You are a company's customer service assistant.\n"
    "Reply clearly, helpfully, and concisely.\n"
    "If company data (hours, address, services) is available, use it as source of truth.\n"
    "If the question isn't covered by that data, answer with general knowledge without making up sensitive facts.\n"
    "Tone: professional, friendly, to-the-point.\n"
)

def _system_for_locale(locale: str) -> str:
    return SYSTEM_EN if str(locale or "").lower().startswith("en") else SYSTEM_PT

def _company_card(company: dict) -> str:
    if not company: 
        return ""
    name = company.get("name") or ""
    addr = (company.get("address") or "") or (company.get("brand_voice") or {}).get("address") or ""
    site = company.get("site_url") or (company.get("brand_voice") or {}).get("site_url") or ""
    hours = company.get("business_hours") or (company.get("brand_voice") or {}).get("business_hours") or {}
    seg = (hours.get("segunda") or ["08:00","21:00"])
    sex = (hours.get("sexta") or ["08:00","21:00"])
    sab = (hours.get("sabado") or ["09:00","13:00"])
    dom = (hours.get("domingo") or "fechado")
    lines = []
    if name: lines.append(f"🏷️ {name}")
    if addr: lines.append(f"📍 {addr}")
    if hours:
        if isinstance(dom, (list, tuple)) and len(dom) >= 2:
            dom_str = f"{dom[0]}–{dom[1]}"
        else:
            dom_str = str(dom)
        lines.append(f"🕒 seg–sex {seg[0]}–{seg[1]}, sáb {sab[0]}–{sab[1]}, dom {dom_str}")
    if site: lines.append(f"🌐 {site}")
    return "\n".join(lines)

def generate_freeform_reply(
    company: dict,
    conversation_summary: str,
    user_text: str,
    locale: str = "pt-PT",
    temperature: float = 0.4,
    max_tokens: int = 400,
) -> str:
    sys = {"role": "system", "content": _system_for_locale(locale)}
    card = _company_card(company)
    ctx = []
    if conversation_summary:
        ctx.append({"role": "system", "content": f"[CONTEXT SUMMARY]\n{conversation_summary}"})
    if card:
        ctx.append({"role": "system", "content": f"[COMPANY]\n{card}"})
    user = {"role": "user", "content": user_text}

    out = chat(
        [sys, *ctx, user],
        temperature=temperature,
        max_tokens=max_tokens
    )
    return out.choices[0].message.content.strip()
