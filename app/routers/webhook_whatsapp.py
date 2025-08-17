# app/routers/webhook_whatsapp.py
from flask import Blueprint, request
from ..services import whatsapp_meta as whatsapp
from ..nlp.intent_extractor import extract          # <- NLU reativada (robusta)
from ..db import SessionLocal
from ..models import Company, Customer, Conversation, Message, Appointment, Reminder
from ..config import Settings
from ..services import gcal, stripe_svc
from datetime import datetime, timedelta
import pytz, json
import traceback

bp = Blueprint('whatsapp', __name__)

def _get_company(db):
    # tenta por EMPRESA_ID; se não houver, usa a primeira
    if Settings.EMPRESA_ID:
        try:
            cid = int(Settings.EMPRESA_ID)
            c = db.query(Company).get(cid)
            if c:
                return c
        except Exception:
            pass
    return db.query(Company).first()

@bp.route('/webhook', methods=['GET'])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == Settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@bp.route('/webhook', methods=['POST'])
def incoming():
    data = request.get_json(silent=True) or {}
    # log simples para debug
    print("Webhook RECEIVED:", data, flush=True)

    db = SessionLocal()

    company = _get_company(db)
    if not company:
        # Não há empresa na DB -> evita AttributeError e informa configuração
        return {"error": "No company configured. Seed the database and set EMPRESA_ID."}, 503

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    # Apenas texto para começar
                    if msg.get("type") != "text":
                        continue

                    from_phone = msg["from"]          # ex: 3519...
                    body = msg["text"]["body"]

                    # Upsert do cliente
                    cust = db.query(Customer).filter_by(company_id=company.id, phone=from_phone).first()
                    if not cust:
                        cust = Customer(company_id=company.id, phone=from_phone, locale=company.locale)
                        db.add(cust); db.commit(); db.refresh(cust)

                    # Conversa
                    conv = db.query(Conversation).filter_by(company_id=company.id, customer_id=cust.id).first()
                    if not conv:
                        conv = Conversation(company_id=company.id, customer_id=cust.id, state='IDLE', context={})
                        db.add(conv); db.commit(); db.refresh(conv)

                    # Guarda a mensagem do utilizador
                    db.add(Message(conversation_id=conv.id, role='user', text=body))
                    db.commit()

                    # -------- NLU ROBUSTA --------
                    # (usa app/nlp/intent_extractor.py com fallback seguro)
                    nlu = extract(body) or {}
                    lang = nlu.get('language') or cust.locale or company.locale or "pt-PT"
                    intent = (nlu.get('intent') or "SMALL_TALK").upper()
                    entities = nlu.get('entities') or {}

                    # -------- RESPOSTA POR INTENT (BÁSICA) --------
                    # Puxa dados úteis da empresa
                    brand = company.brand_voice or {}
                    site = brand.get("site_url", "")
                    pricing = brand.get("pricing", {})
                    bh = company.business_hours or {}
                    addr = company.address or ""

                    if intent == "FAQ_INFO":
                        # Resposta resumida de FAQ/Informações
                        reply = (
                            f"🧘 {company.name}\n"
                            f"Horário: {bh}\n"
                            f"Morada: {addr}\n"
                            f"Preços: {pricing}\n"
                            f"Site: {site}"
                        )
                    elif intent == "SCHEDULE":
                        # Fluxo simples de marcação (perguntas guiadas)
                        # Melhorar depois com parser de datas + Google Calendar
                        if conv.state != "ASK_SERVICE":
                            conv.state = "ASK_SERVICE"
                            db.commit()
                            # lista serviços registados
                            services = company.services or []
                            if services:
                                names = ", ".join(s.get("name","") for s in services[:6])
                                reply = (
                                    f"Vamos agendar! Diga qual serviço pretende.\n"
                                    f"Opções: {names}"
                                )
                            else:
                                reply = "Vamos agendar! Diga o nome do serviço pretendido."
                        elif conv.state == "ASK_SERVICE":
                            # guarda serviço no contexto e pergunta data/hora
                            ctx = conv.context or {}
                            ctx["service_raw"] = body
                            conv.context = ctx
                            conv.state = "ASK_DATETIME"
                            db.commit()
                            reply = "Perfeito. Qual a data e hora preferidas? (ex.: 22/08 às 10h)"
                        else:
                            reply = "Para agendar, diga o serviço e a data/hora preferidos."
                    elif intent == "PAYMENT":
                        reply = "Claro! Diga qual serviço/produto pretende pagar e envio um link seguro para pagamento."
                    elif intent == "HUMAN_HANDOFF":
                        reply = "Vou encaminhar para um atendente humano. Um momento, por favor."
                    else:  # SMALL_TALK / OTHER
                        reply = (
                            f"Olá! Sou o assistente da {company.name}. Posso ajudar com informações, marcações e pagamentos."
                            if lang.startswith("pt") else
                            f"Hi! I'm {company.name}'s assistant. I can help with info, bookings and payments."
                        )

                    # Guarda resposta do assistente (com NLU no payload)
                    db.add(Message(conversation_id=conv.id, role='assistant', text=reply, payload={'nlu': nlu}))
                    db.commit()

                    # Enviar pelo WhatsApp Cloud API (sem derrubar o webhook em caso de erro)
                    try:
                        whatsapp.send_msg(from_phone, reply)
                    except Exception as send_err:
                        print("WA SEND ERROR:", repr(send_err), flush=True)
                        # não levantar exceção para não gerar retry agressivo do Meta

        return {"ok": True}, 200

    except Exception as e:
        # Log detalhado para debug remoto, mas responde 200 para evitar retries agressivos
        print("Webhook ERROR:", repr(e), "\n", traceback.format_exc(), flush=True)
        try:
            db.commit()
        except:
            pass
        return {"ok": False}, 200
