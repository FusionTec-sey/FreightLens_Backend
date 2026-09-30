# FreightLens — Development Rules

> Before any change, read `docs/ARCHITECTURE.md` and the latest 10 entries in `docs/ARCHITECTURE_LOG.md`.

> **This file is the single source of truth for all development standards.**
> Before writing any code, read the relevant detailed rule file under .agents/rules/.

---

## Quick Index

| Topic | File |
|---|---|
| Architecture & Stack | .agents/rules/architecture.md |
| Database & Migrations | .agents/rules/database.md |
| Search (Meilisearch) | .agents/rules/search.md |
| API Design (FastAPI) | .agents/rules/api.md |
| Security & RBAC | .agents/rules/security.md |
| Object Storage (RustFS) | .agents/rules/storage.md |
| Pagination & Tables | .agents/rules/pagination.md |
| Frontend (React) | .agents/rules/frontend.md |
| UI Layout & Viewport | .agents/rules/ui-layout.md |

---

## Core Principles (Non-Negotiable)

### 1. Inspect Before You Implement
Before building anything:
1. Inspect the existing implementation in the affected area.
2. Reuse existing components, services, utilities, and mixins.
3. Do not create duplicate functionality.
4. Follow existing architecture and naming conventions exactly.
5. Consider scalability — assume production data is large.

### 2. Authorization Is Always Backend-Enforced
- Frontend visibility controls (hide buttons, columns, tabs) are UX only.
- The backend API is the security boundary.
- If a user does not have permission, the backend must not return the data.
- See .agents/rules/security.md.

### 3. Tables Always Use Server-Side Pagination
- Never return all rows of a table that can grow.
- Pagination, filtering, and sorting must be implemented server-side.
- See .agents/rules/pagination.md.

### 4. Search Uses Meilisearch — Not SQL LIKE
- Product and entity search must use Services/search_service.py.
- SQL LIKE is not acceptable as a primary search mechanism.
- Meilisearch index must be kept in sync on every create/update/delete.
- See .agents/rules/search.md.

### 5. Schema Migrations via Utils/migrate_*.py
- Every schema change requires a Utils/migrate_*.py migration script.
- Migrations run at startup via containerMgmt.py startup_event.
- Never apply ad-hoc ALTER TABLE manually without a migration script.
- See .agents/rules/database.md.

### 6. Documents Use UUID Primary Keys
- order_documents.id and all document/attachment records use UUID primary keys.
- Prevents IDOR enumeration attacks on file download endpoints.
- See .agents/rules/storage.md and .agents/rules/security.md.

### 7. Multi-Tenant Row Isolation
- Every data model that stores business data must use OrgMixin for org_id.
- Resolve `OrgContext` with `get_org_context` and scope queries with `apply_org_filter`.
- Models with an explicit shared/tenant scope use `apply_shared_or_org_filter`.
- Never expose data from one organisation to another.
- See .agents/rules/database.md.

### 8. Reuse UI Components — Do Not Duplicate
- Before creating any new React component, check what already exists.
- Refer to the component inventory in .agents/rules/frontend.md.

### 9. Scrolling Is Contained — Not Whole-Page
- Application shell (sidebar, navbar) must stay fixed.
- Only the content area or table scrolls.
- See .agents/rules/ui-layout.md.

### 10. Scalability Assumption
Assume production will contain:
- Thousands of products and SKUs
- Hundreds of thousands of purchase order line items
- Millions of audit log and transaction records

Design accordingly from day one.

### 11. No KPIs on Operational Work Screens
- Operational work screens (registers, master tables, entry screens, and transactional listings) must never include top KPI summary cards or metric counters.
- Maximize vertical viewport height for data rows, filters, and actions with contained scrolling.
- All aggregate statistics, counts, and performance metrics belong in their respective module dashboard widgets (`/dashboard`).
- See .agents/rules/ui-layout.md and .agents/rules/frontend.md.

### 12. Flexibility & Continuous Improvement Protocol
- **Living Architecture**: Rules exist to guarantee security, maintainability, and scalability, but must remain flexible when encountering novel engineering requirements, emerging edge cases, or superior paradigms.
- **Proactive Scope of Improvement**: When a current rule is found to be suboptimal, over-restrictive, or causing architectural friction:
  1. **Explain the Why**: Clearly explain why the current rule is insufficient or problematic in this specific context.
  2. **Demonstrate Future Benefit**: Articulate how the proposed change will enhance long-term system health, maintainability, reliability, or developer velocity.
- **Genuine Need Only**: Do not propose rule changes arbitrarily or create unnecessary overhead on every task. Changes should only be suggested when there is a concrete, tangible advantage.
- **Mandatory Approval Gate**: Never unilaterally alter rules, deviate from core conventions, or modify `.agents/rules/` without prior discussion. Always submit the proposal to the user and obtain explicit approval before updating.

### 13. Always Ask Before Proceeding with DOM / Browser Interactions
- Before initiating any automated browser interaction, navigating URLs, manipulating web pages, or inspecting/modifying DOM elements in the browser via subagents or automated tools, the assistant must always ask the user for explicit confirmation.
- Clearly explain the planned verification steps and target URLs, and await user approval before launching browser automation.

### 14. Verification Is Part of Done
- Add or update endpoint tests for authentication, authorization, and tenant isolation when API behavior changes.
- Run the relevant backend test suite and frontend production build before calling a phase complete.
- Record any skipped check or pre-existing failure explicitly.

### 15. Keep Rules Executable
- Rule examples must name the helpers and libraries that exist in the repository.
- When a helper, dependency, or framework convention changes, update the affected rule file in the same approved change.

---

## Known Stabilization Deviations

These are tracked exceptions, not approved patterns for new code:

- `OrgMixin.org_id` is still nullable and defaults to organisation `1`; Phase 2 must remove both behaviors after data cleanup.
- Several cross-module routers do not yet have an explicit module guard; Phase 5 owns the router-by-router authorization review.
- APScheduler starts at import time and FastAPI still uses deprecated startup events; lifecycle migration remains pending.
- Some large router and frontend page files remain above the maintainable size target.
- The frontend production build succeeds with existing ESLint warnings, but strict CI warning enforcement does not yet pass.
- Legacy MySQL migration material and committed development secret defaults remain until Phase 5 cleanup.

---

## Rule Evolution & Modification Workflow

When a genuine scope of improvement is identified during development:

1. **Trigger Condition**:
   - An existing rule prevents an optimal or secure implementation.
   - A new requirement or better engineering pattern emerges that renders a rule obsolete or incomplete.
2. **Proposal Structure**:
   - **Current Rule & Constraint**: Identify the file and section, explaining the exact bottleneck.
   - **Proposed Update / Exception**: Detail the recommended change or standard.
   - **Future Benefit**: Clarify how this benefits the codebase, prevents future regressions, and scales.
3. **Approval Gate**:
   - Explicitly ask the user for approval. Do not proceed with rule updates or exceptions until confirmed.
4. **Synchronize Documentation**:
   - Once approved, update the affected `.agents/rules/*.md` files and `AGENTS.md` to maintain a single source of truth.
