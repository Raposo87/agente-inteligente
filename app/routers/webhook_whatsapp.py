# app/routers/webhook_whatsapp.py
from flask import Blueprint, request, abort
from ..services import whatsapp_meta as whatsapp
from ..nlp.intent_extractor import extract
from ..db import SessionLocal
from ..models import Company, Customer, Conversation, Message, Appointment, Reminder
from ..config import Settings
from ..services import gcal, stripe_svc
from datetime import datetime, timedelta
import pytz, json

bp = Blueprint('whatsapp', __name__)

@bp.route('/webhooks/whatsapp', methods=['GET'])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == Settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

def _get_company(db):
    if Settings.EMPRESA_ID:
        c = db.query(Company).get(int(Settings.EMPRESA_ID))
        if c:
            return c
    return db.query(Company).first()

@bp.route('/webhooks/whatsapp', methods=['POST'])
def incoming():
    data = request.json
    if not data or "entry" not in data:
        return "No data", 400

    db = SessionLocal()
    company = _get_company(db)

    for entry in data["entry"]:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                if msg.get("type") != "text":  # exemplo simples
                    continue
                from_phone = msg["from"]
                body = msg["text"]["body"]

                cust = db.query(Customer).filter_by(company_id=company.id, phone=from_phone).first()
                if not cust:
                    from ..models import Customer  # evita circular import em alguns setups
                    cust = Customer(company_id=company.id, phone=from_phone, locale=company.locale)
                    db.add(cust); db.commit(); db.refresh(cust)

                conv = db.query(Conversation).filter_by(company_id=company.id, customer_id=cust.id).first()
                if not conv:
                    conv = Conversation(company_id=company.id, customer_id=cust.id, state='IDLE', context={})
                    db.add(conv); db.commit(); db.refresh(conv)

                db.add(Message(conversation_id=conv.id, role='user', text=body))

                nlu = extract(body)
                lang = nlu.get('language') or cust.locale or company.locale
                intent = nlu.get('intent')
                ent = nlu.get('entities') or {}

                # ... (lógica de estados igual à tua; no fim envia a resposta)
                reply = "Olá! Posso ajudar com informações, marcações e pagamentos." if lang.startswith('pt') else "Hi! I can help with info, bookings and payments."

                db.add(Message(conversation_id=conv.id, role='assistant', text=reply, payload={'nlu': nlu}))
                db.commit()

                whatsapp.send_msg(from_phone, reply)

    return {"ok": True}
