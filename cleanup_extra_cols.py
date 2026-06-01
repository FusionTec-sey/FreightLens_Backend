from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

with engine.connect() as conn:
    print("Dropping extra constraints and columns from user_refresh_tokens...")
    # Drop FK constraints first
    for fk in ["fk_user_refresh_tokens_created_by", "fk_user_refresh_tokens_updated_by", "fk_user_refresh_tokens_deleted_by"]:
        try:
            conn.execute(text(f"ALTER TABLE usercredentials.user_refresh_tokens DROP FOREIGN KEY {fk};"))
            print(f"  Dropped FK constraint: {fk}")
        except Exception as e:
            print(f"  Skip/Error FK {fk}: {e}")
            
    # Drop columns
    for col in ["updated_at", "is_deleted", "deleted_at", "created_by", "updated_by", "deleted_by"]:
        try:
            conn.execute(text(f"ALTER TABLE usercredentials.user_refresh_tokens DROP COLUMN {col};"))
            print(f"  Dropped column: {col}")
        except Exception as e:
            print(f"  Skip/Error column {col}: {e}")

    print("\nDropping extra constraints and columns from session_audit...")
    # Drop FK constraints first
    for fk in ["fk_session_audit_created_by", "fk_session_audit_updated_by", "fk_session_audit_deleted_by"]:
        try:
            conn.execute(text(f"ALTER TABLE usercredentials.session_audit DROP FOREIGN KEY {fk};"))
            print(f"  Dropped FK constraint: {fk}")
        except Exception as e:
            print(f"  Skip/Error FK {fk}: {e}")
            
    # Drop columns
    for col in ["updated_at", "is_deleted", "deleted_at", "created_by", "updated_by", "deleted_by"]:
        try:
            conn.execute(text(f"ALTER TABLE usercredentials.session_audit DROP COLUMN {col};"))
            print(f"  Dropped column: {col}")
        except Exception as e:
            print(f"  Skip/Error column {col}: {e}")
            
    conn.commit()
    print("\nCleanup complete.")
