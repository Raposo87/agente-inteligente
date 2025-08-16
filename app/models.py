from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Enum, Boolean, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class Company(Base):
    __tablename__ = 'companies'
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    locale = Column(String(16), default='pt-PT')
    timezone = Column(String(64), default='Europe/Lisbon')
    brand_voice = Column(JSON, default={})  # {tone:"Profissional...", greetings:"..."}
    business_hours = Column(JSON, default={})
    address = Column(String(255))
    phone_public = Column(String(50))
    email_public = Column(String(120))
    services = Column(JSON, default=[])     # lista de serviços {code, name, price, duration_min}

class ProviderAccount(Base):
    __tablename__ = 'provider_accounts'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    provider = Column(Enum('twilio','google','stripe','openai', name='provider_enum'))
    credentials = Column(JSON, nullable=False)  # tokens/keys (encriptados em repouso)
    meta = Column(JSON, default={})
    company = relationship('Company')

class Customer(Base):
    __tablename__ = 'customers'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    phone = Column(String(64), index=True)
    name = Column(String(120))
    locale = Column(String(16))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('company_id','phone', name='uq_customer_company_phone'),)

class Conversation(Base):
    __tablename__ = 'conversations'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    state = Column(String(48), default='IDLE')  # IDLE, ASK_DATETIME, ASK_SERVICE, AWAIT_PAYMENT, ...
    context = Column(JSON, default={})          # dados temporários (data proposta, serviço, preço)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey('conversations.id'), nullable=False)
    role = Column(Enum('user','assistant','system', name='role_enum'))
    text = Column(Text)
    payload = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)

class Appointment(Base):
    __tablename__ = 'appointments'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    service_code = Column(String(64))
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    gcal_event_id = Column(String(128))
    status = Column(Enum('confirmed','cancelled','pending', name='appt_status_enum'), default='confirmed')

class Payment(Base):
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    appointment_id = Column(Integer, ForeignKey('appointments.id'))
    amount_cents = Column(Integer)
    currency = Column(String(8), default='EUR')
    stripe_session_id = Column(String(128))
    status = Column(Enum('pending','paid','failed','cancelled', name='pay_status_enum'), default='pending')

class Reminder(Base):
    __tablename__ = 'reminders'
    id = Column(Integer, primary_key=True)
    appointment_id = Column(Integer, ForeignKey('appointments.id'), nullable=False)
    due_at = Column(DateTime, index=True)
    sent = Column(Boolean, default=False)