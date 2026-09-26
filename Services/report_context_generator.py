"""
Services/report_context_generator.py
Generates downloadable, comprehensive AI Context Markdown files for external LLMs
(ChatGPT, Claude, Gemini, etc.) to produce compliant FreightLens report templates.
"""
from typing import Dict, Any, Optional
from Services.report_data_resolvers import get_resolver, ResolverDefinition


def generate_context_file(resolver_key: str) -> str:
    """Generates a complete markdown guide with schemas, examples, and rules for a given resolver."""
    resolver: ResolverDefinition = get_resolver(resolver_key)
    schema = resolver.schema_meta
    sample = resolver.sample_context

    # 1. Build Fields Table
    fields_rows = []
    for field_name, meta in schema.items():
        ftype = meta.get("type", "string")
        fdesc = meta.get("description", "-")
        fex = meta.get("example", "")
        fperm = meta.get("permission", "None" if not meta.get("restricted") else "Restricted")
        fields_rows.append(f"| `{field_name}` | {ftype} | {fdesc} | `{fex}` | {fperm} |")
        
        # Sub fields if object or array
        sub = meta.get("item_fields", {})
        for sname, smeta in sub.items():
            stype = smeta.get("type", "string")
            sdesc = smeta.get("description", f"Field of {field_name}")
            sex = smeta.get("example", "")
            sperm = smeta.get("permission", "None" if not smeta.get("restricted") else "Restricted")
            fields_rows.append(f"| `{field_name}.{sname}` (or in loop) | {stype} | {sdesc} | `{sex}` | {sperm} |")

    fields_table_md = "\n".join(fields_rows)

    # Markdown Document
    md = f"""# FreightLens Report Template — AI Developer Context
## Report Resolver: `{resolver.name}` (`{resolver.key}`)
**Category:** {resolver.category}  
**Primary Entity:** {resolver.entity_type}  
**Description:** {resolver.description}

---

## 1. System & Template Engine Overview
- **Templating Engine:** Sandboxed Jinja2 (Python)
- **PDF Renderer:** WeasyPrint (HTML+CSS to PDF compiler)
- **Paper Formats:** A4 portrait (standard: 210mm x 297mm), A4 landscape, Letter
- **Encoding:** UTF-8

When instructed to generate a FreightLens report template, you must output TWO distinct blocks:
1. **HTML Template** (pure semantic HTML5 with Jinja2 markup, no surrounding `<html>` or `<body>` tags)
2. **CSS Stylesheet** (clean, print-optimized CSS for WeasyPrint)

---

## 2. Available Data Context Fields
The following data context is passed directly to the Jinja2 template for this report:

| Field Name | Type | Description | Example Value | Access Requirement |
|---|---|---|---|---|
{fields_table_md}

---

## 3. Template Syntax & Built-in Helpers

### Jinja2 Syntax Quick Reference
- **Variable output:** `{{{{ po_number }}}}`
- **Null-safe fallback:** `{{{{ notes | default_na }}}}`
- **For loops:**
  ```jinja2
  {{% for item in items %}}
  <tr>
      <td>{{{{ loop.index }}}}</td>
      <td>{{{{ item.description }}}}</td>
      <td>{{{{ item.quantity_ordered }}}} {{{{ item.unit }}}}</td>
  </tr>
  {{% endfor %}}
  ```
- **Conditional rendering:**
  ```jinja2
  {{% if show_financials %}}
  <td class="amount">{{{{ item.total_price | format_currency(currency) }}}}</td>
  {{% endif %}}
  ```

### Available Custom Filters
- `{{{{ date_field | format_date('%d %b %Y') }}}}` → `"15 Mar 2026"`
- `{{{{ number_field | format_number(2) }}}}` → `"1,250.00"`
- `{{{{ amount_field | format_currency('USD') }}}}` → `"USD 1,250.00"`
- `{{{{ optional_text | default_na('-') }}}}` → `"-"` (if None or empty)
- `{{{{ now().strftime('%d %b %Y %H:%M') }}}}` → Current timestamp

---

## 4. PDF Layout & Styling Guidelines (WeasyPrint)
1. **Page Box:** Page margins, orientation, and running page counters are configured via `@page`:
   ```css
   @page {{
       size: A4 portrait;
       margin: 15mm 15mm 20mm 15mm;
       @top-right {{
           content: "Page " counter(page) " of " counter(pages);
           font-size: 8pt;
           color: #64748b;
       }}
   }}
   ```
2. **Repeating Table Headers:** Use standard `<thead>` and `<tbody>`. WeasyPrint automatically repeats `<thead>` across page breaks.
3. **Prevent Row Breaks:** Tables automatically break across pages, but individual rows should avoid breaking inside:
   ```css
   tr {{
       page-break-inside: avoid;
   }}
   ```
4. **Manual Page Breaks:** Use a utility class like `.page-break {{ page-break-before: always; }}`.
5. **DO NOT USE:**
   - `position: fixed` (use `@page` margin boxes instead)
   - JavaScript or `<script>` tags
   - External network font links or heavy external asset URLs

---

## 5. Security Restrictions (Strictly Enforced)
Templates will be rejected by the server validator if they contain:
- `<script>` tags or inline event handlers (`onclick`, `onerror`, `onload`, etc.)
- Python sandbox escape tokens (`__class__`, `__globals__`, `__subclasses__`, `__import__`)
- `<iframe>`, `<object>`, `<embed>`, or `<form>` tags

---

## 6. Sample Template Implementation

### HTML Snippet:
```html
<div class="report-container">
    <div class="header-section">
        <div class="company-info">
            <h2>{{{{ company.name }}}}</h2>
            <p>{{{{ company.address | default_na }}}}</p>
        </div>
        <div class="report-badge">
            <h1>{resolver.name.upper()}</h1>
            <p class="ref-no"># {{{{ po_number or defect_number or bl_number }}}}</p>
        </div>
    </div>

    <table class="data-table">
        <thead>
            <tr>
                <th style="width: 5%%;">#</th>
                <th>Description</th>
                <th style="width: 15%%; text-align: right;">Qty</th>
                {{% if show_financials %}}
                <th style="width: 18%%; text-align: right;">Total</th>
                {{% endif %}}
            </tr>
        </thead>
        <tbody>
            {{% for item in items %}}
            <tr>
                <td>{{{{ loop.index }}}}</td>
                <td>
                    <strong>{{{{ item.item_code or '' }}}}</strong>
                    <div>{{{{ item.description or item.item_description }}}}</div>
                </td>
                <td style="text-align: right;">
                    {{{{ (item.quantity_ordered or item.quantity_affected) | format_number(2) }}}} {{{{ item.unit }}}}
                </td>
                {{% if show_financials %}}
                <td style="text-align: right;">
                    {{{{ item.total_price | format_currency(currency) }}}}
                </td>
                {{% endif %}}
            </tr>
            {{% endfor %}}
        </tbody>
    </table>
</div>
```

### CSS Snippet:
```css
.report-container {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #0f172a;
}}
.header-section {{
    display: flex;
    justify-content: space-between;
    margin-bottom: 24px;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 16px;
}}
.data-table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 16px;
}}
.data-table th {{
    background: #f8fafc;
    border-bottom: 2px solid #cbd5e1;
    font-size: 8.5pt;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 8px 10px;
}}
.data-table td {{
    border-bottom: 1px solid #e2e8f0;
    padding: 8px 10px;
    font-size: 9pt;
}}
```

---

## 7. Instructions for Users
1. Copy this entire document into your AI assistant (e.g. ChatGPT, Claude, Cursor).
2. Prompt: *"Using the FreightLens schema above, please write an HTML template and CSS stylesheet for a custom report that highlights..."*
3. Copy the generated HTML into the **HTML** tab of the FreightLens Code Editor, and CSS into the **CSS** tab.
4. Click **Validate** and **Live Preview** to check formatting and render sample data.
"""
    return md
