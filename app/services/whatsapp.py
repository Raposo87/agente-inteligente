from twilio.rest import Client
from ..config import Settings

client = Client(Settings.TWILIO_ACCOUNT_SID, Settings.TWILIO_AUTH_TOKEN)

def send_msg(to_whatsapp: str, body: str):
    return client.messages.create(
        from_=Settings.TWILIO_WHATSAPP_FROM,
        to=to_whatsapp,
        body=body
    )