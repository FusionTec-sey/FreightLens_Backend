from sqlalchemy import Column, Integer, String, Boolean
from ...db import Base
from ...mixins import AuditMixin

# TABLE: Lookup of order status names, order and badge colours.
class OrderStatus(AuditMixin, Base):
    __tablename__ = "order_status"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # name - VARCHAR(100), required.
    # Status name shown to users.
    name = Column(String(100), nullable=False)
    # code - VARCHAR(50), optional.
    # Short status code.
    code = Column(String(50), nullable=True)
    # sequence_order - INTEGER, optional, default 10.
    # Position in the status sequence.
    sequence_order = Column(Integer, default=10)
    # progress - INTEGER, optional, default 0.
    # Progress percentage this status represents.
    progress = Column(Integer, default=0)
    # color - VARCHAR(50), optional, default bg-blue-500.
    # Colour class for progress bars.
    color = Column(String(50), default="bg-blue-500")
    # badge_color - VARCHAR(200), optional, default bg-blue-50 text-blue-800 border-blue-200.
    # Colour classes for the status badge.
    badge_color = Column(String(200), default="bg-blue-50 text-blue-800 border-blue-200")
    # is_active - BOOLEAN, optional, default True.
    # False hides the record from use without deleting it.
    is_active = Column(Boolean, default=True)
