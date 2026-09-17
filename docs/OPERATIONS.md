# Operations and maintenance

## Normal procedure (cloud-native, current)

The whole pipeline is one Cloud Run Job execution. Media never reaches an operator
machine.

1. Confirm branch and job configuration
   (`gcloud run jobs describe site-visit-workflow --region=us-central1`).
2. Execute `auth-preflight` and read the JSON record: identity matches the designated
   service account, Drive folder resolves with `canDownload: true`, GCS bucket exists
   with create/get/list held and **delete not held**, Sheets reachable.
3. Execute `process-folder --dry-run --limit 1` as a cheap trial. It does Gate 1 and
   Gate 2 only — manifest, stage, ffprobe, WAV, GCS upload — and contacts neither Chirp,
   Vertex, nor Sheets.
4. Execute `process-folder --limit 1 --run-id <id>` for one real asset end to end.
5. Review the catalog row and the GCS evidence for that asset.
6. Execute `process-folder --run-id <id>` for the whole folder.
7. Review. Apply a descriptive rename only through `rename-drive` with an explicit
   approval record; `process-folder` never renames.

Exact commands: [docs/DEPLOYMENT.md](DEPLOYMENT.md). Step-by-step with failure handling:
[docs/RUNBOOKS/full-pipeline.md](RUNBOOKS/full-pipeline.md).

### What each gate does

| Gate | Action | Evidence written |
| --- | --- | --- |
| 1 | List direct children of the folder, classify supported vs excluded with a stated reason, build the manifest | `<run prefix>/manifest.json` |
| 2 | Stage the source from Drive into the container, `ffprobe`, extract mono 16 kHz PCM s16le WAV, verify the audio contract, SHA-256 both, upload the WAV | `<asset prefix>/media-preparation.json`, `<asset prefix>/audio/attempt-0/<id>.wav` |
| 3 | Submit one Chirp `BatchRecognize` per WAV, poll, read the result, apply the empty-transcript policy | `<asset prefix>/transcription-record.json`, `<asset prefix>/transcript.txt`, `<asset prefix>/speech-output/attempt-N/` |
| 4 | L1 -> L2 -> L3 on Vertex, each layer gated on the previous validating; L3 only for `ENRICHED` L2 | `<asset prefix>/prompt-execution/l1.json`, `l2.json`, `l3.json` |
| 5 | Build the full catalog row and upsert it into the Sheet by Drive asset ID | `<asset prefix>/catalog-row.json`, `<asset prefix>/catalog-upsert-record.json` |

### Historical single-visit procedure (superseded, still valid as manual steps)

The original numbered procedure remains accurate as a description of the *single-step*
CLI commands, which still exist for narrow re-runs and diagnosis. It is superseded as
the normal path by `process-folder`.

1. Confirm Git branch, configuration, and Drive authorization.
2. List only the Shared Folder's immediate subfolders and select one visit.
3. Create and retain a manifest containing the visit ID, original Drive file name/ID/link, MIME type, size, and modified time.
4. Choose one safe candidate video and stage a copy; use `ffprobe` to inspect it and `ffmpeg` to extract mono 16 kHz WAV audio.
5. Upload the WAV to a unique GCS staging path and submit one low-concurrency Chirp BatchRecognize request.
6. Record operation status, timestamps, transcript URI, and errors. Retry an empty transcript once; then set `NEEDS_REVIEW`.
7. Generate a strict-JSON L1 proposal and an idempotent draft catalog row.
8. Obtain human approval before applying a descriptive rename or publishing a catalog row.

Use the named `site-visit` CLI command for each stage. Package import and
`config-check` are offline; `auth-preflight`, `list-folder-children`, `list-visits`,
`process-folder`, `intake`, `stage-video`, `transcribe`,
`rename-drive`, and `publish-catalog` are deliberate external-call boundaries.
Persist every generated manifest, transcription record, L1 payload/result, and
approval record in an approved operational location — for `process-folder` that happens
automatically in GCS.

> Step 2's "select one visit subfolder" does not apply to the current folder: folder
> `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` has zero subfolders and 19 direct media children,
> and the processing boundary is `DIRECT_MEDIA_CHILDREN`.

## Reading results

**The Sheet** — `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0`, tab `Catalog`. One row per
Drive asset. Start with `asset_status`:

| `asset_status` | Meaning |
| --- | --- |
| `CATALOGUED` | Every gate that was supposed to run did, and the row carries the extraction. |
| `NEEDS_REVIEW` | Honest partial. Either the transcript was empty after one retry (no extraction, no findings invented), or an extraction layer failed — see `layer_errors` in the log and `l1_status`/`l2_status`/`l3_status` in the row. |
| `FAILED` | That asset threw. The run continued; other assets are unaffected. |
| `DRY_RUN` | `--dry-run` was set; Chirp, Vertex and Sheets were not contacted. |

`l2_status`/`l3_status` of `NOT_RUN` means the layer genuinely did not run — a blank
value is never a fabricated one. `l3_skipped_reason` in the log explains an L3 that was
deliberately skipped because L2 was not `ENRICHED`.

`drive_rename_decision` is always `PROPOSED_ONLY_AWAITING_HUMAN_APPROVAL`.
`catalog_status` is always `DRAFT` until an explicit publication approval.

**The log** — one JSON line per gate plus a final `"gate": "run-summary"` object with
`status_counts`, `excluded_items`, the manifest URI, the evidence prefix, and a per-asset
summary. Read it with:

```powershell
gcloud logging read `
  'resource.type="cloud_run_job" AND resource.labels.job_name="site-visit-workflow"' `
  --project=shir-sitevisit --limit=500 --format="value(textPayload)"
```

**GCS** — the durable copy of everything, including `run-summary.json`.

## Where artifacts land in GCS

Everything is run-scoped, so two runs never collide.

```text
gs://shir-sitevisit-staging/
  site-visit-staging/                          <- GCS_STAGING_PREFIX
    <RUN_ID>/                                  <- run prefix
      manifest.json
      run-summary.json
      <DRIVE_ASSET_ID>/                        <- asset prefix
        media-preparation.json
        audio/attempt-0/<DRIVE_ASSET_ID>.wav
        audio/attempt-1/<DRIVE_ASSET_ID>.wav   (only if a retry happened)
        speech-output/attempt-0/               <- Chirp writes its own objects here
        speech-output/attempt-1/
        transcript.txt
        transcription-record.json
        prompt-execution/l1.json
        prompt-execution/l2.json
        prompt-execution/l3.json
        catalog-row.json
        catalog-upsert-record.json
```

`RUN_ID` comes from `--run-id`, else the `RUN_ID` env var, else a generated UTC stamp
like `20260917T055321Z`. Passing an explicit, meaningful `--run-id` is strongly
recommended — it is the only handle you have for finding a run's artifacts later.

Every write is guarded with `if_generation_match=0`, so re-using a `RUN_ID` against an
existing object fails loudly rather than overwriting.

```powershell
gcloud storage ls -r gs://shir-sitevisit-staging/site-visit-staging/RUN_ID/
gcloud storage cat gs://shir-sitevisit-staging/site-visit-staging/RUN_ID/run-summary.json
```

## Re-running safely

The catalog row key is the **immutable Drive asset ID**. A re-run therefore *updates* the
same row instead of appending a duplicate — that is what makes re-running safe.

- **Re-run the whole folder:** use a **new** `--run-id`. Catalog rows update in place;
  GCS gets a fresh, separate evidence tree. The old tree stays.
- **Re-run one asset:** `process-folder --asset-id <DRIVE_ASSET_ID> --run-id <new id>`.
  Gate 1 still runs (the manifest is cheap and is the audit record), then only that asset
  is processed.
- **Never re-use a `RUN_ID`.** The generation precondition will fail on the first object
  and the asset will be recorded `FAILED`. This is the guard working, not a bug.
- A re-run costs real Chirp and Vertex calls. Use `--limit` and `--dry-run` while you are
  still iterating.
- The catalog `run_id` column tells you which run last wrote each row.

## The no-delete constraint

The runtime identity **cannot delete anything**, deliberately:

- GCS: it holds `objectCreator` + `objectViewer` + `legacyBucketReader`. No role carries
  `storage.objects.delete`. (`roles/storage.objectUser` was granted during setup and then
  removed for exactly this reason — see
  [ADR-0005](decisions/0005-staging-bucket-without-delete.md).)
- Drive: source files report `canDelete: false`.
- Sheets: the code never deletes a row or a tab, and never touches the default `Sheet1`.
- The container work directory is never cleaned up either; the ephemeral filesystem
  disappears with the execution on its own.

Operationally this means:

- **Artifacts accumulate.** Every run leaves a full evidence tree, including WAVs, which
  are the largest objects. Storage cost grows monotonically with the number of runs.
- **Nothing self-heals.** A bad run's artifacts stay. Correct it by doing a new run under
  a new `RUN_ID`; the catalog row updates, the old evidence remains as history.
- **Cleanup is a separate, human-authorized action.** It cannot be performed by the job
  and must not be automated into it. A human with delete rights removes obsolete run
  prefixes deliberately, or an object lifecycle rule is added on the bucket by explicit
  decision. [OPEN] No lifecycle rule is configured today; retention is unbounded until
  someone decides otherwise.
- Do not "fix" a storage problem by granting the service account a delete role. That
  reverses a signed-off decision and needs an ADR.

## Failure handling

One asset's failure never ends the run. The loop records `FAILED` with a sanitized error
and moves to the next asset.

| Failure | Required response |
| --- | --- |
| Drive access/listing | Stop; verify folder membership and OAuth scope. Never choose another folder silently. Run `auth-preflight`; see [Drive HTTP 403 recovery](RUNBOOKS/drive-access-recovery.md). |
| ffprobe/ffmpeg | Retain staged source, log the command/error, validate codec. In the deployed job this usually means an unexpected MIME type or a source with no audio stream. |
| GCS | Check bucket/prefix and least-privilege access, then retry deliberately under a new `RUN_ID`. A `PreconditionFailed` means the `RUN_ID` was re-used. |
| Chirp | Record operation and error; do not fabricate a transcript. Empty output gets one retry then `NEEDS_REVIEW`. A poll timeout is `FAILED`, not empty. |
| L1/L2/L3 extraction | Preserve transcript and validation error; do not infer fields outside the strict schema. A failed L2 keeps the validated L1; a skipped L3 records why. |
| Sheets | Retain the row JSON in GCS, check the idempotent row key and access; do not duplicate records. |
| OOM / task timeout | Raise `--memory` / `--task-timeout` (see the sizing section of `docs/DEPLOYMENT.md`) or split the run with `--limit`. Re-run under a new `RUN_ID`. |

## How to update this later

Add concrete commands and log locations only with the implementation that executes them.
Keep failure responses deterministic and update the corresponding runbook and ADR when
operational behavior changes. If the GCS layout or the catalog column set changes, update
the layout tree and the reading-results table here in the same change as `catalog.py`.
