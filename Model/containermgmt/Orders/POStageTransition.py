from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Audit log of each move between procurement lifecycle stages.
class POStageTransition(OrgMixin, AuditMixin, Base):
    """
    Audit log of all procurement lifecycle stage transitions.
    """
    __tablename__ = "po_stage_transitions"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, required.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # from_stage - VARCHAR(30), required.
    # Stage before.
    from_stage = Column(String(30), nullable=False)
    # to_stage - VARCHAR(30), required.
    # Stage after.
    to_stage = Column(String(30), nullable=False)
    # from_version - INTEGER, required.
    # Version before.
    from_version = Column(Integer, nullable=False)
    # to_version - INTEGER, required.
    # Version after.
    to_version = Column(Integer, nullable=False)
    
    # transition_type - VARCHAR(20), optional, default ADVANCE.
    # ADVANCE, ROLLBACK or REJECT.
    transition_type = Column(String(20), default="ADVANCE") # ADVANCE, ROLLBACK, REJECT
    # comment - TEXT, optional.
    # Reason/comment given.
    comment = Column(Text, nullable=True)
    # gate_checks_passed - BOOLEAN, optional, default True.
    # True if all required checks passed.
    gate_checks_passed = Column(Boolean, default=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="stage_transitions")
