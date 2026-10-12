"""Add the per-company document number series, seeded from existing numbers.

Numbering used to be six literals in Python. This table holds one row per
company per document type so it can be configured instead.

The seed must not invent a starting point. Switching numbering on while real
orders are already in the database is exactly where a naive default of 1 would
issue PO-2026-0001 beside an existing NCE-PO#26156 and fork the sequence, so
each series starts past the highest number already issued, with the prefix
inferred from the text in front of those digits.

Every seeded row is inactive. Nothing changes behaviour until an administrator
switches a series on, so this migration is inert on deploy.
"""
import logging
import re
from collections import Counter

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_document_number_series")

# doc_type -> (table, column, extra WHERE applied to the scan)
SOURCES = {
    "PO": ("purchase_orders", "po_number", "doc_type = 'PO'"),
    "RFQ": ("purchase_orders", "po_number", "doc_type = 'RFQ'"),
    "REQ": ("store_requests", "request_number", None),
    "GRN": ("goods_receipts", "receipt_number", None),
    "PL": ("order_packing_lists", "packing_list_number", None),
    "DEF": ("defect_reports", "defect_number", None),
}

# Only these three were ever counters. The other formats end in a date, a time
# of day or a purchase order id -- GRN-20260920-57 ends in the PO's id, not a
# sequence -- so inferring a prefix from them would bake 20260920 into every
# future receipt. They start from 1 with a plain prefix instead.
COUNTER_BASED = {"PO", "RFQ", "REQ"}

# Trailing digits are the counter; whatever precedes them is the prefix.
TRAILING_DIGITS = re.compile(r"^(.*?)(\d+)$")

DEFAULT_PREFIX = {
    "PO": "PO-", "RFQ": "RFQ-", "REQ": "REQ-",
    "GRN": "GRN-", "PL": "PL-", "DEF": "DEF-",
}


def _create_table(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS containermgmt.document_number_series (
            id SERIAL PRIMARY KEY,
            org_id INTEGER NOT NULL,
            doc_type VARCHAR(30) NOT NULL,
            prefix VARCHAR(30) NOT NULL DEFAULT '',
            suffix VARCHAR(30) NOT NULL DEFAULT '',
            padding INTEGER NOT NULL DEFAULT 4,
            next_number INTEGER NOT NULL DEFAULT 1,
            reset_policy VARCHAR(10) NOT NULL DEFAULT 'never',
            date_token VARCHAR(20),
            last_reset_on DATE,
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            is_shared BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at TIMESTAMPTZ,
            created_by INTEGER REFERENCES usercredentials.users(id),
            updated_by INTEGER REFERENCES usercredentials.users(id),
            deleted_by INTEGER REFERENCES usercredentials.users(id)
        )
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_document_number_series_org_doc
        ON containermgmt.document_number_series (org_id, doc_type)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_document_number_series_doc_type
        ON containermgmt.document_number_series (doc_type)
    """))
    # The table may already exist from SQLAlchemy's create_all, whose DDL has no
    # column defaults, so set them rather than assume this migration built it.
    for column, default in (
        ("prefix", "''"), ("suffix", "''"), ("padding", "4"),
        ("next_number", "1"), ("reset_policy", "'never'"), ("is_active", "FALSE"),
    ):
        conn.execute(text(
            f"ALTER TABLE containermgmt.document_number_series "
            f"ALTER COLUMN {column} SET DEFAULT {default}"
        ))


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute(text("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'containermgmt' AND table_name = :t
    """), {"t": table}).first())


def _seed(conn, doc_type: str, table: str, column: str, extra: str):
    if not _table_exists(conn, table):
        logger.info("Skipping %s seed: containermgmt.%s does not exist.", doc_type, table)
        return

    where = f"{column} IS NOT NULL AND is_deleted = FALSE"
    if extra:
        where += f" AND {extra}"
    rows = conn.execute(text(
        f"SELECT org_id, {column} FROM containermgmt.{table} WHERE {where}"
    )).fetchall()

    # Highest counter seen per company, and the prefix that carried it. The most
    # common prefix wins, so one oddly numbered document cannot set the format.
    highest: dict = {}
    prefixes: dict = {}
    for org_id, value in rows:
        if org_id is None:
            continue
        match = TRAILING_DIGITS.match(str(value).strip())
        if not match:
            continue
        prefix, digits = match.group(1), match.group(2)
        number = int(digits)
        prefixes.setdefault(org_id, Counter())[prefix] += 1
        if number > highest.get(org_id, 0):
            highest[org_id] = number
            # Remember the width of the number actually in use.
            highest[(org_id, "pad")] = len(digits)

    org_ids = [row[0] for row in conn.execute(text(
        "SELECT id FROM usercredentials.organisations"
    )).fetchall()]

    infer = doc_type in COUNTER_BASED
    for org_id in org_ids:
        last = highest.get(org_id, 0) if infer else 0
        prefix_counter = prefixes.get(org_id) if infer else None
        prefix = (prefix_counter.most_common(1)[0][0]
                  if prefix_counter else DEFAULT_PREFIX[doc_type])
        padding = highest.get((org_id, "pad"), 4) if infer else 4
        conn.execute(text("""
            INSERT INTO containermgmt.document_number_series
                (org_id, doc_type, prefix, suffix, padding, next_number,
                 reset_policy, is_active)
            VALUES (:org_id, :doc_type, :prefix, '', :padding, :next_number,
                    'never', FALSE)
            ON CONFLICT (org_id, doc_type) DO NOTHING
        """), {
            "org_id": org_id,
            "doc_type": doc_type,
            "prefix": prefix,
            "padding": padding,
            "next_number": last + 1,
        })
        if last:
            logger.info("Seeded %s series for org %s: continues %s at %s",
                        doc_type, org_id, prefix, last + 1)


def ensure_document_number_series_schema():
    with engine.begin() as conn:
        _create_table(conn)
        for doc_type, (table, column, extra) in SOURCES.items():
            _seed(conn, doc_type, table, column, extra)
    logger.info("containermgmt.document_number_series ready.")
