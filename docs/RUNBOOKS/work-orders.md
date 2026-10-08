# Runbook — AppFolio work orders (ADR 0015)

Everything here is run by a human once; afterwards it runs in the cloud.

| Piece | Runs as | Scheduled | Writes |
| --- | --- | --- | --- |
| `wo-candidates` (job `site-visit-workorders-candidates`) | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` | Cloud Scheduler `site-visit-workorders-candidates-trigger`, 06:00 ET | `WorkOrders` tab (append only) |
| Forms (Apps Script) | `dmyers@shircapital.com` | Apps Script trigger `hourly` | `WorkOrders` decision columns; Gmail |
| `wo-run` (job `site-visit-workorders`) | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` | Cloud Scheduler `site-visit-workorders-trigger`, 08:00 ET | `gs://shir-sitevisit-staging/runs/workorders/<run>/`, `WorkOrders`, AppFolio |

## 1. Secrets (you, LOCAL Git Bash — values never go in chat, history or the repo)

Docs: `docs/research/gcp/secret-manager-and-run-jobs.md` (pulled 2026-10-08).
Run once per secret; `read -rs` hides the value and keeps it out of shell history.

```bash
for s in appfolio-v0-client-id appfolio-v0-client-secret appfolio-v0-developer-id; do gcloud secrets create $s --project=shir-sitevisit --replication-policy=automatic </dev/null; read -rsp "value for $s: " V; echo; printf '%s' "$V" | gcloud secrets versions add $s --project=shir-sitevisit --data-file=-; unset V; gcloud secrets add-iam-policy-binding $s --project=shir-sitevisit --member=serviceAccount:site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor </dev/null; done
```

Env-var secrets are pinned (deployed 2026-10-08: client-id `:2`, client-secret `:2`, developer-id `:1`) (docs advise numbered versions). Rotating a
credential = add version 2, then redeploy the jobs with `:2`.

## 2. Image and jobs

The nightly job runs a **tagged** image (`site-visit:l2-20261008-4a67689`), so a new tag
does not touch it.

```bash
gcloud builds submit --project=shir-sitevisit --config=infra/cloudbuild.yaml --substitutions=_IMAGE=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:wo-20261008-23c897f .
```

Two jobs, because Scheduler cannot override args (see `cloud-scheduler-run-jobs.md`).
Common flags (copy into both):

```bash
COMMON="--project=shir-sitevisit --region=us-central1 --image=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:wo-20261008-23c897f --service-account=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com --memory=1Gi --cpu=1 --task-timeout=1800s --max-retries=0 --tasks=1 --parallelism=1 --set-env-vars=SITE_VISIT_ENVIRONMENT=deployed,GOOGLE_CLOUD_PROJECT=shir-sitevisit,SITE_VISIT_RUNTIME_SERVICE_ACCOUNT=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com,GCS_STAGING_BUCKET=shir-sitevisit-staging,GCS_STAGING_PREFIX=site-visit-staging,CATALOG_TAB_NAME=Catalog,VERTEX_LOCATION=us-central1,VERTEX_MODEL=gemini-2.5-flash,CATALOG_SHEET_ID=1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o"
```

```bash
gcloud run jobs deploy site-visit-workorders-candidates $COMMON --args=wo-candidates
```

```bash
gcloud run jobs deploy site-visit-workorders $COMMON --set-secrets=AF_V0_CLIENT_ID=appfolio-v0-client-id:2,AF_V0_CLIENT_SECRET=appfolio-v0-client-secret:2,AF_V0_DEVELOPER_ID=appfolio-v0-developer-id:1 --args=wo-run
```

`WORK_ORDERS_LIVE` is deliberately absent: every `wo-run` is a dry run until it is added.

## 3. Order of first use

1. `gcloud run jobs execute site-visit-workorders-candidates --region=us-central1 --wait --args=wo-candidates,--dry-run`
   → read the preview in the log (writes nothing).
2. Same without `,--dry-run` → `WorkOrders` + `AppFolioPropertyMap` tabs appear; rows are `PENDING_REVIEW`.
3. Fill `AppFolioPropertyMap` (catalog_property → AppFolio property UUID, `reviewed=YES`).
4. Apps Script: set properties with `DRY_RUN=1`, run `hourly`, read the log; then clear
   `DRY_RUN`, run `installTrigger`.
5. Answer one form. `wo-run` (dry) → read `plan.json`; approve one payload.
6. `gcloud run jobs execute site-visit-workorders --region=us-central1 --wait` (dry) → read
   `plan.json`; approve one payload.
7. `gcloud run jobs update site-visit-workorders --region=us-central1 --update-env-vars=WORK_ORDERS_LIVE=1`,
   then execute once with `--args=wo-run,--live,--max-creates,1,--wo-key,<key>`; check it in AppFolio.
8. Only then the schedulers (invoker = the existing `site-visit-scheduler@` SA):

```bash
for j in site-visit-workorders-candidates site-visit-workorders; do gcloud run jobs add-iam-policy-binding $j --project=shir-sitevisit --region=us-central1 --member=serviceAccount:site-visit-scheduler@shir-sitevisit.iam.gserviceaccount.com --role=roles/run.invoker; done
```

```bash
gcloud scheduler jobs create http site-visit-workorders-candidates-trigger --project=shir-sitevisit --location=us-central1 --schedule="0 6 * * *" --time-zone="America/New_York" --uri="https://run.googleapis.com/v2/projects/shir-sitevisit/locations/us-central1/jobs/site-visit-workorders-candidates:run" --http-method=POST --oauth-service-account-email=site-visit-scheduler@shir-sitevisit.iam.gserviceaccount.com
```

```bash
gcloud scheduler jobs create http site-visit-workorders-trigger --project=shir-sitevisit --location=us-central1 --schedule="0 8 * * *" --time-zone="America/New_York" --uri="https://run.googleapis.com/v2/projects/shir-sitevisit/locations/us-central1/jobs/site-visit-workorders:run" --http-method=POST --oauth-service-account-email=site-visit-scheduler@shir-sitevisit.iam.gserviceaccount.com
```

The scheduled `wo-run` uses the job's standing args (`wo-run`, cap 1). Raise the cap with
`gcloud run jobs update site-visit-workorders --args=wo-run,--live,--max-creates,10` only
after the first live results are reviewed.

Writes are refused 9PM–4AM Pacific (AppFolio maintenance). A created work order cannot be
deleted through the API — cancel it in AppFolio.
