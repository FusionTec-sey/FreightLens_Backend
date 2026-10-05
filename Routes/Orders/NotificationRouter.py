import math
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from Model.db import get_db
from Model.containermgmt.Orders.Notification import Notification
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from Utils.org_filter import OrgContext, apply_org_filter

logger = logging.getLogger("containerMgmt.notifications")

NotificationRouter = APIRouter(prefix="/notifications", tags=["Notifications"])

@NotificationRouter.get("")
@NotificationRouter.get("/")
async def list_notifications(
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    query = apply_org_filter(query, Notification, org_context)

    if unread_only:
        query = query.filter(Notification.is_read == False)

    total = query.count()
    notifs = query.order_by(desc(Notification.created_at), desc(Notification.id)).offset(
        (page - 1) * limit).limit(limit).all()
    
    unread_count = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,
    )
    unread_count = apply_org_filter(unread_count, Notification, org_context).count()

    return {
        "unread_count": unread_count,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total / limit) if total else 1,
        "notifications": [
            {
                "id": n.id,
                "event_type": n.event_type,
                "title": n.title,
                "message": n.message,
                "link_entity_type": n.link_entity_type,
                "link_entity_id": n.link_entity_id,
                "is_read": bool(n.is_read),
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifs
        ]
    }

@NotificationRouter.patch("/{notif_id}/read")
async def mark_read(
    notif_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Notification).filter(
        Notification.id == notif_id,
        Notification.user_id == current_user.id,
    )
    n = apply_org_filter(query, Notification, org_context).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    db.commit()
    return {"success": True}

@NotificationRouter.post("/mark-all-read")
async def mark_all_read(
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,
    )
    query = apply_org_filter(query, Notification, org_context)
    query.update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"success": True}
