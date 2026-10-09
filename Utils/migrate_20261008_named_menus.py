"""Named menu layouts: one organisation may keep several.

Creates `usercredentials.menus`, attaches `menu_items.menu_id`, and adopts any
rows written before this change into a "Main menu" per organisation, so no
existing navigation is lost. Idempotent: safe on every startup.

Menus are served by role assignment (see migrate_20261008_menu_roles). Any
historical default-menu flag is retained for audit but no longer controls serving.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_named_menus")


def ensure_named_menus_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usercredentials.menus (
                id           SERIAL       PRIMARY KEY,
                org_id       INTEGER      NOT NULL
                             REFERENCES usercredentials.organisations(id),
                name         VARCHAR(100) NOT NULL,
                description  VARCHAR(255),
                created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                is_deleted   BOOLEAN      NOT NULL DEFAULT FALSE,
                deleted_at   TIMESTAMPTZ,
                created_by   INTEGER      REFERENCES usercredentials.users(id),
                updated_by   INTEGER      REFERENCES usercredentials.users(id),
                deleted_by   INTEGER      REFERENCES usercredentials.users(id)
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_menus_org_id
            ON usercredentials.menus(org_id)
        """))
        conn.execute(text("""
            ALTER TABLE usercredentials.menu_items
            ADD COLUMN IF NOT EXISTS menu_id INTEGER
        """))

        # Adopt all pre-existing items, including soft-deleted audit rows.
        # Runs once; later restarts find nothing to adopt.
        orphan_orgs = [
            row[0]
            for row in conn.execute(text("""
                SELECT DISTINCT org_id
                FROM usercredentials.menu_items
                WHERE menu_id IS NULL
            """)).fetchall()
        ]
        for org_id in orphan_orgs:
            menu_id = conn.execute(
                text("""
                    SELECT id FROM usercredentials.menus
                    WHERE org_id = :org_id AND NOT is_deleted
                    ORDER BY id LIMIT 1
                """),
                {"org_id": org_id},
            ).scalar()
            if menu_id is None:
                menu_id = conn.execute(
                    text("""
                        INSERT INTO usercredentials.menus
                            (org_id, name, description)
                        VALUES (:org_id, 'Main menu',
                                'Adopted from the navigation saved before menus were named.')
                        RETURNING id
                    """),
                    {"org_id": org_id},
                ).scalar()
            conn.execute(
                text("""
                    UPDATE usercredentials.menu_items
                    SET menu_id = :menu_id
                    WHERE org_id = :org_id AND menu_id IS NULL
                """),
                {"menu_id": menu_id, "org_id": org_id},
            )
            logger.info("Adopted menu items for org_id=%s into menu_id=%s", org_id, menu_id)

        conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE usercredentials.menu_items
                ADD CONSTRAINT fk_menu_items_menu
                FOREIGN KEY (menu_id) REFERENCES usercredentials.menus(id)
                ON DELETE CASCADE;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """))

        still_orphaned = conn.execute(text("""
            SELECT count(*) FROM usercredentials.menu_items WHERE menu_id IS NULL
        """)).scalar()
        if not still_orphaned:
            conn.execute(text("""
                ALTER TABLE usercredentials.menu_items
                ALTER COLUMN menu_id SET NOT NULL
            """))
        else:
            logger.warning(
                "menu_items.menu_id left nullable: %s rows could not be adopted",
                still_orphaned,
            )

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_menu_items_menu_id
            ON usercredentials.menu_items(menu_id)
        """))

    logger.info("usercredentials.menus and menu_items.menu_id verified.")


if __name__ == "__main__":
    ensure_named_menus_schema()
