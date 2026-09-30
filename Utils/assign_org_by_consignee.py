import psycopg2
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

PG_URL = os.getenv("DATABASE_URL")

def assign_tenants_by_consignee():
    if not PG_URL:
        raise RuntimeError("DATABASE_URL is required")
    logging.info("Connecting to PostgreSQL to re-assign tenants based on Consignee...")
    conn = psycopg2.connect(PG_URL)
    cur = conn.cursor()

    # 1. Update bill_of_landing table
    logging.info("Updating bill_of_landing org_id based on Consignee ID...")
    
    # Noblecon (Consignee ID = 1) -> org_id = 2
    cur.execute('UPDATE containermgmt.bill_of_landing SET org_id = 2 WHERE "Consignee" = 1;')
    noble_bol_count = cur.rowcount
    
    # Sahajanand (Consignee ID = 2) -> org_id = 3
    cur.execute('UPDATE containermgmt.bill_of_landing SET org_id = 3 WHERE "Consignee" = 2;')
    sahajanand_bol_count = cur.rowcount

    # Sahaj Root (Consignee ID not in 1, 2 or IS NULL) -> org_id = 1
    cur.execute('UPDATE containermgmt.bill_of_landing SET org_id = 1 WHERE "Consignee" NOT IN (1, 2) OR "Consignee" IS NULL;')
    sahaj_bol_count = cur.rowcount

    logging.info(f"BOL Tenant Assignment -> Noblecon (org_id=2): {noble_bol_count} | Sahajanand (org_id=3): {sahajanand_bol_count} | Sahaj (org_id=1): {sahaj_bol_count}")

    # 2. Update container_details based on BillOfLanding relationship
    logging.info("Updating container_details org_id based on linked BillOfLanding org_id...")
    cur.execute('''
        UPDATE containermgmt.container_details cd
        SET org_id = bol.org_id
        FROM containermgmt.bill_of_landing bol
        WHERE cd."BillOfLanding" = bol."BillOfLanding" AND cd."BillOfLanding" IS NOT NULL;
    ''')
    linked_containers_updated = cur.rowcount

    # 3. For containers without a BL, check note/PONo or default
    cur.execute('''
        UPDATE containermgmt.container_details
        SET org_id = CASE
            WHEN LOWER(note) LIKE '%noble%' OR LOWER("PONo") LIKE '%noble%' OR LOWER("PONo") LIKE '%nce%' THEN 2
            WHEN LOWER(note) LIKE '%sahajanand%' OR LOWER("PONo") LIKE '%sahajanand%' THEN 3
            ELSE 1
        END
        WHERE "BillOfLanding" IS NULL OR "BillOfLanding" = '';
    ''')
    unlinked_containers_updated = cur.rowcount

    conn.commit()

    # 4. Print breakdown summary
    cur.execute('SELECT org_id, COUNT(*) FROM containermgmt.bill_of_landing GROUP BY org_id ORDER BY org_id;')
    bol_stats = cur.fetchall()

    cur.execute('SELECT org_id, COUNT(*) FROM containermgmt.container_details GROUP BY org_id ORDER BY org_id;')
    container_stats = cur.fetchall()

    cur.close()
    conn.close()

    logging.info("=== TENANT RE-ASSIGNMENT COMPLETED SUCCESSFULLY ===")
    logging.info(f"Final Bills of Lading by Tenant (org_id, count): {bol_stats}")
    logging.info(f"Final Containers by Tenant (org_id, count): {container_stats}")

if __name__ == "__main__":
    assign_tenants_by_consignee()
