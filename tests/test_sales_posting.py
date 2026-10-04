"""T13 atomic posting uses exact pricing, money configuration and reservations."""
from datetime import datetime, timezone
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.Credentials.users import User
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.SalesReservationSource import SalesReservationSource
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch, StockReservation
from Model.containermgmt.Orders.SalesIntent import SalesIntentLineRevision
from Model.containermgmt.Orders.SalesPosting import (
    SalesCardConfirmation, SalesInvoice, SalesInvoiceReservation,
    SalesPostingAttempt,
)
from Schema.BranchCounterSchema import CounterSave
from Schema.BranchSettingsSchema import BranchSettingsSave
from Schema.PaymentConfigurationSchema import MethodConfig, MethodSave, MappingConfig, MappingSave
from Schema.SalesPostingSchema import (
    SalesPostingAttemptCreate, SalesPostingFinalize, SalesCardConfirmationAppend,
    SalesPostingTenderInput, SalesReservationBindingInput,
)
from Schema.SalesReservationSchema import SalesDemandReference
from Schema.StaffStoreAssignmentSchema import StaffStoreConfig
from Services.inventory_posting_service import PostingConflict
from Services.payment_configuration_service import save_mapping, save_method
from Services.sales_posting_service import (
    append_card_confirmation, create_posting_attempt, finalize_posting_attempt,
)
from Services.staff_store_assignment_service import save_staff_store_assignment
from Routes.Inventory.BranchCounterRouter import save_counter
from Routes.Inventory.BranchSettingsRouter import save_settings
from tests.test_sales_transaction_pricing import floor_api, _approve, _prepare  # noqa: F401
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def posting(floor_api):
    f = floor_api
    assert f.client.post("/sales/pricing/floor-cases", json=f.case_body).status_code == 200
    _approve(f, f.case_key)
    pricing_key = uuid4()
    priced = _prepare(f, pricing_key, f.case_key)
    assert priced.status_code == 200, priced.text
    pricing = priced.json()

    settings = BranchSettingsSave.model_validate({
        "operation_key": str(uuid4()), "expected_version": 0,
        "config": {"timezone_name": "Indian/Mahe",
            "weekday_cutoff": "04:00", "weekend_cutoff": "06:00",
            "trading_weekdays": [0, 1, 2, 3, 4, 5], "date_overrides": []}})
    save_settings(f.own, settings, f.db, f.context, SimpleNamespace(id=f.user.id))
    counter_key = uuid4()
    counter = save_counter(f.own, counter_key, CounterSave.model_validate({
        "operation_key": str(uuid4()), "expected_version": 0, "code": "T13",
        "config": {"name": "Synthetic checkout", "purpose": "CHECKOUT",
                   "is_enabled": True}}), f.db, f.context,
        SimpleNamespace(id=f.user.id))
    f.db.connection()
    save_staff_store_assignment(f.db, f.context, f.user.id, uuid4(),
        user_id=f.user.id,
        config=StaffStoreConfig(branch_id=f.own, counter_id=counter.id,
                                is_enabled=True),
        expected_version=0, authorize=lambda db: None)
    f.db.commit()

    method_key, mapping_key = uuid4(), uuid4()
    f.db.connection()
    save_method(f.db, f.context, f.user.id, method_key,
        MethodSave(operation_key=uuid4(), expected_version=0, code="SYNTH_CASH",
            config=MethodConfig(label="Synthetic cash", kind="CASH", is_enabled=True),
            reason="Synthetic T13 payment"), authorize=lambda db: None)
    save_mapping(f.db, f.context, f.user.id, mapping_key,
        MappingSave(operation_key=uuid4(), expected_version=0,
            branch_id=f.own, method_key=method_key,
            config=MappingConfig(account_ref="SYNTH_TILL_SCR",
                label="Synthetic till", is_enabled=True),
            reason="Synthetic T13 receiving account"), authorize=lambda db: None)
    f.db.commit()

    document_key = UUID(f.document_key)
    line = f.db.query(SalesIntentLineRevision).filter_by(
        org_id=f.org_a, document_key=document_key, version=1).one()
    site = StockLocation(org_id=f.org_a, branch_id=f.own,
        code="T13SITE", name="Synthetic T13 site", kind="SITE")
    batch = StockBatch(org_id=f.org_a, batch_key=uuid4(),
        product_id=line.product_id, code="T13-BATCH", shade="SYNTHETIC",
        created_by=f.user.id)
    f.db.add_all([site, batch]); f.db.flush()
    balance = StockBalance(org_id=f.org_a, branch_id=f.own,
        location_id=site.id, product_id=line.product_id,
        base_unit=line.base_unit, tracking_policy="BATCH",
        batch_key=batch.batch_key, policy_config=line.policy,
        quantity_step=Decimal("1"), on_hand=line.base_quantity,
        reserved=line.base_quantity, damaged=0, quarantined=0,
        version=2, created_by=f.user.id)
    f.db.add(balance); f.db.flush()
    reservation_key = uuid4()
    reservation = StockReservation(org_id=f.org_a,
        reservation_key=reservation_key, balance_id=balance.id,
        source_line_key=SalesDemandReference(document_key=document_key,
            version=1, line_key=line.line_key).stock_source_key(),
        quantity=line.base_quantity,
        released=0, review_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        created_by=f.user.id)
    f.db.add(reservation); f.db.flush()
    f.db.add(SalesReservationSource(org_id=f.org_a,
        reservation_key=reservation_key, document_key=document_key,
        version=1, line_key=line.line_key, created_by=f.user.id))
    f.db.commit()

    f.posting_attempt_key = uuid4()
    f.posting_operation_key = uuid4()
    f.posting_invoice_key = uuid4()
    f.posting_reservation_key = reservation_key
    f.posting_line_key = line.line_key
    f.posting_counter_key = counter_key
    f.posting_method_key = method_key
    f.posting_mapping_key = mapping_key
    f.posting_pricing = pricing
    f.attempt = SalesPostingAttemptCreate(
        attempt_key=f.posting_attempt_key,
        operation_key=f.posting_operation_key,
        document_key=document_key, expected_draft_version=1,
        pricing_snapshot_key=pricing_key,
        expected_pricing_fingerprint=pricing["pricing_fingerprint"],
        counter_key=counter_key,
        expected_branch_settings_version=1,
        expected_counter_settings_version=1,
        expected_assignment_version=1,
        tenders=[SalesPostingTenderInput(tender_key=uuid4(),
            method_key=method_key, expected_method_version=1,
            mapping_key=mapping_key, expected_mapping_version=1,
            amount_scr=pricing["gross_total_scr"])])
    f.finalize = SalesPostingFinalize(attempt_key=f.posting_attempt_key,
        operation_key=f.posting_operation_key,
        invoice_key=f.posting_invoice_key,
        reservations=[SalesReservationBindingInput(
            source_line_key=line.line_key, reservation_key=reservation_key,
            quantity=format(line.base_quantity, "f"))],
        expected_card_confirmations=[])
    return f


def _create(f, payload=None):
    f.db.connection()
    result = create_posting_attempt(f.db, f.context, f.user.id,
        payload or f.attempt, authorize=lambda db: None, instant=NOW)
    f.db.commit()
    return result


def _finalize(f, payload=None):
    f.db.connection()
    result = finalize_posting_attempt(f.db, f.context, f.user.id,
        payload or f.finalize, authorize=lambda db: None, instant=NOW)
    f.db.commit()
    return result


def test_cash_attempt_and_invoice_post_once_without_handover(posting):
    f = posting
    first = _create(f)
    assert first["status"] == "READY" and not first["replayed"]
    assert _create(f)["replayed"]
    posted = _finalize(f)
    assert not posted["replayed"]
    assert posted["invoice"]["payment_status"] == "PAID"
    assert posted["invoice"]["fulfilment_status"] == "AWAITING_COLLECTION"
    assert posted["invoice"]["gross_total_scr"] == "2200.00"
    replay = _finalize(f)
    assert replay["replayed"] and replay["invoice"]["invoice_key"] == f.posting_invoice_key
    hold = f.db.query(StockReservation).filter_by(
        reservation_key=f.posting_reservation_key).one()
    balance = f.db.get(StockBalance, hold.balance_id)
    assert hold.released == 0 and balance.on_hand == Decimal("24")
    assert f.db.query(SalesInvoice).filter_by(org_id=f.org_a).count() == 1


def test_changed_retry_fails_closed(posting):
    f = posting
    _create(f)
    changed = f.attempt.model_copy(deep=True)
    changed.tenders[0].amount_scr = "2199.00"
    f.db.connection()
    with pytest.raises(PostingConflict):
        create_posting_attempt(f.db, f.context, f.user.id, changed,
            authorize=lambda db: None, instant=NOW)
    f.db.rollback()


def test_unknown_card_outcome_stays_pending_until_exact_confirmation(posting):
    f = posting
    method_key, mapping_key = uuid4(), uuid4()
    f.db.connection()
    save_method(f.db, f.context, f.user.id, method_key,
        MethodSave(operation_key=uuid4(), expected_version=0, code="SYNTH_CARD",
            config=MethodConfig(label="Synthetic card", kind="CARD", is_enabled=True),
            reason="Synthetic T13 card"), authorize=lambda db: None)
    save_mapping(f.db, f.context, f.user.id, mapping_key,
        MappingSave(operation_key=uuid4(), expected_version=0,
            branch_id=f.own, method_key=method_key,
            config=MappingConfig(account_ref="SYNTH_CARD_CLEARING",
                label="Synthetic card clearing", is_enabled=True),
            reason="Synthetic T13 card account"), authorize=lambda db: None)
    f.db.commit()
    tender_key = uuid4()
    f.attempt.tenders = [SalesPostingTenderInput(tender_key=tender_key,
        method_key=method_key, expected_method_version=1,
        mapping_key=mapping_key, expected_mapping_version=1,
        amount_scr=f.posting_pricing["gross_total_scr"])]
    assert _create(f)["status"] == "AWAITING_CARD"
    unknown = SalesCardConfirmationAppend(confirmation_key=uuid4(),
        attempt_key=f.posting_attempt_key, tender_key=tender_key,
        expected_sequence=1, outcome="UNKNOWN")
    f.db.connection()
    assert append_card_confirmation(f.db, f.context, f.user.id, unknown,
        authorize=lambda db: None)["status"] == "AWAITING_CARD"
    f.db.commit()
    declined = SalesCardConfirmationAppend(confirmation_key=uuid4(),
        attempt_key=f.posting_attempt_key, tender_key=tender_key,
        expected_sequence=2, outcome="DECLINED")
    f.db.connection()
    declined_state = append_card_confirmation(f.db, f.context, f.user.id,
        declined, authorize=lambda db: None)
    f.db.commit()
    assert declined_state["status"] == "DECLINED"
    # A declined observation must not strand the sale. The same exact
    # card tender can be retried; changing the tender plan still requires a new
    # draft revision and posting attempt.
    confirmed = SalesCardConfirmationAppend(confirmation_key=uuid4(),
        attempt_key=f.posting_attempt_key, tender_key=tender_key,
        expected_sequence=3, outcome="CONFIRMED",
        provider_reference_hash="a" * 64)
    confirmer = User(org_id=f.org_a,
        username="synthetic-card-confirmer-" + uuid4().hex[:12],
        password_hash="unusable-test-only")
    f.db.add(confirmer); f.db.commit()
    f.db.connection()
    save_staff_store_assignment(f.db, f.context, f.user.id, uuid4(),
        user_id=confirmer.id,
        config=StaffStoreConfig(branch_id=f.own, counter_id=None,
                                is_enabled=True),
        expected_version=0, authorize=lambda db: None)
    f.db.commit()
    f.db.connection()
    ready = append_card_confirmation(f.db, f.context, confirmer.id, confirmed,
        authorize=lambda db: None)
    f.db.commit()
    assert ready["status"] == "READY"
    assert f.db.query(SalesCardConfirmation).filter_by(
        confirmation_key=confirmed.confirmation_key).one().created_by == confirmer.id
    f.finalize.expected_card_confirmations = [confirmed.confirmation_key]
    posted = _finalize(f)
    assert posted["invoice"]["payments"][0]["kind"] == "CARD"
    assert "account_ref" not in posted["invoice"]["payments"][0]
    assert posted["invoice"]["payments"][0]["confirmation_key"] == confirmed.confirmation_key


def test_posted_reservation_cannot_be_released_or_mutated(posting):
    from Services.reservation_release_service import locked_reservation_source
    f = posting
    _create(f); _finalize(f)
    f.db.connection()
    with pytest.raises(PostingConflict, match="Posted-sale"):
        locked_reservation_source(f.db, f.context, f.posting_reservation_key)
    f.db.rollback()
    with pytest.raises(DBAPIError):
        f.db.query(SalesInvoiceReservation).filter_by(
            reservation_key=f.posting_reservation_key).delete()
        f.db.flush()
    f.db.rollback()
    hold = f.db.query(StockReservation).filter_by(
        reservation_key=f.posting_reservation_key).one()
    hold.released += Decimal("1")
    with pytest.raises(DBAPIError, match="cumulative handover history"):
        f.db.flush()
        # The fixture owns an outer rollback transaction, so force this
        # production-deferred invariant to be checked inside the test.
        f.db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    f.db.rollback()


def test_card_confirmation_requires_separate_permission(posting):
    from Routes.Orders.SalesPostingRouter import SalesPostingRouter
    f = posting
    if not any(route.path.startswith("/sales/posting-attempts/")
            for route in f.app.routes):
        f.app.include_router(SalesPostingRouter)
    f.permissions |= {"View_Sale", "Post_Sale"}
    base = f.user.access_policy
    f.user.access_policy = replace(base,
        permission_names=frozenset(f.permissions),
        module_names=frozenset(set(base.module_names) | {"SALES"}),
        field_permissions={**base.field_permissions,
            "PERSONAL": "View_Personal_Data"})
    payload = SalesCardConfirmationAppend(confirmation_key=uuid4(),
        attempt_key=f.posting_attempt_key,
        tender_key=f.attempt.tenders[0].tender_key,
        expected_sequence=1, outcome="UNKNOWN")
    response = f.client.post(
        f"/sales/posting-attempts/{f.posting_attempt_key}/card-confirmations/"
        f"{payload.confirmation_key}", json=payload.model_dump(mode="json"))
    assert response.status_code == 403


def test_foreign_company_cannot_read_or_replay_attempt(posting):
    from Utils.org_filter import OrgContext
    from Services.sales_posting_service import read_posting_attempt
    f = posting; _create(f)
    foreign = OrgContext(current_org_id=f.org_b,
        allowed_org_ids=[f.org_a, f.org_b], is_root=True)
    with pytest.raises(LookupError):
        read_posting_attempt(f.db, foreign, f.posting_attempt_key,
            authorize=lambda db: None)


def test_database_trigger_conflicts_are_safely_redacted():
    from Routes.Orders.SalesPostingRouter import _error
    class TriggerRaised(Exception):
        pgcode = "P0001"
    response = _error(DBAPIError("insert", {}, TriggerRaised(), False))
    assert response.status_code == 409
    assert "reload" in response.detail.lower()
    assert "insert" not in response.detail.lower()


def test_sales_posting_migration_replays(test_engine, monkeypatch):
    from Utils import migrate_20261005_sales_posting as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_sales_posting_schema()
    migration.ensure_sales_posting_schema()
