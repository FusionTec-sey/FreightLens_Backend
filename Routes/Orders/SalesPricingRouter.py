"""Versioned sales pricing and exact floor review; no invoice/posting endpoint."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Model.db import get_db
from Schema.InventoryLocationSchema import LocationPage
from Schema.SalesPricingSchema import (
    BranchProductPriceRead, BranchProductPriceSave,
    CustomerPriceAgreementRead, CustomerPriceAgreementSave,
    ProductTaxAssignmentRead, ProductTaxAssignmentSave,
    TaxRuleRead, TaxRuleSave,
)
from Schema.ManagerCaseSchema import CaseActionRead, PolicyCaseReview
from Schema.SalesPriceFloorSchema import PriceFloorCaseRead, PriceFloorCaseRequest
from Services.manager_case_read_service import case_metadata, case_page
from Services.sales_price_floor_case_service import (
    request_floor_case, review_floor_case, scoped_floor_cases,
)
from Services.inventory_posting_service import PostingConflict
from Services.sales_pricing_configuration_service import (
    list_branch_product_prices, list_customer_price_agreements,
    list_product_tax_assignments, list_tax_rules,
    read_branch_product_price, read_customer_price_agreement,
    read_product_tax_assignment, read_tax_rule,
    save_branch_product_price, save_customer_price_agreement,
    save_product_tax_assignment, save_tax_rule,
)
from Routes.MasterData.CustomerRouter import customer_access, private_response
from Utils.org_filter import OrgContext
from auth.dependencies import get_current_user, get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission


def pricing_access(policy: AccessPolicy = Depends(get_request_policy)):
    if not policy.has("View_Product") or not policy.has("View_Financials"):
        raise HTTPException(403, "Product and financial pricing access required")
    return policy


SalesPricingRouter = APIRouter(prefix="/sales/pricing", tags=["Sales pricing"],
    dependencies=[Depends(require_module("SALES")), Depends(pricing_access),
                  Depends(private_response)])


def _authorize(policy, *, customer=False, manage=False):
    def guard(db):
        pricing_access(policy)
        if customer:
            customer_access(policy)
        if manage and not policy.has("Manage_Financials"):
            raise PermissionError("Financial pricing management access required")
    return guard


def _error(error):
    if isinstance(error, LookupError):
        return HTTPException(404, "Pricing source not found")
    if isinstance(error, PermissionError):
        return HTTPException(403, str(error))
    if isinstance(error, PostingConflict):
        return HTTPException(409, str(error))
    if isinstance(error, ValueError):
        return HTTPException(422, str(error))
    return error


def _save(db, action):
    try:
        if not db.in_transaction():
            db.begin()
        outcome = action()
        db.commit()
        return outcome
    except Exception as error:
        db.rollback()
        raise _error(error) from error


def _floor_guard(policy, permission):
    def authorize(db):
        pricing_access(policy)
        if not policy.has("View_SalesDraft") or not policy.has(permission):
            raise PermissionError("Sales draft and price-floor review access required")
    return authorize


@SalesPricingRouter.post("/floor-cases", response_model=CaseActionRead)
def request_price_floor_case(payload: PriceFloorCaseRequest,
                             db: Session = Depends(get_db),
                             context: OrgContext = Depends(get_org_context),
                             policy: AccessPolicy = Depends(pricing_access),
                             user=Depends(require_permission("Request_PriceFloorException"))):
    authorize = _floor_guard(policy, "Request_PriceFloorException")
    outcome = _save(db, lambda: request_floor_case(db, context, user.id,
        payload, authorize=authorize))
    return CaseActionRead(**outcome.result, replayed=outcome.replayed)


@SalesPricingRouter.get("/floor-cases",
    response_model=LocationPage[PriceFloorCaseRead])
def price_floor_cases(page: int = Query(1, ge=1),
                      limit: int = Query(25, ge=1, le=100),
                      view: Literal["ALL", "MY_REQUESTS", "NEEDS_MY_REVIEW"] = "ALL",
                      db: Session = Depends(get_db),
                      context: OrgContext = Depends(get_org_context),
                      policy: AccessPolicy = Depends(pricing_access),
                      user=Depends(get_current_user)):
    can_review = policy.has("Review_PriceFloorException")
    can_request = policy.has("Request_PriceFloorException")
    if not policy.has("View_SalesDraft") or not (can_review or can_request):
        raise HTTPException(403, "Sales draft and price-floor review access required")
    query = scoped_floor_cases(db, context)
    if not can_review:
        query = query.filter_by(created_by=user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = []
    for case, decision, used in rows:
        details = case.binding["details"]
        items.append(PriceFloorCaseRead(**case_metadata(case, decision, used),
            document_key=details["document_key"], draft_version=details["draft_version"],
            currency=details["pricing"]["currency"],
            gross_total_scr=details["pricing"]["gross_total_scr"],
            floor_line_count=details["floor_line_count"],
            pricing_fingerprint=details["pricing_fingerprint"]))
    return {"items": items, "total": total, "page": page, "limit": limit,
            "pages": max(1, (total + limit - 1) // limit)}


@SalesPricingRouter.post("/floor-cases/{key}/review", response_model=CaseActionRead)
def decide_price_floor_case(key: UUID, payload: PolicyCaseReview,
                            db: Session = Depends(get_db),
                            context: OrgContext = Depends(get_org_context),
                            policy: AccessPolicy = Depends(pricing_access),
                            user=Depends(require_permission("Review_PriceFloorException"))):
    authorize = _floor_guard(policy, "Review_PriceFloorException")
    outcome = _save(db, lambda: review_floor_case(db, context, user.id,
        payload.operation_key, case_key=key, expected_version=payload.expected_version,
        outcome=payload.outcome, reason=payload.reason, authorize=authorize))
    return CaseActionRead(**outcome.result, replayed=outcome.replayed)


@SalesPricingRouter.get("/tax-rules", response_model=LocationPage[TaxRuleRead])
def tax_rules(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
              db: Session = Depends(get_db),
              context: OrgContext = Depends(get_org_context),
              policy: AccessPolicy = Depends(pricing_access)):
    return list_tax_rules(db, context, page=page, limit=limit,
        authorize=_authorize(policy))


@SalesPricingRouter.get("/tax-rules/{key}", response_model=TaxRuleRead)
def tax_rule(key: UUID, db: Session = Depends(get_db),
             context: OrgContext = Depends(get_org_context),
             policy: AccessPolicy = Depends(pricing_access)):
    try:
        return read_tax_rule(db, context, key, authorize=_authorize(policy))
    except Exception as error:
        raise _error(error) from error


@SalesPricingRouter.put("/tax-rules/{key}", response_model=TaxRuleRead)
def put_tax_rule(key: UUID, payload: TaxRuleSave, db: Session = Depends(get_db),
                 context: OrgContext = Depends(get_org_context),
                 policy: AccessPolicy = Depends(pricing_access),
                 user=Depends(require_permission("Manage_Financials"))):
    authorize = _authorize(policy, manage=True)
    _save(db, lambda: save_tax_rule(db, context, user.id, key, payload,
        authorize=authorize))
    return read_tax_rule(db, context, key, authorize=authorize)


@SalesPricingRouter.get("/branch-prices",
    response_model=LocationPage[BranchProductPriceRead])
def branch_prices(page: int = Query(1, ge=1),
                  limit: int = Query(25, ge=1, le=100),
                  branch_id: int | None = Query(None, gt=0),
                  product_id: int | None = Query(None, gt=0),
                  unit: str | None = Query(None, min_length=1, max_length=50),
                  db: Session = Depends(get_db),
                  context: OrgContext = Depends(get_org_context),
                  policy: AccessPolicy = Depends(pricing_access)):
    return list_branch_product_prices(db, context, page=page, limit=limit,
        branch_id=branch_id, product_id=product_id, unit=unit,
        authorize=_authorize(policy))


@SalesPricingRouter.get("/branch-prices/{key}",
    response_model=BranchProductPriceRead)
def branch_price(key: UUID, db: Session = Depends(get_db),
                 context: OrgContext = Depends(get_org_context),
                 policy: AccessPolicy = Depends(pricing_access)):
    try:
        return read_branch_product_price(db, context, key,
            authorize=_authorize(policy))
    except Exception as error:
        raise _error(error) from error


@SalesPricingRouter.put("/branch-prices/{key}",
    response_model=BranchProductPriceRead)
def put_branch_price(key: UUID, payload: BranchProductPriceSave,
                     db: Session = Depends(get_db),
                     context: OrgContext = Depends(get_org_context),
                     policy: AccessPolicy = Depends(pricing_access),
                     user=Depends(require_permission("Manage_Financials"))):
    authorize = _authorize(policy, manage=True)
    _save(db, lambda: save_branch_product_price(db, context, user.id, key,
        payload, authorize=authorize))
    return read_branch_product_price(db, context, key, authorize=authorize)


@SalesPricingRouter.get("/product-tax-assignments",
    response_model=LocationPage[ProductTaxAssignmentRead])
def product_tax_assignments(page: int = Query(1, ge=1),
                            limit: int = Query(25, ge=1, le=100),
                            product_id: int | None = Query(None, gt=0),
                            db: Session = Depends(get_db),
                            context: OrgContext = Depends(get_org_context),
                            policy: AccessPolicy = Depends(pricing_access)):
    return list_product_tax_assignments(db, context, page=page, limit=limit,
        product_id=product_id, authorize=_authorize(policy))


@SalesPricingRouter.get("/product-tax-assignments/{key}",
    response_model=ProductTaxAssignmentRead)
def product_tax_assignment(key: UUID, db: Session = Depends(get_db),
                           context: OrgContext = Depends(get_org_context),
                           policy: AccessPolicy = Depends(pricing_access)):
    try:
        return read_product_tax_assignment(db, context, key,
            authorize=_authorize(policy))
    except Exception as error:
        raise _error(error) from error


@SalesPricingRouter.put("/product-tax-assignments/{key}",
    response_model=ProductTaxAssignmentRead)
def put_product_tax_assignment(key: UUID, payload: ProductTaxAssignmentSave,
                               db: Session = Depends(get_db),
                               context: OrgContext = Depends(get_org_context),
                               policy: AccessPolicy = Depends(pricing_access),
                               user=Depends(require_permission("Manage_Financials"))):
    authorize = _authorize(policy, manage=True)
    _save(db, lambda: save_product_tax_assignment(db, context, user.id, key,
        payload, authorize=authorize))
    return read_product_tax_assignment(db, context, key, authorize=authorize)


@SalesPricingRouter.get("/customer-agreements",
    response_model=LocationPage[CustomerPriceAgreementRead])
def customer_agreements(page: int = Query(1, ge=1),
                        limit: int = Query(25, ge=1, le=100),
                        customer_key: UUID | None = None,
                        branch_id: int | None = Query(None, gt=0),
                        product_id: int | None = Query(None, gt=0),
                        unit: str | None = Query(None, min_length=1, max_length=50),
                        db: Session = Depends(get_db),
                        context: OrgContext = Depends(get_org_context),
                        policy: AccessPolicy = Depends(pricing_access)):
    return list_customer_price_agreements(db, context, page=page, limit=limit,
        customer_key=customer_key, branch_id=branch_id,
        product_id=product_id, unit=unit,
        authorize=_authorize(policy, customer=True))


@SalesPricingRouter.get("/customer-agreements/{key}",
    response_model=CustomerPriceAgreementRead)
def customer_agreement(key: UUID, db: Session = Depends(get_db),
                       context: OrgContext = Depends(get_org_context),
                       policy: AccessPolicy = Depends(pricing_access)):
    try:
        return read_customer_price_agreement(db, context, key,
            authorize=_authorize(policy, customer=True))
    except Exception as error:
        raise _error(error) from error


@SalesPricingRouter.put("/customer-agreements/{key}",
    response_model=CustomerPriceAgreementRead)
def put_customer_agreement(key: UUID, payload: CustomerPriceAgreementSave,
                           db: Session = Depends(get_db),
                           context: OrgContext = Depends(get_org_context),
                           policy: AccessPolicy = Depends(pricing_access),
                           user=Depends(require_permission("Manage_Financials"))):
    authorize = _authorize(policy, customer=True, manage=True)
    _save(db, lambda: save_customer_price_agreement(db, context, user.id, key,
        payload, authorize=authorize))
    return read_customer_price_agreement(db, context, key, authorize=authorize)
