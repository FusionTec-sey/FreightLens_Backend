# Frontend Implementation Guide

This guide details how to consume the REST API endpoints exposed by the FastAPI backend. It covers Authentication, Bill of Lading management, Container operations, and Damage Reporting.

> **CRITICAL NOTE ON FILE UPLOADS**: Many of the Container and Report endpoints require uploading files (images/documents) alongside JSON-like payload data. For these endpoints, the frontend MUST use **`FormData` (multipart/form-data)** instead of `application/json`.

---

## 1. Authentication Endpoints

All secure endpoints require a Bearer token in the `Authorization` header:
`Authorization: Bearer <access_token>`

### Login (Get Token)
- **POST** `/token`
- **Content-Type**: `application/x-www-form-urlencoded`
- **Body**:
  - `username` (string)
  - `password` (string)
- **Returns**: `{ "access_token": "...", "refresh_token": "...", "token_type": "bearer", "permissions": [...] }`

### Refresh Token
- **POST** `/refresh`
- **Content-Type**: `application/json`
- **Body**: `"<refresh_token_string>"`
- **Returns**: `{ "access_token": "...", "token_type": "bearer" }`

---

## 2. Bill of Lading (BoL) Endpoints

### Fetch Bills of Lading
- **GET** `/getBl`
- **Query Params**: `offset` (default 0), `limit` (default 500), `BillOfLanding`, `ConsigneeName`, `Vessel`, `sort_by_arrival` (boolean)
- **Returns**: Paginated list `{"total_count": X, "data": [ { ...bl_details, containers: [...] } ] }`

### Add a Bill of Lading
- **POST** `/addBl`
- **Content-Type**: `application/json`
- **Payload Fields**:

| Field | Type | Required | Description |
|---|---|---|---|
| `BillOfLanding` | string | ✅ | Unique BoL identifier |
| `Consignee` | int | ❌ | Consignee ID |
| `Vessel` | int | ❌ | Vessel ID |
| `ArrivalDate` | datetime string | ✅ | ISO format e.g. `2024-01-15T00:00:00` |
| `Supplier` | int | ❌ | Supplier ID |
| `Provider` | int | ❌ | Logistics Provider ID |
| `Doc` | int | ❌ | Shipping Document type ID |
| `FreeDays` | int | ❌ | Default free days for all containers under this BoL |
| `status` | int | ❌ | Default status ID for all containers under this BoL |
| `new_containers` | array | ❌ | List of container objects to create along with the BoL |

**Example Payload:**
```json
{
    "BillOfLanding": "MAEU123456",
    "Consignee": 1,
    "Vessel": 2,
    "ArrivalDate": "2024-06-01T00:00:00",
    "FreeDays": 14,
    "status": 1,
    "new_containers": [
        { "container_no": "CONT001", "type": 1 },
        { "container_no": "CONT002", "type": 1 }
    ]
}
```
> **Note**: All containers in `new_containers` will inherit `FreeDays` and `status` from the BoL if not individually specified.

### Update a Bill of Lading
- **POST** `/updateBl/{bl_number}`
- **Content-Type**: `application/json`
- **Payload Fields**: Same as Add BoL, except `BillOfLanding` is in the URL path (not the body).

> **⚠️ FreeDays & Status Conflict Rules** — See the [Frontend Logic Guide](./frontend_logic_guide.md) for how to handle syncing and UI restrictions.

---

## 3. Container Management

### Fetch Containers
- **GET** `/getContainerDetails`
- **Query Params**: `offset`, `limit`, `container_id`, `container_no`, `status`, `from_date`, `to_date`, `order_by_arrival`
- **Returns**: Paginated list `{"total_count": X, "data": [...]}`
- Each container object in `data` includes:
  ```json
  {
    "Container_ID": 1,
    "container_no": "CONT001",
    "status": 1,
    "FreeDays": 14,
    "bill_of_landing": {
      "ArrivalDate": "2024-06-01T00:00:00",
      "FreeDays": 14,
      "status": 1,
      "ExcludingDay": 2,
      ...
    }
  }
  ```
  > `FreeDays` and `status` in the container object reflect **the individual container's values**, which may differ from the BoL values if they were overridden.

### Create Container
- **POST** `/createContainer`
- **Content-Type**: `multipart/form-data`
- **Payload Fields** (append to `FormData`):

| Field | Type | Required | Description |
|---|---|---|---|
| `container_no` | string | ✅ | Container number |
| `bill_of_landing.BillOfLanding` | string | ✅ | Parent BoL number |
| `bill_of_landing.ArrivalDate` | datetime string | ❌ | ISO datetime |
| `bill_of_landing.FreeDays` | int | ❌ | Sets/updates the BoL FreeDays |
| `bill_of_landing.status` | int | ❌ | Sets/updates the BoL status |
| `FreeDays` | int | ❌ | Container-specific FreeDays (overrides BoL default) |
| `status` | int | ❌ | Container-specific status (overrides BoL default) |
| `type` | int | ❌ | Container type ID |
| `emptied_at` | int | ❌ | Unload venue ID |
| `tax` | int | ❌ | Tax flag |
| `PONo` | string | ❌ | PO Number |
| `in_bound` | datetime string | ❌ | Inbound date |
| `out_bound` | datetime string | ❌ | Outbound date |
| `empty_date` | date string | ❌ | Date container was emptied |
| `unloaded_at_port` | date string | ❌ | Date unloaded at port |
| `materials` | int (repeatable) | ❌ | Append multiple material IDs |
| `new_docs` | File (repeatable) | ❌ | Shipping documents |
| `inbound_images` | File (repeatable) | ❌ | Inbound container images |
| `empty_images` | File (repeatable) | ❌ | Empty container images |

**Example (JavaScript):**
```javascript
const formData = new FormData();
formData.append("container_no", "CONT001");
formData.append("bill_of_landing.BillOfLanding", "MAEU123456");
formData.append("bill_of_landing.FreeDays", 14);  // Sets BoL FreeDays
formData.append("bill_of_landing.status", 1);     // Sets BoL status
formData.append("FreeDays", 14);  // Optional: explicit container value
formData.append("status", 1);    // Optional: explicit container value
```

### Update Container
- **POST** `/updateContainer/{container_id}`
- **Content-Type**: `multipart/form-data`
- **Payload Fields**: Same as Create Container, plus:
  - `remove_doc_ids` (int, repeatable): IDs of documents to delete from the server.

> **⚠️ FreeDays & Status Conflict Rules** — see Section 5 below.

### Delete Container
- **DELETE** `/deleteContainerDetails/{container_id}`

### Fetch Document/Image File
- **GET** `/getDocument/{doc_id}`
- **Returns**: Rendered file as `application/octet-stream` or appropriate MIME type. Use this URL in `<img>` tags or download links.

---

## 4. Damage Reporting

### Fetch Report List
- **GET** `/getContainerReports`
- **Returns**: `{ "column": [...], "data": [[report_id, container_no], ...] }`

### Fetch Detailed Report By ID
- **GET** `/getDamageReportById/{report_id}`
- **Returns**:
  ```json
  {
      "report_id": 1,
      "container_number": "CONT123",
      "products": [
          {
              "id": 10,
              "name": "Tile",
              "quantity": 5,
              "reason": "Cracked",
              "files": [{ "id": 1, "filename": "img.jpg" }]
          }
      ]
  }
  ```

### Submit New Damage Report
- **POST** `/submitDamagedProducts`
- **Content-Type**: `multipart/form-data`
- **Payload**:
  - `data` (Stringified JSON): `{"container_id": 1, "products": [{"name": "Tile", "quantity": 5, "reason": "Broken", "files": [{}, {}]}]}`
    *Note: The frontend must track the number of files per product in the JSON, then append actual File objects to the FormData sequentially.*
  - `files`: File objects (appended sequentially matching the order in the JSON).

### Update Damage Report
- **POST** `/updateDamagedProducts/{report_id}`
- **Content-Type**: `multipart/form-data`
- **Payload**: Same as submit. Supports `remove_doc_ids` and `remove_product_ids` to delete entries.

---

## 5. FreeDays & Status — Cascade & Conflict Rules

Both `FreeDays` and `status` follow identical logic at two levels: the **Bill of Lading (BoL)** and the **individual Container**.

### How Inheritance Works (on Create)
When a new container is created **without** an explicit `FreeDays` or `status`, the backend automatically sets those values from the parent BoL:

```
BoL.FreeDays = 14  →  Container.FreeDays = 14  (auto-inherited)
BoL.status = 1     →  Container.status = 1     (auto-inherited)
```

To **override** at creation, simply include `FreeDays` or `status` in the container's form fields.

### How Cascade Works (on BoL Update)
When the BoL's `FreeDays` or `status` is changed via `bill_of_landing.FreeDays` / `bill_of_landing.status` in the Update Container endpoint, the backend:
1. Fetches all containers under that BoL.
2. If **all** containers share the same value as the BoL's **current** value → accepts the update and **cascades** the new value to all containers.
3. If **any** container has a different value (custom override) → **rejects** the update with `HTTP 409 Conflict`.

### Conflict Response
```json
HTTP 409 Conflict
{
  "detail": "Cannot update Bill of Lading FreeDays: One or more containers have custom FreeDays. Please update individual containers instead."
}
```
Or for status:
```json
HTTP 409 Conflict
{
  "detail": "Cannot update Bill of Lading status: One or more containers have a custom status. Please update individual containers instead."
}
```

### Frontend Recommended Flow

```
1. User edits FreeDays at the BoL level
       │
       ▼
2. PATCH /updateContainer/{any_container_id}
   with body: { "bill_of_landing.FreeDays": 21 }
       │
       ├── ✅ No conflicts → all containers updated, BoL updated
       │
       └── ❌ HTTP 409 → Show user:
              "Some containers have custom FreeDays.
               Update them individually first, or
               reset all containers to the BoL value."
```

> **Tip**: To let the user force-reset all containers back to the BoL value when a conflict exists, first update each individual container's `FreeDays` / `status` to match the old BoL value, then update the BoL value. This clears all custom overrides.
