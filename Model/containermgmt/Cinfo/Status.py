# models/status.py

from sqlalchemy import Column, Integer, String
from ...db import Base  # Adjust the import based on your project structure

class Status(Base):
    __tablename__ = "status"
    __table_args__ = {'schema': 'containermgmt'}
    
    status_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(45), nullable=True)
