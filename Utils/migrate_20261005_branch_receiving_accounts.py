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
