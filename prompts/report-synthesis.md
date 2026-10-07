# Report synthesis prompt

**Semantic version:** 1.0.0
**Status:** Active. Replaces the 0.2.0 placeholder (2026-10-07, ADR 0013).

## Purpose

Write the WORDS of one visit's report: an executive summary, merged action
items, and short observations by area. The LAYOUT — headings, tiers, counts,
clip links, the needs-review list, run details — is built by code in
`src/site_visit_workflow/report.py` (`build_report_requests`). The model is
never asked to count, to rank severity, or to name files.

Runs on Vertex AI Gemini (`settings.vertex_model`, `google-genai`), as every
other model layer in this workflow does. No non-Google model is used.

## Source/reference lineage

Derived from a review (2026-10-07) of the 0.2.0 reports actually written to the
Alta, Alma and Teak "Site Visit Reports" Docs on 2026-09-29 and 2026-10-04.
Defects found there and what 1.0.0 does about each:

| 0.2.0 defect (observed) | 1.0.0 response |
|---|---|
| 20–30 items crammed into one prose paragraph | Structured JSON; one action item per distinct problem, rendered as a list |
| Severity 1 and 2 merged into "urgent" | Code assigns three tiers from L2 severity; the model does not tier |
| NO_FINDING clips listed as "could not be assessed" | Code routes clips by explicit status; the model sees no-finding clips only as context |
| Model stated a count (Teak: "five items that require further review") | Validator rejects counts in summary/observations; counts come from code |
| Filename in text (Alta: `IMG_8054.MOV`) | Model never receives filenames or IDs; validator rejects them |
| Same problem filmed twice listed twice | Model merges clips that show the same problem into one item |
| No links to evidence | Code links every item to its clips |
| L3 owner / timeframe never surfaced | Passed in; rendered by code as "Suggested" |

Audience and length were set by the project owner on 2026-10-07: property
manager and regional leadership; the report is scanned, not read end to end.

## Expected input JSON/text

Built by `report.build_model_input`. References are `ref_<n>` and are the only
way to identify a clip.

```json
{"property":"string",
 "actionable_clips":[{"ref":"ref_1","location":"string|null","issue_description":"string|null",
   "trade":"string|null","area_type":"unit|common-interior|exterior|amenity|null",
   "severity":1,"recommended_action":"string|null",
   "suggested_owner":"string|null","suggested_timeframe":"string|null"}],
 "no_finding_clips":[{"ref":"ref_7","location":"string|null","note":"string|null"}]}
```

## Output schema

Enforced as `REPORT_RESPONSE_SCHEMA` (Vertex `response_schema`) and then by
`validate_report_content`.

```json
{"executive_summary":"string",
 "action_items":[{"refs":["ref_1","ref_4"],"location":"string","issue":"string","action":"string"}],
 "observations":[{"area":"unit|common-interior|exterior|amenity|general","text":"string","refs":["ref_2"]}]}
```

## Exact prompt text

```text
You write the text of a property site-visit report for a property manager and
regional leadership. They scan it to decide what to fix first. The layout,
the priority tiers, all counts and all links are added by the system; you
supply only the words, as JSON matching the response schema.

INPUT contains actionable_clips (each is one narrated video clip with a real
finding, already rated by severity 1 = safety/urgent to 4 = cosmetic) and
no_finding_clips (clips where nothing needing work was reported). Each clip
has a ref such as ref_3. Refs are the only way to cite a clip.

Produce:

executive_summary: 3 to 5 plain sentences on the overall condition of the
property and the two or three themes that matter most (for example roof
drainage, security of gates and doors, cleanliness of common areas). Lead with
the most serious theme. Mention a clean or well-kept area only if the clips
say so.

action_items: one item per distinct problem.
- Merge clips that show the same problem at the same place into one item and
  list every merged ref. Do not merge different problems just because they
  share a trade or a floor.
- Every actionable ref must appear in exactly one action item. Never cite a
  no_finding ref in an action item.
- location: the clearest short place name, e.g. "Unit 2307, Floor 3" or
  "Pool deck". Use the clip's words; do not invent a unit number.
- issue: one short sentence fragment stating what is wrong, e.g. "AC leaking
  and dripping through the ceiling".
- action: one short imperative stating what to do, based on
  recommended_action when present, e.g. "Have HVAC inspect and repair the
  condensate line". Do not name a vendor, a person, a cost or a date.

observations: up to 8 short bullets that add context the action items do not,
grouped by area (unit, common-interior, exterior, amenity, or general) - such
as patterns across floors or areas the walker said were in good shape. Cite
the refs each bullet draws on. Return an empty list if there is nothing to add.

Rules:
- Use only the information in INPUT. Never invent a finding, location, cost,
  date, vendor or person.
- Never state a number of clips, items, findings or issues anywhere. The
  system prints all counts.
- Never write a ref, a file name, or an identifier inside any text field;
  refs go only in the refs arrays.
- Do not change or comment on severity; the system assigns tiers from it.
- Plain, professional, concrete wording. No headings, bullets or markdown
  inside text fields.
```

## Validation rules

Implemented in `report.validate_report_content`; any breach fails the attempt.

- Response is a JSON object with `executive_summary`, `action_items`, `observations`.
- Every ref exists; action-item refs are actionable; no ref in two action items;
  observation refs are actionable or no-finding.
- No text field contains a filename (`IMG_####`, `.mov` ...), a `ref_<n>`, or a
  25+ character identifier.
- `executive_summary` and observation text state no count of clips/items/findings/issues.
- An actionable ref the model omitted is added back by code as its own item
  (`backfilled_refs` in the run record) — never dropped.
- Two failed attempts → catalogue-only fallback report (`WRITTEN_FALLBACK`),
  stating plainly that the automated summary is unavailable.

## Known limitations / uncertainty behavior

- Merge quality is model judgement; a missed merge shows as two adjacent items.
- An item's tier is the most severe of its merged clips.
- L3 owner/timeframe are suggestions and are labelled as such.
- The count check is a pattern match; an unusual phrasing could slip through.

## Safe update and Git rollback

Change this file, `REPORT_RESPONSE_SCHEMA` and `build_model_input` in one
commit and bump the version. Roll back with `git revert <commit>`.

## How to update this later

Record the lineage of any change (which report defect it answers) in the table
above, bump the semantic version, and add a test in `tests/test_report.py`.
