import os
import sys
import logging
import re
from datetime import datetime
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

# Set logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("migration")

# Add Backend to sys.path
sys.path.append("d:\\WorkPlace\\Seychelles_Sahaj\\Backend")

# Load environment
load_dotenv("d:\\WorkPlace\\Seychelles_Sahaj\\Backend\\.env")
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env")
    sys.exit(1)

# Import models
from Model.db import Base
from Model.containermgmt import *
from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.Credentials.permissions import Permission
from Model.Credentials.SessionAudit import SessionAudit
from Model.containermgmt.AuditLog import AuditLog

# Create root engine (no default database)
logger.info("Connecting to MySQL server...")
temp_url = DATABASE_URL
if "/" in temp_url.split("@")[-1]:
    temp_url = temp_url.rsplit("/", 1)[0]
root_engine = create_engine(temp_url)

def load_sql_dump(filename):
    logger.info(f"Reading SQL dump file: {filename}")
    content = ""
    for encoding in ['utf-8', 'utf-16', 'utf-16-le', 'latin1']:
        try:
            with open(filename, 'r', encoding=encoding) as f:
                content = f.read()
            logger.info(f"Successfully read file with encoding: {encoding}")
            break
        except Exception:
            continue
            
    if not content:
        raise ValueError("Could not read SQL dump with any encoding")

    # Remove DELIMITER ;; ... DELIMITER ; blocks completely (trigger definitions)
    content_clean = re.sub(r'(?i)DELIMITER\s+;;\s*.*?\s*DELIMITER\s*;', '', content, flags=re.DOTALL)

    # Split statements by semicolon
    statements = []
    current_stmt = []
    
    for line in content_clean.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        if line_clean.startswith("--") or line_clean.startswith("/*"):
            continue
        current_stmt.append(line)
        if line_clean.endswith(";"):
            statements.append("\n".join(current_stmt))
            current_stmt = []
            
    logger.info(f"Executing {len(statements)} SQL statements from dump...")
    with root_engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
        for stmt in statements:
            stmt_strip = stmt.strip()
            if not stmt_strip:
                continue
            try:
                conn.execute(text(stmt_strip))
            except Exception as e:
                logger.warning(f"Statement failed: {stmt_strip[:80]}... Error: {e}")
        conn.commit()
    logger.info("SQL dump loaded successfully.")

def read_all_data(engine):
    logger.info("Reading data from raw tables into memory...")
    inspector = inspect(engine)
    data = {}
    
    # Read containermgmt schema tables
    containermgmt_tables = [
        'consignee', 'supplier', 'vessals', 'shipping_document', 'unload_venue',
        'logisticsprovider', 'material', 'container_type', 'status', 'packing_list',
        'container_details02', 'container_details', 'container_docs',
        'damageproduct', 'report_images', 'report_details', 'container_products'
    ]
    for table in containermgmt_tables:
        if inspector.has_table(table, schema='containermgmt'):
            with engine.connect() as conn:
                res = conn.execute(text(f"SELECT * FROM containermgmt.{table}"))
                cols = res.keys()
                data[f"containermgmt.{table}"] = [dict(zip(cols, row)) for row in res.fetchall()]
                logger.info(f"Loaded {len(data[f'containermgmt.{table}'])} rows from containermgmt.{table}")
        else:
            data[f"containermgmt.{table}"] = []
            logger.warning(f"Table containermgmt.{table} not found in database.")

    # Read usercredentials schema tables
    usercredentials_tables = [
        'users', 'roles', 'permissions', 'user_roles', 'role_permissions',
        'session_audit', 'user_refresh_tokens'
    ]
    for table in usercredentials_tables:
        if inspector.has_table(table, schema='usercredentials'):
            with engine.connect() as conn:
                res = conn.execute(text(f"SELECT * FROM usercredentials.{table}"))
                cols = res.keys()
                data[f"usercredentials.{table}"] = [dict(zip(cols, row)) for row in res.fetchall()]
                logger.info(f"Loaded {len(data[f'usercredentials.{table}'])} rows from usercredentials.{table}")
        else:
            data[f"usercredentials.{table}"] = []
            logger.warning(f"Table usercredentials.{table} not found in database.")
            
    return data

def recreate_clean_databases():
    logger.info("Recreating schemas containermgmt and usercredentials...")
    with root_engine.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS containermgmt"))
        conn.execute(text("DROP DATABASE IF EXISTS usercredentials"))
        conn.execute(text("CREATE DATABASE containermgmt"))
        conn.execute(text("CREATE DATABASE usercredentials"))
        conn.commit()
    logger.info("Databases recreated successfully.")

def write_data_back(engine, data):
    logger.info("Writing data back into the normalized schema...")
    now = datetime.now()

    with engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0;"))

        # Helper to insert rows dynamically
        def insert_rows(table_ref, rows, audit=True):
            if not rows:
                return
            # Get column names
            cols = list(rows[0].keys())
            if audit:
                # Add audit columns if missing
                audit_cols = {
                    'created_at': now,
                    'updated_at': now,
                    'is_deleted': 0,
                    'deleted_at': None,
                    'created_by': None,
                    'updated_by': None,
                    'deleted_by': None
                }
                for c, val in audit_cols.items():
                    if c not in cols:
                        cols.append(c)
                        for r in rows:
                            r[c] = val

            col_str = ", ".join([f"`{c}`" for c in cols])
            val_str = ", ".join([f":{c}" for c in cols])
            sql = f"INSERT INTO {table_ref} ({col_str}) VALUES ({val_str})"
            
            conn.execute(text(sql), rows)
            logger.info(f"Inserted {len(rows)} rows into {table_ref}")

        # 1. usercredentials tables
        insert_rows("usercredentials.permissions", data["usercredentials.permissions"], audit=False)
        insert_rows("usercredentials.roles", data["usercredentials.roles"], audit=True)
        insert_rows("usercredentials.users", data["usercredentials.users"], audit=True)
        insert_rows("usercredentials.role_permissions", data["usercredentials.role_permissions"], audit=False)
        insert_rows("usercredentials.user_roles", data["usercredentials.user_roles"], audit=False)
        insert_rows("usercredentials.session_audit", data["usercredentials.session_audit"], audit=False)
        insert_rows("usercredentials.user_refresh_tokens", data["usercredentials.user_refresh_tokens"], audit=False)

        # 2. containermgmt reference tables
        insert_rows("containermgmt.consignee", data["containermgmt.consignee"], audit=True)
        insert_rows("containermgmt.supplier", data["containermgmt.supplier"], audit=True)
        insert_rows("containermgmt.vessals", data["containermgmt.vessals"], audit=True)
        insert_rows("containermgmt.shipping_document", data["containermgmt.shipping_document"], audit=True)
        insert_rows("containermgmt.unload_venue", data["containermgmt.unload_venue"], audit=True)
        insert_rows("containermgmt.logisticsprovider", data["containermgmt.logisticsprovider"], audit=True)
        insert_rows("containermgmt.material", data["containermgmt.material"], audit=True)
        insert_rows("containermgmt.container_type", data["containermgmt.container_type"], audit=True)
        insert_rows("containermgmt.status", data["containermgmt.status"], audit=True)

        # 3. Generate bill_of_landing records
        logger.info("Generating bill_of_landing records from old container details...")
        # Map Container_ID -> BillOfLanding from the dump's container_details table
        c_id_to_bol = {c['Container_ID']: c['BillOfLanding'] for c in data['containermgmt.container_details'] if c.get('BillOfLanding')}
        
        # Group container metadata by BillOfLanding code
        bol_records = {}
        for c02 in data['containermgmt.container_details02']:
            c_id = c02['Container_ID']
            bol_code = c_id_to_bol.get(c_id)
            if bol_code:
                if bol_code not in bol_records:
                    bol_records[bol_code] = {
                        'BillOfLanding': bol_code,
                        'Consignee': c02['consignee'],
                        'Vessel': c02['VessalID'],
                        'ArrivalDate': c02['Arrival_Date'],
                        'Supplier': c02['supplier'],
                        'Provider': None,
                        'Doc': c02['docs'],
                        'FreeDays': None,
                        'status': None
                    }
        
        # Also add any other BillOfLanding keys that exist in container_details but not in container_details02
        for bol_code in set(c_id_to_bol.values()):
            if bol_code not in bol_records:
                bol_records[bol_code] = {
                    'BillOfLanding': bol_code,
                    'Consignee': None,
                    'Vessel': None,
                    'ArrivalDate': None,
                    'Supplier': None,
                    'Provider': None,
                    'Doc': None,
                    'FreeDays': None,
                    'status': None
                }

        insert_rows("containermgmt.bill_of_landing", list(bol_records.values()), audit=False)

        # 4. Map and insert container_details
        logger.info("Mapping and inserting container_details...")
        new_containers = []
        for c02 in data['containermgmt.container_details02']:
            c_id = c02['Container_ID']
            new_containers.append({
                'Container_ID': c_id,
                'container_no': c02['container_no'],
                'in_bound': c02['in_bound'],
                'empty_date': c02['empty_date'],
                'out_bound': c02['out_bound'],
                'unloaded_at_port': c02['unloaded_at_port'],
                'note': c02['note'],
                'tax': c02['tax'],
                'PONo': c02['PONo'],
                'FreeDays': None,
                'BillOfLanding': c_id_to_bol.get(c_id),
                'status': c02['status'],
                'emptied_at': c02['emptied_at'],
                'type': c02['type']
            })
        insert_rows("containermgmt.container_details", new_containers, audit=True)

        # 5. Insert remaining relationship and transaction tables
        insert_rows("containermgmt.packing_list", data["containermgmt.packing_list"], audit=False)
        insert_rows("containermgmt.container_products", data["containermgmt.container_products"], audit=False)
        
        # Map container_id in docs and reports
        insert_rows("containermgmt.container_docs", data["containermgmt.container_docs"], audit=True)
        insert_rows("containermgmt.damageproduct", data["containermgmt.damageproduct"], audit=True)
        insert_rows("containermgmt.report_details", data["containermgmt.report_details"], audit=True)
        insert_rows("containermgmt.report_images", data["containermgmt.report_images"], audit=True)
        
        # Commit transaction
        conn.commit()
    logger.info("All data successfully restored and migrated to the new schema.")

def main():
    logger.info("Starting migration process...")
    
    # 1. Load the raw sql dump
    sql_dump_path = "d:\\WorkPlace\\Seychelles_Sahaj\\Backend\\Dump20260528 (3).sql"
    load_sql_dump(sql_dump_path)
    
    # Create main engine
    engine = create_engine(DATABASE_URL)
    
    # 2. Read all tables from the database
    data = read_all_data(engine)
    
    # 3. Drop and recreate databases
    recreate_clean_databases()
    
    # 4. Create clean tables via SQLAlchemy metadata
    logger.info("Creating clean tables via Base.metadata.create_all...")
    Base.metadata.create_all(bind=engine)
    logger.info("Clean tables created successfully.")
    
    # 5. Restore and normalize data into clean tables
    write_data_back(engine, data)
    
    logger.info("Migration completely finished!")

if __name__ == "__main__":
    main()
