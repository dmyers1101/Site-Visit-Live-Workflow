"""AppFolio work-order job orchestration (ADR 0015).

Two commands, both run by the Cloud Run job `site-visit-workorders` as
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`:

- `wo-candidates` — read the master catalog, select candidates, ask Vertex Gemini
  for groups (validated), append NEW `WorkOrders` rows as PENDING_REVIEW. Existing
  rows are never rewritten. The Apps Script form project picks them up.
- `wo-run` — verify "already exists" answers (read-only), plan creates for
  APPROVED rows, check every invariant, write the plan to GCS. Only with BOTH
  `--live` and env `WORK_ORDERS_LIVE=1` does it POST, capped by `--max-creates`
  (default 1), and only inside AppFolio's write window.

Pre-flight -> plan ("staging", in GCS) -> invariants -> per-create duplicate scan
-> POST -> read-back compare -> ledger write. Any invariant failure sends nothing.

How to update this later
------------------------
Keep AppFolio calls in `appfolio.py` and pure logic in `work_order_plan.py`.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import work_order_plan as wp
from .config import Settings, default_run_id
from .errors import ValidationError
from .google import column_letter, ensure_sheet_tab, read_sheet_records

GROUPING_PROMPT = "work-order-grouping.md"


# --- Sheets ledger ----------------------------------------------------------

def ensure_ledger(sheets: Any, sheet_id: str) -> None:
    for tab, headers in ((wp.LEDGER_TAB, wp.LEDGER_HEADERS), (wp.MAPPING_TAB, wp.MAPPING_HEADERS)):
        ensure_sheet_tab(sheets, sheet_id, tab)
        head = sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"{tab}!1:1").execute(num_retries=5).get("values", [])
        if not head:
            sheets.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f"{tab}!A1", valueInputOption="RAW",
                body={"values": [list(headers)]}).execute()
        elif tuple(head[0][: len(headers)]) != headers[: len(head[0])]:
            raise ValidationError(f"{tab} header does not match the expected columns; refusing to write.")


def append_ledger_rows(sheets: Any, sheet_id: str, rows: list[dict[str, Any]]) -> None:
    if rows:
        sheets.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=f"{wp.LEDGER_TAB}!A:{column_letter(len(wp.LEDGER_HEADERS))}",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": [[r.get(h, "") for h in wp.LEDGER_HEADERS] for r in rows]}).execute()


def update_ledger_row(sheets: Any, sheet_id: str, key: str, changes: dict[str, Any]) -> None:
    """Re-read column A, find the one row for `key`, write only the changed cells."""
    bad = set(changes) - set(wp.LEDGER_HEADERS) | ({"wo_key"} & set(changes))
    if bad:
        raise ValidationError(f"refusing to write ledger columns {sorted(bad)}")
    col_a = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"{wp.LEDGER_TAB}!A:A").execute(num_retries=5).get("values", [])
    hits = [i + 1 for i, r in enumerate(col_a) if r and r[0] == key]
    if len(hits) != 1:
        raise ValidationError(f"ledger key {key} found {len(hits)} times; expected exactly 1")
    data = [{"range": f"{wp.LEDGER_TAB}!{column_letter(wp.LEDGER_HEADERS.index(c) + 1)}{hits[0]}",
             "values": [[v]]} for c, v in {**changes, "updated_at": wp.now_iso()}.items()]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=sheet_id, body={"valueInputOption": "RAW", "data": data}).execute()


# --- grouping on Vertex -----------------------------------------------------

def propose_groups(settings: Settings, client: Any, prompts_dir: Path,
                   clips: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    from google.genai import types

    from .extraction import _fenced_block, generate_with_backoff

    if len(clips) < 2:
        return wp.singleton_groups(clips), "SINGLE"
    text = (prompts_dir / GROUPING_PROMPT).read_text(encoding="utf-8")
    instruction = _fenced_block(text, "Prompt", "text")
    if not instruction:
        raise ValidationError(f"{GROUPING_PROMPT} has no Prompt block")
    items = [{"id": c["source_asset_identifier"], "location": c.get("location", ""),
              "issue": c.get("issue_description", ""), "action": c.get("l2_recommended_action", "")}
             for c in clips]
    schema = {"type": "OBJECT", "required": ["groups"], "properties": {"groups": {
        "type": "ARRAY", "items": {"type": "OBJECT", "required": ["label", "clip_ids"], "properties": {
            "label": {"type": "STRING"}, "clip_ids": {"type": "ARRAY", "items": {"type": "STRING"}}}}}}}
    try:
        response = generate_with_backoff(
            client, model=settings.vertex_model, contents=instruction + json.dumps(items, indent=1),
            config=types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json",
                                               response_schema=schema))
        groups = wp.validate_grouping([i["id"] for i in items], json.loads(response.text or "{}"))
    except Exception:  # noqa: BLE001 - grouping is a convenience; fall back to singles
        groups = None
    return (groups, "MODEL") if groups else (wp.singleton_groups(clips), "FALLBACK_SINGLES")


def cmd_wo_candidates(args: Any) -> dict[str, Any]:
    from .extraction import build_client
    from .google import sheets_service

    settings = Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT",))
    sheet_id = (args.catalog_sheet_id or settings.catalog_sheet_id).strip()
    if not sheet_id:
        raise ValidationError("wo-candidates requires --catalog-sheet-id or CATALOG_SHEET_ID.")
    sheets = sheets_service(settings)
    catalog = read_sheet_records(sheets, sheet_id, args.sheet_name or settings.catalog_tab_name)
    if not args.dry_run:
        ensure_ledger(sheets, sheet_id)
    ledger = read_sheet_records(sheets, sheet_id, wp.LEDGER_TAB)
    claimed = {cid for r in ledger for cid in r.get("clip_asset_ids", "").split(wp.SEP) if cid}
    cutover = (os.environ.get("WORK_ORDERS_CUTOVER") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutover):
        raise ValidationError("wo-candidates requires WORK_ORDERS_CUTOVER=YYYY-MM-DD (visits before it never get forms).")
    candidates = [c for c in wp.select_candidates(catalog, cutover)
                  if c["source_asset_identifier"] not in claimed
                  and (not args.visit_id or c["visit_drive_id"] in args.visit_id)]
    client = build_client(settings) if candidates else None
    by_visit: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        by_visit.setdefault(c["visit_drive_id"], []).append(c)
    new_rows, visits = [], []
    existing = {r["wo_key"] for r in ledger}
    for visit_id, clips in by_visit.items():
        groups, how = propose_groups(settings, client, Path(args.prompts_dir), clips)
        rows = wp.new_ledger_rows(clips, groups, existing, wp.now_iso())
        existing |= {r["wo_key"] for r in rows}
        new_rows += rows
        visits.append({"visit_drive_id": visit_id, "clips": len(clips), "groups": len(groups),
                       "grouping": how, "new_rows": len(rows)})
    if not args.dry_run:
        append_ledger_rows(sheets, sheet_id, new_rows)
    summary = {"gate": "wo-candidates", "dry_run": args.dry_run, "cutover": cutover, "catalog_rows": len(catalog),
               "ledger_rows_before": len(ledger), "candidates": len(candidates),
               "new_rows": len(new_rows), "visits": visits,
               "preview": [{k: r[k] for k in ("wo_key", "kind", "group_label", "priority", "clip_asset_ids")}
                           for r in new_rows[:20]]}
    print(json.dumps(summary, default=str), flush=True)
    return summary


# --- AppFolio run -----------------------------------------------------------

def _verify_existing(af: Any, sheets: Any, sheet_id: str, ledger: list[dict[str, Any]], live: bool) -> list[dict[str, Any]]:
    pending = [r for r in ledger if r.get("status") == wp.EXISTS_PENDING]
    if not pending:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=730)).strftime("%Y-%m-%dT%H:%M:%SZ")
    pool = af.work_orders_since(since)
    out = []
    for r in pending:
        hit = wp.match_existing(pool, r.get("existing_ref", ""))
        change = ({"status": wp.EXISTS_VERIFIED, "appfolio_work_order_ids": hit["Id"],
                   "appfolio_links": hit.get("Link", ""), "last_error": ""} if hit else
                  {"status": wp.EXISTS_UNVERIFIED, "last_error": f"no AppFolio work order matches {r.get('existing_ref')!r}"})
        if live:
            update_ledger_row(sheets, sheet_id, r["wo_key"], change)
        out.append({"wo_key": r["wo_key"], **change})
    return out


def cmd_wo_run(args: Any) -> dict[str, Any]:
    import os

    from .appfolio import AmbiguousWriteError, AppFolioAuthError, AppFolioClient, AppFolioRejected, load_credentials
    from .google import StorageGateway, sheets_service

    settings = Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT", "GCS_STAGING_BUCKET"))
    run_id = (args.run_id or "").strip() or default_run_id()
    live = bool(args.live) and os.environ.get("WORK_ORDERS_LIVE", "") == "1"
    if args.live and not live:
        raise ValidationError("--live also needs env WORK_ORDERS_LIVE=1 on the job (two-key rule, like renames).")
    sheet_id = (args.catalog_sheet_id or settings.catalog_sheet_id).strip()
    if not sheet_id:
        raise ValidationError("wo-run requires --catalog-sheet-id or CATALOG_SHEET_ID.")
    if getattr(args, "check_auth", False):
        # Read-only credential probe: one GET, counts only, no values printed.
        af = AppFolioClient(load_credentials())
        since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            count, status = len(af.work_orders_since(since)), "OK"
        except Exception as error:  # noqa: BLE001 - report the class, not secrets
            count, status = None, f"{type(error).__name__}: {str(error)[:200]}"
        print(json.dumps({"gate": "wo-auth-check", "status": status,
                          "work_orders_updated_last_24h": count, "appfolio_calls": af.call_count}), flush=True)
        return {"status": status}
    sheets = sheets_service(settings)
    ledger = read_sheet_records(sheets, sheet_id, wp.LEDGER_TAB)
    mapping = wp.load_mapping(read_sheet_records(sheets, sheet_id, wp.MAPPING_TAB))
    af = AppFolioClient(load_credentials())  # pre-flight: creds present

    verified = _verify_existing(af, sheets, sheet_id, ledger, live)
    plan = wp.plan_creates(ledger, mapping, set(args.wo_key or []) or None)
    problems = wp.check_plan_invariants(plan, ledger, args.max_creates)
    storage = StorageGateway.from_settings(settings)
    prefix = f"runs/workorders/{run_id}"
    plan_uri = storage.write_json(f"{prefix}/plan.json", {
        "run_id": run_id, "live": live, "max_creates": args.max_creates, "problems": problems,
        "creates": [asdict(c) for c in plan.creates], "blocked": plan.blocked, "exists_checks": verified})
    for key, status, reason in plan.blocked:
        if live:
            update_ledger_row(sheets, sheet_id, key, {"status": status, "last_error": reason})

    results: list[dict[str, Any]] = []
    stop = None
    if problems:
        stop = "INVARIANTS_FAILED"
    elif live and not wp.in_write_window(datetime.now(timezone.utc)):
        stop = "OUTSIDE_APPFOLIO_WRITE_WINDOW"
    elif live:
        rows = {r["wo_key"]: r for r in ledger}
        done: dict[str, list[tuple[str, str, str]]] = {}
        oldest = min((rows[c.wo_key].get("created_at") or wp.now_iso() for c in plan.creates), default=wp.now_iso())
        since = (datetime.strptime(oldest, "%Y-%m-%dT%H:%M:%SZ") - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for c in plan.creates:
            entry: dict[str, Any] = {"wo_key": c.wo_key, "part": c.part, "idempotency_key": c.idempotency_key}
            try:
                prior = wp.find_by_marker(af.work_orders_since(since), c.marker)
                if prior:
                    wo = {"Id": prior["Id"], "Link": prior.get("Link", ""), "replayed": "FOUND_BY_MARKER"}
                else:
                    wo = af.create_work_order(c.body, c.idempotency_key)
                    back = af.get_work_order(wo["Id"]) or {}
                    mismatched = [k for k in ("PropertyId", "JobDescription", "Priority")
                                  if k in c.body and back.get(k) != c.body[k]]
                    if mismatched:
                        entry["readback_mismatch"] = mismatched
                    af.create_work_order_note(wo["Id"], c.note, c.idempotency_key + "-note")
                entry.update(status="CREATED", work_order_id=wo["Id"], link=wo["Link"], replayed=wo["replayed"])
                done.setdefault(c.wo_key, []).append((str(c.part), wo["Id"], wo["Link"]))
            except AppFolioAuthError as error:
                entry.update(status="STOPPED_AUTH", error=str(error)[:300])
                results.append(entry)
                stop = "AUTH"
                break
            except (AppFolioRejected, AmbiguousWriteError, Exception) as error:  # noqa: BLE001
                entry.update(status="FAILED", error=str(error)[:500])
                update_ledger_row(sheets, sheet_id, c.wo_key, {"status": wp.FAILED, "last_error": str(error)[:500]})
            results.append(entry)
            storage.write_json(f"{prefix}/{c.idempotency_key}.json", entry)
        for key, parts in done.items():
            expected = sum(1 for c in plan.creates if c.wo_key == key)
            update_ledger_row(sheets, sheet_id, key, {
                "status": wp.CREATED if len(parts) == expected else wp.FAILED,
                "idempotency_keys": wp.SEP.join(c.idempotency_key for c in plan.creates if c.wo_key == key),
                "appfolio_property_id": next(c.body["PropertyId"] for c in plan.creates if c.wo_key == key),
                "appfolio_work_order_ids": wp.SEP.join(p[1] for p in parts),
                "appfolio_links": wp.SEP.join(p[2] for p in parts),
                "last_error": "" if len(parts) == expected else f"{len(parts)}/{expected} parts created"})
    summary = {"gate": "wo-run", "run_id": run_id, "live": live, "plan_uri": plan_uri,
               "planned_creates": len(plan.creates), "blocked": len(plan.blocked),
               "exists_checked": len(verified), "invariant_problems": problems, "stopped": stop,
               "results": results, "appfolio_calls": af.call_count,
               "dry_run_payloads": [] if live else [c.body for c in plan.creates[:10]]}
    print(json.dumps(summary, default=str), flush=True)
    return summary
