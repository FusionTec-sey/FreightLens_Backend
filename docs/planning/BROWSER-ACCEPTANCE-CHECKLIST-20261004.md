# Browser acceptance checklist — 2026-10-04

Owner-run. Browser acceptance is the only remaining gate on T03, T04, T05 and
T33A; every other criterion in those entries is implemented and automated-verified.
Record results against each row and attach them to the task entries as evidence.

**Setup**

- `http://localhost:3000`, signed in as `parth`.
- Switch company (top right) to **DEMO ONLY - FreightLens T05** (org 4). It is the
  only company with fixtures. On SAHAJ CONSTRUCTION every screen is empty by
  design — that is correct behaviour, not a defect.
- Check each screen in **light and dark** theme, and once at roughly **400px wide**:
  the sidebar must stay fixed, only the content area scrolls, and there must be no
  horizontal page scrollbar.
- Log findings as: screen → action → expected → actual.

---

## 1. T33A — Stock Counts

| # | Screen | Expected |
|---|---|---|
| 1.1 | Stock Counts → Count plans | `DEMO-CNT-1` listed, state **ACTIVE**, 3 scope lines |
| 1.2 | Count plans → Coverage | Per-location table: in scope / counted / outstanding / next due |
| 1.3 | Count rounds | Round 1 **SUBMITTED** and round 2 **ASSIGNED**, both DEMO - Stock display |
| 1.4 | My count rounds | Only rounds assigned to the signed-in user (likely empty) |
| 1.5 | Discrepancies | 3 rows: 0, −2 and −20 PCS; the −20 shows **REVIEWED / RECOUNT_REQUIRED** |
| 1.6 | Open a discrepancy | Counted, expected and difference shown, with the note that expected is a submission-time snapshot and the difference is provisional |
| 1.7 | **Blind sheet** (Count button on your own assigned round) | **CRITICAL.** Product, SKU, unit and step only. **No expected quantity, no earlier count, no stock figure, no value anywhere on the screen.** Any expected number here is a blind-count failure and the most serious defect available |
| 1.8 | Blind sheet | States entries are permanent and a correction needs a new recount round |
| 1.9 | Count plans (as a user without Manage_CountPlan) | No create, scope or activate actions offered |

## 2. T07 — Reservations and POS

| # | Screen | Expected |
|---|---|---|
| 2.1 | Point of Sale → Sales drafts | 6 drafts showing **customer names**, store, item count and date — not raw UUIDs |
| 2.2 | Open a draft | Detail card: reference, customer/store grid, per-line rows, reserved badge indigo only where stock is held |
| 2.3 | Draft → Reserved stock | Holds table; the overdue hold shows a rose **"Follow-up due — still held"** badge |
| 2.4 | Overdue follow-up | Exactly 1 row; "Open draft" drills through and re-checks access |
| 2.5 | Draft `4eb14847…` → Preview work area stock → DEMO-TILL-1 | Four-figure grid and **"Covered in this area"**. Must **not** say "waiting for configured stock runtime authority" — that gate was cleared 2026-10-04 |
| 2.6 | Reservation / Follow-up / Reallocation reviews | Each lists its seeded cases with correct states |
| 2.7 | Local drafts | State badges: amber unconfirmed, rose conflict, slate unsaved |

## 3. T04 — Manager cases and notification delivery

| # | Screen | Expected |
|---|---|---|
| 3.1 | Any Approvals screen | Status badges (amber requested, emerald approved, rose rejected); approve and reject are visually distinct |
| 3.2 | Notifications | Unread entries for the seeded cases; opening one reaches the case |
| 3.3 | Notification text | Contains **no customer name, contact, quantity, amount or reason text** |
| 3.4 | Review your own request | Refused by the backend |

## 4. T05 / T03 — Policies, barcodes, branch settings

| # | Screen | Expected |
|---|---|---|
| 4.1 | Inventory → policy drafts and activation | T05 demo products in mixed states: pending, approved, rejected |
| 4.2 | Barcode reviews | Pending, approved and retired barcode cases present |
| 4.3 | Branch settings → Counters | `DEMO-TILL-1` exists, enabled, with a work area set (seeded 2026-10-04; no counters existed anywhere before) |
| 4.4 | Trading settings | Business-date and cutoff configuration renders and saves |

## 5. POS printing

| # | Screen | Expected |
|---|---|---|
| 5.1 | Draft → Print draft | Company header, customer and store blocks, line table, footer |
| 5.2 | Footer wording | States the document is draft demand, **not an invoice, receipt, quotation or proof of payment**, and not an entitlement to collect |
| 5.3 | Browser print preview | App shell, sidebar and buttons do **not** appear on the printed sheet |

## 6. Cross-cutting

| # | Check | Expected |
|---|---|---|
| 6.1 | Dark mode, every screen above | No unreadable contrast, no white-on-white panels, badges legible |
| 6.2 | ~400px width | Fixed shell, contained scrolling, no horizontal page scroll |
| 6.3 | Company switch mid-session | Data clears and reloads for the newly selected company; no cross-company leakage |
| 6.4 | Compare against Purchase Orders (`/orders`) | Header band, table head, buttons, badges and pagination read as the same product |

---

## Known-empty, not defects

- Orgs 1–3 (`sahaj`, `noblecon`, `sahajanand`) have the SALES module enabled but no
  branches, locations, stock, counters or customers, so POS and Counts screens open
  empty and the work-area preview refuses. Only org 4 is seeded.
- Orgs 1–3 have no enrolled `StoreNode`, so their stock runtime claims fail by
  design until a node is enrolled per company.
- `ProductMasterPage` keeps its own existing visual design and was deliberately not
  re-themed.
