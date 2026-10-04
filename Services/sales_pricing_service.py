"""Exact tax-inclusive SCR pricing; no persistence, stock, invoice or payment effect.

Tax is resolved independently from store/customer price eligibility. The caller must
load authoritative versioned candidates and tax snapshots; this calculator never
guesses a branch, customer agreement, exemption, rate, floor approval or offer.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, localcontext
from typing import Literal
from uuid import UUID


CENT = Decimal('0.01')
ZERO = Decimal('0')
MAX_QUANTITY = Decimal('1000000000000')
MAX_MONEY = Decimal('1000000000000000000')


def _exact(value, name, *, maximum, scale):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f'{name} must be an exact finite Decimal')
    if value < 0 or value >= maximum:
        raise ValueError(f'{name} is outside the supported range')
    if value.as_tuple().exponent < -scale:
        raise ValueError(f'{name} supports at most {scale} decimal places')
    return value


@dataclass(frozen=True)
class PriceCandidate:
    source: Literal['STORE', 'CUSTOMER_AGREEMENT']
    reference_key: str
    version: int
    gross_unit_scr: Decimal

    def validate(self):
        if self.source not in ('STORE', 'CUSTOMER_AGREEMENT'):
            raise ValueError('Only authoritative store and customer-agreement prices are supported')
        if (not isinstance(self.reference_key, str) or not self.reference_key.strip()
                or len(self.reference_key) > 100 or type(self.version) is not int
                or self.version < 1):
            raise ValueError('Versioned price source identity required')
        _exact(self.gross_unit_scr, 'Gross unit price', maximum=MAX_MONEY, scale=6)
        if self.gross_unit_scr == ZERO:
            raise ValueError('Gross unit price must be positive')
        return self


@dataclass(frozen=True)
class TaxRuleSnapshot:
    code: str
    version: int
    treatment: Literal['STANDARD', 'ZERO_RATED', 'EXEMPT']
    rate: Decimal

    def validate(self):
        if (not isinstance(self.code, str) or not self.code.strip()
                or len(self.code) > 32 or type(self.version) is not int
                or self.version < 1):
            raise ValueError('Versioned tax rule identity required')
        _exact(self.rate, 'Tax rate', maximum=Decimal('10'), scale=8)
        if self.treatment == 'STANDARD' and self.rate <= ZERO:
            raise ValueError('Standard-rated supply requires a positive rate')
        if self.treatment in ('ZERO_RATED', 'EXEMPT') and self.rate != ZERO:
            raise ValueError('Zero-rated and exempt supplies require a zero rate')
        if self.treatment not in ('STANDARD', 'ZERO_RATED', 'EXEMPT'):
            raise ValueError('Explicit standard, zero-rated or exempt treatment required')
        return self


@dataclass(frozen=True)
class PricingLineInput:
    line_key: UUID
    product_id: int
    quantity: Decimal
    eligible_prices: tuple[PriceCandidate, ...]
    tax: TaxRuleSnapshot
    floor_gross_unit_scr: Decimal | None = None

    def validate(self):
        if not isinstance(self.line_key, UUID) or not self.line_key.int:
            raise ValueError('Stable nonzero sales line identity required')
        if type(self.product_id) is not int or self.product_id <= 0:
            raise ValueError('Positive product identity required')
        _exact(self.quantity, 'Selling quantity', maximum=MAX_QUANTITY, scale=6)
        if self.quantity == ZERO:
            raise ValueError('Selling quantity must be positive')
        if (not isinstance(self.eligible_prices, tuple) or not self.eligible_prices
                or len(self.eligible_prices) > 32):
            raise ValueError('A bounded eligible price set is required')
        prices = [candidate.validate() for candidate in self.eligible_prices]
        if sum(candidate.source == 'STORE' for candidate in prices) != 1:
            raise ValueError('Exactly one selling-store price is required')
        identities = [(candidate.source, candidate.reference_key, candidate.version)
            for candidate in prices]
        if len(identities) != len(set(identities)):
            raise ValueError('Eligible price sources must be distinct')
        self.tax.validate()
        if self.floor_gross_unit_scr is not None:
            _exact(self.floor_gross_unit_scr, 'Gross price floor',
                maximum=MAX_MONEY, scale=6)
        return self


@dataclass(frozen=True)
class PricedLine:
    line_key: UUID
    product_id: int
    quantity: Decimal
    selected_price: PriceCandidate
    store_price: PriceCandidate
    tax: TaxRuleSnapshot
    raw_gross_scr: Decimal
    gross_scr: Decimal
    net_scr: Decimal
    tax_scr: Decimal
    floor_gross_unit_scr: Decimal | None
    requires_floor_approval: bool


@dataclass(frozen=True)
class PricedInvoice:
    currency: Literal['SCR']
    policy: Literal['best-eligible-tax-inclusive-invoice-round-v1']
    lines: tuple[PricedLine, ...]
    gross_total_scr: Decimal
    net_total_scr: Decimal
    tax_total_scr: Decimal
    requires_floor_approval: bool


def _allocate_cents(raw_by_key):
    target = sum(raw_by_key.values(), ZERO).quantize(CENT, rounding=ROUND_HALF_UP)
    allocated = {key: value.quantize(CENT, rounding=ROUND_DOWN)
        for key, value in raw_by_key.items()}
    cents = int((target - sum(allocated.values(), ZERO)) / CENT)
    order = sorted(raw_by_key, key=lambda key: (
        -(raw_by_key[key] - allocated[key]), str(key)))
    for key in order[:cents]:
        allocated[key] += CENT
    if sum(allocated.values(), ZERO) != target:
        raise ArithmeticError('Invoice-cent allocation did not conserve the rounded total')
    return allocated, target


def calculate_tax_inclusive_invoice(lines):
    """Select the lowest eligible price and allocate invoice-rounded SCR cents.

    The invoice total is rounded once. Line gross and included tax cents are then
    allocated deterministically so displayed lines add back to the exact invoice
    totals. EXEMPT and ZERO_RATED remain distinct even though each carries zero tax.
    """
    if (not isinstance(lines, (tuple, list)) or not lines or len(lines) > 500
            or any(not isinstance(line, PricingLineInput) for line in lines)):
        raise ValueError('A bounded typed invoice line set is required')
    checked = sorted((line.validate() for line in lines), key=lambda line: str(line.line_key))
    if len({line.line_key for line in checked}) != len(checked):
        raise ValueError('Sales line identities must be distinct')
    tax_rules = {}
    for line in checked:
        identity = (line.tax.code, line.tax.version)
        if identity in tax_rules and tax_rules[identity] != line.tax:
            raise ValueError('One tax rule version cannot have conflicting treatment or rate')
        tax_rules[identity] = line.tax
    prepared = []
    with localcontext() as context:
        context.prec = 50
        for line in checked:
            store = next(item for item in line.eligible_prices if item.source == 'STORE')
            # Same-price ties retain the store source; agreements win only when they
            # improve the customer's eligible price.
            selected = min(line.eligible_prices, key=lambda item: (
                item.gross_unit_scr, 0 if item.source == 'STORE' else 1,
                item.reference_key, item.version))
            raw_gross = line.quantity * selected.gross_unit_scr
            if not raw_gross.is_finite() or raw_gross >= MAX_MONEY:
                raise ValueError('Extended line price is outside the supported range')
            raw_tax = ZERO if line.tax.treatment != 'STANDARD' else (
                raw_gross - raw_gross / (Decimal(1) + line.tax.rate))
            prepared.append((line, selected, store, raw_gross, raw_tax))
    gross, gross_total = _allocate_cents({line.line_key: raw
        for line, _, _, raw, _ in prepared})
    tax = {}
    for rule in sorted(tax_rules):
        group = {line.line_key: raw_tax for line, _, _, _, raw_tax in prepared
            if (line.tax.code, line.tax.version) == rule}
        allocation, _ = _allocate_cents(group)
        tax.update(allocation)
    result = []
    for line, selected, store, raw_gross, _ in prepared:
        line_tax = tax[line.line_key]
        line_gross = gross[line.line_key]
        floor = line.floor_gross_unit_scr
        result.append(PricedLine(line.line_key, line.product_id, line.quantity,
            selected, store, line.tax, raw_gross, line_gross,
            line_gross - line_tax, line_tax, floor,
            floor is not None and selected.gross_unit_scr < floor))
    gross_total = sum((line.gross_scr for line in result), ZERO)
    tax_total = sum((line.tax_scr for line in result), ZERO)
    return PricedInvoice('SCR', 'best-eligible-tax-inclusive-invoice-round-v1',
        tuple(result), gross_total, gross_total - tax_total, tax_total,
        any(line.requires_floor_approval for line in result))
