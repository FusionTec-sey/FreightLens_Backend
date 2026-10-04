"""Rebuildable search projection. Financial/draft truth remains in PostgreSQL."""
import logging
from Model.containermgmt.Orders.SalesIntent import SalesIntent
from Services.sales_intent_service import scoped
from Model.containermgmt.Orders.SalesIntent import SalesIntentRevision
from Services.customer_profile_service import historical_names_for_page
from Services.search_service import init_sales_drafts_index, sync_sales_draft_document
from Utils.org_filter import OrgContext

logger = logging.getLogger('containerMgmt.sales.search')


def project_sales_draft(db, context, key, *, authorize):
    """Read latest committed revision, not a potentially old replay receipt."""
    try:
        authorize(db)
        if context.org_id not in context.allowed_org_ids:
            return False
        row = scoped(db, SalesIntentRevision, context, key).order_by(
            SalesIntentRevision.version.desc()).first()
        if row is None:
            return False
        names = historical_names_for_page(db, context,
            [(row.customer_key, row.customer_version)], authorize=authorize)
        return sync_sales_draft_document(dict(id=str(key), org_id=context.org_id,
            branch_id=row.branch_id, version=row.version,
            customer_name=names.get((row.customer_key, row.customer_version)) or ''))
    except Exception:
        # A search failure must not turn an acknowledged save into an uncertain save.
        logger.warning('Sales search projection needs repair; draft data retained')
        return False


def bulk_index_sales_drafts(db):
    """Startup/admin repair; bounded keyset pages, never a public cross-org API."""
    if not init_sales_drafts_index():
        return False
    after = None
    while True:
        query = db.query(SalesIntent.document_key, SalesIntent.org_id).filter(
            SalesIntent.is_deleted.is_(False))
        if after is not None:
            query = query.filter(SalesIntent.document_key > after)
        rows = query.order_by(SalesIntent.document_key).limit(100).all()
        if not rows:
            return True
        for row in rows:
            context = OrgContext(current_org_id=row.org_id, allowed_org_ids=[row.org_id],
                                 selected_org_id=row.org_id, is_root=False)
            if not project_sales_draft(db, context, row.document_key, authorize=lambda session: None):
                return False
        after = rows[-1].document_key
