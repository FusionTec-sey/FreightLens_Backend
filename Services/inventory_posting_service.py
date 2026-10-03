"""Internal atomic posting boundary; no HTTP entrypoint or external side effects.

Callers must authorize the action on EVERY request, including retries. The
callback validates trusted domain records and locks balances in stable order.
It must use only the supplied session: no commit, rollback, network or printing.
An operation key deduplicates ONE intent, not competing distinct intents. Domain
locks are still required for stock, reservations and customer-money balances.
This is not node fencing, cloud inbox processing or final valuation ordering.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Utils.org_filter import OrgContext, apply_org_filter


class PostingConflict(ValueError):
    """An operation key cannot be reused for another intent or actor."""


@dataclass(frozen=True)
class PostingEffect:
    result: dict
    event: dict


@dataclass(frozen=True)
class PostingOutcome:
    operation_key: UUID
    result: dict
    replayed: bool


def _json_snapshot(value: dict) -> tuple[dict, str]:
    """Explicit JSON contract: money/quantities are strings, never binary floats."""
    def validate(item, depth=0):
        if depth > 32:
            raise ValueError("Posting JSON is too deeply nested")
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is list:
            for child in item:
                validate(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                validate(child, depth + 1)
            return
        raise ValueError("Use JSON objects with string keys and decimal strings, not floats")

    if type(value) is not dict:
        raise ValueError("Posting payload must be a JSON object")
    validate(value)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    if len(encoded) > 1_048_576:
        raise ValueError("Posting payload exceeds one MiB")
    return json.loads(encoded), encoded


def execute_once(session_factory: Callable[[], Session] | Session, context: OrgContext,
                 actor_id: int, operation_key: UUID, kind: str, request: dict,
                 apply: Callable[[Session], PostingEffect], *,
                 authorize: Callable[[Session], None] | None = None) -> PostingOutcome:
    """Own a fresh transaction, or join a supplied Session with a required guard.

Never automatically retry a database error here. A caller may retry the same
operation key and identical normalized request after an uncertain response.
Future routes must supply the branch, source line, authority epoch, requested
quantity and expected versions in the request fingerprint as applicable.
"""
    if isinstance(session_factory, Session):
        return execute_in_transaction(session_factory, context, actor_id,
            operation_key, kind, request, apply, authorize=authorize)
    with session_factory() as db:
        with db.begin():
            return execute_in_transaction(db, context, actor_id, operation_key,
                kind, request, apply,
                authorize=authorize if authorize is not None else _legacy_internal_authorization)


def _legacy_internal_authorization(db: Session) -> None:
    """Compatibility for existing internal-only writers, NOT public authorization.

    Public callers and the shared boundary must supply a real authorization guard.
    Node/source enforcement remains a release gate for existing internal writers.
    """


def execute_in_transaction(db: Session, context: OrgContext, actor_id: int,
                           operation_key: UUID, kind: str, request: dict,
                           apply: Callable[[Session], PostingEffect], *,
                           authorize: Callable[[Session], None]) -> PostingOutcome:
    """Join an explicit caller-owned transaction; never commit it.

    The guard must lock/check current authority and permissions on EVERY attempt,
    including replay. It must raise on denial. The outer coordinator owns all
    invoice/payment/stock work and must use one stable intent for the whole sale.
    On any failure the ENTIRE transaction is rolled back, not just this operation:
    catching an error must not leave half a sale available for accidental commit.
    A returned outcome is provisional until the caller commits successfully.
    Callbacks may not commit/rollback or perform external effects.
    """
    if not db.in_transaction():
        raise ValueError("Posting requires an active caller-owned transaction")
    try:
        if not callable(authorize):
            raise ValueError("Posting requires an authorization guard")
        return _execute_in_transaction(db, context, actor_id, operation_key,
            kind, request, apply, authorize)
    except BaseException:
        db.rollback()
        raise


def _execute_in_transaction(db: Session, context: OrgContext, actor_id: int,
                            operation_key: UUID, kind: str, request: dict,
                            apply: Callable[[Session], PostingEffect],
                            authorize: Callable[[Session], None]) -> PostingOutcome:
    org_id = context.org_id
    if org_id not in context.allowed_org_ids:
        raise PermissionError("An allowed active organisation is required")
    if type(actor_id) is not int or actor_id <= 0:
        raise ValueError("Authenticated actor ID is required")
    if not isinstance(operation_key, UUID) or operation_key.int == 0:
        raise ValueError("A nonzero UUID operation key is required")
    if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", kind):
        raise ValueError("Invalid posting kind")
    if type(request) is not dict:
        raise ValueError("Posting request must be a JSON object")
    _, encoded = _json_snapshot({"kind": kind, "request": request})
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    # Collisions only serialize unrelated operations; full keys are always checked.
    lock_key = int.from_bytes(sha256(f"posting-v1:{org_id}:{operation_key}".encode()).digest()[:8],
                              byteorder="big", signed=True)
    # READ COMMITTED sees a competing writer after advisory-lock waiting.
    if db.execute(text("SHOW transaction_isolation")).scalar() != "read committed":
        raise ValueError("Posting requires READ COMMITTED isolation")
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    authorize(db)
    query = db.query(PostingOperation).filter(
        PostingOperation.org_id == org_id,
        PostingOperation.operation_key == operation_key,
        PostingOperation.is_deleted.is_(False),
    )
    previous = apply_org_filter(query, PostingOperation, context).one_or_none()
    if previous is not None:
        if previous.kind != kind or previous.request_digest != digest or previous.created_by != actor_id:
            raise PostingConflict("Operation key already belongs to a different intent or actor")
        result, _ = _json_snapshot(previous.result)
        return PostingOutcome(operation_key, result, True)
    effect = apply(db)
    if not isinstance(effect, PostingEffect):
        raise ValueError("Posting callback must return a PostingEffect")
    result, _ = _json_snapshot(effect.result)
    event_payload, _ = _json_snapshot(effect.event)
    db.add(PostingOperation(org_id=org_id, operation_key=operation_key, kind=kind,
        request_digest=digest, result=result, event_payload=event_payload, created_by=actor_id))
    db.flush()
    return PostingOutcome(operation_key, result, False)
