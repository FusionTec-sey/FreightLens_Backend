"""
migration_v2.py — Security & Architecture Improvements
=======================================================
Run this script ONCE on the production database to apply all required
schema changes identified in the security audit.

Usage:
    python migration_v2.py

Safe to run multiple times — each statement is wrapped in a try/except
so already-applied changes are skipped without stopping the script.
"""

import sys
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


MIGRATIONS = [
    # ──────────────────────────────────────────────────────────────────────────
    # MIGRATION 1 — Fix password_hash column length (CRITICAL)
    # bcrypt hashes are 60 characters; VARCHAR(45) truncates them, breaking login.
    # ──────────────────────────────────────────────────────────────────────────
    (
        "Widen usercredentials.users.password_hash to VARCHAR(255)",
        """
        ALTER TABLE usercredentials.users
            MODIFY COLUMN password_hash VARCHAR(255) NOT NULL;
        """,
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # MIGRATION 2 — Create DB-backed refresh token table
    # Replaces the in-memory fake_refresh_tokens={} dict in auth/routes.py.
    # Tokens survive restarts and work across multiple uvicorn workers.
    # ──────────────────────────────────────────────────────────────────────────
    (
        "Create usercredentials.user_refresh_tokens table",
        """
        CREATE TABLE IF NOT EXISTS usercredentials.user_refresh_tokens (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            user_id     INT NOT NULL
                        COMMENT 'FK to usercredentials.users.id',
            token_hash  VARCHAR(255) NOT NULL
                        COMMENT 'SHA-256 hex digest of the raw refresh token',
            expires_at  DATETIME NOT NULL
                        COMMENT 'When this token expires (UTC)',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                        COMMENT 'When this token was issued (UTC)',
            revoked     TINYINT(1) NOT NULL DEFAULT 0
                        COMMENT '0 = active, 1 = revoked (logout / rotation)',
            CONSTRAINT fk_refresh_user
                FOREIGN KEY (user_id)
                REFERENCES usercredentials.users(id)
                ON DELETE CASCADE,
            INDEX idx_token_hash  (token_hash),
            INDEX idx_user_expires (user_id, expires_at)
        ) ENGINE=InnoDB
          DEFAULT CHARSET=utf8mb4
          COLLATE=utf8mb4_unicode_ci
          COMMENT='Persisted refresh tokens — replaces in-memory dict';
        """,
    ),
]


def run_migration():
    print("=" * 60)
    print("  migration_v2.py — Security Improvements")
    print("=" * 60)

    with engine.connect() as conn:
        for description, sql in MIGRATIONS:
            print(f"\n>> {description}")
            try:
                conn.execute(text(sql.strip()))
                conn.commit()
                print(f"   [OK] Applied")
            except Exception as e:
                msg = str(e)
                # Duplicate column / table already exists → skip gracefully
                if "already exists" in msg.lower() or "duplicate column" in msg.lower():
                    print(f"   [SKIP] Already applied: {msg[:80]}")
                else:
                    print(f"   [ERROR]: {msg}")
                    print("   Aborting migration — fix the error and re-run.")
                    sys.exit(1)

    print("\n" + "=" * 60)
    print("  All migrations completed successfully.")
    print("=" * 60)


if __name__ == "__main__":
    run_migration()
