"""Import the order tracking workbook into purchase orders.

Reads "current order status.xlsx" as it is kept, rather than asking anyone to
reformat it: each sheet is one company, each row one order. Re-running updates
orders by their order number instead of duplicating them, so the sheet can be
corrected and the import repeated.

    python -m Utils.import_order_tracking <workbook.xlsx>              # dry run
    python -m Utils.import_order_tracking <workbook.xlsx> --commit     # write
    python -m Utils.import_order_tracking <workbook.xlsx> --months all # every row

Nothing is written without --commit.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.StoreRequest import StoreRequest
from Model.Credentials.Organisation import Organisation
from Model.db import SessionLocal

logger = logging.getLogger("containerMgmt.import_order_tracking")

DATE_PATTERN = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")

# Each sheet is one company. header_row is 1-based; columns are 0-based indexes
# into the row as the sheet is written, so a renamed heading does not matter but
# a reordered column would -- the headings are checked on load.
@dataclass(frozen=True)
class SheetSpec:
    sheet: str
    org_name: str
    sheet_type: str
    header_row: int
    columns: Dict[str, int]
    expect: Dict[int, str]


SHEETS = [
    SheetSpec(
        sheet="noble",
        org_name="noblecon",
        sheet_type="NOBLE",
        header_row=2,
        columns={
            "supplier": 0, "po_nce": 1, "po_number": 2, "goods": 3,
            "order_mail_date": 4, "quote_sent_date": 5, "quote_received_date": 6,
            "pi_confirmed_date": 7, "payment_date": 8, "balance_payment_date": 9,
            "remark": 10, "shipping_note": 11,
        },
        expect={0: "COMPANY", 2: "P.O NUMBER", 3: "GOODS", 10: "REMARK"},
    ),
    SheetSpec(
        sheet="sahajanand",
        org_name="sahajanand",
        sheet_type="SAHAJANAND",
        header_row=1,
        columns={
            "supplier": 0, "po_nce": 1, "po_number": 2, "goods": 3,
            "order_mail_date": 4, "quote_sent_date": 5, "quote_received_date": 6,
            "pi_confirmed_date": 7, "payment_date": 8, "follow_up": 9,
            "remark": 10, "urgent": 11,
        },
        expect={0: "COMPANY", 2: "ORDER NUMBER", 3: "GOODS", 10: "REMARK"},
    ),
]

# REMARK is doing the job of a status column. Longest phrases first, so
# "Balance Payment / Ready to Load" is not caught by "Advance Payment".
REMARK_STATUS = [
    ("under production", "IN_PRODUCTION"),
    ("ready for loading", "READY"),
    ("ready to load", "READY"),
    ("on port", "ARRIVED"),
    ("sea way", "SHIPPED"),
    ("received", "RECEIVED"),
    ("balance payment", "ORDERED"),
    ("full payment", "ORDERED"),
    ("advance payment", "ORDERED"),
    ("documents dhl", "SHIPPED"),
    ("pip", "IN_PRODUCTION"),
]

STATUS_LABELS = {
    "DRAFT": "Draft", "SUBMITTED": "Submitted", "SOURCING": "Sourcing",
    "ORDERED": "Ordered", "IN_PRODUCTION": "In Production", "READY": "Ready",
    "PACKED": "Packed", "SHIPPED": "Shipped", "ARRIVED": "Arrived",
    "RECEIVED": "Received", "COMPLETED": "Completed", "CANCELLED": "Cancelled",
}

# The noble sheet's second column is headed "P.O Number of N.C.E - Same as
# request number": it is the requisition number, so each row also belongs to a
# requisition, which is what Requisition & RFQs lists.
REQUISITION_STATUS = {
    "DRAFT": ("DRAFT", "Draft"),
    "SUBMITTED": ("SUBMITTED", "Submitted"),
    "SOURCING": ("SOURCING", "Sourcing"),
    "ORDERED": ("ORDERED", "Ordered"),
    "IN_PRODUCTION": ("ORDERED", "Ordered"),
    "READY": ("ORDERED", "Ordered"),
    "PACKED": ("ORDERED", "Ordered"),
    "SHIPPED": ("ORDERED", "Ordered"),
    "ARRIVED": ("ORDERED", "Ordered"),
    "RECEIVED": ("COMPLETED", "Completed"),
    "COMPLETED": ("COMPLETED", "Completed"),
    "CANCELLED": ("CANCELLED", "Cancelled"),
}

# The sheet's date columns are the RFQ-to-PO lifecycle, one column per stage:
#   ORDER MAIL FROM NCE -> CONFIRMED      SENT MAIL FOR QUOTE -> RFQ_SENT
#   RECEIVED QUOTE      -> QUOTE_RECEIVED CONFIRM-QUOTE/PI    -> QUOTE_APPROVED
#   payments            -> PO_ISSUED / PROFORMA
# so the stage is read off the dates rather than guessed from the status.
# Matches LIFECYCLE_SEQUENCE in Routes/Orders/LifecycleService.py.
PRE_AWARD_STAGES = ["DRAFT", "CONFIRMED", "RFQ_SENT", "QUOTE_RECEIVED"]

AFTER_AWARD = {"IN_PRODUCTION", "READY", "PACKED", "SHIPPED", "ARRIVED",
               "RECEIVED", "COMPLETED"}


def lifecycle_for(dates: Dict[str, Optional[date]], status: str) -> str:
    """The stage this order has actually reached, from the dates it carries."""
    if dates.get("payment_date") or dates.get("balance_payment_date") or status in AFTER_AWARD:
        # Paid for, or the goods are already moving: the PO exists.
        return "PROFORMA" if dates.get("balance_payment_date") or status in AFTER_AWARD else "PO_ISSUED"
    if dates.get("pi_confirmed_date"):
        return "QUOTE_APPROVED"
    if dates.get("quote_received_date"):
        return "QUOTE_RECEIVED"
    if dates.get("quote_sent_date"):
        return "RFQ_SENT"
    if dates.get("order_mail_date"):
        return "CONFIRMED"
    return "DRAFT"


PROGRESS = ["DRAFT", "SUBMITTED", "SOURCING", "ORDERED", "IN_PRODUCTION", "READY",
            "PACKED", "SHIPPED", "ARRIVED", "RECEIVED", "COMPLETED"]

DATE_FIELDS = (
    "order_mail_date", "quote_sent_date", "quote_received_date",
    "pi_confirmed_date", "payment_date", "balance_payment_date",
)


@dataclass
class Row:
    sheet: str
    row_number: int
    values: Dict[str, object]
    dates: Dict[str, Optional[date]] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)


def parse_date(value, where: str, problems: List[str]) -> Optional[date]:
    """Dates are kept as text in dd.mm.yyyy. Anything else is reported, never guessed."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    match = DATE_PATTERN.match(str(value))
    if not match:
        problems.append(f"{where}: {value!r} is not dd.mm.yyyy")
        return None
    day, month, year = (int(part) for part in match.groups())
    if not (2000 <= year <= 2035):
        problems.append(f"{where}: year {year} in {value!r} looks wrong")
        return None
    try:
        return date(year, month, day)
    except ValueError:
        problems.append(f"{where}: {value!r} is not a real date")
        return None


def status_for(remark: Optional[str], dates: Dict[str, Optional[date]]) -> tuple[str, str]:
    """Status from the remark, else from how far the dates have progressed."""
    text = (remark or "").strip().lower()
    for phrase, status in REMARK_STATUS:
        if phrase in text:
            return status, f"remark contains {phrase!r}"

    if dates.get("balance_payment_date") or dates.get("payment_date"):
        return "ORDERED", "a payment date is filled"
    if dates.get("pi_confirmed_date"):
        return "ORDERED", "the PI is confirmed"
    if dates.get("quote_received_date"):
        return "SOURCING", "a quote was received"
    if dates.get("quote_sent_date"):
        return "SOURCING", "a quote was requested"
    if dates.get("order_mail_date"):
        return "SUBMITTED", "the order was raised"
    return "DRAFT", "no remark and no dates"


def read_sheet(workbook, spec: SheetSpec) -> List[Row]:
    ws = workbook[spec.sheet]
    rows = list(ws.iter_rows(min_row=spec.header_row, values_only=True))
    header = rows[0]
    for index, expected in spec.expect.items():
        actual = str(header[index] or "").strip().upper().replace("\n", " ")
        if expected not in actual:
            raise SystemExit(
                f"{spec.sheet}: column {index} reads {actual!r}, expected {expected!r}. "
                "The sheet layout changed -- check the column order before importing."
            )

    parsed: List[Row] = []
    for offset, raw in enumerate(rows[1:], start=spec.header_row + 1):
        if not any(value not in (None, "") for value in raw):
            continue
        values = {}
        for name, index in spec.columns.items():
            value = raw[index] if index < len(raw) else None
            values[name] = value.strip() if isinstance(value, str) else value
        row = Row(sheet=spec.sheet, row_number=offset, values=values)
        for name in DATE_FIELDS:
            if name in spec.columns:
                row.dates[name] = parse_date(values.get(name), name, row.problems)
        if not values.get("po_number"):
            row.problems.append("no order number")
        parsed.append(row)
    return parsed


def latest_date(row: Row) -> Optional[date]:
    found = [value for value in row.dates.values() if value]
    return max(found) if found else None


def within_window(row: Row, cutoff: Optional[date]) -> bool:
    if cutoff is None:
        return True
    seen = latest_date(row)
    # A row with no usable date cannot be judged, so it is kept and reported.
    return seen is None or seen >= cutoff



def purge(db: Session, po_numbers: List[str], request_numbers: List[str]) -> Dict[str, int]:
    """Hard-delete exactly the rows this workbook owns, children first.

    Scoped to the numbers found in the file, so rows that came from anywhere
    else -- test fixtures, orders entered in the app -- are never touched.
    Cascades cover items, history, quotes, documents, payments and shipments;
    the three foreign keys that are NO ACTION or SET NULL are cleared by hand
    because they would otherwise block the delete.
    """
    removed: Dict[str, int] = {}
    if not po_numbers:
        return removed

    ids = [row[0] for row in db.execute(
        text("SELECT id FROM containermgmt.purchase_orders WHERE po_number = ANY(:nums)"),
        {"nums": po_numbers},
    )]
    if ids:
        # Self-reference and the quote pointer: cleared first to avoid a cycle.
        db.execute(text("UPDATE containermgmt.purchase_orders SET selected_quote_id = NULL, "
                        "parent_rfq_id = NULL WHERE id = ANY(:ids)"), {"ids": ids})
        db.execute(text("UPDATE containermgmt.purchase_orders SET parent_rfq_id = NULL "
                        "WHERE parent_rfq_id = ANY(:ids)"), {"ids": ids})
        db.execute(text("UPDATE containermgmt.vendor_quote_items SET last_purchase_po_id = NULL "
                        "WHERE last_purchase_po_id = ANY(:ids)"), {"ids": ids})
        # NO ACTION children would block the delete, so they go first.
        for table in ("defect_reports", "goods_receipts"):
            result = db.execute(
                text(f"DELETE FROM containermgmt.{table} WHERE po_id = ANY(:ids)"), {"ids": ids})
            if result.rowcount:
                removed[table] = result.rowcount
        result = db.execute(
            text("DELETE FROM containermgmt.purchase_orders WHERE id = ANY(:ids)"), {"ids": ids})
        removed["purchase_orders"] = result.rowcount

    if request_numbers:
        # Safe now: every order that pointed at these requisitions is gone.
        result = db.execute(
            text("DELETE FROM containermgmt.store_requests WHERE request_number = ANY(:nums)"),
            {"nums": request_numbers})
        removed["store_requests"] = result.rowcount
    return removed


def load_suppliers(db: Session) -> Dict[str, int]:
    from Model.containermgmt.Orders.Product import Product  # noqa: F401  (registers mappers)
    from sqlalchemy import text

    rows = db.execute(text(
        "SELECT supplier_id, name FROM containermgmt.supplier WHERE name IS NOT NULL"
    )).fetchall()
    return {str(name).strip().upper(): supplier_id for supplier_id, name in rows}


def org_ids(db: Session) -> Dict[str, int]:
    return {org.name: org.id for org in db.query(Organisation).all()}


def run(path: str, months: Optional[int], commit: bool, purge_first: bool = False,
        orders_only: bool = False) -> int:
    workbook = load_workbook(path, read_only=True, data_only=True)
    db: Session = SessionLocal()
    try:
        orgs = org_ids(db)
        suppliers = load_suppliers(db)

        all_rows: List[tuple[SheetSpec, Row]] = []
        for spec in SHEETS:
            if spec.sheet not in workbook.sheetnames:
                print(f"! sheet {spec.sheet!r} is not in this workbook, skipped")
                continue
            for row in read_sheet(workbook, spec):
                all_rows.append((spec, row))

        if purge_first:
            # Every number in the file, not just the selected window, so a row
            # that drops out of the window is removed rather than left stale.
            po_numbers = [str(row.values["po_number"]).strip()
                          for _, row in all_rows if row.values.get("po_number")]
            request_numbers = sorted({str(row.values["po_nce"]).strip()
                                      for _, row in all_rows if row.values.get("po_nce")})
            if commit:
                counts = purge(db, po_numbers, request_numbers)
                db.commit()
                print("PURGED (hard delete, scoped to this workbook's numbers)")
                for table, count in sorted(counts.items()):
                    print(f"  {count:4}  {table}")
                print()
            else:
                print(f"would purge {len(po_numbers)} orders and "
                      f"{len(request_numbers)} requisitions by number, then re-seed")
                print()

        cutoff = None
        if months is not None:
            newest = max((latest_date(row) for _, row in all_rows if latest_date(row)), default=None)
            if newest:
                year, month = newest.year, newest.month - months + 1
                while month <= 0:
                    month += 12
                    year -= 1
                cutoff = date(year, month, 1)

        selected = [(spec, row) for spec, row in all_rows if within_window(row, cutoff)]
        statuses = Counter()
        stages = Counter()
        unmatched_suppliers = Counter()
        matched_suppliers = 0
        requisitions: Dict[str, List[str]] = defaultdict(list)
        req_created = req_linked = 0
        problems: List[str] = []
        created = updated = skipped = 0
        undated = 0

        print(f"workbook: {path}")
        print(f"rows read: {len(all_rows)}   selected: {len(selected)}"
              + (f"   (dated on or after {cutoff})" if cutoff else "   (all rows)"))
        print()

        for spec, row in selected:
            if not row.values.get("po_number"):
                skipped += 1
                problems.append(f"{row.sheet} row {row.row_number}: no order number, skipped")
                continue

            po_number = str(row.values["po_number"]).strip()
            status, why = status_for(row.values.get("remark"), row.dates)
            stage = lifecycle_for(row.dates, status)
            stages[stage] += 1
            statuses[f"{status}  ({why})" if status == "DRAFT" else status] += 1

            supplier_name = (row.values.get("supplier") or "").strip()
            supplier_id = suppliers.get(supplier_name.upper()) if supplier_name else None
            if supplier_name and supplier_id is None:
                unmatched_suppliers[supplier_name] += 1
            elif supplier_id is not None:
                matched_suppliers += 1

            if latest_date(row) is None:
                undated += 1
            problems.extend(f"{row.sheet} row {row.row_number}: {p}" for p in row.problems)

            request_number = "" if orders_only else (row.values.get("po_nce") or "").strip()
            if request_number:
                requisitions[request_number].append(status)

            existing = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == po_number).first()
            if existing:
                updated += 1
            else:
                created += 1

            if not commit:
                continue

            org_id = orgs.get(spec.org_name, orgs.get("sahaj"))

            requisition = None
            if request_number:
                requisition = (db.query(StoreRequest)
                               .filter(StoreRequest.request_number == request_number).first())
                if requisition is None:
                    requisition = StoreRequest(request_number=request_number, org_id=org_id)
                    db.add(requisition)
                    db.flush()  # need the id to link the order
                    req_created += 1
                requisition.org_id = org_id
                requisition.title = (row.values.get("goods") or request_number)[:255]
                # The order-mail date is when the request reached the buyer.
                if row.dates.get("order_mail_date") and not requisition.submitted_at:
                    requisition.submitted_at = row.dates["order_mail_date"]
                # A requisition covering several orders takes the status of its
                # least advanced order, so it is not called complete too early.
                least = min(requisitions[request_number],
                            key=lambda value: PROGRESS.index(value) if value in PROGRESS else 0)
                requisition.status, requisition.status_label = REQUISITION_STATUS.get(
                    least, ("SUBMITTED", "Submitted"))
                req_linked += 1

            order = existing or PurchaseOrder(po_number=po_number)
            order.request_id = requisition.id if requisition else None
            order.org_id = org_id
            order.sheet_type = spec.sheet_type
            # Pre-award documents are RFQs and belong in Requisition & RFQs;
            # awarding one in the UI turns it into a PO. Same rule the API uses.
            order.lifecycle_stage = stage
            # orders_only keeps every row in the Orders list, where a pre-award
            # RFQ would otherwise be filtered out of it. The stage still records
            # how far the dates say the order actually got.
            order.doc_type = "PO" if orders_only else (
                "RFQ" if stage in PRE_AWARD_STAGES else "PO")
            order.po_nce = row.values.get("po_nce") or None
            order.company = supplier_name or None
            order.supplier_id = supplier_id
            order.goods_description = row.values.get("goods") or None
            order.status = status
            order.status_label = STATUS_LABELS.get(status, status.title())
            order.currency = order.currency or "USD"
            # Required with no database default; set explicitly for new rows.
            order.stage_version = order.stage_version or 1
            order.lifecycle_version = order.lifecycle_version or 1
            order.lifecycle_locked = bool(order.lifecycle_locked)
            order.urgent_action = bool(row.values.get("urgent"))
            for name in DATE_FIELDS:
                if name in spec.columns:
                    setattr(order, name, row.dates.get(name))
            seen = latest_date(row)
            order.year = seen.year if seen else None
            # Everything the sheet said that has no column of its own is kept
            # verbatim, so nothing is lost to the status mapping.
            notes = [str(row.values[key]) for key in ("remark", "shipping_note", "follow_up")
                     if row.values.get(key)]
            order.remark = " | ".join(notes) or None
            if existing is None:
                db.add(order)

        if commit:
            db.commit()

        print("LIFECYCLE STAGE  (from the date columns)")
        for name, count in stages.most_common():
            kind = "PO" if orders_only else ("RFQ" if name in PRE_AWARD_STAGES else "PO")
            print(f"  {count:4}  {name:<16} -> {kind}")
        print()
        print("STATUS")
        for name, count in statuses.most_common():
            print(f"  {count:4}  {name}")
        print()
        print(f"orders to create: {created}    to update: {updated}    skipped: {skipped}")
        if orders_only:
            print("requisitions: not seeded (--orders-only). The request number is kept on "
                  "every order, so the layer can be rebuilt without re-keying anything.")
        print(f"requisitions (from the request number column): {len(requisitions)} distinct"
              + (f", {req_created} created, {req_linked} orders linked" if commit else ""))
        shared = {} if orders_only else {k: v for k, v in requisitions.items() if len(v) > 1}
        if shared:
            print(f"  covering more than one order: {', '.join(sorted(shared))}")
        if not orders_only:
            print(f"orders with no request number: "
                  f"{len(selected) - sum(len(v) for v in requisitions.values())}")
        print(f"rows with no usable date: {undated}")
        print()

        print(f"suppliers matched to an existing record: {matched_suppliers}")
        print()

        if unmatched_suppliers:
            print(f"SUPPLIERS NOT MATCHED ({len(unmatched_suppliers)} names) "
                  "- kept as text on the order, no supplier record invented:")
            for name, count in unmatched_suppliers.most_common(15):
                print(f"  {count:3}  {name}")
            if len(unmatched_suppliers) > 15:
                print(f"  ... and {len(unmatched_suppliers) - 15} more")
            print()

        if problems:
            print(f"PROBLEMS ({len(problems)}):")
            for line in problems[:25]:
                print(f"  {line}")
            if len(problems) > 25:
                print(f"  ... and {len(problems) - 25} more")
            print()

        print("committed." if commit else "DRY RUN - nothing was written. Re-run with --commit.")
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook")
    parser.add_argument("--commit", action="store_true", help="write to the database")
    parser.add_argument("--orders-only", action="store_true",
                        help="seed purchase orders alone: no requisitions, and every row "
                             "stays a PO so it appears in the Orders list")
    parser.add_argument("--purge", action="store_true",
                        help="hard-delete this workbook's orders and requisitions first, "
                             "then re-seed from scratch")
    parser.add_argument("--months", default="4",
                        help="how many months back from the newest date, or 'all'")
    args = parser.parse_args()
    months = None if str(args.months).lower() == "all" else int(args.months)
    return run(args.workbook, months, args.commit, args.purge, args.orders_only)


if __name__ == "__main__":
    sys.exit(main())
