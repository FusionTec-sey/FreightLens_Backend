import os
import sys
import logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations")

def ensure_user_allowed_orgs_schema():
    """
    Idempotent schema migration to add allowed_org_ids (INTEGER[]) to usercredentials.users
    to support multi-tenant organization assignment per user.
    """
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                table_exists = conn.execute(text("""
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'usercredentials' AND table_name = 'users';
                """)).scalar()

                if not table_exists:
                    return

                has_col = conn.execute(text("""
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_schema = 'usercredentials' 
                      AND table_name = 'users' 
                      AND column_name = 'allowed_org_ids';
                """)).scalar()

                if not has_col:
                    logger.info("Adding allowed_org_ids column to usercredentials.users...")
                    conn.execute(text("""
                        ALTER TABLE usercredentials.users 
                        ADD COLUMN IF NOT EXISTS allowed_org_ids INTEGER[] DEFAULT NULL;
                    """))
                    conn.execute(text("""
                        UPDATE usercredentials.users 
                        SET allowed_org_ids = ARRAY[org_id] 
                        WHERE allowed_org_ids IS NULL AND org_id IS NOT NULL;
                    """))
                    conn.commit()
                    logger.info("Successfully added allowed_org_ids to usercredentials.users.")
                else:
                    logger.info("usercredentials.users already has allowed_org_ids column.")
    except Exception as e:
        logger.error("Failed to migrate user allowed_org_ids: %s", e)
        raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_user_allowed_orgs_schema()
