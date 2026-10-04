from decimal import Decimal as D
from random import Random
from uuid import uuid4
import pytest

from Services.sales_pricing_service import (
    PriceCandidate, PricingLineInput, TaxRuleSnapshot,
    calculate_tax_inclusive_invoice)


def price(source, value, key=None, version=1):
    return PriceCandidate(source, key or source.lower(), version, D(value))


def tax(treatment='STANDARD', rate='0.15', code='VAT15', version=1):
    return TaxRuleSnapshot(code, version, treatment, D(rate))


def line(quantity='1', prices=None, treatment=None, floor=None, key=None):
    return PricingLineInput(key or uuid4(), 7, D(quantity), tuple(
        prices if prices is not None else [price('STORE', '115')]), treatment or tax(),
        D(floor) if floor is not None else None)


def test_tax_inclusive_standard_price_exposes_separate_vat_and_net():
    result = calculate_tax_inclusive_invoice([line()])
    assert result.currency == 'SCR'
    assert result.gross_total_scr == D('115.00')
    assert result.tax_total_scr == D('15.00')
    assert result.net_total_scr == D('100.00')
    assert result.lines[0].tax.treatment == 'STANDARD'


def test_zero_rated_and_exempt_remain_distinct_with_no_tax():
    zero = line(prices=[price('STORE', '10')],
        treatment=tax('ZERO_RATED', '0', 'VAT0'))
    exempt = line(prices=[price('STORE', '20')],
        treatment=tax('EXEMPT', '0', 'EXEMPT'))
    result = calculate_tax_inclusive_invoice([zero, exempt])
    assert result.tax_total_scr == D('0.00')
    assert {item.tax.treatment for item in result.lines} == {'ZERO_RATED', 'EXEMPT'}


def test_best_eligible_customer_price_wins_only_when_better():
    better = line(prices=[price('STORE', '120', 'store-v1'),
        price('CUSTOMER_AGREEMENT', '110', 'agreement-v3', 3)])
    equal = line(prices=[price('CUSTOMER_AGREEMENT', '120', 'agreement-v2', 2),
        price('STORE', '120', 'store-v1')])
    result = calculate_tax_inclusive_invoice([better, equal])
    chosen = {item.line_key: item.selected_price for item in result.lines}
    assert chosen[better.line_key].source == 'CUSTOMER_AGREEMENT'
    assert chosen[better.line_key].reference_key == 'agreement-v3'
    assert chosen[equal.line_key].source == 'STORE'


def test_price_floor_is_an_explicit_approval_flag_not_silent_repricing():
    requested = line(prices=[price('STORE', '120'),
        price('CUSTOMER_AGREEMENT', '90')], floor='100')
    result = calculate_tax_inclusive_invoice([requested])
    assert result.lines[0].selected_price.gross_unit_scr == D('90')
    assert result.lines[0].requires_floor_approval
    assert result.requires_floor_approval


def test_invoice_total_rounds_once_and_allocates_lines_deterministically():
    keys = [uuid4(), uuid4(), uuid4()]
    lines = [line(quantity='0.333333', prices=[price('STORE', '1')], key=key)
        for key in keys]
    one = calculate_tax_inclusive_invoice(lines)
    two = calculate_tax_inclusive_invoice(list(reversed(lines)))
    assert one == two
    assert one.gross_total_scr == D('1.00')
    assert sum(item.gross_scr for item in one.lines) == one.gross_total_scr
    assert sum(item.net_scr for item in one.lines) == one.net_total_scr
    assert sum(item.tax_scr for item in one.lines) == one.tax_total_scr


def test_mixed_tax_groups_each_conserve_invoice_display_totals():
    lines = [line(quantity='3', prices=[price('STORE', '0.05')]),
        line(quantity='2', prices=[price('STORE', '0.07')],
            treatment=tax('STANDARD', '0.10', 'LEVY10')),
        line(quantity='1', prices=[price('STORE', '0.11')],
            treatment=tax('EXEMPT', '0', 'EXEMPT'))]
    result = calculate_tax_inclusive_invoice(lines)
    assert result.gross_total_scr == D('0.40')
    assert result.gross_total_scr == result.net_total_scr + result.tax_total_scr
    assert all(item.gross_scr == item.net_scr + item.tax_scr for item in result.lines)


@pytest.mark.parametrize('bad', [
    lambda: line(quantity='0'),
    lambda: line(quantity='1.0000001'),
    lambda: line(prices=[]),
    lambda: line(prices=[price('CUSTOMER_AGREEMENT', '10')]),
    lambda: line(prices=[price('STORE', '10'), price('STORE', '9', 'other')]),
    lambda: line(prices=[price('STORE', '0')]),
    lambda: line(treatment=tax('STANDARD', '0')),
    lambda: line(treatment=tax('EXEMPT', '0.15')),
])
def test_ambiguous_or_inexact_contracts_fail_closed(bad):
    with pytest.raises(ValueError): calculate_tax_inclusive_invoice([bad()])


def test_duplicate_line_keys_and_non_decimal_money_are_rejected():
    key = uuid4()
    with pytest.raises(ValueError): calculate_tax_inclusive_invoice([
        line(key=key), line(key=key)])
    with pytest.raises(ValueError): calculate_tax_inclusive_invoice([
        line(prices=[PriceCandidate('STORE', 'store', 1, 115)])])
    with pytest.raises(ValueError): calculate_tax_inclusive_invoice([
        line(treatment=tax('STANDARD', '0.15', 'VAT', 1)),
        line(treatment=tax('STANDARD', '0.10', 'VAT', 1))])


def test_200_deterministic_invoices_conserve_rounded_totals():
    random = Random(20261004)
    for _ in range(200):
        lines = []
        for product in range(1, random.randint(2, 20)):
            quantity = D(random.randint(1, 500000)) / D('1000')
            store = D(random.randint(1, 500000)) / D('1000')
            customer = store - D(random.randint(0, 1000)) / D('1000')
            customer = max(customer, D('0.001'))
            rule = tax() if product % 3 else tax('ZERO_RATED', '0', 'VAT0')
            lines.append(PricingLineInput(uuid4(), product, quantity,
                (price('STORE', str(store), f'store-{product}'),
                 price('CUSTOMER_AGREEMENT', str(customer), f'customer-{product}')),
                rule))
        result = calculate_tax_inclusive_invoice(lines)
        assert sum(item.gross_scr for item in result.lines) == result.gross_total_scr
        assert sum(item.tax_scr for item in result.lines) == result.tax_total_scr
        assert sum(item.net_scr for item in result.lines) == result.net_total_scr
        assert result.gross_total_scr == result.net_total_scr + result.tax_total_scr
