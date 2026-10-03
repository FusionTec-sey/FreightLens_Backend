"""Preserve legacy receipt quantities; never guess or reverse historical postings."""
from sqlalchemy import text
from Model.db import engine


def ensure_receipt_posting_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE containermgmt.goods_receipts
            ADD COLUMN IF NOT EXISTS posting_version INTEGER NOT NULL DEFAULT 0
        """))
