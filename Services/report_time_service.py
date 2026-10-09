"""The clock a printed document should use.

Documents carried UTC dates, so anything produced between midnight and 04:00 in
Seychelles was stamped with the previous day -- on purchase orders, RFQs and
export filenames alike. The organisation's own time zone is already stored on its
print profile (`Indian/Mahe` by default); this reads it and hands back the date
and time a reader in that organisation would recognise.
"""
import logging
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

logger = logging.getLogger("containerMgmt.report_time")

# Matches OrgPrintProfile.timezone's own default, so a missing profile and a
# default profile agree.
FALLBACK_TIMEZONE = "Indian/Mahe"


def org_timezone(db: Session, org_context) -> ZoneInfo:
    """The organisation's time zone, falling back rather than failing a render."""
    name = FALLBACK_TIMEZONE
    try:
        from Model.containermgmt.Report.OrgPrintProfile import OrgPrintProfile

        org_id = getattr(org_context, "org_id", None)
        if org_id is not None:
            profile = (
                db.query(OrgPrintProfile)
                .filter(OrgPrintProfile.org_id == org_id)
                .first()
            )
            if profile and profile.timezone:
                name = profile.timezone
    except Exception:
        logger.exception("Could not read the organisation time zone; using %s", FALLBACK_TIMEZONE)

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown time zone %r on the print profile; using %s", name, FALLBACK_TIMEZONE)
        return ZoneInfo(FALLBACK_TIMEZONE)


def org_timezone_name(db: Session, org_context) -> str:
    """The zone's name, for passing to the template renderer."""
    return str(org_timezone(db, org_context))


def org_now(db: Session, org_context) -> datetime:
    """Now, in the organisation's time zone."""
    return datetime.now(org_timezone(db, org_context))


def org_today(db: Session, org_context) -> date:
    """Today's date where the organisation is, not where the server is."""
    return org_now(db, org_context).date()


def org_today_iso(db: Session, org_context) -> str:
    return org_today(db, org_context).isoformat()


def stamp_for_filename(db: Session, org_context, when: Optional[datetime] = None) -> str:
    """`20261009_143000` in the organisation's time zone, for export filenames."""
    moment = when or org_now(db, org_context)
    return moment.strftime("%Y%m%d_%H%M%S")
