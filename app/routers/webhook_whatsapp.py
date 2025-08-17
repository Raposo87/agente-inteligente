# app/routers/webhook_whatsapp.py
from flask import Blueprint, request
from ..services import whatsapp_meta as whatsapp
from ..nlp.intent_extractor import extract
from ..db import SessionLocal
from ..models import Company, Customer, Conversation, Message, Appointment, Reminder
from ..config import Settings
from ..services import gcal, stripe_svc
from datetime import datetime, timedelta
import pytz, json

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
    data = request.json or {}
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

                    db.add(Message(conversation_id=conv.id, role='user', text=body))

                    # NLU (podes trocar por lógica simples enquanto testas)
                    nlu = extract(body)
                    lang = nlu.get('language') or cust.locale or company.locale
                    reply = ("Olá! Sou o assistente da "
                             f"{company.name}. Posso ajudar com informações, marcações e pagamentos."
                            ) if (lang or "").startswith('pt') else (
                             f"Hi! I'm {company.name}'s assistant. I can help with info, bookings and payments."
                            )

                    db.add(Message(conversation_id=conv.id, role='assistant', text=reply, payload={'nlu': nlu}))
                    db.commit()

                    # Enviar pelo WhatsApp Cloud API
                    whatsapp.send_msg(from_phone, reply)

        return {"ok": True}
    except Exception as e:
        # Log leve para debug remoto
        try:
            db.commit()
        except:
            pass
        return {"error": str(e)}, 500
