import logging
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc, func

from Model.db import get_db
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.StoreRequest import StoreRequest
from Model.containermgmt.Orders.GoodsReceipt import GoodsReceipt
from Model.containermgmt.Orders.DefectReport import DefectReport
from Model.containermgmt.Orders.OrderStatusHistory import OrderStatusHistory
from Model.Credentials.users import User
from Model.Credentials.Organisation import Organisation
from auth.dependencies import get_current_user, get_org_context
from Utils.org_filter import OrgContext, apply_org_filter

logger = logging.getLogger("containerMgmt.orders.dailywork")

DailyWorkRouter = APIRouter(prefix="/daily-work", tags=["Daily Operations & EOD"])

@DailyWorkRouter.get("")
@DailyWorkRouter.get("/")
async def get_daily_work_queue(
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    """
    Returns today's active pending work queue grouped by operational category:
    - Sourcing: Requests submitted or in sourcing stage
    - PO Preparation: Draft POs awaiting completion
    - Awaiting Payment: Ordered POs with payment pending
    - Production: POs in manufacturing
    - Ready/Packing: POs ready or being packed
    - In Transit: POs shipped but not yet arrived
    - Awaiting Receipt: Containers arrived / POs awaiting warehouse verification
    - Defects: Open defects awaiting resolution
    """
    base_orders = db.query(PurchaseOrder).filter(PurchaseOrder.is_deleted == False)
    base_orders = apply_org_filter(base_orders, PurchaseOrder, org_context)
    all_active_orders = base_orders.filter(PurchaseOrder.status.notin_(["COMPLETED", "CANCELLED"])).all()

    # Base requests
    base_requests = db.query(StoreRequest).filter(StoreRequest.is_deleted == False)
    base_requests = apply_org_filter(base_requests, StoreRequest, org_context)
    active_requests = base_requests.filter(StoreRequest.status.in_(["SUBMITTED", "SOURCING"])).all()

    # Base defects
    base_defects = db.query(DefectReport).filter(DefectReport.is_deleted == False, DefectReport.status == "OPEN")
    base_defects = apply_org_filter(base_defects, DefectReport, org_context)
    open_defects = base_defects.all()

    queue = {
        "sourcing": [
            {
                "id": r.id,
                "type": "REQUEST",
                "reference": r.request_number,
                "title": r.title or "Items Request",
                "department": r.department,
                "status": r.status_label,
                "required_date": r.required_date.isoformat() if r.required_date else None,
                "urgent": False,
            }
            for r in active_requests
        ],
        "po_preparation": [
            {
                "id": o.id,
                "type": "PO",
                "reference": o.po_number,
                "title": o.goods_description or o.po_number,
                "company": o.company,
                "status": o.status_label,
                "urgent": bool(o.urgent_action),
            }
            for o in all_active_orders if o.status in ["DRAFT", "SOURCING"]
        ],
        "awaiting_payment": [
            {
                "id": o.id,
                "type": "PO",
                "reference": o.po_number,
                "title": o.goods_description or o.po_number,
                "company": o.company,
                "status": o.status_label,
                "payment_status": o.payment_status,
                "urgent": bool(o.urgent_action),
            }
            for o in all_active_orders if o.status == "ORDERED" or (o.payment_status != "FULLY_PAID" and o.status not in ["DRAFT", "SOURCING"])
        ],
        "in_production": [
            {
                "id": o.id,
                "type": "PO",
                "reference": o.po_number,
                "title": o.goods_description or o.po_number,
                "company": o.company,
                "status": o.status_label,
                "eta_date": o.eta_date.isoformat() if o.eta_date else None,
                "urgent": bool(o.urgent_action),
            }
            for o in all_active_orders if o.status == "IN_PRODUCTION"
        ],
        "ready_and_packing": [
            {
                "id": o.id,
                "type": "PO",
                "reference": o.po_number,
                "title": o.goods_description or o.po_number,
                "company": o.company,
                "status": o.status_label,
                "urgent": bool(o.urgent_action),
            }
            for o in all_active_orders if o.status in ["READY", "PACKED"]
        ],
        "in_transit": [
            {
                "id": o.id,
                "type": "PO",
                "reference": o.po_number,
                "title": o.goods_description or o.po_number,
                "company": o.company,
                "status": o.status_label,
                "eta_date": o.eta_date.isoformat() if o.eta_date else None,
                "urgent": bool(o.urgent_action),
            }
            for o in all_active_orders if o.status == "SHIPPED"
        ],
        "awaiting_receipt": [
            {
                "id": o.id,
                "type": "PO",
                "reference": o.po_number,
                "title": o.goods_description or o.po_number,
                "company": o.company,
                "status": o.status_label,
                "urgent": bool(o.urgent_action),
            }
            for o in all_active_orders if o.status == "ARRIVED" or o.receipt_status == "PENDING"
        ],
        "defects": [
            {
                "id": d.id,
                "type": "DEFECT",
                "reference": d.defect_number,
                "title": d.title,
                "category": d.category,
                "status": d.status,
                "discovery_date": d.discovery_date.isoformat() if d.discovery_date else None,
            }
            for d in open_defects
        ]
    }
    
    total_pending = sum(len(items) for items in queue.values())
    return {
        "total_pending_items": total_pending,
        "categories": queue
    }

@DailyWorkRouter.get("/eod-report")
async def get_eod_report(
    target_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    """
    Generates End-of-Day Management Report:
    1. Group-wide summary (Noblecon, Sahajanand, Combined)
    2. Active orders status summary
    3. Today's milestone activity & employee work summary
    4. Exceptions & open defects
    """
    report_date = date.today()
    if target_date:
        try: report_date = datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        except: pass

    # Organizations
    orgs = db.query(Organisation).filter(Organisation.is_active == True).all()

    # Active orders
    base_orders = db.query(PurchaseOrder).filter(PurchaseOrder.is_deleted == False)
    base_orders = apply_org_filter(base_orders, PurchaseOrder, org_context)
    orders = base_orders.all()

    active_count = len([o for o in orders if o.status not in ["COMPLETED", "CANCELLED"]])
    completed_count = len([o for o in orders if o.status == "COMPLETED"])
    urgent_count = len([o for o in orders if o.urgent_action and o.status not in ["COMPLETED", "CANCELLED"]])

    # Status breakdown
    status_counts = {}
    for o in orders:
        st = o.status_label or o.status
        status_counts[st] = status_counts.get(st, 0) + 1

    # Defects
    base_defects = db.query(DefectReport).filter(DefectReport.is_deleted == False)
    base_defects = apply_org_filter(base_defects, DefectReport, org_context)
    open_defects = base_defects.filter(DefectReport.status == "OPEN").all()

    # Today's user activity from status history
    today_start = datetime.combine(report_date, datetime.min.time())
    today_end = datetime.combine(report_date, datetime.max.time())
    
    activity = (
        db.query(OrderStatusHistory)
        .options(joinedload(OrderStatusHistory.user))
        .filter(OrderStatusHistory.changed_at >= today_start, OrderStatusHistory.changed_at <= today_end)
        .all()
    )

    employee_summary = {}
    for a in activity:
        u_name = a.user.username if a.user else "System"
        employee_summary[u_name] = employee_summary.get(u_name, 0) + 1

    return {
        "report_date": report_date.isoformat(),
        "generated_at": datetime.utcnow().isoformat(),
        "group_summary": {
            "total_orders": len(orders),
            "active_orders": active_count,
            "completed_orders": completed_count,
            "urgent_orders": urgent_count,
            "open_defects": len(open_defects),
        },
        "status_breakdown": status_counts,
        "employee_work_summary": [
            {"username": k, "updates_count": v} for k, v in employee_summary.items()
        ],
        "active_exceptions": [
            {
                "reference": d.defect_number,
                "category": d.category,
                "title": d.title,
                "date": d.discovery_date.isoformat() if d.discovery_date else None
            }
            for d in open_defects
        ]
    }
