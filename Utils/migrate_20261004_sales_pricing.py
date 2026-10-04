"""Create empty immutable tax and independent branch-price histories."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Orders.SalesPricing import (
    AGREEMENT_REVISION_FUNCTION, AGREEMENT_REVISION_TRIGGER,
    BranchProductPrice, BranchProductPriceRevision, CustomerPriceAgreement,
    CustomerPriceAgreementRevision, IMMUTABLE_FUNCTION,
    PRICE_REVISION_FUNCTION, PRICE_REVISION_TRIGGER,
    PRODUCT_TAX_REVISION_FUNCTION, PRODUCT_TAX_REVISION_TRIGGER,
    ProductTaxAssignment, ProductTaxAssignmentRevision, SalesTaxRule,
    SalesTaxRuleRevision, SalesTransactionPricing, TAX_REVISION_FUNCTION,
    TAX_REVISION_TRIGGER,
    immutable_trigger,
)


def _trigger(conn, table, name, ddl):
    exists = conn.execute(text(
        "SELECT 1 FROM pg_trigger WHERE tgrelid = "
        "CAST(:table AS regclass) AND tgname = :name AND NOT tgisinternal"),
        {"table": f"containermgmt.{table}", "name": name}).scalar()
    if not exists:
        conn.execute(text(ddl))


def ensure_sales_pricing_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for model in (SalesTaxRule, SalesTaxRuleRevision,
                      BranchProductPrice, BranchProductPriceRevision,
                      ProductTaxAssignment, ProductTaxAssignmentRevision,
                      CustomerPriceAgreement, CustomerPriceAgreementRevision,
                      SalesTransactionPricing):
            model.__table__.create(conn, checkfirst=True)
        conn.execute(text(IMMUTABLE_FUNCTION))
        for model in (SalesTaxRule, SalesTaxRuleRevision,
                      BranchProductPrice, BranchProductPriceRevision,
                      ProductTaxAssignment, ProductTaxAssignmentRevision,
                      CustomerPriceAgreement, CustomerPriceAgreementRevision,
                      SalesTransactionPricing):
            _trigger(conn, model.__tablename__,
                f"{model.__tablename__}_immutable",
                immutable_trigger(model.__tablename__))
        conn.execute(text(TAX_REVISION_FUNCTION))
        _trigger(conn, SalesTaxRuleRevision.__tablename__,
            "sales_tax_revision_guard", TAX_REVISION_TRIGGER)
        conn.execute(text(PRICE_REVISION_FUNCTION))
        _trigger(conn, BranchProductPriceRevision.__tablename__,
            "branch_product_price_revision_guard", PRICE_REVISION_TRIGGER)
        conn.execute(text(PRODUCT_TAX_REVISION_FUNCTION))
        _trigger(conn, ProductTaxAssignmentRevision.__tablename__,
            "product_tax_assignment_revision_guard",
            PRODUCT_TAX_REVISION_TRIGGER)
        conn.execute(text(AGREEMENT_REVISION_FUNCTION))
        _trigger(conn, CustomerPriceAgreementRevision.__tablename__,
            "customer_price_agreement_revision_guard",
            AGREEMENT_REVISION_TRIGGER)
