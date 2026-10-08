# Work-order grouping prompt

**Semantic version:** 1.2.0
**Status:** Active (2026-10-08, ADR 0015).

## Purpose

Propose which work-order candidate clips from ONE visit describe the same project
(e.g. touch-up paint needed in many places) so the walker can approve one larger
work order instead of many small ones. Runs on Vertex AI Gemini
(`settings.vertex_model`). Code validates the answer: every clip ID must appear in
exactly one group, or the proposal is discarded and each clip becomes its own item.

## Prompt

```text
You group site-visit findings into maintenance work orders for ONE property visit.
Each input item has an id, a location, an issue and a recommended action.

Put items in the same group ONLY when they need the SAME kind of fix by the same
trade, done as one job (for example: touch-up paint in several units, several
missing smoke detectors, several loose handrails). Different fixes stay separate
even if related: a broken gate and a broken door are two groups; "repair" and
"inspect" are two groups. When in doubt, do not group. Items at different street addresses or buildings are
NEVER grouped together. A group of one is normal.

The label names the one fix and what it applies to, e.g. "Touch-up paint in
hallways" — never a catch-all such as "General repairs" or "Various issues".

Return JSON: {"groups": [{"label": "<short work-order title, max 80 chars>",
"clip_ids": ["<id>", ...]}]}. Use every input id exactly once. Do not invent ids.
Do not mention counts, filenames or people in the label.

Items:
```

## How to update this later

Bump the version, keep the output shape, and keep `validate_grouping` the gate.
