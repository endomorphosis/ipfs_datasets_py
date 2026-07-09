#!/usr/bin/env python3
"""Generate Xaman mutation disproof vectors and counterexample report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_disproof_suite import (  # noqa: E402,E501
    MODEL_CID_PATH,
    MODEL_PATH,
    build_xaman_disproof_artifacts,
)


CORPUS_DIR = Path('security_ir_artifacts/corpora/xaman-app')
DISPROOF_VECTORS_PATH = CORPUS_DIR / 'disproof-vectors.json'
COUNTEREXAMPLE_REPORT_PATH = CORPUS_DIR / 'counterexample-report.json'


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def generate(repo_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    model_payload = json.loads((repo_root / MODEL_PATH).read_text(encoding='utf-8'))
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    vectors, report = build_xaman_disproof_artifacts(
        model_payload,
        model_cid=model_cid,
    )
    _write_json(repo_root / DISPROOF_VECTORS_PATH, vectors)
    _write_json(repo_root / COUNTEREXAMPLE_REPORT_PATH, report)
    return vectors, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        default=str(ROOT_DIR),
        help='Repository root containing security_ir_artifacts.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    vectors, report = generate(repo_root)
    print(
        'Wrote '
        f'{DISPROOF_VECTORS_PATH} '
        f'({vectors["summary"]["vector_count"]} vectors, '
        f'{report["summary"]["counterexample_count"]} counterexamples, '
        f'{report["summary"]["explicitly_blocked_count"]} blocked)'
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
