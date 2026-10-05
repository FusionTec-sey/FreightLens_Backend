"""PostgreSQL integration coverage for the T18 return lifecycle.

The existing sales fixture deliberately runs inside one rollback-only root
transaction.  That transaction is not visible to a second connection, so a
threaded competing-claim test would exercise missing fixture data rather than
the production row locks.  The quantity-cap test below therefore covers two
distinct committed savepoint operations sequentially; transaction-level
concurrency remains a later dedicated committed-factory test.
"""
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import Model  # noqa: F401 - populate Base metadata before schema preparation
from Model.Credentials.users import User
from Model.db import Base
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.SalesReturn import (
    CustomerCreditLiabilityEntry,
    SalesCreditNote,
    SalesCreditNoteLine,
    SalesInvoiceDebtApplication,
    SalesReturnAllocation,
    SalesReturnClaim,
)
from Schema.SalesReturnSchema import (
    SalesReturnClaimCreate,
    SalesReturnClaimLineInput,
    SalesReturnCreditNoteCreate,
    SalesReturnReview,
)
from Services.inventory_posting_service import PostingConflict
from Services.sales_return_service import (
    process_return_credit,
    read_credit_note,
    read_return_claim,
    read_return_options,
    read_return_processing_options,
    request_return_claim,
    review_return_claim,
)
from Utils.org_filter import OrgContext
from tests.test_sales_collection import collectible  # noqa: F401
from tests.test_sales_posting import NOW, _create, _finalize, posting  # noqa: F401
from tests.test_sales_transaction_pricing import floor_api  # noqa: F401
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture(scope="module")
def t18_schema(test_engine):
    """Install the replay-safe T18 schema before rollback-only sales fixtures."""
    with test_engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS usercredentials"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS containermgmt"))
        Base.metadata.create_all(connection)

    from Utils import migrate_20261005_sales_returns as migration

    original_engine = migration.engine
    migration.engine = test_engine
    try:
        migration.ensure_sales_returns_schema()
        migration.ensure_sales_returns_schema()
        yield
    finally:
        migration.engine = original_engine


def _run_deferred_guards(db):
    """Execute production deferred constraints inside the fixture savepoint."""
    db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db.execute(text("SET CONSTRAINTS ALL DEFERRED"))


@pytest.fixture
def returnable_sale(t18_schema, collectible):
    f = collectible
    f.collect(quantity="10")
    options = read_return_options(
        f.db, f.context, f.posting_invoice_key, authorize=lambda db: None)
    assert len(options["handovers"]) == 1
    f.return_handover = options["handovers"][0]

    reviewer = User(
        org_id=f.org_a,
        username="return-reviewer-" + uuid4().hex[:16],
        password_hash="unusable-test-only",
    )
    f.db.add(reviewer)
    f.db.flush()
    f.return_reviewer_id = reviewer.id
    f.db.commit()

    def claim_payload(quantity="1.000000", *, return_key=None, operation_key=None):
        return SalesReturnClaimCreate(
            return_key=return_key or uuid4(),
            operation_key=operation_key or uuid4(),
            invoice_key=f.posting_invoice_key,
            expected_invoice_version=1,
            returner_name="Synthetic returning customer",
            returner_contact="+248 000 0000",
            reason="Synthetic invoice-linked return integration test",
            lines=[SalesReturnClaimLineInput(
                invoice_line_key=f.collection_line_key,
                handover_allocation_key=(
                    f.return_handover["handover_allocation_key"]),
                quantity=quantity,
                condition="OPENED",
            )],
        )

    def request(payload):
        f.db.connection()
        outcome = request_return_claim(
            f.db, f.context, f.user.id, payload, authorize=lambda db: None)
        _run_deferred_guards(f.db)
        f.db.commit()
        return outcome

    def review(return_key, operation_key, *, actor_id=None):
        f.db.connection()
        result = review_return_claim(
            f.db,
            f.context,
            actor_id or f.return_reviewer_id,
            return_key,
            SalesReturnReview(
                operation_key=operation_key,
                expected_version=1,
                outcome="APPROVED",
                reason="Synthetic independent return approval",
            ),
            authorize=lambda db: None,
        )
        _run_deferred_guards(f.db)
        f.db.commit()
        return result

    def process(return_key, payload):
        f.db.connection()
        result = process_return_credit(
            f.db,
            f.context,
            f.user.id,
            return_key,
            payload,
            stock_authority=f.stock_claim,
            cost_authority=f.cost_claim,
            authorize=lambda db: None,
        )
        _run_deferred_guards(f.db)
        f.db.commit()
        return result

    f.return_claim_payload = claim_payload
    f.request_return = request
    f.review_return = review
    f.process_return = process
    return f


def _approved_return(f, quantity="1.000000"):
    claim = f.return_claim_payload(quantity)
    requested = f.request_return(claim)
    review_key = uuid4()
    reviewed = f.review_return(claim.return_key, review_key)
    options = read_return_processing_options(
        f.db, f.context, claim.return_key, authorize=lambda db: None)
    process_payload = SalesReturnCreditNoteCreate(
        operation_key=uuid4(),
        expected_claim_version=options["claim_version"],
        expected_option_version=options["option_version"],
        expected_fingerprint=options["fingerprint"],
    )
    return SimpleNamespace(
        claim=claim,
        requested=requested,
        review_key=review_key,
        reviewed=reviewed,
        options=options,
        process_payload=process_payload,
    )


def test_request_independent_review_and_processing_restore_quarantined_value_and_credit(
        returnable_sale):
    f = returnable_sale
    flow = _approved_return(f)
    before = f.db.get(StockBalance, f.collection_balance_id)
    before_snapshot = (
        Decimal(before.on_hand), Decimal(before.quarantined), before.version)

    processed = f.process_return(flow.claim.return_key, flow.process_payload)
    note = processed["credit_note"]
    assert not processed["replayed"]
    assert flow.requested.replayed is False
    assert flow.reviewed["claim"]["status"] == "APPROVED"
    assert flow.reviewed["claim"]["requested_by"] == f.user.id
    assert flow.reviewed["claim"]["review"]["reviewer_id"] == f.return_reviewer_id
    assert f.return_reviewer_id != f.user.id

    balance = f.db.get(StockBalance, f.collection_balance_id)
    assert Decimal(balance.on_hand) == before_snapshot[0] + Decimal("1.000000")
    assert Decimal(balance.quarantined) == before_snapshot[1] + Decimal("1.000000")
    assert balance.version == before_snapshot[2] + 1
    assert f.db.query(StockMovement).filter_by(
        org_id=f.org_a, balance_id=balance.id, kind="RETURN").count() == 1
    returned_value = f.db.query(InventoryValuation).filter_by(
        org_id=f.org_a, balance_id=balance.id, kind="RETURN").one()
    assert Decimal(returned_value.quantity) == Decimal("1.000000")
    assert Decimal(returned_value.goods_value_scr) > 0

    assert note["invoice_debt_applied_scr"] == "0.00"
    assert Decimal(note["customer_credit_scr"]) == Decimal(note["gross_credit_scr"])
    liability = f.db.query(CustomerCreditLiabilityEntry).filter_by(
        org_id=f.org_a, credit_note_key=note["credit_note_key"]).one()
    assert liability.customer_key == f.db.query(SalesCreditNote).filter_by(
        org_id=f.org_a, credit_note_key=note["credit_note_key"]).one().customer_key
    assert Decimal(liability.amount_scr) == Decimal(note["gross_credit_scr"])
    assert f.db.query(SalesInvoiceDebtApplication).filter_by(
        org_id=f.org_a, credit_note_key=note["credit_note_key"]).count() == 0


def test_identical_request_review_and_processing_replay_have_one_effect(returnable_sale):
    f = returnable_sale
    claim = f.return_claim_payload()
    first_request = f.request_return(claim)
    replayed_request = f.request_return(claim)
    assert not first_request.replayed and replayed_request.replayed

    review_key = uuid4()
    first_review = f.review_return(claim.return_key, review_key)
    replayed_review = f.review_return(claim.return_key, review_key)
    assert not first_review["replayed"] and replayed_review["replayed"]

    options = read_return_processing_options(
        f.db, f.context, claim.return_key, authorize=lambda db: None)
    payload = SalesReturnCreditNoteCreate(
        operation_key=uuid4(),
        expected_claim_version=2,
        expected_option_version=1,
        expected_fingerprint=options["fingerprint"],
    )
    first = f.process_return(claim.return_key, payload)
    replay = f.process_return(claim.return_key, payload)
    assert not first["replayed"] and replay["replayed"]
    assert replay["credit_note"] == first["credit_note"]
    assert f.db.query(SalesReturnClaim).filter_by(
        org_id=f.org_a, return_key=claim.return_key).count() == 1
    assert f.db.query(SalesReturnAllocation).filter_by(
        org_id=f.org_a, return_key=claim.return_key).count() == 1
    assert f.db.query(SalesCreditNote).filter_by(
        org_id=f.org_a, return_key=claim.return_key).count() == 1
    assert f.db.query(SalesCreditNoteLine).join(SalesCreditNote).filter(
        SalesCreditNote.org_id == f.org_a,
        SalesCreditNote.return_key == claim.return_key,
    ).count() == 1
    assert f.db.query(CustomerCreditLiabilityEntry).join(SalesCreditNote).filter(
        SalesCreditNote.org_id == f.org_a,
        SalesCreditNote.return_key == claim.return_key,
    ).count() == 1


def test_foreign_organisation_cannot_read_claim_or_credit_note(returnable_sale):
    f = returnable_sale
    flow = _approved_return(f)
    processed = f.process_return(flow.claim.return_key, flow.process_payload)
    foreign = OrgContext(
        current_org_id=f.org_b,
        allowed_org_ids=[f.org_a, f.org_b],
        is_root=True,
    )
    with pytest.raises(LookupError):
        read_return_claim(
            f.db, foreign, flow.claim.return_key, authorize=lambda db: None)
    with pytest.raises(LookupError):
        read_credit_note(
            f.db,
            foreign,
            processed["credit_note"]["credit_note_key"],
            authorize=lambda db: None,
        )


def test_database_trigger_rejects_direct_money_child_append(returnable_sale):
    f = returnable_sale
    flow = _approved_return(f)
    processed = f.process_return(flow.claim.return_key, flow.process_payload)
    note = processed["credit_note"]

    f.db.add(SalesInvoiceDebtApplication(
        org_id=f.org_a,
        credit_note_key=note["credit_note_key"],
        invoice_key=f.posting_invoice_key,
        amount_scr=Decimal("1.00"),
        created_by=f.user.id,
    ))
    with pytest.raises(DBAPIError, match="debt before customer credit"):
        f.db.flush()
        f.db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    f.db.rollback()
    assert f.db.query(SalesInvoiceDebtApplication).filter_by(
        org_id=f.org_a, credit_note_key=note["credit_note_key"]).count() == 0
    assert f.db.query(CustomerCreditLiabilityEntry).filter_by(
        org_id=f.org_a, credit_note_key=note["credit_note_key"]).count() == 1


def test_competing_pending_claims_cannot_exceed_exact_handover_quantity(returnable_sale):
    f = returnable_sale
    first = f.return_claim_payload("6.000000")
    f.request_return(first)
    competing = f.return_claim_payload("5.000000")
    f.db.connection()
    with pytest.raises(PostingConflict, match="Pending and accepted returns exceed"):
        request_return_claim(
            f.db, f.context, f.user.id, competing, authorize=lambda db: None)
    assert f.db.query(SalesReturnClaim).filter_by(org_id=f.org_a).count() == 1
    assert f.db.query(SalesReturnAllocation).filter_by(org_id=f.org_a).count() == 1
    options = read_return_options(
        f.db, f.context, f.posting_invoice_key, authorize=lambda db: None)
    assert options["handovers"][0]["pending_return"] == "6.000000"
    assert options["handovers"][0]["returnable"] == "4.000000"


def test_sales_return_migration_replays_and_keeps_database_guards(
        t18_schema, test_engine):
    from Utils import migrate_20261005_sales_returns as migration

    original_engine = migration.engine
    migration.engine = test_engine
    try:
        migration.ensure_sales_returns_schema()
        migration.ensure_sales_returns_schema()
    finally:
        migration.engine = original_engine

    with test_engine.connect() as connection:
        triggers = connection.execute(text("""
            SELECT tgname FROM pg_trigger
            WHERE tgrelid IN (
                'containermgmt.sales_return_claims'::regclass,
                'containermgmt.sales_return_allocations'::regclass,
                'containermgmt.sales_credit_notes'::regclass,
                'containermgmt.sales_credit_note_lines'::regclass,
                'containermgmt.sales_invoice_debt_applications'::regclass,
                'containermgmt.customer_credit_liability_entries'::regclass,
                'containermgmt.inventory_stock_movements'::regclass,
                'containermgmt.inventory_valuations'::regclass
            ) AND NOT tgisinternal
        """)).scalars().all()
    assert {
        "sales_return_claim_guard",
        "sales_return_allocation_guard",
        "sales_credit_note_guard",
        "sales_return_lineage_guard",
        "sales_return_debt_child_guard",
        "customer_credit_return_child_guard",
        "return_stock_movement_guard",
        "return_valuation_guard",
    }.issubset(set(triggers))
