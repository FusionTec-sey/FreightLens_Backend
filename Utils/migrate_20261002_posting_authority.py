"""Add empty authority records and guards; never enroll nodes or activate branches."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.PostingAuthority import (
    StoreNode, BranchAuthorityEpoch, IMMUTABLE_FUNCTION, SEQUENCE_FUNCTION,
    SEQUENCE_TRIGGER, immutable_trigger,
)


def prepare_posting_authority(conn):
    for model in (StoreNode, BranchAuthorityEpoch):
        model.__table__.create(conn, checkfirst=True)
    conn.execute(text(IMMUTABLE_FUNCTION))
    conn.execute(text(SEQUENCE_FUNCTION))
    for table, name, sql in (
        (StoreNode.__tablename__, "posting_authority_immutable", immutable_trigger(StoreNode.__tablename__)),
        (BranchAuthorityEpoch.__tablename__, "posting_authority_immutable", immutable_trigger(BranchAuthorityEpoch.__tablename__)),
        (BranchAuthorityEpoch.__tablename__, "posting_authority_sequence", SEQUENCE_TRIGGER),
    ):
        exists = conn.execute(text("""SELECT 1 FROM pg_trigger
            WHERE tgrelid = to_regclass(:table) AND tgname = :name AND NOT tgisinternal"""),
            {"table": "containermgmt." + table, "name": name}).scalar()
        if not exists:
            conn.execute(text(sql))


def ensure_posting_authority_schema():
    with engine.begin() as conn:
        prepare_posting_authority(conn)
