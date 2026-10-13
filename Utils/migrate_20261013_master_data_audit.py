"""Create the trail for edits to shared master records.

Shared vendors and categories may be edited by any user with the right
permission, from any company, and one edit is seen by everyone at once. That is
only acceptable if the change is attributable, so every field change is recorded
here.

Created directly rather than left to create_all, so the table exists before the
first edit rather than after the first restart that happens to notice.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_master_data_audit")


def ensure_master_data_audit_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS containermgmt.master_data_audit (
                id SERIAL PRIMARY KEY,
                entity_type VARCHAR(40) NOT NULL,
                entity_id INTEGER NOT NULL,
                org_id INTEGER,
                action VARCHAR(20) NOT NULL,
                field_name VARCHAR(60),
                old_value TEXT,
                new_value TEXT,
                changed_by INTEGER REFERENCES usercredentials.users(id),
                changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_master_data_audit_entity
            ON containermgmt.master_data_audit (entity_type, entity_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_master_data_audit_entity_type
            ON containermgmt.master_data_audit (entity_type)
        """))
        logger.info("master_data_audit is ready.")
