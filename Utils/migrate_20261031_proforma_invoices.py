"""Add the proforma invoice, and move recorded payments onto it.

The PO is the commitment; the vendor's proforma is what is paid against. This
creates proforma_invoices and proforma_invoice_items, points order_payments and
order_documents at a proforma, and gives every PO that already has payments one
MIGRATED proforma so its history and totals read the same after the change.

Everything is additive. A migrated proforma is flagged source = 'MIGRATED' and
carries the PO's total as it stood, so nobody mistakes it for a document the
vendor sent. The backfill touches no payment amount and no PO figure, and it
is skipped for any PO that already has a proforma, so a second run does
nothing.
"""
import logging

from sqlalchemy import text

from Model.db import engine
import Model.containermgmt  # noqa: F401  (registers every model on Base.metadata)

logger = logging.getLogger("containerMgmt.migrate_proforma_invoices")


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'containermgmt' AND table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).first())


def ensure_proforma_invoice_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS containermgmt.proforma_invoices (
                id SERIAL PRIMARY KEY,
                org_id INTEGER NOT NULL REFERENCES usercredentials.organisations(id),
                proforma_number VARCHAR(100) NOT NULL,
                vendor_proforma_number VARCHAR(100),
                vendor_proforma_date DATE,
                valid_until DATE,
                po_id INTEGER NOT NULL REFERENCES containermgmt.purchase_orders(id) ON DELETE CASCADE,
                supplier_id INTEGER REFERENCES containermgmt.supplier(supplier_id),
                supplier_name_at_issue VARCHAR(255),
                currency VARCHAR(10) DEFAULT 'USD',
                exchange_rate_to_base NUMERIC(18,8),
                total_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
                advance_percent NUMERIC(5,2),
                payment_terms VARCHAR(255),
                bank_details JSON,
                status VARCHAR(30) NOT NULL DEFAULT 'RECEIVED',
                source VARCHAR(20) NOT NULL DEFAULT 'VENDOR',
                supersedes_id INTEGER REFERENCES containermgmt.proforma_invoices(id) ON DELETE SET NULL,
                variance_status VARCHAR(20) NOT NULL DEFAULT 'NONE',
                variance_data JSON,
                variance_justification TEXT,
                approved_by INTEGER,
                approved_at DATE,
                notes TEXT,
                revision_count INTEGER NOT NULL DEFAULT 0,
                revisions JSON,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMPTZ,
                created_by INTEGER REFERENCES usercredentials.users(id),
                updated_by INTEGER REFERENCES usercredentials.users(id),
                deleted_by INTEGER REFERENCES usercredentials.users(id)
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_proforma_invoices_number ON containermgmt.proforma_invoices (proforma_number)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proforma_invoices_po_id ON containermgmt.proforma_invoices (po_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proforma_invoices_org_id ON containermgmt.proforma_invoices (org_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proforma_invoices_status ON containermgmt.proforma_invoices (status)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS containermgmt.proforma_invoice_items (
                id SERIAL PRIMARY KEY,
                org_id INTEGER NOT NULL REFERENCES usercredentials.organisations(id),
                proforma_id INTEGER NOT NULL REFERENCES containermgmt.proforma_invoices(id) ON DELETE CASCADE,
                po_item_id INTEGER REFERENCES containermgmt.po_items(id) ON DELETE SET NULL,
                item_code VARCHAR(100),
                description TEXT NOT NULL,
                quantity NUMERIC(12,2) NOT NULL DEFAULT 1,
                unit VARCHAR(50) DEFAULT 'PCS',
                unit_price NUMERIC(14,2) NOT NULL DEFAULT 0,
                total_price NUMERIC(14,2) NOT NULL DEFAULT 0,
                po_unit_price NUMERIC(14,2),
                variance_pct NUMERIC(8,2),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMPTZ,
                created_by INTEGER REFERENCES usercredentials.users(id),
                updated_by INTEGER REFERENCES usercredentials.users(id),
                deleted_by INTEGER REFERENCES usercredentials.users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proforma_invoice_items_proforma_id ON containermgmt.proforma_invoice_items (proforma_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proforma_invoice_items_po_item_id ON containermgmt.proforma_invoice_items (po_item_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proforma_invoice_items_org_id ON containermgmt.proforma_invoice_items (org_id)"))

        for table in ("order_payments", "order_documents"):
            if not _column_exists(conn, table, "proforma_id"):
                conn.execute(text(f"""
                    ALTER TABLE containermgmt.{table}
                    ADD COLUMN proforma_id INTEGER
                        REFERENCES containermgmt.proforma_invoices(id) ON DELETE SET NULL
                """))
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_proforma_id ON containermgmt.{table} (proforma_id)"))

        _backfill_migrated_proformas(conn)


def _backfill_migrated_proformas(conn):
    """One MIGRATED proforma per PO that has payments and no proforma yet."""
    rows = conn.execute(text("""
        SELECT po.id, po.org_id, po.po_number, po.supplier_id, po.supplier_name_at_issue,
               po.company, po.currency, po.total_amount,
               COALESCE((SELECT SUM(i.total_price) FROM containermgmt.po_items i
                         WHERE i.po_id = po.id AND i.is_deleted = FALSE), 0) AS items_total
        FROM containermgmt.purchase_orders po
        WHERE po.is_deleted = FALSE
          AND EXISTS (SELECT 1 FROM containermgmt.order_payments p
                      WHERE p.po_id = po.id AND p.is_deleted = FALSE)
          AND NOT EXISTS (SELECT 1 FROM containermgmt.proforma_invoices pf WHERE pf.po_id = po.id)
    """)).fetchall()
    migrated = 0
    for r in rows:
        total = r.total_amount if r.total_amount and r.total_amount > 0 else r.items_total
        number = f"PI-{r.po_number}-M1"
        paid = conn.execute(text("""
            SELECT COALESCE(SUM(amount), 0) FROM containermgmt.order_payments
            WHERE po_id = :po AND is_deleted = FALSE
        """), {"po": r.id}).scalar() or 0
        status = "PAID" if total and paid >= total - 0.01 else ("PART_PAID" if paid > 0 else "APPROVED")
        pf_id = conn.execute(text("""
            INSERT INTO containermgmt.proforma_invoices
                (org_id, proforma_number, po_id, supplier_id, supplier_name_at_issue,
                 currency, total_amount, status, source, variance_status, revision_count, notes)
            VALUES (:org, :num, :po, :sup, :sname, :cur, :total, :status, 'MIGRATED', 'NONE', 0,
                    'Made from payments recorded on the PO before proforma invoices existed.')
            RETURNING id
        """), {
            "org": r.org_id, "num": number, "po": r.id, "sup": r.supplier_id,
            "sname": r.supplier_name_at_issue or r.company, "cur": r.currency or "USD",
            "total": total or 0, "status": status,
        }).scalar()
        conn.execute(text("""
            UPDATE containermgmt.order_payments SET proforma_id = :pf
            WHERE po_id = :po AND is_deleted = FALSE AND proforma_id IS NULL
        """), {"pf": pf_id, "po": r.id})
        migrated += 1
    if migrated:
        logger.info("Created %s migrated proforma invoice(s) for POs that already had payments.", migrated)
