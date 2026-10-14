"""The supplier code has to be real data, and it has to stop moving.

Before this, the directory computed `VEND-0042` from the row id while
serialising, and stored nothing: the code a buyer read off the screen and quoted
on the phone existed in no column, could not be searched, and would have changed
the day the serialiser changed.
"""
import pytest
from fastapi import HTTPException

from Routes.MasterData.MasterDataRouter import (
    _assert_supplier_code_free,
    _clean_supplier_code,
    _issue_supplier_code,
)


def test_an_issued_code_is_padded_and_prefixed():
    assert _issue_supplier_code(42) == "VEND-0042"
    assert _issue_supplier_code(179) == "VEND-0179"


def test_an_issued_code_carries_no_company_or_group_segment():
    """A code that encodes who owns the vendor lies as soon as it is shared."""
    code = _issue_supplier_code(42)

    assert code.count("-") == 1
    assert code.split("-")[1].isdigit()


def test_blank_input_is_no_code_at_all():
    assert _clean_supplier_code(None) is None
    assert _clean_supplier_code("   ") is None
    assert _clean_supplier_code("  VEND-0042 ") == "VEND-0042"


class _Clash:
    name = "AL RABIH TRADING LLC"


class _Query:
    def __init__(self, result):
        self._result = result
        self.filters = 0

    def filter(self, *args, **kwargs):
        self.filters += 1
        return self

    def first(self):
        return self._result


class _Session:
    def __init__(self, result):
        self._query = _Query(result)

    def query(self, *args, **kwargs):
        return self._query


def test_a_code_already_in_use_is_refused_with_the_holder_named():
    with pytest.raises(HTTPException) as raised:
        _assert_supplier_code_free(_Session(_Clash()), "VEND-0042")

    assert raised.value.status_code == 409
    assert "AL RABIH TRADING LLC" in raised.value.detail


def test_a_free_code_passes():
    assert _assert_supplier_code_free(_Session(None), "VEND-9999") is None


def test_the_supplier_being_edited_is_excluded_from_its_own_check():
    """Saving a supplier without changing its code must not clash with itself."""
    session = _Session(None)

    _assert_supplier_code_free(session, "VEND-0042", exclude_id=42)

    assert session.query().filters == 2, "the code lookup, then the exclusion"
