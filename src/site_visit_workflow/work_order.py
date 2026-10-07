"""Work-order request flag, read from the transcript (2026-10-07, ADR 0014).

Deterministic: a phrase match on the Chirp transcript, no model call. The
walker saying "create work order" / "need a work order" marks the clip so the
catalog and the report can surface it.

Values written to the catalog (`work_order_requested`):
- "YES" - a request phrase was found; `work_order_phrase` holds the words heard.
- "NO"  - a transcript existed and contained no request phrase.
- ""    - no transcript, so the check did not run. Blank never means "no".

How to update this later
------------------------
Add a variant to `_REQUEST` and a test in `tests/test_work_order.py`. Chirp
may write "workorder" or "work-order"; both are already accepted.
"""

from __future__ import annotations

import re
from typing import Any

WORK_ORDER_YES = "YES"
WORK_ORDER_NO = "NO"

_REQUEST = re.compile(
    r"\b(create|creating|created|need|needs|needed|needing)\s+"
    r"(?:(?:a|an|the|another|one)\s+)?work[\s-]?orders?\b",
    re.IGNORECASE,
)


def detect_work_order_request(transcript: str | None) -> dict[str, Any]:
    """{"work_order_requested": YES|NO|"", "work_order_phrase": str}."""
    if transcript is None or not transcript.strip():
        return {"work_order_requested": "", "work_order_phrase": ""}
    phrases = [m.group(0) for m in _REQUEST.finditer(transcript)]
    if not phrases:
        return {"work_order_requested": WORK_ORDER_NO, "work_order_phrase": ""}
    return {"work_order_requested": WORK_ORDER_YES,
            "work_order_phrase": "; ".join(dict.fromkeys(p.lower() for p in phrases))}
