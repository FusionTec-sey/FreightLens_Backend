# T04 manager case notification checkpoint

Date: 2026-10-04. Decision revision: BD-20261003-05.

T04 implementation is ready for acceptance checks, but T04 is **not verified complete**. The canonical queue in `docs/planning/TASK-QUEUE.txt` remains unchanged because this workspace denied writes to that file.

## Implemented in this checkpoint

- Notification list, unread count, single read and mark-all-read operations now filter by both the signed-in recipient and allowed company. The list is server-paginated.
- The shared notification route accepts users subscribed to ORDERS, INVENTORY, LOGISTICS or SALES, while still requiring authentication and recipient scope.
- Case notification recipients are selected from company-specific role grants and active module entitlement, matching the request access policy more closely than global role assignments.
- The sidebar profile opens a paginated notification panel with unread state and a review-queue link.

## Verification

- Backend focused access tests: 2 passed (`tests/test_case_notification_access.py`).
- Frontend menu and notification tests: 9 passed.
- Frontend production build: passed with existing project warnings.
- `git diff --check`: passed in both repositories.

## Still required before T04 is called complete

- Database-backed verification of case recipient selection and transaction-coupled delivery in an isolated PostgreSQL test database. The database fixture was unavailable in this session.
- Browser acceptance of the profile notification panel and manager case queue. `AGENTS.md` rule 13 requires explicit owner approval before browser automation; approval was requested and has not yet been received.

No live delivery, external messages, real business data, or deployment was performed. T06 and T07 remain in progress and are outside this checkpoint.
