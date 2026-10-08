# Runbook — AppFolio work orders (ADR 0015)

Everything here is run by a human once; afterwards it runs in the cloud.

| Piece | Runs as | Scheduled | Writes |
| --- | --- | --- | --- |
| `wo-candidates` | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` | Cloud Scheduler `site-visit-workorders-candidates`, 06:00 ET | `WorkOrders` tab (append only) |
| Forms (Apps Script) | `dmyers@shircapital.com` | Apps Script trigger `hourly` | `WorkOrders` decision columns; Gmail |
| `wo-run` | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` | Cloud Scheduler `site-visit-workorders-run`, 08:00 ET | `gs://shir-sitevisit-staging/runs/workorders/<run>/`, `WorkOrders`, AppFolio |

## 1. Secrets (you, local terminal — values never go in chat or the repo)

```bash
printf '%s' 'PASTE_CLIENT_ID' | gcloud secrets create appfolio-v0-client-id --project=shir-sitevisit --data-file=-
```
Repeat for `appfolio-v0-client-secret` and `appfolio-v0-developer-id`, then:
```bash
for s in appfolio-v0-client-id appfolio-v0-client-secret appfolio-v0-developer-id; do gcloud secrets add-iam-policy-binding $s --project=shir-sitevisit --member=serviceAccount:site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor; done
```

## 2. Job (same image as the nightly job)

Build first (`docs/DEPLOYMENT.md`). The nightly job also runs `:latest`, so the rebuild
ships to it too; this change adds code only behind the new commands.

```bash
gcloud run jobs deploy site-visit-workorders --project=shir-sitevisit --region=us-central1 --image=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:latest --service-account=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com --memory=1Gi --task-timeout=1800s --max-retries=0 --set-secrets=AF_V0_CLIENT_ID=appfolio-v0-client-id:latest,AF_V0_CLIENT_SECRET=appfolio-v0-client-secret:latest,AF_V0_DEVELOPER_ID=appfolio-v0-developer-id:latest --set-env-vars=GOOGLE_CLOUD_PROJECT=shir-sitevisit,GCS_STAGING_BUCKET=shir-sitevisit-staging,CATALOG_SHEET_ID=1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o,SITE_VISIT_ENVIRONMENT=deployed --args=wo-run
```
`WORK_ORDERS_LIVE` is deliberately absent: every run is a dry run until it is added.

## 3. Order of first use

1. `--args=wo-candidates,--dry-run` → read the preview in the log.
2. `--args=wo-candidates` → rows appear in `WorkOrders` as `PENDING_REVIEW`.
3. Fill `AppFolioPropertyMap` (catalog_property → AppFolio property UUID, `reviewed=YES`).
4. Apps Script: set properties with `DRY_RUN=1`, run `hourly`, read the log; then clear
   `DRY_RUN`, run `installTrigger`.
5. Answer one form. `wo-run` (dry) → read `plan.json`; approve one payload.
6. Add `WORK_ORDERS_LIVE=1` to the job; run once with
   `--args=wo-run,--live,--max-creates,1,--wo-key,<key>`; check the work order in AppFolio.
7. Only then create the two Cloud Scheduler triggers.

Writes are refused 9PM–4AM Pacific (AppFolio maintenance). A created work order cannot be
deleted through the API — cancel it in AppFolio.
