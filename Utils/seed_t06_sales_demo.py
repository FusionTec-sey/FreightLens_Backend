"""Explicit LOCAL preview fixture for retail sales drafts and stock reservations.

Never a startup migration or production seed. Extends the existing T05 demo
company with the SALES module, synthetic retail customers, saved sales drafts,
source-linked stock holds and reservation review cases in mixed states.

Run only after owner approval:
    python -m Utils.seed_t06_sales_demo --confirm-demo-only --allow-shared-dev

All business writes target the existing synthetic demo company in one
transaction. No credential, role or real-company record is modified.
"""
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from uuid import UUID, uuid5
import argparse
import os

from sqlalchemy import text

from Model.db import engine, SessionLocal
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.PostingAuthority import StoreNode, BranchAuthorityEpoch
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Schema.CustomerSchema import CustomerIdentityInput
from Schema.SalesIntentSchema import SalesIntentInput
from Schema.SalesReservationSchema import SalesDemandReference
from Services.customer_identity_service import create_customer
from Services.sales_intent_service import save_sales_intent
from Services.stock_ledger_service import reserve_stock
from Services.manager_case_service import request_case, review_case
from Services.reservation_release_service import load_release_binding
from Services.reservation_deadline_service import load_deadline_binding
from Services.reservation_reallocation_service import load_reallocation_binding
from Services.posting_authority_service import AuthorityClaim
from Utils.org_filter import OrgContext

CODE = "DEMO-T05-V1"
NS = UUID("6f1b2c14-5d2a-4e71-9b61-9f0c4a2d7e01")
REASON = "DEMO ONLY - synthetic sales fixture, not a sale or payment"


def key(label):
    return uuid5(NS, "freightlens-t06-demo-v1:" + label)


def seed_sales_demo(db, *, allow_shared_dev=False):
    dedicated = db.bind.url.database in {"freightlens_pos_preview", "containermgmt_test"}
    approved_shared_dev = (
        allow_shared_dev
        and db.bind.url.database == "containermgmt_pg"
        and os.getenv("ENVIRONMENT", "").lower() == "development"
    )
    if not dedicated and not approved_shared_dev:
        raise ValueError("T06 sales demo requires the dedicated local preview or isolated test database")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('freightlens-demo-t06-v1', 0))"))
    demo = db.query(Organisation).filter_by(code=CODE).one_or_none()
    if demo is None:
        raise ValueError("Run Utils.seed_t05_demo first; the T06 fixture extends that demo company")
    if db.query(RetailCustomer).filter_by(org_id=demo.id).first() is not None:
        return demo.id, False, []

    actors = {row.username: row.id for row in db.query(User).filter(
        User.org_id == demo.id, User.username.in_(("demo-t05-requestor", "demo-t05-reviewer")),
        User.is_deleted.is_(False)).all()}
    if len(actors) != 2:
        raise ValueError("The T05 demo actors are missing; reseed the T05 fixture")
    actor, reviewer = actors["demo-t05-requestor"], actors["demo-t05-reviewer"]

    context = OrgContext(current_org_id=demo.id, allowed_org_ids=[demo.id],
                         selected_org_id=demo.id, is_root=False)

    def authorize(session):
        if context.org_id != demo.id or demo.code != CODE:
            raise PermissionError("Demo writer scope mismatch")

    # The sales draft, customer and reservation review surfaces all gate on the
    # SALES module; the demo company only carried INVENTORY from the T05 fixture.
    if "SALES" not in (demo.modules or []):
        demo.modules = list(dict.fromkeys(list(demo.modules or []) + ["SALES"]))

    branch = db.query(InventoryBranch).filter_by(org_id=demo.id, code="DEMO-STORE",
                                                 is_deleted=False).one()
    epoch = db.query(BranchAuthorityEpoch).filter_by(org_id=demo.id, branch_id=branch.id,
                                                     state="ACTIVE", is_deleted=False).one()
    node = db.query(StoreNode).filter_by(org_id=demo.id, id=epoch.node_id).one()
    claim = AuthorityClaim(demo.id, branch.id, node.node_key, epoch.epoch)

    products = {row.sku: row.id for row in db.query(Product).filter(
        Product.org_id == demo.id, Product.is_deleted.is_(False)).all()}
    policy_version = {}
    for row in db.query(ProductPolicyActivation).filter(
            ProductPolicyActivation.org_id == demo.id,
            ProductPolicyActivation.is_deleted.is_(False)).all():
        policy_version[row.product_id] = max(policy_version.get(row.product_id, 0), row.version)
    balances = {row.product_id: row.id for row in db.query(StockBalance).filter(
        StockBalance.org_id == demo.id, StockBalance.branch_id == branch.id,
        StockBalance.is_deleted.is_(False)).all()}

    def product(sku):
        identity = products["DEMO-" + sku]
        return identity, policy_version[identity]

    def customer(label, name, kind, contacts):
        profile = CustomerIdentityInput(name=name, kind=kind, contacts=contacts)
        return UUID(create_customer(db, context, actor, key(label), profile,
                                    expected_version=0, authorize=authorize).result["customer_key"])

    def draft(label, customer_key, lines, *, expected_version=0):
        payload = SalesIntentInput(customer_key=customer_key, expected_customer_version=1,
                                   branch_id=branch.id, lines=lines)
        document_key = key(label)
        result = save_sales_intent(db, context, actor, key(label + ":save:v" + str(expected_version + 1)),
                                   document_key, payload, expected_version=expected_version,
                                   authorize=authorize).result
        return document_key, result["version"]

    def line(label, sku, quantity, unit):
        identity, version = product(sku)
        return dict(line_key=key(label), product_id=identity, expected_policy_version=version,
                    quantity=quantity, unit=unit)

    def hold(label, document_key, version, line_key, sku, quantity, unit, review_at):
        """One source-linked reservation; a hold is demand evidence, never a sale."""
        identity, _ = product(sku)
        source = SalesDemandReference(document_key=document_key, line_key=line_key, version=version)
        reservation_key = key(label)
        reserve_stock(db, context, actor, key(label + ":post"), balance_id=balances[identity],
                      reservation_key=reservation_key, source_line_key=source.stock_source_key(),
                      quantity=Decimal(quantity), review_at=review_at, reason=REASON, input_unit=unit,
                      business_date=date.today(), authority=claim, authorize=authorize, sales_source=source)
        return reservation_key, source

    def release_case(label, reservation_key, quantity, *, outcome=None):
        load = lambda session: load_release_binding(session, context, reservation_key, Decimal(quantity))
        binding = load(db)
        case_key = key(label)
        request_case(db, context, actor, case_key, binding=binding,
                     reason=REASON + " - release review example", load_binding=load, authorize=authorize)
        if outcome:
            review_case(db, context, reviewer, key(label + ":review"), case_key=case_key, binding=binding,
                        expected_version=1, outcome=outcome, reason=REASON + " - independent review",
                        load_binding=load, authorize=authorize)
        return case_key

    def deadline_case(label, reservation_key, next_review_at, *, outcome=None):
        load = lambda session: load_deadline_binding(session, context, reservation_key, next_review_at)
        binding = load(db)
        case_key = key(label)
        request_case(db, context, actor, case_key, binding=binding,
                     reason=REASON + " - follow-up date review example", load_binding=load, authorize=authorize)
        if outcome:
            review_case(db, context, reviewer, key(label + ":review"), case_key=case_key, binding=binding,
                        expected_version=1, outcome=outcome, reason=REASON + " - independent review",
                        load_binding=load, authorize=authorize)
        return case_key

    def reallocation_case(label, reservation_key, target, quantity, review_at, *, outcome=None):
        load = lambda session: load_reallocation_binding(session, context, reservation_key, target,
                                                         Decimal(quantity), review_at)
        binding = load(db)
        case_key = key(label)
        request_case(db, context, actor, case_key, binding=binding,
                     reason=REASON + " - reallocation review example", load_binding=load, authorize=authorize)
        if outcome:
            review_case(db, context, reviewer, key(label + ":review"), case_key=case_key, binding=binding,
                        expected_version=1, outcome=outcome, reason=REASON + " - independent review",
                        load_binding=load, authorize=authorize)
        return case_key

    now = datetime.now(timezone.utc)
    walkin = customer("customer:walkin", "DEMO - Walk-in buyer", "PERSON",
                      [dict(kind="PHONE", value="+248 2 510 101", label="Mobile", primary=True)])
    builders = customer("customer:builders", "DEMO - Island Builders Ltd", "BUSINESS",
                        [dict(kind="EMAIL", value="orders@demo-island-builders.example",
                              label="Orders", primary=True),
                         dict(kind="PHONE", value="+248 4 321 000", label="Office")])
    tiler = customer("customer:tiler", "DEMO - Repeat tiler", "PERSON",
                     [dict(kind="PHONE", value="+248 2 777 414", label="Mobile", primary=True)])

    notes = []

    # 1. Clean single-line draft with no holds: freely editable end to end.
    clean, version = draft("draft:clean", walkin, [line("draft:clean:line:1", "EXTENSION", "5", "PCS")])
    notes.append(f"draft clean {clean} v{version} - editable, no holds")

    # 2. Multi-line draft saved twice: revision 2 drops the serial line, so the
    #    read endpoint shows history while the held line stays protected.
    mixed_lines = [line("draft:mixed:line:1", "EXTENDED", "10", "PCS"),
                   line("draft:mixed:line:2", "TILE", "2", "BOX"),
                   line("draft:mixed:line:3", "SERIAL", "1", "PCS")]
    mixed, version = draft("draft:mixed", builders, mixed_lines)
    mixed, version = draft("draft:mixed", builders, mixed_lines[:2], expected_version=version)
    notes.append(f"draft mixed {mixed} v{version} - two revisions, unit conversion on BOX line")

    # 3. Held draft: quantity cannot fall below its active hold without a review.
    held, held_version = draft("draft:held", tiler, [line("draft:held:line:1", "TILE", "5", "M2")])
    held_hold, _ = hold("hold:held", held, held_version, key("draft:held:line:1"), "TILE",
                        "3", "M2", now + timedelta(days=5))
    notes.append(f"draft held {held} v{held_version} - 3 M2 held, pending release review")

    # 4. Overdue hold: appears in the due follow-up inbox.
    overdue, overdue_version = draft("draft:overdue", builders,
                                     [line("draft:overdue:line:1", "BLOCKED", "4", "PCS")])
    overdue_hold, _ = hold("hold:overdue", overdue, overdue_version, key("draft:overdue:line:1"),
                           "BLOCKED", "4", "PCS", now - timedelta(days=2))
    notes.append(f"draft overdue {overdue} v{overdue_version} - hold review date already past")

    # 5. Reallocation source and destination on the same product, store and bucket.
    target_doc, target_version = draft("draft:target", walkin,
                                       [line("draft:target:line:1", "EXTENDED", "6", "PCS")])
    source_hold, _ = hold("hold:mixed", mixed, version, key("draft:mixed:line:1"), "EXTENDED",
                          "6", "PCS", now + timedelta(days=10))
    target = SalesDemandReference(document_key=target_doc, line_key=key("draft:target:line:1"),
                                  version=target_version)
    notes.append(f"draft reallocation target {target_doc} v{target_version}")

    # 6. Second tile hold used by the approved follow-up date case.
    tile_hold, _ = hold("hold:mixed:tile", mixed, version, key("draft:mixed:line:2"), "TILE",
                        "2", "M2", now + timedelta(days=7))

    # 7. Draft with an approved release, ready for the reviewed release apply path.
    approved, approved_version = draft("draft:approved", tiler,
                                       [line("draft:approved:line:1", "EXTENSION", "8", "PCS")])
    approved_hold, _ = hold("hold:approved", approved, approved_version,
                            key("draft:approved:line:1"), "EXTENSION", "8", "PCS", now + timedelta(days=3))
    notes.append(f"draft approved-release {approved} v{approved_version} - 3 PCS release approved, unused")

    release_case("case:release:pending", held_hold, "1")
    release_case("case:release:approved", approved_hold, "3", outcome="APPROVED")
    deadline_case("case:deadline:pending", overdue_hold, now + timedelta(days=14))
    deadline_case("case:deadline:approved", tile_hold, now + timedelta(days=21), outcome="APPROVED")
    reallocation_case("case:reallocation:pending", source_hold, target, "2", now + timedelta(days=10))
    notes.append("cases: release pending/approved, deadline pending/approved, reallocation pending")
    return demo.id, True, notes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-demo-only", action="store_true")
    parser.add_argument("--allow-shared-dev", action="store_true")
    parser.add_argument("--viewer", action="append", default=[])
    args = parser.parse_args()
    dedicated_preview = engine.url.database == "freightlens_pos_preview" and engine.url.host in {"db", "postgres"}
    shared_development = (args.allow_shared_dev and engine.url.database == "containermgmt_pg"
        and engine.url.host in {"db", "postgres", "127.0.0.1", "localhost"}
        and os.getenv("ENVIRONMENT", "").lower() == "development")
    if not args.confirm_demo_only or not (dedicated_preview or shared_development):
        raise SystemExit("Refusing: explicit confirmation and local preview container database required")
    with SessionLocal.begin() as db:
        org_id, created, notes = seed_sales_demo(db, allow_shared_dev=args.allow_shared_dev)
        if created and args.viewer:
            viewers = db.query(User).filter(User.username.in_(args.viewer), User.is_deleted.is_(False)).all()
            for viewer in viewers:
                allowed = viewer.allowed_org_ids if viewer.allowed_org_ids is not None else [viewer.org_id]
                viewer.allowed_org_ids = list(dict.fromkeys(list(allowed) + [org_id]))
    # Projection failures never change committed receipts; retries repair indexing.
    if created:
        from Services.search_service import sync_customer_document
        with SessionLocal() as db:
            for row in db.query(RetailCustomer).filter(RetailCustomer.org_id == org_id,
                                                        RetailCustomer.is_deleted.is_(False)):
                sync_customer_document(row.customer_key, org_id, row.initial_profile)
    print(f"T06 sales demo company {org_id}; created={created}; synthetic records only")
    for note in notes:
        print("  " + note)


if __name__ == "__main__":
    main()

