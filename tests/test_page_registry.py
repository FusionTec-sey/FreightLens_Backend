"""Contract tests for the navigation page registry.

The registry is only trustworthy while it mirrors the React router. These tests
parse ``MainPage.js`` and fail when a route is renamed, a guard is tightened, or
a registry entry claims a page that does not exist.
"""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from auth.policy.catalog import PERMISSION_BY_NAME
from auth.policy.page_registry import (
    KNOWN_MODULES,
    PAGE_BY_KEY,
    PAGE_REGISTRY,
    allowed_pages,
    policy_allows_page,
)

MAIN_PAGE = Path(__file__).resolve().parents[2] / "containermgmt" / "src" / "component" / "MainPage.js"

_ROUTE_RE = re.compile(r'<Route\s+path="(?P<path>[^"]+)"(?P<rest>.*?)/>', re.DOTALL)
_LIST_RE = re.compile(r'required(?P<kind>Permissions|Modules)=\{\[(?P<body>[^\]]*)\]\}')


def _frontend_routes() -> dict[str, dict[str, set[str]]]:
    """Parse ``path`` plus the PrivateRoute guard props declared for each route."""
    source = MAIN_PAGE.read_text(encoding="utf-8")
    routes: dict[str, dict[str, set[str]]] = {}
    for match in _ROUTE_RE.finditer(source):
        guards = {"permissions": set(), "modules": set()}
        for list_match in _LIST_RE.finditer(match.group("rest")):
            names = set(re.findall(r'"([^"]+)"', list_match.group("body")))
            key = "permissions" if list_match.group("kind") == "Permissions" else "modules"
            guards[key] = names
        routes[match.group("path")] = guards
    return routes


def _policy(permissions=(), modules=(), is_platform_admin=False):
    policy = SimpleNamespace(
        permission_names=frozenset(permissions),
        module_names=frozenset(modules),
        is_platform_admin=is_platform_admin,
    )
    policy.has = lambda name: is_platform_admin or name in policy.permission_names
    policy.has_any = lambda *names: any(policy.has(name) for name in names)
    return policy


@pytest.fixture(scope="module")
def frontend_routes():
    if not MAIN_PAGE.exists():
        pytest.skip(f"Frontend router not available at {MAIN_PAGE}")
    routes = _frontend_routes()
    assert routes, "No routes parsed from MainPage.js"
    return routes


def test_every_registry_route_exists_in_the_router(frontend_routes):
    """A registry route that no longer exists would produce a dead menu item."""
    missing = sorted(
        page.route for page in PAGE_REGISTRY if page.route not in frontend_routes
    )
    assert missing == [], f"Registry routes absent from MainPage.js: {missing}"


def test_registry_permissions_are_never_wider_than_the_route_guard(frontend_routes):
    """The menu may be stricter than the guard, never more permissive."""
    widened = {}
    for page in PAGE_REGISTRY:
        guards = frontend_routes.get(page.route)
        if guards is None:
            continue
        extra = set(page.permission_codes) - guards["permissions"]
        if extra:
            widened[page.page_key] = sorted(extra)
    assert widened == {}, f"Registry grants visibility the route guard does not: {widened}"


def test_registry_modules_match_the_route_guard(frontend_routes):
    mismatched = {}
    for page in PAGE_REGISTRY:
        guards = frontend_routes.get(page.route)
        if guards is None:
            continue
        if set(page.module_codes) != guards["modules"]:
            mismatched[page.page_key] = {
                "registry": sorted(page.module_codes),
                "route": sorted(guards["modules"]),
            }
    assert mismatched == {}, f"Module guards drifted: {mismatched}"


def test_registry_only_references_catalogued_permissions():
    unknown = sorted(
        code for page in PAGE_REGISTRY
        for code in page.permission_codes
        if code not in PERMISSION_BY_NAME
    )
    assert unknown == []


def test_registry_only_references_known_modules():
    unknown = sorted(
        module for page in PAGE_REGISTRY
        for module in page.module_codes
        if module not in KNOWN_MODULES
    )
    assert unknown == []


def test_menu_designer_requires_its_own_permission():
    assert PAGE_BY_KEY["MENU_DESIGNER"].permission_codes == ("View_Menu", "Manage_Menu")


def test_menu_designer_is_hidden_without_a_menu_permission():
    page = PAGE_BY_KEY["MENU_DESIGNER"]
    assert policy_allows_page(_policy({"View_Setting"}), page) is False
    assert policy_allows_page(_policy({"View_Menu"}), page) is True


def test_module_subscription_is_required_even_with_the_permission():
    page = PAGE_BY_KEY["ORDERS"]
    assert policy_allows_page(_policy({"View_Order"}, {"ORDERS"}), page) is True
    assert policy_allows_page(_policy({"View_Order"}, set()), page) is False


def test_edit_permission_implies_the_matching_view_page():
    page = PAGE_BY_KEY["ORDERS"]
    assert policy_allows_page(_policy({"Edit_Order"}, {"ORDERS"}), page) is True


def test_unrelated_permission_does_not_reveal_a_page():
    page = PAGE_BY_KEY["TENANT_CONSOLE"]
    assert policy_allows_page(_policy({"View_Container"}, {"LOGISTICS"}), page) is False


def test_platform_admin_sees_every_page():
    assert len(allowed_pages(_policy(is_platform_admin=True))) == len(PAGE_REGISTRY)


def test_user_without_permissions_sees_only_unguarded_pages():
    pages = allowed_pages(_policy())
    assert all(not page.permission_codes and not page.module_codes for page in pages)


# ── Escape hatch: the designer must stay reachable ────────────────────────────

def test_saved_menu_without_the_designer_still_exposes_it():
    """An admin who omits the Menu Designer must not lose the way back in."""
    from Routes.Navigation.MenuRouter import _with_escape_hatches
    from Schema.Credentials.menu import MenuNodeOut

    saved = [MenuNodeOut(label="Logistics", children=[
        MenuNodeOut(label="Containers", page_key="CONTAINER_REGISTER", route="/viewContainer"),
    ])]
    result = _with_escape_hatches(saved, _policy({"Manage_Menu"}))
    assert [node.page_key for node in result][-1] == "MENU_DESIGNER"


def test_escape_hatch_is_not_added_twice():
    from Routes.Navigation.MenuRouter import _with_escape_hatches
    from Schema.Credentials.menu import MenuNodeOut

    saved = [MenuNodeOut(label="System", children=[
        MenuNodeOut(label="Menu Designer", page_key="MENU_DESIGNER", route="/admin/menu"),
    ])]
    result = _with_escape_hatches(saved, _policy({"Manage_Menu"}))
    assert len(result) == 1


def test_escape_hatch_is_not_offered_without_the_permission():
    from Routes.Navigation.MenuRouter import _with_escape_hatches
    from Schema.Credentials.menu import MenuNodeOut

    saved = [MenuNodeOut(label="Orders", page_key="ORDERS", route="/orders")]
    result = _with_escape_hatches(saved, _policy({"View_Order"}, {"ORDERS"}))
    assert [node.page_key for node in result] == ["ORDERS"]


# ── Role-assigned menus: which layout a user is served ────────────────────────

class _FakeQuery:
    """Minimal stand-in for the chained Session.query used by the resolver."""

    def __init__(self, rows, recorder, label):
        self._rows = rows
        self._recorder = recorder
        self._label = label

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        self._recorder.append(self._label)
        return self._rows

    def first(self):
        self._recorder.append(self._label)
        return self._rows[0] if self._rows else None


def _resolver_db(role_ids, assigned_menu, recorder):
    from Model.Credentials.menu import Menu

    class _DB:
        def query(self, *entities):
            if entities[0] is not Menu:
                return _FakeQuery([(role_id,) for role_id in role_ids], recorder, "roles")
            return _FakeQuery(
                [assigned_menu] if assigned_menu else [], recorder, "assigned"
            )

    return _DB()


def _menu(menu_id):
    from Model.Credentials.menu import Menu

    menu = Menu()
    menu.id = menu_id
    menu.org_id = 1
    return menu


def test_a_role_assigned_menu_is_served():
    from Routes.Navigation.MenuRouter import _resolve_menu_for_user

    assigned = _menu(7)
    db = _resolver_db([3], assigned, [])
    assert _resolve_menu_for_user(db, 1, 42) is assigned


def test_a_role_with_no_menu_gets_nothing():
    """No organisation-wide default: an unassigned role means an empty sidebar."""
    from Routes.Navigation.MenuRouter import _resolve_menu_for_user

    db = _resolver_db([3], None, [])
    assert _resolve_menu_for_user(db, 1, 42) is None


def test_user_with_no_roles_skips_the_assignment_lookup():
    from Routes.Navigation.MenuRouter import _resolve_menu_for_user

    recorder = []
    db = _resolver_db([], None, recorder)
    assert _resolve_menu_for_user(db, 1, 42) is None
    assert "assigned" not in recorder


def test_an_admin_keeps_the_designer_when_no_menu_applies():
    """Clearing the default must not strand the person who can fix it."""
    from Routes.Navigation.MenuRouter import _with_escape_hatches

    result = _with_escape_hatches([], _policy({"Manage_Menu"}))
    assert [node.page_key for node in result] == ["MENU_DESIGNER"]


def test_a_user_with_no_menu_and_no_menu_permission_gets_nothing():
    from Routes.Navigation.MenuRouter import _with_escape_hatches

    assert _with_escape_hatches([], _policy({"View_Order"}, {"ORDERS"})) == []
