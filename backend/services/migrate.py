"""Tiny forward-only schema upgrade: adds columns and indexes that exist in the models but not yet in the database.

db.create_all() creates missing tables but never alters existing ones. This fills that gap for additive changes
(new nullable columns and their indexes) on MySQL and SQLite. Use the files in backend/migrations for controlled
production upgrades; set C2H_AUTO_MIGRATE=0 to switch this off.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateIndex

from extensions import db


def ensure_columns():
    insp = inspect(db.engine)
    q = db.engine.dialect.identifier_preparer.quote
    added = []
    for table in db.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl_type = col.type.compile(dialect=db.engine.dialect)
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {q(table.name)} ADD COLUMN {q(col.name)} {ddl_type} NULL"))
            added.append(f"{table.name}.{col.name}")
        have_ix = {i["name"] for i in insp.get_indexes(table.name)}
        for ix in table.indexes:
            if ix.name not in have_ix:
                with db.engine.begin() as conn:
                    conn.execute(CreateIndex(ix))
                added.append(f"index {ix.name}")
    if added:
        logging.info("Schema upgraded: %s", ", ".join(added))
    return added
