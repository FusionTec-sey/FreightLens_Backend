"""Empty customer identity foundation; never import or infer actual customers."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer, FUNCTION, TRIGGER


def ensure_retail_customers_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        RetailCustomer.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid = "
            "'containermgmt.retail_customers'::regclass AND tgname = 'customer_identity_immutable' "
            "AND NOT tgisinternal")).scalar():
            conn.execute(text(TRIGGER))
