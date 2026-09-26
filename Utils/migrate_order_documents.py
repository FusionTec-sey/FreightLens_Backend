import os
import sys
import logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text
from Model.db import engine, Base
import Model.containermgmt  # ensure models registered

logger = logging.getLogger("containerMgmt.migrations")

def ensure_order_documents_schema():
    """
    Idempotent schema migration for order_documents and order_payments:
    - Uses UUID (native PostgreSQL UUID or VARCHAR(36)) for order_documents.id
    - Adds payment_id and vendor_quote_id FK columns to order_documents
    - Updates order_payments.evidence_doc_id to UUID
    """
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                # Check current type of containermgmt.order_documents.id if table exists
                check_doc_table = conn.execute(text("""
                    SELECT data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = 'containermgmt' 
                      AND table_name = 'order_documents' 
                      AND column_name = 'id';
                """)).scalar()

                if check_doc_table == "integer":
                    # Check if any records exist
                    row_count = conn.execute(text("SELECT count(*) FROM containermgmt.order_documents;")).scalar()
                    if row_count == 0:
                        logger.info("Migrating order_documents.id from INTEGER to UUID (0 existing rows)...")
                        # Drop existing empty table or recreate clean with UUID id
                        conn.execute(text("""
                            -- Remove any FK from order_payments first
                            ALTER TABLE IF EXISTS containermgmt.order_payments 
                            DROP CONSTRAINT IF EXISTS order_payments_evidence_doc_id_fkey;

                            DROP TABLE IF EXISTS containermgmt.order_documents CASCADE;
                        """))
                        conn.commit()

                # Create or ensure order_documents exists with UUID id
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS containermgmt.order_documents (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        entity_type VARCHAR(50) NOT NULL,
                        entity_id INTEGER,
                        po_id INTEGER REFERENCES containermgmt.purchase_orders(id) ON DELETE CASCADE,
                        payment_id INTEGER REFERENCES containermgmt.order_payments(id) ON DELETE SET NULL,
                        vendor_quote_id INTEGER REFERENCES containermgmt.vendor_quotes(id) ON DELETE SET NULL,
                        doc_type VARCHAR(50) NOT NULL,
                        title VARCHAR(255),
                        file_name VARCHAR(255) NOT NULL,
                        file_path VARCHAR(500) NOT NULL,
                        file_size INTEGER,
                        mime_type VARCHAR(100),
                        is_confidential BOOLEAN DEFAULT FALSE,
                        notes TEXT,
                        org_id INTEGER REFERENCES usercredentials.organisations(id) DEFAULT 1,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        is_deleted BOOLEAN DEFAULT FALSE,
                        deleted_at TIMESTAMP WITHOUT TIME ZONE,
                        created_by INTEGER,
                        updated_by INTEGER,
                        deleted_by INTEGER
                    );

                    -- Indexes for fast querying
                    CREATE INDEX IF NOT EXISTS idx_order_docs_po_id ON containermgmt.order_documents(po_id);
                    CREATE INDEX IF NOT EXISTS idx_order_docs_payment_id ON containermgmt.order_documents(payment_id);
                    CREATE INDEX IF NOT EXISTS idx_order_docs_vendor_quote_id ON containermgmt.order_documents(vendor_quote_id);
                    CREATE INDEX IF NOT EXISTS idx_order_docs_entity ON containermgmt.order_documents(entity_type, entity_id);
                    CREATE INDEX IF NOT EXISTS idx_order_docs_type ON containermgmt.order_documents(doc_type);
                    CREATE INDEX IF NOT EXISTS idx_order_docs_org_id ON containermgmt.order_documents(org_id);
                """))
                conn.commit()

                # Ensure order_payments.evidence_doc_id is UUID
                check_pay_col = conn.execute(text("""
                    SELECT data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = 'containermgmt' 
                      AND table_name = 'order_payments' 
                      AND column_name = 'evidence_doc_id';
                """)).scalar()

                if check_pay_col and check_pay_col != "uuid":
                    logger.info("Altering order_payments.evidence_doc_id to UUID...")
                    conn.execute(text("""
                        ALTER TABLE containermgmt.order_payments 
                        DROP CONSTRAINT IF EXISTS order_payments_evidence_doc_id_fkey;

                        ALTER TABLE containermgmt.order_payments 
                        ALTER COLUMN evidence_doc_id TYPE UUID USING NULL;

                        ALTER TABLE containermgmt.order_payments 
                        ADD CONSTRAINT order_payments_evidence_doc_id_fkey 
                        FOREIGN KEY (evidence_doc_id) REFERENCES containermgmt.order_documents(id) ON DELETE SET NULL;
                    """))
                    conn.commit()
                elif check_pay_col == "uuid":
                    # Ensure FK constraint exists
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.table_constraints 
                                WHERE constraint_name = 'order_payments_evidence_doc_id_fkey' 
                                  AND table_schema = 'containermgmt'
                            ) THEN
                                ALTER TABLE containermgmt.order_payments 
                                ADD CONSTRAINT order_payments_evidence_doc_id_fkey 
                                FOREIGN KEY (evidence_doc_id) REFERENCES containermgmt.order_documents(id) ON DELETE SET NULL;
                            END IF;
                        END $$;
                    """))
                    conn.commit()

                logger.info("order_documents schema verified and synchronized with UUID support.")
            else:
                Base.metadata.create_all(bind=engine)
                logger.info(f"Skipping Postgres-specific migration on dialect {engine.dialect.name}")
    except Exception as e:
        logger.error("Failed to migrate order_documents schema: %s", e)
        raise

if __name__ == "__main__":
    ensure_order_documents_schema()
