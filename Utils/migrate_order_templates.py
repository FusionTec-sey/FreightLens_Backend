import logging
from sqlalchemy import text
from Model.db import engine, Base
from Model.containermgmt import OrderTemplate, OrderTemplateItem

logger = logging.getLogger("containerMgmt.migrations")

def ensure_order_templates_schema():
    """
    Ensures containermgmt.order_templates and containermgmt.order_template_items are created.
    """
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Order templates schema verified.")
    except Exception as e:
        logger.error(f"Error ensuring order templates schema: {e}")
