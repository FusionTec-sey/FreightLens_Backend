"""Issues document numbers from the per-company series.

Six document types each built their own number from a literal in Python, and
each counted existing rows to decide what came next. Counting is not
allocating: deleting a document handed its number to the next one, and two
people creating a document at the same moment were issued the same number.

This module keeps a stored counter per company per document type and hands out
numbers under a row lock, so neither can happen. A company with no series row,
or one marked inactive, falls back to the caller's own format, which is how
this can be switched on one company at a time.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from Model.containermgmt.MasterData.DocumentNumberSeries import DocumentNumberSeries

logger = logging.getLogger("containerMgmt.document_number")

# The document types a series can be configured for.
DOC_TYPES = {
    "PO": "Purchase Order",
    "RFQ": "RFQ",
    "REQ": "Requisition",
    "GRN": "Goods Receipt",
    "PL": "Packing List",
    "DEF": "Defect Report",
}

RESET_POLICIES = ("never", "daily", "monthly", "yearly")


def _period_start(policy: str, today: date) -> Optional[date]:
    """The date the current counting period began, or None if it never resets."""
    if policy == "daily":
        # A counter that restarts each day, for formats like SAHAJ#260109-1
        # where the date carries the period and the counter is within it.
        return today
    if policy == "yearly":
        return date(today.year, 1, 1)
    if policy == "monthly":
        return date(today.year, today.month, 1)
    return None


def _needs_reset(series: DocumentNumberSeries, today: date) -> bool:
    start = _period_start(series.reset_policy or "never", today)
    if start is None:
        return False
    # Never reset means no reset; a series not yet reset in this period is due.
    return series.last_reset_on is None or series.last_reset_on < start


def format_number(series: DocumentNumberSeries, number: int, today: Optional[date] = None) -> str:
    """Render one number in this series' format, without allocating it.

    Used for the preview in Settings as well as by the allocator, so what an
    administrator is shown is produced by the same code that issues the number.
    """
    today = today or date.today()
    middle = ""
    if series.date_token:
        try:
            middle = today.strftime(series.date_token)
        except (ValueError, TypeError):
            # A malformed token must not stop a document being created.
            logger.warning("Ignoring unusable date_token %r on series %s",
                           series.date_token, series.id)
            middle = ""
    padding = series.padding if series.padding and series.padding > 0 else 0
    counter = str(number).zfill(padding) if padding else str(number)
    return f"{series.prefix or ''}{middle}{counter}{series.suffix or ''}"


def peek_document_number(db: Session, org_id: int, doc_type: str) -> Optional[str]:
    """What the next number would look like, allocating nothing.

    Returns None when no active series is configured, which is the caller's
    signal to keep using its own format.
    """
    series = (
        db.query(DocumentNumberSeries)
        .filter(
            DocumentNumberSeries.org_id == org_id,
            DocumentNumberSeries.doc_type == doc_type.upper(),
            DocumentNumberSeries.is_deleted == False,  # noqa: E712
            DocumentNumberSeries.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not series:
        return None
    today = date.today()
    number = 1 if _needs_reset(series, today) else series.next_number
    return format_number(series, number, today)


def next_document_number(db: Session, org_id: Optional[int], doc_type: str) -> Optional[str]:
    """Allocate and return the next number, or None if no series is configured.

    Runs inside the caller's transaction: the counter moves only if the document
    the caller is creating is itself committed.
    """
    if not org_id:
        return None

    series = (
        db.query(DocumentNumberSeries)
        .filter(
            DocumentNumberSeries.org_id == org_id,
            DocumentNumberSeries.doc_type == doc_type.upper(),
            DocumentNumberSeries.is_deleted == False,  # noqa: E712
            DocumentNumberSeries.is_active == True,  # noqa: E712
        )
        # Concurrent callers queue here instead of reading the same counter.
        .with_for_update(of=DocumentNumberSeries)
        .first()
    )
    if not series:
        return None

    today = date.today()
    if _needs_reset(series, today):
        series.next_number = 1
        series.last_reset_on = today

    number = series.next_number
    series.next_number = number + 1
    db.flush()
    return format_number(series, number, today)
