"""Create empty immutable provenance for safe sales-draft copies."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Orders.SalesIntentCopyOrigin import (
    GUARD_FUNCTION,
    GUARD_TRIGGER,
    IMMUTABLE_FUNCTION,
    IMMUTABLE_TRIGGER,
    SalesIntentCopyOrigin,
)


def _create_trigger(conn, name: str, ddl: str) -> None:
    exists = conn.execute(text(
        "SELECT 1 FROM pg_trigger "
        "WHERE tgrelid='containermgmt.sales_intent_copy_origins'::regclass "
        "AND tgname=:name AND NOT tgisinternal"
    ), {"name": name}).scalar()
    if not exists:
        conn.execute(text(ddl))


def ensure_sales_intent_copy_origins_schema() -> None:
    """Replay-safe additive schema only; no copied drafts or business seeds."""

    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        SalesIntentCopyOrigin.__table__.create(conn, checkfirst=True)
        conn.execute(text(IMMUTABLE_FUNCTION))
        _create_trigger(conn, "sales_intent_copy_immutable", IMMUTABLE_TRIGGER)
        conn.execute(text(GUARD_FUNCTION))
        _create_trigger(conn, "sales_intent_copy_origin_guard", GUARD_TRIGGER)
