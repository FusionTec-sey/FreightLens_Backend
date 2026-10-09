"""Remove the default-menu concept: menus are served by role assignment only.

A menu with no roles assigned reaches nobody. Remove the uniqueness indexes so
several menus can coexist, but retain any old `is_published` column and its values
as historical data. Give that old column a default so new menu inserts still work
when an earlier deployment created it as NOT NULL. New installs do not create it.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_drop_menu_default")


def ensure_menu_default_removed():
    with engine.begin() as conn:
        conn.execute(text("""
            DROP INDEX IF EXISTS usercredentials.uq_menus_one_published_per_org
        """))
        conn.execute(text("""
            DROP INDEX IF EXISTS usercredentials.ix_menus_org_id_published
        """))
        conn.execute(text("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'usercredentials'
                      AND table_name = 'menus'
                      AND column_name = 'is_published'
                ) THEN
                    ALTER TABLE usercredentials.menus
                    ALTER COLUMN is_published SET DEFAULT FALSE;
                END IF;
            END $$;
        """))
    logger.info("usercredentials.menus default-menu indexes removed.")


if __name__ == "__main__":
    ensure_menu_default_removed()
