from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .errors import ValidationError

L1_FIELDS = frozenset(
    {
        "source_asset_identifier",
        "location",
        "issue_description",
        "suggested_filename",
        "confidence_note",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class VisitFolder:
    drive_id: str
    name: str
    web_view_link: str | None = None

    def __post_init__(self) -> None:
        _required(self.drive_id, "Visit folder Drive ID")
        _required(self.name, "Visit folder name")


@dataclass(frozen=True)
class DriveMediaFile:
    drive_id: str
    original_name: str
    mime_type: str
    web_view_link: str | None = None
    size_bytes: int | None = None
    modified_time: str | None = None

    def __post_init__(self) -> None:
        _required(self.drive_id, "Drive file ID")
        _required(self.original_name, "Original Drive file name")
        if not self.mime_type.startswith("video/"):
            raise ValidationError("Only video/* files can be processed.")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValidationError("size_bytes cannot be negative.")


@dataclass(frozen=True)
class VisitManifest:
    schema_version: str
    shared_folder_id: str
    visit: VisitFolder
    media_files: tuple[DriveMediaFile, ...]
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required(self.shared_folder_id, "Configured Shared Folder ID")
        if self.schema_version != "1.0":
            raise ValidationError("Unsupported manifest schema version.")
        if not self.media_files:
            raise ValidationError("A manifest must include immediate video files.")
        if len({asset.drive_id for asset in self.media_files}) != len(self.media_files):
            raise ValidationError("A manifest cannot contain duplicate Drive IDs.")

    def asset(self, drive_id: str) -> DriveMediaFile:
        for asset in self.media_files:
            if asset.drive_id == drive_id:
                return asset
        raise ValidationError("Selected asset is not present in this manifest.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TranscriptStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    RETRY_PENDING = "RETRY_PENDING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


@dataclass(frozen=True)
class TranscriptionRecord:
    source_asset_identifier: str
    wav_gcs_uri: str
    output_gcs_uri: str
    attempt: int
    status: TranscriptStatus
    started_at: str
    operation_name: str | None = None
    completed_at: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        _required(self.source_asset_identifier, "Source asset identifier")
        if not self.wav_gcs_uri.startswith("gs://") or not self.output_gcs_uri.startswith("gs://"):
            raise ValidationError("Transcription paths must use gs:// URIs.")
        if self.attempt not in (0, 1):
            raise ValidationError("Only the initial transcription and one retry are allowed.")
        _required(self.started_at, "Transcription start time")
        if self.status is TranscriptStatus.SUBMITTED and not self.operation_name:
            raise ValidationError("A submitted transcription requires an operation name.")


class EmptyTranscriptDecision(StrEnum):
    COMPLETE = "COMPLETE"
    RETRY_ONCE = "RETRY_ONCE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


def evaluate_transcript(text: str, attempt: int) -> EmptyTranscriptDecision:
    if attempt not in (0, 1):
        raise ValidationError("Only attempt 0 or 1 is valid.")
    if text.strip():
        return EmptyTranscriptDecision.COMPLETE
    return EmptyTranscriptDecision.RETRY_ONCE if attempt == 0 else EmptyTranscriptDecision.NEEDS_REVIEW


@dataclass(frozen=True)
class L1Extraction:
    source_asset_identifier: str
    location: str
    issue_description: str
    suggested_filename: str
    confidence_note: str

    @classmethod
    def from_external_result(cls, payload: dict[str, Any], expected_source_id: str) -> "L1Extraction":
        if set(payload) != L1_FIELDS:
            raise ValidationError(
                "L1 result must contain exactly: " + ", ".join(sorted(L1_FIELDS)) + "."
            )
        for key in L1_FIELDS:
            _required(payload[key], f"L1 field {key}")
        if payload["source_asset_identifier"] != expected_source_id:
            raise ValidationError("L1 source_asset_identifier does not match the selected Drive asset.")
        return cls(**payload)


@dataclass(frozen=True)
class CatalogDraft:
    row_key: str
    source_asset_identifier: str
    original_drive_name: str
    drive_link: str | None
    visit_drive_id: str
    location: str
    issue_description: str
    suggested_filename: str
    confidence_note: str
    transcription_status: str
    wav_gcs_uri: str
    transcript_output_gcs_uri: str
    transcription_started_at: str
    transcription_completed_at: str | None
    catalog_status: str = "DRAFT"

    def __post_init__(self) -> None:
        if self.row_key != self.source_asset_identifier:
            raise ValidationError("Catalog row key must be the immutable Drive asset ID.")
        if self.catalog_status != "DRAFT":
            raise ValidationError("Only DRAFT catalog rows can be created by this workflow.")

    @classmethod
    def from_records(
        cls, manifest: VisitManifest, asset_id: str, extraction: L1Extraction, transcription: TranscriptionRecord
    ) -> "CatalogDraft":
        asset = manifest.asset(asset_id)
        if extraction.source_asset_identifier != asset.drive_id:
            raise ValidationError("Extraction does not belong to selected source asset.")
        if transcription.source_asset_identifier != asset.drive_id:
            raise ValidationError("Transcription does not belong to selected source asset.")
        return cls(
            row_key=asset.drive_id,
            source_asset_identifier=asset.drive_id,
            original_drive_name=asset.original_name,
            drive_link=asset.web_view_link,
            visit_drive_id=manifest.visit.drive_id,
            location=extraction.location,
            issue_description=extraction.issue_description,
            suggested_filename=extraction.suggested_filename,
            confidence_note=extraction.confidence_note,
            transcription_status=transcription.status.value,
            wav_gcs_uri=transcription.wav_gcs_uri,
            transcript_output_gcs_uri=transcription.output_gcs_uri,
            transcription_started_at=transcription.started_at,
            transcription_completed_at=transcription.completed_at,
        )


class ReviewAction(StrEnum):
    RENAME_DRIVE = "RENAME_DRIVE"
    PUBLISH_CATALOG = "PUBLISH_CATALOG"


@dataclass(frozen=True)
class ReviewApproval:
    source_asset_identifier: str
    action: ReviewAction
    approved_by: str
    approved_at: str
    approval_record_id: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_asset_identifier, "Source asset identifier"),
            (self.approved_by, "Approver"),
            (self.approved_at, "Approval time"),
            (self.approval_record_id, "Approval record ID"),
        ):
            _required(value, label)


def require_approval(approval: ReviewApproval | None, asset_id: str, action: ReviewAction) -> ReviewApproval:
    if approval is None:
        from .errors import ApprovalRequiredError

        raise ApprovalRequiredError(f"{action.value} is blocked until an explicit approval record is supplied.")
    if approval.source_asset_identifier != asset_id or approval.action != action:
        raise ValidationError("Approval record does not match the selected asset and action.")
    return approval
