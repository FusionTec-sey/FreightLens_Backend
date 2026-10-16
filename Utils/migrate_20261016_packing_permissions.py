import logging

from Model.db import SessionLocal
from Model.Credentials.permissions import Permission
from Model.Credentials.roles import Role

logger = logging.getLogger("containerMgmt.migrations")

# Role presets in seed.py are only applied when the role is first created, so a
# permission added to a preset later never reaches a role that already exists.
# These grants are additive and idempotent: they add what is missing and never
# remove anything, so a tenant that has tuned its own roles keeps its changes.
GRANTS = {
    # Packing a container is warehouse work. This role could read packing lists
    # and not build one, which is the wrong way round.
    "Warehouse_Operator": ["View_PackingList", "Add_PackingList", "Edit_PackingList"],
    # Already carries View/Add/Edit; voiding a confirmed list is an accounts
    # correction, so it gets the delete too.
    "Accounts_Finance": ["Delete_PackingList"],
    # Every non-platform permission, including the new override.
    "Tenant_Admin": ["Override_PackingQty", "Delete_PackingList"],
    "Super_Admin": ["Override_PackingQty"],
    "admin": ["Override_PackingQty"],
}


def ensure_packing_permissions():
    db = SessionLocal()
    try:
        wanted = {name for names in GRANTS.values() for name in names}
        perms = {
            p.name: p
            for p in db.query(Permission).filter(Permission.name.in_(wanted)).all()
        }
        missing = wanted - set(perms)
        if missing:
            # seed_db creates the catalogue; it runs before this.
            logger.warning("Packing permissions not in the catalogue yet: %s", ", ".join(sorted(missing)))

        added_total = 0
        for role_name, permission_names in GRANTS.items():
            role = db.query(Role).filter(Role.name == role_name).first()
            if not role:
                continue
            held = {p.name for p in (role.permissions or [])}
            added = [perms[n] for n in permission_names if n in perms and n not in held]
            if added:
                role.permissions = list(role.permissions or []) + added
                added_total += len(added)
                logger.info(
                    "Granted %s to role %s",
                    ", ".join(p.name for p in added),
                    role_name,
                )

        db.commit()
        logger.info("Packing list permissions verified (%s grants added).", added_total)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to grant packing list permissions: %s", exc)
    finally:
        db.close()


if __name__ == "__main__":
    ensure_packing_permissions()
