import requests
from ..config import Settings

def send_msg(to_whatsapp: str, body: str):
    url = f"https://graph.facebook.com/v19.0/{Settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {Settings.WHATSAPP_CLOUD_API_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to_whatsapp,
        "type": "text",
        "text": {"body": body}
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()