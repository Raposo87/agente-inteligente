# app/services/whatsapp_meta.py
import requests
from ..config import Settings

def _endpoint():
    # v19.0 ou superior se quiseres — mantém consistente com a tua app
    return f"https://graph.facebook.com/v23.0/{Settings.WHATSAPP_PHONE_NUMBER_ID}/messages"

def send_msg(to_phone: str, body: str):
    headers = {
        "Authorization": f"Bearer {Settings.WHATSAPP_CLOUD_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone.replace("whatsapp:", ""),  # garantimos formato correto
        "type": "text",
        "text": {"body": body},
    }
    r = requests.post(_endpoint(), headers=headers, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()
