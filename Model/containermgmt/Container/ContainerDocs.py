from sqlalchemy import Integer, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship, Mapped, mapped_column
from ...db import Base
import enum

# Define the enum for document types
# TABLE: Allowed container document kinds (AD, ED, D).
class DocType(enum.Enum):
    AD = "AD"
    ED = "ED"
    D = "D"  # Add more types as needed

# Define the SQLAlchemy model
from ...mixins import AuditMixin

# TABLE: Files attached to a container.
class ContainerDocs(AuditMixin, Base):
    __tablename__ = 'container_docs'
    __table_args__ = {'schema': 'containermgmt'}

    # docs_id - INTEGER, primary key.
    # Unique document number.
    docs_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # container_id - INTEGER, foreign key -> containermgmt.container_details.Container_ID, required.
    # Container this row refers to.
    container_id: Mapped[int] = mapped_column(ForeignKey('containermgmt.container_details.Container_ID'))
    # path - TEXT, required.
    # Where the file is stored.
    path: Mapped[str] = mapped_column(Text)
    # Type - ENUM, required.
    # Document kind (AD, ED or D).
    Type: Mapped[DocType] = mapped_column(Enum(DocType, name="doc_type_enum", create_constraint=True))

    container = relationship(
        "ContainerDetails",
        back_populates="documents"
        )
