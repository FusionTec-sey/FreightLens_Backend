"""Assign a menu to roles, so different jobs get different navigation.

A role may be served by at most one menu: role_id is the primary key, so a menu
can never half-claim a role and leave the choice ambiguous. Idempotent.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_menu_roles")


def ensure_menu_roles_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usercredentials.menu_roles (
                role_id INTEGER PRIMARY KEY
                        REFERENCES usercredentials.roles(id) ON DELETE CASCADE,
                menu_id INTEGER NOT NULL
                        REFERENCES usercredentials.menus(id) ON DELETE CASCADE
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_menu_roles_menu_id
            ON usercredentials.menu_roles(menu_id)
        """))
    logger.info("usercredentials.menu_roles verified.")


if __name__ == "__main__":
    ensure_menu_roles_schema()
