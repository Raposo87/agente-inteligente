from dotenv import load_dotenv
load_dotenv()
import os, json
from base64 import b64decode

class Settings:
    # App
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-me')
    TIMEZONE = os.getenv('TIMEZONE', 'Europe/Lisbon')

    # Postgres (Railway dá DATABASE_URL)
    DATABASE_URL = os.getenv("DATABASE_PUBLIC_URL") or os.getenv("DATABASE_URL")

    # OpenAI
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o')

    # Stripe (nomes iguais aos teus)
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')            # <- antes era STRIPE_API_KEY
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
    STRIPE_SUCCESS_URL = os.getenv('STRIPE_SUCCESS_URL')
    STRIPE_CANCEL_URL = os.getenv('STRIPE_CANCEL_URL')

    # WhatsApp Business Cloud API (nomes iguais aos teus)
    WHATSAPP_CLOUD_API_TOKEN = os.getenv('WHATSAPP_CLOUD_API_TOKEN')
    WHATSAPP_PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
    WHATSAPP_BUSINESS_ACCOUNT_ID = os.getenv('WHATSAPP_BUSINESS_ACCOUNT_ID')
    WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.getenv('WHATSAPP_WEBHOOK_VERIFY_TOKEN')

    # Google Calendar
    # Preferência: ficheiro de service account. Suportes: GOOGLE_SERVICE_ACCOUNT_FILE, SERVICE_ACCOUNT_PATH, GOOGLE_CREDENTIALS_FILE
    GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID')

    GOOGLE_CREDENTIALS = None
    # 1) Service account por ficheiro (recomendado)
    sa_path = (
        os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
        or os.getenv('SERVICE_ACCOUNT_PATH')
        or os.getenv('GOOGLE_CREDENTIALS_FILE')
    )
    if sa_path and os.path.exists(sa_path):
        with open(sa_path, 'r', encoding='utf-8') as f:
            GOOGLE_CREDENTIALS = json.load(f)
    else:
        # 2) Opcional: se usares um JSON em base64 noutro ambiente
        raw_b64 = os.getenv('GOOGLE_CREDENTIALS_JSON_BASE64')
        if raw_b64:
            GOOGLE_CREDENTIALS = json.loads(b64decode(raw_b64).decode('utf-8'))

    # NOTA: GOOGLE_TOKEN_FILE é típico de OAuth user-flow; aqui usamos service account, por isso não é necessário.

    # Email (opcional — só se quiseres enviar confirmações por e-mail)
    EMAIL_SMTP_HOST = os.getenv('EMAIL_SMTP_HOST')
    EMAIL_SMTP_PORT = int(os.getenv('EMAIL_SMTP_PORT', '587')) if os.getenv('EMAIL_SMTP_PORT') else None
    EMAIL_USER = os.getenv('EMAIL_USER')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
    EMAIL_SENDER = os.getenv('EMAIL_SENDER')

    # Multi-empresa
    EMPRESA_ID = os.getenv('EMPRESA_ID')
