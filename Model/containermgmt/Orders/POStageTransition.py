from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

class POStageTransition(AuditMixin, Base):
    """
    Audit log of all procurement lifecycle stage transitions.
    """
    __tablename__ = "po_stage_transitions"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    from_stage = Column(String(30), nullable=False)
    to_stage = Column(String(30), nullable=False)
    from_version = Column(Integer, nullable=False)
    to_version = Column(Integer, nullable=False)
    
    transition_type = Column(String(20), default="ADVANCE") # ADVANCE, ROLLBACK, REJECT
    comment = Column(Text, nullable=True)
    gate_checks_passed = Column(Boolean, default=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="stage_transitions")
