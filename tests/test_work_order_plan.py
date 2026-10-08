"""Invariants for AppFolio work-order planning (ADR 0015). One test per rule."""

from datetime import datetime, timezone

import pytest

from site_visit_workflow import work_order_plan as wp
from site_visit_workflow.appfolio import AppFolioClient, AmbiguousWriteError, check_idempotency_key, load_credentials
from site_visit_workflow.errors import ValidationError

PID = "8eb28538-c8f5-41e7-ac82-3f9609cceec9"


def clip(asset, sev="2", req="YES", visit="v1", prop="Alta", **kw):
    return {"source_asset_identifier": asset, "asset_status": "CATALOGUED", "visit_drive_id": visit,
            "property": prop, "visit_name": "2026-10 Alta", "uploader_email": "w@x.com",
            "drive_link": f"https://drive/{asset}", "location": f"Unit {asset}",
            "issue_description": f"paint {asset}", "l2_severity": sev, "l2_status": "ENRICHED",
            "l2_recommended_action": "touch up", "work_order_requested": req, **kw}


def approved(row, decision="CREATE_ONE"):
    return {**row, "status": wp.APPROVED, "decision": decision, "decided_at": "2026-10-08T12:00:00Z"}


def test_priority_mapping():
    assert [wp.priority_for(s) for s in ("1", "2", "3", "4")] == ["Urgent", "Normal", "Low", "Low"]


def test_blank_severity_is_not_a_priority():
    assert wp.priority_for("") is None and wp.priority_for(None) is None and wp.priority_for("x") is None


def test_blank_work_order_flag_is_never_a_candidate():
    rows = [clip("a", sev="3", req=""), clip("b", sev="3", req="NO")]
    assert wp.select_candidates(rows) == []


def test_severity_1_2_unflagged_become_suggested():
    got = wp.select_candidates([clip("a", sev="1", req="NO"), clip("b", sev="", req="")])
    assert [c["_kind"] for c in got] == [wp.KIND_SUGGESTED]


def test_already_tracked_is_not_suggested():
    assert wp.select_candidates([clip("a", sev="1", req="NO", l2_status="ALREADY_TRACKED")]) == []


def test_grouping_must_partition_exactly():
    ids = ["a", "b", "c"]
    assert wp.validate_grouping(ids, {"groups": [{"label": "Paint", "clip_ids": ["a", "b", "c"]}]})
    assert wp.validate_grouping(ids, {"groups": [{"label": "Paint", "clip_ids": ["a", "b"]}]}) is None
    assert wp.validate_grouping(ids, {"groups": [{"label": "P", "clip_ids": ["a", "b", "c", "a"]}]}) is None
    assert wp.validate_grouping(ids, {"groups": [{"label": "P", "clip_ids": ["a", "b", "c", "z"]}]}) is None
    assert wp.validate_grouping(ids, "garbage") is None


def test_group_cannot_span_visits():
    clips = wp.select_candidates([clip("a"), clip("b", visit="v2")])
    with pytest.raises(ValueError):
        wp.new_ledger_rows(clips, [{"label": "x", "clip_ids": ["a", "b"]}], set(), "now")


def test_ledger_rows_idempotent_on_rerun():
    clips = wp.select_candidates([clip("a"), clip("b", sev="1")])
    groups = [{"label": "Paint", "clip_ids": ["b", "a"]}]
    first = wp.new_ledger_rows(clips, groups, set(), "now")
    assert len(first) == 1 and first[0]["severity"] == "1" and first[0]["priority"] == "Urgent"
    assert wp.new_ledger_rows(clips, groups, {first[0]["wo_key"]}, "now") == []


def _ledger(decision="CREATE_ONE", **kw):
    clips = wp.select_candidates([clip("a"), clip("b", sev="3")])
    row = wp.new_ledger_rows(clips, [{"label": "Paint", "clip_ids": ["a", "b"]}], set(), "now")[0]
    return [approved({**row, **kw}, decision)]


def test_unmapped_property_is_blocked_not_guessed():
    plan = wp.plan_creates(_ledger(), {})
    assert plan.creates == [] and plan.blocked[0][1] == wp.BLOCKED_NO_MAPPING


def test_mapping_requires_review_and_uuid():
    m = wp.load_mapping([{"catalog_property": "Alta", "appfolio_property_id": PID, "reviewed": ""},
                         {"catalog_property": "Teak", "appfolio_property_id": "123", "reviewed": "YES"}])
    assert m == {}


B1 = "25d186bc-913e-11e8-a048-b083fede658c"
B2 = "25d189a3-913e-11e8-a048-b083fede658c"
LEGACY = {"Legacy": [("2730 Broadway", B1), ("2910 Voelkel", B2), ("1511-1519 Bingham", PID)]}


def test_legacy_maps_by_heard_address():
    assert wp.resolve_property({"property": "Legacy", "location": "2730 Broadway, hallway"}, LEGACY) == (B1, "address")
    assert wp.resolve_property({"property": "Legacy", "location": "1519 Bingham St rear"}, LEGACY)[0] == PID


def test_legacy_no_or_two_addresses_blocked():
    assert wp.resolve_property({"property": "Legacy", "location": "basement"}, LEGACY)[0] is None
    assert wp.resolve_property({"property": "Legacy", "location": "2730 Broadway and 2910 Voelkel"}, LEGACY)[0] is None
    assert wp.resolve_property({"property": "Legacy", "location": "2731 Broadway"}, LEGACY)[0] is None


def test_split_creates_one_per_clip_with_distinct_keys():
    plan = wp.plan_creates(_ledger("SPLIT"), {"Alta": [("", PID)]})
    assert len(plan.creates) == 2
    assert len({c.idempotency_key for c in plan.creates}) == 2
    assert wp.check_plan_invariants(plan, _ledger("SPLIT"), max_creates=5) == []


def test_clean_plan_passes_all_invariants():
    ledger = _ledger()
    plan = wp.plan_creates(ledger, {"Alta": [("", PID)]})
    assert len(plan.creates) == 1
    body = plan.creates[0].body
    assert body["Priority"] == "Normal" and body["PropertyId"] == PID and body["Status"] == "New"
    assert wp.check_plan_invariants(plan, ledger, max_creates=1) == []


def test_no_recreate_when_id_present():
    ledger = _ledger(appfolio_work_order_ids="abc")
    assert wp.plan_creates(ledger, {"Alta": [("", PID)]}).creates == []


def test_invariant_flags_unapproved_and_cap():
    ledger = _ledger()
    plan = wp.plan_creates(ledger, {"Alta": [("", PID)]})
    ledger[0]["decided_at"] = ""
    problems = wp.check_plan_invariants(plan, ledger, max_creates=0)
    assert any(p.startswith("human_approved") for p in problems)
    assert any(p.startswith("max_creates") for p in problems)


def test_invariant_flags_array_and_bad_priority():
    ledger = _ledger()
    plan = wp.plan_creates(ledger, {"Alta": [("", PID)]})
    plan.creates[0].body["AssignedUsers"] = []
    plan.creates[0].body["Priority"] = "High"
    problems = wp.check_plan_invariants(plan, ledger, max_creates=1)
    assert any(p.startswith("no_array_fields") for p in problems)
    assert any(p.startswith("priority_enum") for p in problems)


def test_duplicate_ledger_keys_flagged():
    ledger = _ledger() * 2
    assert any(p.startswith("ledger_keys_unique") for p in wp.check_plan_invariants(wp.Plan(), ledger, 1))


def test_marker_and_existing_match():
    ledger = _ledger()
    c = wp.plan_creates(ledger, {"Alta": [("", PID)]}).creates[0]
    found = wp.find_by_marker([{"Id": "x", "JobDescription": c.body["JobDescription"]}], c.marker)
    assert found["Id"] == "x"
    wos = [{"Id": PID, "Link": "https://shir.appfolio.com/work_orders/123", "WorkOrderNumber": "4521-1"}]
    assert wp.match_existing(wos, "https://shir.appfolio.com/work_orders/123")
    assert wp.match_existing(wos, "4521-1")
    assert wp.match_existing(wos, PID)
    assert wp.match_existing(wos, "12") is None


def test_write_window_pacific():
    assert not wp.in_write_window(datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc))   # 00:00 PT
    assert wp.in_write_window(datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc))      # 05:00 PT


def test_credentials_env_only():
    with pytest.raises(ValidationError):
        load_credentials({})
    with pytest.raises(ValidationError):
        check_idempotency_key("é")


class _Resp:
    def __init__(self, code, body="", headers=None):
        self.status_code, self.text, self.headers = code, body, headers or {}

    def json(self):
        import json
        return json.loads(self.text)


class _Session:
    def __init__(self, responses):
        self.headers, self.responses, self.calls = {}, list(responses), []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


CREDS = {"AF_V0_CLIENT_ID": "id", "AF_V0_CLIENT_SECRET": "sec", "AF_V0_DEVELOPER_ID": "dev"}


def test_post_sends_idempotency_key_and_reads_replay():
    s = _Session([_Resp(201, '{"Id": "w1", "Link": "L"}', {"Idempotent-Replayed": "true"})])
    out = AppFolioClient(CREDS, session=s, sleep=lambda _: None).create_work_order({"x": 1}, "sv-k")
    assert out == {"Id": "w1", "Link": "L", "replayed": True}
    assert s.calls[0][2]["headers"]["Idempotency-Key"] == "sv-k"


def test_write_transport_failure_is_ambiguous_not_retried():
    s = _Session([ConnectionError("boom")])
    with pytest.raises(AmbiguousWriteError):
        AppFolioClient(CREDS, session=s, sleep=lambda _: None).create_work_order({}, "k")
    assert len(s.calls) == 1


def test_get_requires_filter():
    with pytest.raises(ValidationError):
        list(AppFolioClient(CREDS, session=_Session([]), sleep=lambda _: None).get("/work_orders", {}))
