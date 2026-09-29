# Google Docs API — tabs (pulled 2026-09-29)

Sources:
- https://developers.google.com/workspace/docs/api/how-tos/tabs (page updated 2026-09-03)
- https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request
- https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/response

Library: `google-api-python-client>=2.169.0` (discovery-based; `docs` v1). No new pin needed.

Confirmed shapes:
- Read tabs: `documents.get(documentId, includeTabsContent=True)` → `tabs[].tabProperties{tabId,title}`,
  `tabs[].documentTab.body`, `childTabs[]`. Without the flag only the first tab's content is returned.
- Create: batchUpdate `{"addDocumentTab": {"tabProperties": {"title": ...}}}` →
  reply `replies[i].addDocumentTab.tabProperties.tabId`. Verified live 2026-09-29.
- Rename: `{"updateDocumentTabProperties": {"tabProperties": {"tabId", "title"}, "fields": "title"}}`.
- Write into a tab: `insertText.location = {"index": 1, "tabId": ...}`.
- Exists but NEVER used here: `deleteTab`.

Gotchas:
- A new Doc has one default tab (`t.0`, "Tab 1"); `_write_visit_report` reuses it if empty and unclaimed.
- Vertex 429s happen at report time; all Vertex calls go through `extraction.generate_with_backoff`.
