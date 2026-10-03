from sqlalchemy import text
from sqlalchemy.schema import AddConstraint
from Model.db import engine
from Model.containermgmt.Inventory.CostChargeUse import CostChargeUse, FUNCTION, TRIGGER


def ensure_cost_charge_uses_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        CostChargeUse.__table__.create(conn, checkfirst=True)
        # Also replay safely over an earlier local development creation.
        for name in ('uq_cost_charge_document', 'ck_cost_charge_snapshot', 'ck_cost_charge_required'):
            if not conn.execute(text("""SELECT 1 FROM pg_constraint WHERE
                conrelid = 'containermgmt.inventory_cost_charge_uses'::regclass AND conname = :name"""), {'name': name}).scalar():
                constraint = next(item for item in CostChargeUse.__table__.constraints if item.name == name)
                conn.execute(AddConstraint(constraint))
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
            tgrelid = 'containermgmt.inventory_cost_charge_uses'::regclass
            AND tgname = 'cost_charge_use_guard' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
