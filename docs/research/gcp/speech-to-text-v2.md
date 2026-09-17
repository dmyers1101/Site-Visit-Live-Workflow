# Speech-to-Text v2 / Chirp — confirmed research record

**Date pulled:** 2026-09-17
**Pulled for:** batch transcription of one staged WAV per site-visit asset, from
a deployed Cloud Run Job running as
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`.

## Sources

- https://docs.cloud.google.com/speech-to-text/v2/docs/chirp_3-model
- https://cloud.google.com/speech-to-text/v2/docs
- https://pypi.org/project/google-cloud-speech/

## Confirmed client library

| Library | Version | Notes |
| --- | --- | --- |
| `google-cloud-speech` | `2.40.0` | **Installed in the runtime image**, confirmed in the Cloud Build "Successfully installed" output on 2026-09-17 [VERIFIED — preflight `commands.md`, 06:16 UTC]. Pin at this version; do not rely on a floor. |

## Confirmed model and recognizer shape

| Item | Value | Certainty |
| --- | --- | --- |
| Model id | `chirp_3` | [VERIFIED 2026-09-17] |
| Recognizer path | `projects/{project}/locations/{location}/recognizers/_` | [VERIFIED 2026-09-17] |
| Serving locations | the **`us` and `eu` MULTI-REGIONS** — *not* ordinary regions such as `us-central1` | [VERIFIED 2026-09-17] |
| Batch method | `BatchRecognize`, reading audio from `gs://` | [VERIFIED 2026-09-17] |
| Audio source | Cloud Storage URI only; **Drive is not a supported source** | [VERIFIED 2026-09-17] |

The `_` recognizer is the inline/ad-hoc recognizer: no persistent recognizer
resource has to be created, and configuration is supplied per request.

## IAM and API prerequisites

- `speech.googleapis.com` enabled on `shir-sitevisit` [VERIFIED 2026-09-17].
- Runtime service account holds `roles/speech.client` [VERIFIED — project IAM
  policy, preflight `raw/project-iam-policy.json`].
- Read access to the staging bucket: `roles/storage.objectViewer` on
  `gs://shir-sitevisit-staging` (ADR 0005).

## Revalidation — 2026-09-17

Performed during preflight run `20260917T055321Z-phase2-auth-preflight`
(WebFetch of the Chirp 3 model page at 06:17 UTC, logged in that run's
`commands.md`). Findings:

1. **Model id is `chirp_3`.** Confirmed current. The `.env.example` value
   `TRANSCRIPTION_MODEL=chirp` is a friendly alias, not the API model string;
   the request must carry `chirp_3`.
2. **Recognizer path pattern** is
   `projects/{project}/locations/{location}/recognizers/_`.
3. **`us` / `eu` multi-region constraint — this found a real bug.** Chirp 3 is
   served from the `us` and `eu` multi-regions. The code was building the
   recognizer path from `GOOGLE_CLOUD_REGION=us-central1`, which names a
   location where the model is not offered. The preflight classified the
   Speech-to-Text stage **PARTIAL** for this reason [VERIFIED —
   `authorization-matrix.md`; `go-no-go.md` blocker 4]. The fix is the separate
   `SPEECH_LOCATION` setting, default `us` — see ADR 0006. The client endpoint
   must match the location, not just the path string.
4. **`BatchRecognize` with a GCS source is supported** and is the intended call
   for this workflow: one staged WAV per asset, submitted asynchronously.
   Because Drive is not an accepted source, the Drive → Cloud Run → GCS hop of
   ADR 0004 is mandatory rather than a convenience.
5. **Installed library confirmed as `google-cloud-speech 2.40.0`** in the
   preflight image.

[OPEN] No live `BatchRecognize` submission has been made. Everything above is a
documentation and configuration fact; the request shape has not yet been
exercised against the API. The first submission is the retest for blocker 4.

[OPEN] Audio encoding requirements for the staged WAV (sample rate, channel
count, whether explicit `explicit_decoding_config` is needed or auto-detect
suffices) are not confirmed here and must be recorded after the first live run.

## How to update this later

Re-pull https://docs.cloud.google.com/speech-to-text/v2/docs/chirp_3-model
before any Speech change, before changing `SPEECH_LOCATION`, and whenever a
submission fails oddly — model ids, serving locations, and request shapes all
drift. **Append a new dated revalidation section; do not edit or remove an
earlier one.** Record the library version actually installed in the image
(from the Cloud Build "Successfully installed" line) and the tested request
shape once a live `BatchRecognize` has succeeded.
