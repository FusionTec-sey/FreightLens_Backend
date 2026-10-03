"""Empty versioned retail demand tables, without stock or financial effects."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Orders.SalesIntent import TABLES, FUNCTION, trigger


def ensure_sales_intents_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for table in TABLES:
            table.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        for table in TABLES:
            if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid = CAST(:name AS regclass) "
                "AND tgname = 'sales_intent_immutable' AND NOT tgisinternal"),
                {'name': f'containermgmt.{table.name}'}).scalar():
                conn.execute(text(trigger(table)))
