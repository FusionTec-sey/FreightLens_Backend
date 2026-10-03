from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.ReservationDeadline import ReservationDeadline, FUNCTION, TRIGGER


def ensure_reservation_deadlines_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        ReservationDeadline.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid = 'containermgmt.reservation_deadline_revisions'::regclass "
            "AND tgname = 'reservation_deadline_guard' AND NOT tgisinternal")).scalar():
            conn.execute(text(TRIGGER))
