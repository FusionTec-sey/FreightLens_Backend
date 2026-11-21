from sqlalchemy import Column, ForeignKey, String

from Model.db import Base


# TABLE: Groups of sensitive report fields, each hidden unless the user holds a permission.
class ReportFieldClass(Base):
    __tablename__ = "report_field_classes"
    __table_args__ = {"schema": "containermgmt"}

    # code - VARCHAR(50), primary key.
    # Field-class code.
    code = Column(String(50), primary_key=True)
    # permission_name - VARCHAR(45), foreign key -> usercredentials.permissions.name, required.
    # Permission needed to see these fields.
    permission_name = Column(
        String(45),
        ForeignKey("usercredentials.permissions.name", ondelete="RESTRICT"),
        nullable=False,
    )
    # Holding this grants editing as well as viewing. Nullable so a class that
    # only ever redacts -- the reporting classes do -- stays read-only, which is
    # what every existing row means today.
    # edit_permission_name - VARCHAR(45), foreign key -> usercredentials.permissions.name, optional.
    # Permission that also allows editing (NULL = read-only).
    edit_permission_name = Column(
        String(45),
        ForeignKey("usercredentials.permissions.name", ondelete="RESTRICT"),
        nullable=True,
    )
    # description - VARCHAR(255), required.
    # What the class covers.
    description = Column(String(255), nullable=False)
