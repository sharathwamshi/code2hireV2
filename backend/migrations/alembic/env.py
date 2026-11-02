"""Alembic environment: uses the app's DATABASE_URL and model metadata."""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("C2H_NO_AUTOCREATE", "1")
from config import Config  # noqa: E402
import models  # noqa: E402,F401
from extensions import db  # noqa: E402

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = db.metadata
URL = Config.SQLALCHEMY_DATABASE_URI


def run_migrations_offline():
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(URL, pool_pre_ping=True)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
