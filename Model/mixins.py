from sqlalchemy import Column, Integer, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import declared_attr

class AuditMixin:
    """
    Mixin to automatically add standard audit columns to a SQLAlchemy model.
    """
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    is_deleted = Column(Boolean, default=False, nullable=False)
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
