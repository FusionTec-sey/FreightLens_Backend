from sqlalchemy import Integer, String, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from ...db import Base  # Adjust the import path to your project's base module
from ..Cinfo.ContainerMaterial import container_products

from ...mixins import AuditMixin

class Material(AuditMixin, Base):
    __tablename__ = "material"
    __table_args__ = {"schema": "containermgmt"}  # Remove if you're not using schema

    Id = Column(Integer, primary_key=True, autoincrement=True)
    Name = Column(String(45), unique=True)

    containers = relationship(
        "ContainerDetails",
        secondary=container_products,
        back_populates="materials"
    )