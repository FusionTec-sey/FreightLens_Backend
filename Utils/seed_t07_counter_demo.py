"""Explicit LOCAL preview fixture: one enabled counter and its work area.

Never a startup migration or production seed. Without a counter and a configured
work area the T07 "Preview work area stock" and local-reservation paths cannot be
exercised at all, because no counter rows exist in any company.

Run only after owner approval:
    python -m Utils.seed_t07_counter_demo --confirm-demo-only --allow-shared-dev
"""
from uuid import uuid5
import argparse
import os

from sqlalchemy import text

from Model.db import engine, SessionLocal
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision
from Schema.BranchCounterSchema import CounterConfig
from Utils.seed_t06_sales_demo import CODE, NS, key


def seed_counter(db, *, allow_shared_dev=False):
    dedicated = db.bind.url.database in {"freightlens_pos_preview", "containermgmt_test"}
    approved_shared_dev = (
        allow_shared_dev
        and db.bind.url.database == "containermgmt_pg"
        and os.getenv("ENVIRONMENT", "").lower() == "development"
    )
    if not dedicated and not approved_shared_dev:
        raise ValueError("T07 counter fixture requires the dedicated local preview or isolated test database")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('freightlens-demo-t07-counter-v1', 0))"))
    demo = db.query(Organisation).filter_by(code=CODE).one_or_none()
    if demo is None:
        raise ValueError("Run Utils.seed_t06_sales_demo first; this fixture extends that demo company")
    actor = db.query(User).filter_by(org_id=demo.id, username="demo-t05-requestor", is_deleted=False).one_or_none()
    if actor is None:
        raise ValueError("The T05 demo actor is missing; reseed the T05 fixture")
    branch = db.query(InventoryBranch).filter_by(org_id=demo.id, code="DEMO-STORE", is_deleted=False).one()
    area = db.query(StockLocation).filter_by(org_id=demo.id, branch_id=branch.id, code="DEMO-SITE",
                                             is_active=True, is_deleted=False).one()

    counter_key = uuid5(NS, "freightlens-t07-demo-counter-v1")
    counter = db.query(BranchCounter).filter_by(org_id=demo.id, counter_key=counter_key,
                                                is_deleted=False).one_or_none()
    if counter is not None:
        return demo.id, counter.id, counter_key, False

    counter = BranchCounter(org_id=demo.id, branch_id=branch.id, counter_key=counter_key,
                            code="DEMO-TILL-1", created_by=actor.id)
    db.add(counter)
    db.flush()
    # Checkout counter bound to the demo stock area, so the preview resolves a
    # work area instead of refusing. Enabling a counter is not posting authority.
    config = CounterConfig(name="DEMO - Front till", purpose="BOTH", is_enabled=True,
                           default_stock_location_id=area.id)
    db.add(CounterSettingsRevision(org_id=demo.id, counter_id=counter.id, version=1,
                                   operation_key=key("counter:settings:v1"),
                                   config=config.model_dump(mode="json"), created_by=actor.id))
    db.flush()
    return demo.id, counter.id, counter_key, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-demo-only", action="store_true")
    parser.add_argument("--allow-shared-dev", action="store_true")
    args = parser.parse_args()
    dedicated_preview = engine.url.database == "freightlens_pos_preview" and engine.url.host in {"db", "postgres"}
    shared_development = (args.allow_shared_dev and engine.url.database == "containermgmt_pg"
        and engine.url.host in {"db", "postgres", "127.0.0.1", "localhost"}
        and os.getenv("ENVIRONMENT", "").lower() == "development")
    if not args.confirm_demo_only or not (dedicated_preview or shared_development):
        raise SystemExit("Refusing: explicit confirmation and local preview container database required")
    with SessionLocal.begin() as db:
        org_id, counter_id, counter_key, created = seed_counter(db, allow_shared_dev=args.allow_shared_dev)
    print(f"T07 counter fixture: org {org_id}, counter {counter_id} ({counter_key}); created={created}")


if __name__ == "__main__":
    main()
