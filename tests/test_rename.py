"""Gate 6 rules, tested without contacting Google.

No test here calls a Drive API. `build_new_name` and the eligibility rules are
pure, and the one execution test uses a recording double in place of the
`DriveGateway`, so the approval gate can be proved rather than asserted.
"""

from __future__ import annotations

from typing import Any

import pytest

from site_visit_workflow.catalog import RENAME_DECISION, build_catalog_row
from site_visit_workflow.errors import ValidationError
from site_visit_workflow.models import DriveMediaFile, L1Extraction
from site_visit_workflow.rename import (
    MAX_STEM_CHARACTERS,
    RENAME_FAILED,
    RENAME_RENAMED,
    RENAME_SKIPPED_ASSET_NOT_ELIGIBLE,
    RENAME_SKIPPED_DRY_RUN,
    RENAME_SKIPPED_NOT_APPROVED,
    RENAME_SKIPPED_NO_SUGGESTION,
    asset_is_eligible,
    build_new_name,
    execute_rename,
    plan_rename,
    rename_is_authorized,
    summarize_renames,
)


class RecordingDrive:
    """Stands in for `DriveGateway`: records renames, contacts nothing."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail = fail

    def rename(self, asset_id: str, new_name: str) -> None:
        if self._fail:
            raise RuntimeError("Drive said no")
        self.calls.append((asset_id, new_name))


# --- build_new_name -------------------------------------------------------


@pytest.mark.parametrize(
    ("original", "suggested", "expected"),
    [
        ("IMG_0001.MOV", "kitchen-sink-leak", "kitchen-sink-leak.MOV"),
        ("IMG_0001.mov", "kitchen-sink-leak", "kitchen-sink-leak.mov"),
        # The model's own extension never wins over the real one.
        ("IMG_0001.MOV", "kitchen-sink-leak.mov", "kitchen-sink-leak.MOV"),
        ("IMG_0001.MOV", "kitchen-sink-leak.MOV", "kitchen-sink-leak.MOV"),
        ("IMG_0001.mov", "kitchen-sink-leak.mp4", "kitchen-sink-leak.mov"),
        # An original with no extension keeps having no extension.
        ("IMG_0001", "kitchen-sink-leak", "kitchen-sink-leak"),
    ],
)
def test_the_original_extension_is_always_preserved(
    original: str, suggested: str, expected: str
) -> None:
    assert build_new_name(original, suggested) == expected


@pytest.mark.parametrize(
    ("suggested", "expected_stem"),
    [
        ("unit 4b  water heater", "unit_4b_water_heater"),
        ("  ..leading and trailing.. ", "leading_and_trailing"),
        ("kitchen/sink\\drain", "kitchen_sink_drain"),
        ("roof\ndeck\tcrack", "roof_deck_crack"),
        ("bad\x00control\x07chars", "badcontrolchars"),
    ],
)
def test_suggested_names_are_sanitized(suggested: str, expected_stem: str) -> None:
    assert build_new_name("IMG_0001.MOV", suggested) == f"{expected_stem}.MOV"


@pytest.mark.parametrize("suggested", [None, "", "   ", "...", " . . ", "///", ".mov"])
def test_an_unusable_suggestion_means_skip_rather_than_a_guessed_name(suggested: Any) -> None:
    assert build_new_name("IMG_0001.MOV", suggested) is None


def test_an_over_long_stem_is_capped_and_the_extension_survives() -> None:
    new_name = build_new_name("IMG_0001.MOV", "a" * 400)

    assert new_name is not None
    assert new_name.endswith(".MOV")
    assert len(new_name.removesuffix(".MOV")) == MAX_STEM_CHARACTERS


def test_a_missing_original_name_is_a_validation_failure() -> None:
    with pytest.raises(ValidationError, match="original Drive name"):
        build_new_name("", "kitchen-sink-leak")


# --- eligibility and approval --------------------------------------------


@pytest.mark.parametrize(
    ("status", "l1_validated", "eligible"),
    [
        ("CATALOGUED", True, True),
        ("CATALOGUED", False, False),
        ("NEEDS_REVIEW", True, False),
        ("FAILED", True, False),
        ("DRY_RUN", True, False),
    ],
)
def test_only_a_catalogued_asset_with_a_validated_l1_is_eligible(
    status: str, l1_validated: bool, eligible: bool
) -> None:
    assert asset_is_eligible(status, l1_validated) is eligible


@pytest.mark.parametrize(
    ("env_flag", "cli_flag", "authorized"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_both_approvals_are_required(env_flag: bool, cli_flag: bool, authorized: bool) -> None:
    assert rename_is_authorized(env_flag, cli_flag) is authorized


def test_an_unapproved_run_never_contacts_drive() -> None:
    drive = RecordingDrive()

    outcome = execute_rename(
        drive, "id-1", "IMG_0001.MOV", "kitchen-leak", "CATALOGUED", True, authorized=False
    )

    assert outcome.rename_status == RENAME_SKIPPED_NOT_APPROVED
    assert outcome.new_drive_name is None
    assert drive.calls == []


def test_a_needs_review_asset_is_never_renamed() -> None:
    drive = RecordingDrive()

    outcome = execute_rename(
        drive, "id-1", "IMG_0001.MOV", "kitchen-leak", "NEEDS_REVIEW", True, authorized=True
    )

    assert outcome.rename_status == RENAME_SKIPPED_ASSET_NOT_ELIGIBLE
    assert drive.calls == []


def test_a_dry_run_never_renames() -> None:
    drive = RecordingDrive()

    outcome = execute_rename(
        drive, "id-1", "IMG_0001.MOV", "kitchen-leak", "CATALOGUED", True, True, dry_run=True
    )

    assert outcome.rename_status == RENAME_SKIPPED_DRY_RUN
    assert drive.calls == []


def test_an_approved_eligible_asset_is_renamed_through_the_single_drive_path() -> None:
    drive = RecordingDrive()

    outcome = execute_rename(
        drive, "id-1", "IMG_0001.MOV", "kitchen leak", "CATALOGUED", True, authorized=True
    )

    assert outcome.rename_status == RENAME_RENAMED
    assert outcome.new_drive_name == "kitchen_leak.MOV"
    assert outcome.original_drive_name == "IMG_0001.MOV"
    assert drive.calls == [("id-1", "kitchen_leak.MOV")]


def test_an_approved_asset_with_no_usable_suggestion_is_skipped() -> None:
    drive = RecordingDrive()

    outcome = execute_rename(
        drive, "id-1", "IMG_0001.MOV", "   ", "CATALOGUED", True, authorized=True
    )

    assert outcome.rename_status == RENAME_SKIPPED_NO_SUGGESTION
    assert drive.calls == []


def test_a_drive_failure_is_recorded_and_does_not_raise() -> None:
    outcome = execute_rename(
        RecordingDrive(fail=True),
        "id-1",
        "IMG_0001.MOV",
        "kitchen leak",
        "CATALOGUED",
        True,
        authorized=True,
    )

    assert outcome.rename_status == RENAME_FAILED
    assert outcome.error is not None
    assert outcome.error["error_type"] == "RuntimeError"


def test_rename_counts_are_summarized_for_the_run_summary() -> None:
    outcomes = [
        plan_rename("a", "A.MOV", "x", "CATALOGUED", True, False),
        plan_rename("b", "B.MOV", "x", "NEEDS_REVIEW", True, True),
        plan_rename("c", "C.MOV", "x", "NEEDS_REVIEW", True, True),
    ]

    assert summarize_renames(outcomes) == {
        RENAME_SKIPPED_NOT_APPROVED: 1,
        RENAME_SKIPPED_ASSET_NOT_ELIGIBLE: 2,
    }


# --- idempotency ----------------------------------------------------------


def _row(name: str, decision: str | None) -> dict[str, Any]:
    asset = DriveMediaFile(
        drive_id="drive-id-immutable", original_name=name, mime_type="video/quicktime"
    )
    l1 = L1Extraction(
        source_asset_identifier="drive-id-immutable",
        location="Unit 4B",
        issue_description="Leak under the sink",
        suggested_filename="kitchen leak",
        confidence_note="Stated clearly.",
    )
    return build_catalog_row(
        asset=asset,
        visit_drive_id="visit-1",
        run_id="run-1",
        asset_status="CATALOGUED",
        transcription={"status": "COMPLETED"},
        updated_at="2026-09-18T00:00:00+00:00",
        evidence_gcs_prefix="gs://bucket/prefix",
        l1=l1,
        drive_rename_decision=decision,
    )


def test_the_catalog_row_key_is_unaffected_by_a_rename() -> None:
    before = _row("IMG_0001.MOV", None)
    outcome = execute_rename(
        RecordingDrive(),
        "drive-id-immutable",
        "IMG_0001.MOV",
        "kitchen leak",
        "CATALOGUED",
        True,
        authorized=True,
    )
    after = _row("IMG_0001.MOV", f"RENAMED_TO:{outcome.new_drive_name}")

    # The row key is the immutable Drive file ID, so a re-run after a rename
    # updates the same row instead of appending a duplicate.
    assert before["row_key"] == after["row_key"] == "drive-id-immutable"
    # And the catalogue keeps the DISCOVERY-time name, not the new one.
    assert after["original_drive_name"] == "IMG_0001.MOV"
    assert after["drive_rename_decision"] == "RENAMED_TO:kitchen_leak.MOV"


def test_an_unapproved_run_keeps_the_historical_proposal_wording() -> None:
    assert _row("IMG_0001.MOV", None)["drive_rename_decision"] == RENAME_DECISION
