from types import SimpleNamespace

import pytest

from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.db import _reject_missing_org_ids


def test_before_flush_rejects_tenant_model_without_org_id():
    session = SimpleNamespace(new=[PurchaseOrder(po_number="PO-TEST")])

    with pytest.raises(ValueError, match="PurchaseOrder"):
        _reject_missing_org_ids(session, None, None)


def test_before_flush_accepts_explicit_org_id():
    session = SimpleNamespace(new=[PurchaseOrder(po_number="PO-TEST", org_id=42)])

    _reject_missing_org_ids(session, None, None)
