"""Page registry and tenant menu tables for the Menu Designer.

Creates ``usercredentials.app_pages`` (developer-owned route registry) and
``usercredentials.menu_items`` (tenant-owned navigation). Idempotent: safe to run
on every startup. Registry rows themselves are seeded separately by
``auth.policy.page_registry.sync_page_registry`` during database seeding, because
that needs the permission catalog to be in place first.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_menu_registry")


def ensure_menu_registry_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usercredentials.app_pages (
                page_key         VARCHAR(60)  PRIMARY KEY,
                route            VARCHAR(200) NOT NULL UNIQUE,
                title            VARCHAR(100) NOT NULL,
                default_icon     VARCHAR(50),
                group_key        VARCHAR(60),
                permission_codes VARCHAR[]    NOT NULL DEFAULT '{}',
                module_codes     VARCHAR[]    NOT NULL DEFAULT '{}',
                sort_order       INTEGER      NOT NULL DEFAULT 0,
                is_active        BOOLEAN      NOT NULL DEFAULT TRUE
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usercredentials.menu_items (
                id               SERIAL       PRIMARY KEY,
                org_id           INTEGER      NOT NULL
                                 REFERENCES usercredentials.organisations(id),
                parent_id        INTEGER
                                 REFERENCES usercredentials.menu_items(id) ON DELETE CASCADE,
                label            VARCHAR(100) NOT NULL,
                icon             VARCHAR(50),
                page_key         VARCHAR(60)
                                 REFERENCES usercredentials.app_pages(page_key),
                sort_order       INTEGER      NOT NULL DEFAULT 0,
                is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
                show_when_locked BOOLEAN      NOT NULL DEFAULT FALSE,
                created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                is_deleted       BOOLEAN      NOT NULL DEFAULT FALSE,
                deleted_at       TIMESTAMPTZ,
                created_by       INTEGER      REFERENCES usercredentials.users(id),
                updated_by       INTEGER      REFERENCES usercredentials.users(id),
                deleted_by       INTEGER      REFERENCES usercredentials.users(id)
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_menu_items_org_id
            ON usercredentials.menu_items(org_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_menu_items_parent_id
            ON usercredentials.menu_items(parent_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_menu_items_page_key
            ON usercredentials.menu_items(page_key)
        """))

    logger.info("usercredentials.app_pages and usercredentials.menu_items verified.")


if __name__ == "__main__":
    ensure_menu_registry_schema()
