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
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Model.containermgmt.Orders.DefectReport import DefectReport, DefectImage
from Model.containermgmt.Orders.OrderPayment import OrderPayment
from Model.containermgmt.Orders.OrderShipment import OrderShipment
from Model.containermgmt.Orders.OrderStatusHistory import OrderStatusHistory
from Model.containermgmt.Orders.StoreRequest import StoreRequest, StoreRequestItem
from Model.containermgmt.Orders.Notification import Notification
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Container.BillOfLanding import BillOfLanding
from Model.containermgmt.Container.ContainerDetails import ContainerDetails
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from Utils.org_filter import OrgContext, apply_org_filter
from Utils.blob_storage import blob_storage
from Utils.reportGenerator import generate_defect_report_pdf

logger = logging.getLogger("containerMgmt.orders")

OrderRouter = APIRouter(prefix="/orders", tags=["Purchase Orders"])

def is_accounts_user(user: User, org_context: OrgContext) -> bool:
    if org_context.is_root:
        return True
    user_roles = [r.name for r in getattr(user, "roles", [])]
    return any(r in ["Administrator", "Admin", "Account", "Accounts", "Accounts_Finance", "Finance"] for r in user_roles)

def order_to_dict(order: PurchaseOrder, is_accounts: bool = True) -> dict:
    supplier_name = order.company if is_accounts else "Authorized Supplier"
    if is_accounts and order.supplier_rel and order.supplier_rel.name:
        supplier_name = order.supplier_rel.name

    status_name = order.status_label or order.status
    status_progress = 50
    status_color = "bg-blue-500"
    badge_color = "bg-blue-50 text-blue-800 border-blue-200"

    if order.order_status_rel:
        status_name = order.order_status_rel.name
        status_progress = order.order_status_rel.progress
        status_color = order.order_status_rel.color
        badge_color = order.order_status_rel.badge_color or badge_color

    res = {
        "id": order.id,
        "po_number": order.po_number,
        "po_nce": order.po_nce if is_accounts else None,
        "request_id": order.request_id,
        "request_number": order.store_request.request_number if order.store_request else None,
        "supplier": order.supplier_id if is_accounts else None,
        "company": supplier_name,
        "goods_description": order.goods_description,
        "material_ids": order.material_ids or [],
        "org_id": order.org_id,
        
        # Lifecycle and tracking dimensions
        "status_id": order.status_id,
        "status": order.status,
        "status_label": status_name,
        "status_progress": status_progress,
        "status_color": status_color,
        "badge_color": badge_color,
        
        "payment_status": order.payment_status or "NONE",
        "production_status": order.production_status or "NOT_STARTED",
        "shipment_status": order.shipment_status or "NOT_SHIPPED",
        "receipt_status": order.receipt_status or "PENDING",

        # Financials (Accounts only)
        "total_amount": float(order.total_amount) if order.total_amount and is_accounts else None,
        "advance_amount": float(order.advance_amount) if order.advance_amount and is_accounts else None,
        "balance_amount": float(order.balance_amount) if order.balance_amount and is_accounts else None,
        "currency": order.currency or "USD",

        # Legacy fields
        "sheet_type": order.sheet_type,
        "consignee": order.consignee,
        "year": order.year,
        "urgent_action": bool(order.urgent_action),
        
        # Milestone dates
        "order_mail_date": order.order_mail_date.isoformat() if order.order_mail_date else None,
        "quote_sent_date": order.quote_sent_date.isoformat() if order.quote_sent_date else None,
        "quote_received_date": order.quote_received_date.isoformat() if order.quote_received_date else None,
        "pi_confirmed_date": order.pi_confirmed_date.isoformat() if order.pi_confirmed_date else None,
        "payment_date": order.payment_date.isoformat() if order.payment_date and is_accounts else None,
        "balance_payment_date": order.balance_payment_date.isoformat() if order.balance_payment_date and is_accounts else None,
        "eta_date": order.eta_date.isoformat() if order.eta_date else None,
        "freight_type": order.freight_type or "Sea Freight",
        "remark": order.remark,
        "created_at": order.created_at.isoformat() if order.created_at else None,

        # Line items
        "items": [
            {
                "id": it.id,
                "product_id": it.product_id,
                "item_code": it.item_code,
                "description": it.description,
                "quantity_ordered": float(it.quantity_ordered or 0),
                "quantity_packed": float(it.quantity_packed or 0),
                "quantity_received": float(it.quantity_received or 0),
                "unit": it.unit,
                "unit_price": float(it.unit_price) if it.unit_price and is_accounts else None,
                "total_price": float(it.total_price) if it.total_price and is_accounts else None,
                "notes": it.notes,
            }
            for it in (order.items or []) if not it.is_deleted
        ],

        # Linked shipments
        "shipments": [
            {
                "id": sh.id,
                "bill_of_lading_no": sh.bill_of_lading_no,
                "container_id": sh.container_id,
                "container_no": sh.container.container_no if sh.container else None,
                "arrival_date": sh.bill_of_lading.ArrivalDate.isoformat() if sh.bill_of_lading and sh.bill_of_lading.ArrivalDate else None,
                "shipment_status": sh.shipment_status,
                "notes": sh.notes,
            }
            for sh in (order.shipments or []) if not sh.is_deleted
        ],

        # Linked payments (Accounts only)
        "payments": [
            {
                "id": pm.id,
                "payment_type": pm.payment_type,
                "amount": float(pm.amount or 0),
                "currency": pm.currency,
                "paid_date": pm.paid_date.isoformat() if pm.paid_date else None,
                "due_date": pm.due_date.isoformat() if pm.due_date else None,
                "status": pm.status,
                "reference_number": pm.reference_number,
                "notes": pm.notes,
            }
            for pm in (order.payments or []) if not pm.is_deleted
        ] if is_accounts else [],

        # Documents
        "documents": [
            {
                "id": doc.id,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "file_name": doc.file_name,
                "file_path": doc.file_path,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
            for doc in (order.documents or []) if not doc.is_deleted and (not doc.is_confidential or is_accounts)
        ]
    }
    return res

@OrderRouter.get("")
@OrderRouter.get("/")
async def list_orders(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    urgent_only: Optional[bool] = Query(False),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    query = (
        db.query(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.order_status_rel),
            joinedload(PurchaseOrder.supplier_rel),
            joinedload(PurchaseOrder.store_request),
            joinedload(PurchaseOrder.items),
            joinedload(PurchaseOrder.shipments).joinedload(OrderShipment.container),
            joinedload(PurchaseOrder.shipments).joinedload(OrderShipment.bill_of_lading),
            joinedload(PurchaseOrder.payments),
            joinedload(PurchaseOrder.documents)
        )
        .filter(PurchaseOrder.is_deleted == False)
    )

    query = apply_org_filter(query, PurchaseOrder, org_context)

    # Search
    if search:
        s_term = f"%{search.strip()}%"
        search_clauses = [
            PurchaseOrder.po_number.ilike(s_term),
            PurchaseOrder.company.ilike(s_term),
            PurchaseOrder.goods_description.ilike(s_term),
        ]
        if is_accounts:
            search_clauses.append(PurchaseOrder.po_nce.ilike(s_term))
        query = query.filter(or_(*search_clauses))

    # Status filter
    if status and status != "ALL":
        query = query.filter(
            or_(PurchaseOrder.status == status, PurchaseOrder.status_label == status)
        )

    # Urgent filter
    if urgent_only:
        query = query.filter(PurchaseOrder.urgent_action == True)

    orders = query.order_by(desc(PurchaseOrder.id)).all()
    return [order_to_dict(o, is_accounts) for o in orders]

# ── Document Endpoints (Must be before /{order_id}) ───────────────────────────
@OrderRouter.get("/documents/config")
async def get_document_config(
    current_user: User = Depends(get_current_user)
):
    return {
        "document_types": [
            {"value": "defect_evidence", "label": "Defect Evidence / Photo", "can_upload": True},
            {"value": "defect_resolution", "label": "Resolution Document", "can_upload": True},
            {"value": "credit_note", "label": "Credit Note", "can_upload": True},
            {"value": "inspection_report", "label": "Inspection Report", "can_upload": True},
            {"value": "invoice", "label": "Commercial Invoice", "can_upload": True},
            {"value": "packing_list", "label": "Packing List", "can_upload": True},
            {"value": "bill_of_lading", "label": "Bill of Lading", "can_upload": True},
            {"value": "other", "label": "Other Document", "can_upload": True},
        ]
    }

@OrderRouter.get("/documents")
async def list_documents(
    defect_report_id: Optional[int] = Query(None),
    purchase_order_id: Optional[int] = Query(None),
    request_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    results = []
    if defect_report_id:
        def_q = db.query(DefectReport).filter(DefectReport.id == defect_report_id, DefectReport.is_deleted == False)
        def_q = apply_org_filter(def_q, DefectReport, org_context)
        report = def_q.first()
        if report:
            for img in (report.images or []):
                if not img.is_deleted:
                    results.append({
                        "id": img.id,
                        "original_name": img.caption or (img.file_path.split("/")[-1] if img.file_path else f"evidence_{img.id}.jpg"),
                        "document_type": "defect_evidence",
                        "document_label": img.caption or "Defect Evidence",
                        "file_path": img.file_path,
                        "uploaded_by": "Reporter",
                        "uploaded_at": report.created_at.isoformat() if report.created_at else datetime.utcnow().isoformat(),
                    })
    if purchase_order_id:
        doc_q = db.query(OrderDocument).filter(OrderDocument.po_id == purchase_order_id, OrderDocument.is_deleted == False)
        for doc in doc_q.all():
            results.append({
                "id": doc.id,
                "original_name": doc.title or doc.file_name or f"document_{doc.id}",
                "document_type": doc.doc_type,
                "document_label": doc.doc_type,
                "file_path": doc.file_path,
                "uploaded_by": "System",
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
            })
    if request_id:
        doc_q = db.query(OrderDocument).filter(
            ((OrderDocument.entity_type == "STORE_REQUEST") & (OrderDocument.entity_id == request_id)) |
            (OrderDocument.po_id == request_id),
            OrderDocument.is_deleted == False
        )
        for doc in doc_q.all():
            results.append({
                "id": doc.id,
                "original_name": doc.title or doc.file_name or f"document_{doc.id}",
                "document_type": doc.doc_type,
                "document_label": doc.doc_type,
                "file_path": doc.file_path,
                "uploaded_by": "System",
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
            })
    if not defect_report_id and not purchase_order_id and not request_id:
        doc_q = db.query(OrderDocument).filter(OrderDocument.is_deleted == False).order_by(OrderDocument.created_at.desc()).limit(100)
        for doc in doc_q.all():
            results.append({
                "id": doc.id,
                "original_name": doc.title or doc.file_name or f"document_{doc.id}",
                "document_type": doc.doc_type,
                "document_label": doc.doc_type,
                "file_path": doc.file_path,
                "uploaded_by": "System",
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
            })
    return results

@OrderRouter.post("/documents")
async def upload_general_document(
    file: UploadFile = File(...),
    document_type: str = Form("other"),
    defect_report_id: Optional[int] = Form(None),
    purchase_order_id: Optional[int] = Form(None),
    request_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    file_bytes = await file.read()
    if defect_report_id:
        def_q = db.query(DefectReport).filter(DefectReport.id == defect_report_id, DefectReport.is_deleted == False)
        def_q = apply_org_filter(def_q, DefectReport, org_context)
        report = def_q.first()
        if not report:
            raise HTTPException(status_code=404, detail="Defect report not found")
        key = blob_storage.upload_file(
            file_obj=file_bytes,
            original_filename=file.filename,
            folder=f"defects/{report.defect_number}"
        )
        img = DefectImage(
            defect_id=report.id,
            file_path=key,
            caption=document_type,
            created_by=current_user.id
        )
        db.add(img)
        db.commit()
        db.refresh(img)
        return {"success": True, "id": img.id, "file_path": key}

    if purchase_order_id:
        po_q = db.query(PurchaseOrder).filter(PurchaseOrder.id == purchase_order_id, PurchaseOrder.is_deleted == False)
        po_q = apply_org_filter(po_q, PurchaseOrder, org_context)
        order = po_q.first()
        if not order:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        key = blob_storage.upload_file(
            file_obj=file_bytes,
            original_filename=file.filename,
            folder=f"orders/{order.po_number}"
        )
        doc = OrderDocument(
            entity_type="PO",
            entity_id=order.id,
            po_id=order.id,
            doc_type=document_type.upper(),
            title=file.filename,
            file_name=file.filename,
            file_path=key,
            file_size=len(file_bytes),
            mime_type=file.content_type,
            created_by=current_user.id
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return {"success": True, "id": doc.id, "file_path": key}

    if request_id:
        from Model.containermgmt.Orders.StoreRequest import StoreRequest
        req_q = db.query(StoreRequest).filter(StoreRequest.id == request_id, StoreRequest.is_deleted == False)
        req = req_q.first()
        folder_name = req.request_number if req and req.request_number else f"request_{request_id}"
        key = blob_storage.upload_file(
            file_obj=file_bytes,
            original_filename=file.filename,
            folder=f"requests/{folder_name}"
        )
        doc = OrderDocument(
            entity_type="STORE_REQUEST",
            entity_id=request_id,
            po_id=None,
            doc_type=document_type.upper(),
            title=file.filename,
            file_name=file.filename,
            file_path=key,
            file_size=len(file_bytes),
            mime_type=file.content_type,
            created_by=current_user.id
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return {"success": True, "id": doc.id, "file_path": key}

    # General upload when not linked to a specific entity
    key = blob_storage.upload_file(
        file_obj=file_bytes,
        original_filename=file.filename,
        folder="general"
    )
    doc = OrderDocument(
        entity_type="GENERAL",
        entity_id=None,
        po_id=None,
        doc_type=document_type.upper(),
        title=file.filename,
        file_name=file.filename,
        file_path=key,
        file_size=len(file_bytes),
        mime_type=file.content_type,
        created_by=current_user.id
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"success": True, "id": doc.id, "file_path": key}

@OrderRouter.get("/documents/{document_id}/download")
async def download_order_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = db.query(OrderDocument).filter(OrderDocument.id == document_id, OrderDocument.is_deleted == False).first()
    if doc and doc.file_path:
        body, ctype, fname = blob_storage.get_file(doc.file_path)
        if body:
            return StreamingResponse(body, media_type=ctype, headers={"Content-Disposition": f'attachment; filename="{doc.file_name or fname}"'})
    img = db.query(DefectImage).filter(DefectImage.id == document_id, DefectImage.is_deleted == False).first()
    if img and img.file_path:
        body, ctype, fname = blob_storage.get_file(img.file_path)
        if body:
            return StreamingResponse(body, media_type=ctype, headers={"Content-Disposition": f'attachment; filename="{fname}"'})
    raise HTTPException(status_code=404, detail="Document file not found")

@OrderRouter.delete("/documents/{document_id}")
async def delete_order_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = db.query(OrderDocument).filter(OrderDocument.id == document_id).first()
    if doc:
        doc.is_deleted = True
        if doc.file_path:
            try:
                blob_storage.delete_file(doc.file_path)
            except Exception as del_err:
                logger.warning("Could not delete blob %s: %s", doc.file_path, del_err)
        db.commit()
        return {"success": True}
    img = db.query(DefectImage).filter(DefectImage.id == document_id).first()
    if img:
        img.is_deleted = True
        if img.file_path:
            try:
                blob_storage.delete_file(img.file_path)
            except Exception as del_err:
                logger.warning("Could not delete defect blob %s: %s", img.file_path, del_err)
        db.commit()
        return {"success": True}
    return {"success": True}

@OrderRouter.get("/issues/{issue_id}/pdf")
async def get_issue_pdf_proxy(
    issue_id: int,
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
        .filter(DefectReport.id == issue_id, DefectReport.is_deleted == False)
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

@OrderRouter.put("/issues/{issue_id}")
async def update_issue_proxy(
    issue_id: int,
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
        .filter(DefectReport.id == issue_id, DefectReport.is_deleted == False)
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
    return {"success": True, "id": d.id, "defect_number": d.defect_number, "status": d.status}

@OrderRouter.get("/{order_id}")
async def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    query = (
        db.query(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.order_status_rel),
            joinedload(PurchaseOrder.supplier_rel),
            joinedload(PurchaseOrder.store_request),
            joinedload(PurchaseOrder.items),
            joinedload(PurchaseOrder.shipments).joinedload(OrderShipment.container),
            joinedload(PurchaseOrder.shipments).joinedload(OrderShipment.bill_of_lading),
            joinedload(PurchaseOrder.payments),
            joinedload(PurchaseOrder.documents)
        )
        .filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    )
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    return order_to_dict(order, is_accounts)

@OrderRouter.post("")
@OrderRouter.post("/")
async def create_order(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    po_number = payload.get("po_number", "").strip()
    if not po_number:
        raise HTTPException(status_code=422, detail="PO Number is required")

    existing = db.query(PurchaseOrder).filter(
        PurchaseOrder.po_number.ilike(po_number),
        PurchaseOrder.is_deleted == False
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Order with PO Number '{po_number}' already exists")

    # Match status
    status_val = payload.get("status", "DRAFT")
    status_id = payload.get("status_id")
    status_obj = None
    if status_id:
        status_obj = db.query(OrderStatus).filter(OrderStatus.id == status_id, OrderStatus.is_deleted == False).first()
    if not status_obj and status_val:
        status_obj = db.query(OrderStatus).filter(
            or_(OrderStatus.code == status_val, OrderStatus.name == status_val),
            OrderStatus.is_deleted == False
        ).first()

    status_label = status_obj.name if status_obj else (payload.get("status_label") or status_val)

    # Supplier info
    supplier_id = payload.get("supplier")
    company = payload.get("company", "").strip()
    if supplier_id:
        supp = db.query(Supplier).filter(Supplier.supplier_id == supplier_id).first()
        if supp:
            company = supp.name

    target_org_id = payload.get("org_id") or org_context.selected_org_id or current_user.org_id or 1
    if not org_context.is_root and target_org_id not in org_context.allowed_org_ids:
        target_org_id = current_user.org_id

    # Date parser helper
    def parse_d(val):
        if not val: return None
        try: return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
        except: return None

    new_order = PurchaseOrder(
        po_number=po_number,
        po_nce=payload.get("po_nce", "").strip() or None if is_accounts else None,
        request_id=payload.get("request_id"),
        supplier_id=supplier_id or None,
        company=company or None,
        goods_description=payload.get("goods_description", "").strip() or None,
        material_ids=payload.get("material_ids") or [],
        
        status_id=status_obj.id if status_obj else None,
        status=status_obj.code if status_obj else status_val,
        status_label=status_label,
        
        payment_status=payload.get("payment_status", "NONE"),
        production_status=payload.get("production_status", "NOT_STARTED"),
        shipment_status=payload.get("shipment_status", "NOT_SHIPPED"),
        receipt_status=payload.get("receipt_status", "PENDING"),

        total_amount=payload.get("total_amount") if is_accounts else None,
        advance_amount=payload.get("advance_amount") if is_accounts else None,
        balance_amount=payload.get("balance_amount") if is_accounts else None,
        currency=payload.get("currency", "USD"),

        sheet_type=payload.get("sheet_type", "NOBLE"),
        consignee=payload.get("consignee", "").strip() or None,
        year=payload.get("year") or datetime.utcnow().year,
        urgent_action=bool(payload.get("urgent_action", False)),
        
        order_mail_date=parse_d(payload.get("order_mail_date")),
        quote_sent_date=parse_d(payload.get("quote_sent_date")),
        quote_received_date=parse_d(payload.get("quote_received_date")),
        pi_confirmed_date=parse_d(payload.get("pi_confirmed_date")),
        payment_date=parse_d(payload.get("payment_date")) if is_accounts else None,
        balance_payment_date=parse_d(payload.get("balance_payment_date")) if is_accounts else None,
        eta_date=parse_d(payload.get("eta_date")),
        freight_type=payload.get("freight_type", "Sea Freight"),
        remark=payload.get("remark", "").strip() or None,
        org_id=target_org_id,
        created_by=current_user.id
    )
    db.add(new_order)
    db.flush()

    # Add line items if provided
    for it in payload.get("items", []):
        desc_text = it.get("description", "").strip()
        if not desc_text: continue
        po_it = POItem(
            po_id=new_order.id,
            request_item_id=it.get("request_item_id"),
            product_id=it.get("product_id"),
            item_code=it.get("item_code", "").strip() or None,
            description=desc_text,
            quantity_ordered=float(it.get("quantity_ordered") or 1.0),
            unit=it.get("unit", "PCS"),
            unit_price=float(it.get("unit_price")) if it.get("unit_price") and is_accounts else None,
            total_price=float(it.get("total_price")) if it.get("total_price") and is_accounts else None,
            notes=it.get("notes", "").strip() or None,
            created_by=current_user.id
        )
        db.add(po_it)

    # If linked to a store request, update request status to ORDERED
    if new_order.request_id:
        req_obj = db.query(StoreRequest).filter(StoreRequest.id == new_order.request_id).first()
        if req_obj:
            req_obj.status = "ORDERED"
            req_obj.status_label = "Ordered"

    # Status history log
    hist = OrderStatusHistory(
        entity_type="PO",
        entity_id=new_order.id,
        po_id=new_order.id,
        from_status=None,
        to_status=new_order.status,
        to_status_label=new_order.status_label,
        changed_by=current_user.id,
        notes="PO Created"
    )
    db.add(hist)

    db.commit()
    db.refresh(new_order)
    logger.info("Created PO %s by %s", new_order.po_number, current_user.username)
    return order_to_dict(new_order, is_accounts)

@OrderRouter.put("/{order_id}")
async def update_order(
    order_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    def parse_d(val):
        if not val: return None
        try: return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
        except: return None

    old_status = order.status

    if "po_number" in payload:
        po_num = payload["po_number"].strip()
        if po_num:
            existing = db.query(PurchaseOrder).filter(
                PurchaseOrder.po_number.ilike(po_num),
                PurchaseOrder.id != order_id,
                PurchaseOrder.is_deleted == False
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"Order with PO Number '{po_num}' already exists")
            order.po_number = po_num

    if "po_nce" in payload and is_accounts:
        order.po_nce = payload["po_nce"].strip() or None
    if "supplier" in payload and is_accounts:
        order.supplier_id = payload["supplier"] or None
        if order.supplier_id:
            supp = db.query(Supplier).filter(Supplier.supplier_id == order.supplier_id).first()
            if supp:
                order.company = supp.name
    if "company" in payload and is_accounts and not order.supplier_id:
        order.company = payload["company"].strip() or None
    if "goods_description" in payload:
        order.goods_description = payload["goods_description"].strip() or None

    # Status update
    if "status" in payload or "status_id" in payload:
        s_val = payload.get("status")
        s_id = payload.get("status_id")
        st_obj = None
        if s_id:
            st_obj = db.query(OrderStatus).filter(OrderStatus.id == s_id, OrderStatus.is_deleted == False).first()
        if not st_obj and s_val:
            st_obj = db.query(OrderStatus).filter(
                or_(OrderStatus.code == s_val, OrderStatus.name == s_val),
                OrderStatus.is_deleted == False
            ).first()
        if st_obj:
            order.status_id = st_obj.id
            order.status = st_obj.code
            order.status_label = st_obj.name
        elif s_val:
            order.status = s_val
            order.status_label = payload.get("status_label", s_val)

        # Log transition if changed
        if order.status != old_status:
            hist = OrderStatusHistory(
                entity_type="PO",
                entity_id=order.id,
                po_id=order.id,
                from_status=old_status,
                to_status=order.status,
                to_status_label=order.status_label,
                changed_by=current_user.id,
                notes=payload.get("status_note", "Status updated")
            )
            db.add(hist)

    if is_accounts:
        if "total_amount" in payload: order.total_amount = payload["total_amount"]
        if "advance_amount" in payload: order.advance_amount = payload["advance_amount"]
        if "balance_amount" in payload: order.balance_amount = payload["balance_amount"]
        if "currency" in payload: order.currency = payload["currency"]

    if "payment_status" in payload: order.payment_status = payload["payment_status"]
    if "production_status" in payload: order.production_status = payload["production_status"]
    if "shipment_status" in payload: order.shipment_status = payload["shipment_status"]
    if "receipt_status" in payload: order.receipt_status = payload["receipt_status"]

    if "order_mail_date" in payload: order.order_mail_date = parse_d(payload["order_mail_date"])
    if "quote_sent_date" in payload: order.quote_sent_date = parse_d(payload["quote_sent_date"])
    if "quote_received_date" in payload: order.quote_received_date = parse_d(payload["quote_received_date"])
    if "pi_confirmed_date" in payload: order.pi_confirmed_date = parse_d(payload["pi_confirmed_date"])
    if "payment_date" in payload and is_accounts: order.payment_date = parse_d(payload["payment_date"])
    if "balance_payment_date" in payload and is_accounts: order.balance_payment_date = parse_d(payload["balance_payment_date"])
    if "eta_date" in payload: order.eta_date = parse_d(payload["eta_date"])
    if "freight_type" in payload: order.freight_type = payload["freight_type"]
    if "remark" in payload: order.remark = payload["remark"].strip() or None
    if "urgent_action" in payload: order.urgent_action = bool(payload["urgent_action"])

    order.updated_by = current_user.id
    db.commit()
    db.refresh(order)
    return order_to_dict(order, is_accounts)

# ── Link Shipments (PO ↔ BL / Container) ──────────────────────────────────────
@OrderRouter.post("/{order_id}/shipments")
async def link_shipment(
    order_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    bl_no = payload.get("bill_of_lading_no", "").strip()
    if not bl_no:
        raise HTTPException(status_code=422, detail="Bill of Lading number is required")

    container_id = payload.get("container_id")

    shipment = OrderShipment(
        po_id=order.id,
        bill_of_lading_no=bl_no,
        container_id=container_id,
        shipment_status=payload.get("shipment_status", "IN_TRANSIT"),
        notes=payload.get("notes", "").strip() or None,
        created_by=current_user.id
    )
    db.add(shipment)

    # Update PO shipment status automatically
    order.shipment_status = "SHIPPED"
    shipped_st = db.query(OrderStatus).filter(OrderStatus.code == "SHIPPED").first()
    if shipped_st:
        order.status_id = shipped_st.id
        order.status = "SHIPPED"
        order.status_label = "Shipped"

    db.commit()
    return {"success": True, "message": f"Linked BL {bl_no} to PO {order.po_number}"}

# ── Record Payments ───────────────────────────────────────────────────────────
@OrderRouter.post("/{order_id}/payments")
async def record_payment(
    order_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can record payments.")

    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    amt = float(payload.get("amount") or 0)
    p_type = payload.get("payment_type", "ADVANCE")
    
    paid_d = None
    if payload.get("paid_date"):
        paid_d = datetime.strptime(payload["paid_date"][:10], "%Y-%m-%d").date()

    payment = OrderPayment(
        po_id=order.id,
        payment_type=p_type,
        amount=amt,
        currency=payload.get("currency", order.currency or "USD"),
        paid_date=paid_d,
        status="PAID",
        payment_method=payload.get("payment_method"),
        reference_number=payload.get("reference_number"),
        notes=payload.get("notes"),
        created_by=current_user.id
    )
    db.add(payment)

    # Automatic status update based on payment type
    if p_type in ["ADVANCE", "PROGRESS"]:
        order.payment_status = "PART_PAID"
        part_st = db.query(OrderStatus).filter(OrderStatus.code == "PART_PAID").first()
        if part_st:
            order.status_id = part_st.id
            order.status = "PART_PAID"
            order.status_label = "Part Paid"
    elif p_type in ["BALANCE", "FULL"]:
        order.payment_status = "FULLY_PAID"
        paid_st = db.query(OrderStatus).filter(OrderStatus.code == "PAID").first()
        if paid_st:
            order.status_id = paid_st.id
            order.status = "PAID"
            order.status_label = "Paid"

    db.commit()
    return {"success": True, "message": f"Payment of {amt} recorded for PO {order.po_number}"}

# ── Upload Supporting Documents ───────────────────────────────────────────────
@OrderRouter.post("/{order_id}/documents")
async def upload_order_document(
    order_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form("OTHER"),
    title: Optional[str] = Form(None),
    is_confidential: bool = Form(False),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    file_bytes = await file.read()
    key = blob_storage.upload_file(
        file_bytes=file_bytes,
        file_name=file.filename,
        folder=f"orders/{order.po_number}"
    )

    doc = OrderDocument(
        entity_type="PO",
        entity_id=order.id,
        po_id=order.id,
        doc_type=doc_type,
        title=title or file.filename,
        file_name=file.filename,
        file_path=key,
        file_size=len(file_bytes),
        mime_type=file.content_type,
        is_confidential=is_confidential,
        notes=notes,
        created_by=current_user.id
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"success": True, "document_id": doc.id, "file_path": key}

@OrderRouter.delete("/{order_id}")
async def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    order.is_deleted = True
    order.deleted_at = datetime.utcnow()
    order.deleted_by = current_user.id
    db.commit()
    logger.info("Deleted PO %s by %s", order.po_number, current_user.username)
    return {"success": True, "message": f"Order {order.po_number} deleted successfully"}
