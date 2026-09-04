import logging
import sys
from sqlalchemy import create_engine, text, MetaData, Table, inspect
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("migration")

MYSQL_URL = "mysql+mysqlconnector://mysql:WixN8jgG57GnfHfOj7jYwiF6gD8xzkTJmRPsb5Ri20iC1pBbUngVLLuGAuC4JVqX@82.25.110.112:3309"
PG_URL = "postgresql+psycopg2://postgres:postgres_local@127.0.0.1:5433/containermgmt_pg"

def run_migration():
    logger.info("Connecting to MySQL source & PostgreSQL target...")
    mysql_engine = create_engine(MYSQL_URL)
    pg_engine = create_engine(PG_URL)

    # 1. Initialize PostgreSQL schemas & tables
    from Model.db import Base
    from Model.Credentials import User, Role, Permission, RefreshToken, Organisation
    from Model.containermgmt import (
        ContainerDetails, ContainerDocs, BillOfLanding, Vessal, PackingList,
        ReportDetails, ReportImage, DamageProduct, Supplier, Consignee, ContainerType,
        ShippingDocument, UnloadVenue, Status, Material, LogisticsProvider
    )

    logger.info("Creating schemas in PostgreSQL...")
    with pg_engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS containermgmt;"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS usercredentials;"))
        conn.commit()

    logger.info("Creating tables in PostgreSQL...")
    Base.metadata.create_all(bind=pg_engine)
    logger.info("PostgreSQL tables ready.")

    # 2. Seed Default Organisations
    pg_session = sessionmaker(bind=pg_engine)()
    try:
        org_sahaj = pg_session.query(Organisation).filter_by(id=1).first()
        if not org_sahaj:
            logger.info("Seeding default organisations...")
            sahaj = Organisation(id=1, name="sahaj", display_name="Sahaj Construction", parent_org_id=None, is_active=True)
            noblecon = Organisation(id=2, name="noblecon", display_name="Noblecon", parent_org_id=1, is_active=True)
            sahajanand = Organisation(id=3, name="sahajanand", display_name="Sahajanand", parent_org_id=1, is_active=True)
            pg_session.add_all([sahaj, noblecon, sahajanand])
            pg_session.commit()
            logger.info("Default organisations seeded.")
    except Exception as e:
        logger.error("Failed seeding organisations: %s", e)
        pg_session.rollback()
    finally:
        pg_session.close()

    # Tables to migrate in dependency order: (schema, table_name, has_org_id)
    tables_to_migrate = [
        # usercredentials
        ("usercredentials", "permissions", False),
        ("usercredentials", "roles", False),
        ("usercredentials", "users", True),
        ("usercredentials", "user_roles", False),
        ("usercredentials", "role_permissions", False),
        ("usercredentials", "refresh_tokens", False),
        ("usercredentials", "session_audit", False),
        # containermgmt reference
        ("containermgmt", "status", False),
        ("containermgmt", "unload_venue", False),
        ("containermgmt", "container_type", False),
        ("containermgmt", "vessals", False),
        ("containermgmt", "supplier", False),
        ("containermgmt", "consignee", False),
        ("containermgmt", "logisticsprovider", False),
        ("containermgmt", "shipping_document", False),
        ("containermgmt", "material", False),
        # containermgmt transactional
        ("containermgmt", "bill_of_landing", True),
        ("containermgmt", "container_details", True),
        ("containermgmt", "container_products", False),
        ("containermgmt", "container_docs", False),
        ("containermgmt", "report_details", False),
        ("containermgmt", "report_images", False),
    ]

    with mysql_engine.connect() as mysql_conn, pg_engine.connect() as pg_conn:
        for schema, table_name, has_org_id in tables_to_migrate:
            logger.info(f"Migrating {schema}.{table_name}...")
            try:
                # Read rows from MySQL
                result = mysql_conn.execute(text(f"SELECT * FROM {schema}.{table_name}"))
                keys = list(result.keys())
                rows = [dict(zip(keys, row)) for row in result.fetchall()]

                if not rows:
                    logger.info(f"No rows found in MySQL {schema}.{table_name}")
                    continue

                # Data conversions for PostgreSQL compatibility
                for r in rows:
                    if has_org_id and ("org_id" not in r or r["org_id"] is None):
                        r["org_id"] = 1
                    if "is_deleted" in r and r["is_deleted"] is not None:
                        r["is_deleted"] = bool(r["is_deleted"])
                    if "revoked" in r and r["revoked"] is not None:
                        r["revoked"] = bool(r["revoked"])

                # Construct bulk INSERT for PostgreSQL
                col_names = ", ".join(f'"{k}"' for k in keys) + (', "org_id"' if (has_org_id and "org_id" not in keys) else "")
                val_placeholders = ", ".join(f':{k}' for k in keys) + (', :org_id' if (has_org_id and "org_id" not in keys) else "")
                
                insert_sql = text(f'INSERT INTO {schema}.{table_name} ({col_names}) VALUES ({val_placeholders}) ON CONFLICT DO NOTHING;')
                
                pg_conn.execute(insert_sql, rows)
                pg_conn.commit()
                logger.info(f"Successfully migrated {len(rows)} rows to PostgreSQL {schema}.{table_name}")

            except Exception as e:
                logger.error(f"Error migrating {schema}.{table_name}: {e}")
                pg_conn.rollback()

        # Fix sequences in PostgreSQL so serial/autoincrement works
        logger.info("Syncing PostgreSQL sequence counters...")
        sequence_queries = [
            ("usercredentials", "organisations", "id"),
            ("usercredentials", "users", "id"),
            ("usercredentials", "roles", "id"),
            ("usercredentials", "permissions", "id"),
            ("containermgmt", "container_details", "Container_ID"),
            ("containermgmt", "vessals", "id"),
            ("containermgmt", "supplier", "supplier_id"),
            ("containermgmt", "consignee", "consignee_id"),
            ("containermgmt", "container_type", "type_id"),
            ("containermgmt", "shipping_document", "doc_id"),
            ("containermgmt", "unload_venue", "venue_id"),
            ("containermgmt", "status", "status_id"),
            ("containermgmt", "material", "Id"),
            ("containermgmt", "logisticsprovider", "Id"),
        ]

        for schema, table_name, pk_col in sequence_queries:
            try:
                sql = text(f"""
                    SELECT setval(
                        pg_get_serial_sequence('{schema}.{table_name}', '{pk_col}'),
                        COALESCE((SELECT MAX("{pk_col}") FROM {schema}.{table_name}), 1),
                        true
                    );
                """)
                pg_conn.execute(sql)
                pg_conn.commit()
            except Exception as e:
                logger.warning(f"Could not reset sequence for {schema}.{table_name}: {e}")
                pg_conn.rollback()

    logger.info("MIGRATION COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    run_migration()
