import logging
import io
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc

from Model.db import get_db
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.DefectReport import DefectReport, DefectItem, DefectImage
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.containermgmt.Orders.Notification import Notification
from Model.containermgmt.Container.ContainerDetails import ContainerDetails
from Model.containermgmt.Container.BillOfLanding import BillOfLanding
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from Utils.org_filter import OrgContext, apply_org_filter
from Utils.blob_storage import blob_storage
from Utils.reportGenerator import generate_defect_report_pdf

logger = logging.getLogger("containerMgmt.orders.defects")

DefectRouter = APIRouter(prefix="/defects", tags=["Damage & Defects"])

def format_defect(d: DefectReport) -> dict:
    return {
        "id": d.id,
        "defect_number": d.defect_number,
        "report_type": d.report_type,
        "category": d.category,
        "title": d.title,
        "description": d.description,
        "po_id": d.po_id,
        "po_number": d.purchase_order.po_number if d.purchase_order else None,
        "receipt_id": d.receipt_id,
        "container_id": d.container_id,
        "container_no": d.container.container_no if d.container else None,
        "bill_of_lading_no": d.bill_of_lading_no,
        "unloading_date": d.unloading_date.isoformat() if d.unloading_date else None,
        "discovery_date": d.discovery_date.isoformat() if d.discovery_date else None,
        "status": d.status,
        "resolution_type": d.resolution_type,
        "resolution_notes": d.resolution_notes,
        "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
        "org_id": d.org_id,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "items": [
            {
                "id": it.id,
                "item_description": it.item_description,
                "quantity_affected": float(it.quantity_affected or 0),
                "unit": it.unit,
                "notes": it.notes,
            }
            for it in (d.items or []) if not it.is_deleted
        ],
        "images": [
            {
                "id": img.id,
                "file_path": img.file_path,
                "caption": img.caption,
            }
            for img in (d.images or []) if not img.is_deleted
        ]
    }

@DefectRouter.get("")
@DefectRouter.get("/")
async def list_defects(
    report_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    po_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(DefectReport)
        .options(
            joinedload(DefectReport.purchase_order),
            joinedload(DefectReport.container),
            joinedload(DefectReport.items),
            joinedload(DefectReport.images)
        )
        .filter(DefectReport.is_deleted == False)
    )
    query = apply_org_filter(query, DefectReport, org_context)

    if report_type and report_type != "ALL":
        query = query.filter(DefectReport.report_type == report_type)

    if status and status != "ALL":
        query = query.filter(DefectReport.status == status)

    if po_id:
        query = query.filter(DefectReport.po_id == po_id)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                DefectReport.defect_number.ilike(s),
                DefectReport.title.ilike(s),
                DefectReport.category.ilike(s),
                DefectReport.bill_of_lading_no.ilike(s)
            )
        )

    defects = query.order_by(desc(DefectReport.id)).all()
    return [format_defect(d) for d in defects]

@DefectRouter.get("/{defect_id}")
async def get_defect(
    defect_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(DefectReport)
        .options(
            joinedload(DefectReport.purchase_order),
            joinedload(DefectReport.container),
            joinedload(DefectReport.items),
            joinedload(DefectReport.images)
        )
        .filter(DefectReport.id == defect_id, DefectReport.is_deleted == False)
    )
    query = apply_org_filter(query, DefectReport, org_context)
    d = query.first()
    if not d:
        raise HTTPException(status_code=404, detail="Defect report not found")
    return format_defect(d)

@DefectRouter.post("")
@DefectRouter.post("/")
async def create_defect(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    def_num = payload.get("defect_number", "").strip() or f"DEF-{datetime.utcnow().strftime('%Y%m%d')}-{datetime.utcnow().strftime('%H%M%S')}"
    
    disc_date = date.today()
    if payload.get("discovery_date"):
        disc_date = datetime.strptime(payload["discovery_date"][:10], "%Y-%m-%d").date()

    unload_date = None
    if payload.get("unloading_date"):
        unload_date = datetime.strptime(payload["unloading_date"][:10], "%Y-%m-%d").date()

    po_id = payload.get("po_id")
    target_org_id = payload.get("org_id") or org_context.selected_org_id or current_user.org_id or 1

    if po_id:
        po_rec = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if po_rec:
            target_org_id = po_rec.org_id

    new_def = DefectReport(
        defect_number=def_num,
        report_type=payload.get("report_type", "GOODS_DEFECT"),
        category=payload.get("category", "Shortage"),
        title=payload.get("title", "").strip() or "Defect Report",
        description=payload.get("description", "").strip() or None,
        po_id=po_id,
        receipt_id=payload.get("receipt_id"),
        container_id=payload.get("container_id"),
        bill_of_lading_no=payload.get("bill_of_lading_no", "").strip() or None,
        discovery_date=disc_date,
        unloading_date=unload_date,
        status="OPEN",
        org_id=target_org_id,
        created_by=current_user.id
    )
    db.add(new_def)
    db.flush()

    for item in payload.get("items", []):
        desc_text = item.get("item_description", "").strip()
        if not desc_text: continue
        it_obj = DefectItem(
            defect_id=new_def.id,
            item_description=desc_text,
            quantity_affected=float(item.get("quantity_affected") or 1.0),
            unit=item.get("unit", "PCS"),
            notes=item.get("notes", "").strip() or None,
            created_by=current_user.id
        )
        db.add(it_obj)

    # If linked to a PO, update status to DEFECT_REOPENED
    if po_id:
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if po:
            def_st = db.query(OrderStatus).filter(OrderStatus.code == "DEFECT_REOPENED").first()
            if def_st:
                po.status_id = def_st.id
                po.status = "DEFECT_REOPENED"
                po.status_label = "Defect / Reopened"

    # Notification
    notif = Notification(
        org_id=target_org_id,
        event_type="DEFECT_REPORTED",
        title="New Defect Reported",
        message=f"Defect #{new_def.defect_number} ({new_def.category}) reported by {current_user.username}.",
        link_entity_type="DEFECT",
        link_entity_id=new_def.id
    )
    db.add(notif)

    db.commit()
    db.refresh(new_def)
    return format_defect(new_def)

@DefectRouter.post("/{defect_id}/images")
async def upload_defect_image(
    defect_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(DefectReport).filter(DefectReport.id == defect_id, DefectReport.is_deleted == False)
    query = apply_org_filter(query, DefectReport, org_context)
    d = query.first()
    if not d:
        raise HTTPException(status_code=404, detail="Defect report not found")

    file_bytes = await file.read()
    key = blob_storage.upload_file(
        file_bytes=file_bytes,
        file_name=file.filename,
        folder=f"defects/{d.defect_number}"
    )

    img = DefectImage(
        defect_id=d.id,
        file_path=key,
        caption=caption,
        created_by=current_user.id
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return {"success": True, "image_id": img.id, "file_path": key}

@DefectRouter.put("/{defect_id}")
async def update_defect(
    defect_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(DefectReport)
        .options(
            joinedload(DefectReport.purchase_order),
            joinedload(DefectReport.container),
            joinedload(DefectReport.items),
            joinedload(DefectReport.images)
        )
        .filter(DefectReport.id == defect_id, DefectReport.is_deleted == False)
    )
    query = apply_org_filter(query, DefectReport, org_context)
    d = query.first()
    if not d:
        raise HTTPException(status_code=404, detail="Defect report not found")

    if d.status in ["RESOLVED", "CLOSED"]:
        raise HTTPException(
            status_code=400,
            detail="Resolved or closed reports cannot be edited. Reopen the report to modify."
        )

    if "title" in payload:
        d.title = payload["title"].strip() or d.title
    if "description" in payload:
        d.description = payload["description"].strip()
    if "category" in payload:
        d.category = payload["category"]
    if "report_type" in payload:
        d.report_type = payload["report_type"]
    if "po_id" in payload:
        d.po_id = payload["po_id"]
    if "container_id" in payload:
        d.container_id = payload["container_id"]
        if d.container_id:
            cont = db.query(ContainerDetails).filter(ContainerDetails.Container_ID == d.container_id).first()
            if cont and cont.BillOfLanding:
                d.bill_of_lading_no = cont.BillOfLanding
    if "discovery_date" in payload and payload["discovery_date"]:
        try:
            d.discovery_date = datetime.strptime(str(payload["discovery_date"])[:10], "%Y-%m-%d").date()
        except:
            pass

    d.updated_by = current_user.id
    d.updated_at = datetime.utcnow()

    if "items" in payload and isinstance(payload["items"], list):
        for existing in (d.items or []):
            existing.is_deleted = True

        for item in payload["items"]:
            desc_text = item.get("item_description", "").strip()
            if not desc_text: continue
            it_obj = DefectItem(
                defect_id=d.id,
                item_description=desc_text,
                quantity_affected=float(item.get("quantity_affected") or 1.0),
                unit=item.get("unit", "PCS"),
                notes=item.get("notes", "").strip() or None,
                created_by=current_user.id
            )
            db.add(it_obj)

    db.commit()
    db.refresh(d)
    return format_defect(d)

@DefectRouter.put("/{defect_id}/resolve")
async def resolve_defect(
    defect_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(DefectReport).filter(DefectReport.id == defect_id, DefectReport.is_deleted == False)
    query = apply_org_filter(query, DefectReport, org_context)
    d = query.first()
    if not d:
        raise HTTPException(status_code=404, detail="Defect report not found")

    d.status = "RESOLVED"
    d.resolution_type = payload.get("resolution_type", "REPLACEMENT")  # REPLACEMENT, CREDIT_NOTE, REFUND, ACCEPTED_AS_IS, CLOSED
    d.resolution_notes = payload.get("resolution_notes", "").strip() or None
    d.resolved_at = date.today()
    d.resolved_by = current_user.id
    d.updated_by = current_user.id

    # If linked to PO, can resolve back to COMPLETED
    if d.po_id and payload.get("mark_order_completed", True):
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == d.po_id).first()
        if po and po.status == "DEFECT_REOPENED":
            comp_st = db.query(OrderStatus).filter(OrderStatus.code == "COMPLETED").first()
            if comp_st:
                po.status_id = comp_st.id
                po.status = "COMPLETED"
                po.status_label = "Completed"

    db.commit()
    db.refresh(d)
    return format_defect(d)

@DefectRouter.get("/{defect_id}/pdf")
async def get_defect_pdf(
    defect_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(DefectReport)
        .options(
            joinedload(DefectReport.purchase_order),
            joinedload(DefectReport.container),
            joinedload(DefectReport.items),
            joinedload(DefectReport.images)
        )
        .filter(DefectReport.id == defect_id, DefectReport.is_deleted == False)
    )
    query = apply_org_filter(query, DefectReport, org_context)
    d = query.first()
    if not d:
        raise HTTPException(status_code=404, detail="Defect report not found")

    pdf_bytes = generate_defect_report_pdf(d)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{d.defect_number}.pdf"'}
    )
