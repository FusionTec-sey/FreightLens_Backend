# Backend Architecture & Codebase Details

## Overview
The backend application is a **FastAPI** service designed to orchestrate the tracking, management, and documentation of shipping containers and Bills of Lading (BoL). It integrates with external shipping providers to fetch real-time estimated arrival times (ETAs) and utilizes a relational database for persistent storage.

## Technology Stack
- **Framework**: FastAPI (Python)
- **Database ORM**: SQLAlchemy
- **Authentication**: JWT (JSON Web Tokens) with OAuth2 Password flow
- **Background Tasks**: APScheduler
- **External APIs**: Logistics Providers (Maersk, CMA CGM)

## Project Structure
- **`Model/`**: Contains SQLAlchemy declarative base models mapping to database tables (`ContainerDetails`, `BillOfLanding`, `ReportDetails`, `User`, `Role`, etc.).
- **`Schema/`**: Pydantic models used for data validation, serialization, and defining API request/response structures.
- **`Routes/`**: Contains modularized API endpoints (e.g., `Container.py`, `BillOfLanding.py`, `Credentials.py`).
- **`auth/`**: Manages authentication mechanisms, dependencies (`get_current_user`), and token generation/validation.
- **`ShippingProvider/`**: Abstraction layer integrating with logistics APIs like Maersk and CMA CGM. Consists of scripts like `Shipping.py` defining the `track_and_trace` logic.

## Core Features & Logic

### 1. Container Management
- Operations to create, update, and manage containers. Containers are directly tied to a `BillOfLanding` via Foreign Keys.
- Includes support for multi-part file uploads (Shipping Docs, Inbound Images, Empty Container Images).

### 2. Bill of Lading (BoL) Tracking
- Manages the top-level transport document.
- A background job via APScheduler (`updateArrivalDate`) runs daily. It polls external shipping providers (Maersk/CMA CGM) associated with active BoLs and updates the `ArrivalDate` in the database.

### 3. FreeDays — Cascade & Conflict Logic
`FreeDays` is managed at **two levels**: the BoL level and the individual container level.

**Rules:**
- When **creating** a container, if no `FreeDays` is explicitly provided, it **inherits** the value from the parent BoL.
- When **updating** the BoL's `FreeDays`:
  - The backend checks all child containers linked to that BoL.
  - If **any** container has a `FreeDays` value that differs from the BoL's *current* `FreeDays` (i.e., it was individually overridden), the update is **rejected** with `HTTP 409 Conflict`.
  - If no conflict is found, the new `FreeDays` is **cascaded** to every child container automatically.
- A container's `FreeDays` can always be updated individually without restriction.

> **DB Column**: `FreeDays INT NULL` on both `containermgmt.bill_of_landing` and `containermgmt.container_details`.

### 4. Status — Cascade & Conflict Logic
`status` follows the **exact same logic** as `FreeDays`, applied at both the BoL and individual container level.

**Rules:**
- When **creating** a container, if no `status` is provided, it **inherits** `status` from the parent BoL.
- When **updating** the BoL's `status`:
  - The backend checks all child containers linked to that BoL.
  - If **any** container has a `status` that differs from the BoL's *current* `status` (i.e., it was individually overridden), the update is **rejected** with `HTTP 409 Conflict`.
  - If no conflict exists, the new `status` is **cascaded** to every child container.
- A container's `status` can always be updated individually without restriction.

> **DB Column**: `status INT NULL` (FK → `containermgmt.status.status_id`) added to `containermgmt.bill_of_landing`. Already exists on `containermgmt.container_details`.

### 5. Damage Reporting Workflow
- Allows users to submit reports on damaged products associated with specific containers.
- Saves multiple images per damaged product through relational tables (`ReportDetails` → `DamageProduct` → `ReportImage`).

## Data Model Flow
- **`BillOfLanding`** (1) → (Many) **`ContainerDetails`**
- **`ContainerDetails`** (1) → (Many) **`ContainerDocs`** (Shipping documents and images)
- **`ContainerDetails`** (1) → (Many) **`ReportDetails`** (Damage reports)
- **`ReportDetails`** (1) → (Many) **`DamageProduct`**
- **`DamageProduct`** (1) → (Many) **`ReportImage`**

## Database Migration Required
The following SQL must be executed on the production database (**once**) before deploying these changes:

```sql
-- FreeDays on BoL (new)
ALTER TABLE containermgmt.bill_of_landing ADD COLUMN FreeDays INT NULL;

-- Status on BoL (new)
ALTER TABLE containermgmt.bill_of_landing ADD COLUMN status INT NULL;

-- FreeDays on Containers (new)
ALTER TABLE containermgmt.container_details ADD COLUMN FreeDays INT NULL;

-- NOTE: status already exists on container_details — no migration needed there.
```

## Areas for Architectural Improvement
- **Synchronous External API Calls**: In the APScheduler background tasks, provider polling happens sequentially. Upgrading this to `asyncio.gather` for parallel processing would drastically reduce job latency.
