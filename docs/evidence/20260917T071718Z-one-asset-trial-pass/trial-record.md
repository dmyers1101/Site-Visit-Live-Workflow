# One-asset trial — 20260917T071718Z — PASS

**Run ID:** `20260917T071718Z`
**Execution:** `site-visit-workflow-86w58`
**Image:** `…/site-visit:pipeline-r2`
**Identity:** `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`
**Command:** `site-visit process-folder --limit 1`
**Result:** **All five gates passed.** `status_counts: {"CATALOGUED": 1}`

First fully successful end-to-end run. Every Google API call originated from the
deployed Cloud Run Job as the service account. No key file, no impersonation, no
personal Drive OAuth, no media on any workstation.

## Artifacts produced

```
20260917T071718Z/manifest.json
20260917T071718Z/run-summary.json
20260917T071718Z/<asset>/media-preparation.json
20260917T071718Z/<asset>/audio/attempt-0/<asset>.wav
20260917T071718Z/<asset>/speech-output/attempt-0/<asset>_transcript_….json
20260917T071718Z/<asset>/transcript.txt
20260917T071718Z/<asset>/transcription-record.json
20260917T071718Z/<asset>/prompt-execution/l1.json
20260917T071718Z/<asset>/prompt-execution/l2.json
20260917T071718Z/<asset>/prompt-execution/l3.json
20260917T071718Z/<asset>/catalog-row.json
20260917T071718Z/<asset>/catalog-upsert-record.json
```

## Gate 3 — real transcript

Chirp returned real speech from `IMG_3651.MOV`, opening:

> "Alma hallway one. I would say this side of the building which is in the back
> here does not look great. It clearly has not been vacuumed or cleaned up in a
> little bit…"

This confirms `SPEECH_LOCATION=us` with `chirp_3` and gs:// input/output works.

## Gate 4 — layer boundaries held

| Layer | Prompt | Result |
| --- | --- | --- |
| L1 | 1.2.0 | location "outside unit 2107", issue "Water dripping from siding, indicating a potential leak.", suggested filename, confidence note. **No trade, severity, or priority** — boundary respected. |
| L2 | 1.1.0 | `ENRICHED`, `area_type: exterior`, recommended action, traceability to the L1 record id. |
| L3 | 1.1.0 | `INSUFFICIENT_EVIDENCE`, `responsible_party: null`, `disputed_prior_fields: []`, and an honest note that the transcript does not support an ownership or urgency call. |

L3's behaviour is the important result. The pilot, in the same situation,
fabricated ownership and escalated severity. Here it declined and said why. The
validators and the prompt boundaries are doing what ADR 0008 requires.

## What this run proves

1. The cloud-native media path works: Drive → Cloud Run container → GCS.
2. `SPEECH_LOCATION=us` fixes the recognizer region bug found in preflight.
3. The prompts ship in the image and are read at runtime.
4. The Gate 3 double-write fix is effective — no delete permission was needed.
5. The Sheets tab is created and the row upserted with the Drive asset ID key.

## How to update this later

Create a new dated directory per run; never overwrite this one.
