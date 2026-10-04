"""Add profile history without rewriting original customers or sales references."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.MasterData.CustomerProfileRevision import CustomerProfileRevision, FUNCTION, TRIGGER
from Model.containermgmt.Orders.SalesIntent import PROFILE_FUNCTION, PROFILE_TRIGGER


def ensure_customer_profiles_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        CustomerProfileRevision.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid = 'containermgmt.customer_profile_revisions'::regclass "
            "AND tgname = 'customer_profile_history_guard' AND NOT tgisinternal")).scalar():
            conn.execute(text(TRIGGER))
        # Original version-one rows remain valid. New references may pin later history.
        definition = conn.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'containermgmt.sales_intent_revisions'::regclass "
            "AND conname = 'ck_sales_revision_state'")).scalar()
        if definition is None or 'customer_version = 1' in definition:
            conn.execute(text("ALTER TABLE containermgmt.sales_intent_revisions DROP CONSTRAINT IF EXISTS ck_sales_revision_state"))
            conn.execute(text("ALTER TABLE containermgmt.sales_intent_revisions ADD CONSTRAINT ck_sales_revision_state "
                "CHECK (version > 0 AND customer_version > 0 AND status = 'DRAFT')"))
        conn.execute(text(PROFILE_FUNCTION))
        if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid = 'containermgmt.sales_intent_revisions'::regclass "
            "AND tgname = 'sales_customer_profile_guard' AND NOT tgisinternal")).scalar():
            conn.execute(text(PROFILE_TRIGGER))
