# One-asset trial — 20260917T070454Z

**Run ID:** `20260917T070454Z`
**Execution:** `site-visit-workflow-pkfbt`
**Image:** `us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:pipeline-20260917`
**Runtime identity:** `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`
**Command:** `site-visit process-folder --limit 1`
**Result:** Gates 1–2 PASS · Gate 3 FAILED · Gates 4–5 not reached

This was a real execution against the real Drive folder, as the service
account, from the deployed Cloud Run Job. Container exited 0; the run summary
records the per-asset failure rather than crashing the job, which is the
intended behavior.

## Job configuration used

| Setting | Value |
| --- | --- |
| Memory / CPU | 8Gi / 2 |
| Task timeout | 3600s |
| Retries | 0 |
| `DRIVE_SHARED_FOLDER_ID` | `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` |
| `GCS_STAGING_BUCKET` | `shir-sitevisit-staging` |
| `SPEECH_LOCATION` / `SPEECH_MODEL` | `us` / `chirp_3` |
| `VERTEX_LOCATION` / `VERTEX_MODEL` | `us-central1` / `gemini-2.5-flash` |
| `CATALOG_SHEET_ID` | `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0` |

## What passed

**Gate 1 — discovery.** Boundary correctly resolved as `DIRECT_MEDIA_CHILDREN`.
19 immediate children seen: 16 selected, 3 excluded. Each exclusion carries a
reason: `EXCLUDED_UNSUPPORTED_MIME_TYPE: only video/* sources can be
transcribed.` for the three `image/heif` files. `manifest.json` written to GCS
before any media was staged.

**Gate 2 — media preparation.** `IMG_3651.MOV` was read from Drive into the
container, probed, and transcoded to mono 16 kHz PCM WAV. Both the WAV and
`media-preparation.json` landed in GCS under the run-scoped prefix.

Artifacts produced:

```
gs://shir-sitevisit-staging/site-visit-staging/20260917T070454Z/manifest.json
gs://shir-sitevisit-staging/site-visit-staging/20260917T070454Z/run-summary.json
gs://shir-sitevisit-staging/site-visit-staging/20260917T070454Z/1p-9ppp…/media-preparation.json
gs://shir-sitevisit-staging/site-visit-staging/20260917T070454Z/1p-9ppp…/audio/attempt-0/1p-9ppp….wav
```

This confirms the cloud-native media path end to end: Drive → Cloud Run
container (ephemeral) → GCS, with no operator workstation involved.

## What failed — Gate 3

```
ExternalServiceError: Speech BatchRecognize submission failed: 403 POST
https://storage.googleapis.com/upload/storage/v1/b/shir-sitevisit-staging/o?uploadType=multipart
"site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com does not have
 storage.objects.delete access to the Google Cloud Storage object."
```

**Root cause.** The WAV is uploaded twice. Gate 3 stages it to
`…/audio/attempt-0/<asset>.wav`, and the pre-existing `submit_transcription`
then uploads the same file to the same object again. The second write is an
overwrite, and GCS requires `storage.objects.delete` to overwrite an existing
object.

**This is not a permissions gap.** The service account intentionally has no
delete permission (ADR 0005). The no-delete design worked exactly as intended:
it caught a real double-write that would otherwise have silently clobbered a
staged artifact. The fix is to remove the duplicate upload, not to grant
delete.

**Fix applied:** `submit_transcription` accepts the already-staged `gs://` URI
and performs no upload. All GCS writes use `if_generation_match=0` so a
collision fails loudly instead of overwriting.

## Second issue found and fixed in the same cycle

`infra/Dockerfile` did not copy `prompts/` into the image, while
`extraction.py` reads the versioned prompt files from disk at runtime. Gate 4
would have failed on every asset. Fixed with `COPY prompts ./prompts`. Not
visible in this run because Gate 3 failed first.

## Verification after the fix

Re-run `process-folder --limit 1` and confirm, in order:

1. `run-summary.json` shows `status_counts` with no `FAILED`.
2. A `transcript` artifact exists under the asset's run-scoped prefix.
3. L1/L2/L3 records exist and validate.
4. One row appears in the `Catalog` tab of the catalog Sheet, keyed on the
   Drive asset ID.
5. Re-running the same asset updates that row rather than appending a duplicate.

## How to update this later

Create a new dated trial directory per run. Never overwrite this one. Record
the image tag and execution name so a failure can be traced to exact code.
