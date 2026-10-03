"""INTERNAL ONLY: single-location ordinary/batch/serial stock and owned holds.

No route or legacy writer calls this module. All adapters require a trusted
runtime authority claim and a separate action/source authorization callback.
Before integration, callers MUST authorize every attempt (including replay),
validate the owning sales line and entitlement, enforce node fencing, approved
opening/release decisions and an explicit product policy. Drafts are not active
policies. Batch reservations need the trusted branch business date, not a date
supplied by a till. Serial identity assignment at handover is not enabled.
Do not infer UNTRACKED or manufacture serials from quantity totals.
Opening is not goods receiving or valuation. No sale/handover is implemented.
The first argument may be a session factory (factory-owned internal transaction)
or an active Session with a mandatory authorize guard (caller-owned transaction).
The caller must propagate validation errors out of its transaction context;
outcomes returned from a shared session are provisional until its outer commit.
"""
from datetime import datetime, date
from decimal import Decimal, localcontext, Context
from uuid import UUID
from sqlalchemy import text

from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockReservation, StockMovement, StockBatch
from Model.containermgmt.Orders.Product import Product
from Services.inventory_posting_service import PostingEffect, PostingConflict, execute_once
from Services.posting_authority_service import AuthorityClaim, require_posting_authority
from Services.inventory_quantity_service import QuantityBreakdown, ZERO
from Services.inventory_unit_service import convert_quantity
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Schema.InventoryBatchSchema import StockBatchIdentity
from Schema.InventorySerialSchema import SerialOpening
from Services.serial_stock_service import record_serial_opening, verify_serial_projection
from Services.policy_activation_service import active_policy
from Services.policy_compatibility_service import extends_policy
from Utils.org_filter import apply_org_filter


def _uuid(value):
    if not isinstance(value, UUID) or not value.int:
        raise ValueError("A nonzero UUID reference is required")


def _reason(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("A reason of 1-500 characters is required")


def _positive(value):
    QuantityBreakdown(value)
    if value <= 0:
        raise ValueError("Quantity must be positive")


def _query(db, model, context):
    # Even multi-org/root contexts post within ONE active organisation.
    return apply_org_filter(db.query(model).filter(model.org_id == context.org_id,
        model.is_deleted.is_(False)), model, context)


def _parents(db, context, branch_id, location_id, product_id, base_unit):
    branch = _query(db, InventoryBranch, context).filter_by(id=branch_id, is_active=True).first()
    location = _query(db, StockLocation, context).filter_by(
        id=location_id, branch_id=branch_id, is_active=True).first()
    product = _query(db, Product, context).filter_by(id=product_id, status="active", is_shared=False).first()
    if branch is None or location is None or product is None:
        raise ValueError("Active stock scope not found")
    if not isinstance(base_unit, str) or not base_unit.strip() or base_unit != product.unit:
        raise ValueError("Stock base unit must match the owning product")


def _locked_balance(db, context, balance_id):
    balance = _query(db, StockBalance, context).filter_by(id=balance_id).populate_existing().with_for_update().one_or_none()
    if balance is None:
        raise ValueError("Stock scope not found")
    if balance.tracking_policy not in ("UNTRACKED", "BATCH", "SERIAL"):
        raise ValueError("Tracking policy is not supported by this internal slice")
    if balance.policy_config is None:
        raise ValueError("Stock unit policy requires review before further posting")
    _parents(db, context, balance.branch_id, balance.location_id, balance.product_id, balance.base_unit)
    if balance.tracking_policy == "SERIAL":
        verify_serial_projection(db, context, balance)
    return balance


def _snapshot(balance):
    return QuantityBreakdown(balance.on_hand, balance.reserved, balance.damaged, balance.quarantined)


def _effective_policy(db, context, balance):
    active = active_policy(db, context, balance.product_id)
    if active:
        if not extends_policy(balance.policy_config, active.config):
            raise PostingConflict("Active policy is incompatible with this stock snapshot")
        return InventoryPolicyConfig.model_validate(active.config)
    return InventoryPolicyConfig.model_validate(balance.policy_config)


def _post_stock(factory, context, actor_id, operation_key, kind, request, apply, *,
                authority, authorize, branch_id=None, balance_id=None):
    """Bind runtime authority to immutable stock scope before even replaying.

    No factory/session compatibility bypass. Claims must be server-derived;
    permission/source guards are additional to node ownership, never substitutes.
    """
    claim_snapshot = ({"org_id": authority.org_id, "branch_id": authority.branch_id,
                       "node_key": str(authority.node_key), "epoch": authority.epoch}
                      if isinstance(authority, AuthorityClaim) else None)

    def guard(db):
        if not isinstance(authority, AuthorityClaim):
            raise ValueError("A trusted stock authority claim is required")
        if not callable(authorize):
            raise ValueError("Stock posting requires an authorization guard")
        owning_branch = branch_id
        scope = None
        if balance_id is not None:
            # Identity columns are immutable; do not take a balance lock before
            # the branch authority lock (consistent ordering avoids deadlocks).
            scope = apply_org_filter(db.query(StockBalance.branch_id, StockBalance.location_id,
                StockBalance.product_id, StockBalance.base_unit).filter(
                StockBalance.id == balance_id, StockBalance.org_id == context.org_id,
                StockBalance.is_deleted.is_(False)), StockBalance, context).one_or_none()
            if scope is None:
                raise ValueError("Stock scope not found")
            owning_branch = scope.branch_id
        require_posting_authority(db, context, authority, branch_id=owning_branch)
        if scope is not None:
            _parents(db, context, scope.branch_id, scope.location_id, scope.product_id, scope.base_unit)
        else:
            _parents(db, context, branch_id, request["location_id"], request["product_id"], request["base_unit"])
        authorize(db)

    return execute_once(factory, context, actor_id, operation_key, kind + ".authority-v1",
        {**request, "authority": claim_snapshot}, apply, authorize=guard)


def _record(db, balance, operation_key, actor_id, kind, reason, before, reservation=None):
    after = _snapshot(balance)
    with localcontext(Context(prec=48)):
        on_hand_delta = after.on_hand - before.on_hand
        reserved_delta = after.reserved - before.reserved
    db.add(StockMovement(org_id=balance.org_id, balance_id=balance.id,
        reservation_id=reservation.id if reservation else None, operation_key=operation_key,
        version=balance.version, kind=kind, reason=reason, created_by=actor_id,
        on_hand_delta=on_hand_delta, reserved_delta=reserved_delta, on_hand=after.on_hand,
        reserved=after.reserved, damaged=after.damaged, quarantined=after.quarantined))
    result = {"balance_id": balance.id, "version": balance.version,
              "on_hand": str(after.on_hand), "reserved": str(after.reserved),
              "available": str(after.available), "damaged": str(after.damaged),
              "quarantined": str(after.quarantined), "batch_key": str(balance.batch_key) if balance.batch_key else None}
    if reservation:
        result["reservation_key"] = str(reservation.reservation_key)
        with localcontext(Context(prec=48)):
            result["reservation_remaining"] = str(reservation.quantity - reservation.released)
    return PostingEffect(result, {"kind": "stock." + kind.lower(), "balance_id": balance.id,
        "version": balance.version, "batch_key": result["batch_key"], "on_hand_delta": str(on_hand_delta),
        "reserved_delta": str(reserved_delta), "reservation_key": result.get("reservation_key")})


def open_untracked_stock(factory, context, actor_id, operation_key, *, branch_id, location_id,
                         product_id, base_unit, tracking_policy, quantities: QuantityBreakdown, reason,
                         policy: InventoryPolicyConfig, authorize=None, authority=None):
    if tracking_policy != "UNTRACKED":
        raise ValueError("Explicit untracked quantities are required")
    return _open_stock(factory, context, actor_id, operation_key, branch_id=branch_id,
        location_id=location_id, product_id=product_id, base_unit=base_unit, tracking_policy=tracking_policy,
        quantities=quantities, reason=reason, policy=policy, authorize=authorize, authority=authority)


def open_batch_stock(factory, context, actor_id, operation_key, *, branch_id, location_id,
                     product_id, policy: InventoryPolicyConfig, batch: StockBatchIdentity,
                     quantities: QuantityBreakdown, reason, authorize=None, authority=None):
    """Trusted approved-opening integration only; not receiving or sale authorisation."""
    if not isinstance(policy, InventoryPolicyConfig) or policy.tracking != "BATCH" or not isinstance(batch, StockBatchIdentity):
        raise ValueError("An explicit batch policy and identity are required")
    for flag, field in (("require_expiry", "expires_on"), ("require_shade", "shade"), ("require_calibre", "calibre")):
        if getattr(policy, flag) and getattr(batch, field) is None:
            raise ValueError(f"Batch {field} is required by this policy")
    return _open_stock(factory, context, actor_id, operation_key, branch_id=branch_id,
        location_id=location_id, product_id=product_id, base_unit=policy.base_unit, tracking_policy="BATCH",
        quantities=quantities, reason=reason, policy=policy, batch=batch, authorize=authorize, authority=authority)


def open_serial_stock(factory, context, actor_id, operation_key, *, branch_id, location_id,
                      product_id, policy: InventoryPolicyConfig, serials: SerialOpening, reason,
                      authorize=None, authority=None):
    """Approved opening only. Counts derive from registered identities, never guessed."""
    if not isinstance(policy, InventoryPolicyConfig) or policy.tracking != "SERIAL" or not isinstance(serials, SerialOpening):
        raise ValueError("Explicit serial policy and opening identities are required")
    quantities = QuantityBreakdown(Decimal(len(serials.items)),
        damaged=Decimal(sum(row.condition == "DAMAGED" for row in serials.items)),
        quarantined=Decimal(sum(row.condition == "QUARANTINED" for row in serials.items)))
    return _open_stock(factory, context, actor_id, operation_key, branch_id=branch_id, location_id=location_id,
        product_id=product_id, base_unit=policy.base_unit, tracking_policy="SERIAL", quantities=quantities,
        reason=reason, policy=policy, serials=serials, authorize=authorize, authority=authority)


def _open_stock(factory, context, actor_id, operation_key, *, branch_id, location_id,
                product_id, base_unit, tracking_policy, quantities, reason, policy, batch=None, serials=None,
                authorize=None, authority=None):
    """Approved-opening adapter foundation only; never read legacy current_stock.

No default tracking policy: trusted future integrations must explicitly classify
the product. Existing buckets cannot be reopened even with a new operation key.
Policy transitions need a separate reviewed workflow, never another opening.
"""
    _reason(reason)
    if not isinstance(quantities, QuantityBreakdown):
        raise ValueError("Explicit quantities are required")
    if quantities.reserved != ZERO:
        raise ValueError("Opening cannot create ownerless reservations")
    if not isinstance(policy, InventoryPolicyConfig) or policy.base_unit != base_unit or policy.tracking != tracking_policy:
        raise ValueError("Explicit opening policy must match the product unit and tracking")
    for value in (quantities.on_hand, quantities.damaged, quantities.quarantined):
        convert_quantity(policy, value, base_unit, allow_zero=True)
    request = {"branch_id": branch_id, "location_id": location_id, "product_id": product_id,
        "base_unit": base_unit, "tracking_policy": tracking_policy, "reason": reason,
        "on_hand": str(quantities.on_hand), "damaged": str(quantities.damaged),
        "quarantined": str(quantities.quarantined), "policy": policy.model_dump(mode="json")}
    if batch:
        request["batch"] = batch.model_dump(mode="json")
    if tracking_policy == "SERIAL":
        if not isinstance(serials, SerialOpening):
            raise ValueError("Serial identities are required before opening stock")
        request["serials"] = sorted(serials.model_dump(mode="json")["items"], key=lambda row: row["serial_key"])

    def apply(db):
        _parents(db, context, branch_id, location_id, product_id, base_unit)
        # A product lock serializes classification checks and lot creation across locations.
        apply_org_filter(db.query(Product.id).filter(Product.id == product_id,
            Product.org_id == context.org_id), Product, context).with_for_update(of=Product).one()
        active = active_policy(db, context, product_id)
        if active and active.config != policy.model_dump(mode="json"):
            raise PostingConflict("Opening policy must match the reviewed active policy")
        snapshots = apply_org_filter(db.query(StockBalance.policy_config).filter(
            StockBalance.org_id == context.org_id, StockBalance.product_id == product_id,
            StockBalance.is_deleted.is_(False)), StockBalance, context).distinct().yield_per(100)
        for (snapshot,) in snapshots:
            if not (extends_policy(snapshot, policy.model_dump(mode="json")) if active else snapshot == policy.model_dump(mode="json")):
                raise PostingConflict("Existing product stock needs an approved policy transition; opening cannot change its rules")
        # Serialize creation of an absent bucket using its existing location row.
        _query(db, StockLocation, context).filter_by(id=location_id).with_for_update().one()
        batch_key = batch.batch_key if batch else None
        if _query(db, StockBalance, context).filter_by(location_id=location_id, product_id=product_id, batch_key=batch_key).first():
            raise PostingConflict("Stock bucket is already opened")
        if batch:
            existing = _query(db, StockBatch, context).filter_by(batch_key=batch_key, product_id=product_id).first()
            if existing:
                if any(getattr(existing, field) != getattr(batch, field) for field in ("code", "shade", "calibre", "expires_on")):
                    raise PostingConflict("Batch identity does not match the recorded lot")
            else:
                if _query(db, StockBatch, context).filter_by(product_id=product_id, code=batch.code).first():
                    raise PostingConflict("Batch code already belongs to another recorded identity")
                db.add(StockBatch(org_id=context.org_id, product_id=product_id, created_by=actor_id,
                                 **batch.model_dump()))
                db.flush()
        balance = StockBalance(org_id=context.org_id, branch_id=branch_id, location_id=location_id,
            product_id=product_id, base_unit=base_unit, tracking_policy=tracking_policy,
            batch_key=batch_key,
            policy_config=policy.model_dump(mode="json"), quantity_step=Decimal(policy.quantity_step),
            on_hand=quantities.on_hand, reserved=ZERO, damaged=quantities.damaged,
            quarantined=quantities.quarantined, version=1, created_by=actor_id)
        db.add(balance); db.flush()
        if serials:
            record_serial_opening(db, context, balance, serials, actor_id)
            verify_serial_projection(db, context, balance)
        return _record(db, balance, operation_key, actor_id, "OPENING", reason, QuantityBreakdown(ZERO))
    return _post_stock(factory, context, actor_id, operation_key,
                        "stock.serial-opening.v1" if serials else "stock.batch-opening.v1" if batch else "stock.opening.v2",
                        request, apply, authorize=authorize, authority=authority, branch_id=branch_id)


def reserve_stock(factory, context, actor_id, operation_key, *, balance_id, reservation_key,
                  source_line_key, quantity: Decimal, review_at: datetime, reason, input_unit=None,
                  business_date: date | None = None, authorize=None, authority=None):
    _uuid(reservation_key); _uuid(source_line_key); _positive(quantity); _reason(reason)
    if not isinstance(review_at, datetime) or review_at.utcoffset() is None:
        raise ValueError("Reservation review time must include a timezone")
    if business_date is not None and type(business_date) is not date:
        raise ValueError("Business date must be an explicit calendar date")
    request = {"balance_id": balance_id, "reservation_key": str(reservation_key),
        "source_line_key": str(source_line_key), "quantity": str(quantity),
        "review_at": review_at.isoformat(), "reason": reason, "input_unit": input_unit,
        "business_date": business_date.isoformat() if business_date else None}

    def apply(db):
        # Serialize even distinct bucket requests for one source line. No mixed-lot
        # or multi-location exceptions until the approved request workflow exists.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                   {"key": f"stock-source:{context.org_id}:{source_line_key}"})
        balance = _locked_balance(db, context, balance_id)
        base_quantity = convert_quantity(_effective_policy(db, context, balance), quantity,
                                         input_unit if input_unit is not None else balance.base_unit)
        if balance.batch_key:
            if business_date is None:
                raise ValueError("Trusted branch business date is required for batch reservations")
            lot = _query(db, StockBatch, context).filter_by(batch_key=balance.batch_key, product_id=balance.product_id).one()
            if lot.expires_on and lot.expires_on < business_date:
                raise ValueError("Expired batch cannot be reserved")
        other_hold = _query(db, StockReservation, context).filter(
            StockReservation.source_line_key == source_line_key, StockReservation.balance_id != balance_id).first()
        if other_hold:
            raise PostingConflict("Source line already uses another stock bucket; mixed-batch or multi-location fulfilment requires an approved request")
        if _query(db, StockReservation, context).filter_by(balance_id=balance_id,
                                                          source_line_key=source_line_key).first():
            raise PostingConflict("Source line already has a reservation for this stock bucket")
        before = _snapshot(balance)
        after = before.reserve(base_quantity)
        hold = StockReservation(org_id=context.org_id, balance_id=balance_id,
            reservation_key=reservation_key, source_line_key=source_line_key, quantity=base_quantity,
            released=ZERO, review_at=review_at, created_by=actor_id)
        db.add(hold); db.flush()
        balance.reserved = after.reserved
        balance.version += 1
        balance.updated_by = actor_id
        return _record(db, balance, operation_key, actor_id, "RESERVE", reason, before, hold)
    return _post_stock(factory, context, actor_id, operation_key, "stock.reserve.v2", request, apply,
                        authorize=authorize, authority=authority, balance_id=balance_id)


def release_stock(factory, context, actor_id, operation_key, *, balance_id, reservation_key,
                  source_line_key, quantity: Decimal, reason, input_unit=None, authorize=None, authority=None):
    """Only an approved release adapter may call this; a deadline is NOT approval."""
    _uuid(reservation_key); _uuid(source_line_key); _positive(quantity); _reason(reason)
    request = {"balance_id": balance_id, "reservation_key": str(reservation_key),
        "source_line_key": str(source_line_key), "quantity": str(quantity), "reason": reason, "input_unit": input_unit}

    def apply(db):
        # Release needs no source-allocation lock: it cannot create another bucket.
        # Lock order: operation -> stock bucket -> source reservation.
        balance = _locked_balance(db, context, balance_id)
        base_quantity = convert_quantity(_effective_policy(db, context, balance), quantity,
                                         input_unit if input_unit is not None else balance.base_unit)
        hold = _query(db, StockReservation, context).filter_by(balance_id=balance_id,
            reservation_key=reservation_key, source_line_key=source_line_key).populate_existing().with_for_update().one_or_none()
        if hold is None:
            raise ValueError("Owned reservation not found")
        with localcontext(Context(prec=48)):
            remaining = hold.quantity - hold.released
            new_released = hold.released + base_quantity
        if base_quantity > remaining:
            raise ValueError("Release exceeds this reservation's remaining quantity")
        before = _snapshot(balance)
        balance.reserved = before.release(base_quantity).reserved
        balance.version += 1
        balance.updated_by = actor_id
        hold.released = new_released
        hold.updated_by = actor_id
        return _record(db, balance, operation_key, actor_id, "RELEASE", reason, before, hold)
    return _post_stock(factory, context, actor_id, operation_key, "stock.release.v2", request, apply,
                        authorize=authorize, authority=authority, balance_id=balance_id)
