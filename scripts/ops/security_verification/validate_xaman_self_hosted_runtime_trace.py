#!/usr/bin/env python3
"""Validate a reviewed, redacted Xaman self-hosted runtime-conformance trace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_self_hosted_runtime_trace import (  # noqa: E402
    SelfHostedRuntimeTraceError,
    build_runtime_conformance_report,
    build_trace_template,
    load_trace,
)


DEFAULT_TRACE = Path('security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/runtime-trace-review.json')
DEFAULT_OUT = Path('security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/runtime-conformance-report.json')
DEFAULT_TEMPLATE = Path('security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/runtime-trace-template.json')


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def _path_label(path: Path, root: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root.')
    parser.add_argument('--trace', default=str(DEFAULT_TRACE), help='Reviewed runtime-trace JSON.')
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='Redacted conformance report output.')
    parser.add_argument('--write-template', action='store_true', help='Write the non-evidence trace template and exit.')
    parser.add_argument('--template-out', default=str(DEFAULT_TEMPLATE), help='Template output path.')
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    if args.write_template:
        target = Path(args.template_out)
        if not target.is_absolute():
            target = root / target
        _write_json(target, build_trace_template())
        print(json.dumps({'template_path': _path_label(target, root), 'template_status': 'NOT_RUNTIME_EVIDENCE'}, sort_keys=True))
        return 0

    trace_path = Path(args.trace)
    if not trace_path.is_absolute():
        trace_path = root / trace_path
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    try:
        report = build_runtime_conformance_report(load_trace(str(trace_path)))
    except SelfHostedRuntimeTraceError as exc:
        parser.error(str(exc))
    _write_json(out, report)
    print(
        json.dumps(
            {
                'trace_path': _path_label(trace_path, root),
                'report_path': _path_label(out, root),
                'report_cid': report['artifact_cid'],
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
