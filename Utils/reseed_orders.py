import sys
import os
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

# Ensure python path includes backend root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from Model.db import engine, SessionLocal
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.POStageTransition import POStageTransition
from Model.containermgmt.Orders.POVersionSnapshot import POVersionSnapshot
from Model.containermgmt.Orders.VendorQuote import VendorQuote
from Model.containermgmt.Orders.VendorQuoteItem import VendorQuoteItem
from Model.containermgmt.Orders.OrderPayment import OrderPayment
from Model.containermgmt.Orders.OrderStatusHistory import OrderStatusHistory
from Model.containermgmt.Orders.GoodsReceipt import GoodsReceipt, ReceiptItem
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Cinfo.Consignee import Consignee
from Model.containermgmt.Orders.Product import Product
from Services.search_service import init_orders_index, format_order_doc, get_meili_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reseed_orders")

def clean_and_reseed():
    db = SessionLocal()
    try:
        logger.info("=== STEP 1: PURGING ALL EXISTING ORDER & SOURCING DATA ===")
        with engine.connect() as conn:
            conn.execute(text("""
                TRUNCATE TABLE 
                    containermgmt.defect_images,
                    containermgmt.defect_items,
                    containermgmt.defect_reports,
                    containermgmt.goods_receipt_items,
                    containermgmt.goods_receipts,
                    containermgmt.order_packing_list_items,
                    containermgmt.order_packing_lists,
                    containermgmt.order_shipments,
                    containermgmt.order_payments,
                    containermgmt.order_status_history,
                    containermgmt.order_documents,
                    containermgmt.po_item_history,
                    containermgmt.po_version_snapshots,
                    containermgmt.po_stage_transitions,
                    containermgmt.vendor_quote_items,
                    containermgmt.vendor_quotes,
                    containermgmt.po_items,
                    containermgmt.purchase_orders
                CASCADE;
            """))
            conn.commit()
        logger.info("Existing order tables successfully truncated.")

        # Clear Meilisearch index for purchase_orders
        try:
            client = get_meili_client()
            if client:
                try:
                    client.delete_index("purchase_orders")
                    logger.info("Deleted Meilisearch 'purchase_orders' index.")
                except Exception:
                    pass
                init_orders_index()
                logger.info("Re-initialized fresh Meilisearch 'purchase_orders' index.")
        except Exception as meili_err:
            logger.warning("Could not reset Meilisearch index: %s", meili_err)

        logger.info("=== STEP 2: LOOKING UP REFERENCE DATA ===")
        # Map statuses
        statuses = {s.code: s for s in db.query(OrderStatus).all()}
        
        # Suppliers
        suppliers = {s.name: s for s in db.query(Supplier).filter(Supplier.is_deleted == False).all()}
        sup_doublelin = suppliers.get("DOUBLE LIN VALVES")
        sup_dezhou = suppliers.get("DEZHOU REBELI GLASS BLOCK CO. LTD")
        sup_3h = suppliers.get("3H INC")
        sup_birkin = suppliers.get("BIRKIN INDUSTRY")
        sup_delta = suppliers.get("DELTA IMPORT EXPORT")
        sup_foshan_jun = suppliers.get("FOSHAN JUN ENTERPRISE CO")
        sup_foshan_sannora = suppliers.get("FOSHAN NANHAI SANNORA")
        sup_foshan_toco = suppliers.get("FOSHAN TOCO DECORATIVE MATERIAL CO. LTD")
        sup_gentle = suppliers.get("EMILY - FOSHAN GENTLE")

        first_sup = next(iter(suppliers.values())) if suppliers else None
        def get_sup_id(s_obj):
            return s_obj.supplier_id if s_obj else (first_sup.supplier_id if first_sup else None)
        def get_sup_name(s_obj, fallback="Supplier"):
            return s_obj.name if s_obj else (first_sup.name if first_sup else fallback)

        today = date.today()

        logger.info("=== STEP 3: SEEDING SOURCING RFQS ===")

        # -------------------------------------------------------------
        # RFQ 1: RFQ-2026-0001 (DRAFT)
        # -------------------------------------------------------------
        rfq1 = PurchaseOrder(
            po_number="RFQ-2026-0001",
            doc_type="RFQ",
            org_id=1,
            consignee="SAHAJ CONSTRUCTION",
            goods_description="Bathroom Sanitary Ware & Smart LED Mirrors for Eden Island Villa Renovation",
            lifecycle_stage="DRAFT",
            stage_version=1,
            lifecycle_version=1,
            status="DRAFT",
            status_label="Draft",
            status_id=statuses.get("DRAFT").id if statuses.get("DRAFT") else 1,
            currency="USD",
            order_mail_date=today - timedelta(days=2),
            urgent_action=False,
            remark="Drafting project specifications with lead architect.",
            created_by=1
        )
        db.add(rfq1)
        db.flush()

        it1_1 = POItem(
            po_id=rfq1.id,
            description="LED Smart Touch Bathroom Mirror 90x70cm with Anti-Fog & Demister",
            quantity_ordered=45.0,
            unit="PCS",
            unit_price=85.00,
            draft_unit_price=85.00,
            total_price=3825.00,
            notes="Spec: 5mm copper-free silver mirror, IP44 waterproof",
            created_by=1
        )
        it1_2 = POItem(
            po_id=rfq1.id,
            description="Countertop Ceramic Basin 90cm Oval Matt White",
            quantity_ordered=45.0,
            unit="SET",
            unit_price=120.00,
            draft_unit_price=120.00,
            total_price=5400.00,
            notes="Single tap hole, overflow included",
            created_by=1
        )
        db.add_all([it1_1, it1_2])
        rfq1.total_amount = Decimal("9225.00")

        db.add(POStageTransition(
            po_id=rfq1.id,
            org_id=1,
            from_stage="DRAFT",
            to_stage="DRAFT",
            from_version=1,
            to_version=1,
            transition_type="INITIAL",
            comment="Sourcing RFQ requisition initialized in Draft",
            created_by=1
        ))

        # -------------------------------------------------------------
        # RFQ 2: RFQ-2026-0002 (CONFIRMED)
        # -------------------------------------------------------------
        rfq2 = PurchaseOrder(
            po_number="RFQ-2026-0002",
            doc_type="RFQ",
            org_id=2,
            consignee="NOBLECON ENTERPRISE",
            goods_description="High-Grade Porcelain Glazed Tiles & Stainless Steel Tile Edge Trims",
            lifecycle_stage="CONFIRMED",
            stage_version=1,
            lifecycle_version=2,
            status="CONFIRMED",
            status_label="Confirmed",
            status_id=statuses.get("SUBMITTED").id if statuses.get("SUBMITTED") else 2,
            currency="USD",
            order_mail_date=today - timedelta(days=5),
            urgent_action=False,
            remark="Technical specifications confirmed by project manager. Ready for RFQ broadcast to tile manufacturers.",
            created_by=1
        )
        db.add(rfq2)
        db.flush()

        it2_1 = POItem(
            po_id=rfq2.id,
            description="Porcelain Floor Tile 60x60cm Ivory Glazed Vitrified",
            quantity_ordered=1800.0,
            unit="SQM",
            unit_price=14.50,
            draft_unit_price=14.50,
            total_price=26100.00,
            notes="Grade AAA, Water absorption < 0.5%",
            created_by=1
        )
        it2_2 = POItem(
            po_id=rfq2.id,
            description="Stainless Steel Grade 304 Tile Trim Square Edge 10mm x 2.5m Brushed Rose Gold",
            quantity_ordered=320.0,
            unit="PCS",
            unit_price=12.00,
            draft_unit_price=12.00,
            total_price=3840.00,
            notes="With protective peel-off film",
            created_by=1
        )
        db.add_all([it2_1, it2_2])
        rfq2.total_amount = Decimal("29940.00")

        db.add(POStageTransition(
            po_id=rfq2.id,
            org_id=2,
            from_stage="DRAFT",
            to_stage="CONFIRMED",
            from_version=1,
            to_version=2,
            transition_type="ADVANCE",
            comment="RFQ specifications locked and confirmed for dispatch",
            created_by=1
        ))

        # -------------------------------------------------------------
        # RFQ 3: RFQ-2026-0003 (RFQ_SENT)
        # -------------------------------------------------------------
        rfq3 = PurchaseOrder(
            po_number="RFQ-2026-0003",
            doc_type="RFQ",
            org_id=1,
            consignee="SAHAJ CONSTRUCTION",
            goods_description="Heavy Duty Brass Valves, Ball Valves & Plumbing Fittings",
            lifecycle_stage="RFQ_SENT",
            stage_version=1,
            lifecycle_version=3,
            status="SOURCING",
            status_label="Sourcing",
            status_id=statuses.get("SOURCING").id if statuses.get("SOURCING") else 3,
            currency="USD",
            order_mail_date=today - timedelta(days=8),
            quote_sent_date=today - timedelta(days=6),
            urgent_action=True,
            remark="RFQ dispatched to Double Lin, Foshan Jun, and 3H Inc. Awaiting quotation replies.",
            created_by=1
        )
        db.add(rfq3)
        db.flush()

        it3_1 = POItem(
            po_id=rfq3.id,
            description="Brass Ball Valve 1/2-inch Full Bore PN25 Female Thread",
            quantity_ordered=1200.0,
            unit="PCS",
            unit_price=4.20,
            draft_unit_price=4.20,
            total_price=5040.00,
            created_by=1
        )
        it3_2 = POItem(
            po_id=rfq3.id,
            description="Brass Ball Valve 3/4-inch Full Bore PN25 Female Thread",
            quantity_ordered=800.0,
            unit="PCS",
            unit_price=6.50,
            draft_unit_price=6.50,
            total_price=5200.00,
            created_by=1
        )
        it3_3 = POItem(
            po_id=rfq3.id,
            description="Brass Check Valve 1-inch Spring Type Vertical",
            quantity_ordered=350.0,
            unit="PCS",
            unit_price=9.80,
            draft_unit_price=9.80,
            total_price=3430.00,
            created_by=1
        )
        db.add_all([it3_1, it3_2, it3_3])
        rfq3.total_amount = Decimal("13670.00")

        db.add(POStageTransition(
            po_id=rfq3.id,
            org_id=1,
            from_stage="CONFIRMED",
            to_stage="RFQ_SENT",
            from_version=2,
            to_version=3,
            transition_type="ADVANCE",
            comment="RFQ inquiry dispatched to 3 certified suppliers",
            created_by=1
        ))

        # -------------------------------------------------------------
        # RFQ 4: RFQ-2026-0004 (QUOTE_RECEIVED - Competitive Bidding)
        # -------------------------------------------------------------
        rfq4 = PurchaseOrder(
            po_number="RFQ-2026-0004",
            doc_type="RFQ",
            org_id=3,
            consignee="SAHAJANAND",
            goods_description="Architectural Glass Blocks & Aluminum Extrusion Profiles",
            lifecycle_stage="QUOTE_RECEIVED",
            stage_version=1,
            lifecycle_version=4,
            status="SOURCING",
            status_label="Quotes In",
            status_id=statuses.get("SOURCING").id if statuses.get("SOURCING") else 3,
            currency="USD",
            order_mail_date=today - timedelta(days=12),
            quote_sent_date=today - timedelta(days=10),
            quote_received_date=today - timedelta(days=2),
            urgent_action=False,
            remark="Received 3 vendor quotes with full line item breakdowns. Ready for side-by-side matrix comparison.",
            created_by=1
        )
        db.add(rfq4)
        db.flush()

        it4_1 = POItem(
            po_id=rfq4.id,
            description="Architectural Glass Block 190x190x80mm Clear Wave Pattern",
            quantity_ordered=2500.0,
            unit="PCS",
            unit_price=3.20,
            draft_unit_price=3.20,
            total_price=8000.00,
            created_by=1
        )
        it4_2 = POItem(
            po_id=rfq4.id,
            description="Architectural Aluminum Extrusion Profile 6063-T5 Matt Black Anodized 6.0m",
            quantity_ordered=400.0,
            unit="BAR",
            unit_price=28.00,
            draft_unit_price=28.00,
            total_price=11200.00,
            created_by=1
        )
        db.add_all([it4_1, it4_2])
        rfq4.total_amount = Decimal("19200.00")

        # 3 Vendor Quotes for RFQ 4
        # Quote A (Dezhou Rebeli)
        q4_a = VendorQuote(
            po_id=rfq4.id,
            org_id=3,
            supplier_id=get_sup_id(sup_dezhou),
            quote_reference="QT-DZH-2026-091",
            quote_date=today - timedelta(days=3),
            total_quoted_amount=Decimal("18375.00"),
            currency="USD",
            delivery_lead_time_days=25,
            payment_terms="30% Advance, 70% against BL copy",
            shipping_terms="FOB Qingdao",
            rank=1,
            score_notes="Best unit pricing on glass blocks, fastest delivery schedule (25 days).",
            created_by=1
        )
        db.add(q4_a)
        db.flush()
        db.add_all([
            VendorQuoteItem(vendor_quote_id=q4_a.id, po_item_id=it4_1.id, description=it4_1.description, quantity_quoted=2500, unit_price=2.95, total_price=7375.00, availability="AVAILABLE", lead_time_days=20, created_by=1),
            VendorQuoteItem(vendor_quote_id=q4_a.id, po_item_id=it4_2.id, description=it4_2.description, quantity_quoted=400, unit_price=27.50, total_price=11000.00, availability="AVAILABLE", lead_time_days=25, created_by=1),
        ])

        # Quote B (Foshan Jun Enterprise)
        q4_b = VendorQuote(
            po_id=rfq4.id,
            org_id=3,
            supplier_id=get_sup_id(sup_foshan_jun),
            quote_reference="QT-JUN-2026-884",
            quote_date=today - timedelta(days=2),
            total_quoted_amount=Decimal("19095.00"),
            currency="USD",
            delivery_lead_time_days=30,
            payment_terms="20% Deposit, 80% on dispatch",
            shipping_terms="FOB Foshan",
            rank=2,
            score_notes="Higher unit price on glass blocks, standard lead time.",
            created_by=1
        )
        db.add(q4_b)
        db.flush()
        db.add_all([
            VendorQuoteItem(vendor_quote_id=q4_b.id, po_item_id=it4_1.id, description=it4_1.description, quantity_quoted=2500, unit_price=3.35, total_price=8375.00, availability="AVAILABLE", lead_time_days=28, created_by=1),
            VendorQuoteItem(vendor_quote_id=q4_b.id, po_item_id=it4_2.id, description=it4_2.description, quantity_quoted=400, unit_price=26.80, total_price=10720.00, availability="AVAILABLE", lead_time_days=30, created_by=1),
        ])

        # Quote C (3H Inc)
        q4_c = VendorQuote(
            po_id=rfq4.id,
            org_id=3,
            supplier_id=get_sup_id(sup_3h),
            quote_reference="QT-3H-2026-114",
            quote_date=today - timedelta(days=2),
            total_quoted_amount=Decimal("19100.00"),
            currency="USD",
            delivery_lead_time_days=35,
            payment_terms="30% Advance, 70% before loading",
            shipping_terms="FOB Guangzhou",
            rank=3,
            score_notes="Longer lead time (35 days). Aluminum profile is high quality.",
            created_by=1
        )
        db.add(q4_c)
        db.flush()
        db.add_all([
            VendorQuoteItem(vendor_quote_id=q4_c.id, po_item_id=it4_1.id, description=it4_1.description, quantity_quoted=2500, unit_price=3.40, total_price=8500.00, availability="AVAILABLE", lead_time_days=35, created_by=1),
            VendorQuoteItem(vendor_quote_id=q4_c.id, po_item_id=it4_2.id, description=it4_2.description, quantity_quoted=400, unit_price=26.50, total_price=10600.00, availability="AVAILABLE", lead_time_days=35, created_by=1),
        ])

        db.add(POStageTransition(
            po_id=rfq4.id,
            org_id=3,
            from_stage="RFQ_SENT",
            to_stage="QUOTE_RECEIVED",
            from_version=3,
            to_version=4,
            transition_type="ADVANCE",
            comment="Received 3 competing vendor quotations for evaluation",
            created_by=1
        ))

        # -------------------------------------------------------------
        # RFQ 5: RFQ-2026-0005 (QUOTE_APPROVED / Multi-Vendor Split Award)
        # -------------------------------------------------------------
        rfq5 = PurchaseOrder(
            po_number="RFQ-2026-0005",
            doc_type="RFQ",
            org_id=1,
            consignee="SAHAJ CONSTRUCTION",
            goods_description="Perseverance Luxury Hotel Phase 2 Fitting Fixtures & Hardware",
            lifecycle_stage="QUOTE_APPROVED",
            stage_version=1,
            lifecycle_version=5,
            status="SOURCING",
            status_label="Awarded",
            status_id=statuses.get("SOURCING").id if statuses.get("SOURCING") else 3,
            currency="USD",
            order_mail_date=today - timedelta(days=20),
            quote_sent_date=today - timedelta(days=18),
            quote_received_date=today - timedelta(days=10),
            pi_confirmed_date=today - timedelta(days=5),
            urgent_action=False,
            remark="Evaluated quotes and split award between 3H Inc (Hardware) and Gentle (Sanitary Ware).",
            created_by=1
        )
        db.add(rfq5)
        db.flush()

        it5_1 = POItem(
            po_id=rfq5.id,
            description="Stainless Steel Lever Door Handles Set with Escutcheons Grade 316",
            quantity_ordered=150.0,
            unit="SET",
            unit_price=42.00,
            draft_unit_price=42.00,
            approved_unit_price=39.50,
            total_price=5925.00,
            created_by=1
        )
        it5_2 = POItem(
            po_id=rfq5.id,
            description="Concealed Cistern Dual Flush Wall-Hung Toilet Framework",
            quantity_ordered=80.0,
            unit="SET",
            unit_price=145.00,
            draft_unit_price=145.00,
            approved_unit_price=138.00,
            total_price=11040.00,
            created_by=1
        )
        db.add_all([it5_1, it5_2])
        rfq5.total_amount = Decimal("16965.00")

        # Two quotes for RFQ 5
        q5_1 = VendorQuote(
            po_id=rfq5.id,
            org_id=1,
            supplier_id=get_sup_id(sup_3h),
            quote_reference="QT-3H-2026-077",
            quote_date=today - timedelta(days=12),
            currency="USD",
            total_quoted_amount=Decimal("5925.00"),
            delivery_lead_time_days=20,
            status="ACCEPTED",
            rank=1,
            created_by=1
        )
        q5_2 = VendorQuote(
            po_id=rfq5.id,
            org_id=1,
            supplier_id=get_sup_id(sup_gentle),
            quote_reference="QT-GNT-2026-302",
            quote_date=today - timedelta(days=11),
            currency="USD",
            total_quoted_amount=Decimal("11040.00"),
            delivery_lead_time_days=25,
            status="ACCEPTED",
            rank=1,
            created_by=1
        )
        db.add_all([q5_1, q5_2])
        db.flush()

        qi5_1 = VendorQuoteItem(vendor_quote_id=q5_1.id, po_item_id=it5_1.id, description=it5_1.description, quantity_quoted=150, unit_price=39.50, total_price=5925.00, is_awarded=True, created_by=1)
        qi5_2 = VendorQuoteItem(vendor_quote_id=q5_2.id, po_item_id=it5_2.id, description=it5_2.description, quantity_quoted=80, unit_price=138.00, total_price=11040.00, is_awarded=True, created_by=1)
        db.add_all([qi5_1, qi5_2])
        db.flush()

        it5_1.awarded_quote_id = q5_1.id
        it5_1.awarded_vendor_id = q5_1.supplier_id
        it5_2.awarded_quote_id = q5_2.id
        it5_2.awarded_vendor_id = q5_2.supplier_id

        # Generated Child POs from Split Award
        child_po_a = PurchaseOrder(
            po_number="PO-2026-0005A",
            doc_type="PO",
            parent_rfq_id=rfq5.id,
            origin_rfq_number=rfq5.po_number,
            split_index="A",
            org_id=1,
            supplier_id=q5_1.supplier_id,
            company=get_sup_name(sup_3h, "3H INC"),
            consignee="SAHAJ CONSTRUCTION",
            goods_description="SS316 Lever Door Handles - Sourced via RFQ-2026-0005",
            lifecycle_stage="PO_ISSUED",
            status="IN_PRODUCTION",
            status_label="In Production",
            status_id=statuses.get("IN_PRODUCTION").id if statuses.get("IN_PRODUCTION") else 5,
            payment_status="PART_PAID",
            production_status="IN_PRODUCTION",
            total_amount=Decimal("5925.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=20),
            quote_sent_date=today - timedelta(days=18),
            quote_received_date=today - timedelta(days=10),
            pi_confirmed_date=today - timedelta(days=5),
            eta_date=today + timedelta(days=22),
            remark="Generated from Sourcing RFQ-2026-0005 (Split Award Line 1). In production with 3H Inc.",
            created_by=1
        )
        child_po_b = PurchaseOrder(
            po_number="PO-2026-0005B",
            doc_type="PO",
            parent_rfq_id=rfq5.id,
            origin_rfq_number=rfq5.po_number,
            split_index="B",
            org_id=1,
            supplier_id=q5_2.supplier_id,
            company=get_sup_name(sup_gentle, "EMILY - FOSHAN GENTLE"),
            consignee="SAHAJ CONSTRUCTION",
            goods_description="Concealed Cistern Frameworks - Sourced via RFQ-2026-0005",
            lifecycle_stage="PO_ISSUED",
            status="SHIPPED",
            status_label="Shipped",
            status_id=statuses.get("SHIPPED").id if statuses.get("SHIPPED") else 8,
            payment_status="NONE",
            production_status="READY",
            shipment_status="SHIPPED",
            total_amount=Decimal("11040.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=20),
            quote_sent_date=today - timedelta(days=18),
            quote_received_date=today - timedelta(days=10),
            pi_confirmed_date=today - timedelta(days=5),
            eta_date=today + timedelta(days=14),
            remark="Generated from Sourcing RFQ-2026-0005 (Split Award Line 2). Shipped on vessel.",
            created_by=1
        )
        db.add_all([child_po_a, child_po_b])
        db.flush()

        db.add(POItem(
            po_id=child_po_a.id,
            source_rfq_item_id=it5_1.id,
            description=it5_1.description,
            quantity_ordered=150.0,
            unit="SET",
            unit_price=39.50,
            po_unit_price=39.50,
            total_price=5925.00,
            created_by=1
        ))
        db.add(POItem(
            po_id=child_po_b.id,
            source_rfq_item_id=it5_2.id,
            description=it5_2.description,
            quantity_ordered=80.0,
            unit="SET",
            unit_price=138.00,
            po_unit_price=138.00,
            total_price=11040.00,
            created_by=1
        ))

        db.add(POStageTransition(
            po_id=rfq5.id,
            org_id=1,
            from_stage="QUOTE_RECEIVED",
            to_stage="QUOTE_APPROVED",
            from_version=4,
            to_version=5,
            transition_type="ADVANCE",
            comment="Split award executed across 3H Inc and Foshan Gentle; child POs generated",
            created_by=1
        ))

        logger.info("=== STEP 4: SEEDING OPERATIONAL PURCHASE ORDERS (POs) ===")

        # -------------------------------------------------------------
        # PO 1: PO-2026-0001 (ORDERED / Awaiting Advance)
        # -------------------------------------------------------------
        po1 = PurchaseOrder(
            po_number="PO-2026-0001",
            po_nce="NPO#26-0101",
            doc_type="PO",
            org_id=2,
            supplier_id=get_sup_id(sup_doublelin),
            company=get_sup_name(sup_doublelin, "DOUBLE LIN VALVES"),
            consignee="NOBLECON ENTERPRISE",
            goods_description="Heavy Duty Brass Gate Valves & PPR Pipe Fittings",
            lifecycle_stage="PO_ISSUED",
            status="ORDERED",
            status_label="Ordered",
            status_id=statuses.get("ORDERED").id if statuses.get("ORDERED") else 4,
            payment_status="NONE",
            production_status="NOT_STARTED",
            shipment_status="NOT_SHIPPED",
            receipt_status="PENDING",
            total_amount=Decimal("12450.00"),
            advance_amount=Decimal("0.00"),
            balance_amount=Decimal("12450.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=10),
            quote_sent_date=today - timedelta(days=8),
            quote_received_date=today - timedelta(days=5),
            pi_confirmed_date=today - timedelta(days=2),
            freight_type="Sea Freight",
            remark="Proforma invoice confirmed. Accounts requested for 30% advance telegraphic transfer.",
            created_by=1
        )
        db.add(po1)
        db.flush()
        db.add_all([
            POItem(po_id=po1.id, description="Brass Gate Valve 2-inch PN16 Female Threaded", quantity_ordered=250.0, unit="PCS", unit_price=22.50, po_unit_price=22.50, total_price=5625.00, created_by=1),
            POItem(po_id=po1.id, description="PPR Equal Tee Fitting 32mm PN25 Green", quantity_ordered=1500.0, unit="PCS", unit_price=1.85, po_unit_price=1.85, total_price=2775.00, created_by=1),
            POItem(po_id=po1.id, description="PPR Elbow 90 Degree 32mm PN25 Green", quantity_ordered=2200.0, unit="PCS", unit_price=1.84, po_unit_price=1.84, total_price=4050.00, created_by=1),
        ])
        db.add(OrderStatusHistory(entity_type="PO", entity_id=po1.id, po_id=po1.id, org_id=2, from_status=None, to_status="ORDERED", to_status_label="Ordered", changed_by=1, notes="Official PO issued to Double Lin Valves"))

        # -------------------------------------------------------------
        # PO 2: PO-2026-0002 (PART_PAID / Advance Paid)
        # -------------------------------------------------------------
        po2 = PurchaseOrder(
            po_number="PO-2026-0002",
            po_nce="SPO#26-0204",
            doc_type="PO",
            org_id=1,
            supplier_id=get_sup_id(sup_dezhou),
            company=get_sup_name(sup_dezhou, "DEZHOU REBELI GLASS BLOCK CO. LTD"),
            consignee="SAHAJ CONSTRUCTION",
            goods_description="Architectural Cloud Pattern Glass Blocks & Mortar Spacers",
            lifecycle_stage="PROFORMA",
            status="ORDERED",
            status_label="Ordered",
            status_id=statuses.get("ORDERED").id if statuses.get("ORDERED") else 4,
            payment_status="PART_PAID",
            production_status="NOT_STARTED",
            shipment_status="NOT_SHIPPED",
            receipt_status="PENDING",
            total_amount=Decimal("28500.00"),
            advance_amount=Decimal("8550.00"),
            balance_amount=Decimal("19950.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=15),
            pi_confirmed_date=today - timedelta(days=10),
            payment_date=today - timedelta(days=4),
            freight_type="Sea Freight",
            remark="30% Advance TT cleared. Factory scheduled mold setup.",
            created_by=1
        )
        db.add(po2)
        db.flush()
        db.add_all([
            POItem(po_id=po2.id, description="Glass Block 190x190x80mm Cloudy Diffused Texture", quantity_ordered=6000.0, unit="PCS", unit_price=3.50, po_unit_price=3.50, total_price=21000.00, created_by=1),
            POItem(po_id=po2.id, description="Specialized Plastic Installation Spacers 10mm Cross", quantity_ordered=15000.0, unit="PCS", unit_price=0.50, po_unit_price=0.50, total_price=7500.00, created_by=1),
        ])
        db.add(OrderPayment(
            po_id=po2.id,
            org_id=1,
            payment_type="ADVANCE",
            reference_number="TT-MCB-2026-8819",
            payment_method="Wire Transfer (TT)",
            amount=Decimal("8550.00"),
            currency="USD",
            paid_date=today - timedelta(days=4),
            status="COMPLETED",
            notes="30% advance deposit paid via Mauritius Commercial Bank",
            created_by=1
        ))
        db.add(OrderStatusHistory(entity_type="PO", entity_id=po2.id, po_id=po2.id, org_id=1, from_status="DRAFT", to_status="ORDERED", to_status_label="Ordered", changed_by=1, notes="30% Advance cleared, PO issued"))

        # -------------------------------------------------------------
        # PO 3: PO-2026-0003 (IN_PRODUCTION / Manufacturing)
        # -------------------------------------------------------------
        po3 = PurchaseOrder(
            po_number="PO-2026-0003",
            po_nce="SHJ-PO#26048",
            doc_type="PO",
            org_id=3,
            supplier_id=get_sup_id(sup_foshan_sannora),
            company=get_sup_name(sup_foshan_sannora, "FOSHAN NANHAI SANNORA"),
            consignee="SAHAJANAND",
            goods_description="Custom Vanity Units, Quartz Sinks & Bathroom Mirrors",
            lifecycle_stage="PROFORMA",
            status="IN_PRODUCTION",
            status_label="In Production",
            status_id=statuses.get("IN_PRODUCTION").id if statuses.get("IN_PRODUCTION") else 7,
            payment_status="PART_PAID",
            production_status="IN_PRODUCTION",
            shipment_status="NOT_SHIPPED",
            receipt_status="PENDING",
            total_amount=Decimal("34200.00"),
            advance_amount=Decimal("10260.00"),
            balance_amount=Decimal("23940.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=25),
            pi_confirmed_date=today - timedelta(days=20),
            payment_date=today - timedelta(days=15),
            freight_type="Sea Freight",
            remark="Factory assembly line in progress. Expected completion in 12 days.",
            created_by=1
        )
        db.add(po3)
        db.flush()
        db.add_all([
            POItem(po_id=po3.id, description="Bathroom Vanity Set 90cm Solid Plywood Charcoal Grey", quantity_ordered=60.0, unit="SET", unit_price=350.00, po_unit_price=350.00, total_price=21000.00, created_by=1),
            POItem(po_id=po3.id, description="Engineered Quartz Countertop Basin Slab 90cm Calacatta", quantity_ordered=60.0, unit="PCS", unit_price=220.00, po_unit_price=220.00, total_price=13200.00, created_by=1),
        ])
        db.add(OrderPayment(
            po_id=po3.id,
            org_id=3,
            payment_type="ADVANCE",
            reference_number="TT-BNI-2026-4402",
            payment_method="Wire Transfer (TT)",
            amount=Decimal("10260.00"),
            currency="USD",
            paid_date=today - timedelta(days=15),
            status="COMPLETED",
            notes="30% Advance deposit paid",
            created_by=1
        ))
        db.add(OrderStatusHistory(entity_type="PO", entity_id=po3.id, po_id=po3.id, org_id=3, from_status="PART_PAID", to_status="IN_PRODUCTION", to_status_label="In Production", changed_by=1, notes="Supplier started manufacturing"))

        # -------------------------------------------------------------
        # PO 4: PO-2026-0004 (READY / Cargo Inspected & Ready to Load)
        # -------------------------------------------------------------
        po4 = PurchaseOrder(
            po_number="PO-2026-0004",
            po_nce="NPO#26-0315",
            doc_type="PO",
            org_id=2,
            supplier_id=get_sup_id(sup_3h),
            company=get_sup_name(sup_3h, "3H INC"),
            consignee="NOBLECON ENTERPRISE",
            goods_description="Heavy Friction Hinges, Multipoint Window Locks & Panic Bars",
            lifecycle_stage="PROFORMA",
            status="READY",
            status_label="Ready",
            status_id=statuses.get("READY").id if statuses.get("READY") else 8,
            payment_status="PART_PAID",
            production_status="READY",
            shipment_status="NOT_SHIPPED",
            receipt_status="PENDING",
            total_amount=Decimal("18900.00"),
            advance_amount=Decimal("5670.00"),
            balance_amount=Decimal("13230.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=35),
            payment_date=today - timedelta(days=25),
            freight_type="Sea Freight",
            remark="Quality inspection passed 100%. Palletized and waiting for container booking confirmation.",
            created_by=1
        )
        db.add(po4)
        db.flush()
        db.add_all([
            POItem(po_id=po4.id, description="SS304 Heavy Duty Friction Stays 16-inch Top Hung", quantity_ordered=800.0, unit="PAIR", unit_price=14.50, po_unit_price=14.50, total_price=11600.00, created_by=1),
            POItem(po_id=po4.id, description="Commercial Panic Exit Touch Bar Device 1000mm Fire Rated", quantity_ordered=50.0, unit="PCS", unit_price=146.00, po_unit_price=146.00, total_price=7300.00, created_by=1),
        ])
        db.add(OrderPayment(
            po_id=po4.id,
            org_id=2,
            payment_type="ADVANCE",
            reference_number="TT-NCB-2026-1188",
            payment_method="Wire Transfer (TT)",
            amount=Decimal("5670.00"),
            currency="USD",
            paid_date=today - timedelta(days=25),
            status="COMPLETED",
            notes="30% Advance deposit",
            created_by=1
        ))
        db.add(OrderStatusHistory(entity_type="PO", entity_id=po4.id, po_id=po4.id, org_id=2, from_status="IN_PRODUCTION", to_status="READY", to_status_label="Ready", changed_by=1, notes="Goods finished & inspected"))

        # -------------------------------------------------------------
        # PO 5: PO-2026-0005 (SHIPPED / On Vessel / Sea Way)
        # -------------------------------------------------------------
        po5 = PurchaseOrder(
            po_number="PO-2026-0005",
            po_nce="SPO#26-0422",
            doc_type="PO",
            org_id=1,
            supplier_id=get_sup_id(sup_birkin),
            company=get_sup_name(sup_birkin, "BIRKIN INDUSTRY"),
            consignee="SAHAJ CONSTRUCTION",
            goods_description="Thermo-Mechanically Treated High Strength Rebar Steel T12 & T16",
            lifecycle_stage="PROFORMA",
            status="SHIPPED",
            status_label="Shipped",
            status_id=statuses.get("SHIPPED").id if statuses.get("SHIPPED") else 10,
            payment_status="FULLY_PAID",
            production_status="READY",
            shipment_status="SHIPPED",
            receipt_status="PENDING",
            total_amount=Decimal("46800.00"),
            advance_amount=Decimal("14040.00"),
            balance_amount=Decimal("32760.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=45),
            payment_date=today - timedelta(days=35),
            balance_payment_date=today - timedelta(days=12),
            eta_date=today + timedelta(days=14),
            freight_type="Sea Freight",
            remark="Loaded on CMA CGM MAUPASSANT. Vessel en route to Port Victoria.",
            created_by=1
        )
        db.add(po5)
        db.flush()
        db.add_all([
            POItem(po_id=po5.id, description="High Yield Deformed Rebar Steel Grade 500 T12 x 12m Bundles", quantity_ordered=25.0, unit="TON", unit_price=920.00, po_unit_price=920.00, total_price=23000.00, created_by=1),
            POItem(po_id=po5.id, description="High Yield Deformed Rebar Steel Grade 500 T16 x 12m Bundles", quantity_ordered=25.0, unit="TON", unit_price=952.00, po_unit_price=952.00, total_price=23800.00, created_by=1),
        ])
        db.add_all([
            OrderPayment(po_id=po5.id, org_id=1, payment_type="ADVANCE", reference_number="TT-MCB-2026-6101", payment_method="Wire Transfer (TT)", amount=Decimal("14040.00"), currency="USD", paid_date=today - timedelta(days=35), status="COMPLETED", notes="30% Advance deposit", created_by=1),
            OrderPayment(po_id=po5.id, org_id=1, payment_type="BALANCE", reference_number="TT-MCB-2026-7289", payment_method="Wire Transfer (TT)", amount=Decimal("32760.00"), currency="USD", paid_date=today - timedelta(days=12), status="COMPLETED", notes="70% Final payment against BL copy", created_by=1),
        ])
        db.add(OrderStatusHistory(entity_type="PO", entity_id=po5.id, po_id=po5.id, org_id=1, from_status="READY", to_status="SHIPPED", to_status_label="Shipped", changed_by=1, notes="Vessel departed port of origin"))

        # -------------------------------------------------------------
        # PO 6: PO-2026-0006 (ARRIVED / At Port Victoria)
        # -------------------------------------------------------------
        po6 = PurchaseOrder(
            po_number="PO-2026-0006",
            po_nce="NPO#26-0498",
            doc_type="PO",
            org_id=2,
            supplier_id=get_sup_id(sup_delta),
            company=get_sup_name(sup_delta, "DELTA IMPORT EXPORT"),
            consignee="NOBLECON ENTERPRISE",
            goods_description="Heavy Earthmoving Filter Kits, Hydraulic Cylinders & Hose Assemblies",
            lifecycle_stage="PROFORMA",
            status="ARRIVED",
            status_label="Arrived",
            status_id=statuses.get("ARRIVED").id if statuses.get("ARRIVED") else 11,
            payment_status="FULLY_PAID",
            production_status="READY",
            shipment_status="ARRIVED",
            receipt_status="PENDING",
            total_amount=Decimal("22100.00"),
            advance_amount=Decimal("6630.00"),
            balance_amount=Decimal("15470.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=50),
            payment_date=today - timedelta(days=40),
            balance_payment_date=today - timedelta(days=18),
            eta_date=today - timedelta(days=1),
            freight_type="Sea Freight",
            remark="Container berthed at Quay Port Victoria. Clearing agent processing customs release.",
            created_by=1
        )
        db.add(po6)
        db.flush()
        db.add_all([
            POItem(po_id=po6.id, description="Excavator CAT 320D Complete Hydraulic Cylinder Seal Kits", quantity_ordered=40.0, unit="KIT", unit_price=240.00, po_unit_price=240.00, total_price=9600.00, created_by=1),
            POItem(po_id=po6.id, description="High Pressure 4-Spiral Hydraulic Wire Hose 3/4-inch 100m Roll", quantity_ordered=5.0, unit="ROLL", unit_price=2500.00, po_unit_price=2500.00, total_price=12500.00, created_by=1),
        ])
        db.add_all([
            OrderPayment(po_id=po6.id, org_id=2, payment_type="ADVANCE", reference_number="TT-NCB-2026-3091", payment_method="Wire Transfer (TT)", amount=Decimal("6630.00"), currency="USD", paid_date=today - timedelta(days=40), status="COMPLETED", created_by=1),
            OrderPayment(po_id=po6.id, org_id=2, payment_type="BALANCE", reference_number="TT-NCB-2026-4190", payment_method="Wire Transfer (TT)", amount=Decimal("15470.00"), currency="USD", paid_date=today - timedelta(days=18), status="COMPLETED", created_by=1),
        ])
        db.add(OrderStatusHistory(entity_type="PO", entity_id=po6.id, po_id=po6.id, org_id=2, from_status="SHIPPED", to_status="ARRIVED", to_status_label="Arrived", changed_by=1, notes="Vessel discharged container at Port Victoria"))

        # -------------------------------------------------------------
        # PO 7: PO-2026-0007 (RECEIVED / Goods Received at Warehouse)
        # -------------------------------------------------------------
        po7 = PurchaseOrder(
            po_number="PO-2026-0007",
            po_nce="SPO#26-0511",
            doc_type="PO",
            org_id=1,
            supplier_id=get_sup_id(sup_foshan_jun),
            company=get_sup_name(sup_foshan_jun, "FOSHAN JUN ENTERPRISE CO"),
            consignee="SAHAJ CONSTRUCTION",
            goods_description="Polished Porcelain Floor Tiles & Polyurethane Sealants",
            lifecycle_stage="PROFORMA",
            status="RECEIVED",
            status_label="Received",
            status_id=statuses.get("RECEIVED").id if statuses.get("RECEIVED") else 12,
            payment_status="FULLY_PAID",
            production_status="READY",
            shipment_status="ARRIVED",
            receipt_status="RECEIVED",
            total_amount=Decimal("15600.00"),
            advance_amount=Decimal("15600.00"),
            balance_amount=Decimal("0.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=60),
            payment_date=today - timedelta(days=45),
            freight_type="Sea Freight",
            remark="Goods receipt note verified by Providence warehouse team. 100% quantity reconciled.",
            created_by=1
        )
        db.add(po7)
        db.flush()
        it7_1 = POItem(po_id=po7.id, description="Polished Porcelain Tile 80x80cm Super White Nano Glaze", quantity_ordered=600.0, quantity_received=600.0, unit="SQM", unit_price=22.00, po_unit_price=22.00, total_price=13200.00, created_by=1)
        it7_2 = POItem(po_id=po7.id, description="Polyurethane Construction Joint Sealant 600ml Sausage Grey", quantity_ordered=300.0, quantity_received=300.0, unit="PCS", unit_price=8.00, po_unit_price=8.00, total_price=2400.00, created_by=1)
        db.add_all([it7_1, it7_2])
        db.flush()

        gr = GoodsReceipt(
            receipt_number="GRN-20260920-007",
            po_id=po7.id,
            org_id=1,
            warehouse_location="Providence Industrial Warehouse Bay B2",
            received_date=today - timedelta(days=3),
            received_by=1,
            status="SUBMITTED",
            submitted_at=datetime.utcnow() - timedelta(days=3),
            has_discrepancies=False,
            notes="Consignment received in excellent wooden crates. Zero breakage found.",
            created_by=1
        )
        db.add(gr)
        db.flush()
        db.add_all([
            ReceiptItem(receipt_id=gr.id, po_item_id=it7_1.id, description=it7_1.description, expected_quantity=600.0, received_quantity=600.0, missing_quantity=0, excess_quantity=0, damaged_quantity=0, incorrect_quantity=0, unit="SQM", condition_ok=True, created_by=1),
            ReceiptItem(receipt_id=gr.id, po_item_id=it7_2.id, description=it7_2.description, expected_quantity=300.0, received_quantity=300.0, missing_quantity=0, excess_quantity=0, damaged_quantity=0, incorrect_quantity=0, unit="PCS", condition_ok=True, created_by=1),
        ])
        db.add(OrderStatusHistory(entity_type="PO", entity_id=po7.id, po_id=po7.id, org_id=1, from_status="ARRIVED", to_status="RECEIVED", to_status_label="Received", changed_by=1, notes="Goods Receipt Note GRN-20260920-007 completed"))

        # -------------------------------------------------------------
        # PO 8: PO-2026-0008 (COMPLETED / Closed)
        # -------------------------------------------------------------
        po8 = PurchaseOrder(
            po_number="PO-2026-0008",
            po_nce="SHJ-PO#26019",
            doc_type="PO",
            org_id=3,
            supplier_id=get_sup_id(sup_foshan_toco),
            company=get_sup_name(sup_foshan_toco, "FOSHAN TOCO DECORATIVE MATERIAL CO. LTD"),
            consignee="SAHAJANAND",
            goods_description="Acoustic Ceiling Tiles & Galvanized Grid Suspension Hardware",
            lifecycle_stage="PROFORMA",
            status="COMPLETED",
            status_label="Completed",
            status_id=statuses.get("COMPLETED").id if statuses.get("COMPLETED") else 13,
            payment_status="FULLY_PAID",
            production_status="READY",
            shipment_status="ARRIVED",
            receipt_status="RECEIVED",
            total_amount=Decimal("19400.00"),
            advance_amount=Decimal("19400.00"),
            balance_amount=Decimal("0.00"),
            currency="USD",
            order_mail_date=today - timedelta(days=90),
            payment_date=today - timedelta(days=75),
            freight_type="Sea Freight",
            remark="Order completely settled, delivered to site, and finalized. All invoices audited.",
            created_by=1
        )
        db.add(po8)
        db.flush()
        db.add_all([
            POItem(po_id=po8.id, description="Mineral Fiber Acoustic Ceiling Tile 600x600x15mm Tegular", quantity_ordered=1200.0, quantity_received=1200.0, unit="SQM", unit_price=11.50, po_unit_price=11.50, total_price=13800.00, created_by=1),
            POItem(po_id=po8.id, description="Heavy Duty Ceiling T-Grid Main Runner 3.6m Galvanized Steel", quantity_ordered=1400.0, quantity_received=1400.0, unit="PCS", unit_price=4.00, po_unit_price=4.00, total_price=5600.00, created_by=1),
        ])
        db.add(OrderStatusHistory(entity_type="PO", entity_id=po8.id, po_id=po8.id, org_id=3, from_status="RECEIVED", to_status="COMPLETED", to_status_label="Completed", changed_by=1, notes="Final accounts audit and reconciliation completed"))

        # Commit all new records
        db.commit()
        logger.info("=== STEP 5: SEEDING COMPLETED IN DATABASE ===")

        # -------------------------------------------------------------
        # Sync all newly created orders to Meilisearch
        # -------------------------------------------------------------
        logger.info("=== STEP 6: SYNCING NEW ORDERS TO MEILISEARCH ===")
        all_new_orders = db.query(PurchaseOrder).all()
        client = get_meili_client()
        if client:
            docs = [format_order_doc(o) for o in all_new_orders]
            client.index("purchase_orders").add_documents(docs, primary_key="id")
            logger.info("Successfully synced %d orders/RFQs to Meilisearch.", len(docs))
        
        logger.info("Reseed complete! Total orders created: %d", len(all_new_orders))

    except Exception as e:
        db.rollback()
        logger.exception("Error during re-seeding: %s", e)
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    clean_and_reseed()
