"""Read-only current pricing preview for an existing immutable draft revision."""
import hashlib
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from Services.inventory_posting_service import PostingConflict, _json_snapshot
from Services.sales_pricing_configuration_service import resolve_pricing_line
from Services.sales_pricing_service import calculate_tax_inclusive_invoice


class PricingUnavailable(ValueError):
    """A mandatory current price or tax configuration is unavailable."""


def _money(value):
    return format(value, ".2f")


def transaction_pricing_payload(preview):
    """Canonical exact input shared by approval, preparation and future posting."""
    if type(preview) is not dict or not preview.get("lines"):
        raise ValueError("A complete pricing preview is required")
    pricing = {
        "currency": preview["currency"], "policy": preview["policy"],
        "gross_total_scr": preview["gross_total_scr"],
        "net_total_scr": preview["net_total_scr"],
        "tax_total_scr": preview["tax_total_scr"],
        "lines": [{key: (str(line[key]) if key == "line_key" else line[key])
            for key in (
                "line_key", "product_id", "quantity", "selected_source",
                "selected_reference_key", "selected_version", "gross_unit_scr",
                "store_price_key", "store_price_version", "store_gross_unit_scr",
                "floor_gross_unit_scr", "requires_floor_approval", "tax_code",
                "tax_version", "tax_treatment", "tax_rate", "gross_scr",
                "net_scr", "tax_scr")}
            for line in preview["lines"]],
    }
    pricing, encoded = _json_snapshot(pricing)
    return pricing, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preview_sales_pricing(db, context, draft, *, priced_at: datetime,
                          authorize):
    if not callable(authorize):
        raise ValueError("Sales pricing authorization guard required")
    if type(draft) is not dict or not draft.get("lines"):
        raise ValueError("An existing sales draft snapshot is required")
    try:
        inputs = [resolve_pricing_line(db, context,
            line_key=UUID(line["line_key"]), branch_id=draft["branch_id"],
            product_id=line["product_id"], unit=line["unit"],
            quantity=Decimal(line["quantity"]),
            priced_at=priced_at, customer_key=UUID(draft["customer_key"]),
            authorize=authorize) for line in draft["lines"]]
        invoice = calculate_tax_inclusive_invoice(inputs)
    except (LookupError, PostingConflict) as error:
        raise PricingUnavailable(str(error)) from error
    lines = []
    for line in invoice.lines:
        lines.append(dict(line_key=line.line_key, product_id=line.product_id,
            quantity=format(line.quantity, "f"),
            selected_source=line.selected_price.source,
            selected_reference_key=line.selected_price.reference_key,
            selected_version=line.selected_price.version,
            gross_unit_scr=format(line.selected_price.gross_unit_scr, "f"),
            store_price_key=line.store_price.reference_key,
            store_price_version=line.store_price.version,
            store_gross_unit_scr=format(line.store_price.gross_unit_scr, "f"),
            floor_gross_unit_scr=(format(line.floor_gross_unit_scr, "f")
                if line.floor_gross_unit_scr is not None else None),
            requires_floor_approval=line.requires_floor_approval,
            tax_code=line.tax.code, tax_version=line.tax.version,
            tax_treatment=line.tax.treatment,
            tax_rate=format(line.tax.rate, "f"),
            gross_scr=_money(line.gross_scr), net_scr=_money(line.net_scr),
            tax_scr=_money(line.tax_scr)))
    return dict(document_key=draft["document_key"],
        draft_version=draft["version"], status="READY", currency=invoice.currency,
        policy=invoice.policy, priced_at=priced_at, lines=lines,
        gross_total_scr=_money(invoice.gross_total_scr),
        net_total_scr=_money(invoice.net_total_scr),
        tax_total_scr=_money(invoice.tax_total_scr),
        requires_floor_approval=invoice.requires_floor_approval,
        posting_enabled=False)
