# Handoff prompt — Asana task creation workflow (ties it together)

Paste everything below the line into a new Claude Code session opened at
`apps/live-workflow` (repo `dmyers1101/Site-Visit-Live-Workflow`, branch `main`).
Best done after (or alongside) `01-appfolio-work-orders.md`.

---

We're building the Asana task creation workflow for the Site Visit live
workflow — the piece that ties clips, reports and AppFolio work orders
together. Asana is the task system of record (design LD-5). Before building
anything, read the context below, then ask me one batched round of scope
questions (with your recommended default for each). Do not write code until
I've answered.

## Context (read first)
- `README.md`, `docs/HANDOFF.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`.
- ADR 0013 + `src/site_visit_workflow/report.py`: each visit report has action
  items (Immediate / Priority / Routine-by-area) built from catalog rows, with
  clip links. The report was designed to gain an "Asana task" link per item.
- ADR 0014: work-order request flag. `docs/handoffs/01-appfolio-work-orders.md`:
  AppFolio work-order creation (may or may not be built yet — check).
- L2 statuses now include `ALREADY_TRACKED` (walker says it's already tasked);
  those must not create duplicate tasks.
- Pipeline: Cloud Run Jobs in `shir-sitevisit`, nightly, service account
  `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`; Google-only
  model processing. An Asana MCP connector exists in my Claude environment
  for development; production must call the Asana API directly.

## Scope to clarify with me first
1. **What becomes a task:** every action item, only some tiers, or only
   approved ones? One task per action item or per clip?
2. **Structure:** one project per property vs one shared project with
   sections; assignee rules; due dates from the suggested timeframe or not.
3. **Linking:** task ↔ clip link, report link, AppFolio work-order ID; and the
   report showing an Asana link per action item.
4. **Idempotency + updates:** where task GIDs are stored, what happens on
   rerun, when a clip is re-catalogued, or when a task is closed in Asana.
5. **Auth:** Asana service account / PAT in Secret Manager; workspace and
   project IDs.
6. **Order of operations** with AppFolio: create the work order first, then
   the Asana task referencing it — or the reverse.

## Standing rules for this work
- Pull current Asana API docs first; record in `docs/research/`.
- Dry-run first; no tasks created until I approve a reviewed sample.
  Invariants first (pipeline-verify): no duplicates, every created task traces
  to a catalog row, reruns are no-ops.
- New ADR; README/CHANGELOG updated; source copied to `++TEAM CLAUDE-DM++`;
  state which account it runs as, where it is scheduled, and where output is written.
