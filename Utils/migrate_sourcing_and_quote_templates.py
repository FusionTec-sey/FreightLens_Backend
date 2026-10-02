"""
Utils/migrate_sourcing_and_quote_templates.py
Migration script for Sourcing RFQ & Vendor Quote Comparison Document Templates.
Seeds two standard system templates:
  - sourcing_rfq_requisition (RFQ, ORDERS, Portrait A4)
  - vendor_quote_comparison_sheet (QuoteComparison, ORDERS, Landscape A4)
Activates them by default for all existing organizations.
"""

import logging
import os
import sys

# Ensure parent directory is in sys.path when executed directly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_sourcing_quote_templates")

# ── 1. Sourcing RFQ Template ──────────────────────────────────────────────────

RFQ_TEMPLATE_HTML = """
<div class="report-container">
    <div class="header">
        <div class="brand">
            <h1>REQUEST FOR QUOTATION</h1>
            <div class="rfq-badge">{{ rfq_number }}</div>
            {% if po_nce %}<div class="sub-ref">Internal Requisition: {{ po_nce }}</div>{% endif %}
        </div>
        <div class="meta-box">
            <p><strong>Issue Date:</strong> {{ issue_date or report_date }}</p>
            <p><strong>Closing / Due Date:</strong> <span class="due-tag">{{ due_date or 'Open' }}</span></p>
            <p><strong>Status:</strong> <span class="status-tag">{{ status_label or status }}</span></p>
            <p><strong>Freight Mode:</strong> {{ freight_type or 'Sea Freight' }}</p>
            <p><strong>Delivery Destination:</strong> {{ destination_port or consignee_name }}</p>
        </div>
    </div>

    <div class="parties-grid">
        <div class="party-card">
            <h3>Issuing Buyer / Requisitioner</h3>
            <p class="party-name">{{ org_name }}</p>
            {% if consignee_name and consignee_name != org_name %}
                <p><strong>Consignee:</strong> {{ consignee_name }}</p>
            {% endif %}
            {% if company.address %}<p>{{ company.address }}</p>{% endif %}
            <p class="subtext">Inquiries & Submissions: <strong>{{ buyer_contact or company.email }}</strong></p>
        </div>
        <div class="party-card">
            <h3>Invited Bidder / Vendor</h3>
            <p class="party-name">{{ supplier.name or supplier_name or 'Prospective Supplier' }}</p>
            {% if supplier.address %}<p>{{ supplier.address }}</p>{% endif %}
            {% if supplier.contact_person %}<p>Attn: {{ supplier.contact_person }}</p>{% endif %}
            {% if supplier.email %}<p>{{ supplier.email }}</p>{% endif %}
            <p class="subtext">Please reference <strong>{{ rfq_number }}</strong> on all correspondences.</p>
        </div>
    </div>

    {% if remark %}
    <div class="instructions-box">
        <strong>Requisition Scope & Instructions:</strong>
        <p>{{ remark }}</p>
    </div>
    {% endif %}

    <table class="data-table">
        <thead>
            <tr>
                <th style="width: 5%;">#</th>
                <th style="width: 18%;">Item / SKU</th>
                <th style="width: 42%;">Item Description & Technical Specifications</th>
                <th style="width: 15%; text-align: right;">Quantity</th>
                <th style="width: 8%;">Unit</th>
                {% if show_budget %}
                <th style="width: 12%; text-align: right;">Est. Unit Price</th>
                {% endif %}
            </tr>
        </thead>
        <tbody>
            {% for item in items %}
            <tr>
                <td style="text-align: center;">{{ loop.index }}</td>
                <td><span class="sku-code">{{ item.item_code or item.sku or '—' }}</span></td>
                <td>
                    <div class="item-title">{{ item.description }}</div>
                    {% if item.technical_specifications %}
                    <div class="item-specs">{{ item.technical_specifications }}</div>
                    {% endif %}
                </td>
                <td style="text-align: right; font-weight: 700;">{{ item.quantity | format_number(0) }}</td>
                <td>{{ item.unit or 'PCS' }}</td>
                {% if show_budget %}
                <td style="text-align: right;">{{ item.estimated_unit_price | format_currency(currency) if item.estimated_unit_price else '—' }}</td>
                {% endif %}
            </tr>
            {% else %}
            <tr>
                <td colspan="{% if show_budget %}6{% else %}5{% endif %}" style="text-align: center; color: #64748b; padding: 24px;">
                    No requisition items specified.
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <div class="terms-grid">
        <div class="terms-card">
            <h4>Bidding Terms & Submission Guidelines</h4>
            <ul>
                {% for inst in instructions %}
                    <li>{{ inst }}</li>
                {% else %}
                    <li>Prices must be quoted on a firm CIF Port Victoria or FOB basis.</li>
                    <li>State country of manufacture, brand, and expected shipping lead times.</li>
                    <li>Quotations must remain valid for a minimum of 30 days from closing date.</li>
                {% endfor %}
            </ul>
        </div>
        <div class="terms-card">
            <h4>Commercial Checklist (To be completed by Bidder)</h4>
            <div class="checklist-item"><span>Total Quoted Amount:</span> <span class="fill-line"></span></div>
            <div class="checklist-item"><span>Delivery Lead Time:</span> <span class="fill-line"></span></div>
            <div class="checklist-item"><span>Quotation Validity:</span> <span class="fill-line"></span></div>
            <div class="checklist-item"><span>Payment Terms Offered:</span> <span class="fill-line"></span></div>
        </div>
    </div>

    <div class="signatures">
        <div class="sig-block">
            <div class="sig-line"></div>
            <p>Authorized Buyer / Procurement Lead</p>
            <span class="sig-date">Date: {{ report_date }}</span>
        </div>
        <div class="sig-block">
            <div class="sig-line"></div>
            <p>Bidder Representative Signature & Stamp</p>
            <span class="sig-date">Date: ________________________</span>
        </div>
    </div>
</div>
"""

RFQ_TEMPLATE_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    color: #1e293b;
    font-size: 11px;
    line-height: 1.5;
    margin: 0;
}
.report-container { width: 100%; }
.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2px solid #2563eb;
    padding-bottom: 14px;
    margin-bottom: 18px;
}
.brand h1 { margin: 0; font-size: 22px; color: #1e3a8a; letter-spacing: -0.5px; font-weight: 800; }
.rfq-badge { display: inline-block; font-size: 13px; font-weight: 700; color: #2563eb; margin-top: 3px; font-family: monospace; }
.sub-ref { font-size: 10px; color: #64748b; margin-top: 2px; }
.meta-box { text-align: right; }
.meta-box p { margin: 2px 0; font-size: 10.5px; }
.status-tag { display: inline-block; background: #dbeafe; color: #1d4ed8; padding: 2px 7px; border-radius: 4px; font-weight: 700; font-size: 10px; }
.due-tag { display: inline-block; background: #fee2e2; color: #b91c1c; padding: 2px 6px; border-radius: 4px; font-weight: 700; }

.parties-grid {
    display: flex;
    justify-content: space-between;
    margin-bottom: 16px;
    gap: 16px;
}
.party-card {
    flex: 1;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 14px;
}
.party-card h3 { margin: 0 0 6px 0; font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: 700; letter-spacing: 0.5px; }
.party-name { font-size: 13px; font-weight: 700; color: #0f172a; margin: 0 0 3px 0; }
.subtext { font-size: 9.5px; color: #64748b; margin-top: 6px; }

.instructions-box {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-left: 4px solid #3b82f6;
    padding: 8px 12px;
    border-radius: 4px;
    margin-bottom: 16px;
    font-size: 10.5px;
    color: #1e40af;
}
.instructions-box p { margin: 2px 0 0 0; }

.data-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 20px;
}
.data-table th {
    background: #1e293b;
    color: #ffffff;
    font-size: 10px;
    text-transform: uppercase;
    font-weight: 600;
    padding: 7px 9px;
    border: 1px solid #334155;
    text-align: left;
}
.data-table td {
    padding: 7px 9px;
    border: 1px solid #e2e8f0;
    vertical-align: top;
    font-size: 10.5px;
}
.data-table tr:nth-child(even) td { background: #f8fafc; }
.sku-code { font-family: monospace; font-size: 10px; font-weight: 600; color: #2563eb; background: #eff6ff; padding: 1px 4px; border-radius: 3px; }
.item-title { font-weight: 700; color: #0f172a; }
.item-specs { font-size: 9.5px; color: #64748b; margin-top: 2px; }

.terms-grid {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 30px;
}
.terms-card {
    flex: 1;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 14px;
    background: #fafafa;
}
.terms-card h4 { margin: 0 0 8px 0; font-size: 10.5px; text-transform: uppercase; color: #475569; font-weight: 700; }
.terms-card ul { margin: 0; padding-left: 16px; font-size: 10px; color: #475569; }
.terms-card li { margin-bottom: 4px; }
.checklist-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 10px;
    color: #475569;
    margin-bottom: 6px;
}
.fill-line { flex: 1; border-bottom: 1px dotted #94a3b8; margin-left: 8px; height: 12px; }

.signatures {
    margin-top: 40px;
    display: flex;
    justify-content: space-between;
    page-break-inside: avoid;
}
.sig-block {
    width: 42%;
    text-align: center;
}
.sig-line {
    border-top: 1px solid #64748b;
    margin-bottom: 5px;
}
.sig-block p {
    font-size: 10.5px;
    font-weight: 600;
    color: #334155;
    margin: 0;
}
.sig-date { font-size: 9.5px; color: #94a3b8; }
"""


# ── 2. Vendor Quote Comparison Sheet Template ─────────────────────────────────

QUOTE_COMPARISON_TEMPLATE_HTML = """
<div class="report-container">
    <div class="header">
        <div class="brand">
            <h1>COMMERCIAL BID EVALUATION & PRICE COMPARISON</h1>
            <div class="ref-badge">Requisition Ref: {{ rfq_number }}</div>
            <div class="sub-info">{{ title }}</div>
        </div>
        <div class="meta-box">
            <p><strong>Evaluation Date:</strong> {{ comparison_date }}</p>
            <p><strong>Evaluator:</strong> {{ generated_by }}</p>
            <p><strong>Base Currency:</strong> <span class="cur-tag">{{ currency }}</span></p>
            <p><strong>Total Bidders:</strong> {{ summary.total_vendors or vendors | length }}</p>
            <p><strong>Items Evaluated:</strong> {{ summary.total_items or matrix_rows | length }}</p>
        </div>
    </div>

    <!-- Executive Summary Cards -->
    <div class="kpi-grid">
        <div class="kpi-card highlight">
            <div class="kpi-label">Recommended Award</div>
            <div class="kpi-val">{{ summary.recommended_vendor or 'Under Review' }}</div>
            <div class="kpi-sub">Lowest Compliant Bidder</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Lowest Quoted Total</div>
            <div class="kpi-val font-mono">{{ summary.lowest_vendor_total | format_currency(currency) if summary.lowest_vendor_total else '—' }}</div>
            <div class="kpi-sub">Best Price Option</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Highest Quoted Total</div>
            <div class="kpi-val font-mono">{{ summary.highest_vendor_total | format_currency(currency) if summary.highest_vendor_total else '—' }}</div>
            <div class="kpi-sub">Upper Boundary</div>
        </div>
        <div class="kpi-card savings">
            <div class="kpi-label">Max Cost Variance / Savings</div>
            <div class="kpi-val font-mono">{{ summary.potential_savings | format_currency(currency) if summary.potential_savings else '—' }}</div>
            <div class="kpi-sub">Budget Impact</div>
        </div>
    </div>

    <!-- Participating Bidders Overview -->
    <div class="section-title">Participating Suppliers & Bid Overview</div>
    <div class="vendors-grid">
        {% for v in vendors %}
        <div class="vendor-card {% if v.rank == 1 %}rank-first{% endif %}">
            <div class="vendor-header">
                <span class="rank-badge">Rank #{{ v.rank or loop.index }}</span>
                <span class="status-badge">{{ v.status or 'Active' }}</span>
            </div>
            <div class="vendor-name">{{ v.vendor_name }}</div>
            <div class="vendor-detail"><strong>Quote Ref:</strong> {{ v.quote_reference }} ({{ v.quote_date }})</div>
            <div class="vendor-detail"><strong>Lead Time:</strong> {{ v.lead_time_days }} days</div>
            <div class="vendor-detail"><strong>Terms:</strong> {{ v.shipping_terms or '—' }} • {{ v.payment_terms or '—' }}</div>
            {% if show_financials %}
            <div class="vendor-total">{{ v.total_quoted_amount | format_currency(v.currency or currency) }}</div>
            {% endif %}
            {% if v.score_notes %}
            <div class="vendor-notes">{{ v.score_notes }}</div>
            {% endif %}
        </div>
        {% endfor %}
    </div>

    <!-- Comparative Item-by-Item Price Matrix -->
    <div class="section-title">Item-by-Item Comparative Matrix</div>
    <table class="matrix-table">
        <thead>
            <tr>
                <th style="width: 4%;">#</th>
                <th style="width: 14%;">Item Code</th>
                <th style="width: 24%;">Description</th>
                <th style="width: 8%; text-align: right;">Qty</th>
                <th style="width: 6%;">Unit</th>
                {% for v in vendors %}
                <th style="text-align: right;" class="vendor-th">
                    <div class="th-vendor">{{ v.vendor_name }}</div>
                    <div class="th-meta">Unit Price | Total</div>
                </th>
                {% endfor %}
            </tr>
        </thead>
        <tbody>
            {% for row in matrix_rows %}
            <tr>
                <td style="text-align: center;">{{ loop.index }}</td>
                <td><span class="code-tag">{{ row.item_code }}</span></td>
                <td><div class="item-name">{{ row.description }}</div></td>
                <td style="text-align: right; font-weight: 700;">{{ row.quantity | format_number(0) }}</td>
                <td>{{ row.unit }}</td>
                {% for q in row.quotes %}
                <td style="text-align: right;" class="{% if q.is_awarded %}awarded-cell{% elif q.unit_price == row.lowest_unit_price and q.unit_price is not none %}lowest-cell{% endif %}">
                    {% if show_financials and q.unit_price is not none %}
                        <div class="cell-unit">{{ q.unit_price | format_currency(currency) }}</div>
                        <div class="cell-total font-mono">{{ q.total_price | format_currency(currency) }}</div>
                        {% if q.is_awarded %}
                            <span class="awarded-tag">AWARDED</span>
                        {% elif q.unit_price == row.lowest_unit_price %}
                            <span class="lowest-tag">LOWEST</span>
                        {% endif %}
                    {% else %}
                        <span class="no-quote">—</span>
                    {% endif %}
                </td>
                {% endfor %}
            </tr>
            {% endfor %}
        </tbody>
        <tfoot>
            <tr class="tfoot-row">
                <td colspan="5" style="text-align: right; font-weight: 800; text-transform: uppercase;">
                    Total Commercial Bid ({{ currency }}):
                </td>
                {% for v in vendors %}
                <td style="text-align: right;" class="tfoot-vendor {% if v.rank == 1 %}tfoot-winner{% endif %}">
                    {% if show_financials and v.total_quoted_amount %}
                        <div class="foot-total">{{ v.total_quoted_amount | format_currency(v.currency or currency) }}</div>
                        <div class="foot-rank">Rank #{{ v.rank or loop.index }}</div>
                    {% else %}
                        <div class="foot-total">—</div>
                    {% endif %}
                </td>
                {% endfor %}
            </tr>
        </tfoot>
    </table>

    <!-- Commercial Recommendation & Approvals -->
    <div class="eval-footer">
        <div class="eval-notes">
            <h4>Evaluation Summary & Justification</h4>
            <p>
                Evaluation conducted based on lowest compliant total, delivery timeline feasibility, and supplier terms compliance.
                Selected vendor offer: <strong>{{ summary.recommended_vendor or 'As noted' }}</strong>.
            </p>
        </div>
        <div class="signatures-row">
            <div class="sig-box">
                <div class="s-line"></div>
                <span>Procurement Specialist</span>
            </div>
            <div class="sig-box">
                <div class="s-line"></div>
                <span>Finance & Accounts Review</span>
            </div>
            <div class="sig-box">
                <div class="s-line"></div>
                <span>Managing Director Approval</span>
            </div>
        </div>
    </div>
</div>
"""

QUOTE_COMPARISON_TEMPLATE_CSS = """
@page {
    size: A4 landscape;
    margin: 10mm 12mm 10mm 12mm;
    @bottom-right {
        content: "Page " counter(page) " of " counter(pages);
        font-size: 8pt;
        color: #64748b;
    }
}
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    color: #0f172a;
    font-size: 10px;
    line-height: 1.4;
    margin: 0;
}
.report-container { width: 100%; }

.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2px solid #0f172a;
    padding-bottom: 8px;
    margin-bottom: 12px;
}
.brand h1 { margin: 0; font-size: 17px; color: #0f172a; font-weight: 800; letter-spacing: -0.5px; }
.ref-badge { display: inline-block; font-size: 12px; font-weight: 700; color: #2563eb; font-family: monospace; margin-top: 2px; }
.sub-info { font-size: 9.5px; color: #64748b; margin-top: 2px; }
.meta-box { text-align: right; }
.meta-box p { margin: 1px 0; font-size: 9.5px; }
.cur-tag { background: #e2e8f0; padding: 1px 5px; border-radius: 3px; font-family: monospace; font-weight: 700; }

.kpi-grid {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 12px;
}
.kpi-card {
    flex: 1;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 8px 12px;
}
.kpi-card.highlight {
    background: #eff6ff;
    border-color: #93c5fd;
    border-left: 3px solid #2563eb;
}
.kpi-card.savings {
    background: #f0fdf4;
    border-color: #bbf7d0;
    border-left: 3px solid #16a34a;
}
.kpi-label { font-size: 8.5px; text-transform: uppercase; color: #64748b; font-weight: 700; letter-spacing: 0.5px; }
.kpi-val { font-size: 14px; font-weight: 800; color: #0f172a; margin-top: 2px; }
.kpi-sub { font-size: 8.5px; color: #94a3b8; }

.section-title {
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    color: #475569;
    border-bottom: 1px solid #cbd5e1;
    padding-bottom: 3px;
    margin-bottom: 8px;
    margin-top: 10px;
}

.vendors-grid {
    display: flex;
    gap: 10px;
    margin-bottom: 14px;
}
.vendor-card {
    flex: 1;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 9.5px;
}
.vendor-card.rank-first {
    border-color: #2563eb;
    background: #f8faff;
    box-shadow: 0 1px 3px rgba(37, 99, 235, 0.1);
}
.vendor-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 4px;
}
.rank-badge { font-weight: 700; font-size: 9px; color: #2563eb; background: #dbeafe; padding: 1px 5px; border-radius: 3px; }
.status-badge { font-size: 8.5px; color: #475569; }
.vendor-name { font-weight: 700; font-size: 11px; color: #0f172a; margin-bottom: 3px; }
.vendor-detail { color: #64748b; font-size: 9px; margin-bottom: 1px; }
.vendor-total { font-size: 12px; font-weight: 800; color: #0f172a; margin-top: 5px; border-top: 1px dashed #cbd5e1; padding-top: 3px; font-family: monospace; }
.vendor-notes { font-size: 8.5px; color: #2563eb; font-style: italic; margin-top: 2px; }

.matrix-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 14px;
    page-break-inside: auto;
}
.matrix-table thead { display: table-header-group; }
.matrix-table tr { page-break-inside: avoid; }
.matrix-table th {
    background: #1e293b;
    color: #ffffff;
    font-size: 9px;
    font-weight: 600;
    padding: 6px 8px;
    border: 1px solid #334155;
    text-align: left;
    text-transform: uppercase;
}
.matrix-table td {
    padding: 5px 8px;
    border: 1px solid #e2e8f0;
    vertical-align: middle;
    font-size: 9.5px;
}
.matrix-table tr:nth-child(even) td { background: #f8fafc; }
.vendor-th { background: #0f172a !important; }
.th-vendor { font-weight: 700; color: #ffffff; font-size: 9.5px; }
.th-meta { font-size: 8px; color: #94a3b8; font-weight: normal; }

.code-tag { font-family: monospace; font-size: 9px; font-weight: 600; color: #3b82f6; background: #eff6ff; padding: 1px 3px; border-radius: 2px; }
.item-name { font-weight: 600; color: #0f172a; }

.cell-unit { font-size: 9.5px; font-weight: 700; color: #0f172a; }
.cell-total { font-size: 8.5px; color: #64748b; }
.lowest-cell { background: #f0fdf4 !important; border: 1px solid #86efac !important; }
.lowest-tag { display: inline-block; font-size: 7.5px; font-weight: 700; color: #15803d; background: #dcfce7; padding: 0.5px 3px; border-radius: 2px; margin-top: 1px; }
.awarded-cell { background: #eff6ff !important; border: 1px solid #93c5fd !important; }
.awarded-tag { display: inline-block; font-size: 7.5px; font-weight: 700; color: #1d4ed8; background: #dbeafe; padding: 0.5px 3px; border-radius: 2px; margin-top: 1px; }
.no-quote { color: #94a3b8; font-family: monospace; }

.tfoot-row td {
    background: #e2e8f0 !important;
    border-top: 2px solid #0f172a !important;
    border-bottom: 2px solid #0f172a !important;
    padding: 6px 8px;
}
.tfoot-vendor { background: #cbd5e1 !important; }
.tfoot-winner { background: #dbeafe !important; }
.foot-total { font-size: 11px; font-weight: 800; color: #0f172a; font-family: monospace; }
.foot-rank { font-size: 8.5px; font-weight: 700; color: #2563eb; }

.eval-footer {
    display: flex;
    justify-content: space-between;
    gap: 18px;
    margin-top: 10px;
    page-break-inside: avoid;
}
.eval-notes {
    flex: 1.2;
    background: #fafafa;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 8px 12px;
}
.eval-notes h4 { margin: 0 0 4px 0; font-size: 9.5px; text-transform: uppercase; color: #475569; }
.eval-notes p { margin: 0; font-size: 9px; color: #64748b; line-height: 1.4; }

.signatures-row {
    flex: 1.8;
    display: flex;
    justify-content: space-between;
    gap: 12px;
}
.sig-box {
    flex: 1;
    text-align: center;
    padding-top: 20px;
}
.s-line {
    border-top: 1px solid #64748b;
    margin-bottom: 4px;
}
.sig-box span { font-size: 9px; font-weight: 600; color: #475569; }
"""

NEW_TEMPLATES = [
    {
        "slug": "sourcing_rfq_requisition",
        "name": "Sourcing Request for Quotation (RFQ)",
        "description": "Commercial quotation request document for suppliers with item specifications, bidding deadlines, terms, and submission guidelines.",
        "category": "ORDERS",
        "resolver_key": "sourcing_rfq",
        "entity_type": "RFQ",
        "page_size": "A4",
        "orientation": "portrait",
        "output_format": "pdf",
        "html_content": RFQ_TEMPLATE_HTML.strip(),
        "css_content": RFQ_TEMPLATE_CSS.strip(),
    },
    {
        "slug": "vendor_quote_comparison_sheet",
        "name": "Vendor Commercial Bid Evaluation Matrix",
        "description": "High-density landscape comparative bid matrix comparing unit prices, lead times, lowest bidder highlights, and commercial recommendations.",
        "category": "ORDERS",
        "resolver_key": "quote_comparison",
        "entity_type": "QuoteComparison",
        "page_size": "A4",
        "orientation": "landscape",
        "output_format": "pdf",
        "html_content": QUOTE_COMPARISON_TEMPLATE_HTML.strip(),
        "css_content": QUOTE_COMPARISON_TEMPLATE_CSS.strip(),
    },
]


def ensure_sourcing_and_quote_templates_schema():
    """
    Seeds the Sourcing RFQ and Quote Comparison templates if they do not exist,
    and activates them for all organizations.
    """
    logger.info("Checking Sourcing RFQ & Quote Comparison document templates...")
    with engine.begin() as conn:
        # Get list of existing org ids to activate for all
        org_ids_res = conn.execute(text("SELECT id FROM usercredentials.organisations WHERE is_active = TRUE")).fetchall()
        all_org_ids = [row[0] for row in org_ids_res]
        if not all_org_ids:
            all_org_ids = [1]

        for tpl in NEW_TEMPLATES:
            existing = conn.execute(
                text("""
                    SELECT id, active_version_id 
                    FROM containermgmt.report_templates 
                    WHERE is_system = TRUE AND slug = :slug AND is_deleted = FALSE
                """),
                {"slug": tpl["slug"]}
            ).fetchone()

            if not existing:
                # Insert template record
                result = conn.execute(
                    text("""
                        INSERT INTO containermgmt.report_templates (
                            org_id, slug, name, description, category, resolver_key,
                            entity_type, is_system, is_active, active_org_ids,
                            template_type, page_size, orientation, output_format, is_deleted
                        ) VALUES (
                            (SELECT min(id) FROM usercredentials.organisations),
                            :slug, :name, :description, :category, :resolver_key,
                            :entity_type, TRUE, TRUE, :active_org_ids,
                            'DOCUMENT', :page_size, :orientation, :output_format, FALSE
                        ) RETURNING id;
                    """),
                    {
                        "slug": tpl["slug"],
                        "name": tpl["name"],
                        "description": tpl["description"],
                        "category": tpl["category"],
                        "resolver_key": tpl["resolver_key"],
                        "entity_type": tpl["entity_type"],
                        "active_org_ids": all_org_ids,
                        "page_size": tpl["page_size"],
                        "orientation": tpl["orientation"],
                        "output_format": tpl["output_format"],
                    }
                )
                template_id = result.scalar()

                # Insert Version 1 as PUBLISHED
                v_res = conn.execute(
                    text("""
                        INSERT INTO containermgmt.report_template_versions (
                            template_id, version_number, status, html_content,
                            css_content, change_notes, is_deleted
                        ) VALUES (
                            :template_id, 1, 'PUBLISHED', :html_content,
                            :css_content, 'Initial system release', FALSE
                        ) RETURNING id;
                    """),
                    {
                        "template_id": template_id,
                        "html_content": tpl["html_content"],
                        "css_content": tpl["css_content"],
                    }
                )
                version_id = v_res.scalar()

                # Link active version
                conn.execute(
                    text("""
                        UPDATE containermgmt.report_templates
                        SET active_version_id = :version_id
                        WHERE id = :template_id;
                    """),
                    {"version_id": version_id, "template_id": template_id}
                )
                logger.info(f"Seeded system report template '{tpl['slug']}' (id={template_id}, version={version_id})")
            else:
                # Ensure active_org_ids includes organizations
                template_id = existing[0]
                conn.execute(
                    text("""
                        UPDATE containermgmt.report_templates
                        SET active_org_ids = :active_org_ids
                        WHERE id = :template_id AND (active_org_ids IS NULL OR array_length(active_org_ids, 1) = 0);
                    """),
                    {"template_id": template_id, "active_org_ids": all_org_ids}
                )

    logger.info("Sourcing RFQ & Quote Comparison document templates verified.")


if __name__ == "__main__":
    ensure_sourcing_and_quote_templates_schema()
    print("Sourcing and Quote templates migration executed successfully.")
