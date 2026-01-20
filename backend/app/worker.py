import os
import sys
from rq import Worker, Queue, Connection
from redis import Redis
from redis.exceptions import ConnectionError
from .database import SessionLocal
from .schemas import RokTrackerPayload
from .main import process_ingest, compute_ingest_hash

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
listen = ["ingest"]


def process_ingest_job(payload_dict: dict, ingest_hash: str):
    payload = RokTrackerPayload(**payload_dict)
    db = SessionLocal()
    try:
        return process_ingest(db, payload, ingest_hash)
    finally:
        db.close()


def run_worker():
    try:
        redis_conn = Redis.from_url(redis_url)
        # Test connection
        redis_conn.ping()
        print("✅ Connected to Redis")
    except ConnectionError as e:
        print(f"❌ Redis unavailable: {e}")
        print("ℹ️  The worker requires Redis to process background jobs.")
        print("   Start Redis or use synchronous mode (the API will handle ingest directly).")
        sys.exit(1)
    
    with Connection(redis_conn):
        worker = Worker(map(Queue, listen))
        worker.work()


if __name__ == "__main__":
    run_worker()
