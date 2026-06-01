import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Model.db import Base
# Import all models to register them on Base.metadata
from Model.containermgmt import *
from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.Credentials.SessionAudit import SessionAudit
from Model.containermgmt.AuditLog import AuditLog
from Model.Credentials.refresh_tokens import RefreshToken

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)

# Add connect_timeout to avoid hanging
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 10})

def run_sql(conn, sql, description):
    print(f">> Executing: {description}")
    try:
        conn.execute(text(sql))
        conn.commit()
        print("   [OK] Applied")
    except Exception as e:
        msg = str(e)
        # Handle cases where column already exists or constraint already exists
        if "duplicate column" in msg.lower() or "already exists" in msg.lower() or "duplicate key" in msg.lower() or "duplicate entry" in msg.lower():
            print(f"   [SKIP] Already applied: {msg[:100]}")
        elif "error 1091" in msg.lower() or "can't drop" in msg.lower():
            # Error 1091: Can't drop key/constraint; check if it exists
            print(f"   [SKIP] Constraint to drop not found: {msg[:100]}")
        else:
            print(f"   [ERROR] Failed: {msg}")
            # Do not exit for constraints that might fail or skip, but list it clearly.

def upgrade_schema():
    print("=" * 60)
    print("  Starting Database Schema Upgrade Script")
    print("=" * 60)

    inspector = inspect(engine)

    with engine.connect() as conn:
        # Step 1: Clean orphaned consignee references
        run_sql(
            conn,
            "UPDATE containermgmt.bill_of_landing SET Consignee = NULL WHERE Consignee = 0;",
            "Clean up invalid Consignee = 0 references in bill_of_landing"
        )

        # Step 2: Add missing columns to container_details & bill_of_landing
        run_sql(
            conn,
            "ALTER TABLE containermgmt.container_details ADD COLUMN FreeDays INT NULL;",
            "Add FreeDays to container_details"
        )
        run_sql(
            conn,
            "ALTER TABLE containermgmt.bill_of_landing ADD COLUMN FreeDays INT NULL;",
            "Add FreeDays to bill_of_landing"
        )
        run_sql(
            conn,
            "ALTER TABLE containermgmt.bill_of_landing ADD COLUMN status INT NULL;",
            "Add status to bill_of_landing"
        )

        # Step 3: Modify logistics provider columns to match NOT NULL defaults
        run_sql(
            conn,
            "ALTER TABLE containermgmt.logisticsprovider MODIFY COLUMN ExcludingDays INT NOT NULL DEFAULT 0;",
            "Modify ExcludingDays to NOT NULL in logisticsprovider"
        )
        run_sql(
            conn,
            "ALTER TABLE containermgmt.logisticsprovider MODIFY COLUMN FreeDays INT NOT NULL DEFAULT 0;",
            "Modify FreeDays to NOT NULL in logisticsprovider"
        )

        # Step 4: Drop old constraints on container_docs & report_details pointing to container_details02
        run_sql(
            conn,
            "ALTER TABLE containermgmt.container_docs DROP FOREIGN KEY container_docs_ibfk_1;",
            "Drop legacy FK constraint on container_docs"
        )
        run_sql(
            conn,
            "ALTER TABLE containermgmt.report_details DROP FOREIGN KEY report_details_ibfk_1;",
            "Drop legacy FK constraint on report_details"
        )

        # Step 5: Add re-routed and missing foreign keys
        # For container_docs (references container_details now)
        run_sql(
            conn,
            "ALTER TABLE containermgmt.container_docs ADD CONSTRAINT fk_container_docs_container FOREIGN KEY (container_id) REFERENCES containermgmt.container_details(Container_ID) ON DELETE CASCADE;",
            "Add correct FK constraint on container_docs referencing container_details"
        )
        # For report_details (references container_details now)
        run_sql(
            conn,
            "ALTER TABLE containermgmt.report_details ADD CONSTRAINT fk_report_details_container FOREIGN KEY (container_id) REFERENCES containermgmt.container_details(Container_ID) ON DELETE CASCADE;",
            "Add correct FK constraint on report_details referencing container_details"
        )

        # FKs for container_details
        fks_container = [
            ("fk_container_type", "type", "containermgmt.container_type(type_id)"),
            ("fk_container_emptied_venue", "emptied_at", "containermgmt.unload_venue(venue_id)"),
            ("fk_container_status", "status", "containermgmt.status(status_id)"),
            ("fk_container_bol", "BillOfLanding", "containermgmt.bill_of_landing(BillOfLanding)"),
        ]
        for constraint, col, ref in fks_container:
            run_sql(
                conn,
                f"ALTER TABLE containermgmt.container_details ADD CONSTRAINT {constraint} FOREIGN KEY ({col}) REFERENCES {ref} ON DELETE SET NULL;",
                f"Add FK {constraint} on container_details({col})"
            )

        # FKs for bill_of_landing
        fks_bol = [
            ("fk_bol_consignee", "Consignee", "containermgmt.consignee(consignee_id)"),
            ("fk_bol_vessel", "Vessel", "containermgmt.vessals(id)"),
            ("fk_bol_supplier", "Supplier", "containermgmt.supplier(supplier_id)"),
            ("fk_bol_provider", "Provider", "containermgmt.logisticsprovider(Id)"),
            ("fk_bol_doc", "Doc", "containermgmt.shipping_document(doc_id)"),
            ("fk_bol_status", "status", "containermgmt.status(status_id)"),
        ]
        for constraint, col, ref in fks_bol:
            run_sql(
                conn,
                f"ALTER TABLE containermgmt.bill_of_landing ADD CONSTRAINT {constraint} FOREIGN KEY ({col}) REFERENCES {ref} ON DELETE SET NULL;",
                f"Add FK {constraint} on bill_of_landing({col})"
            )

        # Step 6: Add Audit Columns to all models that require them
        audit_columns = {
            "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL",
            "updated_at": "DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL",
            "is_deleted": "TINYINT(1) DEFAULT 0 NOT NULL",
            "deleted_at": "DATETIME NULL",
            "created_by": "INT NULL",
            "updated_by": "INT NULL",
            "deleted_by": "INT NULL"
        }

        print("\n>> Inspecting tables for audit columns...")
        for table_full_name, model_table in Base.metadata.tables.items():
            # Skip tables that don't use audit mixin (check if created_at is in the model columns)
            if "created_at" not in model_table.columns:
                continue

            parts = table_full_name.split(".")
            schema_name = parts[0] if len(parts) > 1 else None
            table_name = parts[-1]

            # Get database columns
            try:
                db_cols = [c["name"] for c in inspector.get_columns(table_name, schema=schema_name)]
            except Exception as e:
                print(f"   [SKIP] Table {table_full_name} not found in DB: {e}")
                continue

            # Add missing columns
            for col_name, col_type in audit_columns.items():
                if col_name not in db_cols:
                    alter_sql = f"ALTER TABLE {table_full_name} ADD COLUMN {col_name} {col_type};"
                    run_sql(conn, alter_sql, f"Add {col_name} to {table_full_name}")

            # Add foreign keys for audit user relations (if they don't already exist)
            # Fetch existing foreign keys on this table
            try:
                db_fks = inspector.get_foreign_keys(table_name, schema=schema_name)
                db_fk_cols = [fk["constrained_columns"][0] for fk in db_fks if fk["constrained_columns"]]
            except Exception as e:
                db_fk_cols = []

            for audit_col in ["created_by", "updated_by", "deleted_by"]:
                if audit_col not in db_fk_cols:
                    fk_name = f"fk_{table_name}_{audit_col}"
                    fk_sql = f"ALTER TABLE {table_full_name} ADD CONSTRAINT {fk_name} FOREIGN KEY ({audit_col}) REFERENCES usercredentials.users(id) ON DELETE SET NULL;"
                    run_sql(conn, fk_sql, f"Add audit FK {fk_name} on {table_full_name}({audit_col})")

    print("\n" + "=" * 60)
    print("  Schema upgrade process completed.")
    print("=" * 60)

if __name__ == "__main__":
    upgrade_schema()
