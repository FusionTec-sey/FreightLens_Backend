"""Which screen fields belong to which field class.

A field class groups fields that stand or fall together -- customs tax, free-day
allowances, the internal note -- and is gated by a pair of permissions:
``View_X`` shows the group locked, ``Edit_X`` makes it writable, neither hides
it. ``AccessPolicy.field_mode`` resolves the three.

The binding lives in code rather than the database for the same reason
``page_registry`` does: the classes are few and shared, the field keys are a
property of the API contract, and declaring them here buys an import-time check
that every class is real.

Field keys are the names the API uses on the wire, not the column names and not
the frontend's form state -- so ``FreeDays``, not ``freeDays``; ``container_no``,
not ``containerNo``. Nested payloads use a dotted key, matching how the
multipart form already arrives (``bill_of_landing.FreeDays``).

A field that is not registered here is unclassified and therefore open, which is
how unclassified report columns have always behaved.
"""

from types import MappingProxyType
from typing import Mapping

from Model.containermgmt.Report.ReportFieldClass import ReportFieldClass  # noqa: F401
from .catalog import PERMISSION_BY_NAME

# -- Field classes declared by this module -----------------------------------
# code -> (view permission, edit permission or None, description)
FIELD_CLASS_SPECS: tuple[tuple[str, str, str | None, str], ...] = (
    (
        "CONTAINER_TAX",
        "View_ContainerTax",
        "Edit_ContainerTax",
        "Customs tax and duty flags on a container",
    ),
    (
        "CONTAINER_DEMURRAGE",
        "View_Demurrage",
        "Edit_Demurrage",
        "Free-day allowances and demurrage overrides",
    ),
    (
        "CONTAINER_IDENTITY",
        "View_ContainerNo",
        "Edit_ContainerNo",
        "The container number itself",
    ),
    (
        "CONTAINER_MILESTONE",
        "View_ContainerMilestone",
        "Edit_ContainerMilestone",
        "Port milestones and gate movements",
    ),
    (
        "CONTAINER_CARGO",
        "View_Material",
        "Edit_Material",
        "Cargo materials and categories",
    ),
    (
        "CONTAINER_PURCHASE_ORDER",
        "View_ContainerPO",
        "Edit_ContainerPO",
        "Purchase orders linked to a container",
    ),
    (
        "CONTAINER_NOTE",
        "View_ContainerNote",
        "Edit_ContainerNote",
        "Internal operations notes",
    ),
    (
        "CONTAINER_STATUS",
        "View_Status",
        "Edit_Status",
        "Operational status of a container and its bill of lading",
    ),
    (
        "CONTAINER_TYPE",
        "View_ContainerType",
        "Edit_ContainerType",
        "Container type, such as 20ft or 40ft",
    ),
)

# -- entity -> field key -> field class --------------------------------------
_CONTAINER_FIELDS: Mapping[str, str] = {
    "container_no": "CONTAINER_IDENTITY",
    "tax": "CONTAINER_TAX",
    "FreeDays": "CONTAINER_DEMURRAGE",
    "bill_of_landing.FreeDays": "CONTAINER_DEMURRAGE",
    "in_bound": "CONTAINER_MILESTONE",
    "out_bound": "CONTAINER_MILESTONE",
    "unloaded_at_port": "CONTAINER_MILESTONE",
    "empty_date": "CONTAINER_MILESTONE",
    "emptied_at": "CONTAINER_MILESTONE",
    "bill_of_landing.ArrivalDate": "CONTAINER_MILESTONE",
    "materials": "CONTAINER_CARGO",
    # The order link is its own class: who may say what is in a container and
    # who may say which orders it fulfils are different questions, and the
    # latter reaches into the purchasing side of the system.
    "po_ids": "CONTAINER_PURCHASE_ORDER",
    "PONo": "CONTAINER_PURCHASE_ORDER",
    "note": "CONTAINER_NOTE",
    # Both halves of status belong to one class. Setting it on the bill of
    # lading cascades to every container on that B/L, so gating the container
    # field alone would leave the cascade as a way round it.
    "status": "CONTAINER_STATUS",
    "bill_of_landing.status": "CONTAINER_STATUS",
    "type": "CONTAINER_TYPE",
    # Read-only companions the detail response exposes under their own names.
    # Listing them here keeps redaction and write gating on one source of truth;
    # they never appear in a write payload, so gating them costs nothing.
    "emptied_at_rel": "CONTAINER_MILESTONE",
    "purchase_orders": "CONTAINER_PURCHASE_ORDER",
    "status_rel": "CONTAINER_STATUS",
    "type_rel": "CONTAINER_TYPE",
    "containerType": "CONTAINER_TYPE",
}

FIELD_REGISTRY: Mapping[str, Mapping[str, str]] = MappingProxyType({
    "container": MappingProxyType(dict(_CONTAINER_FIELDS)),
})

# Fields gated for writing but never redacted from a response.
#
# The container number is the record's identity: it labels the drawer header,
# the register column and every printed document. Withholding the right to
# change it is reasonable; blanking it out would leave the user unable to tell
# which container they are looking at. Keep this set very small -- anything
# genuinely confidential belongs in a class that redacts.
#
# The linked orders are here for a different reason: the packing panel exists to
# show them, and the delivery roles that pack containers hold no order
# permissions, so redacting them emptied the panel for its own audience.
# Deciding which orders a container fulfils still needs Edit_ContainerPO.
WRITE_GATED_ONLY: frozenset[str] = frozenset({"container_no", "purchase_orders"})

FIELD_CLASS_BY_CODE = MappingProxyType({
    code: {"view": view, "edit": edit, "description": description}
    for code, view, edit, description in FIELD_CLASS_SPECS
})

# -- Registry integrity, enforced at import time -----------------------------
if len(FIELD_CLASS_BY_CODE) != len(FIELD_CLASS_SPECS):
    raise RuntimeError("Field class registry contains duplicate codes")
for _code, _view, _edit, _ in FIELD_CLASS_SPECS:
    for _permission in (_view, _edit):
        if _permission and _permission not in PERMISSION_BY_NAME:
            raise RuntimeError(
                f"Field class {_code} requires permission '{_permission}', "
                "which is not declared in the permission catalog"
            )
for _entity, _fields in FIELD_REGISTRY.items():
    for _key, _class_code in _fields.items():
        if _class_code not in FIELD_CLASS_BY_CODE:
            raise RuntimeError(
                f"Field {_entity}.{_key} references unknown field class {_class_code}"
            )


def field_class_for(entity: str, field_key: str) -> str | None:
    """The class gating one field, or None when the field is unclassified."""
    return FIELD_REGISTRY.get(entity, {}).get(field_key)


def classified_fields(entity: str) -> Mapping[str, str]:
    return FIELD_REGISTRY.get(entity, {})


def partition_by_mode(policy, entity: str, keys) -> tuple[list[str], list[str]]:
    """Split field keys into (writable, refused) for this policy.

    Unclassified keys are always writable, so callers can pass a whole payload
    without first knowing which of its keys are gated.
    """
    writable: list[str] = []
    refused: list[str] = []
    for key in keys:
        code = field_class_for(entity, key)
        if code is None or policy.allows_field_write(code):
            writable.append(key)
        else:
            refused.append(key)
    return writable, refused


def sync_field_classes(db) -> None:
    """Upsert the declared classes into ``report_field_classes``.

    Additive, like ``sync_permission_catalog``: rows seeded elsewhere (the
    reporting classes) are left alone, and a class whose edit permission is added
    later simply gains it.
    """
    existing = {row.code: row for row in db.query(ReportFieldClass).all()}
    for code, view_permission, edit_permission, description in FIELD_CLASS_SPECS:
        row = existing.get(code)
        if row is None:
            db.add(ReportFieldClass(
                code=code,
                permission_name=view_permission,
                edit_permission_name=edit_permission,
                description=description,
            ))
            continue
        row.permission_name = view_permission
        row.edit_permission_name = edit_permission
        row.description = description
