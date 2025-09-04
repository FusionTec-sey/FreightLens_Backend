from sqlalchemy import Integer, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship, Mapped, mapped_column
from ...db import Base
import enum

# Define the enum for document types
class DocType(enum.Enum):
    AD = "AD"
    ED = "ED"
    D = "D"  # Add more types as needed

# Define the SQLAlchemy model
class ContainerDocs(Base):
    __tablename__ = 'container_docs'
    __table_args__ = {'schema': 'containermgmt'}

    docs_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    container_id: Mapped[int] = mapped_column(ForeignKey('containermgmt.container_details.Container_ID'))
    path: Mapped[str] = mapped_column(Text)
    Type: Mapped[DocType] = mapped_column(Enum(DocType, name="doc_type_enum", create_constraint=True))

    container = relationship(
        "ContainerDetails",
        back_populates="documents"
        )
