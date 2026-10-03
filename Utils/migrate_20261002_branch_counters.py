from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision, FUNCTION, trigger


def ensure_branch_counters_schema():
    with engine.begin() as conn:
        for model in (BranchCounter, CounterSettingsRevision):
            model.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        for model in (BranchCounter, CounterSettingsRevision):
            if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(:table)
                AND tgname='counter_immutable' AND NOT tgisinternal"""),
                {"table": "containermgmt." + model.__tablename__}).scalar():
                conn.execute(text(trigger(model.__tablename__)))
