#!/usr/bin/env python3
"""Build a ranked proof-lane remediation matrix from counterexample/fuzz triage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_counterexample_triage import (  # noqa: E402
    build_gap_remediation_matrix,
)


TRIAGE_PATH = Path('security_ir_artifacts/corpora/xaman-app/counterexample-triage.json')
OUTPUT_PATH = Path('security_ir_artifacts/corpora/xaman-app/gap-remediation-matrix.json')


def _load(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'expected JSON object: {path}')
    return payload


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root.')
    parser.add_argument('--triage', default=str(TRIAGE_PATH), help='Input triage report path.')
    parser.add_argument('--out', default=str(OUTPUT_PATH), help='Output remediation matrix path.')
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    triage_path = Path(args.triage)
    out_path = Path(args.out)
    if not triage_path.is_absolute():
        triage_path = root / triage_path
    if not out_path.is_absolute():
        out_path = root / out_path

    triage = _load(triage_path)
    report = build_gap_remediation_matrix(triage_report=triage)
    _write(out_path, report)
    print(
        json.dumps(
            {
                'artifact_path': str(out_path.relative_to(root)) if out_path.is_relative_to(root) else str(out_path),
                'overall_status': report['overall_status'],
                'matrix_entry_count': report['summary']['entry_count'],
                'required_task_count': report['summary']['required_task_count'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
