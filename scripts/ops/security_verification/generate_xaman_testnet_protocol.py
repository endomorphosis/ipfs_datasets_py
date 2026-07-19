#!/usr/bin/env python3
"""Generate Xaman Testnet Tamarin/ProVerif protocol artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_protocol import (  # noqa: E402
    ASSUMPTIONS_PATH,
    FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PROTOCOL_REPORT_PATH,
    PROVERIF_ARTIFACT_PATH,
    TAMARIN_ARTIFACT_PATH,
    TRACE_MAP_PATH,
    XAMAN_TESTNET_PAYLOAD_PV,
    XAMAN_TESTNET_PAYLOAD_SPTHY,
    build_xaman_testnet_protocol_report,
    detect_solver,
    run_proverif_check,
    run_tamarin_check,
    solver_version,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _load_json_if_present(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return _load_json(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def generate(
    repo_root: Path,
    *,
    tamarin_executable: str | None = None,
    proverif_executable: str | None = None,
    run_solver: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    tamarin_path = repo_root / TAMARIN_ARTIFACT_PATH
    proverif_path = repo_root / PROVERIF_ARTIFACT_PATH
    report_path = repo_root / PROTOCOL_REPORT_PATH
    tamarin_path.parent.mkdir(parents=True, exist_ok=True)
    tamarin_path.write_text(XAMAN_TESTNET_PAYLOAD_SPTHY, encoding='utf-8')
    proverif_path.write_text(XAMAN_TESTNET_PAYLOAD_PV, encoding='utf-8')

    tamarin = tamarin_executable or detect_solver(
        'tamarin-prover',
        install_if_missing=run_solver,
        reason='Xaman Testnet Tamarin protocol execution',
    )
    proverif = proverif_executable or detect_solver(
        'proverif',
        install_if_missing=run_solver,
        reason='Xaman Testnet ProVerif protocol execution',
    )
    proverif_source = proverif_path.read_text(encoding='utf-8')
    tamarin_run = None
    proverif_run = None
    if run_solver and tamarin is not None:
        tamarin_run = run_tamarin_check(
            tamarin_path=tamarin_path,
            tamarin_executable=tamarin,
            timeout_seconds=timeout_seconds,
        )
    if run_solver and proverif is not None and proverif_path.is_file():
        proverif_run = run_proverif_check(
            proverif_path=proverif_path,
            proverif_executable=proverif,
            timeout_seconds=timeout_seconds,
        )

    report = build_xaman_testnet_protocol_report(
        model_payload=_load_json(repo_root / MODEL_PATH),
        model_cid=(repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip(),
        trace_map_payload=_load_json(repo_root / TRACE_MAP_PATH),
        assumptions_payload=_load_json(repo_root / ASSUMPTIONS_PATH),
        tamarin_source=tamarin_path.read_text(encoding='utf-8'),
        tamarin_executable=tamarin,
        tamarin_version=solver_version(tamarin),
        tamarin_run=tamarin_run,
        proverif_executable=proverif,
        proverif_version=solver_version(proverif),
        proverif_model_source=proverif_source,
        proverif_run=proverif_run,
        fuzz_counterexample_manifest=_load_json_if_present(repo_root / FUZZ_COUNTEREXAMPLE_MANIFEST_PATH),
    )
    _write_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_ir_artifacts.')
    parser.add_argument('--tamarin-executable', default=None, help='Optional explicit tamarin-prover executable.')
    parser.add_argument('--proverif-executable', default=None, help='Optional explicit proverif executable.')
    parser.add_argument('--run-solver', action='store_true', help='Invoke available protocol solvers.')
    parser.add_argument('--timeout-seconds', type=int, default=120, help='Per-solver timeout.')
    args = parser.parse_args(argv)

    report = generate(
        Path(args.repo_root).resolve(),
        tamarin_executable=args.tamarin_executable,
        proverif_executable=args.proverif_executable,
        run_solver=args.run_solver,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                'tamarin_path': TAMARIN_ARTIFACT_PATH,
                'protocol_report_path': PROTOCOL_REPORT_PATH,
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'unsupported_semantic_count': report['summary']['unsupported_semantic_count'],
                'unavailable_protocol_solver_blocks_testnet_assurance': report['coverage_decision'][
                    'unavailable_protocol_solver_blocks_testnet_assurance'
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
