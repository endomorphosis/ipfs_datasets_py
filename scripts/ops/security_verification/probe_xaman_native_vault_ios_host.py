#!/usr/bin/env python3
"""Probe a redacted iOS/XCTest host readiness record for Xaman native-vault testing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_ios_preflight import (  # noqa: E402
    IOSHostPreflightError,
    probe_ios_host,
)


DEFAULT_OUT = Path('security_ir_artifacts/corpora/xaman-app/runtime/native-vault-ios-host-preflight.json')
DEFAULT_SOURCE_ROOT = Path.home() / '.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app'


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def _resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root.')
    parser.add_argument('--source-root', default=str(DEFAULT_SOURCE_ROOT), help='Explicit Xaman source root.')
    parser.add_argument('--xcodebuild', default='/usr/bin/xcodebuild', help='Explicit xcodebuild binary.')
    parser.add_argument('--xcrun', default='/usr/bin/xcrun', help='Explicit xcrun binary.')
    parser.add_argument(
        '--emit-blocked-artifact',
        action='store_true',
        help='Write a deterministic blocked artifact when host preconditions are unavailable.',
    )
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='Redacted preflight artifact path.')
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    try:
        report = probe_ios_host(
            xcodebuild=_resolve(root, args.xcodebuild),
            xcrun=_resolve(root, args.xcrun),
            source_root=_resolve(root, args.source_root),
            emit_blocked_artifact=args.emit_blocked_artifact,
        )
    except IOSHostPreflightError as exc:
        parser.error(str(exc))
    out = _resolve(root, args.out)
    _write_json(out, report)
    print(
        json.dumps(
            {
                'artifact_cid': report['artifact_cid'],
                'out': str(out.relative_to(root)) if out.is_relative_to(root) else str(out),
                'security_decision': report['security_decision'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
