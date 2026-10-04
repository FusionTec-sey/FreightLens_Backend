# Local Docker integration verification — 2026-10-04

This is a verification record, not a second task queue. Run a pending check only when its failure or feature is being investigated.

## Running checkpoint

- Backend `codex/pos-development`: local merge `88e1136` includes GitHub checkpoint `d3ba51f` and retains the two earlier local commits.
- Frontend `codex/pos-development`: `65a2769`.
- Existing Docker Compose project is running PostgreSQL, RustFS, Meilisearch, backend, report worker, and frontend. `docker compose up -d --no-build` succeeds with the ignored local `.env`.
- Backup before startup migrations: `../../../../backups/freightlens-preintegration-20261004.dump` (workspace `backups` directory).
- Backend `/health` returned 200 with database and object storage connected. Frontend `/`, `/sales/drafts`, and `/master-data/customers` returned 200.
- The local database has `parth` and `admin_sahaj` assigned `Super_Admin` roles with platform-admin authority. Short-lived local tokens for those database users received 200 from `/auth/me/access`, `/master-data/customers`, `/sales/drafts`, `/inventory/cost-pools`, and `/admin/stats`. `/auth/me/access` reported `is_platform_admin: true` for both. Password login and browser sessions were not exercised.
- Docker frontend production build succeeded with existing ESLint and Browserslist warnings. Frontend tests: 213 passed in 41 suites.
- Backend full suite on a separate synthetic `freightlens_integrate_test` database: 1204 passed, 2 expected failures, 3 failed, 22 warnings. Raw logs are in workspace `backups/backend-integration-pytest-20261004.log` and `backups/frontend-integration-tests-20261004.log`.

## Pending checks on request

1. **Reporting worker test:** `tests/test_reporting_worker.py::test_issued_copy_detection_uses_document_type_and_lifecycle` raises `NameError` because the test references `columns` without defining it. If investigating reporting, fix that test and run only its affected test file.
2. **T05 demo seed:** `tests/test_t05_demo_seed.py::test_demo_seed_is_atomic_scoped_and_repeatable` rejects the custom test database name. The seed allows the dedicated `containermgmt_test` database. If investigating T05, run this test against that isolated synthetic database.
3. **Test environment assertion:** `tests/test_test_environment.py::test_test_database_is_explicitly_isolated` expects the URL to end in `/containermgmt_test`. If investigating test setup, run this file with that database name.
4. **Browser and actual login:** Visual navigation and password-based sessions for `parth` and `admin_sahaj` remain unverified. Browser automation requires the approval specified in `AGENTS.md`; credentials were not requested or used.

The full backend suite is recorded above. Do not repeat it routinely; use focused checks for a specific change or failure.
