from sqlalchemy import Column, Integer, DateTime, Boolean, ForeignKey, func, text
from sqlalchemy.orm import declared_attr, relationship

class AuditMixin:
    """
    Mixin to automatically add standard audit columns to a SQLAlchemy model.
    """
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    is_deleted = Column(Boolean, default=False, server_default=text('false'), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def created_by(cls):
        # Using string reference for the foreign key to avoid circular imports.
        # Ensure the 'usercredentials' schema exists and matches the user table setup.
        return Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)

    @declared_attr
    def updated_by(cls):
        return Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)
        
    @declared_attr
    def deleted_by(cls):
        return Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)

    @declared_attr
    def created_by_user(cls):
        return relationship("User", primaryjoin=f"User.id == {cls.__name__}.created_by", viewonly=True)

    @declared_attr
    def updated_by_user(cls):
        return relationship("User", primaryjoin=f"User.id == {cls.__name__}.updated_by", viewonly=True)


class OrgMixin:
    """
    Mixin to automatically add org_id column to data models for multi-tenant row isolation.
    """
    @declared_attr
    def org_id(cls):
        return Column(Integer, ForeignKey('usercredentials.organisations.id'), nullable=False, index=True)

    @declared_attr
    def organisation(cls):
        return relationship("Organisation", primaryjoin=f"Organisation.id == {cls.__name__}.org_id", viewonly=True)

