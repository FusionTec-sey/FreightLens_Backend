# Running FreightLens Locally

## Docker development (hot reload)

From `Backend`, copy the development-only environment template and start the
isolated local stack:

```powershell
Copy-Item local-dev.env.example .env.local
docker compose --env-file .env.local -p freightlens-dev -f docker-compose.dev.yml up --build
```

Open the React app at `http://localhost:13000`; the API is at
`http://localhost:19000` (`/docs` and `/health`). Backend and frontend source are
bind-mounted for reload. PostgreSQL, Meilisearch, and RustFS data persist in named
volumes. All published ports bind to loopback; this stack is local-development only
and must not use staging or production secrets.

Stop without deleting data using:

```powershell
docker compose --env-file .env.local -p freightlens-dev -f docker-compose.dev.yml down
```

Do not add `-v` unless you intentionally want to delete the local database, search,
and object-storage volumes. After changing the React dependency lockfile, rebuild with
`docker compose --env-file .env.local -p freightlens-dev -f docker-compose.dev.yml up --build frontend`.

## Prerequisites

- Python 3.11
- Node.js 20 and npm
- Docker Desktop with Linux containers

## Infrastructure

From `Backend`:

```powershell
docker compose up -d postgres rustfs meilisearch
docker compose ps
```

Local ports are PostgreSQL `5433`, RustFS `9005`, RustFS console `9006`, and Meilisearch `7700`.

## Backend

Copy `.env.example` to `.env`, replace every placeholder with a unique local value, and never commit the result. `JWT_SECRET_KEY` and `MEDIA_SIGNING_KEY` must be separate random values. CMA CGM push webhooks are disabled by default; when enabling them with `CMA_CGM_WEBHOOK_ENABLED=true`, also configure a separate random `CMA_CGM_WEBHOOK_SECRET`.

Generate a signing key once per environment:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn containerMgmt:app --host 0.0.0.0 --port 9000 --reload
```

API documentation is at `http://localhost:9000/docs` outside production. Health is at `http://localhost:9000/health`.

## Frontend

From `containermgmt`, set `REACT_APP_NETWORK=http://localhost:9000` in `.env`, then run:

```powershell
npm ci
npm start
```

The app is available at `http://localhost:3000`.

## Verification

```powershell
# Backend
.\.venv\Scripts\python.exe -m pytest -q

# Frontend
npm run build
```

Before deployment, back up PostgreSQL and complete the affected-screen walkthrough described in the stabilization plan.
