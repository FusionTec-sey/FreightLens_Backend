"""One scoped projection for per-draft holds and the overdue follow-up inbox."""
from sqlalchemy import func
from Model.containermgmt.Inventory.SalesReservationSource import SalesReservationSource
from Model.containermgmt.Inventory.StockLedger import StockReservation, StockBalance
from Model.containermgmt.Inventory.ReservationDeadline import ReservationDeadline
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision
from Model.containermgmt.Orders.Product import Product
from Services.sales_reservation_source_service import owned


def reservation_sources_page(db, context, *, page, limit, document_key=None, due_only=False, branch_id=None):
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Company denied')
    if page < 1 or limit < 1 or limit > 100: raise ValueError('Invalid reservation page')
    if document_key is not None and owned(db, SalesIntent, context).filter_by(document_key=document_key).first() is None:
        raise LookupError('Sales draft not found')
    deadline = owned(db, ReservationDeadline, context).filter(ReservationDeadline.reservation_key == StockReservation.reservation_key)
    date_query = deadline.with_entities(ReservationDeadline.review_at).order_by(ReservationDeadline.version.desc()).limit(1).correlate(StockReservation).scalar_subquery()
    version_query = deadline.with_entities(ReservationDeadline.version).order_by(ReservationDeadline.version.desc()).limit(1).correlate(StockReservation).scalar_subquery()
    review_date = func.coalesce(date_query, StockReservation.review_at)
    due = (review_date <= func.now()) & (StockReservation.quantity > StockReservation.released)
    latest_version = owned(db, SalesIntentRevision, context).filter(SalesIntentRevision.document_key == SalesReservationSource.document_key).with_entities(
        func.max(SalesIntentRevision.version)).correlate(SalesReservationSource).scalar_subquery()
    query = owned(db, SalesReservationSource, context).join(StockReservation,
        (StockReservation.org_id == SalesReservationSource.org_id) & (StockReservation.reservation_key == SalesReservationSource.reservation_key)
    ).join(StockBalance, (StockBalance.org_id == StockReservation.org_id) & (StockBalance.id == StockReservation.balance_id)
    ).join(SalesIntent, (SalesIntent.org_id == SalesReservationSource.org_id) & (SalesIntent.document_key == SalesReservationSource.document_key)
    ).join(Product, (Product.org_id == StockBalance.org_id) & (Product.id == StockBalance.product_id)
    ).join(InventoryBranch, (InventoryBranch.org_id == StockBalance.org_id) & (InventoryBranch.id == StockBalance.branch_id)
    ).join(StockLocation, (StockLocation.org_id == StockBalance.org_id) & (StockLocation.id == StockBalance.location_id)
    ).filter(StockReservation.is_deleted.is_(False), StockBalance.is_deleted.is_(False), SalesIntent.is_deleted.is_(False),
        Product.is_deleted.is_(False), InventoryBranch.is_deleted.is_(False), StockLocation.is_deleted.is_(False))
    if document_key is not None: query = query.filter(SalesReservationSource.document_key == document_key)
    # Reviewed dates only move forward, so the original indexed deadline is a
    # safe prefilter before checking current history. Future holds cannot be due.
    if due_only: query = query.filter(StockReservation.review_at <= func.now(), due)
    if branch_id is not None: query = query.filter(StockBalance.branch_id == branch_id)
    total = query.count()
    # Only public labels are selected, never Product's eager supplier relationships.
    rows = query.with_entities(SalesReservationSource.document_key, SalesReservationSource.line_key,
        StockReservation.reservation_key, StockReservation.quantity, StockReservation.released,
        (StockReservation.quantity-StockReservation.released).label('remaining'), StockBalance.product_id,
        Product.name.label('product_name'), StockBalance.location_id, StockLocation.name.label('location_name'),
        StockBalance.branch_id, InventoryBranch.name.label('branch_name'), StockBalance.base_unit,
        latest_version.label('source_version'), review_date.label('review_at'), func.coalesce(version_query, 0).label('deadline_version'), due.label('review_due')
    ).order_by(review_date, StockReservation.id).offset((page-1)*limit).limit(limit).all()
    items = []
    for row in rows:
        item = row._asdict()
        item.update(held_quantity=str(item.pop('quantity')), released_before=str(item.pop('released')), remaining_quantity=str(item.pop('remaining')))
        items.append(item)
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total+limit-1)//limit))
