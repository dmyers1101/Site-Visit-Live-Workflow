"""Portfolio walk, path splitting, uploader resolution, and coverage - no Google calls."""

from __future__ import annotations

from site_visit_workflow.portfolio import (
    FOLDER_MIME,
    PortfolioClip,
    inventory_summary,
    resolve_uploader,
    split_path,
    walk_portfolio,
)

SA = "site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com"


def _folder(fid: str, name: str) -> dict:
    return {"id": fid, "name": name, "mimeType": FOLDER_MIME}


def _video(fid: str, name: str, email: str = "walker@shircapital.com") -> dict:
    return {
        "id": fid, "name": name, "mimeType": "video/quicktime",
        "createdTime": "2026-09-01T00:00:00Z",
        "lastModifyingUser": {"emailAddress": email, "displayName": "Walker"},
    }


TREE = {
    "root": [_folder("tx", "TX"), _folder("pa", "PA")],
    "tx": [_folder("alma", "Alma")],
    "alma": [_folder("v1", "2026-08 Executive - Parth Vaidya")],
    "v1": [_video("c2", "IMG_2.MOV"), _video("c1", "IMG_1.MOV"),
           {"id": "h", "name": "x.heic", "mimeType": "image/heif"}],
    "pa": [_folder("legacy", "Legacy"), _folder("venue", "Venue")],
    "legacy": [_folder("oak", "Oakland")],
    "oak": [_folder("v2", "2026-09 Regional - Tony Corsa")],
    "v2": [_video("c3", "IMG_3.MOV")],
    "venue": [_folder("empty", "2026-08 Executive - Laura Beynon")],
    "empty": [],
}


def test_every_folder_with_videos_is_a_visit_at_any_depth() -> None:
    visits = walk_portfolio("root", lambda fid: TREE[fid])

    assert [v.drive_id for v in visits] == ["v2", "v1"]
    oak = visits[0]
    assert (oak.state, oak.property_name, oak.group) == ("PA", "Legacy", "Oakland")
    alma = visits[1]
    assert (alma.state, alma.property_name, alma.group) == ("TX", "Alma", None)
    assert [c.name for c in alma.clips] == ["IMG_1.MOV", "IMG_2.MOV"]
    assert alma.other_children == 1


def test_split_path_for_a_standard_visit() -> None:
    assert split_path(("TX", "Alma", "2026-08 x")) == ("TX", "Alma", None)


def test_the_service_account_is_never_the_uploader() -> None:
    clip = PortfolioClip("c", "n", "video/quicktime", None, SA, "SA")

    assert resolve_uploader(clip, SA) == (None, None)
    assert resolve_uploader(clip, SA, {"emailAddress": "a@shircapital.com", "displayName": "A"}) == (
        "a@shircapital.com", "A",
    )


def test_a_human_last_modifier_is_the_uploader() -> None:
    clip = PortfolioClip("c", "n", "video/quicktime", None, "a@shircapital.com", "A")

    assert resolve_uploader(clip, SA) == ("a@shircapital.com", "A")


def test_inventory_counts_pending_against_catalogued_ids() -> None:
    visits = walk_portfolio("root", lambda fid: TREE[fid])

    summary = inventory_summary(visits, {"c1"})

    assert (summary["visit_count"], summary["clip_count"], summary["pending_count"]) == (2, 3, 2)
    assert summary["properties"] == ["Alma", "Legacy"]


# --- incremental selection, naming, catalog columns -------------------------

from site_visit_workflow.catalog import FULL_CATALOG_HEADERS, PORTFOLIO_COLUMNS  # noqa: E402
from site_visit_workflow.portfolio import (  # noqa: E402
    renamed_names,
    row_extras,
    select_pending,
    tab_title,
)


def _alma():
    return walk_portfolio("root", lambda fid: TREE[fid])[1]


def test_catalogued_and_needs_review_are_skipped_failed_is_retried() -> None:
    records = {
        "c1": {"asset_status": "CATALOGUED"},
        "c2": {"asset_status": "FAILED", "attempt_count": "1"},
    }

    skip, attempts = select_pending(_alma(), records)

    assert skip == {"c1"}
    assert attempts == {"c2": 2}


def test_a_clip_failed_three_times_stops_being_retried() -> None:
    skip, _ = select_pending(_alma(), {"c2": {"asset_status": "FAILED", "attempt_count": "3"}})

    assert "c2" in skip


def test_row_extras_carry_the_path_and_uploader() -> None:
    extras = row_extras(_alma(), {"c1": ("w@shircapital.com", "Walker")}, {"c1": 1})

    assert extras["c1"]["property"] == "Alma"
    assert extras["c1"]["uploader_name"] == "Walker"
    assert extras["c2"]["uploader_email"] is None
    assert set(extras["c1"]) == set(PORTFOLIO_COLUMNS)


def test_portfolio_columns_are_appended_not_inserted() -> None:
    assert FULL_CATALOG_HEADERS[:34][-1] == "updated_at"
    assert FULL_CATALOG_HEADERS[34:] == PORTFOLIO_COLUMNS


def test_tab_title_uses_latest_date_and_most_frequent_uploader() -> None:
    rows = [
        {"uploaded_at": "2026-09-01T10:00:00Z", "uploader_name": "Parth Vaidya"},
        {"uploaded_at": "2026-09-03T10:00:00Z", "uploader_name": "Parth Vaidya"},
        {"uploaded_at": "2026-09-02T10:00:00Z", "uploader_name": "Other"},
    ]

    assert tab_title(rows) == "2026-09-03 · Parth Vaidya"
    assert tab_title([{}]) == "undated · Unknown uploader"


def test_renamed_names_reads_the_rename_decision_column() -> None:
    rows = [{"row_key": "a", "drive_rename_decision": "RENAMED_TO:roof.MOV"},
            {"row_key": "b", "drive_rename_decision": "SKIPPED_ASSET_NOT_ELIGIBLE"}]

    assert renamed_names(rows) == {"a": "roof.MOV"}


def test_report_is_due_self_heals_after_a_failed_report() -> None:
    from site_visit_workflow.portfolio import report_is_due

    rows = [{"updated_at": "2026-09-29T18:00:00+00:00"}]
    assert report_is_due(rows, None, 0) is True
    assert report_is_due(rows, {"updated_at": "2026-09-29T17:00:00+00:00"}, 0) is True
    assert report_is_due(rows, {"updated_at": "2026-09-29T19:00:00+00:00"}, 0) is False
    assert report_is_due([], None, 5) is False


def test_generate_with_backoff_retries_quota_then_succeeds() -> None:
    from site_visit_workflow.extraction import generate_with_backoff

    calls = []

    class Models:
        def generate_content(self, **kw):
            calls.append(kw)
            if len(calls) < 3:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return "ok"

    class Client:
        models = Models()

    waits = []
    assert generate_with_backoff(Client(), sleep=waits.append, model="m") == "ok"
    assert waits == [10.0, 20.0]
