# ADR 0013 — Structured report template; replace the visit tab in place

## Status
Accepted (2026-10-07). Amends ADR 0010 ("Never used: `deleteContentRange`";
"Report Docs grow forever") for registered visit tabs only. Replaces the
placeholder report prompt 0.2.0 with `prompts/report-synthesis.md` 1.0.0.

## Context
A review of the 0.2.0 reports in the Alta, Alma and Teak report Docs
(2026-09-29 / 10-04) found: one plain-text block with no headings or links;
20–30 items packed into one paragraph; severity 1 and 2 merged; NO_FINDING
clips listed as "could not be assessed"; a count stated by the model despite
the rule (Teak); a filename in the text (Alta); and every rerun stacking a full
copy on top (Alta's tab holds three). The owner asked for a clearer template
with sections and a distinct action-items section, and for reruns to replace
rather than stack. All model processing stays on Google (Vertex Gemini).

## Decision
- **Code owns layout; the model owns words.** The model returns
  schema-validated JSON (summary, merged action items citing `ref_<n>`,
  observations by area). Code routes every clip by explicit status, assigns
  tiers from L2 severity (1 Immediate, 2 Priority, 3–4 Routine), writes all
  counts, adds clip links and L3 "Suggested" owner/timeframe, and builds the
  Docs requests. Validation rejects unknown/non-actionable refs, counts,
  filenames and IDs; an omitted actionable clip is added back by code; two
  failed attempts → catalogue-only fallback (`WRITTEN_FALLBACK`).
- **Sections:** header · At a glance · Summary · Action items (three tiers) ·
  Observations by area · Needs human review · Run details. Routine is
  sub-grouped by area (Units, Common interior, Exterior, Amenities, General)
  after the Alta preview showed 25 routine items in one list.
- **No tables.** The Docs API cannot insert a table and fill it in one
  `batchUpdate` (`docs/research/gcp/docs-api-formatting.md`), which would make
  the write non-atomic. Headings, bullets, bold, links and small grey detail
  lines are used instead.
- **Replace in place, atomically.** For a tab the Reports registry maps to this
  visit, the old content is cleared by `deleteContentRange` in the SAME
  `batchUpdate` that writes the new report, guarded by `requiredRevisionId`.
  Nothing is cleared until the content has validated and every request is
  built. New or unclaimed-empty tabs are never cleared. The single-folder
  `process-folder --report` path still prepends (no delete).
- `preview-report` writes a visit's report to a new tab of a scratch Doc for
  review without touching property Docs or the registry.

## Consequences
- One current report per visit tab; earlier versions remain in the Doc's
  version history (File → Version history), not in the body.
- A hand edit made inside a registered visit tab is overwritten on the next
  report for that visit. Notes belong in a separate tab or a comment.
- Still never used: `deleteTab`, Drive delete/trash, Sheets clear.
- Rollback: `git revert` the commit; the 0.2.0 prompt is in Git history.
