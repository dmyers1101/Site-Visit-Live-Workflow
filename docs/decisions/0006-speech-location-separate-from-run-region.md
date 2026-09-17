# ADR 0006: the Chirp recognizer location is a separate setting from the Cloud Run region

## Status

Accepted

## Context

The workflow ran with a single `GOOGLE_CLOUD_REGION=us-central1` setting and
used it for everything regional, including the Speech-to-Text v2 recognizer
path. That is wrong.

Chirp 3 is served from the `us` and `eu` **multi-regions**, not from
`us-central1` [VERIFIED — https://docs.cloud.google.com/speech-to-text/v2/docs/chirp_3-model,
retrieved 2026-09-17 during preflight run `20260917T055321Z-phase2-auth-preflight`].
A recognizer path built as
`projects/shir-sitevisit/locations/us-central1/recognizers/_` names a location
where the model is not offered.

This was a real bug, not a theoretical one. The Phase 2 preflight classified
the Speech-to-Text stage **PARTIAL** for exactly this reason: the API was
enabled and `roles/speech.client` was present, but the region the code would
have used was wrong [VERIFIED — preflight `authorization-matrix.md`;
`go-no-go.md` blocker 4]. It would have surfaced as a confusing model- or
recognizer-not-found error that reads like a permission problem.

Collapsing compute region and model-serving location into one variable is a
false economy in general: they are chosen for different reasons. Cloud Run
region is picked for latency, cost, and data residency of the compute. A model
serving location is picked from wherever the vendor happens to offer that
model, and that set changes without notice.

## Decision

Introduce a dedicated `SPEECH_LOCATION` setting, default `us`, and use it — and
only it — to build the Speech-to-Text v2 recognizer path and API endpoint.
`GOOGLE_CLOUD_REGION` continues to govern Cloud Run and other regional
resources and must never be substituted for it. `VERTEX_LOCATION` remains a
third, independent setting (currently `us-central1`) for the same reason.

Valid values for `SPEECH_LOCATION` are `us` and `eu`. The setting is recorded in
`.env.example` and is passed to the Cloud Run Job as an explicit environment
variable.

## Consequences

The recognizer path becomes
`projects/{project}/locations/{SPEECH_LOCATION}/recognizers/_`, and the client
must be constructed against the matching regional endpoint rather than the
global default. Audio staged in `gs://shir-sitevisit-staging` is already US
multi-region, which aligns with `SPEECH_LOCATION=us`; if the location is ever
changed to `eu`, the staging bucket location has to move with it or the job
pays cross-region reads and may violate residency expectations.

There are now three location settings to keep straight. That is the honest
shape of the system (LD-7) and is preferable to one variable that is silently
wrong for two of its three uses. Configuration documentation and the runbook
must say which setting drives which product.

[OPEN] Chirp 3 multi-region availability is a vendor fact with no stability
guarantee. It is pinned by retrieval date, not assumed permanent.

## How to update this later

Re-pull https://docs.cloud.google.com/speech-to-text/v2/docs/chirp_3-model
before changing `SPEECH_LOCATION` or the model id, and record the new retrieval
date in `docs/research/gcp/speech-to-text-v2.md`. Never reuse
`GOOGLE_CLOUD_REGION` for a model-serving location, for Speech or for any
product added later. If a future model is offered in ordinary regions, that is a
new fact requiring a dated re-pull — not a reason to collapse the settings back
together.
