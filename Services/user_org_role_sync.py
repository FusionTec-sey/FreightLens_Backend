from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from Model.Credentials.Organisation import Organisation
from Model.Credentials.user_org_roles import user_org_roles
from Model.Credentials.users import User


def sync_user_org_roles(db: Session, user: User) -> None:
    """Mirror global roles into each active organisation available to a user."""
    org_ids = list(user.allowed_org_ids or ([user.org_id] if user.org_id else []))
    active_ids = (
        [
            row[0]
            for row in db.execute(
                select(Organisation.id).where(
                    Organisation.id.in_(org_ids),
                    Organisation.is_active.is_(True),
                )
            )
        ]
        if org_ids
        else []
    )

    db.execute(delete(user_org_roles).where(user_org_roles.c.user_id == user.id))
    rows = [
        {"user_id": user.id, "org_id": org_id, "role_id": role.id}
        for org_id in active_ids
        for role in user.roles
        if not getattr(role, "is_deleted", False)
        and (role.org_id is None or role.org_id == org_id)
    ]
    if rows:
        db.execute(insert(user_org_roles), rows)
