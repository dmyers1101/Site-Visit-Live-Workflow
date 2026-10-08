# Change guide — how to change common things

Start at `docs/HANDOFF.md`. Every code change: tests green → commit to `main` →
rebuild image → update BOTH jobs to the new image → CHANGELOG entry → Drive source copy.

## Build and roll out a new image
```powershell
$IMG = "us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:YYYYMMDD-x"
gcloud builds submit --config=infra/cloudbuild.yaml --project=shir-sitevisit --substitutions=_IMAGE=$IMG .
gcloud run jobs update site-visit-workflow --region=us-central1 --image=$IMG
gcloud run jobs update site-visit-nightly  --region=us-central1 --image=$IMG
```
**Roll back:** run the two `update` lines with the previous tag (see `gcloud artifacts docker images list
us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit --include-tags`).

## Add a property or visit
Nothing to configure. Create `Master / State / Property / <visit folder>` and upload clips.
A new Property gets its own "<Property> Site Visit Reports" Doc automatically.

## Change the schedule
```powershell
gcloud scheduler jobs update http site-visit-nightly-trigger --location=us-central1 --schedule="0 3 * * *" --time-zone="America/New_York"
```

## Change the nightly clip cap
```powershell
gcloud run jobs update site-visit-nightly --region=us-central1 `
  --args=process-portfolio,--root,1UkjYIHnSs-igeOy9k-Iw_d1-bEnH-mwN,--catalog-sheet-id,1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o,--max-clips,40,--rename-approved,--report
```

## Pause renames (keep processing)
```powershell
gcloud run jobs update site-visit-nightly --region=us-central1 --update-env-vars=RENAME_APPROVED=false
```
Suggested names still land in the Sheet. Set back to `true` to resume.

## Edit a prompt (L1/L2/L3/report)
Edit `prompts/<file>.md`: bump **Semantic version**, add a "Changed in" note, update the validator in
`src/site_visit_workflow/models.py` if the schema changes, add/adjust tests, then roll out a new image.
The version + SHA-256 of the prompt used is recorded in every run's evidence.

## Add a catalog column
Append to `FULL_CATALOG_HEADERS` in `catalog.py` (never insert/reorder), extend `build_catalog_row`,
update the column-letter pin in `tests/test_catalog_rows.py`. Removing a column needs an ADR.

## Reprocess a clip
Clear its `asset_status` in the master Sheet `Catalog` tab; the next run picks it up.

## After an L2/L3 prompt change: reprocess a visit (2026-10-08)

Existing rows keep their old L2/L3 values until reprocessed. Per visit, on the
manual job:

1. `--args=reprocess-l2,--visit-id,<visit folder id>,--dry-run` — read the
   `status_transitions` and `changed_rows` in the log; nothing is written.
2. `--args=reprocess-l2,--visit-id,<visit folder id>,--report` — writes the
   L2/L3 columns and rewrites that visit's report tab.
Transcripts, L1, filenames and every other column are never changed.
