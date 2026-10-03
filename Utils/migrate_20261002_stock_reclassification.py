"""Empty append-only proposal store; no stock backfill or activation."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.StockReclassification import StockReclassificationProposal, FUNCTION, TRIGGER


def ensure_stock_reclassification_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        StockReclassificationProposal.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger
            WHERE tgrelid = 'containermgmt.inventory_stock_reclassification_proposals'::regclass
            AND tgname = 'reclassification_proposal_immutable' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
