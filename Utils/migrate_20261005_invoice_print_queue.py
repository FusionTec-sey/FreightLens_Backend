"""Replay-safe T17 invoice artifact and print-state foundation."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Orders.SalesInvoicePrint import (
    ARTIFACT_GUARD_FUNCTION, ARTIFACT_GUARD_TRIGGER, IMMUTABLE_FUNCTION,
    JOB_EVENT_GUARD_FUNCTION, JOB_EVENT_GUARD_TRIGGER,
    JOB_STATE_GUARD_FUNCTION, JOB_STATE_GUARD_TRIGGER,
    JOB_UPDATE_FUNCTION, JOB_UPDATE_TRIGGER, MODELS, SalesInvoiceArtifact,
    SalesInvoicePrintEvent, SalesInvoicePrintJob, immutable_trigger,
)


SALES_INVOICE_TEMPLATE_HTML = """
<div class="invoice-document">
  <header class="invoice-header"><div><h1>TAX INVOICE</h1>
    <strong>{{ company.legal_name }}</strong><p>{{ company.address }}</p>
    <p>Tax/VAT: {{ company.tax_id }}</p>{% if company.phone %}<p>{{ company.phone }}</p>{% endif %}
    {% if company.email %}<p>{{ company.email }}</p>{% endif %}</div>
    <div class="invoice-meta"><strong>{{ invoice.invoice_number }}</strong>
      <p>Business date: {{ invoice.business_date }}</p><p>Issued: {{ invoice.issued_at }}</p>
      <p>Store: {{ branch.name }}</p></div></header>
  <section class="customer"><h2>Customer</h2><strong>{{ customer.name }}</strong>
    {% for contact in customer.contacts %}<p>{{ contact.kind }}: {{ contact.value }}</p>{% endfor %}</section>
  <table><thead><tr><th>#</th><th>SKU / item</th><th class="number">Qty</th>
    <th class="number">Unit price SCR</th><th class="number">Tax</th><th class="number">Total SCR</th>
  </tr></thead><tbody>{% for line in lines %}<tr><td>{{ loop.index }}</td>
    <td><strong>{{ line.product_name }}</strong><br><small>{{ line.sku }}</small></td>
    <td class="number">{{ line.quantity }} {{ line.unit }}</td><td class="number">{{ line.gross_unit_scr }}</td>
    <td class="number">{{ line.tax_treatment|replace('_', ' ') }}<br>{{ line.tax_total_scr }}</td>
    <td class="number">{{ line.gross_total_scr }}</td></tr>{% endfor %}</tbody></table>
  <section class="totals"><p>Net <strong>SCR {{ invoice.net_total_scr }}</strong></p>
    <p>Included tax <strong>SCR {{ invoice.tax_total_scr }}</strong></p>
    <p class="grand">Total <strong>SCR {{ invoice.gross_total_scr }}</strong></p></section>
  <section class="payments"><h2>Payment</h2>{% for payment in payments %}
    <p>{{ payment.kind }} — SCR {{ payment.amount_scr }}</p>{% endfor %}</section>
  {% if terms %}<section class="terms"><h2>Terms</h2><p>{{ terms }}</p></section>{% endif %}
  <footer>Payment and physical handover are recorded separately.</footer>
</div>
""".strip()

SALES_INVOICE_TEMPLATE_CSS = """
body { color:#0f172a; font-family:Arial,sans-serif; font-size:10pt; }
.invoice-header { display:flex; justify-content:space-between; gap:18mm; border-bottom:2px solid #0f172a; padding-bottom:5mm; }
.invoice-header h1 { margin:0 0 3mm; font-size:20pt; } .invoice-header p,.customer p,.payments p { margin:1mm 0; }
.invoice-meta { min-width:58mm; text-align:right; } .invoice-meta>strong { font-size:13pt; }
.customer { margin:5mm 0; padding:3mm; background:#f8fafc; } h2 { margin:0 0 2mm; font-size:10pt; text-transform:uppercase; color:#475569; }
table { width:100%; border-collapse:collapse; } th { background:#0f172a; color:white; text-align:left; padding:2.5mm; }
td { border-bottom:1px solid #cbd5e1; padding:2.5mm; vertical-align:top; } .number { text-align:right; white-space:nowrap; }
.totals { margin:5mm 0 5mm auto; width:72mm; } .totals p { display:flex; justify-content:space-between; margin:1.5mm 0; }
.totals .grand { border-top:2px solid #0f172a; padding-top:2mm; font-size:13pt; }
.payments,.terms { margin-top:4mm; padding-top:3mm; border-top:1px solid #cbd5e1; }
footer { margin-top:8mm; color:#64748b; font-size:8.5pt; }
""".strip()


def _seed_template(conn):
    row = conn.execute(text("""
        SELECT id FROM containermgmt.report_templates
        WHERE is_system=TRUE AND slug='sales_invoice' AND is_deleted=FALSE
    """)).first()
    if row:
        return
    template_id = conn.execute(text("""
        INSERT INTO containermgmt.report_templates
          (org_id,slug,name,description,category,resolver_key,entity_type,is_system,
           is_active,page_size,orientation,output_format,is_deleted)
        VALUES ((SELECT min(id) FROM usercredentials.organisations),'sales_invoice',
          'Standard Sales Tax Invoice','Immutable tax-inclusive SCR sales invoice',
          'SALES','sales_invoice','SalesInvoice',TRUE,TRUE,'A4','portrait','pdf',FALSE)
        RETURNING id
    """)).scalar_one()
    version_id = conn.execute(text("""
        INSERT INTO containermgmt.report_template_versions
          (template_id,version_number,status,html_content,css_content,change_notes,is_deleted)
        VALUES (:template_id,1,'PUBLISHED',:html,:css,
          'T17 immutable invoice release',FALSE) RETURNING id
    """), {"template_id": template_id, "html": SALES_INVOICE_TEMPLATE_HTML,
            "css": SALES_INVOICE_TEMPLATE_CSS}).scalar_one()
    conn.execute(text("""UPDATE containermgmt.report_templates
        SET active_version_id=:version_id WHERE id=:template_id"""),
        {"version_id": version_id, "template_id": template_id})


def _trigger(conn, table, name, ddl):
    exists = conn.execute(text(
        "SELECT 1 FROM pg_trigger WHERE tgrelid=CAST(:table AS regclass) "
        "AND tgname=:name AND NOT tgisinternal"
    ), {"table": f"containermgmt.{table}", "name": name}).scalar()
    if not exists:
        conn.execute(text(ddl))


def ensure_sales_invoice_printing_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for model in MODELS:
            model.__table__.create(conn, checkfirst=True)
        _seed_template(conn)
        conn.execute(text(IMMUTABLE_FUNCTION))
        for model in (SalesInvoiceArtifact, SalesInvoicePrintEvent):
            _trigger(conn, model.__tablename__, f"{model.__tablename__}_immutable",
                     immutable_trigger(model.__tablename__))
        conn.execute(text(ARTIFACT_GUARD_FUNCTION))
        _trigger(conn, SalesInvoiceArtifact.__tablename__,
                 "sales_invoice_artifact_guard", ARTIFACT_GUARD_TRIGGER)
        conn.execute(text(JOB_UPDATE_FUNCTION))
        _trigger(conn, SalesInvoicePrintJob.__tablename__,
                 "sales_invoice_print_job_update_guard", JOB_UPDATE_TRIGGER)
        conn.execute(text(JOB_STATE_GUARD_FUNCTION))
        _trigger(conn, SalesInvoicePrintJob.__tablename__,
                 "sales_invoice_print_job_state_guard", JOB_STATE_GUARD_TRIGGER)
        conn.execute(text(JOB_EVENT_GUARD_FUNCTION))
        _trigger(conn, SalesInvoicePrintEvent.__tablename__,
                 "sales_invoice_print_event_guard", JOB_EVENT_GUARD_TRIGGER)


if __name__ == "__main__":
    ensure_sales_invoice_printing_schema()
