from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from Services.settings_revision_service import (lock_settings_operation, require_matching_retry,
    require_current_version, SettingsConflict)


@pytest.mark.parametrize("change", [{"target_matches": False}, {"expected_version": 4},
    {"actor_id": 8}, {"config": {"enabled": False}}])
def test_replay_requires_exact_target_actor_version_and_content(change):
    previous = SimpleNamespace(version=3, created_by=7, config={"enabled": True})
    values = dict(target_matches=True, expected_version=2, actor_id=7, config={"enabled": True}, message="Conflict")
    with pytest.raises(SettingsConflict, match="Conflict"):
        require_matching_retry(previous, **{**values, **change})


def test_historical_retry_is_independent_of_current_revision():
    previous = SimpleNamespace(version=3, created_by=7, config={"enabled": True})
    require_matching_retry(previous, target_matches=True, expected_version=2, actor_id=7,
        config={"enabled": True}, message="Conflict")
    require_current_version(None, 0, "Stale")
    with pytest.raises(SettingsConflict, match="Stale"):
        require_current_version(SimpleNamespace(version=5), 2, "Stale")


@pytest.mark.parametrize("namespace", ["branch-settings", "counter-settings"])
def test_lock_namespace_and_order_remain_compatible(namespace):
    db = Mock()
    lock_settings_operation(db, namespace, 7, "stable-key")
    assert str(db.execute.call_args_list[0].args[0]) == "SET LOCAL lock_timeout = '5s'"
    assert db.execute.call_args_list[1].args[1] == {"key": f"{namespace}:7:stable-key"}
    db.commit.assert_not_called()


def test_unrecognised_namespace_is_not_silently_accepted():
    db = Mock()
    with pytest.raises(ValueError): lock_settings_operation(db, "stock", 7, "stable-key")
    db.execute.assert_not_called()
