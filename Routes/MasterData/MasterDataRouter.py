from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc, asc
import math
from typing import Optional, List
from datetime import date
from pydantic import BaseModel

from Model.db import get_db
from Model.containermgmt.MasterData.Currency import Currency, CurrencyExchangeRate
from Model.containermgmt.MasterData.PaymentTerm import PaymentTerm
from Model.containermgmt.MasterData.DocumentType import MasterDocumentType
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.Credentials.Organisation import Organisation
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import can_view_supplier_user
from Utils.org_filter import OrgContext
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
    current_user = Depends(get_current_user)
):
    query = db.query(PaymentTerm)
    if active_only:
        query = query.filter(PaymentTerm.is_active == True)
    terms = query.order_by(PaymentTerm.id.asc()).all()

    results = []
    for t in terms:
        # Count vendors bound to this term
        vendor_count = db.query(Supplier).filter(
            Supplier.default_payment_term_id == t.id,
            Supplier.is_deleted != True
        ).count()

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
    existing = db.query(PaymentTerm).filter(PaymentTerm.code == code_clean).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Payment term code '{code_clean}' already exists.")

    term = PaymentTerm(
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

    term = db.query(PaymentTerm).filter(PaymentTerm.id == id).first()
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

    term = db.query(PaymentTerm).filter(PaymentTerm.id == id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Payment term not found.")

    # Soft delete / deactivate
    term.is_active = False
    db.commit()
    return {"success": True, "message": f"Payment term '{term.name}' deactivated."}


# ── 4. Enhanced Suppliers Master Endpoints ───────────────────────────────────

@MasterDataRouter.get("/suppliers")
def get_suppliers_master(
    page: Optional[int] = Query(None, ge=1),
    limit: Optional[int] = Query(None, ge=1, le=200),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("asc"),
    active_only: bool = False,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    can_view_supplier = can_view_supplier_user(current_user)
    query = db.query(Supplier).filter(Supplier.is_deleted != True)
    if active_only:
        query = query.filter(Supplier.is_active == True)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Supplier.name.ilike(s),
                Supplier.code.ilike(s),
                Supplier.contact_person.ilike(s),
                Supplier.email.ilike(s),
                Supplier.phone.ilike(s)
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
            "code": s.code or f"VEND-{s.supplier_id:04d}",
            "address": s.address,
            "email": s.email,
            "phone": s.phone,
            "contact_person": s.contact_person,
            "country": s.country or "Seychelles",
            "logo_url": s.logo_url,
            "logo_signed_url": (
                blob_storage.signed_url(s.logo_url, ttl=15 * 60)
                if can_view_supplier and s.logo_url else None
            ),
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
    existing = db.query(Supplier).filter(Supplier.name.ilike(name_clean), Supplier.is_deleted != True).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Supplier '{name_clean}' already exists.")

    supplier = Supplier(
        name=name_clean,
        code=payload.code.strip() if payload.code else None,
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
        supplier.code = f"VEND-{supplier.supplier_id:04d}"
        db.commit()

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

    supplier = db.query(Supplier).filter(Supplier.supplier_id == id, Supplier.is_deleted != True).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")

    if "name" in payload and payload["name"]:
        supplier.name = payload["name"].strip()
    if "code" in payload:
        supplier.code = payload["code"].strip() if payload["code"] else None
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

    db.commit()
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

    supplier = db.query(Supplier).filter(Supplier.supplier_id == id, Supplier.is_deleted != True).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")

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

    supplier = db.query(Supplier).filter(Supplier.supplier_id == id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")

    supplier.is_deleted = True
    supplier.is_active = False
    db.commit()
    return {"success": True, "message": f"Supplier '{supplier.name}' deleted."}


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
    current_user = Depends(get_current_user)
):
    """Retrieve document types configured in reference data, optionally filtered by stage/space."""
    query = db.query(MasterDocumentType).filter(MasterDocumentType.is_deleted == False)
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
    existing = db.query(MasterDocumentType).filter(MasterDocumentType.code == cleaned_code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Document type with code '{cleaned_code}' already exists.")

    new_doc_type = MasterDocumentType(
        code=cleaned_code,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        applicable_spaces=[s.strip().upper() for s in payload.applicable_spaces if s],
        is_active=payload.is_active,
        display_order=payload.display_order,
        created_by=getattr(current_user, "username", "Admin"),
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

    doc_type = db.query(MasterDocumentType).filter(MasterDocumentType.id == type_id).first()
    if not doc_type:
        raise HTTPException(status_code=404, detail="Document type not found.")

    cleaned_code = payload.code.strip().lower().replace(" ", "_")
    if cleaned_code != doc_type.code:
        duplicate = db.query(MasterDocumentType).filter(
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
    doc_type.updated_by = getattr(current_user, "username", "Admin")

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

    doc_type = db.query(MasterDocumentType).filter(MasterDocumentType.id == type_id).first()
    if not doc_type:
        raise HTTPException(status_code=404, detail="Document type not found.")

    db.delete(doc_type)
    db.commit()
    return {"success": True, "message": f"Document type '{doc_type.name}' deleted."}

