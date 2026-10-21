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
- `docker/env.docker.example` — safe local defaults used directly by Compose. No real secrets.
- `docker/nginx.conf` — SPA routing and `/api` proxy to the API container.
- `Makefile` — short local commands.

All three published ports bind to `127.0.0.1`. This matters because local API
authentication bypass is enabled for development.

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

## Smoke Tests

Check only the local health endpoints during initial setup:

```bash
curl -fsS http://localhost:8001/api/health
curl -fsS http://localhost:8080/healthz
```

Cron endpoints may call external providers when credentials are configured. Use
the offline tests in `AGENTS.md` to validate cron behavior.

## Useful Commands

```bash
make docker-ps
make docker-logs
make docker-migrate
make docker-test
make docker-down
make docker-clean
```

## Provider boundaries

Compose reads `docker/env.docker.example` directly, so a copied
`docker/.env.docker` is **not** loaded by `docker compose up`. Keep provider keys
empty for normal development. Any separate live integration setup requires an
explicit reviewed Compose override, a dedicated provider sandbox, and the
cost/consent rules in `CLAUDE.md` and `AGENTS.md`.
