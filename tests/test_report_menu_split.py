"""Two reporting screens, and a designer a viewer cannot wander into.

The reporting hub was one page with a segmented toggle, so the registers half
could not be placed in a menu at all. Splitting it retires the `REPORTS` page
key, and a menu row's `page_key` is a foreign key into `app_pages` -- which is
why the repoint is a migration and not a hopeful UPDATE.

The second rule here is the one that had teeth: `REPORT_EDITOR_NEW` admitted
`View_Report`, while every write endpoint under it requires
`Manage_Report_Template`. A viewer could open the designer, lay out a template
and be refused at the save.
"""
from auth.policy.page_registry import PAGE_BY_KEY, PAGE_REGISTRY


def _page(key):
    return PAGE_BY_KEY[key]


def test_each_reporting_screen_has_its_own_page_key():
    documents = _page("REPORT_DOCUMENT_TEMPLATES")
    registers = _page("REPORT_OPERATIONAL_REGISTERS")

    assert documents.route == "/reports/documents"
    assert registers.route == "/reports/registers"
    assert documents.title == "Print Document Templates"
    assert registers.title == "Operational Registers"


def test_the_old_hub_key_is_gone_from_the_registry():
    """It stays in the database as an inactive row; the migration repoints the
    menu items that referenced it."""
    assert "REPORTS" not in PAGE_BY_KEY


def test_viewing_a_report_is_not_permission_to_design_one():
    editor = _page("REPORT_EDITOR_NEW")

    assert "View_Report" not in editor.permission_codes
    assert "Manage_Report_Template" in editor.permission_codes


def test_both_screens_are_visible_to_a_plain_report_viewer():
    """Previewing and running a register is the ordinary case; only designing
    is gated."""
    for key in ("REPORT_DOCUMENT_TEMPLATES", "REPORT_OPERATIONAL_REGISTERS"):
        assert "View_Report" in _page(key).permission_codes


def test_no_reporting_page_is_wider_than_the_designer_it_opens():
    """A page that can reach the designer must not be visible to more people
    than the designer's own permissions allow."""
    editor = set(_page("REPORT_EDITOR_NEW").permission_codes)

    assert "View_Report" not in editor
    assert "View_Order" not in editor
    assert editor <= {"Manage_Report_Template", "Manage_Operational_Template"}


def test_every_reporting_route_is_unique():
    """Two page keys on one route would make a menu entry ambiguous."""
    routes = [p.route for p in PAGE_REGISTRY if p.group_key == "REPORTING"]

    assert len(routes) == len(set(routes)), routes
