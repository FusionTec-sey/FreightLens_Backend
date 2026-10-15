"""The supplier master: scope, reasons, and learning a vendor's terms.

Three rules worth pinning down, each of which had a defect behind it:

* a supplier search must not be wider than the list it searches;
* a merge or a retirement without a reason is unexplainable later;
* a vendor's minimum order quantity has to be learned at award, or the same
  deviation is rediscovered at every quote.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from Routes.MasterData.MasterDataRouter import _require_reason
from Routes.Orders.QuoteComparisonService import QuoteComparisonService
from Services.search_service import format_supplier_doc, supplier_scope_filter


class _Ctx(SimpleNamespace):
    pass


def test_a_selected_company_sees_shared_vendors_and_its_own():
    """Selecting a company must not hide the shared vendors it buys through."""
    clause = supplier_scope_filter(_Ctx(selected_org_id=2, allowed_org_ids=[1, 2], current_org_id=1))

    assert clause == "(is_shared = true OR org_id = 2)"


def test_all_companies_mode_covers_every_allowed_company():
    clause = supplier_scope_filter(_Ctx(selected_org_id=None, allowed_org_ids=[2, 3], current_org_id=2))

    assert "is_shared = true" in clause
    assert "org_id = 2" in clause and "org_id = 3" in clause


def test_a_user_with_no_company_sees_only_shared_vendors():
    """Never everything: an empty scope is a narrower answer, not a wider one."""
    clause = supplier_scope_filter(_Ctx(selected_org_id=None, allowed_org_ids=[], current_org_id=None))

    assert clause == "is_shared = true"


def test_the_index_document_carries_the_identifiers():
    """A buyer searching a registration number is searching for the vendor."""
    doc = format_supplier_doc(
        SimpleNamespace(
            supplier_id=42, name="AL RABIH TRADING LLC", code="VEND-0042",
            contact_person=None, email=None, phone=None, country="UAE",
            address=None, default_currency="AED", is_active=True,
            is_shared=True, is_deleted=False, org_id=1,
        ),
        ["CN-1234567"],
    )

    assert doc["id"] == "42", "Meilisearch keys documents by a string id"
    assert doc["identifier_values"] == ["CN-1234567"]
    assert doc["is_shared"] is True


def test_a_blank_reason_is_refused():
    for blank in (None, "", "   ", "ok"):
        with pytest.raises(HTTPException) as raised:
            _require_reason(blank, "Say why.")
        assert raised.value.status_code == 422
        assert raised.value.detail == "Say why."


def test_a_real_reason_comes_back_trimmed():
    assert _require_reason("  same company, two imports  ", "Say why.") == "same company, two imports"


class _Query:
    def __init__(self, existing):
        self._existing = existing

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._existing


class _Session:
    def __init__(self, existing=None):
        self._existing = existing
        self.added = []

    def query(self, *args, **kwargs):
        return _Query(self._existing)

    def add(self, obj):
        self.added.append(obj)


def _po():
    return SimpleNamespace(org_id=1)


def _line(product_id=7, requested=3, ordered=5):
    return SimpleNamespace(
        product_id=product_id,
        quantity_requested=Decimal(str(requested)),
        quantity_ordered=Decimal(str(ordered)),
    )


def _quote(lead=30, currency="USD"):
    return SimpleNamespace(
        supplier_id=42, delivery_lead_time_days=lead, currency=currency,
        quote_reference="Q-1", id=1,
    )


def _quote_line(quoted=5, price="10.00", code="TL-6060", description="Tile 60x60"):
    return SimpleNamespace(
        quantity_quoted=Decimal(str(quoted)), unit_price=Decimal(price),
        item_code=code, description=description,
    )


def test_a_vendor_offering_more_than_asked_reveals_a_minimum():
    """Ordered 3, vendor quoted 5: five is their floor, and worth keeping."""
    session = _Session()

    QuoteComparisonService._learn_vendor_terms(
        _po(), _line(requested=3, ordered=5), _quote(), _quote_line(quoted=5), 1, session
    )

    assert len(session.added) == 1
    link = session.added[0]
    assert link.min_order_qty == Decimal("5")
    assert link.lead_time_days == 30
    assert link.factory_code == "TL-6060"
    assert link.supplier_id == 42 and link.product_id == 7


def test_quoting_exactly_what_was_asked_reveals_no_minimum():
    """Their quantity echoing the request says nothing about a floor."""
    session = _Session()

    QuoteComparisonService._learn_vendor_terms(
        _po(), _line(requested=10, ordered=10), _quote(), _quote_line(quoted=10), 1, session
    )

    assert session.added[0].min_order_qty is None


def test_a_free_text_line_has_nothing_to_learn_against():
    session = _Session()

    QuoteComparisonService._learn_vendor_terms(
        _po(), _line(product_id=None), _quote(), _quote_line(), 1, session
    )

    assert session.added == []


def test_an_existing_link_is_topped_up_and_never_overwritten():
    """A figure a buyer typed outranks anything inferred from a quote."""
    existing = SimpleNamespace(
        factory_code="BUYER-CODE", vendor_product_name="As catalogued",
        unit_cost=Decimal("9.00"), currency="USD", min_order_qty=Decimal("12"),
        lead_time_days=14, updated_by=None,
    )
    session = _Session(existing=existing)

    QuoteComparisonService._learn_vendor_terms(
        _po(), _line(requested=3, ordered=5), _quote(lead=30),
        _quote_line(quoted=5, price="11.00", code="VENDOR-CODE"), 1, session,
    )

    assert session.added == [], "an existing link is updated in place"
    assert existing.factory_code == "BUYER-CODE", "their code was already recorded"
    assert existing.lead_time_days == 14, "a known lead time is not replaced"
    assert existing.min_order_qty == Decimal("12"), "the higher known minimum stands"
    assert existing.unit_cost == Decimal("11.00"), "the awarded price is what we agreed to pay"


def test_a_higher_minimum_moves_the_recorded_one_up():
    existing = SimpleNamespace(
        factory_code=None, vendor_product_name=None, unit_cost=None, currency="USD",
        min_order_qty=Decimal("5"), lead_time_days=None, updated_by=None,
    )
    session = _Session(existing=existing)

    QuoteComparisonService._learn_vendor_terms(
        _po(), _line(requested=6, ordered=20), _quote(), _quote_line(quoted=20), 1, session
    )

    assert existing.min_order_qty == Decimal("20")


def test_an_award_with_no_quote_attached_learns_nothing():
    """The terms are a by-product of the award and must never break it."""
    session = _Session()

    QuoteComparisonService._learn_vendor_terms(_po(), _line(), None, _quote_line(), 1, session)

    assert session.added == []


# ── The scope a product's vendor list pages over ────────────────────────────
#
# GET /products/{id}/vendors shows the agreed terms on the link, which are
# group-level master data, beside what this company last paid, which is not.
# The second half reuses _org_scope, and the clause it returns is qualified
# with the purchase order's alias inside the lateral join -- so "no company at
# all" has to stay a narrower answer, not a wider one.
from Routes.MasterData.MasterDataRouter import _org_scope


def test_a_selected_company_scopes_the_last_order_to_itself():
    clause, params = _org_scope(_Ctx(selected_org_id=2, allowed_org_ids=[1, 2], current_org_id=1))

    assert clause == "org_id = :scope_org"
    assert params == {"scope_org": 2}
    assert f"po.{clause}" == "po.org_id = :scope_org", "qualifiable inside the lateral join"


def test_a_user_with_no_company_sees_no_order_history():
    clause, params = _org_scope(_Ctx(selected_org_id=None, allowed_org_ids=[], current_org_id=None))

    assert clause == "1 = 0"
    assert params == {}
    # "1 = 0" names no column, so it must never be prefixed with the alias.
    assert ("1 = 0" if clause == "1 = 0" else f"po.{clause}") == "1 = 0"
