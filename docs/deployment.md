# deployment.md — Hosting & Deployment Guide

Verified cost model: [`cost-model.md`](cost-model.md) ($0/month on
always-free tiers, prices checked 2026-10-25). **Nothing in this repo
provisions infrastructure automatically.**

## Option A (primary): GitHub Actions + Cloud Run + Neon — $0

### A1. Database — Neon Postgres (free plan)

1. Create a Neon project (free plan, no card). Region: `aws-us-east-1`
   (close to GH Actions + Cloud Run `us-east4/us-central1`).
2. Create two roles:
   - `collector` — read/write (owner of schema).
   - `api_ro` — read-only:
     ```sql
     GRANT USAGE ON SCHEMA public TO api_ro;
     GRANT SELECT ON ALL TABLES IN SCHEMA public TO api_ro;
     ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO api_ro;
     ```
3. Connection strings:
   - `DATABASE_URL` (collector, `-pooler` endpoint) → GH Actions secret +
     Cloud Run secret `FT_DATABASE_URL` (form `postgresql+psycopg://…`).
   - API gets the `api_ro` DSN.
4. Set a Neon usage alert at 80 CU-hours/month (the tightest free limit).

### A2. Collector — GitHub Actions (public repo = free)

1. Push this repo to GitHub (public).
2. Add secret `DATABASE_URL` (collector DSN).
3. `.github/workflows/collector.yml` schedules:
   - 13:17 UTC daily — catches Benzinga's morning Halftime article.
   - 23:17 UTC weekdays — catches Fast Money's post-air video/RSS.
   - 23:47 UTC weekdays — performance computation after US close settles.
   - `workflow_dispatch` — operator backfill (`mode=backfill` + window).
4. Initial historical load: run the backfill dispatch repeatedly (each
   invocation is bounded by `--max-units`, default 40) or run locally:
   ```bash
   DATABASE_URL=postgresql+psycopg://… uv run final-trades backfill \
     --start 2025-10-25 --end 2026-10-25 --max-units 40
   ```
   Repeat until `coverage-report` shows the backlog exhausted. Interrupted
   invocations are safe — state is durable per date.
5. Cron reliability: Actions may delay/drop scheduled runs under load; the
   backlog design recovers automatically on the next run. Keep the repo
   active (auto-disable after 60 days of inactivity).

### A3. API + SPA — Cloud Run (always-free tier)

1. Enable billing account (required even for $0) + **set a $1 budget alert**.
2. Build & push (from repo root):
   ```bash
   gcloud builds submit --tag us-docker.pkg.dev/$PROJECT/final-trades/api:latest
   ```
   or `docker build -f deploy/Dockerfile` + push to any registry.
3. Create Secret Manager secret `FT_DATABASE_URL` (api_ro DSN); grant the
   run service account `secretmanager.secretAccessor`.
4. Edit `deploy/cloud-run/api-service.yaml` (image, region, SA, secret env)
   then `gcloud run services replace api-service.yaml`, or deploy via
   console with: port 8000, 512Mi/1 CPU, min-instances 0, **max-instances
   2**, allow unauthenticated.
5. Verify: `curl https://<url>/healthz`, browse the dashboard, confirm 405
   on `POST /api/v1/runs`.
6. Free-tier budget: ~150k req/mo ≈ 7% of the 2M free requests; cold starts
   1–3s after scale-to-zero (overview is cached 60s).

### A4. Alternative scheduler — Cloud Run Jobs

If you prefer GCP-native scheduling over Actions cron: follow
`deploy/cloud-run/README.md` (jobs `ft-collector` + `ft-performance`,
3 Cloud Scheduler jobs — free). `maxRetries: 0` is intentional: recovery is
cross-run, not job-level retry.

## Option B: docker-compose (any $4+ VPS or local machine)

```bash
POSTGRES_PASSWORD=... docker compose -f deploy/docker-compose.yml up --build -d
# API on :8000; collector loops every COLLECT_INTERVAL_SECONDS (default 6h)
```

Data durability: the `pgdata` volume. Backups: `docker compose exec db
pg_dump -U collector final_trades | gzip > backup-$(date +%F).sql.gz`.

## Option C: fully local (development)

```bash
uv sync --extra dev && cp .env.example .env
uv run final-trades migrate
uv run final-trades collect --once     # SQLite at data/final_trades.sqlite3
uv run final-trades serve              # API :8000 serves web/dist if built
cd web && npm install && npm run dev   # dev server :5173 with /api proxy
```

## Environment reference

See `.env.example` — every variable is validated at startup (fail fast).
Secrets (`DATABASE_URL` with credentials, `TIINGO_API_KEY`) live only in
provider secret stores; log output shows presence, never values.

## Portability

- One Docker image, standard SQL (Alembic), no vendor SDKs in app code.
  Moving hosts = point `DATABASE_URL` + run the image elsewhere.
- SQLite ↔ Postgres both supported by the same migrations
  (`render_as_batch`, portable types).
- Export/migration: `pg_dump` (see operations.md). No proprietary formats.
