from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from Model.containermgmt.Report.OrgPrintProfile import OrgPrintProfile


DEFAULT_REPORT_TIMEZONE = "Indian/Mahe"


def report_timezone(db, org_id: int | None) -> ZoneInfo:
    timezone_name = DEFAULT_REPORT_TIMEZONE
    if db is not None and org_id:
        profile = db.query(OrgPrintProfile).filter(
            OrgPrintProfile.org_id == org_id,
            OrgPrintProfile.is_deleted.is_(False),
        ).first()
        timezone_name = getattr(profile, "timezone", None) or DEFAULT_REPORT_TIMEZONE
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_REPORT_TIMEZONE)


def report_now(db, org_id: int | None) -> datetime:
    return datetime.now(report_timezone(db, org_id))


def report_today(db, org_id: int | None):
    return report_now(db, org_id).date()
