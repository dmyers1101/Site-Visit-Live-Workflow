# Operations and maintenance

## Normal single-visit procedure

1. Confirm Git branch, configuration, and Drive authorization.
2. List only the Shared Folder's immediate subfolders and select one visit.
3. Create and retain a manifest containing the visit ID, original Drive file name/ID/link, MIME type, size, and modified time.
4. Choose one safe candidate video and stage a copy; use `ffprobe` to inspect it and `ffmpeg` to extract mono 16 kHz WAV audio.
5. Upload the WAV to a unique GCS staging path and submit one low-concurrency Chirp BatchRecognize request.
6. Record operation status, timestamps, transcript URI, and errors. Retry an empty transcript once; then set `NEEDS_REVIEW`.
7. Generate a strict-JSON L1 proposal and an idempotent draft catalog row.
8. Obtain human approval before applying a descriptive rename or publishing a catalog row.

Use the named `site-visit` CLI command for each stage. Package import and
`config-check` are offline; `intake`, `stage-video`, `transcribe`,
`rename-drive`, and `publish-catalog` are deliberate external-call boundaries.
Persist every generated manifest, transcription record, L1 payload/result, and
approval record in an approved operational location.

## Failure handling

| Failure | Required response |
| --- | --- |
| Drive access/listing | Stop; verify folder membership and OAuth scope. Never choose another folder silently. |
| ffprobe/ffmpeg | Retain staged source, log the command/error, validate codec and local tools. |
| GCS | Retain local WAV, verify bucket/prefix and least-privilege access, then retry deliberately. |
| Chirp | Record operation and error; do not fabricate a transcript. Empty output gets one retry then `NEEDS_REVIEW`. |
| L1 extraction | Preserve transcript and validation error; do not infer fields outside its strict schema. |
| Sheets | Retain draft payload, check idempotent row key and access; do not duplicate records. |

## How to update this later

Add concrete commands and log locations only with the implementation that executes them. Keep failure responses deterministic and update the corresponding runbook and ADR when operational behavior changes.
