"""Version-pinned, atomic receipt coordinator; deliberately no HTTP adapter."""
from decimal import Decimal
from uuid import UUID
from Services.document_evidence_preparation_service import (
    PreparedDocumentContent, prepare_document_content)
from Services.inventory_posting_service import execute_once, PostingEffect
from Services.inventory_receipt_cost_review_service import (
    ACTION as COST_ACTION, RECEIPT_POSTING_KIND,
    approved_receipt_cost_binding, reviewed_receipt_cost_binding)
from Services.inventory_receipt_source_use_service import consume_receipt_source
from Services.inventory_receipt_movement_service import (
    check_receipt_stock, append_receipt_stock)
from Services.inventory_receipt_valuation_service import (
    check_receipt_value, append_receipt_values)
from Services.manager_case_service import CaseBinding, consume_case
from Services.posting_authority_service import AuthorityClaim, CostPoolAuthorityClaim


INTERNAL_VALUE_KIND = 'inventory.receipt.post-value.v1'


def _identities(context, operation_key, manifest_key, classification_case_key,
        expected_valuation_version, reason, stock_authority, cost_authority,
        authorize_stock, authorize_cost):
    if any(not isinstance(key, UUID) or not key.int
            for key in (operation_key, manifest_key, classification_case_key)):
        raise ValueError('Nonzero receipt operation, manifest and classification case identities required')
    if (not isinstance(stock_authority, AuthorityClaim)
            or stock_authority.org_id != context.org_id):
        raise PermissionError('Trusted receiving-store authority required')
    if (not isinstance(cost_authority, CostPoolAuthorityClaim)
            or cost_authority.org_id != context.org_id):
        raise PermissionError('Trusted central cost-pool claim required')
    if not callable(authorize_stock) or not callable(authorize_cost):
        raise ValueError('Separate stock and financial permission guards required')
    if type(expected_valuation_version) is not int or expected_valuation_version < 0:
        raise ValueError('Expected valuation version must be nonnegative')
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ValueError('A bounded receipt posting reason is required')
    return dict(stock_authority=dict(org_id=stock_authority.org_id,
            branch_id=stock_authority.branch_id, node_key=str(stock_authority.node_key),
            epoch=stock_authority.epoch),
        cost_authority=dict(org_id=cost_authority.org_id,
            cost_pool_id=cost_authority.cost_pool_id,
            node_key=str(cost_authority.node_key), epoch=cost_authority.epoch))


def _post_receipt(factory, context, actor_id, operation_key, *, manifest_key,
        classification_case_key, expected_valuation_version, goods_value_scr, reason,
        stock_authority, cost_authority, authorize_stock, authorize_cost,
        kind, cost_case_key=None, cost_binding=None, load_cost_binding=None):
    authority = _identities(context, operation_key, manifest_key,
        classification_case_key, expected_valuation_version, reason,
        stock_authority, cost_authority, authorize_stock, authorize_cost)
    if not isinstance(goods_value_scr, Decimal):
        raise ValueError('Receipt value must be an exact Decimal')
    request = dict(manifest_key=str(manifest_key),
        classification_case_key=str(classification_case_key),
        expected_valuation_version=expected_valuation_version,
        goods_value_scr=format(goods_value_scr, '.6f'), reason=reason.strip(),
        **authority)
    if cost_case_key is not None:
        if (not isinstance(cost_case_key, UUID) or not cost_case_key.int
                or not isinstance(cost_binding, CaseBinding)
                or not callable(load_cost_binding)):
            raise ValueError('Exact approved receipt cost case and loader required')
        request.update(cost_case_key=str(cost_case_key),
            cost_binding=cost_binding.snapshot())

    def guard(db):
        # Central pool -> branch -> purchasing source -> product/location/cases.
        check_receipt_value(db, context, manifest_key=manifest_key,
            authority=cost_authority, authorize=authorize_cost)
        check_receipt_stock(db, context, manifest_key=manifest_key,
            authority=stock_authority, authorize=authorize_stock)
        if load_cost_binding is not None:
            load_cost_binding(db)

    def effect(db):
        consume_receipt_source(db, context, actor_id, operation_key,
            manifest_key=manifest_key, case_key=classification_case_key,
            authorize=authorize_stock)
        if load_cost_binding is not None:
            consume_case(db, context, actor_id, operation_key,
                case_key=cost_case_key, binding=cost_binding,
                load_binding=load_cost_binding, authorize=authorize_cost)
        movements = append_receipt_stock(db, context, actor_id, operation_key,
            manifest_key=manifest_key, authority=stock_authority,
            authorize=authorize_stock)
        valuation = append_receipt_values(db, context, actor_id, operation_key,
            manifest_key=manifest_key,
            expected_version=expected_valuation_version,
            goods_value_scr=goods_value_scr, reason=reason,
            authority=cost_authority, authorize=authorize_cost)
        result = dict(valuation)
        result.update(manifest_key=str(manifest_key),
            classification_case_key=str(classification_case_key),
            cost_case_key=str(cost_case_key) if cost_case_key else None,
            status='POSTED_UNRECONCILED', movements=movements)
        event = dict(kind='inventory.receipt.posted',
            manifest_key=str(manifest_key),
            classification_case_key=str(classification_case_key),
            cost_case_key=str(cost_case_key) if cost_case_key else None,
            balance_versions=[dict(balance_id=row['balance_id'],
                version=row['version']) for row in movements],
            valuation_ids=valuation['valuation_ids'],
            cost_pool_id=valuation['cost_pool_id'], status=valuation['status'])
        return PostingEffect(result, event)

    return execute_once(factory, context, actor_id, operation_key, kind,
        request, effect, authorize=guard)


def post_receipt_value_internal(factory, context, actor_id, operation_key, *,
        manifest_key, classification_case_key, expected_valuation_version,
        reviewed_goods_value_scr, reason, stock_authority, cost_authority,
        authorize_stock, authorize_cost):
    """Lower-layer composition test seam; adapters must never call this function."""
    return _post_receipt(factory, context, actor_id, operation_key,
        manifest_key=manifest_key, classification_case_key=classification_case_key,
        expected_valuation_version=expected_valuation_version,
        goods_value_scr=reviewed_goods_value_scr, reason=reason,
        stock_authority=stock_authority, cost_authority=cost_authority,
        authorize_stock=authorize_stock, authorize_cost=authorize_cost,
        kind=INTERNAL_VALUE_KIND)


def post_reviewed_receipt(factory, context, actor_id, operation_key, *, manifest_key,
        classification_case_key, cost_case_key, expected_valuation_version,
        prepared_cost, reason, stock_authority, cost_authority,
        authorize_stock, authorize_cost):
    """Post only exact, approved content-bound PO/FX evidence."""
    if not isinstance(prepared_cost, PreparedDocumentContent):
        raise ValueError('Server-prepared version-pinned receipt cost content required')
    source = prepared_cost.source
    if (source.org_id != context.org_id or source.action != COST_ACTION
            or source.source_version != 2
            or source.source_type != 'inventory.receipt.manifest'
            or source.source_key != str(manifest_key)):
        raise PermissionError('Prepared receipt cost evidence scope denied')
    content = prepared_cost.content_map()

    def load(db):
        current = approved_receipt_cost_binding(db, context, cost_case_key,
            manifest_key, authorize=authorize_cost, document_content=content,
            replay_operation_key=operation_key, replay_actor_id=actor_id)
        prepared_cost.require_current(current)
        return current

    return _post_receipt(factory, context, actor_id, operation_key,
        manifest_key=manifest_key,
        classification_case_key=classification_case_key,
        expected_valuation_version=expected_valuation_version,
        goods_value_scr=Decimal(source.details['goods_value_scr']), reason=reason,
        stock_authority=stock_authority, cost_authority=cost_authority,
        authorize_stock=authorize_stock, authorize_cost=authorize_cost,
        kind=RECEIPT_POSTING_KIND, cost_case_key=cost_case_key,
        cost_binding=source, load_cost_binding=load)


def prepare_and_post_reviewed_receipt(factory, context, actor_id, operation_key, *,
        manifest_key, classification_case_key, cost_case_key,
        expected_valuation_version, reason, stock_authority, cost_authority,
        authorize_stock, authorize_cost, storage, max_bytes):
    """Verify original reviewed file versions outside the posting transaction."""
    prepared = prepare_document_content(factory, authorize=authorize_cost,
        load_binding=lambda db: reviewed_receipt_cost_binding(db, context,
            cost_case_key, manifest_key, authorize=authorize_cost,
            replay_operation_key=operation_key, replay_actor_id=actor_id),
        storage=storage, max_bytes=max_bytes, expected_action=COST_ACTION,
        min_documents=1, max_documents=2)
    return post_reviewed_receipt(factory, context, actor_id, operation_key,
        manifest_key=manifest_key,
        classification_case_key=classification_case_key,
        cost_case_key=cost_case_key,
        expected_valuation_version=expected_valuation_version,
        prepared_cost=prepared, reason=reason,
        stock_authority=stock_authority, cost_authority=cost_authority,
        authorize_stock=authorize_stock, authorize_cost=authorize_cost)
