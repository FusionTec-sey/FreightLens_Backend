"""The attribute names the container print resolver reads must exist.

Printing a container raised AttributeError on a live database for every
container that had a bill of lading, because `resolve_container_details` still
read attributes that renames had removed:

    bl.supplier_rel.Supplier   -> Supplier.name
    bl.consignee_rel.Consignee -> derived from the owning organisation
    bl.vessel_rel.VessalName   -> Vessal.VessalNo
    m.Material                 -> Material.Name

The bill of lading resolver had already been corrected for the first three; the
container one was left behind, and nothing failed until someone pressed Print.
These assertions are static -- no database -- so the next rename breaks a test
rather than a document.
"""

import ast
import inspect

from Model.containermgmt.Cinfo.Material import Material
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Cinfo.Vessals import Vessal
from Model.containermgmt.Container.BillOfLanding import BillOfLanding
from Services import report_data_resolvers


def _attribute_names(function) -> set[str]:
    """Every `.attr` read anywhere inside one function."""
    source = inspect.getsource(function)
    tree = ast.parse(inspect.cleandoc(source))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }


def test_the_models_still_carry_the_names_the_resolver_reads():
    assert hasattr(Supplier, "name")
    assert not hasattr(Supplier, "Supplier")

    assert hasattr(Material, "Name")
    assert not hasattr(Material, "Material")

    assert hasattr(Vessal, "VessalNo")
    assert not hasattr(Vessal, "VessalName")

    # The consignee column holds an organisation id now; the relationship is
    # gone, so reading bl.consignee_rel is an AttributeError waiting to happen.
    assert not hasattr(BillOfLanding, "consignee_rel")


def test_the_container_resolver_reads_no_removed_attribute():
    read = _attribute_names(report_data_resolvers.resolve_container_details)

    for dead in ("consignee_rel", "VessalName"):
        assert dead not in read, f"resolve_container_details still reads .{dead}"

    assert "name" in read, "the supplier name should be read as .name"
    assert "VessalNo" in read


def test_the_bill_of_lading_resolver_stays_corrected():
    """It was fixed once; keep it that way, since the two drifted apart before."""
    read = _attribute_names(report_data_resolvers.resolve_bl_summary)

    for dead in ("consignee_rel", "VessalName"):
        assert dead not in read, f"resolve_bl_summary still reads .{dead}"
