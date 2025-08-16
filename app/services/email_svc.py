# app/services/email_svc.py
import smtplib, ssl
from email.message import EmailMessage
from ..config import Settings

def send_email(to_addr: str, subject: str, body: str):
    if not all([Settings.EMAIL_SMTP_HOST, Settings.EMAIL_USER, Settings.EMAIL_PASSWORD, Settings.EMAIL_SENDER]):
        raise RuntimeError("Email SMTP envs em falta.")
    msg = EmailMessage()
    msg['From'] = Settings.EMAIL_SENDER
    msg['To'] = to_addr
    msg['Subject'] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(Settings.EMAIL_SMTP_HOST, Settings.EMAIL_SMTP_PORT or 587) as server:
        server.starttls(context=context)
        server.login(Settings.EMAIL_USER, Settings.EMAIL_PASSWORD)
        server.send_message(msg)
