# FreightLens — Backend API Documentation

**Version:** 1.0  
**Base URL:** `http://<HOST_IP>:<HOST_PORT>` (default: `http://localhost:9000`)  
**Auth Scheme:** OAuth2 Bearer Token (JWT)

> All endpoints marked with 🔒 require a valid `Authorization: Bearer <access_token>` header.

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [System](#2-system)
3. [Reference Data (Info)](#3-reference-data-info)
4. [Bill of Lading](#4-bill-of-lading)
5. [Containers](#5-containers)
6. [Damage Reports](#6-damage-reports)
7. [Tracking & Integration](#7-tracking--integration)
8. [Settings & Configuration](#8-settings--configuration)
9. [User & Role Management](#9-user--role-management)
10. [Data Models](#10-data-models)
11. [Error Reference](#11-error-reference)

---

## 1. Authentication

> **Base router prefix:** `/`

---

### POST `/token`
Login and receive JWT tokens.

**Rate Limit:** 5 requests/minute per IP  
**Auth:** None

**Request:** `application/x-www-form-urlencoded`
| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | ✅ | Username |
| `password` | string | ✅ | Password |

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "permissions": ["view_container", "edit_container"]
}
```

**Errors:**
| Code | Reason |
|---|---|
| `401` | Invalid username or password |

---

### POST `/refresh`
Exchange a valid refresh token for a new access token.

**Auth:** None

**Request:** `application/json`
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiJ9..."
}
```

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer"
}
```

**Errors:**
| Code | Reason |
|---|---|
| `401` | Token expired, revoked, or invalid |

---

### POST `/logout` 🔒
Revoke the current refresh token. The user's session is ended.

**Auth:** Bearer token

**Request:** `application/json`
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiJ9..."
}
```

**Response `200 OK`:**
```json
{ "message": "Logged out successfully" }
```

---

### GET `/users/me` 🔒
Get the currently authenticated user's info and roles.

**Response `200 OK`:**
```json
{
  "username": "john",
  "roles": ["admin", "viewer"]
}
```

---

## 2. System

---

### GET `/health`
Liveness and database connectivity check. Used by load balancers and monitoring systems.

**Auth:** None

**Response `200 OK`:**
```json
{
  "status": "ok",
  "database": "connected",
  "environment": "development"
}
```

**Response `503 Service Unavailable`:**
```json
{ "detail": "Database unavailable: <error message>" }
```

---

## 3. Reference Data (Info)

> All GET (read) endpoints in this group require **no authentication**.  
> All POST (write) endpoints require 🔒 **Bearer token**.

---

### GET `/supplierDetails`
Returns list of all suppliers.

**Response:**
```json
[{ "supplier_id": 1, "name": "ABC Logistics" }]
```

---

### GET `/containerType`
Returns list of container types.

---

### GET `/unloadVenue`
Returns list of unload venues.

---

### GET `/consignee`
Returns list of consignees.

---

### GET `/shippingDocument`
Returns list of shipping document types.

---

### GET `/status`
Returns list of all container status codes and their labels.

---

### GET `/vessal`
Returns list of registered vessels.

---

### GET `/logisticsProvider`
Returns list of logistics providers.

---

### GET `/material`
Returns list of materials.

---

### POST `/setVessal` 🔒
Create a new vessel record.

**Request:** `application/json`
```json
{ "name": "MSC Diana" }
```

---

### POST `/setSupplier` 🔒
Create a new supplier.

**Request:** `application/json`
```json
{ "name": "Global Freight Co." }
```

---

### POST `/setUnloadVenue` 🔒
Create a new unload venue.

---

### POST `/setConsignee` 🔒
Create a new consignee.

---

### POST `/setContainerType` 🔒
Create a new container type.

---

### POST `/setShippingDocument` 🔒
Create a new shipping document type.

---

### POST `/setMaterial` 🔒
Create a new material.

---

### POST `/setProvider` 🔒
Create a new logistics provider.

---

### GET `/getDashboardInfo` 🔒
Returns aggregated counts for the dashboard.

**Response:**
```json
{
  "total_containers": 142,
  "in_transit": 30,
  "on_port": 50,
  "inbound": 12,
  "empty": 20,
  "complete": 25,
  "gate_pass": 5
}
```

---

### GET `/getContainerCountsByMonth/{year}` 🔒
Returns monthly container counts for a given year.

**Path Parameters:**
| Name | Type | Description |
|---|---|---|
| `year` | integer | Calendar year, e.g. `2025` |

**Response:**
```json
[
  { "month": 1, "count": 18 },
  { "month": 2, "count": 24 }
]
```

---

## 4. Bill of Lading

> **Base router prefix:** `/`

All BoL endpoints require 🔒 **Bearer token**.

---

### POST `/addBl` 🔒
Create a new Bill of Lading.

**Request:** `application/json`
```json
{
  "BillOfLanding": "MAEU123456789",
  "Supplier": 1,
  "Vessel": 2,
  "ShippingDocumentType": 1,
  "Consignee": 3,
  "ArrivalDate": "2025-06-15",
  "FreeDays": 14
}
```

**Response `200 OK`:**
```json
{ "message": "Bill of Lading added successfully", "BillOfLanding": "MAEU123456789" }
```

**Errors:**
| Code | Reason |
|---|---|
| `409` | Bill of Lading number already exists |
| `422` | Validation error |

---

### GET `/getBl` 🔒
Retrieve a paginated list of Bills of Lading with filters.

**Query Parameters:**
| Name | Type | Default | Description |
|---|---|---|---|
| `BillOfLanding` | string | — | Filter by exact BoL number |
| `Supplier` | integer | — | Filter by supplier ID |
| `ArrivalDate` | date | — | Filter by arrival date |
| `offset` | integer | `0` | Pagination offset |
| `limit` | integer | `50` | Max records (up to 1000) |

**Response `200 OK`:**
```json
{
  "total_count": 85,
  "data": [
    {
      "BillOfLanding": "MAEU123456789",
      "Supplier": "ABC Logistics",
      "Vessel": "MSC Diana",
      "ArrivalDate": "2025-06-15",
      "FreeDays": 14,
      "status": 2,
      "containers": [...]
    }
  ]
}
```

---

### POST `/updateBl/{bl_number}` 🔒
Update fields of an existing Bill of Lading.

**Path Parameters:**
| Name | Type | Description |
|---|---|---|
| `bl_number` | string | The BoL reference number |

**Request:** `application/json` — send only fields to update.
```json
{
  "ArrivalDate": "2025-07-01",
  "FreeDays": 21
}
```

> ⚠️ Updating `FreeDays` on a BoL cascades the update to all containers linked to that BoL that have not overridden their FreeDays value.

---

### DELETE `/deleteBl/{bl_code}` 🔒
Delete a Bill of Lading and all associated containers.

**Path Parameters:**
| Name | Type | Description |
|---|---|---|
| `bl_code` | string | The BoL reference number |

**Response `200 OK`:**
```json
{ "message": "Deleted successfully" }
```

---

## 5. Containers

> **Base router prefix:** `/`

All endpoints require 🔒 **Bearer token** unless noted.

---

### POST `/createContainer` 🔒
Create one or more containers under a Bill of Lading.

**Request:** `multipart/form-data`
| Field | Type | Required | Description |
|---|---|---|---|
| `data` | JSON string | ✅ | Container data (see below) |
| `files` | file(s) | ❌ | Container documents |

**`data` JSON structure:**
```json
{
  "BillOfLanding": "MAEU123456789",
  "containers": [
    {
      "container_no": "MSCU1234567",
      "type": 1,
      "FreeDays": 14,
      "PONo": "PO-2025-001"
    }
  ]
}
```

**Response `200 OK`:**
```json
{ "message": "Containers created", "count": 3 }
```

---

### GET `/getContainerDetails` 🔒
Retrieve a paginated, filtered list of containers.

**Query Parameters:**
| Name | Type | Default | Description |
|---|---|---|---|
| `container_no` | string | — | Filter by container number |
| `BillOfLanding` | string | — | Filter by BoL number |
| `status` | integer | — | Filter by status ID |
| `offset` | integer | `0` | Pagination offset |
| `limit` | integer | `50` | Max records (up to 1000) |

**Response `200 OK`:**
```json
{
  "total_count": 142,
  "data": [
    {
      "Container_ID": 10,
      "container_no": "MSCU1234567",
      "BillOfLanding": "MAEU123456789",
      "status": "On Port",
      "FreeDays": 14,
      "in_bound": "2025-06-20T14:30:00",
      "empty_date": null,
      "materials": ["Rice", "Wheat"]
    }
  ]
}
```

---

### GET `/getAllContainers` 🔒
Returns a simplified list of all non-completed containers (for report dropdowns).

**Response:** JSON string
```json
{
  "data": [[10, "MSCU1234567"], [11, "MSCU9876543"]]
}
```

---

### POST `/updateContainerDetails/{container_id}` 🔒
Full update of a container record with optional new document uploads.

**Path Parameters:**
| Name | Type | Description |
|---|---|---|
| `container_id` | integer | Container primary key |

**Request:** `multipart/form-data`
| Field | Type | Description |
|---|---|---|
| `data` | JSON string | Fields to update |
| `files` | file(s) | New documents to attach |
| `remove_doc_ids` | integer[] | IDs of documents to delete |

---

### POST `/updateContainer/{container_id}` 🔒
Quick status/date update for a container (lightweight update, no file handling).

**Path Parameters:**
| Name | Type | Description |
|---|---|---|
| `container_id` | integer | Container primary key |

**Request:** `application/json`
```json
{
  "status": 3,
  "in_bound": "2025-06-22T09:00:00",
  "empty_date": "2025-06-25"
}
```

---

### DELETE `/deleteContainerDetails/{container_id}` 🔒
Delete a container and all its documents.

---

### GET `/getDocument/{doc_id}` 🔒
Stream/download a container document by its ID.

**Response:** Binary file stream (`application/pdf`, `image/*`, etc.)

---

### GET `/arrived`
Returns all containers currently at the Gate Pass stage (status = 3).

**Response:**
```json
[
  {
    "Container_ID": 10,
    "container_no": "MSCU1234567",
    "arrival_on_port": "2025-06-15",
    "venue": "Port Louis Yard"
  }
]
```

---

### GET `/toPickup`
Returns all containers with Empty status (status = 7) ready for pickup.

**Response:**
```json
[
  {
    "Container_ID": 11,
    "container_no": "MSCU9876543",
    "emptyDate": "2025-07-01",
    "venue": "Harbour Depot"
  }
]
```

---

## 6. Damage Reports

> All endpoints require 🔒 **Bearer token** unless noted.

---

### GET `/getContainerReports` 🔒
List all damage reports with associated container numbers.

**Response:**
```json
{
  "column": ["Report Id", "Container No"],
  "data": [[1, "MSCU1234567"], [2, "MSCU9876543"]]
}
```

---

### GET `/getDamageReport`
Paginated list of damage reports.

**Auth:** None (public — see improvement note in roadmap)

**Query Parameters:**
| Name | Type | Default | Description |
|---|---|---|---|
| `report_id` | integer | — | Filter by specific report ID |
| `offset` | integer | `0` | Pagination offset |
| `limit` | integer | `500` | Max records (up to 1000) |

---

### POST `/submitDamagedProducts` 🔒
Create a new damage report with products and photos.

**Request:** `multipart/form-data`
| Field | Type | Required | Description |
|---|---|---|---|
| `data` | JSON string | ✅ | Report data |
| `files` | file(s) | ❌ | Product damage images |

**`data` JSON structure:**
```json
{
  "container_id": 10,
  "products": [
    {
      "name": "Rice Bags",
      "quantity": 5,
      "reason": "Water damage",
      "files": ["file_0", "file_1"]
    }
  ]
}
```

**Response `200 OK`:**
```json
{ "message": "Report submitted", "report_id": 7 }
```

---

### GET `/getDamageReportById/{report_id}` 🔒
Get full detail of a damage report including all products and image IDs.

**Response:**
```json
{
  "report_id": 7,
  "containerId": 10,
  "container_number": "MSCU1234567",
  "products": [
    {
      "id": 3,
      "name": "Rice Bags",
      "quantity": 5,
      "reason": "Water damage",
      "files": [{ "id": 11, "filename": "img_001.jpg" }]
    }
  ]
}
```

---

### POST `/updateDamagedProducts/{report_id}` 🔒
Update an existing damage report: add/edit/remove products and images.

**Path Parameters:**
| Name | Type | Description |
|---|---|---|
| `report_id` | integer | Damage report ID |

**Request:** `multipart/form-data`
| Field | Type | Description |
|---|---|---|
| `data` | JSON string | Updated products list |
| `files` | file(s) | New images to add |
| `remove_doc_ids` | integer[] | Image IDs to delete |
| `remove_product_ids` | integer[] | Product IDs to delete |

---

### GET `/getReportImage/{image_id}`
Serve a damage report image file inline.

**Auth:** None

**Response:** Binary file stream (image or PDF)

---

### GET `/reports/{report_id}`
Generate and stream a PDF version of a damage report.

**Auth:** None

**Response:** `application/pdf` stream
```
Content-Disposition: inline; filename=damage_report_7.pdf
```

---

### DELETE `/deleteDamagedReport/{report_id}` 🔒
Delete a damage report, all its products, all images, and removes files from disk.

---

## 7. Tracking & Integration

---

### GET `/track_and_trace`
Query live shipping tracking data for a Bill of Lading from Maersk and CMA CGM.

**Auth:** None

**Query Parameters:**
| Name | Type | Required | Description |
|---|---|---|---|
| `bl` | string | ✅ | Bill of Lading reference number |

**Response `200 OK`:**
```json
[
  {
    "eventDateTime": "2025-06-15T10:30:00",
    "eventType": "ARRI",
    "location": "Port Louis",
    "vessel": "MSC Diana"
  }
]
```

**Notes:**
- Queries Maersk first; falls back to CMA CGM if not found.
- A background scheduler also calls this daily to auto-update `ArrivalDate` on Bills of Lading.

---

## 8. Settings & Configuration

> All endpoints require 🔒 **Bearer token**.

---

### GET `/settings/demurrage-days` 🔒
Returns the static bitmask mapping for days of the week used in demurrage calculations.

**Response:**
```json
{
  "Monday": 1,
  "Tuesday": 2,
  "Wednesday": 4,
  "Thursday": 8,
  "Friday": 16,
  "Saturday": 32,
  "Sunday": 64
}
```

> **Usage:** The frontend uses this map to let users select which days to exclude from demurrage calculations. Values are OR'd together to produce the `ExcludingDays` bitmask (e.g. Saturday + Sunday = 32 + 64 = `96`).

---

### GET `/settings/logistics-providers` 🔒
List all logistics providers with their demurrage configuration.

**Response:**
```json
[
  {
    "Id": 1,
    "Name": "Maersk",
    "ExcludingDays": 96,
    "FreeDays": 14,
    "ExcludingDaysList": ["Saturday", "Sunday"]
  }
]
```

---

### POST `/settings/logistics-providers/{provider_id}` 🔒
Update the demurrage settings for a logistics provider.

**Path Parameters:**
| Name | Type | Description |
|---|---|---|
| `provider_id` | integer | Logistics provider ID |

**Request:** `application/json` — send one or both fields:
```json
{
  "FreeDays": 21,
  "ExcludingDaysList": ["Saturday", "Sunday"]
}
```

> You can also send `ExcludingDays` as a raw bitmask integer instead of `ExcludingDaysList`.

**Response:** Full updated provider object (same as GET list item).

**Errors:**
| Code | Reason |
|---|---|
| `404` | Provider ID not found |
| `400` | Invalid day name in `ExcludingDaysList` |

---

## 9. User & Role Management

> All endpoints require 🔒 **Bearer token** (admin role recommended).

---

### GET `/getRole`
List all roles.

**Response:**
```json
[{ "id": 1, "name": "admin" }, { "id": 2, "name": "viewer" }]
```

---

### GET `/getUser`
List all users with their roles.

**Response:**
```json
[
  { "id": 1, "username": "john", "roles": ["admin"] }
]
```

---

### GET `/getPermission`
List all permissions.

**Response:**
```json
[{ "id": 1, "name": "edit_container", "descriptionp": "Can edit containers" }]
```

---

### POST `/addPermission`
Create a new role and assign permissions to it.

**Request:** `application/json`
```json
{
  "name": "manager",
  "permissions": [1, 2, 3]
}
```

---

### POST `/addUser`
Create a new user and assign roles.

**Request:** `application/json`
```json
{
  "username": "jane",
  "password": "SecureP@ss1!",
  "roles": [1]
}
```

**Response:**
```json
{ "id": 5, "username": "jane", "roles": ["admin"] }
```

---

### DELETE `/deleteUser/{user_id}`
Delete a user (clears all role associations first).

---

### DELETE `/deleteRole/{role_id}`
Delete a role (clears all user and permission associations first).

---

## 10. Data Models

### Container Status Codes
| ID | Label | Description |
|---|---|---|
| `1` | In Transit | Vessel has not yet arrived |
| `2` | On Port | Arrived at port, not cleared |
| `3` | Gate Pass | Cleared, ready for pickup |
| `4` | Complete | Delivered and done |
| `6` | Inbound | Moving from port to warehouse |
| `7` | Empty | Container emptied, awaiting return |
| `8` | Unknown | Status cannot be determined |

---

### Demurrage Day Bitmask
| Day | Value |
|---|---|
| Monday | `1` |
| Tuesday | `2` |
| Wednesday | `4` |
| Thursday | `8` |
| Friday | `16` |
| Saturday | `32` |
| Sunday | `64` |

**Example:** To exclude weekends → `32 + 64 = 96`

---

### Database Schemas

| Schema | Tables |
|---|---|
| `usercredentials` | `users`, `roles`, `permissions`, `user_roles`, `role_permissions`, `user_refresh_tokens` |
| `containermgmt` | `container_details`, `bill_of_landing`, `supplier`, `container_type`, `unload_venue`, `consignee`, `shipping_document`, `material`, `container_products`, `status`, `vessel`, `logisticsprovider`, `report_details`, `damage_product`, `report_image`, `container_docs` |

---

## 11. Error Reference

| HTTP Code | Meaning |
|---|---|
| `400` | Bad Request — malformed JSON or invalid field value |
| `401` | Unauthorized — missing or invalid/expired Bearer token |
| `403` | Forbidden — authenticated but lacks required role |
| `404` | Not Found — resource does not exist |
| `409` | Conflict — duplicate unique key (e.g. BoL already exists) |
| `422` | Unprocessable Entity — Pydantic validation failed |
| `429` | Too Many Requests — rate limit exceeded (5 login attempts/min) |
| `503` | Service Unavailable — database connection failure |

All error responses follow the standard FastAPI format:
```json
{ "detail": "Human-readable error message" }
```

---

## 12. Security Compliance Matrix

> This section tracks the implementation status of every security requirement against the agreed standard checklist.  
> Last reviewed: 2026-05-25

| # | Security Area | Requirement | Method | Status | Implementation | Notes |
|---|---|---|---|---|---|---|
| 1 | **HTTPS** | Mandatory | TLS/SSL via Nginx | ⏳ Pending | Infrastructure — not in codebase | Must be configured at deployment time via Nginx + Let's Encrypt or Cloudflare. Set `ENVIRONMENT=production` in `.env`. |
| 2 | **Authentication** | Mandatory | JWT Access Token | ✅ Done | [`auth/routes.py`](auth/routes.py) — `POST /token` | OAuth2 Bearer, 1-hour access token lifetime. |
| 3 | **Authorization** | Mandatory | Role-based checks | ✅ Done | [`auth/dependencies.py`](auth/dependencies.py) — `get_current_user`, `require_roles` | Actual DB roles embedded in JWT payload. Removed hardcoded `"admin"` string. |
| 4 | **Password Security** | Mandatory | Argon2 or bcrypt | ✅ Done | [`auth/security.py`](auth/security.py) | `passlib` + `bcrypt` scheme. Column widened to `VARCHAR(255)` — bcrypt truncation bug fixed via `migration_v2.py`. |
| 5 | **Input Validation** | Mandatory | Pydantic validation | ✅ Done | All `Schema/` files | All request bodies validated via Pydantic v2 models at endpoint entry. |
| 6 | **SQL Injection Protection** | Mandatory | SQLAlchemy ORM | ✅ Done | All `Model/` and `Routes/` files | No raw string-formatted SQL queries. All queries use parameterized SQLAlchemy ORM calls. |
| 7 | **Secret Management** | Mandatory | `.env` variables | ✅ Done | [`auth/config.py`](auth/config.py), [`.env`](.env) | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, DB URL, and all API keys loaded from `.env`. Startup debug prints removed. |
| 8 | **Rate Limiting** | Mandatory | Per-IP login limits | ✅ Done | [`containerMgmt.py`](containerMgmt.py) + `slowapi==0.1.9` | `POST /token` limited to **5 requests/minute per IP**. Returns `429 Too Many Requests` on breach. |
| 9 | **Token Expiry** | Mandatory | Short-lived JWT | ✅ Done | [`auth/routes.py`](auth/routes.py) | Access token: **1 hour**. Refresh token: **7 days**, persisted in DB with revocation support. |
| 10 | **CORS Security** | Mandatory | Restrict origins | ✅ Done | [`containerMgmt.py`](containerMgmt.py) | `allow_origins` reads from `ALLOWED_ORIGINS` in `.env`. No more wildcard `*`. |
| 11 | **Logging** | Recommended | Auth failures + API logs | ✅ Done | [`containerMgmt.py`](containerMgmt.py), [`auth/routes.py`](auth/routes.py) | Python `logging` module configured with console + `app.log` file. Failed logins and logouts logged with username and IP. |
| 12 | **API Key Security** | If using external APIs | Header-based API keys | ✅ Done | [`auth/config.py`](auth/config.py), [`.env`](.env) | Maersk and CMA CGM credentials loaded from environment. Startup print of credentials removed. |
| 13 | **Refresh Tokens** | Recommended | Separate refresh token | ✅ Done | [`auth/routes.py`](auth/routes.py), [`Model/Credentials/refresh_tokens.py`](Model/Credentials/refresh_tokens.py) | DB-backed refresh tokens. SHA-256 hashed before storage. Revocable via `POST /logout`. Replaced in-memory `fake_refresh_tokens = {}`. |
| 14 | **Swagger Protection** | Recommended | Disable/protect docs | ✅ Done | [`containerMgmt.py`](containerMgmt.py) | `/docs` and `/redoc` are **hidden** when `ENVIRONMENT=production` in `.env`. Visible only in `development`. |
| 15 | **Reverse Proxy** | Recommended | Nginx | ⏳ Pending | Infrastructure | Not in codebase. Must be configured at deployment. Nginx should terminate TLS and proxy to `uvicorn` on `localhost:9000`. |
| 16 | **Monitoring** | Recommended | Basic metrics/logging | 🔶 Partial | [`containerMgmt.py`](containerMgmt.py) — `GET /health` | Health check endpoint added. Structured file logging active (`app.log`). Full APM (Prometheus, Grafana, Sentry) is a future infra task. |

---

### Security Checklist Summary

```
✅  Implemented  (12/16)
⏳  Pending      ( 2/16) — HTTPS, Nginx (infrastructure, not code)
🔶  Partial      ( 1/16) — Monitoring (logging done, APM pending)
❌  Missing      ( 0/16)
```

---

### Database Security Migrations Applied

Run via [`migration_v2.py`](migration_v2.py):

```sql
-- Fix bcrypt hash truncation (password_hash was VARCHAR(45), bcrypt = 60 chars)
ALTER TABLE usercredentials.users
    MODIFY COLUMN password_hash VARCHAR(255) NOT NULL;

-- Replace in-memory refresh token dict with persistent DB table
CREATE TABLE IF NOT EXISTS usercredentials.user_refresh_tokens (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    token_hash  VARCHAR(255) NOT NULL,
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    revoked     TINYINT(1) NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES usercredentials.users(id) ON DELETE CASCADE,
    INDEX idx_token_hash  (token_hash),
    INDEX idx_user_expires (user_id, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### Remaining Production Actions (Manual)

Before going live, complete the following infrastructure steps:

1. **Generate a strong JWT secret:**
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Set the result as `JWT_SECRET_KEY` in the production `.env`.

2. **Set production environment:**
   ```env
   ENVIRONMENT=production
   ALLOWED_ORIGINS=https://yourdomain.com
   ```

3. **Configure Nginx** as a reverse proxy with TLS:
   ```nginx
   server {
       listen 443 ssl;
       server_name yourdomain.com;

       ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

       location / {
           proxy_pass         http://127.0.0.1:9000;
           proxy_set_header   Host $host;
           proxy_set_header   X-Real-IP $remote_addr;
           proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header   X-Forwarded-Proto $scheme;
       }
   }
   ```

---

## 13. API Design Improvement Guide

> Based on an analysis of the current backend, the API currently leans heavily on **RPC-style routing** (Remote Procedure Call) rather than standard **RESTful routing**. This section outlines the basics of REST API design, analyzes the current bottlenecks, and provides a roadmap for refactoring the API into a modern, predictable, and scalable standard.

### 13.1 What are the Basics of API Design?

A modern REST API should follow these core principles:
1. **Resource-Based URLs:** URLs should represent things (nouns), not actions (verbs). The HTTP method (`GET`, `POST`, `PUT`, `DELETE`) provides the action.
2. **Plural Nouns:** Use plural nouns for collections (e.g., `/containers`, not `/container` or `/getContainer`).
3. **Standard HTTP Methods:**
   - `GET`: Read data.
   - `POST`: Create new data.
   - `PUT`: Replace an existing record entirely.
   - `PATCH`: Partially update an existing record.
   - `DELETE`: Remove a record.
4. **Predictable Hierarchy:** Nested resources should logically follow parent resources (e.g., `/reports/{id}/images`).
5. **Standardized Responses:** Consistent pagination, error formats, and envelope structures (which FastAPI largely helps with via Pydantic).

### 13.2 Current State vs. RESTful Standard (Bottlenecks)

The current API uses "verbs" in the URLs (`get...`, `set...`, `update...`, `delete...`), which creates a cluttered and unpredictable routing structure. 

#### Examples of Current Bottlenecks:
* **Inconsistency:** `/setVessal` vs `/addBl` vs `/createContainer`. All do the same action (create), but use different verbs.
* **Redundancy:** `GET /getBl` repeats the verb "get" which is already handled by the HTTP `GET` method.
* **Non-Standard Updates:** `POST /updateBl/{bl_number}` uses `POST` instead of `PUT` or `PATCH`.
* **Typos:** `/setVessal` instead of `/vessels`.

### 13.3 Refactoring Roadmap (What We Have to Implement)

To bring the API up to industry standards, the routes should be refactored to follow resource-based naming. 

#### Reference Data (Info Routes)
| Current RPC Route (Bad) | Target REST Route (Good) | HTTP Method |
|---|---|---|
| `/setVessal` | `/vessels` | `POST` |
| `/vessal` | `/vessels` | `GET` |
| `/setSupplier` | `/suppliers` | `POST` |
| `/supplierDetails` | `/suppliers` | `GET` |
| `/setConsignee` | `/consignees` | `POST` |
| `/consignee` | `/consignees` | `GET` |

#### Bill of Lading (BoL)
| Current RPC Route (Bad) | Target REST Route (Good) | HTTP Method |
|---|---|---|
| `/getBl` | `/bills-of-lading` | `GET` |
| `/addBl` | `/bills-of-lading` | `POST` |
| `/updateBl/{id}` | `/bills-of-lading/{id}` | `PATCH` (or `PUT`) |
| `/deleteBl/{id}` | `/bills-of-lading/{id}` | `DELETE` |

#### Containers
| Current RPC Route (Bad) | Target REST Route (Good) | HTTP Method |
|---|---|---|
| `/getContainerDetails` | `/containers` | `GET` |
| `/createContainer` | `/containers` | `POST` |
| `/updateContainerDetails/{id}` | `/containers/{id}` | `PUT` |
| `/updateContainer/{id}` | `/containers/{id}/status` | `PATCH` |
| `/deleteContainerDetails/{id}`| `/containers/{id}` | `DELETE` |

#### Damage Reports
| Current RPC Route (Bad) | Target REST Route (Good) | HTTP Method |
|---|---|---|
| `/getDamageReport` | `/damage-reports` | `GET` |
| `/submitDamagedProducts` | `/damage-reports` | `POST` |
| `/getDamageReportById/{id}` | `/damage-reports/{id}` | `GET` |
| `/updateDamagedProducts/{id}`| `/damage-reports/{id}` | `PUT` |
| `/deleteDamagedReport/{id}` | `/damage-reports/{id}` | `DELETE` |

### 13.4 How to Execute the Refactor (Action Plan)

Because the frontend currently depends on the existing RPC routes, you cannot simply change them overnight without breaking the UI. Follow this gradual transition plan:

**Phase 1: Dual Routing (Recommended First Step)**
Add the new RESTful route definitions pointing to the exact same handler functions as the old routes, but keep the old ones active.
```python
# Old Route (Deprecated but active)
@Cinfo.post("/setVessal", deprecated=True)
# New REST Route
@Cinfo.post("/vessels")
async def create_vessel(...):
    # logic
```

**Phase 2: Frontend Migration**
Update the React frontend codebase to point to the new endpoints (`/vessels`, `/containers`, etc.).

**Phase 3: Cleanup**
Once the frontend is fully migrated, remove the old deprecated routes (`/setVessal`, `/getContainerDetails`) from the FastAPI backend to enforce the new clean API contract.

