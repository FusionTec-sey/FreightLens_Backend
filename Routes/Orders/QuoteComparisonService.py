import logging
from decimal import Decimal
from typing import Dict, Any, List, Optional
from datetime import date, datetime, timedelta
from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, or_

from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.VendorQuote import VendorQuote
from Model.containermgmt.Orders.VendorQuoteItem import VendorQuoteItem
from Model.containermgmt.Cinfo.Supplier import Supplier
from Services.currency_service import CurrencyRateNotFound, sync_order_for_current_stage

logger = logging.getLogger("containerMgmt.quote_comparison")

class QuoteComparisonService:

    @staticmethod
    def get_historical_benchmark(
        product_id: Optional[int],
        item_code: Optional[str],
        supplier_id: Optional[int],
        current_po_id: int,
        db: Session
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves the last purchase price and PO reference for this product and supplier.
        Falls back to last purchase price across any supplier if no vendor-specific record exists.
        """
        if not product_id and not item_code:
            return None

        # Try vendor-specific match first
        query = db.query(POItem).join(PurchaseOrder, POItem.po_id == PurchaseOrder.id).filter(
            PurchaseOrder.id != current_po_id,
            POItem.is_deleted == False,
            POItem.unit_price != None,
            POItem.unit_price > 0,
            PurchaseOrder.lifecycle_stage.in_(["PO_ISSUED", "PROFORMA"]) | PurchaseOrder.status.in_(["ORDERED", "SHIPPED", "ARRIVED", "RECEIVED", "COMPLETED", "PAID"])
        )

        if product_id:
            query = query.filter(POItem.product_id == product_id)
        elif item_code:
            query = query.filter(POItem.item_code == item_code)

        if supplier_id:
            vendor_match = query.filter(PurchaseOrder.supplier_id == supplier_id).order_by(desc(PurchaseOrder.created_at)).first()
            if vendor_match:
                return {
                    "price": float(vendor_match.unit_price),
                    "po_id": vendor_match.po_id,
                    "po_number": vendor_match.purchase_order.po_number if vendor_match.purchase_order else None,
                    "date": vendor_match.purchase_order.order_mail_date.isoformat() if (vendor_match.purchase_order and vendor_match.purchase_order.order_mail_date) else None,
                    "vendor_specific": True
                }

        # Global fallback (any supplier)
        global_match = query.order_by(desc(PurchaseOrder.created_at)).first()
        if global_match:
            return {
                "price": float(global_match.unit_price),
                "po_id": global_match.po_id,
                "po_number": global_match.purchase_order.po_number if global_match.purchase_order else None,
                "date": global_match.purchase_order.order_mail_date.isoformat() if (global_match.purchase_order and global_match.purchase_order.order_mail_date) else None,
                "vendor_specific": False
            }

        return None

    @staticmethod
    def get_comparison_matrix(po_id: int, db: Session) -> Dict[str, Any]:
        """
        Builds a comprehensive side-by-side comparison matrix across all vendor quotes
        for a given purchase order, with historical pricing benchmarks and best-price tags.
        """
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found.")

        quotes = db.query(VendorQuote).filter(
            VendorQuote.po_id == po_id,
            VendorQuote.is_deleted == False
        ).order_by(VendorQuote.total_quoted_amount.asc()).all()

        active_items = [it for it in (po.items or []) if not it.is_deleted and it.item_status != "USER_REMOVED"]

        vendors = []
        for q in quotes:
            vendors.append({
                "quote_id": q.id,
                "supplier_id": q.supplier_id,
                "supplier_name": q.supplier.name if q.supplier else "Vendor",
                "quote_reference": q.quote_reference,
                "quote_date": q.quote_date.isoformat() if q.quote_date else None,
                "valid_until": q.valid_until.isoformat() if q.valid_until else None,
                "total_quoted_amount": float(q.total_quoted_amount or 0),
                "currency": q.currency or "USD",
                "delivery_lead_time_days": q.delivery_lead_time_days,
                "payment_terms": q.payment_terms,
                "shipping_terms": q.shipping_terms,
                "status": q.status,
                "rank": q.rank,
                "score_notes": q.score_notes,
                "is_selected": (po.selected_quote_id == q.id),
                "items_count": len([i for i in (q.items or []) if not i.is_deleted]),
                "documents": [
                    {
                        "id": str(d.id),
                        "file_name": d.file_name,
                        "title": d.title,
                        "file_path": d.file_path,
                        "file_size": d.file_size,
                        "mime_type": d.mime_type,
                        "created_at": d.created_at.isoformat() if d.created_at else None,
                    }
                    for d in (q.documents or []) if not d.is_deleted
                ]
            })

        matrix_rows = []
        for it in active_items:
            hist = QuoteComparisonService.get_historical_benchmark(
                product_id=it.product_id,
                item_code=it.item_code,
                supplier_id=po.supplier_id,
                current_po_id=po.id,
                db=db
            )

            # Collect quotes for this line item
            quote_map = {}
            quoted_prices = []

            for q in quotes:
                # Find matching quote item
                matching_qi = next(
                    (qi for qi in (q.items or []) if (not qi.is_deleted) and (qi.po_item_id == it.id or (it.item_code and qi.item_code == it.item_code))),
                    None
                )

                if matching_qi:
                    u_price = float(matching_qi.unit_price)
                    quoted_prices.append(u_price)

                    # Compute trend vs benchmark
                    price_trend = "SAME"
                    trend_pct = 0.0
                    if hist and hist["price"] > 0:
                        diff = u_price - hist["price"]
                        ratio = diff / hist["price"]
                        trend_pct = round(ratio * 100.0, 2)
                        if trend_pct > 0.5:
                            price_trend = "UP"
                        elif trend_pct < -0.5:
                            price_trend = "DOWN"
                        else:
                            price_trend = "SAME"

                    quote_map[q.id] = {
                        "quote_item_id": matching_qi.id,
                        "unit_price": u_price,
                        "total_price": float(matching_qi.total_price),
                        "quantity_quoted": float(matching_qi.quantity_quoted),
                        "availability": matching_qi.availability or "AVAILABLE",
                        "lead_time_days": matching_qi.lead_time_days or q.delivery_lead_time_days,
                        "is_substitute": bool(matching_qi.is_substitute),
                        "notes": matching_qi.notes,
                        "price_trend": price_trend,
                        "trend_pct": trend_pct,
                    }
                else:
                    quote_map[q.id] = None

            lowest_price = min(quoted_prices) if quoted_prices else None

            # Mark lowest price on items
            for q_id, q_data in quote_map.items():
                if q_data and lowest_price is not None:
                    q_data["is_lowest"] = (q_data["unit_price"] == lowest_price)

            matrix_rows.append({
                "po_item_id": it.id,
                "item_code": it.item_code,
                "description": it.description,
                "quantity_ordered": float(it.quantity_ordered or 1),
                "unit": it.unit or "PCS",
                "approved_unit_price": float(it.approved_unit_price) if it.approved_unit_price else None,
                "awarded_vendor_id": getattr(it, "awarded_vendor_id", None),
                "awarded_quote_id": getattr(it, "awarded_quote_id", None),
                "source_rfq_item_id": getattr(it, "source_rfq_item_id", None),
                "historical_benchmark": hist,
                "lowest_quoted_price": lowest_price,
                "vendor_quotes": quote_map,
            })

        child_pos_serialized = [
            {
                "id": c.id,
                "po_number": c.po_number,
                "supplier_id": c.supplier_id,
                "company": c.company or (c.supplier_rel.name if c.supplier_rel else "Supplier"),
                "total_amount": float(c.total_amount or 0),
                "status": c.status,
                "lifecycle_stage": c.lifecycle_stage,
                "items_count": len([i for i in (c.items or []) if not i.is_deleted])
            }
            for c in (po.child_pos or []) if not c.is_deleted
        ] if hasattr(po, "child_pos") and po.child_pos else []

        return {
            "po": {
                "id": po.id,
                "po_number": po.po_number,
                "consignee": po.consignee,
                "sheet_type": po.sheet_type,
                "doc_type": getattr(po, "doc_type", "PO") or "PO",
                "parent_rfq_id": getattr(po, "parent_rfq_id", None),
                "origin_rfq_number": getattr(po, "origin_rfq_number", None),
                "split_index": getattr(po, "split_index", None),
                "child_pos": child_pos_serialized,
                "lifecycle_stage": po.lifecycle_stage,
                "lifecycle_version": po.lifecycle_version,
                "selected_quote_id": po.selected_quote_id,
                "currency": po.currency or "USD",
                "eta_date": po.eta_date.isoformat() if po.eta_date else None,
            },
            "vendors": vendors,
            "line_items": matrix_rows,
            "total_items": len(active_items),
            "total_quotes": len(quotes),
        }

    @staticmethod
    def award_quote(
        po_id: int,
        quote_id: int,
        line_awards: Optional[List[Dict[str, Any]]],
        user_id: Optional[int],
        db: Session
    ) -> Dict[str, Any]:
        """
        Awards a winning quote (or specific line-items). Copies prices to PO items
        and advances lifecycle stage to QUOTE_APPROVED.
        """
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).with_for_update(of=PurchaseOrder).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found.")

        winning_quote = db.query(VendorQuote).filter(VendorQuote.id == quote_id, VendorQuote.po_id == po_id).first()
        if not winning_quote:
            raise HTTPException(status_code=404, detail="Vendor Quote not found for this PO.")

        active_items = {it.id: it for it in (po.items or []) if not it.is_deleted}

        if line_awards:
            # Split-award: user manually awarded specific line items to specific quotes
            for award in line_awards:
                po_it_id = award.get("po_item_id")
                unit_price = award.get("approved_unit_price")
                if po_it_id in active_items and unit_price is not None:
                    active_items[po_it_id].approved_unit_price = Decimal(str(unit_price))
                    active_items[po_it_id].unit_price = Decimal(str(unit_price))
                    if active_items[po_it_id].quantity_ordered:
                        active_items[po_it_id].total_price = active_items[po_it_id].quantity_ordered * Decimal(str(unit_price))
        else:
            # Award entire quote
            for qi in (winning_quote.items or []):
                if qi.po_item_id and qi.po_item_id in active_items:
                    it = active_items[qi.po_item_id]
                    it.approved_unit_price = qi.unit_price
                    it.unit_price = qi.unit_price
                    if it.quantity_ordered:
                        it.total_price = it.quantity_ordered * qi.unit_price

            # Update PO supplier and company
            po.supplier_id = winning_quote.supplier_id
            if winning_quote.supplier and winning_quote.supplier.name:
                po.company = winning_quote.supplier.name

        po.selected_quote_id = winning_quote.id
        winning_quote.status = "ACCEPTED"

        # Mark other quotes as superseded
        other_quotes = db.query(VendorQuote).filter(
            VendorQuote.po_id == po_id,
            VendorQuote.id != quote_id,
            VendorQuote.is_deleted == False
        ).all()
        for oq in other_quotes:
            oq.status = "SUPERSEDED"

        # Update total amount on PO
        new_total = sum(Decimal(str(it.total_price or 0)) for it in active_items.values())
        if new_total > 0:
            po.total_amount = new_total

        today_date = date.today()
        po.pi_confirmed_date = po.pi_confirmed_date or today_date
        if not po.order_mail_date:
            po.order_mail_date = today_date
        if not po.quote_sent_date:
            po.quote_sent_date = today_date
        if not po.quote_received_date:
            po.quote_received_date = winning_quote.quote_date or today_date
        # Note: eta_date is not auto-updated here; shipping schedule is determined manually or via BL/vessel tracking

        # Auto-advance stage if in QUOTE_RECEIVED
        if po.lifecycle_stage in ["RFQ_SENT", "QUOTE_RECEIVED"]:
            from .LifecycleService import LifecycleService
            try:
                LifecycleService.transition_stage(
                    po_id=po.id,
                    target_stage="QUOTE_APPROVED",
                    expected_version=po.lifecycle_version,
                    user_id=user_id,
                    comment=f"Awarded Quote #{winning_quote.quote_reference or winning_quote.id} from {winning_quote.supplier.name if winning_quote.supplier else 'Vendor'}",
                    db=db
                )
            except Exception as e:
                logger.warning(f"Could not auto-advance to QUOTE_APPROVED: {e}")
                po.lifecycle_stage = "QUOTE_APPROVED"
                po.lifecycle_version += 1
                db.commit()

        db.commit()
        db.refresh(po)
        try:
            from Services.search_service import sync_order_document
            sync_order_document(po)
        except Exception as e:
            logger.warning("Failed to sync order %s to Meilisearch after award: %s", po.id, e)
        return {
            "message": "Quote successfully awarded and approved.",
            "po_id": po.id,
            "selected_quote_id": po.selected_quote_id,
            "lifecycle_stage": po.lifecycle_stage,
            "lifecycle_version": po.lifecycle_version,
            "total_amount": float(po.total_amount) if po.total_amount else None
        }

    @staticmethod
    def split_award_rfq(
        rfq_id: int,
        allocations: List[Dict[str, Any]],
        user_id: Optional[int],
        db: Session
    ) -> Dict[str, Any]:
        """
        Splits and awards line items of an RFQ across one or more vendor quotes.
        Atomically generates dedicated child Purchase Orders for each winning vendor,
        marks the parent RFQ as QUOTE_APPROVED / AWARDED, and captures version snapshots.
        """
        rfq = db.query(PurchaseOrder).filter(PurchaseOrder.id == rfq_id).with_for_update(of=PurchaseOrder).first()
        if not rfq:
            raise HTTPException(status_code=404, detail="RFQ not found.")

        # Prevent duplicate split/award if active child POs already exist
        existing_children = db.query(PurchaseOrder).filter(
            PurchaseOrder.parent_rfq_id == rfq.id,
            PurchaseOrder.is_deleted == False
        ).all()
        if existing_children:
            child_nums = ", ".join(c.po_number for c in existing_children)
            raise HTTPException(
                status_code=400,
                detail=f"This RFQ has already been split and awarded into Purchase Order(s): {child_nums}. Duplicate Purchase Orders cannot be created. To re-award, revoke the existing award first."
            )

        if not allocations:
            raise HTTPException(status_code=400, detail="No line-item allocations provided.")

        active_rfq_items = {it.id: it for it in (rfq.items or []) if not it.is_deleted and it.item_status != "USER_REMOVED"}

        # Group allocations by supplier_id
        supplier_allocations: Dict[int, Dict[str, Any]] = {}

        for alloc in allocations:
            item_id = alloc.get("po_item_id")
            quote_id = alloc.get("quote_id")
            unit_price = alloc.get("unit_price")

            if not item_id or item_id not in active_rfq_items:
                continue

            rfq_item = active_rfq_items[item_id]

            quote = db.query(VendorQuote).filter(VendorQuote.id == quote_id, VendorQuote.po_id == rfq.id).first()
            if not quote:
                raise HTTPException(status_code=400, detail=f"Invalid quote #{quote_id} for RFQ #{rfq.id}.")

            sup_id = quote.supplier_id
            if sup_id not in supplier_allocations:
                supplier_allocations[sup_id] = {
                    "quote": quote,
                    "items": []
                }
            supplier_allocations[sup_id]["items"].append({
                "rfq_item": rfq_item,
                "unit_price": unit_price if unit_price is not None else float(quote.total_quoted_amount)
            })

        if not supplier_allocations:
            raise HTTPException(status_code=400, detail="No valid allocations mapped to active RFQ items.")

        is_multi_vendor = len(supplier_allocations) > 1
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        created_pos = []
        awarded_quote_ids = set()

        for idx, (supp_id, sup_data) in enumerate(supplier_allocations.items()):
            quote = sup_data["quote"]
            awarded_quote_ids.add(quote.id)
            items_data = sup_data["items"]

            suffix = alphabet[idx % len(alphabet)] if is_multi_vendor else "A"
            
            # Form child po_number
            base_num = rfq.po_number
            if base_num.startswith("RFQ-"):
                po_base = base_num.replace("RFQ-", "PO-", 1)
            else:
                po_base = base_num

            if is_multi_vendor:
                candidate_po_num = f"{po_base}-{suffix}"
            else:
                candidate_po_num = po_base if not base_num.startswith("PO-") else f"{po_base}-{suffix}"

            # Ensure uniqueness
            collision_check = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == candidate_po_num).first()
            if collision_check:
                candidate_po_num = f"{po_base}-{suffix}-{datetime.utcnow().strftime('%M%S')}"

            supplier_obj = db.query(Supplier).filter(Supplier.supplier_id == supp_id).first()
            company_name = supplier_obj.name if supplier_obj else rfq.company

            today_date = date.today()
            lead_days = quote.delivery_lead_time_days
            child_eta = rfq.eta_date or ((today_date + timedelta(days=int(lead_days))) if lead_days else None)

            child_po = PurchaseOrder(
                po_number=candidate_po_num,
                doc_type="PO",
                parent_rfq_id=rfq.id,
                origin_rfq_number=rfq.po_number,
                split_index=suffix if is_multi_vendor else None,
                request_id=rfq.request_id,
                supplier_id=supp_id,
                company=company_name,
                goods_description=f"Awarded items from {rfq.po_number}",
                material_ids=rfq.material_ids,
                status="ORDERED",
                status_label="PO Issued",
                lifecycle_stage="PO_ISSUED",
                stage_version=1,
                lifecycle_version=1,
                lifecycle_locked=False,
                selected_quote_id=quote.id,
                payment_status="NONE",
                production_status="NOT_STARTED",
                shipment_status="NOT_SHIPPED",
                receipt_status="PENDING",
                currency=quote.currency or rfq.currency or "USD",
                sheet_type=rfq.sheet_type,
                consignee=rfq.consignee,
                year=rfq.year or datetime.utcnow().year,
                urgent_action=rfq.urgent_action,
                order_mail_date=rfq.order_mail_date or today_date,
                quote_sent_date=rfq.quote_sent_date or today_date,
                quote_received_date=rfq.quote_received_date or quote.quote_date or today_date,
                pi_confirmed_date=today_date,
                eta_date=child_eta,
                freight_type=rfq.freight_type or "Sea Freight",
                remark=f"Generated via split award from {rfq.po_number}",
                org_id=rfq.org_id,
                created_by=user_id or rfq.created_by
            )
            db.add(child_po)
            db.flush()

            child_po_total = Decimal("0.0")
            for idata in items_data:
                orig_it = idata["rfq_item"]
                u_price = Decimal(str(idata["unit_price"]))
                qty = Decimal(str(orig_it.quantity_ordered or 1.0))
                line_total = qty * u_price
                child_po_total += line_total

                # Create child item
                child_it = POItem(
                    org_id=child_po.org_id,
                    po_id=child_po.id,
                    source_rfq_item_id=orig_it.id,
                    awarded_vendor_id=supp_id,
                    awarded_quote_id=quote.id,
                    request_item_id=orig_it.request_item_id,
                    product_id=orig_it.product_id,
                    item_code=orig_it.item_code,
                    description=orig_it.description,
                    quantity_ordered=orig_it.quantity_ordered,
                    unit=orig_it.unit,
                    draft_unit_price=orig_it.draft_unit_price or orig_it.unit_price,
                    approved_unit_price=u_price,
                    unit_price=u_price,
                    po_unit_price=u_price,
                    total_price=line_total,
                    currency=child_po.currency,
                    item_status="ACTIVE",
                    notes=orig_it.notes,
                    created_by=user_id
                )
                db.add(child_it)

                # Update original RFQ item
                orig_it.awarded_vendor_id = supp_id
                orig_it.awarded_quote_id = quote.id
                orig_it.approved_unit_price = u_price
                orig_it.unit_price = u_price
                orig_it.total_price = line_total

                # Mark quote item as awarded
                matching_qi = db.query(VendorQuoteItem).filter(
                    VendorQuoteItem.vendor_quote_id == quote.id,
                    or_(
                        VendorQuoteItem.po_item_id == orig_it.id,
                        VendorQuoteItem.item_code == orig_it.item_code
                    )
                ).first()
                if matching_qi:
                    matching_qi.is_awarded = True

            child_po.total_amount = child_po_total
            db.flush()
            try:
                sync_order_for_current_stage(db, child_po)
            except CurrencyRateNotFound as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            created_pos.append(child_po)

        # Update parent RFQ
        rfq.doc_type = "RFQ"
        rfq.lifecycle_stage = "QUOTE_APPROVED"
        rfq.status = "SOURCING"
        rfq.status_label = "Awarded"
        rfq.lifecycle_locked = True
        rfq.lifecycle_version += 1
        rfq.total_amount = sum(c.total_amount for c in created_pos)
        if not rfq.order_mail_date:
            rfq.order_mail_date = today_date
        if not rfq.quote_sent_date:
            rfq.quote_sent_date = today_date
        if not rfq.quote_received_date:
            rfq.quote_received_date = today_date
        if not rfq.pi_confirmed_date:
            rfq.pi_confirmed_date = today_date

        # Update quotes statuses
        all_rfq_quotes = db.query(VendorQuote).filter(VendorQuote.po_id == rfq.id, VendorQuote.is_deleted == False).all()
        for q in all_rfq_quotes:
            if q.id in awarded_quote_ids:
                q.status = "ACCEPTED"
            else:
                q.status = "SUPERSEDED"

        # Capture snapshots
        from .LifecycleService import LifecycleService
        created_po_nums = [p.po_number for p in created_pos]
        LifecycleService.capture_po_snapshot(
            po=rfq,
            db=db,
            transition_type="STAGE_CHANGE",
            change_summary=f"Split and awarded to {len(created_pos)} Purchase Orders: {', '.join(created_po_nums)}",
            user_id=user_id
        )
        db.flush()

        # Capture initial snapshot for each child PO
        for p in created_pos:
            LifecycleService.capture_po_snapshot(
                po=p,
                db=db,
                transition_type="INITIAL",
                change_summary=f"Created from {rfq.po_number} as official PO issued to {p.company}",
                user_id=user_id
            )

        db.commit()
        for p in created_pos:
            db.refresh(p)
        db.refresh(rfq)
        try:
            from Services.search_service import sync_order_document
            sync_order_document(rfq)
            for p in created_pos:
                sync_order_document(p)
        except Exception as e:
            logger.warning("Failed to sync orders to Meilisearch after split award: %s", e)

        return {
            "success": True,
            "message": f"Successfully split and created {len(created_pos)} Purchase Orders.",
            "rfq_id": rfq.id,
            "rfq_number": rfq.po_number,
            "created_pos": [
                {
                    "id": p.id,
                    "po_number": p.po_number,
                    "supplier_id": p.supplier_id,
                    "company": p.company,
                    "total_amount": float(p.total_amount or 0),
                    "items_count": len(p.items),
                    "currency": p.currency,
                    "lifecycle_stage": p.lifecycle_stage,
                }
                for p in created_pos
            ]
        }

    @staticmethod
    def revoke_rfq_award(
        rfq_id: int,
        user_id: Optional[int],
        db: Session
    ) -> Dict[str, Any]:
        """
        Safely revokes an existing award/split on an RFQ.
        Validates that none of the generated child POs have progressed beyond PO_ISSUED (no payments, shipments, etc.).
        Soft-deletes the child POs and restores the parent RFQ back to QUOTE_RECEIVED stage.
        """
        rfq = db.query(PurchaseOrder).filter(PurchaseOrder.id == rfq_id).with_for_update(of=PurchaseOrder).first()
        if not rfq:
            raise HTTPException(status_code=404, detail="RFQ not found.")

        # Find active child POs
        child_pos = db.query(PurchaseOrder).filter(
            PurchaseOrder.parent_rfq_id == rfq.id,
            PurchaseOrder.is_deleted == False
        ).all()

        if not child_pos and rfq.lifecycle_stage not in ["QUOTE_APPROVED", "PO_ISSUED"]:
            raise HTTPException(status_code=400, detail="This RFQ has not been awarded or has no active child Purchase Orders.")

        # Validate that no child PO has advanced or recorded transactions
        for child in child_pos:
            active_payments = [p for p in (child.payments or []) if not p.is_deleted]
            if active_payments:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot revoke award: Purchase Order '{child.po_number}' already has recorded payments. Settle or cancel payments first."
                )
            active_shipments = [s for s in (child.shipments or []) if not s.is_deleted]
            if active_shipments:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot revoke award: Purchase Order '{child.po_number}' already has recorded shipments."
                )
            if child.lifecycle_stage not in ["PO_ISSUED", "DRAFT", "ORDERED"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot revoke award: Purchase Order '{child.po_number}' has already progressed to stage '{child.lifecycle_stage}'."
                )

        revoked_po_numbers = [c.po_number for c in child_pos]

        # Soft delete child POs and their items
        for child in child_pos:
            child.is_deleted = True
            child.updated_by = user_id
            for it in (child.items or []):
                it.is_deleted = True
                it.updated_by = user_id

        # Reset RFQ items
        for it in (rfq.items or []):
            it.awarded_vendor_id = None
            it.awarded_quote_id = None
            it.approved_unit_price = None

        # Reset quote items is_awarded and quotes status
        all_rfq_quotes = db.query(VendorQuote).filter(
            VendorQuote.po_id == rfq.id,
            VendorQuote.is_deleted == False
        ).all()
        for q in all_rfq_quotes:
            q.status = "SUBMITTED"
            for qi in (q.items or []):
                qi.is_awarded = False

        # Reset parent RFQ lifecycle stage
        rfq.selected_quote_id = None
        rfq.lifecycle_stage = "QUOTE_RECEIVED"
        rfq.status_label = "Quotes Received"
        rfq.lifecycle_locked = False
        rfq.lifecycle_version += 1

        # Capture snapshot
        from .LifecycleService import LifecycleService
        LifecycleService.capture_po_snapshot(
            po=rfq,
            db=db,
            transition_type="STAGE_CHANGE",
            change_summary=f"Revoked award and cancelled child POs: {', '.join(revoked_po_numbers)}",
            user_id=user_id
        )

        db.commit()
        db.refresh(rfq)
        try:
            from Services.search_service import sync_order_document
            sync_order_document(rfq)
            for cpo in child_pos:
                sync_order_document(cpo)
        except Exception as e:
            logger.warning("Failed to sync orders to Meilisearch after revoke award: %s", e)

        return {
            "success": True,
            "message": f"Award successfully revoked. {len(child_pos)} child Purchase Order(s) cancelled.",
            "revoked_pos": revoked_po_numbers,
            "rfq_id": rfq.id,
            "lifecycle_stage": rfq.lifecycle_stage
        }


