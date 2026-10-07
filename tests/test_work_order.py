"""Work-order flag (ADR 0014): deterministic transcript phrase match, header extension."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from site_visit_workflow import google as g
from site_visit_workflow.errors import ValidationError
from site_visit_workflow.work_order import detect_work_order_request


@pytest.mark.parametrize("text, phrase", [
    ("Okay create work order for this sink.", "create work order"),
    ("We need a work order on the gate.", "need a work order"),
    ("This needs a work-order right away", "needs a work-order"),
    ("Create a workorder please", "create a workorder"),
    ("NEED WORK ORDER for unit 2307", "need work order"),
    ("needed another work order here", "needed another work order"),
])
def test_request_phrases_are_flagged(text: str, phrase: str) -> None:
    result = detect_work_order_request(text)
    assert result == {"work_order_requested": "YES", "work_order_phrase": phrase}, result


@pytest.mark.parametrize("text", [
    "The sink is leaking under the cabinet.",
    "We already have a work order open for that.",
    "Work order number 12 was closed.",
])
def test_other_speech_is_not_flagged(text: str) -> None:
    assert detect_work_order_request(text)["work_order_requested"] == "NO"


@pytest.mark.parametrize("text", [None, "", "   "])
def test_no_transcript_means_not_checked_not_no(text: Any) -> None:
    assert detect_work_order_request(text) == {"work_order_requested": "", "work_order_phrase": ""}


def test_repeated_phrases_are_recorded_once() -> None:
    result = detect_work_order_request("Need a work order. Yes, need a work order.")
    assert result["work_order_phrase"] == "need a work order"


class _FakeSheets:
    def __init__(self, header: list[str]) -> None:
        self.header = header
        self.updates: list[dict[str, Any]] = []

    def spreadsheets(self) -> "_FakeSheets":
        return self

    def values(self) -> "_FakeSheets":
        return self

    def get(self, **_kw: Any) -> Any:
        return SimpleNamespace(execute=lambda num_retries=0: {"values": [self.header]})

    def update(self, **kw: Any) -> Any:
        self.updates.append(kw)
        return SimpleNamespace(execute=lambda: {})


def test_missing_header_cells_are_appended_to_the_right_only() -> None:
    g._HEADERS_CHECKED.clear()
    sheets = _FakeSheets(["row_key", "a"])
    g._extend_header_once(sheets, "s", "Catalog", ("row_key", "a", "work_order_requested", "work_order_phrase"))
    assert sheets.updates == [{"spreadsheetId": "s", "range": "Catalog!C1:D1", "valueInputOption": "RAW",
                               "body": {"values": [["work_order_requested", "work_order_phrase"]]}}]


def test_a_header_that_is_not_a_prefix_is_never_rewritten() -> None:
    g._HEADERS_CHECKED.clear()
    sheets = _FakeSheets(["row_key", "other"])
    with pytest.raises(ValidationError, match="not a prefix"):
        g._extend_header_once(sheets, "s", "Catalog", ("row_key", "a", "b"))
    assert sheets.updates == []
