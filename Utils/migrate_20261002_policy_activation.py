from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation, FUNCTION, TRIGGER, PRODUCT_GUARD, PRODUCT_TRIGGER


def ensure_policy_activation_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        ProductPolicyActivation.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        conn.execute(text(PRODUCT_GUARD))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger
            WHERE tgrelid=to_regclass('containermgmt.inventory_product_policy_activations')
            AND tgname='policy_activation_immutable' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger
            WHERE tgrelid=to_regclass('containermgmt.products')
            AND tgname='activated_product_guard' AND NOT tgisinternal""")).scalar():
            conn.execute(text(PRODUCT_TRIGGER))
