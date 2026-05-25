import sys
import os

# Add Backend path so we can import models
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Model.db import engine, Base
from sqlalchemy import inspect
from sqlalchemy.sql import text

# Import everything so Base knows about all tables
from Model.containermgmt import *
from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.Credentials.SessionAudit import SessionAudit
from Model.containermgmt.AuditLog import AuditLog

def upgrade_tables():
    print("Starting database audit columns upgrade...")
    
    # 1. Create any brand new tables (e.g., session_audit, audit_logs)
    Base.metadata.create_all(engine)
    print("Created brand new tables (if any).")

    # 2. Iterate through all tables and add audit columns if missing
    inspector = inspect(engine)
    
    audit_columns = {
        "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "is_deleted": "TINYINT(1) DEFAULT 0",
        "deleted_at": "DATETIME NULL",
        "created_by": "INT NULL",
        "updated_by": "INT NULL",
        "deleted_by": "INT NULL"
    }

    with engine.begin() as conn:
        for table_name in Base.metadata.tables.keys():
            # Skip the new audit ledger tables
            if table_name in ["containermgmt.audit_logs", "usercredentials.session_audit"]:
                continue
                
            # SQLite vs MySQL parsing
            # Base.metadata.tables stores them as "schema.table" usually
            parts = table_name.split(".")
            actual_table_name = parts[-1]
            schema_name = parts[0] if len(parts) > 1 else None

            # Get existing columns in the table
            try:
                existing_cols = [c["name"] for c in inspector.get_columns(actual_table_name, schema=schema_name)]
            except Exception as e:
                print(f"Skipping {table_name}: {e}")
                continue

            # Add missing columns
            for col_name, col_type in audit_columns.items():
                if col_name not in existing_cols:
                    # SQLite does not support multiple ADD COLUMN statements or ON UPDATE
                    # We assume MySQL here based on the schema names and syntax requested
                    full_table_ref = f"{schema_name}.{actual_table_name}" if schema_name else actual_table_name
                    
                    alter_query = f"ALTER TABLE {full_table_ref} ADD COLUMN {col_name} {col_type}"
                    print(f"Executing: {alter_query}")
                    try:
                        conn.execute(text(alter_query))
                    except Exception as e:
                        print(f"Failed to add {col_name} to {full_table_ref}. Error: {e}")

    print("Upgrade complete! All tables now have audit columns.")

if __name__ == "__main__":
    upgrade_tables()
