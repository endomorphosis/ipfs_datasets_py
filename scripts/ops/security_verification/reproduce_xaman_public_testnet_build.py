#!/usr/bin/env python3
"""Record the locked Xaman Android Testnet public-build reproduction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_public_build_reproduction import (  # noqa: E402
    PUBLIC_BUILD_DOC_PATH,
    PUBLIC_BUILD_ENVIRONMENT_PATH,
    PUBLIC_BUILD_REPRODUCTION_PATH,
    generate_public_build_reproduction,
)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding='utf-8')


def generate(repo_root: Path, *, out: Path | None = None) -> tuple[dict[str, Any], dict[str, Any], str]:
    environment, reproduction, markdown = generate_public_build_reproduction(repo_root)
    _write_json(repo_root / PUBLIC_BUILD_ENVIRONMENT_PATH, environment)
    _write_json(out or (repo_root / PUBLIC_BUILD_REPRODUCTION_PATH), reproduction)
    _write_text(repo_root / PUBLIC_BUILD_DOC_PATH, markdown)
    return environment, reproduction, markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        default=str(ROOT_DIR),
        help='Repository root containing security_ir_artifacts.',
    )
    parser.add_argument(
        '--out',
        default=PUBLIC_BUILD_REPRODUCTION_PATH,
        help='Reproduction report output path. The environment JSON and markdown use their standard task paths.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    environment, reproduction, _markdown = generate(repo_root, out=out_path)
    print(
        json.dumps(
            {
                'environment_path': PUBLIC_BUILD_ENVIRONMENT_PATH,
                'environment_cid': environment['artifact_cid'],
                'reproduction_path': str(out_path.relative_to(repo_root) if out_path.is_relative_to(repo_root) else out_path),
                'reproduction_cid': reproduction['artifact_cid'],
                'overall_status': reproduction['overall_status'],
                'security_decision': reproduction['security_decision'],
                'doc_path': PUBLIC_BUILD_DOC_PATH,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
