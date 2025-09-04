from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from ...db import Base

class BillOfLanding(Base):
    __tablename__ = "bill_of_landing"
    __table_args__ = {'schema': 'containermgmt'}

    BillOfLanding = Column(String(100), primary_key=True)
    Consignee = Column(Integer, ForeignKey("containermgmt.consignee.consignee_id"), nullable=True)
    Vessel = Column(Integer, ForeignKey("containermgmt.vessals.id"), nullable=True)
    ArrivalDate = Column(DateTime, nullable=True)
    Supplier = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id"), nullable=True)
    Provider = Column(Integer, ForeignKey("containermgmt.logisticsprovider.Id"), nullable=True)
    Doc = Column(Integer,  ForeignKey("containermgmt.shipping_document.doc_id"), nullable=True)
    # ✅ Relationships
    # In BillOfLanding model
    consignee_rel = relationship("Consignee", back_populates="bill_of_landings", lazy="joined")
    vessel_rel = relationship("Vessal", back_populates="bill_of_landings", lazy="joined")
    supplier_rel = relationship("Supplier", back_populates="bill_of_landings", lazy="joined")
    provider_rel = relationship("LogisticsProvider", back_populates="bill_of_landings", lazy="joined")
    doc_rel = relationship("ShippingDocument", back_populates="bill_of_landings", lazy="joined")

    containers = relationship("ContainerDetails", back_populates="bill_of_landing")
