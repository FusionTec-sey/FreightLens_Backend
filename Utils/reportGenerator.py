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
