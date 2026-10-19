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
    # Holding this grants editing as well as viewing. Nullable so a class that
    # only ever redacts -- the reporting classes do -- stays read-only, which is
    # what every existing row means today.
    edit_permission_name = Column(
        String(45),
        ForeignKey("usercredentials.permissions.name", ondelete="RESTRICT"),
        nullable=True,
    )
    description = Column(String(255), nullable=False)
