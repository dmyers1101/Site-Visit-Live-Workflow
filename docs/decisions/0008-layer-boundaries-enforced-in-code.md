# ADR 0008: L2/L3 layer boundaries are enforced by validators, not by prompt text

## Status

Accepted

## Context

The extraction pipeline runs in layers: L1 extracts location, issue
description, and a suggested filename; L2 enriches with trade, area type,
severity, and a recommended action; L3 adds ownership, urgency, and
uncertainty. Each layer is supposed to stay in its lane.

The pilot proved that asking politely does not keep it there. The pilot L3
instruction explicitly permitted correcting earlier fields, and the logged runs
under `pilot/logs/` show what followed. In
`20260807T081748Z_L3_response.txt` — 134 items, the fullest run —
[VERIFIED against the pilot logs, per `prompts/l3-refinement.md`]:

- **10 of 134 records silently rewrote `trade`.** 6 changed `location`, 2
  changed `issue`, 1 changed `area_type`, 1 changed `severity`, relative to the
  L2 record, with no flag beyond a free-text note.
- **Out-of-vocabulary enums.** L3 emitted `pest-control`, `restoration`,
  `painting`, and `drywall` as `trade` values, none of which were in the
  allowed list. The layer permitted to "correct" also quietly widened a closed
  vocabulary.
- **Findings invented from nothing.** In `20260807T080639Z_L3_response.txt`, an
  item whose L1 issue was `null` acquired an invented issue ("Master key not
  working") and had its severity escalated from 2 to 1.
- **Every response was wrapped in a markdown code fence**, and 20 of 134 L3
  objects **echoed the full transcript back** in the response.
- **14 of 134 returned a `null` note** where a note was required.

Every one of these is a case where the prompt said not to and the model did
anyway. A rewritten `trade` is indistinguishable from a correct one once it is
in the catalog; an invented finding becomes a punch-list item someone is
dispatched to fix.

## Decision

Layer boundaries are enforced in code. Prompt text states the boundary; a
validator makes it true.

1. **L3 may not overwrite L1 or L2 values.** The pilot's permission to correct
   earlier fields is removed. L3's output schema does not contain L1 or L2
   fields at all, so there is no channel through which to rewrite one.
2. **Disagreement is reported, not applied.** L3 reports objections via
   `disputed_prior_fields`, an always-present array whose members are drawn only
   from a fixed field list. It is a review signal: nothing downstream may act on
   it automatically. A disputed severity does not change severity; the catalog
   keeps the L2 value until a validated re-run replaces it.
3. **Validators reject, not warn.** Every layer's response passes a validator
   before it is persisted. Rejections include: any unknown key (the object is
   closed), markdown code fences or any prose outside the JSON object, any enum
   value outside its controlled vocabulary, a `null` in a required string, a
   missing key where an explicit `null` was required, an echoed transcript, and
   an identifier that does not match the manifest asset ID.
4. **A layer never runs on an unvalidated input.** L3 runs only on an L2 record
   that validated with `enrichment_status: ENRICHED`; `NO_FINDING` and
   `INSUFFICIENT_EVIDENCE` records are never promoted. An empty transcript
   therefore cannot reach L3 to have a finding invented for it.
5. **Uncertainty downgrades status; it never guesses an enum.**

## Consequences

Prompt text alone proved insufficient, so validation is mandatory — a layer
with no validator does not ship. Each failure mode listed above gets a standing
negative test: rewritten prior field, out-of-vocabulary trade, echoed
transcript, fenced output, null note, invented finding from a null issue.

Strict rejection means some model responses fail outright rather than being
half-accepted. That is the intent. A rejected record becomes `NEEDS_REVIEW` and
reaches a human; a leniently-parsed record becomes a wrong punch-list item that
nobody catches.

Enum vocabularies are now closed and schema-bearing. Adding a `trade` value or
a member of the `disputed_prior_fields` field list is a schema change requiring
an ADR, a catalog migration, and new negative tests in the same reviewed
commit — not a prompt edit.

The validators are the real contract, so the prompt files and the validator
code must be versioned and changed together. Drift between them is the failure
this ADR exists to prevent.

## How to update this later

Do not restore any layer's permission to overwrite an earlier layer's fields.
Do not widen a controlled vocabulary or the closed key set without an ADR, a
catalog schema migration, and new negative validation tests. Keep every pilot
failure above as a permanent negative test even after it stops occurring — the
absence of a failure is not evidence the guard can be removed. Changes to
`prompts/l2-enrichment.md` and `prompts/l3-refinement.md` follow
`prompts/prompt-governance.md` and update their validators first.
