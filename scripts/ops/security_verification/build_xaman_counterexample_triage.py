#!/usr/bin/env python3
"""Build the Xaman source/model/runtime counterexample triage artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_counterexample_triage import (  # noqa: E402
    build_counterexample_triage,
)


COUNTEREXAMPLE_PATH = Path('security_ir_artifacts/corpora/xaman-app/counterexample-report.json')
FUZZ_PATH = Path('security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json')
TRANSACTION_COVERAGE_PATH = Path('security_ir_artifacts/corpora/xaman-app/xrpl-transaction-coverage.json')
NATIVE_VAULT_STATE_FUZZ_PATH = Path('security_ir_artifacts/corpora/xaman-app/native-vault/rekey-state-fuzz-report.json')
OUTPUT_PATH = Path('security_ir_artifacts/corpora/xaman-app/counterexample-triage.json')


def _load(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'expected JSON object: {path}')
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root.')
    parser.add_argument('--out', default=str(OUTPUT_PATH), help='Triage report path.')
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    report = build_counterexample_triage(
        counterexample_report=_load(root / COUNTEREXAMPLE_PATH),
        fuzz_report=_load(root / FUZZ_PATH),
        transaction_coverage=_load(root / TRANSACTION_COVERAGE_PATH),
        native_vault_state_fuzz=_load(root / NATIVE_VAULT_STATE_FUZZ_PATH),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')
    print(json.dumps({'report_path': str(out.relative_to(root)) if out.is_relative_to(root) else str(out), 'overall_status': report['overall_status'], 'entry_count': report['summary']['entry_count']}, sort_keys=True))
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
