"""Add empty configuration tables; never infer or backfill valuation ownership."""
from Model.db import engine
from Model.containermgmt.Inventory.CostPool import InventoryCostPool, BranchCostPool


def ensure_inventory_cost_pools_schema():
    with engine.begin() as conn:
        InventoryCostPool.__table__.create(conn, checkfirst=True)
        BranchCostPool.__table__.create(conn, checkfirst=True)
