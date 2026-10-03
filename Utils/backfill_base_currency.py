import logging
import os
from datetime import date

from Model.containermgmt.MasterData.Currency import CurrencyExchangeRate
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.db import SessionLocal
from Services.currency_service import CurrencyRateNotFound, sync_order_for_current_stage


logger = logging.getLogger("containerMgmt.backfill_base_currency")


def backfill_base_currency_values(db) -> tuple[int, list[str]]:
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment not in {"development", "test"}:
        raise RuntimeError("Base-currency demo backfill is restricted to development and test")

    # Demo rates were historically seeded with today's effective date. Clone
    # their earliest configured value to a baseline date so older demo orders
    # can be converted deterministically without weakening runtime rate checks.
    rates = db.query(CurrencyExchangeRate).filter(
        CurrencyExchangeRate.is_active.is_(True),
        CurrencyExchangeRate.is_deleted.is_(False),
    ).order_by(CurrencyExchangeRate.effective_date).all()
    seen_pairs = set()
    for rate in rates:
        key = (rate.org_id, rate.from_currency, rate.to_currency)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        if rate.effective_date > date(2000, 1, 1):
            db.add(CurrencyExchangeRate(
                org_id=rate.org_id,
                from_currency=rate.from_currency,
                to_currency=rate.to_currency,
                rate=rate.rate,
                effective_date=date(2000, 1, 1),
                is_active=True,
            ))
    db.flush()

    updated = 0
    errors = []
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.is_deleted.is_(False)).all()
    for order in orders:
        try:
            sync_order_for_current_stage(db, order)
            updated += 1
        except CurrencyRateNotFound as exc:
            errors.append(f"{order.po_number}: {exc}")
    if errors:
        db.rollback()
    else:
        db.commit()
    return updated, errors


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as session:
        count, failures = backfill_base_currency_values(session)
        if failures:
            for failure in failures:
                logger.error(failure)
            raise SystemExit(f"Backfill rolled back; {len(failures)} order(s) have no exchange rate")
        logger.info("Backfilled base-currency values for %d purchase orders", count)
