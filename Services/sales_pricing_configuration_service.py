"""Append-only T11 tax and branch-price configuration.

No default rate, product classification, customer eligibility, invoice, stock or
payment effect is inferred here. Public routes must add explicit permissions.
"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, text

from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Orders.SalesPricing import (
    BranchProductPrice, BranchProductPriceRevision, CustomerPriceAgreement,
    CustomerPriceAgreementRevision, ProductTaxAssignment,
    ProductTaxAssignmentRevision, SalesTaxRule, SalesTaxRuleRevision,
)
from Schema.SalesPricingSchema import (
    BranchProductPriceRead, BranchProductPriceSave,
    CustomerPriceAgreementRead, CustomerPriceAgreementSave,
    ProductTaxAssignmentRead, ProductTaxAssignmentSave, TaxRuleRead, TaxRuleSave,
)
from Services.inventory_posting_service import (
    PostingConflict, PostingEffect, execute_once,
)
from Services.sales_pricing_service import (
    PriceCandidate, PricingLineInput, TaxRuleSnapshot,
)
from Utils.org_filter import apply_org_filter


def _allowed(context):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Sales pricing company scope denied")


def _lock(db, namespace, context, identity):
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"sales-pricing:{namespace}:{context.org_id}:{identity}"})


def _tax_header(db, context, tax_rule_key, *, lock=False):
    query = apply_org_filter(db.query(SalesTaxRule).filter_by(
        org_id=context.org_id, tax_rule_key=tax_rule_key, is_deleted=False),
        SalesTaxRule, context)
    return (query.populate_existing().with_for_update() if lock else query).one_or_none()


def _price_header(db, context, price_key, *, lock=False):
    query = apply_org_filter(db.query(BranchProductPrice).filter_by(
        org_id=context.org_id, price_key=price_key, is_deleted=False),
        BranchProductPrice, context)
    return (query.populate_existing().with_for_update() if lock else query).one_or_none()


def _latest_tax(db, context, tax_rule_key):
    return apply_org_filter(db.query(SalesTaxRuleRevision).filter_by(
        org_id=context.org_id, tax_rule_key=tax_rule_key, is_deleted=False),
        SalesTaxRuleRevision, context).order_by(
            SalesTaxRuleRevision.version.desc()).first()


def _latest_price(db, context, price_key):
    return apply_org_filter(db.query(BranchProductPriceRevision).filter_by(
        org_id=context.org_id, price_key=price_key, is_deleted=False),
        BranchProductPriceRevision, context).order_by(
            BranchProductPriceRevision.version.desc()).first()


def _tax_read(header, revision):
    return TaxRuleRead(tax_rule_key=header.tax_rule_key, code=header.code,
        version=revision.version, name=revision.name,
        treatment=revision.treatment, rate=str(revision.rate),
        is_enabled=revision.is_enabled)


def _price_read(header, revision):
    return BranchProductPriceRead(price_key=header.price_key,
        branch_id=header.branch_id, product_id=header.product_id,
        unit=header.unit,
        version=revision.version, gross_unit_scr=str(revision.gross_unit_scr),
        floor_gross_unit_scr=(str(revision.floor_gross_unit_scr)
            if revision.floor_gross_unit_scr is not None else None),
        is_enabled=revision.is_enabled)


def read_tax_rule(db, context, tax_rule_key, *, authorize):
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    authorize(db); _allowed(context)
    header = _tax_header(db, context, tax_rule_key)
    if header is None:
        raise LookupError("Tax rule not found")
    return _tax_read(header, _latest_tax(db, context, tax_rule_key))


def read_branch_product_price(db, context, price_key, *, authorize):
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    authorize(db); _allowed(context)
    header = _price_header(db, context, price_key)
    if header is None:
        raise LookupError("Branch product price not found")
    return _price_read(header, _latest_price(db, context, price_key))


def _page(query, page, limit, project):
    if type(page) is not int or page < 1 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid sales pricing pagination")
    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return dict(items=[project(*row) if not hasattr(row, "__table__") else project(row)
        for row in rows], total=total, page=page, limit=limit,
        pages=max(1, (total + limit - 1) // limit))


def list_tax_rules(db, context, *, page, limit, authorize):
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    authorize(db); _allowed(context)
    latest = db.query(SalesTaxRuleRevision.tax_rule_key,
        func.max(SalesTaxRuleRevision.version).label("version")).filter(
        SalesTaxRuleRevision.org_id == context.org_id,
        SalesTaxRuleRevision.is_deleted.is_(False)).group_by(
            SalesTaxRuleRevision.tax_rule_key).subquery()
    query = db.query(SalesTaxRule, SalesTaxRuleRevision).join(latest,
        SalesTaxRule.tax_rule_key == latest.c.tax_rule_key).join(
        SalesTaxRuleRevision,
        (SalesTaxRuleRevision.tax_rule_key == latest.c.tax_rule_key)
        & (SalesTaxRuleRevision.version == latest.c.version)
        & (SalesTaxRuleRevision.org_id == context.org_id)).filter(
        SalesTaxRule.org_id == context.org_id,
        SalesTaxRule.is_deleted.is_(False)).order_by(SalesTaxRule.code)
    return _page(query, page, limit, _tax_read)


def list_branch_product_prices(db, context, *, page, limit, authorize,
                               branch_id=None, product_id=None, unit=None):
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    authorize(db); _allowed(context)
    latest = db.query(BranchProductPriceRevision.price_key,
        func.max(BranchProductPriceRevision.version).label("version")).filter(
        BranchProductPriceRevision.org_id == context.org_id,
        BranchProductPriceRevision.is_deleted.is_(False)).group_by(
            BranchProductPriceRevision.price_key).subquery()
    query = db.query(BranchProductPrice, BranchProductPriceRevision).join(latest,
        BranchProductPrice.price_key == latest.c.price_key).join(
        BranchProductPriceRevision,
        (BranchProductPriceRevision.price_key == latest.c.price_key)
        & (BranchProductPriceRevision.version == latest.c.version)
        & (BranchProductPriceRevision.org_id == context.org_id)).filter(
        BranchProductPrice.org_id == context.org_id,
        BranchProductPrice.is_deleted.is_(False))
    if branch_id is not None: query = query.filter(BranchProductPrice.branch_id == branch_id)
    if product_id is not None: query = query.filter(BranchProductPrice.product_id == product_id)
    if unit is not None: query = query.filter(BranchProductPrice.unit == unit)
    return _page(query.order_by(BranchProductPrice.branch_id,
        BranchProductPrice.product_id, BranchProductPrice.unit),
        page, limit, _price_read)


def _same_tax_config(row, payload):
    return (row.name == payload.config.name
        and row.treatment == payload.config.treatment
        and row.rate == Decimal(payload.config.rate)
        and row.is_enabled is payload.config.is_enabled)


def save_tax_rule(factory, context, actor_id, tax_rule_key: UUID,
                  payload: TaxRuleSave, *, authorize):
    if not isinstance(payload, TaxRuleSave):
        raise ValueError("Typed tax rule save required")
    payload = TaxRuleSave.model_validate(payload.model_dump())
    if not isinstance(tax_rule_key, UUID) or not tax_rule_key.int:
        raise ValueError("Nonzero tax rule key required")
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    request = payload.model_dump(mode="json", exclude={"operation_key"})
    request["tax_rule_key"] = str(tax_rule_key)

    def guard(db):
        authorize(db); _allowed(context)
        if payload.expected_version:
            _lock(db, "tax-key", context, tax_rule_key)
            if _tax_header(db, context, tax_rule_key, lock=True) is None:
                raise LookupError("Tax rule not found")

    def effect(db):
        _lock(db, "tax-code", context, payload.code)
        header = _tax_header(db, context, tax_rule_key, lock=True)
        if header is None:
            if payload.expected_version != 0:
                raise PostingConflict("Tax rule changed; reload before saving")
            existing = apply_org_filter(db.query(SalesTaxRule).filter_by(
                org_id=context.org_id, code=payload.code, is_deleted=False),
                SalesTaxRule, context).one_or_none()
            if existing is not None:
                raise PostingConflict("Tax rule code already exists")
            header = SalesTaxRule(org_id=context.org_id,
                tax_rule_key=tax_rule_key, code=payload.code,
                creation_operation_key=payload.operation_key,
                created_by=actor_id)
            db.add(header); db.flush()
            current = None
        else:
            if header.code != payload.code:
                raise PostingConflict("Tax rule code is immutable")
            current = _latest_tax(db, context, tax_rule_key)
        version = current.version if current else 0
        if version != payload.expected_version:
            raise PostingConflict("Tax rule changed; reload before saving")
        if current is not None and _same_tax_config(current, payload):
            raise ValueError("Tax rule has no changes")
        revision = SalesTaxRuleRevision(org_id=context.org_id,
            tax_rule_key=tax_rule_key, version=version + 1,
            operation_key=payload.operation_key, name=payload.config.name,
            treatment=payload.config.treatment,
            rate=Decimal(payload.config.rate),
            is_enabled=payload.config.is_enabled, reason=payload.reason,
            created_by=actor_id)
        db.add(revision); db.flush()
        result = {"tax_rule_key": str(tax_rule_key), "version": revision.version}
        return PostingEffect(result, {"kind": "sales.tax-rule.saved", **result})

    return execute_once(factory, context, actor_id, payload.operation_key,
        "sales.tax-rule.save.v1", request, effect, authorize=guard)


def _price_scope(db, context, branch_id, product_id, *, lock=True):
    branch = apply_org_filter(db.query(InventoryBranch).filter_by(
        org_id=context.org_id, id=branch_id, is_deleted=False),
        InventoryBranch, context)
    # Select only eligibility columns. Product relationships eagerly include
    # supplier pricing and must never be loaded by a retail pricing operation.
    product = apply_org_filter(db.query(Product.id, Product.status,
        Product.is_shared).filter_by(
        org_id=context.org_id, id=product_id, is_deleted=False),
        Product, context)
    if lock:
        branch = branch.with_for_update()
        product = product.with_for_update(of=Product)
    branch = branch.one_or_none()
    product = product.one_or_none()
    if branch is None or product is None:
        raise LookupError("Branch or product not found")
    if not branch.is_active or product.status != "active" or product.is_shared:
        raise PostingConflict("Active tenant-owned branch and product required")
    return branch, product


def _same_price_config(row, payload):
    floor = (Decimal(payload.config.floor_gross_unit_scr)
        if payload.config.floor_gross_unit_scr is not None else None)
    return (row.gross_unit_scr == Decimal(payload.config.gross_unit_scr)
        and row.floor_gross_unit_scr == floor
        and row.is_enabled is payload.config.is_enabled)


def save_branch_product_price(factory, context, actor_id, price_key: UUID,
                              payload: BranchProductPriceSave, *, authorize):
    if not isinstance(payload, BranchProductPriceSave):
        raise ValueError("Typed branch product price save required")
    payload = BranchProductPriceSave.model_validate(payload.model_dump())
    if not isinstance(price_key, UUID) or not price_key.int:
        raise ValueError("Nonzero branch product price key required")
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    request = payload.model_dump(mode="json", exclude={"operation_key"})
    request["price_key"] = str(price_key)

    def guard(db):
        authorize(db); _allowed(context)
        _lock(db, "branch-product",
            context, f"{payload.branch_id}:{payload.product_id}:{payload.unit}")
        _price_scope(db, context, payload.branch_id, payload.product_id)
        if payload.expected_version:
            header = _price_header(db, context, price_key, lock=True)
            if header is None:
                raise LookupError("Branch product price not found")

    def effect(db):
        header = _price_header(db, context, price_key, lock=True)
        if header is None:
            if payload.expected_version != 0:
                raise PostingConflict("Branch product price changed; reload before saving")
            existing = apply_org_filter(db.query(BranchProductPrice).filter_by(
                org_id=context.org_id, branch_id=payload.branch_id,
                product_id=payload.product_id, unit=payload.unit,
                is_deleted=False),
                BranchProductPrice, context).one_or_none()
            if existing is not None:
                raise PostingConflict("Branch product price already exists")
            header = BranchProductPrice(org_id=context.org_id,
                price_key=price_key, branch_id=payload.branch_id,
                product_id=payload.product_id, unit=payload.unit,
                creation_operation_key=payload.operation_key,
                created_by=actor_id)
            db.add(header); db.flush()
            current = None
        else:
            if (header.branch_id != payload.branch_id
                    or header.product_id != payload.product_id
                    or header.unit != payload.unit):
                raise PostingConflict("Branch product price target is immutable")
            current = _latest_price(db, context, price_key)
        version = current.version if current else 0
        if version != payload.expected_version:
            raise PostingConflict("Branch product price changed; reload before saving")
        if current is not None and _same_price_config(current, payload):
            raise ValueError("Branch product price has no changes")
        revision = BranchProductPriceRevision(org_id=context.org_id,
            price_key=price_key, version=version + 1,
            operation_key=payload.operation_key,
            gross_unit_scr=Decimal(payload.config.gross_unit_scr),
            floor_gross_unit_scr=(Decimal(payload.config.floor_gross_unit_scr)
                if payload.config.floor_gross_unit_scr is not None else None),
            is_enabled=payload.config.is_enabled, reason=payload.reason,
            created_by=actor_id)
        db.add(revision); db.flush()
        result = {"price_key": str(price_key), "version": revision.version}
        return PostingEffect(result,
            {"kind": "sales.branch-product-price.saved", **result})

    return execute_once(factory, context, actor_id, payload.operation_key,
        "sales.branch-product-price.save.v1", request, effect, authorize=guard)


def tax_snapshot(read: TaxRuleRead):
    if not read.is_enabled:
        raise PostingConflict("Tax rule is disabled")
    return TaxRuleSnapshot(read.code, read.version, read.treatment,
        Decimal(read.rate)).validate()


def store_price_candidate(read: BranchProductPriceRead):
    if not read.is_enabled:
        raise PostingConflict("Branch product price is disabled")
    return PriceCandidate("STORE", str(read.price_key), read.version,
        Decimal(read.gross_unit_scr)).validate()


def _assignment_header(db, context, assignment_key, *, lock=False):
    query = apply_org_filter(db.query(ProductTaxAssignment).filter_by(
        org_id=context.org_id, assignment_key=assignment_key,
        is_deleted=False), ProductTaxAssignment, context)
    return (query.populate_existing().with_for_update() if lock else query).one_or_none()


def _latest_assignment(db, context, assignment_key):
    return apply_org_filter(db.query(ProductTaxAssignmentRevision).filter_by(
        org_id=context.org_id, assignment_key=assignment_key,
        is_deleted=False), ProductTaxAssignmentRevision, context).order_by(
            ProductTaxAssignmentRevision.version.desc()).first()


def _assignment_read(header, revision):
    return ProductTaxAssignmentRead(assignment_key=header.assignment_key,
        product_id=header.product_id, version=revision.version,
        tax_rule_key=revision.tax_rule_key, is_enabled=revision.is_enabled)


def read_product_tax_assignment(db, context, assignment_key, *, authorize):
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    authorize(db); _allowed(context)
    header = _assignment_header(db, context, assignment_key)
    if header is None:
        raise LookupError("Product tax assignment not found")
    return _assignment_read(header,
        _latest_assignment(db, context, assignment_key))


def list_product_tax_assignments(db, context, *, page, limit, authorize,
                                 product_id=None):
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    authorize(db); _allowed(context)
    latest = db.query(ProductTaxAssignmentRevision.assignment_key,
        func.max(ProductTaxAssignmentRevision.version).label("version")).filter(
        ProductTaxAssignmentRevision.org_id == context.org_id,
        ProductTaxAssignmentRevision.is_deleted.is_(False)).group_by(
            ProductTaxAssignmentRevision.assignment_key).subquery()
    query = db.query(ProductTaxAssignment, ProductTaxAssignmentRevision).join(
        latest, ProductTaxAssignment.assignment_key == latest.c.assignment_key).join(
        ProductTaxAssignmentRevision,
        (ProductTaxAssignmentRevision.assignment_key == latest.c.assignment_key)
        & (ProductTaxAssignmentRevision.version == latest.c.version)
        & (ProductTaxAssignmentRevision.org_id == context.org_id)).filter(
        ProductTaxAssignment.org_id == context.org_id,
        ProductTaxAssignment.is_deleted.is_(False))
    if product_id is not None:
        query = query.filter(ProductTaxAssignment.product_id == product_id)
    return _page(query.order_by(ProductTaxAssignment.product_id),
        page, limit, _assignment_read)


def _product_scope(db, context, product_id, *, lock=True):
    query = apply_org_filter(db.query(Product.id, Product.status,
        Product.is_shared).filter_by(
        org_id=context.org_id, id=product_id, is_deleted=False),
        Product, context)
    product = (query.with_for_update(of=Product) if lock else query).one_or_none()
    if product is None:
        raise LookupError("Product not found")
    if product.status != "active" or product.is_shared:
        raise PostingConflict("Active tenant-owned product required")
    return product


def save_product_tax_assignment(factory, context, actor_id,
                                assignment_key: UUID,
                                payload: ProductTaxAssignmentSave, *, authorize):
    if not isinstance(payload, ProductTaxAssignmentSave):
        raise ValueError("Typed product tax assignment save required")
    payload = ProductTaxAssignmentSave.model_validate(payload.model_dump())
    if not isinstance(assignment_key, UUID) or not assignment_key.int:
        raise ValueError("Nonzero product tax assignment key required")
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    request = payload.model_dump(mode="json", exclude={"operation_key"})
    request["assignment_key"] = str(assignment_key)

    def guard(db):
        authorize(db); _allowed(context)
        _lock(db, "product-tax", context, payload.product_id)
        _product_scope(db, context, payload.product_id)
        if payload.expected_version and _assignment_header(
                db, context, assignment_key, lock=True) is None:
            raise LookupError("Product tax assignment not found")

    def effect(db):
        tax_header = _tax_header(db, context, payload.tax_rule_key, lock=True)
        tax_revision = (_latest_tax(db, context, payload.tax_rule_key)
            if tax_header is not None else None)
        if tax_header is None or tax_revision is None:
            raise LookupError("Tax rule not found")
        if payload.is_enabled and not tax_revision.is_enabled:
            raise PostingConflict("Enabled assignment requires an enabled tax rule")
        header = _assignment_header(db, context, assignment_key, lock=True)
        if header is None:
            if payload.expected_version != 0:
                raise PostingConflict("Product tax assignment changed; reload before saving")
            existing = apply_org_filter(db.query(ProductTaxAssignment).filter_by(
                org_id=context.org_id, product_id=payload.product_id,
                is_deleted=False), ProductTaxAssignment, context).one_or_none()
            if existing is not None:
                raise PostingConflict("Product tax assignment already exists")
            header = ProductTaxAssignment(org_id=context.org_id,
                assignment_key=assignment_key, product_id=payload.product_id,
                creation_operation_key=payload.operation_key,
                created_by=actor_id)
            db.add(header); db.flush(); current = None
        else:
            if header.product_id != payload.product_id:
                raise PostingConflict("Product tax assignment target is immutable")
            current = _latest_assignment(db, context, assignment_key)
        version = current.version if current else 0
        if version != payload.expected_version:
            raise PostingConflict("Product tax assignment changed; reload before saving")
        if (current is not None and current.tax_rule_key == payload.tax_rule_key
                and current.is_enabled is payload.is_enabled):
            raise ValueError("Product tax assignment has no changes")
        revision = ProductTaxAssignmentRevision(org_id=context.org_id,
            assignment_key=assignment_key, version=version + 1,
            operation_key=payload.operation_key,
            tax_rule_key=payload.tax_rule_key,
            is_enabled=payload.is_enabled, reason=payload.reason,
            created_by=actor_id)
        db.add(revision); db.flush()
        result = {"assignment_key": str(assignment_key),
            "version": revision.version}
        return PostingEffect(result,
            {"kind": "sales.product-tax-assignment.saved", **result})

    return execute_once(factory, context, actor_id, payload.operation_key,
        "sales.product-tax-assignment.save.v1", request, effect,
        authorize=guard)


def _agreement_header(db, context, agreement_key, *, lock=False):
    query = apply_org_filter(db.query(CustomerPriceAgreement).filter_by(
        org_id=context.org_id, agreement_key=agreement_key,
        is_deleted=False), CustomerPriceAgreement, context)
    return (query.populate_existing().with_for_update() if lock else query).one_or_none()


def _latest_agreement(db, context, agreement_key):
    return apply_org_filter(db.query(CustomerPriceAgreementRevision).filter_by(
        org_id=context.org_id, agreement_key=agreement_key,
        is_deleted=False), CustomerPriceAgreementRevision, context).order_by(
            CustomerPriceAgreementRevision.version.desc()).first()


def _agreement_read(header, revision):
    return CustomerPriceAgreementRead(agreement_key=header.agreement_key,
        customer_key=header.customer_key, branch_id=header.branch_id,
        product_id=header.product_id, unit=header.unit,
        version=revision.version,
        gross_unit_scr=str(revision.gross_unit_scr),
        valid_from=revision.valid_from, valid_until=revision.valid_until,
        terms_reference=revision.terms_reference,
        is_enabled=revision.is_enabled)


def read_customer_price_agreement(db, context, agreement_key, *, authorize):
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    authorize(db); _allowed(context)
    header = _agreement_header(db, context, agreement_key)
    if header is None:
        raise LookupError("Customer price agreement not found")
    return _agreement_read(header,
        _latest_agreement(db, context, agreement_key))


def list_customer_price_agreements(db, context, *, page, limit, authorize,
                                   customer_key=None, branch_id=None,
                                   product_id=None, unit=None):
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    authorize(db); _allowed(context)
    latest = db.query(CustomerPriceAgreementRevision.agreement_key,
        func.max(CustomerPriceAgreementRevision.version).label("version")).filter(
        CustomerPriceAgreementRevision.org_id == context.org_id,
        CustomerPriceAgreementRevision.is_deleted.is_(False)).group_by(
            CustomerPriceAgreementRevision.agreement_key).subquery()
    query = db.query(CustomerPriceAgreement, CustomerPriceAgreementRevision).join(
        latest, CustomerPriceAgreement.agreement_key == latest.c.agreement_key).join(
        CustomerPriceAgreementRevision,
        (CustomerPriceAgreementRevision.agreement_key == latest.c.agreement_key)
        & (CustomerPriceAgreementRevision.version == latest.c.version)
        & (CustomerPriceAgreementRevision.org_id == context.org_id)).filter(
        CustomerPriceAgreement.org_id == context.org_id,
        CustomerPriceAgreement.is_deleted.is_(False))
    if customer_key is not None:
        query = query.filter(CustomerPriceAgreement.customer_key == customer_key)
    if branch_id is not None:
        query = query.filter(CustomerPriceAgreement.branch_id == branch_id)
    if product_id is not None:
        query = query.filter(CustomerPriceAgreement.product_id == product_id)
    if unit is not None:
        query = query.filter(CustomerPriceAgreement.unit == unit)
    return _page(query.order_by(CustomerPriceAgreement.customer_key,
        CustomerPriceAgreement.branch_id, CustomerPriceAgreement.product_id,
        CustomerPriceAgreement.unit), page, limit, _agreement_read)


def _customer_scope(db, context, customer_key, *, lock=True):
    query = apply_org_filter(db.query(RetailCustomer).filter_by(
        org_id=context.org_id, customer_key=customer_key,
        is_deleted=False), RetailCustomer, context)
    customer = (query.with_for_update() if lock else query).one_or_none()
    if customer is None:
        raise LookupError("Customer not found")
    return customer


def _same_agreement_config(row, payload):
    config = payload.config
    return (row.gross_unit_scr == Decimal(config.gross_unit_scr)
        and row.valid_from == config.valid_from
        and row.valid_until == config.valid_until
        and row.terms_reference == config.terms_reference
        and row.is_enabled is config.is_enabled)


def save_customer_price_agreement(factory, context, actor_id,
                                  agreement_key: UUID,
                                  payload: CustomerPriceAgreementSave, *, authorize):
    if not isinstance(payload, CustomerPriceAgreementSave):
        raise ValueError("Typed customer price agreement save required")
    payload = CustomerPriceAgreementSave.model_validate(payload.model_dump())
    if not isinstance(agreement_key, UUID) or not agreement_key.int:
        raise ValueError("Nonzero customer price agreement key required")
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    request = payload.model_dump(mode="json", exclude={"operation_key"})
    request["agreement_key"] = str(agreement_key)

    def guard(db):
        authorize(db); _allowed(context)
        identity = (f"{payload.customer_key}:{payload.branch_id}:"
            f"{payload.product_id}:{payload.unit}")
        _lock(db, "customer-price", context, identity)
        _price_scope(db, context, payload.branch_id, payload.product_id)
        _customer_scope(db, context, payload.customer_key)
        if payload.expected_version and _agreement_header(
                db, context, agreement_key, lock=True) is None:
            raise LookupError("Customer price agreement not found")

    def effect(db):
        header = _agreement_header(db, context, agreement_key, lock=True)
        if header is None:
            if payload.expected_version != 0:
                raise PostingConflict("Customer price agreement changed; reload before saving")
            existing = apply_org_filter(db.query(CustomerPriceAgreement).filter_by(
                org_id=context.org_id, customer_key=payload.customer_key,
                branch_id=payload.branch_id, product_id=payload.product_id,
                unit=payload.unit, is_deleted=False),
                CustomerPriceAgreement, context).one_or_none()
            if existing is not None:
                raise PostingConflict("Customer price agreement already exists")
            header = CustomerPriceAgreement(org_id=context.org_id,
                agreement_key=agreement_key,
                customer_key=payload.customer_key,
                branch_id=payload.branch_id, product_id=payload.product_id,
                unit=payload.unit,
                creation_operation_key=payload.operation_key,
                created_by=actor_id)
            db.add(header); db.flush(); current = None
        else:
            if (header.customer_key != payload.customer_key
                    or header.branch_id != payload.branch_id
                    or header.product_id != payload.product_id
                    or header.unit != payload.unit):
                raise PostingConflict("Customer price agreement target is immutable")
            current = _latest_agreement(db, context, agreement_key)
        version = current.version if current else 0
        if version != payload.expected_version:
            raise PostingConflict("Customer price agreement changed; reload before saving")
        if current is not None and _same_agreement_config(current, payload):
            raise ValueError("Customer price agreement has no changes")
        config = payload.config
        revision = CustomerPriceAgreementRevision(org_id=context.org_id,
            agreement_key=agreement_key, version=version + 1,
            operation_key=payload.operation_key,
            gross_unit_scr=Decimal(config.gross_unit_scr),
            valid_from=config.valid_from, valid_until=config.valid_until,
            terms_reference=config.terms_reference,
            is_enabled=config.is_enabled, reason=payload.reason,
            created_by=actor_id)
        db.add(revision); db.flush()
        result = {"agreement_key": str(agreement_key),
            "version": revision.version}
        return PostingEffect(result,
            {"kind": "sales.customer-price-agreement.saved", **result})

    return execute_once(factory, context, actor_id, payload.operation_key,
        "sales.customer-price-agreement.save.v1", request, effect,
        authorize=guard)


def resolve_pricing_line(db, context, *, line_key: UUID, branch_id: int,
                         product_id: int, unit: str, quantity: Decimal,
                         priced_at: datetime, customer_key: UUID | None,
                         authorize):
    """Resolve current eligible snapshots; callers persist them before posting."""
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    authorize(db); _allowed(context)
    if (not isinstance(priced_at, datetime) or priced_at.tzinfo is None
            or priced_at.utcoffset() is None):
        raise ValueError("Pricing time must include a timezone")
    _price_scope(db, context, branch_id, product_id, lock=False)
    price_header = apply_org_filter(db.query(BranchProductPrice).filter_by(
        org_id=context.org_id, branch_id=branch_id, product_id=product_id,
        unit=unit, is_deleted=False), BranchProductPrice, context).one_or_none()
    if price_header is None:
        raise LookupError("Branch product price is not configured")
    price = _price_read(price_header,
        _latest_price(db, context, price_header.price_key))
    store = store_price_candidate(price)
    assignment_header = apply_org_filter(db.query(ProductTaxAssignment).filter_by(
        org_id=context.org_id, product_id=product_id, is_deleted=False),
        ProductTaxAssignment, context).one_or_none()
    if assignment_header is None:
        raise LookupError("Product tax treatment is not configured")
    assignment = _assignment_read(assignment_header,
        _latest_assignment(db, context, assignment_header.assignment_key))
    if not assignment.is_enabled:
        raise PostingConflict("Product tax treatment is disabled")
    tax = read_tax_rule(db, context, assignment.tax_rule_key,
        authorize=lambda session: None)
    tax_value = tax_snapshot(tax)
    prices = [store]
    if customer_key is not None:
        _customer_scope(db, context, customer_key, lock=False)
        agreement_header = apply_org_filter(db.query(CustomerPriceAgreement).filter_by(
            org_id=context.org_id, customer_key=customer_key,
            branch_id=branch_id, product_id=product_id, unit=unit,
            is_deleted=False),
            CustomerPriceAgreement, context).one_or_none()
        if agreement_header is not None:
            agreement = _agreement_read(agreement_header,
                _latest_agreement(db, context, agreement_header.agreement_key))
            if (agreement.is_enabled and agreement.valid_from <= priced_at
                    and (agreement.valid_until is None
                         or priced_at < agreement.valid_until)):
                prices.append(PriceCandidate("CUSTOMER_AGREEMENT",
                    str(agreement.agreement_key), agreement.version,
                    Decimal(agreement.gross_unit_scr)).validate())
    return PricingLineInput(line_key=line_key, product_id=product_id,
        quantity=quantity, eligible_prices=tuple(prices), tax=tax_value,
        floor_gross_unit_scr=(Decimal(price.floor_gross_unit_scr)
            if price.floor_gross_unit_scr is not None else None)).validate()
