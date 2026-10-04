from decimal import Decimal
from uuid import uuid4
import pytest
from Schema.InventoryReceiptSchema import InventoryReceiptManifest
from Services.inventory_receipt_manifest_service import prepare_inventory_receipt_manifest
from Services.stock_reclassification_service import validate_stock_manifest
from Services.inventory_quantity_service import QuantityBreakdown
from Schema.InventorySerialSchema import SerialOpening
from tests.test_inventory_receipt_source import receipt  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


def manifest(f, **changes):
    return InventoryReceiptManifest(**(dict(source=f.receipt_source,
        on_hand='24', damaged='0', quarantined='0', reason='Synthetic receipt classification',
        batches=[dict(identity=dict(batch_key=uuid4(), code='SYNTHETIC', shade='A', calibre='1'),
            on_hand='24', damaged='0', quarantined='0')]) | changes))


def prepare(f, payload):
    f.db.connection()
    return prepare_inventory_receipt_manifest(f.db, f.context, payload, authorize=lambda db: None)


def test_batch_manifest_conserves_source_and_has_no_posting_effect(receipt):
    result = prepare(receipt, manifest(receipt))
    assert result['quantities']['on_hand'] == '24.000000'
    assert result['quantities']['available'] == '24.000000'
    assert not result['physical_posting_enabled']
    assert not receipt.db.new and not receipt.db.dirty


@pytest.mark.parametrize('on_hand', ['23', '25'])
def test_manifest_rejects_under_or_over_receipt(receipt, on_hand):
    with pytest.raises(ValueError, match='conserve received quantity'):
        prepare(receipt, manifest(receipt, on_hand=on_hand))


def test_manifest_does_not_make_reported_damage_available(receipt):
    receipt.receipt_line.damaged_quantity = Decimal('1'); receipt.db.commit()
    with pytest.raises(ValueError, match='cannot become available'):
        prepare(receipt, manifest(receipt))
    payload = manifest(receipt).model_dump()
    payload['damaged'] = payload['batches'][0]['damaged'] = '12'
    result = prepare(receipt, InventoryReceiptManifest(**payload))
    assert result['condition_review_required']
    assert result['quantities']['available'] == '12.000000'


def test_manifest_rejects_inconsistent_batch_condition_totals(receipt):
    with pytest.raises(ValueError, match='conserve'):
        prepare(receipt, manifest(receipt, damaged='1'))


def test_manifest_rejects_duplicate_batch_identity(receipt):
    payload = manifest(receipt).model_dump()
    payload['batches'][0]['on_hand'] = '12'
    payload['batches'] = [payload['batches'][0], payload['batches'][0]]
    with pytest.raises(ValueError, match='unique'):
        prepare(receipt, InventoryReceiptManifest(**payload))


def test_shared_manifest_validator_supports_untracked_and_serial_without_conversion():
    policy = dict(base_unit='PCS', quantity_step='1', tracking='UNTRACKED', conversions=[])
    quantities = QuantityBreakdown(Decimal('2'), damaged=Decimal('1'))
    assert validate_stock_manifest(policy, quantities) == quantities
    serials = SerialOpening(items=[dict(serial_key=uuid4(), serial_number='SYN-A', condition='AVAILABLE'),
        dict(serial_key=uuid4(), serial_number='SYN-B', condition='DAMAGED')])
    with pytest.raises(ValueError): validate_stock_manifest(policy, quantities, serials=serials)
    policy['tracking'] = 'SERIAL'
    assert validate_stock_manifest(policy, quantities, serials=serials) == quantities
    with pytest.raises(ValueError):
        validate_stock_manifest(policy, QuantityBreakdown(Decimal('3')), serials=serials)
