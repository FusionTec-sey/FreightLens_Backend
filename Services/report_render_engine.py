"""
Services/report_render_engine.py
Sandboxed Jinja2 rendering engine and WeasyPrint PDF compilation pipeline.
Executes templates within an ImmutableSandboxedEnvironment with strict helper functions.
"""
import logging
from typing import Dict, Any, Callable, Optional
from datetime import datetime, date
from decimal import Decimal
from urllib.parse import unquote, urlparse

import nh3
import weasyprint
from jinja2.sandbox import SandboxedEnvironment
from jinja2 import Undefined

logger = logging.getLogger("containerMgmt.report_render_engine")

SAFE_HTML_TAGS = set(nh3.ALLOWED_TAGS) | {"main", "section"}
SAFE_HTML_ATTRIBUTES = {
    tag: set(attributes) | {"class", "id", "style", "title"}
    for tag, attributes in nh3.ALLOWED_ATTRIBUTES.items()
}
SAFE_HTML_ATTRIBUTES["*"] = {"class", "id", "style", "title"}
SAFE_HTML_ATTRIBUTES["img"] = SAFE_HTML_ATTRIBUTES.get("img", set()) | {
    "src", "alt", "width", "height"
}
SAFE_URL_SCHEMES = {"asset", "data"}
BLOCKED_HTML_TAGS = {"script", "iframe", "object", "embed", "form"}


# ── Helper filters & formatters ──────────────────────────────────────────────

def format_date_filter(val: Any, fmt: str = "%d %b %Y") -> str:
    if not val or isinstance(val, Undefined):
        return "-"
    if isinstance(val, (datetime, date)):
        return val.strftime(fmt)
    if isinstance(val, str):
        try:
            # Handle ISO formatted strings
            cleaned = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt.strftime(fmt)
        except Exception:
            return val
    return str(val)


def format_number_filter(val: Any, decimals: int = 2) -> str:
    if val is None or val == "" or isinstance(val, Undefined):
        return "-"
    try:
        num = float(val)
        return f"{num:,.{decimals}f}"
    except (ValueError, TypeError, Exception):
        return str(val)


def format_currency_filter(val: Any, currency: str = "USD", decimals: int = 2) -> str:
    if val is None or val == "" or isinstance(val, Undefined):
        return "-"
    try:
        num = float(val)
        return f"{currency} {num:,.{decimals}f}"
    except (ValueError, TypeError, Exception):
        return str(val)


def default_na_filter(val: Any, placeholder: str = "-") -> str:
    if val is None or val == "" or isinstance(val, Undefined) or str(val).strip() == "":
        return placeholder
    return str(val)


def get_sandboxed_env() -> SandboxedEnvironment:
    """Configures a sandboxed Jinja2 environment with safe helpers and strict attribute access."""
    env = SandboxedEnvironment(autoescape=True)
    env.filters["format_date"] = format_date_filter
    env.filters["format_number"] = format_number_filter
    env.filters["format_currency"] = format_currency_filter
    env.filters["default_na"] = default_na_filter
    env.globals["now"] = datetime.utcnow
    return env


def sanitize_html_fragment(fragment: Optional[str]) -> Optional[str]:
    """Remove executable markup and external resource URLs from rendered fragments."""
    if not fragment:
        return fragment
    return nh3.clean(
        fragment,
        tags=SAFE_HTML_TAGS,
        attributes=SAFE_HTML_ATTRIBUTES,
        clean_content_tags=BLOCKED_HTML_TAGS,
        url_schemes=SAFE_URL_SCHEMES,
        generic_attribute_prefixes={"data-", "aria-"},
        url_relative="deny",
        link_rel=None,
    )


def build_safe_url_fetcher(
    asset_loader: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Callable[[str], Dict[str, Any]]:
    """Create a deny-by-default WeasyPrint fetcher for inline and scoped assets."""
    def safe_url_fetcher(url: str) -> Dict[str, Any]:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme == "data":
            return weasyprint.default_url_fetcher(url)
        if scheme == "asset" and asset_loader is not None:
            asset_key = unquote(f"{parsed.netloc}{parsed.path}").lstrip("/")
            if not asset_key or ".." in asset_key.split("/"):
                raise ValueError("Invalid report asset key")
            return asset_loader(asset_key)
        raise ValueError(f"Blocked report resource URL scheme: {scheme or 'relative'}")

    return safe_url_fetcher


# ── Document Assembly & Rendering ────────────────────────────────────────────

BASE_PRINT_CSS = """
@page {
    size: __PAGE_SIZE__ __ORIENTATION__;
    margin: 15mm 15mm 18mm 15mm;
    @top-right {
        content: "Page " counter(page) " of " counter(pages);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 8pt;
        color: #64748b;
    }
    @top-center {
        content: element(report-header);
    }
    @bottom-center {
        content: element(report-footer);
    }
}

.report-header {
    position: running(report-header);
}

.report-footer {
    position: running(report-footer);
}

*, *::before, *::after {
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 9.5pt;
    line-height: 1.4;
    color: #1e293b;
    background: #ffffff;
    margin: 0;
    padding: 0;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}

table {
    width: 100%;
    border-collapse: collapse;
    page-break-inside: auto;
}

tr {
    page-break-inside: avoid;
    page-break-after: auto;
}

thead {
    display: table-header-group;
}

tfoot {
    display: table-footer-group;
}

th, td {
    padding: 6px 8px;
    text-align: left;
    vertical-align: top;
}

.no-break {
    page-break-inside: avoid;
}

.page-break {
    page-break-before: always;
}
"""


def build_full_html(
    html_body: str,
    css_content: Optional[str] = None,
    header_html: Optional[str] = None,
    footer_html: Optional[str] = None,
    page_size: str = "A4",
    orientation: str = "portrait",
) -> str:
    """Wraps body, styles, and headers into an assembled HTML5 document for WeasyPrint."""
    base_css = (
        BASE_PRINT_CSS
        .replace("__PAGE_SIZE__", page_size or "A4")
        .replace("__ORIENTATION__", orientation or "portrait")
    )
    user_css = css_content or ""

    header_block = f'<header class="report-header">{header_html}</header>' if header_html else ""
    footer_block = f'<footer class="report-footer">{footer_html}</footer>' if footer_html else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Report</title>
    <style>
        {base_css}
        {user_css}
    </style>
</head>
<body>
    {header_block}
    <main class="report-content">
        {html_body}
    </main>
    {footer_block}
</body>
</html>"""


def render_html_document(
    html_template: str,
    context: Dict[str, Any],
    css_content: Optional[str] = None,
    header_template: Optional[str] = None,
    footer_template: Optional[str] = None,
    page_size: str = "A4",
    orientation: str = "portrait",
) -> str:
    """Renders Jinja2 templates into a complete HTML string using sandboxed environment."""
    env = get_sandboxed_env()

    body_tmpl = env.from_string(html_template)
    rendered_body = sanitize_html_fragment(body_tmpl.render(context))

    rendered_header = None
    if header_template and header_template.strip():
        hdr_tmpl = env.from_string(header_template)
        rendered_header = sanitize_html_fragment(hdr_tmpl.render(context))

    rendered_footer = None
    if footer_template and footer_template.strip():
        ftr_tmpl = env.from_string(footer_template)
        rendered_footer = sanitize_html_fragment(ftr_tmpl.render(context))

    return build_full_html(
        html_body=rendered_body,
        css_content=css_content,
        header_html=rendered_header,
        footer_html=rendered_footer,
        page_size=page_size,
        orientation=orientation,
    )


def compile_pdf_from_html(
    full_html: str,
    asset_loader: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> bytes:
    """Compiles a complete HTML string into a PDF binary byte stream using WeasyPrint."""
    try:
        html_doc = weasyprint.HTML(
            string=full_html,
            url_fetcher=build_safe_url_fetcher(asset_loader),
        )
        pdf_bytes = html_doc.write_pdf()
        return pdf_bytes
    except Exception as e:
        logger.error("WeasyPrint PDF compilation failed: %s", e)
        raise RuntimeError(f"PDF compilation error: {str(e)}")
