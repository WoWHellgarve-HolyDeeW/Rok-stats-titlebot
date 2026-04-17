from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from pathlib import Path

# Resolve DB path: use DATABASE_URL env var, or default to rokstats.db at the project root
raw_db_url = os.getenv("DATABASE_URL", "").strip()
if not raw_db_url:
    # Default: project root (one level above backend/)
    _project_root = Path(__file__).resolve().parent.parent.parent
    _db_path = _project_root / "rokstats.db"
    DATABASE_URL = f"sqlite:///{_db_path}"
else:
    DATABASE_URL = raw_db_url

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
