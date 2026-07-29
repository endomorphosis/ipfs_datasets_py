#!/usr/bin/env python3
"""Generate Xaman Tamarin/ProVerif protocol projection artifacts."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_protocol_projection import (
    PROTOCOL_REPORT_PATH,
    TAMARIN_ARTIFACT_PATH,
    XAMAN_PAYLOAD_PROTOCOL_SPTHY,
    build_xaman_protocol_report,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
MODEL_CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
LIFECYCLE_FACTS_PATH = CORPUS_DIR / 'payload-lifecycle-facts.json'
WALLET_AUTH_FACTS_PATH = CORPUS_DIR / 'wallet-auth-facts.json'


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _solver_version(executable: str | None, args: list[str]) -> str | None:
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (completed.stdout or completed.stderr).strip()
    return output.splitlines()[0] if output else None


def main() -> int:
    tamarin_path = REPO_ROOT / TAMARIN_ARTIFACT_PATH
    report_path = REPO_ROOT / PROTOCOL_REPORT_PATH
    tamarin_path.parent.mkdir(parents=True, exist_ok=True)

    tamarin_path.write_text(f'{XAMAN_PAYLOAD_PROTOCOL_SPTHY}\n', encoding='utf-8')
    tamarin_executable = shutil.which('tamarin-prover')
    proverif_executable = shutil.which('proverif')
    report = build_xaman_protocol_report(
        model_payload=_load_json(MODEL_PATH),
        model_cid=MODEL_CID_PATH.read_text(encoding='utf-8').strip(),
        lifecycle_facts=_load_json(LIFECYCLE_FACTS_PATH),
        wallet_auth_facts=_load_json(WALLET_AUTH_FACTS_PATH),
        tamarin_source=tamarin_path.read_text(encoding='utf-8').rstrip('\n'),
        tamarin_executable=tamarin_executable,
        tamarin_version=_solver_version(tamarin_executable, ['--version']),
        proverif_executable=proverif_executable,
        proverif_version=_solver_version(proverif_executable, ['-version']),
    )
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
