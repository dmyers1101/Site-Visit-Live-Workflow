# AppFolio Database API v0 — work orders (research note)

**Pulled:** 2026-10-08 · **Source:** company copy of the official docs at
`My Drive\_dev\docs\appfolio_API_documentation_v0\` (`_00_getting_started.md`,
`work_orders.md`, `_WRITE_NOTES.md`), captured from
https://developer.appfolio.com/api_documentation/database. Public web search
found only conflicting third-party pages; those are not used.

## Confirmed
- **Base URL:** `https://api.appfolio.com/api/v0/{endpoint}`
- **Auth:** HTTP Basic `client_id:client_secret` + header `X-AppFolio-Developer-ID`.
  One credential set per customer database.
- **Rate limits:** 8/sec · 256/min · 4096/hr per credential set; honour `Retry-After`.
- **Maintenance window:** `533` between 9PM–4AM PST — do not write then.
- **`POST /work_orders`** → `201 {"Id": uuid, "Link": uri}`.
  - Required: `JobDescription` + exactly one of `PropertyId | UnitId | OccupancyId |
    InspectionId | ServiceRequestId` (UUIDs, not UI integer IDs).
  - Optional used here: `Description`, `Priority`, `Status`.
  - **`Priority` enum: `Urgent` | `Normal` | `Low` only** (no "High").
  - `Status` enum on create: Assigned, Canceled, Completed, New, Scheduled, Waiting, Work Completed.
  - `VendorTrade` has its own list (Painting, Plumbing, Pest Control, …) — left blank by decision.
- **`Idempotency-Key`** honoured on POST only (≤256 printable ASCII, 24h TTL,
  same key + different body → 422, replay header `Idempotent-Replayed: true`).
- **`GET /work_orders`** must filter on `filters[Id]` or `filters[LastUpdatedAtFrom]`;
  pages of up to 1000 via `page[number]`/`page[size]`, follow `next_page_path`.
  No filter by description, so duplicate detection is a date-bounded scan.
- **Notes:** `POST /work_orders/{id}/notes` (idempotent) — used for the clip links.
- **Errors:** 401/403/701 stop the run; 404 no retry; 422 never retry; 429/500/503/533 back off.
- **Empty array `[]` clears collections** — payloads are built from present keys only.

## Open
- Properties endpoint not in our docs copy; the `property_id` crosswalk reuses
  `_dev/warehouse/scripts/afv0_build_crosswalk.py`.
- A walker-entered "existing work order" number is the UI integer; the list
  response exposes UUID `Id` and a `Link` — matching an integer needs a scan on `Link`.

## Reuse
`_dev/warehouse/scripts/afv0.py` already implements creds (env `AF_V0_CLIENT_ID`,
`AF_V0_CLIENT_SECRET`, `AF_V0_DEVELOPER_ID`), the 6/200/4000 limiter, the status
ladder and `prune_unset`. It is ported into this package; in Cloud Run the env
vars come from Secret Manager.

## How to update this later
Re-pull from developer.appfolio.com if a call fails oddly; replace any line
here that the live API contradicts and note the date.
