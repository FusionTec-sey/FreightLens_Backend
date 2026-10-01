import logging

from sqlalchemy import text

from Model.db import engine


logger = logging.getLogger("containerMgmt.migrations.reporting_worker")


def ensure_reporting_worker_schema() -> None:
    if engine.dialect.name != "postgresql":
        logger.info("Skipping reporting worker migration on %s", engine.dialect.name)
        return

    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE containermgmt.report_render_jobs
                ADD COLUMN IF NOT EXISTS data_snapshot JSONB,
                ADD COLUMN IF NOT EXISTS output_sha256 VARCHAR(64),
                ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3,
                ADD COLUMN IF NOT EXISTS worker_id VARCHAR(100),
                ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS retry_at TIMESTAMPTZ;

            CREATE INDEX IF NOT EXISTS ix_render_jobs_worker_id
                ON containermgmt.report_render_jobs(worker_id);
            CREATE INDEX IF NOT EXISTS ix_render_jobs_lease_expires_at
                ON containermgmt.report_render_jobs(lease_expires_at);
            CREATE INDEX IF NOT EXISTS ix_render_jobs_retry_at
                ON containermgmt.report_render_jobs(retry_at);
            CREATE INDEX IF NOT EXISTS ix_render_jobs_claim
                ON containermgmt.report_render_jobs(status, retry_at, requested_at);
        """))

    logger.info("Reporting worker schema is ready")
