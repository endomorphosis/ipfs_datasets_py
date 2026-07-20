#!/usr/bin/env python3
"""Prepare the non-evidence Xaman native-vault fault-injection contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_fault_injection import (  # noqa: E402
    NativeVaultFaultInjectionError,
    build_fault_injection_plan,
    build_fault_injection_template,
    validate_fault_injection_report,
)


DEFAULT_ASSESSMENT = Path('security_ir_artifacts/corpora/xaman-app/native-vault-public-source-assessment.json')
DEFAULT_PLAN = Path('security_ir_artifacts/corpora/xaman-app/native-vault/fault-injection-plan.json')
DEFAULT_TEMPLATE = Path('security_ir_artifacts/corpora/xaman-app/runtime/native-vault-rekey-fault-injection-template.json')


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'expected JSON object: {path}')
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def _resolve(root: Path, raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else root / path


def _label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root.')
    parser.add_argument('--assessment', default=str(DEFAULT_ASSESSMENT), help='Native-vault assessment JSON.')
    parser.add_argument('--plan-out', default=str(DEFAULT_PLAN), help='Prepared plan output path.')
    parser.add_argument('--template-out', default=str(DEFAULT_TEMPLATE), help='Non-evidence template output path.')
    parser.add_argument('--validate-report', help='Validate an already reviewed runtime report; does not execute tests.')
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    if args.validate_report:
        try:
            validate_fault_injection_report(_load_json(_resolve(root, args.validate_report)))
        except (NativeVaultFaultInjectionError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps({'report_path': str(args.validate_report), 'validation': 'passed'}, sort_keys=True))
        return 0

    try:
        plan = build_fault_injection_plan(_load_json(_resolve(root, args.assessment)))
        template = build_fault_injection_template(plan)
    except (NativeVaultFaultInjectionError, ValueError) as exc:
        parser.error(str(exc))
    plan_path = _resolve(root, args.plan_out)
    template_path = _resolve(root, args.template_out)
    _write_json(plan_path, plan)
    _write_json(template_path, template)
    print(json.dumps({
        'plan_cid': plan['artifact_cid'],
        'plan_path': _label(plan_path, root),
        'template_path': _label(template_path, root),
        'template_status': template['template_status'],
    }, sort_keys=True))
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
