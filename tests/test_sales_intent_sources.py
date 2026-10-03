"""Draft source checks use real reviewed policies and rollback-only synthetic data."""
from uuid import uuid4
import pytest
from pydantic import ValidationError
from Model.containermgmt.Inventory.Location import InventoryBranch
from Schema.SalesIntentSchema import SalesIntentInput
from Services.customer_identity_service import create_customer
from Services.inventory_posting_service import PostingConflict
from Services.sales_intent_source_service import prepare_sales_intent
from tests.test_customer_identity import profile
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


def payload(**changes):
    return dict(customer_key=uuid4(), expected_customer_version=1, branch_id=1,
        lines=[dict(line_key=uuid4(), product_id=1, expected_policy_version=1,
                    quantity='2', unit='BOX')]) | changes


@pytest.mark.parametrize('quantity', ['0', '-1', '1.0000001', '1e3', 1.5, True])
def test_quantity_requires_positive_exact_bounded_string(quantity):
    data = payload(); data['lines'][0]['quantity'] = quantity
    with pytest.raises(ValidationError): SalesIntentInput(**data)


def test_duplicate_line_and_financial_fields_rejected():
    data = payload(); data['lines'] *= 2
    with pytest.raises(ValidationError): SalesIntentInput(**data)
    data = payload(); data['lines'][0]['price'] = '100'
    with pytest.raises(ValidationError): SalesIntentInput(**data)


@pytest.fixture
def source(activation):
    f = activation
    assert f.client.post(f.activate_url, json=f.payload).status_code == 200
    f.db.get(InventoryBranch, f.own).kind = 'STORE'
    f.customer_key = uuid4()
    create_customer(f.db, f.context, f.user.id, f.customer_key, profile(),
                    expected_version=0, authorize=lambda db: None)
    f.db.commit()
    f.data = payload(customer_key=f.customer_key, branch_id=f.own)
    f.data['lines'][0]['product_id'] = f.product.id
    return f


def prepare(f):
    # A read establishes the caller transaction; preparation never owns commit.
    f.db.connection()
    return prepare_sales_intent(f.db, f.context, SalesIntentInput(**f.data),
                               authorize=lambda db: None)


def test_exact_conversion_without_stock_or_financial_effect(source):
    f = source; result = prepare(f)
    assert result['status'] == 'DRAFT'
    assert result['lines'][0]['base_quantity'] == '24'
    assert result['lines'][0]['base_unit'] == 'PCS'
    assert f.product.current_stock == 0
    assert not f.db.new and not f.db.dirty
    assert f.db.in_transaction()


@pytest.mark.parametrize('reference', ['customer', 'branch', 'product'])
def test_foreign_sources_denied_even_with_root_context(source, reference):
    from Utils.org_filter import OrgContext
    f = source
    f.context = OrgContext(current_org_id=f.org_a, allowed_org_ids=[f.org_a, f.org_b], is_root=True)
    if reference == 'branch': f.data['branch_id'] = f.foreign
    elif reference == 'product': f.data['lines'][0]['product_id'] = f.foreign_product.id
    else: f.data['customer_key'] = uuid4()
    with pytest.raises(LookupError): prepare(f)


def test_stale_policy_and_unknown_unit_fail(source):
    f = source; f.data['lines'][0]['expected_policy_version'] = 2
    with pytest.raises(PostingConflict): prepare(f)
    f.data['lines'][0]['expected_policy_version'] = 1
    f.data['lines'][0]['unit'] = 'UNREVIEWED'
    with pytest.raises(ValueError): prepare(f)


def test_permission_and_transaction_are_mandatory(source):
    f = source; data = SalesIntentInput(**f.data); f.db.commit()
    with pytest.raises(ValueError, match='caller-owned'):
        prepare_sales_intent(f.db, f.context, data, authorize=lambda db: None)
    f.db.connection()
    with pytest.raises(ValueError, match='permission guard'):
        prepare_sales_intent(f.db, f.context, data, authorize=None)
    def denied(db): raise PermissionError('denied')
    with pytest.raises(PermissionError):
        prepare_sales_intent(f.db, f.context, data, authorize=denied)
