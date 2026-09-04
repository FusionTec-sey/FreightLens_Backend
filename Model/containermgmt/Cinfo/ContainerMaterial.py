from sqlalchemy import Table, Column, ForeignKey, Integer
from ...db import Base  # Adjust the import as needed

container_products = Table(
    "container_products",
    Base.metadata,
    Column("ContainerId", Integer, ForeignKey("containermgmt.container_details.Container_ID"), primary_key=True),
    Column("MaterialId", Integer, ForeignKey("containermgmt.material.Id"), primary_key=True),
    schema="containermgmt"
)