# ADR 0015 — AppFolio work orders via walker confirmation form

## Status
Accepted (2026-10-08). Built dry-run only; no AppFolio write until a reviewed sample is approved.

## Context
ADR 0014 flags clips where the walker asks for a work order. Those requests must
become AppFolio work orders (Database API v0) without duplicates, guessing, or
unapproved writes. Asana is out of scope for this ADR (next session).

## Decision
- **Candidates:** clips with `work_order_requested = YES`, plus severity 1–2 items
  as unticked suggestions. Blank flags are skipped, never treated as NO.
- **Grouping:** Vertex Gemini proposes groups of clips describing one project
  (e.g. touch-up paint across a property). Code validates every clip ID.
- **Confirmation:** one Google Form per visit, emailed to the clip uploader. Per
  item/group: *Create work order (one for the group)* · *Split per clip* ·
  *Already exists (enter WO # / link)* · *Skip*. Reminder at 24h; at 48h escalate to
  dmyers@shircapital.com and jcohen@signaturenexus.com. Nothing is created by default.
- **Sender:** dmyers@shircapital.com for now; swap to `sitevisits@` once the admin creates it.
- **Ledger:** new `WorkOrders` tab in the master catalog, keyed by Drive asset ID (+ group
  ID), holding status, form response, `appfolio_work_order_id`, link, timestamps.
  Request/response evidence in GCS. Create only when the ID is empty; POST carries a
  deterministic `Idempotency-Key`.
- **Mapping:** `AppFolioPropertyMap` tab (catalog property → property UUID), human-reviewed.
  Property level only (no `GET /units` in our docs, so no unit matching). Hedge 1 & 2 maps
  wholly to Hedge 1 (owner decision 2026-10-08). Legacy has one map row per building
  (`address_match`, from the Asana Legacy walk subtasks); a clip maps only when exactly one
  building address is heard in its location/issue text, else BLOCKED_NO_MAPPING. The map
  lives in the Sheet only — AppFolio IDs are not committed to the repo. Unmapped →
  `BLOCKED_NO_MAPPING`.
- **Fields:** `JobDescription` (location + issue + action + walker phrase), `PropertyId`
  or `UnitId`, `Priority` (severity 1 → Urgent, 2 → Normal, 3–4 → Low), `Status` New; clip links
  as a work-order note. Vendor, trade, assignee left blank.
- **"Already exists":** verified read-only against AppFolio; verified items appear in the
  report under "Already tracked" with the link.
- **Runtime:** separate Cloud Run job `site-visit-workorders`, as
  `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`, Cloud Scheduler 08:00 ET
  (03:00 ET falls inside AppFolio's 9PM–4AM PST maintenance window). Credentials in Secret Manager. Forms and email are an Apps
  Script project running as dmyers@shircapital.com on a time trigger.

## Consequences
- Writes are reversible only by cancelling in AppFolio (the API has no delete for work
  orders); first live tests are single, named work orders.
- AppFolio has no "High" priority, so severity 2 maps to Normal and 3–4 to Low (confirmed 2026-10-08).
