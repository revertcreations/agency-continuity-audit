#!/usr/bin/env python3
"""Read-only evidence audit for a persistent agent workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


OBJECTIVE_FILES = ("MANDATE.md", "CHARACTER.md", "AGENTS.md")


def finding(identifier: str, status: str, summary: str, evidence=None) -> dict:
    return {"id": identifier, "status": status, "summary": summary, "evidence": evidence or []}


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def sqlite_tables(path: Path) -> set[str]:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        connection.close()
        return tables
    except sqlite3.Error:
        return set()


def audit(project: Path, state_dir: Path) -> dict:
    project, state_dir = project.resolve(), state_dir.resolve()
    results = []
    objectives = [project / name for name in OBJECTIVE_FILES if (project / name).is_file()]
    results.append(finding("authoritative-objective", "pass" if objectives else "fail",
        "An explicit objective or boundary source exists." if objectives else "No objective or boundary source found.",
        [str(path) for path in objectives]))

    sqlite_files = sorted(state_dir.glob("*.sqlite")) if state_dir.is_dir() else []
    json_files = sorted(state_dir.glob("*.json")) if state_dir.is_dir() else []
    results.append(finding("structured-state", "pass" if sqlite_files or json_files else "fail",
        "Structured durable state exists." if sqlite_files or json_files else "Only prose or no durable state was found.",
        [str(path) for path in sqlite_files + json_files[:10]]))

    table_map = {str(path): sqlite_tables(path) for path in sqlite_files}
    correction_sources = [path for path, tables in table_map.items() if {"correction_events", "memory_edges"} & tables]
    results.append(finding("correction-path", "pass" if correction_sources else "warn",
        "A structured correction or supersession path exists." if correction_sources
        else "No structured correction path was proven; stale beliefs may survive corrections.", correction_sources))

    candidates = [path for path in json_files if "continuity" in path.name or "resume" in path.name]
    continuity = next((value for path in candidates if (value := read_json(path))), {})
    transport = continuity.get("transportHealthy")
    results.append(finding("continuity-verifier", "pass" if transport is True else "warn",
        "Continuity reports healthy transport." if transport is True else "No current healthy continuity verification was found.",
        [str(path) for path in candidates]))

    proof = continuity.get("rebootProof", {})
    restarted = proof.get("verifiedAcrossRestart") is True
    results.append(finding("actual-restart-proof", "pass" if restarted else "warn",
        "Recovery was witnessed across distinct boots." if restarted
        else "Restart recovery is not proven by an observation from a different boot.", [proof] if proof else []))

    operations = continuity.get("operations", {})
    human_required = operations.get("humanRequired") is True
    results.append(finding("authority-exceptions", "warn" if human_required else "pass",
        "Human authority is currently required." if human_required else "No current human-required exception is reported.",
        operations.get("issues", []) if isinstance(operations, dict) else []))

    finance = continuity.get("finance", {})
    floor_proven = finance.get("freedomFloorProven") is True
    results.append(finding("commercial-outcome", "pass" if floor_proven else "warn",
        "The declared commercial floor is reported proven." if floor_proven
        else "Commercial completion is unproven; operational health must not be presented as income.",
        [finance] if finance else []))

    units = continuity.get("continuity", {}).get("units", {})
    unhealthy = [name for name, state in units.items() if not state.get("active") or not state.get("enabled")]
    results.append(finding("scheduler-health", "pass" if units and not unhealthy else "warn",
        "Required scheduled units are active and enabled." if units and not unhealthy
        else "Scheduler presence and health are not fully proven.", unhealthy or list(units)))

    severity = {"pass": 0, "warn": 1, "fail": 2}
    overall = max(results, key=lambda item: severity[item["status"]])["status"]
    inventory = "\n".join(str(path) for path in sqlite_files + json_files)
    return {"schemaVersion": 1, "overall": overall, "project": str(project), "stateDir": str(state_dir),
        "sourceInventoryHash": hashlib.sha256(inventory.encode()).hexdigest(), "findings": results,
        "claimBoundary": "This checks durable evidence surfaces; it does not prove quality, safety, demand, or revenue by absence of findings."}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.project, args.state_dir or args.project / ".agent-state")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Agency continuity audit: {result['overall']}")
        for item in result["findings"]:
            print(f"[{item['status'].upper()}] {item['id']}: {item['summary']}")
    return 1 if result["overall"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
