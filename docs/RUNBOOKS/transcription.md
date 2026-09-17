# Runbook: transcription

## Purpose

Safely prepare and transcribe approved video. In the cloud-native workflow this is
**Gate 2** (media preparation) and **Gate 3** (Chirp) of `process-folder`, executed
inside the Cloud Run Job. No media is ever copied to an operator workstation.

## Configuration that matters

| Setting | Value | Why |
| --- | --- | --- |
| `SPEECH_LOCATION` | `us` | Chirp 3 is served from the `us` / `eu` **multi-regions**. `us-central1` is not a valid Chirp location and this is deliberately a separate setting from the Cloud Run region. [ADR-0006](../decisions/0006-speech-location-separate-from-run-region.md) |
| Recognizer | `projects/shir-sitevisit/locations/us/recognizers/_` | The implicit `_` recognizer, built as `projects/{project}/locations/{SPEECH_LOCATION}/recognizers/_` |
| `SPEECH_MODEL` | `chirp_3` | The legacy alias `chirp` is **rejected with an explicit error**, never silently remapped — a silent mapping would hide the next such drift |
| Audio contract | mono, 16 kHz, `pcm_s16le` | Asserted on the produced WAV before Chirp sees it |
| Tooling | ffmpeg 7.1.5 / ffprobe, in the image | Not required on an operator machine |

## Procedure (cloud-native)

Gate 2 and Gate 3 run automatically per asset inside `process-folder`. For one asset:

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=process-folder,--limit,1,--run-id,20260917-transcribe-01
```

What happens, per asset:

1. **Gate 2 — stage.** The source is downloaded from Drive into the container's
   ephemeral work directory. The Drive source is never modified.
2. **Gate 2 — probe.** `ffprobe` records duration, format, size, stream count, and the
   audio/video codec, channels and sample rate.
3. **Gate 2 — extract.** `ffmpeg -vn -ac 1 -ar 16000 -c:a pcm_s16le` writes a **new**
   WAV. An existing WAV is never overwritten — a collision is a hard stop.
4. **Gate 2 — verify and checksum.** The produced WAV is re-probed and must actually be
   mono 16 kHz `pcm_s16le`, or the asset fails. Both the source and the WAV are SHA-256
   checksummed so the evidence record can prove what was sent.
5. **Gate 2 — upload.** The WAV goes to
   `<asset prefix>/audio/attempt-0/<DRIVE_ASSET_ID>.wav`, and the evidence record to
   `<asset prefix>/media-preparation.json`.
6. **Gate 3 — submit.** One Speech-to-Text v2 `BatchRecognize` request per WAV, with
   Chirp 3, writing results under `<asset prefix>/speech-output/attempt-0/`.
7. **Gate 3 — poll.** The operation is polled up to `--poll-timeout-seconds` (default
   1800). A timeout is recorded as `FAILED`, not as an empty transcript.
8. **Gate 3 — read and decide.** The batch result objects are read into transcript text,
   written to `<asset prefix>/transcript.txt`, and the empty-transcript policy is applied.
   The full attempt history lands in `<asset prefix>/transcription-record.json`.

Nothing is inferred and no transcript is ever invented.

## Empty transcript policy

An empty transcript is retried **exactly once**, automatically, as attempt 1 — a second
WAV upload under `audio/attempt-1/` and a second `BatchRecognize` under
`speech-output/attempt-1/`. Only attempts `0` and `1` are permitted anywhere in the code.

If attempt 1 is also empty, the asset is `NEEDS_REVIEW`:

- Gate 4 does **not** run. No extraction is attempted on an empty transcript.
- A real catalog row is still written, with `transcription_status` reflecting the
  outcome, `l1_status`/`l2_status`/`l3_status` = `NOT_RUN`, and blank extraction fields.
- `NEEDS_REVIEW` is not a valid maintenance finding. It is an honest gap for a human.

Common causes worth checking before re-running: the source has no audio stream (visible
in `media-preparation.json` as `has_audio_stream: false`), the clip is silent, or the
narration is inaudible. Re-running will not fix any of those.

## Single-step commands (manual diagnosis)

Still supported for a narrow re-run outside the pipeline:

1. Stage a local copy without changing the Drive source (`site-visit stage-video`).
2. Run `site-visit prepare-media` with the same manifest and selected asset ID
   to inspect it with `ffprobe`; retain duration, stream codec, and errors.
3. That command extracts mono 16 kHz WAV with `ffmpeg`; retain both staged
   media and WAV.
4. Explicitly run `site-visit transcribe` with a unique, clearly named GCS
   object path, attempt `0`, and one manifest asset ID.
5. It uploads the WAV and submits one Speech-to-Text v2 BatchRecognize
   `chirp_3` request; it does not wait for or invent a transcript.
6. Record request/operation identifiers, start/end timestamps, status, transcript GCS URI, and errors.

Use `site-visit evaluate-transcript` after retrieving an approved transcript
artifact. It returns `RETRY_ONCE` on attempt 0; submit the same retained
evidence at attempt 1. If that result is empty, it sets `NEEDS_REVIEW`; it is
not a valid maintenance finding.

> These steps are the manual equivalent of what Gates 2 and 3 now do automatically.
> Do **not** run them against the real Drive folder from a workstation — that would put a
> personal identity on the media path. Run them only in the job, or against a local test
> file.

## How to update this later

Record verified current model and SDK choices in the GCP research note before changing
the request configuration. Changing the audio contract means changing `WAV_CHANNELS`,
`WAV_SAMPLE_RATE`, `WAV_CODEC` in `src/site_visit_workflow/media.py`, the ffmpeg
arguments, and this runbook together.
