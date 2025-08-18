# app/routers/webhook_whatsapp.py
from flask import Blueprint, request
from ..services import whatsapp_meta as whatsapp
from ..nlp.intent_extractor import extract
from ..db import SessionLocal
from ..models import Company, Customer, Conversation, Message, Appointment, Reminder
from ..config import Settings
from ..services import gcal, stripe_svc
from datetime import datetime, timedelta
import pytz, json, traceback

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
    print("Webhook RECEIVED:", data, flush=True)

    db = SessionLocal()
    company = _get_company(db)
    if not company:
        return {"error": "No company configured. Seed the database and set EMPRESA_ID."}, 503

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue

                    from_phone = msg["from"]
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

                    # Guarda a msg do utilizador
                    db.add(Message(conversation_id=conv.id, role='user', text=body))
                    db.commit()

                    # -------- NLU --------
                    nlu = extract(body) or {}
                    lang = nlu.get('language') or cust.locale or company.locale or "pt-PT"
                    intent = (nlu.get('intent') or "SMALL_TALK").upper()
                    entities = nlu.get('entities') or {}

                    # -------- Dados da empresa --------
                    brand = company.brand_voice or {}
                    site = brand.get("site_url") or getattr(company, "site_url", "") or ""
                    pricing = brand.get("pricing") or getattr(company, "pricing", {}) or {}
                    bh = company.business_hours or getattr(company, "business_hours", {}) or {}
                    addr = company.address or getattr(company, "address", "") or ""

                    about = (
                        brand.get("about")
                        or getattr(company, "description", None)
                        or getattr(company, "descricao", None)
                        or "Estúdio de yoga focado no bem-estar e equilíbrio para todos os níveis."
                    )

                    def benefits_text():
                        if lang.startswith("pt"):
                            return (
                                "• Melhora a mobilidade e força\n"
                                "• Reduz stress e ansiedade\n"
                                "• Aumenta foco e qualidade do sono\n"
                                "• Adapta-se a vários níveis"
                            )
                        else:
                            return (
                                "• Improves mobility and strength\n"
                                "• Reduces stress and anxiety\n"
                                "• Boosts focus and sleep quality\n"
                                "• Adapts to all levels"
                            )

                    # -------- Lógica por intent --------
                    lower = body.lower()

                    if intent == "FAQ_INFO":
                        concept_like = any(k in lower for k in [
                            "o que é", "o que e", "o que faz", "benefício", "beneficio", "para que serve",
                            "como funciona", "what is", "benefit", "how does it work"
                        ])
                        if concept_like:
                            if lang.startswith("pt"):
                                reply = (
                                    f"🧘 {company.name}\n"
                                    f"{about}\n\n"
                                    f"Benefícios:\n{benefits_text()}\n\n"
                                    f"Queres que te recomende uma modalidade ideal para o teu nível/objetivo?"
                                )
                            else:
                                reply = (
                                    f"🧘 {company.name}\n"
                                    f"{about}\n\n"
                                    f"Benefits:\n{benefits_text()}\n\n"
                                    f"Would you like me to suggest a class style for your level/goal?"
                                )
                        else:
                            # FAQ curta e prática (sem dicts Python)
                            if lang.startswith("pt"):
                                # tenta extrair horas “bonitas”
                                seg_open = (bh.get('segunda') or ['08:00','21:00'])[0]
                                sex_close = (bh.get('sexta') or ['08:00','21:00'])[1]
                                sab = bh.get('sabado') or ['09:00','13:00']
                                dom = bh.get('domingo') or 'fechado'
                                dropin = pricing.get('avulsa', '15')

                                reply = (
                                    f"🧘 {company.name}\n"
                                    f"Horário: seg–sex {seg_open}–{sex_close}, sáb {sab[0]}–{sab[1]}, dom {dom}\n"
                                    f"Morada: {addr}\n"
                                    f"Preços: aula avulsa {dropin}€; packs/mensais sob consulta\n"
                                    f"Site: {site}"
                                )
                            else:
                                seg_open = (bh.get('segunda') or ['08:00','21:00'])[0]
                                sex_close = (bh.get('sexta') or ['08:00','21:00'])[1]
                                sab = bh.get('sabado') or ['09:00','13:00']
                                dom = bh.get('domingo') or 'closed'
                                dropin = pricing.get('avulsa', '15')

                                reply = (
                                    f"🧘 {company.name}\n"
                                    f"Hours: Mon–Fri {seg_open}–{sex_close}, Sat {sab[0]}–{sab[1]}, Sun {dom}\n"
                                    f"Address: {addr}\n"
                                    f"Prices: drop-in {dropin}€; packs/monthlies on request\n"
                                    f"Site: {site}"
                                )

                    elif intent == "SCHEDULE":
                        # Mini-máquina de estados (pergunta serviço -> pergunta data/hora)
                        if conv.state != "ASK_SERVICE":
                            conv.state = "ASK_SERVICE"; db.commit()
                            services = getattr(company, "services", None) or brand.get("services", []) or []
                            if services and isinstance(services, list):
                                names = ", ".join(s.get("name") or s.get("nome","") for s in services[:6])
                            else:
                                names = "Hatha, Vinyasa, Yoga Dinâmico"
                            reply = (
                                "Vamos agendar! Diz qual modalidade/serviço preferes.\n"
                                f"Opções: {names}" if lang.startswith("pt") else
                                "Let's book it! Tell me which class/service you prefer.\n"
                                f"Options: {names}"
                            )
                        elif conv.state == "ASK_SERVICE":
                            ctx = conv.context or {}
                            ctx["service_raw"] = body
                            conv.context = ctx; conv.state = "ASK_DATETIME"; db.commit()
                            reply = (
                                "Perfeito. Qual a data e hora preferidas? (ex.: 22/08 às 10h)"
                                if lang.startswith("pt")
                                else "Great. What date and time do you prefer? (e.g., 22/08 at 10:00)"
                            )
                        else:
                            reply = "Para agendar, diz o serviço e a data/hora." if lang.startswith("pt") else \
                                    "To book, please tell me the service and date/time."

                    elif intent == "PAYMENT":
                        reply = "Claro! Diz qual serviço/produto e envio um link seguro de pagamento." if lang.startswith("pt") else \
                                "Sure! Tell me the service/product and I'll send a secure checkout link."

                    elif intent == "HUMAN_HANDOFF":
                        reply = "Vou encaminhar para um atendente humano. Um momento, por favor." if lang.startswith("pt") else \
                                "I'll hand you off to a human agent. One moment, please."

                    else:  # SMALL_TALK / OTHER
                        reply = (
                            f"Olá! Sou o assistente da {company.name}. Posso ajudar com informações, marcações e pagamentos."
                            if lang.startswith("pt") else
                            f"Hi! I'm {company.name}'s assistant. I can help with info, bookings and payments."
                        )

                    # Guarda resposta (com NLU)
                    db.add(Message(conversation_id=conv.id, role='assistant', text=reply, payload={'nlu': nlu}))
                    db.commit()

                    # Envia pelo WhatsApp (sem derrubar se falhar)
                    try:
                        whatsapp.send_msg(from_phone, reply)
                    except Exception as send_err:
                        print("WA SEND ERROR:", repr(send_err), flush=True)

        return {"ok": True}, 200

    except Exception as e:
        print("Webhook ERROR:", repr(e), "\n", traceback.format_exc(), flush=True)
        try:
            db.commit()
        except:
            pass
        # 200 para o Meta não re-tentar agressivamente enquanto debugamos
        return {"ok": False}, 200
