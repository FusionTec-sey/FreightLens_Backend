from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.ManagerCase import (
    ManagerCase, ManagerCaseDecision, ManagerCaseUse, IMMUTABLE, REVIEW_CHECK, REVIEW_TRIGGER, USE_CHECK, USE_TRIGGER, immutable_trigger,
)


def ensure_manager_cases_schema():
    with engine.begin() as conn:
        for model in (ManagerCase, ManagerCaseDecision, ManagerCaseUse):
            model.__table__.create(conn, checkfirst=True)
        conn.execute(text(IMMUTABLE)); conn.execute(text(REVIEW_CHECK))
        conn.execute(text(USE_CHECK))
        triggers = [(model.__tablename__, "manager_case_immutable", immutable_trigger(model.__tablename__))
                    for model in (ManagerCase, ManagerCaseDecision, ManagerCaseUse)]
        triggers.append((ManagerCaseDecision.__tablename__, "manager_case_review_guard", REVIEW_TRIGGER))
        triggers.append((ManagerCaseUse.__tablename__, "manager_case_use_guard", USE_TRIGGER))
        for table, name, sql in triggers:
            if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(:table)
                AND tgname=:name AND NOT tgisinternal"""), {"table": "containermgmt." + table, "name": name}).scalar():
                conn.execute(text(sql))
