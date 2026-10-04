"""Create the empty immutable T16 collection history and deferred guards."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Orders.SalesCollection import (
    ALLOCATION_GUARD_FUNCTION,
    ALLOCATION_GUARD_TRIGGER,
    COMMITTED_HANDOVER_FUNCTION,
    COMMITTED_HANDOVER_TRIGGER,
    HEADER_GUARD_FUNCTION,
    HEADER_GUARD_TRIGGER,
    IMMUTABLE_FUNCTION,
    MODELS,
    SalesCollection,
    SalesCollectionAllocation,
    immutable_trigger,
)


def _trigger(conn, table: str, name: str, ddl: str) -> None:
    exists = conn.execute(text(
        "SELECT 1 FROM pg_trigger WHERE tgrelid=CAST(:table AS regclass) "
        "AND tgname=:name AND NOT tgisinternal"
    ), {"table": f"containermgmt.{table}", "name": name}).scalar()
    if not exists:
        conn.execute(text(ddl))


def ensure_sales_collection_schema() -> None:
    """Replay-safe creation only; no seed, backfill or public collection action."""

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

        conn.execute(text(HEADER_GUARD_FUNCTION))
        _trigger(
            conn,
            SalesCollection.__tablename__,
            "sales_collection_header_guard",
            HEADER_GUARD_TRIGGER,
        )
        conn.execute(text(ALLOCATION_GUARD_FUNCTION))
        _trigger(
            conn,
            SalesCollectionAllocation.__tablename__,
            "sales_collection_allocation_guard",
            ALLOCATION_GUARD_TRIGGER,
        )
        conn.execute(text(COMMITTED_HANDOVER_FUNCTION))
        _trigger(
            conn,
            "inventory_stock_movements",
            "posted_sale_handover_collection_guard",
            COMMITTED_HANDOVER_TRIGGER,
        )
