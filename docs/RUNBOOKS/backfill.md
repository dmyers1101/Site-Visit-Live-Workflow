# Runbook — backfill / manual portfolio run

Never run two portfolio executions at the same time (Speech/Vertex quota, duplicate work).
Pause the scheduler first if a manual batch could overlap 02:00 ET:
`gcloud scheduler jobs pause site-visit-nightly-trigger --location=us-central1`.

## 1. Inventory (read-only) — manual job, default args
```powershell
gcloud run jobs execute site-visit-workflow --region=us-central1 --wait `
  --args=list-portfolio,--catalog-sheet-id,1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o
```
Read `pending_count` and the per-visit table in the execution log.

## 2. One batch WITH renames — run the nightly job by hand
Its standing args are exactly one 60-clip batch (`--rename-approved --report`):
```powershell
gcloud run jobs execute site-visit-nightly --region=us-central1 --wait
```
Repeat until inventory shows `pending_count: 0` (NEEDS_REVIEW clips count as done).

## 3. A batch WITHOUT renames, or targeted — manual job with explicit args
The manual job has no `RENAME_APPROVED`, so it can never rename:
```powershell
gcloud run jobs execute site-visit-workflow --region=us-central1 --wait `
  --args=process-portfolio,--catalog-sheet-id,1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o,--max-clips,60,--report,--visit-id,VISIT_FOLDER_ID
```
`--dry-run` exercises Drive/ffmpeg/GCS only (no Speech, Vertex, Sheets, renames).

## 4. Record it
New folder `docs/evidence/<date>-<run-id>/RESULT.md`: execution name, image, args, counts.
