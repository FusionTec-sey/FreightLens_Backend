from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

class POVersionSnapshot(AuditMixin, Base):
    """
    Immutable audit snapshot capturing the exact state of a Purchase Order at a given version and stage.
    """
    __tablename__ = "po_version_snapshots"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    lifecycle_stage = Column(String(30), nullable=False, index=True) # e.g. 'DRAFT', 'CONFIRMED'
    stage_version = Column(Integer, nullable=False, default=1)       # Version within stage: 1, 2, 3...
    global_version = Column(Integer, nullable=False)                 # Sequential overall version counter
    
    parent_snapshot_id = Column(Integer, ForeignKey("containermgmt.po_version_snapshots.id", ondelete="SET NULL"), nullable=True)
    transition_type = Column(String(30), nullable=False, default="MUTATION") # INITIAL, STAGE_ADVANCE, STAGE_ROLLBACK, MUTATION, VARIANCE_APPROVED
    change_summary = Column(Text, nullable=True)
    diff_data = Column(JSON, nullable=True)       # Array of specific field/item diffs
    snapshot_data = Column(JSON, nullable=False)   # Complete JSON representation of the PO at this version
    
    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="version_snapshots")
    parent_snapshot = relationship("POVersionSnapshot", remote_side=[id])
