from uuid import uuid4
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Inventory.Location import StockLocation
from Services.policy_compatibility_service import extends_policy
from Services.manager_case_service import request_case, review_case
from Services.policy_activation_service import activate_initial_policy
from Services.inventory_posting_service import PostingConflict
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from tests.test_policy_activation_concurrency import reviewed  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401
from tests.test_unit_barcode_concurrency import registration


@pytest.fixture
def extension(reviewed):
    f = reviewed; f.activate()
    f.balance = f.open(policy=f.policy).result["balance_id"]
    registration(f)
    f.new_policy = InventoryPolicyConfig.model_validate({**f.policy.model_dump(mode="json"), "conversions": [{"unit": "BOX", "factor": "2"}]})
    with f.factory.begin() as db:
        db.add(ProductPolicyDraft(org_id=f.orgs[0], product_id=f.products[0], version=2,
            config=f.new_policy.model_dump(mode="json"), created_by=f.actor))
    with f.factory.begin() as db: f.extension_binding = f.load(db)
    f.extension_case = uuid4()
    request_case(f.factory, f.context, f.actor, f.extension_case, binding=f.extension_binding,
        reason="Add box sales", load_binding=f.load, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=f.extension_case,
        binding=f.extension_binding, expected_version=1, outcome="APPROVED", reason="Exact factor checked",
        load_binding=f.load, authorize=lambda db: None)
    f.extend = lambda key=None, factory=None: activate_initial_policy(factory or f.factory, f.context,
        f.actor, key or uuid4(), case_key=f.extension_case, binding=f.extension_binding,
        expected_active_version=1, authorize=lambda db: None)
    return f


def test_extension_preserves_stock_snapshot_and_supports_new_unit(extension):
    f = extension; key = uuid4()
    hold, source = uuid4(), uuid4()
    f.reserve(f.balance, reservation_key=hold, source_line_key=source, quantity=Decimal("1"))
    assert f.extension_binding.details["transition"] == "EXTEND_UNITS"
    assert f.extend(key).result["version"] == 2 and f.extend(key).replayed
    f.reserve(f.balance, quantity=Decimal("2"), input_unit="BOX")
    f.release(f.balance, hold, source, quantity=Decimal("0.5"), input_unit="BOX")
    with f.factory.begin() as db:
        balance = db.get(StockBalance, f.balance)
        assert balance.policy_config == f.policy.model_dump(mode="json")
        assert balance.on_hand == 10 and balance.reserved == 4
        place = StockLocation(org_id=f.orgs[0], branch_id=f.branches[0], code="SECOND", name="Second", kind="SITE")
        db.add(place); db.flush(); location = place.id
    assert f.open(policy=f.new_policy, location_id=location).result["on_hand"]


@pytest.mark.parametrize("same_key", [True, False])
def test_competing_extensions_have_one_effect(extension, same_key):
    f = extension; key = uuid4(); barrier = Barrier(2, timeout=10)
    def run(_):
        barrier.wait()
        try: return "replay" if f.extend(key if same_key else uuid4()).replayed else "posted"
        except PostingConflict: return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == sorted(["posted", "replay" if same_key else "conflict"])


def test_extension_rollback_keeps_old_policy_and_approval(extension):
    f = extension; key = uuid4()
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.extend(key, factory=db)
            raise RuntimeError("Synthetic failure")
    with pytest.raises(ValueError, match="not configured"):
        f.reserve(f.balance, input_unit="BOX", quantity=Decimal("1"))
    assert not f.extend(key).replayed


@pytest.mark.parametrize("change", [
    {"base_unit": "M2"}, {"quantity_step": "0.1"}, {"tracking": "SERIAL"},
    {"conversions": []}, {"conversions": [{"unit": "BOX", "factor": "3"}]},
    {"conversions": [{"unit": "box", "factor": "2"}]},
])
def test_extensions_never_reinterpret_existing_rules(change):
    original = {"base_unit": "PCS", "quantity_step": "1", "tracking": "UNTRACKED", "conversions": [{"unit": "BOX", "factor": "2"}]}
    assert not extends_policy(original, {**original, **change})


def test_decimal_equivalence_is_not_binary_float_comparison():
    original = {"base_unit": "M2", "quantity_step": "0.000001", "tracking": "UNTRACKED", "conversions": [{"unit": "BOX", "factor": "1.44000000"}]}
    assert extends_policy(original, {**original, "conversions": [{"unit": "BOX", "factor": "1.44"}, {"unit": "PALLET", "factor": "144"}]})
    assert not extends_policy(None, original)
    assert not extends_policy(original, {"base_unit": "M2"})
