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
from Utils import migrate_report_templates


def test_owned_or_shared_master_models_have_explicit_owner_and_flag():
    for model in (Supplier, PaymentTerm, MasterDocumentType, Product, ProductCategory):
        assert model.__table__.c.org_id.nullable is False
        assert model.__table__.c.is_shared.nullable is False


def test_reporting_foundation_tables_expose_required_contract():
    assert OrgPrintProfile.__table__.c.org_id.primary_key
    assert OrgPrintProfile.__table__.c.locale.nullable is False
    assert OrgPrintProfile.__table__.c.timezone.nullable is False

    assignment_columns = ReportTemplateAssignment.__table__.c
    assert assignment_columns.org_id.nullable is False
    assert assignment_columns.template_id.nullable is False
    assert assignment_columns.default_options.nullable is False

    assert ReportFieldClass.__table__.c.permission_name.nullable is False
    assert {row[0] for row in FIELD_CLASSES} == {
        "FINANCIAL",
        "SUPPLIER_IDENTITY",
        "BUDGET",
        "PERSONAL",
    }


def test_foundation_migration_enforces_one_default_per_org_entity():
    source = open(migrate_reporting_foundation.__file__, encoding="utf-8").read()

    assert "uq_report_template_default_org_entity" in source
    assert "WHERE is_default = TRUE AND is_deleted = FALSE" in source


def test_system_template_seed_uses_explicit_root_owner():
    source = open(migrate_report_templates.__file__, encoding="utf-8").read()

    assert "(SELECT min(id) FROM usercredentials.organisations)" in source
    assert "slug = :slug AND org_id IS NULL" not in source


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
