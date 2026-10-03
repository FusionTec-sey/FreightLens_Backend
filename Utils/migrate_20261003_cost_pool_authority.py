"""Empty central authority history; no node enrollment or activation."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.PostingAuthority import (
    CostPoolAuthorityEpoch, IMMUTABLE_FUNCTION, immutable_trigger,
    POOL_SEQUENCE_FUNCTION, POOL_SEQUENCE_TRIGGER)


def ensure_cost_pool_authority_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        CostPoolAuthorityEpoch.__table__.create(conn, checkfirst=True)
        conn.execute(text(IMMUTABLE_FUNCTION))
        conn.execute(text(POOL_SEQUENCE_FUNCTION))
        for name, sql in (
            ('posting_authority_immutable', immutable_trigger(CostPoolAuthorityEpoch.__tablename__)),
            ('pool_authority_sequence', POOL_SEQUENCE_TRIGGER),
        ):
            exists = conn.execute(text('SELECT 1 FROM pg_trigger WHERE tgrelid = to_regclass(:table) '
                'AND tgname = :name AND NOT tgisinternal'),
                dict(table='containermgmt.' + CostPoolAuthorityEpoch.__tablename__, name=name)).scalar()
            if not exists: conn.execute(text(sql))
