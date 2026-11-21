from sqlalchemy import Column, ForeignKey, Integer, JSON, String, Text, text
from sqlalchemy.orm import relationship

from Model.db import Base
from Model.mixins import AuditMixin


# TABLE: Company letterhead details used on printed documents.
class OrgPrintProfile(AuditMixin, Base):
    __tablename__ = "org_print_profiles"
    __table_args__ = {"schema": "containermgmt"}

    # org_id - INTEGER, primary key, foreign key -> usercredentials.organisations.id.
    # Company this profile belongs to.
    org_id = Column(
        Integer,
        ForeignKey("usercredentials.organisations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # legal_name - VARCHAR(255), optional.
    # Registered company name.
    legal_name = Column(String(255), nullable=True)
    # address - TEXT, optional.
    # Printed address.
    address = Column(Text, nullable=True)
    # tax_id - VARCHAR(100), optional.
    # Tax number.
    tax_id = Column(String(100), nullable=True)
    # contact_email - VARCHAR(255), optional.
    # Contact e-mail on documents.
    contact_email = Column(String(255), nullable=True)
    # contact_phone - VARCHAR(100), optional.
    # Contact phone on documents.
    contact_phone = Column(String(100), nullable=True)
    # logo_asset_key - VARCHAR(500), optional.
    # Stored logo file.
    logo_asset_key = Column(String(500), nullable=True)
    # stamp_asset_key - VARCHAR(500), optional.
    # Stored company stamp file.
    stamp_asset_key = Column(String(500), nullable=True)
    # signature_asset_key - VARCHAR(500), optional.
    # Stored signature file.
    signature_asset_key = Column(String(500), nullable=True)
    # bank_details - JSON, required.
    # Bank details printed on documents (JSON).
    bank_details = Column(JSON, nullable=False, default=dict, server_default=text("'{}'::json"))
    # default_terms - JSON, required.
    # Default terms and conditions text (JSON).
    default_terms = Column(JSON, nullable=False, default=dict, server_default=text("'{}'::json"))
    # brand_color - VARCHAR(20), optional.
    # Main brand colour.
    brand_color = Column(String(20), nullable=True)
    # font_family - VARCHAR(100), optional.
    # Font used in documents.
    font_family = Column(String(100), nullable=True)
    # locale - VARCHAR(20), required, default en-SC.
    # Language/region for formats (default en-SC).
    locale = Column(String(20), nullable=False, default="en-SC", server_default="en-SC")
    # timezone - VARCHAR(100), required, default Indian/Mahe.
    # Timezone for dates (default Indian/Mahe).
    timezone = Column(
        String(100), nullable=False, default="Indian/Mahe", server_default="Indian/Mahe"
    )

    organisation = relationship("Organisation", viewonly=True)
