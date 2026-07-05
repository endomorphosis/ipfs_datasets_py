"""CLI entrypoint for running exchange security claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .claims import default_claims
from .ir.examples import example_minimal_exchange_model
from .ir.schema import SecurityModelIR, validate_ir
from .reports.proof_report import ProofReport
from .runners.coq_runner import CoqRunner
from .runners.datalog_runner import DatalogRunner
from .runners.hyperltl_runner import HyperLTLRunner
from .runners.lean_runner import LeanRunner
from .runners.proverif_runner import ProVerifRunner
from .runners.tamarin_runner import TamarinRunner
from .runners.tla_runner import TLARunner
from .runners.z3_runner import Z3Runner


RUNNER_FACTORIES = {
    'z3': Z3Runner,
    'tla': TLARunner,
    'datalog': DatalogRunner,
    'tamarin': TamarinRunner,
    'proverif': ProVerifRunner,
    'hyperltl': HyperLTLRunner,
    'lean': LeanRunner,
    'coq': CoqRunner,
}

DEFAULT_PROVERS = ('z3', 'tla', 'datalog', 'tamarin', 'proverif', 'hyperltl', 'lean', 'coq')


def _normalize_provers(provers: Iterable[str]) -> list[str]:
    selected_provers = [item.strip() for item in provers if item.strip()]
    if not selected_provers:
        return ['z3']
    unsupported = sorted({prover_name for prover_name in selected_provers if prover_name not in RUNNER_FACTORIES})
    if unsupported:
        raise ValueError(f"Unsupported provers: {', '.join(unsupported)}")
    return selected_provers


def _load_model(args: argparse.Namespace) -> SecurityModelIR:
    if args.example or not args.model:
        return example_minimal_exchange_model()
    payload = json.loads(Path(args.model).read_text(encoding='utf-8'))
    return validate_ir(SecurityModelIR.from_dict(payload))


def prove_claims(model: SecurityModelIR, provers: Iterable[str]) -> list[ProofReport]:
    reports: list[ProofReport] = []
    selected_provers = _normalize_provers(provers)
    for claim in default_claims():
        prover_iter = iter(selected_provers)
        first_prover_name = next(prover_iter)
        first_runner = RUNNER_FACTORIES[first_prover_name]()
        last_report = first_runner.run_claim(claim, model)
        if last_report.status in {'PROVED', 'DISPROVED', 'NOT_MODELED'}:
            reports.append(last_report)
            continue
        for prover_name in prover_iter:
            runner_factory = RUNNER_FACTORIES[prover_name]
            runner = runner_factory()
            report = runner.run_claim(claim, model)
            last_report = report
            if report.status in {'PROVED', 'DISPROVED', 'NOT_MODELED'}:
                reports.append(report)
                break
        else:
            reports.append(last_report)
    return reports


def _should_fail(report: ProofReport, *, strict: bool, fail_on_unknown_critical: bool) -> bool:
    if not strict:
        return False
    if report.status == 'DISPROVED' and report.risk in {'blocking', 'high'}:
        return True
    if report.status == 'UNKNOWN' and report.risk == 'blocking' and fail_on_unknown_critical:
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run crypto exchange security claims.')
    parser.add_argument('--example', action='store_true', help='Use the built-in example security model')
    parser.add_argument('--model', help='Path to a canonical security model JSON file')
    parser.add_argument('--out', help='Path to write proof reports as JSON')
    parser.add_argument('--strict', action='store_true', help='Return nonzero on critical DISPROVED results')
    parser.add_argument('--fail-on-unknown-critical', action='store_true', help='Treat blocking UNKNOWN results as failures in strict mode')
    parser.add_argument('--provers', default=','.join(DEFAULT_PROVERS), help='Comma-separated prover list')
    args = parser.parse_args(argv)
    model = _load_model(args)
    try:
        provers = _normalize_provers(args.provers.split(','))
    except ValueError as exc:
        parser.error(str(exc))
    reports = prove_claims(model, provers)
    payload = {'model_id': model.model_id, 'reports': [report.to_dict() for report in reports]}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if any(_should_fail(report, strict=args.strict, fail_on_unknown_critical=args.fail_on_unknown_critical) for report in reports) else 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
