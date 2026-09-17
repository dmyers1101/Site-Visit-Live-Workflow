# GCP API research record

**Research date:** 2026-09-16

The CLI has an intentionally explicit integration boundary for these APIs, but
this repository has not executed live cloud tests. Validate current API
behavior, regional availability, SDK versions, pricing, quotas, and model
configuration before any live command.

| Service | Official documentation | Setup and caveats |
| --- | --- | --- |
| Google Drive API | https://developers.google.com/workspace/drive/api/guides/about-sdk | Immediate-child listing uses `supportsAllDrives` / `includeItemsFromAllDrives`; validate configured-folder access before execution. |
| Cloud Storage | https://cloud.google.com/storage/docs | Use a dedicated staging prefix and least-privilege object access; retain staged artifacts. |
| Speech-to-Text v2 | https://cloud.google.com/speech-to-text/v2/docs | The explicit batch boundary requests `chirp_3` for one WAV; confirm current regional availability and request shape before execution. |
| Vertex AI | https://cloud.google.com/vertex-ai/generative-ai/docs | Use only the approved extraction prompt and strict JSON response validation. Confirm model IDs at implementation time. |
| Google Sheets API | https://developers.google.com/workspace/sheets/api | Upsert draft rows using the immutable source ID rather than appending duplicates. |

## How to update this later

Before wiring each API, add the exact library version, configuration command, tested request shape, and dated official URL to this record. Never include credential values.
