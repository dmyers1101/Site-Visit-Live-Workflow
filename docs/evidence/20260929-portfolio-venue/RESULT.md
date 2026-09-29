# Portfolio first runs — Venue / 2026-08 Regional - Tony Corsa (2026-09-29)

Visit folder `1yfvpNuJb5qHEUT2c66IJORIiqke5fluo` (6 videos, 2 HEIC). Identity:
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`. Master Sheet
`1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o`.

## Preceding steps
| Execution | Image | Command | Result |
| --- | --- | --- | --- |
| `site-visit-workflow-58pxq` | `portfolio-inv-20260929` | `list-portfolio` | 7 visits / 5 properties / 224 clips / 210 pending. SA can read the whole master tree. Cross-checked 9 "empty" visit folders with the operator's Drive access: only Venue/Laura Beynon has videos, matching the walk. |
| `site-visit-workflow-xzvnt` | `portfolio-20260929a` | `migrate-catalog --source-sheet-id 1GW3fg8I…` | Master Sheet created by the SA in the master folder; 16 rows copied (A1:AP17); uploader resolved to `pvaidya@shircapital.com` via first revision (SA was last modifier after the 09-18 renames). Source Sheet untouched. |

## Run 1 — `20260929-portfolio-venue-01` (`site-visit-workflow-fp56t`, image `portfolio-20260929b`)
`process-portfolio --visit-id 1yfvp… --rename-approved --report`
- 6 processed: 3 CATALOGUED, 3 NEEDS_REVIEW (2 empty transcripts; 1 L2 rejection "area_type cannot be null").
- **Defect:** the 3 CATALOGUED clips had L1 location=null AND issue=null and were renamed
  `no_location_no_issue.MOV`, `unspecified_content.MOV`, `positive_observation.MOV`.
  Restored by the operator's session (Drive API, as dmyers@) to `IMG_1026.MOV`, `IMG_1027.MOV`,
  `IMG_1037.MOV`. Their Sheet rows still read `RENAMED_TO:…` (historical). Fixed in code:
  `rename.l1_has_finding`.
- **Defect:** report failed — Vertex `429 RESOURCE_EXHAUSTED`. Fixed: `generate_with_backoff`;
  report-due rule so a failed report is retried next run.

## Run 2 — `20260929-portfolio-venue-02` (`site-visit-workflow-vwlzp`, image `portfolio-20260929c`)
Same args.
- **I3 idempotency: pending 0, processed 0** — no clip reprocessed.
- **Self-heal:** report WRITTEN into Doc `12jxtI37hoNLiHrTeotCCco63kicoYT1YYBN2VYuEGG0`
  ("Venue Site Visit Reports", in the Venue property folder), default tab `t.0` reused and retitled
  `2026-09-25 · paregional`. Counts line `Clips reviewed: 6 … Needs human review: 3` matches the Sheet.
- Uploader `paregional` is the Drive account's display name (a shared login), per ADR 0011.
