"""One row per vendor, visible to every company.

A vendor was scoped to one organisation, so the same company was entered once
per tenant: "EMILY - FOSHAN GENTLE" existed twice, under two organisations, and
the directory listed it twice with nothing to tell the rows apart. The scoping
was fiction anyway -- bills of lading showed single vendors serving three
companies at once -- and it is what made a vendor vanish from a quotation's
vendor list while sitting in plain sight in the master.

Duplicates are merged into one row per name, every reference is repointed at the
survivor, and every vendor is marked shared so each company can use it. Which
organisation owns a vendor stops being a visibility rule; `org_id` is kept only
as a record of who first entered it.

Re-running is a no-op: with no duplicates left there is nothing to merge, and
the suppliers are already shared.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_unique_shared_suppliers")

# Every column that points at supplier.supplier_id, found from the live schema's
# foreign keys rather than listed by hand, so a new one cannot be missed.
_FK_QUERY = """
    SELECT tc.table_schema, tc.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name
    JOIN information_schema.constraint_column_usage ccu
      ON ccu.constraint_name = tc.constraint_name
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND ccu.table_schema = 'containermgmt'
      AND ccu.table_name = 'supplier'
      AND ccu.column_name = 'supplier_id'
"""

# Filled in from a loser only where the survivor has nothing, so merging adds
# detail and never overwrites it.
_MERGEABLE = (
    "code", "address", "email", "phone", "contact_person", "country",
    "logo_url", "default_currency", "default_payment_term_id", "notes",
)


def _normalised_name():
    """Group on the name as a person reads it: case and spacing do not matter."""
    return "lower(regexp_replace(trim(name), '\\s+', ' ', 'g'))"


def ensure_unique_shared_suppliers():
    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'containermgmt' AND table_name = 'supplier'
        """)).first()
        if not exists:
            logger.info("supplier table is not there yet; nothing to do.")
            return

        references = [
            (row.table_schema, row.table_name, row.column_name)
            for row in conn.execute(text(_FK_QUERY))
        ]

        groups = conn.execute(text(f"""
            SELECT {_normalised_name()} AS norm,
                   array_agg(supplier_id ORDER BY supplier_id) AS ids
            FROM containermgmt.supplier
            WHERE is_deleted IS NOT TRUE AND name IS NOT NULL AND trim(name) <> ''
            GROUP BY 1
            HAVING count(*) > 1
        """)).fetchall()

        merged = 0
        repointed = 0
        for group in groups:
            ids = list(group.ids)
            # The survivor is the most complete row, so the directory keeps the
            # best record rather than whichever was entered first.
            survivor = conn.execute(text(f"""
                SELECT supplier_id FROM containermgmt.supplier
                WHERE supplier_id = ANY(:ids)
                ORDER BY (
                    {' + '.join(f"(CASE WHEN {c} IS NOT NULL THEN 1 ELSE 0 END)" for c in _MERGEABLE)}
                ) DESC, is_shared DESC, supplier_id ASC
                LIMIT 1
            """), {"ids": ids}).scalar()
            losers = [i for i in ids if i != survivor]
            if not losers:
                continue

            # Carry across anything the survivor is missing.
            for column in _MERGEABLE:
                conn.execute(text(f"""
                    UPDATE containermgmt.supplier s SET {column} = donor.{column}
                    FROM (
                        SELECT {column} FROM containermgmt.supplier
                        WHERE supplier_id = ANY(:losers) AND {column} IS NOT NULL
                        ORDER BY supplier_id LIMIT 1
                    ) AS donor
                    WHERE s.supplier_id = :survivor AND s.{column} IS NULL
                """), {"losers": losers, "survivor": survivor})

            for schema, table, column in references:
                result = conn.execute(text(f"""
                    UPDATE {schema}.{table} SET "{column}" = :survivor
                    WHERE "{column}" = ANY(:losers)
                """), {"survivor": survivor, "losers": losers})
                repointed += result.rowcount

            # product_suppliers has no uniqueness constraint, so repointing can
            # leave the same product listed against the survivor twice.
            conn.execute(text("""
                DELETE FROM containermgmt.product_suppliers a
                USING containermgmt.product_suppliers b
                WHERE a.supplier_id = :survivor AND b.supplier_id = :survivor
                  AND a.product_id = b.product_id AND a.id > b.id
            """), {"survivor": survivor})

            conn.execute(text(
                "DELETE FROM containermgmt.supplier WHERE supplier_id = ANY(:losers)"
            ), {"losers": losers})
            merged += len(losers)

        # Visibility is no longer a per-organisation matter.
        shared = conn.execute(text("""
            UPDATE containermgmt.supplier SET is_shared = TRUE
            WHERE is_deleted IS NOT TRUE AND is_shared IS NOT TRUE
        """)).rowcount

        remaining = conn.execute(text(
            "SELECT count(*) FROM containermgmt.supplier WHERE is_deleted IS NOT TRUE"
        )).scalar()
        logger.info(
            "Suppliers are unique and shared (%s duplicates merged, %s references "
            "repointed, %s newly shared, %s vendors remain).",
            merged, repointed, shared, remaining,
        )
