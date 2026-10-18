"""Move a menu layout between companies, and between installations.

A menu carries no authority. Every item is put through ``policy_allows_page``
for the person looking at it, so a layout that names a page grants nobody
access to it. That is what makes this safe to hand around: the file holds the
design, and the roles that decide who sees it stay where they are, per company,
assigned by hand.

So nothing identifying travels. No ids, no org_id, no role assignments, no
audit columns. The tree is carried as nesting rather than ``parent_id``,
because a parent id means nothing in another database.

The one thing that can stop an import is ``page_key``: it is a foreign key into
``app_pages``, which is rebuilt from the code's PAGE_REGISTRY at startup. A
menu designed on a newer build can name a page an older installation has never
heard of, and the foreign key would reject the insert outright. So the import
checks first, and refuses the whole file rather than quietly dropping entries --
a menu missing three screens is worse than one that never arrived, because
nobody finds out until they go looking for something that is not there.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from Model.Credentials.app_page import AppPage
from Model.Credentials.menu import Menu
from Model.Credentials.menu_item import MenuItem

FORMAT_VERSION = 1

# Enough to stop a malformed file making a menu nobody can use or delete.
MAX_ITEMS = 500
MAX_DEPTH = 5
MAX_LABEL = 100
MAX_ICON = 50
MAX_NAME = 100
MAX_DESCRIPTION = 255


class MenuTransferError(Exception):
    """A file that cannot become a menu here, with the reason a person needs."""

    def __init__(self, message: str, missing_pages: Optional[List[str]] = None):
        super().__init__(message)
        self.message = message
        self.missing_pages = missing_pages or []


# ── Export ───────────────────────────────────────────────────────────────────

def registry_fingerprint(db: Session) -> Dict[str, Any]:
    """What this installation knows how to show.

    Carried for context in a refusal message, not as the test. Comparing
    fingerprints would reject every file from a newer build, including the many
    that only use pages this one has had for releases.
    """
    keys = sorted(row[0] for row in db.query(AppPage.page_key).all())
    digest = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:12]
    return {"page_count": len(keys), "digest": digest}


def _item_payload(item: MenuItem, children: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "label": item.label,
        "icon": item.icon,
        "page_key": item.page_key,
        "is_separator": bool(item.is_separator),
        "is_active": bool(item.is_active),
        "show_when_locked": bool(item.show_when_locked),
        "sort_order": item.sort_order or 0,
        "children": children,
    }


def serialize_menu(db: Session, menu: Menu, org_label: Optional[str] = None) -> Dict[str, Any]:
    """The menu as a portable document."""
    rows = (
        db.query(MenuItem)
        .filter(MenuItem.menu_id == menu.id, MenuItem.is_deleted.is_(False))
        .order_by(MenuItem.sort_order, MenuItem.id)
        .all()
    )

    by_parent: Dict[Optional[int], List[MenuItem]] = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, []).append(row)

    def build(parent_id: Optional[int], depth: int) -> List[Dict[str, Any]]:
        # Depth-capped on the way out as well as in: a cycle in stored data
        # would otherwise recurse until the stack gives out.
        if depth > MAX_DEPTH:
            return []
        return [
            _item_payload(child, build(child.id, depth + 1))
            for child in by_parent.get(parent_id, [])
        ]

    return {
        "format": FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exported_from": org_label,
        "registry": registry_fingerprint(db),
        "menu": {"name": menu.name, "description": menu.description},
        "items": build(None, 1),
    }


# ── Import ───────────────────────────────────────────────────────────────────

def _walk(items: Any, depth: int, out: List[Tuple[Dict[str, Any], int]]) -> None:
    if depth > MAX_DEPTH:
        raise MenuTransferError(
            f"This menu is nested more than {MAX_DEPTH} levels deep, which this app cannot show."
        )
    if not isinstance(items, list):
        raise MenuTransferError("The file is not shaped like a menu: items should be a list.")
    for raw in items:
        if not isinstance(raw, dict):
            raise MenuTransferError("The file is not shaped like a menu: an item is not an object.")
        out.append((raw, depth))
        _walk(raw.get("children") or [], depth + 1, out)


def inspect_document(db: Session, document: Any) -> Dict[str, Any]:
    """Read a file and say what importing it would do. Writes nothing."""
    if not isinstance(document, dict):
        raise MenuTransferError("That file is not a menu export.")

    fmt = document.get("format")
    if fmt != FORMAT_VERSION:
        raise MenuTransferError(
            f"This file is format {fmt!r}; this app reads format {FORMAT_VERSION}."
        )

    menu_block = document.get("menu")
    if not isinstance(menu_block, dict) or not (menu_block.get("name") or "").strip():
        raise MenuTransferError("The file does not name the menu it holds.")

    flat: List[Tuple[Dict[str, Any], int]] = []
    _walk(document.get("items") or [], 1, flat)

    if not flat:
        raise MenuTransferError("That menu has no items in it.")
    if len(flat) > MAX_ITEMS:
        raise MenuTransferError(
            f"This menu has {len(flat)} items; the most this app will import at once is {MAX_ITEMS}."
        )

    for raw, _ in flat:
        label = (raw.get("label") or "").strip()
        if not label:
            raise MenuTransferError("An item in this file has no label.")
        if len(label) > MAX_LABEL:
            raise MenuTransferError(f"The label {label[:30]!r}… is longer than {MAX_LABEL} characters.")

    # The test that matters: the pages this menu names, against the pages this
    # installation has. Not a build comparison -- a menu from a newer build
    # imports cleanly if it happens to name nothing new, which is the usual case.
    wanted = {
        (raw.get("page_key") or "").strip()
        for raw, _ in flat
        if (raw.get("page_key") or "").strip()
    }
    known = {row[0] for row in db.query(AppPage.page_key).filter(AppPage.page_key.in_(wanted)).all()} if wanted else set()
    missing = sorted(wanted - known)

    return {
        "name": menu_block.get("name", "").strip()[:MAX_NAME],
        "description": (menu_block.get("description") or "").strip()[:MAX_DESCRIPTION] or None,
        "item_count": len(flat),
        "page_count": len(wanted),
        "separator_count": len([1 for raw, _ in flat if raw.get("is_separator")]),
        "missing_pages": missing,
        "can_import": not missing,
        "exported_from": document.get("exported_from"),
        "exported_at": document.get("exported_at"),
        "source_registry": document.get("registry") or {},
        # The nesting, kept for the builder; the flat list was only for checking.
        "items": document.get("items") or [],
    }


def refusal_message(report: Dict[str, Any], db: Session) -> str:
    """Why this file cannot be imported here, in words that say what to do."""
    missing = report["missing_pages"]
    here = registry_fingerprint(db)
    there = report.get("source_registry") or {}
    ahead = (there.get("page_count") or 0) > here["page_count"]

    opening = (
        "This menu was designed on a newer version of the app."
        if ahead
        else "This menu uses pages this installation does not have."
    )
    listed = ", ".join(missing[:8]) + ("…" if len(missing) > 8 else "")
    return (
        f"{opening} It uses {len(missing)} "
        f"page{'' if len(missing) == 1 else 's'} this installation does not have: {listed}. "
        "Update this installation, or export the menu again once these pages exist here."
    )


def unique_name(db: Session, org_id: int, wanted: str) -> str:
    """A name that does not collide, because importing never overwrites.

    Replacing a live sidebar from a file is how an afternoon disappears. The
    old menu stays until somebody deletes it on purpose.
    """
    taken = {
        row[0]
        for row in db.query(Menu.name).filter(
            Menu.org_id == org_id, Menu.is_deleted.is_(False)
        )
    }
    if wanted not in taken:
        return wanted
    for suffix in [" (imported)"] + [f" (imported {n})" for n in range(2, 50)]:
        candidate = f"{wanted}{suffix}"[:MAX_NAME]
        if candidate not in taken:
            return candidate
    return f"{wanted[:MAX_NAME - 10]} (imported)"


def build_menu(
    db: Session,
    report: Dict[str, Any],
    org_id: int,
    user_id: Optional[int],
    name_override: Optional[str] = None,
) -> Menu:
    """Create the menu and its items. Caller commits.

    It reaches nobody until a role is assigned to it, because roles did not
    travel and should not have.
    """
    if not report["can_import"]:
        raise MenuTransferError(refusal_message(report, db), report["missing_pages"])

    name = (name_override or report["name"]).strip()[:MAX_NAME]
    menu = Menu(
        org_id=org_id,
        name=unique_name(db, org_id, name),
        description=report["description"],
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(menu)
    db.flush()

    def create(items: List[Dict[str, Any]], parent_id: Optional[int], depth: int) -> None:
        for order, raw in enumerate(items, start=1):
            page_key = (raw.get("page_key") or "").strip() or None
            row = MenuItem(
                org_id=org_id,
                menu_id=menu.id,
                parent_id=parent_id,
                label=(raw.get("label") or "").strip()[:MAX_LABEL],
                icon=((raw.get("icon") or "").strip() or None),
                page_key=page_key,
                is_separator=bool(raw.get("is_separator")),
                is_active=bool(raw.get("is_active", True)),
                show_when_locked=bool(raw.get("show_when_locked")),
                # Renumbered rather than carried: the file's order is what
                # matters, and gaps in it are nobody's business here.
                sort_order=order * 10,
                created_by=user_id,
                updated_by=user_id,
            )
            if row.icon:
                row.icon = row.icon[:MAX_ICON]
            db.add(row)
            db.flush()
            create(raw.get("children") or [], row.id, depth + 1)

    create(report["items"], None, 1)
    return menu
