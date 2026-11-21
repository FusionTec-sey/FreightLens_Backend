from sqlalchemy import Column, String, Integer

from ...db import Base

from ...mixins import AuditMixin

# TABLE: LEGACY simple packing-list text per container (see order_packing_lists for the current one).
class PackingList(AuditMixin, Base):
    __tablename__ = 'packing_list'
    __table_args__ = {'schema': 'containermgmt'}

    # container_id - INTEGER, primary key.
    # Container the list belongs to.
    container_id = Column(Integer, primary_key=True)
    # packing_list - VARCHAR(45), optional.
    # Packing list reference/text.
    packing_list = Column(String(45))