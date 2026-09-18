"""Gate 7 summary building and prompt loading, with no Google API calls.

The Vertex call and the Docs write are not exercised here - they are boundaries
this suite deliberately never crosses. What is tested is everything that
decides WHAT would be sent: the counts, the finding list, the honesty rules for
unassessed assets, and the runtime prompt-file contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from site_visit_workflow.errors import ValidationError
from site_visit_workflow.report import (
    REPORT_PROMPT_FILE,
    build_report_summary,
    compose_document_text,
    load_report_prompt,
    validate_report_text,
)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "row_key": "id-1",
        "original_drive_name": "IMG_0001.MOV",
        "location": "Unit 4B kitchen",
        "issue_description": "Leak under the sink",
        "asset_status": "CATALOGUED",
        "l2_trade": "plumbing",
        "l2_severity": 2,
        "l2_recommended_action": "Schedule a plumber",
    }
    row.update(overrides)
    return row


def test_the_summary_counts_every_status_including_the_unassessed() -> None:
    rows = [
        _row(),
        _row(row_key="id-2", asset_status="NEEDS_REVIEW", l2_trade="", l2_severity="",
             l2_recommended_action="", location="", issue_description=""),
        _row(row_key="id-3", asset_status="FAILED", l2_trade="", l2_severity=""),
    ]

    summary = build_report_summary("run-1", "Teak visit", rows)

    assert summary["counts"] == {
        "total": 3,
        "catalogued": 1,
        "needs_review": 1,
        "failed": 1,
        "other": 0,
    }
    # An unassessed clip is still listed. Dropping it silently is the failure
    # mode the report exists to avoid.
    assert len(summary["findings"]) == 3


def test_blank_catalog_cells_become_nulls_rather_than_empty_strings() -> None:
    rows = [_row(row_key="id-2", asset_status="NEEDS_REVIEW", l2_trade="", l2_severity="",
                 location="", issue_description="", l2_recommended_action="")]

    finding = build_report_summary("run-1", "Teak visit", rows)["findings"][0]

    assert finding["location"] is None
    assert finding["issue_description"] is None
    assert finding["trade"] is None
    assert finding["severity"] is None
    assert finding["recommended_action"] is None
    assert finding["status"] == "NEEDS_REVIEW"


def test_counts_by_trade_and_severity_are_grouped() -> None:
    rows = [
        _row(),
        _row(row_key="id-2", l2_trade="plumbing", l2_severity=1),
        _row(row_key="id-3", l2_trade="electrical", l2_severity=3),
    ]

    summary = build_report_summary("run-1", "Teak visit", rows)

    assert summary["by_trade"] == {"electrical": 1, "plumbing": 2}
    assert summary["by_severity"] == {"1": 1, "2": 1, "3": 1}


def test_only_an_actually_renamed_asset_carries_a_new_name() -> None:
    rows = [_row(), _row(row_key="id-2")]

    summary = build_report_summary(
        "run-1", "Teak visit", rows, new_names={"id-1": "kitchen_leak.MOV", "id-2": None}
    )

    by_key = {finding["original_drive_name"]: finding for finding in summary["findings"]}
    assert summary["findings"][0]["new_drive_name"] == "kitchen_leak.MOV"
    assert summary["findings"][1]["new_drive_name"] is None
    assert by_key["IMG_0001.MOV"]["status"] == "CATALOGUED"


def test_an_empty_run_still_produces_a_valid_summary() -> None:
    summary = build_report_summary("run-1", "Teak visit", [])

    assert summary["counts"]["total"] == 0
    assert summary["findings"] == []
    assert summary["run_id"] == "run-1"


def test_the_report_prompt_is_read_from_disk_at_runtime() -> None:
    prompt = load_report_prompt(PROMPTS_DIR)

    assert prompt.version
    assert prompt.instruction_text.strip()
    assert len(prompt.sha256) == 64
    assert prompt.path.endswith(REPORT_PROMPT_FILE)


def test_a_missing_report_prompt_is_a_clear_runtime_stop(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="missing at runtime"):
        load_report_prompt(tmp_path)


def test_a_prompt_file_without_a_version_is_rejected(tmp_path: Path) -> None:
    (tmp_path / REPORT_PROMPT_FILE).write_text(
        "# Report\n\n## Exact prompt text\n\n```text\nWrite it.\n```\n", encoding="utf-8"
    )

    with pytest.raises(ValidationError, match="Semantic version"):
        load_report_prompt(tmp_path)


@pytest.mark.parametrize("text", ["", "   ", "```text\nreport\n```"])
def test_an_empty_or_fenced_report_is_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        validate_report_text(text)


def test_the_document_block_carries_the_title_run_id_and_date() -> None:
    body = compose_document_text("run-1", "Teak visit", "2026-09-18T00:00:00+00:00", "Narrative.")

    assert body.startswith("Site visit report - Teak visit\n")
    assert "Run ID: run-1" in body
    assert "Generated: 2026-09-18T00:00:00+00:00" in body
    assert body.rstrip().endswith("Narrative.")
