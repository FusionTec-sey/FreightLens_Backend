"""Reviewed opening/import composition over the existing stock and value writers."""
from decimal import Decimal
from uuid import UUID, uuid5

from Model.containermgmt.Inventory.CostPool import BranchCostPool, InventoryCostPool
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseUse
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.Product import Product
from Schema.InventoryOpeningSchema import InventoryOpeningInput
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.inventory_costing_service import CostBalance, CostPool, receive
from Services.inventory_posting_service import (
    PostingConflict, PostingOutcome, lock_operation_attempt)
from Services.inventory_quantity_service import QuantityBreakdown
from Services.inventory_unit_service import convert_quantity
from Services.inventory_valuation_service import record_opening_value
from Services.manager_case_service import CaseBinding, consume_case
from Services.policy_activation_service import active_policy
from Services.stock_ledger_service import (
    open_batch_stock, open_serial_stock, open_untracked_stock)
from Utils.org_filter import apply_org_filter


ACTION = 'inventory.stock.open'
SOURCE_TYPE = 'inventory.opening-import'


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id,
        model.is_deleted.is_(False)), model, context)


def opening_value_operation(operation_key):
    if not isinstance(operation_key, UUID) or not operation_key.int:
        raise ValueError('Stable nonzero opening operation identity required')
    return uuid5(operation_key, 'freightlens.inventory.opening-value.v1')


def _quantities(policy, payload):
    quantities = QuantityBreakdown(Decimal(payload.on_hand),
        damaged=Decimal(payload.damaged),
        quarantined=Decimal(payload.quarantined))
    for value in (quantities.on_hand, quantities.damaged,
            quantities.quarantined):
        convert_quantity(policy, value, policy.base_unit, allow_zero=True)
    if quantities.on_hand <= 0:
        raise ValueError('Opening quantity must be positive')
    if policy.tracking == 'UNTRACKED':
        if payload.batch is not None or payload.serials is not None:
            raise ValueError('Untracked opening cannot carry batch or serial identities')
    elif policy.tracking == 'BATCH':
        if payload.batch is None or payload.serials is not None:
            raise ValueError('Batch opening requires exactly one batch identity')
        for flag, field in (('require_expiry', 'expires_on'),
                ('require_shade', 'shade'), ('require_calibre', 'calibre')):
            if getattr(policy, flag) and getattr(payload.batch, field) is None:
                raise ValueError(f'Batch {field} is required by the active policy')
    elif policy.tracking == 'SERIAL':
        if payload.serials is None or payload.batch is not None:
            raise ValueError('Serial opening requires exact serial identities')
        serial_on_hand = Decimal(len(payload.serials.items))
        serial_damaged = Decimal(sum(
            row.condition == 'DAMAGED' for row in payload.serials.items))
        serial_quarantined = Decimal(sum(
            row.condition == 'QUARANTINED' for row in payload.serials.items))
        if (quantities.on_hand != serial_on_hand
                or quantities.damaged != serial_damaged
                or quantities.quarantined != serial_quarantined):
            raise ValueError('Serial identities must exactly match opening conditions')
    else:
        raise ValueError('Unsupported opening tracking policy')
    return quantities


def opening_binding(db, context, payload, *, lock=True):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Opening/import company denied')
    if not isinstance(payload, InventoryOpeningInput):
        raise ValueError('Typed opening/import intent required')
    branch = _owned(db, InventoryBranch, context).filter_by(
        id=payload.branch_id, is_active=True).one_or_none()
    location_query = _owned(db, StockLocation, context).filter_by(
        id=payload.location_id, branch_id=payload.branch_id, is_active=True)
    product_query = _owned(db, Product, context).filter_by(
        id=payload.product_id, status='active', is_shared=False)
    if lock:
        location_query = location_query.with_for_update()
        product_query = product_query.with_for_update(of=Product)
    location = location_query.one_or_none()
    product = product_query.one_or_none()
    if branch is None or location is None or product is None:
        raise LookupError('Active opening stock scope not found')
    policy_row = active_policy(db, context, product.id)
    if policy_row is None or policy_row.version != payload.expected_policy_version:
        raise PostingConflict('Reviewed product policy changed; refresh the opening')
    policy = InventoryPolicyConfig.model_validate(policy_row.config)
    if policy.base_unit != product.unit:
        raise PostingConflict('Active opening policy unit differs from the product')
    quantities = _quantities(policy, payload)
    batch_key = payload.batch.batch_key if payload.batch else None
    existing = _owned(db, StockBalance, context).filter_by(
        location_id=location.id, product_id=product.id,
        batch_key=batch_key).one_or_none()
    if existing is not None:
        raise PostingConflict('Opening target stock bucket already exists')
    mapping = _owned(db, BranchCostPool, context).join(InventoryCostPool,
        (InventoryCostPool.id == BranchCostPool.cost_pool_id)
        & (InventoryCostPool.org_id == BranchCostPool.org_id)).filter(
            BranchCostPool.branch_id == branch.id,
            InventoryCostPool.is_active.is_(True),
            InventoryCostPool.is_deleted.is_(False)).one_or_none()
    if mapping is None:
        raise ValueError('An active exact branch cost-pool mapping is required')
    latest = _owned(db, InventoryValuation, context).filter_by(
        cost_pool_id=mapping.cost_pool_id,
        product_id=product.id).order_by(
            InventoryValuation.version.desc()).first()
    version = latest.version if latest else 0
    if version != payload.expected_valuation_version:
        raise PostingConflict('Valuation version changed; refresh the opening')
    if latest is not None and latest.base_unit != policy.base_unit:
        raise PostingConflict('Valuation base unit differs from the opening')
    goods = Decimal(payload.goods_value_scr)
    additional = Decimal(payload.additional_cost_scr)
    receive(CostBalance(CostPool(context.org_id, mapping.cost_pool_id,
        product.id), Decimal(0), Decimal(0)), quantities.on_hand,
        goods, additional)
    return CaseBinding(org_id=context.org_id, action=ACTION,
        source_type=SOURCE_TYPE, source_key=str(payload.source_key),
        source_version=1, details={
            'source_key': str(payload.source_key),
            'branch_id': branch.id, 'location_id': location.id,
            'product_id': product.id, 'product_name': product.name,
            'base_unit': policy.base_unit,
            'tracking_policy': policy.tracking,
            'expected_policy_version': policy_row.version,
            'policy': policy.model_dump(mode='json'),
            'expected_valuation_version': version,
            'cost_pool_id': mapping.cost_pool_id,
            'on_hand': format(quantities.on_hand, '.6f'),
            'damaged': format(quantities.damaged, '.6f'),
            'quarantined': format(quantities.quarantined, '.6f'),
            'goods_value_scr': format(goods, '.6f'),
            'additional_cost_scr': format(additional, '.6f'),
            'reason': payload.reason,
            'batch': payload.batch.model_dump(mode='json')
                if payload.batch else None,
            'serials': payload.serials.model_dump(mode='json')
                if payload.serials else None,
        })


def _input_from_binding(binding):
    details = binding.details
    return InventoryOpeningInput(**{name: details[name] for name in (
        'source_key', 'branch_id', 'location_id', 'product_id',
        'expected_policy_version', 'expected_valuation_version', 'on_hand',
        'damaged', 'quarantined', 'goods_value_scr', 'additional_cost_scr',
        'reason', 'batch', 'serials')})


def reload_opening_binding(db, context, binding, *, replay_operation=None):
    if replay_operation is not None:
        value_key = opening_value_operation(replay_operation)
        use = _owned(db, ManagerCaseUse, context).join(ManagerCase,
            (ManagerCase.id == ManagerCaseUse.case_id)
            & (ManagerCase.org_id == ManagerCaseUse.org_id)).filter(
                ManagerCaseUse.operation_key == replay_operation,
                ManagerCase.binding == binding.snapshot()).one_or_none()
        movement = _owned(db, StockMovement, context).join(StockBalance,
            (StockBalance.id == StockMovement.balance_id)
            & (StockBalance.org_id == StockMovement.org_id)).filter(
                StockMovement.operation_key == replay_operation,
                StockMovement.kind == 'OPENING',
                StockBalance.branch_id == binding.details['branch_id'],
                StockBalance.location_id == binding.details['location_id'],
                StockBalance.product_id == binding.details['product_id']).with_entities(
                    StockMovement, StockBalance).one_or_none()
        valuation = _owned(db, InventoryValuation, context).filter_by(
            operation_key=value_key, kind='OPENING').one_or_none()
        if use is not None and movement is not None and valuation is not None:
            stock, balance = movement
            details = binding.details
            if (valuation.balance_id == balance.id
                    and valuation.source_version == stock.version == 1
                    and valuation.cost_pool_id == details['cost_pool_id']
                    and valuation.version == details['expected_valuation_version'] + 1
                    and format(stock.on_hand, '.6f') == details['on_hand']
                    and format(stock.damaged, '.6f') == details['damaged']
                    and format(stock.quarantined, '.6f') == details['quarantined']
                    and format(valuation.goods_value_scr, '.6f') == details['goods_value_scr']
                    and format(valuation.additional_cost_scr, '.6f') == details['additional_cost_scr']):
                return binding
    return opening_binding(db, context, _input_from_binding(binding), lock=True)


def execute_reviewed_opening(db, context, actor_id, operation_key, *, case_key,
        binding, stock_authority, cost_authority, authorize_stock,
        authorize_cost):
    if not db.in_transaction():
        raise ValueError('Opening execution requires an active transaction')
    if not isinstance(binding, CaseBinding) or binding.action != ACTION \
            or binding.source_type != SOURCE_TYPE:
        raise ValueError('Exact reviewed opening/import binding required')
    try:
        # Serialize before checking replay/source state. Otherwise a same-key
        # retry can observe no receipt, wait behind the first product lock, and
        # then misreport the newly committed bucket as a conflicting opening.
        lock_operation_attempt(db, context, operation_key)
        current = reload_opening_binding(db, context, binding,
            replay_operation=operation_key)
        if current.snapshot() != binding.snapshot():
            raise PostingConflict('Reviewed opening/import source changed')
        details = binding.details
        policy = InventoryPolicyConfig.model_validate(details['policy'])
        quantities = QuantityBreakdown(Decimal(details['on_hand']),
            damaged=Decimal(details['damaged']),
            quarantined=Decimal(details['quarantined']))
        use = _owned(db, ManagerCaseUse, context).join(ManagerCase,
            (ManagerCase.id == ManagerCaseUse.case_id)
            & (ManagerCase.org_id == ManagerCaseUse.org_id)).filter(
                ManagerCase.case_key == case_key,
                ManagerCaseUse.operation_key == operation_key).one_or_none()
        existing_movement = _owned(db, StockMovement, context).filter_by(
            operation_key=operation_key, kind='OPENING').first()
        if existing_movement is not None and use is None:
            raise PostingConflict(
                'Opening operation belongs to another reviewed case')
        if existing_movement is None and use is not None:
            raise PostingConflict('Opening approval use has no matching movement')
        if use is None:
            consume_case(db, context, actor_id, operation_key,
                case_key=case_key, binding=binding,
                load_binding=lambda session: reload_opening_binding(
                    session, context, binding), authorize=authorize_stock)
        common = dict(branch_id=details['branch_id'],
            location_id=details['location_id'], product_id=details['product_id'],
            reason=details['reason'], policy=policy,
            authorize=authorize_stock, authority=stock_authority)
        if policy.tracking == 'BATCH':
            from Schema.InventoryBatchSchema import StockBatchIdentity
            opened = open_batch_stock(db, context, actor_id, operation_key,
                batch=StockBatchIdentity.model_validate(details['batch']),
                quantities=quantities, **common)
        elif policy.tracking == 'SERIAL':
            from Schema.InventorySerialSchema import SerialOpening
            opened = open_serial_stock(db, context, actor_id, operation_key,
                serials=SerialOpening.model_validate(details['serials']), **common)
        else:
            opened = open_untracked_stock(db, context, actor_id, operation_key,
                base_unit=details['base_unit'], tracking_policy='UNTRACKED',
                quantities=quantities, **common)
        valued = record_opening_value(db, context, actor_id,
            opening_value_operation(operation_key),
            balance_id=opened.result['balance_id'],
            expected_version=details['expected_valuation_version'],
            goods_value_scr=Decimal(details['goods_value_scr']),
            additional_cost_scr=Decimal(details['additional_cost_scr']),
            reason=details['reason'], authority_claim=cost_authority,
            authorize=authorize_cost)
        result = {
            'status': 'POSTED_UNRECONCILED',
            'balance_id': opened.result['balance_id'],
            'balance_version': opened.result['version'],
            'valuation_id': valued.result['valuation_id'],
            'valuation_version': valued.result['version'],
            'cost_pool_id': valued.result['cost_pool_id'],
            'product_id': valued.result['product_id'],
            'on_hand': opened.result['on_hand'],
            'available': opened.result['available'],
            'damaged': opened.result['damaged'],
            'quarantined': opened.result['quarantined'],
            'pool_quantity': valued.result['pool_quantity'],
            'pool_value_scr': valued.result['pool_value_scr'],
            'average_cost_scr': valued.result['average_cost_scr'],
        }
        return PostingOutcome(operation_key, result,
            opened.replayed and valued.replayed)
    except BaseException:
        db.rollback()
        raise
