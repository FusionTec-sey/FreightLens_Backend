from types import SimpleNamespace

from Routes.Orders.order_serialization import order_to_dict


def _order(**overrides):
    values = {
        "id": 10,
        "po_number": "PO-10",
        "po_nce": "NCE-10",
        "request_id": None,
        "store_request": None,
        "supplier_id": 20,
        "supplier_rel": SimpleNamespace(name="Supplier A"),
        "company": "Supplier A",
        "goods_description": "Test goods",
        "material_ids": [],
        "org_id": 1001,
        "status_id": 1,
        "status": "DRAFT",
        "status_label": "Draft",
        "order_status_rel": None,
        "lifecycle_stage": "DRAFT",
        "lifecycle_version": 1,
        "stage_version": 1,
        "lifecycle_locked": False,
        "selected_quote_id": 30,
        "payment_status": "NONE",
        "production_status": "NOT_STARTED",
        "shipment_status": "NOT_SHIPPED",
        "receipt_status": "PENDING",
        "total_amount": 1000,
        "advance_amount": 200,
        "balance_amount": 800,
        "currency": "USD",
        "doc_type": "PO",
        "parent_rfq_id": None,
        "origin_rfq_number": None,
        "split_index": None,
        "child_pos": [],
        "sheet_type": None,
        "consignee": None,
        "year": 2026,
        "urgent_action": False,
        "order_mail_date": None,
        "quote_sent_date": None,
        "quote_received_date": None,
        "pi_confirmed_date": None,
        "payment_date": None,
        "balance_payment_date": None,
        "eta_date": None,
        "freight_type": "Sea Freight",
        "remark": None,
        "created_at": None,
        "items": [],
        "shipments": [],
        "payments": [],
        "documents": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_rfq_serialization_redacts_supplier_and_financial_data():
    result = order_to_dict(_order(doc_type="RFQ"), is_accounts=True, can_view_supplier=True)

    assert result["company"] is None
    assert result["supplier"] is None
    assert result["total_amount"] is None
    assert result["selected_quote_id"] is None
    assert result["payments"] == []


def test_authorized_po_serialization_keeps_supplier_and_financial_data():
    result = order_to_dict(_order(), is_accounts=True, can_view_supplier=True)

    assert result["company"] == "Supplier A"
    assert result["supplier"] == 20
    assert result["total_amount"] == 1000.0
    assert result["advance_amount"] == 200.0
    assert result["balance_amount"] == 800.0


def test_non_financial_po_serialization_redacts_amounts():
    result = order_to_dict(_order(), is_accounts=False, can_view_supplier=True)

    assert result["company"] == "Supplier A"
    assert result["total_amount"] is None
    assert result["advance_amount"] is None
    assert result["balance_amount"] is None
