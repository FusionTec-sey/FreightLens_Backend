"""Point the existing Print & Reports menu entries at the screen that replaced it.

The reporting hub was one page with a segmented toggle: print document templates
on one side, operational registers on the other. The registers half could not be
put in a menu at all, because the menu points at a page key and there was only
one. Splitting the hub into `/reports/documents` and `/reports/registers` retires
the `REPORTS` page key -- and seven menu rows across the tenants point at it.

A page key dropped from the registry is deactivated rather than deleted, and
`/navigation/my-menu` then stops serving the items that reference it. So the
rows have to be repointed, or an admin who arranged their menu months ago loses
the reporting entry with no explanation.

The registers entry is then added beside it, once per menu that does not have
one: the point of the split was that registers could not be reached from the
menu, and leaving every tenant to discover a new page key in the Menu Designer
would have left it exactly as unreachable. An admin can move or remove it like
any other item.

A label is only rewritten when it still reads "Print & Reports" -- the name of
the page that no longer exists. A label somebody chose is theirs.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_report_menu_split")

_REPOINT = """
    UPDATE usercredentials.menu_items
    SET page_key = 'REPORT_DOCUMENT_TEMPLATES'
    WHERE page_key = 'REPORTS'
"""

_RELABEL = """
    UPDATE usercredentials.menu_items
    SET label = 'Print Document Templates'
    WHERE page_key = 'REPORT_DOCUMENT_TEMPLATES'
      AND label IN ('Print & Reports', 'Print and Reports', 'Reporting & Document Hub')
"""

# Make room first, so the new item lands directly under the documents one
# rather than tying with whatever already held that position.
_MAKE_ROOM = """
    UPDATE usercredentials.menu_items m
    SET sort_order = m.sort_order + 1
    FROM (
        SELECT menu_id, parent_id, sort_order
        FROM usercredentials.menu_items
        WHERE page_key = 'REPORT_DOCUMENT_TEMPLATES' AND is_deleted IS NOT TRUE
    ) d
    WHERE m.menu_id = d.menu_id
      AND coalesce(m.parent_id, -1) = coalesce(d.parent_id, -1)
      AND m.sort_order > d.sort_order
      AND m.is_deleted IS NOT TRUE
      AND NOT EXISTS (
          SELECT 1 FROM usercredentials.menu_items r
          WHERE r.menu_id = d.menu_id AND r.page_key = 'REPORT_OPERATIONAL_REGISTERS'
            AND r.is_deleted IS NOT TRUE
      )
"""

_ADD_REGISTERS = """
    INSERT INTO usercredentials.menu_items
        (menu_id, org_id, parent_id, label, icon, page_key, sort_order,
         is_active, show_when_locked, is_separator)
    SELECT d.menu_id, d.org_id, d.parent_id, 'Operational Registers', 'Table',
           'REPORT_OPERATIONAL_REGISTERS', d.sort_order + 1,
           d.is_active, d.show_when_locked, FALSE
    FROM usercredentials.menu_items d
    WHERE d.page_key = 'REPORT_DOCUMENT_TEMPLATES'
      AND d.is_deleted IS NOT TRUE
      AND NOT EXISTS (
          SELECT 1 FROM usercredentials.menu_items r
          WHERE r.menu_id = d.menu_id
            AND r.page_key = 'REPORT_OPERATIONAL_REGISTERS'
            AND r.is_deleted IS NOT TRUE
      )
"""


def ensure_report_menu_split():
    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'usercredentials' AND table_name = 'menu_items'
        """)).first()
        if not exists:
            logger.info("menu_items is not there yet; nothing to repoint.")
            return

        moved = conn.execute(text(_REPOINT)).rowcount
        if moved:
            logger.info(
                "Repointed %s menu item(s) from REPORTS to REPORT_DOCUMENT_TEMPLATES.", moved
            )
        relabelled = conn.execute(text(_RELABEL)).rowcount
        if relabelled:
            logger.info("Renamed %s menu item(s) to Print Document Templates.", relabelled)

        # Only when the new page exists: the menu's page_key is a foreign key
        # into app_pages, which the registry sync fills.
        known = conn.execute(text("""
            SELECT 1 FROM usercredentials.app_pages
            WHERE page_key = 'REPORT_OPERATIONAL_REGISTERS'
        """)).first()
        if known:
            conn.execute(text(_MAKE_ROOM))
            added = conn.execute(text(_ADD_REGISTERS)).rowcount
            if added:
                logger.info("Added the Operational Registers entry to %s menu(s).", added)
        else:
            logger.warning(
                "REPORT_OPERATIONAL_REGISTERS is not in app_pages yet; the menu entry "
                "will be added on the next start, after the registry sync."
            )

        # The editor's own entry asked for View_Report, which let a viewer into
        # the designer to be refused by the server at the end. Nothing to
        # repoint there -- the key is unchanged -- but a menu row that was
        # visible to viewers should stop being so, and the registry's
        # permissions are what decides that on the next sync.
        logger.info("Reporting menu keys are ready.")
