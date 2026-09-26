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

All files for all organisations go into this bucket.
Tenant isolation is enforced by the `org_id` filter on `order_documents` records — not by separate buckets.

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
The hash is the first 12 characters of the file content hash.

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
2. Verify the document belongs to an order with `org_id == current_user.org_id`.
3. If not found or org mismatch: return 404.
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
    contents = await file.read()
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    file_hash = hashlib.md5(contents).hexdigest()[:12]
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin"
    object_key = f"orders/{order.po_number}/po_documents/{ts}_{file_hash}.{ext}"

    blob_storage.upload_file(
        file_obj=io.BytesIO(contents),
        object_key=object_key,
        content_type=file.content_type
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
