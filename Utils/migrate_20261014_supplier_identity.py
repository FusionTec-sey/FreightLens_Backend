"""Give every supplier a real code, and somewhere to put who they are.

Three things, all in one window because each of them is cheap only while the
supplier table is still as the import left it.

**The code was a display fallback, not data.** The directory showed
`VEND-0042` for every vendor, computed from the row id at serialisation time:
of 136 suppliers, not one had a code stored. So the code people read off the
screen, quote on the phone and write on a delivery note existed nowhere, could
not be searched, and would have changed the day the serialiser changed. The
backfill writes down exactly what was being displayed -- nobody's code moves --
and a unique index then holds it.

**Identifiers belong in rows.** A tax number, a company registration number,
later a GLN or a DUNS; an overseas supplier carries a different set from a
Seychelles one. As columns that is a widening table of mostly-empty cells where
no field can be made mandatory. As rows it is one shape, with `verified_at`
sitting where verification will be recorded, and "same country, same
registration number" becomes a far stronger duplicate check than the name match
used today.

**linked_org_id is deliberately unused.** It is the counterparty seam for
connected vendor tenants (docs/planning/CONNECTED-VENDOR-NETWORK-FUTURE-SCOPE.md).
A nullable column added now costs nothing; the same column added later is a
migration across a live supplier table.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_supplier_identity")

# What the serialiser displayed: `s.code or f"VEND-{s.supplier_id:04d}"`.
# The backfill has to match it character for character, or every vendor's code
# changes under the people who have been reading it.
_BACKFILL = """
    UPDATE containermgmt.supplier
    SET code = 'VEND-' || lpad(supplier_id::text, 4, '0')
    WHERE (code IS NULL OR trim(code) = '')
"""


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'containermgmt' AND table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).first())


def ensure_supplier_identity_schema():
    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'containermgmt' AND table_name = 'supplier'
        """)).first()
        if not exists:
            logger.info("supplier table is not there yet; nothing to do.")
            return

        # The code column lives in the model, not in a migration of its own, so a
        # database older than that model would have the backfill fail on a column
        # that is not there -- and these migrations run before the app serves, so
        # that is a refusal to boot, not a warning.
        if not _column_exists(conn, "supplier", "code"):
            conn.execute(text("ALTER TABLE containermgmt.supplier ADD COLUMN code VARCHAR(50)"))
            logger.info("Added the missing supplier.code column before backfilling it.")

        filled = conn.execute(text(_BACKFILL)).rowcount
        if filled:
            logger.info("Wrote down %s supplier code(s) that were only ever displayed.", filled)

        # Case-insensitive, because VEND-0042 and vend-0042 are one code to a
        # person. Deleted rows are excluded so retiring a vendor does not hold
        # its code hostage.
        clashes = conn.execute(text("""
            SELECT lower(trim(code)) AS code, count(*) AS n
            FROM containermgmt.supplier
            WHERE is_deleted IS NOT TRUE AND code IS NOT NULL AND trim(code) <> ''
            GROUP BY 1 HAVING count(*) > 1
        """)).fetchall()
        if clashes:
            # Never guess which vendor keeps the code: that is a merge decision.
            logger.warning(
                "Supplier codes are not unique yet, so the index is being skipped: %s. "
                "Resolve each duplicate (merge or recode) and restart.",
                ", ".join(f"{row.code} x{row.n}" for row in clashes),
            )
        else:
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_code_ci
                ON containermgmt.supplier (lower(trim(code)))
                WHERE is_deleted IS NOT TRUE AND code IS NOT NULL AND trim(code) <> ''
            """))

        if not _column_exists(conn, "supplier", "linked_org_id"):
            conn.execute(text("""
                ALTER TABLE containermgmt.supplier
                ADD COLUMN linked_org_id INTEGER
                REFERENCES usercredentials.organisations(id) ON DELETE SET NULL
            """))
            logger.info("Added supplier.linked_org_id (unused; the counterparty seam).")

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS containermgmt.supplier_identifiers (
                id SERIAL PRIMARY KEY,
                supplier_id INTEGER NOT NULL
                    REFERENCES containermgmt.supplier(supplier_id) ON DELETE CASCADE,
                id_type VARCHAR(30) NOT NULL,
                country VARCHAR(100),
                value VARCHAR(100) NOT NULL,
                is_primary BOOLEAN NOT NULL DEFAULT FALSE,
                verified_at TIMESTAMPTZ,
                verified_by INTEGER REFERENCES usercredentials.users(id),
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_by INTEGER REFERENCES usercredentials.users(id),
                updated_by INTEGER REFERENCES usercredentials.users(id),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMPTZ,
                deleted_by INTEGER REFERENCES usercredentials.users(id)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_supplier_identifiers_supplier
            ON containermgmt.supplier_identifiers (supplier_id)
            WHERE is_deleted IS NOT TRUE
        """))
        # Two suppliers cannot hold the same registration number in the same
        # country: that is one company entered twice, which is exactly what the
        # index is here to catch.
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_identifier_value
            ON containermgmt.supplier_identifiers (
                id_type, lower(coalesce(country, '')), lower(trim(value))
            )
            WHERE is_deleted IS NOT TRUE
        """))

        coded = conn.execute(text("""
            SELECT count(*) FROM containermgmt.supplier
            WHERE is_deleted IS NOT TRUE AND code IS NOT NULL AND trim(code) <> ''
        """)).scalar()
        logger.info("Supplier identity is ready (%s vendors carry a stored code).", coded)
