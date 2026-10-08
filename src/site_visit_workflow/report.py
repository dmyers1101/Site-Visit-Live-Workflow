"""Gate 7: the structured visit report, written into a Google Doc tab.

Boundary: this module reads the catalogue rows the caller already holds - it
never re-reads the Sheet - so the report can never disagree with what Gate 5
wrote. It calls Vertex (Gemini, via `google-genai`) for WORDS ONLY and builds
the document LAYOUT in code.

Division of labour (report-synthesis 1.0.0, ADR 0013):
- Code routes every clip to exactly one place (action item / needs review /
  no finding) from EXPLICIT statuses, assigns the tier from L2 severity, writes
  every count, attaches every clip link, and builds the Docs requests.
- The model returns schema-validated JSON: an executive summary, merged action
  items that cite clips by short reference (`ref_1`, `ref_2` ...), and observations
  by area. It never sees Drive IDs, links, or filenames.
- Validation rejects an unknown or non-actionable reference, a stated count, a
  filename or an ID. After two failed attempts the report falls back to a
  catalogue-only rendering rather than publishing unvalidated text.
- An actionable clip the model forgot is added back by code as its own item,
  so no finding is ever silently dropped.

How to update this later
------------------------
The prompt file is read from `--prompts-dir` at RUNTIME; a missing file is a
hard stop. `REPORT_RESPONSE_SCHEMA`, `build_model_input` and the prompt's
`## Expected input JSON/text` / `## Output schema` blocks are one unit: change
them together and bump the prompt version.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import ExternalServiceError, ValidationError
from .extraction import _VERSION_PATTERN, _fenced_block, _sdk_version, generate_with_backoff
from .models import CODE_FENCE_MARKER, utc_now

REPORT_PROMPT_FILE = "report-synthesis.md"

REPORT_STATUS_WRITTEN = "WRITTEN"
REPORT_STATUS_WRITTEN_FALLBACK = "WRITTEN_FALLBACK"
REPORT_STATUS_NOT_REQUESTED = "NOT_REQUESTED"
REPORT_STATUS_SKIPPED_DRY_RUN = "SKIPPED_DRY_RUN"
REPORT_STATUS_FAILED = "FAILED"

MODEL_ATTEMPTS = 2

# Where a clip lands in the report. Decided from explicit status values only.
BUCKET_ACTION = "ACTION"
BUCKET_REVIEW = "REVIEW"
BUCKET_NO_FINDING = "NO_FINDING"
BUCKET_TRACKED = "ALREADY_TRACKED"

TIERS = (
    ("immediate", "Immediate — safety (severity 1)", (1,)),
    ("priority", "Priority (severity 2)", (2,)),
    ("routine", "Routine (severity 3–4)", (3, 4)),
)
AREA_TITLES = {
    "unit": "Units",
    "common-interior": "Common interior",
    "exterior": "Exterior",
    "amenity": "Amenities",
    "general": "General",
}


# --- Prompt -------------------------------------------------------------------


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
    """Read the versioned report prompt at runtime; a missing file is a hard stop."""
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


# --- Summary (pure) -----------------------------------------------------------


def _blank_to_none(value: Any) -> Any:
    """Catalogue rows carry "" where a layer did not run; the report sees null."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _severity(value: Any) -> int | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return number if 1 <= number <= 4 else None


def classify_row(row: dict[str, Any]) -> tuple[str, str | None]:
    """(bucket, review reason) from EXPLICIT statuses. A blank never means "no finding".

    - CATALOGUED + L2 ENRICHED + severity 1-4  -> ACTION
    - CATALOGUED + L2 NO_FINDING               -> NO_FINDING
    - CATALOGUED + L2 ALREADY_TRACKED          -> ALREADY_TRACKED (listed, not a new item)
    - everything else                           -> REVIEW, with the reason
    """
    asset_status = str(row.get("asset_status") or "").strip()
    l2_status = str(row.get("l2_status") or "").strip()
    if asset_status == "FAILED":
        return BUCKET_REVIEW, "Processing failed; the clip was not assessed"
    if asset_status == "NEEDS_REVIEW":
        return BUCKET_REVIEW, "Transcript or extraction needs a person to check it"
    if asset_status != "CATALOGUED":
        return BUCKET_REVIEW, f"Unrecognised status {asset_status or '(blank)'}"
    if l2_status == "NO_FINDING":
        return BUCKET_NO_FINDING, None
    if l2_status == "ALREADY_TRACKED":
        return BUCKET_TRACKED, None
    if l2_status == "INSUFFICIENT_EVIDENCE":
        return BUCKET_REVIEW, "Not enough detail in the narration to assess"
    if l2_status == "ENRICHED":
        if _severity(row.get("l2_severity")) is None:
            return BUCKET_REVIEW, "Finding recorded without a valid severity"
        return BUCKET_ACTION, None
    return BUCKET_REVIEW, f"Assessment not run (L2 status {l2_status or '(blank)'})"


def tier_for(severity: int) -> str:
    for key, _title, levels in TIERS:
        if severity in levels:
            return key
    raise ValidationError(f"Severity {severity!r} has no tier.")


def _most_common(values: list[str]) -> str | None:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return max(sorted(counts), key=lambda k: counts[k]) if counts else None


def build_report_summary(
    run_id: str,
    folder_name: str,
    rows: list[dict[str, Any]],
    generated_at: str | None = None,
    new_names: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Everything the report needs, computed in code. One `clip` per input row.

    Each clip gets a short reference `ref_<n>` (input order), its bucket, and the
    fields the model and the renderer use. Counts come only from here.
    """
    names = new_names or {}
    counts = {"total": len(rows), "catalogued": 0, "needs_review": 0, "failed": 0, "other": 0,
              "action": 0, "review": 0, "no_finding": 0, "tracked": 0}
    clips: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        status = str(row.get("asset_status") or "UNKNOWN")
        counts[{"CATALOGUED": "catalogued", "NEEDS_REVIEW": "needs_review",
                "FAILED": "failed"}.get(status, "other")] += 1
        bucket, reason = classify_row(row)
        counts[{BUCKET_ACTION: "action", BUCKET_REVIEW: "review",
                BUCKET_NO_FINDING: "no_finding", BUCKET_TRACKED: "tracked"}[bucket]] += 1
        severity = _severity(row.get("l2_severity"))
        new_name = names.get(str(row.get("row_key"))) or None
        clips.append({
            "ref": f"ref_{index}",
            "row_key": str(row.get("row_key") or ""),
            "bucket": bucket,
            "review_reason": reason,
            "status": status,
            "location": _blank_to_none(row.get("location")),
            "issue_description": _blank_to_none(row.get("issue_description")),
            "trade": _blank_to_none(row.get("l2_trade")),
            "area_type": _blank_to_none(row.get("l2_area_type")),
            "severity": severity,
            "tier": tier_for(severity) if bucket == BUCKET_ACTION else None,
            "recommended_action": _blank_to_none(row.get("l2_recommended_action")),
            "suggested_owner": _blank_to_none(row.get("l3_responsible_party")),
            "suggested_timeframe": _blank_to_none(row.get("l3_urgency_window")),
            "link": _blank_to_none(row.get("drive_link")),
            "work_order": str(row.get("work_order_requested") or "").strip().upper() == "YES",
            "display_name": new_name or _blank_to_none(row.get("original_drive_name")) or f"Clip {index}",
        })
    dates = sorted(str(r.get("uploaded_at") or "")[:10] for r in rows if _blank_to_none(r.get("uploaded_at")))
    visit = {
        "property": _most_common([str(r.get("property") or "").strip() for r in rows]),
        "visit_name": _most_common([str(r.get("visit_name") or "").strip() for r in rows]),
        "walked_by": _most_common(
            [str(r.get("uploader_name") or r.get("uploader_email") or "").strip() for r in rows]),
        "visit_date": dates[-1] if dates else None,
    }
    return {
        "run_id": run_id,
        "folder_name": folder_name,
        "generated_at": generated_at or utc_now(),
        "counts": counts,
        "visit": visit,
        "clips": clips,
    }


def build_model_input(summary: dict[str, Any]) -> dict[str, Any]:
    """What the model sees: references and words only. No IDs, links or filenames."""
    actionable, no_finding = [], []
    for clip in summary["clips"]:
        if clip["bucket"] == BUCKET_ACTION:
            actionable.append({key: clip[key] for key in (
                "ref", "location", "issue_description", "trade", "area_type", "severity",
                "recommended_action", "suggested_owner", "suggested_timeframe")})
        elif clip["bucket"] == BUCKET_NO_FINDING:
            no_finding.append({"ref": clip["ref"], "location": clip["location"],
                               "note": clip["issue_description"]})
    return {
        "property": summary["visit"]["property"] or summary["folder_name"],
        "actionable_clips": actionable,
        "no_finding_clips": no_finding,
    }


# --- Model output: schema + validation ---------------------------------------

def _str(nullable: bool = False, enum: tuple[str, ...] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "STRING"}
    if nullable:
        schema["nullable"] = True
    if enum:
        schema["enum"] = list(enum)
    return schema


_REFS = {"type": "ARRAY", "items": {"type": "STRING"}}

REPORT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "executive_summary": _str(),
        "action_items": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"refs": _REFS, "location": _str(), "issue": _str(), "action": _str()},
            "required": ["refs", "location", "issue", "action"],
        }},
        "observations": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"area": _str(enum=tuple(AREA_TITLES)), "text": _str(), "refs": _REFS},
            "required": ["area", "text", "refs"],
        }},
    },
    "required": ["executive_summary", "action_items", "observations"],
}

_FILENAME = re.compile(r"\bIMG_\d+|\.(mov|mp4|m4v|wav)\b", re.IGNORECASE)
_CLIP_REF = re.compile(r"\bref_\d+\b", re.IGNORECASE)
_DRIVE_ID = re.compile(r"\b[A-Za-z0-9_-]{25,}\b")
_NUMBER = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|several dozen|dozens of)"
_COUNT = re.compile(
    rf"\b{_NUMBER}\s+(\w+\s+)?(clips?|videos?|findings?|items?|issues?|observations?|reviews?)\b",
    re.IGNORECASE,
)


def _check_text(where: str, text: Any, allow_counts: bool) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValidationError(f"{where}: empty text.")
    if text.strip().startswith(CODE_FENCE_MARKER):
        raise ValidationError(f"{where}: begins with a code fence.")
    for pattern, label in ((_FILENAME, "a filename"), (_CLIP_REF, "a clip reference"),
                           (_DRIVE_ID, "an identifier")):
        if pattern.search(text):
            raise ValidationError(f"{where}: contains {label}: {pattern.search(text).group(0)!r}.")
    if not allow_counts and _COUNT.search(text):
        raise ValidationError(f"{where}: states a count: {_COUNT.search(text).group(0)!r}.")
    return text.strip()


def validate_report_content(raw: str, summary: dict[str, Any]) -> dict[str, Any]:
    """Parse and check the model JSON against this run's clips. Raises on any breach.

    Returns `{executive_summary, action_items, observations, backfilled_refs}`;
    each action item carries the clips it cites. Tier, trade, owner, timeframe
    and links are attached by code from those clips - never taken from the model.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError("Report response was empty.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValidationError(f"Report response is not JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValidationError("Report response is not a JSON object.")
    by_ref = {clip["ref"]: clip for clip in summary["clips"]}
    actionable = {ref for ref, clip in by_ref.items() if clip["bucket"] == BUCKET_ACTION}
    citable = actionable | {ref for ref, clip in by_ref.items() if clip["bucket"] == BUCKET_NO_FINDING}

    executive_summary = _check_text("executive_summary", data.get("executive_summary"), False)

    items, cited = [], set()
    for n, item in enumerate(data.get("action_items") or []):
        where = f"action_items[{n}]"
        refs = item.get("refs") if isinstance(item, dict) else None
        if not isinstance(refs, list) or not refs:
            raise ValidationError(f"{where}: cites no clips.")
        unknown = [r for r in refs if r not in by_ref]
        if unknown:
            raise ValidationError(f"{where}: cites unknown clips {unknown}.")
        not_actionable = [r for r in refs if r not in actionable]
        if not_actionable:
            raise ValidationError(f"{where}: cites clips with no actionable finding {not_actionable}.")
        repeated = sorted(set(refs) & cited)
        if repeated:
            raise ValidationError(f"{where}: clips {repeated} are already in another action item.")
        cited.update(refs)
        items.append(_action_item(
            [by_ref[r] for r in dict.fromkeys(refs)],
            _check_text(f"{where}.location", item.get("location"), True),
            _check_text(f"{where}.issue", item.get("issue"), True),
            _check_text(f"{where}.action", item.get("action"), True),
        ))

    backfilled = [ref for ref in by_ref if ref in actionable and ref not in cited]
    for ref in backfilled:
        items.append(_backfill_item(by_ref[ref]))

    observations = []
    for n, obs in enumerate(data.get("observations") or []):
        where = f"observations[{n}]"
        if not isinstance(obs, dict) or obs.get("area") not in AREA_TITLES:
            raise ValidationError(f"{where}: area must be one of {sorted(AREA_TITLES)}.")
        refs = obs.get("refs") or []
        bad = [r for r in refs if r not in citable]
        if bad:
            raise ValidationError(f"{where}: cites unknown or unassessed clips {bad}.")
        observations.append({"area": obs["area"], "text": _check_text(where, obs.get("text"), False),
                             "clips": [by_ref[r] for r in dict.fromkeys(refs)]})

    return {"executive_summary": executive_summary, "action_items": _order(items),
            "observations": observations, "backfilled_refs": backfilled}


def _action_item(clips: list[dict[str, Any]], location: str, issue: str, action: str) -> dict[str, Any]:
    severity = min(c["severity"] for c in clips)

    def first(key: str) -> str | None:
        return next((c[key] for c in clips if c[key]), None)

    return {"tier": tier_for(severity), "severity": severity, "area": first("area_type") if first("area_type") in AREA_TITLES else "general",
            "location": location, "issue": issue,
            "action": action, "trade": first("trade"), "suggested_owner": first("suggested_owner"),
            "suggested_timeframe": first("suggested_timeframe"), "clips": clips}


def _backfill_item(clip: dict[str, Any]) -> dict[str, Any]:
    return _action_item([clip], clip["location"] or "Location not stated",
                        clip["issue_description"] or "Issue not described",
                        clip["recommended_action"] or "Review the clip and decide the action")


def _order(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda i: (i["severity"], i["location"].lower()))


def fallback_content(summary: dict[str, Any], reason: str) -> dict[str, Any]:
    """Catalogue-only report used when the model output fails validation twice."""
    items = [_backfill_item(c) for c in summary["clips"] if c["bucket"] == BUCKET_ACTION]
    return {
        "executive_summary": (
            "An automated summary is not available for this run because the model output "
            "did not pass validation. The action items below are listed directly from the "
            "catalogue, one per clip."
        ),
        "action_items": _order(items),
        "observations": [],
        "backfilled_refs": [c["ref"] for c in summary["clips"] if c["bucket"] == BUCKET_ACTION],
        "fallback_reason": reason,
    }


def generate_report_content(
    client: Any, settings: Settings, prompt: ReportPrompt, summary: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Up to MODEL_ATTEMPTS schema-constrained Vertex calls; fall back on repeated failure.

    A Vertex transport error is raised (the run records Gate 7 as FAILED). Only
    a VALIDATION failure falls back, because then the catalogue data is fine and
    only the prose is untrustworthy.
    """
    try:
        from google.genai import types
    except ImportError as error:
        raise ExternalServiceError("google-genai is not installed.") from error
    contents = (prompt.instruction_text + "\n\nINPUT:\n"
                + json.dumps(build_model_input(summary), sort_keys=True))
    usage: dict[str, Any] = {"attempts": []}
    errors: list[str] = []
    for _attempt in range(MODEL_ATTEMPTS):
        try:
            response = generate_with_backoff(
                client,
                model=settings.vertex_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=REPORT_RESPONSE_SCHEMA,
                ),
            )
        except Exception as error:  # noqa: BLE001 - one boundary, one error type
            raise ExternalServiceError(f"Report Vertex request failed: {error}") from error
        metadata = getattr(response, "usage_metadata", None)
        usage["attempts"].append({name: getattr(metadata, name, None) for name in (
            "prompt_token_count", "candidates_token_count", "total_token_count")})
        try:
            content = validate_report_content(response.text or "", summary)
            content["validation_errors"] = errors
            return content, usage
        except ValidationError as error:
            errors.append(str(error))
    content = fallback_content(summary, "; ".join(errors))
    content["validation_errors"] = errors
    return content, usage


# --- Document rendering (pure) -----------------------------------------------


def _u16(text: str) -> int:
    """Docs indices are UTF-16 code units, not Python characters."""
    return len(text.encode("utf-16-le")) // 2


class _DocBuilder:
    """Accumulates paragraphs, then emits one insertText plus style requests."""

    GREY = {"color": {"rgbColor": {"red": 0.4, "green": 0.4, "blue": 0.4}}}

    def __init__(self, start: int, tab_id: str | None) -> None:
        self.start = start
        self.tab_id = tab_id
        self.text: list[str] = []
        self.cursor = start
        self.paragraph_styles: list[tuple[int, int, dict[str, Any], str]] = []
        self.text_styles: list[tuple[int, int, dict[str, Any], str]] = []
        self.bullets: list[tuple[int, int]] = []

    def _range(self, start: int, end: int) -> dict[str, Any]:
        rng: dict[str, Any] = {"startIndex": start, "endIndex": end}
        if self.tab_id:
            rng["tabId"] = self.tab_id
        return rng

    def paragraph(self, parts: list[tuple[str, dict[str, Any] | None]], style: str = "NORMAL_TEXT",
                  bullet: bool = False, small: bool = False, indent: bool = False) -> None:
        """`parts` = [(text, text_style_or_None)]; a link style is {"link": url}."""
        begin = self.cursor
        for text, text_style in parts:
            if not text:
                continue
            length = _u16(text)
            if text_style:
                self.text_styles.append((self.cursor, self.cursor + length, text_style,
                                         ",".join(sorted(text_style))))
            self.text.append(text)
            self.cursor += length
        self.text.append("\n")
        self.cursor += 1
        if style != "NORMAL_TEXT":
            self.paragraph_styles.append((begin, self.cursor, {"namedStyleType": style}, "namedStyleType"))
        if indent:
            self.paragraph_styles.append((begin, self.cursor, {
                "indentStart": {"magnitude": 36, "unit": "PT"},
                "indentFirstLine": {"magnitude": 36, "unit": "PT"}}, "indentStart,indentFirstLine"))
        if small:
            self.text_styles.append((begin, self.cursor - 1, {
                "fontSize": {"magnitude": 9, "unit": "PT"}, "foregroundColor": self.GREY},
                "fontSize,foregroundColor"))
        if bullet:
            self.bullets.append((begin, self.cursor))

    def requests(self) -> list[dict[str, Any]]:
        body = "".join(self.text)
        end = self.cursor
        location: dict[str, Any] = {"index": self.start}
        if self.tab_id:
            location["tabId"] = self.tab_id
        out: list[dict[str, Any]] = [{"insertText": {"location": location, "text": body}}]
        # Reset whatever style the insertion point carried, then apply ours.
        out.append({"updateParagraphStyle": {"range": self._range(self.start, end),
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}, "fields": "namedStyleType"}})
        out.append({"deleteParagraphBullets": {"range": self._range(self.start, end)}})
        out.append({"updateTextStyle": {"range": self._range(self.start, end), "textStyle": {},
                    "fields": "bold,italic,underline,link,fontSize,foregroundColor"}})
        for start, stop, style, fields in self.paragraph_styles:
            out.append({"updateParagraphStyle": {"range": self._range(start, stop),
                        "paragraphStyle": style, "fields": fields}})
        for start, stop in self.bullets:
            out.append({"createParagraphBullets": {"range": self._range(start, stop),
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}})
        for start, stop, style, fields in self.text_styles:
            if stop <= start:
                continue
            if "link" in style:
                style = {"link": {"url": style["link"]}}
            out.append({"updateTextStyle": {"range": self._range(start, stop),
                        "textStyle": style, "fields": fields}})
        return out


BOLD = {"bold": True}
WORK_ORDER_LABEL = "WORK ORDER REQUESTED  "
WORK_ORDER_STYLE = {"bold": True, "foregroundColor": {"color": {"rgbColor": {"red": 0.75, "green": 0.1, "blue": 0.1}}}}
ITALIC = {"italic": True}


def _clip_parts(clips: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any] | None]]:
    parts: list[tuple[str, dict[str, Any] | None]] = []
    for n, clip in enumerate(clips):
        if n:
            parts.append((", ", None))
        parts.append((clip["display_name"], {"link": clip["link"]} if clip["link"] else None))
    return parts


_KEEP_HYPHEN = {"in-house"}


def _clips(n: int) -> str:
    return f"{n} clip" if n == 1 else f"{n} clips"


def _human(value: str | None) -> str:
    """Catalogue vocabulary ("general-maintenance", "this-week") as plain words."""
    text = str(value or "").strip()
    if text.lower() not in _KEEP_HYPHEN:
        text = text.replace("_", " ").replace("-", " ")
    return text[:1].upper() + text[1:]


def _date(value: str | None) -> str:
    return (value or "")[:10] or "not recorded"


def build_report_requests(
    summary: dict[str, Any],
    content: dict[str, Any],
    prompt_version: str,
    model_id: str,
    tab_id: str | None = None,
    start_index: int = 1,
) -> list[dict[str, Any]]:
    """The whole report as Docs `batchUpdate` requests inserted at `start_index`. Pure."""
    doc = _DocBuilder(start_index, tab_id)
    visit, counts = summary["visit"], summary["counts"]
    title = visit["property"] or summary["folder_name"]
    doc.paragraph([(f"{title} — Site Visit Report", None)], style="HEADING_1")
    meta = [visit["visit_name"] or summary["folder_name"],
            f"Walked by {visit['walked_by'] or 'unknown'}",
            f"Visit date {_date(visit['visit_date'])}",
            f"Generated {_date(summary['generated_at'])}"]
    doc.paragraph([(" · ".join(meta), None)], small=True)

    by_tier = {key: [i for i in content["action_items"] if i["tier"] == key] for key, _t, _l in TIERS}
    doc.paragraph([("At a glance", None)], style="HEADING_2")
    tier_line = " · ".join(f"{len(by_tier[key])} {key}" for key, _t, _l in TIERS)
    for label, value in (
        ("Clips reviewed: ", str(counts["total"])),
        ("Action items: ", f"{len(content['action_items'])} ({tier_line})"),
        ("Needs human review: ", _clips(counts["review"])),
        ("Already tracked: ", _clips(counts["tracked"])),
        ("No issue found: ", _clips(counts["no_finding"])),
        ("Work order requested on site: ",
         _clips(sum(1 for c in summary["clips"] if c["work_order"]))),
    ):
        doc.paragraph([(label, BOLD), (value, None)], bullet=True)

    doc.paragraph([("Summary", None)], style="HEADING_2")
    doc.paragraph([(content["executive_summary"], None)])

    doc.paragraph([("Action items", None)], style="HEADING_2")
    for key, tier_title, _levels in TIERS:
        doc.paragraph([(tier_title, None)], style="HEADING_3")
        if not by_tier[key]:
            doc.paragraph([("None.", ITALIC)])
            continue
        # Routine is long: group it by area (ADR 0013). Immediate/Priority stay flat.
        groups = ([(AREA_TITLES[a], [i for i in by_tier[key] if i["area"] == a]) for a in AREA_TITLES]
                  if key == "routine" else [(None, by_tier[key])])
        for group_title, group_items in groups:
            if not group_items:
                continue
            if group_title:
                doc.paragraph([(group_title, None)], style="HEADING_4")
            for item in group_items:
                flag = [(WORK_ORDER_LABEL, WORK_ORDER_STYLE)] if any(c["work_order"] for c in item["clips"]) else []
                doc.paragraph(flag + [(item["location"], BOLD), (" — " + item["issue"], None)], bullet=True)
                detail: list[tuple[str, dict[str, Any] | None]] = [("Action: ", BOLD), (item["action"], None)]
                if item["trade"]:
                    detail += [("   Trade: ", BOLD), (_human(item["trade"]), None)]
                if item["suggested_owner"]:
                    detail += [("   Suggested owner: ", BOLD), (_human(item["suggested_owner"]), None)]
                if item["suggested_timeframe"]:
                    detail += [("   Suggested timeframe: ", BOLD), (_human(item["suggested_timeframe"]), None)]
                detail += [("   Clips: ", BOLD)] + _clip_parts(item["clips"])
                doc.paragraph(detail, small=True, indent=True)

    if content["observations"]:
        doc.paragraph([("Observations by area", None)], style="HEADING_2")
        for area, area_title in AREA_TITLES.items():
            notes = [o for o in content["observations"] if o["area"] == area]
            if not notes:
                continue
            doc.paragraph([(area_title, None)], style="HEADING_3")
            for note in notes:
                parts: list[tuple[str, dict[str, Any] | None]] = [(note["text"], None)]
                if note["clips"]:
                    parts += [(" (", None)] + _clip_parts(note["clips"]) + [(")", None)]
                doc.paragraph(parts, bullet=True)

    tracked = [c for c in summary["clips"] if c["bucket"] == BUCKET_TRACKED]
    if tracked:
        doc.paragraph([("Already tracked", None)], style="HEADING_2")
        doc.paragraph([("Issues the walker said are already tasked or were identified earlier. "
                        "Not repeated as new action items.", ITALIC)], small=True)
        for clip in tracked:
            what = clip["location"] or "Location not stated"
            if clip["issue_description"]:
                what += f" — {clip['issue_description']}"
            doc.paragraph([(what, None), (" ", None)] + _clip_parts([clip]), bullet=True)

    review = [c for c in summary["clips"] if c["bucket"] == BUCKET_REVIEW]
    doc.paragraph([("Needs human review", None)], style="HEADING_2")
    if not review:
        doc.paragraph([("None.", ITALIC)])
    for clip in review:
        what = clip["location"] or "Location not stated"
        if clip["issue_description"]:
            what += f" — {clip['issue_description']}"
        flag = [(WORK_ORDER_LABEL, WORK_ORDER_STYLE)] if clip["work_order"] else []
        doc.paragraph(flag + [(what, BOLD), (f". {clip['review_reason']}. ", None)] + _clip_parts([clip]),
                      bullet=True)

    doc.paragraph([("Run details", None)], style="HEADING_2")
    details = f"Run {summary['run_id']} · prompt report-synthesis {prompt_version} · model {model_id}"
    if content.get("fallback_reason"):
        details += " · catalogue-only fallback (model output failed validation)"
    elif content.get("backfilled_refs"):
        details += f" · {len(content['backfilled_refs'])} item(s) added from the catalogue"
    doc.paragraph([(details, None)], small=True)
    no_finding = [c for c in summary["clips"] if c["bucket"] == BUCKET_NO_FINDING]
    if no_finding:
        parts: list[tuple[str, dict[str, Any] | None]] = [("Clips with no issue found: ", None)]
        for n, clip in enumerate(no_finding):
            if n:
                parts.append(("; ", None))
            parts.append((f"{clip['location'] or 'location not stated'} (", None))
            parts += _clip_parts([clip]) + [(")", None)]
        doc.paragraph(parts, small=True)
    return doc.requests()


# --- Gate 7 orchestration ----------------------------------------------------


@dataclass(frozen=True)
class ReportRecord:
    """The complete, auditable record of the one report call and Doc write."""

    run_id: str
    status: str
    document_id: str | None = None
    document_web_link: str | None = None
    document_created: bool = False
    tab_id: str | None = None
    replaced_existing: bool = False
    model_id: str | None = None
    prompt_file: str | None = None
    prompt_version: str | None = None
    prompt_sha256: str | None = None
    sdk_version: str | None = None
    action_item_count: int = 0
    backfilled_refs: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
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
    tab_id: str | None = None,
    replace: bool = False,
) -> ReportRecord:
    """Gate 7 end to end: summarize, generate + validate, then ONE atomic Doc write.

    Nothing in the Doc is touched until the content has validated (or fallen
    back) and every request is built. With `replace=True` the tab's previous
    report is cleared in the same atomic batchUpdate as the new one is written.
    """
    from .google import write_report_requests

    prompt = load_report_prompt(prompts_dir)
    generated_at = utc_now()
    summary = build_report_summary(settings.run_id, folder_name, rows,
                                   generated_at=generated_at, new_names=new_names)
    content, usage = generate_report_content(client, settings, prompt, summary)
    result = write_report_requests(
        docs, document_id, tab_id,
        lambda start: build_report_requests(summary, content, prompt.version,
                                            settings.vertex_model, tab_id=tab_id, start_index=start),
        replace=replace,
    )
    return ReportRecord(
        run_id=settings.run_id,
        status=REPORT_STATUS_WRITTEN_FALLBACK if content.get("fallback_reason") else REPORT_STATUS_WRITTEN,
        document_id=document_id,
        document_web_link=document_web_link,
        document_created=document_created,
        tab_id=tab_id,
        replaced_existing=bool(result.get("cleared_characters")),
        model_id=settings.vertex_model,
        prompt_file=prompt.path,
        prompt_version=prompt.version,
        prompt_sha256=prompt.sha256,
        sdk_version=_sdk_version(),
        action_item_count=len(content["action_items"]),
        backfilled_refs=list(content.get("backfilled_refs") or []),
        validation_errors=list(content.get("validation_errors") or []),
        generated_at=generated_at,
        written_at=utc_now(),
        usage=usage,
        summary_counts=summary["counts"],
    )
