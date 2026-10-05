"""T20A exact branch account configuration and pure journal composition."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.containermgmt.Accounting.AccountingConfiguration import ACCOUNT_ROLES
from Model.containermgmt.Inventory.Location import InventoryBranch
from Schema.AccountingConfigurationSchema import (
    AccountMappingConfig,
    AccountMappingSave,
)
from Services.accounting_configuration_service import (
    get_account_mapping,
    list_account_mapping_revisions,
    list_account_mappings,
    lookup_account_mapping,
    require_account_mapping,
    save_account_mapping,
)
from Services.accounting_journal_service import JournalLine, compose_balanced_journal
from Services.inventory_posting_service import PostingConflict
from Utils.migrate_20261005_accounting_configuration import (
    ensure_accounting_configuration_schema,
)
from Utils.org_filter import OrgContext
from tests.test_stock_ledger import stock  # noqa: F401


def mapping_payload(
    f,
    *,
    operation=None,
    expected=0,
    branch=None,
    role="SALES_REVENUE",
    account="TEST.REVENUE",
    enabled=True,
):
    return AccountMappingSave(
        operation_key=operation or uuid4(),
        expected_version=expected,
        branch_id=branch or f.branches[0],
        account_role=role,
        config=AccountMappingConfig(
            account_ref=account,
            label="Test-only logical account",
            is_enabled=enabled,
        ),
        reason="Test-only configuration",
    )


@pytest.fixture
def accounting(stock):
    ensure_accounting_configuration_schema()
    ensure_accounting_configuration_schema()
    stock.mapping_key = uuid4()
    stock.authorize = lambda db: None
    return stock


def write(f, action):
    with f.factory.begin() as db:
        return action(db)


def test_migration_seeds_nothing_and_exposes_explicit_roles(accounting):
    f = accounting
    assert ACCOUNT_ROLES == (
        "SALES_REVENUE",
        "OUTPUT_TAX_PAYABLE",
        "CUSTOMER_CREDIT_LIABILITY",
        "COST_OF_GOODS_SOLD",
        "INVENTORY_ASSET",
        "CASH_OVER_SHORT",
        "CASH_DEPOSIT_CLEARING",
    )
    with f.factory() as db:
        assert db.execute(
            text(
                "SELECT count(*) FROM containermgmt.branch_account_mappings "
                "WHERE org_id = :org"
            ),
            {"org": f.orgs[0]},
        ).scalar() == 0
        blocked = lookup_account_mapping(
            db,
            f.context,
            f.branches[0],
            "SALES_REVENUE",
            authorize=f.authorize,
        )
    assert blocked == {
        "status": "BLOCKED",
        "reason": "MAPPING_MISSING",
        "branch_id": f.branches[0],
        "account_role": "SALES_REVENUE",
    }


def test_stable_replay_stale_version_and_immutable_history(accounting):
    f = accounting
    payload = mapping_payload(f)
    first = write(
        f,
        lambda db: save_account_mapping(
            db,
            f.context,
            f.actor,
            f.mapping_key,
            payload,
            authorize=f.authorize,
        ),
    )
    replay = write(
        f,
        lambda db: save_account_mapping(
            db,
            f.context,
            f.actor,
            f.mapping_key,
            payload,
            authorize=f.authorize,
        ),
    )
    assert first.result == {"key": str(f.mapping_key), "version": 1}
    assert replay.replayed and replay.result == first.result
    with pytest.raises(PostingConflict, match="different intent"):
        write(
            f,
            lambda db: save_account_mapping(
                db,
                f.context,
                f.actor,
                f.mapping_key,
                mapping_payload(
                    f,
                    operation=payload.operation_key,
                    account="TEST.CHANGED",
                ),
                authorize=f.authorize,
            ),
        )
    with pytest.raises(PostingConflict, match="changed"):
        write(
            f,
            lambda db: save_account_mapping(
                db,
                f.context,
                f.actor,
                f.mapping_key,
                mapping_payload(f, expected=0),
                authorize=f.authorize,
            ),
        )
    second = write(
        f,
        lambda db: save_account_mapping(
            db,
            f.context,
            f.actor,
            f.mapping_key,
            mapping_payload(
                f, expected=1, account="TEST.REVENUE.V2", enabled=False
            ),
            authorize=f.authorize,
        ),
    )
    assert second.result["version"] == 2
    with f.factory() as db:
        page = list_account_mapping_revisions(
            db,
            f.context,
            f.mapping_key,
            page=1,
            limit=1,
            authorize=f.authorize,
        )
        assert page["total"] == 2 and page["pages"] == 2
        assert page["items"][0]["version"] == 2
        assert lookup_account_mapping(
            db,
            f.context,
            f.branches[0],
            "SALES_REVENUE",
            authorize=f.authorize,
        )["reason"] == "MAPPING_DISABLED"
    with f.factory.begin() as db:
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(
                text(
                    "UPDATE containermgmt.branch_account_mapping_revisions "
                    "SET label = 'Tampered' WHERE mapping_key = :key"
                ),
                {"key": f.mapping_key},
            )
        db.rollback()


def test_tenant_isolation_branch_ownership_and_no_fallback(accounting):
    f = accounting
    write(
        f,
        lambda db: save_account_mapping(
            db,
            f.context,
            f.actor,
            f.mapping_key,
            mapping_payload(f),
            authorize=f.authorize,
        ),
    )
    foreign = OrgContext(
        current_org_id=f.orgs[1], allowed_org_ids=[f.orgs[1]], is_root=False
    )
    with f.factory() as db:
        assert list_account_mappings(
            db, foreign, page=1, limit=10, authorize=f.authorize
        )["items"] == []
        with pytest.raises(LookupError):
            get_account_mapping(db, foreign, f.mapping_key, authorize=f.authorize)
        with pytest.raises(LookupError, match="Branch"):
            lookup_account_mapping(
                db,
                f.context,
                f.branches[1],
                "SALES_REVENUE",
                authorize=f.authorize,
            )
    with pytest.raises(LookupError, match="Branch"):
        write(
            f,
            lambda db: save_account_mapping(
                db,
                f.context,
                f.actor,
                uuid4(),
                mapping_payload(f, branch=f.branches[1], role="INVENTORY_ASSET"),
                authorize=f.authorize,
            ),
        )


def test_exact_locked_revision_and_permission_guard(accounting):
    f = accounting
    write(
        f,
        lambda db: save_account_mapping(
            db,
            f.context,
            f.actor,
            f.mapping_key,
            mapping_payload(f),
            authorize=f.authorize,
        ),
    )
    with f.factory.begin() as db:
        exact = require_account_mapping(
            db,
            f.context,
            f.branches[0],
            "SALES_REVENUE",
            expected_mapping_key=f.mapping_key,
            expected_mapping_version=1,
            authorize=f.authorize,
        )
    assert exact["account_ref"] == "TEST.REVENUE"
    with f.factory.begin() as db, pytest.raises(PostingConflict, match="changed"):
        require_account_mapping(
            db,
            f.context,
            f.branches[0],
            "SALES_REVENUE",
            expected_mapping_key=f.mapping_key,
            expected_mapping_version=2,
            authorize=f.authorize,
        )
    with f.factory() as db, pytest.raises(PermissionError):
        list_account_mappings(
            db,
            f.context,
            page=1,
            limit=10,
            authorize=lambda session: (_ for _ in ()).throw(PermissionError()),
        )


def test_same_mapping_key_race_is_a_domain_conflict(accounting):
    f = accounting
    with f.factory.begin() as db:
        branch = InventoryBranch(
            org_id=f.orgs[0],
            code=f"RACE{uuid4().hex[:8].upper()}",
            name="Synthetic race branch",
            kind="STORE",
            created_by=f.actor,
        )
        db.add(branch)
        db.flush()
        second_branch = branch.id
    barrier = Barrier(2, timeout=10)

    def save(branch_id, role):
        barrier.wait()
        try:
            return write(
                f,
                lambda db: save_account_mapping(
                    db,
                    f.context,
                    f.actor,
                    f.mapping_key,
                    mapping_payload(f, branch=branch_id, role=role),
                    authorize=f.authorize,
                ),
            )
        except PostingConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: save(*args),
                (
                    (f.branches[0], "SALES_REVENUE"),
                    (second_branch, "INVENTORY_ASSET"),
                ),
            )
        )
    assert results.count("conflict") == 1
    assert sum(result != "conflict" for result in results) == 1


def test_database_rejects_malformed_immutable_audit_rows(accounting):
    f = accounting
    with f.factory.begin() as db:
        with pytest.raises(DBAPIError, match="ck_branch_account_mapping_audit"):
            db.execute(
                text(
                    """INSERT INTO containermgmt.branch_account_mappings
                    (org_id, mapping_key, branch_id, account_role,
                     creation_operation_key, created_by)
                    VALUES (:org, :key, :branch, 'SALES_REVENUE', :operation, NULL)"""
                ),
                {
                    "org": f.orgs[0],
                    "key": uuid4(),
                    "branch": f.branches[0],
                    "operation": uuid4(),
                },
            )
        db.rollback()


def test_exact_balanced_journal_is_immutable():
    journal = compose_balanced_journal(
        [
            JournalLine("TEST.RECEIVING", "DEBIT", Decimal("100.00")),
            JournalLine(
                "TEST.TAX", "CREDIT", Decimal("15.00"), "OUTPUT_TAX_PAYABLE"
            ),
            JournalLine(
                "TEST.REVENUE", "CREDIT", Decimal("85.00"), "SALES_REVENUE"
            ),
        ]
    )
    assert journal.debit_total == journal.credit_total == Decimal("100.00")
    assert isinstance(journal.lines, tuple)
    with pytest.raises(FrozenInstanceError):
        journal.debit_total = Decimal("0.00")


def test_unbalanced_and_float_journals_are_rejected():
    with pytest.raises(ValueError, match="not balanced"):
        compose_balanced_journal(
            [
                JournalLine(
                    "TEST.INVENTORY", "DEBIT", Decimal("10.00"), "INVENTORY_ASSET"
                ),
                JournalLine(
                    "TEST.COGS", "CREDIT", Decimal("9.99"), "COST_OF_GOODS_SOLD"
                ),
            ]
        )
    with pytest.raises(TypeError, match="floats are forbidden"):
        JournalLine("TEST.INVENTORY", "DEBIT", 10.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exact SCR cents"):
        JournalLine("TEST.INVENTORY", "DEBIT", Decimal("1.001"))
