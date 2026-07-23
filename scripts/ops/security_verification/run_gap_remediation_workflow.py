#!/usr/bin/env python3
"""Build a prioritized execution manifest for gap-remediation lanes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_gap_remediation_workflow import (  # noqa: E402
    build_gap_remediation_execution_manifest,
)


MATRIX_PATH = Path('security_ir_artifacts/corpora/xaman-app/gap-remediation-matrix.json')
COUNTEREXAMPLE_REPORT_PATH = Path('security_ir_artifacts/corpora/xaman-app/counterexample-report.json')
FUZZ_REPORT_PATH = Path('security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json')
FUZZ_COUNTEREXAMPLE_MANIFEST_PATH = Path('security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json')
NATIVE_VAULT_STATE_FUZZ_PATH = Path('security_ir_artifacts/corpora/xaman-app/native-vault/rekey-state-fuzz-report.json')
OUTPUT_PATH = Path('security_ir_artifacts/corpora/xaman-app/testnet/fuzz/final-gap-remediation-manifest.json')


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'{path} does not contain a JSON object')
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def generate(
    repo_root: Path,
    *,
    matrix_path: Path = MATRIX_PATH,
    counterexample_report_path: Path = COUNTEREXAMPLE_REPORT_PATH,
    fuzz_report_path: Path = FUZZ_REPORT_PATH,
    fuzz_counterexample_manifest_path: Path = FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
    native_vault_state_fuzz_path: Path = NATIVE_VAULT_STATE_FUZZ_PATH,
    out_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    matrix = _load_json(repo_root / matrix_path)
    if matrix.get('task_id') != 'PORTAL-CXTP-170':
        raise ValueError('gap-remediation matrix input is not PORTAL-CXTP-170')

    counterexample_report = _load_json(repo_root / counterexample_report_path)
    fuzz_report = _load_json(repo_root / fuzz_report_path)
    fuzz_counterexample_manifest = _load_json(repo_root / fuzz_counterexample_manifest_path)
    native_vault_state_fuzz = _load_json(repo_root / native_vault_state_fuzz_path)

    manifest = build_gap_remediation_execution_manifest(
        gap_remediation_matrix=matrix,
        counterexample_report=counterexample_report,
        fuzz_report=fuzz_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
        native_vault_state_fuzz=native_vault_state_fuzz,
    )
    out = Path(out_path)
    if not out.is_absolute():
        out = repo_root / out
    _write_json(out, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_ir_artifacts.')
    parser.add_argument('--matrix', default=str(MATRIX_PATH), help='Gap-remediation matrix input path.')
    parser.add_argument('--counterexample-report', default=str(COUNTEREXAMPLE_REPORT_PATH), help='Counterexample report path.')
    parser.add_argument('--fuzz-report', default=str(FUZZ_REPORT_PATH), help='Xaman testnet fuzz report path.')
    parser.add_argument(
        '--fuzz-counterexample-manifest',
        default=str(FUZZ_COUNTEREXAMPLE_MANIFEST_PATH),
        help='Fuzz counterexample manifest path.',
    )
    parser.add_argument(
        '--native-vault-state-fuzz',
        default=str(NATIVE_VAULT_STATE_FUZZ_PATH),
        help='Native-vault rekey state-fuzz report path.',
    )
    parser.add_argument('--out', default=str(OUTPUT_PATH), help='Output remediation execution manifest path.')
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()

    def _normalize(path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else repo_root / p

    manifest = generate(
        repo_root=repo_root,
        matrix_path=_normalize(args.matrix),
        counterexample_report_path=_normalize(args.counterexample_report),
        fuzz_report_path=_normalize(args.fuzz_report),
        fuzz_counterexample_manifest_path=_normalize(args.fuzz_counterexample_manifest),
        native_vault_state_fuzz_path=_normalize(args.native_vault_state_fuzz),
        out_path=_normalize(args.out),
    )

    print(
        json.dumps(
            {
                'out': str(Path(args.out)),
                'overall_status': manifest['overall_status'],
                'entry_count': manifest['summary']['entry_count'],
                'ready_count': manifest['summary']['ready_count'],
                'blocked_count': manifest['summary']['blocked_count'],
            },
            sort_keys=True,
        ),
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
