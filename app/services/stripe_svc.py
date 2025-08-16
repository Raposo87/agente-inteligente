# app/services/stripe_svc.py
import stripe
from ..config import Settings

stripe.api_key = Settings.STRIPE_SECRET_KEY   # <- antes era STRIPE_API_KEY

def create_checkout_session(amount_cents: int, currency: str, name: str, metadata: dict=None):
    metadata = metadata or {}
    session = stripe.checkout.Session.create(
        mode='payment',
        line_items=[{
            'price_data': {
                'currency': currency,
                'product_data': {'name': name},
                'unit_amount': amount_cents,
            },
            'quantity': 1,
        }],
        success_url=Settings.STRIPE_SUCCESS_URL + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=Settings.STRIPE_CANCEL_URL,
        metadata=metadata
    )
    return session.id, session.url
