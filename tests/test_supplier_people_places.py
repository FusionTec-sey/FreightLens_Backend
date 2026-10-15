"""A vendor's people and places: one primary, and the old fields kept honest.

Two rules carry the risk here:

* exactly one contact and one address may be primary, which the database
  enforces with a partial unique index -- so promoting one has to demote the
  other in the same transaction, or the insert fails on an index nobody asked
  about;
* the supplier's own `contact_person`, `email`, `phone` and `address` columns
  are still read by screens, prints and exports, so the primary row has to keep
  them correct rather than leaving two answers in the database.
"""
from types import SimpleNamespace

from Routes.MasterData.MasterDataRouter import (
    ADDRESS_TYPES,
    CONTACT_ROLES,
    _clear_other_primaries,
    _sync_primary_address,
    _sync_primary_contact,
)


class _Result:
    def __init__(self, row=None):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _Session:
    """Records the SQL it was asked to run, and answers the one read."""

    def __init__(self, row=None):
        self.row = row
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        return _Result(self.row)


def test_promoting_a_primary_demotes_whoever_holds_it():
    session = _Session()

    _clear_other_primaries(session, "supplier_contacts", 42)

    sql, params = session.statements[0]
    assert "supplier_contacts" in sql
    assert "is_primary = FALSE" in sql
    assert params == {"id": 42}


def test_the_row_being_promoted_is_not_demoted_with_the_rest():
    """Updating the current primary in place must not switch it off."""
    session = _Session()

    _clear_other_primaries(session, "supplier_addresses", 42, keep_id=7)

    sql, params = session.statements[0]
    assert "id <> :keep" in sql
    assert params == {"id": 42, "keep": 7}


def test_the_primary_contact_fills_the_vendors_own_fields():
    supplier = SimpleNamespace(supplier_id=42, contact_person=None, email=None, phone=None)
    session = _Session(row={"name": "Ms Chen", "email": "chen@example.com", "phone": "+86 1", "mobile": None})

    _sync_primary_contact(session, supplier)

    assert supplier.contact_person == "Ms Chen"
    assert supplier.email == "chen@example.com"
    assert supplier.phone == "+86 1"


def test_a_contact_with_only_a_mobile_still_fills_the_phone():
    supplier = SimpleNamespace(supplier_id=42, contact_person=None, email=None, phone=None)
    session = _Session(row={"name": "Mr Wang", "email": None, "phone": None, "mobile": "+86 2"})

    _sync_primary_contact(session, supplier)

    assert supplier.phone == "+86 2"
    assert supplier.email is None, "an email nobody gave is not invented"


def test_no_primary_contact_leaves_the_old_fields_alone():
    """A vendor whose contacts were all removed keeps what it had."""
    supplier = SimpleNamespace(supplier_id=42, contact_person="As imported", email="old@example.com", phone=None)
    session = _Session(row=None)

    _sync_primary_contact(session, supplier)

    assert supplier.contact_person == "As imported"
    assert supplier.email == "old@example.com"


def test_the_primary_address_becomes_the_single_address_line():
    supplier = SimpleNamespace(supplier_id=42, address=None, country=None)
    session = _Session(row={
        "line1": "12 Factory Road", "line2": None, "city": "Foshan",
        "state": "Guangdong", "postal_code": "528000", "country": "China",
    })

    _sync_primary_address(session, supplier)

    assert supplier.address == "12 Factory Road, Foshan, Guangdong, 528000"
    assert supplier.country == "China", "a country nobody had recorded is worth taking"


def test_a_country_already_recorded_is_not_overwritten():
    """The vendor's country drives currency and customs; an address does not get to move it."""
    supplier = SimpleNamespace(supplier_id=42, address=None, country="Seychelles")
    session = _Session(row={
        "line1": "Suite 4", "line2": None, "city": "Hong Kong",
        "state": None, "postal_code": None, "country": "Hong Kong",
    })

    _sync_primary_address(session, supplier)

    assert supplier.country == "Seychelles"


def test_a_long_address_is_cut_to_what_the_column_holds():
    supplier = SimpleNamespace(supplier_id=42, address=None, country="China")
    session = _Session(row={
        "line1": "x" * 300, "line2": None, "city": None,
        "state": None, "postal_code": None, "country": "China",
    })

    _sync_primary_address(session, supplier)

    assert len(supplier.address) == 255, "the column is VARCHAR(255); a 500 is not an answer"


def test_the_roles_and_types_are_the_ones_the_migration_wrote():
    # The UI, the schema's defaults and these lists have to agree, or a row the
    # database accepts is a row the form cannot show.
    assert CONTACT_ROLES == ("SALES", "ACCOUNTS", "LOGISTICS", "ESCALATION", "OTHER")
    assert ADDRESS_TYPES == ("REGISTERED", "FACTORY", "WAREHOUSE", "REMIT_TO", "OTHER")
    assert "OTHER" in CONTACT_ROLES and "OTHER" in ADDRESS_TYPES, "nothing is forced into a wrong box"
