from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.CostAllocation import CostAllocationProposal, FUNCTION, TRIGGER


def ensure_cost_allocation_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        CostAllocationProposal.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
            tgrelid = 'containermgmt.inventory_cost_allocation_proposals'::regclass
            AND tgname = 'cost_proposal_immutable' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
