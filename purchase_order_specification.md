# Purchase Order Lifecycle Management Specification

This specification outlines the architecture, data management, and state machine design for an adaptable Purchase Order (PO) workflow capable of handling deep changes (item additions, structural updates, deletions) at every stage.

---

## 1. Core Workflow Architecture

```
[Draft] -> [Confirmed Draft] -> [Request for Quote (RFQ)] -> [Quote Received] -> [Quote Approved] -> [Purchase Order] -> [Proforma Invoice]
```

### Stage Transitions & Allowed Changes

| Stage | Definition | Allowed Modifications | Impact on Previous States |
| :--- | :--- | :--- | :--- |
| **1. Draft** | Initial internal request. | Unlimited additions, removals, price adjustments. | None (Local scratchpad). |
| **2. Confirmed Draft** | Internal validation complete. Locked for review. | Minor quantities / notes adjustments only. | Promotes to RFQ. Reverting to Draft triggers a revision loop. |
| **3. Request for Quote (RFQ)** | Sent out to single or multiple vendors. | Vendors can suggest substitute items or quantities. | Generates Vendor Quotation variants. |
| **4. Quote Received** | Vendor pricing/availability received. | Price adjustments, shipping terms, partial line-item rejections. | System captures and versions the specific vendor counter-offer. |
| **5. Quote Approved** | Final selection of vendor offer. | Strictly locked. No item changes allowed without rollback. | Authorizes immediate generation of the official PO. |
| **6. Purchase Order (PO)** | Legal binding document issued to vendor. | Contractual amendments only via Change Orders. | Triggers inventory allocation and financial accounting encumbrance. |
| **7. Proforma Invoice** | Vendor's advance billing received. | Line items must match PO. Financial terms / down-payment schedules added. | Sets up down-payment processing and finalizes Three-Way Matching. |

---

## 2. Managing Item Mutations & Price Variances

To handle continuous changes (adding/removing items, price fluctuations) without corrupting financial trails, the system must abandon destructive overwrites (`UPDATE` queries on line items) in favor of **immutable document snapshotting** and **audit delta logging**.

### Recommended Database Schema Strategy

1. **The Header Table (`purchase_orders`)**
   Tracks the global state, current active version, and references to vendor info.
2. **The Immutable Version Table (`po_versions`)**
   Every structural change (e.g., adding an item, updating a price) saves a *new* entry here with a incremented version counter (`v1`, `v2`, `v3`).
3. **The Line Items Snapshot (`po_line_items`)**
   Tied explicitly to a unique `po_version_id`. Instead of deleting an item, a new version is created *without* that line item.

### Handling Price Deviations (Quote vs. PO vs. Proforma)
* **Quote Line Price:** Temporary market price proposed by vendor.
* **PO Line Price:** Contractually locked acquisition cost.
* **Proforma Price:** Finalized invoice price (including custom duties, handling fees, or volume discounts applied late).
* **Variance Logic:** If the Proforma Invoice amount deviates from the Approved PO by more than a configurable threshold (e.g., ±2%), the system must automatically divert the document to a **Variance Approval Queue** before payment clearance.

---

## 3. Comparative Design Alternatives

### Alternative A: The Linear Mutation Model (Current Foundation)
Modifies a single database record continuously using status flags.
* **Pros:** Simple schema; easy to query current state.
* **Cons:** Total loss of historical audit trails; high risk of breaking data integrity when items are deleted mid-process.

### Alternative B: The Split-Document Model (Recommended)
Transforms entities completely at milestones (e.g., closing the RFQ and spawning an independent PO record).
* **Pros:** Clean business boundaries; specialized data structures optimize performance per phase.
* **Cons:** Requires complex relational mappings to trace an item's lineage back to its original Draft request.

---

## 4. LLM Engineering Prompt (Claude Opus Optimized)

Copy and paste this prompt directly into **Claude Opus** to generate your application code, database scripts, or front-end mocks:

```text
You are an expert Enterprise Solutions Architect specializing in supply chain and ERP workflows. Help me design and code a resilient Purchase Order Lifecycle Management System based on the following specifications:

1. WORKFLOW PIPELINE:
   Draft -> Confirmed Draft -> RFQ Sent -> Quote Received -> Quote Approved -> Purchase Order -> Proforma Invoice.

2. CRITICAL CONSTRAINT:
   Items can be added, removed, or have price/quantity mutations at ANY stage before the Purchase Order is officially issued. 

3. TECHNICAL REQUIREMENTS:
   - Provide a clean database schema (SQL/PostgreSQL syntax) that utilizes a document versioning design pattern (immutable snapshots) to preserve a clear audit trail of deletions and edits.
   - Outline a state machine matrix using pseudocode or explicit conditional logic to block invalid state transitions (e.g., preventing item deletion after Quote Approval).
   - Write a software service class (Python or TypeScript) showcasing how a line item addition or deletion handles calculating financial line-item totals and variance warnings at the Proforma Invoice stage.

4. EDGE CASES TO IMPLEMENT:
   - What happens when a vendor fulfills only 80% of an RFQ? Show how partial quote acceptance behaves.
   - How does the database differentiate a user deleting an item from an item being rejected during the Quote Approval stage?

Deliver production-ready schema patterns and deeply commented service code.
```