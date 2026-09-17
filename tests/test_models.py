from dataclasses import asdict

import pytest

from site_visit_workflow.errors import ApprovalRequiredError, ValidationError
from site_visit_workflow.models import (
    CatalogDraft,
    DriveMediaFile,
    EmptyTranscriptDecision,
    L1Extraction,
    ReviewAction,
    ReviewApproval,
    TranscriptStatus,
    TranscriptionRecord,
    VisitFolder,
    VisitManifest,
    evaluate_transcript,
    require_approval,
)


def manifest() -> VisitManifest:
    return VisitManifest(
        schema_version="1.0",
        shared_folder_id="shared-folder",
        visit=VisitFolder("visit-id", "Visit 1"),
        media_files=(
            DriveMediaFile(
                "video-id", "original.mp4", "video/mp4", "https://drive.example/video-id", 3, "2026-01-01"
            ),
        ),
    )


def record(attempt: int = 0) -> TranscriptionRecord:
    return TranscriptionRecord(
        source_asset_identifier="video-id",
        wav_gcs_uri="gs://bucket/staging/video.wav",
        output_gcs_uri="gs://bucket/output/video/",
        attempt=attempt,
        status=TranscriptStatus.COMPLETED,
        started_at="2026-01-01T00:00:00Z",
    )


def l1() -> L1Extraction:
    return L1Extraction.from_external_result(
        {
            "source_asset_identifier": "video-id",
            "location": "Kitchen",
            "issue_description": "Leak under sink.",
            "suggested_filename": "kitchen-sink-leak.mp4",
            "confidence_note": "Transcript-supported; visually unverified.",
        },
        "video-id",
    )


def test_manifest_preserves_source_identity_and_rejects_non_video() -> None:
    asset = manifest().asset("video-id")
    assert asset.drive_id == "video-id"
    assert asset.original_name == "original.mp4"
    with pytest.raises(ValidationError, match="Only video"):
        DriveMediaFile("file", "photo.jpg", "image/jpeg")


def test_l1_validation_requires_exact_allowlist_and_matching_source() -> None:
    payload = asdict(l1())
    payload["severity"] = "high"
    with pytest.raises(ValidationError, match="exactly"):
        L1Extraction.from_external_result(payload, "video-id")
    payload = asdict(l1())
    payload["source_asset_identifier"] = "other"
    with pytest.raises(ValidationError, match="does not match"):
        L1Extraction.from_external_result(payload, "video-id")


@pytest.mark.parametrize(
    ("text", "attempt", "expected"),
    [
        ("useful transcript", 0, EmptyTranscriptDecision.COMPLETE),
        ("  ", 0, EmptyTranscriptDecision.RETRY_ONCE),
        ("", 1, EmptyTranscriptDecision.NEEDS_REVIEW),
    ],
)
def test_empty_transcript_policy(text: str, attempt: int, expected: EmptyTranscriptDecision) -> None:
    assert evaluate_transcript(text, attempt) is expected


def test_catalog_row_is_idempotent_by_drive_id() -> None:
    draft = CatalogDraft.from_records(manifest(), "video-id", l1(), record())
    assert draft.row_key == "video-id"
    assert draft.source_asset_identifier == "video-id"
    assert draft.original_drive_name == "original.mp4"
    assert draft.wav_gcs_uri == "gs://bucket/staging/video.wav"
    assert draft.transcript_output_gcs_uri == "gs://bucket/output/video/"
    assert draft.catalog_status == "DRAFT"


def test_rename_and_publish_require_matching_explicit_approval() -> None:
    with pytest.raises(ApprovalRequiredError):
        require_approval(None, "video-id", ReviewAction.RENAME_DRIVE)
    approval = ReviewApproval(
        source_asset_identifier="video-id",
        action=ReviewAction.PUBLISH_CATALOG,
        approved_by="reviewer@example.com",
        approved_at="2026-01-01T00:00:00Z",
        approval_record_id="approval-1",
    )
    with pytest.raises(ValidationError, match="does not match"):
        require_approval(approval, "video-id", ReviewAction.RENAME_DRIVE)


def test_transcription_allows_one_retry_only() -> None:
    with pytest.raises(ValidationError, match="Only the initial"):
        TranscriptionRecord(
            source_asset_identifier="video-id",
            wav_gcs_uri="gs://bucket/video.wav",
            output_gcs_uri="gs://bucket/output/",
            attempt=2,
            status=TranscriptStatus.FAILED,
            started_at="2026-01-01T00:00:00Z",
        )
