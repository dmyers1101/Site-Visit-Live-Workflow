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


# The L1 boundary in prompts/claude-overnight-phase2-trial.md types `location`
# and `issue_description` as "string or null": a genuinely location-less clip is
# a real outcome on this corpus, not a validation failure. The identifier, the
# proposed filename, and the confidence note stay required and non-empty.
L1_NULLABLE_FIELDS = frozenset({"location", "issue_description"})


def _required_or_null(value: Any, label: str) -> str | None:
    """Accept an explicit null or a non-empty string; an empty string is neither."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            f"{label} must be a non-empty string or an explicit null, not an empty value."
        )
    return value.strip()


@dataclass(frozen=True)
class L1Extraction:
    source_asset_identifier: str
    location: str | None
    issue_description: str | None
    suggested_filename: str
    confidence_note: str

    @classmethod
    def from_external_result(cls, payload: dict[str, Any], expected_source_id: str) -> "L1Extraction":
        if set(payload) != L1_FIELDS:
            raise ValidationError(
                "L1 result must contain exactly: " + ", ".join(sorted(L1_FIELDS)) + "."
            )
        normalized = dict(payload)
        for key in sorted(L1_FIELDS):
            if key in L1_NULLABLE_FIELDS:
                normalized[key] = _required_or_null(payload[key], f"L1 field {key}")
            else:
                normalized[key] = _required(payload[key], f"L1 field {key}")
        if normalized["source_asset_identifier"] != expected_source_id:
            raise ValidationError("L1 source_asset_identifier does not match the selected Drive asset.")
        return cls(**normalized)


L2_FIELDS = frozenset(
    {
        "source_asset_identifier",
        "prior_layer",
        "prior_layer_record_id",
        "enrichment_status",
        "trade",
        "area_type",
        "severity",
        "recommended_action",
        "enrichment_note",
    }
)
L2_CONDITIONAL_FIELDS = ("trade", "area_type", "severity", "recommended_action")
L2_TRADES = ("plumbing", "electrical", "hvac", "landscaping", "cleaning", "general-maintenance", "safety", "structural")
L2_AREA_TYPES = ("unit", "common-interior", "exterior", "amenity")
# Per prompts/l2-enrichment.md v1.0.0 severity is the pilot's INTEGER 1-4 scale:
# 1 urgent/safety, 2 high, 3 medium, 4 low/cosmetic. A string form ("high",
# "2", "urgent-safety") is a validation failure, never something to coerce.
L2_SEVERITIES = (1, 2, 3, 4)
L2_SEVERITY_MEANINGS = {1: "urgent/safety", 2: "high", 3: "medium", 4: "low/cosmetic"}
L2_STATUSES = ("ENRICHED", "NO_FINDING", "INSUFFICIENT_EVIDENCE")

L3_FIELDS = frozenset(
    {
        "source_asset_identifier",
        "prior_layer",
        "prior_layer_record_id",
        "refinement_status",
        "responsible_party",
        "urgency_window",
        "disputed_prior_fields",
        "refinement_note",
    }
)
L3_CONDITIONAL_FIELDS = ("responsible_party", "urgency_window")
L3_RESPONSIBLE_PARTIES = ("in-house", "vendor")
L3_URGENCY_WINDOWS = ("immediate", "this-week", "this-month", "routine")
L3_STATUSES = ("REFINED", "INSUFFICIENT_EVIDENCE")
L3_DISPUTABLE_FIELDS = (
    "location",
    "issue_description",
    "suggested_filename",
    "trade",
    "area_type",
    "severity",
    "recommended_action",
)


CODE_FENCE_MARKER = "```"


def parse_strict_json(raw: str, layer: str) -> dict[str, Any]:
    """Parse one layer response as strict JSON, with the pilot failure modes rejected.

    The pilot returned every response inside a ```json fence, and this parser
    deliberately does NOT strip one: a fence means the model ignored the
    response_mime_type contract, and that is a validation failure to record,
    not a formatting quirk to paper over.
    """
    import json as _json

    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError(f"{layer} response was empty.")
    if CODE_FENCE_MARKER in raw:
        raise ValidationError(
            f"{layer} response contained a Markdown code fence; strict JSON only is required."
        )
    try:
        payload = _json.loads(raw)
    except ValueError as error:
        raise ValidationError(f"{layer} response was not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValidationError(f"{layer} response must be a single JSON object.")
    return payload


def _exact_keys(payload: dict[str, Any], allowed: frozenset[str], layer: str) -> None:
    """The layer objects are closed: an extra or missing key is a rejection, not a warning."""
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise ValidationError(
            f"{layer} result must contain exactly: " + ", ".join(sorted(allowed)) + "."
        )


def _enum(value: Any, allowed: tuple[str, ...], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValidationError(f"{label} must be one of: " + ", ".join(allowed) + ".")
    return value


def _int_enum(value: Any, allowed: tuple[int, ...], label: str) -> int:
    """Strictly an int from the allowed set.

    `isinstance(True, int)` is True and `True == 1`, so booleans are excluded
    explicitly. A string form is rejected outright rather than coerced: the
    prompt file states severity is an integer enum and never a string.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value not in allowed:
        raise ValidationError(
            f"{label} must be the integer: " + ", ".join(str(item) for item in allowed) + "."
        )
    return value


def _gated_nullable(payload: dict[str, Any], fields: tuple[str, ...], populated: bool, layer: str) -> None:
    """Populated statuses require every conditional field; downgraded statuses require explicit nulls."""
    for name in fields:
        if populated and payload[name] is None:
            raise ValidationError(f"{layer} field {name} cannot be null for this status.")
        if not populated and payload[name] is not None:
            raise ValidationError(f"{layer} field {name} must be null for this status.")


@dataclass(frozen=True)
class L2Enrichment:
    source_asset_identifier: str
    prior_layer: str
    prior_layer_record_id: str
    enrichment_status: str
    trade: str | None
    area_type: str | None
    severity: int | None
    recommended_action: str | None
    enrichment_note: str

    @classmethod
    def from_external_result(
        cls,
        payload: dict[str, Any],
        expected_source_id: str,
        expected_prior_record_id: str,
        evidence_supports_finding: bool = True,
    ) -> "L2Enrichment":
        _exact_keys(payload, L2_FIELDS, "L2")
        if payload["source_asset_identifier"] != expected_source_id:
            raise ValidationError("L2 source_asset_identifier does not match the selected Drive asset.")
        if payload["prior_layer"] != "L1":
            raise ValidationError("L2 prior_layer must be the literal L1.")
        if payload["prior_layer_record_id"] != expected_prior_record_id:
            raise ValidationError("L2 prior_layer_record_id does not match the validated L1 record.")
        status = _enum(payload["enrichment_status"], L2_STATUSES, "L2 enrichment_status")
        if not evidence_supports_finding and status != "NO_FINDING":
            raise ValidationError(
                "L2 must return NO_FINDING when the L1 issue description or the transcript "
                "carries no evidence of a finding."
            )
        _required(payload["enrichment_note"], "L2 field enrichment_note")
        _gated_nullable(payload, L2_CONDITIONAL_FIELDS, status == "ENRICHED", "L2")
        if status == "ENRICHED":
            _enum(payload["trade"], L2_TRADES, "L2 trade")
            _enum(payload["area_type"], L2_AREA_TYPES, "L2 area_type")
            _int_enum(payload["severity"], L2_SEVERITIES, "L2 severity")
            _required(payload["recommended_action"], "L2 field recommended_action")
        return cls(**payload)


@dataclass(frozen=True)
class L3Refinement:
    source_asset_identifier: str
    prior_layer: str
    prior_layer_record_id: str
    refinement_status: str
    responsible_party: str | None
    urgency_window: str | None
    disputed_prior_fields: tuple[str, ...]
    refinement_note: str

    @classmethod
    def from_external_result(
        cls, payload: dict[str, Any], expected_source_id: str, expected_prior_record_id: str
    ) -> "L3Refinement":
        _exact_keys(payload, L3_FIELDS, "L3")
        if payload["source_asset_identifier"] != expected_source_id:
            raise ValidationError("L3 source_asset_identifier does not match the selected Drive asset.")
        if payload["prior_layer"] != "L2":
            raise ValidationError("L3 prior_layer must be the literal L2.")
        if payload["prior_layer_record_id"] != expected_prior_record_id:
            raise ValidationError("L3 prior_layer_record_id does not match the validated L2 record.")
        status = _enum(payload["refinement_status"], L3_STATUSES, "L3 refinement_status")
        _required(payload["refinement_note"], "L3 field refinement_note")
        _gated_nullable(payload, L3_CONDITIONAL_FIELDS, status == "REFINED", "L3")
        if status == "REFINED":
            _enum(payload["responsible_party"], L3_RESPONSIBLE_PARTIES, "L3 responsible_party")
            _enum(payload["urgency_window"], L3_URGENCY_WINDOWS, "L3 urgency_window")
        disputed = payload["disputed_prior_fields"]
        if not isinstance(disputed, list):
            raise ValidationError("L3 disputed_prior_fields must always be present as an array.")
        if len(set(disputed)) != len(disputed):
            raise ValidationError("L3 disputed_prior_fields members must be unique.")
        for name in disputed:
            _enum(name, L3_DISPUTABLE_FIELDS, "L3 disputed_prior_fields member")
        return cls(**{**payload, "disputed_prior_fields": tuple(disputed)})


def l3_is_permitted(enrichment: L2Enrichment) -> bool:
    """L3 runs only on an ENRICHED L2; NO_FINDING and INSUFFICIENT_EVIDENCE stop the chain."""
    return enrichment.enrichment_status == "ENRICHED"


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
