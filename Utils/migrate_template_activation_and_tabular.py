"""
Utils/migrate_template_activation_and_tabular.py
Migration script adding organization activation controls and tabular operational template support.

Changes to containermgmt.report_templates:
- active_org_ids: INTEGER[] (tracks organizations that activated this template from the library)
- template_type: VARCHAR(30) DEFAULT 'DOCUMENT' ('DOCUMENT' vs 'OPERATIONAL_TABULAR')
- table_config: JSONB (custom columns, labels, order, widths, formatting)
- paper_settings: JSONB (paper size, orientation, margins, repeating headers, page break rules)
"""

import logging
from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_template_activation")


def ensure_template_activation_and_tabular_schema():
    with engine.begin() as conn:
        logger.info("Verifying containermgmt.report_templates activation and tabular columns...")

        # 1. active_org_ids
        conn.execute(text("""
            ALTER TABLE containermgmt.report_templates
            ADD COLUMN IF NOT EXISTS active_org_ids INTEGER[] DEFAULT '{}'::INTEGER[];
        """))

        # 2. template_type
        conn.execute(text("""
            ALTER TABLE containermgmt.report_templates
            ADD COLUMN IF NOT EXISTS template_type VARCHAR(30) DEFAULT 'DOCUMENT' NOT NULL;
        """))

        # 3. table_config
        conn.execute(text("""
            ALTER TABLE containermgmt.report_templates
            ADD COLUMN IF NOT EXISTS table_config JSONB DEFAULT NULL;
        """))

        # 4. paper_settings
        conn.execute(text("""
            ALTER TABLE containermgmt.report_templates
            ADD COLUMN IF NOT EXISTS paper_settings JSONB DEFAULT NULL;
        """))

        # Seed initial activation for existing system templates for Org 1 (Sahaj main org)
        conn.execute(text("""
            UPDATE containermgmt.report_templates
            SET active_org_ids = '{1}'::INTEGER[]
            WHERE is_system = TRUE AND (active_org_ids IS NULL OR array_length(active_org_ids, 1) IS NULL);
        """))

        logger.info("containermgmt.report_templates activation and tabular columns verified.")


if __name__ == "__main__":
    ensure_template_activation_and_tabular_schema()
    print("Template activation and tabular schema migration executed successfully.")
