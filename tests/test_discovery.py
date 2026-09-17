"""Gate 1 is pure, so it is tested without contacting Drive."""

import pytest

from site_visit_workflow.discovery import (
    EXCLUSION_FOLDER,
    EXCLUSION_NOT_DOWNLOADABLE,
    EXCLUSION_NOT_VIDEO,
    EXCLUSION_TRASHED,
    FOLDER_MIME,
    build_manifest,
    classify_children,
    exclusion_reason,
    is_supported_video,
    manifest_document,
    select_assets,
)
from site_visit_workflow.errors import ValidationError


def child(drive_id: str, name: str, mime_type: str, **extra: object) -> dict:
    item = {
        "drive_id": drive_id,
        "name": name,
        "mime_type": mime_type,
        "web_view_link": f"https://drive.example/{drive_id}",
        "size_bytes": 1024,
        "modified_time": "2026-05-01T00:00:00.000Z",
        "trashed": False,
        "capabilities": {"canDownload": True, "canRename": True, "canDelete": False},
    }
    item.update(extra)
    return item


def trial_folder_children() -> list[dict]:
    """The confirmed shape of the approved folder: 16 QuickTime videos, 3 HEIC images."""
    videos = [child(f"video-{i}", f"IMG_{i}.MOV", "video/quicktime") for i in range(16)]
    images = [child(f"image-{i}", f"IMG_{i}.HEIC", "image/heif") for i in range(3)]
    return videos + images


def test_supported_video_detection() -> None:
    assert is_supported_video("video/quicktime")
    assert is_supported_video("VIDEO/MP4")
    assert not is_supported_video("image/heif")
    assert not is_supported_video("")


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (child("f", "Sub", FOLDER_MIME), EXCLUSION_FOLDER),
        (child("t", "Old.MOV", "video/quicktime", trashed=True), EXCLUSION_TRASHED),
        (child("i", "Photo.HEIC", "image/heif"), EXCLUSION_NOT_VIDEO),
        (
            child("d", "Locked.MOV", "video/quicktime", capabilities={"canDownload": False}),
            EXCLUSION_NOT_DOWNLOADABLE,
        ),
        (child("ok", "Good.MOV", "video/quicktime"), None),
    ],
)
def test_every_exclusion_carries_its_reason(item: dict, expected: str | None) -> None:
    assert exclusion_reason(item) == expected


def test_trial_folder_splits_into_sixteen_videos_and_three_excluded_images() -> None:
    classification = classify_children(trial_folder_children())

    assert classification.supported_count == 16
    assert classification.excluded_count == 3
    assert {item["reason"] for item in classification.excluded} == {EXCLUSION_NOT_VIDEO}
    assert classification.mime_type_counts() == {"image/heif": 3, "video/quicktime": 16}


def test_subfolders_are_excluded_never_traversed() -> None:
    classification = classify_children([child("sub", "Visit A", FOLDER_MIME)] + trial_folder_children())

    reasons = {item["drive_id"]: item["reason"] for item in classification.excluded}
    assert reasons["sub"] == EXCLUSION_FOLDER
    assert classification.supported_count == 16


def test_duplicate_drive_ids_are_rejected() -> None:
    duplicate = child("video-0", "IMG_0.MOV", "video/quicktime")
    with pytest.raises(ValidationError, match="duplicate"):
        classify_children([duplicate, duplicate])


def test_manifest_records_boundary_and_every_exclusion() -> None:
    classification = classify_children(trial_folder_children())
    manifest = build_manifest("folder-id", "Teak Test Library", classification)
    document = manifest_document("20260917T000000Z", manifest, classification)

    assert document["processing_boundary"] == "DIRECT_MEDIA_CHILDREN"
    assert document["manifest_id"] == "20260917T000000Z-folder-id"
    assert document["supported_count"] == 16
    assert len(document["excluded_items"]) == 3
    assert all(item["reason"] for item in document["excluded_items"])
    assert manifest.visit.drive_id == "folder-id"


def test_a_folder_with_no_supported_video_refuses_to_produce_a_manifest() -> None:
    classification = classify_children([child("i", "Photo.HEIC", "image/heif")])
    with pytest.raises(ValidationError, match="no supported video"):
        build_manifest("folder-id", "Empty", classification)


def test_limit_and_asset_id_select_cheaply_without_reordering() -> None:
    manifest = build_manifest("folder-id", "Library", classify_children(trial_folder_children()))

    assert len(select_assets(manifest, limit=1)) == 1
    assert select_assets(manifest, limit=3)[0].drive_id == "video-0"
    assert select_assets(manifest, asset_id="video-5")[0].drive_id == "video-5"
    with pytest.raises(ValidationError, match="not present"):
        select_assets(manifest, asset_id="image-0")
    with pytest.raises(ValidationError, match="at least 1"):
        select_assets(manifest, limit=0)
