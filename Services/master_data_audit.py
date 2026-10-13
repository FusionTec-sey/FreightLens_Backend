"""Record what changed on a shared master record.

A shared vendor or category is edited by one company and seen by all of them,
so an edit has to be attributable after the fact. These helpers take a snapshot
before the change and compare it after, writing one row per field that actually
moved -- a save that changes nothing records nothing.
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from Model.containermgmt.MasterData.MasterDataAudit import MasterDataAudit

logger = logging.getLogger("containerMgmt.master_data_audit")


def snapshot(obj, fields) -> dict:
    """The values of `fields` as they stand, for comparing against later."""
    return {f: getattr(obj, f, None) for f in fields}


def _as_text(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def record_changes(db: Session, entity_type: str, entity_id: int, before: dict,
                   after_obj, user_id, org_id=None, action: str = "updated") -> int:
    """Write one audit row per field whose value moved. Returns how many.

    Never raises into the caller: losing an audit row must not fail the edit the
    user asked for, but it must be visible in the log.
    """
    try:
        written = 0
        for field, old in before.items():
            new = getattr(after_obj, field, None)
            if _as_text(old) == _as_text(new):
                continue
            db.add(MasterDataAudit(
                entity_type=entity_type, entity_id=entity_id, org_id=org_id,
                action=action, field_name=field,
                old_value=_as_text(old), new_value=_as_text(new),
                changed_by=user_id,
            ))
            written += 1
        return written
    except Exception:
        logger.exception("Could not record %s audit for %s %s", action, entity_type, entity_id)
        return 0


def record_event(db: Session, entity_type: str, entity_id: int, action: str,
                 user_id, org_id=None, field_name=None, old_value=None, new_value=None) -> None:
    """Record something that is not a field edit -- a create, or a deletion."""
    try:
        db.add(MasterDataAudit(
            entity_type=entity_type, entity_id=entity_id, org_id=org_id,
            action=action, field_name=field_name,
            old_value=_as_text(old_value), new_value=_as_text(new_value),
            changed_by=user_id,
        ))
    except Exception:
        logger.exception("Could not record %s event for %s %s", action, entity_type, entity_id)
