# Google Docs API — formatting, tables, replace-in-place (pulled 2026-10-07)

Sources:
- https://developers.google.com/workspace/docs/api/how-tos/tables (page updated 2026-09-03)
- https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request (page updated 2026-09-30)

Library: `google-api-python-client>=2.169.0` (discovery-based `docs` v1). No new pin needed.

Confirmed shapes:
- `batchUpdate` applies its requests in order and atomically: an invalid request
  means none are applied. `writeControl.requiredRevisionId` makes it fail if the
  Doc changed since it was read.
- `deleteContentRange.range` = `{startIndex, endIndex, tabId}`. Cannot delete the
  final newline of the body, so a full clear is `[1, bodyEnd - 1)`; skip when empty.
  A range that covers whole tables is allowed.
- `insertText.location` = `{index, tabId}`. Indices are UTF-16 code units.
- `updateParagraphStyle` `{range, paragraphStyle{namedStyleType|indentStart|...}, fields}`.
- `updateTextStyle` `{range, textStyle{bold|link{url}|fontSize{magnitude,unit}|foregroundColor}, fields}`;
  a field in the mask with no value resets it.
- `createParagraphBullets` `{range, bulletPreset}` — `BULLET_DISC_CIRCLE_SQUARE` used.
  Leading tabs set nesting AND are removed (shifts indices) — not used here.
- `deleteParagraphBullets` `{range}`.

Gotchas that shaped the design (ADR 0013):
- **"You cannot insert a table and write to its cells within a single batchUpdate."**
  A table report would need two batches and so could not be cleared-and-written
  atomically. The report therefore uses headings, bullets, bold, links and small
  grey text — no tables.
