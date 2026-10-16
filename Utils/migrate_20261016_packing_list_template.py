import logging
import os

from sqlalchemy.orm import Session

from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Model.containermgmt.Report.ReportTemplateVersion import ReportTemplateVersion
from Model.containermgmt.Report.ReportTemplateAssignment import ReportTemplateAssignment
from Model.Credentials.Organisation import Organisation

logger = logging.getLogger("containerMgmt.migrations")

SLUG = "packing_list"

# The built-in layout, seeded as a system template so Print has something to
# render from on day one and the design is editable in the designer rather
# than locked in Python. The file stays the source of the default; once a
# tenant edits it they are on their own version, which is the point.
TEMPLATE_PATH = os.path.join("templates", "report", "packing_list.html")


def _body_and_css() -> tuple:
    with open(TEMPLATE_PATH, encoding="utf-8") as handle:
        raw = handle.read()
    # The designer edits a body and a stylesheet, not a whole document.
    css = ""
    if "<style>" in raw and "</style>" in raw:
        css = raw.split("<style>", 1)[1].split("</style>", 1)[0].strip()
    body = raw
    if "<body>" in raw and "</body>" in raw:
        body = raw.split("<body>", 1)[1].rsplit("</body>", 1)[0].strip()
    return body, css


def ensure_packing_list_template(db: Session) -> None:
    try:
        template = (
            db.query(ReportTemplate)
            .filter(ReportTemplate.slug == SLUG, ReportTemplate.is_deleted == False)
            .first()
        )
        if template:
            logger.info("Packing list template already present; leaving it alone.")
        else:
            # System templates are owned by the root organisation, as every
            # other seeded one is; the assignments below are what make them
            # reachable from each tenant.
            seeded = (
                db.query(ReportTemplate.org_id)
                .filter(ReportTemplate.is_system == True)
                .order_by(ReportTemplate.id.asc())
                .first()
            )
            fallback = db.query(Organisation.id).order_by(Organisation.id.asc()).first()
            root_org_id = (seeded or fallback)[0]
            body, css = _body_and_css()
            template = ReportTemplate(
                slug=SLUG,
                name="Packing List (standard)",
                description="The built-in packing list layout: container and seal, lines grouped by order, carton numbers, totals and signature blocks.",
                category="ORDERS",
                resolver_key="packing_list",
                entity_type="PackingList",
                is_system=True,
                is_active=True,
                template_type="DOCUMENT",
                page_size="A4",
                orientation="portrait",
                output_format="pdf",
                org_id=root_org_id,
            )
            db.add(template)
            db.flush()

            version = ReportTemplateVersion(
                template_id=template.id,
                version_number=1,
                status="PUBLISHED",
                html_content=body,
                css_content=css,
                change_notes="Seeded from the built-in layout.",
            )
            db.add(version)
            db.flush()
            template.active_version_id = version.id
            logger.info("Seeded the standard packing list template.")

        # Every organisation can print one without being asked to design it.
        org_ids = [row[0] for row in db.query(Organisation.id).all()]
        existing = {
            row[0]
            for row in db.query(ReportTemplateAssignment.org_id).filter(
                ReportTemplateAssignment.template_id == template.id
            )
        }
        added = 0
        for org_id in org_ids:
            if org_id in existing:
                continue
            db.add(ReportTemplateAssignment(
                template_id=template.id,
                org_id=org_id,
                entity_type="PackingList",
                is_active=True,
            ))
            added += 1
        db.commit()
        if added:
            logger.info("Activated the packing list template for %s organisation(s).", added)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to seed the packing list template: %s", exc)
