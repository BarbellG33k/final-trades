# Cloud Run deployment (alternative to GitHub Actions cron).
# PREPARED CONFIG ONLY — nothing here provisions infrastructure.
# Cost: $0 within always-free tiers (see docs/cost-model.md).
# Requires: GCP project + billing account (card on file even for $0),
# Artifact Registry or Docker Hub image, Neon Postgres DATABASE_URL secret.
#
# Build & push:
#   docker build -f deploy/Dockerfile -t "$REGION-docker.pkg.dev/$PROJECT/final-trades/api:latest" .
#   docker push "$REGION-docker.pkg.dev/$PROJECT/final-trades/api:latest"
#
# Deploy API service (from api-service.yaml, edit image first):
#   gcloud run services replace api-service.yaml
#
# Deploy collector job (edit image in collector-job.yaml first):
#   gcloud run jobs replace collector-job.yaml
#
# Schedules (Cloud Scheduler: 3 free jobs per billing account):
#   gcloud scheduler jobs create http ft-collect-am \
#     --schedule="17 13 * * *" --time-zone=UTC \
#     --http-method=POST \
#     --uri="https://run.googleapis.com/v1/projects/$PROJECT/locations/$REGION/jobs/ft-collector:run" \
#     --oauth-service-account-email=$SA
#   gcloud scheduler jobs create http ft-collect-pm \
#     --schedule="17 23 * * 1-5" --time-zone=UTC ... (same target)
#   gcloud scheduler jobs create http ft-performance \
#     --schedule="47 23 * * 1-5" --time-zone=UTC \
#     --uri="https://run.googleapis.com/v1/projects/$PROJECT/locations/$REGION/jobs/ft-performance:run" ...
#
# Secret (DATABASE_URL) — create once:
#   printf '%s' "$NEON_DSN" | gcloud secrets create FT_DATABASE_URL --data-file=-
#   gcloud secrets add-iam-policy-binding FT_DATABASE_URL \
#     --member="serviceAccount:$RUN_SA" --role="roles/secretmanager.secretAccessor"
