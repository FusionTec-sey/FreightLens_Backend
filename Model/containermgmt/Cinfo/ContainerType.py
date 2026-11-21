from sqlalchemy import Column, String, Integer

from ...db import Base


from ...mixins import AuditMixin

# TABLE: Lookup list of container types (e.g. 20ft, 40HC).
class ContainerType(AuditMixin, Base):
    __tablename__ = 'container_type'
    __table_args__ = {'schema': 'containermgmt'}

    # type_id - INTEGER, primary key.
    # Unique type number.
    type_id = Column(Integer, primary_key=True)
    # type - VARCHAR(45), optional.
    # Type name.
    type = Column(String(45))
