"""Add empty draft revisions; never infer or activate existing product tracking."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft, FUNCTION, TRIGGER


def ensure_inventory_policy_drafts_schema():
    with engine.begin() as conn:
        ProductPolicyDraft.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger
            WHERE tgrelid = 'containermgmt.inventory_product_policy_drafts'::regclass
            AND tgname = 'policy_draft_immutable' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
