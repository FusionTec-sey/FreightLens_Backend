import logging
from decimal import Decimal
from typing import Dict, Any, List, Optional
from datetime import date, timedelta
from fastapi import HTTPException
from sqlalchemy.orm import Session

from Model.containermgmt.Orders.POVersionSnapshot import POVersionSnapshot
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.POItemHistory import POItemHistory
from Model.containermgmt.Orders.POStageTransition import POStageTransition
from Model.containermgmt.Orders.VendorQuote import VendorQuote
from Model.containermgmt.Cinfo.Supplier import Supplier

logger = logging.getLogger("containerMgmt.lifecycle")

LIFECYCLE_SEQUENCE = [
    "DRAFT",
    "CONFIRMED",
    "RFQ_SENT",
    "QUOTE_RECEIVED",
    "QUOTE_APPROVED",
    "PO_ISSUED",
    "PROFORMA",
]

WARNING_LEVELS = {
    "DRAFT": "NONE",
    # Confirmed lines are still editable -- nothing has gone to a vendor -- but the
    # change is recorded with a reason all the same: a quantity that moved between
    # confirmation and dispatch is exactly what nobody can account for afterwards.
    # CAUTION, not WARNING: the reason belongs to the document, not to each line.
    "CONFIRMED": "CAUTION",
    "RFQ_SENT": "WARNING",
    "QUOTE_RECEIVED": "WARNING",
    "QUOTE_APPROVED": "CRITICAL",
    "PO_ISSUED": "CRITICAL",
    "PROFORMA": "CRITICAL",
}

STAGE_TITLES = {
    "DRAFT": "Draft PO",
    "CONFIRMED": "Confirmed Draft",
    "RFQ_SENT": "RFQ Sent",
    "QUOTE_RECEIVED": "Quote Received",
    "QUOTE_APPROVED": "Quote Approved",
    "PO_ISSUED": "PO Generated",
    "PROFORMA": "Proforma Invoice",
}

DEFAULT_VARIANCE_THRESHOLD = Decimal("2.0")  # ±2.0% fallback

# What a reopened document shows in the lists while its revision window is open.
# Rolling the stage back to CONFIRMED on its own left the old label in place, so a
# requisition reopened from RFQ_SENT still read "RFQ Sent" everywhere but here.
REVISION_STATUS_LABEL = "Under Revision"

# How long a revision window stays open unattended. The window is meant to be
# spent on the change it was opened for: whoever walks away from it leaves a
# document editable with a reason already given for an edit nobody made. Leaving
# the screen closes it outright; this is the backstop for the tab that was closed,
# the browser that crashed and the session that was never came back to.
REVISION_WINDOW_MINUTES = 60

class LifecycleService:

    @staticmethod
    def get_warning_level(stage: str) -> str:
        return WARNING_LEVELS.get(stage.upper(), "NONE")

    @staticmethod
    def serialize_po_for_snapshot(po: PurchaseOrder) -> Dict[str, Any]:
        """
        Creates an immutable, self-contained JSON snapshot of the Purchase Order and its items.
        """
        active_items = [it for it in (po.items or []) if not it.is_deleted]
        return {
            "id": po.id,
            "po_number": po.po_number,
            "po_nce": po.po_nce,
            "supplier_id": po.supplier_id,
            "company": po.company,
            "goods_description": po.goods_description,
            "sheet_type": po.sheet_type,
            "consignee": po.consignee,
            "currency": po.currency or "USD",
            "total_amount": float(po.total_amount) if po.total_amount is not None else None,
            "advance_amount": float(po.advance_amount) if po.advance_amount is not None else None,
            "balance_amount": float(po.balance_amount) if po.balance_amount is not None else None,
            "lifecycle_stage": po.lifecycle_stage or "DRAFT",
            "lifecycle_version": po.lifecycle_version or 1,
            "stage_version": getattr(po, "stage_version", 1) or 1,
            "lifecycle_locked": bool(po.lifecycle_locked),
            "status": po.status,
            "status_label": po.status_label,
            "freight_type": po.freight_type,
            "remark": po.remark,
            "items": [
                {
                    "id": it.id,
                    "product_id": it.product_id,
                    "item_code": it.item_code,
                    "description": it.description,
                    "quantity_ordered": float(it.quantity_ordered or 0),
                    "unit": it.unit,
                    "unit_price": float(it.unit_price) if it.unit_price is not None else None,
                    "draft_unit_price": float(it.draft_unit_price) if it.draft_unit_price is not None else None,
                    "approved_unit_price": float(it.approved_unit_price) if it.approved_unit_price is not None else None,
                    "po_unit_price": float(it.po_unit_price) if it.po_unit_price is not None else None,
                    "proforma_unit_price": float(it.proforma_unit_price) if it.proforma_unit_price is not None else None,
                    "total_price": float(it.total_price) if it.total_price is not None else None,
                    "item_status": it.item_status or "ACTIVE",
                    "notes": it.notes,
                }
                for it in active_items
            ]
        }

    @staticmethod
    def capture_po_snapshot(
        po: PurchaseOrder,
        db: Session,
        transition_type: str,
        change_summary: str,
        diff_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None
    ) -> POVersionSnapshot:
        """
        Captures an immutable snapshot in containermgmt.po_version_snapshots linked to its parent.
        """
        last_snap = db.query(POVersionSnapshot).filter(
            POVersionSnapshot.po_id == po.id
        ).order_by(POVersionSnapshot.id.desc()).first()

        snapshot_payload = LifecycleService.serialize_po_for_snapshot(po)

        snap = POVersionSnapshot(
            po_id=po.id,
            lifecycle_stage=po.lifecycle_stage or "DRAFT",
            stage_version=getattr(po, "stage_version", 1) or 1,
            global_version=po.lifecycle_version or 1,
            parent_snapshot_id=last_snap.id if last_snap else None,
            transition_type=transition_type,
            change_summary=change_summary,
            diff_data=diff_data or {},
            snapshot_data=snapshot_payload,
            created_by=user_id
        )
        db.add(snap)
        return snap

    @staticmethod
    def get_gate_checklist(po: PurchaseOrder, db: Session) -> Dict[str, Any]:
        """
        Evaluates readiness criteria for current stage and next stage progression.
        """
        current_stage = po.lifecycle_stage or "DRAFT"
        curr_idx = LIFECYCLE_SEQUENCE.index(current_stage) if current_stage in LIFECYCLE_SEQUENCE else 0
        next_stage = LIFECYCLE_SEQUENCE[curr_idx + 1] if curr_idx + 1 < len(LIFECYCLE_SEQUENCE) else None

        active_items = [it for it in (po.items or []) if not it.is_deleted and it.item_status != "USER_REMOVED"]

        checks = []
        is_ready = True

        if current_stage == "DRAFT":
            has_consignee = bool(po.sheet_type or po.consignee)
            checks.append({
                "key": "has_consignee",
                "label": "Consignee organization selected",
                "passed": has_consignee,
                "required": True
            })
            has_items = len(active_items) > 0
            checks.append({
                "key": "has_items",
                "label": "At least one product line item added",
                "passed": has_items,
                "required": True
            })
            if not has_consignee or not has_items:
                is_ready = False

        elif current_stage == "CONFIRMED":
            valid_items = all(it.description and float(it.quantity_ordered or 0) > 0 for it in active_items) if active_items else False
            checks.append({
                "key": "valid_quantities",
                "label": "All items have valid quantities and descriptions",
                "passed": valid_items,
                "required": True
            })
            is_rfq = (po.doc_type or "").upper() == "RFQ"
            has_supplier = bool(po.supplier_id or po.company) or is_rfq
            checks.append({
                "key": "has_supplier",
                "label": "Primary supplier or vendor assigned" if not is_rfq else "RFQ Sourcing multi-vendor dispatch ready",
                "passed": has_supplier,
                "required": not is_rfq
            })
            if not valid_items or (not has_supplier and not is_rfq):
                is_ready = False

        elif current_stage == "RFQ_SENT":
            quote_count = db.query(VendorQuote).filter(VendorQuote.po_id == po.id, VendorQuote.is_deleted == False).count()
            has_quotes = quote_count > 0 or bool(po.quote_received_date)
            checks.append({
                "key": "quotes_recorded",
                "label": f"Vendor quotes captured (currently {quote_count} quotes on file)",
                "passed": has_quotes,
                "required": True
            })
            if not has_quotes:
                is_ready = False

        elif current_stage == "QUOTE_RECEIVED":
            has_selected = po.selected_quote_id is not None or all(it.approved_unit_price is not None for it in active_items)
            checks.append({
                "key": "quote_awarded",
                "label": "Winning quote awarded or approved unit prices set on all items",
                "passed": has_selected,
                "required": True
            })
            if not has_selected:
                is_ready = False

        elif current_stage == "QUOTE_APPROVED":
            all_approved = all(it.approved_unit_price is not None for it in active_items) if active_items else False
            checks.append({
                "key": "prices_finalized",
                "label": "Approved prices finalized for order generation",
                "passed": all_approved,
                "required": True
            })
            if not all_approved:
                is_ready = False

        elif current_stage == "PO_ISSUED":
            checks.append({
                "key": "po_issued",
                "label": "Official PO issued; ready for Proforma invoice matching",
                "passed": True,
                "required": True
            })

        return {
            "current_stage": current_stage,
            "current_stage_title": STAGE_TITLES.get(current_stage, current_stage),
            "current_step": curr_idx + 1,
            "next_stage": next_stage,
            "next_stage_title": STAGE_TITLES.get(next_stage, next_stage) if next_stage else None,
            "lifecycle_version": po.lifecycle_version or 1,
            "stage_version": getattr(po, "stage_version", 1) or 1,
            "lifecycle_locked": bool(po.lifecycle_locked),
            "warning_level": LifecycleService.get_warning_level(current_stage),
            "is_ready_to_advance": is_ready and not po.lifecycle_locked,
            "checks": checks,
        }

    @staticmethod
    def transition_stage(
        po_id: int,
        target_stage: str,
        expected_version: int,
        user_id: Optional[int],
        comment: Optional[str],
        db: Session
    ) -> PurchaseOrder:
        """
        Executes a stage transition with optimistic locking and gate validation.
        """
        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id,
            PurchaseOrder.is_deleted == False
        ).with_for_update(of=PurchaseOrder).first()

        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found.")

        # Optimistic Lock Check
        if po.lifecycle_version != expected_version:
            raise HTTPException(
                status_code=409,
                detail=f"Conflict: Document was modified by another user (Current version: v{po.lifecycle_version}, expected: v{expected_version}). Please refresh."
            )

        if po.lifecycle_locked:
            raise HTTPException(
                status_code=423,
                detail="Purchase Order is locked due to unresolved price variance. Approval required before advancing."
            )

        target_stage = target_stage.upper()
        if target_stage not in LIFECYCLE_SEQUENCE:
            raise HTTPException(status_code=400, detail=f"Invalid target lifecycle stage: {target_stage}")

        old_stage = po.lifecycle_stage or "DRAFT"
        curr_idx = LIFECYCLE_SEQUENCE.index(old_stage) if old_stage in LIFECYCLE_SEQUENCE else 0
        tgt_idx = LIFECYCLE_SEQUENCE.index(target_stage)

        transition_type = "ADVANCE" if tgt_idx > curr_idx else "ROLLBACK"

        # A rollback while child POs are live would leave two documents claiming
        # the same line: the RFQ reopened for editing, and a purchase order the
        # vendor is already working to. That is corruption, not a revision.
        if transition_type == "ROLLBACK":
            live_children = db.query(PurchaseOrder).filter(
                PurchaseOrder.parent_rfq_id == po.id,
                PurchaseOrder.is_deleted == False,
                PurchaseOrder.status != "CANCELLED",
            ).all()
            if live_children:
                names = ", ".join(c.po_number or f"#{c.id}" for c in live_children)
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"This RFQ has already been awarded to {len(live_children)} purchase "
                        f"order(s): {names}. Change them there, or cancel them before rolling "
                        "the RFQ back."
                    ),
                )

        # Gate check only applies when advancing forward
        if transition_type == "ADVANCE":
            checklist = LifecycleService.get_gate_checklist(po, db)
            failed_required = [c for c in checklist["checks"] if c["required"] and not c["passed"]]
            if failed_required:
                reasons = "; ".join(c["label"] for c in failed_required)
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot advance to {target_stage}. Unmet requirements: {reasons}"
                )

        # Stage entry actions
        active_items = [it for it in (po.items or []) if not it.is_deleted]
        today_date = date.today()

        if target_stage == "CONFIRMED":
            # Freeze draft prices
            for it in active_items:
                if it.draft_unit_price is None and it.unit_price is not None:
                    it.draft_unit_price = it.unit_price
            if not po.order_mail_date:
                po.order_mail_date = today_date

        elif target_stage == "RFQ_SENT":
            if not po.order_mail_date:
                po.order_mail_date = today_date
            if not po.quote_sent_date:
                po.quote_sent_date = today_date

        elif target_stage == "QUOTE_RECEIVED":
            if not po.order_mail_date:
                po.order_mail_date = today_date
            if not po.quote_sent_date:
                po.quote_sent_date = today_date
            if not po.quote_received_date:
                po.quote_received_date = today_date

        elif target_stage == "QUOTE_APPROVED":
            if not po.order_mail_date:
                po.order_mail_date = today_date
            if not po.quote_sent_date:
                po.quote_sent_date = today_date
            if not po.quote_received_date:
                po.quote_received_date = today_date
            if not po.pi_confirmed_date:
                po.pi_confirmed_date = today_date
            # Ensure approved prices are populated
            if po.selected_quote_id:
                quote = db.query(VendorQuote).filter(VendorQuote.id == po.selected_quote_id).first()
                if quote:
                    for q_item in quote.items:
                        if q_item.po_item_id:
                            target_it = next((i for i in active_items if i.id == q_item.po_item_id), None)
                            if target_it:
                                target_it.approved_unit_price = q_item.unit_price
                    # Note: eta_date is not auto-updated here; shipping schedule is determined manually or via BL/vessel tracking

        elif target_stage == "PO_ISSUED":
            if not po.order_mail_date:
                po.order_mail_date = today_date
            if not po.quote_sent_date:
                po.quote_sent_date = today_date
            if not po.quote_received_date:
                po.quote_received_date = today_date
            if not po.pi_confirmed_date:
                po.pi_confirmed_date = today_date
            # Note: eta_date is not auto-updated here; shipping schedule is determined manually or via BL/vessel tracking
            # Copy approved unit price to official po_unit_price
            for it in active_items:
                if it.approved_unit_price is not None:
                    it.po_unit_price = it.approved_unit_price
                    it.unit_price = it.approved_unit_price
                    if it.quantity_ordered:
                        it.total_price = Decimal(str(it.quantity_ordered)) * Decimal(str(it.approved_unit_price))
            # Sync total amount
            subtotal = sum(Decimal(str(it.total_price or 0)) for it in active_items)
            if subtotal > 0:
                po.total_amount = subtotal
            if po.status in ["DRAFT", "SUBMITTED", "SOURCING"]:
                po.status = "ORDERED"
                po.status_label = "Ordered"

        elif target_stage == "PROFORMA":
            if not po.pi_confirmed_date:
                po.pi_confirmed_date = today_date
            # Check price variance on Proforma entry
            variance_result = LifecycleService.check_proforma_variance(po, db)
            if variance_result["has_variance"]:
                po.lifecycle_locked = True
                logger.warning(f"PO #{po.po_number} locked due to proforma variance.")

        elif target_stage == "SHIPPED":
            # Note: eta_date is not auto-updated here; shipping schedule is determined manually or via BL/vessel tracking
            pass

        # Log transition
        new_version = po.lifecycle_version + 1
        old_stage_v = getattr(po, "stage_version", 1) or 1
        transition_record = POStageTransition(
            org_id=po.org_id,
            po_id=po.id,
            from_stage=old_stage,
            to_stage=target_stage,
            from_version=po.lifecycle_version,
            to_version=new_version,
            transition_type=transition_type,
            comment=comment,
            gate_checks_passed=True,
            created_by=user_id
        )
        db.add(transition_record)

        po.lifecycle_stage = target_stage
        po.stage_version = 1
        po.lifecycle_version = new_version

        # Capture stage transition version snapshot with lineage
        change_desc = (
            f"Promoted to {target_stage} v1 from {old_stage} v{old_stage_v}"
            if transition_type == "ADVANCE"
            else f"Rolled back to {target_stage} v1 from {old_stage} v{old_stage_v}"
        )
        # The caller's comment carries the reason a user was made to type -- a
        # revision's "why". Leaving it in diff_data only put it where the version
        # history does not look, so a revision read as an unexplained rollback.
        if comment:
            change_desc = f"{change_desc} — {comment}"
        LifecycleService.capture_po_snapshot(
            po=po,
            db=db,
            transition_type=f"STAGE_{transition_type}",
            change_summary=change_desc,
            diff_data={
                "from_stage": old_stage,
                "to_stage": target_stage,
                "from_stage_version": old_stage_v,
                "to_stage_version": 1,
                "comment": comment
            },
            user_id=user_id
        )

        db.commit()
        db.refresh(po)
        try:
            from Services.search_service import sync_order_document
            sync_order_document(po)
        except Exception as e:
            logger.warning("Failed to sync order %s to Meilisearch after transition: %s", po.id, e)

        logger.info(f"PO #{po.po_number} transitioned {old_stage} -> {target_stage} (v{new_version}) by user {user_id}")
        return po

    @staticmethod
    def check_proforma_variance(po: PurchaseOrder, db: Session) -> Dict[str, Any]:
        """
        Calculates item-by-item variance between PO unit price and Proforma unit price
        against the supplier's configured variance threshold.
        """
        threshold_pct = DEFAULT_VARIANCE_THRESHOLD
        if po.supplier_id:
            supp = db.query(Supplier).filter(Supplier.supplier_id == po.supplier_id).first()
            if supp and supp.variance_threshold_pct is not None:
                threshold_pct = Decimal(str(supp.variance_threshold_pct))

        threshold_ratio = threshold_pct / Decimal("100.0")

        variances = []
        active_items = [it for it in (po.items or []) if not it.is_deleted and it.item_status != "USER_REMOVED"]

        for it in active_items:
            po_p = it.po_unit_price or it.approved_unit_price or it.unit_price
            pf_p = it.proforma_unit_price

            if po_p and pf_p and Decimal(str(po_p)) > 0:
                po_dec = Decimal(str(po_p))
                pf_dec = Decimal(str(pf_p))
                diff = pf_dec - po_dec
                variance_ratio = abs(diff) / po_dec
                var_pct = round(float(variance_ratio * Decimal("100.0")), 2)

                if variance_ratio > threshold_ratio:
                    variances.append({
                        "po_item_id": it.id,
                        "item_code": it.item_code,
                        "description": it.description,
                        "po_price": float(po_dec),
                        "proforma_price": float(pf_dec),
                        "diff": float(diff),
                        "variance_pct": var_pct,
                        "threshold_pct": float(threshold_pct),
                        "status": "EXCEEDED"
                    })

        has_var = len(variances) > 0
        return {
            "has_variance": has_var,
            "locked": has_var,
            "threshold_pct": float(threshold_pct),
            "variances": variances,
            "requires_permission": "Approve_Variance" if has_var else None,
            "message": f"{len(variances)} line item(s) exceed the {threshold_pct}% variance threshold" if has_var else "All prices within tolerance"
        }

    @staticmethod
    def approve_variance(
        po_id: int,
        user_id: Optional[int],
        justification: str,
        db: Session
    ) -> PurchaseOrder:
        """
        Unlocks a PO locked due to proforma price variance.
        """
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).with_for_update(of=PurchaseOrder).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found.")

        if not justification or len(justification.strip()) < 5:
            raise HTTPException(status_code=422, detail="Approval justification of at least 5 characters is mandatory.")

        po.lifecycle_locked = False
        old_v = po.lifecycle_version
        po.lifecycle_version += 1
        po.stage_version = (getattr(po, "stage_version", 1) or 1) + 1

        # Log transition record documenting the variance approval
        transition = POStageTransition(
            org_id=po.org_id,
            po_id=po.id,
            from_stage=po.lifecycle_stage,
            to_stage=po.lifecycle_stage,
            from_version=old_v,
            to_version=po.lifecycle_version,
            transition_type="VARIANCE_APPROVED",
            comment=f"Price variance approved: {justification}",
            gate_checks_passed=True,
            created_by=user_id
        )
        db.add(transition)

        LifecycleService.capture_po_snapshot(
            po=po,
            db=db,
            transition_type="VARIANCE_APPROVED",
            change_summary=f"Price variance approved: {justification}",
            diff_data={"justification": justification},
            user_id=user_id
        )

        db.commit()
        db.refresh(po)
        logger.info(f"Variance approved on PO #{po.po_number} by User {user_id}")
        return po

    @staticmethod
    def revise(
        po_id: int,
        reason: str,
        user_id: Optional[int],
        db: Session,
    ) -> Dict[str, Any]:
        """Reopen a sent document for editing, on the record.

        A revision is the buyer changing the request, so it is deliberately
        heavier than an edit: it needs a reason, it returns the document to the
        stage where lines are editable, and it stands the open quotes down,
        because they answered the previous version. Nothing is deleted -- the
        quotes stay readable, marked superseded, and the rollback snapshot keeps
        the version the vendors were sent.
        """
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise HTTPException(
                status_code=422,
                detail="A revision needs a reason: the vendors have to be told what changed and why.",
            )

        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False
        ).first()
        if not po:
            raise HTTPException(status_code=404, detail="Document not found.")

        stage = (po.lifecycle_stage or "DRAFT").upper()
        if stage == "DRAFT":
            raise HTTPException(
                status_code=400,
                detail=f"{po.po_number or 'This document'} is still a draft; edit it directly.",
            )
        if stage in ("PO_ISSUED", "PROFORMA"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{po.po_number or 'This document'} is an issued purchase order. "
                    "Changing it is a change order, not a revision."
                ),
            )

        # Quotes answer one version of a request. They are stood down here, not
        # deleted: what a vendor offered against v1 is evidence, and the buyer
        # usually wants to see it when deciding v2.
        open_quotes = db.query(VendorQuote).filter(
            VendorQuote.po_id == po.id,
            VendorQuote.is_deleted == False,
            VendorQuote.status == "PENDING",
        ).all()
        for quote in open_quotes:
            quote.status = "SUPERSEDED"

        version_before = po.lifecycle_version

        # A confirmed requisition is already at the stage where lines are editable,
        # so there is nothing to roll back -- but it is still closed to editing until
        # someone says why they are reopening it. That is the whole point: the reason
        # answers "why was this not settled before you confirmed it?". The marker is
        # the snapshot itself; editing stays open until the requisition is sent.
        if stage == "CONFIRMED":
            po.lifecycle_version = (version_before or 1) + 1
            po.status_label = REVISION_STATUS_LABEL
            LifecycleService.capture_po_snapshot(
                po=po,
                db=db,
                transition_type="REVISION_OPENED",
                change_summary=f"Revision: {reason}",
                diff_data={"revision_reason": reason, "opened_at_stage": stage},
                user_id=user_id,
            )
            db.commit()
            db.refresh(po)
            return {
                "message": (
                    f"{po.po_number or 'The document'} is open for editing. "
                    "Make the changes and send it to vendors when ready."
                ),
                "po_id": po.id,
                "lifecycle_stage": po.lifecycle_stage,
                "lifecycle_version": po.lifecycle_version,
                "revised_from_stage": stage,
                "superseded_quotes": len(open_quotes),
                "reason": reason,
            }

        # Through the ordinary machinery, so this revision gets the same
        # snapshot, the same optimistic lock and the same refusal if child
        # purchase orders are already live.
        LifecycleService.transition_stage(
            po_id=po.id,
            target_stage="CONFIRMED",
            expected_version=version_before,
            user_id=user_id,
            comment=f"Revision: {reason}",
            db=db,
        )
        # After the rollback, not before: transition_stage sets its own labels for
        # the stage it lands on, and this has to be what survives.
        po.status_label = REVISION_STATUS_LABEL
        db.commit()
        db.refresh(po)

        return {
            "message": (
                f"{po.po_number or 'The document'} is open for editing again. "
                f"{len(open_quotes)} open quote(s) were superseded; send it again when the "
                "changes are made."
            ),
            "po_id": po.id,
            "lifecycle_stage": po.lifecycle_stage,
            "lifecycle_version": po.lifecycle_version,
            "revised_from_stage": stage,
            "superseded_quotes": len(open_quotes),
            "reason": reason,
        }

    @staticmethod
    def close_revision(
        po_id: int,
        user_id: Optional[int],
        db: Session,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Shut an open revision window without applying changes.

        Reopening is a commitment to make a change and say why. Walking away from
        it is not, so leaving the document locks it again and the next edit asks
        for its own reason -- the alternative is a requisition sitting editable on
        a reason given for an edit that never happened.

        Nothing is rolled back: the stage, the superseded quotes and the reason
        already given all stand, because they are what happened. Only the window
        closes. Idempotent, so the screen can call it on the way out without
        knowing whether a save has already closed it.
        """
        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False
        ).first()
        if not po:
            raise HTTPException(status_code=404, detail="Document not found.")

        # Reading the trail rather than a flag, the same way the window is opened
        # and spent. Imported here: OrderRouter imports this service.
        from .OrderRouter import _revision_is_open

        if not _revision_is_open(po):
            return {
                "message": "No revision was open on this document.",
                "po_id": po.id,
                "closed": False,
                "lifecycle_stage": po.lifecycle_stage,
                "status_label": po.status_label,
            }

        stage = (po.lifecycle_stage or "DRAFT").upper()
        po.lifecycle_version = (po.lifecycle_version or 1) + 1
        po.status_label = STAGE_TITLES.get(stage, po.status_label)

        LifecycleService.capture_po_snapshot(
            po=po,
            db=db,
            transition_type="REVISION_CLOSED",
            change_summary=note or "Revision closed without changes; the document is locked again.",
            diff_data={"closed_without_changes": True, "note": note or None},
            user_id=user_id,
        )
        db.commit()
        db.refresh(po)
        return {
            "message": (
                f"{po.po_number or 'The document'} is locked again. "
                "Revising it needs a new reason."
            ),
            "po_id": po.id,
            "closed": True,
            "lifecycle_stage": po.lifecycle_stage,
            "status_label": po.status_label,
        }

    @staticmethod
    def record_item_history(
        po: PurchaseOrder,
        item: POItem,
        action: str,
        field_name: Optional[str],
        old_value: Optional[str],
        new_value: Optional[str],
        reason: Optional[str],
        user_id: Optional[int],
        db: Session
    ) -> POItemHistory:
        """
        Creates an immutable delta audit record for line-item changes.
        Enforces mandatory reason when PO is at CRITICAL warning level.
        """
        warning_level = LifecycleService.get_warning_level(po.lifecycle_stage)
        # The reason is asked for once, by Revise, before editing is opened at all.
        # A save does not ask again -- the change summary it records is the version
        # history, not a second justification.
        if warning_level == "CRITICAL" and (not reason or len(reason.strip()) < 5):
            raise HTTPException(
                status_code=422,
                detail=f"A mandatory revision reason is required when modifying items in stage {po.lifecycle_stage}."
            )

        history_entry = POItemHistory(
            po_item_id=item.id,
            po_id=po.id,
            lifecycle_stage=po.lifecycle_stage,
            lifecycle_version=po.lifecycle_version,
            action=action,
            field_name=field_name,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            quantity=item.quantity_ordered,
            unit_price=item.unit_price,
            total_price=item.total_price,
            reason=reason,
            created_by=user_id
        )
        db.add(history_entry)
        return history_entry
