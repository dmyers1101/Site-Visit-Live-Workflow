# Runbook — nightly operations

## What runs
| | |
| --- | --- |
| Scheduler | Cloud Scheduler job `site-visit-nightly-trigger`, project `shir-sitevisit`, `us-central1` |
| Schedule | `0 2 * * *` America/New_York (02:00 ET daily) |
| Calls | Cloud Run job `site-visit-nightly` (`:run`), authenticated as `site-visit-scheduler@shir-sitevisit.iam.gserviceaccount.com` |
| Runs as | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |
| Command | `process-portfolio --max-clips 60 --rename-approved --report` over master folder `1UkjYIHnSs-igeOy9k-Iw_d1-bEnH-mwN` |
| Writes | Master Sheet `1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o` (tabs `Catalog`, `Reports`); one "<Property> Site Visit Reports" Doc per Property folder; renames CATALOGUED clips; evidence in `gs://shir-sitevisit-staging/site-visit-staging/<run-id>*` |

## What it does each night
1. Walks the master folder; every folder with videos is a visit.
2. Skips clips already `CATALOGUED` / `NEEDS_REVIEW` (or FAILED 3×).
3. Processes up to 60 new clips (transcribe → L1/L2/L3 → Sheet → rename).
4. Rewrites the report tab for every visit that got new rows (newest on top).

## Morning check (2 minutes)
```powershell
gcloud run jobs executions list --job=site-visit-nightly --region=us-central1 --limit=3
```
Then read the summary line:
```powershell
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="site-visit-nightly" AND jsonPayload.gate="portfolio-summary"' --limit=1 --format=json
```
Look at each visit's `status`, `processed`, `status_counts`, and `report.status`.

## Human queue
Filter the master Sheet `Catalog` tab on `asset_status = NEEDS_REVIEW`. Typical causes: empty transcript
(silent clip), or an L2/L3 validation rejection. To force a reprocess of one clip, clear its
`asset_status` cell; it is picked up next night.

## When something fails
| Symptom | Meaning | Action |
| --- | --- | --- |
| visit `status: FAILED` | whole visit errored (e.g. Drive permission) | read `error`; re-run manually (`backfill.md`) |
| `report.status: FAILED` | report only; clips are saved | nothing — the next night retries it automatically |
| clips `FAILED` | transient per-clip error | retried nightly up to 3 attempts (`attempt_count`) |
| execution timed out | >2h | lower `--max-clips` on the job (`change-guide.md`) |
| Speech/Vertex 429 | quota | calls back off automatically; if persistent, request quota increase |

## Pause / resume
```powershell
gcloud scheduler jobs pause site-visit-nightly-trigger --location=us-central1
gcloud scheduler jobs resume site-visit-nightly-trigger --location=us-central1
```
