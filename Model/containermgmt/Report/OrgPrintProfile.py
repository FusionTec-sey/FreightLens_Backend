from sqlalchemy import Column, ForeignKey, Integer, JSON, String, Text, text
from sqlalchemy.orm import relationship

from Model.db import Base
from Model.mixins import AuditMixin


class OrgPrintProfile(AuditMixin, Base):
    __tablename__ = "org_print_profiles"
    __table_args__ = {"schema": "containermgmt"}

    org_id = Column(
        Integer,
        ForeignKey("usercredentials.organisations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    legal_name = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    tax_id = Column(String(100), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(100), nullable=True)
    logo_asset_key = Column(String(500), nullable=True)
    stamp_asset_key = Column(String(500), nullable=True)
    signature_asset_key = Column(String(500), nullable=True)
    bank_details = Column(JSON, nullable=False, default=dict, server_default=text("'{}'::json"))
    default_terms = Column(JSON, nullable=False, default=dict, server_default=text("'{}'::json"))
    brand_color = Column(String(20), nullable=True)
    font_family = Column(String(100), nullable=True)
    locale = Column(String(20), nullable=False, default="en-SC", server_default="en-SC")
    timezone = Column(
        String(100), nullable=False, default="Indian/Mahe", server_default="Indian/Mahe"
    )

    organisation = relationship("Organisation", viewonly=True)
