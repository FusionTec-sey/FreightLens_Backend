"""
cron_jobs.py
────────────
All scheduled background jobs for the Container Management system.

Jobs registered here run three times a day: 04:00, 13:00, 20:00 (server local time).

  ┌──────────────────────────────────┬────────────────────┬──────────────┐
  │ Job                              │ Schedule           │ minute offset│
  ├──────────────────────────────────┼────────────────────┼──────────────┤
  │ updateArrivalDate                │ 04:00, 13:00, 20:00│     :00      │
  │ updateContainerStatus            │ 04:00, 13:00, 20:00│     :01      │
  └──────────────────────────────────┴────────────────────┴──────────────┘

updateArrivalDate runs first (minute=0) so that updateContainerStatus
(minute=1) always works against the freshest ETA data.
"""

import logging
from datetime import datetime, date as date_type

from apscheduler.schedulers.background import BackgroundScheduler

from Model.db import get_db
from Model.containermgmt.Container.BillOfLanding import BillOfLanding as bl
from Model.containermgmt.Container.ContainerDetails import ContainerDetails as cd
from ShippingProvider.Shipping import track_and_trace

logger = logging.getLogger("containerMgmt.cron")

# ── Status constants ───────────────────────────────────────────────────────────
STATUS_IN_TRANSIT = 1   # ArrivalDate > now (cron managed)
STATUS_ON_PORT    = 2   # ArrivalDate <= now (cron managed)
STATUS_GATE_PASS  = 3
STATUS_COMPLETE   = 4   # out_bound OR unloaded_at_port is set
STATUS_INBOUND    = 6   # in_bound date is set
STATUS_EMPTY      = 7   # empty_date is set
STATUS_UNKNOWN    = 8

# Statuses that must NOT be overridden by the arrival-date cron logic
STATUS_SKIP_IDS = {STATUS_GATE_PASS, STATUS_COMPLETE, STATUS_INBOUND, STATUS_EMPTY, STATUS_UNKNOWN}


def derive_status_from_dates(container) -> int | None:
    """Return the appropriate status integer derived from a container's date fields.

    Priority (highest → lowest):
      1. out_bound OR unloaded_at_port  → Complete  (4)
      2. empty_date                     → Unloaded     (7)
      3. in_bound                       → Inbound   (6)
      4. None of the above              → return None (leave unchanged; cron handles the rest)

    Call this whenever in_bound, empty_date, out_bound, or unloaded_at_port is written
    so the status stays consistent with the data.
    """
    if container.out_bound or container.unloaded_at_port:
        return STATUS_COMPLETE
    if container.empty_date:
        return STATUS_EMPTY
    if container.in_bound:
        return STATUS_INBOUND
    return None


# ── Job 1: Refresh ETAs from the shipping provider ────────────────────────────
def updateArrivalDate():
    """Fetch the latest ETA from the shipping provider and persist it to the DB."""
    db = next(get_db())
    try:
        records = (
            db.query(bl)
            .filter(bl.ArrivalDate > datetime.now())
            .all()
        )
        for record in records:
            data = track_and_trace(record.BillOfLanding)
            logger.info(
                "[updateArrivalDate] BoL=%s | data=%s",
                record.BillOfLanding,
                data,
            )
            if data:
                db.query(bl).filter(bl.BillOfLanding == record.BillOfLanding).update(
                    {
                        bl.ArrivalDate: datetime.fromisoformat(
                            data[0]["eventDateTime"]
                        ).strftime("%Y-%m-%d %H:%M:%S")
                    }
                )
                db.commit()
    except Exception as e:
        logger.exception("[updateArrivalDate] Error: %s", e)
    finally:
        db.close()


# ── Job 2: Auto-update container status based on ArrivalDate ──────────────────
def updateContainerStatus():
    """Auto-update container status based on the linked BillOfLanding ArrivalDate.

    Rules
    ─────
    - ArrivalDate <= NOW  →  status = 2 (On Port)    [vessel has arrived]
    - ArrivalDate >  NOW  →  status = 1 (In Transit)  [vessel still at sea]

    Containers already in Gate Pass (3), Complete (4), Inbound (6),
    Unloaded (7), or Unknown (8) are intentionally left untouched.

    Schedule: 04:01, 13:01, 20:01 daily (runs 1 minute after updateArrivalDate).
    """
    now = datetime.now()
    logger.info(
        "[updateContainerStatus] Running at %s",
        now.strftime("%Y-%m-%d %H:%M:%S"),
    )
    db = next(get_db())
    updated_on_port = 0
    updated_in_transit = 0
    try:
        # Fetch all containers that still participate in transit/port logic
        containers = (
            db.query(cd)
            .filter(cd.status.notin_(STATUS_SKIP_IDS))
            .all()
        )

        for container in containers:
            # Resolve ArrivalDate through the linked BillOfLanding
            arrival: datetime | None = None
            if container.bill_of_landing and container.bill_of_landing.ArrivalDate:
                arrival = container.bill_of_landing.ArrivalDate
                if not isinstance(arrival, datetime):
                    # Coerce plain date → datetime for comparison
                    if isinstance(arrival, date_type):
                        arrival = datetime.combine(arrival, datetime.min.time())

            if arrival is None:
                # No arrival date linked — skip this container
                continue

            if arrival <= now:
                # Vessel has arrived — mark as On Port
                if container.status != STATUS_ON_PORT:
                    container.status = STATUS_ON_PORT
                    updated_on_port += 1
                    logger.info(
                        "[updateContainerStatus] Container %s → On Port (ArrivalDate=%s)",
                        container.container_no,
                        arrival,
                    )
            else:
                # Vessel still at sea — mark as In Transit
                if container.status != STATUS_IN_TRANSIT:
                    container.status = STATUS_IN_TRANSIT
                    updated_in_transit += 1
                    logger.info(
                        "[updateContainerStatus] Container %s → In Transit (ArrivalDate=%s)",
                        container.container_no,
                        arrival,
                    )

        db.commit()
        logger.info(
            "[updateContainerStatus] Done — On Port: %d | In Transit: %d | Unchanged: %d",
            updated_on_port,
            updated_in_transit,
            len(containers) - updated_on_port - updated_in_transit,
        )
    except Exception as e:
        db.rollback()
        logger.exception("[updateContainerStatus] Error: %s", e)
    finally:
        db.close()


# ── One-shot startup backfill ──────────────────────────────────────────────────
def backfill_container_statuses():
    """Scan every non-deleted container and fix statuses that are missing or wrong.

    Applies the full priority chain:
      1. out_bound / unloaded_at_port  → Complete  (4)
      2. empty_date                    → Unloaded     (7)
      3. in_bound                      → Inbound   (6)
      4. ArrivalDate <= now            → On Port   (2)
      5. ArrivalDate > now             → In Transit (1)
      6. No dates at all               → Unknown   (8)

    Gate Pass (3) containers are skipped — they were set manually and must
    not be overridden.

    Called once from the FastAPI startup event to correct records entered
    before the auto-status logic was introduced.
    """
    now = datetime.now()
    logger.info("[backfill] Starting one-shot status backfill at %s", now.strftime("%Y-%m-%d %H:%M:%S"))
    db = next(get_db())

    counts = {
        "complete": 0, "empty": 0, "inbound": 0,
        "on_port": 0, "in_transit": 0, "unknown": 0,
        "skipped_gate_pass": 0, "already_correct": 0,
    }

    try:
        containers = (
            db.query(cd)
            .filter(cd.is_deleted == False)
            .all()
        )

        for container in containers:
            # Gate Pass is a manual state — never touch it
            if container.status == STATUS_GATE_PASS:
                counts["skipped_gate_pass"] += 1
                continue

            # ── Step 1: derive from date fields ───────────────────────────
            new_status = derive_status_from_dates(container)

            # ── Step 2: fall back to ArrivalDate-based logic ──────────────
            if new_status is None:
                arrival = None
                if container.bill_of_landing and container.bill_of_landing.ArrivalDate:
                    arrival = container.bill_of_landing.ArrivalDate
                    if not isinstance(arrival, datetime):
                        if isinstance(arrival, date_type):
                            arrival = datetime.combine(arrival, datetime.min.time())

                if arrival is None:
                    new_status = STATUS_UNKNOWN
                elif arrival <= now:
                    new_status = STATUS_ON_PORT
                else:
                    new_status = STATUS_IN_TRANSIT

            # ── Apply only if something actually changed ───────────────────
            if container.status == new_status:
                counts["already_correct"] += 1
                continue

            old_status = container.status
            container.status = new_status

            label = {
                STATUS_COMPLETE:   "complete",
                STATUS_EMPTY:      "empty",
                STATUS_INBOUND:    "inbound",
                STATUS_ON_PORT:    "on_port",
                STATUS_IN_TRANSIT: "in_transit",
                STATUS_UNKNOWN:    "unknown",
            }.get(new_status, str(new_status))
            counts[label] = counts.get(label, 0) + 1

            logger.info(
                "[backfill] Container %s | %s → %s",
                container.container_no,
                old_status,
                new_status,
            )

        db.commit()
        logger.info(
            "[backfill] Done — Complete: %(complete)d | Empty: %(empty)d | "
            "Inbound: %(inbound)d | On Port: %(on_port)d | In Transit: %(in_transit)d | "
            "Unknown: %(unknown)d | Gate Pass skipped: %(skipped_gate_pass)d | "
            "Already correct: %(already_correct)d",
            counts,
        )
    except Exception as e:
        db.rollback()
        logger.exception("[backfill] Error during status backfill: %s", e)
    finally:
        db.close()


# ── Scheduler factory ─────────────────────────────────────────────────────────
def create_scheduler() -> BackgroundScheduler:
    """Build and return a configured (but not yet started) BackgroundScheduler."""
    scheduler = BackgroundScheduler()

    # Job 1 — refresh ETAs from the shipping provider (runs first)
    scheduler.add_job(
        updateArrivalDate,
        "cron",
        hour="4,13,20",
        minute=0,
        id="updateArrivalDate",
    )

    # Job 2 — auto-update container statuses (runs 1 minute after Job 1)
    scheduler.add_job(
        updateContainerStatus,
        "cron",
        hour="4,13,20",
        minute=1,
        id="updateContainerStatus",
    )

    return scheduler
