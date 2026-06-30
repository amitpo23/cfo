# Rezef Local Docker

This setup runs the full local stack with pinned runtime versions:

- API: Python 3.12 slim + `uv 0.10.11`
- Frontend build: Node 20 Alpine
- Frontend runtime: nginx 1.27 Alpine
- Database: PostgreSQL 16 Alpine

## Files

- `Dockerfile.api` — FastAPI backend image. Runs Alembic migrations on boot, then starts Uvicorn.
- `Dockerfile.frontend` — builds Vite and serves the static app with nginx.
- `docker-compose.yml` — local stack: Postgres, API, frontend.
- `docker/env.docker.example` — safe local defaults. No real secrets.
- `docker/nginx.conf` — SPA routing and `/api` proxy to the API container.
- `Makefile` — short local commands.

## Prerequisite

Install Docker Desktop or another Docker-compatible CLI. The current machine
must have both:

```bash
docker --version
docker compose version
```

## Run

```bash
make docker-build
make docker-up
```

Open:

- App: `http://localhost:8080`
- API health: `http://localhost:8001/api/health`
- API docs: `http://localhost:8001/api/docs`
- Postgres: `localhost:5433`, database `cfo`, user `cfo`

## Local Registration

The Docker default registration code is:

```text
local-register
```

## Cron Smoke Tests

The Docker default cron secret is:

```bash
curl -H "Authorization: Bearer local-cron-secret" http://localhost:8001/api/cron/sync
curl -H "Authorization: Bearer local-cron-secret" http://localhost:8001/api/cron/process-ocr
```

## Useful Commands

```bash
make docker-ps
make docker-logs
make docker-migrate
make docker-test
make docker-down
make docker-clean
```

## Real Integrations

For real local integration tests, do not edit `docker/env.docker.example`.
Create a private file, keep it ignored, and run compose with it explicitly:

```bash
cp docker/env.docker.example docker/.env.docker
# edit docker/.env.docker with private values
docker compose -f docker-compose.yml --env-file docker/.env.docker up --build
```

Required for full live E2E:

- `SUMIT_API_KEY`
- `SUMIT_COMPANY_ID`
- `OPEN_FINANCE_CLIENT_ID`
- `OPEN_FINANCE_CLIENT_SECRET`
- `OPEN_FINANCE_USER_ID`
- `GOOGLE_CLIENT_ID`
- `VITE_GOOGLE_CLIENT_ID`
