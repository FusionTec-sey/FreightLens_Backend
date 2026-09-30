# Object Storage Rules (RustFS / S3)

## Storage Service

All file operations go through `Utils/blob_storage.py`.

Never:
- Save uploaded files to the local filesystem.
- Import `boto3` or `minio` directly in a route or model.
- Construct presigned URLs outside of `blob_storage.py`.

Always:
- Use `blob_storage.upload_file()`, `blob_storage.download_file()`, `blob_storage.delete_file()`.
- Use the object key naming conventions below.

---

## Bucket

Single bucket: `containermgmt-blobs`

All files for all organisations go into this bucket. Tenant isolation is enforced by
the authenticated owning endpoint and an organisation-scoped database record, not by
separate buckets or by an unverified object key.

Direct media reads must use short-lived application signatures. Operational documents
must only be read through authenticated owning-resource endpoints. Never expose a
stable public object URL.

---

## Object Key Naming Conventions

Object keys encode the context of the file. Follow this structure precisely:

### Order Documents
```
orders/{po_number}/po_documents/{timestamp}_{hash}.{ext}
```
Example: `orders/PO-2026-0007-A/po_documents/20260923114757_fd988f0943b1.pdf`

### Payment Proof (Swift slips, bank confirmations)
```
orders/{po_number}/payments/pay_{payment_id}_{payment_type}/{timestamp}_{hash}.{ext}
```
Example: `orders/PO-2026-0007-A/payments/pay_20_ADVANCE/20260923114757_fd988f0943b1.pdf`

### Vendor Quotations (attached to RFQ)
```
rfqs/{rfq_number}/vendor_quotes/v{supplier_id}/{timestamp}_{hash}.{ext}
```
Example: `rfqs/RFQ-2026-0003/vendor_quotes/v42/20260923130000_ab123def.pdf`

### Product Images
```
products/images/{timestamp}_{hash}.{ext}
```

### Product Videos
```
products/videos/{timestamp}_{hash}.{ext}
```

### Container Documents
```
containers/{container_no}/documents/{timestamp}_{hash}.{ext}
```

### General rule for new file categories
```
{entity_type}/{entity_identifier}/{document_category}/{timestamp}_{hash}.{ext}
```

The timestamp format is `YYYYMMDDHHMMSS`.
The generated suffix is a collision-resistant identifier owned by `blob_storage`.
Callers provide a validated folder and the original filename, not a complete object key.

---

## Document Database Records

Every uploaded file is tracked in `containermgmt.order_documents`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Generated via `gen_random_uuid()` — never integer |
| `order_id` | Integer FK | PO or RFQ the document belongs to |
| `payment_id` | Integer FK nullable | If this doc is a payment proof |
| `vendor_quote_id` | Integer FK nullable | If this doc is a vendor quotation |
| `document_type` | varchar | See document types below |
| `file_url` | text | RustFS object key (relative, not full URL) |
| `original_filename` | text | Original user-uploaded filename |
| `file_size` | bigint | Bytes |
| `content_type` | varchar | MIME type |

### Document types (current)
- `contract` — signed purchase contracts
- `proforma` — proforma invoices
- `po_document` — general PO documents
- `payment_proof` — Swift MT103, bank transfer confirmation
- `quotation` — vendor quotation sheets submitted to RFQ
- `packing_list` — supplier packing list PDF

---

## Download Security

Download endpoints use UUID:
```
GET /orders/documents/{document_id}/download
```

The `document_id` is a UUID string — never an integer.

Before streaming the file:
1. Look up the document record by UUID.
2. Verify the owning order through `get_org_context` and `apply_org_filter`.
3. Scope the owning order with `apply_org_filter`; if not found, return 404.
4. Stream the file from RustFS using `blob_storage.download_file(doc.file_url)`.

---

## Backward Compatibility

Legacy documents created before the UUID migration may have integer IDs as strings.
The download endpoint must handle both:

```python
try:
    uuid.UUID(document_id)  # Valid UUID
    doc = db.query(OrderDocument).filter(OrderDocument.id == document_id).first()
except ValueError:
    # Legacy integer ID
    try:
        legacy_id = int(document_id)
        doc = db.query(OrderDocument).filter(OrderDocument.legacy_id == legacy_id).first()
    except ValueError:
        raise HTTPException(404, "Invalid document identifier")
```

---

## Upload Flow

Standard pattern for accepting a file upload and recording it:

```python
from Utils.blob_storage import blob_storage
from datetime import datetime
import hashlib

async def upload_document(file: UploadFile, order, payment_id=None):
    folder = f"orders/{order.po_number}/po_documents"
    object_key = blob_storage.upload_file(
        file_obj=file,
        folder=folder,
        original_filename=file.filename,
    )

    doc = OrderDocument(
        order_id=order.id,
        payment_id=payment_id,
        document_type="po_document",
        file_url=object_key,
        original_filename=file.filename,
        file_size=len(contents),
        content_type=file.content_type,
    )
    db.add(doc)
    db.commit()
    return doc
```

`Utils.blob_storage._safe_key` must validate every caller-provided folder or object key.
Do not bypass it, import `boto3` in a route, or build a local filesystem path directly.
