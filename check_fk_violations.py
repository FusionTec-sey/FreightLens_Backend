from sqlalchemy import text
from Model.db import engine

checks = [
    # container_details checks
    ("container_details.status -> status.status_id",
     "SELECT COUNT(*) FROM containermgmt.container_details c LEFT JOIN containermgmt.status s ON c.status = s.status_id WHERE c.status IS NOT NULL AND s.status_id IS NULL"),
    
    ("container_details.emptied_at -> unload_venue.venue_id",
     "SELECT COUNT(*) FROM containermgmt.container_details c LEFT JOIN containermgmt.unload_venue v ON c.emptied_at = v.venue_id WHERE c.emptied_at IS NOT NULL AND v.venue_id IS NULL"),
     
    ("container_details.type -> container_type.type_id",
     "SELECT COUNT(*) FROM containermgmt.container_details c LEFT JOIN containermgmt.container_type t ON c.type = t.type_id WHERE c.type IS NOT NULL AND t.type_id IS NULL"),
     
    ("container_details.BillOfLanding -> bill_of_landing.BillOfLanding",
     "SELECT COUNT(*) FROM containermgmt.container_details c LEFT JOIN containermgmt.bill_of_landing b ON c.BillOfLanding = b.BillOfLanding WHERE c.BillOfLanding IS NOT NULL AND b.BillOfLanding IS NULL"),

    # bill_of_landing checks
    ("bill_of_landing.Consignee -> consignee.consignee_id",
     "SELECT COUNT(*) FROM containermgmt.bill_of_landing b LEFT JOIN containermgmt.consignee c ON b.Consignee = c.consignee_id WHERE b.Consignee IS NOT NULL AND c.consignee_id IS NULL"),
     
    ("bill_of_landing.Vessel -> vessals.id",
     "SELECT COUNT(*) FROM containermgmt.bill_of_landing b LEFT JOIN containermgmt.vessals v ON b.Vessel = v.id WHERE b.Vessel IS NOT NULL AND v.id IS NULL"),
     
    ("bill_of_landing.Supplier -> supplier.supplier_id",
     "SELECT COUNT(*) FROM containermgmt.bill_of_landing b LEFT JOIN containermgmt.supplier s ON b.Supplier = s.supplier_id WHERE b.Supplier IS NOT NULL AND s.supplier_id IS NULL"),
     
    ("bill_of_landing.Provider -> logisticsprovider.Id",
     "SELECT COUNT(*) FROM containermgmt.bill_of_landing b LEFT JOIN containermgmt.logisticsprovider l ON b.Provider = l.Id WHERE b.Provider IS NOT NULL AND l.Id IS NULL"),
     
    ("bill_of_landing.Doc -> shipping_document.doc_id",
     "SELECT COUNT(*) FROM containermgmt.bill_of_landing b LEFT JOIN containermgmt.shipping_document d ON b.Doc = d.doc_id WHERE b.Doc IS NOT NULL AND d.doc_id IS NULL"),
]

with engine.connect() as conn:
    print("Checking for FK violations:")
    violations_found = False
    for desc, query in checks:
        try:
            res = conn.execute(text(query))
            cnt = res.fetchone()[0]
            if cnt > 0:
                print(f"  [VIOLATION] {desc}: {cnt} orphaned records found!")
                violations_found = True
            else:
                print(f"  [OK] {desc}")
        except Exception as e:
            print(f"  [ERROR] {desc}: {e}")
            
    if not violations_found:
        print("\nAll potential foreign keys are clean! No violations found.")
