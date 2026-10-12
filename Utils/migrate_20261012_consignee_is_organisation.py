"""Point bill_of_landing.Consignee at the organisation instead of the consignee table.

The consignee table duplicated `organisations`: one row per organisation, kept
in sync by hand and auto-created from any unrecognised free text. Across 778
bills of lading the consignee never once differed from the document's own
organisation.

Consignee lists are now served from `organisations`, which changed what the id
means: a stored 1 meant consignee 1 (Noblecon, org 8) but reads as organisation
1 (Sahaj Construction). This migration rewrites the stored ids into the
organisation id space so the two agree, and drops the foreign key to the
consignee table, which no longer constrains anything meaningful.

The table itself is left in place and untouched. Dropping it is a separate
change, once this has been live long enough to be sure of.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_consignee_is_organisation")


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'containermgmt' AND table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).first())


def ensure_consignee_points_at_organisation():
    with engine.begin() as conn:
        if not _column_exists(conn, "bill_of_landing", "Consignee"):
            logger.info("bill_of_landing.Consignee is already gone; nothing to do.")
            return

        # A row whose value already equals its own organisation is in the target
        # id space and must be left alone. Judging it against the consignee
        # table would be meaningless -- an organisation id happens to match an
        # unrelated consignee id -- and would rewrite a correct value into a
        # wrong one. This is what makes the migration safe to re-run, and safe
        # on an environment whose data already arrived in the new shape.
        pending = """
            b."Consignee" IS NOT NULL
            AND b."Consignee" IS DISTINCT FROM b.org_id
        """

        # Refuse to rewrite anything if a bill of lading ever named a consignee
        # from a different organisation. That would mean the consignee carried
        # information the organisation does not, and this would destroy it.
        disagreements = conn.execute(text(f"""
            SELECT count(*) FROM containermgmt.bill_of_landing b
            JOIN containermgmt.consignee c ON c.consignee_id = b."Consignee"
            WHERE {pending}
              AND c.org_id IS NOT NULL AND b.org_id IS NOT NULL AND c.org_id <> b.org_id
        """)).scalar()
        if disagreements:
            raise RuntimeError(
                f"{disagreements} bills of lading name a consignee from a different "
                "organisation. Consignee carries real information here, so it must "
                "not be collapsed into the organisation. Migration aborted."
            )

        # The foreign key would reject organisation ids, which are not consignee ids.
        constraint = conn.execute(text("""
            SELECT c.conname FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_class rt ON rt.oid = c.confrelid
            WHERE n.nspname = 'containermgmt' AND t.relname = 'bill_of_landing'
              AND rt.relname = 'consignee' AND c.contype = 'f'
        """)).scalar()
        if constraint:
            conn.execute(text(
                f'ALTER TABLE containermgmt.bill_of_landing DROP CONSTRAINT "{constraint}"'
            ))
            logger.info("Dropped foreign key %s.", constraint)

        # Rewrite via the consignee row's own org_id, so a stored id is
        # translated rather than assumed.
        translated = conn.execute(text(f"""
            UPDATE containermgmt.bill_of_landing b
            SET "Consignee" = c.org_id
            FROM containermgmt.consignee c
            WHERE c.consignee_id = b."Consignee" AND c.org_id IS NOT NULL
              AND {pending}
        """)).rowcount

        # A bill of lading with no consignee takes its own organisation, which
        # is what it would have been set to anyway.
        filled = conn.execute(text("""
            UPDATE containermgmt.bill_of_landing
            SET "Consignee" = org_id
            WHERE "Consignee" IS NULL AND org_id IS NOT NULL
        """)).rowcount

        already = conn.execute(text("""
            SELECT count(*) FROM containermgmt.bill_of_landing
            WHERE "Consignee" IS NOT NULL AND "Consignee" = org_id
        """)).scalar()
        logger.info(
            "bill_of_landing.Consignee holds organisation ids "
            "(%s translated, %s filled from the owning organisation, "
            "%s already correct).",
            translated, filled, already,
        )
