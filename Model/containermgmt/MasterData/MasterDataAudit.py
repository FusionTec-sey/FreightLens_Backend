from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func, Index

from ...db import Base


class MasterDataAudit(Base):
    """Who changed a shared master record, and what it said before.

    Shared records are edited by any user with the right permission, from any
    company, and one edit is seen by every company at once -- a renamed vendor
    changes what everyone's screens show. That is only safe if the change is
    attributable, so every field change is recorded here, one row per field.

    Follows po_item_history: action plus field_name / old_value / new_value.
    """
    __tablename__ = "master_data_audit"
    __table_args__ = (
        Index("ix_master_data_audit_entity", "entity_type", "entity_id"),
        {"schema": "containermgmt"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    entity_type = Column(String(40), nullable=False, index=True)  # "supplier", "product_category"
    entity_id = Column(Integer, nullable=False)
    # The company the record belonged to when it changed. Null for a shared
    # record, which belongs to no single company.
    org_id = Column(Integer, nullable=True)

    action = Column(String(20), nullable=False)  # created | updated | deleted
    field_name = Column(String(60), nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    changed_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
