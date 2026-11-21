from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

# TABLE: Frozen copy of a whole PO at a given version and stage.
class POVersionSnapshot(AuditMixin, Base):
    """
    Immutable audit snapshot capturing the exact state of a Purchase Order at a given version and stage.
    """
    __tablename__ = "po_version_snapshots"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, required.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # lifecycle_stage - VARCHAR(30), required.
    # Stage when the snapshot was taken.
    lifecycle_stage = Column(String(30), nullable=False, index=True) # e.g. 'DRAFT', 'CONFIRMED'
    # stage_version - INTEGER, required, default 1.
    # Version within that stage.
    stage_version = Column(Integer, nullable=False, default=1)       # Version within stage: 1, 2, 3...
    # global_version - INTEGER, required.
    # Overall sequential version number.
    global_version = Column(Integer, nullable=False)                 # Sequential overall version counter
    
    # parent_snapshot_id - INTEGER, foreign key -> containermgmt.po_version_snapshots.id, optional.
    # Previous snapshot.
    parent_snapshot_id = Column(Integer, ForeignKey("containermgmt.po_version_snapshots.id", ondelete="SET NULL"), nullable=True)
    # transition_type - VARCHAR(30), required, default MUTATION.
    # INITIAL, STAGE_ADVANCE, STAGE_ROLLBACK, MUTATION or VARIANCE_APPROVED.
    transition_type = Column(String(30), nullable=False, default="MUTATION") # INITIAL, STAGE_ADVANCE, STAGE_ROLLBACK, MUTATION, VARIANCE_APPROVED
    # change_summary - TEXT, optional.
    # Plain-text summary of what changed.
    change_summary = Column(Text, nullable=True)
    # diff_data - JSON, optional.
    # Field-by-field differences (JSON).
    diff_data = Column(JSON, nullable=True)       # Array of specific field/item diffs
    # snapshot_data - JSON, required.
    # Complete PO contents at this version (JSON).
    snapshot_data = Column(JSON, nullable=False)   # Complete JSON representation of the PO at this version
    
    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="version_snapshots")
    parent_snapshot = relationship("POVersionSnapshot", remote_side=[id])
