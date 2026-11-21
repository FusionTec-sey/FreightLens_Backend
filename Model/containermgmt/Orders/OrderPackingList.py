from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, Numeric, JSON
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Packing list header: what the vendor packed, for one order or one container.
class OrderPackingList(OrgMixin, AuditMixin, Base):
    __tablename__ = "order_packing_lists"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # Nullable: a list built from a container covers several orders, so no
    # single one owns the header. Which orders it covers is derived from its
    # lines, which keeps one source of truth as lines are added and removed.
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, optional.
    # Order covered (NULL when a container list spans several orders).
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=True, index=True)
    # container_id - INTEGER, foreign key -> containermgmt.container_details.Container_ID, optional.
    # Container the list was built for.
    container_id = Column(Integer, ForeignKey("containermgmt.container_details.Container_ID"), nullable=True, index=True)
    # The container as typed, for a tenant without the LOGISTICS module: there
    # is no container record to point at, but the shipment is still real. A
    # list must carry one or the other.
    # container_no_text - VARCHAR(50), optional.
    # Container number typed in, for companies without the LOGISTICS module.
    container_no_text = Column(String(50), nullable=True)
    # source - VARCHAR(20), optional, default PO.
    # Which flow built it: PO or CONTAINER.
    source = Column(String(20), default="PO")  # PO | CONTAINER -- which flow built it

    # packing_list_number - VARCHAR(100), required.
    # Packing list number.
    packing_list_number = Column(String(100), nullable=False, index=True)
    # supplier_invoice_ref - VARCHAR(100), optional.
    # Vendor invoice this list goes with.
    supplier_invoice_ref = Column(String(100), nullable=True)
    # package_count - INTEGER, optional.
    # Number of packages/cartons.
    package_count = Column(Integer, nullable=True)
    # total_gross_weight - NUMERIC(10,2), optional.
    # Total gross weight.
    total_gross_weight = Column(Numeric(10, 2), nullable=True)
    # total_cbm - NUMERIC(10,2), optional.
    # Total volume in cubic metres.
    total_cbm = Column(Numeric(10, 2), nullable=True)
    
    # date_issued - DATE, optional.
    # Date the list was issued.
    date_issued = Column(Date, nullable=True)
    # status - VARCHAR(50), optional, default CONFIRMED.
    # DRAFT, CONFIRMED, SHIPPED or RECEIVED.
    status = Column(String(50), default="CONFIRMED")  # DRAFT, CONFIRMED, SHIPPED, RECEIVED
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Why a confirmed list was reopened, kept per revision rather than only the
    # latest: the point of asking is that someone can read back what happened,
    # and a field that only holds the most recent answer loses the rest.
    # [{"at": iso, "by": user_id, "by_name": str, "reason": str}]
    # revisions - JSON, optional.
    # Reasons the list was reopened: [{at, by, by_name, reason}].
    revisions = Column(JSON, nullable=True)
    # revision_count - INTEGER, required, default 0.
    # How many times it was reopened.
    revision_count = Column(Integer, nullable=False, default=0)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="packing_lists")
    container = relationship("ContainerDetails", foreign_keys=[container_id], lazy="joined")
    items = relationship("PackingListItem", back_populates="packing_list", cascade="all, delete-orphan")
    receipts = relationship("GoodsReceipt", back_populates="packing_list")


# TABLE: Lines of a packing list.
class PackingListItem(AuditMixin, Base):
    __tablename__ = "order_packing_list_items"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # packing_list_id - INTEGER, foreign key -> containermgmt.order_packing_lists.id, required.
    # Packing list this line belongs to.
    packing_list_id = Column(Integer, ForeignKey("containermgmt.order_packing_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    # po_item_id - INTEGER, foreign key -> containermgmt.po_items.id, optional.
    # PO line being packed.
    po_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id"), nullable=True, index=True)
    # Denormalised from the PO item: a line still has to name its order when it
    # was added by hand (no po_item_id) or when the item is later removed.
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, optional.
    # Order of the line (kept even if the PO line is removed).
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id"), nullable=True, index=True)
    # The order as typed, for a tenant without the ORDERS module. It seeds
    # nothing and is never written back to: there is no order to read from.
    # po_number_text - VARCHAR(100), optional.
    # Order number typed in, for companies without the ORDERS module.
    po_number_text = Column(String(100), nullable=True)
    
    # item_code - VARCHAR(100), optional.
    # Item/article code for this line.
    item_code = Column(String(100), nullable=True)
    # description - TEXT, required.
    # What is packed.
    description = Column(Text, nullable=False)
    # quantity_packed - NUMERIC(12,2), required, default 1.0.
    # Quantity packed.
    quantity_packed = Column(Numeric(12, 2), nullable=False, default=1.0)
    # unit - VARCHAR(50), optional, default PCS.
    # Unit of measure, e.g. PCS, KG.
    unit = Column(String(50), default="PCS")
    
    # carton_numbers - VARCHAR(100), optional.
    # Carton number range holding the item.
    carton_numbers = Column(String(100), nullable=True)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Relationships
    packing_list = relationship("OrderPackingList", back_populates="items")
    po_item = relationship("POItem", back_populates="packing_items")
    purchase_order = relationship("PurchaseOrder", foreign_keys=[po_id])
    receipt_items = relationship("ReceiptItem", back_populates="packing_item")
