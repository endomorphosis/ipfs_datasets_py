#!/usr/bin/env python3
"""Run deterministic Xaman Testnet trace and input-space fuzz campaigns."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_fuzzing import (  # noqa: E402
    CAMPAIGN_MANIFEST_PATH,
    COUNTEREXAMPLE_DIR,
    FUZZ_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    TRACE_MAP_PATH,
    build_campaign_manifest,
    build_xaman_testnet_fuzz_report,
    counterexample_artifacts,
)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )


def generate(repo_root: Path) -> dict[str, object]:
    model_payload = _load_json(repo_root / MODEL_PATH)
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    trace_map_payload = _load_json(repo_root / TRACE_MAP_PATH)
    report = build_xaman_testnet_fuzz_report(
        model_payload,
        model_cid=model_cid,
        trace_map_payload=trace_map_payload,
    )

    counterexample_dir = repo_root / COUNTEREXAMPLE_DIR
    if counterexample_dir.exists():
        shutil.rmtree(counterexample_dir)
    for rel_path, artifact in counterexample_artifacts(report).items():
        _write_json(repo_root / rel_path, artifact)
    campaign_manifest = build_campaign_manifest(report)
    _write_json(repo_root / CAMPAIGN_MANIFEST_PATH, campaign_manifest)
    _write_json(repo_root / FUZZ_REPORT_PATH, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        default=str(ROOT_DIR),
        help='Repository root containing security_ir_artifacts.',
    )
    parser.add_argument(
        '--out',
        default=None,
        help='Optional output path for the generated counterexample manifest.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    report = generate(repo_root)
    if args.out is not None:
        out_path = (repo_root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out).resolve()
        manifest = _load_json(repo_root / COUNTEREXAMPLE_DIR / 'manifest.json')
        _write_json(out_path, manifest)
    print(
        json.dumps(
            {
                'campaign_manifest_path': CAMPAIGN_MANIFEST_PATH,
                'fuzz_report_path': FUZZ_REPORT_PATH,
                'counterexample_dir': COUNTEREXAMPLE_DIR,
                'overall_status': report['summary']['overall_status'],
                'total_case_count': report['summary']['total_case_count'],
                'counterexample_count': report['summary']['counterexample_count'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
