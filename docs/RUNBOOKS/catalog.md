# Runbook: catalog

## Target

| | |
| --- | --- |
| Spreadsheet | `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0` |
| Name | "Site Visit Catalog — Live Workflow" |
| Owner | `dmyers@shircapital.com` |
| Shared to | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` as **writer** |
| Tab | `Catalog` — created by the code if absent |
| Never touched | the default `Sheet1` tab |

The Sheet is operator-owned on purpose. The service account is not a member of the Shared
Drive and must not write a non-media file into the immutable source-media folder, so a
human creates the Sheet and shares it. See
[ADR-0007](../decisions/0007-catalog-sheet-ownership-and-location.md).

The Sheet is an **output**, not the system of record. The durable evidence is the GCS run
tree; the Sheet is the readable view.

## Draft catalog schema (the original 15 fields)

These remain the first 15 columns, in this order, and are also the `CatalogDraft`
contract used by the single-step `publish-catalog` command.

| Field | Purpose |
| --- | --- |
| `row_key` | Idempotent key, such as immutable Drive file ID |
| `visit_drive_id` | Selected visit manifest Drive identifier |
| `source_asset_identifier` | Immutable source Drive identifier |
| `original_drive_name` | Original evidence name |
| `drive_link` | Source link |
| `wav_gcs_uri` / `transcript_output_gcs_uri` | Retained transcription artifact locations |
| `transcript_status` | Completed, failed, or `NEEDS_REVIEW` |
| `location` | L1 proposal field |
| `issue_description` | L1 proposal field |
| `suggested_filename` | Proposed only; not a rename command |
| `confidence_note` | L1 uncertainty disclosure |
| `catalog_status` | Always `DRAFT` until explicit publication approval |
| `transcription_started_at` / `transcription_completed_at` | Processing audit timestamps |

> Column-name clarification: the actual header written to the Sheet is
> `transcription_status`. The row above names it `transcript_status`; the Sheet header is
> authoritative.

## Full catalog row (schema version 2.0)

`process-folder` Gate 5 writes a wider row. The full header order is exactly the 15 above
followed by the Gate 5 additions, so the two read side by side:

| Field | Purpose |
| --- | --- |
| `catalog_schema_version` | `2.0` |
| `run_id` | Which run last wrote this row |
| `asset_status` | `CATALOGUED`, `NEEDS_REVIEW`, `FAILED`, or `DRY_RUN` |
| `l1_status` | `VALIDATED` or `NOT_RUN` |
| `l2_status` | The L2 `enrichment_status`, or `NOT_RUN` |
| `l2_trade` / `l2_area_type` / `l2_severity` / `l2_recommended_action` / `l2_enrichment_note` | L2 enrichment fields |
| `l3_status` | The L3 `refinement_status`, or `NOT_RUN` |
| `l3_responsible_party` / `l3_urgency_window` / `l3_disputed_prior_fields` / `l3_refinement_note` | L3 refinement fields; `l3_disputed_prior_fields` is comma-joined |
| `transcript_gcs_uri` | The plain-text transcript object |
| `evidence_gcs_prefix` | The asset's whole GCS evidence prefix for this run |
| `drive_rename_decision` | Always `PROPOSED_ONLY_AWAITING_HUMAN_APPROVAL` |
| `updated_at` | UTC timestamp of this upsert |

A layer that did not run is recorded as `NOT_RUN` with blank values — **never** as an
invented finding. A `NEEDS_REVIEW` transcript therefore produces a real row with no
extraction content, which is the honest outcome.

## Procedure (cloud-native)

Gate 5 runs automatically at the end of each asset in `process-folder`:

1. The tab named by `CATALOG_TAB_NAME` (or `--sheet-name`) is created if it is missing.
   `Sheet1` is left alone.
2. The full row is built from the manifest, the transcription record, and whichever
   extraction layers validated. A structural drift between the row and
   `FULL_CATALOG_HEADERS` is a hard error.
3. `catalog-row.json` is written to GCS **before** the Sheet is touched, so the row
   exists durably even if Sheets fails.
4. The row is **upserted by `row_key`** — the immutable Drive asset ID. An existing row
   is updated in place; a new asset appends. Nothing is ever deleted.
5. `catalog-upsert-record.json` records the outcome.

## Reading and reviewing

Sort or filter by `asset_status` first. `CATALOGUED` rows are complete; `NEEDS_REVIEW`
rows are honest partials that need a human; `FAILED` rows mean that asset threw and the
run continued without it. Cross-check any row against `evidence_gcs_prefix` for the
transcript, the probe record, and the raw L1/L2/L3 responses.

`suggested_filename` is a **proposal**. Nothing in the pipeline renames Drive media.
Applying one requires the separate `site-visit rename-drive` command with an explicit
approval record, by a human decision.

## Idempotency and re-runs

Because the key is the immutable Drive asset ID, re-processing an asset **updates** its
row instead of duplicating it. Use a new `--run-id` for each re-run (GCS objects are
write-once and a reused run ID will fail the generation precondition); the row's `run_id`
column then tells you which run last wrote it.

Validate the L1 JSON exactly against its approved schema. Upsert one draft row by
`row_key`; retain the original Drive name and ID. Publish or rename only after a human
records approval.

## How to update this later

Version the schema before adding fields and retain the idempotency key across migrations.
Adding a column means **appending** to `FULL_CATALOG_HEADERS` in
`src/site_visit_workflow/catalog.py` — never inserting in the middle, never removing one,
since existing sheets already carry the old order — plus extending `build_catalog_row`, a
width test, and this table. A column removal is a catalog migration and needs an ADR.
