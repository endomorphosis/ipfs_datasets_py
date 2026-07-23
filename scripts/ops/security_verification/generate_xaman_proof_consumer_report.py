#!/usr/bin/env python3
"""Generate the Xaman proof-consumer invariant report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_proof_consumer import (  # noqa: E402,E501
    ENVIRONMENT_PROBE_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PROOF_CONSUMER_REPORT_PATH,
    PROOF_KERNEL_PATH,
    build_xaman_proof_consumer_report,
)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def generate(repo_root: Path) -> dict[str, object]:
    model_payload = _load_json(repo_root / MODEL_PATH)
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    environment_probe = _load_json(repo_root / ENVIRONMENT_PROBE_PATH)
    lean_source = (repo_root / PROOF_KERNEL_PATH).read_text(encoding='utf-8')
    report = build_xaman_proof_consumer_report(
        model_payload=model_payload,
        model_cid=model_cid,
        environment_probe=environment_probe,
        lean_source=lean_source,
    )
    _write_json(repo_root / PROOF_CONSUMER_REPORT_PATH, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        default=str(ROOT_DIR),
        help='Repository root containing security_ir_artifacts.',
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    report = generate(repo_root)
    print(
        'Wrote '
        f'{PROOF_CONSUMER_REPORT_PATH} '
        f'({report["summary"]["accepted_fixture_count"]} accepted, '
        f'{report["summary"]["rejected_fixture_count"]} rejected, '
        f'artifact {report["artifact_cid"]})'
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
