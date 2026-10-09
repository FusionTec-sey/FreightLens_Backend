"""Seeding helpers for named navigation menus.

An organisation with no published menu is still usable: `/navigation/my-menu`
derives a menu from the page registry. Seeding gives admins a concrete layout to
edit from day one and starts the `updated_by` audit trail.

The trade-off is deliberate: a saved menu is a snapshot, so screens shipped later
do not appear in it automatically. The designer's "pages not in this menu" panel
is what surfaces them.
"""
import logging
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from Model.Credentials.menu import Menu
from Model.Credentials.menu_roles import menu_roles
from Model.Credentials.roles import Role
from Model.Credentials.menu_item import MenuItem
from auth.policy.page_registry import PAGE_GROUPS, PAGE_REGISTRY

logger = logging.getLogger("containerMgmt.navigation")

DEFAULT_MENU_NAME = "Main menu"
DEFAULT_MENU_DESCRIPTION = "Created from the pages this release ships with."


def seed_menu_items(db: Session, menu: Menu, *, user_id: Optional[int] = None) -> int:
    """Fill an empty menu with the registry-derived layout.

    The caller owns the transaction. Returns the number of rows created, and
    does nothing when the menu already holds rows.
    """
    already = (
        db.query(MenuItem.id)
        .filter(MenuItem.menu_id == menu.id, MenuItem.is_deleted.is_(False))
        .first()
    )
    if already is not None:
        return 0

    created = 0
    order = 0

    # A heading followed by its pages at the top level, which is how the sidebar
    # draws a section. Headings are ordinary items, so an admin can move or
    # delete any of them.
    for group in PAGE_GROUPS:
        pages = [page for page in PAGE_REGISTRY if page.group_key == group.group_key]
        if not pages:
            continue
        db.add(
            MenuItem(
                menu_id=menu.id,
                org_id=menu.org_id,
                parent_id=None,
                label=group.label,
                icon=None,
                page_key=None,
                is_separator=True,
                sort_order=order,
                is_active=True,
                show_when_locked=False,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        order += 1
        created += 1

        for page in pages:
            db.add(
                MenuItem(
                    menu_id=menu.id,
                    org_id=menu.org_id,
                    parent_id=None,
                    label=page.title,
                    icon=page.default_icon,
                    page_key=page.page_key,
                    is_separator=False,
                    sort_order=order,
                    is_active=True,
                    show_when_locked=False,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            order += 1
            created += 1

    db.flush()
    return created


def org_has_menu(db: Session, org_id: int) -> bool:
    return (
        db.query(Menu.id)
        .filter(Menu.org_id == org_id, Menu.is_deleted.is_(False))
        .first()
        is not None
    )


def seed_default_menu(
    db: Session,
    org_id: int,
    *,
    user_id: Optional[int] = None,
    commit: bool = False,
    include_shared_roles: bool = False,
) -> int:
    """Create the starter menu for an organisation that has none.

    Assigned to every role the organisation already has. The root starter menu
    also takes unassigned shared roles, since existing installations have only
    shared roles and would otherwise show every user an empty sidebar.
    Roles created later are unassigned until an admin says otherwise.

    No-op when the organisation already has a menu, so this is safe to call on
    every startup and from an org-creation path that may be retried.
    Returns the number of menu item rows created.
    """
    if org_has_menu(db, org_id):
        return 0

    menu = Menu(
        org_id=org_id,
        name=DEFAULT_MENU_NAME,
        description=DEFAULT_MENU_DESCRIPTION,
        is_shared=include_shared_roles,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(menu)
    db.flush()

    role_scope = (
        or_(Role.org_id == org_id, Role.org_id.is_(None))
        if include_shared_roles else Role.org_id == org_id
    )
    org_role_ids = [
        row[0]
        for row in db.query(Role.id)
        .filter(Role.is_deleted.is_(False), role_scope)
        .all()
    ]
    for role_id in org_role_ids:
        already = db.execute(
            menu_roles.select().where(menu_roles.c.role_id == role_id)
        ).first()
        if already is None:
            db.execute(menu_roles.insert().values(role_id=role_id, menu_id=menu.id))

    created = seed_menu_items(db, menu, user_id=user_id)
    if commit:
        db.commit()

    logger.info(
        "Seeded default menu id=%s for org_id=%s rows=%s", menu.id, org_id, created
    )
    return created


def seed_root_organisation_menu() -> int:
    """Startup hook: give the root organisation a menu it can edit.

    Other existing organisations are left on the derived default until an admin
    saves one, so an upgrade never silently freezes their navigation.
    """
    from Model.Credentials.Organisation import Organisation
    from Model.db import SessionLocal

    db = SessionLocal()
    try:
        root = db.query(Organisation).filter(Organisation.id == 1).first()
        if root is None:
            return 0
        return seed_default_menu(db, root.id, commit=True, include_shared_roles=True)
    except Exception:
        db.rollback()
        logger.exception("Could not seed the root organisation menu")
        return 0
    finally:
        db.close()
