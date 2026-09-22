"""
Migration & Data Unification Script:
1. Harmonizes legal entity names across Organisations and Consignees.
2. Links Consignee records to their respective Tenant org_id and standard short codes.
3. Backfills existing Purchase Orders and RFQs to their correct tenant org_id.
"""

import logging
from sqlalchemy import text
from Model.db import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("unify_org_consignee")

def run_migration():
    db = SessionLocal()
    try:
        logger.info("=== 1. Harmonizing usercredentials.organisations ===")
        # Ensure code column exists on organisations
        db.execute(text("""
            ALTER TABLE usercredentials.organisations
            ADD COLUMN IF NOT EXISTS code VARCHAR(20);
        """))
        db.commit()

        # Update canonical names, display names, and codes
        db.execute(text("""
            UPDATE usercredentials.organisations
            SET code = 'SAHAJ', display_name = 'SAHAJ CONSTRUCTION'
            WHERE id = 1;

            UPDATE usercredentials.organisations
            SET code = 'NOBLE', display_name = 'NOBLECON ENTERPRISE'
            WHERE id = 2;

            UPDATE usercredentials.organisations
            SET code = 'SAHAJANAND', display_name = 'SAHAJANAND'
            WHERE id = 3;
        """))
        db.commit()
        logger.info("  [+] Organisations updated successfully.")

        logger.info("=== 2. Harmonizing containermgmt.consignee ===")
        # Ensure org_id and code columns exist on consignee
        db.execute(text("""
            ALTER TABLE containermgmt.consignee
            ADD COLUMN IF NOT EXISTS org_id INTEGER REFERENCES usercredentials.organisations(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS code VARCHAR(20);
        """))
        db.commit()

        # Remove blank/corrupt consignees
        db.execute(text("""
            DELETE FROM containermgmt.consignee
            WHERE TRIM(COALESCE(consignee_name, '')) = '';
        """))
        db.commit()

        # Ensure Noblecon Enterprise (org_id = 2, code = 'NOBLE')
        noble_con = db.execute(text("""
            SELECT consignee_id FROM containermgmt.consignee WHERE consignee_name ILIKE '%NOBLE%' LIMIT 1;
        """)).fetchone()
        if noble_con:
            db.execute(text("""
                UPDATE containermgmt.consignee
                SET consignee_name = 'NOBLECON ENTERPRISE', org_id = 2, code = 'NOBLE', is_deleted = FALSE
                WHERE consignee_id = :cid;
            """), {"cid": noble_con[0]})
        else:
            db.execute(text("""
                INSERT INTO containermgmt.consignee (consignee_name, org_id, code, is_deleted)
                VALUES ('NOBLECON ENTERPRISE', 2, 'NOBLE', FALSE);
            """))

        # Ensure Sahajanand (org_id = 3, code = 'SAHAJANAND')
        sahaj_anand = db.execute(text("""
            SELECT consignee_id FROM containermgmt.consignee WHERE consignee_name ILIKE '%SAHAJANAND%' LIMIT 1;
        """)).fetchone()
        if sahaj_anand:
            db.execute(text("""
                UPDATE containermgmt.consignee
                SET consignee_name = 'SAHAJANAND', org_id = 3, code = 'SAHAJANAND', is_deleted = FALSE
                WHERE consignee_id = :cid;
            """), {"cid": sahaj_anand[0]})
        else:
            db.execute(text("""
                INSERT INTO containermgmt.consignee (consignee_name, org_id, code, is_deleted)
                VALUES ('SAHAJANAND', 3, 'SAHAJANAND', FALSE);
            """))

        # Ensure Sahaj Construction (org_id = 1, code = 'SAHAJ')
        sahaj_con = db.execute(text("""
            SELECT consignee_id FROM containermgmt.consignee WHERE consignee_name ILIKE '%SAHAJ%' AND consignee_name NOT ILIKE '%SAHAJANAND%' LIMIT 1;
        """)).fetchone()
        if sahaj_con:
            db.execute(text("""
                UPDATE containermgmt.consignee
                SET consignee_name = 'SAHAJ CONSTRUCTION', org_id = 1, code = 'SAHAJ', is_deleted = FALSE
                WHERE consignee_id = :cid;
            """), {"cid": sahaj_con[0]})
        else:
            db.execute(text("""
                INSERT INTO containermgmt.consignee (consignee_name, org_id, code, is_deleted)
                VALUES ('SAHAJ CONSTRUCTION', 1, 'SAHAJ', FALSE);
            """))
        db.commit()
        logger.info("  [+] Consignee canonical master records synchronized.")

        logger.info("=== 3. Backfilling containermgmt.purchase_orders Tenant Isolation ===")
        # Backfill Noblecon orders
        r_noble = db.execute(text("""
            UPDATE containermgmt.purchase_orders
            SET org_id = 2, sheet_type = 'NOBLE', consignee = 'NOBLECON ENTERPRISE'
            WHERE (sheet_type ILIKE '%NOBLE%' OR consignee ILIKE '%NOBLE%');
        """))
        logger.info("  [*] Updated %d orders to Noblecon Enterprise (org_id = 2)", r_noble.rowcount)

        # Backfill Sahajanand orders
        r_sahajanand = db.execute(text("""
            UPDATE containermgmt.purchase_orders
            SET org_id = 3, sheet_type = 'SAHAJANAND', consignee = 'SAHAJANAND'
            WHERE (sheet_type ILIKE '%SAHAJANAND%' OR consignee ILIKE '%SAHAJANAND%');
        """))
        logger.info("  [*] Updated %d orders to Sahajanand (org_id = 3)", r_sahajanand.rowcount)

        # Backfill Sahaj Construction orders
        r_sahaj = db.execute(text("""
            UPDATE containermgmt.purchase_orders
            SET org_id = 1, sheet_type = 'SAHAJ', consignee = 'SAHAJ CONSTRUCTION'
            WHERE org_id IS NULL OR (sheet_type ILIKE '%SAHAJ%' AND sheet_type NOT ILIKE '%SAHAJANAND%')
               OR (consignee ILIKE '%SAHAJ%' AND consignee NOT ILIKE '%SAHAJANAND%');
        """))
        logger.info("  [*] Updated %d orders to Sahaj Construction (org_id = 1)", r_sahaj.rowcount)

        db.commit()

        # Log Final Counts
        logger.info("=== Final Purchase Order Counts by Tenant ===")
        counts = db.execute(text("""
            SELECT o.name, po.org_id, COUNT(*)
            FROM containermgmt.purchase_orders po
            JOIN usercredentials.organisations o ON po.org_id = o.id
            GROUP BY o.name, po.org_id;
        """)).fetchall()
        for row in counts:
            logger.info("  -> Tenant: %-15s (org_id = %d): %d orders", row[0], row[1], row[2])

        logger.info("=== Migration and Data Unification Completed Successfully! ===")

    except Exception as e:
        db.rollback()
        logger.error("Migration failed: %s", e, exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()
