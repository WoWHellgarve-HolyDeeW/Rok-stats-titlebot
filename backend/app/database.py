from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

raw_db_url = os.getenv("DATABASE_URL", "").strip()
DATABASE_URL = raw_db_url or "sqlite:///./rokstats.db"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
