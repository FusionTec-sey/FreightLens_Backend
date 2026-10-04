"""Explicit LOCAL preview fixture. Never a startup migration or production seed.

Run only after owner approval: python -m Utils.seed_t05_demo --confirm-demo-only
All business writes target a new synthetic company in one transaction. Existing
preview administrators gain only that demo-company assignment; roles unchanged.
"""
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import argparse
import os
import secrets
from sqlalchemy import text
from Model.db import engine, SessionLocal
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.CostPool import InventoryCostPool, BranchCostPool
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Model.containermgmt.Inventory.PostingAuthority import StoreNode, BranchAuthorityEpoch, CostPoolAuthorityEpoch
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Schema.UnitBarcodeSchema import UnitBarcodeCreate
from Schema.InventoryBatchSchema import StockBatchIdentity
from Schema.InventorySerialSchema import SerialOpening
from Services.manager_case_service import request_case, review_case
from Services.policy_case_binding_service import load_policy_case_binding
from Services.policy_activation_service import activate_initial_policy
from Services.unit_barcode_service import register_barcode
from Services.barcode_retirement_service import load_retirement_binding, retire_barcode
from Services.stock_ledger_service import open_untracked_stock, open_batch_stock, open_serial_stock, reserve_stock
from Services.inventory_valuation_service import record_opening_value
from Services.inventory_quantity_service import QuantityBreakdown
from Services.posting_authority_service import AuthorityClaim, CostPoolAuthorityClaim
from Utils.org_filter import OrgContext
from auth.security import hash_password

NAME = "DEMO ONLY - FreightLens T05"
CODE = "DEMO-T05-V1"


def seed_demo(db, viewer_ids, *, allow_shared_dev=False):
    dedicated_database = db.bind.url.database in {"freightlens_pos_preview", "containermgmt_test"}
    approved_shared_dev = (
        allow_shared_dev
        and db.bind.url.database == "containermgmt_pg"
        and os.getenv("ENVIRONMENT", "").lower() == "development"
    )
    if not dedicated_database and not approved_shared_dev:
        raise ValueError("T05 demo requires the dedicated local preview or isolated test database")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('freightlens-demo-t05-v1', 0))"))
    existing = db.query(Organisation).filter_by(name=NAME).one_or_none()
    if existing:
        if existing.code != CODE:
            raise ValueError("Demo name is occupied by an unrecognised organisation")
        return existing.id, False
    viewers = db.query(User).filter(User.id.in_(viewer_ids), User.is_deleted.is_(False)).all()
    if len(viewers) != len(set(viewer_ids)) or not viewers:
        raise ValueError("Explicit existing local preview viewers are required")
    demo = Organisation(name=NAME, display_name=NAME, code=CODE, parent_org_id=viewers[0].org_id,
        modules=["INVENTORY"], base_currency="SCR")
    db.add(demo); db.flush()
    actors = [User(username="demo-t05-" + role, password_hash=hash_password(secrets.token_urlsafe(32)),
                   org_id=demo.id, allowed_org_ids=[demo.id]) for role in ("requestor", "reviewer")]
    db.add_all(actors); db.flush()
    actor, reviewer = [row.id for row in actors]
    context = OrgContext(current_org_id=demo.id, allowed_org_ids=[demo.id], selected_org_id=demo.id, is_root=False)
    def authorize(session):
        if context.org_id != demo.id or demo.code != CODE:
            raise PermissionError("Demo writer scope mismatch")
    branch = InventoryBranch(org_id=demo.id, code="DEMO-STORE", name="DEMO - Training store", kind="STORE", created_by=actor)
    db.add(branch); db.flush()
    location = StockLocation(org_id=demo.id, branch_id=branch.id, code="DEMO-SITE", name="DEMO - Stock display", kind="SITE", created_by=actor)
    pool = InventoryCostPool(org_id=demo.id, code="DEMO-POOL", name="DEMO - Empty valuation pool", created_by=actor)
    db.add_all([location, pool]); db.flush()
    db.add(BranchCostPool(org_id=demo.id, branch_id=branch.id, cost_pool_id=pool.id, created_by=actor))
    node = StoreNode(org_id=demo.id, node_key=uuid4(), created_by=actor)
    db.add(node); db.flush()
    db.add(BranchAuthorityEpoch(org_id=demo.id, branch_id=branch.id, node_id=node.id, epoch=1,
        state="ACTIVE", reason="DEMO ONLY - synthetic local fixture", created_by=actor)); db.flush()
    db.add(CostPoolAuthorityEpoch(org_id=demo.id, cost_pool_id=pool.id, node_id=node.id, epoch=1, state="ACTIVE", reason="DEMO ONLY - synthetic local fixture", created_by=actor)); db.flush()
    claim = AuthorityClaim(demo.id, branch.id, node.node_key, 1)
    central_claim = CostPoolAuthorityClaim(demo.id, pool.id, node.node_key, 1)
    ordinary = InventoryPolicyConfig(base_unit="PCS", quantity_step="1", tracking="UNTRACKED")
    products = []
    def product(sku, label, policy=ordinary):
        row = Product(org_id=demo.id, sku="DEMO-" + sku, name="DEMO - " + label, unit=policy.base_unit,
            description="Synthetic T05 training record. Not real inventory. Do not use for trading.",
            current_stock=0, created_by=actor)
        db.add(row); db.flush(); products.append(row)
        return row
    def draft(row, policy, version=1):
        db.add(ProductPolicyDraft(org_id=demo.id, product_id=row.id, version=version,
            config=policy.model_dump(mode="json"), created_by=actor)); db.flush()
    def case(row, decision=None, activate=False):
        load = lambda session: load_policy_case_binding(session, context, row.id)
        binding = load(db); key = uuid4()
        request_case(db, context, actor, key, binding=binding, reason="DEMO ONLY - " + row.name,
            load_binding=load, authorize=authorize)
        if decision:
            review_case(db, context, reviewer, uuid4(), case_key=key, binding=binding, expected_version=1,
                outcome=decision, reason="DEMO ONLY - independent example review", load_binding=load, authorize=authorize)
        if activate:
            activate_initial_policy(db, context, actor, uuid4(), case_key=key, binding=binding,
                expected_active_version=binding.details.get("expected_active_version", 0), authorize=authorize)
        return key
    def barcode(row, code, unit, version=1):
        return register_barcode(db, context, actor, product_id=row.id,
            payload=UnitBarcodeCreate(operation_key=uuid4(), expected_policy_version=version, barcode=code, unit=unit),
            authorize=authorize).result["id"]
    def stock(row, policy):
        return open_untracked_stock(db, context, actor, uuid4(), branch_id=branch.id, location_id=location.id,
            product_id=row.id, base_unit=policy.base_unit, tracking_policy="UNTRACKED", policy=policy,
            quantities=QuantityBreakdown(Decimal("20"), damaged=Decimal("1"), quarantined=Decimal("1")),
            reason="DEMO ONLY - synthetic opening", authority=claim, authorize=authorize).result["balance_id"]
    def value(balance_id, goods_value, additional_cost):
        return record_opening_value(db, context, actor, uuid4(), balance_id=balance_id,
            expected_version=0, goods_value_scr=Decimal(goods_value), additional_cost_scr=Decimal(additional_cost),
            reason="DEMO ONLY - synthetic opening valuation", authority_claim=central_claim, authorize=authorize).result["valuation_id"]
    product("SETUP", "Not configured")
    row = product("DRAFT", "Saved policy draft"); draft(row, ordinary)
    for state in ("PENDING", "APPROVED", "REJECTED"):
        row = product(state, state.title() + " policy review"); draft(row, ordinary)
        case(row, None if state == "PENDING" else state)
    tile_policy = InventoryPolicyConfig(base_unit="M2", quantity_step="0.01", tracking="BATCH",
        require_shade=True, require_calibre=True, conversions=[{"unit": "BOX", "factor": "1.44"}])
    tile = product("TILE", "Batch tiles and barcode reviews", tile_policy); draft(tile, tile_policy); case(tile, "APPROVED", True)
    tile_balance = open_batch_stock(db, context, actor, uuid4(), branch_id=branch.id, location_id=location.id, product_id=tile.id,
        policy=tile_policy, batch=StockBatchIdentity(batch_key=uuid4(), code="DEMO-LOT-A", shade="DEMO-A", calibre="DEMO-60"),
        quantities=QuantityBreakdown(Decimal("28.80"), damaged=Decimal("1.44"), quarantined=Decimal("2.88")),
        reason="DEMO ONLY - synthetic tile opening", authority=claim, authorize=authorize).result["balance_id"]
    value(tile_balance, "4320", "350")
    barcode(tile, "DEMO-TILE-BOX", "BOX")
    for state in ("PENDING", "APPROVED", "RETIRED"):
        identity = barcode(tile, "DEMO-CODE-" + state, "BOX")
        load = lambda session, identity=identity: load_retirement_binding(session, context, identity)
        binding = load(db); key = uuid4()
        request_case(db, context, actor, key, binding=binding, reason="DEMO ONLY - label correction example",
            load_binding=load, authorize=authorize)
        if state != "PENDING":
            review_case(db, context, reviewer, uuid4(), case_key=key, binding=binding, expected_version=1,
                outcome="APPROVED", reason="DEMO ONLY - checked code", load_binding=load, authorize=authorize)
        if state == "RETIRED":
            retire_barcode(db, context, actor, uuid4(), case_key=key, binding=binding, authorize=authorize)
    serial_policy = InventoryPolicyConfig(base_unit="PCS", quantity_step="1", tracking="SERIAL")
    row = product("SERIAL", "Serial identities", serial_policy); draft(row, serial_policy); case(row, "APPROVED", True)
    serial_balance = open_serial_stock(db, context, actor, uuid4(), branch_id=branch.id, location_id=location.id, product_id=row.id,
        policy=serial_policy, serials=SerialOpening(items=[{"serial_key": uuid4(), "serial_number": "DEMO-SERIAL-" + str(i),
            "condition": condition} for i, condition in enumerate(("AVAILABLE", "DAMAGED", "QUARANTINED"), 1)]),
        reason="DEMO ONLY - synthetic serial opening", authority=claim, authorize=authorize).result["balance_id"]
    value(serial_balance, "3000", "150")
    for state in ("EXTENSION", "EXTENDED", "BLOCKED"):
        row = product(state, state.title() + " stock policy"); draft(row, ordinary); case(row, "APPROVED", True)
        balance = stock(row, ordinary); barcode(row, "DEMO-" + state + "-PCS", "PCS")
        value(balance, "1000", "75")
        reserve_stock(db, context, actor, uuid4(), balance_id=balance, reservation_key=uuid4(), source_line_key=uuid4(),
            quantity=Decimal("2"), review_at=datetime.now(timezone.utc) + timedelta(days=7),
            reason="DEMO ONLY - synthetic hold, not a sale", authority=claim, authorize=authorize)
        next_policy = InventoryPolicyConfig(base_unit="PCS", quantity_step="1", tracking="BATCH") if state == "BLOCKED" else (
            InventoryPolicyConfig(base_unit="PCS", quantity_step="1", tracking="UNTRACKED", conversions=[{"unit": "BOX", "factor": "2"}]))
        draft(row, next_policy, 2); case(row, "APPROVED", state == "EXTENDED")
    for viewer in viewers:
        viewer.allowed_org_ids = list(dict.fromkeys((viewer.allowed_org_ids if viewer.allowed_org_ids is not None else [viewer.org_id]) + [demo.id]))
    db.flush()
    return demo.id, True


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--confirm-demo-only", action="store_true")
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
        # Explicit existing development viewers; never modify credentials or roles.
        viewer_names = args.viewer or ["admin", "admin_sahaj"]
        viewers = db.query(User.id).filter(User.username.in_(viewer_names), User.org_id == 1).all()
        org_id, created = seed_demo(db, [row.id for row in viewers], allow_shared_dev=args.allow_shared_dev)
    from Services.search_service import sync_product_document
    with SessionLocal() as db:
        for row in db.query(Product).filter(Product.org_id == org_id, Product.is_deleted.is_(False)):
            sync_product_document(row)
    print(f"T05 demo company {org_id}; created={created}; synthetic records only")


if __name__ == "__main__":
    main()
