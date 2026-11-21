from sqlalchemy import Column, Integer, DateTime, Boolean, ForeignKey, func, text
from sqlalchemy.orm import declared_attr, relationship

# Standard audit columns added to most tables: who/when a row was created, changed and soft-deleted.
class AuditMixin:
    """
    Mixin to automatically add standard audit columns to a SQLAlchemy model.
    """
    # created_at - TIMESTAMP WITH TIME ZONE, required, default now().
    # When the row was first created. Filled in automatically by the database.
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # updated_at - TIMESTAMP WITH TIME ZONE, required, default now().
    # When the row was last changed. Refreshed automatically on every update.
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # is_deleted - BOOLEAN, required, default false.
    # Soft delete. True = row is hidden from screens but kept in the database so history
    # and references to it survive. False = normal, visible row.
    is_deleted = Column(Boolean, default=False, server_default=text('false'), nullable=False)
    # deleted_at - TIMESTAMP WITH TIME ZONE, optional.
    # When the row was soft-deleted. Empty while the row is still active.
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def created_by(cls):
        # created_by - INTEGER, foreign key -> usercredentials.users.id, optional.
        # User who created the row (empty for system-generated rows).
        # Using string reference for the foreign key to avoid circular imports.
        # Ensure the 'usercredentials' schema exists and matches the user table setup.
        return Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)

    @declared_attr
    def updated_by(cls):
        # updated_by - INTEGER, foreign key -> usercredentials.users.id, optional.
        # User who last changed the row.
        return Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)
        
    @declared_attr
    def deleted_by(cls):
        # deleted_by - INTEGER, foreign key -> usercredentials.users.id, optional.
        # User who soft-deleted the row.
        return Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)

    @declared_attr
    def created_by_user(cls):
        return relationship("User", primaryjoin=f"User.id == {cls.__name__}.created_by", viewonly=True)

    @declared_attr
    def updated_by_user(cls):
        return relationship("User", primaryjoin=f"User.id == {cls.__name__}.updated_by", viewonly=True)


# Adds org_id so every row belongs to exactly one company (multi-tenant isolation).
class OrgMixin:
    """
    Mixin to automatically add org_id column to data models for multi-tenant row isolation.
    """
    @declared_attr
    def org_id(cls):
        # org_id - INTEGER, foreign key -> usercredentials.organisations.id, required, indexed.
        # Company (tenant) that owns this row. Every query is filtered on it so one company
        # never sees another company's data.
        return Column(Integer, ForeignKey('usercredentials.organisations.id'), nullable=False, index=True)

    @declared_attr
    def organisation(cls):
        return relationship("Organisation", primaryjoin=f"Organisation.id == {cls.__name__}.org_id", viewonly=True)

