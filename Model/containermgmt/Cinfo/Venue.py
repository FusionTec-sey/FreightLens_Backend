
from sqlalchemy import Column, String,Integer
from sqlalchemy.orm import relationship
from ...db import Base


from ...mixins import AuditMixin

# TABLE: Lookup list of places where containers are emptied.
class UnloadVenue(AuditMixin, Base):
    __tablename__ = 'unload_venue'
    __table_args__ = {'schema': 'containermgmt'}

    # venue_id - INTEGER, primary key.
    # Unique venue number.
    venue_id = Column(Integer, primary_key=True)
    # venue - VARCHAR(45), optional.
    # Venue name.
    venue = Column(String(45))