import logging

from sqlalchemy import text

from Model.db import Base, engine

logger = logging.getLogger("containerMgmt.migrations.bootstrap")


def ensure_root_organisation() -> None:
    """Create the root organisation before owner-backed migrations run."""
    from Model.Credentials.Organisation import Organisation

    Base.metadata.create_all(bind=engine, tables=[Organisation.__table__])
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM usercredentials.organisations WHERE id = 1")
        ).scalar()
        if exists:
            return
        conn.execute(text("""
            INSERT INTO usercredentials.organisations
                (id, name, display_name, parent_org_id, is_active, modules,
                 plan, base_currency)
            VALUES (1, 'sahaj', 'Sahaj Construction', NULL, TRUE,
                    '{LOGISTICS,ORDERS,INVENTORY}', 'complete', 'SCR')
        """))
        conn.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('usercredentials.organisations', 'id'),
                GREATEST((SELECT max(id) FROM usercredentials.organisations), 1)
            )
        """))
    logger.info("Bootstrapped root organisation id=1")
