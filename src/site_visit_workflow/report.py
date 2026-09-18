"""Gate 7: the narrative run report, written into a Google Doc.

Boundary: this module reads the catalogue records the run already holds IN
MEMORY - it never re-reads the Sheet, so the report can never disagree with
what Gate 5 wrote. It calls Vertex exactly once per run through the same
`google-genai` client pattern `extraction.py` uses, and it writes the result
into a Doc with a single `insertText` request. It never issues a Docs delete
request of any kind, never deletes or trashes a Drive file, and never touches a
source video.

Unlike L1/L2/L3 this layer is deliberately UNSTRUCTURED: the output is prose
for a human, so there is no `response_schema` and no strict JSON parse. The
only validation is "non-empty, and not a code fence", per
`prompts/report-synthesis.md` (0.1.0, PLACEHOLDER).

How to update this later
------------------------
The prompt file is the versioned source of truth and is read from
`--prompts-dir` at RUNTIME, exactly like the extraction prompts; a missing file
is a hard stop, never a silent skip. When the placeholder prompt is replaced,
bump its semantic version and revisit `build_report_summary` in the same
commit - the summary shape and the prompt's `## Expected input JSON/text`
block are a pair.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import ExternalServiceError, ValidationError
from .extraction import _VERSION_PATTERN, _fenced_block, _sdk_version
from .models import CODE_FENCE_MARKER, utc_now

REPORT_PROMPT_FILE = "report-synthesis.md"

REPORT_STATUS_WRITTEN = "WRITTEN"
REPORT_STATUS_NOT_REQUESTED = "NOT_REQUESTED"
REPORT_STATUS_SKIPPED_DRY_RUN = "SKIPPED_DRY_RUN"
REPORT_STATUS_FAILED = "FAILED"

# Catalogue columns the report is allowed to see. The report never receives the
# transcript, the GCS URIs, or the Drive IDs: the prompt asks for locations and
# issues, and a narrative layer has no business handling identifiers.
FINDING_FIELDS = (
    "original_drive_name",
    "new_drive_name",
    "location",
    "issue_description",
    "trade",
    "severity",
    "recommended_action",
    "status",
)


@dataclass(frozen=True)
class ReportPrompt:
    """The governed report prompt file, as read from disk for this run."""

    path: str
    version: str
    instruction_text: str
    sha256: str

    def evidence(self) -> dict[str, Any]:
        return {
            "prompt_file": self.path,
            "prompt_version": self.version,
            "prompt_sha256": self.sha256,
        }


def load_report_prompt(prompts_dir: Path) -> ReportPrompt:
    """Read the versioned report prompt at runtime; a missing file is a hard stop.

    Deliberately separate from `extraction.load_prompt_file`: that loader also
    requires an `## Output schema` block, and this layer correctly has none.
    """
    path = Path(prompts_dir) / REPORT_PROMPT_FILE
    if not path.is_file():
        raise ValidationError(
            f"Report prompt file is missing at runtime: {path}. "
            "The versioned prompt file is required before any model call."
        )
    text = path.read_text(encoding="utf-8")
    version_match = _VERSION_PATTERN.search(text)
    if not version_match:
        raise ValidationError("Report prompt file does not declare a **Semantic version:**.")
    instruction = _fenced_block(text, "Exact prompt text", "text")
    if not instruction or not instruction.strip():
        raise ValidationError("Report prompt file has no `## Exact prompt text` block.")
    return ReportPrompt(
        path=str(path),
        version=version_match.group(1),
        instruction_text=instruction.strip(),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _blank_to_none(value: Any) -> Any:
    """Catalogue rows carry "" where a layer did not run; the report sees null."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def build_report_summary(
    run_id: str,
    folder_name: str,
    rows: list[dict[str, Any]],
    generated_at: str | None = None,
    new_names: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Build the compact JSON summary the report prompt consumes.

    `rows` are the in-memory catalogue rows for this run, exactly as Gate 5
    built them. `new_names` maps a Drive asset ID to the name Gate 6 gave it,
    so the report can mention the new filenames; an asset that was not renamed
    carries `null` and is never described as renamed.

    Nothing is invented: an asset with no L2 record contributes no trade and no
    severity, and is still counted and still listed, because silently dropping
    an unassessed clip is the failure mode this report exists to avoid.
    """
    names = new_names or {}
    counts = {"total": len(rows), "catalogued": 0, "needs_review": 0, "failed": 0, "other": 0}
    by_trade: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    findings: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("asset_status") or "UNKNOWN")
        bucket = {
            "CATALOGUED": "catalogued",
            "NEEDS_REVIEW": "needs_review",
            "FAILED": "failed",
        }.get(status, "other")
        counts[bucket] += 1
        trade = _blank_to_none(row.get("l2_trade"))
        if trade:
            by_trade[str(trade)] = by_trade.get(str(trade), 0) + 1
        severity = _blank_to_none(row.get("l2_severity"))
        if severity is not None:
            by_severity[str(severity)] = by_severity.get(str(severity), 0) + 1
        findings.append(
            {
                "original_drive_name": row.get("original_drive_name"),
                "new_drive_name": names.get(str(row.get("row_key"))) or None,
                "location": _blank_to_none(row.get("location")),
                "issue_description": _blank_to_none(row.get("issue_description")),
                "trade": trade,
                "severity": severity,
                "recommended_action": _blank_to_none(row.get("l2_recommended_action")),
                "status": status,
            }
        )
    return {
        "run_id": run_id,
        "folder_name": folder_name,
        "generated_at": generated_at or utc_now(),
        "counts": counts,
        "by_trade": dict(sorted(by_trade.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "findings": findings,
    }


def validate_report_text(text: str) -> str:
    """Non-empty, and not a code fence. No structural validation at 0.1.0."""
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("Report response was empty.")
    if text.strip().startswith(CODE_FENCE_MARKER):
        raise ValidationError("Report response began with a Markdown code fence.")
    return text.strip()


def generate_report_text(
    client: Any, settings: Settings, prompt: ReportPrompt, summary: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """One Vertex call, plain text out. No `response_schema`: this is narrative."""
    try:
        from google.genai import types
    except ImportError as error:
        raise ExternalServiceError("google-genai is not installed.") from error
    contents = prompt.instruction_text + "\n\nINPUT:\n" + json.dumps(summary, sort_keys=True)
    try:
        response = client.models.generate_content(
            model=settings.vertex_model,
            contents=contents,
            config=types.GenerateContentConfig(temperature=0.0),
        )
    except Exception as error:  # noqa: BLE001 - one boundary, one error type
        raise ExternalServiceError(f"Report Vertex request failed: {error}") from error
    usage: dict[str, Any] = {}
    metadata = getattr(response, "usage_metadata", None)
    if metadata is not None:
        for name in ("prompt_token_count", "candidates_token_count", "total_token_count"):
            usage[name] = getattr(metadata, name, None)
    return validate_report_text(response.text or ""), usage


def compose_document_text(
    run_id: str, folder_name: str, generated_at: str, narrative: str
) -> str:
    """Title line, run ID, date, then the model's narrative. Inserted as one block."""
    return (
        f"Site visit report - {folder_name}\n"
        f"Run ID: {run_id}\n"
        f"Generated: {generated_at}\n\n"
        f"{narrative.strip()}\n\n"
    )


@dataclass(frozen=True)
class ReportRecord:
    """The complete, auditable record of the one report call and Doc write."""

    run_id: str
    status: str
    document_id: str | None = None
    document_web_link: str | None = None
    document_created: bool = False
    model_id: str | None = None
    prompt_file: str | None = None
    prompt_version: str | None = None
    prompt_sha256: str | None = None
    sdk_version: str | None = None
    character_count: int = 0
    generated_at: str | None = None
    written_at: str | None = None
    error: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    summary_counts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def run_report(
    client: Any,
    settings: Settings,
    docs: Any,
    prompts_dir: Path,
    document_id: str,
    document_web_link: str | None,
    document_created: bool,
    folder_name: str,
    rows: list[dict[str, Any]],
    new_names: dict[str, str | None] | None = None,
) -> ReportRecord:
    """Gate 7 end to end: summarize, call Vertex once, insert into the Doc.

    The caller resolves the document ID before the asset loop, so a report
    failure here still leaves an operator able to find the Doc.
    """
    from .google import insert_document_text

    prompt = load_report_prompt(prompts_dir)
    generated_at = utc_now()
    summary = build_report_summary(
        settings.run_id, folder_name, rows, generated_at=generated_at, new_names=new_names
    )
    narrative, usage = generate_report_text(client, settings, prompt, summary)
    body = compose_document_text(settings.run_id, folder_name, generated_at, narrative)
    insert_document_text(docs, document_id, body)
    return ReportRecord(
        run_id=settings.run_id,
        status=REPORT_STATUS_WRITTEN,
        document_id=document_id,
        document_web_link=document_web_link,
        document_created=document_created,
        model_id=settings.vertex_model,
        prompt_file=prompt.path,
        prompt_version=prompt.version,
        prompt_sha256=prompt.sha256,
        sdk_version=_sdk_version(),
        character_count=len(body),
        generated_at=generated_at,
        written_at=utc_now(),
        usage=usage,
        summary_counts=summary["counts"],
    )
