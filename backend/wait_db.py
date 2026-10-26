"""Waits for MySQL to accept connections (used by docker compose)."""
import os
import time

from sqlalchemy import create_engine, text

url = os.getenv("DATABASE_URL")
for i in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("SELECT 1"))
        print("Database is ready.")
        break
    except Exception as e:
        print("Waiting for database…", e.__class__.__name__)
        time.sleep(2)
