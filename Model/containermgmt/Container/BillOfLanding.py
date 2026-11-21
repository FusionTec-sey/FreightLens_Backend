from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from ...db import Base

from ...mixins import AuditMixin, OrgMixin

# TABLE: Bill of lading: the shipping document that groups containers on one voyage.
class BillOfLanding(OrgMixin, AuditMixin, Base):

    __tablename__ = "bill_of_landing"
    __table_args__ = {'schema': 'containermgmt'}

    # BillOfLanding - VARCHAR(100), primary key.
    # Bill of lading number.
    BillOfLanding = Column(String(100), primary_key=True)
    # The consignee of a bill of lading is an organisation. This pointed at the
    # consignee table, which held one row per organisation kept in sync by hand;
    # the ids were rewritten into the organisation id space and the foreign key
    # dropped, so this is a plain organisation id.
    # Consignee - INTEGER, optional.
    # Organisation id of the consignee receiving the goods.
    Consignee = Column(Integer, index=True, nullable=True)
    # Vessel - INTEGER, foreign key -> containermgmt.vessals.id, optional.
    # Ship carrying the cargo.
    Vessel = Column(Integer, ForeignKey("containermgmt.vessals.id"), index=True, nullable=True)
    # ArrivalDate - TIMESTAMP, optional.
    # Expected/actual arrival date.
    ArrivalDate = Column(DateTime, index=True, nullable=True)
    # Supplier - INTEGER, foreign key -> containermgmt.supplier.supplier_id, optional.
    # Vendor who shipped the goods.
    Supplier = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id"), index=True, nullable=True)
    # The vendor as it stood when this bill was recorded -- see PurchaseOrder.
    # supplier_name_at_issue - VARCHAR(255), optional.
    # Vendor name frozen when the bill was recorded.
    supplier_name_at_issue = Column(String(255), nullable=True)
    # Provider - INTEGER, foreign key -> containermgmt.logisticsprovider.Id, optional.
    # Shipping line / logistics provider.
    Provider = Column(Integer, ForeignKey("containermgmt.logisticsprovider.Id"), index=True, nullable=True)
    # FreeDays - INTEGER, optional.
    # Free days granted before charges start.
    FreeDays = Column(Integer, nullable=True)
    # status - INTEGER, foreign key -> containermgmt.status.status_id, optional.
    # Shipment status.
    status = Column(Integer, ForeignKey("containermgmt.status.status_id"), index=True, nullable=True)
    # Doc - INTEGER, foreign key -> containermgmt.shipping_document.doc_id, optional.
    # Type of shipping document.
    Doc = Column(Integer,  ForeignKey("containermgmt.shipping_document.doc_id"), index=True, nullable=True)

    # Rich Logistics Tracking Manifest Columns
    # origin_port - VARCHAR(100), optional.
    # Port of origin.
    origin_port = Column(String(100), nullable=True)
    # destination_port - VARCHAR(100), optional.
    # Port of destination.
    destination_port = Column(String(100), nullable=True)
    # transshipment_ports - JSON, optional.
    # Intermediate ports (JSON list).
    transshipment_ports = Column(JSON, nullable=True)
    # carrier_name - VARCHAR(100), optional.
    # Carrier/shipping line name.
    carrier_name = Column(String(100), nullable=True)
    # shipped_on_board_date - TIMESTAMP, optional.
    # Date goods were loaded on the ship.
    shipped_on_board_date = Column(DateTime, nullable=True)
    # raw_tracking_data - JSON, optional.
    # Unprocessed tracking data from the carrier (JSON).
    raw_tracking_data = Column(JSON, nullable=True)
    # ✅ Relationships
    # In BillOfLanding model
    vessel_rel = relationship("Vessal", back_populates="bill_of_landings", lazy="joined")
    supplier_rel = relationship("Supplier", back_populates="bill_of_landings", lazy="joined")
    provider_rel = relationship("LogisticsProvider", back_populates="bill_of_landings", lazy="joined")
    doc_rel = relationship("ShippingDocument", back_populates="bill_of_landings", lazy="joined")

    containers = relationship("ContainerDetails", back_populates="bill_of_landing")
