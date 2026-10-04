from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4
import pytest
from Model.containermgmt.Orders.GoodsReceipt import GoodsReceipt, ReceiptItem
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Inventory.Location import StockLocation
from Schema.InventoryReceiptSchema import InventoryReceiptSource
from Services.inventory_receipt_source_service import prepare_inventory_receipt_source
from Services.inventory_posting_service import PostingConflict
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def receipt(source):
    f = source
    po = PurchaseOrder(org_id=f.org_a, po_number='SYNTHETIC-' + uuid4().hex, doc_type='PO')
    f.db.add(po); f.db.flush()
    item = POItem(org_id=f.org_a, po_id=po.id, product_id=f.product.id,
        description='Synthetic', unit='BOX', quantity_ordered=Decimal('10'))
    gr = GoodsReceipt(org_id=f.org_a, po_id=po.id, receipt_number=uuid4().hex,
        received_date=date(2026, 10, 4), status='SUBMITTED', posting_version=1,
        submitted_at=datetime.now(timezone.utc))
    location = StockLocation(org_id=f.org_a, branch_id=f.own, code='RECEIVE', name='Synthetic receiving', kind='SITE')
    f.db.add_all([item, gr, location]); f.db.flush()
    line = ReceiptItem(receipt_id=gr.id, po_item_id=item.id, description='Synthetic',
        unit='BOX', received_quantity=Decimal('2'), damaged_quantity=Decimal('0'),
        incorrect_quantity=Decimal('0'), condition_ok=True)
    f.db.add(line); f.db.flush()
    f.receipt, f.receipt_line, f.po_item = gr, line, item
    f.receipt_source = InventoryReceiptSource(receipt_id=gr.id, receipt_item_id=line.id,
        branch_id=f.own, location_id=location.id, expected_policy_version=1)
    f.db.commit()
    return f


def prepare(f, **changes):
    f.db.connection()
    payload = InventoryReceiptSource(**(f.receipt_source.model_dump() | changes))
    return prepare_inventory_receipt_source(f.db, f.context, payload, authorize=lambda db: None)


def test_receipt_source_converts_exactly_without_mutation(receipt):
    f = receipt
    result = prepare(f)
    assert result['product_id'] == f.product.id
    assert result['base_quantities']['received_quantity'] == '24.000000'
    assert Decimal(result['base_quantities']['damaged_quantity']) == 0
    assert not result['physical_posting_enabled'] and not result['requires_condition_review']
    assert not f.db.new and not f.db.dirty
    assert f.db.in_transaction()
    assert f.product.current_stock == 0
    assert 'unit_price' not in result and 'supplier_id' not in result


@pytest.mark.parametrize('field,value', [('status', 'DRAFT'), ('posting_version', 0), ('submitted_at', None)])
def test_unsubmitted_or_legacy_receipt_blocked(receipt, field, value):
    setattr(receipt.receipt, field, value); receipt.db.commit()
    with pytest.raises(PostingConflict): prepare(receipt)


@pytest.mark.parametrize('field,value', [('unit', 'PCS'), ('product_id', None), ('item_status', 'USER_REMOVED')])
def test_ambiguous_po_line_blocked(receipt, field, value):
    setattr(receipt.po_item, field, value); receipt.db.commit()
    with pytest.raises(PostingConflict): prepare(receipt)


def test_stale_policy_wrong_line_location_and_company_blocked(receipt):
    f = receipt
    with pytest.raises(PostingConflict): prepare(f, expected_policy_version=2)
    with pytest.raises(LookupError): prepare(f, receipt_item_id=2147483647)
    with pytest.raises(LookupError): prepare(f, branch_id=f.foreign)
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]; f.context.is_root = True
    with pytest.raises(LookupError): prepare(f)


def test_discrepancies_are_preserved_not_subtracted_or_made_saleable(receipt):
    f = receipt
    f.receipt_line.damaged_quantity = Decimal('1')
    f.receipt_line.incorrect_quantity = Decimal('1')
    f.db.commit()
    result = prepare(f)
    assert result['requires_condition_review']
    assert Decimal(result['base_quantities']['received_quantity']) == 24
    assert Decimal(result['base_quantities']['damaged_quantity']) == 12
    assert Decimal(result['base_quantities']['incorrect_quantity']) == 12
    assert 'available_quantity' not in result
    f.receipt_line.damaged_quantity = Decimal('3'); f.db.commit()
    with pytest.raises(PostingConflict): prepare(f)


def test_permission_and_transaction_are_mandatory(receipt):
    f = receipt
    f.db.commit()
    with pytest.raises(ValueError):
        prepare_inventory_receipt_source(f.db, f.context, f.receipt_source, authorize=lambda db: None)
    f.db.connection()
    def denied(db): raise PermissionError('Denied')
    with pytest.raises(PermissionError):
        prepare_inventory_receipt_source(f.db, f.context, f.receipt_source, authorize=denied)
    with pytest.raises(ValueError):
        prepare_inventory_receipt_source(f.db, f.context, f.receipt_source, authorize=None)


@pytest.mark.parametrize('field,value', [('received_quantity', Decimal('0')), ('damaged_quantity', Decimal('-1')), ('incorrect_quantity', Decimal('-1'))])
def test_invalid_authoritative_quantities_fail_closed(receipt, field, value):
    setattr(receipt.receipt_line, field, value); receipt.db.commit()
    with pytest.raises(ValueError): prepare(receipt)


def test_foreign_po_item_cannot_be_used_through_own_receipt(receipt):
    f = receipt
    f.po_item.org_id = f.org_b; f.db.commit()
    with pytest.raises(PostingConflict): prepare(f)
