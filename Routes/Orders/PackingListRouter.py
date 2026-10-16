import io
import logging
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import or_, and_, desc

from Model.db import get_db
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.OrderPackingList import OrderPackingList, PackingListItem
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.containermgmt.Orders.OrderShipment import OrderShipment
from Model.containermgmt.Container.ContainerDetails import ContainerDetails
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import has_permission
from Utils.org_filter import OrgContext, apply_org_filter
from Services.document_number_service import next_document_number
from Utils.reportGenerator import generate_packing_list_pdf
from Routes.Orders.PackingQuantityService import (
    draft_held_map, open_items, remaining_for_item, is_packable_item,
)

logger = logging.getLogger("containerMgmt.orders.packing")

PackingListRouter = APIRouter(prefix="/packing-lists", tags=["Packing Lists"])

DRAFT = "DRAFT"
CONFIRMED = "CONFIRMED"


def _covered_orders(pl: OrderPackingList) -> list:
    """The orders a packing list covers, derived from its lines.

    Not stored on the header: removing the last line of an order should drop
    that order from the list's coverage by itself.
    """
    seen = {}
    for line in (pl.items or []):
        if line.is_deleted:
            continue
        if not line.po_id:
            # A typed order number still names an order, it just is not one we
            # hold. Keyed by its text so two lines of the same number group.
            if line.po_number_text and line.po_number_text not in seen:
                seen[line.po_number_text] = {
                    "id": None,
                    "po_number": line.po_number_text,
                    "company": None,
                    "linked": False,
                }
            continue
        if line.po_id in seen:
            continue
        po = line.purchase_order
        seen[line.po_id] = {
            "id": line.po_id,
            "po_number": po.po_number if po else None,
            "company": (po.supplier_name_at_issue or po.company) if po else None,
            "linked": True,
        }
    return list(seen.values())


def format_packing_list(pl: OrderPackingList) -> dict:
    lines = [it for it in (pl.items or []) if not it.is_deleted]
    return {
        "id": pl.id,
        "po_id": pl.po_id,
        "po_number": pl.purchase_order.po_number if pl.purchase_order else None,
        "container_id": pl.container_id,
        "container_no": pl.container.container_no if pl.container else pl.container_no_text,
        "container_is_linked": bool(pl.container_id),
        "purchase_orders": _covered_orders(pl),
        "source": pl.source or "PO",
        "packing_list_number": pl.packing_list_number,
        "supplier_invoice_ref": pl.supplier_invoice_ref,
        "package_count": pl.package_count,
        "total_gross_weight": float(pl.total_gross_weight or 0),
        "total_cbm": float(pl.total_cbm or 0),
        "date_issued": pl.date_issued.isoformat() if pl.date_issued else None,
        "status": pl.status,
        "notes": pl.notes,
        "revisions": pl.revisions or [],
        "revision_count": pl.revision_count or 0,
        "line_count": len(lines),
        "off_po_line_count": len([it for it in lines if not it.po_id]),
        "created_at": pl.created_at.isoformat() if pl.created_at else None,
        "items": [
            {
                "id": it.id,
                "po_id": it.po_id,
                "po_number": (
                    it.purchase_order.po_number if it.purchase_order else it.po_number_text
                ),
                "po_is_linked": bool(it.po_id),
                "po_item_id": it.po_item_id,
                "item_code": it.item_code,
                "description": it.description,
                "quantity_packed": float(it.quantity_packed or 0),
                "unit": it.unit,
                "carton_numbers": it.carton_numbers,
                "notes": it.notes,
            }
            for it in lines
        ]
    }


def _base_query(db: Session, org_context: OrgContext):
    query = (
        db.query(OrderPackingList)
        .outerjoin(PurchaseOrder, OrderPackingList.po_id == PurchaseOrder.id)
        .options(
            joinedload(OrderPackingList.purchase_order),
            joinedload(OrderPackingList.container),
            selectinload(OrderPackingList.items).joinedload(PackingListItem.purchase_order),
        )
        .filter(OrderPackingList.is_deleted == False)
    )
    return apply_org_filter(query, OrderPackingList, org_context)


def _load_container(db: Session, container_id: int, org_context: OrgContext) -> ContainerDetails:
    container = (
        db.query(ContainerDetails)
        .filter(ContainerDetails.Container_ID == container_id,
                ContainerDetails.is_deleted == False)
        .first()
    )
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")
    return container


def _assert_packable(po: PurchaseOrder) -> None:
    """A purchase order under revision is not a thing to pack against.

    Quantities are exactly what a revision changes, so packing one mid-revision
    is the same class of conflict as awarding one, and that is already blocked
    on the bidding desk.
    """
    from Routes.Orders.OrderRouter import assert_no_open_revision
    assert_no_open_revision(po, "packing it")


@PackingListRouter.get("")
@PackingListRouter.get("/")
async def list_packing_lists(
    po_id: Optional[int] = Query(None),
    container_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = _base_query(db, org_context)

    if po_id:
        # Either the legacy header order, or any line that names it: a
        # container-first list has no header order at all.
        query = query.filter(
            or_(
                OrderPackingList.po_id == po_id,
                OrderPackingList.items.any(
                    and_(PackingListItem.po_id == po_id, PackingListItem.is_deleted == False)
                ),
            )
        )
    if container_id:
        query = query.filter(OrderPackingList.container_id == container_id)
    if status and status.upper() != "ALL":
        query = query.filter(OrderPackingList.status == status.upper())

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                OrderPackingList.packing_list_number.ilike(s),
                OrderPackingList.supplier_invoice_ref.ilike(s),
                PurchaseOrder.po_number.ilike(s),
                OrderPackingList.container.has(ContainerDetails.container_no.ilike(s)),
                OrderPackingList.items.any(
                    and_(
                        PackingListItem.is_deleted == False,
                        PackingListItem.purchase_order.has(PurchaseOrder.po_number.ilike(s)),
                    )
                ),
            )
        )

    lists = query.order_by(desc(OrderPackingList.id)).all()
    return [format_packing_list(pl) for pl in lists]


@PackingListRouter.post("/draft-from-container")
async def draft_from_container(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    """Seed a packing list from whatever the container's orders still owe.

    Writes nothing. The caller edits what comes back and posts it, so someone
    who opens the builder and walks away has reserved nothing and left no
    half-made record behind.
    """
    if not has_permission(current_user, "Add_PackingList"):
        raise HTTPException(status_code=403, detail="Access forbidden: 'Add_PackingList' is required.")

    container_id = payload.get("container_id")
    if not container_id:
        raise HTTPException(status_code=422, detail="Container is required")

    container = _load_container(db, int(container_id), org_context)
    exclude_id = payload.get("packing_list_id")

    linked = [po for po in (container.purchase_orders or []) if not po.is_deleted]
    wanted = {int(v) for v in (payload.get("po_ids") or [])}
    if wanted:
        linked = [po for po in linked if po.id in wanted]

    if not linked:
        return {
            "container_id": container.Container_ID,
            "container_no": container.container_no,
            "packing_list_number": _suggest_number(db, container.org_id, container),
            "purchase_orders": [],
            "items": [],
            "warnings": ["No purchase orders are linked to this container yet."],
        }

    held = draft_held_map(
        db,
        po_ids=[po.id for po in linked],
        exclude_packing_list_id=int(exclude_id) if exclude_id else None,
    )

    items, warnings, covered = [], [], []
    for po in linked:
        try:
            _assert_packable(po)
        except HTTPException as exc:
            warnings.append(f"{po.po_number}: {exc.detail}")
            continue

        open_lines = open_items(po, held)
        covered.append({
            "id": po.id,
            "po_number": po.po_number,
            "company": po.supplier_name_at_issue or po.company,
            "open_item_count": len(open_lines),
            "fully_packed": len(open_lines) == 0,
        })
        if not open_lines:
            warnings.append(f"{po.po_number} is fully packed; nothing of it was added.")
            continue

        for item, remaining in open_lines:
            items.append({
                "po_id": po.id,
                "po_number": po.po_number,
                "po_item_id": item.id,
                "item_code": item.item_code,
                "description": item.description,
                "unit": item.unit or "PCS",
                "quantity_ordered": float(item.quantity_ordered or 0),
                "quantity_already_packed": float(item.quantity_packed or 0),
                "draft_held": held.get(item.id, 0.0),
                "remaining": remaining,
                # The remaining, never the ordered quantity: the second
                # container for an order must not start over-packed.
                "quantity_packed": remaining,
                "carton_numbers": "",
                "notes": None,
            })

    return {
        "container_id": container.Container_ID,
        "container_no": container.container_no,
        "bill_of_lading": container.BillOfLanding,
        "packing_list_number": _suggest_number(db, container.org_id, container),
        "purchase_orders": covered,
        "items": items,
        "warnings": warnings,
    }


def _apply_lines(
    db: Session,
    pl: OrderPackingList,
    raw_items: list,
    current_user: User,
    commit_quantities: bool,
) -> None:
    """Replace the list's lines, checking each against what is still owed.

    The ceiling is re-read here rather than trusted from the browser: the
    numbers the builder seeded with may be minutes old, and another container's
    list may have taken the rest in between.
    """
    may_override = has_permission(current_user, "Override_PackingQty")

    po_ids = {int(i["po_id"]) for i in raw_items if i.get("po_id")}
    held = draft_held_map(db, po_ids=po_ids, exclude_packing_list_id=pl.id)

    # Which orders this list may draw from. Enforced whenever the list belongs
    # to a container or an order -- including when the set is empty, which is
    # itself an answer: a container carrying nothing can pack nothing.
    allowed_po_ids = set()
    enforce_allowed = bool(pl.container_id or pl.po_id)
    if pl.container_id:
        container = db.query(ContainerDetails).filter(
            ContainerDetails.Container_ID == pl.container_id
        ).first()
        allowed_po_ids = {po.id for po in (container.purchase_orders or [])} if container else set()
    if pl.po_id:
        allowed_po_ids.add(pl.po_id)

    for line in (pl.items or []):
        line.is_deleted = True

    errors = []
    for raw in raw_items:
        description = (raw.get("description") or "").strip()
        if not description:
            continue

        quantity = float(raw.get("quantity_packed") or 0)
        if quantity <= 0:
            continue

        po_id = raw.get("po_id")
        po_item_id = raw.get("po_item_id")
        po_number_text = (raw.get("po_number_text") or "").strip() or None
        po_item = None

        if po_item_id:
            po_item = db.query(POItem).filter(POItem.id == int(po_item_id)).first()
            if not po_item:
                errors.append(f"{description}: the order line it came from no longer exists.")
                continue
            po_id = po_item.po_id

            # A tampered payload must not be able to pack an order this
            # container never carried.
            if enforce_allowed and po_id not in allowed_po_ids:
                label = po_item.purchase_order.po_number if po_item.purchase_order else po_id
                errors.append(f"{description}: {label} is not linked to this container.")
                continue

            ceiling = remaining_for_item(po_item, held.get(po_item.id, 0.0))
            if quantity > ceiling and not may_override:
                unit = po_item.unit or "PCS"
                errors.append(
                    f"{po_item.item_code or description}: {quantity:g} exceeds the "
                    f"{ceiling:g} {unit} still outstanding."
                )
                continue

        line = PackingListItem(
            packing_list_id=pl.id,
            po_id=int(po_id) if po_id else None,
            po_number_text=None if po_id else po_number_text,
            po_item_id=int(po_item_id) if po_item_id else None,
            item_code=(raw.get("item_code") or "").strip() or None,
            description=description,
            quantity_packed=quantity,
            unit=raw.get("unit") or "PCS",
            carton_numbers=(raw.get("carton_numbers") or "").strip() or None,
            notes=(raw.get("notes") or "").strip() or None,
            created_by=current_user.id,
        )

        if po_item is not None:
            ceiling = remaining_for_item(po_item, held.get(po_item.id, 0.0))
            if quantity > ceiling:
                over = quantity - ceiling
                who = getattr(current_user, "username", None) or current_user.id
                note = f"Over-packed by {over:g} (approved by {who})"
                line.notes = f"{line.notes}. {note}" if line.notes else note

        db.add(line)

        # Only a confirmed list moves the order's packed total. A draft holds
        # softly: draft_held already keeps other lists from planning against
        # the same quantity, and nothing has to be released if it is abandoned.
        if commit_quantities and po_item is not None:
            po_item.quantity_packed = float(po_item.quantity_packed or 0) + quantity

    if errors:
        db.rollback()
        raise HTTPException(status_code=422, detail=" ".join(errors))


def _advance_orders(db: Session, pl: OrderPackingList) -> None:
    """Mark the covered orders packed, and record the shipment leg."""
    for covered in _covered_orders(pl):
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == covered["id"]).first()
        if not po:
            continue

        if po.status in ["ORDERED", "IN_PRODUCTION", "READY"]:
            packed_st = db.query(OrderStatus).filter(OrderStatus.code == "PACKED").first()
            if packed_st:
                po.status_id = packed_st.id
                po.status = "PACKED"
                po.status_label = "Packed"

        if pl.container_id:
            existing = db.query(OrderShipment).filter(
                OrderShipment.po_id == po.id,
                OrderShipment.container_id == pl.container_id,
            ).first()
            if not existing:
                container = db.query(ContainerDetails).filter(
                    ContainerDetails.Container_ID == pl.container_id
                ).first()
                db.add(OrderShipment(
                    org_id=po.org_id,
                    po_id=po.id,
                    container_id=pl.container_id,
                    bill_of_lading_no=(container.BillOfLanding if container else None) or None,
                    shipment_status="IN_TRANSIT",
                ))


def _suggest_number(db: Session, org_id, container, po=None, container_no_text=None) -> str:
    """A packing list number, from the company's series or a readable fallback.

    next_document_number returns None for a company with no series configured
    -- by design, so the caller supplies its own format. packing_list_number is
    NOT NULL, so there has to be one.
    """
    issued = next_document_number(db, org_id, "PL")
    if issued:
        return issued
    if container is not None:
        # Numbered within the container, so a second load reads as a second
        # list rather than a collision.
        seq = (
            db.query(OrderPackingList)
            .filter(
                OrderPackingList.container_id == container.Container_ID,
                OrderPackingList.is_deleted == False,
            )
            .count()
        ) + 1
        return f"PL-{container.container_no}-{seq}"
    if container_no_text:
        seq = (
            db.query(OrderPackingList)
            .filter(
                OrderPackingList.container_no_text == container_no_text,
                OrderPackingList.is_deleted == False,
            )
            .count()
        ) + 1
        return f"PL-{container_no_text}-{seq}"
    if po is not None:
        return f"PL-{po.po_number}"
    return f"PL-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"


def _consignee_name(db: Session, bl) -> Optional[str]:
    """The consignee of a bill of lading is an organisation, by id."""
    if not bl or not getattr(bl, "Consignee", None):
        return None
    from Model.Credentials.Organisation import Organisation
    org = db.query(Organisation).filter(Organisation.id == bl.Consignee).first()
    return getattr(org, "display_name", None) if org else None


@PackingListRouter.get("/{packing_id}/pdf")
async def get_packing_list_pdf(
    packing_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    pl = _base_query(db, org_context).filter(OrderPackingList.id == packing_id).first()
    if not pl:
        raise HTTPException(status_code=404, detail="Packing list not found")

    container = pl.container
    bl = getattr(container, "bill_of_landing", None) if container else None
    lines = [it for it in (pl.items or []) if not it.is_deleted]

    groups = []
    for covered in _covered_orders(pl):
        group_lines = [it for it in lines if it.po_id == covered["id"]]
        if group_lines:
            label = covered["po_number"] or f"Order #{covered['id']}"
            if covered["company"]:
                label = f"{label} — {covered['company']}"
            groups.append({"label": label, "lines": group_lines})

    # Hand-added goods last, and named so nobody reads them as ordered.
    off_po = [it for it in lines if not it.po_id]
    if off_po:
        groups.append({"label": "Not on any purchase order", "lines": off_po})

    supplier = next(
        (c["company"] for c in _covered_orders(pl) if c["company"]), None
    )

    pdf_bytes = generate_packing_list_pdf({
        "packing_list_number": pl.packing_list_number,
        "is_draft": (pl.status or "").upper() == DRAFT,
        "status": pl.status,
        "container_no": container.container_no if container else None,
        "seal_number": getattr(container, "seal_number", None) if container else None,
        "bill_of_lading": getattr(bl, "BillOfLanding", None) if bl else (
            container.BillOfLanding if container else None
        ),
        "consignee": _consignee_name(db, bl),
        "supplier": supplier,
        "date_issued": pl.date_issued.strftime("%d %b %Y") if pl.date_issued else None,
        "supplier_invoice_ref": pl.supplier_invoice_ref,
        "package_count": pl.package_count,
        "total_gross_weight": float(pl.total_gross_weight) if pl.total_gross_weight else None,
        "total_cbm": float(pl.total_cbm) if pl.total_cbm else None,
        "notes": pl.notes,
        "groups": groups,
        "line_count": len(lines),
        "order_count": len(_covered_orders(pl)),
        "total_quantity": sum(float(it.quantity_packed or 0) for it in lines),
        "created_by": getattr(pl.created_by_user, "username", None),
        "generated_at": datetime.now().strftime("%d %b %Y %H:%M"),
    })

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{pl.packing_list_number}.pdf"'}
    )


@PackingListRouter.get("/{packing_id}")
async def get_packing_list(
    packing_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    pl = _base_query(db, org_context).filter(OrderPackingList.id == packing_id).first()
    if not pl:
        raise HTTPException(status_code=404, detail="Packing list not found")
    return format_packing_list(pl)


@PackingListRouter.post("")
@PackingListRouter.post("/")
async def create_packing_list(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    if not has_permission(current_user, "Add_PackingList"):
        raise HTTPException(status_code=403, detail="Access forbidden: 'Add_PackingList' is required.")

    container_id = payload.get("container_id")
    container_no_text = (payload.get("container_no_text") or "").strip() or None
    po_id = payload.get("po_id")
    if not container_id and not po_id and not container_no_text:
        raise HTTPException(
            status_code=422,
            detail="A packing list needs a container or a purchase order to belong to.",
        )

    org_id = None
    container = None
    if container_id:
        container = _load_container(db, int(container_id), org_context)
        org_id = container.org_id

    po = None
    if po_id:
        po_query = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False
        )
        po = apply_org_filter(po_query, PurchaseOrder, org_context).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        _assert_packable(po)
        org_id = org_id or po.org_id

    if org_id is None:
        # A typed container has no organisation of its own, so the list belongs
        # to the one the user is acting in.
        org_id = org_context.org_id

    status = (payload.get("status") or CONFIRMED).upper()
    if status not in (DRAFT, CONFIRMED):
        raise HTTPException(status_code=422, detail="A new packing list is either a draft or confirmed")

    pl_number = (
        (payload.get("packing_list_number") or "").strip()
        or _suggest_number(db, org_id, container, po, container_no_text)
    )

    new_pl = OrderPackingList(
        org_id=org_id,
        po_id=po.id if po else None,
        container_id=container.Container_ID if container else None,
        container_no_text=None if container else container_no_text,
        source="CONTAINER" if (container or container_no_text) else "PO",
        packing_list_number=pl_number,
        supplier_invoice_ref=(payload.get("supplier_invoice_ref") or "").strip() or None,
        package_count=payload.get("package_count"),
        total_gross_weight=payload.get("total_gross_weight"),
        total_cbm=payload.get("total_cbm"),
        date_issued=datetime.strptime(payload["date_issued"][:10], "%Y-%m-%d").date() if payload.get("date_issued") else None,
        status=status,
        notes=(payload.get("notes") or "").strip() or None,
        created_by=current_user.id
    )
    db.add(new_pl)
    db.flush()

    _apply_lines(db, new_pl, payload.get("items", []), current_user,
                 commit_quantities=(status == CONFIRMED))

    if status == CONFIRMED:
        db.flush()
        db.refresh(new_pl)
        _advance_orders(db, new_pl)

    db.commit()
    db.refresh(new_pl)
    return format_packing_list(new_pl)


@PackingListRouter.post("/{packing_id}/revise")
async def revise_packing_list(
    packing_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    """Reopen a confirmed packing list for editing, on the record.

    The same shape as revising a sent RFQ: the reason is asked for first and
    recorded against the document, not collected on save. A confirmed list has
    already moved quantities onto the orders, so reopening hands them back --
    the lines keep their numbers and the draft holds them softly instead, which
    is what lets the ceilings be recomputed honestly while it is being edited.
    """
    if not has_permission(current_user, "Edit_PackingList"):
        raise HTTPException(status_code=403, detail="Access forbidden: 'Edit_PackingList' is required.")

    reason = (payload.get("reason") or "").strip()
    if len(reason) < 5:
        raise HTTPException(
            status_code=422,
            detail="A revision needs a reason: this list has already been counted against the orders.",
        )

    pl = _base_query(db, org_context).filter(OrderPackingList.id == packing_id).first()
    if not pl:
        raise HTTPException(status_code=404, detail="Packing list not found")

    status = (pl.status or "").upper()
    if status == DRAFT:
        raise HTTPException(status_code=409, detail=f"{pl.packing_list_number} is already a draft.")
    if status in ("SHIPPED", "RECEIVED"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{pl.packing_list_number} is {status.lower()}. Goods have moved against it, "
                "so it cannot be reopened here."
            ),
        )

    returned = 0.0
    for line in (pl.items or []):
        if line.is_deleted or not line.po_item_id:
            continue
        item = db.query(POItem).filter(POItem.id == line.po_item_id).first()
        if item:
            before = float(item.quantity_packed or 0)
            item.quantity_packed = max(0.0, before - float(line.quantity_packed or 0))
            returned += before - float(item.quantity_packed)

    entry = {
        "at": datetime.utcnow().isoformat(timespec="seconds"),
        "by": getattr(current_user, "id", None),
        "by_name": getattr(current_user, "username", None),
        "reason": reason,
        "from_status": status,
        "quantity_returned": returned,
    }
    # Reassigned rather than appended: SQLAlchemy does not see a mutation
    # inside a plain JSON column, and the write would be dropped silently.
    pl.revisions = list(pl.revisions or []) + [entry]
    pl.revision_count = (pl.revision_count or 0) + 1
    pl.status = DRAFT
    pl.updated_by = current_user.id

    db.commit()
    db.refresh(pl)
    return {
        "message": (
            f"{pl.packing_list_number} reopened for editing; {returned:g} returned to the orders."
        ),
        **format_packing_list(pl),
    }


@PackingListRouter.delete("/{packing_id}")
async def delete_packing_list(
    packing_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    """Remove a draft, or void a confirmed list.

    A confirmed list has already added its quantities to the orders, so
    deleting the rows alone would leave them looking part-packed with nothing
    to show for it. Voiding gives that quantity back, which is also what makes
    unlinking the order possible again afterwards.
    """
    if not has_permission(current_user, "Delete_PackingList"):
        raise HTTPException(status_code=403, detail="Access forbidden: 'Delete_PackingList' is required.")

    pl = _base_query(db, org_context).filter(OrderPackingList.id == packing_id).first()
    if not pl:
        raise HTTPException(status_code=404, detail="Packing list not found")

    status = (pl.status or "").upper()
    if status in ("SHIPPED", "RECEIVED"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{pl.packing_list_number} is {status.lower()}. Goods have already moved against it, "
                "so it cannot be voided here."
            ),
        )

    returned = 0.0
    for line in (pl.items or []):
        if line.is_deleted:
            continue
        if status == CONFIRMED and line.po_item_id:
            item = db.query(POItem).filter(POItem.id == line.po_item_id).first()
            if item:
                before = float(item.quantity_packed or 0)
                item.quantity_packed = max(0.0, before - float(line.quantity_packed or 0))
                returned += before - float(item.quantity_packed)
        line.is_deleted = True
        line.deleted_by = current_user.id

    pl.is_deleted = True
    pl.deleted_by = current_user.id
    db.commit()

    return {
        "message": (
            f"{pl.packing_list_number} voided; {returned:g} returned to the purchase orders."
            if status == CONFIRMED
            else f"{pl.packing_list_number} deleted."
        ),
        "id": pl.id,
        "quantity_returned": returned,
    }


@PackingListRouter.put("/{packing_id}")
async def update_packing_list(
    packing_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    """Edit a draft, or confirm it.

    Drafts only: once a list is confirmed its quantities are on the orders and
    on other screens, and quietly rewriting it would move numbers nobody asked
    to have moved.
    """
    if not has_permission(current_user, "Edit_PackingList"):
        raise HTTPException(status_code=403, detail="Access forbidden: 'Edit_PackingList' is required.")

    pl = _base_query(db, org_context).filter(OrderPackingList.id == packing_id).first()
    if not pl:
        raise HTTPException(status_code=404, detail="Packing list not found")
    if (pl.status or "").upper() != DRAFT:
        raise HTTPException(
            status_code=409,
            detail=f"{pl.packing_list_number} is {(pl.status or '').lower()} and can no longer be edited.",
        )

    status = (payload.get("status") or DRAFT).upper()
    if status not in (DRAFT, CONFIRMED):
        raise HTTPException(status_code=422, detail="A packing list is either a draft or confirmed")

    for field in ("supplier_invoice_ref", "notes"):
        if field in payload:
            setattr(pl, field, (payload.get(field) or "").strip() or None)
    for field in ("package_count", "total_gross_weight", "total_cbm"):
        if field in payload:
            setattr(pl, field, payload.get(field))
    if payload.get("packing_list_number"):
        pl.packing_list_number = payload["packing_list_number"].strip()
    if payload.get("date_issued"):
        pl.date_issued = datetime.strptime(payload["date_issued"][:10], "%Y-%m-%d").date()

    pl.status = status
    pl.updated_by = current_user.id

    lines = payload.get("items")
    if lines is None:
        # Confirming without re-sending the lines: re-run what is already
        # there, so the same ceilings are checked before anything is committed.
        lines = [
            {
                "po_id": it.po_id, "po_item_id": it.po_item_id,
                "item_code": it.item_code, "description": it.description,
                "quantity_packed": float(it.quantity_packed or 0),
                "unit": it.unit, "carton_numbers": it.carton_numbers, "notes": it.notes,
            }
            for it in (pl.items or []) if not it.is_deleted
        ]

    _apply_lines(db, pl, lines, current_user, commit_quantities=(status == CONFIRMED))

    if status == CONFIRMED:
        db.flush()
        db.refresh(pl)
        _advance_orders(db, pl)

    db.commit()
    db.refresh(pl)
    return format_packing_list(pl)
