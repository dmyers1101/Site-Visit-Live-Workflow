"""reprocess-l2 invariants (pure): eligibility, column guard, row rebuild."""

from __future__ import annotations

from typing import Any

import pytest

from site_visit_workflow import reprocess as rpc
from site_visit_workflow.catalog import FULL_CATALOG_HEADERS
from site_visit_workflow.errors import ValidationError
from site_visit_workflow.models import L1Extraction, L2Enrichment

ID = "1iP8OgTaAMxKoy-KzxKlQ6XtItIe_dUDz"


def _row(**over: Any) -> dict[str, Any]:
    row = {name: "" for name in FULL_CATALOG_HEADERS}
    row.update({
        "row_key": ID, "source_asset_identifier": ID, "original_drive_name": "North_Wing_first_floor_stain.MOV",
        "drive_link": "https://drive.google.com/file/d/x/view", "visit_drive_id": "visit-1",
        "location": "North Wing, first floor", "issue_description": "stain",
        "suggested_filename": "North_Wing_first_floor_stain", "confidence_note": "High confidence",
        "transcription_status": "COMPLETED", "wav_gcs_uri": "gs://b/w.wav", "transcript_output_gcs_uri": "gs://b/o/",
        "transcription_started_at": "t0", "transcription_completed_at": "t1", "catalog_status": "DRAFT",
        "catalog_schema_version": "2.0", "run_id": "20260929T185459Z-v01", "asset_status": "CATALOGUED",
        "l1_status": "VALIDATED", "l2_status": "NO_FINDING", "l2_enrichment_note": "old note",
        "l3_status": "NOT_RUN", "transcript_gcs_uri": "gs://b/p/transcript.txt", "evidence_gcs_prefix": "gs://b/p",
        "drive_rename_decision": "RENAMED_TO:North_Wing_first_floor_stain.MOV", "updated_at": "old",
        "state": "TX", "property": "Alta", "visit_name": "2026-08 Executive", "uploader_name": "lbeynon",
        "uploaded_at": "2026-09-24T00:00:00Z",
    })
    row.update(over)
    return row


def _l1() -> L1Extraction:
    return L1Extraction(ID, "North Wing, first floor", "stain", "North_Wing_first_floor_stain", "High confidence")


def _tracked() -> L2Enrichment:
    return L2Enrichment(ID, "L1", "L1-rec", "ALREADY_TRACKED", None, None, None, None, "Speaker already identified it.")


@pytest.mark.parametrize("over, ok", [
    ({}, True),
    ({"transcription_status": "FAILED"}, False),
    ({"l1_status": "NOT_RUN"}, False),
    ({"transcript_gcs_uri": ""}, False),
    ({"evidence_gcs_prefix": ""}, False),
])
def test_only_rows_with_a_transcript_and_validated_l1_are_eligible(over: dict[str, Any], ok: bool) -> None:
    assert rpc.eligible(_row(**over))[0] is ok


def test_rebuild_changes_only_l2_l3_status_and_timestamp() -> None:
    old = _row()
    new = rpc.rebuild_row(old, _l1(), _tracked(), None, {}, "now")

    changed = rpc.assert_only_layer_columns_changed(old, new)

    assert new["l2_status"] == "ALREADY_TRACKED"
    assert changed <= rpc.REPROCESS_COLUMNS and "l2_status" in changed
    assert tuple(new) == FULL_CATALOG_HEADERS
    for name in ("drive_rename_decision", "run_id", "evidence_gcs_prefix", "location", "uploaded_at"):
        assert new[name] == old[name], name


def test_a_layer_error_marks_the_row_needs_review() -> None:
    new = rpc.rebuild_row(_row(), _l1(), None, None, {"L2": "bad"}, "now")
    assert new["asset_status"] == "NEEDS_REVIEW" and new["l2_status"] == "NOT_RUN"


def test_a_change_outside_the_layer_columns_aborts() -> None:
    old = _row()
    new = dict(old, location="Somewhere else")
    with pytest.raises(ValidationError, match="non-L2/L3 columns"):
        rpc.assert_only_layer_columns_changed(old, new)


def test_object_names_must_be_in_the_staging_bucket() -> None:
    assert rpc.object_name("gs://b/p/transcript.txt", "b") == "p/transcript.txt"
    with pytest.raises(ValidationError):
        rpc.object_name("gs://other/p", "b")
