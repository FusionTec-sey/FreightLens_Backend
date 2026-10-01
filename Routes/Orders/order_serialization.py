from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder


def order_to_dict(order: PurchaseOrder, is_accounts: bool = True, can_view_supplier: bool = True) -> dict:
    doc_type = (getattr(order, "doc_type", "PO") or "PO").upper()
    is_rfq = (doc_type == "RFQ")

    # Authoritative financial authorization:
    # 1. RFQ documents NEVER expose purchasing prices, line totals, advance/balance, or payment records to ANY role.
    # 2. Purchase Orders (PO) only expose financial figures to authorized accounts/financial users.
    can_view_financials = is_accounts and (not is_rfq)

    is_awarded = (order.lifecycle_stage or "").upper() in ["QUOTE_APPROVED", "PO_ISSUED", "ORDERED", "RECEIVED", "COMPLETED"]

    # STRICT VENDOR SECURITY:
    # 1. Sourcing RFQ documents are material requisitions: NEVER expose vendor names, candidate vendors, or supplier IDs.
    # 2. Purchase Orders (PO) only expose vendor/supplier details to users with verified supplier clearance.
    supplier_name = None
    if not is_rfq and can_view_supplier:
        supplier_name = order.company
        if order.supplier_rel and order.supplier_rel.name:
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

    # Calculate authoritative financial values
    active_payments = [pm for pm in (order.payments or []) if not pm.is_deleted]
    active_payments_sum = sum(float(pm.amount or 0) for pm in active_payments)

    eff_advance = float(order.advance_amount) if order.advance_amount is not None else (active_payments_sum if active_payments else 0.0)
    if active_payments and (eff_advance == 0 or eff_advance is None):
        eff_advance = active_payments_sum

    eff_total = float(order.total_amount) if order.total_amount is not None else None
    eff_balance = float(order.balance_amount) if order.balance_amount is not None else (
        max(0.0, eff_total - eff_advance) if eff_total is not None else None
    )

    # Fulfillment rollup for Sourcing RFQs with child POs
    active_child_pos = [c for c in (getattr(order, "child_pos", None) or []) if not c.is_deleted]
    fulfillment_summary = None
    if is_rfq and is_awarded:
        STAGE_RANKS = {
            "COMPLETED": 100,
            "RECEIVED": 96,
            "ARRIVED": 92,
            "SHIPPED": 85,
            "PACKED": 78,
            "READY": 70,
            "IN_PRODUCTION": 55,
            "ORDERED": 40,
            "PO_ISSUED": 35,
            "SOURCING": 25,
            "SUBMITTED": 15,
            "DRAFT": 5,
        }
        if active_child_pos:
            sorted_by_progress = sorted(active_child_pos, key=lambda c: STAGE_RANKS.get(str(c.status).upper(), 30), reverse=True)
            primary_child = sorted_by_progress[0]
            
            child_etas = [c.eta_date for c in active_child_pos if c.eta_date]
            earliest_child_eta = min(child_etas) if child_etas else None

            child_status_counts = {}
            for c in active_child_pos:
                lbl = c.status_label or (c.order_status_rel.name if c.order_status_rel else c.status)
                child_status_counts[lbl] = child_status_counts.get(lbl, 0) + 1

            summary_parts = [f"{cnt} {st}" if len(active_child_pos) > 1 else st for st, cnt in child_status_counts.items()]
            summary_desc = ", ".join(summary_parts)

            primary_lbl = primary_child.status_label or (primary_child.order_status_rel.name if primary_child.order_status_rel else primary_child.status)
            fulfillment_summary = {
                "total_child_pos": len(active_child_pos),
                "primary_status": primary_child.status,
                "primary_status_label": primary_lbl,
                "primary_status_color": primary_child.order_status_rel.color if primary_child.order_status_rel else "bg-indigo-500",
                "primary_badge_color": primary_child.order_status_rel.badge_color if primary_child.order_status_rel else "bg-indigo-50 text-indigo-800 border-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-800",
                "primary_progress": primary_child.order_status_rel.progress if primary_child.order_status_rel else STAGE_RANKS.get(str(primary_child.status).upper(), 40),
                "summary_desc": summary_desc,
                "eta_date": earliest_child_eta.isoformat() if earliest_child_eta else None,
            }
        else:
            fulfillment_summary = {
                "total_child_pos": 0,
                "primary_status": "AWAITING_PO",
                "primary_status_label": "Awarded / Awaiting PO",
                "primary_status_color": "bg-emerald-500",
                "primary_badge_color": "bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800",
                "primary_progress": 35,
                "summary_desc": "Awarded - PO issuance pending",
                "eta_date": None,
            }

    raw_payment_status = (order.payment_status or "NONE").upper()
    payment_label = "Paid" if raw_payment_status in ["FULLY_PAID", "PAID"] else ("Part Paid" if raw_payment_status in ["PART_PAID", "ADVANCE_PAID"] else "Unpaid")
    payment_badge_color = (
        "bg-emerald-50 text-emerald-800 border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-700"
        if raw_payment_status in ["FULLY_PAID", "PAID"]
        else (
            "bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-700"
            if raw_payment_status in ["PART_PAID", "ADVANCE_PAID"]
            else "bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700"
        )
    )

    effective_eta = order.eta_date.isoformat() if order.eta_date else (
        fulfillment_summary["eta_date"] if (fulfillment_summary and fulfillment_summary.get("eta_date")) else None
    )

    res = {
        "id": order.id,
        "po_number": order.po_number,
        "po_nce": order.po_nce if can_view_financials else None,
        "request_id": order.request_id,
        "request_number": order.store_request.request_number if order.store_request else None,
        "supplier": order.supplier_id if (can_view_supplier and not is_rfq) else None,
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
        
        # Procurement Lifecycle Stage (7-stage pipeline)
        "lifecycle_stage": order.lifecycle_stage or "DRAFT",
        "lifecycle_version": order.lifecycle_version or 1,
        "stage_version": getattr(order, "stage_version", 1) or 1,
        "lifecycle_locked": bool(order.lifecycle_locked),
        "selected_quote_id": order.selected_quote_id if can_view_financials else None,
        
        # Decoupled Operational Dimensions
        "payment_status": raw_payment_status,
        "payment_label": payment_label,
        "payment_badge_color": payment_badge_color,
        "production_status": order.production_status or "NOT_STARTED",
        "shipment_status": order.shipment_status or "NOT_SHIPPED",
        "receipt_status": order.receipt_status or "PENDING",

        # Fulfillment rollup for Sourcing view
        "fulfillment_summary": fulfillment_summary,

        # Financials (Accounts on PO only)
        "total_amount": eff_total if (eff_total is not None and can_view_financials) else None,
        "advance_amount": eff_advance if can_view_financials else None,
        "balance_amount": eff_balance if can_view_financials else None,
        "currency": order.currency or "USD",

        # Document classification & lineage: RFQ vs PO
        "doc_type": doc_type,
        "parent_rfq_id": getattr(order, "parent_rfq_id", None),
        "origin_rfq_number": getattr(order, "origin_rfq_number", None),
        "split_index": getattr(order, "split_index", None),
        "child_pos": [
            {
                "id": c.id,
                "po_number": c.po_number,
                "supplier_id": c.supplier_id if (can_view_supplier and not is_rfq) else None,
                "company": (c.company or (c.supplier_rel.name if c.supplier_rel else None)) if (can_view_supplier and not is_rfq) else None,
                "total_amount": float(c.total_amount or 0) if can_view_financials else None,
                "status": c.status,
                "status_label": c.status_label or (c.order_status_rel.name if c.order_status_rel else c.status),
                "status_color": c.order_status_rel.color if c.order_status_rel else "bg-blue-500",
                "badge_color": c.order_status_rel.badge_color if c.order_status_rel else "bg-blue-50 text-blue-800 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-800",
                "lifecycle_stage": c.lifecycle_stage,
                "payment_status": (c.payment_status or "NONE").upper(),
                "production_status": c.production_status or "NOT_STARTED",
                "shipment_status": c.shipment_status or "NOT_SHIPPED",
                "receipt_status": c.receipt_status or "PENDING",
                "eta_date": c.eta_date.isoformat() if c.eta_date else None,
                "currency": c.currency or "USD",
                "items_count": len([i for i in (c.items or []) if not i.is_deleted])
            }
            for c in active_child_pos
        ],

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
        "payment_date": order.payment_date.isoformat() if order.payment_date and can_view_financials else None,
        "balance_payment_date": order.balance_payment_date.isoformat() if order.balance_payment_date and can_view_financials else None,
        "eta_date": effective_eta,
        "freight_type": order.freight_type or "Sea Freight",
        "remark": order.remark,
        "created_at": order.created_at.isoformat() if order.created_at else None,

        # Line items - prices strictly sanitized for RFQ or non-financial PO
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
                "unit_price": float(it.unit_price) if it.unit_price and can_view_financials else None,
                "total_price": float(it.total_price) if it.total_price and can_view_financials else None,
                "draft_unit_price": float(it.draft_unit_price) if it.draft_unit_price and can_view_financials else None,
                "approved_unit_price": float(it.approved_unit_price) if it.approved_unit_price and can_view_financials else None,
                "po_unit_price": float(it.po_unit_price) if it.po_unit_price and can_view_financials else None,
                "proforma_unit_price": float(it.proforma_unit_price) if it.proforma_unit_price and can_view_financials else None,
                "source_rfq_item_id": getattr(it, "source_rfq_item_id", None),
                "awarded_vendor_id": getattr(it, "awarded_vendor_id", None) if can_view_financials else None,
                "awarded_quote_id": getattr(it, "awarded_quote_id", None) if can_view_financials else None,
                "item_status": it.item_status or "ACTIVE",
                "revision_count": len([h for h in (it.history or []) if not h.is_deleted]),
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

        # Linked payments (Accounts on PO only)
        "payments": [
            {
                "id": pm.id,
                "payment_type": pm.payment_type,
                "amount": float(pm.amount or 0),
                "currency": pm.currency,
                "paid_date": pm.paid_date.isoformat() if pm.paid_date else None,
                "due_date": pm.due_date.isoformat() if pm.due_date else None,
                "status": pm.status,
                "payment_method": pm.payment_method,
                "reference_number": pm.reference_number,
                "notes": pm.notes,
                "created_at": pm.created_at.isoformat() if hasattr(pm, 'created_at') and pm.created_at else None,
            }
            for pm in (order.payments or []) if not pm.is_deleted
        ] if can_view_financials else [],

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
