from flask import Flask
from .config import Settings
from .db import engine
from .models import Base
from .routers.webhook_whatsapp import bp as wa_bp
from .routers.webhook_stripe import bp as stripe_bp
from .routers.health import bp as health_bp


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = Settings.SECRET_KEY
    # Criar tabelas (ou usar Alembic para migrações reais)
    Base.metadata.create_all(bind=engine)

    app.register_blueprint(wa_bp)
    app.register_blueprint(stripe_bp)
    app.register_blueprint(health_bp)
    return app