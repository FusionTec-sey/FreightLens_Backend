"""Add empty master tables without guessing branch ownership of existing stock."""
from Model.db import engine
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation


def ensure_inventory_locations_schema():
    with engine.begin() as conn:
        InventoryBranch.__table__.create(conn, checkfirst=True)
        StockLocation.__table__.create(conn, checkfirst=True)
