"""Prepare immutable pricing inputs without posting a sale or consuming approval."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from Model.containermgmt.Orders.SalesIntent import SalesIntent
from Model.containermgmt.Orders.SalesPricing import SalesTransactionPricing
from Schema.SalesPricingSchema import SalesTransactionPricingPrepare
from Services.inventory_posting_service import (
    PostingConflict, PostingEffect, execute_once,
)
from Services.sales_intent_service import get_sales_intent
from Services.sales_price_floor_case_service import (
    floor_binding_from_preview, require_approved_floor_case,
)
from Services.sales_pricing_preview_service import (
    preview_sales_pricing, transaction_pricing_payload,
)
from Utils.org_filter import apply_org_filter


def _scoped(db, context):
    return apply_org_filter(db.query(SalesTransactionPricing).filter_by(
        org_id=context.org_id, is_deleted=False), SalesTransactionPricing,
        context)


def _result(row, *, replayed=False):
    return {
        "pricing_snapshot_key": str(row.pricing_snapshot_key),
        "document_key": str(row.document_key),
        "draft_version": row.draft_version,
        "status": "PREPARED",
        "priced_at": row.priced_at.isoformat(),
        "currency": row.currency,
        "policy": row.policy,
        "pricing": row.pricing,
        "pricing_fingerprint": row.pricing_fingerprint,
        "gross_total_scr": format(row.gross_total_scr, ".2f"),
        "net_total_scr": format(row.net_total_scr, ".2f"),
        "tax_total_scr": format(row.tax_total_scr, ".2f"),
        "requires_floor_approval": row.requires_floor_approval,
        "floor_case_key": (str(row.floor_case_key)
            if row.floor_case_key is not None else None),
        "created_at": row.created_at.isoformat(),
        "created_by": row.created_by,
        "posting_enabled": False,
        "replayed": replayed,
    }


def prepare_transaction_pricing(factory, context, actor_id, document_key,
                                payload, *, authorize):
    """Freeze one exact draft/pricing choice for later T13 posting.

    Price-floor approval is validated and referenced but deliberately remains
    unconsumed. The eventual sale coordinator must consume it in the same
    transaction as invoice, stock, money, numbering and outbox effects.
    """
    if not callable(authorize):
        raise ValueError("Sales pricing preparation authorization is required")
    key = UUID(str(document_key))
    if not key.int:
        raise ValueError("Nonzero sales draft key required")
    if not isinstance(payload, SalesTransactionPricingPrepare):
        payload = SalesTransactionPricingPrepare.model_validate(payload)

    def apply(db):
        # Shares the stable parent lock and lock order with draft revision saves.
        parent = apply_org_filter(db.query(SalesIntent).filter_by(
            org_id=context.org_id, document_key=key, is_deleted=False),
            SalesIntent, context).with_for_update().one_or_none()
        if parent is None:
            raise LookupError("Sales draft not found")
        draft = get_sales_intent(db, context, key, authorize=authorize)
        if draft["version"] != payload.expected_draft_version:
            raise PostingConflict(
                "Sales draft changed; refresh pricing before preparation")
        priced_at = datetime.now(timezone.utc)
        preview = preview_sales_pricing(db, context, draft,
            priced_at=priced_at, authorize=authorize)
        pricing, fingerprint = transaction_pricing_payload(preview)

        if preview["requires_floor_approval"]:
            if payload.floor_case_key is None:
                raise PermissionError(
                    "These prices require an approved price-floor case")
            binding = floor_binding_from_preview(context, key,
                draft["version"], preview)
            require_approved_floor_case(db, context, payload.floor_case_key,
                binding, authorize=authorize)
        elif payload.floor_case_key is not None:
            raise ValueError(
                "A price-floor case cannot be attached when current pricing is within floor")

        row = SalesTransactionPricing(
            org_id=context.org_id,
            pricing_snapshot_key=payload.operation_key,
            document_key=key,
            draft_version=draft["version"],
            operation_key=payload.operation_key,
            priced_at=priced_at,
            currency=preview["currency"],
            policy=preview["policy"],
            pricing=pricing,
            pricing_fingerprint=fingerprint,
            gross_total_scr=Decimal(preview["gross_total_scr"]),
            net_total_scr=Decimal(preview["net_total_scr"]),
            tax_total_scr=Decimal(preview["tax_total_scr"]),
            requires_floor_approval=preview["requires_floor_approval"],
            floor_case_key=payload.floor_case_key,
            created_by=actor_id,
        )
        db.add(row)
        db.flush()
        result = _result(row)
        return PostingEffect(result, {
            "kind": "sales.transaction-pricing.prepared",
            "pricing_snapshot_key": str(row.pricing_snapshot_key),
            "document_key": str(key),
            "draft_version": draft["version"],
            "pricing_fingerprint": fingerprint,
        })

    outcome = execute_once(factory, context, actor_id, payload.operation_key,
        "sales.transaction-pricing.prepare.v1", {
            "document_key": str(key),
            "expected_draft_version": payload.expected_draft_version,
            "floor_case_key": (str(payload.floor_case_key)
                if payload.floor_case_key is not None else None),
        }, apply, authorize=authorize)
    return dict(outcome.result, replayed=outcome.replayed)


def latest_transaction_pricing(db, context, document_key, *, authorize,
                               draft_version=None):
    if not callable(authorize):
        raise ValueError("Sales pricing read authorization is required")
    authorize(db)
    key = UUID(str(document_key))
    query = _scoped(db, context).filter(
        SalesTransactionPricing.document_key == key)
    if draft_version is not None:
        if type(draft_version) is not int or draft_version <= 0:
            raise ValueError("Positive draft version required")
        query = query.filter(
            SalesTransactionPricing.draft_version == draft_version)
    row = query.order_by(SalesTransactionPricing.created_at.desc(),
        SalesTransactionPricing.pricing_snapshot_key.desc()).first()
    if row is None:
        raise LookupError("Prepared pricing not found")
    return _result(row)
