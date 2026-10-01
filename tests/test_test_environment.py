import os
import importlib


def test_test_database_is_explicitly_isolated(test_database_url):
    assert test_database_url.endswith("/containermgmt_test")
    assert os.environ["DATABASE_URL"] == test_database_url


def test_scheduler_is_disabled_during_tests():
    assert os.environ["DISABLE_SCHEDULER"] == "1"
    application = importlib.import_module("containerMgmt")
    assert application.scheduler is None


def test_two_organisation_fixture_is_isolated(organisation_contexts):
    first, second = organisation_contexts
    assert first.current_org_id != second.current_org_id
    assert second.current_org_id not in first.allowed_org_ids
    assert first.current_org_id not in second.allowed_org_ids
