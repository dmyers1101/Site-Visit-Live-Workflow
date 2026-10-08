"""Gate 7 (report-synthesis 1.0.0, ADR 0013), with no live Google calls.

One test per report invariant, named after it. The Vertex call is replaced by a
fake client and the Docs API by a fake service, so what is exercised is every
decision about WHAT would be written and in what order.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from site_visit_workflow import report as rp
from site_visit_workflow.errors import ValidationError
from site_visit_workflow.google import write_report_requests

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _row(key: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "row_key": f"drive-id-{key}",
        "original_drive_name": f"IMG_{key}.MOV",
        "drive_link": f"https://drive.google.com/file/d/{key}/view",
        "location": "Unit 4B kitchen",
        "issue_description": "Leak under the sink",
        "asset_status": "CATALOGUED",
        "l2_status": "ENRICHED",
        "l2_trade": "plumbing",
        "l2_area_type": "unit",
        "l2_severity": "2",
        "l2_recommended_action": "Schedule a plumber",
        "l3_responsible_party": "maintenance",
        "l3_urgency_window": "within 48 hours",
        "property": "Alma",
        "visit_name": "2026-08 Regional",
        "uploader_name": "Pat Example",
        "uploaded_at": "2026-09-03T10:00:00Z",
    }
    row.update(overrides)
    return row


def _rows() -> list[dict[str, Any]]:
    return [
        _row("1"),
        _row("2", location="Pool gate", issue_description="Gate propped open", l2_trade="safety",
             l2_area_type="amenity", l2_severity="1"),
        _row("3", location="Unit 4B kitchen", l2_severity="3"),
        _row("4", l2_status="NO_FINDING", l2_severity="", location="Lobby", issue_description="Looks clean"),
        _row("5", asset_status="NEEDS_REVIEW", l2_status="NOT_RUN", l2_severity="", location=""),
        _row("6", asset_status="FAILED", l2_status="", l2_severity=""),
        _row("7", l2_status="INSUFFICIENT_EVIDENCE", l2_severity=""),
        _row("8", l2_status="", l2_severity="", issue_description=""),  # blank status
    ]


def _summary() -> dict[str, Any]:
    return rp.build_report_summary("run-1", "Alma / 2026-08 Regional", _rows(),
                                   generated_at="2026-10-07T00:00:00+00:00")


def _good_output() -> dict[str, Any]:
    return {
        "executive_summary": "The property is in fair condition. Gate security is the top concern.",
        "action_items": [
            {"refs": ["ref_1", "ref_3"], "location": "Unit 4B kitchen", "issue": "Leak under the sink",
             "action": "Have a plumber repair the supply line"},
            {"refs": ["ref_2"], "location": "Pool gate", "issue": "Gate propped open",
             "action": "Repair the closer"},
        ],
        "observations": [{"area": "common-interior", "text": "The lobby was clean.", "refs": ["ref_4"]}],
    }


# --- Invariant 6: no blank-means-something ----------------------------------


@pytest.mark.parametrize("overrides, bucket", [
    ({}, rp.BUCKET_ACTION),
    ({"l2_status": "NO_FINDING", "l2_severity": ""}, rp.BUCKET_NO_FINDING),
    ({"l2_status": "", "l2_severity": ""}, rp.BUCKET_REVIEW),
    ({"l2_status": "ENRICHED", "l2_severity": ""}, rp.BUCKET_REVIEW),
    ({"l2_status": "ENRICHED", "l2_severity": "7"}, rp.BUCKET_REVIEW),
    ({"l2_status": "INSUFFICIENT_EVIDENCE"}, rp.BUCKET_REVIEW),
    ({"l2_status": "ALREADY_TRACKED", "l2_severity": ""}, rp.BUCKET_TRACKED),
    ({"asset_status": "NEEDS_REVIEW"}, rp.BUCKET_REVIEW),
    ({"asset_status": "FAILED"}, rp.BUCKET_REVIEW),
    ({"asset_status": ""}, rp.BUCKET_REVIEW),
])
def test_no_blank_means_no_finding(overrides: dict[str, Any], bucket: str) -> None:
    assert rp.classify_row(_row("x", **overrides))[0] == bucket


# --- Invariant 2 + 5: every clip in exactly one place; counts from code ------


def test_every_clip_lands_in_exactly_one_bucket_and_counts_add_up() -> None:
    summary = _summary()
    counts = summary["counts"]
    buckets = [c["bucket"] for c in summary["clips"]]

    assert len(summary["clips"]) == counts["total"] == 8
    assert counts["action"] + counts["review"] + counts["no_finding"] == counts["total"], counts
    assert (buckets.count(rp.BUCKET_ACTION), buckets.count(rp.BUCKET_REVIEW),
            buckets.count(rp.BUCKET_NO_FINDING)) == (3, 4, 1), buckets


def test_the_model_never_sees_ids_links_or_filenames() -> None:
    payload = json.dumps(rp.build_model_input(_summary()))

    for forbidden in ("drive-id-", "https://", "IMG_", ".MOV"):
        assert forbidden not in payload, forbidden
    assert '"ref_1"' in payload


# --- Invariant 3 + 4: traceability and tiers ---------------------------------


def test_valid_output_is_accepted_and_tiers_come_from_severity() -> None:
    content = rp.validate_report_content(json.dumps(_good_output()), _summary())

    tiers = [(i["location"], i["tier"], i["severity"]) for i in content["action_items"]]
    assert tiers == [("Pool gate", "immediate", 1), ("Unit 4B kitchen", "priority", 2)], tiers
    assert content["backfilled_refs"] == []


@pytest.mark.parametrize("mutate, message", [
    (lambda o: o["action_items"][0]["refs"].append("ref_99"), "unknown clips"),
    (lambda o: o["action_items"][0]["refs"].append("ref_4"), "no actionable finding"),
    (lambda o: o["action_items"][1]["refs"].append("ref_1"), "already in another"),
    (lambda o: o["observations"][0]["refs"].append("ref_5"), "unknown or unassessed"),
    (lambda o: o["action_items"][0].update(refs=[]), "cites no clips"),
])
def test_untraceable_references_are_rejected(mutate: Any, message: str) -> None:
    output = _good_output()
    mutate(output)
    with pytest.raises(ValidationError, match=message):
        rp.validate_report_content(json.dumps(output), _summary())


def test_an_actionable_clip_the_model_omits_is_backfilled_not_dropped() -> None:
    output = _good_output()
    output["action_items"][0]["refs"] = ["ref_1"]  # ref_3 omitted

    content = rp.validate_report_content(json.dumps(output), _summary())

    assert content["backfilled_refs"] == ["ref_3"]
    cited = [c["ref"] for i in content["action_items"] for c in i["clips"]]
    assert sorted(cited) == ["ref_1", "ref_2", "ref_3"], cited


# --- Invariant 9: clean model text ------------------------------------------


@pytest.mark.parametrize("field, text, message", [
    ("executive_summary", "Five clips showed leaks.", "count"),
    ("executive_summary", "We reviewed 12 findings today.", "count"),
    ("executive_summary", "See IMG_8054.MOV for the leak.", "filename"),
    ("executive_summary", "The leak (ref_1) is bad.", "clip reference"),
    ("executive_summary", "Doc 1F1r7QwHvJbaSlTXdbALaM7L2x-bKB3y5 was used.", "identifier"),
    ("executive_summary", "   ", "empty"),
])
def test_counts_filenames_and_ids_in_model_text_are_rejected(field: str, text: str, message: str) -> None:
    output = _good_output()
    output[field] = text
    with pytest.raises(ValidationError, match=message):
        rp.validate_report_content(json.dumps(output), _summary())


def test_ordinary_quantities_are_not_mistaken_for_counts() -> None:
    output = _good_output()
    output["executive_summary"] = "Two laundry machines need replacement and three umbrellas are missing."
    rp.validate_report_content(json.dumps(output), _summary())


# --- Model retries and fallback --------------------------------------------


class _FakeModels:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls = 0

    def generate_content(self, **_kwargs: Any) -> Any:
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return SimpleNamespace(text=text, usage_metadata=None)


def _settings() -> Any:
    return SimpleNamespace(vertex_model="gemini-2.5-flash", run_id="run-1")


def test_a_bad_first_answer_is_retried_then_accepted() -> None:
    client = SimpleNamespace(models=_FakeModels(["not json", json.dumps(_good_output())]))
    prompt = rp.load_report_prompt(PROMPTS_DIR)

    content, _usage = rp.generate_report_content(client, _settings(), prompt, _summary())

    assert client.models.calls == 2
    assert "fallback_reason" not in content
    assert len(content["validation_errors"]) == 1


def test_repeated_bad_answers_fall_back_to_the_catalogue() -> None:
    client = SimpleNamespace(models=_FakeModels(["not json"]))
    prompt = rp.load_report_prompt(PROMPTS_DIR)

    content, _usage = rp.generate_report_content(client, _settings(), prompt, _summary())

    assert client.models.calls == rp.MODEL_ATTEMPTS
    assert content["fallback_reason"]
    assert sorted(c["ref"] for i in content["action_items"] for c in i["clips"]) == [
        "ref_1", "ref_2", "ref_3"]


# --- Rendering ---------------------------------------------------------------


def _apply_insert(requests: list[dict[str, Any]], start: int = 1) -> str:
    """The document text as it would read after the insert: index -> character."""
    return "\0" * start + requests[0]["insertText"]["text"]


def test_rendered_ranges_land_on_the_intended_text() -> None:
    summary = _summary()
    content = rp.validate_report_content(json.dumps(_good_output()), summary)
    requests = rp.build_report_requests(summary, content, "1.0.0", "gemini-2.5-flash", tab_id="t.1")
    doc = _apply_insert(requests)
    end = len(doc)

    links = {}
    for req in requests:
        for kind in ("updateTextStyle", "updateParagraphStyle", "createParagraphBullets",
                     "deleteParagraphBullets"):
            if kind in req:
                rng = req[kind]["range"]
                assert rng["tabId"] == "t.1"
                assert 1 <= rng["startIndex"] < rng["endIndex"] <= end, req
                url = req[kind].get("textStyle", {}).get("link", {}).get("url")
                if url:
                    links[doc[rng["startIndex"]:rng["endIndex"]]] = url
    assert links["IMG_1.MOV"] == "https://drive.google.com/file/d/1/view"
    assert links["IMG_4.MOV"] == "https://drive.google.com/file/d/4/view"  # no-finding list


def test_the_template_has_every_section_in_order() -> None:
    summary = _summary()
    content = rp.validate_report_content(json.dumps(_good_output()), summary)
    text = rp.build_report_requests(summary, content, "1.0.0", "m")[0]["insertText"]["text"]

    order = ["Alma — Site Visit Report", "At a glance", "Summary", "Action items",
             "Immediate — safety (severity 1)", "Priority (severity 2)", "Routine (severity 3–4)",
             "Observations by area", "Needs human review", "Run details"]
    lines = text.split(chr(10))
    positions = [lines.index(h) for h in order]
    assert positions == sorted(positions), list(zip(order, positions))
    assert "Walked by Pat Example" in text
    assert "Suggested owner: Maintenance" in text
    assert "Suggested timeframe: Within 48 hours" in text
    assert "Clips reviewed: 8" in text


def test_a_work_order_request_is_flagged_in_the_report() -> None:
    rows = _rows()
    rows[1]["work_order_requested"] = "YES"
    summary = rp.build_report_summary("run-1", "Alma", rows)
    content = rp.validate_report_content(json.dumps(_good_output()), summary)
    text = rp.build_report_requests(summary, content, "1.0.0", "m")[0]["insertText"]["text"]

    assert "Work order requested on site: 1 clip" in text
    assert "WORK ORDER REQUESTED  Pool gate" in text


def test_routine_items_are_grouped_by_area_and_none_are_lost() -> None:
    rows = [_row("1", l2_severity="3", l2_area_type="unit"),
            _row("2", l2_severity="4", l2_area_type="exterior", location="Siding"),
            _row("3", l2_severity="3", l2_area_type="rooftop", location="Roof")]  # unknown area
    summary = rp.build_report_summary("run-1", "Alma", rows)
    content = rp.fallback_content(summary, "test")
    lines = rp.build_report_requests(summary, content, "1.0.0", "m")[0]["insertText"]["text"].split(chr(10))

    routine = lines[lines.index("Routine (severity 3–4)"):lines.index("Needs human review")]
    assert [h for h in routine if h in ("Units", "Exterior", "General")] == ["Units", "Exterior", "General"]
    assert sum(1 for line in routine if line.startswith(("Unit 4B", "Siding", "Roof"))) == 3


def test_already_tracked_clips_are_listed_but_never_become_action_items() -> None:
    rows = _rows() + [_row("9", l2_status="ALREADY_TRACKED", l2_severity="", location="North Wing",
                           issue_description="stain")]
    summary = rp.build_report_summary("run-1", "Alma", rows)
    output = _good_output()
    output["action_items"][0]["refs"].append("ref_9")
    with pytest.raises(ValidationError, match="no actionable finding"):
        rp.validate_report_content(json.dumps(output), summary)

    content = rp.validate_report_content(json.dumps(_good_output()), summary)
    text = rp.build_report_requests(summary, content, "1.0.0", "m")[0]["insertText"]["text"]
    assert "Already tracked: 1 clip" in text
    assert "North Wing — stain IMG_9.MOV" in text
    assert summary["counts"]["action"] + summary["counts"]["review"] + summary["counts"]["no_finding"]         + summary["counts"]["tracked"] == summary["counts"]["total"]


def test_indices_count_utf16_units_not_characters() -> None:
    assert rp._u16("a—b") == 3
    assert rp._u16("😀") == 2


# --- Invariants 1, 7, 8: atomic write, replace-in-place, clear only when told ---


class _FakeDocs:
    def __init__(self, body_end: int, revision: str = "rev-1") -> None:
        self.doc = {"revisionId": revision, "tabs": [{"tabProperties": {"tabId": "t.1"},
                    "documentTab": {"body": {"content": [{"endIndex": 1}, {"endIndex": body_end}]}}}]}
        self.batches: list[dict[str, Any]] = []

    def documents(self) -> "_FakeDocs":
        return self

    def get(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(execute=lambda: self.doc)

    def batchUpdate(self, documentId: str, body: dict[str, Any]) -> Any:  # noqa: N802,N803
        self.batches.append(body)
        return SimpleNamespace(execute=lambda: {})


def _builder(start: int) -> list[dict[str, Any]]:
    return [{"insertText": {"location": {"index": start, "tabId": "t.1"}, "text": "Report\n"}}]


def test_replace_clears_and_writes_in_one_revision_guarded_batch() -> None:
    docs = _FakeDocs(body_end=500)

    result = write_report_requests(docs, "doc", "t.1", _builder, replace=True)

    assert len(docs.batches) == 1
    batch = docs.batches[0]
    assert batch["requests"][0] == {"deleteContentRange": {"range": {
        "startIndex": 1, "endIndex": 499, "tabId": "t.1"}}}
    assert "insertText" in batch["requests"][1]
    assert batch["writeControl"] == {"requiredRevisionId": "rev-1"}
    assert result["cleared_characters"] == 498


def test_rerun_leaves_exactly_one_report_in_the_tab() -> None:
    docs = _FakeDocs(body_end=500)
    write_report_requests(docs, "doc", "t.1", _builder, replace=True)
    docs.doc["tabs"][0]["documentTab"]["body"]["content"][-1]["endIndex"] = 9  # after first write
    write_report_requests(docs, "doc", "t.1", _builder, replace=True)

    second = docs.batches[1]["requests"]
    assert second[0]["deleteContentRange"]["range"]["endIndex"] == 8
    assert sum("insertText" in r for r in second) == 1


def test_without_replace_nothing_is_deleted() -> None:
    docs = _FakeDocs(body_end=500)
    write_report_requests(docs, "doc", "t.1", _builder, replace=False)
    assert not any("deleteContentRange" in r for r in docs.batches[0]["requests"])


def test_an_empty_tab_is_not_cleared() -> None:
    docs = _FakeDocs(body_end=2)
    write_report_requests(docs, "doc", "t.1", _builder, replace=True)
    assert not any("deleteContentRange" in r for r in docs.batches[0]["requests"])


def test_an_empty_report_is_never_written_and_nothing_is_cleared() -> None:
    docs = _FakeDocs(body_end=500)
    with pytest.raises(ValidationError, match="empty report"):
        write_report_requests(docs, "doc", "t.1", lambda s: [{"insertText": {"text": " "}}], replace=True)
    assert docs.batches == []


def test_an_unknown_tab_is_refused_before_any_write() -> None:
    docs = _FakeDocs(body_end=500)
    with pytest.raises(ValidationError, match="not found"):
        write_report_requests(docs, "doc", "t.9", _builder, replace=True)
    assert docs.batches == []


# --- Prompt contract -----------------------------------------------------------


def test_the_report_prompt_is_read_from_disk_at_runtime() -> None:
    prompt = rp.load_report_prompt(PROMPTS_DIR)

    assert prompt.version == "1.0.0"
    assert "ref" in prompt.instruction_text
    assert "Never state a number" in prompt.instruction_text
    assert len(prompt.sha256) == 64


def test_a_missing_report_prompt_is_a_clear_runtime_stop(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="missing at runtime"):
        rp.load_report_prompt(tmp_path)


def test_a_prompt_file_without_a_version_is_rejected(tmp_path: Path) -> None:
    (tmp_path / rp.REPORT_PROMPT_FILE).write_text(
        "# Report\n\n## Exact prompt text\n\n```text\nWrite it.\n```\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="Semantic version"):
        rp.load_report_prompt(tmp_path)
