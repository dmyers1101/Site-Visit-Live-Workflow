# Workflow package

`site-visit` is a Python 3.11 CLI. Imports and `config-check` do not call
Google. `intake`, `stage-video`, `transcribe`, `rename-drive`, and
`publish-catalog` are explicitly named external actions. All source selection
is constrained by a manifest created from one immediate visit folder.

The domain contracts in `models.py` preserve original Drive identifiers and
names, enforce the L1 allow-list, make catalog rows idempotent by Drive ID,
and require a matching approval record before mutation.

## Cloud-native end-to-end run (`process-folder`)

`process-folder` runs Gates 1 to 5 inside the deployed Cloud Run Job. Media
bytes flow **Drive -> the container's ephemeral filesystem -> GCS**; no
operator workstation is ever involved.

| Module | Role |
| --- | --- |
| `discovery.py` | Pure Gate 1: classify direct Drive children, record every exclusion reason, build the manifest. |
| `google.py` | The only Drive/GCS/Speech/Sheets boundary. `StorageGateway` is create-only. |
| `media.py` | ffprobe capture plus the mono 16 kHz PCM WAV contract, verified after transcoding. |
| `extraction.py` | Vertex L1 -> L2 -> L3 over `google-genai`, reading `prompts/*.md` at runtime. |
| `catalog.py` | Pure Gate 5: one ordered catalog row per asset, keyed by the immutable Drive asset ID. |

Safety properties this package holds by construction:

- **Nothing is ever deleted.** No Drive file, GCS object, Sheets row, Sheets
  tab, or staged local file is deleted, trashed, or truncated. GCS writes use
  an `if_generation_match=0` precondition and fail rather than overwrite; the
  runtime identity has no GCS delete permission by design.
- **Drive is never renamed automatically.** Suggested filenames are proposals
  recorded in the catalog and awaiting human approval.
- **An empty transcript is retried once, then becomes `NEEDS_REVIEW`.** The
  extraction path stops; no finding is inferred from silence.
- **Assets are processed sequentially** — conservative concurrency of one.

Selectors: `--limit N`, `--asset-id ID`, and `--dry-run` (everything except the
Chirp, Vertex, and Sheets calls) make a single-asset trial cheap.

## How to update this later

Add a contract test before changing a model, status, or CLI argument. Preserve
the manifest schema and immutable Drive fields; version any incompatible
schema change and amend the appropriate prompt and runbook in the same change.
