#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


FAILURE_HINTS: Dict[str, Dict[str, Any]] = {
    "canary_exit_nonzero": {
        "message": "Canary smoke command failed before producing expected outputs.",
        "commands": [
            "bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_proof_audit_smoke.sh",
            "bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_mode.sh",
        ],
    },
    "regression_exit_nonzero": {
        "message": "Regression smoke command failed before producing expected outputs.",
        "commands": [
            "bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_proof_audit_smoke.sh",
            "bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_check.sh",
        ],
    },
    "canary_artifact_missing": {
        "message": "Canary smoke completed but expected canary proof-audit artifact is missing.",
        "commands": [
            "bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_proof_audit_smoke.sh",
            "bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_certificate_audit.sh",
        ],
    },
    "regression_artifact_missing": {
        "message": "Regression smoke completed but expected regression proof-audit artifact is missing.",
        "commands": [
            "bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_proof_audit_smoke.sh",
            "bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_certificate_audit.sh",
        ],
    },
}


def _load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: str, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def build_triage(summary: Dict[str, Any]) -> Dict[str, Any]:
    overall_passed = bool(summary.get("overall_passed", False))
    error_code = str(summary.get("error_code") or "UNKNOWN")
    failure_reasons = [str(x) for x in (summary.get("failure_reasons") or [])]

    hints: List[Dict[str, Any]] = []
    commands: List[str] = []

    for reason in failure_reasons:
        hint_def = FAILURE_HINTS.get(reason)
        if hint_def is None:
            hints.append(
                {
                    "reason": reason,
                    "message": "Unknown failure reason. Inspect summary and logs directly.",
                    "commands": [],
                }
            )
            continue
        reason_commands = [str(c) for c in (hint_def.get("commands") or [])]
        hints.append(
            {
                "reason": reason,
                "message": str(hint_def.get("message") or ""),
                "commands": reason_commands,
            }
        )
        commands.extend(reason_commands)

    if overall_passed and error_code == "OK":
        status = "ok"
        top_message = "Integration smoke passed. No remediation required."
    else:
        status = "needs_action"
        top_message = "Integration smoke failed. Follow recommended commands in order."

    return {
        "status": status,
        "top_message": top_message,
        "overall_passed": overall_passed,
        "error_code": error_code,
        "failure_reasons": failure_reasons,
        "hints": hints,
        "recommended_commands": _dedupe_keep_order(commands),
        "summary_ref": summary,
    }


def render_triage_markdown(triage: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Proof-Audit Integration Triage")
    lines.append("")
    lines.append(f"- status: `{triage['status']}`")
    lines.append(f"- error_code: `{triage['error_code']}`")
    lines.append(f"- overall_passed: `{str(triage['overall_passed']).lower()}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(triage["top_message"])
    lines.append("")

    failure_reasons = list(triage.get("failure_reasons") or [])
    lines.append("## Failure Reasons")
    lines.append("")
    if failure_reasons:
        for reason in failure_reasons:
            lines.append(f"- `{reason}`")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Recommended Commands")
    lines.append("")
    commands = list(triage.get("recommended_commands") or [])
    if commands:
        for command in commands:
            lines.append(f"- `{command}`")
    else:
        lines.append("- none")
    lines.append("")

    checks = (triage.get("summary_ref") or {}).get("checks") or {}
    canary = checks.get("canary_smoke") or {}
    regression = checks.get("regression_smoke") or {}

    lines.append("## Paths")
    lines.append("")
    lines.append(f"- canary_log: `{canary.get('log_path', '')}`")
    lines.append(f"- regression_log: `{regression.get('log_path', '')}`")
    lines.append(f"- canary_artifact: `{canary.get('artifact_path', '')}`")
    lines.append(f"- regression_artifact: `{regression.get('artifact_path', '')}`")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    default_output_json = "/tmp/formal_logic_proof_audit_integration_smoke/triage.json"
    ap = argparse.ArgumentParser(description="Assess proof-audit integration smoke summary and emit remediation hints")
    ap.add_argument(
        "--summary",
        default="/tmp/formal_logic_proof_audit_integration_smoke/summary.json",
        help="Path to integration smoke summary JSON",
    )
    ap.add_argument(
        "--output",
        default=default_output_json,
        help="Path to output artifact (JSON by default, markdown when --format=markdown)",
    )
    ap.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format",
    )
    ap.add_argument(
        "--fail-on-needs-action",
        action="store_true",
        help="Return exit code 2 when triage status is needs_action",
    )
    args = ap.parse_args()

    summary = _load_json(args.summary)
    triage = build_triage(summary)

    output_path = args.output
    if args.format == "markdown" and args.output == default_output_json:
        output_path = "/tmp/formal_logic_proof_audit_integration_smoke/triage.md"

    if args.format == "json":
        _write_json(output_path, triage)
    else:
        _write_text(output_path, render_triage_markdown(triage))

    print(f"status={triage['status']}")
    print(f"error_code={triage['error_code']}")
    print(f"failure_reason_count={len(triage['failure_reasons'])}")
    print(f"recommended_command_count={len(triage['recommended_commands'])}")
    print(f"output_format={args.format}")
    print(f"output={output_path}")

    for command in triage["recommended_commands"]:
        print(f"recommended_command={command}")

    if args.fail_on_needs_action and triage["status"] == "needs_action":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
