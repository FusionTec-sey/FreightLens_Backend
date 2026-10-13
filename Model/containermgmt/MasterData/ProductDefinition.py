from sqlalchemy import Column, Integer, String, Text, Numeric, Boolean, ForeignKey, Index

from ...db import Base
from ...mixins import AuditMixin


class ProductDefinition(AuditMixin, Base):
    """What is true about a product for every company in the group.

    Deliberately holds no company data: no stock, no cost, no internal code, no
    supplier. Those differ per company and stay on that company's own product
    row, which is why a product is copied from here rather than shared from it.

    A company adopts a definition, which copies these fields into a product of
    its own and records `products.definition_id` back to this row. The link is
    what makes group-wide reporting possible without the companies sharing a
    record they would otherwise fight over -- and it is why deleting a
    definition cannot break anything: the copy already holds everything the
    company needs.
    """
    __tablename__ = "product_definitions"
    __table_args__ = (
        Index("ix_product_definitions_sku_unique", "sku_key", unique=True),
        {"schema": "containermgmt"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # SKU is the natural key: across 5,790 products it was unique and never
    # blank. sku_key is its normalised form, so case and spacing cannot produce
    # the duplicates the vendor master accumulated.
    sku = Column(String(100), nullable=False)
    sku_key = Column(String(100), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    brand = Column(String(100), nullable=True)
    model_number = Column(String(100), nullable=True)
    series = Column(String(100), nullable=True)
    country_of_origin = Column(String(100), nullable=True)
    barcode = Column(String(100), nullable=True)
    hs_code = Column(String(20), nullable=True)
    unit = Column(String(50), nullable=True, default="PCS")

    length = Column(Numeric(10, 4), nullable=True)
    width = Column(Numeric(10, 4), nullable=True)
    height = Column(Numeric(10, 4), nullable=True)
    weight_per_unit = Column(Numeric(10, 4), nullable=True)
    dimension_unit = Column(String(10), nullable=True)
    weight_unit = Column(String(10), nullable=True)

    # A hint, not a rule: a company on its own catalogue has to map it.
    suggested_category_id = Column(
        Integer,
        ForeignKey("containermgmt.product_categories.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Who first published it. Provenance only -- it grants no ownership, since
    # every company reads every definition.
    source_org_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
