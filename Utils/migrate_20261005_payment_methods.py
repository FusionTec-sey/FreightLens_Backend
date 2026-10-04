"""Create empty payment method identities and immutable consecutive history."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Orders.PaymentConfiguration import PaymentMethod, PaymentMethodRevision


IMMUTABLE = """
CREATE OR REPLACE FUNCTION containermgmt.payment_config_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'Payment configuration history is immutable';
END $$
"""

CONSECUTIVE = """
CREATE OR REPLACE FUNCTION containermgmt.payment_config_consecutive() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE prior integer; first_kind text;
BEGIN
  IF TG_TABLE_NAME = 'payment_method_revisions' THEN
    PERFORM 1 FROM containermgmt.payment_methods
      WHERE method_key = NEW.method_key AND org_id = NEW.org_id FOR UPDATE;
    SELECT COALESCE(MAX(version), 0) INTO prior
      FROM containermgmt.payment_method_revisions
      WHERE method_key = NEW.method_key AND org_id = NEW.org_id;
    SELECT kind INTO first_kind FROM containermgmt.payment_method_revisions
      WHERE method_key = NEW.method_key AND org_id = NEW.org_id AND version = 1;
    IF first_kind IS NOT NULL AND NEW.kind <> first_kind THEN
      RAISE EXCEPTION 'Payment method type is immutable';
    END IF;
  ELSE
    PERFORM 1 FROM containermgmt.branch_receiving_accounts
      WHERE mapping_key = NEW.mapping_key AND org_id = NEW.org_id FOR UPDATE;
    SELECT COALESCE(MAX(version), 0) INTO prior
      FROM containermgmt.branch_receiving_account_revisions
      WHERE mapping_key = NEW.mapping_key AND org_id = NEW.org_id;
  END IF;
  IF NEW.version <> prior + 1 THEN
    RAISE EXCEPTION 'Payment configuration revision must be consecutive';
  END IF;
  RETURN NEW;
END $$
"""


def _trigger_exists(conn, table, suffix):
    return conn.execute(text("""SELECT 1 FROM pg_trigger WHERE tgrelid =
        CAST(:name AS regclass) AND tgname = :trigger AND NOT tgisinternal"""),
        {"name": f"containermgmt.{table}", "trigger": f"{table}_{suffix}"}).scalar()


def ensure_payment_methods_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for model in (PaymentMethod, PaymentMethodRevision):
            model.__table__.create(conn, checkfirst=True)
        conn.execute(text(IMMUTABLE))
        conn.execute(text(CONSECUTIVE))
        for model in (PaymentMethod, PaymentMethodRevision):
            table = model.__tablename__
            if not _trigger_exists(conn, table, "immutable"):
                conn.execute(text(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
                    ON containermgmt.{table} FOR EACH ROW
                    EXECUTE FUNCTION containermgmt.payment_config_immutable()"""))
        table = PaymentMethodRevision.__tablename__
        if not _trigger_exists(conn, table, "consecutive"):
            conn.execute(text(f"""CREATE TRIGGER {table}_consecutive BEFORE INSERT
                ON containermgmt.{table} FOR EACH ROW
                EXECUTE FUNCTION containermgmt.payment_config_consecutive()"""))
