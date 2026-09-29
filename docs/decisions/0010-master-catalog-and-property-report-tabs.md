# ADR 0010 — Master catalog Sheet, per-property report Docs, one tab per visit

## Status
Accepted (2026-09-29). Supersedes the per-visit Sheet/Doc outputs of the
2026-09-18 run for portfolio use (`process-folder` still supports them).

## Context
Operator decision (2026-09-29): one portfolio-wide catalog; one report Doc per
property; one tab per visit titled with the latest upload date and the uploader;
newest report at the top.

## Decision
- **Master Sheet** "Site Visit Master Catalog" (`1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o`)
  in the master folder, tab `Catalog`. Row key is still the Drive file ID.
  Eight columns appended (never inserted): `state, property, property_group,
  visit_name, uploader_email, uploader_name, uploaded_at, attempt_count`.
- **Report Doc** "<Property> Site Visit Reports" in each Property folder,
  found-or-created by exact title.
- **Visit tab**: created with Docs `addDocumentTab` (or the Doc's empty default tab
  is reused), titled `<latest uploaded_at date> · <most frequent uploader>` via
  `updateDocumentTabProperties` (fields `title`). Each report is `insertText` at
  index 1 of that tab, so the newest is on top; older reports stay below.
- The Doc/tab per visit is recorded in the master Sheet's **`Reports`** tab
  (`row_key`=visit folder ID, `doc_id`, `tab_id`, `tab_title`, `updated_at`),
  because tab titles change.
- A report is (re)written when the run processed clips for the visit **or** the
  visit's rows are newer than its `Reports.updated_at` (self-heals a failed report).
- Clip counts in the report are written by code (`format_counts_line`).
- Never used: `deleteTab`, `deleteContentRange`, Drive delete/trash.

## Consequences
- The 16 test-folder rows were copied in with `migrate-catalog`; the old Sheet
  `1GW3fg8I…` is left untouched as history.
- If someone deletes a tab by hand, the next report creates a new one.
- Report Docs grow forever (append-only by design, ADR 0005 spirit).
