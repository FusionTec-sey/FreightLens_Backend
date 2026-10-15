from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc, asc, func, text as sqltext
import math
from typing import Optional, List
from datetime import date
from pydantic import BaseModel

from Model.db import get_db
from Model.containermgmt.MasterData.Currency import Currency, CurrencyExchangeRate
from Model.containermgmt.MasterData.PaymentTerm import PaymentTerm
from Model.containermgmt.MasterData.DocumentType import MasterDocumentType
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Orders.Product import Product
from Model.Credentials.Organisation import Organisation
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import can_view_supplier_user, is_financial_user
from Utils.org_filter import OrgContext, apply_org_filter, apply_shared_or_org_filter
from Services.master_data_audit import snapshot, record_changes, record_event
from Services.search_service import (
    remove_supplier_document, search_suppliers_with_total, supplier_scope_filter,
    sync_supplier_document,
)


# What a trail records for a vendor. Identity and terms -- the things another
# company would notice changing under it.
SUPPLIER_AUDITED_FIELDS = (
    "name", "code", "address", "email", "phone", "contact_person", "country",
    "default_currency", "default_payment_term_id", "variance_threshold_pct",
    "is_active", "is_shared", "notes",
)


def _supplier_usage(db: Session, supplier_id: int) -> dict:
    """Where a vendor is already used, and by how many companies.

    A shared vendor is retired by one company for everyone, so the count of who
    else depends on it is shown before that happens.
    """
    counts = {}
    for label, sql in (
        ("purchase_orders",
         'SELECT count(*), count(DISTINCT org_id) FROM containermgmt.purchase_orders WHERE supplier_id = :id'),
        ("vendor_quotes",
         'SELECT count(*), 0 FROM containermgmt.vendor_quotes WHERE supplier_id = :id'),
        ("bills_of_lading",
         'SELECT count(*), count(DISTINCT org_id) FROM containermgmt.bill_of_landing WHERE "Supplier" = :id'),
        ("products",
         'SELECT count(*), count(DISTINCT org_id) FROM containermgmt.products WHERE default_supplier_id = :id'),
    ):
        try:
            row = db.execute(sqltext(sql), {"id": supplier_id}).first()
            counts[label] = int(row[0] or 0)
            counts.setdefault("_orgs", set()).update([row[1]] if row[1] else [])
        except Exception:
            counts[label] = 0
    orgs = counts.pop("_orgs", set())
    total = sum(v for v in counts.values())
    return {"counts": counts, "total": total, "companies": max(orgs) if orgs else 0}
from Utils.blob_storage import blob_storage
from Routes.Orders.OrderRouter import is_accounts_user

MasterDataRouter = APIRouter(prefix="/master-data", tags=["Master Data"])


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class CurrencySchema(BaseModel):
    code: str
    name: str
    symbol: Optional[str] = None
    decimals: Optional[int] = 2
    is_active: Optional[bool] = True

class ExchangeRateCreateSchema(BaseModel):
    org_id: Optional[int] = None
    from_currency: str
    to_currency: str
    rate: float
    effective_date: Optional[date] = None

class PaymentTermSchema(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    advance_pct: float = 0.0
    progress_pct: float = 0.0
    balance_pct: float = 100.0
    balance_trigger: str = "ON_BL"
    credit_days: int = 0
    is_active: bool = True

class SupplierMasterSchema(BaseModel):
    name: str
    code: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    contact_person: Optional[str] = None
    country: Optional[str] = None
    logo_url: Optional[str] = None
    default_currency: Optional[str] = "USD"
    default_payment_term_id: Optional[int] = None
    variance_threshold_pct: Optional[float] = 2.0
    notes: Optional[str] = None
    is_active: Optional[bool] = True
    is_shared: bool = False


# ── 1. Currencies Endpoints ───────────────────────────────────────────────────

@MasterDataRouter.get("/currencies")
def get_currencies(
    active_only: bool = False,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(Currency)
    if active_only:
        query = query.filter(Currency.is_active == True)
    currencies = query.order_by(Currency.code.asc()).all()
    return [
        {
            "code": c.code,
            "name": c.name,
            "symbol": c.symbol or c.code,
            "decimals": c.decimals,
            "is_active": c.is_active,
        }
        for c in currencies
    ]

@MasterDataRouter.post("/currencies")
def create_currency(
    payload: CurrencySchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can manage currencies.")

    code_clean = payload.code.strip().upper()
    existing = db.query(Currency).filter(Currency.code == code_clean).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Currency '{code_clean}' already exists.")

    currency = Currency(
        code=code_clean,
        name=payload.name.strip(),
        symbol=payload.symbol.strip() if payload.symbol else code_clean,
        decimals=payload.decimals if payload.decimals is not None else 2,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(currency)
    db.commit()
    db.refresh(currency)
    return {"success": True, "message": f"Currency {currency.code} added successfully.", "currency": currency.code}

@MasterDataRouter.put("/currencies/{code}")
def update_currency(
    code: str,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can modify currencies.")

    currency = db.query(Currency).filter(Currency.code == code.strip().upper()).first()
    if not currency:
        raise HTTPException(status_code=404, detail="Currency not found.")

    if "name" in payload and payload["name"]:
        currency.name = payload["name"].strip()
    if "symbol" in payload:
        currency.symbol = payload["symbol"].strip() if payload["symbol"] else currency.code
    if "decimals" in payload and payload["decimals"] is not None:
        currency.decimals = int(payload["decimals"])
    if "is_active" in payload and payload["is_active"] is not None:
        currency.is_active = bool(payload["is_active"])

    db.commit()
    return {"success": True, "message": f"Currency {currency.code} updated successfully."}


# ── 2. Exchange Rates Endpoints ───────────────────────────────────────────────

@MasterDataRouter.get("/exchange-rates")
def get_exchange_rates(
    org_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(CurrencyExchangeRate).filter(CurrencyExchangeRate.is_active == True)
    if org_id is not None:
        query = query.filter(or_(CurrencyExchangeRate.org_id == org_id, CurrencyExchangeRate.org_id == None))
    rates = query.order_by(CurrencyExchangeRate.from_currency.asc()).all()

    # Determine base currency for the queried organization
    base_curr = "SCR"
    if org_id is not None:
        org = db.query(Organisation).filter(Organisation.id == org_id).first()
        if org and org.base_currency:
            base_curr = org.base_currency

    return {
        "org_id": org_id,
        "base_currency": base_curr,
        "rates": [
            {
                "id": r.id,
                "org_id": r.org_id,
                "from_currency": r.from_currency,
                "to_currency": r.to_currency,
                "rate": float(r.rate),
                "effective_date": r.effective_date.isoformat() if r.effective_date else None,
                "is_override": r.org_id is not None,
            }
            for r in rates
        ]
    }

@MasterDataRouter.post("/exchange-rates")
def upsert_exchange_rate(
    payload: ExchangeRateCreateSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can manage exchange rates.")

    from_c = payload.from_currency.strip().upper()
    to_c = payload.to_currency.strip().upper()
    if from_c == to_c:
        raise HTTPException(status_code=400, detail="From and To currency cannot be the same.")

    if payload.rate <= 0:
        raise HTTPException(status_code=400, detail="Exchange rate must be greater than zero.")

    # Check existing rate for org_id (or global if org_id is None)
    existing = db.query(CurrencyExchangeRate).filter(
        CurrencyExchangeRate.org_id == payload.org_id,
        CurrencyExchangeRate.from_currency == from_c,
        CurrencyExchangeRate.to_currency == to_c,
        CurrencyExchangeRate.is_active == True
    ).first()

    if existing:
        existing.rate = payload.rate
        existing.effective_date = payload.effective_date or date.today()
        db.commit()
        db.refresh(existing)
        return {"success": True, "message": f"Updated exchange rate {from_c} -> {to_c}: {payload.rate}", "rate_id": existing.id}
    else:
        new_rate = CurrencyExchangeRate(
            org_id=payload.org_id,
            from_currency=from_c,
            to_currency=to_c,
            rate=payload.rate,
            effective_date=payload.effective_date or date.today(),
            is_active=True,
            created_by=current_user.id if hasattr(current_user, 'id') else None
        )
        db.add(new_rate)
        db.commit()
        db.refresh(new_rate)
        return {"success": True, "message": f"Saved exchange rate {from_c} -> {to_c}: {payload.rate}", "rate_id": new_rate.id}

@MasterDataRouter.get("/exchange-rates/convert")
def convert_currency(
    from_currency: str,
    to_currency: str,
    amount: float,
    org_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    from_c = from_currency.strip().upper()
    to_c = to_currency.strip().upper()

    if from_c == to_c:
        return {
            "from_currency": from_c,
            "to_currency": to_c,
            "amount": amount,
            "rate": 1.0,
            "converted_amount": amount
        }

    # 1. Direct rate search (prefer org override first, then global)
    direct_rate = db.query(CurrencyExchangeRate).filter(
        CurrencyExchangeRate.from_currency == from_c,
        CurrencyExchangeRate.to_currency == to_c,
        CurrencyExchangeRate.is_active == True,
        or_(CurrencyExchangeRate.org_id == org_id, CurrencyExchangeRate.org_id == None)
    ).order_by(desc(CurrencyExchangeRate.org_id)).first()

    if direct_rate:
        rate = float(direct_rate.rate)
        return {
            "from_currency": from_c,
            "to_currency": to_c,
            "amount": amount,
            "rate": rate,
            "converted_amount": round(amount * rate, 2)
        }

    # 2. Inverse rate search
    inv_rate = db.query(CurrencyExchangeRate).filter(
        CurrencyExchangeRate.from_currency == to_c,
        CurrencyExchangeRate.to_currency == from_c,
        CurrencyExchangeRate.is_active == True,
        or_(CurrencyExchangeRate.org_id == org_id, CurrencyExchangeRate.org_id == None)
    ).order_by(desc(CurrencyExchangeRate.org_id)).first()

    if inv_rate and float(inv_rate.rate) > 0:
        rate = 1.0 / float(inv_rate.rate)
        return {
            "from_currency": from_c,
            "to_currency": to_c,
            "amount": amount,
            "rate": rate,
            "converted_amount": round(amount * rate, 2)
        }

    # 3. Cross-rate via SCR or USD fallback
    for intermediary in ["SCR", "USD"]:
        if from_c != intermediary and to_c != intermediary:
            rate_from = db.query(CurrencyExchangeRate).filter(
                CurrencyExchangeRate.from_currency == from_c,
                CurrencyExchangeRate.to_currency == intermediary,
                CurrencyExchangeRate.is_active == True
            ).first()
            rate_to = db.query(CurrencyExchangeRate).filter(
                CurrencyExchangeRate.from_currency == intermediary,
                CurrencyExchangeRate.to_currency == to_c,
                CurrencyExchangeRate.is_active == True
            ).first()

            if rate_from and rate_to:
                computed_rate = float(rate_from.rate) * float(rate_to.rate)
                return {
                    "from_currency": from_c,
                    "to_currency": to_c,
                    "amount": amount,
                    "rate": computed_rate,
                    "converted_amount": round(amount * computed_rate, 2)
                }

    raise HTTPException(
        status_code=404,
        detail=f"No exchange rate configured between {from_c} and {to_c}."
    )


# ── 3. Payment Terms Endpoints ────────────────────────────────────────────────

@MasterDataRouter.get("/payment-terms")
def get_payment_terms(
    active_only: bool = True,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    query = apply_shared_or_org_filter(db.query(PaymentTerm), PaymentTerm, org_context)
    if active_only:
        query = query.filter(PaymentTerm.is_active == True)
    terms = query.order_by(PaymentTerm.id.asc()).all()

    results = []
    for t in terms:
        # Count vendors bound to this term
        vendor_query = db.query(Supplier).filter(
            Supplier.default_payment_term_id == t.id,
            Supplier.is_deleted != True
        )
        vendor_count = apply_shared_or_org_filter(vendor_query, Supplier, org_context).count()

        results.append({
            "id": t.id,
            "code": t.code,
            "name": t.name,
            "description": t.description,
            "advance_pct": float(t.advance_pct or 0),
            "progress_pct": float(t.progress_pct or 0),
            "balance_pct": float(t.balance_pct or 0),
            "balance_trigger": t.balance_trigger,
            "credit_days": t.credit_days,
            "is_active": t.is_active,
            "is_shared": t.is_shared,
            "org_id": t.org_id,
            "vendor_count": vendor_count,
        })

    return results

@MasterDataRouter.post("/payment-terms")
def create_payment_term(
    payload: PaymentTermSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can create payment terms.")

    total_pct = payload.advance_pct + payload.progress_pct + payload.balance_pct
    if abs(total_pct - 100.0) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Payment terms percentages must sum to 100% (currently {total_pct:.1f}%)."
        )

    code_clean = payload.code.strip().upper().replace(" ", "_")
    existing = db.query(PaymentTerm).filter(
        PaymentTerm.org_id == org_context.org_id,
        PaymentTerm.code == code_clean,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Payment term code '{code_clean}' already exists.")

    term = PaymentTerm(
        org_id=org_context.org_id,
        is_shared=False,
        code=code_clean,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        advance_pct=payload.advance_pct,
        progress_pct=payload.progress_pct,
        balance_pct=payload.balance_pct,
        balance_trigger=payload.balance_trigger.strip(),
        credit_days=payload.credit_days,
        is_active=payload.is_active,
        created_by=current_user.id if hasattr(current_user, 'id') else None
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return {"success": True, "message": f"Payment term '{term.name}' created.", "term_id": term.id}

@MasterDataRouter.put("/payment-terms/{id}")
def update_payment_term(
    id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can edit payment terms.")

    term = db.query(PaymentTerm).filter(
        PaymentTerm.id == id,
        PaymentTerm.org_id == org_context.org_id,
    ).first()
    if not term:
        raise HTTPException(status_code=404, detail="Payment term not found.")

    if "name" in payload and payload["name"]:
        term.name = payload["name"].strip()
    if "description" in payload:
        term.description = payload["description"]
    if "advance_pct" in payload:
        term.advance_pct = float(payload["advance_pct"])
    if "progress_pct" in payload:
        term.progress_pct = float(payload["progress_pct"])
    if "balance_pct" in payload:
        term.balance_pct = float(payload["balance_pct"])

    total_pct = float(term.advance_pct) + float(term.progress_pct) + float(term.balance_pct)
    if abs(total_pct - 100.0) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Percentages must sum to 100% (currently {total_pct:.1f}%)."
        )

    if "balance_trigger" in payload and payload["balance_trigger"]:
        term.balance_trigger = payload["balance_trigger"]
    if "credit_days" in payload and payload["credit_days"] is not None:
        term.credit_days = int(payload["credit_days"])
    if "is_active" in payload and payload["is_active"] is not None:
        term.is_active = bool(payload["is_active"])

    db.commit()
    return {"success": True, "message": f"Payment term '{term.name}' updated."}

@MasterDataRouter.delete("/payment-terms/{id}")
def delete_payment_term(
    id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can delete payment terms.")

    term = db.query(PaymentTerm).filter(
        PaymentTerm.id == id,
        PaymentTerm.org_id == org_context.org_id,
    ).first()
    if not term:
        raise HTTPException(status_code=404, detail="Payment term not found.")

    # Soft delete / deactivate
    term.is_active = False
    db.commit()
    return {"success": True, "message": f"Payment term '{term.name}' deactivated."}


# ── 4. Enhanced Suppliers Master Endpoints ───────────────────────────────────

def _clean_supplier_code(raw) -> Optional[str]:
    return (raw or "").strip() or None


def _issue_supplier_code(supplier_id: int) -> str:
    """The form the directory has always displayed, now stored on the row.

    Deliberately meaningless: no company or group segment, because a supplier
    created by one company and later shared across the group would carry a code
    that lies, and recoding it would break every document that quoted it.
    """
    return f"VEND-{supplier_id:04d}"


def _assert_supplier_code_free(db: Session, code: str, exclude_id: Optional[int] = None) -> None:
    """Codes are unique across the group -- one vendor, one reference.

    Checked here as well as by the unique index so the answer is a 409 a person
    can read rather than a 500 out of the driver.
    """
    query = db.query(Supplier).filter(
        func.lower(func.trim(Supplier.code)) == code.strip().lower(),
        Supplier.is_deleted != True,
    )
    if exclude_id is not None:
        query = query.filter(Supplier.supplier_id != exclude_id)
    clash = query.first()
    if clash:
        raise HTTPException(status_code=409, detail=(
            f"Supplier code {code} is already used by '{clash.name}'."))


@MasterDataRouter.get("/suppliers")
def get_suppliers_master(
    page: Optional[int] = Query(None, ge=1),
    limit: Optional[int] = Query(None, ge=1, le=200),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("asc"),
    active_only: bool = False,
    status: Optional[str] = Query(
        None,
        pattern="^(active|inactive)$",
        description="Narrow to active or inactive vendors. The directory's own "
                    "filter: without it a retired vendor is still listed.",
    ),
    currency: Optional[str] = Query(
        None,
        description="Narrow to one default trade currency. Filtered here rather "
                    "than in the browser, so it holds across pages.",
    ),
    for_org_id: Optional[int] = Query(
        None,
        description=(
            "Narrow to the suppliers a document owned by this organisation may "
            "use: shared ones, plus that organisation's own."
        ),
    ),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    can_view_supplier = can_view_supplier_user(current_user)
    query = db.query(Supplier).filter(Supplier.is_deleted != True)
    query = apply_shared_or_org_filter(query, Supplier, org_context)
    if active_only or status == "active":
        query = query.filter(Supplier.is_active == True)
    elif status == "inactive":
        query = query.filter(Supplier.is_active == False)

    if currency:
        query = query.filter(func.upper(Supplier.default_currency) == currency.strip().upper())

    # A user whose context spans several organisations otherwise sees suppliers
    # that a document belonging to one of them cannot accept -- the vendor quote
    # endpoint requires shared-or-same-organisation and rejects the rest. This
    # narrows, never widens: it is applied on top of the scope filter above.
    if for_org_id is not None:
        query = query.filter(
            or_(Supplier.is_shared == True, Supplier.org_id == for_org_id)
        )

    # A typed search goes to the index when there is one. Seven ILIKE clauses
    # cannot cope with a typo or two words in the wrong order, and suppliers are
    # now indexed alongside products and orders. The SQL path below stays as the
    # fallback for when Meilisearch is unavailable -- an outage must narrow the
    # directory's search, never empty it.
    indexed_ids = None
    indexed_total = 0
    if search and search.strip():
        filters = ["is_deleted = false"]
        scope = supplier_scope_filter(org_context)
        if scope:
            filters.append(scope)
        if active_only or status == "active":
            filters.append("is_active = true")
        elif status == "inactive":
            filters.append("is_active = false")
        if currency:
            filters.append(f'default_currency = "{currency.strip().upper()}"')
        hits, indexed_total = search_suppliers_with_total(
            search.strip(), filters=filters,
            limit=(limit or 25), offset=((max(1, page or 1) - 1) * (limit or 25)),
        )
        if hits is not None:
            indexed_ids = [
                int(h.get("supplier_id") or h.get("id"))
                for h in hits if (h.get("supplier_id") or h.get("id"))
            ]

    if search and indexed_ids is None:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Supplier.name.ilike(s),
                Supplier.code.ilike(s),
                Supplier.contact_person.ilike(s),
                Supplier.email.ilike(s),
                Supplier.phone.ilike(s),
                Supplier.country.ilike(s),
            )
        )

    ALLOWED_SORT = {
        "id": Supplier.supplier_id,
        "name": Supplier.name,
        "code": Supplier.code,
        "country": Supplier.country,
    }
    sort_col = ALLOWED_SORT.get(sort_by, Supplier.name)
    if sort_dir == "desc":
        query = query.order_by(desc(sort_col))
    else:
        query = query.order_by(asc(sort_col))

    def serialize_supplier(s):
        return {
            "id": s.supplier_id,
            "supplier_id": s.supplier_id,
            "name": s.name,
            "code": s.code,
            "address": s.address,
            "email": s.email,
            "phone": s.phone,
            "contact_person": s.contact_person,
            # Not defaulted to Seychelles any more: 136 of 136 vendors have no
            # country recorded, and a fabricated one is the field deduplication
            # and verification will later be matched on.
            "country": s.country,
            "logo_url": s.logo_url,
            "logo_signed_url": (
                blob_storage.signed_url(s.logo_url, ttl=15 * 60)
                if can_view_supplier and s.logo_url else None
            ),
            "is_shared": bool(s.is_shared),
            "org_id": s.org_id,
            # Named, so the directory can show which company a vendor is
            # restricted to rather than a bare id.
            "org_name": (
                (s.organisation.display_name or s.organisation.name)
                if s.organisation else None
            ),
            "scope": "shared" if s.is_shared else "tenant",
            "default_currency": s.default_currency or "USD",
            "default_payment_term_id": s.default_payment_term_id,
            "payment_term": {
                "id": s.payment_term.id,
                "code": s.payment_term.code,
                "name": s.payment_term.name,
                "advance_pct": float(s.payment_term.advance_pct or 0),
                "balance_pct": float(s.payment_term.balance_pct or 100),
                "balance_trigger": s.payment_term.balance_trigger,
            } if s.payment_term else None,
            "variance_threshold_pct": float(s.variance_threshold_pct or 2.0),
            "notes": s.notes,
            "is_active": s.is_active if s.is_active is not None else True,
        }

    if indexed_ids is not None:
        # The index decided the page and the ranking; the database still decides
        # what the user may see, so the rows are re-read under the scope filter
        # and anything it drops stays dropped.
        p = page or 1
        l = limit or 25
        if not indexed_ids:
            return {"items": [], "total": indexed_total, "page": p, "limit": l,
                    "pages": math.ceil(indexed_total / l) if indexed_total > 0 else 1}
        rows = query.filter(Supplier.supplier_id.in_(indexed_ids)).all()
        by_id = {r.supplier_id: r for r in rows}
        ordered = [by_id[i] for i in indexed_ids if i in by_id]
        return {
            "items": [serialize_supplier(s) for s in ordered],
            "total": indexed_total,
            "page": p,
            "limit": l,
            "pages": math.ceil(indexed_total / l) if indexed_total > 0 else 1,
        }

    if page is not None or limit is not None:
        p = page or 1
        l = limit or 25
        offset = (p - 1) * l
        total_count = query.count()
        suppliers = query.offset(offset).limit(l).all()
        return {
            "items": [serialize_supplier(s) for s in suppliers],
            "total": total_count,
            "page": p,
            "limit": l,
            "pages": math.ceil(total_count / l) if total_count > 0 else 1
        }

    suppliers = query.all()
    return [serialize_supplier(s) for s in suppliers]

@MasterDataRouter.post("/suppliers")
def create_supplier_master(
    payload: SupplierMasterSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance or Admin users can create suppliers.")

    name_clean = payload.name.strip()
    if payload.is_shared and not org_context.is_root:
        raise HTTPException(status_code=403, detail="Only root organisation users can create shared suppliers.")

    existing_query = db.query(Supplier).filter(Supplier.name.ilike(name_clean), Supplier.is_deleted != True)
    existing = apply_shared_or_org_filter(existing_query, Supplier, org_context).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Supplier '{name_clean}' already exists.")

    code_clean = _clean_supplier_code(payload.code)
    if code_clean:
        _assert_supplier_code_free(db, code_clean)

    supplier = Supplier(
        # org_id is NOT NULL and records who entered the vendor; is_shared alone
        # decides who may see it. Writing None here raised an IntegrityError and
        # returned a 500 -- on the normal case, since 136 of 136 vendors are
        # shared. The update path already works this way.
        org_id=org_context.org_id,
        is_shared=payload.is_shared,
        name=name_clean,
        code=_clean_supplier_code(payload.code),
        address=payload.address.strip() if payload.address else None,
        email=payload.email.strip() if payload.email else None,
        phone=payload.phone.strip() if payload.phone else None,
        contact_person=payload.contact_person.strip() if payload.contact_person else None,
        country=payload.country.strip() if payload.country else "Seychelles",
        logo_url=payload.logo_url.strip() if payload.logo_url else None,
        default_currency=payload.default_currency.strip().upper() if payload.default_currency else "USD",
        default_payment_term_id=payload.default_payment_term_id,
        variance_threshold_pct=payload.variance_threshold_pct or 2.0,
        notes=payload.notes.strip() if payload.notes else None,
        is_active=payload.is_active if payload.is_active is not None else True,
        created_by=current_user.id if hasattr(current_user, 'id') else None
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)

    if not supplier.code:
        supplier.code = _issue_supplier_code(supplier.supplier_id)
        db.commit()

    # The index is what the directory searches, so a vendor that is not in it
    # cannot be found by the screen that was just used to create it.
    sync_supplier_document(supplier)
    return {"success": True, "message": f"Supplier '{supplier.name}' registered successfully.", "supplier_id": supplier.supplier_id}

@MasterDataRouter.put("/suppliers/{id}")
def update_supplier_master(
    id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance or Admin users can update suppliers.")

    supplier_query = db.query(Supplier).filter(Supplier.supplier_id == id, Supplier.is_deleted != True)
    supplier = apply_shared_or_org_filter(supplier_query, Supplier, org_context).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")

    # A shared vendor is edited by whoever holds the permission, from any
    # company -- root is not a separate gate. One edit is seen by every company
    # at once, so what moved and who moved it is recorded below.
    before = snapshot(supplier, SUPPLIER_AUDITED_FIELDS)

    if "name" in payload and payload["name"]:
        supplier.name = payload["name"].strip()
    if "code" in payload:
        # Immutable once issued: it is quoted on purchase orders and delivery
        # notes, and changing it silently rewrites what those documents mean.
        requested_code = _clean_supplier_code(payload["code"])
        if supplier.code and requested_code and requested_code.lower() != supplier.code.lower():
            raise HTTPException(status_code=409, detail=(
                f"Supplier code {supplier.code} cannot be changed. It is the "
                "reference on documents already issued."))
        if not supplier.code and requested_code:
            _assert_supplier_code_free(db, requested_code)
            supplier.code = requested_code
    if "address" in payload:
        supplier.address = payload["address"].strip() if payload["address"] else None
    if "email" in payload:
        supplier.email = payload["email"].strip() if payload["email"] else None
    if "phone" in payload:
        supplier.phone = payload["phone"].strip() if payload["phone"] else None
    if "contact_person" in payload:
        supplier.contact_person = payload["contact_person"].strip() if payload["contact_person"] else None
    if "country" in payload:
        supplier.country = payload["country"].strip() if payload["country"] else None
    if "logo_url" in payload:
        supplier.logo_url = payload["logo_url"].strip() if payload["logo_url"] else None
    if "default_currency" in payload and payload["default_currency"]:
        supplier.default_currency = payload["default_currency"].strip().upper()
    if "default_payment_term_id" in payload:
        supplier.default_payment_term_id = payload["default_payment_term_id"] if payload["default_payment_term_id"] else None
    if "variance_threshold_pct" in payload and payload["variance_threshold_pct"] is not None:
        supplier.variance_threshold_pct = float(payload["variance_threshold_pct"])
    if "notes" in payload:
        supplier.notes = payload["notes"]
    if "is_active" in payload and payload["is_active"] is not None:
        supplier.is_active = bool(payload["is_active"])
    if "is_shared" in payload and payload["is_shared"] is not None:
        requested_shared = bool(payload["is_shared"])
        if requested_shared != bool(supplier.is_shared):
            if not org_context.is_root:
                raise HTTPException(status_code=403, detail="Only root organisation users can change supplier scope.")
            supplier.is_shared = requested_shared
            # org_id is NOT NULL and records who entered the vendor; is_shared
            # alone decides visibility. Setting it to None raised an
            # IntegrityError and returned a 500.
            if not requested_shared:
                supplier.org_id = org_context.org_id

    record_changes(
        db, "supplier", supplier.supplier_id, before, supplier, current_user.id,
        org_id=None if supplier.is_shared else supplier.org_id,
    )
    db.commit()
    sync_supplier_document(supplier, [i["value"] for i in _identifier_rows(db, supplier.supplier_id)])
    return {"success": True, "message": f"Supplier '{supplier.name}' updated successfully."}

@MasterDataRouter.post("/suppliers/{id}/logo")
def upload_supplier_logo(
    id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance or Admin users can upload logos.")

    supplier_query = db.query(Supplier).filter(Supplier.supplier_id == id, Supplier.is_deleted != True)
    supplier = apply_shared_or_org_filter(supplier_query, Supplier, org_context).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    if supplier.is_shared and not org_context.is_root:
        raise HTTPException(status_code=403, detail="Shared supplier logos can only be updated by root organisation users.")

    key = blob_storage.upload_file(
        file_obj=file,
        folder="suppliers/logos",
        original_filename=file.filename
    )
    supplier.logo_url = key
    db.commit()
    return {
        "success": True,
        "logo_url": key,
        "logo_signed_url": blob_storage.signed_url(key, ttl=15 * 60),
        "message": "Supplier logo uploaded successfully.",
    }

@MasterDataRouter.delete("/suppliers/{id}")
def delete_supplier_master(
    id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance or Admin users can delete suppliers.")

    supplier_query = db.query(Supplier).filter(Supplier.supplier_id == id, Supplier.is_deleted != True)
    supplier = apply_shared_or_org_filter(supplier_query, Supplier, org_context).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    # Retiring a shared vendor takes it out of every company's picker, so what
    # already depends on it is recorded with the deletion.
    usage = _supplier_usage(db, supplier.supplier_id)
    record_event(
        db, "supplier", supplier.supplier_id, "deleted", current_user.id,
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name="is_deleted", old_value=False, new_value=True,
    )
    supplier.is_deleted = True
    supplier.is_active = False
    db.commit()
    remove_supplier_document(supplier.supplier_id)
    return {
        "success": True,
        "message": f"Supplier '{supplier.name}' deleted.",
        "was_used_by": usage,
    }


@MasterDataRouter.get("/suppliers/{id}/usage")
def get_supplier_usage(
    id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """What already depends on this vendor, for the screen to show before retiring it."""
    supplier_query = db.query(Supplier).filter(Supplier.supplier_id == id, Supplier.is_deleted != True)
    supplier = apply_shared_or_org_filter(supplier_query, Supplier, org_context).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    usage = _supplier_usage(db, id)
    usage["is_shared"] = bool(supplier.is_shared)
    usage["name"] = supplier.name
    return usage



# ── 4b. Supplier profile: one vendor, everything it is attached to ───────────
#
# The directory could only ever show a row. Opening a vendor is where a buyer
# answers the questions that matter before using it: what do we buy from them,
# what is outstanding, what did they last quote, and what breaks if we retire
# them. Each tab is paged on the server, because a vendor with four hundred
# order lines must not arrive as one response.

# What a usable vendor record needs filled in. Deliberately short: a long list
# nobody can satisfy gets ignored, and these are the fields documents and
# payments actually need.
SUPPLIER_COMPLETENESS_FIELDS = (
    ("code", "Vendor code"),
    ("name", "Name"),
    ("country", "Country"),
    ("contact_person", "Contact person"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("address", "Address"),
    ("default_currency", "Default currency"),
    ("default_payment_term_id", "Payment terms"),
)


def _supplier_or_404(db: Session, supplier_id: int, org_context: OrgContext) -> Supplier:
    query = db.query(Supplier).filter(
        Supplier.supplier_id == supplier_id, Supplier.is_deleted != True
    )
    supplier = apply_shared_or_org_filter(query, Supplier, org_context).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    return supplier


def _org_scope(org_context: OrgContext):
    """The organisations whose documents this user may count or list.

    Returned as SQL plus parameters rather than applied in Python, so a tab
    never pages over rows it then has to drop.
    """
    if org_context.selected_org_id:
        return "org_id = :scope_org", {"scope_org": org_context.selected_org_id}
    allowed = list(org_context.allowed_org_ids or [])
    if not allowed:
        # No organisation at all means nothing to show, not everything.
        return "1 = 0", {}
    return "org_id = ANY(:scope_orgs)", {"scope_orgs": allowed}


def _paged(page: Optional[int], limit: Optional[int]):
    p = max(1, page or 1)
    l = min(200, max(1, limit or 25))
    return p, l, (p - 1) * l


def _page_envelope(items: list, total: int, page: int, limit: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total / limit) if total > 0 else 1,
    }


def _identifier_rows(db: Session, supplier_id: int) -> list:
    rows = db.execute(sqltext("""
        SELECT id, id_type, country, value, is_primary, verified_at, notes
        FROM containermgmt.supplier_identifiers
        WHERE supplier_id = :id AND is_deleted IS NOT TRUE
        ORDER BY is_primary DESC, id_type ASC, id ASC
    """), {"id": supplier_id}).mappings().all()
    return [
        {
            "id": r["id"],
            "id_type": r["id_type"],
            "country": r["country"],
            "value": r["value"],
            "is_primary": bool(r["is_primary"]),
            # An identifier proves nothing until someone checked it against a
            # register, so the screen says which ones were.
            "verified": r["verified_at"] is not None,
            "verified_at": r["verified_at"].isoformat() if r["verified_at"] else None,
            "notes": r["notes"],
        }
        for r in rows
    ]


@MasterDataRouter.get("/suppliers/{id}/profile")
def get_supplier_profile(
    id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    supplier = _supplier_or_404(db, id, org_context)
    can_edit = is_accounts_user(current_user, org_context) and (
        not supplier.is_shared or org_context.is_root
    )
    missing = [
        label for field, label in SUPPLIER_COMPLETENESS_FIELDS
        if not getattr(supplier, field, None)
    ]
    filled = len(SUPPLIER_COMPLETENESS_FIELDS) - len(missing)
    return {
        "id": supplier.supplier_id,
        "supplier_id": supplier.supplier_id,
        "name": supplier.name,
        "code": supplier.code,
        "address": supplier.address,
        "email": supplier.email,
        "phone": supplier.phone,
        "contact_person": supplier.contact_person,
        "country": supplier.country,
        "logo_url": supplier.logo_url,
        "logo_signed_url": (
            blob_storage.signed_url(supplier.logo_url, ttl=15 * 60)
            if can_view_supplier_user(current_user) and supplier.logo_url else None
        ),
        "is_shared": bool(supplier.is_shared),
        "is_active": supplier.is_active if supplier.is_active is not None else True,
        "org_id": supplier.org_id,
        "org_name": (
            (supplier.organisation.display_name or supplier.organisation.name)
            if supplier.organisation else None
        ),
        "default_currency": supplier.default_currency or "USD",
        "default_payment_term_id": supplier.default_payment_term_id,
        "payment_term": {
            "id": supplier.payment_term.id,
            "code": supplier.payment_term.code,
            "name": supplier.payment_term.name,
        } if supplier.payment_term else None,
        "variance_threshold_pct": float(supplier.variance_threshold_pct or 2.0),
        "notes": supplier.notes,
        # The counterparty seam: null until a vendor's own tenant is linked.
        "linked_org_id": supplier.linked_org_id,
        "identifiers": _identifier_rows(db, supplier.supplier_id),
        # The people and the places, sent with the profile so the tab opens on
        # what it already knows rather than on a spinner.
        "contacts": _contact_rows(db, supplier.supplier_id),
        "addresses": _address_rows(db, supplier.supplier_id),
        "usage": _supplier_usage(db, supplier.supplier_id),
        "completeness": {
            "filled": filled,
            "of": len(SUPPLIER_COMPLETENESS_FIELDS),
            "missing": missing,
        },
        # Said once, here, so buttons match the server's answer instead of
        # discovering a 403 on click.
        "permissions": {
            "can_edit": can_edit,
            "can_view_financials": is_financial_user(current_user, org_context),
        },
    }


@MasterDataRouter.get("/suppliers/{id}/products")
def get_supplier_products(
    id: int,
    page: Optional[int] = Query(None, ge=1),
    limit: Optional[int] = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """What we buy from this vendor, preferred or not.

    Costs are shown only to financial staff; the rest of the row -- their SKU,
    minimum order quantity and lead time -- is what a buyer needs to write a
    requisition, so it is never hidden.
    """
    _supplier_or_404(db, id, org_context)
    show_money = is_financial_user(current_user, org_context)
    p, l, offset = _paged(page, limit)

    total = db.execute(sqltext("""
        SELECT count(*) FROM containermgmt.product_suppliers ps
        JOIN containermgmt.products pr ON pr.id = ps.product_id
        WHERE ps.supplier_id = :id AND ps.is_deleted IS NOT TRUE
          AND pr.is_deleted IS NOT TRUE
    """), {"id": id}).scalar() or 0

    rows = db.execute(sqltext("""
        SELECT ps.id AS link_id, ps.product_id, pr.code, pr.sku, pr.name,
               pr.unit, ps.factory_code, ps.vendor_product_name,
               ps.unit_cost, ps.currency, ps.min_order_qty, ps.lead_time_days,
               ps.is_default, ps.notes,
               (pr.default_supplier_id = :id) AS is_product_default
        FROM containermgmt.product_suppliers ps
        JOIN containermgmt.products pr ON pr.id = ps.product_id
        WHERE ps.supplier_id = :id AND ps.is_deleted IS NOT TRUE
          AND pr.is_deleted IS NOT TRUE
        ORDER BY ps.is_default DESC, pr.name ASC
        LIMIT :limit OFFSET :offset
    """), {"id": id, "limit": l, "offset": offset}).mappings().all()

    items = [
        {
            "link_id": r["link_id"],
            "product_id": r["product_id"],
            "code": r["code"],
            "sku": r["sku"],
            "name": r["name"],
            "unit": r["unit"],
            # Their article number: the join key a shared catalogue will map
            # onto, and what a vendor actually quotes against.
            "factory_code": r["factory_code"],
            "vendor_product_name": r["vendor_product_name"],
            "unit_cost": float(r["unit_cost"]) if (show_money and r["unit_cost"] is not None) else None,
            "currency": r["currency"] if show_money else None,
            "min_order_qty": float(r["min_order_qty"]) if r["min_order_qty"] is not None else None,
            "lead_time_days": r["lead_time_days"],
            "is_preferred": bool(r["is_default"]),
            "is_product_default": bool(r["is_product_default"]),
            "notes": r["notes"],
        }
        for r in rows
    ]
    return _page_envelope(items, int(total), p, l)


@MasterDataRouter.get("/suppliers/{id}/orders")
def get_supplier_orders(
    id: int,
    page: Optional[int] = Query(None, ge=1),
    limit: Optional[int] = Query(None, ge=1, le=200),
    doc_type: Optional[str] = Query(None, description="PO or RFQ; both when omitted."),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """Orders and requisitions addressed to this vendor, in this user's scope.

    A shared vendor is used by several companies, and a user sees only the
    documents of the companies they belong to -- filtered in the query, so the
    pager counts what the user can actually open.
    """
    _supplier_or_404(db, id, org_context)
    show_money = is_financial_user(current_user, org_context)
    p, l, offset = _paged(page, limit)
    scope_sql, params = _org_scope(org_context)
    params = {**params, "id": id}

    type_sql = ""
    if doc_type:
        type_sql = " AND doc_type = :doc_type"
        params["doc_type"] = doc_type.strip().upper()

    total = db.execute(sqltext(f"""
        SELECT count(*) FROM containermgmt.purchase_orders
        WHERE supplier_id = :id AND is_deleted IS NOT TRUE AND {scope_sql}{type_sql}
    """), params).scalar() or 0

    rows = db.execute(sqltext(f"""
        SELECT id, po_number, doc_type, lifecycle_stage, status_label, status,
               order_mail_date, created_at, currency, total_amount, org_id
        FROM containermgmt.purchase_orders
        WHERE supplier_id = :id AND is_deleted IS NOT TRUE AND {scope_sql}{type_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": l, "offset": offset}).mappings().all()

    items = [
        {
            "id": r["id"],
            "po_number": r["po_number"],
            "doc_type": r["doc_type"],
            "lifecycle_stage": r["lifecycle_stage"],
            "status": r["status_label"] or r["status"],
            # order_mail_date is when it went to the vendor; created_at is
            # when it was raised, which every document has.
            "order_date": (r["order_mail_date"] or r["created_at"]).isoformat() if (r["order_mail_date"] or r["created_at"]) else None,
            "currency": r["currency"] if show_money else None,
            "total_amount": float(r["total_amount"]) if (show_money and r["total_amount"] is not None) else None,
            "org_id": r["org_id"],
        }
        for r in rows
    ]
    return _page_envelope(items, int(total), p, l)


@MasterDataRouter.get("/suppliers/{id}/quotes")
def get_supplier_quotes(
    id: int,
    page: Optional[int] = Query(None, ge=1),
    limit: Optional[int] = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """What this vendor has quoted, newest first.

    Quote amounts are financial data, so the list is refused outright rather
    than served with its numbers stripped: a quote with no price is not a quote.
    """
    _supplier_or_404(db, id, org_context)
    if not is_financial_user(current_user, org_context):
        raise HTTPException(
            status_code=403,
            detail="Quote history needs financial access.",
        )
    p, l, offset = _paged(page, limit)
    scope_sql, params = _org_scope(org_context)
    params = {**params, "id": id}

    total = db.execute(sqltext(f"""
        SELECT count(*) FROM containermgmt.vendor_quotes q
        JOIN containermgmt.purchase_orders po ON po.id = q.po_id
        WHERE q.supplier_id = :id AND q.is_deleted IS NOT TRUE AND po.{scope_sql}
    """), params).scalar() or 0

    rows = db.execute(sqltext(f"""
        SELECT q.id, q.quote_reference, q.quote_date, q.valid_until,
               q.total_quoted_amount, q.currency, q.status, q.rank,
               q.delivery_lead_time_days, po.po_number, po.id AS po_id
        FROM containermgmt.vendor_quotes q
        JOIN containermgmt.purchase_orders po ON po.id = q.po_id
        WHERE q.supplier_id = :id AND q.is_deleted IS NOT TRUE AND po.{scope_sql}
        ORDER BY q.quote_date DESC, q.id DESC
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": l, "offset": offset}).mappings().all()

    items = [
        {
            "id": r["id"],
            "quote_reference": r["quote_reference"],
            "quote_date": r["quote_date"].isoformat() if r["quote_date"] else None,
            "valid_until": r["valid_until"].isoformat() if r["valid_until"] else None,
            "total_quoted_amount": float(r["total_quoted_amount"] or 0),
            "currency": r["currency"],
            "status": r["status"],
            "rank": r["rank"],
            "lead_time_days": r["delivery_lead_time_days"],
            "po_number": r["po_number"],
            "po_id": r["po_id"],
        }
        for r in rows
    ]
    return _page_envelope(items, int(total), p, l)



# ── 4c. Who they are, and merging two rows that are one vendor ──────────────

# The claims worth recording. Anything else is a note, not an identifier.
IDENTIFIER_TYPES = ("TAX", "VAT", "REGISTRATION", "GLN", "DUNS", "LEI", "OTHER")


class SupplierIdentifierSchema(BaseModel):
    id_type: str
    value: str
    country: Optional[str] = None
    is_primary: Optional[bool] = False
    notes: Optional[str] = None


class SupplierMergeSchema(BaseModel):
    into_supplier_id: int
    reason: str


class SupplierRetireSchema(BaseModel):
    reason: str


def _require_reason(reason: Optional[str], message: str) -> str:
    """A reason, or a 422. The same rule as a revision or a revoked award.

    Five characters is not a quality bar; it rejects "x" and "ok" while leaving
    the judgement to the person. What matters is that the record exists, because
    months later it is the only thing that explains the decision.
    """
    cleaned = (reason or "").strip()
    if len(cleaned) < 5:
        raise HTTPException(status_code=422, detail=message)
    return cleaned


def _assert_may_edit_supplier(supplier: Supplier, org_context: OrgContext, current_user) -> None:
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance or Admin users can change suppliers.")
    if supplier.is_shared and not org_context.is_root:
        raise HTTPException(status_code=403, detail="Shared suppliers are managed by the root organisation.")


@MasterDataRouter.get("/suppliers/{id}/identifiers")
def list_supplier_identifiers(
    id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    _supplier_or_404(db, id, org_context)
    return {"items": _identifier_rows(db, id), "types": list(IDENTIFIER_TYPES)}


@MasterDataRouter.post("/suppliers/{id}/identifiers")
def add_supplier_identifier(
    id: int,
    payload: SupplierIdentifierSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """Record a tax or registration number against a vendor.

    Unverified on purpose: the row says what the vendor claims, and someone
    checking it against a register later is a separate, recorded act.
    """
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)

    id_type = (payload.id_type or "").strip().upper()
    if id_type not in IDENTIFIER_TYPES:
        raise HTTPException(status_code=400, detail=(
            f"'{id_type}' is not an identifier type. Use one of: {', '.join(IDENTIFIER_TYPES)}."))
    value = (payload.value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="An identifier needs a value.")
    country = (payload.country or "").strip() or None

    # The same registration number in the same country is the same company.
    # Said here with the holder named, rather than left to the unique index.
    clash = db.execute(sqltext("""
        SELECT i.supplier_id, s.name, s.code
        FROM containermgmt.supplier_identifiers i
        JOIN containermgmt.supplier s ON s.supplier_id = i.supplier_id
        WHERE i.is_deleted IS NOT TRUE AND i.id_type = :t
          AND lower(coalesce(i.country, '')) = lower(coalesce(:c, ''))
          AND lower(trim(i.value)) = lower(:v)
        LIMIT 1
    """), {"t": id_type, "c": country, "v": value}).mappings().first()
    if clash:
        if clash["supplier_id"] == id:
            raise HTTPException(status_code=409, detail="This vendor already holds that identifier.")
        raise HTTPException(status_code=409, detail=(
            f"{id_type} {value} is already recorded against '{clash['name']}' "
            f"({clash['code']}). If they are the same company, merge the two records."))

    if payload.is_primary:
        db.execute(sqltext("""
            UPDATE containermgmt.supplier_identifiers SET is_primary = FALSE
            WHERE supplier_id = :id AND is_deleted IS NOT TRUE
        """), {"id": id})

    new_id = db.execute(sqltext("""
        INSERT INTO containermgmt.supplier_identifiers
            (supplier_id, id_type, country, value, is_primary, notes, created_by)
        VALUES (:id, :t, :c, :v, :p, :n, :u)
        RETURNING id
    """), {
        "id": id, "t": id_type, "c": country, "v": value,
        "p": bool(payload.is_primary), "n": (payload.notes or "").strip() or None,
        "u": getattr(current_user, "id", None),
    }).scalar()

    record_event(
        db, "supplier", id, "identifier_added", getattr(current_user, "id", None),
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name=id_type, new_value=value,
    )
    db.commit()
    sync_supplier_document(supplier, [i["value"] for i in _identifier_rows(db, id)])
    return {"success": True, "id": new_id, "items": _identifier_rows(db, id)}


@MasterDataRouter.post("/suppliers/{id}/identifiers/{identifier_id}/verify")
def verify_supplier_identifier(
    id: int,
    identifier_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """Mark an identifier as checked, by whom and when.

    Only the fact is recorded here. What counts as a check -- a public register,
    a certificate on file -- is a policy decision, and the audit row is what
    makes it reviewable either way.
    """
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)
    updated = db.execute(sqltext("""
        UPDATE containermgmt.supplier_identifiers
        SET verified_at = now(), verified_by = :u, updated_by = :u
        WHERE id = :iid AND supplier_id = :id AND is_deleted IS NOT TRUE
    """), {"iid": identifier_id, "id": id, "u": getattr(current_user, "id", None)}).rowcount
    if not updated:
        raise HTTPException(status_code=404, detail="Identifier not found.")
    record_event(
        db, "supplier", id, "identifier_verified", getattr(current_user, "id", None),
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name=str(identifier_id), new_value="verified",
    )
    db.commit()
    sync_supplier_document(supplier, [i["value"] for i in _identifier_rows(db, id)])
    return {"success": True, "items": _identifier_rows(db, id)}


@MasterDataRouter.delete("/suppliers/{id}/identifiers/{identifier_id}")
def remove_supplier_identifier(
    id: int,
    identifier_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)
    # Soft, like everything else here: a number that was once recorded against a
    # vendor is part of why a payment or a document was accepted.
    updated = db.execute(sqltext("""
        UPDATE containermgmt.supplier_identifiers
        SET is_deleted = TRUE, deleted_at = now(), deleted_by = :u
        WHERE id = :iid AND supplier_id = :id AND is_deleted IS NOT TRUE
    """), {"iid": identifier_id, "id": id, "u": getattr(current_user, "id", None)}).rowcount
    if not updated:
        raise HTTPException(status_code=404, detail="Identifier not found.")
    record_event(
        db, "supplier", id, "identifier_removed", getattr(current_user, "id", None),
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name=str(identifier_id), old_value="present", new_value=None,
    )
    db.commit()
    sync_supplier_document(supplier, [i["value"] for i in _identifier_rows(db, id)])
    return {"success": True, "items": _identifier_rows(db, id)}


# ── 4d. The people and the places a vendor has ──────────────────────────────
#
# One contact_person and one address on the supplier row cannot hold what a
# vendor actually is: a salesperson and someone in accounts, a registered
# office that is not the factory. Each is a row, each knows what it is for, and
# the row marked primary keeps the old single fields on the supplier correct so
# that nothing still reading them shows something different.

CONTACT_ROLES = ("SALES", "ACCOUNTS", "LOGISTICS", "ESCALATION", "OTHER")
ADDRESS_TYPES = ("REGISTERED", "FACTORY", "WAREHOUSE", "REMIT_TO", "OTHER")


class SupplierContactSchema(BaseModel):
    name: str
    role: Optional[str] = None
    job_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    is_primary: bool = False
    notes: Optional[str] = None


class SupplierAddressSchema(BaseModel):
    address_type: Optional[str] = "OTHER"
    label: Optional[str] = None
    line1: Optional[str] = None
    line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    is_primary: bool = False
    notes: Optional[str] = None


def _contact_rows(db: Session, supplier_id: int) -> list:
    rows = db.execute(sqltext("""
        SELECT id, name, role, job_title, email, phone, mobile, is_primary, notes
        FROM containermgmt.supplier_contacts
        WHERE supplier_id = :id AND is_deleted IS NOT TRUE
        ORDER BY is_primary DESC, name ASC
    """), {"id": supplier_id}).mappings().all()
    return [dict(r) for r in rows]


def _address_rows(db: Session, supplier_id: int) -> list:
    rows = db.execute(sqltext("""
        SELECT id, address_type, label, line1, line2, city, state, postal_code,
               country, is_primary, notes
        FROM containermgmt.supplier_addresses
        WHERE supplier_id = :id AND is_deleted IS NOT TRUE
        ORDER BY is_primary DESC, address_type ASC, id ASC
    """), {"id": supplier_id}).mappings().all()
    return [dict(r) for r in rows]


def _clear_other_primaries(db: Session, table: str, supplier_id: int, keep_id: Optional[int] = None) -> None:
    """One primary per vendor.

    The unique index enforces it, so demoting the previous holder has to happen
    in the same transaction as promoting the new one -- otherwise the insert
    fails on an index nobody asked about.
    """
    sql = f"""
        UPDATE containermgmt.{table} SET is_primary = FALSE
        WHERE supplier_id = :id AND is_primary IS TRUE AND is_deleted IS NOT TRUE
    """
    params = {"id": supplier_id}
    if keep_id is not None:
        sql += " AND id <> :keep"
        params["keep"] = keep_id
    db.execute(sqltext(sql), params)


def _sync_primary_contact(db: Session, supplier: Supplier) -> None:
    """Keep the supplier's own contact fields showing the primary contact.

    Every screen, print template and export that reads contact_person, email or
    phone keeps working, and keeps agreeing with the contacts tab.
    """
    primary = db.execute(sqltext("""
        SELECT name, email, phone, mobile FROM containermgmt.supplier_contacts
        WHERE supplier_id = :id AND is_primary IS TRUE AND is_deleted IS NOT TRUE
        LIMIT 1
    """), {"id": supplier.supplier_id}).mappings().first()
    if not primary:
        return
    supplier.contact_person = primary["name"]
    if primary["email"]:
        supplier.email = primary["email"]
    if primary["phone"] or primary["mobile"]:
        supplier.phone = primary["phone"] or primary["mobile"]


def _sync_primary_address(db: Session, supplier: Supplier) -> None:
    """Keep the supplier's single address field showing the primary address."""
    primary = db.execute(sqltext("""
        SELECT line1, line2, city, state, postal_code, country
        FROM containermgmt.supplier_addresses
        WHERE supplier_id = :id AND is_primary IS TRUE AND is_deleted IS NOT TRUE
        LIMIT 1
    """), {"id": supplier.supplier_id}).mappings().first()
    if not primary:
        return
    parts = [primary[k] for k in ("line1", "line2", "city", "state", "postal_code") if primary[k]]
    one_line = ", ".join(str(p).strip() for p in parts)
    if one_line:
        supplier.address = one_line[:255]
    if primary["country"] and not supplier.country:
        supplier.country = primary["country"]


@MasterDataRouter.get("/suppliers/{id}/contacts")
def list_supplier_contacts(
    id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    _supplier_or_404(db, id, org_context)
    return {"items": _contact_rows(db, id), "roles": list(CONTACT_ROLES)}


@MasterDataRouter.post("/suppliers/{id}/contacts")
def add_supplier_contact(
    id: int,
    payload: SupplierContactSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A contact needs a name.")
    role = (payload.role or "OTHER").strip().upper()
    if role not in CONTACT_ROLES:
        raise HTTPException(status_code=400, detail=(
            f"'{role}' is not a contact role. Use one of: {', '.join(CONTACT_ROLES)}."))

    # The first contact is the primary one whether or not anyone said so: a
    # vendor with contacts and no primary is a vendor whose purchase order has
    # nobody to address.
    existing = _contact_rows(db, id)
    make_primary = bool(payload.is_primary) or not existing
    if make_primary:
        _clear_other_primaries(db, "supplier_contacts", id)

    new_id = db.execute(sqltext("""
        INSERT INTO containermgmt.supplier_contacts
            (supplier_id, name, role, job_title, email, phone, mobile, is_primary, notes, created_by)
        VALUES (:id, :n, :r, :jt, :e, :p, :m, :pr, :no, :u)
        RETURNING id
    """), {
        "id": id, "n": name, "r": role,
        "jt": (payload.job_title or "").strip() or None,
        "e": (payload.email or "").strip() or None,
        "p": (payload.phone or "").strip() or None,
        "m": (payload.mobile or "").strip() or None,
        "pr": make_primary, "no": (payload.notes or "").strip() or None,
        "u": getattr(current_user, "id", None),
    }).scalar()

    if make_primary:
        _sync_primary_contact(db, supplier)
    record_event(
        db, "supplier", id, "contact_added", getattr(current_user, "id", None),
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name=role, new_value=name,
    )
    db.commit()
    return {"success": True, "id": new_id, "items": _contact_rows(db, id)}


@MasterDataRouter.put("/suppliers/{id}/contacts/{contact_id}")
def update_supplier_contact(
    id: int,
    contact_id: int,
    payload: SupplierContactSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A contact needs a name.")
    role = (payload.role or "OTHER").strip().upper()
    if role not in CONTACT_ROLES:
        raise HTTPException(status_code=400, detail=(
            f"'{role}' is not a contact role. Use one of: {', '.join(CONTACT_ROLES)}."))

    if payload.is_primary:
        _clear_other_primaries(db, "supplier_contacts", id, keep_id=contact_id)

    updated = db.execute(sqltext("""
        UPDATE containermgmt.supplier_contacts
        SET name = :n, role = :r, job_title = :jt, email = :e, phone = :p,
            mobile = :m, is_primary = :pr, notes = :no,
            updated_at = now(), updated_by = :u
        WHERE id = :cid AND supplier_id = :id AND is_deleted IS NOT TRUE
    """), {
        "cid": contact_id, "id": id, "n": name, "r": role,
        "jt": (payload.job_title or "").strip() or None,
        "e": (payload.email or "").strip() or None,
        "p": (payload.phone or "").strip() or None,
        "m": (payload.mobile or "").strip() or None,
        "pr": bool(payload.is_primary), "no": (payload.notes or "").strip() or None,
        "u": getattr(current_user, "id", None),
    }).rowcount
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found.")

    if payload.is_primary:
        _sync_primary_contact(db, supplier)
    record_event(
        db, "supplier", id, "contact_updated", getattr(current_user, "id", None),
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name=role, new_value=name,
    )
    db.commit()
    return {"success": True, "items": _contact_rows(db, id)}


@MasterDataRouter.delete("/suppliers/{id}/contacts/{contact_id}")
def remove_supplier_contact(
    id: int,
    contact_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)

    row = db.execute(sqltext("""
        SELECT name, is_primary FROM containermgmt.supplier_contacts
        WHERE id = :cid AND supplier_id = :id AND is_deleted IS NOT TRUE
    """), {"cid": contact_id, "id": id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found.")

    db.execute(sqltext("""
        UPDATE containermgmt.supplier_contacts
        SET is_deleted = TRUE, deleted_at = now(), deleted_by = :u, is_primary = FALSE
        WHERE id = :cid AND supplier_id = :id
    """), {"cid": contact_id, "id": id, "u": getattr(current_user, "id", None)})

    # Removing the primary leaves no primary, so the oldest remaining contact
    # takes over rather than the vendor being left with nobody.
    if row["is_primary"]:
        heir = db.execute(sqltext("""
            SELECT id FROM containermgmt.supplier_contacts
            WHERE supplier_id = :id AND is_deleted IS NOT TRUE
            ORDER BY id ASC LIMIT 1
        """), {"id": id}).scalar()
        if heir:
            db.execute(sqltext("UPDATE containermgmt.supplier_contacts SET is_primary = TRUE WHERE id = :h"), {"h": heir})
            _sync_primary_contact(db, supplier)

    record_event(
        db, "supplier", id, "contact_removed", getattr(current_user, "id", None),
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name=str(contact_id), old_value=row["name"], new_value=None,
    )
    db.commit()
    return {"success": True, "items": _contact_rows(db, id)}


@MasterDataRouter.get("/suppliers/{id}/addresses")
def list_supplier_addresses(
    id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    _supplier_or_404(db, id, org_context)
    return {"items": _address_rows(db, id), "types": list(ADDRESS_TYPES)}


@MasterDataRouter.post("/suppliers/{id}/addresses")
def add_supplier_address(
    id: int,
    payload: SupplierAddressSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)

    address_type = (payload.address_type or "OTHER").strip().upper()
    if address_type not in ADDRESS_TYPES:
        raise HTTPException(status_code=400, detail=(
            f"'{address_type}' is not an address type. Use one of: {', '.join(ADDRESS_TYPES)}."))
    if not (payload.line1 or "").strip() and not (payload.city or "").strip():
        raise HTTPException(status_code=400, detail="An address needs at least a street or a city.")

    existing = _address_rows(db, id)
    make_primary = bool(payload.is_primary) or not existing
    if make_primary:
        _clear_other_primaries(db, "supplier_addresses", id)

    new_id = db.execute(sqltext("""
        INSERT INTO containermgmt.supplier_addresses
            (supplier_id, address_type, label, line1, line2, city, state,
             postal_code, country, is_primary, notes, created_by)
        VALUES (:id, :t, :l, :l1, :l2, :c, :s, :pc, :co, :pr, :no, :u)
        RETURNING id
    """), {
        "id": id, "t": address_type,
        "l": (payload.label or "").strip() or None,
        "l1": (payload.line1 or "").strip() or None,
        "l2": (payload.line2 or "").strip() or None,
        "c": (payload.city or "").strip() or None,
        "s": (payload.state or "").strip() or None,
        "pc": (payload.postal_code or "").strip() or None,
        "co": (payload.country or "").strip() or None,
        "pr": make_primary, "no": (payload.notes or "").strip() or None,
        "u": getattr(current_user, "id", None),
    }).scalar()

    if make_primary:
        _sync_primary_address(db, supplier)
    record_event(
        db, "supplier", id, "address_added", getattr(current_user, "id", None),
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name=address_type, new_value=(payload.line1 or payload.city or "")[:200] or None,
    )
    db.commit()
    return {"success": True, "id": new_id, "items": _address_rows(db, id)}


@MasterDataRouter.put("/suppliers/{id}/addresses/{address_id}")
def update_supplier_address(
    id: int,
    address_id: int,
    payload: SupplierAddressSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)

    address_type = (payload.address_type or "OTHER").strip().upper()
    if address_type not in ADDRESS_TYPES:
        raise HTTPException(status_code=400, detail=(
            f"'{address_type}' is not an address type. Use one of: {', '.join(ADDRESS_TYPES)}."))

    if payload.is_primary:
        _clear_other_primaries(db, "supplier_addresses", id, keep_id=address_id)

    updated = db.execute(sqltext("""
        UPDATE containermgmt.supplier_addresses
        SET address_type = :t, label = :l, line1 = :l1, line2 = :l2, city = :c,
            state = :s, postal_code = :pc, country = :co, is_primary = :pr,
            notes = :no, updated_at = now(), updated_by = :u
        WHERE id = :aid AND supplier_id = :id AND is_deleted IS NOT TRUE
    """), {
        "aid": address_id, "id": id, "t": address_type,
        "l": (payload.label or "").strip() or None,
        "l1": (payload.line1 or "").strip() or None,
        "l2": (payload.line2 or "").strip() or None,
        "c": (payload.city or "").strip() or None,
        "s": (payload.state or "").strip() or None,
        "pc": (payload.postal_code or "").strip() or None,
        "co": (payload.country or "").strip() or None,
        "pr": bool(payload.is_primary), "no": (payload.notes or "").strip() or None,
        "u": getattr(current_user, "id", None),
    }).rowcount
    if not updated:
        raise HTTPException(status_code=404, detail="Address not found.")

    if payload.is_primary:
        _sync_primary_address(db, supplier)
    record_event(
        db, "supplier", id, "address_updated", getattr(current_user, "id", None),
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name=address_type, new_value=(payload.line1 or payload.city or "")[:200] or None,
    )
    db.commit()
    return {"success": True, "items": _address_rows(db, id)}


@MasterDataRouter.delete("/suppliers/{id}/addresses/{address_id}")
def remove_supplier_address(
    id: int,
    address_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)

    row = db.execute(sqltext("""
        SELECT address_type, line1, is_primary FROM containermgmt.supplier_addresses
        WHERE id = :aid AND supplier_id = :id AND is_deleted IS NOT TRUE
    """), {"aid": address_id, "id": id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Address not found.")

    db.execute(sqltext("""
        UPDATE containermgmt.supplier_addresses
        SET is_deleted = TRUE, deleted_at = now(), deleted_by = :u, is_primary = FALSE
        WHERE id = :aid AND supplier_id = :id
    """), {"aid": address_id, "id": id, "u": getattr(current_user, "id", None)})

    if row["is_primary"]:
        heir = db.execute(sqltext("""
            SELECT id FROM containermgmt.supplier_addresses
            WHERE supplier_id = :id AND is_deleted IS NOT TRUE
            ORDER BY id ASC LIMIT 1
        """), {"id": id}).scalar()
        if heir:
            db.execute(sqltext("UPDATE containermgmt.supplier_addresses SET is_primary = TRUE WHERE id = :h"), {"h": heir})
            _sync_primary_address(db, supplier)

    record_event(
        db, "supplier", id, "address_removed", getattr(current_user, "id", None),
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name=str(address_id), old_value=row["line1"] or row["address_type"], new_value=None,
    )
    db.commit()
    return {"success": True, "items": _address_rows(db, id)}


# ── 4e. What happened to this vendor ────────────────────────────────────────
#
# Every write on a supplier has recorded an audit row since the merge and
# retirement work: which field, from what, to what, by whom, when. Nothing read
# them back, so the answer to "who changed the payment terms" existed in the
# database and nowhere a buyer could reach -- and the reasons captured on merge
# and retirement were written and never shown.

# Plain language for the actions the supplier endpoints record. Anything not
# listed falls back to its own name with the underscores removed, so a new
# event appears in the feed the day it is first recorded rather than silently
# vanishing from it.
ACTIVITY_LABELS = {
    "created": "Vendor created",
    "updated": "Changed",
    "deleted": "Retired",
    "retired": "Retired",
    "merged_away": "Merged into another vendor",
    "merged_in": "Another vendor merged into this one",
    "identifier_added": "Identifier recorded",
    "identifier_verified": "Identifier verified",
    "identifier_removed": "Identifier removed",
    "contact_added": "Contact added",
    "contact_updated": "Contact changed",
    "contact_removed": "Contact removed",
    "address_added": "Address added",
    "address_updated": "Address changed",
    "address_removed": "Address removed",
}

ACTIVITY_FIELD_LABELS = {
    "name": "name",
    "code": "vendor code",
    "address": "address",
    "email": "email",
    "phone": "phone",
    "contact_person": "contact person",
    "country": "country",
    "default_currency": "default currency",
    "default_payment_term_id": "payment terms",
    "variance_threshold_pct": "variance threshold",
    "is_active": "status",
    "is_shared": "visibility",
    "is_deleted": "retirement",
    "notes": "notes",
    "merge_reason": "merge",
    "retire_reason": "retirement",
}

# A contact's role and an address's type are recorded in field_name, so the
# sentence has to read them as words rather than as the enum the table holds.
ACTIVITY_KIND_WORDS = {
    "SALES": "sales",
    "ACCOUNTS": "accounts",
    "LOGISTICS": "logistics",
    "ESCALATION": "escalation",
    "REGISTERED": "registered office",
    "FACTORY": "factory",
    "WAREHOUSE": "warehouse",
    "REMIT_TO": "remit to",
    "OTHER": "other",
}

# An action whose detail is nobody's business without the permission that
# governs it. Bank accounts are not built yet; the filter is here so the feed
# cannot start leaking them the day they are.
ACTIVITY_FINANCIAL_PREFIXES = ("bank", "payment_account")


def _activity_sentence(action: str, field: Optional[str], old, new) -> str:
    """One readable line for one recorded change.

    Built on the server so the feed, an export and anything else that reads it
    tell the same story, rather than each re-deriving it from column values.
    """
    label = ACTIVITY_LABELS.get(action) or action.replace("_", " ").capitalize()
    field_label = ACTIVITY_FIELD_LABELS.get(field or "", (field or "").replace("_", " "))

    if action in ("updated",) and field:
        if old and new:
            return f"Changed {field_label} from “{old}” to “{new}”"
        if new:
            return f"Set {field_label} to “{new}”"
        if old:
            return f"Cleared {field_label} (was “{old}”)"
        return f"Changed {field_label}"

    if action in ("merged_away", "merged_in") and new:
        return f"{label}: {new}"

    if action in ("deleted", "retired"):
        # The reason, when there is one, is the only part worth reading.
        return f"{label}{f' — {new}' if new and new not in ('true', 'True') else ''}"

    detail = new or old
    # A contact or an address records its role or its type where a field edit
    # would record a column, so it is read as a kind, not as a field.
    # "Identifier verified: verified" says it twice; the label already said it.
    if detail and detail.lower() in label.lower():
        detail = None
    kind = ACTIVITY_KIND_WORDS.get((field or "").upper())
    if kind and detail:
        return f"{label}: {detail} ({kind})"
    if detail and field and not (field or "").isdigit():
        return f"{label}: {field} {detail}"
    if detail:
        return f"{label}: {detail}"
    if field_label and not (field or "").isdigit():
        return f"{label} ({field_label})"
    return label


@MasterDataRouter.get("/suppliers/{id}/activity")
def get_supplier_activity(
    id: int,
    page: Optional[int] = Query(None, ge=1),
    limit: Optional[int] = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """Who changed this vendor, what they changed it from, and when.

    A shared vendor is edited by one company and seen by all of them, so an
    event belongs either to the shared record itself -- recorded with no
    org_id -- or to one company, and a user sees the shared ones plus their
    own. Scoped in the query, so the pager counts what the user can read.
    """
    _supplier_or_404(db, id, org_context)
    p, l, offset = _paged(page, limit)

    # Shared-record events carry no org_id; company events carry theirs.
    if org_context.selected_org_id:
        scope_sql = "(a.org_id IS NULL OR a.org_id = :scope_org)"
        params = {"scope_org": org_context.selected_org_id}
    else:
        allowed = list(org_context.allowed_org_ids or [])
        if allowed:
            scope_sql = "(a.org_id IS NULL OR a.org_id = ANY(:scope_orgs))"
            params = {"scope_orgs": allowed}
        else:
            scope_sql = "a.org_id IS NULL"
            params = {}

    hide_financial = not is_financial_user(current_user, org_context)
    money_sql = ""
    if hide_financial:
        money_sql = " AND NOT (" + " OR ".join(
            f"a.action LIKE '{prefix}%'" for prefix in ACTIVITY_FINANCIAL_PREFIXES
        ) + ")"

    params["id"] = id
    total = db.execute(sqltext(f"""
        SELECT count(*) FROM containermgmt.master_data_audit a
        WHERE a.entity_type = 'supplier' AND a.entity_id = :id
          AND {scope_sql}{money_sql}
    """), params).scalar() or 0

    rows = db.execute(sqltext(f"""
        SELECT a.id, a.action, a.field_name, a.old_value, a.new_value,
               a.changed_at, a.changed_by, a.org_id, u.username
        FROM containermgmt.master_data_audit a
        LEFT JOIN usercredentials.users u ON u.id = a.changed_by
        WHERE a.entity_type = 'supplier' AND a.entity_id = :id
          AND {scope_sql}{money_sql}
        ORDER BY a.changed_at DESC, a.id DESC
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": l, "offset": offset}).mappings().all()

    items = [
        {
            "id": r["id"],
            "action": r["action"],
            "label": ACTIVITY_LABELS.get(r["action"]) or r["action"].replace("_", " ").capitalize(),
            "summary": _activity_sentence(r["action"], r["field_name"], r["old_value"], r["new_value"]),
            "field_name": r["field_name"],
            "field_label": ACTIVITY_FIELD_LABELS.get(r["field_name"] or "") or (r["field_name"] or None),
            "old_value": r["old_value"],
            "new_value": r["new_value"],
            "changed_at": r["changed_at"].isoformat() if r["changed_at"] else None,
            # The username, or nothing: an event recorded by a job has no actor,
            # and inventing one would be worse than saying so.
            "actor": r["username"],
            "actor_id": r["changed_by"],
            "org_id": r["org_id"],
            "is_shared_event": r["org_id"] is None,
        }
        for r in rows
    ]
    return _page_envelope(items, int(total), p, l)


# Every column in the database that points at supplier.supplier_id, read from
# the live schema rather than listed by hand, so a reference added later cannot
# be missed by a merge.
_SUPPLIER_FK_QUERY = """
    SELECT tc.table_schema, tc.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name
    JOIN information_schema.constraint_column_usage ccu
      ON ccu.constraint_name = tc.constraint_name
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND ccu.table_schema = 'containermgmt'
      AND ccu.table_name = 'supplier'
      AND ccu.column_name = 'supplier_id'
"""

# Filled on the survivor only where it has nothing, so a merge adds detail and
# never overwrites it.
_MERGE_FILLABLE = (
    "address", "email", "phone", "contact_person", "country", "logo_url",
    "default_currency", "default_payment_term_id", "notes",
)


@MasterDataRouter.get("/suppliers/{id}/merge-preview")
def preview_supplier_merge(
    id: int,
    into_supplier_id: int = Query(..., description="The record that survives."),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """What a merge would move, before anyone agrees to it."""
    loser = _supplier_or_404(db, id, org_context)
    survivor = _supplier_or_404(db, into_supplier_id, org_context)
    if loser.supplier_id == survivor.supplier_id:
        raise HTTPException(status_code=400, detail="A supplier cannot be merged into itself.")
    return {
        "from": {"id": loser.supplier_id, "name": loser.name, "code": loser.code,
                 "usage": _supplier_usage(db, loser.supplier_id)},
        "into": {"id": survivor.supplier_id, "name": survivor.name, "code": survivor.code,
                 "usage": _supplier_usage(db, survivor.supplier_id)},
        "fields_to_fill": [
            field for field in _MERGE_FILLABLE
            if not getattr(survivor, field, None) and getattr(loser, field, None)
        ],
        "identifiers_to_move": _identifier_rows(db, loser.supplier_id),
    }


@MasterDataRouter.post("/suppliers/{id}/merge")
def merge_supplier(
    id: int,
    payload: SupplierMergeSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """Two rows that are one vendor become one row, with nothing orphaned.

    The one-off migration merged the duplicates the import created, by name.
    New ones keep arriving, and a name match cannot be trusted for this: it is
    a judgement a person makes, with a reason, and this is where they record it.

    Everything pointing at the merged record is repointed at the survivor, the
    survivor keeps every value it already had, and the loser is retired rather
    than deleted so its code and history stay readable.
    """
    loser = _supplier_or_404(db, id, org_context)
    survivor = _supplier_or_404(db, payload.into_supplier_id, org_context)
    _assert_may_edit_supplier(loser, org_context, current_user)
    _assert_may_edit_supplier(survivor, org_context, current_user)

    if loser.supplier_id == survivor.supplier_id:
        raise HTTPException(status_code=400, detail="A supplier cannot be merged into itself.")
    reason = _require_reason(payload.reason, (
        "Say why these two records are the same vendor. The reason is kept "
        "with the merge, and it is the only thing that explains it later."))

    user_id = getattr(current_user, "id", None)
    moved = {}

    for field in _MERGE_FILLABLE:
        if not getattr(survivor, field, None) and getattr(loser, field, None):
            setattr(survivor, field, getattr(loser, field))

    references = [
        (row.table_schema, row.table_name, row.column_name)
        for row in db.execute(sqltext(_SUPPLIER_FK_QUERY))
    ]
    for schema, table, column in references:
        if table == "supplier_identifiers":
            continue  # handled below, where a clash is possible
        result = db.execute(sqltext(
            f'UPDATE {schema}.{table} SET "{column}" = :survivor WHERE "{column}" = :loser'
        ), {"survivor": survivor.supplier_id, "loser": loser.supplier_id})
        if result.rowcount:
            moved[f"{table}.{column}"] = result.rowcount

    # Identifiers move unless the survivor already holds the same claim -- the
    # unique index would reject the duplicate, and the claim is already there.
    db.execute(sqltext("""
        UPDATE containermgmt.supplier_identifiers i
        SET supplier_id = :survivor, is_primary = FALSE, updated_by = :u
        WHERE i.supplier_id = :loser AND i.is_deleted IS NOT TRUE
          AND NOT EXISTS (
            SELECT 1 FROM containermgmt.supplier_identifiers k
            WHERE k.supplier_id = :survivor AND k.is_deleted IS NOT TRUE
              AND k.id_type = i.id_type
              AND lower(coalesce(k.country, '')) = lower(coalesce(i.country, ''))
              AND lower(trim(k.value)) = lower(trim(i.value))
          )
    """), {"survivor": survivor.supplier_id, "loser": loser.supplier_id, "u": user_id})

    # Whatever did not move is a claim the survivor already holds, so it is
    # retired rather than left pointing at a merged-away record.
    db.execute(sqltext("""
        UPDATE containermgmt.supplier_identifiers
        SET is_deleted = TRUE, deleted_at = now(), deleted_by = :u
        WHERE supplier_id = :loser AND is_deleted IS NOT TRUE
    """), {"loser": loser.supplier_id, "u": user_id})

    # Repointing can list the same product against the survivor twice;
    # product_suppliers has no uniqueness constraint to stop it.
    db.execute(sqltext("""
        DELETE FROM containermgmt.product_suppliers a
        USING containermgmt.product_suppliers b
        WHERE a.supplier_id = :survivor AND b.supplier_id = :survivor
          AND a.product_id = b.product_id AND a.id > b.id
    """), {"survivor": survivor.supplier_id})

    # Nothing may still point at the record being merged away. A half-merge is
    # worse than no merge: the history splits across two rows and looks
    # authoritative on both.
    db.flush()
    orphans = {}
    for schema, table, column in references:
        if table == "supplier_identifiers":
            # Duplicate claims stay on the loser, soft-deleted: they are a
            # record of what was once held against that row, not a live link.
            continue
        left = db.execute(sqltext(
            f'SELECT count(*) FROM {schema}.{table} WHERE "{column}" = :loser'
        ), {"loser": loser.supplier_id}).scalar() or 0
        if left:
            orphans[f"{table}.{column}"] = int(left)
    if orphans:
        db.rollback()
        raise HTTPException(status_code=409, detail=(
            "The merge was stopped: some records still point at "
            f"{loser.code or loser.name} ({orphans}). Nothing was changed."))

    loser.is_active = False
    loser.is_deleted = True
    loser.deleted_by = user_id
    merged_note = (
        f"Merged into {survivor.code or survivor.name} on "
        f"{date.today().isoformat()}: {reason}"
    )
    loser.notes = f"{loser.notes}\n{merged_note}" if loser.notes else merged_note

    for entity_id, action, old, new in (
        (loser.supplier_id, "merged_away", loser.code, survivor.code),
        (survivor.supplier_id, "merged_in", loser.code, survivor.code),
    ):
        record_event(
            db, "supplier", entity_id, action, user_id,
            org_id=None if survivor.is_shared else survivor.org_id,
            field_name="merge_reason", old_value=old, new_value=f"{new} — {reason}",
        )
    db.commit()
    # The merged-away record must stop being findable, and the survivor's own
    # document now carries whatever moved onto it.
    remove_supplier_document(loser.supplier_id)
    sync_supplier_document(survivor, [i["value"] for i in _identifier_rows(db, survivor.supplier_id)])
    return {
        "success": True,
        "message": (
            f"'{loser.name}' merged into '{survivor.name}'. "
            f"{sum(moved.values())} reference(s) repointed."
        ),
        "survivor_id": survivor.supplier_id,
        "moved": moved,
    }


@MasterDataRouter.post("/suppliers/{id}/retire")
def retire_supplier(
    id: int,
    payload: SupplierRetireSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """Retire a vendor for good, with the reason on the record.

    Different from deactivation, which is reversible and leaves the vendor in
    the directory. Retirement takes it out of the directory for new work; every
    document that already names it is untouched and stays readable.
    """
    supplier = _supplier_or_404(db, id, org_context)
    _assert_may_edit_supplier(supplier, org_context, current_user)
    reason = _require_reason(payload.reason, (
        "Say why this vendor is being retired. It is a shared record, and "
        "the reason is what answers the question months later."))

    usage = _supplier_usage(db, id)
    user_id = getattr(current_user, "id", None)
    record_event(
        db, "supplier", id, "retired", user_id,
        org_id=None if supplier.is_shared else supplier.org_id,
        field_name="retirement_reason", old_value=None, new_value=reason,
    )
    note = f"Retired on {date.today().isoformat()}: {reason}"
    supplier.notes = f"{supplier.notes}\n{note}" if supplier.notes else note
    supplier.is_active = False
    supplier.is_deleted = True
    supplier.deleted_by = user_id
    db.commit()
    remove_supplier_document(supplier.supplier_id)
    return {
        "success": True,
        "message": f"'{supplier.name}' retired.",
        "was_used_by": usage,
    }


@MasterDataRouter.get("/products/supplier-terms")
def get_product_supplier_terms(
    product_ids: str = Query(..., description="Comma-separated product ids."),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """What vendors have told us about these products, for the entry screen.

    A minimum order quantity is only cheap to honour while the requisition is
    being typed. Discovered when the quote comes back, it costs a re-quote, a
    revision and an explanation; shown beside the quantity field, it costs
    nothing. The preferred vendor's terms win, because that is who the line is
    most likely going to.

    Batched on purpose: a requisition with twenty lines asks once.
    """
    wanted = []
    for raw in (product_ids or "").split(","):
        raw = raw.strip()
        if raw.isdigit():
            wanted.append(int(raw))
    wanted = wanted[:200]
    if not wanted:
        return {"items": {}}

    rows = db.execute(sqltext("""
        SELECT ps.product_id, ps.supplier_id, ps.min_order_qty, ps.lead_time_days,
               ps.factory_code, ps.is_default, s.name AS supplier_name, s.code AS supplier_code,
               count(*) OVER (PARTITION BY ps.product_id) AS vendor_count
        FROM containermgmt.product_suppliers ps
        JOIN containermgmt.supplier s ON s.supplier_id = ps.supplier_id
        WHERE ps.product_id = ANY(:ids) AND ps.is_deleted IS NOT TRUE
          AND s.is_deleted IS NOT TRUE AND s.is_active IS NOT FALSE
        ORDER BY ps.product_id,
                 ps.is_default DESC,
                 (ps.min_order_qty IS NOT NULL) DESC,
                 ps.min_order_qty DESC NULLS LAST
    """), {"ids": wanted}).mappings().all()

    terms = {}
    for r in rows:
        key = str(r["product_id"])
        if key in terms:
            continue  # the ordering already put the most relevant vendor first
        terms[key] = {
            "supplier_id": r["supplier_id"],
            "supplier_name": r["supplier_name"],
            "supplier_code": r["supplier_code"],
            "is_preferred": bool(r["is_default"]),
            "min_order_qty": float(r["min_order_qty"]) if r["min_order_qty"] is not None else None,
            "lead_time_days": r["lead_time_days"],
            "factory_code": r["factory_code"],
            "vendor_count": int(r["vendor_count"] or 1),
        }
    return {"items": terms}


@MasterDataRouter.get("/products/{product_id}/vendors")
def get_product_vendors(
    product_id: int,
    page: Optional[int] = Query(None, ge=1),
    limit: Optional[int] = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """Who can supply this product, and on what terms.

    The other half of the vendor profile's Products tab. The same link rows
    answer a different question here: not "what do we buy from this vendor"
    but "who do we buy this from, and which of them is cheapest, fastest or
    willing to sell the quantity we need". Awards now write each vendor's
    article number, cost, lead time and minimum back onto the link, so the
    comparison is a read rather than a round of e-mails.

    Last ordered is scoped to the user's own companies -- what a shared vendor
    charged another company is not this user's to see -- while the agreed terms
    on the link are group-level master data and are not.
    """
    product = apply_org_filter(
        db.query(Product).filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    show_money = is_financial_user(current_user, org_context)
    p, l, offset = _paged(page, limit)
    scope_sql, scope_params = _org_scope(org_context)
    # The scope clause is written for an unqualified table; inside the lateral
    # join it has to name the purchase order, and "1 = 0" has no column to name.
    po_scope = "1 = 0" if scope_sql == "1 = 0" else f"po.{scope_sql}"
    params = {**scope_params, "pid": product_id}

    total = db.execute(sqltext("""
        SELECT count(*) FROM containermgmt.product_suppliers ps
        JOIN containermgmt.supplier s ON s.supplier_id = ps.supplier_id
        WHERE ps.product_id = :pid AND ps.is_deleted IS NOT TRUE
          AND s.is_deleted IS NOT TRUE
    """), {"pid": product_id}).scalar() or 0

    # The preferred vendor first, then the ones that have quoted a price, then
    # by name: a buyer scanning this list is looking for a reason to pick, and
    # a row with no terms on it is not one.
    rows = db.execute(sqltext(f"""
        SELECT ps.id AS link_id, ps.supplier_id, s.name, s.code, s.country,
               s.is_active, s.default_currency,
               ps.factory_code, ps.vendor_product_name, ps.unit_cost, ps.currency,
               ps.min_order_qty, ps.lead_time_days, ps.is_default, ps.notes,
               (p.default_supplier_id = ps.supplier_id) AS is_product_default,
               last_po.order_date AS last_order_date,
               last_po.unit_price AS last_unit_price,
               last_po.po_number AS last_po_number,
               last_po.po_id AS last_po_id
        FROM containermgmt.product_suppliers ps
        JOIN containermgmt.supplier s ON s.supplier_id = ps.supplier_id
        JOIN containermgmt.products p ON p.id = ps.product_id
        LEFT JOIN LATERAL (
            SELECT po.id AS po_id, po.po_number,
                   coalesce(po.order_mail_date, po.created_at) AS order_date,
                   pi.unit_price
            FROM containermgmt.po_items pi
            JOIN containermgmt.purchase_orders po ON po.id = pi.po_id
            WHERE pi.product_id = ps.product_id
              AND po.supplier_id = ps.supplier_id
              AND pi.is_deleted IS NOT TRUE AND po.is_deleted IS NOT TRUE
              AND {po_scope}
            ORDER BY coalesce(po.order_mail_date, po.created_at) DESC, po.id DESC
            LIMIT 1
        ) last_po ON TRUE
        WHERE ps.product_id = :pid AND ps.is_deleted IS NOT TRUE
          AND s.is_deleted IS NOT TRUE
        ORDER BY ps.is_default DESC,
                 (ps.unit_cost IS NOT NULL) DESC,
                 s.name ASC
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": l, "offset": offset}).mappings().all()

    items = [
        {
            "link_id": r["link_id"],
            "supplier_id": r["supplier_id"],
            "name": r["name"],
            "code": r["code"],
            "country": r["country"],
            "is_active": bool(r["is_active"]),
            # Their article number, which is what they quote against.
            "factory_code": r["factory_code"],
            "vendor_product_name": r["vendor_product_name"],
            "unit_cost": float(r["unit_cost"]) if (show_money and r["unit_cost"] is not None) else None,
            "currency": (r["currency"] or r["default_currency"]) if show_money else None,
            "min_order_qty": float(r["min_order_qty"]) if r["min_order_qty"] is not None else None,
            "lead_time_days": r["lead_time_days"],
            "is_preferred": bool(r["is_default"]),
            "is_product_default": bool(r["is_product_default"]),
            "last_order_date": r["last_order_date"].isoformat() if r["last_order_date"] else None,
            "last_unit_price": float(r["last_unit_price"]) if (show_money and r["last_unit_price"] is not None) else None,
            "last_po_number": r["last_po_number"],
            "last_po_id": r["last_po_id"],
            "notes": r["notes"],
        }
        for r in rows
    ]
    return _page_envelope(items, int(total), p, l)


# ── 5. Organization Base Currency Endpoints ───────────────────────────────────

@MasterDataRouter.get("/organizations")
def get_master_data_organizations(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    orgs = db.query(Organisation).filter(Organisation.is_active == True).order_by(Organisation.id.asc()).all()
    return [
        {
            "id": o.id,
            "name": o.name,
            "display_name": o.display_name or o.name,
            "parent_org_id": o.parent_org_id,
            "base_currency": o.base_currency or "SCR",
            "is_active": o.is_active,
        }
        for o in orgs
    ]

@MasterDataRouter.put("/organizations/{org_id}/base-currency")
def set_organization_base_currency(
    org_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance or Admin users can change entity base currency.")

    org = db.query(Organisation).filter(Organisation.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")

    new_curr = (payload.get("base_currency") or "SCR").strip().upper()
    curr_exists = db.query(Currency).filter(Currency.code == new_curr).first()
    if not curr_exists:
        raise HTTPException(status_code=400, detail=f"Currency '{new_curr}' is not registered in currencies list.")

    org.base_currency = new_curr
    db.commit()
    return {
        "success": True,
        "message": f"Base currency for '{org.display_name or org.name}' updated to {new_curr}."
    }


# ── Document Types Master Data ───────────────────────────────────────────────

class DocumentTypeSchema(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    applicable_spaces: List[str] = []
    is_active: bool = True
    display_order: int = 0


@MasterDataRouter.get("/document-types")
def list_document_types(
    space: Optional[str] = Query(None, description="Filter by space: SOURCING, ORDER, PAYMENT, SHIPPING, DEFECTS"),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    """Retrieve document types configured in reference data, optionally filtered by stage/space."""
    query = apply_shared_or_org_filter(
        db.query(MasterDocumentType).filter(MasterDocumentType.is_deleted == False),
        MasterDocumentType,
        org_context,
    )
    if active_only:
        query = query.filter(MasterDocumentType.is_active == True)
    
    rows = query.order_by(MasterDocumentType.display_order.asc(), MasterDocumentType.id.asc()).all()
    
    if space:
        target_space = space.strip().upper()
        # Filter where target_space is in applicable_spaces (or applicable_spaces is empty/all)
        filtered_rows = []
        for r in rows:
            spaces = [str(s).upper() for s in (r.applicable_spaces or [])]
            if not spaces or target_space in spaces:
                filtered_rows.append(r)
        rows = filtered_rows

    return [
        {
            "id": r.id,
            "code": r.code,
            "name": r.name,
            "description": r.description,
            "applicable_spaces": r.applicable_spaces or [],
            "is_active": r.is_active,
            "display_order": r.display_order,
            "is_shared": r.is_shared,
            "org_id": r.org_id,
        }
        for r in rows
    ]


@MasterDataRouter.post("/document-types")
def create_document_type(
    payload: DocumentTypeSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance or Admin users can manage document types.")

    cleaned_code = payload.code.strip().lower().replace(" ", "_")
    existing = db.query(MasterDocumentType).filter(
        MasterDocumentType.org_id == org_context.org_id,
        MasterDocumentType.code == cleaned_code,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Document type with code '{cleaned_code}' already exists.")

    new_doc_type = MasterDocumentType(
        org_id=org_context.org_id,
        is_shared=False,
        code=cleaned_code,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        applicable_spaces=[s.strip().upper() for s in payload.applicable_spaces if s],
        is_active=payload.is_active,
        display_order=payload.display_order,
        created_by=getattr(current_user, "id", None),
    )
    db.add(new_doc_type)
    db.commit()
    db.refresh(new_doc_type)
    return {
        "id": new_doc_type.id,
        "code": new_doc_type.code,
        "name": new_doc_type.name,
        "description": new_doc_type.description,
        "applicable_spaces": new_doc_type.applicable_spaces,
        "is_active": new_doc_type.is_active,
        "display_order": new_doc_type.display_order,
    }


@MasterDataRouter.put("/document-types/{type_id}")
def update_document_type(
    type_id: int,
    payload: DocumentTypeSchema,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance or Admin users can manage document types.")

    doc_type = db.query(MasterDocumentType).filter(
        MasterDocumentType.id == type_id,
        MasterDocumentType.org_id == org_context.org_id,
    ).first()
    if not doc_type:
        raise HTTPException(status_code=404, detail="Document type not found.")

    cleaned_code = payload.code.strip().lower().replace(" ", "_")
    if cleaned_code != doc_type.code:
        duplicate = db.query(MasterDocumentType).filter(
            MasterDocumentType.org_id == org_context.org_id,
            MasterDocumentType.code == cleaned_code,
            MasterDocumentType.id != type_id
        ).first()
        if duplicate:
            raise HTTPException(status_code=400, detail=f"Document type with code '{cleaned_code}' already exists.")
        doc_type.code = cleaned_code

    doc_type.name = payload.name.strip()
    doc_type.description = payload.description.strip() if payload.description else None
    doc_type.applicable_spaces = [s.strip().upper() for s in payload.applicable_spaces if s]
    doc_type.is_active = payload.is_active
    doc_type.display_order = payload.display_order
    doc_type.updated_by = getattr(current_user, "id", None)

    db.commit()
    db.refresh(doc_type)
    return {
        "id": doc_type.id,
        "code": doc_type.code,
        "name": doc_type.name,
        "description": doc_type.description,
        "applicable_spaces": doc_type.applicable_spaces,
        "is_active": doc_type.is_active,
        "display_order": doc_type.display_order,
    }


@MasterDataRouter.delete("/document-types/{type_id}")
def delete_document_type(
    type_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance or Admin users can manage document types.")

    doc_type = db.query(MasterDocumentType).filter(
        MasterDocumentType.id == type_id,
        MasterDocumentType.org_id == org_context.org_id,
    ).first()
    if not doc_type:
        raise HTTPException(status_code=404, detail="Document type not found.")

    db.delete(doc_type)
    db.commit()
    return {"success": True, "message": f"Document type '{doc_type.name}' deleted."}

