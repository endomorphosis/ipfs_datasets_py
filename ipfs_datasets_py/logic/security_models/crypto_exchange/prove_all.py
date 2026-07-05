"""CLI entrypoint for running exchange security claims."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from .claims.base import SecurityClaim
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
FAIL_POLICIES = {'disproof', 'unknown-critical'}


def _normalize_provers(provers: Iterable[str]) -> list[str]:
    selected_provers = [item.strip() for item in provers if item.strip()]
    if not selected_provers:
        return ['z3']
    unsupported = sorted({prover_name for prover_name in selected_provers if prover_name not in RUNNER_FACTORIES})
    if unsupported:
        raise ValueError(f"Unsupported provers: {', '.join(unsupported)}")
    return selected_provers


def _normalize_fail_policies(values: Iterable[str]) -> set[str]:
    policies = {
        token.strip()
        for item in values
        for token in item.split(',')
        if token.strip()
    }
    unsupported = sorted(policy for policy in policies if policy not in FAIL_POLICIES)
    if unsupported:
        raise ValueError(f"Unsupported fail policies: {', '.join(unsupported)}")
    return policies


def _load_model(args: argparse.Namespace) -> SecurityModelIR:
    if args.example or not args.model:
        return example_minimal_exchange_model()
    payload = json.loads(Path(args.model).read_text(encoding='utf-8'))
    return validate_ir(SecurityModelIR.from_dict(payload))


def _no_prover_report(claim: SecurityClaim, model: SecurityModelIR) -> ProofReport:
    return ProofReport(
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
    )


def prove_claims(model: SecurityModelIR, provers: Iterable[str]) -> list[ProofReport]:
    reports: list[ProofReport] = []
    selected_provers = _normalize_provers(provers)
    for claim in default_claims():
        last_report = _no_prover_report(claim, model)
        for prover_name in selected_provers:
            runner_factory = RUNNER_FACTORIES[prover_name]
            runner = runner_factory()
            report = runner.run_claim(claim, model)
            last_report = report
            if report.status in {'PROVED', 'DISPROVED', 'NOT_MODELED'}:
                break
        reports.append(last_report)
    return reports


def _proof_dependency_mode(model: SecurityModelIR, key: str) -> str:
    proof_modes = model.metadata.get('proof_dependency_modes', {})
    if not isinstance(proof_modes, dict):
        return 'not-used'
    return str(proof_modes.get(key, 'not-used')).strip().lower()


def _execution_policy_violations(
    model: SecurityModelIR,
    *,
    require_real_ergoai: bool,
    forbid_simulated_zkp: bool,
) -> list[str]:
    violations: list[str] = []
    flogic_mode = _proof_dependency_mode(model, 'flogic')
    zkp_mode = _proof_dependency_mode(model, 'zkp')
    if require_real_ergoai and flogic_mode == 'simulated':
        violations.append('simulated F-logic dependencies are forbidden for this proof run')
    if require_real_ergoai and flogic_mode in {'required', 'real'}:
        from ipfs_datasets_py.logic.flogic.ergoai_wrapper import ERGOAI_AVAILABLE

        if not ERGOAI_AVAILABLE:
            violations.append(
                'real ErgoAI was required, but the model metadata indicates an F-logic dependency without an available ErgoAI binary'
            )
    if forbid_simulated_zkp and zkp_mode == 'simulated':
        violations.append('simulated ZKP dependencies are forbidden for this proof run')
    return violations


def _should_fail(report: ProofReport, *, fail_policies: set[str]) -> bool:
    if 'disproof' in fail_policies and report.status == 'DISPROVED' and report.risk in {'blocking', 'high'}:
        return True
    if 'unknown-critical' in fail_policies and report.status == 'UNKNOWN' and report.risk == 'blocking':
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run crypto exchange security claims.')
    parser.add_argument('--example', action='store_true', help='Use the built-in example security model')
    parser.add_argument('--model', help='Path to a canonical security model JSON file')
    parser.add_argument('--out', help='Path to write proof reports as JSON')
    parser.add_argument('--strict', action='store_true', help='Backward-compatible alias for --fail-on disproof')
    parser.add_argument('--fail-on-unknown-critical', action='store_true', help='Backward-compatible strict-mode alias for --fail-on unknown-critical')
    parser.add_argument('--fail-on', action='append', default=[], help='Repeatable failure policy; takes precedence over legacy strict flags: disproof, unknown-critical')
    parser.add_argument('--require-real-ergoai', action='store_true', help='Reject models that depend on simulated or unavailable ErgoAI/F-logic execution')
    parser.add_argument('--forbid-simulated-zkp', action='store_true', help='Reject models that depend on simulated ZKP execution')
    parser.add_argument('--provers', default=','.join(DEFAULT_PROVERS), help='Comma-separated prover list')
    args = parser.parse_args(argv)
    model = _load_model(args)
    try:
        provers = _normalize_provers(args.provers.split(','))
        fail_policies = _normalize_fail_policies(args.fail_on)
    except ValueError as exc:
        parser.error(str(exc))
    if args.strict:
        fail_policies.add('disproof')
        if args.fail_on_unknown_critical:
            fail_policies.add('unknown-critical')
    policy_violations = _execution_policy_violations(
        model,
        require_real_ergoai=args.require_real_ergoai,
        forbid_simulated_zkp=args.forbid_simulated_zkp,
    )
    if policy_violations:
        for violation in policy_violations:
            print(f'error: {violation}', file=sys.stderr)
        return 2
    reports = prove_claims(model, provers)
    payload = {'model_id': model.model_id, 'reports': [report.to_dict() for report in reports]}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if any(_should_fail(report, fail_policies=fail_policies) for report in reports) else 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
