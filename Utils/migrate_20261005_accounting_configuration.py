"""Create empty immutable per-branch logical account-role configuration."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Accounting.AccountingConfiguration import (
    BranchAccountMapping,
    BranchAccountMappingRevision,
)


IMMUTABLE = """
CREATE OR REPLACE FUNCTION containermgmt.accounting_config_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Accounting configuration history is immutable';
END $$
"""


CONSECUTIVE = """
CREATE OR REPLACE FUNCTION containermgmt.accounting_config_consecutive()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior integer;
BEGIN
  PERFORM 1 FROM containermgmt.branch_account_mappings
    WHERE mapping_key = NEW.mapping_key AND org_id = NEW.org_id FOR UPDATE;
  SELECT COALESCE(MAX(version), 0) INTO prior
    FROM containermgmt.branch_account_mapping_revisions
    WHERE mapping_key = NEW.mapping_key AND org_id = NEW.org_id;
  IF NEW.version <> prior + 1 THEN
    RAISE EXCEPTION 'Accounting configuration revision must be consecutive';
  END IF;
  RETURN NEW;
END $$
"""


def _trigger_exists(conn, table: str, suffix: str):
    return conn.execute(
        text(
            """SELECT 1 FROM pg_trigger WHERE tgrelid =
            CAST(:name AS regclass) AND tgname = :trigger AND NOT tgisinternal"""
        ),
        {
            "name": f"containermgmt.{table}",
            "trigger": f"{table}_{suffix}",
        },
    ).scalar()


def ensure_accounting_configuration_schema() -> None:
    """Replay-safe DDL only; deliberately inserts no account mapping rows."""
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for model in (BranchAccountMapping, BranchAccountMappingRevision):
            model.__table__.create(conn, checkfirst=True)
        conn.execute(text(IMMUTABLE))
        conn.execute(text(CONSECUTIVE))
        for model in (BranchAccountMapping, BranchAccountMappingRevision):
            table = model.__tablename__
            if not _trigger_exists(conn, table, "immutable"):
                conn.execute(
                    text(
                        f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
                        ON containermgmt.{table} FOR EACH ROW
                        EXECUTE FUNCTION containermgmt.accounting_config_immutable()"""
                    )
                )
        table = BranchAccountMappingRevision.__tablename__
        if not _trigger_exists(conn, table, "consecutive"):
            conn.execute(
                text(
                    f"""CREATE TRIGGER {table}_consecutive BEFORE INSERT
                    ON containermgmt.{table} FOR EACH ROW
                    EXECUTE FUNCTION containermgmt.accounting_config_consecutive()"""
                )
            )
