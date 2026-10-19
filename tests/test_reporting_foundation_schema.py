from Model.Credentials.roles import Role
from Model.Credentials.user_org_roles import user_org_roles
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.MasterData.DocumentType import MasterDocumentType
from Model.containermgmt.MasterData.PaymentTerm import PaymentTerm
from Model.containermgmt.Orders.OrderPayment import OrderPayment
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.Product import Product, ProductCategory
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Report.OrgPrintProfile import OrgPrintProfile
from Model.containermgmt.Report.ReportFieldClass import ReportFieldClass
from Model.containermgmt.Report.ReportTemplateAssignment import ReportTemplateAssignment
from Model.containermgmt.Report.ReportTemplateVersion import ReportTemplateVersion
from Utils import migrate_reporting_foundation
from Utils.migrate_reporting_foundation import FIELD_CLASSES
from auth.policy.field_registry import FIELD_CLASS_SPECS
from Utils import migrate_report_templates, migrate_sourcing_and_quote_templates


def test_owned_or_shared_master_models_have_explicit_owner_and_flag():
    for model in (Supplier, PaymentTerm, MasterDocumentType, ProductCategory):
        assert model.__table__.c.org_id.nullable is False
        assert model.__table__.c.is_shared.nullable is False


def test_a_product_belongs_to_one_company_and_links_to_a_group_definition():
    """A product is not shared.

    Its row mixes universal facts with company facts -- internal code, unit
    cost, stock, default supplier -- so it is copied from the group dictionary
    rather than shared from it, and carries a link to the entry it came from.
    The is_shared flag it used to have was never read by anything.
    """
    assert Product.__table__.c.org_id.nullable is False
    assert "is_shared" not in Product.__table__.c
    assert "definition_id" in Product.__table__.c


def test_reporting_foundation_tables_expose_required_contract():
    assert OrgPrintProfile.__table__.c.org_id.primary_key
    assert OrgPrintProfile.__table__.c.locale.nullable is False
    assert OrgPrintProfile.__table__.c.timezone.nullable is False

    assignment_columns = ReportTemplateAssignment.__table__.c
    assert assignment_columns.org_id.nullable is False
    assert assignment_columns.template_id.nullable is False
    assert assignment_columns.default_options.nullable is False

    assert ReportFieldClass.__table__.c.permission_name.nullable is False
    # Editing is a second permission on the class; nullable so the reporting
    # classes below stay read-only, which is all they have ever meant.
    assert ReportFieldClass.__table__.c.edit_permission_name.nullable is True

    seeded = {row[0]: row for row in FIELD_CLASSES}
    reporting_classes = {"FINANCIAL", "SUPPLIER_IDENTITY", "BUDGET", "PERSONAL"}
    assert reporting_classes <= set(seeded)
    for code in reporting_classes:
        assert seeded[code][2] is None, f"{code} must stay read-only"

    # Screen field classes are declared in the field registry and seeded here too.
    assert {code for code, _, _, _ in FIELD_CLASS_SPECS} <= set(seeded)
    for code, _view, edit, _description in FIELD_CLASS_SPECS:
        assert edit, f"{code} is a screen class and needs an edit permission"


def test_foundation_migration_enforces_one_default_per_org_entity():
    source = open(migrate_reporting_foundation.__file__, encoding="utf-8").read()

    assert "uq_report_template_default_org_entity" in source
    assert "WHERE is_default = TRUE AND is_deleted = FALSE" in source


def test_system_template_seed_uses_explicit_root_owner():
    sources = (
        open(module.__file__, encoding="utf-8").read()
        for module in (migrate_report_templates, migrate_sourcing_and_quote_templates)
    )

    for source in sources:
        assert "(SELECT min(id) FROM usercredentials.organisations)" in source
        assert "slug = :slug AND org_id IS NULL" not in source
        assert "NULL, :slug" not in source


def test_roles_can_be_assigned_per_organisation():
    assert Role.__table__.c.org_id.nullable is True
    assert Role.__table__.c.is_platform_admin.nullable is False
    assert {column.name for column in user_org_roles.primary_key.columns} == {
        "user_id",
        "org_id",
        "role_id",
    }


def test_template_versions_own_render_settings():
    assert "paper_settings" in ReportTemplateVersion.__table__.c
    assert "options_schema" in ReportTemplateVersion.__table__.c


def test_transaction_money_models_preserve_base_currency_values():
    for model, expected in (
        (PurchaseOrder, {"base_currency", "exchange_rate_to_base", "total_amount_base"}),
        (POItem, {"base_currency", "exchange_rate_to_base", "total_price_base"}),
        (OrderPayment, {"base_currency", "base_amount"}),
    ):
        assert expected.issubset(model.__table__.c.keys())
