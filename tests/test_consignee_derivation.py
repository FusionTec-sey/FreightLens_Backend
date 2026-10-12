"""The consignee of a document is its organisation.

The consignee table duplicated `organisations`: one row per organisation, kept
in sync by hand, auto-created from any unrecognised free text, and across 778
bills of lading the consignee never once differed from the document's own
organisation. These pin the derivation that replaced it, and the three saved
report templates that print `consignee` depend on it still resolving.
"""
from types import SimpleNamespace

from Services.report_data_resolvers import _consignee_for_org


class _Query:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _DB:
    def __init__(self, organisation=None):
        self._organisation = organisation
        self.queries = 0

    def query(self, *args, **kwargs):
        self.queries += 1
        return _Query(self._organisation)


def test_uses_the_organisations_display_name():
    db = _DB(SimpleNamespace(display_name="Noblecon Enterprise", name="noblecon"))
    assert _consignee_for_org(db, 8) == "Noblecon Enterprise"


def test_falls_back_to_the_slug_when_no_display_name_is_set():
    db = _DB(SimpleNamespace(display_name=None, name="noblecon"))
    assert _consignee_for_org(db, 8) == "noblecon"


def test_an_empty_display_name_does_not_win_over_the_slug():
    """A blank display name used to produce a blank consignee on the document."""
    db = _DB(SimpleNamespace(display_name="", name="noblecon"))
    assert _consignee_for_org(db, 8) == "noblecon"


def test_no_organisation_id_resolves_to_nothing_without_querying():
    db = _DB()
    assert _consignee_for_org(db, None) is None
    assert db.queries == 0


def test_an_unknown_organisation_resolves_to_nothing():
    assert _consignee_for_org(_DB(None), 999) is None


def test_every_company_is_consignable():
    """Sahaj Construction had no consignee row, so it could never be chosen.

    Deriving from the organisation means a company is consignable as soon as it
    exists, with nothing to create by hand.
    """
    for org_id, display in ((1, "Sahaj Construction"), (8, "Noblecon Enterprise"),
                            (9, "Sahajanand")):
        db = _DB(SimpleNamespace(display_name=display, name=str(org_id)))
        assert _consignee_for_org(db, org_id) == display
