from flask import Blueprint, request, abort
import stripe
from ..config import Settings
from ..db import SessionLocal
from ..models import Payment

bp = Blueprint('stripe', __name__)

@bp.route('/webhooks/stripe', methods=['POST'])
def handle():
    payload = request.data
    sig = request.headers.get('Stripe-Signature')
    try:
        event = stripe.Webhook.construct_event(payload, sig, Settings.STRIPE_WEBHOOK_SECRET)
    except Exception:
        abort(400)

    db = SessionLocal()
    if event['type'] == 'checkout.session.completed':
        sess = event['data']['object']
        pay = db.query(Payment).filter_by(stripe_session_id=sess['id']).first()
        if pay:
            pay.status = 'paid'
            db.commit()
    return {"ok": True}