from sqlalchemy import Column, Integer, String, Boolean
from ...db import Base
from ...mixins import AuditMixin

class OrderStatus(AuditMixin, Base):
    __tablename__ = "order_status"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), nullable=True)
    sequence_order = Column(Integer, default=10)
    progress = Column(Integer, default=0)
    color = Column(String(50), default="bg-blue-500")
    badge_color = Column(String(200), default="bg-blue-50 text-blue-800 border-blue-200")
    is_active = Column(Boolean, default=True)
