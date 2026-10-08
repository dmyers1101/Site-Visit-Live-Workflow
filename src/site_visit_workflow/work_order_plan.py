"""Pure work-order planning and invariants (ADR 0015). No network, no Google, no AppFolio.

Flow, one ledger row per proposed work order (`WorkOrders` tab, key `wo_key`):

    catalog rows --select_candidates--> clips
    clips --(Gemini proposal, validated by validate_grouping)--> groups
    groups --new_ledger_rows--> PENDING_REVIEW rows        (wo-candidates)
    Apps Script form: walker decides -> CREATE_ONE | SPLIT | EXISTS | SKIP
    APPROVED rows --plan_creates--> planned POSTs            (wo-run)
    check_plan_invariants(plan) -> any violation = nothing is sent

Ledger statuses: PENDING_REVIEW -> APPROVED | DECLINED | EXISTS_PENDING
-> CREATED | EXISTS_VERIFIED | EXISTS_UNVERIFIED | BLOCKED_NO_MAPPING | FAILED.
Rows are never deleted. An existing row's identity columns are never rewritten.

How to update this later
------------------------
Adding a ledger column means appending to LEDGER_HEADERS (never inserting) and
to the Apps Script `HEADERS` check. A new invariant gets a test named after it in
tests/test_work_order_plan.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .work_order import WORK_ORDER_YES

LEDGER_TAB = "WorkOrders"
MAPPING_TAB = "AppFolioPropertyMap"
MAPPING_HEADERS = ("catalog_property", "appfolio_property_id", "appfolio_property_name", "reviewed")

LEDGER_HEADERS: tuple[str, ...] = (
    "wo_key", "visit_drive_id", "state", "property", "visit_name", "uploader_email",
    "kind", "group_label", "clip_asset_ids", "clip_links", "location", "issue_summary",
    "recommended_action", "severity", "priority",
    "form_id", "form_url", "form_item_id", "form_sent_at", "reminder_sent_at", "escalated_at",
    "decision", "existing_ref", "decided_by", "decided_at",
    "status", "appfolio_property_id", "idempotency_keys", "appfolio_work_order_ids",
    "appfolio_links", "last_error", "created_at", "updated_at",
)

KIND_REQUESTED = "REQUESTED"   # walker said "create/need a work order"
KIND_SUGGESTED = "SUGGESTED"   # severity 1-2, not requested; unticked on the form

PENDING = "PENDING_REVIEW"
APPROVED = "APPROVED"
DECLINED = "DECLINED"
EXISTS_PENDING = "EXISTS_PENDING"
CREATED = "CREATED"
EXISTS_VERIFIED = "EXISTS_VERIFIED"
EXISTS_UNVERIFIED = "EXISTS_UNVERIFIED"
BLOCKED_NO_MAPPING = "BLOCKED_NO_MAPPING"
FAILED = "FAILED"

DECISIONS = ("CREATE_ONE", "SPLIT", "EXISTS", "SKIP")
PRIORITY_ENUM = ("Urgent", "Normal", "Low")
MARKER_PREFIX = "[SV-WO "
JOB_DESCRIPTION_MAX = 2000
SEP = "; "
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
PACIFIC = ZoneInfo("America/Los_Angeles")


def priority_for(severity: Any) -> str | None:
    """Severity 1 Urgent, 2 Normal, 3-4 Low (confirmed 2026-10-08). Blank/invalid -> None (omit)."""
    try:
        value = int(str(severity).strip())
    except (TypeError, ValueError):
        return None
    return {1: "Urgent", 2: "Normal", 3: "Low", 4: "Low"}.get(value)


def _severity(row: dict[str, Any]) -> int | None:
    try:
        return int(str(row.get("l2_severity", "")).strip())
    except ValueError:
        return None


def select_candidates(catalog_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clips that belong on a form. Blank `work_order_requested` is never NO and never YES."""
    out = []
    for row in catalog_rows:
        if row.get("asset_status") != "CATALOGUED" or not row.get("visit_drive_id"):
            continue
        requested = row.get("work_order_requested") == WORK_ORDER_YES
        sev = _severity(row)
        suggested = (not requested and sev in (1, 2)
                     and row.get("l2_status") not in ("ALREADY_TRACKED", "NO_FINDING"))
        if requested or suggested:
            out.append({**row, "_kind": KIND_REQUESTED if requested else KIND_SUGGESTED})
    return out


def validate_grouping(clip_ids: list[str], proposal: Any) -> list[dict[str, Any]] | None:
    """A model proposal is accepted only if it partitions `clip_ids` exactly. Else None."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get("groups"), list):
        return None
    seen: list[str] = []
    groups = []
    for group in proposal["groups"]:
        ids = group.get("clip_ids") if isinstance(group, dict) else None
        label = (group.get("label") or "").strip() if isinstance(group, dict) else ""
        if not isinstance(ids, list) or not ids or not label:
            return None
        seen.extend(ids)
        groups.append({"label": label[:120], "clip_ids": list(ids)})
    if sorted(seen) != sorted(clip_ids) or len(seen) != len(set(seen)):
        return None
    return groups


def singleton_groups(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"label": (c.get("issue_description") or c.get("location") or "Item")[:120],
             "clip_ids": [c["source_asset_identifier"]]} for c in clips]


def wo_key(visit_id: str, clip_ids: list[str]) -> str:
    """Deterministic: the same clips in the same visit always produce the same key."""
    return f"wo_{visit_id}_{sorted(clip_ids)[0]}" + (f"_g{len(clip_ids)}" if len(clip_ids) > 1 else "")


def new_ledger_rows(clips: list[dict[str, Any]], groups: list[dict[str, Any]],
                    existing_keys: set[str], now: str) -> list[dict[str, Any]]:
    """PENDING rows for groups not already in the ledger. Existing rows are never rewritten."""
    by_id = {c["source_asset_identifier"]: c for c in clips}
    rows = []
    for group in groups:
        members = [by_id[i] for i in group["clip_ids"]]
        visits = {m["visit_drive_id"] for m in members}
        props = {m.get("property", "") for m in members}
        if len(visits) != 1 or len(props) != 1:
            raise ValueError(f"group {group['label']!r} spans visits/properties: {visits} {props}")
        key = wo_key(visits.pop(), group["clip_ids"])
        if key in existing_keys:
            continue
        sevs = [s for s in (_severity(m) for m in members) if s is not None]
        sev = min(sevs) if sevs else ""
        first = members[0]
        rows.append({h: "" for h in LEDGER_HEADERS} | {
            "wo_key": key, "visit_drive_id": first["visit_drive_id"], "state": first.get("state", ""),
            "property": first.get("property", ""), "visit_name": first.get("visit_name", ""),
            "uploader_email": first.get("uploader_email", ""),
            "kind": KIND_REQUESTED if any(m["_kind"] == KIND_REQUESTED for m in members) else KIND_SUGGESTED,
            "group_label": group["label"],
            "clip_asset_ids": SEP.join(m["source_asset_identifier"] for m in members),
            "clip_links": SEP.join(m.get("drive_link", "") for m in members),
            "location": SEP.join(dict.fromkeys(m.get("location", "") for m in members if m.get("location"))),
            "issue_summary": SEP.join(dict.fromkeys(m.get("issue_description", "") for m in members if m.get("issue_description"))),
            "recommended_action": SEP.join(dict.fromkeys(m.get("l2_recommended_action", "") for m in members if m.get("l2_recommended_action"))),
            "severity": str(sev), "priority": priority_for(sev) or "",
            "status": PENDING, "created_at": now, "updated_at": now,
        })
    return rows


def marker(key: str, part: int | None = None) -> str:
    return f"{MARKER_PREFIX}{key}{'' if part is None else f'#{part}'}]"


def idempotency_key(key: str, part: int | None = None) -> str:
    return f"sv-{key}{'' if part is None else f'-{part}'}"[:256]


def job_description(row: dict[str, Any], clip_index: int | None = None) -> str:
    """Location + issue + action + the walker's words, ending in the duplicate-scan marker."""
    if clip_index is None:
        where, issue = row["location"], row["issue_summary"]
    else:
        where = row["location"].split(SEP)[min(clip_index, len(row["location"].split(SEP)) - 1)] if row["location"] else ""
        issue = row["issue_summary"].split(SEP)[min(clip_index, len(row["issue_summary"].split(SEP)) - 1)] if row["issue_summary"] else ""
    lines = [f"Site visit {row.get('visit_name', '')}: {row['group_label']}".strip()]
    if where:
        lines.append(f"Location: {where}")
    if issue:
        lines.append(f"Issue: {issue}")
    if row.get("recommended_action"):
        lines.append(f"Recommended: {row['recommended_action']}")
    tail = marker(row["wo_key"], clip_index)
    text = "\n".join(lines)
    return text[: JOB_DESCRIPTION_MAX - len(tail) - 1] + "\n" + tail


@dataclass
class PlannedCreate:
    wo_key: str
    part: int | None
    body: dict[str, Any]
    idempotency_key: str
    note: str
    marker: str


@dataclass
class Plan:
    creates: list[PlannedCreate] = field(default_factory=list)
    blocked: list[tuple[str, str, str]] = field(default_factory=list)  # (key, status, reason)


def load_mapping(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Only reviewed=YES rows with a UUID count. Duplicate property names are a hard error."""
    out: dict[str, str] = {}
    for r in rows:
        if (r.get("reviewed") or "").strip().upper() != "YES":
            continue
        name = (r.get("catalog_property") or "").strip()
        pid = (r.get("appfolio_property_id") or "").strip()
        if not name or not _UUID.match(pid):
            continue
        if name in out and out[name] != pid:
            raise ValueError(f"{MAPPING_TAB}: {name!r} maps to two property IDs")
        out[name] = pid
    return out


def plan_creates(ledger: list[dict[str, Any]], mapping: dict[str, str],
                 only_keys: set[str] | None = None) -> Plan:
    plan = Plan()
    for row in ledger:
        if row.get("status") != APPROVED or row.get("decision") not in ("CREATE_ONE", "SPLIT"):
            continue
        if only_keys and row["wo_key"] not in only_keys:
            continue
        if row.get("appfolio_work_order_ids"):
            continue  # already created; never again
        pid = mapping.get(row.get("property", "").strip())
        if not pid:
            plan.blocked.append((row["wo_key"], BLOCKED_NO_MAPPING, f"no reviewed mapping for {row.get('property')!r}"))
            continue
        clips = row["clip_asset_ids"].split(SEP)
        links = row["clip_links"].split(SEP)
        parts: list[int | None] = list(range(len(clips))) if row["decision"] == "SPLIT" and len(clips) > 1 else [None]
        for part in parts:
            body: dict[str, Any] = {"PropertyId": pid, "JobDescription": job_description(row, part), "Status": "New"}
            if row.get("priority"):
                body["Priority"] = row["priority"]
            shown = links if part is None else [links[part]]
            note = "Site visit clip(s):\n" + "\n".join(l for l in shown if l)
            plan.creates.append(PlannedCreate(row["wo_key"], part, body, idempotency_key(row["wo_key"], part),
                                              note, marker(row["wo_key"], part)))
    return plan


def in_write_window(now_utc: datetime) -> bool:
    """AppFolio maintenance is 9PM-4AM Pacific; writes only 04:00-20:59 PT."""
    local = now_utc.astimezone(PACIFIC)
    return 4 <= local.hour < 21


def check_plan_invariants(plan: Plan, ledger: list[dict[str, Any]], max_creates: int) -> list[str]:
    """Every violation as a sentence with the actual numbers. Empty list = safe to send."""
    problems: list[str] = []
    keys = [r["wo_key"] for r in ledger]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        problems.append(f"ledger_keys_unique: {len(dupes)} duplicated wo_key(s): {dupes[:5]}")
    by_key = {r["wo_key"]: r for r in ledger}
    if len(plan.creates) > max_creates:
        problems.append(f"max_creates: plan has {len(plan.creates)} creates, cap is {max_creates}")
    idem = [c.idempotency_key for c in plan.creates]
    if len(idem) != len(set(idem)):
        problems.append("idempotency_keys_unique: duplicate keys in plan")
    for c in plan.creates:
        row = by_key.get(c.wo_key, {})
        tag = f"{c.wo_key}{'' if c.part is None else f'#{c.part}'}"
        if row.get("appfolio_work_order_ids"):
            problems.append(f"no_recreate: {tag} already has work order id(s) {row['appfolio_work_order_ids']}")
        if row.get("status") != APPROVED or row.get("decision") not in ("CREATE_ONE", "SPLIT") or not row.get("decided_at"):
            problems.append(f"human_approved: {tag} status={row.get('status')!r} decision={row.get('decision')!r} decided_at={row.get('decided_at')!r}")
        targets = [k for k in ("PropertyId", "UnitId", "OccupancyId", "InspectionId", "ServiceRequestId") if k in c.body]
        if targets != ["PropertyId"] or not _UUID.match(str(c.body["PropertyId"])):
            problems.append(f"single_uuid_target: {tag} targets={targets} value={c.body.get('PropertyId')!r}")
        if "Priority" in c.body and c.body["Priority"] not in PRIORITY_ENUM:
            problems.append(f"priority_enum: {tag} Priority={c.body['Priority']!r}")
        if c.body.get("Priority") != (priority_for(row.get("severity")) or None):
            problems.append(f"priority_matches_severity: {tag} severity={row.get('severity')!r} Priority={c.body.get('Priority')!r}")
        if any(isinstance(v, list) for v in c.body.values()):
            problems.append(f"no_array_fields: {tag} has array field(s) that could clear data")
        if not c.body.get("JobDescription", "").endswith(c.marker) or len(c.body["JobDescription"]) > JOB_DESCRIPTION_MAX:
            problems.append(f"marker_present: {tag} JobDescription missing marker or over {JOB_DESCRIPTION_MAX} chars")
    return problems


def find_by_marker(work_orders: list[dict[str, Any]], mark: str) -> dict[str, Any] | None:
    for wo in work_orders:
        if mark in (wo.get("JobDescription") or ""):
            return wo
    return None


def match_existing(work_orders: list[dict[str, Any]], ref: str) -> dict[str, Any] | None:
    """Match a walker-entered WO number or link against `WorkOrderNumber`, `Link`, or `Id` (UUID)."""
    ref = (ref or "").strip()
    if not ref:
        return None
    link = re.search(r"work_orders/(\d+)", ref)
    number = None if link else re.fullmatch(r"#?\s*([\w-]+)", ref)
    for wo in work_orders:
        if _UUID.match(ref) and wo.get("Id", "").lower() == ref.lower():
            return wo
        if link and re.search(rf"/work_orders/{link.group(1)}(?:\D|$)", wo.get("Link") or ""):
            return wo
        if number and str(wo.get("WorkOrderNumber") or "").strip() == number.group(1):
            return wo
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
