# Docker deployment notes

## Services

- `api`: FastAPI application, starts only after PostgreSQL health checks pass.
- `db`: PostgreSQL 17 with a persistent named volume.
- `postgres_data`: database files.
- `uploads_data`: uploaded source files.

## Startup sequence

1. PostgreSQL starts and passes `pg_isready`.
2. The API container runs `alembic upgrade head`.
3. Uvicorn starts only if migrations succeed.
4. Docker health checks query `/health`.

Production containers do not create tables automatically on application startup. SQLite development/test mode retains a convenience bootstrap; schema changes should be committed as Alembic migrations.

## Commands

```bash
docker compose config
docker compose up --build -d
docker compose ps
docker compose logs -f api
docker compose exec api alembic current
docker compose exec api pytest -q
docker compose down
```

## Security notes

- Configure a unique `POSTGRES_PASSWORD` in the untracked `.env` file.
- The PostgreSQL port is bound to loopback by default.
- API uploads persist in a named volume. Back them up according to the deployment's retention policy.
- The current `/health` endpoint is a liveness check, not a full dependency readiness report.
- Add TLS/reverse proxy, authentication/authorization, secrets management, backup/restore drills, monitoring and resource limits before exposing publicly.

## Verification status

Application tests run outside Docker are recorded in the project README. Docker image build and Docker Compose end-to-end integration must be run on a machine with Docker installed; do not treat a successful Python test run as proof that containers have been built or started.
