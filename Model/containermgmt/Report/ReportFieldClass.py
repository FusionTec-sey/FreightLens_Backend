from sqlalchemy import Column, ForeignKey, String

from Model.db import Base


class ReportFieldClass(Base):
    __tablename__ = "report_field_classes"
    __table_args__ = {"schema": "containermgmt"}

    code = Column(String(50), primary_key=True)
    permission_name = Column(
        String(45),
        ForeignKey("usercredentials.permissions.name", ondelete="RESTRICT"),
        nullable=False,
    )
    description = Column(String(255), nullable=False)
