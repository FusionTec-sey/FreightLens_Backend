"""Atomic retail sale posting; payment confirmation is not physical collection."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, Context, localcontext
from hashlib import sha256
from uuid import UUID, uuid5

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from Model.containermgmt.Inventory.BranchCounter import BranchCounter
from Model.containermgmt.Inventory.BranchCounter import CounterSettingsRevision
from Model.containermgmt.Inventory.BranchSettings import BranchSettingsRevision
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseUse
from Model.containermgmt.Inventory.SalesReservationSource import SalesReservationSource
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement, StockReservation
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Orders.PaymentConfiguration import (
    BranchReceivingAccount, BranchReceivingAccountRevision,
    PaymentMethod, PaymentMethodRevision,
)
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision, SalesIntentLineRevision
from Model.containermgmt.Orders.SalesPosting import (
    SalesPostingAttempt, SalesPostingTender, SalesCardConfirmation,
    SalesInvoice, SalesInvoiceLine, SalesInvoicePayment,
    SalesInvoiceReservation,
)
from Model.containermgmt.Orders.SalesPricing import (
    BranchProductPrice, CustomerPriceAgreement, ProductTaxAssignment,
    ProductTaxAssignmentRevision, SalesTaxRule, SalesTransactionPricing,
)
from Schema.SalesPostingSchema import (
    SalesPostingAttemptCreate, SalesCardConfirmationAppend,
    SalesPostingFinalize,
)
from Schema.BranchCounterSchema import CounterConfig
from Services.branch_action_context_service import require_branch_action_context
from Services.customer_profile_service import read_customer_profile
from Services.inventory_posting_service import (
    PostingConflict, PostingEffect, execute_once, lock_operation_attempt,
    _json_snapshot,
)
from Services.manager_case_service import consume_case
from Services.payment_configuration_service import require_receiving_account
from Services.sales_price_floor_case_service import floor_binding_from_preview
from Services.sales_pricing_preview_service import (
    preview_sales_pricing, transaction_pricing_payload,
)
from Services.staff_store_assignment_service import (
    latest_assignment, require_staff_store_assignment,
)
from Utils.org_filter import apply_org_filter


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id, model.is_deleted.is_(False)),
        model, context)


def _guard(context, authorize, db):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Sale company scope denied")
    if not callable(authorize):
        raise ValueError("Sale posting authorization guard required")
    authorize(db)


def _digest(value):
    _, encoded = _json_snapshot(value)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _money(value):
    return format(Decimal(value), ".2f")


def _quantity(value):
    return format(Decimal(value), "f")


def _attempt_status(db, context, attempt):
    invoice = _owned(db, SalesInvoice, context).filter_by(
        attempt_key=attempt.attempt_key).one_or_none()
    if invoice is not None:
        return "POSTED", invoice.invoice_key
    tenders = _owned(db, SalesPostingTender, context).filter_by(
        attempt_key=attempt.attempt_key).order_by(SalesPostingTender.tender_key).all()
    state = "READY"
    for tender in tenders:
        if tender.kind != "CARD":
            continue
        latest = _owned(db, SalesCardConfirmation, context).filter_by(
            attempt_key=attempt.attempt_key, tender_key=tender.tender_key
        ).order_by(SalesCardConfirmation.sequence.desc()).first()
        if latest is not None and latest.outcome == "DECLINED":
            return "DECLINED", None
        if latest is None or latest.outcome != "CONFIRMED":
            state = "AWAITING_CARD"
    return state, None


def _attempt_read(db, context, attempt):
    tenders = _owned(db, SalesPostingTender, context).filter_by(
        attempt_key=attempt.attempt_key).order_by(SalesPostingTender.tender_key).all()
    confirmations = _owned(db, SalesCardConfirmation, context).filter_by(
        attempt_key=attempt.attempt_key).order_by(
        SalesCardConfirmation.tender_key, SalesCardConfirmation.sequence).all()
    status, invoice_key = _attempt_status(db, context, attempt)
    return dict(
        attempt_key=attempt.attempt_key, operation_key=attempt.operation_key,
        document_key=attempt.document_key, draft_version=attempt.draft_version,
        pricing_snapshot_key=attempt.pricing_snapshot_key,
        pricing_fingerprint=attempt.pricing_fingerprint,
        branch_id=attempt.branch_id, counter_id=attempt.counter_id,
        counter_key=attempt.counter_key,
        branch_settings_version=attempt.branch_settings_version,
        counter_settings_version=attempt.counter_settings_version,
        assignment_version=attempt.assignment_version,
        business_date=attempt.business_date,
        customer_key=attempt.customer_key,
        customer_version=attempt.customer_version,
        currency=attempt.currency, gross_total_scr=_money(attempt.gross_total_scr),
        net_total_scr=_money(attempt.net_total_scr),
        tax_total_scr=_money(attempt.tax_total_scr), status=status,
        created_at=attempt.created_at, invoice_key=invoice_key,
        tenders=[dict(tender_key=row.tender_key, method_key=row.method_key,
            method_version=row.method_version, mapping_key=row.mapping_key,
            mapping_version=row.mapping_version, kind=row.kind,
            amount_scr=_money(row.amount_scr))
            for row in tenders],
        card_confirmations=[dict(confirmation_key=row.confirmation_key,
            tender_key=row.tender_key, sequence=row.sequence,
            outcome=row.outcome,
            provider_reference_hash=row.provider_reference_hash,
            observed_at=row.observed_at) for row in confirmations],
    )


def read_posting_attempt(db, context, attempt_key, *, authorize, lock=False):
    _guard(context, authorize, db)
    query = _owned(db, SalesPostingAttempt, context).filter_by(
        attempt_key=UUID(str(attempt_key)))
    attempt = (query.with_for_update() if lock else query).one_or_none()
    if attempt is None:
        raise LookupError("Sales posting attempt not found")
    return _attempt_read(db, context, attempt)


def read_posting_options(db, context, actor_id, document_key, draft_version, *,
                         authorize):
    """Return checkout-safe exact inputs without exposing ledger accounts."""
    _guard(context, authorize, db)
    if type(draft_version) is not int or draft_version <= 0:
        raise ValueError("Positive draft version required")
    draft = _draft_snapshot(db, context, UUID(str(document_key)), draft_version,
        authorize=authorize)
    branch_id = draft["branch_id"]
    assignment = latest_assignment(db, context, actor_id)
    if assignment is None:
        raise PermissionError("Working-store assignment missing")
    assignment = require_staff_store_assignment(db, context, actor_id,
        branch_id=branch_id, expected_version=assignment.version)
    settings = _owned(db, BranchSettingsRevision, context).filter_by(
        branch_id=branch_id).order_by(
        BranchSettingsRevision.version.desc()).first()
    if settings is None:
        raise PostingConflict("Branch trading settings are required")

    counters = []
    roots = _owned(db, BranchCounter, context).filter_by(
        branch_id=branch_id).order_by(BranchCounter.code).all()
    for counter in roots:
        revision = _owned(db, CounterSettingsRevision, context).filter_by(
            counter_id=counter.id).order_by(
            CounterSettingsRevision.version.desc()).first()
        if revision is None:
            continue
        config = CounterConfig.model_validate(revision.config)
        if config.is_enabled and config.purpose in ("CHECKOUT", "BOTH"):
            counters.append(dict(counter_key=counter.counter_key,
                code=counter.code, name=config.name, version=revision.version))

    payment_methods = []
    mappings = _owned(db, BranchReceivingAccount, context).filter_by(
        branch_id=branch_id).order_by(
        BranchReceivingAccount.mapping_key).all()
    for mapping in mappings:
        mapping_revision = _owned(db, BranchReceivingAccountRevision, context).filter_by(
            mapping_key=mapping.mapping_key).order_by(
            BranchReceivingAccountRevision.version.desc()).first()
        method = _owned(db, PaymentMethod, context).filter_by(
            method_key=mapping.method_key).one_or_none()
        method_revision = (_owned(db, PaymentMethodRevision, context).filter_by(
            method_key=mapping.method_key).order_by(
            PaymentMethodRevision.version.desc()).first() if method else None)
        if (mapping_revision is None or method_revision is None
                or not mapping_revision.is_enabled or not method_revision.is_enabled
                or method_revision.kind not in ("CASH", "CARD")):
            continue
        payment_methods.append(dict(method_key=method.method_key,
            method_version=method_revision.version, code=method.code,
            label=method_revision.label, kind=method_revision.kind,
            mapping_key=mapping.mapping_key,
            mapping_version=mapping_revision.version))

    valid_lines = {UUID(str(line["line_key"])) for line in draft["lines"]}
    sources = _owned(db, SalesReservationSource, context).filter_by(
        document_key=UUID(str(document_key)), version=draft_version).order_by(
        SalesReservationSource.line_key,
        SalesReservationSource.reservation_key).all()
    reservation_keys = [row.reservation_key for row in sources]
    holds = {row.reservation_key: row for row in _owned(
        db, StockReservation, context).filter(
        StockReservation.reservation_key.in_(reservation_keys)).all()} if reservation_keys else {}
    reservations = []
    for source in sources:
        hold = holds.get(source.reservation_key)
        if hold is None or source.line_key not in valid_lines:
            continue
        remaining = Decimal(hold.quantity) - Decimal(hold.released)
        if remaining > 0:
            reservations.append(dict(source_line_key=source.line_key,
                reservation_key=source.reservation_key,
                quantity=_quantity(remaining)))
    existing = _owned(db, SalesPostingAttempt, context).filter_by(
        document_key=UUID(str(document_key)),
        draft_version=draft_version).one_or_none()
    existing_status = existing_invoice_key = None
    if existing is not None:
        existing_status, existing_invoice_key = _attempt_status(
            db, context, existing)
        if existing_status != "POSTED" and existing.created_by != actor_id:
            raise PermissionError(
                "This draft checkout is controlled by another salesperson")
    return dict(document_key=UUID(str(document_key)),
        draft_version=draft_version, branch_id=branch_id,
        branch_settings_version=settings.version,
        assignment_version=assignment.version, counters=counters,
        payment_methods=payment_methods, reservations=reservations,
        existing_attempt_key=(existing.attempt_key if existing else None),
        existing_operation_key=(existing.operation_key if existing else None),
        existing_status=existing_status,
        existing_invoice_key=existing_invoice_key)


def _lock_branch(db, context, branch_id):
    branch = _owned(db, InventoryBranch, context).filter_by(
        id=branch_id, is_active=True).with_for_update().one_or_none()
    if branch is None:
        raise PermissionError("Selling branch is unavailable")
    return branch


def _lock_pricing_sources(db, context, pricing, customer_key):
    lines = pricing.pricing["lines"]
    product_ids = sorted({int(line["product_id"]) for line in lines})
    products = _owned(db, Product, context).filter(
        Product.id.in_(product_ids), Product.status == "active",
        Product.is_shared.is_(False)).order_by(Product.id).with_for_update(of=Product).all()
    if [row.id for row in products] != product_ids:
        raise PostingConflict("A priced product is no longer available")
    price_keys = sorted({UUID(line["store_price_key"]) for line in lines}, key=str)
    prices = _owned(db, BranchProductPrice, context).filter(
        BranchProductPrice.price_key.in_(price_keys)).order_by(
        BranchProductPrice.price_key).with_for_update().all()
    if len(prices) != len(price_keys):
        raise PostingConflict("A store price identity is unavailable")
    # Match agreement writers' product -> customer -> agreement lock order.
    customer = _owned(db, RetailCustomer, context).filter_by(
        customer_key=customer_key).with_for_update().one_or_none()
    if customer is None:
        raise PostingConflict("The priced customer is unavailable")
    agreement_keys = sorted({UUID(line["selected_reference_key"])
        for line in lines if line["selected_source"] == "CUSTOMER_AGREEMENT"}, key=str)
    if agreement_keys:
        agreements = _owned(db, CustomerPriceAgreement, context).filter(
            CustomerPriceAgreement.agreement_key.in_(agreement_keys)).order_by(
            CustomerPriceAgreement.agreement_key).with_for_update().all()
        if len(agreements) != len(agreement_keys):
            raise PostingConflict("An agreed customer price identity is unavailable")
    # Product locks above prevent assignment writers from advancing. Resolve the
    # tax parents first, matching configuration's tax-header -> assignment-header
    # lock order, then lock the assignment identities themselves.
    assignments = _owned(db, ProductTaxAssignment, context).filter(
        ProductTaxAssignment.product_id.in_(product_ids)).order_by(
        ProductTaxAssignment.product_id).all()
    if len(assignments) != len(product_ids):
        raise PostingConflict("A product tax assignment is unavailable")
    tax_keys = []
    for header in assignments:
        revision = _owned(db, ProductTaxAssignmentRevision, context).filter_by(
            assignment_key=header.assignment_key).order_by(
            ProductTaxAssignmentRevision.version.desc()).first()
        if revision is None or not revision.is_enabled:
            raise PostingConflict("A product tax assignment is disabled")
        tax_keys.append(revision.tax_rule_key)
    taxes = _owned(db, SalesTaxRule, context).filter(
        SalesTaxRule.tax_rule_key.in_(sorted(set(tax_keys), key=str))).order_by(
        SalesTaxRule.tax_rule_key).with_for_update().all()
    if len(taxes) != len(set(tax_keys)):
        raise PostingConflict("A sales tax rule is unavailable")
    locked_assignments = _owned(db, ProductTaxAssignment, context).filter(
        ProductTaxAssignment.product_id.in_(product_ids)).order_by(
        ProductTaxAssignment.product_id).with_for_update().all()
    if [row.assignment_key for row in locked_assignments] != [
            row.assignment_key for row in assignments]:
        raise PostingConflict("A product tax assignment changed")
    return {row.id: row for row in products}


def _current_pricing(db, context, attempt, pricing, *, authorize, now):
    draft = _draft_snapshot(db, context, attempt.document_key,
        attempt.draft_version, authorize=authorize)
    _lock_pricing_sources(db, context, pricing, attempt.customer_key)
    preview = preview_sales_pricing(db, context, draft, priced_at=now,
        authorize=authorize)
    _, fingerprint = transaction_pricing_payload(preview)
    if fingerprint != attempt.pricing_fingerprint:
        raise PostingConflict("Price or tax configuration changed; prepare a new posting attempt")
    return draft, preview


def _draft_snapshot(db, context, document_key, version, *, authorize):
    parent = _owned(db, SalesIntent, context).filter_by(
        document_key=document_key).with_for_update().one_or_none()
    if parent is None:
        raise LookupError("Sales draft not found")
    latest = _owned(db, SalesIntentRevision, context).filter_by(
        document_key=document_key).order_by(SalesIntentRevision.version.desc()).first()
    if latest is None or latest.version != version:
        raise PostingConflict("Sales draft changed; start a new posting attempt")
    from Services.sales_intent_service import get_sales_intent
    return get_sales_intent(db, context, document_key, version=version,
        authorize=authorize)


def create_posting_attempt(db, context, actor_id, payload, *, authorize,
                           instant=None):
    """Freeze a recoverable exact tender plan; no invoice or money is posted."""
    if not db.in_transaction():
        raise ValueError("Posting-attempt creation requires a caller transaction")
    payload = SalesPostingAttemptCreate.model_validate(payload)
    request = payload.model_dump(mode="json")
    digest = _digest(request)
    lock_operation_attempt(db, context, payload.operation_key)
    _guard(context, authorize, db)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": (f"sales-post-attempt:{context.org_id}:"
                 f"{payload.document_key}:{payload.expected_draft_version}")})
    existing = _owned(db, SalesPostingAttempt, context).filter(or_(
        SalesPostingAttempt.attempt_key == payload.attempt_key,
        SalesPostingAttempt.operation_key == payload.operation_key,
        (SalesPostingAttempt.document_key == payload.document_key)
        & (SalesPostingAttempt.draft_version == payload.expected_draft_version),
        SalesPostingAttempt.pricing_snapshot_key == payload.pricing_snapshot_key,
    )).with_for_update().one_or_none()
    if existing is not None:
        if (existing.attempt_key != payload.attempt_key
                or existing.operation_key != payload.operation_key
                or existing.request_digest != digest
                or existing.created_by != actor_id):
            raise PostingConflict("Draft, pricing or operation already belongs to another posting attempt")
        result = _attempt_read(db, context, existing)
        return dict(attempt_key=existing.attempt_key,
                    status=result["status"], replayed=True)
    now = instant or datetime.now(timezone.utc)
    draft = _draft_snapshot(db, context, payload.document_key,
        payload.expected_draft_version, authorize=authorize)
    branch = _lock_branch(db, context, draft["branch_id"])
    action = require_branch_action_context(db, context,
        branch_id=draft["branch_id"], counter_key=payload.counter_key,
        branch_version=payload.expected_branch_settings_version,
        counter_version=payload.expected_counter_settings_version,
        instant=now, action="CHECKOUT", authorize=authorize)
    assignment = require_staff_store_assignment(db, context, actor_id,
        branch_id=draft["branch_id"],
        expected_version=payload.expected_assignment_version)
    pricing = _owned(db, SalesTransactionPricing, context).filter_by(
        pricing_snapshot_key=payload.pricing_snapshot_key).with_for_update().one_or_none()
    if (pricing is None or pricing.document_key != payload.document_key
            or pricing.draft_version != payload.expected_draft_version
            or pricing.pricing_fingerprint != payload.expected_pricing_fingerprint):
        raise PostingConflict("Exact prepared pricing is unavailable")
    provisional = type("Attempt", (), dict(document_key=payload.document_key,
        draft_version=payload.expected_draft_version,
        pricing_fingerprint=pricing.pricing_fingerprint,
        customer_key=UUID(draft["customer_key"])))
    _current_pricing(db, context, provisional, pricing,
        authorize=authorize, now=now)
    customer = read_customer_profile(db, context, UUID(draft["customer_key"]),
        version=draft["customer_version"], authorize=authorize,
        lock=True)
    tenders = []
    total = Decimal(0)
    for item in sorted(payload.tenders, key=lambda row: str(row.method_key)):
        resolved = require_receiving_account(db, context, draft["branch_id"],
            item.method_key, expected_method_version=item.expected_method_version,
            expected_mapping_key=item.mapping_key,
            expected_mapping_version=item.expected_mapping_version,
            authorize=authorize)
        amount = Decimal(item.amount_scr)
        total += amount
        tenders.append((item, resolved, amount))
    if total != pricing.gross_total_scr:
        raise PostingConflict("Payment plan must equal the exact invoice total")
    attempt = SalesPostingAttempt(org_id=context.org_id,
        attempt_key=payload.attempt_key, operation_key=payload.operation_key,
        request_digest=digest, document_key=payload.document_key,
        draft_version=payload.expected_draft_version,
        pricing_snapshot_key=payload.pricing_snapshot_key,
        pricing_fingerprint=pricing.pricing_fingerprint,
        branch_id=draft["branch_id"], counter_id=action.counter_id,
        counter_key=payload.counter_key,
        branch_settings_version=action.branch_settings_version,
        counter_settings_version=action.counter_settings_version,
        assignment_version=assignment.version,
        business_date=action.business_date,
        customer_key=UUID(draft["customer_key"]),
        customer_version=customer.version, currency=pricing.currency,
        gross_total_scr=pricing.gross_total_scr,
        net_total_scr=pricing.net_total_scr,
        tax_total_scr=pricing.tax_total_scr, created_by=actor_id)
    db.add(attempt); db.flush()
    for item, resolved, amount in tenders:
        db.add(SalesPostingTender(org_id=context.org_id,
            tender_key=item.tender_key, attempt_key=attempt.attempt_key,
            method_key=item.method_key,
            method_version=resolved["method_version"],
            mapping_key=item.mapping_key,
            mapping_version=resolved["version"], kind=resolved["method_kind"],
            account_ref=resolved["account_ref"], amount_scr=amount,
            created_by=actor_id))
    db.flush()
    status, _ = _attempt_status(db, context, attempt)
    return dict(attempt_key=attempt.attempt_key, status=status, replayed=False)


def append_card_confirmation(db, context, actor_id, payload, *, authorize):
    """Record external evidence once; never calls a card provider."""
    if not db.in_transaction():
        raise ValueError("Card confirmation requires a caller transaction")
    payload = SalesCardConfirmationAppend.model_validate(payload)
    request = payload.model_dump(mode="json")
    digest = _digest(request)
    lock_operation_attempt(db, context, payload.confirmation_key)
    _guard(context, authorize, db)
    existing = _owned(db, SalesCardConfirmation, context).filter_by(
        confirmation_key=payload.confirmation_key).one_or_none()
    if existing is not None:
        if (existing.attempt_key != payload.attempt_key
                or existing.tender_key != payload.tender_key
                or existing.request_digest != digest
                or existing.created_by != actor_id):
            raise PostingConflict("Confirmation key belongs to another observation")
        attempt = _owned(db, SalesPostingAttempt, context).filter_by(
            attempt_key=payload.attempt_key).one()
        return _attempt_read(db, context, attempt)
    attempt = _owned(db, SalesPostingAttempt, context).filter_by(
        attempt_key=payload.attempt_key).with_for_update().one_or_none()
    if attempt is None:
        raise LookupError("Sales posting attempt not found")
    confirmer_assignment = latest_assignment(db, context, actor_id)
    if confirmer_assignment is None:
        raise PermissionError("Card confirmer has no working-store assignment")
    require_staff_store_assignment(db, context, actor_id,
        branch_id=attempt.branch_id,
        expected_version=confirmer_assignment.version)
    if _owned(db, SalesInvoice, context).filter_by(
            attempt_key=attempt.attempt_key).first():
        raise PostingConflict("Posted card evidence cannot be changed")
    tender = _owned(db, SalesPostingTender, context).filter_by(
        attempt_key=attempt.attempt_key,
        tender_key=payload.tender_key).with_for_update().one_or_none()
    if tender is None or tender.kind != "CARD":
        raise LookupError("Card tender not found")
    db.add(SalesCardConfirmation(org_id=context.org_id,
        confirmation_key=payload.confirmation_key,
        attempt_key=attempt.attempt_key, tender_key=tender.tender_key,
        sequence=payload.expected_sequence, request_digest=digest,
        outcome=payload.outcome,
        provider_reference_hash=payload.provider_reference_hash,
        created_by=actor_id))
    db.flush()
    return _attempt_read(db, context, attempt)


def _confirmed_cards(db, context, attempt_key):
    result = {}
    cards = _owned(db, SalesPostingTender, context).filter_by(
        attempt_key=attempt_key, kind="CARD").order_by(
        SalesPostingTender.tender_key).all()
    for tender in cards:
        latest = _owned(db, SalesCardConfirmation, context).filter_by(
            attempt_key=attempt_key, tender_key=tender.tender_key
        ).order_by(SalesCardConfirmation.sequence.desc()).with_for_update().first()
        if latest is None or latest.outcome != "CONFIRMED":
            raise PostingConflict("Every card tender needs confirmed external evidence")
        result[tender.tender_key] = latest
    return result


def _reservation_plan(db, context, attempt, payload, draft_lines):
    requested = {row.reservation_key: row for row in payload.reservations}
    reservations = _owned(db, StockReservation, context).filter(
        StockReservation.reservation_key.in_(sorted(requested, key=str))
    ).order_by(StockReservation.balance_id, StockReservation.reservation_key).all()
    if len(reservations) != len(requested):
        raise PostingConflict("A named stock reservation is unavailable")
    balance_ids = sorted({row.balance_id for row in reservations})
    balances = _owned(db, StockBalance, context).filter(
        StockBalance.id.in_(balance_ids)).order_by(StockBalance.id).with_for_update().all()
    by_balance = {row.id: row for row in balances}
    reservations = _owned(db, StockReservation, context).filter(
        StockReservation.reservation_key.in_(sorted(requested, key=str))
    ).order_by(StockReservation.balance_id,
        StockReservation.reservation_key).with_for_update().all()
    sources = {row.reservation_key: row for row in _owned(
        db, SalesReservationSource, context).filter(
        SalesReservationSource.reservation_key.in_(sorted(requested, key=str))).all()}
    line_totals = defaultdict(Decimal)
    plan = []
    for reservation in reservations:
        item = requested[reservation.reservation_key]
        source = sources.get(reservation.reservation_key)
        balance = by_balance.get(reservation.balance_id)
        quantity = Decimal(item.quantity)
        if (source is None or balance is None
                or source.document_key != attempt.document_key
                or source.version != attempt.draft_version
                or source.line_key != item.source_line_key
                or reservation.quantity - reservation.released != quantity):
            raise PostingConflict("Reservation no longer matches the exact draft demand")
        line = draft_lines.get(source.line_key)
        if line is None or balance.product_id != line.product_id:
            raise PostingConflict("Reservation stock does not match the invoice line")
        if balance.branch_id != attempt.branch_id:
            movement = _owned(db, StockMovement, context).filter_by(
                reservation_id=reservation.id, balance_id=balance.id,
                kind="RESERVE").order_by(StockMovement.id.desc()).first()
            approved = (movement is not None and _owned(db, ManagerCaseUse, context)
                .join(ManagerCase, (ManagerCase.id == ManagerCaseUse.case_id)
                    & (ManagerCase.org_id == ManagerCaseUse.org_id))
                .filter(ManagerCase.action == "inventory.fulfilment.other-store",
                    ManagerCaseUse.operation_key == movement.operation_key).first())
            if not approved:
                raise PermissionError("Other-store stock requires its exact consumed approval")
        line_totals[source.line_key] += quantity
        plan.append((reservation, source, quantity))
    for key, line in draft_lines.items():
        if line_totals[key] != line.base_quantity:
            raise PostingConflict("Every invoice line requires exact active reserved quantity")
    return plan


def _next_invoice_number(db, context, branch_id, business_date):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"sales-invoice-number:{context.org_id}:{branch_id}:{business_date.isoformat()}"})
    count = _owned(db, SalesInvoice, context).filter_by(
        branch_id=branch_id, business_date=business_date).count()
    return f"INV-{branch_id:04d}-{business_date:%Y%m%d}-{count + 1:06d}"


def finalize_posting_attempt(factory, context, actor_id, payload, *, authorize,
                             instant=None):
    payload = SalesPostingFinalize.model_validate(payload)
    now = instant or datetime.now(timezone.utc)
    request = payload.model_dump(mode="json")

    def guard(db):
        _guard(context, authorize, db)
        attempt = _owned(db, SalesPostingAttempt, context).filter_by(
            attempt_key=payload.attempt_key).one_or_none()
        if (attempt is None or attempt.operation_key != payload.operation_key
                or attempt.created_by != actor_id):
            raise PermissionError("Exact owned sales posting attempt required")
        # A completed write retry is deliberately narrower than first posting:
        # it must retain current store authority, but immutable historical price,
        # payment and customer configuration remains readable via the invoice.
        require_staff_store_assignment(db, context, actor_id,
            branch_id=attempt.branch_id,
            expected_version=attempt.assignment_version)

    def effect(db):
        attempt = _owned(db, SalesPostingAttempt, context).filter_by(
            attempt_key=payload.attempt_key).with_for_update().one_or_none()
        if attempt is None or attempt.operation_key != payload.operation_key:
            raise LookupError("Exact sales posting attempt not found")
        if attempt.created_by != actor_id:
            raise PermissionError("Only the posting-attempt owner may finalize it")
        _lock_branch(db, context, attempt.branch_id)
        action = require_branch_action_context(db, context,
            branch_id=attempt.branch_id, counter_key=attempt.counter_key,
            branch_version=attempt.branch_settings_version,
            counter_version=attempt.counter_settings_version,
            instant=now, action="CHECKOUT", authorize=authorize)
        if (action.counter_id != attempt.counter_id
                or action.business_date != attempt.business_date):
            raise PostingConflict("Posting attempt crossed its checkout business context")
        assignment = require_staff_store_assignment(db, context, actor_id,
            branch_id=attempt.branch_id,
            expected_version=attempt.assignment_version)
        pricing = _owned(db, SalesTransactionPricing, context).filter_by(
            pricing_snapshot_key=attempt.pricing_snapshot_key).with_for_update().one()
        draft, preview = _current_pricing(db, context, attempt, pricing,
            authorize=authorize, now=now)
        customer = read_customer_profile(db, context, attempt.customer_key,
            version=attempt.customer_version, authorize=authorize, lock=True)
        tenders = _owned(db, SalesPostingTender, context).filter_by(
            attempt_key=attempt.attempt_key).order_by(
            SalesPostingTender.method_key).all()
        for tender in tenders:
            resolved = require_receiving_account(db, context, attempt.branch_id,
                tender.method_key,
                expected_method_version=tender.method_version,
                expected_mapping_key=tender.mapping_key,
                expected_mapping_version=tender.mapping_version,
                authorize=authorize)
            if (resolved["account_ref"] != tender.account_ref
                    or resolved["method_kind"] != tender.kind):
                raise PostingConflict("Payment configuration changed")
        cards = _confirmed_cards(db, context, attempt.attempt_key)
        if set(payload.expected_card_confirmations) != {
                row.confirmation_key for row in cards.values()}:
            raise PostingConflict("Confirmed card evidence changed; reload before finalizing")
        draft_lines = {row.line_key: row for row in _owned(
            db, SalesIntentLineRevision, context).filter_by(
            document_key=attempt.document_key,
            version=attempt.draft_version).all()}
        reservations = _reservation_plan(db, context, attempt, payload, draft_lines)
        if pricing.requires_floor_approval:
            binding = floor_binding_from_preview(context, attempt.document_key,
                attempt.draft_version, preview)
            consume_case(db, context, actor_id, payload.operation_key,
                case_key=pricing.floor_case_key, binding=binding,
                load_binding=lambda session: floor_binding_from_preview(
                    context, attempt.document_key, attempt.draft_version,
                    _current_pricing(session, context, attempt, pricing,
                        authorize=authorize, now=now)[1]),
                authorize=authorize)
        branch = _owned(db, InventoryBranch, context).filter_by(
            id=attempt.branch_id).one()
        invoice_number = _next_invoice_number(db, context,
            attempt.branch_id, attempt.business_date)
        invoice = SalesInvoice(org_id=context.org_id,
            invoice_key=payload.invoice_key, attempt_key=attempt.attempt_key,
            operation_key=payload.operation_key, invoice_number=invoice_number,
            document_key=attempt.document_key,
            draft_version=attempt.draft_version,
            branch_id=attempt.branch_id, counter_id=attempt.counter_id,
            branch_settings_version=attempt.branch_settings_version,
            counter_settings_version=attempt.counter_settings_version,
            assignment_version=assignment.version,
            customer_key=attempt.customer_key,
            customer_version=attempt.customer_version,
            customer_snapshot=customer.model_dump(mode="json"),
            branch_snapshot={"id": branch.id, "code": branch.code,
                "name": branch.name, "kind": branch.kind},
            business_date=attempt.business_date, currency=attempt.currency,
            gross_total_scr=attempt.gross_total_scr,
            net_total_scr=attempt.net_total_scr,
            tax_total_scr=attempt.tax_total_scr, created_by=actor_id)
        db.add(invoice); db.flush()
        pricing_lines = {UUID(row["line_key"]): row
            for row in pricing.pricing["lines"]}
        products = {row.id: row for row in _owned(db, Product, context).filter(
            Product.id.in_([line.product_id for line in draft_lines.values()])).all()}
        invoice_lines = {}
        for position, line in enumerate(sorted(draft_lines.values(),
                key=lambda row: row.position), 1):
            priced = pricing_lines.get(line.line_key)
            product = products.get(line.product_id)
            if priced is None or product is None:
                raise PostingConflict("Invoice snapshot input is incomplete")
            key = uuid5(invoice.invoice_key, f"line:{line.line_key}")
            invoice_lines[line.line_key] = key
            db.add(SalesInvoiceLine(org_id=context.org_id,
                line_key=key, invoice_key=invoice.invoice_key,
                position=position, document_key=attempt.document_key,
                draft_version=attempt.draft_version,
                source_line_key=line.line_key, product_id=line.product_id,
                product_name=product.name, sku=product.sku,
                policy_version=line.policy_version, quantity=line.quantity,
                unit=line.unit, base_quantity=line.base_quantity,
                base_unit=line.base_unit,
                gross_unit_scr=Decimal(priced["gross_unit_scr"]),
                gross_total_scr=Decimal(priced["gross_scr"]),
                net_total_scr=Decimal(priced["net_scr"]),
                tax_total_scr=Decimal(priced["tax_scr"]),
                tax_treatment=priced["tax_treatment"],
                tax_rate=Decimal(priced["tax_rate"]),
                pricing_snapshot=priced, created_by=actor_id))
        db.flush()
        for tender in tenders:
            confirmation = cards.get(tender.tender_key)
            db.add(SalesInvoicePayment(org_id=context.org_id,
                payment_key=uuid5(invoice.invoice_key, f"payment:{tender.tender_key}"),
                invoice_key=invoice.invoice_key, attempt_key=attempt.attempt_key,
                tender_key=tender.tender_key, kind=tender.kind,
                account_ref=tender.account_ref, amount_scr=tender.amount_scr,
                confirmation_key=(confirmation.confirmation_key
                    if confirmation is not None else None), created_by=actor_id))
        for reservation, source, quantity in reservations:
            db.add(SalesInvoiceReservation(org_id=context.org_id,
                invoice_key=invoice.invoice_key,
                line_key=invoice_lines[source.line_key],
                reservation_key=reservation.reservation_key,
                quantity=quantity, created_by=actor_id))
        db.flush()
        result = {"invoice_key": str(invoice.invoice_key),
            "invoice_number": invoice.invoice_number}
        return PostingEffect(result, {"kind": "sales.invoice.posted", **result,
            "branch_id": invoice.branch_id,
            "business_date": invoice.business_date.isoformat()})

    outcome = execute_once(factory, context, actor_id, payload.operation_key,
        "sales.invoice.post.v1", request, effect, authorize=guard)
    if isinstance(factory, Session):
        invoice = read_invoice(factory, context,
            UUID(outcome.result["invoice_key"]), authorize=authorize)
    else:
        with factory() as db:
            invoice = read_invoice(db, context,
                UUID(outcome.result["invoice_key"]), authorize=authorize)
    return dict(invoice=invoice, replayed=outcome.replayed)


def read_invoice(db, context, invoice_key, *, authorize):
    _guard(context, authorize, db)
    invoice = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=UUID(str(invoice_key))).one_or_none()
    if invoice is None:
        raise LookupError("Sales invoice not found")
    attempt = _owned(db, SalesPostingAttempt, context).filter_by(
        attempt_key=invoice.attempt_key).one()
    lines = _owned(db, SalesInvoiceLine, context).filter_by(
        invoice_key=invoice.invoice_key).order_by(SalesInvoiceLine.position).all()
    payments = _owned(db, SalesInvoicePayment, context).filter_by(
        invoice_key=invoice.invoice_key).order_by(SalesInvoicePayment.payment_key).all()
    reservations = _owned(db, SalesInvoiceReservation, context).filter_by(
        invoice_key=invoice.invoice_key).order_by(
        SalesInvoiceReservation.line_key,
        SalesInvoiceReservation.reservation_key).all()
    from Services.sales_collection_service import invoice_fulfilment_status
    fulfilment_status = invoice_fulfilment_status(
        db, context, invoice.invoice_key)
    return dict(invoice_key=invoice.invoice_key,
        attempt_key=invoice.attempt_key, operation_key=invoice.operation_key,
        invoice_number=invoice.invoice_number,
        document_key=attempt.document_key, draft_version=attempt.draft_version,
        branch_id=invoice.branch_id, counter_id=invoice.counter_id,
        branch_settings_version=invoice.branch_settings_version,
        counter_settings_version=invoice.counter_settings_version,
        assignment_version=invoice.assignment_version,
        customer_key=invoice.customer_key,
        customer_version=invoice.customer_version,
        customer_snapshot=invoice.customer_snapshot,
        branch_snapshot=invoice.branch_snapshot,
        business_date=invoice.business_date, issued_at=invoice.issued_at,
        currency=invoice.currency,
        gross_total_scr=_money(invoice.gross_total_scr),
        net_total_scr=_money(invoice.net_total_scr),
        tax_total_scr=_money(invoice.tax_total_scr),
        payment_status="PAID", fulfilment_status=fulfilment_status,
        lines=[dict(line_key=row.line_key,
            source_line_key=row.source_line_key, position=row.position,
            product_id=row.product_id, product_name=row.product_name,
            sku=row.sku, policy_version=row.policy_version,
            quantity=_quantity(row.quantity), unit=row.unit,
            base_quantity=_quantity(row.base_quantity), base_unit=row.base_unit,
            gross_unit_scr=_quantity(row.gross_unit_scr),
            gross_total_scr=_money(row.gross_total_scr),
            net_total_scr=_money(row.net_total_scr),
            tax_total_scr=_money(row.tax_total_scr),
            tax_treatment=row.tax_treatment, tax_rate=_quantity(row.tax_rate),
            pricing_snapshot=row.pricing_snapshot) for row in lines],
        payments=[dict(payment_key=row.payment_key,
            tender_key=row.tender_key, kind=row.kind,
            amount_scr=_money(row.amount_scr),
            confirmation_key=row.confirmation_key) for row in payments],
        reservations=[dict(line_key=row.line_key,
            reservation_key=row.reservation_key,
            quantity=_quantity(row.quantity)) for row in reservations])


def _posted_invoice_for_draft(db, context, document_key, draft_version, *, authorize):
    _guard(context, authorize, db)
    if type(draft_version) is not int or draft_version <= 0:
        raise ValueError("Positive exact draft version required")
    invoice = _owned(db, SalesInvoice, context).filter_by(
        document_key=UUID(str(document_key)),
        draft_version=draft_version,
    ).one_or_none()
    if invoice is None:
        raise LookupError("Posted sales invoice not found for this draft revision")
    return invoice


def read_invoice_reference_for_draft(
        db, context, document_key, draft_version, *, authorize):
    """Return only the exact posted identity needed by post-sale workspaces."""
    invoice = _posted_invoice_for_draft(
        db, context, document_key, draft_version, authorize=authorize)
    return {
        "invoice_key": invoice.invoice_key,
        "document_key": invoice.document_key,
        "draft_version": invoice.draft_version,
    }


def read_invoice_for_draft(db, context, document_key, draft_version, *, authorize):
    """Resolve one exact posted draft revision without requiring posting authority."""
    invoice = _posted_invoice_for_draft(
        db, context, document_key, draft_version, authorize=authorize)
    return read_invoice(db, context, invoice.invoice_key, authorize=authorize)
