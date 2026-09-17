# ADR 0007: the catalog Sheet is owned by the operator and shared to the service account

## Status

Accepted

## Context

The workflow publishes catalog rows to a Google Sheet. Something has to create
that Sheet and decide where it lives. The Phase 2 preflight was originally
planned to have the service account create it in the Shared Drive so the
operator could see it. That turned out not to be cleanly possible, and the
preflight recorded the Sheets stages as **FAIL** with `CATALOG_SHEET_ID` empty
[VERIFIED — `authorization-matrix.md`, `go-no-go.md` blocker 1].

Three candidate locations were considered, and each of the two rejected ones
fails for a specific reason:

- **Shared Drive root, created by the service account.** Not possible.
  `drives().get` on `0AGzXWk46WhgyUk9PVA` returns HTTP 404 "Shared drive not
  found" [VERIFIED — preflight], which confirms the SA is shared on the source
  *folder* only and is not a member of the Shared Drive. It cannot create a
  file in the Shared Drive root. Adding Shared Drive membership would be a
  meaningful privilege increase for one file.
- **Inside the source media folder, created by the service account.** Possible
  — the folder reports `canAddChildren: true` — and deliberately rejected. It
  would write a non-media file into the immutable source-media folder, which
  conflicts with the single-folder immutable-source policy of ADR 0002.
  Polluting the evidence folder to save one manual step is a bad trade.
- **The service account's own My Drive.** Possible and useless. The Sheet would
  be invisible to the operator who has to review it, and would sit against
  service-account Drive storage limits with no human owner if the SA is ever
  rotated or deleted.

## Decision

The catalog Sheet is created by the operator, in a Drive location the operator
controls, and shared to
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` as **writer**. The
service account does not create it and is not its owner.

This was done on 2026-09-17 at 06:42 UTC by `dmyers@shircapital.com`:
Sheet "Site Visit Catalog — Live Workflow", ID
`158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0`, tab `Catalog`, shared to the
service account as writer [VERIFIED — preflight `change-log.md`]. The ID is
supplied to the job as `CATALOG_SHEET_ID` and the tab as `CATALOG_TAB_NAME`.

## Consequences

This is the least-privilege resolution: it needs no Drive membership change and
no IAM change beyond that single share. The SA gains write access to exactly
one Sheet and nothing else, and the source media folder stays media-only.

The Sheet is human-owned, so it survives service-account rotation and is
visible to the operator without any extra step — but it also means Sheet
creation is a **manual prerequisite**, not something the pipeline can
bootstrap. A fresh environment cannot be stood up entirely by code; setup
documentation and the runbook must state the create-and-share step explicitly,
and a missing or unshared `CATALOG_SHEET_ID` must fail loudly at preflight
rather than at publish time.

Ownership living with an individual account is a real risk worth naming
(LD-7): if `dmyers@shircapital.com` is offboarded, the Sheet goes with it.
[OPEN] Moving ownership to a Shared Drive that the SA is shared into — as a
single file share, not a drive membership — would fix that, and is the likely
long-term answer.

The catalog remains an **output**, not the system of record (LD-6). Losing the
Sheet must be recoverable by republishing from the database.

## How to update this later

If the Sheet moves, record the new ID and location here and in
`docs/SETUP.md`, and re-run `auth-preflight` to confirm `sheets.readable` and
`can_edit: true` before the next publish. Do not resolve a future access
problem by granting the service account Shared Drive membership or by creating
files inside the source media folder; both were considered and rejected above.
