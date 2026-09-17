"""Flattening BatchRecognize output and the empty-transcript stop. No API calls."""

import pytest

from site_visit_workflow.google import transcript_text_from_batch_result
from site_visit_workflow.models import EmptyTranscriptDecision, evaluate_transcript


def batch_result(*transcripts: str) -> dict:
    return {
        "results": [
            {"alternatives": [{"transcript": text, "confidence": 0.9}]} for text in transcripts
        ]
    }


def test_alternatives_are_joined_in_order() -> None:
    payload = batch_result("Kitchen sink is leaking.", "Under the trap.")

    assert transcript_text_from_batch_result(payload) == "Kitchen sink is leaking. Under the trap."


def test_only_the_top_alternative_of_each_result_is_used() -> None:
    payload = {
        "results": [
            {"alternatives": [{"transcript": "first"}, {"transcript": "second-guess"}]},
        ]
    }

    assert transcript_text_from_batch_result(payload) == "first"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": []},
        {"results": None},
        {"results": [{}]},
        {"results": [{"alternatives": []}]},
        {"results": [{"alternatives": [{"transcript": "   "}]}]},
        {"results": [{"alternatives": [{}]}]},
    ],
)
def test_a_silent_clip_yields_an_empty_string_never_invented_text(payload: dict) -> None:
    assert transcript_text_from_batch_result(payload) == ""


def test_empty_transcript_is_retried_once_then_becomes_needs_review() -> None:
    assert evaluate_transcript("", 0) is EmptyTranscriptDecision.RETRY_ONCE
    assert evaluate_transcript("", 1) is EmptyTranscriptDecision.NEEDS_REVIEW
    assert evaluate_transcript("audible narration", 1) is EmptyTranscriptDecision.COMPLETE
