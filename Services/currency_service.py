from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from Model.Credentials.Organisation import Organisation
from Model.containermgmt.MasterData.Currency import CurrencyExchangeRate
from Model.containermgmt.Orders.OrderPayment import OrderPayment
from Model.containermgmt.Orders.POItem import POItem


MONEY_QUANTUM = Decimal("0.01")
RATE_QUANTUM = Decimal("0.00000001")
ISSUED_STAGES = {"PO_ISSUED", "PROFORMA", "SHIPPED", "ARRIVED", "RECEIVED", "COMPLETED"}


class CurrencyRateNotFound(ValueError):
    pass


def _money(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _find_rate(
    db: Session,
    org_id: int,
    from_currency: str,
    to_currency: str,
    on_date: date,
) -> Decimal | None:
    for scoped_org_id in (org_id, None):
        row = (
            db.query(CurrencyExchangeRate)
            .filter(
                CurrencyExchangeRate.org_id.is_(None)
                if scoped_org_id is None
                else CurrencyExchangeRate.org_id == scoped_org_id,
                CurrencyExchangeRate.from_currency == from_currency,
                CurrencyExchangeRate.to_currency == to_currency,
                CurrencyExchangeRate.effective_date <= on_date,
                CurrencyExchangeRate.is_active.is_(True),
                CurrencyExchangeRate.is_deleted.is_(False),
            )
            .order_by(CurrencyExchangeRate.effective_date.desc(), CurrencyExchangeRate.id.desc())
            .first()
        )
        if row:
            return Decimal(str(row.rate))
    return None


def to_base(
    db: Session,
    org_id: int,
    currency: str,
    amount,
    on_date: date | None = None,
) -> tuple[Decimal, Decimal | None, str]:
    organisation = db.query(Organisation).filter(Organisation.id == org_id).first()
    if not organisation:
        raise CurrencyRateNotFound(f"Organisation {org_id} does not exist")

    source = (currency or organisation.base_currency or "SCR").upper()
    base = (organisation.base_currency or "SCR").upper()
    effective_date = on_date or date.today()
    decimal_amount = _money(amount)
    if source == base:
        return Decimal("1.00000000"), decimal_amount, base

    rate = _find_rate(db, org_id, source, base, effective_date)
    if rate is None:
        inverse = _find_rate(db, org_id, base, source, effective_date)
        if inverse:
            rate = Decimal("1") / inverse
    if rate is None:
        raise CurrencyRateNotFound(
            f"No {source} to {base} exchange rate is effective on {effective_date.isoformat()}"
        )

    normalized_rate = rate.quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)
    converted = (
        (decimal_amount * normalized_rate).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        if decimal_amount is not None else None
    )
    return normalized_rate, converted, base


def sync_order_base_amounts(db: Session, order, *, freeze_rate: bool = False) -> None:
    effective_date = order.order_mail_date or date.today()
    currency = (order.currency or "USD").upper()
    frozen = freeze_rate and order.exchange_rate_to_base is not None

    if frozen:
        rate = Decimal(str(order.exchange_rate_to_base))
        organisation = db.query(Organisation).filter(Organisation.id == order.org_id).first()
        if not organisation:
            raise CurrencyRateNotFound(f"Organisation {order.org_id} does not exist")
        base_currency = (order.base_currency or organisation.base_currency or "SCR").upper()
        total_base = _money(Decimal(str(order.total_amount or 0)) * rate)
    else:
        rate, total_base, base_currency = to_base(
            db, order.org_id, currency, order.total_amount, effective_date
        )

    order.currency = currency
    order.base_currency = base_currency
    order.exchange_rate_to_base = rate
    order.total_amount_base = total_base

    items = db.query(POItem).filter(POItem.po_id == order.id, POItem.is_deleted.is_(False)).all()
    for item in items:
        item_currency = (item.currency or currency).upper()
        item.currency = item_currency
        if frozen and item_currency == currency:
            item_rate = rate
            item_base_currency = base_currency
            unit_base = _money(Decimal(str(item.unit_price or 0)) * item_rate) if item.unit_price is not None else None
            line_base = _money(Decimal(str(item.total_price or 0)) * item_rate) if item.total_price is not None else None
        else:
            item_rate, unit_base, item_base_currency = to_base(
                db, order.org_id, item_currency, item.unit_price, effective_date
            )
            _, line_base, _ = to_base(
                db, order.org_id, item_currency, item.total_price, effective_date
            )
        item.base_currency = item_base_currency
        item.exchange_rate_to_base = item_rate
        item.unit_price_base = unit_base
        item.total_price_base = line_base

    paid_base = Decimal("0.00")
    payments = db.query(OrderPayment).filter(
        OrderPayment.po_id == order.id, OrderPayment.is_deleted.is_(False)
    ).all()
    for payment in payments:
        payment_currency = (payment.currency or currency).upper()
        payment_rate, payment_base, payment_base_currency = to_base(
            db,
            order.org_id,
            payment_currency,
            payment.amount,
            payment.paid_date or effective_date,
        )
        payment.currency = payment_currency
        payment.exchange_rate = payment_rate
        payment.base_currency = payment_base_currency
        payment.base_amount = payment_base
        payment.amount_local = payment_base
        paid_base += payment_base or Decimal("0.00")

    order.advance_amount_base = paid_base.quantize(MONEY_QUANTUM)
    order.balance_amount_base = max(
        Decimal("0.00"), Decimal(str(order.total_amount_base or 0)) - paid_base
    ).quantize(MONEY_QUANTUM)
    if rate:
        order.advance_amount = (paid_base / rate).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        order.balance_amount = max(
            Decimal("0.00"), Decimal(str(order.total_amount or 0)) - order.advance_amount
        ).quantize(MONEY_QUANTUM)


def sync_order_for_current_stage(db: Session, order) -> None:
    sync_order_base_amounts(
        db,
        order,
        freeze_rate=(order.lifecycle_stage or "").upper() in ISSUED_STAGES,
    )
