"""Pure exact journal composition primitives.

This module does not resolve accounts, persist journals, fence periods, or export
anything. Callers supply already resolved opaque account references and exact
Decimal amounts. ``account_role`` is optional so a future caller can retain the
T20 role source where applicable while using the exact T12 receiving-account
reference for a captured payment side without duplicating that catalogue. Binary
floats are rejected rather than converted.
"""
from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Iterable, Literal

from Model.containermgmt.Accounting.AccountingConfiguration import ACCOUNT_ROLES


JournalSide = Literal["DEBIT", "CREDIT"]
MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class JournalLine:
    account_ref: str
    side: JournalSide
    amount: Decimal
    account_role: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.account_ref, str) or not re.fullmatch(
            r"[A-Z0-9][A-Z0-9_.:-]{0,63}", self.account_ref
        ):
            raise ValueError("Journal account reference is invalid")
        if self.account_role is not None and self.account_role not in ACCOUNT_ROLES:
            raise ValueError("Unsupported logical account role")
        if self.side not in ("DEBIT", "CREDIT"):
            raise ValueError("Journal side must be DEBIT or CREDIT")
        if not isinstance(self.amount, Decimal):
            raise TypeError("Journal amounts must be Decimal; floats are forbidden")
        if not self.amount.is_finite() or self.amount <= 0:
            raise ValueError("Journal amounts must be finite and positive")
        if self.amount.as_tuple().exponent < -2:
            raise ValueError("Journal amounts must use exact SCR cents")


@dataclass(frozen=True, slots=True)
class JournalComposition:
    lines: tuple[JournalLine, ...]
    debit_total: Decimal
    credit_total: Decimal


def compose_balanced_journal(lines: Iterable[JournalLine]) -> JournalComposition:
    """Return an immutable exact composition or reject an unbalanced request."""
    frozen_lines = tuple(lines)
    if len(frozen_lines) < 2:
        raise ValueError("A journal requires at least two lines")
    if not all(isinstance(line, JournalLine) for line in frozen_lines):
        raise TypeError("Journal entries must be JournalLine instances")
    debit_total = sum(
        (line.amount for line in frozen_lines if line.side == "DEBIT"), Decimal("0.00")
    )
    credit_total = sum(
        (line.amount for line in frozen_lines if line.side == "CREDIT"), Decimal("0.00")
    )
    if debit_total == Decimal("0.00") or credit_total == Decimal("0.00"):
        raise ValueError("A journal requires debit and credit lines")
    if debit_total != credit_total:
        raise ValueError("Journal is not balanced")
    return JournalComposition(frozen_lines, debit_total, credit_total)
