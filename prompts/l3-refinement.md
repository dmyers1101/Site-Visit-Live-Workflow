# L3 refinement prompt

**Semantic version:** 1.2.0

## Purpose

Add controlled ownership, urgency, and uncertainty fields to a single
**validated** L2 result. It is a payload for an explicitly approved external
model run.

**Changed in 1.1.0 (2026-09-17):** the prior statement that "the CLI never
invokes Vertex AI or Gemini automatically" is superseded — `process-folder`
invokes Vertex AI directly from the deployed Cloud Run Job. Preserved here
rather than removed. Layer boundaries are unchanged and are now enforced by
validators in `src/site_visit_workflow/models.py`.

L3
refines; it does not rewrite L1 or L2 fields, and it does not assign work.

## Source/reference lineage

Derived from the pilot symbol `L3_INSTR` in `pilot/run_pipeline.py` and from
the three logged pilot runs under `pilot/logs/`:

- `20260807T080639Z_L3_prompt.txt` / `_L3_response.txt` — 41 items.
- `20260807T081512Z_L3_prompt.txt` / `_L3_response.txt` — single-item run.
- `20260807T081748Z_L3_prompt.txt` / `_L3_response.txt` — 134 items, the
  fullest run; its vocabulary counts are the basis for the enums below.

The controlled vocabularies are the pilot's real ones: `responsible_party`
(`in-house`, `vendor` — both used, 101/33 in the large run) and
`urgency_window` (`immediate`, `this-week`, `this-month`, `routine` — all four
used). The pilot's free-text `notes` field becomes `refinement_note` here, and
the pilot's positional `index` is replaced by the immutable
`source_asset_identifier`.

The pilot's L3 was explicitly permitted to correct earlier fields
("You MAY correct earlier fields"). That permission is **removed** here: the
"Prompt boundaries" section of `prompts/claude-overnight-phase2-trial.md`
limits L3 to ownership, urgency, and uncertainty/note fields, and the binding
prompt wins over the pilot. The pilot logs show why — see the limitations
section. Disagreement is reported via `disputed_prior_fields` instead of being
overwritten. Input contract comes from `prompts/l2-enrichment.md`; governance
from `prompts/prompt-governance.md`.

**Changed in 1.2.0 (2026-09-17):** the full-library run
`20260917T072151Z` had 2 of 16 assets rejected by the L3 validator with
"responsible_party/urgency_window must be null for this status". The model had
partial confidence and kept the single field it was sure of while declaring
INSUFFICIENT_EVIDENCE. The coupling rule was already correct and the validator
behaved correctly; the prompt simply did not say the rule is all-or-nothing.
That is now explicit. No schema or validator change.

## Expected input JSON/text

```json
{"source_asset_identifier":"Drive ID","l2_record_id":"string","l2":{"source_asset_identifier":"Drive ID","prior_layer":"L1","prior_layer_record_id":"string","enrichment_status":"ENRICHED","trade":"string","area_type":"string","severity":"1|2|3|4","recommended_action":"string","enrichment_note":"string"},"l1":{"location":"string","issue_description":"string","suggested_filename":"string","confidence_note":"string"},"transcript_text":"string"}
```

## Exact prompt text

```text
Return JSON only. Return a bare JSON object with no prose and no code fence.
Use the validated L2 record, the validated L1 facts, and the transcript as
evidence. Return exactly these eight keys and no others:
source_asset_identifier, prior_layer, prior_layer_record_id,
refinement_status, responsible_party, urgency_window, disputed_prior_fields,
refinement_note. Copy source_asset_identifier and prior_layer_record_id
exactly from the input; set prior_layer to "L2". Set refinement_status to
REFINED only when the evidence supports both an owner class and an urgency
window; otherwise use INSUFFICIENT_EVIDENCE and set responsible_party and
urgency_window to null. This is all-or-nothing: if you can determine only one
of the two, the status is INSUFFICIENT_EVIDENCE and you must still set BOTH
fields to null. Do not keep the one you are confident about. Put what you did
determine in refinement_note instead. A non-null responsible_party or
urgency_window alongside INSUFFICIENT_EVIDENCE is rejected. responsible_party is one of in-house, vendor.
urgency_window is one of immediate, this-week, this-month, routine.
disputed_prior_fields is an array, possibly empty, whose members are drawn
only from location, issue_description, suggested_filename, trade, area_type,
severity, recommended_action. Do not invent a value outside these lists. Do
not echo the transcript. Do not restate, re-emit, or correct any L1 or L2
field value; if one looks wrong, name it in disputed_prior_fields and explain
in refinement_note. Do not escalate or downgrade severity. Do not return
assignee names, vendor names, dates, task IDs, report text, or Drive filename
changes. State uncertainty in refinement_note; do not fabricate missing
facts, and never derive a finding from an empty transcript.
```

## Output schema

```json
{"source_asset_identifier":"string","prior_layer":"L2","prior_layer_record_id":"string","refinement_status":"REFINED|INSUFFICIENT_EVIDENCE","responsible_party":"in-house|vendor|null","urgency_window":"immediate|this-week|this-month|routine|null","disputed_prior_fields":["location|issue_description|suggested_filename|trade|area_type|severity|recommended_action"],"refinement_note":"string"}
```

`disputed_prior_fields` is always present; an empty array means no dispute.

## Validation rules

- Strict JSON, no prose, no code fence; the key set must match the schema
  exactly. The object is closed — extra keys are a rejection, not a warning.
  Reject an echoed `transcript`, `index`, or any L1/L2 field (both failures
  appear in the pilot L3 responses).
- `source_asset_identifier` must equal the validated L2 and L1 identifiers and
  the selected manifest asset ID; `prior_layer` must be the literal `L2` and
  `prior_layer_record_id` must equal the supplied `l2_record_id`.
- Enum fields must match their fixed value lists exactly, lowercase.
- `refinement_note` is a non-empty string — the pilot returned `null` notes on
  14 of 134 items in `20260807T081748Z_L3_response.txt`; that is a rejection
  here. `disputed_prior_fields` is always present as an array with unique
  members drawn only from the fixed field list. Nullable fields are present
  with an explicit `null`; a missing key is a rejection.
- When `refinement_status` is `REFINED`, `responsible_party` and
  `urgency_window` must both be non-null; when it is `INSUFFICIENT_EVIDENCE`,
  both must be `null`.
- L3 runs only on an L2 record that is validated and whose `enrichment_status`
  is `ENRICHED`. An L2 record with status `NO_FINDING` or
  `INSUFFICIENT_EVIDENCE` must not be sent to L3.
- On uncertainty the model must downgrade the status, never guess an enum.
- A valid result remains a proposal and cannot rename Drive, create a task,
  create a report, or publish Sheets. `urgency_window` is not a due date and
  `responsible_party` is not an assignee.

## Known limitations / uncertainty behavior

- **Silent rewriting of earlier layers is the pilot's proven failure mode.**
  In `20260807T081748Z_L3_response.txt`, 10 of 134 items changed `trade`, 6
  changed `location`, 2 changed `issue`, and 1 each changed `area_type` and
  `severity` relative to the L2 record — with no flag other than a free-text
  note. In `20260807T080639Z_L3_response.txt` an item whose L1 issue was null
  had an issue invented ("Master key not working") and its severity escalated
  from 2 to 1. Removing the correction permission and adding
  `disputed_prior_fields` is the direct countermeasure.
- **Out-of-vocabulary enums.** Pilot L3 emitted `pest-control`, `restoration`,
  `painting`, and `drywall` for `trade`, none of which were in the allowed
  list — the layer that was allowed to "correct" also widened a closed
  vocabulary. L3 no longer emits trade at all; a wrong trade is disputed, not
  replaced.
- **Code fences and echoed transcripts.** Every pilot response was fenced, and
  20 of 134 L3 objects in the large run echoed the transcript. The validator
  must reject both rather than tolerate them.
- `responsible_party` is a class (in-house vs vendor), not a person or a
  company; the pilot vocabulary has no third value, so genuinely mixed or
  unknown ownership must use `INSUFFICIENT_EVIDENCE`. The pilot's strong skew
  to `in-house` should be treated as reviewable, not as a norm.
- `urgency_window` is a review hint derived from narration, not an SLA; the
  binding priority remains manual in the app.
- L3 cannot correct an upstream error. `disputed_prior_fields` is a review
  signal only — nothing downstream may act on it automatically; resolution is
  a human decision or an L1/L2 re-run. A disputed severity does not change
  severity; the catalog keeps the L2 value until a validated re-run replaces
  it.
- An empty or silent transcript never reaches L3, because L2 marks it
  `NO_FINDING` and only `ENRICHED` records are promoted.

## Safe update and Git rollback

Version this file, update its validator and tests first, and obtain prompt
governance approval before any external execution. Enum changes and changes to
the `disputed_prior_fields` field list are schema changes: make them with the
catalog migration and negative tests in the same reviewed commit. Keep a
negative test for each pilot failure above (rewritten prior field,
out-of-vocabulary trade, echoed transcript, fenced output, null note). Use
`git revert <commit>` to roll back and select the prior version explicitly;
preserve previous versioned prompt payloads as audit evidence.

## How to update this later

Do not expand the allowed keys or enum values without an ADR, a catalog schema
migration, and new negative validation tests. Do not restore the pilot's
permission to overwrite earlier layers' fields, and do not add assignment,
scheduling, or publication fields — those cross the layer boundary.
