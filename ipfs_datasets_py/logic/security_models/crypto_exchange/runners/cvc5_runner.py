"""CVC5 CLI-backed proof runner for exchange security claims."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..claims.base import SecurityClaim
from ..compilers.to_smtlib import SMTLIBCompilation, compile_claim_to_smtlib
from ..ir.schema import SecurityModelIR, evidence_review_statuses
from ..reports.proof_report import ProofReport
from ..runners.base import BaseSecurityRunner


_PREFERRED_CVC5_PATH = Path('/home/barberb/.local/bin/cvc5')
_ENV_CVC5_PATH = 'IPFS_DATASETS_PY_CVC5'


@dataclass(frozen=True, slots=True)
class CVC5CLIResult:
    """Raw CVC5 process result normalized for proof-report mapping."""

    solver_result: str
    stdout: str
    stderr: str
    returncode: int | None
    reason_unknown: str | None = None


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


__all__ = ['CVC5CLIResult', 'CVC5Runner']
