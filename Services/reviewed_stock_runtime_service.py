"""Server-owned scope for reviewed stock execution, never an approval bypass."""
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Services.manager_case_service import CaseBinding
from Services.sales_reservation_source_service import owned
from Services.stock_runtime_service import local_stock_runtime


def reviewed_stock_scope(db, context, key, *, action, source_type):
    case = owned(db, ManagerCase, context).filter_by(case_key=key,
        action=action, source_type=source_type).one_or_none()
    if case is None: raise LookupError('Case not found')
    binding = CaseBinding(**case.binding)
    balance = owned(db, StockBalance, context).filter_by(id=binding.details['balance_id']).one_or_none()
    if balance is None: raise LookupError('Stock not found')
    authority = local_stock_runtime().claim_for(db, context, balance.branch_id)
    return binding, balance, authority
