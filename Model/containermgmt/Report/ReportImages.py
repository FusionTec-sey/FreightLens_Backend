from sqlalchemy import Column, String, Text, ForeignKey, Integer
from ...db import Base # Adjust this import path based on your project
from sqlalchemy.orm import relationship


from ...mixins import AuditMixin

# TABLE: LEGACY: photos attached to damaged products.
class ReportImage(AuditMixin, Base):
    __tablename__ = 'report_images'
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # DMGP_id - INTEGER, foreign key -> containermgmt.damageproduct.id, optional.
    # Damaged product the photo belongs to.
    DMGP_id = Column(Integer, ForeignKey('containermgmt.damageproduct.id'), nullable=True)
    # path - TEXT, required.
    # Where the photo is stored.
    path = Column(Text, nullable=False)

    # Optional: define relationship to DamageProduct
    damage_product = relationship("DamageProduct", back_populates="images")