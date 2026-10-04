import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from Model.db import engine


logger = logging.getLogger("containerMgmt.migrations.reporting_foundation")

FIELD_CLASSES = (
    ("FINANCIAL", "View_Financials", "Prices, costs, payments, margins, and currency values"),
    ("SUPPLIER_IDENTITY", "View_Supplier", "Supplier names and identifying contact details"),
    ("BUDGET", "View_Budget", "Budgets, allocations, and budget variance values"),
    ("PERSONAL", "View_Personal_Data", "Personal contact and identity data"),
)


def ensure_reporting_foundation_schema() -> None:
    """Install the normalized reporting and tenant-ownership schema."""
    if engine.dialect.name != "postgresql":
        logger.info("Skipping reporting foundation migration on %s", engine.dialect.name)
        return

    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE usercredentials.roles
                ADD COLUMN IF NOT EXISTS org_id INTEGER
                    REFERENCES usercredentials.organisations(id) ON DELETE CASCADE,
                ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE usercredentials.roles
                DROP CONSTRAINT IF EXISTS roles_name_key;

            CREATE INDEX IF NOT EXISTS ix_roles_org_id
                ON usercredentials.roles(org_id);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_system_name
                ON usercredentials.roles(lower(name)) WHERE org_id IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_org_name
                ON usercredentials.roles(org_id, lower(name)) WHERE org_id IS NOT NULL;

            CREATE TABLE IF NOT EXISTS usercredentials.user_org_roles (
                user_id INTEGER NOT NULL REFERENCES usercredentials.users(id) ON DELETE CASCADE,
                org_id INTEGER NOT NULL REFERENCES usercredentials.organisations(id) ON DELETE CASCADE,
                role_id INTEGER NOT NULL REFERENCES usercredentials.roles(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, org_id, role_id)
            );
            CREATE INDEX IF NOT EXISTS ix_user_org_roles_org_user
                ON usercredentials.user_org_roles(org_id, user_id);

            ALTER TABLE containermgmt.supplier
                ADD COLUMN IF NOT EXISTS org_id INTEGER
                    REFERENCES usercredentials.organisations(id),
                ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE containermgmt.payment_terms
                ADD COLUMN IF NOT EXISTS org_id INTEGER
                    REFERENCES usercredentials.organisations(id),
                ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE containermgmt.master_document_types
                ADD COLUMN IF NOT EXISTS org_id INTEGER
                    REFERENCES usercredentials.organisations(id),
                ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE containermgmt.products
                ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE containermgmt.product_categories
                ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE;

            CREATE INDEX IF NOT EXISTS ix_supplier_is_shared
                ON containermgmt.supplier(is_shared);
            CREATE INDEX IF NOT EXISTS ix_payment_terms_org_id
                ON containermgmt.payment_terms(org_id);
            CREATE INDEX IF NOT EXISTS ix_payment_terms_is_shared
                ON containermgmt.payment_terms(is_shared);
            CREATE INDEX IF NOT EXISTS ix_master_document_types_org_id
                ON containermgmt.master_document_types(org_id);
            CREATE INDEX IF NOT EXISTS ix_master_document_types_is_shared
                ON containermgmt.master_document_types(is_shared);
            CREATE INDEX IF NOT EXISTS ix_products_is_shared
                ON containermgmt.products(is_shared);
            CREATE INDEX IF NOT EXISTS ix_product_categories_is_shared
                ON containermgmt.product_categories(is_shared);
        """))

        # Legacy scope used NULL org_id for shared suppliers. The normalized
        # model keeps an explicit owner for every row and uses is_shared only
        # as the visibility decision, so remove the old constraint first.
        conn.execute(text("""
            ALTER TABLE containermgmt.supplier
                DROP CONSTRAINT IF EXISTS ck_supplier_scope;
        """))

        conn.execute(text("""
            DO $$
            DECLARE owner_org_id INTEGER;
            BEGIN
                SELECT min(id) INTO owner_org_id FROM usercredentials.organisations;
                IF owner_org_id IS NOT NULL THEN
                    UPDATE containermgmt.supplier
                    SET org_id = owner_org_id, is_shared = TRUE
                    WHERE org_id IS NULL;
                    UPDATE containermgmt.payment_terms
                    SET org_id = owner_org_id, is_shared = TRUE
                    WHERE org_id IS NULL;
                    UPDATE containermgmt.master_document_types
                    SET org_id = owner_org_id, is_shared = TRUE
                    WHERE org_id IS NULL;
                END IF;
            END $$;
        """))

        for table in ("supplier", "payment_terms", "master_document_types"):
            null_count = conn.execute(text(
                f"SELECT count(*) FROM containermgmt.{table} WHERE org_id IS NULL"
            )).scalar_one()
            if null_count:
                raise RuntimeError(
                    f"Cannot enforce master-data ownership on {table}: "
                    f"{null_count} rows have no organisation"
                )
            conn.execute(text(
                f"ALTER TABLE containermgmt.{table} ALTER COLUMN org_id SET NOT NULL"
            ))

        conn.execute(text("""
            ALTER TABLE containermgmt.supplier
                DROP CONSTRAINT IF EXISTS ck_supplier_scope;
            ALTER TABLE containermgmt.payment_terms
                DROP CONSTRAINT IF EXISTS payment_terms_code_key;
            ALTER TABLE containermgmt.master_document_types
                DROP CONSTRAINT IF EXISTS master_document_types_code_key;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_terms_org_code
                ON containermgmt.payment_terms(org_id, code);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_master_document_types_org_code
                ON containermgmt.master_document_types(org_id, code);

            CREATE TABLE IF NOT EXISTS containermgmt.org_print_profiles (
                org_id INTEGER PRIMARY KEY
                    REFERENCES usercredentials.organisations(id) ON DELETE CASCADE,
                legal_name VARCHAR(255),
                address TEXT,
                tax_id VARCHAR(100),
                contact_email VARCHAR(255),
                contact_phone VARCHAR(100),
                logo_asset_key VARCHAR(500),
                stamp_asset_key VARCHAR(500),
                signature_asset_key VARCHAR(500),
                bank_details JSONB NOT NULL DEFAULT '{}'::jsonb,
                default_terms JSONB NOT NULL DEFAULT '{}'::jsonb,
                brand_color VARCHAR(20),
                font_family VARCHAR(100),
                locale VARCHAR(20) NOT NULL DEFAULT 'en-SC',
                timezone VARCHAR(100) NOT NULL DEFAULT 'Indian/Mahe',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMPTZ,
                created_by INTEGER REFERENCES usercredentials.users(id),
                updated_by INTEGER REFERENCES usercredentials.users(id),
                deleted_by INTEGER REFERENCES usercredentials.users(id)
            );

            CREATE TABLE IF NOT EXISTS containermgmt.report_template_assignments (
                id SERIAL PRIMARY KEY,
                org_id INTEGER NOT NULL
                    REFERENCES usercredentials.organisations(id) ON DELETE CASCADE,
                template_id INTEGER NOT NULL
                    REFERENCES containermgmt.report_templates(id) ON DELETE CASCADE,
                entity_type VARCHAR(100) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                default_options JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMPTZ,
                created_by INTEGER REFERENCES usercredentials.users(id),
                updated_by INTEGER REFERENCES usercredentials.users(id),
                deleted_by INTEGER REFERENCES usercredentials.users(id),
                CONSTRAINT uq_report_template_assignment UNIQUE (org_id, template_id)
            );
            CREATE INDEX IF NOT EXISTS ix_report_template_assignments_org_entity
                ON containermgmt.report_template_assignments(org_id, entity_type);
            CREATE INDEX IF NOT EXISTS ix_report_template_assignments_template_id
                ON containermgmt.report_template_assignments(template_id);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_report_template_default_org_entity
                ON containermgmt.report_template_assignments(org_id, entity_type)
                WHERE is_default = TRUE AND is_deleted = FALSE;

            CREATE TABLE IF NOT EXISTS containermgmt.report_field_classes (
                code VARCHAR(50) PRIMARY KEY,
                permission_name VARCHAR(45) NOT NULL
                    REFERENCES usercredentials.permissions(name) ON DELETE RESTRICT,
                description VARCHAR(255) NOT NULL
            );

            ALTER TABLE containermgmt.report_template_versions
                ADD COLUMN IF NOT EXISTS paper_settings JSONB,
                ADD COLUMN IF NOT EXISTS options_schema JSONB;
            ALTER TABLE containermgmt.report_templates
                ADD COLUMN IF NOT EXISTS is_default_for_new_orgs BOOLEAN NOT NULL DEFAULT FALSE;
            UPDATE containermgmt.report_templates
            SET is_default_for_new_orgs = TRUE
            WHERE is_system IS TRUE;

            ALTER TABLE containermgmt.purchase_orders
                ADD COLUMN IF NOT EXISTS base_currency VARCHAR(10),
                ADD COLUMN IF NOT EXISTS exchange_rate_to_base NUMERIC(18, 8),
                ADD COLUMN IF NOT EXISTS total_amount_base NUMERIC(14, 2),
                ADD COLUMN IF NOT EXISTS advance_amount_base NUMERIC(14, 2),
                ADD COLUMN IF NOT EXISTS balance_amount_base NUMERIC(14, 2);
            ALTER TABLE containermgmt.po_items
                ADD COLUMN IF NOT EXISTS base_currency VARCHAR(10),
                ADD COLUMN IF NOT EXISTS exchange_rate_to_base NUMERIC(18, 8),
                ADD COLUMN IF NOT EXISTS unit_price_base NUMERIC(14, 2),
                ADD COLUMN IF NOT EXISTS total_price_base NUMERIC(14, 2);
            ALTER TABLE containermgmt.order_payments
                ADD COLUMN IF NOT EXISTS base_currency VARCHAR(10),
                ADD COLUMN IF NOT EXISTS base_amount NUMERIC(14, 2);

            UPDATE containermgmt.report_template_versions AS version
            SET paper_settings = template.paper_settings
            FROM containermgmt.report_templates AS template
            WHERE version.template_id = template.id
              AND version.paper_settings IS NULL
              AND template.paper_settings IS NOT NULL;

            INSERT INTO containermgmt.report_template_assignments
                (org_id, template_id, entity_type, is_active, is_default, default_options)
            SELECT active_org_id, template.id, template.entity_type, TRUE, FALSE,
                   COALESCE(template.default_params, '{}'::json)
            FROM containermgmt.report_templates AS template
            CROSS JOIN LATERAL unnest(COALESCE(template.active_org_ids, '{}'::integer[]))
                AS active_org_id
            JOIN usercredentials.organisations AS organisation
                ON organisation.id = active_org_id
            ON CONFLICT (org_id, template_id) DO NOTHING;

            INSERT INTO usercredentials.user_org_roles (user_id, org_id, role_id)
            SELECT DISTINCT users.id, allowed_org_id, user_roles.role_id
            FROM usercredentials.users AS users
            JOIN usercredentials.user_roles AS user_roles ON user_roles.user_id = users.id
            CROSS JOIN LATERAL unnest(
                CASE
                    WHEN array_length(users.allowed_org_ids, 1) IS NOT NULL
                        THEN users.allowed_org_ids
                    WHEN users.org_id IS NOT NULL THEN ARRAY[users.org_id]
                    ELSE '{}'::integer[]
                END
            ) AS allowed_org_id
            JOIN usercredentials.organisations AS organisation
                ON organisation.id = allowed_org_id
            ON CONFLICT DO NOTHING;
        """))

        conn.execute(text("""
            ALTER TABLE containermgmt.report_render_jobs
                ADD COLUMN IF NOT EXISTS is_issued BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS retain_until TIMESTAMPTZ;
            CREATE INDEX IF NOT EXISTS ix_report_render_jobs_is_issued
                ON containermgmt.report_render_jobs(is_issued);
            CREATE INDEX IF NOT EXISTS ix_report_render_jobs_retain_until
                ON containermgmt.report_render_jobs(retain_until);
        """))

    logger.info("Reporting foundation schema is ready")


def seed_reporting_foundation(db: Session) -> None:
    """Seed rows that depend on organisations and permissions created by seed_db."""
    for code, permission_name, description in FIELD_CLASSES:
        db.execute(text("""
            INSERT INTO usercredentials.permissions (name, description)
            VALUES (:name, :description)
            ON CONFLICT (name) DO NOTHING
        """), {"name": permission_name, "description": description})
        db.execute(text("""
            INSERT INTO containermgmt.report_field_classes
                (code, permission_name, description)
            VALUES (:code, :permission_name, :description)
            ON CONFLICT (code) DO UPDATE SET
                permission_name = EXCLUDED.permission_name,
                description = EXCLUDED.description
        """), {
            "code": code,
            "permission_name": permission_name,
            "description": description,
        })

    db.execute(text("""
        INSERT INTO containermgmt.org_print_profiles
            (org_id, legal_name, logo_asset_key, bank_details, default_terms,
             locale, timezone)
        SELECT id, COALESCE(display_name, name), logo_url, '{}'::json, '{}'::json,
               'en-SC', 'Indian/Mahe'
        FROM usercredentials.organisations
        ON CONFLICT (org_id) DO NOTHING
    """))
    db.execute(text("""
        UPDATE usercredentials.roles
        SET is_platform_admin = TRUE
        WHERE lower(name) IN ('super_admin', 'superadmin', 'root')
          AND org_id IS NULL
    """))
    db.execute(text("""
        INSERT INTO usercredentials.user_org_roles (user_id, org_id, role_id)
        SELECT DISTINCT users.id, allowed_org_id, user_roles.role_id
        FROM usercredentials.users AS users
        JOIN usercredentials.user_roles AS user_roles ON user_roles.user_id = users.id
        CROSS JOIN LATERAL unnest(
            CASE
                WHEN array_length(users.allowed_org_ids, 1) IS NOT NULL
                    THEN users.allowed_org_ids
                WHEN users.org_id IS NOT NULL THEN ARRAY[users.org_id]
                ELSE '{}'::integer[]
            END
        ) AS allowed_org_id
        JOIN usercredentials.organisations AS organisation
            ON organisation.id = allowed_org_id
        ON CONFLICT DO NOTHING
    """))
    db.execute(text("""
        INSERT INTO containermgmt.report_template_assignments
            (org_id, template_id, entity_type, is_active, is_default, default_options)
        SELECT active_org_id, template.id, template.entity_type, TRUE, FALSE,
               COALESCE(template.default_params, '{}'::json)
        FROM containermgmt.report_templates AS template
        CROSS JOIN LATERAL unnest(COALESCE(template.active_org_ids, '{}'::integer[]))
            AS active_org_id
        JOIN usercredentials.organisations AS organisation
            ON organisation.id = active_org_id
        ON CONFLICT (org_id, template_id) DO NOTHING
    """))
    db.execute(text("""
        INSERT INTO containermgmt.report_template_assignments
            (org_id, template_id, entity_type, is_active, is_default, default_options)
        SELECT template.org_id, template.id, template.entity_type,
               template.is_active, FALSE, COALESCE(template.default_params, '{}'::json)
        FROM containermgmt.report_templates AS template
        WHERE template.is_system IS FALSE
          AND template.org_id IS NOT NULL
          AND template.is_deleted IS FALSE
        ON CONFLICT (org_id, template_id) DO NOTHING
    """))
    db.commit()

    # Legacy seeders now write owner-backed shared defaults.
    from Utils.migrate_master_data import ensure_master_data_schema
    from Utils.migrate_master_document_types import ensure_master_document_types_schema

    ensure_master_data_schema()
    ensure_master_document_types_schema()
