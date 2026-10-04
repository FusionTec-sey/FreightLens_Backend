"""Create the empty immutable T13 sales-posting history and database guards."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Orders.SalesPosting import (
    ATTEMPT_GUARD_FUNCTION,
    ATTEMPT_GUARD_TRIGGER,
    CARD_GUARD_FUNCTION,
    CARD_GUARD_TRIGGER,
    COMMITTED_RELEASE_FUNCTION,
    COMMITTED_RELEASE_TRIGGER,
    COMMITTED_RESERVATION_UPDATE_FUNCTION,
    COMMITTED_RESERVATION_UPDATE_TRIGGER,
    IMMUTABLE_FUNCTION,
    INVOICE_GUARD_FUNCTION,
    INVOICE_GUARD_TRIGGER,
    LINE_GUARD_FUNCTION,
    LINE_GUARD_TRIGGER,
    MODELS,
    PAYMENT_GUARD_FUNCTION,
    PAYMENT_GUARD_TRIGGER,
    RESERVATION_GUARD_FUNCTION,
    RESERVATION_GUARD_TRIGGER,
    SalesCardConfirmation,
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoicePayment,
    SalesInvoiceReservation,
    SalesPostingAttempt,
    SalesPostingTender,
    TENDER_GUARD_FUNCTION,
    TENDER_GUARD_TRIGGER,
    TOTALS_FUNCTION,
    immutable_trigger,
    totals_trigger,
)


def _trigger(conn, table: str, name: str, ddl: str) -> None:
    exists = conn.execute(text(
        "SELECT 1 FROM pg_trigger WHERE tgrelid=CAST(:table AS regclass) "
        "AND tgname=:name AND NOT tgisinternal"
    ), {"table": f"containermgmt.{table}", "name": name}).scalar()
    if not exists:
        conn.execute(text(ddl))


def ensure_sales_posting_schema() -> None:
    """Replay-safe creation only; no seed, backfill or financial activation."""

    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for model in MODELS:
            model.__table__.create(conn, checkfirst=True)

        conn.execute(text(IMMUTABLE_FUNCTION))
        for model in MODELS:
            _trigger(
                conn,
                model.__tablename__,
                f"{model.__tablename__}_immutable",
                immutable_trigger(model.__tablename__),
            )

        for model, function, trigger_name, trigger in (
            (SalesPostingAttempt, ATTEMPT_GUARD_FUNCTION,
             "sales_post_attempt_guard", ATTEMPT_GUARD_TRIGGER),
            (SalesPostingTender, TENDER_GUARD_FUNCTION,
             "sales_post_tender_guard", TENDER_GUARD_TRIGGER),
            (SalesCardConfirmation, CARD_GUARD_FUNCTION,
             "sales_card_confirmation_guard", CARD_GUARD_TRIGGER),
            (SalesInvoice, INVOICE_GUARD_FUNCTION,
             "sales_invoice_guard", INVOICE_GUARD_TRIGGER),
            (SalesInvoiceLine, LINE_GUARD_FUNCTION,
             "sales_invoice_line_guard", LINE_GUARD_TRIGGER),
            (SalesInvoicePayment, PAYMENT_GUARD_FUNCTION,
             "sales_invoice_payment_guard", PAYMENT_GUARD_TRIGGER),
            (SalesInvoiceReservation, RESERVATION_GUARD_FUNCTION,
             "sales_invoice_reservation_guard", RESERVATION_GUARD_TRIGGER),
        ):
            conn.execute(text(function))
            _trigger(conn, model.__tablename__, trigger_name, trigger)

        conn.execute(text(TOTALS_FUNCTION))
        for model in (
            SalesPostingAttempt,
            SalesPostingTender,
            SalesInvoice,
            SalesInvoiceLine,
            SalesInvoicePayment,
            SalesInvoiceReservation,
        ):
            _trigger(
                conn,
                model.__tablename__,
                f"{model.__tablename__}_totals_guard",
                totals_trigger(model.__tablename__),
            )

        conn.execute(text(COMMITTED_RELEASE_FUNCTION))
        _trigger(conn, "inventory_stock_movements",
                 "posted_sale_reservation_release_guard",
                 COMMITTED_RELEASE_TRIGGER)
        conn.execute(text(COMMITTED_RESERVATION_UPDATE_FUNCTION))
        _trigger(conn, "inventory_stock_reservations",
                 "posted_sale_reservation_update_guard",
                 COMMITTED_RESERVATION_UPDATE_TRIGGER)
