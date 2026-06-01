import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import inspect, text
from Model.db import engine, Base

# Import all models to register them on Base.metadata
from Model.containermgmt import *
from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.Credentials.SessionAudit import SessionAudit
from Model.containermgmt.AuditLog import AuditLog
from Model.Credentials.refresh_tokens import RefreshToken

def map_sa_type_to_mysql(col):
    # Returns a simplified MySQL data type representation for basic comparison
    from sqlalchemy.dialects.mysql import VARCHAR, INTEGER, DATETIME, DATE, TINYINT, SMALLINT, TEXT
    
    t = col.type
    if hasattr(t, "impl"):
        t = t.impl
        
    type_name = str(t).lower()
    
    if "varchar" in type_name:
        return "varchar"
    if "integer" in type_name or "int" in type_name:
        if "smallint" in type_name:
            return "smallint"
        if "tinyint" in type_name:
            return "tinyint"
        return "int"
    if "datetime" in type_name:
        return "datetime"
    if "date" in type_name:
        return "date"
    if "tinyint" in type_name or "boolean" in type_name:
        return "tinyint"
    if "text" in type_name:
        return "text"
    return type_name

def compare_schema():
    print("Connecting to database...", flush=True)
    inspector = inspect(engine)
    
    model_tables = Base.metadata.tables
    print(f"Loaded {len(model_tables)} tables from SQLAlchemy models.", flush=True)
    
    # Cache table names by schema
    schema_tables = {}
    
    diffs = []
    
    for idx, (table_full_name, model_table) in enumerate(model_tables.items(), 1):
        parts = table_full_name.split(".")
        schema_name = parts[0] if len(parts) > 1 else None
        table_name = parts[-1]
        
        print(f"[{idx}/{len(model_tables)}] Inspecting table '{table_full_name}'...", flush=True)
        
        if schema_name not in schema_tables:
            print(f"  Fetching table list for schema '{schema_name}'...", flush=True)
            schema_tables[schema_name] = inspector.get_table_names(schema=schema_name)
            
        db_tables = schema_tables[schema_name]
        
        if table_name not in db_tables:
            diffs.append({
                "type": "missing_table",
                "table": table_full_name,
                "message": f"Table '{table_full_name}' is missing in the database."
            })
            continue
            
        # Get columns in DB
        db_cols = {c["name"]: c for c in inspector.get_columns(table_name, schema=schema_name)}
        
        # Check for missing/modified columns
        for col_name, model_col in model_table.columns.items():
            if col_name not in db_cols:
                diffs.append({
                    "type": "missing_column",
                    "table": table_full_name,
                    "column": col_name,
                    "model_col": model_col,
                    "message": f"Column '{col_name}' is missing in database table '{table_full_name}'."
                })
            else:
                db_col = db_cols[col_name]
                model_type_simp = map_sa_type_to_mysql(model_col)
                db_type_simp = str(db_col["type"]).lower()
                
                type_mismatch = False
                if "varchar" in model_type_simp and "varchar" not in db_type_simp:
                    type_mismatch = True
                elif "int" in model_type_simp and "int" not in db_type_simp:
                    if "tinyint" in model_type_simp and "tiny" not in db_type_simp:
                        type_mismatch = True
                    elif "smallint" in model_type_simp and "small" not in db_type_simp:
                        type_mismatch = True
                    elif "smallint" not in model_type_simp and "tinyint" not in model_type_simp and ("tiny" in db_type_simp or "small" in db_type_simp):
                        type_mismatch = True
                elif "datetime" in model_type_simp and "datetime" not in db_type_simp and "timestamp" not in db_type_simp:
                    type_mismatch = True
                elif "date" in model_type_simp and "date" not in db_type_simp:
                    type_mismatch = True
                elif "text" in model_type_simp and "text" not in db_type_simp:
                    type_mismatch = True
                
                length_mismatch = False
                if not type_mismatch and "varchar" in model_type_simp:
                    model_len = getattr(model_col.type, "length", None)
                    db_len = getattr(db_col["type"], "length", None)
                    if model_len and db_len and model_len != db_len:
                        length_mismatch = True
                
                db_nullable = db_col["nullable"]
                model_nullable = model_col.nullable
                nullable_mismatch = False
                if model_nullable != db_nullable:
                    nullable_mismatch = True
                
                if type_mismatch or length_mismatch or nullable_mismatch:
                    reasons = []
                    if type_mismatch:
                        reasons.append(f"type: model={model_col.type} vs db={db_col['type']}")
                    if length_mismatch:
                        reasons.append(f"length: model={model_col.type.length} vs db={db_col['type'].length}")
                    if nullable_mismatch:
                        reasons.append(f"nullable: model={model_col.nullable} vs db={db_col['nullable']}")
                        
                    diffs.append({
                        "type": "modified_column",
                        "table": table_full_name,
                        "column": col_name,
                        "model_col": model_col,
                        "db_col": db_col,
                        "reasons": reasons,
                        "message": f"Column '{col_name}' on table '{table_full_name}' differs: {', '.join(reasons)}"
                    })
                    
        for col_name in db_cols:
            if col_name not in model_table.columns:
                diffs.append({
                    "type": "extra_column",
                    "table": table_full_name,
                    "column": col_name,
                    "db_col": db_cols[col_name],
                    "message": f"Column '{col_name}' exists in database table '{table_full_name}' but is not in ORM model."
                })

    print(f"\nFound {len(diffs)} differences:", flush=True)
    for d in diffs:
        print(f"[{d['type'].upper()}] {d['message']}", flush=True)
        
if __name__ == "__main__":
    compare_schema()
