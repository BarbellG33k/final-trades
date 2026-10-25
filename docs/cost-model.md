# cost-model.md — Verified Operating Cost Model

All prices **checked 2026-10-25** against official pricing pages/docs (via
research subagent; source URLs inline). Workload assumptions: collector 2–4
runs/day × 5–15 min; API+SPA ~a few thousand requests/day (~150k/mo);
Postgres < 500 MB; public GitHub repo.

**Bottom line: the selected architecture costs $0/month on always-free tiers
(no trial credits), with a documented <$3 fallback path.**

## Selected architecture (primary, $0)

| Component | Service | Free-tier terms (checked 2026-10-25) | Our usage | Headroom |
|---|---|---|---|---|
| Collector | GitHub Actions cron (public repo) | Free/unlimited standard minutes for public repos; the 2026-03-01 $0.002/min platform charge explicitly exempts public repos ([github.com/pricing](https://github.com/pricing)) | ~2 h/month of runner time | ∞ |
| API + SPA | Cloud Run service (request-based) | Always free: 2M requests, 180k vCPU-s, 360k GiB-s/mo per billing account ([cloud.google.com/run/pricing](https://cloud.google.com/run/pricing)) | ~150k req/mo (~7%), scale-to-zero idle | ~13× requests |
| Database | Neon Postgres Free | Permanent free plan, no card: 1 GB storage/project (20 GB account), 100 CU-hours/mo compute, auto-suspend after 5 min, 5 GB egress ([neon.tech](https://neon.tech/pricing); ⚠️ some secondary sources say 0.5 GB — official page says 1 GB, verify at signup) | <500 MB data, ~4–12 h awake/day at 0.25 CU ≈ 30–90 CU-h | Storage 2×; **CU-hours is the tightest constraint — set an alert** |
| Market data | Yahoo Finance via yfinance (keyless); optional free Tiingo key | $0 ([DECISIONS D-007](DECISIONS.md)) | ~40 tickers/day | n/a |
| Backups | Neon branch/PITR on free tier + weekly `pg_dump` committed to GH Actions artifacts / repo-private store | $0 | <500 MB dumps | n/a |

**Total: $0.00/month.** Requires a GCP billing account (card) even for $0 —
set a billing alert at $1 and max-instances caps on the Cloud Run service.

### Alternative scheduler (documented, also $0)

Cloud Run **Jobs** + Cloud Scheduler: Jobs always-free pool is separate
(240k vCPU-s + 450k GiB-s/mo; our ~27k vCPU-s + 54k GiB-s ≈ 11%); Cloud
Scheduler gives **3 free jobs/billing account**, then $0.10/job/month
([cloud.google.com/scheduler/pricing](https://cloud.google.com/scheduler/pricing)).
Config in `deploy/cloud-run/`. Stronger scheduling guarantees than Actions
cron; costs $0 for ≤3 schedules.

## Known caveats (accepted)

- **GH Actions cron**: delayed under load, may drop queued runs at peak,
  auto-disables after 60 days of repo inactivity, default branch only
  ([docs](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows)).
  Accepted: the cross-run backlog design treats missed runs as normal;
  schedule off-the-hour; active repo never idles 60 days.
- **Cloud Run cold starts**: 1–3 s for Python after scale-to-zero. Accepted
  for a hobby dashboard; `/overview` is cached 60 s.
- **Neon CU-hours**: if the API keeps compute awake ~12 h/day the budget is
  tight. Mitigations: 5-min auto-suspend, low traffic, alert at 80 CU-h;
  fallback below.
- **Neon egress**: 5 GB/mo free — JSON API traffic is far below this.

## Fallback ladder (if a free tier stops fitting)

1. **DB compute pressure** → Supabase Free (500 MB, pauses after 1 week
   inactivity — daily traffic prevents) or Turso Free (5 GB libSQL;
   ⚠️ Turso is being acquired by Supabase, longevity uncertain). $0.
2. **API pressure** → move SPA to Cloudflare Pages (unlimited static
   requests free) and keep only `/api/v1` on Cloud Run. $0.
3. **Always-on need** → Oracle Cloud Always Free ARM VM (2 OCPU/12 GB after
   the Aug 2026 halving; idle-reclamation risk; you own patching/backups). $0.
4. **Paid ceiling** (≤$3/mo, requires approval): not currently needed; the
   first paid rungs (Railway Hobby $5, Hetzner €4–6, DO $4) all exceed $3, so
   per requirements we stay on free tiers rather than pay.

## Rejected options (with reasons)

- **Cloud SQL Postgres**: minimum ≈ $9.4/mo (db-f1-micro $0.0105/hr + 10 GiB
  SSD) — blows the ceiling ([cloud.google.com/sql/pricing](https://cloud.google.com/sql/pricing)).
- **AWS Lambda + EventBridge**: compute is $0 (Lambda 1M req/400k GB-s
  always-free stands; EventBridge Scheduler 14M free invocations) but RDS
  free tier became 6-months-time-boxed for accounts created after
  2025-07-15; Aurora DSQL always-free is promising but unproven with
  SQLAlchemy. Kept as documented alternative, not primary.
- **Netlify Scheduled Functions**: 30-second cap cannot run a 5–15 min
  collector; free plan moved to a 300-credits model.
- **Render**: free Postgres expires after 30 days (not durable); free web
  services spin down (1-min cold starts) and bandwidth dropped to 5 GB/mo
  (2026-04-23).
- **Fly.io**: no free tier for new orgs since 2024-10-07.
- **Railway Free**: $1/mo usage credit ≈ 100 MB RAM-month — insufficient for
  always-on API+DB; no custom domain on free.
- **Vercel**: Hobby is fine for static SPA but FastAPI-as-functions fights
  SQLAlchemy pooling/cold starts; non-commercial clause.
- **Self-hosted n8n / DO droplet**: $4+/mo and self-managed — over ceiling.

## Cost guards built into the app

- Bounded per-run fetch quotas (`BACKLOG_MAX_DATES_PER_RUN`, capacity share).
- No public endpoint can trigger ingestion or paid work (AGENTS.md security
  rules); rate limits + pagination caps bound API cost.
- HTTP client: zero retries, ≥2 s/host politeness, response size caps.
- Static assets immutable-cached; API summaries cached 60 s.
- Billing alert at $1 on any cloud account used.
