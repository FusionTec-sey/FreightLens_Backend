"""Put Proforma Invoices in the menus that already carry procurement.

A menu is data an administrator arranges, so a new screen does not appear in it
by itself. Without this the page exists, is routed and is in the page registry,
but nobody can reach it from the sidebar.

It is added directly after Vendor Quotes & Bidding, in every menu that has
that entry, under the same folder (or at the top level for a flat menu). Menu
visibility is already filtered by the permissions on each page, so a user
without the proforma permissions does not see it even in a menu that lists it.

Idempotent: a menu that already has a page is left alone, and nothing is moved
or removed. Must run after sync_page_registry, because menu_items.page_key is a
foreign key into app_pages.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_proforma_menu_pages")

# (page_key, label, icon), in the order they are placed after the anchor.
NEW_PAGES = (
    ("PROFORMAS", "Proforma Invoices", "ReceiptText"),
)
ANCHOR = "ORDER_QUOTES"


def ensure_proforma_menu_pages():
    added = 0
    with engine.begin() as conn:
        registered = {r[0] for r in conn.execute(text(
            "SELECT page_key FROM usercredentials.app_pages WHERE page_key = ANY(:keys)"
        ), {"keys": [k for k, _, _ in NEW_PAGES]})}
        pages = [p for p in NEW_PAGES if p[0] in registered]
        if not pages:
            return

        anchors = conn.execute(text("""
            SELECT id, menu_id, org_id, parent_id, sort_order
            FROM usercredentials.menu_items
            WHERE page_key = :anchor AND is_deleted = FALSE
        """), {"anchor": ANCHOR}).fetchall()

        for anchor in anchors:
            position = anchor.sort_order
            for key, label, icon in pages:
                present = conn.execute(text("""
                    SELECT 1 FROM usercredentials.menu_items
                    WHERE menu_id = :m AND page_key = :k AND is_deleted = FALSE
                """), {"m": anchor.menu_id, "k": key}).first()
                if present:
                    continue
                # Make room: later siblings in the same folder move down one.
                conn.execute(text("""
                    UPDATE usercredentials.menu_items
                    SET sort_order = sort_order + 1
                    WHERE menu_id = :m AND is_deleted = FALSE
                      AND parent_id IS NOT DISTINCT FROM :p
                      AND sort_order > :pos
                """), {"m": anchor.menu_id, "p": anchor.parent_id, "pos": position})
                position += 1
                conn.execute(text("""
                    INSERT INTO usercredentials.menu_items
                        (org_id, menu_id, parent_id, label, icon, page_key, sort_order,
                         is_active, is_separator, show_when_locked)
                    VALUES (:org, :m, :p, :label, :icon, :k, :pos, TRUE, FALSE, FALSE)
                """), {"org": anchor.org_id, "m": anchor.menu_id, "p": anchor.parent_id,
                       "label": label, "icon": icon, "k": key, "pos": position})
                added += 1
    if added:
        logger.info("Added %s procurement page(s) to existing menus.", added)
