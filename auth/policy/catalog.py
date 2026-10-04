from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from Model.Credentials.permissions import Permission


@dataclass(frozen=True)
class PermissionSpec:
    name: str
    description: str
    module: Optional[str] = None
    field_class: Optional[str] = None
    platform_only: bool = False


def _specs(module: Optional[str], entries: list[tuple[str, str]]) -> list[PermissionSpec]:
    return [PermissionSpec(name, description, module) for name, description in entries]


# This is the single authoritative catalog. Database synchronization is additive:
# deployments may retain retired permissions for audit history, but code may only
# authorize names declared here.
PERMISSION_CATALOG = [
    *_specs('SALES', [
        ('View_SalesDraft', 'View company-owned retail sales drafts'),
        ('Manage_SalesDraft', 'Create and revise retail sales drafts, without confirming sales'),
        ('Request_PriceFloorException', 'Request review of an exact sales price-floor exception'),
        ('Review_PriceFloorException', 'Independently approve or reject an exact sales price-floor exception'),
    ]),
    *_specs(None, [
        ("View_Dashboard", "View dashboard and summary statistics"),
        ("View_Report", "View reporting catalog, templates, and registers"),
        ("Manage_Report_Template", "Create, edit, version, and publish document templates"),
        ("Toggle_Report_Template", "Activate or deactivate report templates"),
        ("View_Operational_Register", "View the operational register catalog"),
        ("Run_Operational_Register", "Run operational registers on screen"),
        ("Export_Report", "Export operational registers and rendered reports"),
        ("Manage_Operational_Template", "Design and save tabular report templates"),
        ("Manage_Print_Profile", "Manage organisation branding and print defaults"),
        ("Generate_Report", "Generate report files and PDFs"),
        ("Add_Report", "Create report definitions"),
        ("Edit_Report", "Edit report definitions"),
        ("Delete_Report", "Delete report definitions"),
        ("View_User", "View user accounts"),
        ("Add_User", "Create user accounts"),
        ("Edit_User", "Update user accounts and organisation roles"),
        ("Delete_User", "Deactivate user accounts"),
        ("View_Role", "View roles and permissions"),
        ("Add_Role", "Create tenant roles"),
        ("Edit_Role", "Update tenant roles"),
        ("Delete_Role", "Delete tenant roles"),
        ("View_Setting", "View settings"),
        ("Edit_Setting", "Update settings"),
        ("View_MasterData", "View shared reference data"),
        ("View_Customer", "View company-owned retail customer identities"),
        ("Manage_Customer", "Create and update company-owned retail customer profiles"),
        ("Request_CustomerDuplicate", "Request review of exact customer identity pairs"),
        ("Review_CustomerDuplicate", "Independently review duplicate customer assessments without merging"),
        ("Edit_MasterData", "Update shared reference data"),
        ("Add_RefData", "Add reference data"),
        ("Edit_RefData", "Edit reference data"),
        ("Delete_RefData", "Delete reference data"),
        ("Customize_Dashboard", "Personalize dashboard layout"),
        ("Manage_DashboardTemplate", "Manage dashboard templates"),
    ]),
    PermissionSpec("Cross_Org_Report", "Run reports across assigned organisations"),
    PermissionSpec("View_Personal_Data", "View personal contact and identity data", field_class="PERSONAL"),
    PermissionSpec("View_TenantConsole", "Access the multi-tenant organisation console", platform_only=True),
    PermissionSpec("Manage_TenantConsole", "Configure organisations and tenant modules", platform_only=True),
    PermissionSpec("View_Financials", "View confidential prices, payments, and totals", "ORDERS", "FINANCIAL"),
    PermissionSpec("Manage_Financials", "Manage confidential prices, payments, and terms", "ORDERS", "FINANCIAL"),
    PermissionSpec("View_Supplier", "View supplier identities and contact details", "ORDERS", "SUPPLIER_IDENTITY"),
    PermissionSpec("Vendor_Pricing_View", "View supplier quotations and vendor pricing", "ORDERS", "FINANCIAL"),
    *_specs("ORDERS", [
        ("View_Order", "View purchase orders"), ("Add_Order", "Create purchase orders"),
        ("Edit_Order", "Edit purchase orders"), ("Delete_Order", "Delete purchase orders"),
        ("View_RFQ", "View sourcing requests and RFQs"), ("Add_RFQ", "Create sourcing requests and RFQs"),
        ("Edit_RFQ", "Edit sourcing requests and RFQs"), ("Delete_RFQ", "Delete sourcing requests and RFQs"),
        ("Send_RFQ", "Send RFQs to suppliers"), ("View_VendorQuote", "View vendor quotations"),
        ("Add_VendorQuote", "Record vendor quotations"), ("Compare_Quote", "Compare vendor quotations"),
        ("Approve_Quote", "Approve a vendor quotation"), ("Issue_PO", "Issue an approved purchase order"),
        ("Approve_Variance", "Approve price variances"),
        ("Add_Payment", "Record a payment"), ("Edit_Payment", "Edit a payment"),
        ("Delete_Payment", "Delete a payment"), ("View_OrderPayment", "View order payments"),
        ("View_OrderTemplate", "View order templates"), ("Add_OrderTemplate", "Create order templates"),
        ("Edit_OrderTemplate", "Edit order templates"), ("Delete_OrderTemplate", "Delete order templates"),
        ("View_StoreRequest", "View store requests"), ("Add_StoreRequest", "Create store requests"),
        ("Edit_StoreRequest", "Edit store requests"), ("Submit_StoreRequest", "Submit store requests"),
        ("Withdraw_StoreRequest", "Withdraw store requests"), ("Delete_StoreRequest", "Delete store requests"),
        ("View_PackingList", "View packing lists"), ("Add_PackingList", "Create packing lists"),
        ("Edit_PackingList", "Edit packing lists"), ("Delete_PackingList", "Delete packing lists"),
        ("View_GoodsReceipt", "View goods receipts"), ("Verify_Receipt", "Verify goods receipts"),
        ("Edit_Receipt", "Edit goods receipts"), ("Submit_Receipt", "Submit goods receipts"),
        ("View_Defect", "View defects"), ("Add_Defect", "Report defects"),
        ("Edit_Defect", "Edit defects"), ("Resolve_Defect", "Resolve defects"),
        ("Delete_Defect", "Delete defects"), ("View_OrderDocument", "View order documents"),
        ("View_Document", "View operational documents"), ("Upload_Document", "Upload documents"),
        ("Add_Document", "Add documents"), ("Edit_Document", "Edit documents"),
        ("Delete_Document", "Delete documents"), ("View_DailyWork", "View daily work queues"),
        ("View_EODReport", "View end-of-day reports"), ("Print_PurchaseOrder", "Print purchase orders"),
        ("Edit_Supplier", "Create or edit suppliers"), ("Add_Supplier", "Create suppliers"),
        ("View_Budget", "View purchasing budgets"),
    ]),
    *_specs("LOGISTICS", [
        ("View_Container", "View containers"), ("View_Containers", "View container collections"),
        ("Add_Container", "Create containers"), ("Edit_Container", "Edit containers"),
        ("Delete_Container", "Delete containers"), ("View_BL", "View bills of lading"),
        ("Add_BillOfLanding", "Create bills of lading"), ("Edit_BillOfLanding", "Edit bills of lading"),
        ("Delete_BillOfLanding", "Delete bills of lading"), ("Print_Container", "Print container documents"),
        ("Print_BillOfLanding", "Print bills of lading"),
        ("View_ContainerId", "View the container ID column"), ("View_ArrivalDate", "View arrival dates"),
        ("View_EmptyAt", "View empty-return dates"), ("View_Demurrage", "View demurrage"),
        ("View_Status", "View container status"), ("View_Material", "View container materials"),
        ("View_Consignee", "View consignee details"), ("View_ReportId", "View report IDs"),
        ("View_ContainerNo", "View container numbers"), ("View_container_no", "View BL container numbers"),
        ("View_status", "View BL status"), ("View_location", "View BL locations"),
        ("View_weight", "View BL weights"), ("View_demurrage", "View BL demurrage"),
        ("View_BillOfLanding", "View bill of lading numbers"), ("View_vessel_name", "View vessel names"),
        ("View_consignee_name", "View consignee names"), ("View_arrivalDate", "View BL arrival dates"),
    ]),
    *_specs("INVENTORY", [
        ('Post_InventoryCost', 'Post independently verified inventory costs through central authority'),
        ('Post_InventoryReceipt', 'Post an approved receipt into stock and valuation atomically'),
        ('Request_ReservationRelease', 'Request exact saved-demand stock release review'),
        ('Review_ReservationRelease', 'Approve or reject saved-demand stock release requests'),
        ('Execute_ReservationRelease', 'Execute an exact approved saved-demand stock release'),
        ('Request_ReservationReallocation', 'Request exact same-store draft reservation reallocation'),
        ('Review_ReservationReallocation', 'Review exact source and destination reservation reallocation'),
        ('Execute_ReservationReallocation', 'Execute an exact independently approved draft hold reallocation'),
        ('Request_OtherStoreFulfilment', 'Request explicitly chosen other-store draft stock'),
        ('Allocate_SalesDraftStock', 'Allocate eligible same-store stock to exact saved draft demand'),
        ('Review_OtherStoreFulfilment', 'Review exact other-store fulfilment without posting stock'),
        ('Execute_OtherStoreFulfilment', 'Reserve the exact independently approved other-store stock'),
        ('Request_ReservationDeadline', 'Request a reviewed reservation follow-up date'),
        ('Review_ReservationDeadline', 'Review exact reservation follow-up dates'),
        ('Schedule_ReservationReview', 'Apply an approved reservation follow-up date without releasing stock'),
        ('View_CountPlan', 'View cycle-count plans, scope and annual coverage'),
        ('Manage_CountPlan', 'Create and activate cycle-count plans and their scope'),
        ('Assign_CountSession', 'Assign counters and open recount rounds'),
        ('Enter_CountResult', 'Enter and submit blind counts for own assigned rounds'),
        ('View_CountDiscrepancy', 'View provisional count discrepancies'),
        ('Review_CountDiscrepancy', 'Review count discrepancies without stock adjustment'),
        ('Request_StockAdjustment', 'Request review of an exact location stock correction'),
        ('Review_StockAdjustment', 'Independently review an exact location stock correction'),
        ('Execute_StockAdjustment', 'Execute an exact approved location stock correction'),
        ('Request_ReceiptCostReview', 'Request exact PO-price and FX evidence review for a receipt'),
        ('Review_ReceiptCostReview', 'Independently review exact receipt PO-price and FX evidence'),
        ('Request_CostReconciliation', 'Request review of an exact product and cost-pool reconciliation state'),
        ('Review_CostReconciliation', 'Independently review an exact inventory-cost reconciliation state'),
        ('Execute_CostReconciliation', 'Close an independently approved inventory-cost reconciliation checkpoint'),
        ("View_Product", "View products and stock levels"), ("Add_Product", "Create products"),
        ("Edit_Product", "Edit products"), ("Delete_Product", "Delete products"),
        ("Adjust_Stock", "Adjust stock with a reason"), ("View_ProductCategory", "View product categories"),
        ("Manage_ProductCategory", "Manage product categories"),
        ("Manage_InventoryLocation", "Create inventory branches and physical stock locations"),
        ("Manage_BranchSettings", "Configure branch trading calendars and business-date rules"),
        ("Request_InventoryReview", "Request manager review of an exact saved inventory policy"),
        ("Review_InventoryPolicy", "Review inventory policy cases without self approval"),
        ("Activate_InventoryPolicy", "Activate exact reviewed inventory policies"),
        ("Manage_InventoryBarcode", "Register product unit barcodes against reviewed policies"),
        ("Request_BarcodeRetirement", "Request exact barcode retirement review"),
        ("Review_BarcodeRetirement", "Independently approve or reject barcode retirement"),
        ("Retire_InventoryBarcode", "Apply an approved barcode retirement"),
        ("Manage_InventoryCostPool", "Create cost pools and assign initial branch valuation scope"),
        ("View_InventoryReport", "View inventory reports"), ("Export_Inventory", "Export inventory data"),
    ]),
]

PERMISSION_BY_NAME = {spec.name: spec for spec in PERMISSION_CATALOG}
PLATFORM_PERMISSION_NAMES = frozenset(
    spec.name for spec in PERMISSION_CATALOG if spec.platform_only
)

if len(PERMISSION_BY_NAME) != len(PERMISSION_CATALOG):
    raise RuntimeError("Permission catalog contains duplicate names")


def sync_permission_catalog(db: Session) -> dict[str, Permission]:
    existing = {permission.name: permission for permission in db.query(Permission).all()}
    for spec in PERMISSION_CATALOG:
        permission = existing.get(spec.name)
        if permission is None:
            permission = Permission(name=spec.name, description=spec.description)
            db.add(permission)
            db.flush()
            existing[spec.name] = permission
        elif permission.description != spec.description:
            permission.description = spec.description
    return {spec.name: existing[spec.name] for spec in PERMISSION_CATALOG}
