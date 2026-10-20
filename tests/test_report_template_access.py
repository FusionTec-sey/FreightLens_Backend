"""Who may list report templates.

The template library is a design surface -- template names, descriptions and
the HTML/CSS behind every printed document. Writing one has always required a
Manage_ permission, but listing them required only a login, and the frontend
route that was the only other barrier admitted View_Container, which every user
who can open the container register holds.

These are static checks on the route definitions, so they need no database.
"""

import ast
import importlib
import inspect

# Routes.Reports re-exports the APIRouter instance under the same name as the
# module, so ask for the module explicitly.
report_router_module = importlib.import_module("Routes.Reports.ReportRouter")


def _calls_in(function_name: str) -> list[ast.Call]:
    source = inspect.getsource(getattr(report_router_module, function_name))
    tree = ast.parse(inspect.cleandoc(source))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _require_any_names(function_name: str) -> set[str]:
    names: set[str] = set()
    for call in _calls_in(function_name):
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == "require_any":
            for argument in call.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    names.add(argument.value)
    return names


def test_the_template_catalog_is_not_open_to_any_login():
    required = _require_any_names("get_templates_catalog")

    assert required, "GET /templates must require a permission"
    assert "View_Report" in required
    assert "Manage_Report_Template" in required

    # The whole point: holding only container or order rights is not enough.
    assert "View_Container" not in required
    assert "View_Order" not in required


def test_toggling_a_template_still_needs_more_than_listing_it():
    assert _require_any_names("toggle_active_status") == {
        "Toggle_Report_Template",
        "Manage_Report_Template",
        "Manage_Operational_Template",
    }


def test_by_entity_is_filtered_by_print_permission_not_report_permission():
    """The Print dialog calls this one.

    Gating it on the report permissions would take printing away from the
    delivery roles, which hold none of them -- the same mistake as gating a
    read on a permission no role has been granted. It filters by each
    template's own resolver print permissions instead, so it is never stricter
    than the render it feeds.
    """
    source = inspect.getsource(report_router_module.get_templates_by_entity)

    assert "require_any" not in source, "by-entity must not demand report permissions"
    assert "print_permissions" in source
    assert "has_permission" in source
