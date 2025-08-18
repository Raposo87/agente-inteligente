# app/routers/webhook_whatsapp.py
from flask import Blueprint, request
from ..services import whatsapp_meta as whatsapp
from ..nlp.intent_extractor import extract
from ..db import SessionLocal
from ..models import Company, Customer, Conversation, Message
from ..config import Settings
from ..services import gcal, stripe_svc  # gcal é opcional aqui; stripe_svc é usado
from datetime import datetime
import unicodedata, re, traceback

bp = Blueprint('whatsapp', __name__)

# -------------------- Helpers --------------------

def _get_company(db):
    if Settings.EMPRESA_ID:
        try:
            cid = int(Settings.EMPRESA_ID)
            c = db.query(Company).get(cid)
            if c:
                return c
        except Exception:
            pass
    return db.query(Company).first()

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()

def _detect_english(user_text: str) -> bool:
    """
    Só troca para EN se detectar termos típicos de EN.
    'ok/okay' NÃO forçam EN.
    """
    t = (user_text or "").lower().strip()
    if t in {"ok", "ok.", "okay", "okay."}:
        return False
    en_hits = any(w in t for w in ["book", "schedule", "class", "what", "when", "how", "price", "pay", "payment", "benefit", "hi", "hello"])
    pt_hits = any(w in t for w in ["olá", "ola", "marcar", "aula", "preço", "preco", "pagar", "benefício", "beneficio", "horário", "horario"])
    return en_hits and not pt_hits

def _find_service(services, user_text):
    """
    Tenta casar pelo nome (case-insensitive + sem acentos).
    services: lista de dicts, cada um podendo ter 'name'/'nome', 'schedule'/'horarios' etc.
    """
    if not services:
        return None
    nt = _norm(user_text)
    best = None
    for s in services:
        name = s.get("name") or s.get("nome") or ""
        if _norm(name) in nt or nt in _norm(name):
            best = s
            break
    # fallback: tentativa parcial por palavras
    if not best:
        for s in services:
            name = s.get("name") or s.get("nome") or ""
            if any(tok and tok in _norm(name) for tok in nt.split()):
                best = s
                break
    return best

def _service_days_times(service, lang_pt=True):
    """
    Extrai dias & horários do serviço.
    Suporta formatos:
      - service['schedule'] = {'segunda': ['10:00','18:00'], 'quarta': ['...','...'], ...}
      - service['horarios']  (sinónimo PT)
      - service['slots'] = [{'day':'tuesday','times':['10:00','18:00']}, ...]
    """
    if not service:
        return None, None
    sched = service.get("schedule") or service.get("horarios")
    if isinstance(sched, dict):
        # normaliza chaves
        return list(sched.keys()), sched
    slots = service.get("slots")
    if isinstance(slots, list):
        # converte lista em dict {day: times}
        out = {}
        for it in slots:
            day = (it.get("day") or it.get("dia") or "").lower()
            times = it.get("times") or it.get("horas") or []
            if day:
                out.setdefault(day, [])
                out[day].extend(times)
        return list(out.keys()), out
    return None, None

def _format_days_times(days, mapping, lang_pt=True):
    if not days or not mapping:
        return ""
    order_pt = ["segunda","terca","terça","quarta","quinta","sexta","sabado","sábado","domingo"]
    order_en = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    order = order_pt if lang_pt else order_en

    # Mapear chaves PT/EN
    def key_norm(k):
        k2 = _norm(k)
        # normalizações rápidas
        repl = {"terca":"terça", "sabado":"sábado"}
        return repl.get(k2, k2)

    lines = []
    for d in order:
        # tenta encontrar d nas chaves
        found = None
        for k in mapping.keys():
            if key_norm(k) == key_norm(d):
                found = k; break
        if not found:
            continue
        times = mapping.get(found) or []
        if isinstance(times, list):
            times_str = ", ".join(times)
        else:
            # pode vir ['10:00','18:00'] como janela, mas vamos imprimir raw
            times_str = str(times)
        if lang_pt:
            day_label = {"segunda":"Seg", "terça":"Ter", "terca":"Ter", "quarta":"Qua", "quinta":"Qui", "sexta":"Sex", "sábado":"Sáb", "sabado":"Sáb", "domingo":"Dom"}.get(key_norm(found), found.title())
        else:
            day_label = found.title()
        lines.append(f"{day_label}: {times_str}")
    return "\n".join(lines)

# -------------------- Rotas --------------------

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
        return {"error": "No company configured. Seed DB & set EMPRESA_ID."}, 200

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # Ignora eventos de status (sent/delivered/read)
                if value.get("statuses"):
                    print("Ignoring statuses event", flush=True)
                    continue

                messages = value.get("messages", [])
                if not messages:
                    continue

                for msg in messages:
                    if msg.get("type") != "text":
                        continue

                    msg_id = msg.get("id")
                    from_phone = msg["from"]
                    body = (msg.get("text") or {}).get("body", "")

                    # FINALIZAR CONVERSA (comando explícito)
                    if _norm(body) == "finalizar conversa":
                        # encerra conversa
                        cust = db.query(Customer).filter_by(company_id=company.id, phone=from_phone).first()
                        if cust:
                            conv = db.query(Conversation).filter_by(company_id=company.id, customer_id=cust.id).first()
                            if conv:
                                conv.state = "IDLE"
                                conv.context = {}
                                db.commit()
                        try:
                            whatsapp.send_msg(from_phone, "Conversa finalizada. Até breve! 🙏")
                        except Exception as e_send:
                            print("WA SEND ERROR:", repr(e_send), flush=True)
                        return {"ok": True}, 200

                    # Upsert cliente
                    cust = db.query(Customer).filter_by(company_id=company.id, phone=from_phone).first()
                    if not cust:
                        cust = Customer(company_id=company.id, phone=from_phone, locale=company.locale)
                        db.add(cust); db.commit(); db.refresh(cust)

                    # Conversa
                    conv = db.query(Conversation).filter_by(company_id=company.id, customer_id=cust.id).first()
                    if not conv:
                        conv = Conversation(company_id=company.id, customer_id=cust.id, state='IDLE', context={})
                        db.add(conv); db.commit(); db.refresh(conv)

                    # Deduplicação por wamid
                    ctx = conv.context or {}
                    last_wamid = ctx.get("last_wamid")
                    if msg_id and last_wamid == msg_id:
                        print(f"Duplicate wamid detected ({msg_id}) -> skipping reply", flush=True)
                        continue
                    if msg_id:
                        ctx["last_wamid"] = msg_id
                        conv.context = ctx
                        db.commit()

                    # Guarda mensagem do utilizador
                    db.add(Message(conversation_id=conv.id, role='user', text=body, payload={"wamid": msg_id} if msg_id else {}))
                    db.commit()

                    # NLU robusta (e deteção de idioma com regra PT>EN)
                    try:
                        nlu = extract(body) or {}
                    except Exception as nlu_err:
                        print("NLU error:", repr(nlu_err), flush=True)
                        nlu = {}

                    # Idioma: só EN se claramente em inglês
                    if _detect_english(body):
                        lang = "en"
                    else:
                        lang = "pt-PT"

                    intent = (nlu.get('intent') or "SMALL_TALK").upper()
                    entities = nlu.get('entities') or {}

                    # Dados da empresa
                    brand = company.brand_voice or {}
                    site = brand.get("site_url") or getattr(company, "site_url", "") or ""
                    pricing = brand.get("pricing") or getattr(company, "pricing", {}) or {}
                    bh = company.business_hours or getattr(company, "business_hours", {}) or {}
                    addr = company.address or getattr(company, "address", "") or ""
                    services = getattr(company, "services", None) or brand.get("services", []) or []

                    about = (
                        brand.get("about")
                        or getattr(company, "description", None)
                        or getattr(company, "descricao", None)
                        or "Estúdio de yoga focado no bem-estar e equilíbrio para todos os níveis."
                    )

                    # ---------- Lógica ----------
                    reply = None
                    lower = body.lower()

                    if intent == "FAQ_INFO":
                        concept_like = any(k in lower for k in [
                            "o que é", "o que e", "o que faz", "benefício", "beneficio", "para que serve",
                            "como funciona", "what is", "benefit", "how does it work"
                        ])
                        if concept_like:
                            if lang.startswith("pt"):
                                reply = (
                                    f"🧘 {company.name}\n{about}\n\n"
                                    "Benefícios:\n"
                                    "• Melhora a mobilidade e força\n"
                                    "• Reduz stress e ansiedade\n"
                                    "• Aumenta foco e qualidade do sono\n"
                                    "• Adapta-se a vários níveis\n\n"
                                    "Queres que te recomende uma modalidade ideal para o teu nível/objetivo?"
                                )
                            else:
                                reply = (
                                    f"🧘 {company.name}\n{about}\n\n"
                                    "Benefits:\n"
                                    "• Improves mobility and strength\n"
                                    "• Reduces stress and anxiety\n"
                                    "• Boosts focus and sleep quality\n"
                                    "• Adapts to all levels\n\n"
                                    "Would you like me to suggest a class style for your level/goal?"
                                )
                        else:
                            # FAQ reduzida (sem dicionários raw)
                            seg_open = (bh.get('segunda') or ['08:00','21:00'])[0]
                            sex_close = (bh.get('sexta') or ['08:00','21:00'])[1]
                            sab = bh.get('sabado') or ['09:00','13:00']
                            dom = bh.get('domingo') or ('fechado' if lang.startswith("pt") else 'closed')
                            dropin = pricing.get('avulsa', '15')
                            reply = (
                                f"🧘 {company.name}\n"
                                f"Horário: seg–sex {seg_open}–{sex_close}, sáb {sab[0]}–{sab[1]}, dom {dom}\n"
                                f"Morada: {addr}\n"
                                f"Preços: aula avulsa {dropin}€; packs/mensais sob consulta\n"
                                f"Site: {site}"
                                if lang.startswith("pt") else
                                f"🧘 {company.name}\n"
                                f"Hours: Mon–Fri {seg_open}–{sex_close}, Sat {sab[0]}–{sab[1]}, Sun {dom}\n"
                                f"Address: {addr}\n"
                                f"Prices: drop-in {dropin}€; packs/monthlies on request\n"
                                f"Site: {site}"
                            )

                    elif intent == "SCHEDULE" or conv.state in ["ASK_SERVICE", "ASK_DATETIME", "ASK_SLOT"]:
                        # Início do fluxo
                        if conv.state not in ["ASK_SERVICE", "ASK_DATETIME", "ASK_SLOT"]:
                            conv.state = "ASK_SERVICE"; db.commit()
                            if services and isinstance(services, list):
                                names = ", ".join(s.get("name") or s.get("nome","") for s in services[:6])
                            else:
                                names = "Hatha Yoga, Vinyasa Yoga, Yoga Dinâmico"
                            reply = (
                                "Vamos agendar! Diz qual modalidade/serviço preferes.\n"
                                f"Opções: {names}" if lang.startswith("pt") else
                                "Let's book it! Tell me which class/service you prefer.\n"
                                f"Options: {names}"
                            )

                        elif conv.state == "ASK_SERVICE":
                            # Aceita qualquer input como serviço e já mostra dias & horários dessa modalidade
                            sel = _find_service(services, body)
                            ctx = conv.context or {}
                            ctx["service_raw"] = body
                            ctx["service_name"] = (sel.get("name") or sel.get("nome")) if sel else body
                            # Extrai e mostra agenda
                            days, mapping = _service_days_times(sel, lang_pt=lang.startswith("pt"))
                            if days and mapping:
                                agenda_txt = _format_days_times(days, mapping, lang_pt=lang.startswith("pt"))
                                reply = (
                                    f"Para {ctx['service_name']}, temos:\n{agenda_txt}\n\n"
                                    "Escolhe o dia e a hora (ex.: terça às 19:00)."
                                    if lang.startswith("pt") else
                                    f"For {ctx['service_name']}, we have:\n{agenda_txt}\n\n"
                                    "Please choose a day and time (e.g., Tuesday at 19:00)."
                                )
                                conv.state = "ASK_SLOT"
                            else:
                                reply = (
                                    "Registei a modalidade. Diz a data e a hora pretendidas (ex.: 22/08 às 10:00)."
                                    if lang.startswith("pt") else
                                    "Got it. Tell me your preferred date and time (e.g., 22/08 at 10:00)."
                                )
                                conv.state = "ASK_DATETIME"
                            conv.context = ctx; db.commit()

                        elif conv.state == "ASK_SLOT":
                            # Cliente escolheu um dia/hora de entre os apresentados → criar checkout Stripe
                            ctx = conv.context or {}
                            service_name = ctx.get("service_name") or ctx.get("service_raw") or "Aula"
                            # Extrair algo tipo "terça às 19:00" / "tuesday at 19:00"
                            txt = body.lower()
                            # captura horário HH:MM
                            m_time = re.search(r"(\d{1,2}[:h]\d{2})", txt)
                            chosen_time = m_time.group(1).replace("h", ":") if m_time else None
                            # captura dia textual simples
                            weekdays_pt = ["segunda","terca","terça","quarta","quinta","sexta","sabado","sábado","domingo"]
                            weekdays_en = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
                            day_found = None
                            for d in weekdays_pt + weekdays_en:
                                if d in txt:
                                    day_found = d; break

                            if not (day_found and chosen_time):
                                reply = (
                                    "Preciso do dia e da hora (ex.: terça às 19:00)."
                                    if lang.startswith("pt") else
                                    "I need the day and time (e.g., Tuesday at 19:00)."
                                )
                            else:
                                # Monta metadata para checkout
                                amount_eur = pricing.get('avulsa') or 15
                                metadata = {
                                    "service_name": service_name,
                                    "weekday": day_found,
                                    "time": chosen_time,
                                    "customer_phone": from_phone,
                                    "company_id": str(company.id),
                                }
                                try:
                                    checkout = stripe_svc.create_checkout_session(
                                        amount_eur=float(amount_eur),
                                        currency="eur",
                                        success_url=Settings.STRIPE_SUCCESS_URL,
                                        cancel_url=Settings.STRIPE_CANCEL_URL,
                                        customer_phone=from_phone,
                                        description=f"{company.name} - {service_name} ({day_found} {chosen_time})",
                                        metadata=metadata
                                    )
                                    pay_url = checkout["url"] if isinstance(checkout, dict) else checkout
                                    reply = (
                                        f"Perfeito! Para confirmar {service_name} ({day_found} {chosen_time}), segue o pagamento seguro:\n{pay_url}\n\n"
                                        "Assim que o pagamento for confirmado, recebes um email com os dados da aula e a marcação fica concluída. 🙏"
                                        if lang.startswith("pt") else
                                        f"Great! To confirm {service_name} ({day_found} {chosen_time}), here is your secure payment link:\n{pay_url}\n\n"
                                        "Once paid, you'll receive an email with your class details and the booking will be finalized. 🙏"
                                    )
                                    # Guarda contexto para o webhook do Stripe usar (opcional)
                                    ctx["slot_weekday"] = day_found
                                    ctx["slot_time"] = chosen_time
                                    conv.context = ctx
                                    # estado de espera de pagamento
                                    conv.state = "PAY_WAIT"
                                    db.commit()
                                except Exception as e_stripe:
                                    print("STRIPE error:", repr(e_stripe), flush=True)
                                    reply = (
                                        "Não consegui gerar o pagamento agora. Podes tentar novamente ou falar com um atendente."
                                        if lang.startswith("pt") else
                                        "I couldn't create the payment link now. Please try again or talk to a human agent."
                                    )

                        elif conv.state == "ASK_DATETIME":
                            # caminho alternativo quando não há agenda por modalidade → pedir data/hora direta
                            reply = (
                                "Recebido! Para finalizar, preciso do pagamento. Qualquer preferência de modalidade/horário, diz-me."
                                if lang.startswith("pt") else
                                "Got it! To finalize I’ll need payment. If you have a preference for style/time, tell me."
                            )

                    elif intent == "PAYMENT":
                        reply = "Diz qual serviço/modalidade e eu envio um link de pagamento seguro." if lang.startswith("pt") else \
                                "Tell me the service/style and I’ll send a secure payment link."

                    else:
                        # Saudação apenas se conversa acabou de iniciar
                        has_assistant_msg = db.query(Message).filter_by(conversation_id=conv.id, role='assistant').first() is not None
                        if not has_assistant_msg or conv.state == 'IDLE':
                            reply = (
                                f"Vamos agendar! Diz qual modalidade/serviço preferes.\nOpções: Hatha Yoga, Vinyasa Yoga, Yoga Dinâmico"
                                if "marcar" in lower or "agendar" in lower else
                                f"Olá! Sou o assistente da {company.name}. Posso ajudar com informações, marcações e pagamentos."
                            )
                            conv.state = 'ACTIVE'; db.commit()
                        else:
                            reply = None

                    if not reply:
                        continue

                    db.add(Message(conversation_id=conv.id, role='assistant', text=reply, payload={'nlu': nlu}))
                    db.commit()

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
        return {"ok": False}, 200
