import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations")


def ensure_supplier_scope_schema():
    """Classify every supplier as shared or owned by exactly one organisation."""
    if engine.dialect.name != "postgresql":
        logger.info("Skipping supplier scope migration on %s", engine.dialect.name)
        return

    with engine.begin() as conn:
        table_exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'containermgmt' AND table_name = 'supplier'
        """)).scalar()
        if not table_exists:
            return

        conn.execute(text("""
            ALTER TABLE containermgmt.supplier
            ADD COLUMN IF NOT EXISTS org_id INTEGER
                REFERENCES usercredentials.organisations(id)
        """))
        conn.execute(text("""
            ALTER TABLE containermgmt.supplier
            ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE
        """))

        # Preserve the previously global visibility of legacy rows explicitly.
        conn.execute(text("""
            UPDATE containermgmt.supplier
            SET is_shared = TRUE
            WHERE org_id IS NULL AND is_shared = FALSE
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_supplier_org_id
            ON containermgmt.supplier(org_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_supplier_is_shared
            ON containermgmt.supplier(is_shared)
        """))

        constraint_exists = conn.execute(text("""
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_supplier_scope'
              AND conrelid = 'containermgmt.supplier'::regclass
        """)).scalar()
        if not constraint_exists:
            conn.execute(text("""
                ALTER TABLE containermgmt.supplier
                ADD CONSTRAINT ck_supplier_scope CHECK (
                    (is_shared = TRUE AND org_id IS NULL)
                    OR (is_shared = FALSE AND org_id IS NOT NULL)
                )
            """))

    logger.info("Supplier shared/tenant scope schema is ready")
