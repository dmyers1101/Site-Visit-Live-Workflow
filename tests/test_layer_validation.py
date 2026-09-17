"""L2/L3 validators, written against the recorded pilot failure modes.

Each rejection here corresponds to something the pilot actually produced:
transcripts echoed back inside the response, Markdown code fences on 100% of
responses, out-of-vocabulary trade values, and null notes.
"""

import pytest

from site_visit_workflow.errors import ValidationError
from site_visit_workflow.models import (
    L1Extraction,
    L2Enrichment,
    L3Refinement,
    l3_is_permitted,
    parse_strict_json,
)

ASSET = "video-id"
L1_RECORD = "L1-video-id-abc"
L2_RECORD = "L2-video-id-def"


def l2_payload(**overrides: object) -> dict:
    payload = {
        "source_asset_identifier": ASSET,
        "prior_layer": "L1",
        "prior_layer_record_id": L1_RECORD,
        "enrichment_status": "ENRICHED",
        "trade": "plumbing",
        "area_type": "unit",
        "severity": 2,
        "recommended_action": "Dispatch a plumber to reseal the trap.",
        "enrichment_note": "Transcript-supported; visually unverified.",
    }
    payload.update(overrides)
    return payload


def l3_payload(**overrides: object) -> dict:
    payload = {
        "source_asset_identifier": ASSET,
        "prior_layer": "L2",
        "prior_layer_record_id": L2_RECORD,
        "refinement_status": "REFINED",
        "responsible_party": "vendor",
        "urgency_window": "this-week",
        "disputed_prior_fields": [],
        "refinement_note": "Owner class inferred from the narrated scope.",
    }
    payload.update(overrides)
    return payload


def validated_l2(**overrides: object) -> L2Enrichment:
    return L2Enrichment.from_external_result(l2_payload(**overrides), ASSET, L1_RECORD)


# --- strict JSON parsing -----------------------------------------------------


def test_markdown_code_fence_is_a_validation_failure_not_something_to_strip() -> None:
    fenced = '```json\n{"a": 1}\n```'
    with pytest.raises(ValidationError, match="code fence"):
        parse_strict_json(fenced, "L2")


def test_empty_and_non_object_responses_are_rejected() -> None:
    with pytest.raises(ValidationError, match="empty"):
        parse_strict_json("   ", "L1")
    with pytest.raises(ValidationError, match="not valid JSON"):
        parse_strict_json("{oops}", "L1")
    with pytest.raises(ValidationError, match="single JSON object"):
        parse_strict_json("[1, 2]", "L1")


# --- L1 nullable boundary ----------------------------------------------------


def l1_payload(**overrides: object) -> dict:
    payload = {
        "source_asset_identifier": ASSET,
        "location": "Building 3 breezeway",
        "issue_description": "Downspout is detached at the elbow.",
        "suggested_filename": "bldg3-downspout-detached.mov",
        "confidence_note": "Narration is clear; no visual confirmation.",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("field", ["location", "issue_description"])
def test_l1_accepts_an_explicit_null_location_or_issue(field: str) -> None:
    """A genuinely location-less clip is a real outcome, not a validation failure."""
    extraction = L1Extraction.from_external_result(l1_payload(**{field: None}), ASSET)

    assert getattr(extraction, field) is None
    assert extraction.suggested_filename == "bldg3-downspout-detached.mov"


def test_l1_accepts_both_nullable_fields_being_null_at_once() -> None:
    extraction = L1Extraction.from_external_result(
        l1_payload(location=None, issue_description=None), ASSET
    )

    assert extraction.location is None
    assert extraction.issue_description is None
    assert extraction.confidence_note


@pytest.mark.parametrize("field", ["location", "issue_description"])
def test_l1_rejects_an_empty_string_in_place_of_an_explicit_null(field: str) -> None:
    with pytest.raises(ValidationError, match="explicit null"):
        L1Extraction.from_external_result(l1_payload(**{field: "   "}), ASSET)


@pytest.mark.parametrize("field", ["source_asset_identifier", "suggested_filename", "confidence_note"])
def test_l1_keeps_the_other_three_fields_required_and_non_empty(field: str) -> None:
    with pytest.raises(ValidationError):
        L1Extraction.from_external_result(l1_payload(**{field: None}), ASSET)
    with pytest.raises(ValidationError):
        L1Extraction.from_external_result(l1_payload(**{field: "  "}), ASSET)


def test_l1_still_rejects_extra_keys_and_a_mismatched_source() -> None:
    with pytest.raises(ValidationError, match="exactly"):
        L1Extraction.from_external_result(l1_payload(trade="plumbing"), ASSET)
    with pytest.raises(ValidationError, match="does not match"):
        L1Extraction.from_external_result(l1_payload(source_asset_identifier="other"), ASSET)


# --- L2 ----------------------------------------------------------------------


def test_l2_accepts_the_governed_nine_key_object() -> None:
    enrichment = validated_l2()
    assert enrichment.source_asset_identifier == ASSET
    assert enrichment.prior_layer_record_id == L1_RECORD
    assert enrichment.severity == 2


def test_l2_rejects_an_echoed_transcript_or_any_other_extra_key() -> None:
    with pytest.raises(ValidationError, match="exactly"):
        L2Enrichment.from_external_result(
            l2_payload(transcript_text="the whole transcript again"), ASSET, L1_RECORD
        )


def test_l2_rejects_a_missing_key() -> None:
    payload = l2_payload()
    del payload["area_type"]
    with pytest.raises(ValidationError, match="exactly"):
        L2Enrichment.from_external_result(payload, ASSET, L1_RECORD)


@pytest.mark.parametrize("trade", ["pest-control", "restoration", "painting", "drywall", "Plumbing"])
def test_l2_rejects_out_of_vocabulary_trades(trade: str) -> None:
    with pytest.raises(ValidationError, match="L2 trade must be one of"):
        L2Enrichment.from_external_result(l2_payload(trade=trade), ASSET, L1_RECORD)


@pytest.mark.parametrize(
    ("field", "value"),
    [("area_type", "roof"), ("enrichment_status", "DONE"), ("prior_layer", "L0")],
)
def test_l2_rejects_other_out_of_vocabulary_enums(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        L2Enrichment.from_external_result(l2_payload(**{field: value}), ASSET, L1_RECORD)


@pytest.mark.parametrize("severity", [1, 2, 3, 4])
def test_l2_accepts_the_integer_severity_scale(severity: int) -> None:
    assert L2Enrichment.from_external_result(
        l2_payload(severity=severity), ASSET, L1_RECORD
    ).severity == severity


@pytest.mark.parametrize(
    "severity", ["high", "2", "urgent-safety", "low-cosmetic", 0, 5, -1, 2.0, True]
)
def test_l2_rejects_string_and_out_of_range_severity_without_coercing(severity: object) -> None:
    """Severity is an integer enum; a string form is a failure, never coerced."""
    with pytest.raises(ValidationError, match="L2 severity must be the integer"):
        L2Enrichment.from_external_result(l2_payload(severity=severity), ASSET, L1_RECORD)


def test_l2_rejects_a_null_note() -> None:
    with pytest.raises(ValidationError, match="enrichment_note"):
        L2Enrichment.from_external_result(l2_payload(enrichment_note=None), ASSET, L1_RECORD)


def test_l2_coupling_rule_enriched_requires_all_four_fields() -> None:
    with pytest.raises(ValidationError, match="cannot be null"):
        L2Enrichment.from_external_result(l2_payload(severity=None), ASSET, L1_RECORD)


@pytest.mark.parametrize("status", ["NO_FINDING", "INSUFFICIENT_EVIDENCE"])
def test_l2_coupling_rule_other_statuses_require_all_four_nulls(status: str) -> None:
    with pytest.raises(ValidationError, match="must be null"):
        L2Enrichment.from_external_result(l2_payload(enrichment_status=status), ASSET, L1_RECORD)

    cleared = l2_payload(
        enrichment_status=status, trade=None, area_type=None, severity=None, recommended_action=None
    )
    assert L2Enrichment.from_external_result(cleared, ASSET, L1_RECORD).enrichment_status == status


def test_l2_without_supporting_evidence_may_only_be_no_finding() -> None:
    cleared = l2_payload(
        enrichment_status="INSUFFICIENT_EVIDENCE",
        trade=None,
        area_type=None,
        severity=None,
        recommended_action=None,
    )
    with pytest.raises(ValidationError, match="NO_FINDING"):
        L2Enrichment.from_external_result(
            cleared, ASSET, L1_RECORD, evidence_supports_finding=False
        )


def test_l2_traceability_is_enforced_in_both_directions() -> None:
    with pytest.raises(ValidationError, match="does not match the selected Drive asset"):
        L2Enrichment.from_external_result(l2_payload(source_asset_identifier="other"), ASSET, L1_RECORD)
    with pytest.raises(ValidationError, match="prior_layer must be the literal L1"):
        L2Enrichment.from_external_result(l2_payload(prior_layer="L2"), ASSET, L1_RECORD)
    with pytest.raises(ValidationError, match="prior_layer_record_id"):
        L2Enrichment.from_external_result(l2_payload(prior_layer_record_id="stale"), ASSET, L1_RECORD)


# --- L3 ----------------------------------------------------------------------


def test_l3_runs_only_on_an_enriched_l2() -> None:
    assert l3_is_permitted(validated_l2()) is True
    for status in ("NO_FINDING", "INSUFFICIENT_EVIDENCE"):
        downgraded = validated_l2(
            enrichment_status=status,
            trade=None,
            area_type=None,
            severity=None,
            recommended_action=None,
        )
        assert l3_is_permitted(downgraded) is False


def test_l3_accepts_the_governed_eight_key_object() -> None:
    refinement = L3Refinement.from_external_result(l3_payload(), ASSET, L2_RECORD)
    assert refinement.disputed_prior_fields == ()
    assert refinement.urgency_window == "this-week"


def test_l3_rejects_extra_keys_including_restated_upstream_values() -> None:
    with pytest.raises(ValidationError, match="exactly"):
        L3Refinement.from_external_result(l3_payload(severity="high"), ASSET, L2_RECORD)
    with pytest.raises(ValidationError, match="exactly"):
        L3Refinement.from_external_result(
            l3_payload(transcript_text="echoed transcript"), ASSET, L2_RECORD
        )


def test_l3_coupling_rule() -> None:
    with pytest.raises(ValidationError, match="cannot be null"):
        L3Refinement.from_external_result(l3_payload(urgency_window=None), ASSET, L2_RECORD)
    with pytest.raises(ValidationError, match="must be null"):
        L3Refinement.from_external_result(
            l3_payload(refinement_status="INSUFFICIENT_EVIDENCE"), ASSET, L2_RECORD
        )
    downgraded = l3_payload(
        refinement_status="INSUFFICIENT_EVIDENCE", responsible_party=None, urgency_window=None
    )
    assert L3Refinement.from_external_result(downgraded, ASSET, L2_RECORD).responsible_party is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("responsible_party", "contractor"), ("urgency_window", "asap"), ("refinement_status", "OK")],
)
def test_l3_rejects_out_of_vocabulary_enums(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match="must be one of"):
        L3Refinement.from_external_result(l3_payload(**{field: value}), ASSET, L2_RECORD)


def test_l3_disputed_fields_must_be_a_unique_array_from_the_fixed_list() -> None:
    accepted = L3Refinement.from_external_result(
        l3_payload(disputed_prior_fields=["severity", "location"]), ASSET, L2_RECORD
    )
    assert accepted.disputed_prior_fields == ("severity", "location")
    with pytest.raises(ValidationError, match="array"):
        L3Refinement.from_external_result(l3_payload(disputed_prior_fields="severity"), ASSET, L2_RECORD)
    with pytest.raises(ValidationError, match="unique"):
        L3Refinement.from_external_result(
            l3_payload(disputed_prior_fields=["severity", "severity"]), ASSET, L2_RECORD
        )
    with pytest.raises(ValidationError, match="must be one of"):
        L3Refinement.from_external_result(
            l3_payload(disputed_prior_fields=["priority"]), ASSET, L2_RECORD
        )


def test_l3_rejects_a_null_note() -> None:
    with pytest.raises(ValidationError, match="refinement_note"):
        L3Refinement.from_external_result(l3_payload(refinement_note=None), ASSET, L2_RECORD)
