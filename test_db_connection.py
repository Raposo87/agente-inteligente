import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv; load_dotenv()

db_url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL", "")
print("DATABASE_URL:", db_url)

engine = create_engine(db_url)
with engine.connect() as conn:
    print("OK:", conn.execute(text("select now()")).scalar())
