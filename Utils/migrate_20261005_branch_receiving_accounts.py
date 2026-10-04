"""Create empty exact branch/method receiving-account mapping history."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Orders.PaymentConfiguration import (
    BranchReceivingAccount, BranchReceivingAccountRevision)
from Utils.migrate_20261005_payment_methods import (
    IMMUTABLE, CONSECUTIVE, _trigger_exists)


def ensure_branch_receiving_accounts_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for model in (BranchReceivingAccount, BranchReceivingAccountRevision):
            model.__table__.create(conn, checkfirst=True)
        # Early isolated development used a SYNTH_-only constraint. Retain
        # synthetic fixtures but allow any bounded opaque accounting identifier.
        conn.execute(text("""ALTER TABLE containermgmt.branch_receiving_account_revisions
            DROP CONSTRAINT IF EXISTS ck_receiving_account_ref_synthetic"""))
        if not conn.execute(text("""SELECT 1 FROM pg_constraint
            WHERE conrelid='containermgmt.branch_receiving_account_revisions'::regclass
            AND conname='ck_receiving_account_ref'""")).scalar():
            conn.execute(text("""ALTER TABLE containermgmt.branch_receiving_account_revisions
                ADD CONSTRAINT ck_receiving_account_ref CHECK
                (account_ref ~ '^[A-Z0-9][A-Z0-9_.:-]{0,63}$')"""))
        conn.execute(text(IMMUTABLE))
        conn.execute(text(CONSECUTIVE))
        for model in (BranchReceivingAccount, BranchReceivingAccountRevision):
            table = model.__tablename__
            if not _trigger_exists(conn, table, "immutable"):
                conn.execute(text(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
                    ON containermgmt.{table} FOR EACH ROW
                    EXECUTE FUNCTION containermgmt.payment_config_immutable()"""))
        table = BranchReceivingAccountRevision.__tablename__
        if not _trigger_exists(conn, table, "consecutive"):
            conn.execute(text(f"""CREATE TRIGGER {table}_consecutive BEFORE INSERT
                ON containermgmt.{table} FOR EACH ROW
                EXECUTE FUNCTION containermgmt.payment_config_consecutive()"""))
