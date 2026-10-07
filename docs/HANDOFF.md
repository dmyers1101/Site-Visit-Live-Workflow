# Handoff — Phase 2 cloud-native Site Visit workflow

**Written:** 2026-09-17
**For:** a future session or a different person, on a different machine, with no
context from the build.

This document is the single starting point. Read it before running anything.

## Portfolio + nightly (2026-09-29) — read this first

Production scope is now the **whole master folder**, processed **nightly**.
ADRs 0009–0012; runbooks `RUNBOOKS/nightly-operations.md`, `backfill.md`, `change-guide.md`.

| Thing | Value |
| --- | --- |
| Master video folder | `1UkjYIHnSs-igeOy9k-Iw_d1-bEnH-mwN` (State / Property / [Group] / Visit) |
| Master catalog Sheet | `1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o` — tabs `Catalog`, `Reports` |
| Report Docs | "<Property> Site Visit Reports" in each Property folder; one tab per visit |
| Nightly job | Cloud Run `site-visit-nightly` — `process-portfolio --max-clips 60 --rename-approved --report` |
| Manual job | Cloud Run `site-visit-workflow` — safe default `list-portfolio`; pass `--args` per run |
| Schedule | Cloud Scheduler `site-visit-nightly-trigger`, `us-central1`, `0 2 * * *` America/New_York |
| Runs as | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |
| Triggered as | `site-visit-scheduler@shir-sitevisit.iam.gserviceaccount.com` (`run.invoker` on the nightly job only) |
| Output | master Sheet + property Docs in Drive; renames CATALOGUED clips in place; evidence in `gs://shir-sitevisit-staging` |

Safety rule 2 is amended by ADR 0012: the nightly job's configuration is the standing
rename approval. Nothing runs on a workstation.

## What this is

A cloud-native pipeline that turns narrated site-visit videos in a Google Drive
folder into transcripts, structured extractions, and rows in a Google Sheets
catalogue. Everything runs inside a Cloud Run Job. No media ever touches an
operator workstation.

## The hard safety rules

1. **Never delete anything** — not Drive files, GCS objects, Sheet rows or tabs,
   logs, or evidence. The service account is provisioned with no delete
   permission anywhere, deliberately (ADR 0005). If something fails with a
   delete-permission error, that is a signal the code is doing something wrong;
   do not grant delete to make it pass.
2. **Never rename a Drive source video automatically.** Suggested filenames are
   proposals. A rename requires an explicit human approval record.
   **Amended 2026-09-18 (wording corrected, rule intact):** `process-folder`
   can now rename, in Gate 6, but only when BOTH the `RENAME_APPROVED`
   environment flag and the `--rename-approved` CLI flag are present, and only
   for an asset that reached CATALOGUED with a validated L1 record. Without
   both, every suggested name stays a proposal exactly as before. The
   catalogue keeps the discovery-time `original_drive_name`, and the row key is
   the immutable Drive file ID, so a rename cannot break idempotency.
3. **The only runtime identity is**
   `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`, attached
   directly to the Cloud Run Job. No service-account key file, no impersonation,
   no personal Drive OAuth, no `GOOGLE_APPLICATION_CREDENTIALS`, no substitute
   service account.
4. **Your human account is the deployer, never the Drive runtime identity.** It
   builds images and starts jobs. It does not read Drive on the pipeline's
   behalf.
5. **Never widen access to make an error disappear.** Record the exact error and
   the least-privilege fix.

## Where things live

| Thing | Location |
| --- | --- |
| Primary working folder | `<user home>\My Drive\Site Visit App\apps\live-workflow` (varies by device, e.g. `C:\Users\SHIRA\…`, `C:\Users\dmyer\…`) |
| GitHub | `dmyers1101/Site-Visit-Live-Workflow`, branch `main` |
| GCP project | `shir-sitevisit` (number `847827326811`) |
| Cloud Run Job | `site-visit-workflow`, region `us-central1` |
| Test video library (Drive) | `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` — "2026-08 Executive - Parth Vaidya" |
| Staging bucket | `gs://shir-sitevisit-staging` (US, uniform access, no delete) |
| Catalog Sheet (current; SA-created in Shared Drive 2026-09-18) | `1GW3fg8IeobZn9uhs_4W5yOUUURISI0Ll0xRYhpOu22U` |
| Report Doc (SA-created 2026-09-18) | `1l2htL4V3Lyy8nI1jiw00nr-pCM-qEWH6Eh9eN4W4ZTU` |
| Legacy Catalog Sheet (09-17 runs; individually owned) | `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0`, tab `Catalog` |
| Image repo | `us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit` |

The local folder and GitHub `main` hold the same files. Work happens on `main`.
The former build branch `agents/pasted-text-processing` is merged and behind
`main`; do not use it. Note that Google Drive sync has twice reverted files in one worktree to
the other's copy — if a file looks like it lost content, check `git diff HEAD`
before trusting the working copy.

## Source library boundary

The test folder holds **direct media children and zero subfolders**: 19 items,
16 `video/quicktime` and 3 `image/heif`. The HEICs are excluded with a recorded
reason. Any code that discovers work by listing *subfolders* will find nothing
here — the boundary constant is `DIRECT_MEDIA_CHILDREN`.

## The pipeline

`site-visit process-folder` runs five gates, sequentially, one asset at a time,
continuing past a single asset's failure:

| Gate | Does | Writes |
| --- | --- | --- |
| 1 discovery | Lists immediate children, classifies, builds the manifest | `manifest.json` |
| 2 media | Reads Drive bytes into the container, ffprobe, mono 16 kHz WAV | `media-preparation.json`, the WAV |
| 3 transcription | One Chirp `BatchRecognize` per WAV; empty transcript retries once then `NEEDS_REVIEW` | transcript + transcription record |
| 4 extraction | Vertex L1 → L2 → L3, each gated on the previous validating | per-layer prompt/response evidence |
| 5 catalog | Upserts one Sheet row per asset, keyed on the immutable Drive asset ID | catalog row |
| 6 rename (2026-09-18) | Renames each CATALOGUED asset to its suggested filename — ONLY with both approvals | per-asset rename record |
| 7 report (2026-09-18) | One Vertex call over the run's in-memory catalogue rows; inserts the narrative into a Google Doc | report record, Doc text |

Gate 7 runs after Gate 6 so the report can name the new filenames. A failure in
Gate 6 or Gate 7 is recorded and the run continues; neither can fail the run.

Useful flags: `--limit N`, `--asset-id ID`, `--dry-run` (skips Chirp/Vertex/
Sheets but still exercises Drive, ffmpeg and GCS), `--run-id`, `--prompts-dir`,
`--rename-approved`, `--report`, `--catalog-sheet-id`, `--report-doc-id`.

**Output files are self-provisioned (2026-09-18).** `CATALOG_SHEET_ID` and
`REPORT_DOC_ID` are OPTIONAL for `process-folder`: when either is empty the run
creates that file in `DRIVE_OUTPUT_PARENT_ID` (default: the configured Drive
folder) and reports the new ID in the `"gate": "outputs"` log line and in the
run summary. The Sheet ID is therefore an OUTPUT of a run, not only an input.
`publish-catalog` still requires a pre-existing `CATALOG_SHEET_ID`.

## Running it

See `docs/DEPLOYMENT.md` for exact copy-pasteable commands and
`docs/RUNBOOKS/full-pipeline.md` for the end-to-end procedure. The short form:

```bash
# verify authorization first — read-only, changes nothing
gcloud run jobs deploy site-visit-workflow ... --args=auth-preflight
gcloud run jobs execute site-visit-workflow --region=us-central1 --async

# then the pipeline
gcloud run jobs deploy site-visit-workflow ... --args=process-folder,--limit,1
```

**Sizing matters.** Cloud Run's `/tmp` is in-memory and counts against the
memory limit, and the work directory is never cleaned. Use `--memory=8Gi
--cpu=2 --task-timeout=3600s`. 1Gi/600s will OOM or time out on 16 videos.

## Prompts are versioned governance artifacts

`prompts/l1-extraction.md` (1.3.0), `l2-enrichment.md` (1.1.0),
`l3-refinement.md` (1.2.0) are read from disk at runtime and are shipped in the
image by `COPY prompts ./prompts`. Changing a prompt means bumping its version
and updating the validator and tests first. The layer boundaries are enforced in
`src/site_visit_workflow/models.py`, not only in prompt text, because the pilot
demonstrated prompt text alone is insufficient (ADR 0008).

L1 may emit only location, issue description, suggested filename, confidence
note. L2 adds trade, area type, severity (integer 1–4), recommended action. L3
adds responsible party and urgency window and may **not** overwrite upstream
values — it reports disagreement via `disputed_prior_fields`.

## Current verified state (2026-09-18)

The pipeline has been run end to end against the full test library.

| Run | Scope | Result |
| --- | --- | --- |
| `20260917T071718Z` | 1 asset | All five gates passed |
| `20260917T072151Z` | 16 assets | 13 catalogued, 3 needs-review |
| `20260917T073809Z` | 16 assets | 9 failed on Speech 429 quota — fixed with backoff |
| `20260917T075400Z` | 16 assets | **14 catalogued, 2 needs-review, 0 failed** |
| `20260918T100802Z` | 16 assets, `--rename-approved --report` | 14 catalogued + renamed, 2 needs-review, report Doc written — `docs/evidence/20260918-e2e-full-run/RESULT.md` |

The catalog Sheet holds exactly 16 rows, one per video, after four runs. Every
upsert in the final run was an UPDATE, so the idempotent row key works.

The two needs-review assets are `IMG_3662.MOV` (empty transcript after one
retry) and `IMG_3667.MOV` (L3 returned a prior-layer record id that did not
match its L2 record, so the traceability validator rejected it). Both are
guardrails firing correctly, not defects.

**Do not re-run the full library twice within about 30 minutes** — that exceeds
the project's Speech-to-Text quota. The poll loop now backs off rather than
failing, but the underlying quota is still finite.

## Known open items

- **`trade` vocabulary is closed at 8 values** and has real gaps: pest control,
  painting, drywall, restoration. Interim rule is nearest value plus an
  explanation in `enrichment_note`. Widening needs an ADR.
- **No GCS lifecycle policy.** Artifacts accumulate and the service account
  cannot delete them. Cleanup is a separate, human-authorized action (ADR 0005).
- **Catalog Sheet ownership — resolved for new runs (2026-09-18):** the SA now
  creates the Sheet/Doc in the Shared Drive. The legacy `158eA2…` Sheet is still
  individually owned.
- **Resolved 2026-09-29 — defects from the 09-18 run** (see its RESULT.md):
  the asset ID is stripped from filenames, report counts are written by code,
  Gate 6 de-duplicates sibling names, and reports now go to per-property Docs
  with one tab per visit (newest on top) instead of one append-only Doc.
- **Diagrams under `docs/diagrams/` are stale** — they predate `process-folder`
  and still show the single-asset, approval-per-write flow.
- **Corrected 2026-09-18:** the service account CAN create and rename files in
  the Shared Drive (`canAddChildren: true`). `drives.get` returning 404 only
  means it cannot enumerate the drive object, not that it cannot write.

## How to update this later

Update this file whenever a resource ID, identity, boundary, or safety rule
changes. Record every live run in a new dated directory under `docs/evidence/`;
never overwrite an existing one.
