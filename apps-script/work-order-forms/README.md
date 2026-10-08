# Work-order confirmation forms (Apps Script)

Purpose: email each walker one Google Form per visit asking, per proposed work
order, *create one · split per clip · already exists · skip*; record the answer
in the master catalog `WorkOrders` tab. It never touches AppFolio (ADR 0015).

| | |
| --- | --- |
| Script project | `14k6OVngL3CQEiLY99wwyIqcHn2G7mx2Rnb9bGiJebDYgRInXu8lQ3mVd` — "Site Visit - Work Order Forms" |
| Runs as | `dmyers@shircapital.com` (project owner) |
| Sends as | `SENDER_FROM`, blank for now; swap to `sitevisits@` when the admin creates it, then run `testSendAs` |
| Scheduled | installable time trigger `hourly` (created by `installTrigger`) |
| Writes | master catalog Sheet, tab `WorkOrders`; forms in `FORMS_FOLDER_ID` |

Script Properties are documented at the top of `Code.gs`. Set `DRY_RUN=1` for the
first run and read the execution log before clearing it.

Deploy: `clasp push` from a scratch copy holding `.clasp.json` (kept out of the repo);
pull and diff first so an editor change is never overwritten. `clasp run` is not
available — run `testSendAs`, `installTrigger` and `hourly` from the editor.
