"""
Migration script for Master Document Types in containermgmt.
Creates containermgmt.master_document_types and seeds stage-aware document types.
"""
import json
import logging
from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_master_document_types")

DEFAULT_DOCUMENT_TYPES = [
    # SOURCING
    {
        "code": "quotation",
        "name": "Vendor Quotation / Proforma",
        "description": "Supplier quotation sheet, pricing schedule, or initial proforma invoice.",
        "applicable_spaces": ["SOURCING", "ORDER"],
        "display_order": 10,
    },
    {
        "code": "technical_spec",
        "name": "Technical Specification / Datasheet",
        "description": "Technical requirements, CAD drawings, material safety datasheets (MSDS).",
        "applicable_spaces": ["SOURCING"],
        "display_order": 20,
    },
    {
        "code": "compliance_cert",
        "name": "Compliance & Test Certificate",
        "description": "Certificates of conformity, factory test reports, ISO / CE certifications.",
        "applicable_spaces": ["SOURCING", "ORDER"],
        "display_order": 30,
    },
    {
        "code": "tender_doc",
        "name": "Tender / RFQ Terms & Conditions",
        "description": "Buyer bidding guidelines, tender specifications, and terms.",
        "applicable_spaces": ["SOURCING"],
        "display_order": 40,
    },

    # ORDER / PO WORKBENCH
    {
        "code": "po_contract",
        "name": "Signed PO Contract",
        "description": "Executed purchase order agreement counter-signed by buyer and supplier.",
        "applicable_spaces": ["ORDER"],
        "display_order": 100,
    },
    {
        "code": "order_confirmation",
        "name": "Supplier Order Confirmation",
        "description": "Official supplier acknowledgment of purchase order.",
        "applicable_spaces": ["ORDER"],
        "display_order": 110,
    },
    {
        "code": "proforma_invoice",
        "name": "Proforma Invoice",
        "description": "Confirmed proforma invoice with final itemized values.",
        "applicable_spaces": ["ORDER"],
        "display_order": 120,
    },
    {
        "code": "export_permit",
        "name": "Export License / Permit",
        "description": "Origin country export authorization or clearance certificate.",
        "applicable_spaces": ["ORDER", "SHIPPING"],
        "display_order": 130,
    },

    # PAYMENT & FINANCIAL CLEARANCE
    {
        "code": "payment_proof",
        "name": "Bank TT / Swift MT103 / Payment Slip",
        "description": "Official bank wire confirmation, Swift slip, or transaction receipt.",
        "applicable_spaces": ["PAYMENT"],
        "display_order": 200,
    },
    {
        "code": "wire_receipt",
        "name": "Wire Transfer Receipt / Bank Voucher",
        "description": "Internal payment advice or debit voucher from bank.",
        "applicable_spaces": ["PAYMENT"],
        "display_order": 210,
    },
    {
        "code": "lc_document",
        "name": "Letter of Credit / Bank Guarantee",
        "description": "Documentary credit advice, LC copy, or performance guarantee.",
        "applicable_spaces": ["PAYMENT"],
        "display_order": 220,
    },
    {
        "code": "remittance_advice",
        "name": "Remittance Advice",
        "description": "Accounts payable remittance confirmation sent to supplier.",
        "applicable_spaces": ["PAYMENT"],
        "display_order": 230,
    },

    # SHIPPING & LOGISTICS
    {
        "code": "bill_of_lading",
        "name": "Bill of Lading / Sea Waybill",
        "description": "Carrier ocean bill of lading, Master BL, or House BL.",
        "applicable_spaces": ["SHIPPING"],
        "display_order": 300,
    },
    {
        "code": "packing_list",
        "name": "Packing List",
        "description": "Container packing list, cargo manifest, and weight details.",
        "applicable_spaces": ["SHIPPING", "ORDER"],
        "display_order": 310,
    },
    {
        "code": "commercial_invoice",
        "name": "Commercial Invoice",
        "description": "Final customs commercial invoice with HS codes.",
        "applicable_spaces": ["SHIPPING", "ORDER"],
        "display_order": 320,
    },
    {
        "code": "cert_of_origin",
        "name": "Certificate of Origin",
        "description": "Chamber of commerce Certificate of Origin (COO).",
        "applicable_spaces": ["SHIPPING"],
        "display_order": 330,
    },
    {
        "code": "insurance_cert",
        "name": "Marine Cargo Insurance",
        "description": "Ocean transit insurance policy / cargo certificate.",
        "applicable_spaces": ["SHIPPING"],
        "display_order": 340,
    },

    # DEFECTS, CLAIMS & QUALITY
    {
        "code": "inspection_report",
        "name": "Quality Inspection Report",
        "description": "Pre-shipment or destination warehouse QA inspection report.",
        "applicable_spaces": ["ORDER", "DEFECTS"],
        "display_order": 400,
    },
    {
        "code": "defect_evidence",
        "name": "Defect Evidence / Photos",
        "description": "Photographs, videos, and technical evidence of damaged or missing cargo.",
        "applicable_spaces": ["DEFECTS"],
        "display_order": 410,
    },
    {
        "code": "defect_resolution",
        "name": "Claim Resolution Agreement",
        "description": "Supplier settlement agreement or joint inspection sign-off.",
        "applicable_spaces": ["DEFECTS"],
        "display_order": 420,
    },
    {
        "code": "credit_note",
        "name": "Vendor Credit Note",
        "description": "Credit adjustment issued by vendor for damaged goods or claims.",
        "applicable_spaces": ["DEFECTS", "PAYMENT"],
        "display_order": 430,
    },

    # GENERAL
    {
        "code": "other",
        "name": "Other Supporting Document",
        "description": "Miscellaneous documentation, general correspondences, and notes.",
        "applicable_spaces": ["SOURCING", "ORDER", "PAYMENT", "SHIPPING", "DEFECTS"],
        "display_order": 999,
    },
]


def ensure_master_document_types_schema():
    """Idempotently creates containermgmt.master_document_types and seeds defaults."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS containermgmt.master_document_types (
                id SERIAL PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                applicable_spaces JSONB NOT NULL DEFAULT '[]'::jsonb,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMP WITHOUT TIME ZONE,
                created_by INTEGER,
                updated_by INTEGER,
                deleted_by INTEGER
            );

            ALTER TABLE containermgmt.master_document_types 
                ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE containermgmt.master_document_types 
                ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITHOUT TIME ZONE;
            ALTER TABLE containermgmt.master_document_types 
                ADD COLUMN IF NOT EXISTS deleted_by INTEGER;

            CREATE INDEX IF NOT EXISTS idx_master_document_types_code 
                ON containermgmt.master_document_types(code);
            CREATE INDEX IF NOT EXISTS idx_master_document_types_active 
                ON containermgmt.master_document_types(is_active);
            CREATE INDEX IF NOT EXISTS idx_master_document_types_deleted 
                ON containermgmt.master_document_types(is_deleted);
        """))

        # Seed defaults if missing
        for item in DEFAULT_DOCUMENT_TYPES:
            existing = conn.execute(
                text("SELECT id FROM containermgmt.master_document_types WHERE code = :code"),
                {"code": item["code"]}
            ).fetchone()

            if not existing:
                conn.execute(
                    text("""
                        INSERT INTO containermgmt.master_document_types 
                        (code, name, description, applicable_spaces, is_active, display_order, created_by)
                        VALUES (:code, :name, :description, CAST(:applicable_spaces AS jsonb), TRUE, :display_order, 'System')
                    """),
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "description": item["description"],
                        "applicable_spaces": json.dumps(item["applicable_spaces"]),
                        "display_order": item["display_order"],
                    }
                )
                logger.info(f"Seeded document type: {item['code']} -> {item['name']}")

    logger.info("containermgmt.master_document_types schema verified and seeded.")


if __name__ == "__main__":
    ensure_master_document_types_schema()
    print("Migration and seeding of containermgmt.master_document_types completed successfully.")
