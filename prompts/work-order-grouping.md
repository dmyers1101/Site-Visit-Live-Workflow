# Work-order grouping prompt

**Semantic version:** 1.0.0
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

Put items in the same group ONLY when one vendor or crew would do them as one job
(for example: touch-up paint in several units, several missing smoke detectors,
several trip hazards on the same walkway). Different trades, or unrelated problems,
stay in separate groups. A group of one is normal.

Return JSON: {"groups": [{"label": "<short work-order title, max 80 chars>",
"clip_ids": ["<id>", ...]}]}. Use every input id exactly once. Do not invent ids.
Do not mention counts, filenames or people in the label.

Items:
```

## How to update this later

Bump the version, keep the output shape, and keep `validate_grouping` the gate.
