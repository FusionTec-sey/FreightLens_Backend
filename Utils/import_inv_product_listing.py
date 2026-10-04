"""
Utils/import_inv_product_listing.py

Automated Seeding and Enrichment Template Exporter for FreightLens Product Master.
Source: INV_ProductListing.xlsx

Terms Applied:
- Excluded: Type, LastVendor, NormalPrice
- Included: Item Code -> sku & code, Description -> name (<=255) & description (full text), Category -> product_categories (under root 'Products')
- Defaults: unit = 'PCS', status = 'active', current_stock = 0.0, org_id = 1
- Upsert Logic: If (org_id, sku) already exists, updates name/description/category/unit/status.
- Duplicate Resolution: If duplicate SKU appears in file (e.g. SKU '303'), appends '-1' to preserve distinct items.
- Empty Description: Falls back to Item Code as Name.
- Export: Creates INV_ProductListing_Enrichment_Template.xlsx with all seeded products + empty columns for bulk logistics/warehouse/pricing enrichment.
"""

import os
import sys

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import psycopg2
from psycopg2.extras import execute_batch

DEFAULT_DB_HOST = os.getenv("TARGET_DB_HOST", "82.25.110.112")
DEFAULT_DB_PORT = int(os.getenv("TARGET_DB_PORT", "1234"))
DEFAULT_DB_USER = os.getenv("TARGET_DB_USER", "postgres")
DEFAULT_DB_PASSWORD = os.getenv("TARGET_DB_PASSWORD", "Frigh1liner_Fu5i0n1ech")
DEFAULT_DB_NAME = os.getenv("TARGET_DB_NAME", "containermgmt_pg")
EXCEL_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "INV_ProductListing.xlsx")
EXPORT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "INV_ProductListing_Enrichment_Template.xlsx")


def get_db_connection():
    return psycopg2.connect(
        host=DEFAULT_DB_HOST,
        port=DEFAULT_DB_PORT,
        user=DEFAULT_DB_USER,
        password=DEFAULT_DB_PASSWORD,
        dbname=DEFAULT_DB_NAME,
        connect_timeout=10,
    )


def get_admin_user_id(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM usercredentials.users ORDER BY id ASC LIMIT 1;")
        row = cur.fetchone()
        return row[0] if row else 1


def preprocess_excel_data(file_path):
    wb = openpyxl.load_workbook(file_path, data_only=True)
    sheet = wb["INV_ProductListing"]
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Excel sheet is empty")

    data_rows = rows[1:]

    processed_products = []
    categories_set = set()
    sku_tracker = {}
    duplicate_count = 0
    empty_desc_count = 0
    truncated_name_count = 0

    for idx, r in enumerate(data_rows, start=2):
        raw_sku = str(r[0]).strip() if r[0] is not None else ""
        raw_desc = str(r[1]).strip() if r[1] is not None else ""
        raw_cat = str(r[3]).strip() if r[3] is not None else "General Products"

        if not raw_sku:
            continue

        # Handle duplicate SKU in Excel
        if raw_sku in sku_tracker:
            duplicate_count += 1
            sku_tracker[raw_sku] += 1
            unique_sku = f"{raw_sku}-{sku_tracker[raw_sku]}"
        else:
            sku_tracker[raw_sku] = 0
            unique_sku = raw_sku

        # Handle empty description
        if not raw_desc:
            empty_desc_count += 1
            name = unique_sku
            description = unique_sku
        else:
            description = raw_desc
            if len(raw_desc) > 255:
                truncated_name_count += 1
                name = raw_desc[:255].strip()
            else:
                name = raw_desc

        category_name = raw_cat if raw_cat else "General Products"
        categories_set.add(category_name)

        processed_products.append({
            "sku": unique_sku,
            "code": unique_sku,
            "name": name,
            "description": description,
            "category_name": category_name,
            "unit": "PCS",
            "status": "active",
            "excel_row": idx,
        })

    return {
        "products": processed_products,
        "categories": sorted(list(categories_set)),
        "total_rows": len(data_rows),
        "valid_products": len(processed_products),
        "duplicates_resolved": duplicate_count,
        "empty_descriptions_handled": empty_desc_count,
        "long_names_truncated_for_db_varchar": truncated_name_count,
    }


def seed_categories(conn, org_id, categories, user_id):
    with conn.cursor() as cur:
        # 1. Get or create root 'Products' category
        cur.execute(
            """
            SELECT id FROM containermgmt.product_categories 
            WHERE org_id = %s AND name = 'Products' AND parent_id IS NULL;
            """,
            (org_id,),
        )
        row = cur.fetchone()
        if row:
            root_id = row[0]
        else:
            cur.execute(
                """
                INSERT INTO containermgmt.product_categories (
                    org_id, name, description, is_subcategory, is_deleted, created_by, updated_by, created_at, updated_at
                ) VALUES (%s, 'Products', 'Master Root Product Catalog', FALSE, FALSE, %s, %s, NOW(), NOW())
                RETURNING id;
                """,
                (org_id, user_id, user_id),
            )
            root_id = cur.fetchone()[0]

        # 2. Get existing categories
        cur.execute(
            "SELECT id, name FROM containermgmt.product_categories WHERE org_id = %s;",
            (org_id,),
        )
        cat_map = {r[1].strip().upper(): r[0] for r in cur.fetchall()}

        # 3. Create missing categories under root
        created_count = 0
        for cat_name in categories:
            norm_name = cat_name.strip()
            if norm_name.upper() not in cat_map:
                cur.execute(
                    """
                    INSERT INTO containermgmt.product_categories (
                        org_id, name, description, parent_id, is_subcategory, is_deleted, created_by, updated_by, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, TRUE, FALSE, %s, %s, NOW(), NOW())
                    RETURNING id;
                    """,
                    (org_id, norm_name, f"Category for {norm_name}", root_id, user_id, user_id),
                )
                new_id = cur.fetchone()[0]
                cat_map[norm_name.upper()] = new_id
                created_count += 1

    return cat_map, created_count


def ensure_unique_sku_index(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_containermgmt_products_org_sku 
            ON containermgmt.products (org_id, sku);
            """
        )


def seed_products(conn, org_id, products, cat_map, user_id):
    ensure_unique_sku_index(conn)

    upsert_sql = """
        INSERT INTO containermgmt.products (
            org_id, sku, code, name, description, category_id,
            unit, status, current_stock, is_deleted, created_by, updated_by,
            created_at, updated_at
        ) VALUES (
            %(org_id)s, %(sku)s, %(code)s, %(name)s, %(description)s, %(category_id)s,
            %(unit)s, %(status)s, 0.0, FALSE, %(user_id)s, %(user_id)s,
            NOW(), NOW()
        )
        ON CONFLICT (org_id, sku) DO UPDATE SET
            code = EXCLUDED.code,
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            category_id = EXCLUDED.category_id,
            unit = EXCLUDED.unit,
            status = EXCLUDED.status,
            is_deleted = FALSE,
            updated_by = EXCLUDED.updated_by,
            updated_at = NOW();
    """

    records = []
    for p in products:
        cat_id = cat_map.get(p["category_name"].strip().upper())
        records.append({
            "org_id": org_id,
            "sku": p["sku"],
            "code": p["code"],
            "name": p["name"],
            "description": p["description"],
            "category_id": cat_id,
            "unit": p["unit"],
            "status": p["status"],
            "user_id": user_id,
        })

    with conn.cursor() as cur:
        execute_batch(cur, upsert_sql, records, page_size=500)

    return len(records)


def export_enrichment_template(products, output_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Product_Master_Enrichment"
    ws.views.sheetView[0].showGridLines = True

    # Color definitions
    header_fill_primary = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")  # Navy
    header_fill_enrich = PatternFill(start_color="0D9488", end_color="0D9488", fill_type="solid")   # Teal
    header_fill_stock = PatternFill(start_color="6366F1", end_color="6366F1", fill_type="solid")    # Indigo
    header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=9)
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )

    headers = [
        # Seeded Core Identification (Columns A-E)
        ("Item Code / SKU", "seeded", 18),
        ("Product Name", "seeded", 35),
        ("Full Description", "seeded", 45),
        ("Category", "seeded", 24),
        ("Unit of Measure", "seeded", 16),
        # Empty Enrichment Columns for Logistics & Physical Specs (Columns F-O)
        ("Unit Length (mm)", "enrich", 16),
        ("Unit Width (mm)", "enrich", 16),
        ("Unit Height (mm)", "enrich", 16),
        ("Weight per Unit (kg)", "enrich", 18),
        ("Units per Box / Carton", "enrich", 20),
        ("Box Weight (kg)", "enrich", 16),
        ("Master Length (mm)", "enrich", 18),
        ("Master Width (mm)", "enrich", 18),
        ("Master Height (mm)", "enrich", 18),
        ("Master Tare Weight (kg)", "enrich", 22),
        # Pricing, Supplier & Compliance (Columns P-T)
        ("Barcode / EAN", "enrich", 18),
        ("HS Code", "enrich", 16),
        ("Estimated Unit Cost", "enrich", 18),
        ("Cost Currency (e.g. USD/SCR)", "enrich", 24),
        ("Primary Supplier Name", "enrich", 26),
        # Inventory Controls (Columns U-W)
        ("Initial Stock Count", "stock", 18),
        ("Min Reorder Quantity", "stock", 20),
        ("Warehouse Bin / Shelf", "stock", 20),
    ]

    # Write Headers
    for col_idx, (col_name, col_type, width) in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if col_type == "seeded":
            cell.fill = header_fill_primary
        elif col_type == "stock":
            cell.fill = header_fill_stock
        else:
            cell.fill = header_fill_enrich

        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "F2"  # Freeze A-E so SKU and Name stay visible while scrolling horizontally
    ws.auto_filter.ref = f"A1:W{len(products) + 1}"

    # Populate Data
    for row_idx, p in enumerate(products, start=2):
        row_values = [
            p["sku"],
            p["name"],
            p["description"],
            p["category_name"],
            p["unit"],
            # Empty enrichment columns:
            "", "", "", "", "", "", "", "", "", "",
            "", "", "", "", "",
            0, "", "",
        ]
        for col_idx, val in enumerate(row_values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border
            if col_idx in (1, 5):
                cell.alignment = Alignment(horizontal="center")
            else:
                cell.alignment = Alignment(horizontal="left")

        ws.row_dimensions[row_idx].height = 19

    wb.save(output_path)
    return output_path


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "preview"
    print("=" * 70)
    print(f"📦 FREIGHTLENS PRODUCT MASTER SEEDER & ENRICHMENT EXPORTER")
    print(f"Action: {action.upper()}")
    print("=" * 70)

    # 1. Preprocess
    print("\n🔍 Step 1: Pre-processing Excel Data...")
    audit = preprocess_excel_data(EXCEL_FILE)
    print(f"  • Total Excel Rows: {audit['total_rows']}")
    print(f"  • Valid Products to Seed: {audit['valid_products']}")
    print(f"  • Distinct Categories Found: {len(audit['categories'])}")
    print(f"  • Duplicate SKUs Disambiguated: {audit['duplicates_resolved']}")
    print(f"  • Empty Descriptions Defaulted: {audit['empty_descriptions_handled']}")
    print(f"  • Long Names Handled (<=255 chars for name, full in desc): {audit['long_names_truncated_for_db_varchar']}")

    if action == "preview":
        print("\n✅ Pre-processing Complete. Database was NOT modified.")
        print("Ready for confirmation to execute.")
        return

    # 2. Connect
    print(f"\n🔌 Step 2: Connecting to Database at {DEFAULT_DB_HOST}:{DEFAULT_DB_PORT}...")
    conn = get_db_connection()
    conn.autocommit = False

    try:
        org_id = 1
        user_id = get_admin_user_id(conn)
        print(f"  • Operating under Org ID: {org_id}, Audit User ID: {user_id}")

        # 3. Seed Categories
        print("\n📁 Step 3: Seeding / Verifying Product Categories...")
        cat_map, created_cats = seed_categories(conn, org_id, audit["categories"], user_id)
        print(f"  • Total Categories in Catalog: {len(cat_map)}")
        print(f"  • New Categories Created: {created_cats}")

        # 4. Upsert Products
        print("\n📥 Step 4: Upserting 5,782 Products into containermgmt.products...")
        seeded_count = seed_products(conn, org_id, audit["products"], cat_map, user_id)
        conn.commit()
        print(f"  • Successfully Committed: {seeded_count} Products into Database!")

        # 5. Export Enrichment Template
        print(f"\n📊 Step 5: Generating Bulk Enrichment Spreadsheet...")
        export_path = export_enrichment_template(audit["products"], EXPORT_FILE)
        print(f"  • Export Complete: {export_path}")
        print(f"  • Total Records in Enrichment Template: {seeded_count}")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error during seeding: {e}")
        raise
    finally:
        conn.close()

    print("\n🎉 ALL OPERATIONS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
