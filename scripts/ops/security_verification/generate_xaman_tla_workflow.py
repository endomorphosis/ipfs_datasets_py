#!/usr/bin/env python3
"""Generate Xaman TLA+/Apalache workflow artifacts."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_tla_workflow import (
    APALACHE_REPORT_PATH,
    TLA_ARTIFACT_PATH,
    XAMAN_SIGNING_TLA,
    build_xaman_tla_workflow_report,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
MODEL_CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
LIFECYCLE_FACTS_PATH = CORPUS_DIR / 'payload-lifecycle-facts.json'


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _apalache_version(executable: str | None) -> str | None:
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, 'version'],
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
    tla_path = REPO_ROOT / TLA_ARTIFACT_PATH
    report_path = REPO_ROOT / APALACHE_REPORT_PATH
    tla_path.parent.mkdir(parents=True, exist_ok=True)

    tla_path.write_text(f'{XAMAN_SIGNING_TLA}\n', encoding='utf-8')
    apalache_executable = shutil.which('apalache-mc') or shutil.which('apalache')
    report = build_xaman_tla_workflow_report(
        model_payload=_load_json(MODEL_PATH),
        model_cid=MODEL_CID_PATH.read_text(encoding='utf-8').strip(),
        lifecycle_facts=_load_json(LIFECYCLE_FACTS_PATH),
        tla_source=tla_path.read_text(encoding='utf-8').rstrip('\n'),
        apalache_executable=apalache_executable,
        apalache_version=_apalache_version(apalache_executable),
    )
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
