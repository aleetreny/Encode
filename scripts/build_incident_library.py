"""Build Incident Library Script (`scripts/build_incident_library.py`).

Generates pre-computed offline incident JSONL files and an index.json catalog in
`frontend/public/incidents/` covering all disruptable assets across the 6 canonical
simulation hours {9, 12, 13, 18, 19, 20}, plus key multi-failure demo combinations.

Features:
- Fast parallel generation using Python's ThreadPoolExecutor with in-memory LiveSession.
- Full event sequence in each .jsonl:
    1. session.snapshot (at start_hour = hour)
    2. incident.detected
    3. solution.updated (reason: "incident")
    4. agent.thought (digit-free)
    5. agent.tool_call
    6. options.ready (cached=True, distinct trade-off tags, digit-free)
    7. plan.applied (at hour + 0.25)
    8. solution.updated (reason: "plan_applied" at hour + 0.25)
- Zero digits guardrail enforced on all Gemini/agent prose fields.
- index.json with peak MW, peak households off, recommended_id, cached_at_utc.
- CLI flags: --fast (default), --full, --live-all, --workers.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import datetime as dt
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.live.agent_loop import (
    OPERATIONAL_LEVER_TYPES,
    has_digits,
    is_tag_truthful,
    sanitize_no_digits,
)
from backend.live.catalog import build_catalog
from backend.live.engine import LiveSession

HOURS = [9, 12, 13, 18, 19, 20]
DURATION_H = 4

# Core disruptable assets from demo scenario catalog
CORE_GENERATORS = [
    "solar_ng",
    "solar_nc",
    "wind_nc",
    "gas_ng",
    "gas_centro",
    "coal_cs",
    "hydro_sur",
    "wind_sur",
    "diesel_centro",
]

CORE_LINES = ["L1", "L2", "L3", "L4"]
CORE_BATTERIES = ["b_centro"]

CORE_ASSETS = CORE_GENERATORS + CORE_LINES + CORE_BATTERIES  # 14 assets

# Asset aliases to guarantee 100% compatibility with any variant naming
ASSET_ALIASES: dict[str, str] = {
    "wind_austral": "wind_sur",
    "coal_ng": "coal_cs",
    "wind_ng": "wind_nc",
    "b_ng": "b_centro",
}

COMBOS = [
    {
        "key": "combo_gas_centro_L3_18",
        "assets": ["gas_centro", "L3"],
        "hour": 18,
    },
    {
        "key": "combo_L1_gas_ng_12",
        "assets": ["L1", "gas_ng"],
        "hour": 12,
        "aliases": ["combo_L1_coal_ng_12"],
    },
]


JURY_NAMES = [
    "Prof. María González",
    "Dr. Carlos Muñoz",
    "Ing. Sofía Valdivia",
    "Dr. Andrés Pizarro",
    "Jurado Londres",
]


def _pick_jury_name(asset_key: str, hour: int) -> str:
    idx = (sum(ord(c) for c in asset_key) + hour) % len(JURY_NAMES)
    return JURY_NAMES[idx]


def enforce_digit_free_and_cached(events: list[dict[str, Any]], asset_key: str, hour: int) -> None:
    """Enforce cached model execution metadata and zero digits across all prose fields.
    Preserves honest `model`, `status`, and `response_id` from `run_incident_evaluation`.
    """
    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for ev in events:
        etype = ev.get("type")
        if etype == "incident.detected":
            disr = ev.setdefault("disruption", {})
            disr["source"] = "jury"
            if not disr.get("jury_name"):
                disr["jury_name"] = _pick_jury_name(asset_key, hour)
        elif etype == "agent.thought":
            raw_delta = ev.get("delta", "")
            if has_digits(raw_delta):
                ev["delta"] = sanitize_no_digits(raw_delta)
            assert not has_digits(ev["delta"]), f"Digit found in thought delta: {ev['delta']}"

        elif etype == "agent.note":
            raw_text = ev.get("text_es", "")
            if has_digits(raw_text):
                ev["text_es"] = sanitize_no_digits(raw_text)
            assert not has_digits(ev["text_es"]), f"Digit found in note text: {ev['text_es']}"

        elif etype == "options.ready":
            raw_diag = ev.get("diagnosis_es", "")
            if has_digits(raw_diag):
                ev["diagnosis_es"] = sanitize_no_digits(raw_diag)
            assert not has_digits(ev["diagnosis_es"]), f"Digit in diagnosis: {ev['diagnosis_es']}"

            # Mark pre-recorded library entry as cached while preserving honest model/status/response_id
            me = ev.setdefault("model_execution", {})
            me["cached"] = True
            if not me.get("cached_at_utc"):
                me["cached_at_utc"] = now_utc
            if not me.get("response_id"):
                me["response_id"] = f"det-{asset_key}-{hour}"
            if str(me["response_id"]).startswith("det-") or me.get("status") != "ok":
                me["model"] = "deterministic-planner"
                if me.get("status") == "ok":
                    me["status"] = "error"

            # Ensure options validation and digit-free prose
            opts = ev.get("options", [])
            assert len(opts) == 2, f"Expected 2 options in {asset_key}_{hour}"
            for opt in opts:
                raw_t = opt.get("title_es", "")
                if has_digits(raw_t):
                    opt["title_es"] = sanitize_no_digits(raw_t)
                assert not has_digits(opt["title_es"]), f"Digit in option title: {opt['title_es']}"

                raw_r = opt.get("rationale_es", "")
                if has_digits(raw_r):
                    opt["rationale_es"] = sanitize_no_digits(raw_r)
                assert not has_digits(opt["rationale_es"]), f"Digit in option rationale: {opt['rationale_es']}"

                for lv in opt.get("levers", []):
                    assert lv.get("type") in OPERATIONAL_LEVER_TYPES, (
                        f"Non-operational lever {lv.get('type')} in {asset_key}_{hour}"
                    )

            opt_a, opt_b = opts[0], opts[1]
            assert opt_a["tradeoff_tag"] != opt_b["tradeoff_tag"], f"Duplicate tags in {asset_key}_{hour}"
            assert is_tag_truthful(opt_a["tradeoff_tag"], opt_a["metrics"], opt_b["metrics"]), (
                f"Untruthful tag_a {opt_a['tradeoff_tag']} in {asset_key}_{hour}: {opt_a['metrics']} vs {opt_b['metrics']}"
            )
            assert is_tag_truthful(opt_b["tradeoff_tag"], opt_b["metrics"], opt_a["metrics"]), (
                f"Untruthful tag_b {opt_b['tradeoff_tag']} in {asset_key}_{hour}: {opt_b['metrics']} vs {opt_a['metrics']}"
            )

            hh_a = float(opt_a["metrics"]["households_reconnected"])
            hh_b = float(opt_b["metrics"]["households_reconnected"])
            rec_id = ev.get("recommended_id")
            rec_opt = next((o for o in opts if o["option_id"] == rec_id), opts[0])
            if max(hh_a, hh_b) > 0:
                assert float(rec_opt["metrics"]["households_reconnected"]) > 0, (
                    f"Recommended 0-reconnected option in {asset_key}_{hour} when improvement > 0 exists"
                )
            else:
                assert "ninguna maniobra" in ev["diagnosis_es"].lower(), (
                    f"Missing zero-improvement notice in diagnosis_es for {asset_key}_{hour}"
                )


def generate_single_incident(
    asset_id: str,
    hour: int,
    allow_live: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run in-memory LiveSession and record full event stream for single asset disruption."""
    async def _run() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        max_attempts = 3 if allow_live else 1
        events: list[dict[str, Any]] = []
        for attempt in range(max_attempts):
            ses = LiveSession(
                session_id=f"ses_{asset_id}_{hour}",
                start_hour=float(hour),
                allow_live_gemini=allow_live,
            )
            q = ses.subscribe()
            disrupt_res = await ses.disrupt(
                asset_id,
                duration_h=DURATION_H,
                source="jury",
                jury_name=_pick_jury_name(asset_id, hour),
                from_hour_override=hour,
                wait_for_options=True,
            )

            # Advance hour past agent events and apply recommended option
            ses.hour = round(max(ses.hour + 0.05, float(hour) + 0.25), 2)
            await ses.decide(
                incident_id=disrupt_res["incident_id"],
                option_id=None,
                decision="apply",
            )

            events = []
            while not q.empty():
                events.append(q.get_nowait())

            options_ev = next(e for e in events if e["type"] == "options.ready")
            if not allow_live or options_ev["model_execution"].get("status") == "ok":
                break
            await asyncio.sleep(1.5 * (attempt + 1))

        if allow_live:
            options_ev = next(e for e in events if e["type"] == "options.ready")
            me = options_ev["model_execution"]
            assert me.get("status") == "ok" and me.get("model") == "gemini-4-argon" and not str(me.get("response_id", "")).startswith("det-"), (
                f"Live Gemini required for {asset_id}_{hour}, got {me}"
            )

        enforce_digit_free_and_cached(events, asset_id, hour)

        # Extract summary info for index
        detected_ev = next(e for e in events if e["type"] == "incident.detected")
        options_ev = next(e for e in events if e["type"] == "options.ready")
        impact = detected_ev.get("impact", {})

        meta = {
            "file": f"/incidents/{asset_id}_{hour}.jsonl",
            "asset_id": asset_id,
            "hour": hour,
            "duration_h": DURATION_H,
            "unserved_mw_peak": impact.get("unserved_mw_peak", 0.0),
            "households_off_peak": impact.get("households_off_peak", 0),
            "recommended_id": options_ev.get("recommended_id", ""),
            "cached_at_utc": options_ev["model_execution"]["cached_at_utc"],
        }
        return meta, events

    return asyncio.run(_run())


def generate_combo_incident(
    combo_spec: dict[str, Any],
    allow_live: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run in-memory LiveSession and record multi-failure combination events."""
    combo_key = combo_spec["key"]
    assets = combo_spec["assets"]
    hour = combo_spec["hour"]

    async def _run() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        max_attempts = 3 if allow_live else 1
        events: list[dict[str, Any]] = []
        for attempt in range(max_attempts):
            ses = LiveSession(
                session_id=f"ses_{combo_key}",
                start_hour=float(hour),
                allow_live_gemini=allow_live,
            )
            q = ses.subscribe()

            # Stack disruptions
            res1 = await ses.disrupt(
                assets[0],
                duration_h=DURATION_H,
                from_hour_override=hour,
                wait_for_options=False,
            )
            # Cancel any eval task from first disruption so only combined state is evaluated
            for t in list(ses._eval_tasks):
                t.cancel()
            ses._eval_tasks.clear()

            res2 = await ses.disrupt(
                assets[1],
                duration_h=DURATION_H,
                from_hour_override=hour,
                wait_for_options=True,
            )

            ses.hour = round(max(ses.hour + 0.05, float(hour) + 0.25), 2)
            await ses.decide(
                incident_id=res2["incident_id"],
                option_id=None,
                decision="apply",
            )

            events = []
            while not q.empty():
                events.append(q.get_nowait())

            options_ev = next(e for e in events if e["type"] == "options.ready")
            if not allow_live or options_ev["model_execution"].get("status") == "ok":
                break
            await asyncio.sleep(1.5 * (attempt + 1))

        if allow_live:
            options_ev = next(e for e in events if e["type"] == "options.ready")
            me = options_ev["model_execution"]
            assert me.get("status") == "ok" and me.get("model") == "gemini-4-argon" and not str(me.get("response_id", "")).startswith("det-"), (
                f"Live Gemini required for {combo_key}, got {me}"
            )

        enforce_digit_free_and_cached(events, combo_key, hour)

        detected_events = [e for e in events if e["type"] == "incident.detected"]
        last_detected = detected_events[-1] if detected_events else {}
        options_ev = next(e for e in events if e["type"] == "options.ready")
        impact = last_detected.get("impact", {})

        meta = {
            "file": f"/incidents/{combo_key}.jsonl",
            "assets": assets,
            "hour": hour,
            "duration_h": DURATION_H,
            "unserved_mw_peak": impact.get("unserved_mw_peak", 0.0),
            "households_off_peak": impact.get("households_off_peak", 0),
            "recommended_id": options_ev.get("recommended_id", ""),
            "cached_at_utc": options_ev["model_execution"]["cached_at_utc"],
        }
        return meta, events

    return asyncio.run(_run())


def write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    """Write events as line-delimited JSON with trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def build_library(
    out_dir: Path,
    fast: bool = True,
    live_all: bool = False,
    workers: int = 4,
) -> dict[str, Any]:
    """Generate all incident files and index.json catalog."""
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    index_data: dict[str, Any] = {
        "generated_at_utc": generated_at_utc,
        "hours": HOURS,
        "duration_h": DURATION_H,
        "assets_count": len(CORE_ASSETS),
        "incidents": {},
        "combos": {},
    }

    tasks_single: list[tuple[str, int]] = []
    for asset in CORE_ASSETS:
        for h in HOURS:
            tasks_single.append((asset, h))

    print(f"Generating {len(tasks_single)} single-asset incidents ({len(CORE_ASSETS)} assets × {len(HOURS)} hours)...")
    if live_all:
        os.environ.setdefault("GRIDPILOT_GEMINI_TIMEOUT_S", "22.0")

    def _worker_single(item: tuple[str, int]) -> tuple[str, int, dict[str, Any], list[dict[str, Any]]]:
        asset, h = item
        file_key = f"{asset}_{h}"
        jsonl_path = out_dir / f"{file_key}.jsonl"
        allow_live = bool(live_all and os.getenv("GEMINI_API_KEY"))
        if allow_live and jsonl_path.is_file():
            try:
                existing_evs = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                opt_ev = next((e for e in existing_evs if e.get("type") == "options.ready"), None)
                inc_ev = next((e for e in existing_evs if e.get("type") == "incident.detected"), None)
                if opt_ev and inc_ev:
                    me = opt_ev.get("model_execution", {})
                    if (
                        me.get("status") == "ok"
                        and me.get("model") == "gemini-4-argon"
                        and not str(me.get("response_id", "det-")).startswith("det-")
                        and float(opt_ev.get("hour", 0)) > float(inc_ev.get("hour", 0))
                    ):
                        enforce_digit_free_and_cached(existing_evs, asset, h)
                        write_jsonl(jsonl_path, existing_evs)
                        impact = inc_ev.get("impact", {})
                        meta = {
                            "file": f"/incidents/{asset}_{h}.jsonl",
                            "asset_id": asset,
                            "hour": h,
                            "duration_h": DURATION_H,
                            "unserved_mw_peak": impact.get("unserved_mw_peak", 0.0),
                            "households_off_peak": impact.get("households_off_peak", 0),
                            "recommended_id": opt_ev.get("recommended_id", ""),
                            "cached_at_utc": me["cached_at_utc"],
                        }
                        return asset, h, meta, existing_evs
            except Exception:
                pass
        meta, evs = generate_single_incident(asset, h, allow_live=allow_live)
        write_jsonl(jsonl_path, evs)
        return asset, h, meta, evs

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for asset, h, meta, evs in executor.map(_worker_single, tasks_single):
            file_key = f"{asset}_{h}"
            index_data["incidents"][file_key] = meta

    # Write alias files and index entries
    print("Writing alias incident files...")
    for alias_name, canonical_name in ASSET_ALIASES.items():
        for h in HOURS:
            canonical_key = f"{canonical_name}_{h}"
            alias_key = f"{alias_name}_{h}"
            if canonical_key in index_data["incidents"]:
                canonical_path = out_dir / f"{canonical_key}.jsonl"
                alias_path = out_dir / f"{alias_key}.jsonl"
                with open(canonical_path, "r", encoding="utf-8") as f_in, open(alias_path, "w", encoding="utf-8") as f_out:
                    f_out.write(f_in.read())

                alias_meta = dict(index_data["incidents"][canonical_key])
                alias_meta["file"] = f"/incidents/{alias_key}.jsonl"
                alias_meta["asset_id"] = alias_name
                index_data["incidents"][alias_key] = alias_meta

    print("Generating multi-failure combos...")
    for combo in COMBOS:
        combo_key = combo["key"]
        meta, evs = generate_combo_incident(combo, allow_live=bool(live_all and os.getenv("GEMINI_API_KEY")))
        jsonl_path = out_dir / f"{combo_key}.jsonl"
        write_jsonl(jsonl_path, evs)
        index_data["combos"][combo_key] = meta
        index_data["incidents"][combo_key] = meta

        # Write combo aliases if any
        for calias in combo.get("aliases", []):
            calias_path = out_dir / f"{calias}.jsonl"
            with open(jsonl_path, "r", encoding="utf-8") as f_in, open(calias_path, "w", encoding="utf-8") as f_out:
                f_out.write(f_in.read())
            calias_meta = dict(meta)
            calias_meta["file"] = f"/incidents/{calias}.jsonl"
            index_data["combos"][calias] = calias_meta
            index_data["incidents"][calias] = calias_meta

    # Write index.json
    index_path = out_dir / "index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {len(index_data['incidents'])} incidents index in {out_dir}")
    return index_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline incident library for GridPilot Live Ops")
    parser.add_argument("--fast", action="store_true", default=True, help="Fast generation with deterministic solver")
    parser.add_argument("--full", action="store_true", default=False, help="Generate full catalog")
    parser.add_argument("--live-all", action="store_true", default=False, help="Call live Gemini model for all sessions")
    parser.add_argument("--workers", type=int, default=6, help="Worker threads for parallel LP generation")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "frontend" / "public" / "incidents",
        help="Target output directory",
    )
    args = parser.parse_args()

    build_library(
        out_dir=args.out_dir,
        fast=args.fast,
        live_all=args.live_all,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
