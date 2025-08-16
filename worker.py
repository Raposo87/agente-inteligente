import time
from datetime import datetime
import pytz
from app.db import SessionLocal
from app.models import Reminder, Appointment, Customer, Company
from app.services import whatsapp
from app.config import Settings

INTERVAL_SEC = 30

def loop():
    tz = pytz.timezone(Settings.TIMEZONE)
    while True:
        now = datetime.now(tz)
        db = SessionLocal()
        due = db.query(Reminder).filter(Reminder.sent == False, Reminder.due_at <= now).all()
        for r in due:
            appt = db.query(Appointment).get(r.appointment_id)
            cust = db.query(Customer).get(appt.customer_id)
            comp = db.query(Company).get(appt.company_id)
            msg = f"Lembrete: tem {appt.service_code} em {appt.start_at.strftime('%d/%m %H:%M')} em {comp.name}."
            whatsapp.send_msg(cust.phone, msg)
            r.sent = True
            db.commit()
        time.sleep(INTERVAL_SEC)

if __name__ == '__main__':
    loop()