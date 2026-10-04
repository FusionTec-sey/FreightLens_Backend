from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.StaffStoreAssignment import StaffStoreAssignment, FUNCTION, TRIGGER


def ensure_staff_store_assignments_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        StaffStoreAssignment.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger
            WHERE tgrelid=to_regclass('containermgmt.inventory_staff_store_assignments')
            AND tgname='staff_store_assignment_guard' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
