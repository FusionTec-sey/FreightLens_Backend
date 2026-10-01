from sqlalchemy import func

from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from reporting.catalog.definitions import DataType, DatasetDef, FieldDef, OrgScope
from reporting.catalog.enums import PurchaseOrderLifecycle, PurchaseOrderStatus
from reporting.catalog.registry import ReportingCatalog


catalog = ReportingCatalog()


PURCHASE_ORDER_DATASET = catalog.register(DatasetDef(
    key="purchase_orders",
    label="Purchase Orders",
    model=PurchaseOrder,
    module="ORDERS",
    permission="View_Report",
    org_scope=OrgScope.OWNED,
    from_clause=PurchaseOrder.__table__.outerjoin(
        Supplier.__table__,
        PurchaseOrder.supplier_id == Supplier.supplier_id,
    ),
    search_fields=(PurchaseOrder.po_number, PurchaseOrder.po_nce, PurchaseOrder.company),
    default_sort="po_date",
    max_rows=10_000,
    fields={
        "id": FieldDef("id", "ID", PurchaseOrder.id, DataType.NUMBER),
        "po_number": FieldDef(
            "po_number", "PO #", PurchaseOrder.po_number,
            filter_ops=frozenset({"eq", "contains"}), sortable=True,
        ),
        "po_date": FieldDef(
            "po_date", "Order Date", PurchaseOrder.order_mail_date, DataType.DATE,
            filter_ops=frozenset({"gte", "lte", "is_null"}), sortable=True,
        ),
        "supplier_id": FieldDef(
            "supplier_id", "Supplier ID", PurchaseOrder.supplier_id, DataType.NUMBER,
            field_class="SUPPLIER_IDENTITY", filter_ops=frozenset({"eq", "in"}),
        ),
        "supplier_name": FieldDef(
            "supplier_name", "Supplier", func.coalesce(Supplier.name, PurchaseOrder.company),
            field_class="SUPPLIER_IDENTITY", sortable=True,
        ),
        "status": FieldDef(
            "status", "Status", PurchaseOrder.status,
            filter_ops=frozenset({"eq", "in"}), sortable=True,
            allowed_values=frozenset(item.value for item in PurchaseOrderStatus),
        ),
        "lifecycle_stage": FieldDef(
            "lifecycle_stage", "Lifecycle Stage", PurchaseOrder.lifecycle_stage,
            filter_ops=frozenset({"eq", "in"}), sortable=True,
            allowed_values=frozenset(item.value for item in PurchaseOrderLifecycle),
        ),
        "currency": FieldDef("currency", "Currency", PurchaseOrder.currency, sortable=True),
        "base_currency": FieldDef(
            "base_currency", "Base Currency", PurchaseOrder.base_currency,
            field_class="FINANCIAL",
        ),
        "total_amount": FieldDef(
            "total_amount", "Total Value", PurchaseOrder.total_amount, DataType.CURRENCY,
            field_class="FINANCIAL", filter_ops=frozenset({"gte", "lte"}),
            sortable=True, aggregatable=True,
        ),
        "advance_amount": FieldDef(
            "advance_amount", "Advance Paid", PurchaseOrder.advance_amount,
            DataType.CURRENCY, field_class="FINANCIAL", aggregatable=True,
        ),
        "balance_amount": FieldDef(
            "balance_amount", "Balance Due", PurchaseOrder.balance_amount,
            DataType.CURRENCY, field_class="FINANCIAL", sortable=True, aggregatable=True,
        ),
        "total_amount_base": FieldDef(
            "total_amount_base", "Total Value (Base)", PurchaseOrder.total_amount_base,
            DataType.CURRENCY, field_class="FINANCIAL",
            filter_ops=frozenset({"gte", "lte"}), sortable=True, aggregatable=True,
        ),
        "advance_amount_base": FieldDef(
            "advance_amount_base", "Advance Paid (Base)", PurchaseOrder.advance_amount_base,
            DataType.CURRENCY, field_class="FINANCIAL", aggregatable=True,
        ),
        "balance_amount_base": FieldDef(
            "balance_amount_base", "Balance Due (Base)", PurchaseOrder.balance_amount_base,
            DataType.CURRENCY, field_class="FINANCIAL", aggregatable=True,
        ),
    },
))
