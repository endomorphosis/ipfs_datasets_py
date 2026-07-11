"""CVC5 CLI-backed proof runner for exchange security claims."""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..claims.base import SecurityClaim
from ..compilers.to_smtlib import (
    SMTLIBCompilation,
    SMTLIB_LOGIC,
    XAMAN_CRITICAL_SEVERITIES,
    compile_claim_to_smtlib,
    compile_ir_claims_to_smtlib,
    emit_ir_smtlib_artifacts,
)
from ..ir.cid import calculate_artifact_cid, calculate_model_cid
from ..ir.schema import SecurityModelIR, evidence_review_statuses
from ..reports.proof_report import ProofReport
from ..runners.base import BaseSecurityRunner


_PREFERRED_CVC5_PATH = Path('/home/barberb/.local/bin/cvc5')
_ENV_CVC5_PATH = 'IPFS_DATASETS_PY_CVC5'
XAMAN_DIFFERENTIAL_SCHEMA_VERSION = 'xaman-z3-cvc5-differential/v1'
XAMAN_DIFFERENTIAL_CLASSIFICATIONS = ('proved', 'disproved', 'unknown', 'blocked')
SUPPORTED_SMTLIB_LOGICS = frozenset({SMTLIB_LOGIC})


@dataclass(frozen=True, slots=True)
class CVC5CLIResult:
    """Raw CVC5 process result normalized for proof-report mapping."""

    solver_result: str
    stdout: str
    stderr: str
    returncode: int | None
    reason_unknown: str | None = None


@dataclass(frozen=True, slots=True)
class SMTLIBSolverRun:
    """A normalized solver execution result for an SMT-LIB2 artifact."""

    prover: str
    solver_result: str
    stdout: str = ''
    stderr: str = ''
    returncode: int | None = None
    reason_unknown: str | None = None
    solver_version: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'prover': self.prover,
            'solver_result': self.solver_result,
            'stdout': self.stdout,
            'stderr': self.stderr,
            'returncode': self.returncode,
            'reason_unknown': self.reason_unknown,
            'solver_version': self.solver_version,
        }


class CVC5Runner(BaseSecurityRunner):
    """Evaluate SMT-LIB2 claim artifacts with the CVC5 command-line solver."""

    prover_name = 'cvc5'

    def __init__(self, timeout_ms: int = 5_000, executable: str | os.PathLike[str] | None = None) -> None:
        self.timeout_ms = timeout_ms
        self.executable = str(executable) if executable is not None else None

    @classmethod
    def executable_path(cls, explicit: str | os.PathLike[str] | None = None) -> str | None:
        """Return the CVC5 executable, preferring the task-required local path."""

        if explicit is not None:
            candidate = str(explicit)
            resolved = shutil.which(candidate) if os.path.basename(candidate) == candidate else candidate
            if resolved and os.path.isfile(resolved) and os.access(resolved, os.X_OK):
                return resolved
            return None

        candidates: list[str] = []
        env_path = os.environ.get(_ENV_CVC5_PATH)
        if env_path:
            candidates.append(env_path)
        candidates.append(str(_PREFERRED_CVC5_PATH))
        discovered = shutil.which('cvc5')
        if discovered:
            candidates.append(discovered)

        for candidate in candidates:
            resolved = shutil.which(candidate) if os.path.basename(candidate) == candidate else candidate
            if resolved and os.path.isfile(resolved) and os.access(resolved, os.X_OK):
                return resolved
        if explicit is None:
            from ipfs_datasets_py.logic.external_provers.lazy_installer import (
                ensure_prover_executable,
            )

            return ensure_prover_executable(
                'cvc5',
                reason='CVC5 SMT-LIB differential execution',
            )
        return None

    def _executable_path(self) -> str | None:
        return self.executable_path(self.executable)

    @classmethod
    def is_available(cls) -> bool:
        return cls.executable_path() is not None

    def _solver_version(self) -> str:
        executable = self._executable_path()
        if not executable:
            return ''
        try:
            completed = subprocess.run(
                [executable, '--version'],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ''
        output = (completed.stdout or completed.stderr).strip().splitlines()
        return output[0] if output else ''

    def _run_cli(self, artifact: SMTLIBCompilation) -> CVC5CLIResult:
        executable = self._executable_path()
        if executable is None:
            return CVC5CLIResult(
                solver_result='unavailable',
                stdout='',
                stderr='',
                returncode=None,
                reason_unknown=(
                    'cvc5 executable not found: expected /home/barberb/.local/bin/cvc5, '
                    f'{_ENV_CVC5_PATH}, or a cvc5 executable on PATH'
                ),
            )

        timeout_seconds = max(self.timeout_ms, 1) / 1000
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.smt2', delete=False) as handle:
            handle.write(artifact.smtlib)
            smtlib_path = handle.name
        try:
            try:
                completed = subprocess.run(
                    [executable, '--lang', 'smt2', smtlib_path],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                return CVC5CLIResult(
                    solver_result='timeout',
                    stdout=exc.stdout.decode('utf-8', errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or ''),
                    stderr=exc.stderr.decode('utf-8', errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or ''),
                    returncode=None,
                    reason_unknown=f'cvc5 timed out after {self.timeout_ms} ms',
                )
            except OSError as exc:
                return CVC5CLIResult(
                    solver_result='unavailable',
                    stdout='',
                    stderr=str(exc),
                    returncode=None,
                    reason_unknown=f'cvc5 executable could not be run: {exc}',
                )
        finally:
            Path(smtlib_path).unlink(missing_ok=True)

        stdout = completed.stdout or ''
        stderr = completed.stderr or ''
        if completed.returncode != 0:
            solver_result = self._classify_error(stderr or stdout)
            return CVC5CLIResult(
                solver_result=solver_result,
                stdout=stdout,
                stderr=stderr,
                returncode=completed.returncode,
                reason_unknown=f'cvc5 exited with code {completed.returncode}: {(stderr or stdout).strip()}',
            )

        parsed = self._parse_solver_result(stdout)
        if parsed in {'sat', 'unsat', 'unknown'}:
            return CVC5CLIResult(
                solver_result=parsed,
                stdout=stdout,
                stderr=stderr,
                returncode=completed.returncode,
                reason_unknown='cvc5 returned unknown' if parsed == 'unknown' else None,
            )
        solver_result = self._classify_error(stderr or stdout)
        if solver_result == 'error':
            solver_result = 'parser_error'
        return CVC5CLIResult(
            solver_result=solver_result,
            stdout=stdout,
            stderr=stderr,
            returncode=completed.returncode,
            reason_unknown=f'cvc5 output did not contain a SAT/UNSAT/UNKNOWN result: {stdout.strip()}',
        )

    def run_smtlib_artifact(self, artifact: SMTLIBCompilation) -> SMTLIBSolverRun:
        """Run a precompiled SMT-LIB artifact and return a normalized result."""

        result = self._run_cli(artifact)
        return SMTLIBSolverRun(
            prover=self.prover_name,
            solver_result=result.solver_result,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            reason_unknown=result.reason_unknown,
            solver_version=self._solver_version(),
        )

    @staticmethod
    def _parse_solver_result(stdout: str) -> str:
        for raw_line in stdout.replace('\r\n', '\n').replace('\r', '\n').splitlines():
            line = raw_line.strip().lower()
            if line in {'sat', 'unsat', 'unknown'}:
                return line
        return ''

    @staticmethod
    def _classify_error(output: str) -> str:
        lowered = output.lower()
        if 'unsupported' in lowered:
            return 'unsupported'
        if 'parse' in lowered or 'parser' in lowered or 'syntax' in lowered:
            return 'parser_error'
        return 'error'

    def _report(
        self,
        claim: SecurityClaim,
        model: SecurityModelIR,
        artifact: SMTLIBCompilation,
        *,
        status: str,
        solver_result: str,
        proof_or_trace_cid: str,
        counterexample: dict[str, Any] | None,
        reason_unknown: str | None = None,
        stdout: str = '',
        stderr: str = '',
        returncode: int | None = None,
    ) -> ProofReport:
        soundness_notes = list(artifact.metadata.get('soundness_notes', []))
        evidence_refs = list(artifact.metadata.get('evidence_refs', []))
        if claim.severity == 'blocking' and 'heuristic' in evidence_review_statuses(evidence_refs):
            soundness_notes.append('Blocking proof depends on heuristic evidence and should not be treated as production-grade without review.')
        if status == 'UNKNOWN':
            soundness_notes.append('CVC5 did not discharge this claim; blocking and high-risk release gates must treat it as fail-closed.')

        if counterexample is not None:
            counterexample.setdefault('cvc5_stdout', stdout)
            counterexample.setdefault('cvc5_stderr', stderr)
            counterexample.setdefault('cvc5_returncode', returncode)
            counterexample.setdefault('smtlib_artifact_cid', artifact.artifact_cid)
            counterexample.setdefault('compiler_artifact_cid', artifact.metadata.get('compiler_artifact_cid'))

        return ProofReport(
            claim_id=claim.claim_id,
            claim_version=claim.claim_version,
            model_cid=artifact.model_cid,
            model_schema_version=artifact.model_schema_version,
            status=status,  # type: ignore[arg-type]
            prover=self.prover_name,
            solver_name=self.prover_name,
            solver_version=self._solver_version(),
            solver_result=solver_result,
            timeout_ms=self.timeout_ms,
            reason_unknown=reason_unknown,
            proof_or_trace_cid=proof_or_trace_cid,
            assumptions=list(claim.required_assumptions),
            compiler_cid=artifact.artifact_cid,
            counterexample=counterexample,
            risk=claim.severity,  # type: ignore[arg-type]
            signatures=[],
            assertion_count=int(artifact.metadata.get('assertion_count', 0)),
            evidence_refs=evidence_refs,
            soundness_notes=soundness_notes,
        )

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR) -> ProofReport:
        artifact = compile_claim_to_smtlib(claim, model)
        if not artifact.modeled:
            reason = artifact.not_modeled_reason or 'claim is not modeled for SMT-LIB2'
            return self._report(
                claim,
                model,
                artifact,
                status='NOT_MODELED',
                solver_result='not-modeled',
                proof_or_trace_cid='',
                counterexample={'reason': reason, 'smtlib_artifact_cid': artifact.artifact_cid},
                reason_unknown=reason,
            )

        result = self._run_cli(artifact)
        if result.solver_result == 'unsat':
            proof_payload = {
                'claim_id': claim.claim_id,
                'result': 'unsat-violation',
                'prover': self.prover_name,
                'smtlib_artifact_cid': artifact.artifact_cid,
            }
            return self._report(
                claim,
                model,
                artifact,
                status='PROVED',
                solver_result='unsat',
                proof_or_trace_cid=ProofReport.content_cid(proof_payload),
                counterexample=None,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        if result.solver_result == 'sat':
            counterexample = {
                'reason': 'CVC5 found a satisfying violation trace.',
                'compiler_artifact': artifact.metadata.get('compiler_artifact', {}),
                'evidence_refs': artifact.metadata.get('evidence_refs', []),
                'soundness_notes': artifact.metadata.get('soundness_notes', []),
            }
            return self._report(
                claim,
                model,
                artifact,
                status='DISPROVED',
                solver_result='sat',
                proof_or_trace_cid=ProofReport.content_cid(counterexample),
                counterexample=counterexample,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )

        reason = result.reason_unknown or f'cvc5 returned {result.solver_result}'
        return self._report(
            claim,
            model,
            artifact,
            status='UNKNOWN',
            solver_result=result.solver_result,
            proof_or_trace_cid='',
            counterexample={'reason': reason},
            reason_unknown=reason,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )


def run_z3_smtlib_artifact(artifact: SMTLIBCompilation, *, timeout_ms: int = 5_000) -> SMTLIBSolverRun:
    """Run a precompiled SMT-LIB artifact through Z3's SMT-LIB parser."""

    try:
        import z3
    except ImportError:
        return SMTLIBSolverRun(
            prover='z3',
            solver_result='unavailable',
            reason_unknown='Z3 Python bindings are not installed',
        )
    solver = z3.Solver()
    solver.set('timeout', timeout_ms)
    try:
        solver.from_string(artifact.smtlib)
        result = solver.check()
    except z3.Z3Exception as exc:
        return SMTLIBSolverRun(
            prover='z3',
            solver_result='parser_error',
            stderr=str(exc),
            reason_unknown=f'Z3 could not parse or run SMT-LIB: {exc}',
            solver_version=getattr(z3, 'get_full_version', lambda: 'unknown')(),
        )
    result_text = str(result)
    reason_unknown = None
    if result_text == 'unknown':
        reason_unknown = solver.reason_unknown()
    return SMTLIBSolverRun(
        prover='z3',
        solver_result=result_text if result_text in {'sat', 'unsat', 'unknown'} else 'error',
        reason_unknown=reason_unknown,
        solver_version=getattr(z3, 'get_full_version', lambda: 'unknown')(),
    )


def run_xaman_smt_differential(
    model: SecurityModelIR,
    *,
    smtlib_dir: str | Path,
    report_path: str | Path | None = None,
    timeout_ms: int = 5_000,
    cvc5_executable: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Emit Xaman SMT-LIB artifacts and cross-check them with Z3 and CVC5."""

    smtlib_directory = Path(smtlib_dir)
    manifest = emit_ir_smtlib_artifacts(
        model,
        smtlib_directory,
        severities=XAMAN_CRITICAL_SEVERITIES,
    )
    artifacts = compile_ir_claims_to_smtlib(
        model,
        severities=XAMAN_CRITICAL_SEVERITIES,
    )
    manifest_entries_by_claim = {
        entry['claim_id']: entry
        for entry in manifest['artifacts']
    }
    cvc5_runner = CVC5Runner(timeout_ms=timeout_ms, executable=cvc5_executable)
    claim_reports: list[dict[str, Any]] = []
    unsupported_theory_rejections: list[dict[str, Any]] = []
    disagreement_rejections: list[dict[str, Any]] = []
    for artifact in artifacts:
        logic = str(artifact.metadata.get('logic') or '')
        unsupported = logic not in SUPPORTED_SMTLIB_LOGICS
        if unsupported:
            unsupported_theory_rejections.append(
                {
                    'claim_id': artifact.claim_id,
                    'logic': logic,
                    'reason': f'unsupported SMT-LIB logic {logic}',
                }
            )
            z3_result = SMTLIBSolverRun(
                prover='z3',
                solver_result='unsupported',
                reason_unknown=f'unsupported SMT-LIB logic {logic}',
            )
            cvc5_result = SMTLIBSolverRun(
                prover='cvc5',
                solver_result='unsupported',
                reason_unknown=f'unsupported SMT-LIB logic {logic}',
            )
        else:
            z3_result = run_z3_smtlib_artifact(artifact, timeout_ms=timeout_ms)
            cvc5_result = cvc5_runner.run_smtlib_artifact(artifact)
        solver_results = {
            'z3': z3_result.to_dict(),
            'cvc5': cvc5_result.to_dict(),
        }
        comparable_results = {
            prover: result['solver_result']
            for prover, result in solver_results.items()
            if result['solver_result'] in {'sat', 'unsat', 'unknown'}
        }
        disagreement = len(comparable_results) == 2 and len(set(comparable_results.values())) > 1
        if disagreement:
            disagreement_rejections.append(
                {
                    'claim_id': artifact.claim_id,
                    'solver_results': dict(comparable_results),
                    'reason': 'Z3/CVC5 solver result disagreement',
                }
            )
        classification, classification_reason = _classify_xaman_differential(
            artifact,
            z3_result,
            cvc5_result,
            unsupported=unsupported,
            disagreement=disagreement,
        )
        manifest_entry = manifest_entries_by_claim[artifact.claim_id]
        claim_reports.append(
            {
                'claim_id': artifact.claim_id,
                'claim_version': artifact.claim_version,
                'severity': artifact.metadata['severity'],
                'risk': artifact.metadata.get('risk', artifact.metadata['severity']),
                'domain': artifact.metadata.get('domain'),
                'xaman_category': artifact.metadata.get('xaman_category'),
                'classification': classification,
                'classification_reason': classification_reason,
                'blocked_by_assumptions': list(artifact.metadata.get('blocking_assumption_ids', [])),
                'agreement': not disagreement,
                'disagreement': disagreement,
                'unsupported_theory': unsupported,
                'smtlib_artifact': {
                    'path': f'smtlib/{manifest_entry["path"]}',
                    'artifact_cid': artifact.artifact_cid,
                    'logic': logic,
                    'query_kind': artifact.metadata['query_kind'],
                    'assertion_count': artifact.metadata['assertion_count'],
                },
                'solver_results': solver_results,
                'evidence_refs': list(artifact.metadata.get('evidence_refs', [])),
                'soundness_notes': list(artifact.metadata.get('soundness_notes', [])),
            }
        )
    summary = _xaman_differential_summary(
        claim_reports,
        unsupported_theory_rejections=unsupported_theory_rejections,
        disagreement_rejections=disagreement_rejections,
    )
    report = {
        'schema_version': XAMAN_DIFFERENTIAL_SCHEMA_VERSION,
        'task_id': 'PORTAL-CXTP-069',
        'model_id': model.model_id,
        'model_schema_version': model.schema_version,
        'model_cid': calculate_model_cid(model),
        'classification_vocabulary': list(XAMAN_DIFFERENTIAL_CLASSIFICATIONS),
        'selected_provers': ['z3', 'cvc5'],
        'timeout_ms': timeout_ms,
        'smtlib_manifest_path': 'security_ir_artifacts/corpora/xaman-app/smtlib/manifest.json',
        'smtlib_manifest_cid': calculate_artifact_cid(manifest),
        'supported_smtlib_logics': sorted(SUPPORTED_SMTLIB_LOGICS),
        'unsupported_theory_rejections': unsupported_theory_rejections,
        'disagreement_rejections': disagreement_rejections,
        'summary': summary,
        'claims': claim_reports,
    }
    report['report_cid'] = calculate_artifact_cid(report)
    if report_path is not None:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return report


def _classify_xaman_differential(
    artifact: SMTLIBCompilation,
    z3_result: SMTLIBSolverRun,
    cvc5_result: SMTLIBSolverRun,
    *,
    unsupported: bool,
    disagreement: bool,
) -> tuple[str, str]:
    blockers = list(artifact.metadata.get('blocking_assumption_ids', []))
    solver_values = {z3_result.solver_result, cvc5_result.solver_result}
    if unsupported:
        return 'unknown', 'unsupported SMT-LIB theory was rejected before proof classification'
    if disagreement:
        return 'unknown', 'Z3 and CVC5 disagreed; differential proof is rejected fail-closed'
    if any(value in {'unavailable', 'timeout', 'parser_error', 'error', 'unsupported'} for value in solver_values):
        return 'unknown', 'at least one solver did not return sat, unsat, or unknown'
    if 'unknown' in solver_values:
        return 'unknown', 'at least one solver returned unknown'
    if blockers:
        return 'blocked', 'claim has blocking assumptions that prevent production proof acceptance'
    if solver_values == {'unsat'}:
        return 'proved', 'both solvers found no satisfiable blocking or violation condition'
    if solver_values == {'sat'}:
        return 'disproved', 'both solvers found a satisfiable violation condition'
    return 'unknown', 'solver result combination is not classified'


def _xaman_differential_summary(
    claim_reports: list[dict[str, Any]],
    *,
    unsupported_theory_rejections: list[dict[str, Any]],
    disagreement_rejections: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = {
        classification: sum(report['classification'] == classification for report in claim_reports)
        for classification in XAMAN_DIFFERENTIAL_CLASSIFICATIONS
    }
    blocking_or_high = [
        report
        for report in claim_reports
        if report.get('severity') in {'blocking', 'high'}
    ]
    return {
        'claim_count': len(claim_reports),
        'critical_claim_count': len(blocking_or_high),
        'proved': counts['proved'],
        'disproved': counts['disproved'],
        'unknown': counts['unknown'],
        'blocked': counts['blocked'],
        'agreements': sum(not bool(report['disagreement']) for report in claim_reports),
        'disagreements': len(disagreement_rejections),
        'unsupported_theory_rejections': len(unsupported_theory_rejections),
        'release_ready': (
            counts['blocked'] == 0
            and counts['unknown'] == 0
            and counts['disproved'] == 0
            and not unsupported_theory_rejections
            and not disagreement_rejections
        ),
    }


__all__ = [
    'CVC5CLIResult',
    'CVC5Runner',
    'SMTLIBSolverRun',
    'SUPPORTED_SMTLIB_LOGICS',
    'XAMAN_DIFFERENTIAL_CLASSIFICATIONS',
    'XAMAN_DIFFERENTIAL_SCHEMA_VERSION',
    'run_xaman_smt_differential',
    'run_z3_smtlib_artifact',
]
