import logging
from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations")

def ensure_decouple_financial_status():
    """
    Idempotent migration to decouple financial status from operational workflow stages:
    1. Deactivate PART_PAID and PAID in containermgmt.order_status table.
    2. Recalibrate operational stages sequence and progress percentages.
    3. Update any purchase order having status IN ('PART_PAID', 'PAID') to physical stage 'ORDERED'
       while preserving/setting their payment_status.
    """
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                # 1. Deactivate financial statuses from order_status
                conn.execute(text("""
                    UPDATE containermgmt.order_status
                    SET is_active = FALSE
                    WHERE code IN ('PART_PAID', 'PAID');
                """))
                
                # 2. Update operational sequences and progress
                operational_updates = [
                    ("DRAFT", 1, 5, "bg-slate-400", "bg-slate-100 text-slate-700 border-slate-300"),
                    ("SUBMITTED", 2, 15, "bg-blue-400", "bg-blue-100 text-blue-700 border-blue-300"),
                    ("SOURCING", 3, 25, "bg-indigo-400", "bg-indigo-100 text-indigo-700 border-indigo-300"),
                    ("ORDERED", 4, 40, "bg-purple-500", "bg-purple-100 text-purple-700 border-purple-300"),
                    ("IN_PRODUCTION", 5, 55, "bg-orange-500", "bg-orange-100 text-orange-800 border-orange-300"),
                    ("READY", 6, 70, "bg-yellow-500", "bg-yellow-100 text-yellow-800 border-yellow-300"),
                    ("PACKED", 7, 78, "bg-lime-500", "bg-lime-100 text-lime-800 border-lime-300"),
                    ("SHIPPED", 8, 85, "bg-cyan-500", "bg-cyan-100 text-cyan-800 border-cyan-300"),
                    ("ARRIVED", 9, 92, "bg-blue-600", "bg-blue-100 text-blue-800 border-blue-300"),
                    ("RECEIVED", 10, 96, "bg-emerald-500", "bg-emerald-100 text-emerald-800 border-emerald-300"),
                    ("COMPLETED", 11, 100, "bg-emerald-600", "bg-emerald-100 text-emerald-800 border-emerald-300"),
                    ("CANCELLED", 12, 0, "bg-red-500", "bg-red-100 text-red-800 border-red-300"),
                    ("DEFECT_REOPENED", 13, 95, "bg-rose-500", "bg-rose-100 text-rose-800 border-rose-300"),
                ]
                for code, seq, prog, col, badge in operational_updates:
                    conn.execute(text("""
                        UPDATE containermgmt.order_status
                        SET sequence_order = :seq, progress = :prog, color = :col, badge_color = :badge, is_active = TRUE
                        WHERE code = :code;
                    """), {"code": code, "seq": seq, "prog": prog, "col": col, "badge": badge})

                # 3. Disentangle any purchase orders whose status was set to PART_PAID or PAID
                conn.execute(text("""
                    UPDATE containermgmt.purchase_orders
                    SET 
                        payment_status = CASE 
                            WHEN status = 'PAID' THEN 'FULLY_PAID'
                            WHEN status = 'PART_PAID' THEN 'PART_PAID'
                            ELSE COALESCE(payment_status, 'NONE')
                        END,
                        status = CASE
                            WHEN receipt_status = 'RECEIVED' THEN 'RECEIVED'
                            WHEN shipment_status IN ('SHIPPED', 'ARRIVED') THEN 'SHIPPED'
                            WHEN production_status = 'IN_PRODUCTION' THEN 'IN_PRODUCTION'
                            WHEN production_status = 'READY' THEN 'READY'
                            ELSE 'ORDERED'
                        END,
                        status_label = CASE
                            WHEN receipt_status = 'RECEIVED' THEN 'Received'
                            WHEN shipment_status IN ('SHIPPED', 'ARRIVED') THEN 'Shipped'
                            WHEN production_status = 'IN_PRODUCTION' THEN 'In Production'
                            WHEN production_status = 'READY' THEN 'Ready'
                            ELSE 'Ordered'
                        END,
                        status_id = (SELECT id FROM containermgmt.order_status WHERE code = 'ORDERED' LIMIT 1)
                    WHERE status IN ('PAID', 'PART_PAID');
                """))
                conn.commit()
                logger.info("Successfully decoupled financial status from physical workflow stages.")
    except Exception as e:
        logger.error(f"Error in ensure_decouple_financial_status: {e}")
