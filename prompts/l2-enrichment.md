# L2 enrichment prompt

**Semantic version:** 1.0.0

## Purpose

Add controlled analysis fields to a single **validated** L1 result. It is a
payload for an explicitly approved external model run; the CLI never invokes
Vertex AI or Gemini automatically. L2 enriches; it does not re-extract, does
not correct L1 facts, and does not create work.

## Source/reference lineage

Derived from the pilot symbol `L2_INSTR` in `pilot/run_pipeline.py` and from
the three logged pilot runs under `pilot/logs/`:

- `20260807T080639Z_L2_prompt.txt` / `_L2_response.txt` — 41 items.
- `20260807T081512Z_L2_prompt.txt` / `_L2_response.txt` — single-item run.
- `20260807T081748Z_L2_prompt.txt` / `_L2_response.txt` — 134 items, the
  fullest run; its vocabulary counts are the basis for the enums below.

The controlled vocabularies are the pilot's real ones, not new terms.
`trade` (all eight values, of which seven appear in
`20260807T081748Z_L2_response.txt`), `area_type` (all four values appear), and
`severity` as the pilot's integer 1-4 scale — kept as integers rather than
renamed to words, per the observed vocabulary. Field naming follows
`prompts/l1-extraction.md` (`issue_description`, `suggested_filename`) rather
than the pilot's `issue` / `descriptive_filename`, and the pilot's positional
`index` is replaced by the immutable `source_asset_identifier`.
`prompts/l1-extraction.md` fixes L1's field set; trade and priority are never
extracted at L1 (see the ADR reversing LD-2), and priority remains manual in
the app — L2 emits severity, not priority. The layer boundary is set by the
"Prompt boundaries" section of `prompts/claude-overnight-phase2-trial.md` and
by `prompts/prompt-governance.md`; where the pilot conflicts with those, they
win. The pilot dropped empty transcripts upstream
(`20260807T081748Z_chirp_transcripts.jsonl`: 7 of 141 empty, never reaching
L1), so empty-input behavior was never exercised and is specified here
explicitly instead of inherited.

## Expected input JSON/text

```json
{"source_asset_identifier":"Drive ID","l1_record_id":"string","l1":{"source_asset_identifier":"Drive ID","location":"string","issue_description":"string","suggested_filename":"string","confidence_note":"string"},"transcript_text":"string"}
```

## Exact prompt text

```text
Return JSON only. Return a bare JSON object with no prose and no code fence.
Use the validated L1 record and the transcript as evidence. Return exactly
these nine keys and no others: source_asset_identifier, prior_layer,
prior_layer_record_id, enrichment_status, trade, area_type, severity,
recommended_action, enrichment_note. Copy source_asset_identifier and
prior_layer_record_id exactly from the input; set prior_layer to "L1".
Set enrichment_status to ENRICHED only when the transcript states a
maintenance issue; use NO_FINDING when the transcript records no issue,
records a positive observation, or is empty, and INSUFFICIENT_EVIDENCE when
an issue is implied but cannot be classified. When the status is not
ENRICHED, set trade, area_type, severity, and recommended_action to null.
trade is one of plumbing, electrical, hvac, landscaping, cleaning,
general-maintenance, safety, structural. area_type is one of unit,
common-interior, exterior, amenity. severity is the integer 1, 2, 3, or 4,
where 1 is urgent/safety, 2 is high, 3 is medium, and 4 is low/cosmetic.
recommended_action is one concrete next step. Do not invent a value outside
these lists. Do not echo the transcript. Do not restate, correct, or return
location, issue_description, or suggested_filename. Do not return priority,
owner, assignee, due date, task, report, or Drive filename changes. State
uncertainty in enrichment_note; do not fabricate missing facts, and never
derive a finding from an empty transcript or from a null L1
issue_description.
```

## Output schema

```json
{"source_asset_identifier":"string","prior_layer":"L1","prior_layer_record_id":"string","enrichment_status":"ENRICHED|NO_FINDING|INSUFFICIENT_EVIDENCE","trade":"plumbing|electrical|hvac|landscaping|cleaning|general-maintenance|safety|structural|null","area_type":"unit|common-interior|exterior|amenity|null","severity":"1|2|3|4|null","recommended_action":"string|null","enrichment_note":"string"}
```

`severity` is an integer enum (`1|2|3|4`) or `null` — never a string.

## Validation rules

- Strict JSON, no prose, no code fence; the key set must match the schema
  exactly. The object is closed — extra keys are a rejection, not a warning.
  Reject an echoed `transcript`, `index`, or any L1 field (this is the exact
  failure seen in every pilot L2 response).
- `source_asset_identifier` must equal the validated L1 identifier and the
  selected manifest asset ID; `prior_layer` must be the literal `L1` and
  `prior_layer_record_id` must equal the supplied `l1_record_id`.
- Enum fields must match their fixed value lists exactly, lowercase;
  `severity` must be an integer 1-4, not a string and not out of range.
- `enrichment_note` is a non-empty string. Every other nullable field is
  present with an explicit `null`; a missing key is a rejection.
- When `enrichment_status` is `ENRICHED`, `trade`, `area_type`, `severity`,
  and `recommended_action` must all be non-null. When it is `NO_FINDING` or
  `INSUFFICIENT_EVIDENCE`, all four must be `null`.
- If the input `transcript_text` is empty or the L1 `issue_description` is
  null or empty, the only acceptable status is `NO_FINDING`. Any enriched
  result on that input is a rejection.
- On uncertainty the model must downgrade the status, never guess an enum:
  unclassifiable evidence is `INSUFFICIENT_EVIDENCE` with the reason recorded
  in `enrichment_note`.
- L1 must be validated before L2 runs; L2 on an unvalidated or rejected L1
  result is a rejection.
- A valid result remains a proposal and cannot rename Drive, create a task,
  create a report, or publish Sheets.

## Known limitations / uncertainty behavior

- **Inventing findings from a non-finding is the pilot's proven failure mode.**
  In `20260807T081748Z_L2_response.txt` the items whose L1 `issue` was null
  were still assigned a trade, a severity, and a recommended action — one of
  them a positive observation about rock beds that became a landscaping item.
  The same happens in `20260807T080639Z_L2_response.txt`. The
  `enrichment_status` gate and the null-coupling rule above exist to stop it.
- **Key leakage.** Every pilot L2 response re-emitted `transcript` alongside
  the requested keys. The closed key set and the explicit "do not echo the
  transcript" instruction are the countermeasure; the validator must enforce
  it rather than ignore unknown keys.
- **Code fences.** Every pilot response was wrapped in a ```json fence despite
  "Return ONLY a JSON array"; the pilot tolerated it with a lenient parser.
  This prompt asks for a bare object and the validator should reject fences
  rather than strip them silently.
- **Vocabulary gaps are real.** The eight-value `trade` list has no pest
  control, painting, drywall, or restoration category; a pilot ant-colony item
  landed in `general-maintenance`. Classify to the nearest allowed value and
  record the gap in `enrichment_note`. Adding a value requires an ADR and a
  catalog migration — never an ad-hoc string.
- Severity is a transcript-derived judgment, not an inspection finding, and
  the pilot distribution skewed to 2 and 3 on ambiguous narration; treat it as
  reviewable. It carries no due date or priority — priority stays manual in
  the app.
- `trade` and `area_type` are single-valued; genuinely mixed items must pick
  the dominant value and record the ambiguity in `enrichment_note`.
- L2 cannot repair a wrong or null L1 location or issue. It records the
  conflict in `enrichment_note` and leaves correction to human review or an L1
  re-run.

## Safe update and Git rollback

Version this file, update its validator and tests first, and obtain prompt
governance approval before any external execution. Enum changes are schema
changes: add the value, migrate the catalog, and add negative tests in the
same reviewed commit. Keep a negative test for each pilot failure above
(echoed transcript, fenced output, enriched non-finding). Use
`git revert <commit>` to roll back and select the prior version explicitly;
preserve previous versioned prompt payloads as audit evidence.

## How to update this later

Do not expand the allowed keys or enum values without an ADR, a catalog schema
migration, and new negative validation tests. Any field that assigns work,
ownership, or a date belongs to L3 or to the app, not here.
