#!/usr/bin/env python3
"""Probe a redacted Android host readiness record for native-vault testing."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_android_preflight import (  # noqa: E402
    AVD_NAME,
    AndroidHostPreflightError,
    probe_android_host,
)


DEFAULT_OUT = Path('security_ir_artifacts/corpora/xaman-app/runtime/native-vault-android-host-preflight.json')


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def _resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root.')
    parser.add_argument('--android-sdk', default=os.environ.get('ANDROID_SDK_ROOT', ''), help='Explicit Android SDK root.')
    parser.add_argument('--java-home', default=os.environ.get('JAVA_HOME', ''), help='Optional locked JDK root for sdkmanager.')
    parser.add_argument('--avd-home', default=str(Path.home() / '.android/avd'), help='AVD home directory.')
    parser.add_argument('--avd-name', default=AVD_NAME, help='Expected API-34 verifier AVD name.')
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='Redacted preflight artifact path.')
    args = parser.parse_args(argv)
    if not args.android_sdk:
        parser.error('--android-sdk or ANDROID_SDK_ROOT is required')
    root = Path(args.repo_root).resolve()
    try:
        report = probe_android_host(
            android_sdk=_resolve(root, args.android_sdk),
            avd_home=_resolve(root, args.avd_home),
            avd_name=args.avd_name,
            java_home=_resolve(root, args.java_home) if args.java_home else None,
        )
    except AndroidHostPreflightError as exc:
        parser.error(str(exc))
    out = _resolve(root, args.out)
    _write_json(out, report)
    print(json.dumps({
        'artifact_cid': report['artifact_cid'],
        'out': str(out.relative_to(root)) if out.is_relative_to(root) else str(out),
        'security_decision': report['security_decision'],
    }, sort_keys=True))
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
