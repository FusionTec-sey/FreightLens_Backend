"""Menus shared across companies, and explicit section separators.

* `menus.is_shared` lets one menu serve a role in every company, the way a role
  with no org_id is itself shared. Without it a shared role has to be given a
  near-identical menu in each company.
* `menu_items.is_separator` makes the section heading an item an admin adds where
  they want one, instead of it being implied by an item's position in the tree.

Idempotent: safe on every startup.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_shared_menus")


def ensure_shared_menus_and_separators():
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE usercredentials.menus
            ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_menus_is_shared
            ON usercredentials.menus(is_shared)
        """))
        conn.execute(text("""
            ALTER TABLE usercredentials.menu_items
            ADD COLUMN IF NOT EXISTS is_separator BOOLEAN NOT NULL DEFAULT FALSE
        """))
    logger.info("usercredentials menus.is_shared and menu_items.is_separator verified.")


if __name__ == "__main__":
    ensure_shared_menus_and_separators()
