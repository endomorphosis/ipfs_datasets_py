#!/usr/bin/env python3
"""Run a fail-closed crypto-exchange security assurance baseline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import (  # noqa: E402
    main as prove_all_main,
)
from scripts.ops.security_verification.run_security_ir_disproof_suite import (  # noqa: E402
    main as disproof_main,
)

INPUT_FIELDS = ('example', 'model', 'source_path')
PROOF_DOMAINS = (
    'withdrawals',
    'ledger',
    'deposits',
    'capabilities',
    'hsm',
    'audit',
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _z3_version() -> str | None:
    if importlib.util.find_spec('z3') is None:
        return None
    import z3

    return str(getattr(z3, 'get_full_version', lambda: 'unknown')())


def _input_args(args: argparse.Namespace) -> list[str]:
    if args.model:
        return ['--model', args.model]
    if args.source_path:
        values = ['--source-path', args.source_path]
        if args.source_model_id:
            values.extend(['--source-model-id', args.source_model_id])
        return values
    return ['--example']


def _proof_args(args: argparse.Namespace, proof_path: Path, counterexamples_dir: Path) -> list[str]:
    values = [
        *_input_args(args),
        '--strict-validation',
        '--explain-soundness',
        '--fail-on',
        'disproof',
        '--fail-on',
        'unknown-critical',
        '--fail-on',
        'not-modeled-critical',
        '--require-reviewed-evidence',
        '--release-gate',
        '--require-current-assumptions',
        '--require-real-ergoai',
        '--forbid-simulated-zkp',
        '--min-modeled-blocking-claims',
        str(args.min_modeled_blocking_claims),
        '--min-proved-blocking-claims',
        str(args.min_proved_blocking_claims),
        '--emit-counterexamples-dir',
        str(counterexamples_dir),
        '--out',
        str(proof_path),
    ]
    for domain in PROOF_DOMAINS:
        values.extend(['--require-domain', domain])
    return values


def _disproof_args(args: argparse.Namespace, disproof_path: Path) -> list[str]:
    return [
        *_input_args(args),
        '--fuzz-rounds',
        str(args.fuzz_rounds),
        '--seed',
        str(args.seed),
        '--out',
        str(disproof_path),
    ]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _claim_table(reports: list[dict[str, Any]]) -> str:
    lines = [
        '| Claim | Status | Risk | Assumptions |',
        '| --- | --- | --- | --- |',
    ]
    for report in reports:
        assumptions = ','.join(str(item) for item in report.get('assumptions', []))
        lines.append(
            '| `{}` | `{}` | `{}` | `{}` |'.format(
                report.get('claim_id', ''),
                report.get('status', ''),
                report.get('risk', ''),
                assumptions,
            )
        )
    return '\n'.join(lines)


def _render_summary(
    *,
    generated_at: str,
    z3_version: str,
    args: argparse.Namespace,
    proof_path: Path,
    disproof_path: Path,
    proof_payload: dict[str, Any],
    disproof_payload: dict[str, Any],
) -> str:
    coverage = proof_payload.get('coverage', {})
    release_gate = proof_payload.get('release_gate', {})
    gate_summary = release_gate.get('gates', {}) if isinstance(release_gate, dict) else {}
    assumption_registry = proof_payload.get('assumption_registry', {})
    assumption_summary = assumption_registry.get('summary', {}) if isinstance(assumption_registry, dict) else {}
    disproof_summary = disproof_payload.get('summary', {})
    reports = proof_payload.get('reports', [])
    if not isinstance(reports, list):
        reports = []
    input_label = args.model or args.source_path or 'built-in example'
    lines = [
        '# Crypto Exchange Assurance Baseline',
        '',
        f'Generated: {generated_at}',
        '',
        '## Environment',
        '',
        f'- Python: `{sys.executable}`',
        f'- Z3 Python bindings: `{z3_version}`',
        f'- Model input: `{input_label}`',
        f'- Proof report: `{proof_path}`',
        f'- Disproof report: `{disproof_path}`',
        '',
        '## Proof Coverage',
        '',
        f'- Total claims: `{coverage.get("total_claims", 0)}`',
        f'- Proved: `{coverage.get("proved", 0)}`',
        f'- Disproved: `{coverage.get("disproved", 0)}`',
        f'- Unknown: `{coverage.get("unknown", 0)}`',
        f'- Not modeled: `{coverage.get("not_modeled", 0)}`',
        f'- Blocking claims: `{coverage.get("blocking_claims", 0)}`',
        f'- Blocking modeled: `{coverage.get("blocking_modeled", 0)}`',
        f'- Blocking proved: `{coverage.get("blocking_proved", 0)}`',
        '',
        _claim_table(reports),
        '',
        '## Release Gate',
        '',
        f'- Release ready: `{release_gate.get("release_ready", "not reported") if isinstance(release_gate, dict) else "not reported"}`',
        f'- Blocking accepted: `{gate_summary.get("blocking", {}).get("accepted", 0)}/{gate_summary.get("blocking", {}).get("total", 0)}`',
        f'- High accepted: `{gate_summary.get("high", {}).get("accepted", 0)}/{gate_summary.get("high", {}).get("total", 0)}`',
        f'- Medium accepted: `{gate_summary.get("medium", {}).get("accepted", 0)}/{gate_summary.get("medium", {}).get("total", 0)}`',
        f'- Failures: `{len(release_gate.get("failures", [])) if isinstance(release_gate, dict) else 0}`',
        f'- Attention items: `{len(release_gate.get("attention", [])) if isinstance(release_gate, dict) else 0}`',
        '',
        '## Assumption Registry',
        '',
        f'- Assumption evidence ready: `{assumption_registry.get("release_ready", "not reported") if isinstance(assumption_registry, dict) else "not reported"}`',
        f'- Required assumptions: `{assumption_summary.get("total", 0)}`',
        f'- Owned: `{assumption_summary.get("owned", 0)}/{assumption_summary.get("total", 0)}`',
        f'- Evidenced: `{assumption_summary.get("evidenced", 0)}/{assumption_summary.get("total", 0)}`',
        f'- Current: `{assumption_summary.get("current", 0)}/{assumption_summary.get("total", 0)}`',
        f'- Stale: `{assumption_summary.get("stale", 0)}`',
        f'- Failures: `{len(assumption_registry.get("failures", [])) if isinstance(assumption_registry, dict) else 0}`',
        '',
        '## Disproof Coverage',
        '',
        f'- Seed: `{disproof_payload.get("seed", args.seed)}`',
        f'- Scenario count: `{disproof_summary.get("scenario_count", 0)}`',
        f'- Scenario failures: `{disproof_summary.get("scenario_failures", 0)}`',
        f'- Total disproved claims: `{disproof_summary.get("total_disproved_claims", 0)}`',
        '',
        '## Soundness Boundary',
        '',
        'This baseline covers the implemented bounded Z3/IR verifier for the selected model input. '
        'It does not prove a production exchange secure unless the input facts are complete, reviewed, '
        'and tied to the deployed code and environment.',
        '',
        'Treat any future `DISPROVED`, blocking `UNKNOWN`, blocking `NOT_MODELED`, missing Z3, '
        'simulated proof dependency, stale model CID, stale assumption evidence, or unreviewed blocking evidence as non-secure.',
    ]
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', action='store_true', help='Use the built-in example model')
    parser.add_argument('--model', help='Path to a canonical security model JSON file')
    parser.add_argument('--source-path', help='Supported source file or directory to autoformalize before proving')
    parser.add_argument('--source-model-id', help='Optional model_id override when using --source-path')
    parser.add_argument('--out-dir', default='security_ir_artifacts', help='Directory for generated assurance artifacts')
    parser.add_argument('--proof-report-name', default='proof-baseline.json', help='Proof report filename inside --out-dir')
    parser.add_argument('--disproof-report-name', default='disproof-baseline.json', help='Disproof report filename inside --out-dir')
    parser.add_argument('--summary-name', default='assurance-baseline.md', help='Markdown summary filename inside --out-dir')
    parser.add_argument('--fuzz-rounds', type=int, default=8, help='Deterministic bounded mutation-fuzz rounds')
    parser.add_argument('--seed', type=int, default=7, help='Seed for deterministic fuzzed mutation selection')
    parser.add_argument('--min-modeled-blocking-claims', type=int, default=3)
    parser.add_argument('--min-proved-blocking-claims', type=int, default=3)
    args = parser.parse_args(argv)

    if sum(bool(getattr(args, field_name)) for field_name in INPUT_FIELDS) > 1:
        parser.error('choose only one input: --example, --model, or --source-path')
    if args.fuzz_rounds < 0:
        parser.error('--fuzz-rounds must be non-negative')

    z3_version = _z3_version()
    if z3_version is None:
        print('error: z3-solver is required for the assurance baseline', file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    proof_path = out_dir / args.proof_report_name
    disproof_path = out_dir / args.disproof_report_name
    summary_path = out_dir / args.summary_name
    counterexamples_dir = out_dir / 'counterexamples'

    proof_rc = prove_all_main(_proof_args(args, proof_path, counterexamples_dir))
    if proof_rc != 0:
        print(f'error: proof baseline failed with exit code {proof_rc}', file=sys.stderr)
        return proof_rc

    disproof_rc = disproof_main(_disproof_args(args, disproof_path))
    if disproof_rc != 0:
        print(f'error: disproof baseline failed with exit code {disproof_rc}', file=sys.stderr)
        return disproof_rc

    proof_payload = _load_json(proof_path)
    disproof_payload = _load_json(disproof_path)
    summary_path.write_text(
        _render_summary(
            generated_at=_utc_now(),
            z3_version=z3_version,
            args=args,
            proof_path=proof_path,
            disproof_path=disproof_path,
            proof_payload=proof_payload,
            disproof_payload=disproof_payload,
        ),
        encoding='utf-8',
    )
    print(f'wrote proof report: {proof_path}')
    print(f'wrote disproof report: {disproof_path}')
    print(f'wrote assurance summary: {summary_path}')
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
