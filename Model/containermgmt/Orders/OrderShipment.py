from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class OrderShipment(OrgMixin, AuditMixin, Base):
    __tablename__ = "order_shipments"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Nullable: an order is linked to a container before the container has a
    # manifest. The empty string that stood in for "no B/L yet" is not a
    # bill_of_landing row, so it violated the foreign key outright.
    bill_of_lading_no = Column(String(100), ForeignKey("containermgmt.bill_of_landing.BillOfLanding"), nullable=True, index=True)
    container_id = Column(Integer, ForeignKey("containermgmt.container_details.Container_ID"), nullable=True, index=True)
    
    # Partial / full shipment tracking
    shipment_status = Column(String(50), default="IN_TRANSIT")  # IN_TRANSIT, ARRIVED, DELIVERED, COMPLETED
    notes = Column(Text, nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="shipments")
    bill_of_lading = relationship("BillOfLanding", foreign_keys=[bill_of_lading_no], lazy="joined")
    container = relationship("ContainerDetails", foreign_keys=[container_id], lazy="joined")
