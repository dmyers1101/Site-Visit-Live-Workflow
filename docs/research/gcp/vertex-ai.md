# Vertex AI / Gemini — confirmed research record

**Date pulled:** 2026-09-17
**Pulled for:** the L1/L2/L3 extraction layers of the live workflow, run from a
deployed Cloud Run Job as
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`.

## Sources

- https://cloud.google.com/vertex-ai/generative-ai/docs
- https://cloud.google.com/vertex-ai/generative-ai/docs/models
- https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output
- https://pypi.org/project/google-genai/

## Confirmed client library

| Library | Version | Notes |
| --- | --- | --- |
| `google-genai` | `2.24.0` | **Installed in the runtime image** and confirmed in Cloud Build output for build `d7fd83ec…` on 2026-09-17 [VERIFIED — preflight `commands.md`, 06:21 UTC]. This is the current unified Google Gen AI SDK; it supersedes the older `vertexai` / `google-cloud-aiplatform` generative surface. Added to `pyproject.toml` during this run. |
| `google-auth` | `2.58.0` | Ambient ADC from the Cloud Run metadata server. No key file. |

Pin `google-genai` in `requirements.txt` / `pyproject.toml` at the version
actually installed in the image, not at a floor that lets the image drift.

The SDK is pointed at Vertex (not the Gemini Developer API) by configuring the
client for Vertex with the project and location; `VERTEX_LOCATION` is
`us-central1` and is a **separate setting** from `SPEECH_LOCATION` and from
`GOOGLE_CLOUD_REGION` — see ADR 0006.

## Confirmed model

| Setting | Value | Certainty |
| --- | --- | --- |
| `VERTEX_MODEL` | `gemini-2.5-flash` | [VERIFIED] available as of 2026-09-17 [preflight `commands.md`, 06:18 UTC] |

**Pilot model IDs were NOT assumed current.** The `pilot/` runs from 2026-08
name their own model, and that name was deliberately not carried forward.
Generative model IDs are retired and renamed on the vendor's schedule; a pilot
log is a record of what ran that day, not a statement about what is available
now. The model ID above was confirmed by a dated lookup during the 2026-09-17
preflight and is pinned in configuration with that date attached.

The preflight classified the Vertex L1 stage **PARTIAL** precisely because no
model ID had been pinned in code or config and no live model call had been
attempted [VERIFIED — `authorization-matrix.md`]. Pinning the ID closes the
config half; a first live L1 call is still outstanding.

## Structured output

Strict JSON is obtained from the API, not from parsing prose. The generation
config sets:

- `response_mime_type="application/json"` — the model returns a JSON document
  rather than markdown-wrapped text.
- `response_schema=<schema>` — a schema constraining the returned object, which
  is what closes the key set and the enum vocabularies.

This is the direct countermeasure to two proven pilot failure modes: every
pilot response arrived inside a markdown code fence, and out-of-vocabulary enum
values were emitted freely (see ADR 0008).

**`response_schema` is a constraint, not a guarantee.** It does not remove the
need for the local validators. The repository still rejects unknown keys, code
fences, out-of-vocabulary enums, nulls in required strings, and echoed
transcripts on the client side. Belt and braces is the decided posture — see
ADR 0008.

[ASSUMED] Schema support covers the object/enum/array shapes the L1–L3 output
schemas need. This has not yet been exercised against a live call; confirm with
the first L1 call and record the result here.

## IAM and API prerequisites

- `aiplatform.googleapis.com` enabled on `shir-sitevisit` [VERIFIED 2026-09-17].
- Runtime service account holds `roles/aiplatform.user` [VERIFIED — project IAM
  policy, preflight `raw/project-iam-policy.json`].
- No key file; ambient ADC only (ADR 0003).

## Open items

- [OPEN] No live Vertex call has been made from the deployed job. Every fact
  above about availability is a documentation/config fact, not an observed one.
- [OPEN] Quotas, rate limits, and per-token cost for `gemini-2.5-flash` on this
  project have not been checked and are not recorded here.
- [OPEN] Behavior under `response_schema` when the model cannot satisfy the
  schema (refusal, truncation, or malformed output) is untested.

## How to update this later

Re-pull before the first live L1 call and before any model change; generative
model IDs, SDK surfaces, and structured-output parameters all drift. Record the
new retrieval date, the source URLs, and the version of `google-genai`
**actually installed in the image** — read it from the Cloud Build
"Successfully installed" line, not from the dependency floor in
`pyproject.toml`. When a model ID is retired, supersede the value in the table
above with a dated row rather than editing history. Never carry a model ID
forward from a pilot log or from memory.
