"""Pure Gate 1 logic: classify Drive children and build one run manifest.

Nothing in this module contacts Google. It takes the raw metadata dictionaries
that `DriveGateway.list_immediate_children_detailed` already returned and turns
them into a supported/excluded split plus a `VisitManifest`. Keeping it pure is
what lets Gate 1 be unit-tested without an API call, and it keeps the Drive
boundary in `google.py`.

The confirmed processing boundary for the trial folder is *direct media
children*: the approved folder holds 19 direct media files and zero
subfolders, so this module never recurses. A subfolder is recorded as an
excluded item with its reason, never traversed.

How to update this later
------------------------
Add a MIME type by extending `SUPPORTED_VIDEO_MIME_PREFIXES` or
`SUPPORTED_VIDEO_MIME_TYPES` and adding a test that asserts both the new
inclusion and the exclusion reason it replaces. Do not make `classify_children`
recursive: a deeper boundary is an ADR and a schema change, not an edit here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ValidationError
from .models import DriveMediaFile, VisitFolder, VisitManifest, utc_now

FOLDER_MIME = "application/vnd.google-apps.folder"
SUPPORTED_VIDEO_MIME_PREFIXES = ("video/",)
SUPPORTED_VIDEO_MIME_TYPES: tuple[str, ...] = ()

EXCLUSION_FOLDER = "EXCLUDED_SUBFOLDER: the documented boundary is direct media children only."
EXCLUSION_TRASHED = "EXCLUDED_TRASHED: the item is in the Drive trash."
EXCLUSION_NOT_VIDEO = "EXCLUDED_UNSUPPORTED_MIME_TYPE: only video/* sources can be transcribed."
EXCLUSION_NOT_DOWNLOADABLE = "EXCLUDED_NOT_DOWNLOADABLE: the runtime identity lacks canDownload."


def is_supported_video(mime_type: str) -> bool:
    """One place decides what this workflow can transcribe."""
    mime = (mime_type or "").strip().lower()
    return mime.startswith(SUPPORTED_VIDEO_MIME_PREFIXES) or mime in SUPPORTED_VIDEO_MIME_TYPES


def exclusion_reason(item: dict[str, Any]) -> str | None:
    """Return why this child is out of scope, or None when it is processable."""
    mime = (item.get("mime_type") or "").strip()
    if mime == FOLDER_MIME:
        return EXCLUSION_FOLDER
    if item.get("trashed"):
        return EXCLUSION_TRASHED
    if not is_supported_video(mime):
        return EXCLUSION_NOT_VIDEO
    capabilities = item.get("capabilities") or {}
    if capabilities.get("canDownload") is False:
        return EXCLUSION_NOT_DOWNLOADABLE
    return None


@dataclass(frozen=True)
class FolderClassification:
    """The full, auditable Gate 1 split — every child lands on exactly one side."""

    supported: tuple[DriveMediaFile, ...]
    excluded: tuple[dict[str, Any], ...]

    @property
    def supported_count(self) -> int:
        return len(self.supported)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)

    def mime_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for asset in self.supported:
            counts[asset.mime_type] = counts.get(asset.mime_type, 0) + 1
        for item in self.excluded:
            mime = item.get("mime_type") or "unknown"
            counts[mime] = counts.get(mime, 0) + 1
        return dict(sorted(counts.items()))


def _media_from_item(item: dict[str, Any]) -> DriveMediaFile:
    size = item.get("size_bytes")
    return DriveMediaFile(
        drive_id=item["drive_id"],
        original_name=item["name"],
        mime_type=item["mime_type"],
        web_view_link=item.get("web_view_link"),
        size_bytes=int(size) if size not in (None, "") else None,
        modified_time=item.get("modified_time"),
    )


def classify_children(children: list[dict[str, Any]]) -> FolderClassification:
    """Split immediate children into processable videos and excluded items with reasons."""
    supported: list[DriveMediaFile] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in children:
        drive_id = (item.get("drive_id") or "").strip()
        if not drive_id:
            raise ValidationError("Every Drive child must carry a Drive ID.")
        if drive_id in seen:
            raise ValidationError(f"Drive listing returned a duplicate child ID: {drive_id}")
        seen.add(drive_id)
        reason = exclusion_reason(item)
        if reason is None:
            supported.append(_media_from_item(item))
            continue
        excluded.append(
            {
                "drive_id": drive_id,
                "name": item.get("name"),
                "mime_type": item.get("mime_type"),
                "web_view_link": item.get("web_view_link"),
                "reason": reason,
            }
        )
    return FolderClassification(supported=tuple(supported), excluded=tuple(excluded))


def build_manifest(
    shared_folder_id: str,
    folder_name: str,
    classification: FolderClassification,
    folder_web_view_link: str | None = None,
    created_at: str | None = None,
) -> VisitManifest:
    """Build the single Gate 1 manifest before anything is downloaded or staged."""
    if not classification.supported:
        raise ValidationError(
            "The configured Drive folder contains no supported video children; "
            "nothing can be processed and no manifest is written."
        )
    return VisitManifest(
        schema_version="1.0",
        shared_folder_id=shared_folder_id,
        visit=VisitFolder(
            drive_id=shared_folder_id, name=folder_name, web_view_link=folder_web_view_link
        ),
        media_files=classification.supported,
        created_at=created_at or utc_now(),
    )


def manifest_document(
    run_id: str, manifest: VisitManifest, classification: FolderClassification
) -> dict[str, Any]:
    """The manifest as it is written to GCS: the manifest plus its exclusion record."""
    return {
        "manifest_id": f"{run_id}-{manifest.shared_folder_id}",
        "run_id": run_id,
        "processing_boundary": "DIRECT_MEDIA_CHILDREN",
        "manifest": manifest.to_dict(),
        "supported_count": classification.supported_count,
        "excluded_count": classification.excluded_count,
        "mime_type_counts": classification.mime_type_counts(),
        "excluded_items": list(classification.excluded),
    }


def select_assets(
    manifest: VisitManifest, asset_id: str | None = None, limit: int | None = None
) -> tuple[DriveMediaFile, ...]:
    """Apply the cheap-trial selectors, preserving manifest order."""
    assets = manifest.media_files
    if asset_id:
        assets = (manifest.asset(asset_id),)
    if limit is not None:
        if limit < 1:
            raise ValidationError("--limit must be at least 1.")
        assets = assets[:limit]
    return assets
