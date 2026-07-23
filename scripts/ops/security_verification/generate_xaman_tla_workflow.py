#!/usr/bin/env python3
"""Generate reconciled Xaman TLA+/Apalache workflow artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_tla_workflow import (
    APALACHE_REPORT_PATH,
    APALACHE_SOLVER_LANE_REPORT_PATH,
    TLA_ARTIFACT_PATH,
    build_apalache_solver_lane_report,
    build_xaman_tla_workflow_report,
    discover_apalache_executable,
    generated_tla_source,
    read_apalache_version,
    run_apalache_checks,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
MODEL_CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
LIFECYCLE_FACTS_PATH = CORPUS_DIR / 'payload-lifecycle-facts.json'


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def generate(*, run_apalache: bool = True) -> dict[str, dict[str, Any]]:
    tla_path = REPO_ROOT / TLA_ARTIFACT_PATH
    tla_source = generated_tla_source()
    tla_path.parent.mkdir(parents=True, exist_ok=True)
    tla_path.write_text(tla_source, encoding='utf-8')

    if run_apalache:
        apalache_executable = discover_apalache_executable()
    else:
        from ipfs_datasets_py.logic.external_provers.lazy_installer import find_executable

        apalache_executable = find_executable('apalache-mc') or find_executable('apalache')
    apalache_version = read_apalache_version(apalache_executable)
    apalache_runs = (
        run_apalache_checks(
            executable=apalache_executable,
            source=tla_source,
            version_output=apalache_version,
        )
        if run_apalache
        else None
    )
    xaman_report = build_xaman_tla_workflow_report(
        model_payload=_load_json(MODEL_PATH),
        model_cid=MODEL_CID_PATH.read_text(encoding='utf-8').strip(),
        lifecycle_facts=_load_json(LIFECYCLE_FACTS_PATH),
        tla_source=tla_source,
        apalache_executable=apalache_executable,
        apalache_version=apalache_version,
        apalache_runs=apalache_runs,
    )
    lane_report = build_apalache_solver_lane_report(
        repo_root=REPO_ROOT,
        tla_source=tla_source,
        xaman_tla_report=xaman_report,
        apalache_executable=apalache_executable,
        apalache_version=apalache_version,
        apalache_runs=apalache_runs,
    )
    _write_json(REPO_ROOT / APALACHE_REPORT_PATH, xaman_report)
    _write_json(REPO_ROOT / APALACHE_SOLVER_LANE_REPORT_PATH, lane_report)
    return {'xaman_tla_report': xaman_report, 'apalache_solver_lane_report': lane_report}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--skip-apalache',
        action='store_true',
        help='Write source and reports without running Apalache; reports will be blocker evidence.',
    )
    args = parser.parse_args(argv)
    reports = generate(run_apalache=not args.skip_apalache)
    print(
        json.dumps(
            {
                'tla_source': TLA_ARTIFACT_PATH,
                'xaman_tla_report': APALACHE_REPORT_PATH,
                'apalache_solver_lane_report': APALACHE_SOLVER_LANE_REPORT_PATH,
                'xaman_tla_status': reports['xaman_tla_report']['overall_status'],
                'solver_lane_status': reports['apalache_solver_lane_report']['overall_status'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
