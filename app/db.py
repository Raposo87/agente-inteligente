from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .config import Settings

engine = create_engine(Settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)