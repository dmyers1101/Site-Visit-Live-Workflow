"""Portfolio discovery: find every visit folder under the master folder.

Boundary: READ-ONLY. This module lists folders and files and never renames,
moves, creates, or deletes anything.

The master folder is not uniformly deep. Observed 2026-09-29:
    Master / State / Property / Visit            (e.g. TX / Alma / 2026-08 ...)
    Master / State / Property / Group / Visit    (e.g. PA / Legacy / Oakland / ...)
So a visit folder is defined by CONTENT, not depth: any folder with at least one
direct video child. Its path below the master gives State (first segment) and
Property (second segment); anything between Property and the visit folder is
kept as `group`. A folder is never descended into past MAX_DEPTH.

Uploader: in a Shared Drive files have no `owners`, and a Gate 6 rename makes
the service account the `lastModifyingUser`. `resolve_uploader` therefore
ignores the runtime service account and lets the caller fall back to the
file's first revision. It never infers an uploader from a blank value - an
unknown uploader stays None and is reported as such.

How to update this later
------------------------
If the folder convention changes (e.g. a new level above State), change
`split_path` and extend `tests/test_portfolio.py` in the same commit. Record the
decision in an ADR (see docs/decisions/0009-portfolio-boundary.md).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .discovery import is_supported_video
from .errors import ValidationError

FOLDER_MIME = "application/vnd.google-apps.folder"
MAX_DEPTH = 6

# A lister returns every direct child of a folder (already paginated) as dicts
# with at least: id, name, mimeType; optionally createdTime, lastModifyingUser.
Lister = Callable[[str], list[dict[str, Any]]]


@dataclass(frozen=True)
class PortfolioClip:
    drive_id: str
    name: str
    mime_type: str
    created_time: str | None
    last_modifying_email: str | None
    last_modifying_name: str | None


@dataclass(frozen=True)
class PortfolioVisit:
    drive_id: str
    name: str
    path: tuple[str, ...]
    state: str | None
    property_name: str | None
    group: str | None
    clips: tuple[PortfolioClip, ...] = field(default_factory=tuple)
    other_children: int = 0

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["clip_count"] = len(self.clips)
        return record


def split_path(path: tuple[str, ...]) -> tuple[str | None, str | None, str | None]:
    """(state, property, group) from the folder path BELOW master, excluding the visit.

    `path` includes the visit folder as its last element.
    """
    parents = path[:-1]
    state = parents[0] if len(parents) >= 1 else None
    property_name = parents[1] if len(parents) >= 2 else None
    group = " / ".join(parents[2:]) if len(parents) > 2 else None
    return state, property_name, group


def _clip(item: dict[str, Any]) -> PortfolioClip:
    user = item.get("lastModifyingUser") or {}
    return PortfolioClip(
        drive_id=item["id"],
        name=item["name"],
        mime_type=item.get("mimeType", ""),
        created_time=item.get("createdTime"),
        last_modifying_email=user.get("emailAddress"),
        last_modifying_name=user.get("displayName"),
    )


def walk_portfolio(root_id: str, lister: Lister, max_depth: int = MAX_DEPTH) -> list[PortfolioVisit]:
    """Depth-first walk; every folder with >=1 direct video child is a visit.

    A visit folder's own subfolders are still walked (a visit could in
    principle contain a nested visit), so nothing below master is skipped
    silently. Order is deterministic: by path.
    """
    if not root_id or not root_id.strip():
        raise ValidationError("A portfolio walk requires the master folder ID.")
    visits: list[PortfolioVisit] = []
    seen: set[str] = set()

    def visit(folder_id: str, path: tuple[str, ...]) -> None:
        if folder_id in seen:
            return
        seen.add(folder_id)
        children = lister(folder_id)
        folders = [c for c in children if c.get("mimeType") == FOLDER_MIME]
        videos = [c for c in children if is_supported_video(c.get("mimeType", ""))]
        if videos and path:
            state, property_name, group = split_path(path)
            visits.append(
                PortfolioVisit(
                    drive_id=folder_id,
                    name=path[-1],
                    path=path,
                    state=state,
                    property_name=property_name,
                    group=group,
                    clips=tuple(sorted((_clip(v) for v in videos), key=lambda c: c.name)),
                    other_children=len(children) - len(videos) - len(folders),
                )
            )
        if len(path) >= max_depth:
            return
        for child in sorted(folders, key=lambda c: c["name"]):
            visit(child["id"], path + (child["name"],))

    visit(root_id, ())
    return sorted(visits, key=lambda v: v.path)


def resolve_uploader(
    clip: PortfolioClip, runtime_service_account: str, first_revision_user: dict[str, Any] | None = None
) -> tuple[str | None, str | None]:
    """(email, display name) of the human who uploaded the clip, or (None, None).

    The runtime service account is never the uploader: if it is the last
    modifier (because Gate 6 renamed the file), the first revision's user is
    used instead when supplied.
    """
    sa = (runtime_service_account or "").strip().lower()
    email = (clip.last_modifying_email or "").strip()
    if email and email.lower() != sa:
        return email, clip.last_modifying_name
    if first_revision_user:
        rev_email = (first_revision_user.get("emailAddress") or "").strip()
        if rev_email and rev_email.lower() != sa:
            return rev_email, first_revision_user.get("displayName")
    return None, None


def inventory_summary(visits: list[PortfolioVisit], catalogued_ids: set[str] | None = None) -> dict[str, Any]:
    """Coverage report: counts per visit, and how many clips are already catalogued."""
    done = catalogued_ids or set()
    rows = []
    for v in visits:
        pending = [c for c in v.clips if c.drive_id not in done]
        rows.append(
            {
                "state": v.state,
                "property": v.property_name,
                "group": v.group,
                "visit": v.name,
                "visit_drive_id": v.drive_id,
                "clips": len(v.clips),
                "already_catalogued": len(v.clips) - len(pending),
                "pending": len(pending),
            }
        )
    return {
        "visit_count": len(visits),
        "clip_count": sum(r["clips"] for r in rows),
        "pending_count": sum(r["pending"] for r in rows),
        "properties": sorted({r["property"] for r in rows if r["property"]}),
        "visits": rows,
    }


# --- Incremental selection and report naming (pure) -------------------------

MAX_FAILED_ATTEMPTS = 3
# A row in one of these states is finished for the nightly run. NEEDS_REVIEW is
# the human queue: re-running it would re-spend quota on the same empty or
# rejected clip every night.
TERMINAL_STATUSES = frozenset({"CATALOGUED", "NEEDS_REVIEW"})
REPORTS_TAB = "Reports"
REPORT_REGISTRY_HEADERS = ("row_key", "property", "visit_name", "doc_id", "tab_id", "tab_title", "updated_at")


def _attempts(record: dict[str, Any] | None) -> int:
    try:
        return int(str((record or {}).get("attempt_count") or "0").strip() or 0)
    except ValueError:
        return 0


def select_pending(
    visit: PortfolioVisit, records_by_id: dict[str, dict[str, Any]]
) -> tuple[set[str], dict[str, int]]:
    """(skip_ids, next_attempt_by_id) for one visit.

    Skip: a clip whose row is CATALOGUED or NEEDS_REVIEW, or FAILED
    MAX_FAILED_ATTEMPTS times. Everything else (no row, or FAILED below the
    cap) is pending, and its next attempt number is prior + 1.
    """
    skip: set[str] = set()
    attempts: dict[str, int] = {}
    for clip in visit.clips:
        record = records_by_id.get(clip.drive_id)
        status = str((record or {}).get("asset_status") or "")
        if status in TERMINAL_STATUSES or _attempts(record) >= MAX_FAILED_ATTEMPTS:
            skip.add(clip.drive_id)
        else:
            attempts[clip.drive_id] = _attempts(record) + 1
    return skip, attempts


def row_extras(
    visit: PortfolioVisit,
    uploaders: dict[str, tuple[str | None, str | None]],
    attempts: dict[str, int],
) -> dict[str, dict[str, Any]]:
    """Per-clip values for the portfolio columns of the catalog row."""
    return {
        clip.drive_id: {
            "state": visit.state,
            "property": visit.property_name,
            "property_group": visit.group,
            "visit_name": visit.name,
            "uploader_email": uploaders.get(clip.drive_id, (None, None))[0],
            "uploader_name": uploaders.get(clip.drive_id, (None, None))[1],
            "uploaded_at": clip.created_time,
            "attempt_count": attempts.get(clip.drive_id),
        }
        for clip in visit.clips
    }


def tab_title(records: list[dict[str, Any]]) -> str:
    """`<latest upload date> · <uploader>` for a visit tab.

    Uploader is the most frequent known uploader name (email if no name);
    "Unknown uploader" when none is known - never guessed.
    """
    dates = sorted(str(r.get("uploaded_at") or "")[:10] for r in records if r.get("uploaded_at"))
    counts: dict[str, int] = {}
    for r in records:
        who = str(r.get("uploader_name") or r.get("uploader_email") or "").strip()
        if who:
            counts[who] = counts.get(who, 0) + 1
    uploader = max(sorted(counts), key=lambda k: counts[k]) if counts else "Unknown uploader"
    return f"{dates[-1] if dates else 'undated'} · {uploader}"


def renamed_names(records: list[dict[str, Any]]) -> dict[str, str | None]:
    """Drive ID -> new name, from the catalog's `drive_rename_decision` column."""
    prefix = "RENAMED_TO:"
    return {
        str(r["row_key"]): str(r["drive_rename_decision"])[len(prefix):]
        for r in records
        if str(r.get("drive_rename_decision") or "").startswith(prefix)
    }


def report_is_due(rows: list[dict[str, Any]], registry_row: dict[str, Any] | None, processed: int) -> bool:
    """A visit needs a report if clips were processed now, or its rows postdate its last report.

    ISO-8601 UTC strings compare correctly as text. No rows -> never due.
    """
    if not rows:
        return False
    if processed:
        return True
    if not registry_row or not registry_row.get("updated_at"):
        return True
    newest = max(str(r.get("updated_at") or "") for r in rows)
    return newest > str(registry_row["updated_at"])
