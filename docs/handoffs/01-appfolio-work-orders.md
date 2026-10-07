# Handoff prompt — AppFolio work-order creation (v0 API)

Paste everything below the line into a new Claude Code session opened at
`apps/live-workflow` (repo `dmyers1101/Site-Visit-Live-Workflow`, branch `main`).

---

We're starting the AppFolio work-order creation setup for the Site Visit live
workflow, using the AppFolio **v0 API**. Before building anything, read the
context below, then ask me one batched round of scope questions (with your
recommended default for each). Do not write code until I've answered.

## Context (read first)
- `README.md`, `docs/HANDOFF.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`.
- ADR 0014 (`docs/decisions/0014-work-order-request-flag.md`) and
  `src/site_visit_workflow/work_order.py`: clips where the walker says
  "create/need a work order" are flagged in the master catalog
  (`work_order_requested` = YES, `work_order_phrase`).
- ADR 0013 + `src/site_visit_workflow/report.py`: the visit report and its
  action items (tier, location, issue, action, trade, clip links).
- The live pipeline runs as a Cloud Run Job in `shir-sitevisit`, nightly, as
  service account `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`.
  All model processing stays on Google (Vertex Gemini).
- An AppFolio MCP connector exists in my Claude environment
  (`appfolio_db_create_work_order`, `appfolio_db_get_work_orders`, ...). It is a
  development aid, not the production path.

## Scope to clarify with me first
1. **Trigger:** only clips flagged `work_order_requested = YES`, or also
   severity 1-2 action items, or a manual approval step first?
2. **Mapping:** how a visit/clip maps to an AppFolio property and unit (the
   catalog has `property` names and free-text locations, not AppFolio IDs).
3. **Fields:** what a work order needs (description, priority, vendor,
   category, unit, attachments/clip link) and which we can fill honestly.
4. **v0 API access:** credentials (client ID/secret in Secret Manager — never
   in the repo), base URL, rate limits, sandbox vs production.
5. **Idempotency + write-back:** where the AppFolio work-order ID is stored
   (new catalog column?) so reruns never create duplicates.
6. **Where it runs:** inside the nightly job or a separate job.

## Standing rules for this work
- Pull the current AppFolio v0 API docs before coding; record them in
  `docs/research/` with date, URLs and the confirmed request shapes.
- Dry-run mode first; nothing is created in AppFolio until I approve a
  reviewed sample. Use the pipeline-verify approach (invariants first).
- New ADR for the decision; README/CHANGELOG updated; source copied to the
  `++TEAM CLAUDE-DM++` Drive folder; state which account it runs as, where it
  is scheduled, and where its output is written.
