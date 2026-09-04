from weasyprint import HTML # type: ignore
from jinja2 import Environment, FileSystemLoader
import os

def generate_damage_report_pdf(data: dict) -> bytes:
    template_dir = os.path.join("templates", "report")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("damage_report.html")

    html_content = template.render(data)
    pdf_bytes = HTML(string=html_content, base_url=".").write_pdf()

    return pdf_bytes

def generate_defect_report_pdf(d) -> bytes:
    items_html = ""
    for idx, it in enumerate(d.items or [], 1):
        if not it.is_deleted:
            items_html += f"""
            <tr>
                <td style="text-align:center;">{idx}</td>
                <td><strong>{it.item_description}</strong></td>
                <td>{it.quantity_affected or 1} {it.unit or 'PCS'}</td>
                <td>{it.notes or '—'}</td>
            </tr>
            """

    report_type_str = "Receiving Defect" if getattr(d, 'report_type', None) == 'GOODS_DEFECT' else 'Container Damage'
    disc_date = str(d.discovery_date or (d.created_at.strftime('%Y-%m-%d') if d.created_at else '—'))
    cont_or_po = ""
    if d.container and d.container.container_no:
        cont_or_po = d.container.container_no
    elif d.purchase_order and d.purchase_order.po_number:
        cont_or_po = d.purchase_order.po_number
    else:
        cont_or_po = "—"

    resolution_html = ""
    if getattr(d, 'status', None) == 'RESOLVED' or getattr(d, 'resolution_type', None):
        resolution_html = f"""
        <div style="font-size: 15px; font-weight: 600; color: #0f172a; margin-top: 24px; margin-bottom: 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px;">Resolution</div>
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; margin-top: 8px; font-size: 13px;">
            <strong>Status: {d.status}</strong> · {d.resolution_type or 'Pending Review'}<br/>
            {d.resolution_notes or ''}
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{d.defect_number}</title>
    <style>
        @page {{ size: A4 portrait; margin: 20mm; }}
        body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1e293b; line-height: 1.5; font-size: 13px; }}
        .header {{ border-bottom: 2px solid #2563eb; padding-bottom: 16px; margin-bottom: 20px; }}
        .title {{ font-size: 22px; font-weight: bold; color: #0f172a; margin: 0; }}
        .ref {{ font-size: 13px; color: #2563eb; font-weight: 600; margin-top: 4px; }}
        .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
        .meta-table td {{ width: 50%; padding: 6px 0; vertical-align: top; font-size: 13px; border: none; }}
        .meta-label {{ color: #64748b; text-transform: uppercase; font-size: 11px; font-weight: 600; }}
        .meta-val {{ font-weight: 600; color: #0f172a; margin-top: 2px; }}
        table.items-table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12px; }}
        table.items-table th {{ background: #f1f5f9; border: 1px solid #cbd5e1; padding: 8px 10px; text-align: left; font-weight: 600; color: #475569; }}
        table.items-table td {{ border: 1px solid #cbd5e1; padding: 8px 10px; text-align: left; }}
        .section-title {{ font-size: 15px; font-weight: 600; color: #0f172a; margin-top: 20px; margin-bottom: 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 700; background: #e0f2fe; color: #0369a1; }}
        .notes-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; margin-top: 8px; font-size: 13px; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="title">Damage & Defect Report</div>
        <div class="ref">{d.defect_number} · <span class="badge">{d.status}</span></div>
    </div>

    <table class="meta-table">
        <tr>
            <td>
                <div class="meta-label">Report Type</div>
                <div class="meta-val">{report_type_str}</div>
            </td>
            <td>
                <div class="meta-label">Discovery Date</div>
                <div class="meta-val">{disc_date}</div>
            </td>
        </tr>
        <tr>
            <td>
                <div class="meta-label">Container / Order Reference</div>
                <div class="meta-val">{cont_or_po}</div>
            </td>
            <td>
                <div class="meta-label">Bill of Lading</div>
                <div class="meta-val">{d.bill_of_lading_no or '—'}</div>
            </td>
        </tr>
    </table>

    <div class="section-title">Summary & Description</div>
    <div class="notes-box">
        <strong>{d.title or 'Defect Details'}</strong><br/>
        {d.description or 'No additional description provided.'}
    </div>

    <div class="section-title">Affected Goods & Observations</div>
    <table class="items-table">
        <thead>
            <tr>
                <th style="width: 35px; text-align:center;">#</th>
                <th>Description</th>
                <th style="width: 100px;">Quantity</th>
                <th>Observation / Notes</th>
            </tr>
        </thead>
        <tbody>
            {items_html if items_html else '<tr><td colspan="4" style="text-align:center; color:#64748b; padding:16px;">No individual item rows specified</td></tr>'}
        </tbody>
    </table>

    {resolution_html}

    <div style="margin-top: 40px; border-top: 1px solid #cbd5e1; padding-top: 10px; font-size: 11px; color: #94a3b8; text-align: right;">
        FreightLens Defect Register · Generated on {disc_date}
    </div>
</body>
</html>"""
    return HTML(string=html).write_pdf()
