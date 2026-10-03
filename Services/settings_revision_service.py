"""Shared configuration-write mechanics, not stock posting or authorization.

Callers retain scoped queries, permission/parent checks, domain validation and
transaction ownership. Keep the existing lock namespaces for retry compatibility.
"""
from sqlalchemy import text


class SettingsConflict(ValueError):
    pass


def lock_settings_operation(db, namespace, org_id, operation_key):
    if namespace not in ("branch-settings", "counter-settings"):
        raise ValueError("Unsupported settings lock namespace")
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
               {"key": f"{namespace}:{org_id}:{operation_key}"})


def require_matching_retry(previous, *, target_matches, expected_version, actor_id, config, message):
    if (not target_matches or previous.version != expected_version + 1
            or previous.config != config or previous.created_by != actor_id):
        raise SettingsConflict(message)


def require_current_version(previous, expected_version, message):
    if (previous.version if previous else 0) != expected_version:
        raise SettingsConflict(message)
