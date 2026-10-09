from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert

from Services.legacy_sync_service import _hash, _org_slug_for_row, _payload, _source_lookup, _status


def test_container_ownership_ignores_temporary_upgrade_copy():
    sources = {
        "consignee": {1: {"consignee_name": "NOBLECON ENTERPRISE"}},
        "bill_of_landing": {},
        "container_details02": {10: {"container_no": "ABC", "consignee": 1}},
    }
    assert _org_slug_for_row("container_details", {"Container_ID": 10, "container_no": "ABC"}, sources) == "legacy-unknown"
    assert _org_slug_for_row("container_details", {"Container_ID": 10, "container_no": "DIFFERENT"}, sources) == "legacy-unknown"


def test_source_change_does_not_overwrite_a_locally_edited_target():
    db = create_engine("sqlite://")
    table = Table("status", MetaData(), Column("status_id", Integer, primary_key=True), Column("name", String))
    table.create(db)
    with db.begin() as conn:
        conn.execute(insert(table).values(status_id=7, name="Locally edited"))
        original = {"status_id": 7, "name": "Original"}
        tracked = {"source_hash": _hash(original), "target_hash": _hash(original), "status": "imported"}
        status, _ = _status(conn, tracked, table, "status", {"status_id": 7, "name": "Changed in source"},
                            _hash({"status_id": 7, "name": "Changed in source"}), original)
        assert status == "conflict"


def test_supplier_scope_follows_observed_consignee_usage():
    table = Table("supplier", MetaData(), Column("supplier_id", Integer, primary_key=True),
                  Column("org_id", Integer), Column("is_shared", Integer), Column("is_active", Integer))
    snapshot = {
        "consignee": [("1", {"consignee_id": 1, "consignee_name": "NOBLECON ENTERPRISE"}, ""),
                       ("2", {"consignee_id": 2, "consignee_name": "SAHAJANAND"}, "")],
        "bill_of_landing": [("a", {"BillOfLanding": "A", "Consignee": 1, "Supplier": 10}, ""),
                            ("b", {"BillOfLanding": "B", "Consignee": 2, "Supplier": 11}, ""),
                            ("c", {"BillOfLanding": "C", "Consignee": 1, "Supplier": 11}, "")],
    }
    sources = _source_lookup(snapshot)
    orgs = {"noblecon": 2, "sahajanand": 3, "legacy-unknown": 4}
    assigned = _payload("supplier", {"supplier_id": 10}, table, sources, orgs, 1)
    shared = _payload("supplier", {"supplier_id": 11}, table, sources, orgs, 1)
    unknown = _payload("supplier", {"supplier_id": 12}, table, sources, orgs, 1)
    assert (assigned["org_id"], assigned["is_shared"]) == (2, False)
    assert (shared["org_id"], shared["is_shared"]) == (1, True)
    assert (unknown["org_id"], unknown["is_shared"]) == (4, False)
