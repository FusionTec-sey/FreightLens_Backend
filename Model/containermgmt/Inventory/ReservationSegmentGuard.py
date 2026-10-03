"""Database guards for historical hold segments and approved supplements."""
FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_reservation_segment()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF EXISTS (SELECT 1 FROM containermgmt.inventory_stock_reservations h
 WHERE h.org_id=NEW.org_id AND h.balance_id=NEW.balance_id
 AND h.source_line_key=NEW.source_line_key AND h.id<NEW.id)
 AND NOT EXISTS (SELECT 1 FROM containermgmt.reservation_reallocations r
 JOIN containermgmt.inventory_stock_movements m
 ON m.org_id=r.org_id AND m.operation_key=r.reserve_operation
 WHERE r.org_id=NEW.org_id AND r.target_key=NEW.reservation_key
 AND m.reservation_id=NEW.id AND m.balance_id=NEW.balance_id
 AND r.quantity=NEW.quantity AND m.reserved_delta=NEW.quantity)
THEN RAISE EXCEPTION 'Supplemental reservation requires approved paired reallocation'; END IF;
RETURN NEW; END; $$"""
TRIGGER = """CREATE CONSTRAINT TRIGGER reservation_segment_guard
AFTER INSERT ON containermgmt.inventory_stock_reservations
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_reservation_segment()"""
IDENTITY_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.protect_reservation_segment()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Reservation history cannot be deleted'; END IF;
IF ROW(NEW.id,NEW.org_id,NEW.reservation_key,NEW.balance_id,NEW.source_line_key,
 NEW.quantity,NEW.review_at,NEW.created_by,NEW.created_at,NEW.is_deleted,NEW.deleted_at)
 IS DISTINCT FROM ROW(OLD.id,OLD.org_id,OLD.reservation_key,OLD.balance_id,OLD.source_line_key,
 OLD.quantity,OLD.review_at,OLD.created_by,OLD.created_at,OLD.is_deleted,OLD.deleted_at)
 OR NEW.released<OLD.released THEN
RAISE EXCEPTION 'Reservation identity, original quantity and review date are immutable'; END IF;
RETURN NEW; END; $$"""
IDENTITY_TRIGGER = """CREATE TRIGGER reservation_segment_identity
BEFORE UPDATE OR DELETE ON containermgmt.inventory_stock_reservations
FOR EACH ROW EXECUTE FUNCTION containermgmt.protect_reservation_segment()"""
