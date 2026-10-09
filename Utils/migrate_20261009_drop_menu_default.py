"""Remove the default-menu concept: menus are served by role assignment only.

A menu with no roles assigned reaches nobody, so the `is_published` flag and the
one-published-per-organisation index it needed are gone. Idempotent.
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
            ALTER TABLE usercredentials.menus DROP COLUMN IF EXISTS is_published
        """))
    logger.info("usercredentials.menus default-menu flag removed.")


if __name__ == "__main__":
    ensure_menu_default_removed()
