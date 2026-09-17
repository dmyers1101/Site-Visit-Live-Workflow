# Runbook: full pipeline (`process-folder`)

## Purpose

Run the configured Drive folder end to end in one Cloud Run Job execution: manifest,
media preparation, transcription, three extraction layers, and one catalog row per asset.

Media never touches an operator workstation. Drive -> container -> GCS, entirely inside
the job.

## Command surface

```text
site-visit process-folder [--limit N] [--asset-id ID] [--dry-run] [--run-id ID]
                          [--sheet-name NAME] [--prompts-dir DIR] [--work-dir DIR]
                          [--poll-timeout-seconds N] [--output PATH]
```

| Flag | Default | Effect |
| --- | --- | --- |
| `--limit N` | all | Process at most the first N manifest assets |
| `--asset-id ID` | all | Process exactly one Drive asset ID |
| `--dry-run` | off | Gates 1–2 only. Chirp, Vertex and Sheets are not contacted, and `CATALOG_SHEET_ID` is not required |
| `--run-id ID` | generated UTC stamp | The GCS evidence prefix segment and the catalog `run_id` |
| `--sheet-name NAME` | `CATALOG_TAB_NAME` (`Catalog`) | Catalog tab; created if absent |
| `--prompts-dir DIR` | `prompts` | Where `l1-extraction.md`, `l2-enrichment.md`, `l3-refinement.md` are read at runtime |
| `--work-dir DIR` | fresh temp dir | Container-local staging. Never cleaned up — the ephemeral filesystem disappears with the execution |
| `--poll-timeout-seconds N` | `1800` | Chirp operation poll ceiling per attempt |
| `--output PATH` | none | Also write the run summary JSON to a container-local path |

## The five gates

| Gate | Action | Failure behaviour |
| --- | --- | --- |
| 1 | Discovery: classify direct children, build and upload `manifest.json` | Fails the **whole run** if no supported video child exists — nothing is written |
| 2 | Stage from Drive, ffprobe, mono 16 kHz PCM WAV, verify, SHA-256, upload | Asset marked `FAILED`; run continues |
| 3 | Chirp `BatchRecognize`, poll, empty-transcript policy (one retry) | Empty twice -> `NEEDS_REVIEW`, Gate 4 skipped, row still written |
| 4 | L1 -> L2 -> L3 on Vertex, each gated on the previous | A failed layer is recorded in `layer_errors`; validated upstream layers are kept |
| 5 | Build the full row and upsert it by Drive asset ID | Asset marked `FAILED`; the row JSON is already in GCS |

The loop is **sequential by design** — one asset at a time, conservative concurrency of
one — and a single asset's failure never ends the run.

## Procedure

### 1. Pre-flight

```powershell
gcloud run jobs describe site-visit-workflow --project=shir-sitevisit --region=us-central1
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=auth-preflight
```

Confirm: `matches_designated_identity: true`; Drive folder resolves with
`canDownload: true` and `canDelete: false`; GCS holds create/get/list and **not** delete;
Sheets reachable. Confirm the job has `--memory=8Gi --cpu=2 --task-timeout=3600s` — the
old 1Gi/600s configuration will OOM or time out on 16 videos.

### 2. Cheap trial

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=process-folder,--dry-run,--limit,1,--run-id,20260917-dry-01
```

Confirms Drive download, ffmpeg, the audio contract, and GCS writes without spending a
Chirp or Vertex call. Expect `supported_count: 16`, `excluded_count: 3` (the HEICs), and
one asset at `DRY_RUN`.

### 3. One real asset

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=process-folder,--limit,1,--run-id,20260917-trial-01
```

Review the row and its evidence before spending the whole folder.

### 4. Full run

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=process-folder,--run-id,20260917-full-01
```

Always pass an explicit, meaningful `--run-id`. It is the only handle for finding that
run's artifacts later.

## What to check after a run

1. **The run summary.** The last log line is `"gate": "run-summary"`; the same object is
   at `gs://shir-sitevisit-staging/site-visit-staging/<RUN_ID>/run-summary.json`.

   ```powershell
   gcloud storage cat gs://shir-sitevisit-staging/site-visit-staging/RUN_ID/run-summary.json
   ```

   Check `status_counts` (how many `CATALOGUED` / `NEEDS_REVIEW` / `FAILED`),
   `selected_asset_count`, `excluded_items`, and that `runtime_service_account`,
   `speech_location`, `vertex_location` and `vertex_model` are the expected values.

2. **The arithmetic.** For the current folder: 19 children = 16 supported + 3 excluded
   HEICs. `selected_asset_count` should be 16 for a full run, and the `status_counts`
   should sum to 16. Any other number means the folder changed or a selector was applied.

3. **The Sheet.** `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0`, tab `Catalog`. One row
   per asset, keyed by Drive asset ID, `run_id` matching this run. Confirm `Sheet1` is
   untouched.

4. **Every non-`CATALOGUED` asset.** Open its `evidence_gcs_prefix` and read
   `transcription-record.json` (was the transcript empty, or did the operation fail?) and
   `prompt-execution/*.json` (which layer failed, and why).

5. **The log**, for anything the summary flattened:

   ```powershell
   gcloud logging read `
     'resource.type="cloud_run_job" AND resource.labels.job_name="site-visit-workflow"' `
     --project=shir-sitevisit --limit=500 --format="value(textPayload)"
   ```

## Failure handling

| Symptom | Diagnosis | Action |
| --- | --- | --- |
| Run ends immediately, no manifest | Gate 1 found no supported video children, or Drive is unauthorized | Run `auth-preflight` and `list-folder-children`. Do not substitute another folder |
| Task killed / OOM | `/tmp` is in-memory and staged media counts against `--memory`; the work dir is never cleaned up | Raise `--memory` (8Gi floor) or split the run with `--limit`, then re-run under a **new** `--run-id` |
| Task timeout | 16 assets sequentially exceeds the task timeout | Raise `--task-timeout` to 3600s, or run in `--limit` batches |
| Asset `FAILED` with a precondition/generation error | The `RUN_ID` was re-used and the object already exists | Re-run with a new `--run-id`. This is the write-once guard working, not a bug |
| Asset `NEEDS_REVIEW`, transcript empty twice | Silent clip, no audio stream, or inaudible narration | Check `media-preparation.json` for `has_audio_stream`. Re-running will not fix a silent source; this is a human finding |
| Asset `NEEDS_REVIEW`, `layer_errors` populated | An extraction layer failed schema validation | Read the layer JSON in `prompt-execution/`. Do not hand-edit the row to fill the gap |
| "L1 prompt file is missing at runtime: prompts/l1-extraction.md" | **[OPEN] known gap:** `infra/Dockerfile` does not copy `prompts/` into the image, so Gate 4 cannot load its runtime prompts | Add `COPY prompts ./prompts` to `infra/Dockerfile`, rebuild and redeploy. See the note in `docs/DEPLOYMENT.md` |
| `l3_skipped_reason` present | L2 was not `ENRICHED`, so L3 was deliberately skipped | Expected behaviour, not a failure |
| Chirp region error | `SPEECH_LOCATION` is not `us` (or `eu`) | Chirp 3 is multi-region only; `us-central1` is invalid there |
| `SPEECH_MODEL=chirp` rejected | The legacy alias is refused on purpose | Set `SPEECH_MODEL=chirp_3` explicitly |
| Sheets failure at Gate 5 | Sharing or tab problem | The row JSON is already in GCS. Fix the share, then re-run that asset with `--asset-id` and a new `--run-id` |

A failed asset is never retried inside the run. Re-run it deliberately:

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=process-folder,--asset-id,DRIVE_ASSET_ID,--run-id,20260917-repair-01
```

Because the catalog key is the immutable Drive asset ID, this updates the existing row
rather than duplicating it.

## Standing constraints

- Nothing is deleted — not a Drive file, not a GCS object, not a Sheets row or tab.
  Artifacts accumulate; cleanup is a separate, human-authorized action.
- No Drive rename. `suggested_filename` is a proposal and
  `drive_rename_decision` is always `PROPOSED_ONLY_AWAITING_HUMAN_APPROVAL`.
- No fabrication. A missing transcript or a failed layer produces `NOT_RUN` and blanks.
- The processing boundary is direct media children; subfolders are excluded with a
  reason, never traversed.

## How to update this later

Adding a gate means adding one private helper in `cmd_process_folder` and one entry in
the per-asset record — not inlining Google calls into the loop — and adding the gate to
the tables here. Keep the loop sequential: conservative concurrency is a documented
requirement, not an oversight. Update the expected counts in "What to check after a run"
whenever the configured folder changes.
