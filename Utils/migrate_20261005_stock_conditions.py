"""Enable only reviewed T18 return-stock condition transitions."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Inventory.StockLedger import MOVEMENT_KIND_CHECK


CONDITION_GUARD_FUNCTION = r"""
CREATE OR REPLACE FUNCTION containermgmt.guard_reviewed_stock_condition()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    prior containermgmt.inventory_stock_movements%ROWTYPE;
    source_line containermgmt.sales_credit_note_lines%ROWTYPE;
    bound jsonb;
    disposition numeric;
BEGIN
    IF NEW.kind <> 'CONDITION' THEN RETURN NEW; END IF;

    SELECT * INTO prior FROM containermgmt.inventory_stock_movements
     WHERE org_id=NEW.org_id AND balance_id=NEW.balance_id
       AND version=NEW.version-1 FOR SHARE;
    IF prior.id IS NULL
       OR NEW.on_hand<>prior.on_hand OR NEW.reserved<>prior.reserved
       OR NEW.on_hand_delta<>0 OR NEW.reserved_delta<>0
       OR NEW.damaged<=prior.damaged OR NEW.quarantined>=prior.quarantined
       OR NEW.damaged-prior.damaged<>prior.quarantined-NEW.quarantined THEN
        RAISE EXCEPTION 'Condition movement must exactly conserve stock while moving quarantine to damaged';
    END IF;

    SELECT review.binding INTO bound
      FROM containermgmt.manager_case_uses used
      JOIN containermgmt.manager_cases review
        ON review.id=used.case_id AND review.org_id=used.org_id
      JOIN containermgmt.manager_case_decisions decision
        ON decision.case_id=review.id AND decision.org_id=review.org_id
     WHERE used.org_id=NEW.org_id AND used.operation_key=NEW.operation_key
       AND used.created_by=NEW.created_by AND decision.outcome='APPROVED'
       AND review.action='inventory.stock.condition-transition'
       AND review.source_type='sales.return-credit-line'
       AND review.source_version=NEW.version-1
       AND (review.binding->'details'->>'balance_id')::integer=NEW.balance_id
       AND (review.binding->'details'->>'before_on_hand')::numeric=prior.on_hand
       AND (review.binding->'details'->>'before_reserved')::numeric=prior.reserved
       AND (review.binding->'details'->>'before_damaged')::numeric=prior.damaged
       AND (review.binding->'details'->>'before_quarantined')::numeric=prior.quarantined
       AND (review.binding->'details'->>'target_damaged')::numeric=NEW.damaged
       AND (review.binding->'details'->>'target_quarantined')::numeric=NEW.quarantined
       AND (review.binding->'details'->>'quantity')::numeric=NEW.damaged-prior.damaged
       AND review.source_key=review.binding->'details'->>'credit_note_line_id';
    IF bound IS NULL THEN
        RAISE EXCEPTION 'Condition movement requires its exact approved manager case use';
    END IF;

    SELECT * INTO source_line FROM containermgmt.sales_credit_note_lines
     WHERE org_id=NEW.org_id
       AND id=(bound->'details'->>'credit_note_line_id')::integer
       AND balance_id=NEW.balance_id
       AND return_operation_key=(bound->'details'->>'return_operation_key')::uuid
       AND quantity=(bound->'details'->>'source_return_quantity')::numeric
       AND base_unit=bound->'details'->>'base_unit'
     FOR SHARE;
    IF source_line.id IS NULL OR NOT EXISTS (
        SELECT 1 FROM containermgmt.sales_return_allocations allocation
        JOIN containermgmt.sales_credit_notes note
          ON note.credit_note_key=source_line.credit_note_key
         AND note.org_id=source_line.org_id AND NOT note.is_deleted
         AND note.return_key=allocation.return_key
         WHERE allocation.id=source_line.return_allocation_id
           AND allocation.org_id=source_line.org_id AND NOT allocation.is_deleted
           AND allocation.balance_id=source_line.balance_id
           AND allocation.invoice_key=source_line.invoice_key
           AND allocation.invoice_line_key=source_line.invoice_line_key
           AND allocation.handover_allocation_key=source_line.handover_allocation_key
           AND allocation.quantity=source_line.quantity
           AND allocation.base_unit=source_line.base_unit
           AND note.credit_note_key=(bound->'details'->>'credit_note_key')::uuid
           AND note.return_key=(bound->'details'->>'return_key')::uuid
           AND source_line.invoice_key=(bound->'details'->>'invoice_key')::uuid
           AND source_line.invoice_line_key=(bound->'details'->>'invoice_line_key')::uuid
           AND source_line.handover_allocation_key=
               (bound->'details'->>'handover_allocation_key')::uuid
    ) OR NOT EXISTS (
        SELECT 1 FROM containermgmt.inventory_stock_movements returned
         WHERE returned.org_id=NEW.org_id
           AND returned.balance_id=NEW.balance_id
           AND returned.operation_key=source_line.return_operation_key
           AND returned.kind='RETURN'
           AND returned.on_hand_delta=(
               SELECT SUM(line.quantity)
                 FROM containermgmt.sales_credit_note_lines line
                WHERE line.org_id=source_line.org_id
                  AND line.balance_id=source_line.balance_id
                  AND line.return_operation_key=source_line.return_operation_key
                  AND NOT line.is_deleted)
    ) THEN
        RAISE EXCEPTION 'Condition movement requires exact T18 return-stock lineage';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM containermgmt.inventory_posting_operations posted
         WHERE posted.org_id=NEW.org_id AND posted.operation_key=NEW.operation_key
           AND posted.kind='stock.condition-transition.v1.authority-v1'
           AND posted.created_by=NEW.created_by
    ) THEN
        RAISE EXCEPTION 'Condition movement requires its exact posting receipt';
    END IF;

    SELECT COALESCE(SUM(
        (review.binding->'details'->>'quantity')::numeric), 0)
      INTO disposition
      FROM containermgmt.manager_cases review
      JOIN containermgmt.manager_case_uses used
        ON used.case_id=review.id AND used.org_id=review.org_id
     WHERE review.org_id=NEW.org_id
       AND review.action='inventory.stock.condition-transition'
       AND review.source_type='sales.return-credit-line'
       AND review.source_key=source_line.id::text;
    IF disposition>source_line.quantity THEN
        RAISE EXCEPTION 'Condition movements exceed exact returned source quantity';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM containermgmt.inventory_stock_balances balance
         WHERE balance.id=NEW.balance_id AND balance.org_id=NEW.org_id
           AND balance.version=NEW.version AND balance.on_hand=NEW.on_hand
           AND balance.reserved=NEW.reserved AND balance.damaged=NEW.damaged
           AND balance.quarantined=NEW.quarantined
           AND balance.tracking_policy IN ('UNTRACKED', 'BATCH')
           AND NOT balance.is_deleted
    ) THEN
        RAISE EXCEPTION 'Condition movement must equal the current non-serial stock projection';
    END IF;
    RETURN NEW;
END;
$$
"""

CONDITION_GUARD_TRIGGER = r"""
CREATE CONSTRAINT TRIGGER reviewed_stock_condition_guard
AFTER INSERT ON containermgmt.inventory_stock_movements
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.guard_reviewed_stock_condition()
"""


def prepare_stock_condition_schema(conn):
    exists = conn.execute(text("""SELECT 1 FROM information_schema.tables
        WHERE table_schema='containermgmt'
          AND table_name='inventory_stock_movements'""")).scalar()
    if not exists:
        return
    definition = conn.execute(text("""SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid='containermgmt.inventory_stock_movements'::regclass
          AND conname='ck_stock_movement_kind'""")).scalar()
    if not definition or "CONDITION" not in definition:
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_movements "
                          "DROP CONSTRAINT IF EXISTS ck_stock_movement_kind"))
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_movements "
                          "ADD CONSTRAINT ck_stock_movement_kind CHECK (" +
                          MOVEMENT_KIND_CHECK + ")"))
    conn.execute(text(CONDITION_GUARD_FUNCTION))
    trigger = conn.execute(text("""SELECT 1 FROM pg_trigger
        WHERE tgrelid='containermgmt.inventory_stock_movements'::regclass
          AND tgname='reviewed_stock_condition_guard' AND NOT tgisinternal""")).scalar()
    if not trigger:
        conn.execute(text(CONDITION_GUARD_TRIGGER))


def ensure_stock_condition_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        prepare_stock_condition_schema(conn)
