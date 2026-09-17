"""Gate 5 row building: idempotent key, honest NOT_RUN layers, stable width."""

import pytest

from site_visit_workflow.catalog import (
    FULL_CATALOG_HEADERS,
    RENAME_DECISION,
    build_catalog_row,
    row_values,
)
from site_visit_workflow.errors import ValidationError
from site_visit_workflow.google import column_letter
from site_visit_workflow.models import DriveMediaFile, L1Extraction, L2Enrichment, L3Refinement

ASSET_ID = "1AbCdEfGhIjK"
L1_RECORD = "L1-record"
L2_RECORD = "L2-record"


def asset() -> DriveMediaFile:
    return DriveMediaFile(
        drive_id=ASSET_ID,
        original_name="IMG_4312.MOV",
        mime_type="video/quicktime",
        web_view_link=f"https://drive.google.com/file/d/{ASSET_ID}/view",
        size_bytes=52_428_800,
        modified_time="2026-05-14T18:02:11.000Z",
    )


def transcription(status: str = "COMPLETED") -> dict:
    return {
        "status": status,
        "wav_gcs_uri": f"gs://bucket/prefix/run/{ASSET_ID}/audio/attempt-0/{ASSET_ID}.wav",
        "output_gcs_uri": f"gs://bucket/prefix/run/{ASSET_ID}/speech-output/attempt-0/",
        "started_at": "2026-09-17T06:00:00+00:00",
        "completed_at": "2026-09-17T06:02:00+00:00",
        "transcript_gcs_uri": f"gs://bucket/prefix/run/{ASSET_ID}/transcript.txt",
    }


def l1(source: str = ASSET_ID) -> L1Extraction:
    return L1Extraction.from_external_result(
        {
            "source_asset_identifier": source,
            "location": "Building 3 breezeway",
            "issue_description": "Downspout is detached at the elbow.",
            "suggested_filename": "bldg3-breezeway-downspout-detached.mov",
            "confidence_note": "Narration is clear; no visual confirmation.",
        },
        source,
    )


def l2() -> L2Enrichment:
    return L2Enrichment.from_external_result(
        {
            "source_asset_identifier": ASSET_ID,
            "prior_layer": "L1",
            "prior_layer_record_id": L1_RECORD,
            "enrichment_status": "ENRICHED",
            "trade": "general-maintenance",
            "area_type": "exterior",
            "severity": 3,
            "recommended_action": "Reattach and secure the downspout elbow.",
            "enrichment_note": "Trade chosen as the nearest allowed value.",
        },
        ASSET_ID,
        L1_RECORD,
    )


def l3() -> L3Refinement:
    return L3Refinement.from_external_result(
        {
            "source_asset_identifier": ASSET_ID,
            "prior_layer": "L2",
            "prior_layer_record_id": L2_RECORD,
            "refinement_status": "REFINED",
            "responsible_party": "in-house",
            "urgency_window": "this-month",
            "disputed_prior_fields": ["severity"],
            "refinement_note": "Severity reads low-cosmetic from the narration.",
        },
        ASSET_ID,
        L2_RECORD,
    )


def row(**kwargs: object) -> dict:
    defaults = {
        "asset": asset(),
        "visit_drive_id": "folder-id",
        "run_id": "20260917T060000Z",
        "asset_status": "CATALOGUED",
        "transcription": transcription(),
        "updated_at": "2026-09-17T06:05:00+00:00",
        "evidence_gcs_prefix": f"gs://bucket/prefix/run/{ASSET_ID}",
    }
    defaults.update(kwargs)
    return build_catalog_row(**defaults)


def test_row_key_is_the_immutable_drive_asset_id() -> None:
    built = row(l1=l1(), l2=l2(), l3=l3())

    assert built["row_key"] == ASSET_ID
    assert built["row_key"] == built["source_asset_identifier"]
    assert built["original_drive_name"] == "IMG_4312.MOV"


def test_two_runs_over_the_same_asset_produce_the_same_row_key() -> None:
    first = row(run_id="run-a", l1=l1())
    second = row(run_id="run-b", l1=l1(), updated_at="2026-09-18T06:05:00+00:00")

    assert first["row_key"] == second["row_key"]
    assert first["run_id"] != second["run_id"]


def test_row_width_and_order_match_the_header_contract() -> None:
    built = row(l1=l1(), l2=l2(), l3=l3())
    values = row_values(built)

    assert tuple(built) == FULL_CATALOG_HEADERS
    assert len(values) == len(FULL_CATALOG_HEADERS)
    assert values[0] == ASSET_ID
    assert column_letter(len(FULL_CATALOG_HEADERS)) == "AH"


def test_headers_start_with_the_original_catalog_draft_columns() -> None:
    from site_visit_workflow.cli import CATALOG_HEADERS

    assert FULL_CATALOG_HEADERS[: len(CATALOG_HEADERS)] == CATALOG_HEADERS


def test_a_needs_review_asset_gets_a_real_row_with_no_invented_findings() -> None:
    built = row(asset_status="NEEDS_REVIEW", transcription=transcription("NEEDS_REVIEW"))

    assert built["asset_status"] == "NEEDS_REVIEW"
    assert built["l1_status"] == "NOT_RUN"
    assert built["l2_status"] == "NOT_RUN"
    assert built["l3_status"] == "NOT_RUN"
    assert built["issue_description"] == ""
    assert built["l2_severity"] == ""
    assert built["l3_disputed_prior_fields"] == ""


def test_a_stopped_chain_records_the_layers_that_did_run() -> None:
    stopped = L2Enrichment.from_external_result(
        {
            "source_asset_identifier": ASSET_ID,
            "prior_layer": "L1",
            "prior_layer_record_id": L1_RECORD,
            "enrichment_status": "NO_FINDING",
            "trade": None,
            "area_type": None,
            "severity": None,
            "recommended_action": None,
            "enrichment_note": "Narration records no maintenance issue.",
        },
        ASSET_ID,
        L1_RECORD,
    )
    built = row(l1=l1(), l2=stopped)

    assert built["l1_status"] == "VALIDATED"
    assert built["l2_status"] == "NO_FINDING"
    assert built["l3_status"] == "NOT_RUN"


def test_integer_severity_reaches_the_sheet_as_an_integer() -> None:
    built = row(l1=l1(), l2=l2(), l3=l3())
    values = row_values(built)

    assert built["l2_severity"] == 3
    assert isinstance(built["l2_severity"], int)
    assert values[FULL_CATALOG_HEADERS.index("l2_severity")] == 3


def test_a_null_severity_renders_as_an_empty_cell_not_the_word_none() -> None:
    cleared = L2Enrichment.from_external_result(
        {
            "source_asset_identifier": ASSET_ID,
            "prior_layer": "L1",
            "prior_layer_record_id": L1_RECORD,
            "enrichment_status": "INSUFFICIENT_EVIDENCE",
            "trade": None,
            "area_type": None,
            "severity": None,
            "recommended_action": None,
            "enrichment_note": "Narration is audible but the issue is unclassifiable.",
        },
        ASSET_ID,
        L1_RECORD,
    )
    built = row(l1=l1(), l2=cleared)

    assert built["l2_severity"] == ""
    assert built["l2_trade"] == ""
    assert built["l2_status"] == "INSUFFICIENT_EVIDENCE"


def test_a_location_less_clip_still_produces_a_catalog_row() -> None:
    nullable = L1Extraction.from_external_result(
        {
            "source_asset_identifier": ASSET_ID,
            "location": None,
            "issue_description": None,
            "suggested_filename": "unlabelled-clip.mov",
            "confidence_note": "Narration gives no location and states no issue.",
        },
        ASSET_ID,
    )
    built = row(l1=nullable)

    assert built["l1_status"] == "VALIDATED"
    assert built["location"] == ""
    assert built["issue_description"] == ""
    assert built["suggested_filename"] == "unlabelled-clip.mov"


def test_every_row_records_that_drive_was_not_renamed() -> None:
    assert row(l1=l1())["drive_rename_decision"] == RENAME_DECISION


def test_a_row_refuses_records_belonging_to_another_asset() -> None:
    with pytest.raises(ValidationError, match="does not belong"):
        row(l1=l1(source="a-different-asset"))


def test_a_layer_cannot_be_catalogued_without_its_prior_layer() -> None:
    with pytest.raises(ValidationError, match="without its validated L1"):
        row(l2=l2())
    with pytest.raises(ValidationError, match="without its validated L2"):
        row(l1=l1(), l3=l3())


def test_row_values_reports_a_missing_column_rather_than_shifting_data() -> None:
    built = row(l1=l1())
    del built["updated_at"]
    with pytest.raises(ValidationError, match="missing columns"):
        row_values(built)


@pytest.mark.parametrize(("index", "expected"), [(1, "A"), (15, "O"), (26, "Z"), (27, "AA"), (34, "AH")])
def test_column_letters_extend_past_z(index: int, expected: str) -> None:
    assert column_letter(index) == expected
