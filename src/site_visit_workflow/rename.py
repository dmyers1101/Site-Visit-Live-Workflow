"""Gate 6: the approval-gated rename of a Drive source video.

Boundary: this module RENAMES and nothing else. It never deletes, never
trashes, never moves a file between folders, and never touches file content.
The Drive file ID is immutable and is unaffected by a rename, so the catalogue
row key - which is that ID - survives a rename untouched. That is what keeps
the run idempotent: re-running after a rename updates the same row rather than
appending a duplicate.

Two independent approvals are required before a single rename is attempted:
the `RENAME_APPROVED` environment flag AND the `--rename-approved` CLI flag.
Belt and braces is deliberate - this mutates the operator's source library,
which every prior run of this pipeline explicitly refused to do.

Only an asset that reached CATALOGUED with a validated L1 record is eligible.
A NEEDS_REVIEW or FAILED asset keeps its original name: renaming a file whose
extraction was not trusted would put an untrusted name on the source of truth.

How to update this later
------------------------
`build_new_name` is pure and is the only place sanitization rules live; change
it there and extend `tests/test_rename.py` in the same commit. If a future
requirement seems to need a delete, a move, or an overwrite, raise it as an ADR
- the service account holds no delete permission anywhere by design (ADR 0005).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .errors import ValidationError

# Recorded per asset, in the run summary and in the archived evidence record.
RENAME_RENAMED = "RENAMED"
RENAME_SKIPPED_NOT_APPROVED = "SKIPPED_NOT_APPROVED"
RENAME_SKIPPED_NO_SUGGESTION = "SKIPPED_NO_SUGGESTION"
RENAME_SKIPPED_ASSET_NOT_ELIGIBLE = "SKIPPED_ASSET_NOT_ELIGIBLE"
RENAME_SKIPPED_DRY_RUN = "SKIPPED_DRY_RUN"
RENAME_FAILED = "FAILED"

MAX_STEM_CHARACTERS = 120

# Extensions the model is known to append to its own suggestion. The ORIGINAL
# file's extension always wins; one of these trailing on the suggestion is
# dropped so the result is not "kitchen-leak.mov.MOV".
KNOWN_MEDIA_EXTENSIONS = frozenset(
    {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".wav", ".mp3", ".heic", ".jpg", ".jpeg", ".png"}
)

_PATH_SEPARATORS = str.maketrans({"/": " ", "\\": " ", ":": " "})
_WHITESPACE = re.compile(r"\s+")
_TRIMMABLE = " ._-"


def _strip_control_characters(value: str) -> str:
    """Drop control and format characters; a Drive name must stay printable."""
    return "".join(character for character in value if unicodedata.category(character)[0] != "C")


def sanitize_stem(suggested_filename: str) -> str:
    """Reduce a model-suggested name to a safe, extension-free filename stem.

    Returns an empty string when nothing usable survives, which the caller
    treats as "skip this asset" rather than as an error.
    """
    # Newlines and tabs are control characters AND word separators, so they are
    # normalized to spaces before the remaining control characters are dropped;
    # otherwise "roof\ndeck" would silently become "roofdeck".
    stem = _WHITESPACE.sub(" ", suggested_filename)
    # Path separators become spaces (and then underscores) rather than being
    # deleted outright, so "kitchen/sink" stays readable as "kitchen_sink" and
    # no suggestion can ever escape into a path.
    stem = _strip_control_characters(stem).translate(_PATH_SEPARATORS)
    # A bare extension (".mov") carries no name at all; it is not a stem.
    if stem.strip().lower() in KNOWN_MEDIA_EXTENSIONS:
        return ""
    candidate = PurePosixPath(stem.strip())
    if candidate.suffix.lower() in KNOWN_MEDIA_EXTENSIONS:
        stem = stem.strip()[: -len(candidate.suffix)]
    stem = _WHITESPACE.sub("_", stem.strip())
    stem = stem.strip(_TRIMMABLE)
    if len(stem) > MAX_STEM_CHARACTERS:
        stem = stem[:MAX_STEM_CHARACTERS].strip(_TRIMMABLE)
    return stem


def build_new_name(original_name: str, suggested_filename: str | None) -> str | None:
    """Compose the new Drive name, or None meaning "skip, do not rename".

    The ORIGINAL file's extension is preserved exactly, including its case: the
    model emits `.mov`, `.MOV`, or no extension at all, and none of those may be
    allowed to change what the file actually is. An empty or unusable
    suggestion returns None rather than a guessed name.
    """
    if not isinstance(original_name, str) or not original_name.strip():
        raise ValidationError("A rename requires the file's original Drive name.")
    if not suggested_filename or not isinstance(suggested_filename, str):
        return None
    stem = sanitize_stem(suggested_filename)
    if not stem:
        return None
    extension = PurePosixPath(original_name.strip()).suffix
    return f"{stem}{extension}"


def asset_is_eligible(asset_status: str, l1_validated: bool) -> bool:
    """Only a CATALOGUED asset whose L1 validated may be renamed."""
    return asset_status == "CATALOGUED" and bool(l1_validated)


def rename_is_authorized(env_flag: bool, cli_flag: bool) -> bool:
    """Both approvals must be present. Either one alone authorizes nothing."""
    return bool(env_flag) and bool(cli_flag)


@dataclass(frozen=True)
class RenameOutcome:
    """The complete per-asset rename record, as archived and summarised."""

    source_asset_identifier: str
    rename_status: str
    original_drive_name: str
    new_drive_name: str | None = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def rename_asset(drive_service: Any, file_id: str, new_name: str) -> None:
    """Rename one Drive file through the existing `DriveGateway.rename` path.

    `drive_service` is a `DriveGateway`. There is deliberately only ONE Drive
    rename implementation in this codebase; a second code path reading the same
    inputs is the class of bug that produced the double-WAV-upload, so this
    function delegates rather than calling `files().update` again.
    """
    if not file_id or not file_id.strip():
        raise ValidationError("A rename requires the immutable Drive file ID.")
    if not new_name or not new_name.strip():
        raise ValidationError("A rename requires a non-empty new name.")
    renamer = getattr(drive_service, "rename", None)
    if renamer is None:
        raise ValidationError(
            "rename_asset expects a DriveGateway; no second Drive rename path exists."
        )
    renamer(file_id, new_name)


def plan_rename(
    asset_id: str,
    original_drive_name: str,
    suggested_filename: str | None,
    asset_status: str,
    l1_validated: bool,
    authorized: bool,
    dry_run: bool = False,
) -> RenameOutcome:
    """Decide, without contacting Drive, what should happen to one asset.

    Returned statuses other than RENAMED are final; RENAMED is returned only by
    `execute_rename` after Drive has actually accepted the change.
    """
    if dry_run:
        return RenameOutcome(asset_id, RENAME_SKIPPED_DRY_RUN, original_drive_name)
    if not authorized:
        return RenameOutcome(asset_id, RENAME_SKIPPED_NOT_APPROVED, original_drive_name)
    if not asset_is_eligible(asset_status, l1_validated):
        return RenameOutcome(asset_id, RENAME_SKIPPED_ASSET_NOT_ELIGIBLE, original_drive_name)
    if build_new_name(original_drive_name, suggested_filename) is None:
        return RenameOutcome(asset_id, RENAME_SKIPPED_NO_SUGGESTION, original_drive_name)
    return RenameOutcome(asset_id, RENAME_RENAMED, original_drive_name)


def execute_rename(
    drive_service: Any,
    asset_id: str,
    original_drive_name: str,
    suggested_filename: str | None,
    asset_status: str,
    l1_validated: bool,
    authorized: bool,
    dry_run: bool = False,
) -> RenameOutcome:
    """Gate 6 for one asset: plan, then rename only when the plan says RENAMED.

    A failure here is recorded and returned; it never ends the run, consistent
    with every other gate. `original_drive_name` is the DISCOVERY-time name and
    is passed through unchanged, so the catalogue keeps the name the file had
    when the run started.
    """
    planned = plan_rename(
        asset_id,
        original_drive_name,
        suggested_filename,
        asset_status,
        l1_validated,
        authorized,
        dry_run=dry_run,
    )
    if planned.rename_status != RENAME_RENAMED:
        return planned
    new_name = build_new_name(original_drive_name, suggested_filename)
    if new_name is None:  # pragma: no cover - plan_rename already excluded this
        return RenameOutcome(asset_id, RENAME_SKIPPED_NO_SUGGESTION, original_drive_name)
    if new_name == original_drive_name:
        # Nothing to change. Recorded as RENAMED with identical names would be
        # misleading, so it is reported as "no suggestion worth applying".
        return RenameOutcome(
            asset_id, RENAME_SKIPPED_NO_SUGGESTION, original_drive_name, new_drive_name=new_name
        )
    try:
        rename_asset(drive_service, asset_id, new_name)
    except Exception as error:  # noqa: BLE001 - one asset's failure is not fatal
        return RenameOutcome(
            asset_id,
            RENAME_FAILED,
            original_drive_name,
            new_drive_name=new_name,
            error={"error_type": type(error).__name__, "message": str(error)[:600]},
        )
    return RenameOutcome(asset_id, RENAME_RENAMED, original_drive_name, new_drive_name=new_name)


def summarize_renames(outcomes: list[RenameOutcome]) -> dict[str, int]:
    """Counts by rename status, for the run summary."""
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.rename_status] = counts.get(outcome.rename_status, 0) + 1
    return counts
