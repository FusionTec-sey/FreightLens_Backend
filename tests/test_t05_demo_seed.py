from Model.Credentials.users import User
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Model.containermgmt.Inventory.UnitBarcode import UnitBarcodeRetirement
from Utils.seed_t05_demo import seed_demo
from tests.test_stock_ledger import stock  # noqa: F401


def test_demo_seed_is_atomic_scoped_and_repeatable(stock):
    f = stock
    with f.factory() as db:
        viewer = db.get(User, f.actor)
        original_ids = viewer.allowed_org_ids
        foreign = db.query(Product.id, Product.current_stock).filter(Product.org_id.in_(f.orgs)).all()
        org, created = seed_demo(db, [f.actor])
        assert created and org not in f.orgs
        assert db.query(Product).filter_by(org_id=org).count() == 10
        assert db.query(ManagerCase).filter_by(org_id=org).count() > 10
        assert db.query(UnitBarcodeRetirement).filter_by(org_id=org).count() == 1
        assert seed_demo(db, [f.actor]) == (org, False)
        assert db.query(Product).filter_by(org_id=org).count() == 10
        assert db.query(Product.id, Product.current_stock).filter(Product.org_id.in_(f.orgs)).all() == foreign
        assert set(viewer.allowed_org_ids) == set((original_ids or [f.orgs[0]]) + [org])
        db.rollback()
    with f.factory() as db:
        assert db.query(Product).filter_by(org_id=org).count() == 0
        assert db.get(User, f.actor).allowed_org_ids == original_ids
