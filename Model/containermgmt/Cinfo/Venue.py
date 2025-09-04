
from sqlalchemy import Column, String,Integer
from sqlalchemy.orm import relationship
from ...db import Base


class UnloadVenue(Base):
    __tablename__ = 'unload_venue'
    __table_args__ = {'schema': 'containermgmt'}

    venue_id = Column(Integer, primary_key=True)
    venue = Column(String(45))