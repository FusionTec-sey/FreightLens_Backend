"""Navigation endpoints: the user's filtered menu, and the admin menu designer.

Cross-module router: navigation spans every module, so it carries no
``require_module`` guard. Every endpoint is authenticated and authorized on its
own, as required for the documented cross-module exceptions.

The menu decides what a user *sees*. It is never a security boundary: the React
route guard and each endpoint's own permission check remain the real locks.
"""
import logging
from typing import Dict, List, Optional

from fastapi import Depends, HTTPException, status
from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from Model.Credentials.Organisation import Organisation
from Model.Credentials.app_page import AppPage
from Model.Credentials.menu import Menu
from Model.Credentials.menu_roles import menu_roles
from Model.Credentials.menu_item import MenuItem
from Model.Credentials.roles import Role
from Model.Credentials.user_org_roles import user_org_roles
from Model.Credentials.users import User
from Model.db import get_db
from Schema.Credentials.menu import (
    AppPageOut,
    MenuCreateIn,
    MenuDetailOut,
    MenuItemOut,
    MenuNodeOut,
    MenuSaveRequest,
    MenuSummaryOut,
    MenuUpdateIn,
    MyMenuResponse,
    OrgMenuSummaryOut,
    PageGroupOut,
    PageRegistryResponse,
    RoleVisibilityOut,
)
from Utils.org_filter import OrgContext
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from Services.navigation_service import seed_menu_items
from auth.policy.catalog import PLATFORM_PERMISSION_NAMES
from auth.policy.page_registry import (
    PAGE_BY_KEY,
    PAGE_GROUPS,
    allowed_pages,
    policy_allows_page,
)

logger = logging.getLogger("containerMgmt.navigation")

MenuRouter = InferringRouter()

MAX_MENU_DEPTH = 3
MAX_MENU_ITEMS = 300


def _node_from_page(page_key: str, label: str, icon: Optional[str], locked: bool,
                    item_id: Optional[int] = None) -> MenuNodeOut:
    page = PAGE_BY_KEY[page_key]
    return MenuNodeOut(
        id=item_id,
        page_key=page_key,
        label=label,
        icon=icon or page.default_icon,
        route=page.route,
        permission_codes=list(page.permission_codes),
        module_codes=list(page.module_codes),
        locked=locked,
    )


def _prune(nodes: List[MenuNodeOut]) -> List[MenuNodeOut]:
    """Drop folders that ended up with no visible children."""
    kept: List[MenuNodeOut] = []
    for node in nodes:
        node.children = _prune(node.children)
        if node.is_separator or node.route or node.children:
            kept.append(node)
    return kept


def _drop_empty_separators(nodes: List[MenuNodeOut]) -> List[MenuNodeOut]:
    """Remove a heading with nothing left under it.

    Permission filtering can empty out a whole section; leaving its heading
    behind would advertise a group the viewer has no items in.
    """
    kept: List[MenuNodeOut] = []
    seen_item_since_separator = False
    # Walk backwards: a heading survives only if something followed it before the
    # next heading began.
    for node in reversed(nodes):
        if node.is_separator:
            if seen_item_since_separator:
                kept.append(node)
            seen_item_since_separator = False
        else:
            kept.append(node)
            seen_item_since_separator = True
    kept.reverse()
    return kept


def _stored_menu(rows: List[MenuItem], policy: AccessPolicy) -> List[MenuNodeOut]:
    """Build the tree an admin arranged, filtered for this user."""
    nodes: Dict[int, MenuNodeOut] = {}
    order: List[MenuItem] = []

    for row in rows:
        if row.page_key:
            page = PAGE_BY_KEY.get(row.page_key)
            # Orphan: the page was retired from the registry. Never show it.
            if page is None:
                continue
            allowed = policy_allows_page(policy, page)
            if not allowed and not row.show_when_locked:
                continue
            nodes[row.id] = _node_from_page(
                row.page_key, row.label, row.icon, locked=not allowed, item_id=row.id
            )
        else:
            nodes[row.id] = MenuNodeOut(
                id=row.id,
                label=row.label,
                icon=row.icon,
                is_separator=bool(row.is_separator),
            )
        order.append(row)

    roots: List[MenuNodeOut] = []
    for row in order:
        node = nodes[row.id]
        parent = nodes.get(row.parent_id) if row.parent_id else None
        if row.parent_id and parent is None:
            # Parent was filtered out or is inactive: do not promote a child
            # into the root level, that would leak a hidden grouping.
            continue
        if parent is not None:
            parent.children.append(node)
        else:
            roots.append(node)

    return _drop_empty_separators(_prune(roots))


# Pages that must stay reachable from the sidebar, in registry order. Without
# this, an admin who saves a menu that omits the designer loses the only way
# back into it and can reach the screen solely by typing its URL.
_ALWAYS_REACHABLE = ("MENU_DESIGNER",)


def _contains_page(nodes: List[MenuNodeOut], page_key: str) -> bool:
    return any(
        node.page_key == page_key or _contains_page(node.children, page_key)
        for node in nodes
    )


def _resolve_menu_for_user(db: Session, org_id: int, user_id: int) -> Optional[Menu]:
    """Which menu this user is served.

    Only a menu assigned to one of the user's roles in this organisation, from
    the menus this company may use: its own, plus any shared across companies. A
    role belongs to at most one menu, but a user may hold several roles, so ties
    break on the lowest menu id: deterministic, so the same user always gets the
    same navigation.

    Returns None when no role of theirs has a menu. There is no organisation-wide
    default, so that means no sidebar.
    """
    role_ids = [
        row[0]
        for row in db.query(user_org_roles.c.role_id)
        .filter(
            user_org_roles.c.user_id == user_id,
            user_org_roles.c.org_id == org_id,
        )
        .all()
    ]

    if role_ids:
        assigned = (
            db.query(Menu)
            .join(menu_roles, menu_roles.c.menu_id == Menu.id)
            .filter(
                menu_roles.c.role_id.in_(role_ids),
                _menu_scope(org_id),
                Menu.is_deleted.is_(False),
            )
            .order_by(Menu.id)
            .first()
        )
        if assigned is not None:
            return assigned

    return None


def _org_label(db: Session, org_id: int) -> Optional[str]:
    org = db.query(Organisation).filter(Organisation.id == org_id).first()
    return (org.display_name or org.name) if org else None


def _assigned_role_ids(db: Session, menu_id: int) -> List[int]:
    return [
        row[0]
        for row in db.query(menu_roles.c.role_id)
        .filter(menu_roles.c.menu_id == menu_id)
        .all()
    ]


def _menu_scope(org_id: int):
    """Menus this company may use: its own, plus any shared across companies."""
    return or_(Menu.is_shared.is_(True), Menu.org_id == org_id)


def _load_menu(db: Session, menu_id: int, org_context: OrgContext) -> Menu:
    """Fetch a menu belonging to the active organisation, or 404.

    Scoping the lookup by org_id rather than checking afterwards means a menu id
    from another tenant is indistinguishable from one that does not exist.
    """
    menu = (
        db.query(Menu)
        .filter(
            Menu.id == menu_id,
            _menu_scope(org_context.org_id),
            Menu.is_deleted.is_(False),
        )
        .first()
    )
    if menu is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found."
        )
    return menu


def _with_escape_hatches(menu: List[MenuNodeOut], policy: AccessPolicy) -> List[MenuNodeOut]:
    """Append any self-administration page the saved menu left out."""
    for page_key in _ALWAYS_REACHABLE:
        page = PAGE_BY_KEY.get(page_key)
        if page is None or _contains_page(menu, page_key):
            continue
        if not policy_allows_page(policy, page):
            continue
        menu = [*menu, _node_from_page(page_key, page.title, page.default_icon, locked=False)]
    return menu


@cbv(MenuRouter)
class NavigationAPI:
    # ── User-facing ───────────────────────────────────────────────────────────

    @MenuRouter.get("/navigation/my-menu", response_model=MyMenuResponse)
    async def my_menu(
        self,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
    ):
        """The signed-in user's navigation tree for the active organisation.

        Served from the menu assigned to one of the user's roles, and from
        nothing else. A role with no menu -- or a user with no role -- gets no
        sidebar, in any organisation, including one where no menu has been
        designed yet. Whoever may manage menus keeps a link to that screen, so
        an empty navigation is always recoverable.
        """
        served = _resolve_menu_for_user(db, org_context.org_id, policy.user.id)
        rows = (
            db.query(MenuItem)
            .filter(
                MenuItem.menu_id == served.id,
                MenuItem.is_deleted.is_(False),
                MenuItem.is_active.is_(True),
            )
            .order_by(MenuItem.sort_order, MenuItem.id)
            .all()
            if served
            else []
        )

        # _with_escape_hatches keeps the designer reachable even from an empty
        # menu, so nobody who can fix navigation is locked out by it.
        menu = _with_escape_hatches(_stored_menu(rows, policy) if rows else [], policy)

        return MyMenuResponse(
            menu=menu,
            permissions=sorted(policy.permission_names),
            modules=sorted(policy.module_names),
            is_default=False,
        )

    # ── Menu designer ─────────────────────────────────────────────────────────

    @MenuRouter.get("/navigation/pages", response_model=PageRegistryResponse)
    async def list_pages(
        self,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
    ):
        """Page registry: what the designer offers instead of free-typed URLs.

        Groups come with it so the designer can seed a draft that matches the
        default menu ``/my-menu`` serves before any admin arranges one.
        """
        policy.require_any("View_Menu", "Manage_Menu")
        pages = (
            db.query(AppPage)
            .filter(AppPage.is_active.is_(True))
            .order_by(AppPage.group_key, AppPage.sort_order, AppPage.title)
            .all()
        )
        return PageRegistryResponse(
            pages=[AppPageOut.model_validate(page) for page in pages],
            max_menu_depth=MAX_MENU_DEPTH,
            max_menu_items=MAX_MENU_ITEMS,
            groups=[
                PageGroupOut(
                    group_key=group.group_key,
                    label=group.label,
                    icon=group.icon,
                    sort_order=group.sort_order,
                )
                for group in PAGE_GROUPS
            ],
        )

    # -- Menus: the list the designer opens on --------------------------------

    @MenuRouter.get("/navigation/menus", response_model=List[MenuSummaryOut])
    async def list_menus(
        self,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
    ):
        """Every menu this organisation has designed."""
        policy.require_any("View_Menu", "Manage_Menu")
        menus = (
            db.query(Menu)
            .filter(_menu_scope(org_context.org_id), Menu.is_deleted.is_(False))
            .order_by(Menu.name)
            .all()
        )
        if not menus:
            return []

        active_page_count = (
            db.query(func.count(AppPage.page_key))
            .filter(AppPage.is_active.is_(True))
            .scalar()
            or 0
        )
        menu_ids = [menu.id for menu in menus]

        # One grouped query for counts rather than two per menu.
        counts = {
            row.menu_id: row
            for row in (
                db.query(
                    MenuItem.menu_id.label("menu_id"),
                    func.count(MenuItem.id).label("item_count"),
                    func.count(func.distinct(MenuItem.page_key)).label("page_count"),
                )
                .filter(
                    MenuItem.menu_id.in_(menu_ids),
                    MenuItem.is_deleted.is_(False),
                )
                .group_by(MenuItem.menu_id)
                .all()
            )
        }
        editors = {
            row[0]: row[1]
            for row in (
                db.query(Menu.id, User.username)
                .join(User, User.id == Menu.updated_by)
                .filter(Menu.id.in_(menu_ids))
                .all()
            )
        }
        roles_by_menu: Dict[int, List[tuple]] = {}
        for menu_id, role_id, role_name in (
            db.query(menu_roles.c.menu_id, Role.id, Role.name)
            .join(Role, Role.id == menu_roles.c.role_id)
            .filter(menu_roles.c.menu_id.in_(menu_ids), Role.is_deleted.is_(False))
            .order_by(Role.name)
            .all()
        ):
            roles_by_menu.setdefault(menu_id, []).append((role_id, role_name))

        org_label = _org_label(db, org_context.org_id)
        summaries = []
        for menu in menus:
            row = counts.get(menu.id)
            page_count = int(row.page_count) if row else 0
            assigned = roles_by_menu.get(menu.id, [])
            summaries.append(
                MenuSummaryOut(
                    id=menu.id,
                    org_id=menu.org_id,
                    org_name=org_label if not menu.is_shared else None,
                    is_shared=bool(menu.is_shared),
                    name=menu.name,
                    description=menu.description,
                    item_count=int(row.item_count) if row else 0,
                    page_count=page_count,
                    unmapped_page_count=max(active_page_count - page_count, 0),
                    role_ids=[role_id for role_id, _ in assigned],
                    role_names=[role_name for _, role_name in assigned],
                    updated_at=menu.updated_at.isoformat() if menu.updated_at else None,
                    updated_by=editors.get(menu.id),
                )
            )
        return summaries

    @MenuRouter.post("/navigation/menus", response_model=MenuDetailOut)
    async def create_menu(
        self,
        payload: MenuCreateIn,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        current_user=Depends(get_current_user),
    ):
        """Start a new menu, by default seeded from the page registry.

        It reaches nobody until roles are assigned to it.
        """
        policy.require_any("Manage_Menu")
        org_id = org_context.org_id

        menu = Menu(
            org_id=org_id,
            name=payload.name,
            description=payload.description,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(menu)
        db.flush()

        if payload.seed_from_default:
            seed_menu_items(db, menu, user_id=current_user.id)
        db.commit()
        db.refresh(menu)

        items = (
            db.query(MenuItem)
            .filter(MenuItem.menu_id == menu.id, MenuItem.is_deleted.is_(False))
            .order_by(MenuItem.sort_order, MenuItem.id)
            .all()
        )
        logger.info(
            "Menu created id=%s org_id=%s by user_id=%s items=%s",
            menu.id, org_id, current_user.id, len(items),
        )
        return MenuDetailOut(
            id=menu.id,
            org_id=menu.org_id,
            org_name=None if menu.is_shared else _org_label(db, menu.org_id),
            is_shared=bool(menu.is_shared),
            name=menu.name,
            description=menu.description,
            role_ids=_assigned_role_ids(db, menu.id),
            items=[MenuItemOut.model_validate(item) for item in items],
        )

    @MenuRouter.get("/navigation/menus/{menu_id}", response_model=MenuDetailOut)
    async def get_menu(
        self,
        menu_id: int,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
    ):
        """One menu with its rows, unfiltered, for editing."""
        policy.require_any("View_Menu", "Manage_Menu")
        menu = _load_menu(db, menu_id, org_context)
        items = (
            db.query(MenuItem)
            .filter(MenuItem.menu_id == menu.id, MenuItem.is_deleted.is_(False))
            .order_by(MenuItem.parent_id.nullsfirst(), MenuItem.sort_order, MenuItem.id)
            .all()
        )
        return MenuDetailOut(
            id=menu.id,
            org_id=menu.org_id,
            org_name=None if menu.is_shared else _org_label(db, menu.org_id),
            is_shared=bool(menu.is_shared),
            name=menu.name,
            description=menu.description,
            role_ids=_assigned_role_ids(db, menu.id),
            items=[MenuItemOut.model_validate(item) for item in items],
        )

    @MenuRouter.patch("/navigation/menus/{menu_id}", response_model=MenuSummaryOut)
    async def update_menu(
        self,
        menu_id: int,
        payload: MenuUpdateIn,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        current_user=Depends(get_current_user),
    ):
        """Rename a menu, or set which roles it serves."""
        policy.require_any("Manage_Menu")
        menu = _load_menu(db, menu_id, org_context)

        if payload.name is not None:
            name = payload.name.strip()
            if not name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A menu needs a name.",
                )
            menu.name = name
        if payload.description is not None:
            menu.description = payload.description

        if payload.is_shared is not None and bool(payload.is_shared) != bool(menu.is_shared):
            if not policy.is_platform_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only platform administrators can share a menu across companies.",
                )
            menu.is_shared = bool(payload.is_shared)

        if payload.role_ids is not None:
            wanted = set(payload.role_ids)
            if wanted:
                # Only roles this organisation can actually use.
                valid = {
                    row[0]
                    for row in db.query(Role.id)
                    .filter(
                        Role.id.in_(wanted),
                        Role.is_deleted.is_(False),
                        # A shared menu may only take roles that are themselves
                        # shared, or it would claim one company's role for all.
                        Role.org_id.is_(None)
                        if menu.is_shared
                        else or_(Role.org_id.is_(None), Role.org_id == menu.org_id),
                    )
                    .all()
                }
                unknown = wanted - valid
                if unknown:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Those roles are not available to this organisation.",
                    )
            # A role belongs to one menu, so clear this menu's assignment and
            # release each wanted role from whichever menu held it before.
            db.execute(menu_roles.delete().where(menu_roles.c.menu_id == menu.id))
            if wanted:
                db.execute(
                    menu_roles.delete().where(menu_roles.c.role_id.in_(wanted))
                )
            for role_id in sorted(wanted):
                db.execute(menu_roles.insert().values(role_id=role_id, menu_id=menu.id))

        menu.updated_by = current_user.id
        db.commit()
        db.refresh(menu)
        logger.info(
            "Menu updated id=%s org_id=%s by user_id=%s roles=%s",
            menu.id, menu.org_id, current_user.id, len(_assigned_role_ids(db, menu.id)),
        )
        return MenuSummaryOut(
            id=menu.id,
            org_id=menu.org_id,
            org_name=None if menu.is_shared else _org_label(db, menu.org_id),
            is_shared=bool(menu.is_shared),
            name=menu.name,
            description=menu.description,
            role_ids=_assigned_role_ids(db, menu.id),
            updated_at=menu.updated_at.isoformat() if menu.updated_at else None,
        )

    @MenuRouter.delete("/navigation/menus/{menu_id}")
    async def delete_menu(
        self,
        menu_id: int,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        current_user=Depends(get_current_user),
    ):
        """Soft-delete a menu.

        Roles assigned to it lose their sidebar until another menu is assigned,
        which the caller is expected to have confirmed.
        """
        policy.require_any("Manage_Menu")
        menu = _load_menu(db, menu_id, org_context)

        now = func.now()
        menu.is_deleted = True
        menu.deleted_at = now
        menu.deleted_by = current_user.id
        (
            db.query(MenuItem)
            .filter(MenuItem.menu_id == menu.id, MenuItem.is_deleted.is_(False))
            .update(
                {
                    MenuItem.is_deleted: True,
                    MenuItem.deleted_at: now,
                    MenuItem.deleted_by: current_user.id,
                },
                synchronize_session=False,
            )
        )
        db.execute(menu_roles.delete().where(menu_roles.c.menu_id == menu.id))
        db.commit()
        logger.info(
            "Menu deleted id=%s org_id=%s by user_id=%s",
            menu.id, menu.org_id, current_user.id,
        )
        return {"ok": True}

    @MenuRouter.put("/navigation/menus/{menu_id}/items")
    async def save_menu(
        self,
        menu_id: int,
        payload: MenuSaveRequest,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        current_user=Depends(get_current_user),
    ):
        """Replace one menu's items in a single transaction.

        A half-saved menu would leave users without navigation, so the whole tree
        is validated before anything is written.
        """
        policy.require_any("Manage_Menu")
        menu = _load_menu(db, menu_id, org_context)
        items = payload.items
        org_id = menu.org_id

        if len(items) > MAX_MENU_ITEMS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A menu may hold at most {MAX_MENU_ITEMS} items.",
            )

        temp_ids = {item.temp_id for item in items}
        if len(temp_ids) != len(items):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Duplicate temp_id in the submitted menu.",
            )

        active_page_keys = {
            row[0]
            for row in db.query(AppPage.page_key).filter(AppPage.is_active.is_(True)).all()
        }
        parent_of = {item.temp_id: item.parent_temp_id for item in items}

        for item in items:
            if item.is_separator and item.page_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A separator is a heading and cannot open a page.",
                )
            if item.page_key and item.page_key not in active_page_keys:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown or inactive page: {item.page_key}",
                )
            if item.parent_temp_id and item.parent_temp_id not in temp_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Menu item '{item.label}' references a missing parent.",
                )

            # Walk to the root: catches cycles and over-deep nesting in one pass.
            seen = {item.temp_id}
            depth = 0
            cursor = item.parent_temp_id
            while cursor:
                if cursor in seen:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Circular menu nesting is not allowed.",
                    )
                seen.add(cursor)
                depth += 1
                if depth >= MAX_MENU_DEPTH:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Menu nesting is limited to {MAX_MENU_DEPTH} levels.",
                    )
                cursor = parent_of.get(cursor)

        def depth_of(temp_id: Optional[str]) -> int:
            level = 0
            cursor = temp_id
            while cursor:
                level += 1
                cursor = parent_of.get(cursor)
            return level

        try:
            now = func.now()
            # Supersede this menu's current rows rather than deleting them, so
            # who changed navigation and when stays answerable.
            (
                db.query(MenuItem)
                .filter(MenuItem.menu_id == menu.id, MenuItem.is_deleted.is_(False))
                .update(
                    {
                        MenuItem.is_deleted: True,
                        MenuItem.deleted_at: now,
                        MenuItem.deleted_by: current_user.id,
                    },
                    synchronize_session=False,
                )
            )

            id_by_temp: Dict[str, int] = {}
            for item in sorted(items, key=lambda i: depth_of(i.parent_temp_id)):
                row = MenuItem(
                    menu_id=menu.id,
                    org_id=org_id,
                    parent_id=id_by_temp.get(item.parent_temp_id) if item.parent_temp_id else None,
                    label=item.label,
                    icon=item.icon,
                    page_key=item.page_key,
                    is_separator=item.is_separator,
                    sort_order=item.sort_order,
                    is_active=item.is_active,
                    show_when_locked=item.show_when_locked,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                )
                db.add(row)
                db.flush()
                id_by_temp[item.temp_id] = row.id

            menu.updated_by = current_user.id
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Menu save failed for menu_id=%s org_id=%s", menu_id, org_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not save the menu.",
            )

        logger.info(
            "Menu saved id=%s org_id=%s by user_id=%s items=%s",
            menu.id, org_id, current_user.id, len(items),
        )
        return {"ok": True, "items": len(items)}


    @MenuRouter.get("/navigation/role-visibility", response_model=List[RoleVisibilityOut])
    async def role_visibility(
        self,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
    ):
        """Pages each role of the active organisation may see.

        The designer uses this to preview a draft menu as a given role. The same
        ``policy_allows_page`` rule as ``/my-menu`` is applied, so the preview can
        never disagree with what that role will actually get.
        """
        policy.require_any("View_Menu", "Manage_Menu")
        org_id = org_context.org_id

        organisation = (
            db.query(Organisation).filter(Organisation.id == org_id).first()
        )
        modules = list(organisation.modules or []) if organisation else []

        role_scope = or_(Role.org_id.is_(None), Role.org_id == org_id)
        roles = (
            db.query(Role)
            .options(joinedload(Role.permissions))
            .filter(Role.is_deleted.is_(False), role_scope)
            .order_by(Role.name)
            .all()
        )
        if not policy.is_platform_admin:
            # Never disclose platform-level roles or permissions to a tenant admin.
            roles = [
                role for role in roles
                if not role.is_platform_admin
                and not any(
                    permission.name in PLATFORM_PERMISSION_NAMES
                    for permission in role.permissions
                )
            ]

        result: List[RoleVisibilityOut] = []
        for role in roles:
            role_policy = AccessPolicy.from_role_sets(
                user=policy.user,
                org_ids=[org_id],
                roles_by_org={org_id: [role]},
                modules_by_org={org_id: modules},
                field_permissions={},
                is_platform_admin=bool(role.is_platform_admin),
            )
            result.append(
                RoleVisibilityOut(
                    role_id=role.id,
                    role_name=role.name,
                    is_platform_admin=bool(role.is_platform_admin),
                    allowed_page_keys=[
                        page.page_key for page in allowed_pages(role_policy)
                    ],
                )
            )
        return result

    @MenuRouter.get("/navigation/org-menus", response_model=List[OrgMenuSummaryOut])
    async def org_menus(
        self,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
    ):
        """Every organisation's menu state. Platform administrators only.

        Answers "which tenants have designed their own navigation, which are
        still on the shipped default, and who changed one last". Switching the
        active organisation is what then opens that tenant's menus for editing.
        """
        if not policy.is_platform_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only platform administrators can list menus across organisations.",
            )

        # Menus and their role assignments per organisation, in one pass each.
        menu_rows = (
            db.query(Menu)
            .filter(Menu.is_deleted.is_(False))
            .order_by(Menu.org_id, Menu.updated_at.desc())
            .all()
        )
        menus_by_org: Dict[int, List[Menu]] = {}
        for menu in menu_rows:
            menus_by_org.setdefault(menu.org_id, []).append(menu)

        item_counts = {
            row.menu_id: int(row.item_count)
            for row in (
                db.query(
                    MenuItem.menu_id.label("menu_id"),
                    func.count(MenuItem.id).label("item_count"),
                )
                .filter(MenuItem.is_deleted.is_(False))
                .group_by(MenuItem.menu_id)
                .all()
            )
        }
        assigned_counts: Dict[int, int] = {}
        for menu_id, in db.query(menu_roles.c.menu_id).all():
            assigned_counts[menu_id] = assigned_counts.get(menu_id, 0) + 1

        editors = {
            row[0]: row[1]
            for row in (
                db.query(Menu.id, User.username)
                .join(User, User.id == Menu.updated_by)
                .filter(Menu.is_deleted.is_(False))
                .all()
            )
        }

        organisations = (
            db.query(Organisation)
            .filter(Organisation.id.in_(policy.org_ids))
            .order_by(Organisation.display_name)
            .all()
        )

        summaries: List[OrgMenuSummaryOut] = []
        for org in organisations:
            menus = menus_by_org.get(org.id, [])
            newest = menus[0] if menus else None
            summaries.append(
                OrgMenuSummaryOut(
                    org_id=org.id,
                    org_name=org.display_name or org.name,
                    is_active=bool(org.is_active),
                    menu_count=len(menus),
                    assigned_role_count=sum(
                        assigned_counts.get(menu.id, 0) for menu in menus
                    ),
                    item_count=sum(item_counts.get(menu.id, 0) for menu in menus),
                    is_custom=bool(menus),
                    updated_at=(
                        newest.updated_at.isoformat()
                        if newest and newest.updated_at
                        else None
                    ),
                    updated_by=editors.get(newest.id) if newest else None,
                )
            )
        return summaries
