# app/routers/webhook_whatsapp.py
from flask import Blueprint, request
from ..services import whatsapp_meta as whatsapp
from ..nlp.intent_extractor import extract
from ..db import SessionLocal
from ..models import Company, Customer, Conversation, Message
from ..config import Settings
from ..services import gcal, stripe_svc
from datetime import datetime
import unicodedata, re, traceback

# LLM freeform responder + rate-limit
from ..nlp.responder import generate_freeform_reply
from ..utils.ratelimit import llm_allowed

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
    t = (user_text or "").lower().strip()
    # “ok” não força inglês
    if t in {"ok", "ok.", "okay", "okay."}:
        return False
    en_hits = any(w in t for w in ["book", "schedule", "class", "what", "when", "how", "price", "pay", "payment", "benefit", "hi", "hello"])
    pt_hits = any(w in t for w in ["olá", "ola", "marcar", "agendar", "aula", "preço", "preco", "pagar", "benefício", "beneficio", "horário", "horario"])
    return en_hits and not pt_hits

def _find_service(services, user_text):
    if not services:
        return None
    nt = _norm(user_text)
    # match direto
    for s in services:
        name = s.get("name") or s.get("nome") or ""
        if _norm(name) in nt or nt in _norm(name):
            return s
    # match parcial por tokens
    for s in services:
        name = s.get("name") or s.get("nome") or ""
        if any(tok and tok in _norm(name) for tok in nt.split()):
            return s
    return None

def _service_days_times(service, lang_pt=True):
    """
    Suporta:
      - service['schedule'] ou ['horarios']: dict {dia -> [horas]}
      - service['slots']: [{day:'tuesday','times':['10:00','18:00']}, ...]
    Retorna (dias, mapping) com horas deduplicadas.
    """
    if not service:
        return None, None
    sched = service.get("schedule") or service.get("horarios")
    if isinstance(sched, dict):
        # dedup horas por dia
        mapping = {}
        for k, v in sched.items():
            if isinstance(v, list):
                uniq = sorted(set(v), key=lambda x: x)
                mapping[k] = uniq
            else:
                mapping[k] = v
        return list(mapping.keys()), mapping
    slots = service.get("slots")
    if isinstance(slots, list):
        out = {}
        for it in slots:
            day = (it.get("day") or it.get("dia") or "").lower()
            times = it.get("times") or it.get("horas") or []
            if not day:
                continue
            out.setdefault(day, [])
            out[day].extend(times if isinstance(times, list) else [times])
        # dedup
        for d in list(out.keys()):
            out[d] = sorted(set(out[d]), key=lambda x: x)
        return list(out.keys()), out
    return None, None

def _format_days_times(days, mapping, lang_pt=True):
    if not days or not mapping:
        return ""
    order_pt = ["segunda","terca","terça","quarta","quinta","sexta","sabado","sábado","domingo"]
    order_en = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    order = order_pt if lang_pt else order_en

    def key_norm(k):
        k2 = _norm(k)
        repl = {"terca":"terça", "sabado":"sábado"}
        return repl.get(k2, k2)

    lines = []
    seen = set()
    for d in order:
        found = None
        for k in mapping.keys():
            if key_norm(k) == key_norm(d):
                found = k; break
        if not found:
            continue
        if key_norm(found) in seen:
            continue
        seen.add(key_norm(found))
        times = mapping.get(found) or []
        if isinstance(times, list):
            times_str = ", ".join(times)
        else:
            times_str = str(times)
        if lang_pt:
            day_label = {"segunda":"Seg", "terça":"Ter", "terca":"Ter", "quarta":"Qua", "quinta":"Qui", "sexta":"Sex", "sábado":"Sáb", "sabado":"Sáb", "domingo":"Dom"}.get(key_norm(found), found.title())
        else:
            day_label = found.title()
        if times_str:
            lines.append(f"{day_label}: {times_str}")
    return "\n".join(lines)

def _modalities_overview(services, lang_pt=True):
    """
    Gera um texto breve a explicar cada modalidade.
    Usa campos do JSON se existirem: description/descricao/about/benefits.
    Fallback para descrições padrão.
    """
    if not services:
        return "Temos Hatha (técnica e alinhamento), Vinyasa (fluidez com respiração) e Yoga Dinâmico (maior intensidade)." if lang_pt \
            else "We offer Hatha (technique & alignment), Vinyasa (flow with breath), and Dynamic Yoga (more intensity)."

    def desc_default(name):
        n = _norm(name)
        if "hatha" in n:
            return "Foco em alinhamento, posturas clássicas e base técnica (nível aberto)."
        if "vinyasa" in n:
            return "Sequências fluidas sincronizadas com a respiração; ritmo moderado."
        if "dinam" in n or "dynamic" in n:
            return "Prática mais intensa e energética; reforça força e resistência."
        return "Prática orientada ao bem-estar e consciência corporal."

    lines = []
    for s in services:
        name = s.get("name") or s.get("nome") or "Modalidade"
        d = s.get("description") or s.get("descricao") or s.get("about")
        ben = s.get("benefits") or s.get("beneficios")
        chunk = f"• {name}: {d or desc_default(name)}"
        if isinstance(ben, list) and ben:
            chunk += " | " + ", ".join(ben[:4])
        lines.append(chunk)
    txt = "\n".join(lines)
    if lang_pt:
        return f"Aqui vai um resumo das modalidades:\n{txt}\n\nQual delas preferes experimentar?"
    else:
        return f"Here’s a quick overview:\n{txt}\n\nWhich one would you like to try?"

def _wants_overview(text):
    t = _norm(text)
    triggers = [
        "falar sobre", "explicar", "explica", "entender", "sobre cada", "diferen", "qual a diferença",
        "tell me about", "explain", "differences", "difference", "what are"
    ]
    return any(k in t for k in triggers)

def _mentions_trial(text):
    t = _norm(text)
    return any(k in t for k in ["aula experimental", "aula de experiencia", "aula de experiência", "trial", "first class", "teste"])

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

                    # FINALIZAR CONVERSA
                    if _norm(body) == "finalizar conversa":
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

                    # Upsert cliente e conversa
                    cust = db.query(Customer).filter_by(company_id=company.id, phone=from_phone).first()
                    if not cust:
                        cust = Customer(company_id=company.id, phone=from_phone, locale=company.locale)
                        db.add(cust); db.commit(); db.refresh(cust)

                    conv = db.query(Conversation).filter_by(company_id=company.id, customer_id=cust.id).first()
                    if not conv:
                        conv = Conversation(company_id=company.id, customer_id=cust.id, state='IDLE', context={})
                        db.add(conv); db.commit(); db.refresh(conv)

                    # Dedup por wamid
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

                    # NLU + idioma
                    try:
                        nlu = extract(body) or {}
                    except Exception as nlu_err:
                        print("NLU error:", repr(nlu_err), flush=True)
                        nlu = {}

                    lang = "en" if _detect_english(body) else "pt-PT"
                    intent = (nlu.get('intent') or "SMALL_TALK").upper()

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

                    reply = None
                    lower = _norm(body)

                    # -------- INTENT FAQ_INFO (conceito) --------
                    if intent == "FAQ_INFO":
                        concept_like = any(k in lower for k in [
                            "o que e", "o que faz", "beneficio", "para que serve", "como funciona",
                            "what is", "benefit", "how does it work"
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

                    # -------- FLUXO DE AGENDAMENTO --------
                    elif intent == "SCHEDULE" or conv.state in ["ASK_SERVICE", "ASK_DATETIME", "ASK_SLOT"]:
                        # "Aula experimental" — apresenta opções de teste
                        if _mentions_trial(body):
                            exp = pricing.get("pack_experiencia") or {}
                            aulas = exp.get("aulas")
                            dur = exp.get("duracao_dias")
                            preco = exp.get("preco")
                            trial_txt = []
                            if preco:
                                trial_txt.append(f"Pack experiência: {aulas} aulas / {dur} dias — {preco}€")
                            dropin = pricing.get("avulsa")
                            if dropin:
                                trial_txt.append(f"Aula avulsa: {dropin}€")
                            trial_line = "\n".join(trial_txt) if trial_txt else "Temos opções de aula avulsa e packs de experiência."
                            reply = (f"Perfeito — aula experimental!\n{trial_line}\n\n"
                                     "Qual modalidade queres experimentar? (Hatha, Vinyasa, Dinâmico)")
                            conv.state = "ASK_SERVICE"; db.commit()
                        # iniciar fluxo se necessário
                        elif conv.state not in ["ASK_SERVICE", "ASK_DATETIME", "ASK_SLOT"]:
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
                            # Pedido de EXPLICAÇÃO de modalidades
                            if _wants_overview(body):
                                reply = _modalities_overview(services, lang_pt=lang.startswith("pt"))
                            else:
                                # Aceita escolha e mostra agenda dessa modalidade
                                sel = _find_service(services, body)
                                ctx = conv.context or {}
                                ctx["service_raw"] = body
                                ctx["service_name"] = (sel.get("name") or sel.get("nome")) if sel else body
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
                            # Cliente escolhe dia e hora de entre a lista
                            ctx = conv.context or {}
                            service_name = ctx.get("service_name") or ctx.get("service_raw") or "Aula"
                            txt = body.lower()
                            m_time = re.search(r"(\d{1,2}[:h]\d{2})", txt)
                            chosen_time = m_time.group(1).replace("h", ":") if m_time else None
                            weekdays_pt = ["segunda","terca","terça","quarta","quinta","sexta","sabado","sábado","domingo"]
                            weekdays_en = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
                            day_found = None
                            for d in weekdays_pt + weekdays_en:
                                if d in txt:
                                    day_found = d; break
                            if not (day_found and chosen_time):
                                reply = "Preciso do dia e da hora (ex.: terça às 19:00)." if lang.startswith("pt") else \
                                        "I need the day and time (e.g., Tuesday at 19:00)."
                            else:
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
                                        "Após confirmação, recebes email com os dados da aula e eu aviso aqui que está marcado. 🙏"
                                        if lang.startswith("pt") else
                                        f"Great! To confirm {service_name} ({day_found} {chosen_time}), here is your secure payment link:\n{pay_url}\n\n"
                                        "Once confirmed, you'll get an email with details and I’ll confirm booking here. 🙏"
                                    )
                                    ctx["slot_weekday"] = day_found
                                    ctx["slot_time"] = chosen_time
                                    conv.context = ctx
                                    conv.state = "PAY_WAIT"
                                    db.commit()
                                except Exception as e_stripe:
                                    print("STRIPE error:", repr(e_stripe), flush=True)
                                    reply = "Não consegui gerar o pagamento agora. Tenta de novo ou fala com um atendente." if lang.startswith("pt") else \
                                            "I couldn't create the payment link now. Please try again or talk to a human agent."

                        elif conv.state == "ASK_DATETIME":
                            # Alternativa quando não há agenda pré-definida
                            reply = "Recebido! Para confirmar preciso do pagamento. Preferes aula avulsa ou pack experiência?" if lang.startswith("pt") else \
                                    "Got it! To confirm I need payment. Do you prefer a drop-in or a trial pack?"

                    # -------- INTENT PAYMENT fora do fluxo --------
                    elif intent == "PAYMENT":
                        reply = "Diz qual serviço/modalidade e eu envio um link de pagamento seguro." if lang.startswith("pt") else \
                                "Tell me the service/style and I’ll send a secure payment link."

                    else:
                        has_assistant_msg = db.query(Message).filter_by(conversation_id=conv.id, role='assistant').first() is not None
                        if not has_assistant_msg or conv.state == 'IDLE':
                            reply = (
                                f"Vamos agendar! Diz qual modalidade/serviço preferes.\nOpções: Hatha Yoga, Vinyasa Yoga, Yoga Dinâmico"
                                if ("marcar" in lower or "agendar" in lower or "aula" in lower) else
                                f"Olá! Sou o assistente da {company.name}. Posso ajudar com informações, marcações e pagamentos."
                            )
                            conv.state = 'ACTIVE'; db.commit()
                        else:
                            reply = None

                    # -------------------- BLOCO LLM FREEFORM (pedido) --------------------
                    if not reply:
                        # Se ainda não temos resposta estruturada, tentamos LLM livre.
                        use_llm = (str(getattr(Settings, "USE_LLM_FREEFORM", "false")).lower() in ("true", "1", "yes"))
                        if use_llm and llm_allowed(conv, cooldown_seconds=int(getattr(Settings, "LLM_COOLDOWN_SECONDS", 25))):
                            try:
                                # resumo simples (opcional)
                                summary = ""
                                # idioma por heurística (PT por defeito)
                                locale = "en" if _detect_english(body) else "pt-PT"
                                # dicionário leve da empresa
                                company_dict = {
                                    "name": company.name,
                                    "brand_voice": company.brand_voice or {},
                                    "description": getattr(company, "description", None),
                                    "descricao": getattr(company, "descricao", None),
                                    "site_url": getattr(company, "site_url", None),
                                    "address": getattr(company, "address", None),
                                    "business_hours": getattr(company, "business_hours", None),
                                    "services": getattr(company, "services", None) or (company.brand_voice or {}).get("services", []),
                                }
                                reply = generate_freeform_reply(
                                    company=company_dict,
                                    conversation_summary=summary,
                                    user_text=body,
                                    locale=locale,
                                    temperature=float(getattr(Settings, "OPENAI_TEMPERATURE", 0.4)),
                                    max_tokens=int(getattr(Settings, "OPENAI_MAX_TOKENS", 400)),
                                )
                            except Exception as gen_err:
                                print("LLM freeform error:", repr(gen_err), flush=True)
                                # Fallback curto
                                reply = "Posso ajudar com isso! Queres que confirme essa informação ou preferes seguir com uma marcação/pagamento?"

                    # Se mesmo assim não houver reply, não envia nada
                    if not reply:
                        continue

                    # Guarda resposta + payload NLU
                    db.add(Message(conversation_id=conv.id, role='assistant', text=reply, payload={'nlu': nlu}))
                    db.commit()

                    # Envia WhatsApp
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
