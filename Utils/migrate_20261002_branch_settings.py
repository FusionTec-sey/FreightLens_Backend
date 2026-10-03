"""Empty immutable branch configuration history; no hours or calendars seeded."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.BranchSettings import BranchSettingsRevision, FUNCTION, TRIGGER


def ensure_branch_settings_schema():
    with engine.begin() as conn:
        BranchSettingsRevision.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger
            WHERE tgrelid = 'containermgmt.inventory_branch_settings_revisions'::regclass
            AND tgname = 'branch_settings_immutable' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
