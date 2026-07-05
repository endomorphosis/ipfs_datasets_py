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


def _load_model(args: argparse.Namespace) -> SecurityModelIR:
    if args.example or not args.model:
        return example_minimal_exchange_model()
    payload = json.loads(Path(args.model).read_text(encoding='utf-8'))
    return validate_ir(SecurityModelIR.from_dict(payload))


def prove_claims(model: SecurityModelIR, provers: Iterable[str]) -> list[ProofReport]:
    reports: list[ProofReport] = []
    selected_provers = list(provers) or ['z3']
    for claim in default_claims():
        for prover_name in selected_provers:
            runner_factory = RUNNER_FACTORIES[prover_name]
            runner = runner_factory()
            report = runner.run_claim(claim, model)
            if prover_name == 'z3' or report.status in {'PROVED', 'DISPROVED', 'NOT_MODELED'}:
                reports.append(report)
                break
        else:
            reports.append(ProofReport(
                claim_id=claim.claim_id,
                model_cid='',
                status='UNKNOWN',
                prover='none',
                proof_or_trace_cid='',
                assumptions=list(claim.required_assumptions),
                compiler_cid='',
                counterexample={'reason': 'no prover selected'},
                risk=claim.severity,
                signatures=[],
            ))
    return reports


def _should_fail(report: ProofReport, *, strict: bool, fail_on_unknown_critical: bool) -> bool:
    if report.status == 'DISPROVED' and report.risk in {'blocking', 'high'}:
        return strict
    if report.status == 'UNKNOWN' and report.risk == 'blocking' and fail_on_unknown_critical and strict:
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run crypto exchange security claims.')
    parser.add_argument('--example', action='store_true', help='Use the built-in example security model')
    parser.add_argument('--model', help='Path to a canonical security model JSON file')
    parser.add_argument('--out', help='Path to write proof reports as JSON')
    parser.add_argument('--strict', action='store_true', help='Return nonzero on critical DISPROVED results')
    parser.add_argument('--fail-on-unknown-critical', action='store_true', help='Treat blocking UNKNOWN results as failures in strict mode')
    parser.add_argument('--provers', default='z3,tla,datalog,tamarin,hyperltl,lean,coq', help='Comma-separated prover list')
    args = parser.parse_args(argv)
    model = _load_model(args)
    provers = [item.strip() for item in args.provers.split(',') if item.strip()]
    reports = prove_claims(model, provers)
    payload = {'model_id': model.model_id, 'reports': [report.to_dict() for report in reports]}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if any(_should_fail(report, strict=args.strict, fail_on_unknown_critical=args.fail_on_unknown_critical) for report in reports) else 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
