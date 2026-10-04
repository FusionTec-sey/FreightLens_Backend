"""Empty immutable proposal store; no stock backfill or activation."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.ReceiptManifest import (InventoryReceiptManifestRecord,
    IMMUTABLE_FUNCTION, IMMUTABLE_TRIGGER, SOURCE_FUNCTION, SOURCE_TRIGGER)


def ensure_receipt_manifest_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        InventoryReceiptManifestRecord.__table__.create(conn, checkfirst=True)
        for function, trigger, name in ((IMMUTABLE_FUNCTION, IMMUTABLE_TRIGGER, 'receipt_manifest_immutable'),
                                       (SOURCE_FUNCTION, SOURCE_TRIGGER, 'receipt_manifest_source')):
            conn.execute(text(function))
            if not conn.execute(text("""SELECT 1 FROM pg_trigger
                WHERE tgrelid='containermgmt.inventory_receipt_manifests'::regclass
                AND tgname=:name AND NOT tgisinternal"""), {'name': name}).scalar():
                conn.execute(text(trigger))
