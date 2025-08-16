# app/services/gcal.py
from google.oauth2 import service_account
from googleapiclient.discovery import build
from ..config import Settings

SCOPES = ['https://www.googleapis.com/auth/calendar']

_service = None

def svc():
    global _service
    if _service:
        return _service
    if not Settings.GOOGLE_CREDENTIALS:
        raise RuntimeError("Credenciais Google não carregadas. Verifica GOOGLE_SERVICE_ACCOUNT_FILE / SERVICE_ACCOUNT_PATH / GOOGLE_CREDENTIALS_FILE.")
    creds = service_account.Credentials.from_service_account_info(
        Settings.GOOGLE_CREDENTIALS, scopes=SCOPES
    )
    _service = build('calendar', 'v3', credentials=creds)
    return _service

def is_free(start_iso: str, end_iso: str, calendar_id: str=None) -> bool:
    calendar_id = calendar_id or Settings.GOOGLE_CALENDAR_ID
    fb = svc().freebusy().query(body={
        "timeMin": start_iso,
        "timeMax": end_iso,
        "items": [{"id": calendar_id}],
    }).execute()
    busy = fb['calendars'][calendar_id].get('busy', [])
    return len(busy) == 0

def create_event(summary: str, description: str, start_iso: str, end_iso: str, calendar_id: str=None, attendee_email: str=None):
    calendar_id = calendar_id or Settings.GOOGLE_CALENDAR_ID
    event = {
        'summary': summary,
        'description': description,
        'start': {'dateTime': start_iso},
        'end': {'dateTime': end_iso},
    }
    if attendee_email:
        event['attendees'] = [{'email': attendee_email}]
    created = svc().events().insert(calendarId=calendar_id, body=event).execute()
    return created['id']
