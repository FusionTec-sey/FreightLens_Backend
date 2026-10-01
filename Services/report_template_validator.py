"""
Services/report_template_validator.py
Validates customer-configurable report templates for security (SSTI, XSS, resource exhaustion)
and Jinja2 syntax correctness before saving or rendering.
"""
import re
import logging
from html import unescape
from typing import Tuple, List, Optional
from jinja2 import Environment
from jinja2.sandbox import SandboxedEnvironment
from jinja2.exceptions import TemplateSyntaxError

logger = logging.getLogger("containerMgmt.report_validator")

# Maximum size thresholds (bytes)
MAX_HTML_BYTES = 512 * 1024   # 500 KB
MAX_CSS_BYTES = 100 * 1024    # 100 KB

# Forbidden tokens that could lead to Python SSTI sandbox escape
FORBIDDEN_SSTI_PATTERNS = [
    r"__class__",
    r"__mro__",
    r"__subclasses__",
    r"__bases__",
    r"__globals__",
    r"__builtins__",
    r"__import__",
    r"__init__",
    r"\bimport\s+",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bos\.",
    r"\bsys\.",
    r"\bsubprocess\b",
]

# Forbidden HTML / XSS / script tokens
FORBIDDEN_HTML_PATTERNS = [
    (r"<\s*script\b[^>]*>", "Script tags (<script>) are strictly forbidden in report templates."),
    (r"javascript\s*:", "Inline JavaScript URLs ('javascript:') are forbidden."),
    (r"\bon\w+\s*=", "Inline JavaScript event handlers (e.g. onclick, onerror, onload) are forbidden."),
    (r"<\s*iframe\b[^>]*>", "Embedded iframes (<iframe>) are forbidden."),
    (r"<\s*object\b[^>]*>", "Embedded objects (<object>) are forbidden."),
    (r"<\s*embed\b[^>]*>", "Embedded plugins (<embed>) are forbidden."),
    (r"<\s*form\b[^>]*>", "Interactive forms (<form>) are forbidden in print templates."),
]


def validate_template(
    html_content: str,
    css_content: Optional[str] = None,
    header_html: Optional[str] = None,
    footer_html: Optional[str] = None,
    resolver_key: Optional[str] = None,
) -> Tuple[bool, List[str], List[str]]:
    """
    Validates HTML and CSS template snippets.
    Returns:
        (is_valid: bool, errors: List[str], warnings: List[str])
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not html_content or not html_content.strip():
        errors.append("HTML content cannot be empty.")
        return False, errors, warnings

    # 1. Size checks
    html_size = len(html_content.encode("utf-8"))
    if html_size > MAX_HTML_BYTES:
        errors.append(f"HTML content exceeds maximum allowed size of {MAX_HTML_BYTES // 1024} KB (Current: {html_size // 1024} KB).")

    if css_content:
        css_size = len(css_content.encode("utf-8"))
        if css_size > MAX_CSS_BYTES:
            errors.append(f"CSS content exceeds maximum allowed size of {MAX_CSS_BYTES // 1024} KB (Current: {css_size // 1024} KB).")

    # 2. SSTI Pattern Scans across all text fragments
    all_content = unescape(
        f"{html_content}\n{css_content or ''}\n{header_html or ''}\n{footer_html or ''}"
    )
    for pat in FORBIDDEN_SSTI_PATTERNS:
        match = re.search(pat, all_content, re.IGNORECASE)
        if match:
            errors.append(f"Security restriction: Forbidden SSTI token or pattern detected: '{match.group(0)}'.")

    # 3. HTML/XSS tag scans
    for pat, msg in FORBIDDEN_HTML_PATTERNS:
        if re.search(pat, unescape(html_content), re.IGNORECASE):
            errors.append(msg)
        if header_html and re.search(pat, unescape(header_html), re.IGNORECASE):
            errors.append(f"In header: {msg}")
        if footer_html and re.search(pat, unescape(footer_html), re.IGNORECASE):
            errors.append(f"In footer: {msg}")

    # 4. CSS Quality & Layout warnings
    if css_content:
        if "position: fixed" in css_content.lower():
            warnings.append("Using 'position: fixed' in WeasyPrint CSS can cause page overlap. Use @page margins or margin boxes for repeating headers/footers.")
        unsafe_css_url = re.search(
            r"url\s*\(\s*['\"]?(?!data:|asset:)[^)]+",
            unescape(css_content),
            re.IGNORECASE,
        )
        if unsafe_css_url:
            errors.append("CSS resource URLs must use the approved data: or asset: scheme.")

    # 5. Jinja2 Syntax Validation
    sandbox = SandboxedEnvironment()

    def _check_jinja(snippet: str, label: str):
        try:
            sandbox.parse(snippet)
        except TemplateSyntaxError as e:
            errors.append(f"Jinja2 Syntax Error in {label} at line {e.lineno}: {e.message}")
        except Exception as e:
            errors.append(f"Template parsing failed in {label}: {str(e)}")

    _check_jinja(html_content, "Main HTML Body")
    if header_html and header_html.strip():
        _check_jinja(header_html, "Header HTML")
    if footer_html and footer_html.strip():
        _check_jinja(footer_html, "Footer HTML")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings
