"""Local verification for structured Leanstral legal-IR audits.

Leanstral audit responses are useful only as hypotheses.  This module verifies
those hypotheses against deterministic compilation, canonical evidence hashes,
source provenance spans, verifier-owned Lean theorem statements, and local
bridge/prover routes.  A model assertion is never treated as proof.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ipfs_datasets_py.logic.common import ProofCache
from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    HammerBackendRunner,
    KernelVerifier,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer import (
    LegalIRHammerConfig,
    LegalIRHammerReport,
    LegalIRHammerRunner,
)

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
    LogicalStatement,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
    AggregatedProverResult,
    ProverIntegrationAdapter,
    ProverStatus,
)

from .codec import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
    modal_ir_to_flogic_triples,
)
from .leanstral_audit import (
    LeanstralAuditRequest,
    LeanstralAuditResponse,
    LeanstralAuditValidation,
    validate_leanstral_audit_response,
)
from .leanstral import (
    LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
    LegalIRLeanTask,
    LeanstralFailureBranchCandidateValidation,
    LeanstralFailureBranchSanitization,
    LeanstralProposal,
    _drafted_logic_candidate_copies_source_span,
    _obligation_contract_id,
    _typed_logic_rejection_reason,
    sanitize_leanstral_failure_branch_candidates,
    validate_leanstral_failure_branch_candidate,
)
from .leanstral_theorems import generate_legal_semantics_theorem_registry
from .lean_runtime import resolve_lean_executable
from .kg_bridge import modal_ir_to_neo4j_graph_data


LEANSTRAL_VERIFIER_SCHEMA_VERSION = "legal-ir-leanstral-verifier-v1"
LEANSTRAL_LEAN_CACHE_SCHEMA_VERSION = "legal-ir-lean-registry-cache-v1"
LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION = "legal-ir-leanstral-hammer-verifier-v1"


class LeanstralVerificationOutcome(str, Enum):
    """Final verifier outcome for one audit response."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"
    TIMED_OUT = "timed-out"


@dataclass(frozen=True)
class LeanstralVerifierConfig:
    """Bounded local-check configuration."""

    codec_config: ModalLogicCodecConfig = field(default_factory=ModalLogicCodecConfig)
    allow_partial_source_span_evidence: bool = False
    canonical_recompile_backend: str = "codec"
    lean_executable: Optional[str] = None
    lean_max_formulas: int = 0
    lean_parallel_workers: int = 1
    lean_proof_cache_max_entries: int = 4096
    lean_proof_cache_path: Optional[str] = None
    lean_proof_cache_ttl_seconds: int = 2_592_000
    lean_slice_size: int = 0
    lean_timeout_seconds: float = 5.0
    modal_bridge_require_proof: bool = False
    prover_timeout_seconds: float = 5.0
    use_provers: Sequence[str] = field(default_factory=tuple)
    run_lean: bool = True
    run_modal_bridge: bool = True
    run_syntax_check: bool = True
    run_graph_check: bool = True
    run_provenance_check: bool = True

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["codec_config"] = asdict(self.codec_config)
        payload["use_provers"] = list(self.use_provers)
        return payload


@dataclass(frozen=True)
class LeanstralCompilerCheck:
    """Deterministic recompilation and canonical hash result."""

    example_id: str
    document_id: str
    expected_modal_ir_hash: str
    actual_modal_ir_hash: str
    accepted: bool
    reasons: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "actual_modal_ir_hash": self.actual_modal_ir_hash,
            "document_id": self.document_id,
            "example_id": self.example_id,
            "expected_modal_ir_hash": self.expected_modal_ir_hash,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LeanstralSourceSpanCheck:
    """Source provenance hash check for one formula span."""

    example_id: str
    formula_id: str
    expected_hash: str
    actual_hash: str
    start_char: int
    end_char: int
    accepted: bool
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeanstralLocalCheck:
    """One local proof/prover route result."""

    checker_name: str
    status: LeanstralVerificationOutcome
    route_available: bool
    theorem_valid: bool
    timeout_seconds: float
    elapsed_seconds: float
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checker_name": self.checker_name,
            "details": _json_ready(self.details),
            "elapsed_seconds": self.elapsed_seconds,
            "error_message": self.error_message,
            "route_available": self.route_available,
            "status": self.status.value,
            "theorem_valid": self.theorem_valid,
            "timeout_seconds": self.timeout_seconds,
        }


def _json_ready(value: Any) -> Any:
    """Convert verifier and prover detail objects to deterministic JSON data."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _json_ready(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _file_sha256(path: Path) -> str:
    """Hash a local verifier dependency without trusting its path alone."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "unavailable"
    return digest.hexdigest()


def _callable_source_hash(value: Any) -> str:
    """Hash the source module that defines a verifier-owned callable."""

    source_path = inspect.getsourcefile(value)
    if source_path:
        return _file_sha256(Path(source_path))
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def _local_check_from_mapping(value: Mapping[str, Any]) -> LeanstralLocalCheck:
    """Rehydrate a JSON-safe local check from the persistent proof cache."""

    status_value = value.get("status", LeanstralVerificationOutcome.UNSUPPORTED.value)
    if isinstance(status_value, LeanstralVerificationOutcome):
        status = status_value
    else:
        status = LeanstralVerificationOutcome(str(status_value))
    details = value.get("details")
    return LeanstralLocalCheck(
        checker_name=str(value.get("checker_name") or "lean"),
        status=status,
        route_available=bool(value.get("route_available")),
        theorem_valid=bool(value.get("theorem_valid")),
        timeout_seconds=float(value.get("timeout_seconds") or 0.0),
        elapsed_seconds=float(value.get("elapsed_seconds") or 0.0),
        details=dict(details) if isinstance(details, Mapping) else {},
        error_message=str(value.get("error_message") or ""),
    )


@dataclass(frozen=True)
class LeanstralAuditVerificationResult:
    """Full verifier report for a Leanstral audit response."""

    schema_version: str
    outcome: LeanstralVerificationOutcome
    accepted: bool
    reasons: Sequence[str]
    audit_validation: LeanstralAuditValidation
    compiler_checks: Sequence[LeanstralCompilerCheck] = field(default_factory=tuple)
    source_span_checks: Sequence[LeanstralSourceSpanCheck] = field(default_factory=tuple)
    local_checks: Sequence[LeanstralLocalCheck] = field(default_factory=tuple)
    response_hash: str = ""
    request_id: str = ""
    verified_by: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "audit_validation": self.audit_validation.to_dict(),
            "compiler_checks": [check.to_dict() for check in self.compiler_checks],
            "local_checks": [check.to_dict() for check in self.local_checks],
            "outcome": self.outcome.value,
            "reasons": list(self.reasons),
            "request_id": self.request_id,
            "response_hash": self.response_hash,
            "schema_version": self.schema_version,
            "source_span_checks": [check.to_dict() for check in self.source_span_checks],
            "verified_by": list(self.verified_by),
        }


@dataclass(frozen=True)
class LeanstralHammerVerifierConfig:
    """Controls deterministic and hammer checks for drafted logic candidates."""

    hammer_config: LegalIRHammerConfig = field(default_factory=LegalIRHammerConfig)
    require_hammer_proof: bool = True
    run_syntax_check: bool = True
    run_provenance_check: bool = True
    run_graph_check: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hammer_config": asdict(self.hammer_config),
            "require_hammer_proof": bool(self.require_hammer_proof),
            "run_graph_check": bool(self.run_graph_check),
            "run_provenance_check": bool(self.run_provenance_check),
            "run_syntax_check": bool(self.run_syntax_check),
        }


@dataclass(frozen=True)
class LeanstralHammerCandidateResult:
    """Verification result for one Leanstral drafted logic candidate."""

    candidate_index: int
    candidate: Mapping[str, Any]
    accepted: bool
    trusted: bool
    reasons: Sequence[str] = field(default_factory=tuple)
    deterministic_checks: Sequence[LeanstralLocalCheck] = field(default_factory=tuple)
    hammer_report: Optional[LegalIRHammerReport] = None
    verified_guidance: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    schema_version: str = LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": bool(self.accepted),
            "candidate": _json_ready(self.candidate),
            "candidate_index": int(self.candidate_index),
            "deterministic_checks": [
                check.to_dict() for check in self.deterministic_checks
            ],
            "hammer_report": self.hammer_report.to_dict()
            if self.hammer_report is not None
            else None,
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
            "trusted": bool(self.trusted),
            "verified_guidance": [_json_ready(item) for item in self.verified_guidance],
        }


@dataclass(frozen=True)
class LeanstralHammerVerificationReport:
    """Batch verification report for Leanstral drafted logic candidates."""

    task_id: str
    proposal_task_id: str
    accepted: bool
    trusted: bool
    candidate_results: Sequence[LeanstralHammerCandidateResult] = field(default_factory=tuple)
    reasons: Sequence[str] = field(default_factory=tuple)
    schema_version: str = LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION

    @property
    def candidate_count(self) -> int:
        return len(self.candidate_results)

    @property
    def trusted_candidate_count(self) -> int:
        return sum(1 for result in self.candidate_results if result.trusted)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": bool(self.accepted),
            "candidate_count": self.candidate_count,
            "candidate_results": [
                result.to_dict() for result in self.candidate_results
            ],
            "proposal_task_id": self.proposal_task_id,
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "trusted": bool(self.trusted),
            "trusted_candidate_count": self.trusted_candidate_count,
        }


class LeanstralHammerCandidateVerifier:
    """Verify Leanstral drafted candidates before they become reward signal."""

    def __init__(
        self,
        config: Optional[LeanstralHammerVerifierConfig] = None,
        *,
        backends: Optional[Sequence[HammerBackendRunner]] = None,
        kernel_verifier: Optional[KernelVerifier] = None,
    ) -> None:
        self.config = config or LeanstralHammerVerifierConfig()
        self.backends = list(backends) if backends is not None else None
        self.kernel_verifier = kernel_verifier

    def verify(
        self,
        task: LegalIRLeanTask,
        proposal: Optional[LeanstralProposal],
        *,
        sample_or_document: Any = None,
    ) -> LeanstralHammerVerificationReport:
        if proposal is None:
            return LeanstralHammerVerificationReport(
                task_id=task.task_id,
                proposal_task_id="",
                accepted=False,
                trusted=False,
                reasons=("invalid_leanstral_proposal",),
            )
        if proposal.task_id != task.task_id:
            return LeanstralHammerVerificationReport(
                task_id=task.task_id,
                proposal_task_id=proposal.task_id,
                accepted=False,
                trusted=False,
                reasons=("task_id_mismatch",),
            )
        results = [
            self._verify_candidate(
                task,
                candidate,
                index=index,
                sample_or_document=sample_or_document,
            )
            for index, candidate in enumerate(proposal.drafted_logic_candidates, start=1)
        ]
        if not results:
            return LeanstralHammerVerificationReport(
                task_id=task.task_id,
                proposal_task_id=proposal.task_id,
                accepted=False,
                trusted=False,
                reasons=("missing_drafted_logic_candidates",),
            )
        reasons = tuple(
            dict.fromkeys(
                reason
                for result in results
                for reason in result.reasons
                if reason
            )
        )
        return LeanstralHammerVerificationReport(
            task_id=task.task_id,
            proposal_task_id=proposal.task_id,
            accepted=all(result.accepted for result in results),
            trusted=all(result.trusted for result in results),
            candidate_results=tuple(results),
            reasons=reasons,
        )

    def _verify_candidate(
        self,
        task: LegalIRLeanTask,
        candidate: Mapping[str, Any],
        *,
        index: int,
        sample_or_document: Any = None,
    ) -> LeanstralHammerCandidateResult:
        checks: List[LeanstralLocalCheck] = []
        if self.config.run_syntax_check:
            checks.append(_check_hammer_candidate_syntax(candidate))
            checks.append(_check_hammer_candidate_contract(task, candidate))
        if self.config.run_provenance_check:
            checks.append(_check_hammer_candidate_provenance(task, candidate))
        if self.config.run_graph_check:
            checks.append(_check_hammer_candidate_graph_shape(candidate))
        deterministic_reasons = tuple(
            dict.fromkeys(
                reason
                for check in checks
                if check.status == LeanstralVerificationOutcome.REJECTED
                for reason in str(check.error_message or "").split(";")
                if reason
            )
        )
        if deterministic_reasons:
            return LeanstralHammerCandidateResult(
                candidate_index=index,
                candidate=dict(candidate),
                accepted=False,
                trusted=False,
                reasons=deterministic_reasons,
                deterministic_checks=tuple(checks),
            )

        selected_obligations = _candidate_obligations(task, candidate)
        if not selected_obligations:
            return LeanstralHammerCandidateResult(
                candidate_index=index,
                candidate=dict(candidate),
                accepted=False,
                trusted=False,
                reasons=("missing_matching_proof_obligation",),
                deterministic_checks=tuple(checks),
            )

        hammer_report = LegalIRHammerRunner(
            config=self.config.hammer_config,
            backends=self.backends,
            kernel_verifier=self.kernel_verifier,
        ).prove(
            sample_or_document or {},
            obligations=selected_obligations,
            extra_candidate_metadata={
                "drafted_logic_candidates": [dict(candidate)],
                "target_metrics": _string_sequence(candidate.get("target_metrics"))
                or _string_sequence(candidate.get("target_metric")),
            },
        )
        hammer_reasons = tuple(
            dict.fromkeys(
                reason
                for artifact in hammer_report.artifacts
                for reason in (
                    *artifact.rejection_reasons,
                    artifact.failure_reason,
                )
                if reason
            )
        )
        proof_accepted = (
            hammer_report.trusted_count == hammer_report.obligation_count
            if self.config.require_hammer_proof
            else True
        )
        trusted_guidance = tuple(
            artifact.to_dict() for artifact in hammer_report.artifacts if artifact.trusted
        )
        return LeanstralHammerCandidateResult(
            candidate_index=index,
            candidate=dict(candidate),
            accepted=proof_accepted,
            trusted=proof_accepted,
            reasons=() if proof_accepted else hammer_reasons or ("hammer_proof_failed",),
            deterministic_checks=tuple(checks),
            hammer_report=hammer_report,
            verified_guidance=trusted_guidance,
        )


class LeanstralAuditVerifier:
    """Verify Leanstral audits with deterministic local authorities."""

    def __init__(
        self,
        config: Optional[LeanstralVerifierConfig] = None,
        *,
        prover_adapter: Optional[ProverIntegrationAdapter] = None,
    ) -> None:
        self.config = config or LeanstralVerifierConfig()
        self.codec = DeterministicModalLogicCodec(self.config.codec_config)
        self.prover_adapter = prover_adapter
        self._lean_check_cache: Dict[str, LeanstralLocalCheck] = {}
        self._lean_toolchain_identities: Dict[str, Dict[str, str]] = {}
        self._lean_theorem_generator_hash = _callable_source_hash(
            generate_legal_semantics_theorem_registry
        )
        self._lean_proof_cache = (
            ProofCache(
                maxsize=max(1, int(self.config.lean_proof_cache_max_entries or 1)),
                ttl=max(1, int(self.config.lean_proof_cache_ttl_seconds or 1)),
                enable_persistence=True,
                persistence_path=self.config.lean_proof_cache_path,
            )
            if self.config.lean_proof_cache_path
            else None
        )
        self._recompiled_sample_cache: Dict[str, LegalSample] = {}

    def verify(
        self,
        request: LeanstralAuditRequest,
        response: Optional[LeanstralAuditResponse],
        *,
        examples: Sequence[LegalSample | Mapping[str, Any]] = (),
    ) -> LeanstralAuditVerificationResult:
        """Verify one structured audit response.

        ``examples`` may contain ``LegalSample`` objects or JSON-like mappings.
        Mappings can provide ``text``/``source_text``, expected
        ``modal_ir_hash``, and ``source_span_hashes``.  If omitted, examples are
        extracted from the response's witness/counterexample fields when they
        carry source text, then from the request's referenced_examples manifest.
        """

        audit_validation = validate_leanstral_audit_response(request, response)
        if not audit_validation.accepted or response is None:
            return self._result(
                LeanstralVerificationOutcome.REJECTED,
                tuple(audit_validation.reasons) or ("audit_schema_rejected",),
                audit_validation,
                response=response,
                request_id=request.request_id,
            )

        reference_examples = (
            tuple(examples)
            or tuple(_examples_from_response(response))
            or tuple(_examples_from_request(request, response=response))
        )
        if not reference_examples:
            return self._result(
                LeanstralVerificationOutcome.UNSUPPORTED,
                ("missing_referenced_examples",),
                audit_validation,
                response=response,
                request_id=request.request_id,
            )

        compiled_samples: List[LegalSample] = []
        compiler_checks: List[LeanstralCompilerCheck] = []
        span_checks: List[LeanstralSourceSpanCheck] = []
        for index, example in enumerate(reference_examples):
            compiled = self._compile_example(
                example,
                request=request,
                single_example=len(reference_examples) == 1,
                index=index,
            )
            compiler_checks.append(compiled["compiler_check"])
            span_checks.extend(compiled["span_checks"])
            sample = compiled.get("sample")
            if isinstance(sample, LegalSample):
                compiled_samples.append(sample)

        deterministic_reasons = _failed_deterministic_reasons(
            compiler_checks,
            span_checks,
        )
        if deterministic_reasons:
            return self._result(
                LeanstralVerificationOutcome.REJECTED,
                deterministic_reasons,
                audit_validation,
                compiler_checks=compiler_checks,
                source_span_checks=span_checks,
                response=response,
                request_id=request.request_id,
            )

        local_checks: List[LeanstralLocalCheck] = []
        for sample in compiled_samples:
            if self.config.run_syntax_check:
                local_checks.append(self._check_modal_ir_syntax(sample))
            if self.config.run_graph_check:
                local_checks.append(self._check_modal_ir_graph(sample))
            if self.config.run_provenance_check:
                local_checks.append(
                    self._check_modal_ir_provenance(sample, span_checks)
                )

        cheap_outcome, cheap_reasons = _outcome_from_local_checks(local_checks)
        if cheap_outcome == LeanstralVerificationOutcome.REJECTED:
            return self._result(
                LeanstralVerificationOutcome.REJECTED,
                cheap_reasons,
                audit_validation,
                compiler_checks=compiler_checks,
                source_span_checks=span_checks,
                local_checks=local_checks,
                response=response,
                request_id=request.request_id,
            )

        for sample in compiled_samples:
            if self.config.run_lean:
                local_checks.append(self._check_lean_registry(sample))
            if self.config.run_modal_bridge:
                local_checks.extend(self._check_modal_bridge(sample))

        outcome, reasons = _outcome_from_local_checks(local_checks)
        return self._result(
            outcome,
            reasons,
            audit_validation,
            compiler_checks=compiler_checks,
            source_span_checks=span_checks,
            local_checks=local_checks,
            response=response,
            request_id=request.request_id,
        )

    def _compile_example(
        self,
        example: LegalSample | Mapping[str, Any],
        *,
        request: LeanstralAuditRequest,
        single_example: bool,
        index: int,
    ) -> Dict[str, Any]:
        reference = _normalize_reference_example(example)
        example_id = reference["example_id"] or f"example-{index + 1}"
        expected_hash = reference["expected_modal_ir_hash"]
        expected_spans = dict(reference["source_span_hashes"])
        source_span_hash_format = str(reference["source_span_hash_format"] or "raw_span_v1")
        if not expected_hash and single_example:
            expected_hash = str(request.evidence.get("modal_ir_hash", "")).strip()
        if not expected_spans and single_example:
            raw_spans = request.evidence.get("source_span_hashes")
            if isinstance(raw_spans, Mapping):
                expected_spans = {
                    str(key): str(value)
                    for key, value in raw_spans.items()
                    if str(key).strip()
                }

        sample = reference["sample"]
        if sample is None:
            text = str(reference["text"]).strip()
            if not text:
                return {
                    "compiler_check": LeanstralCompilerCheck(
                        example_id=example_id,
                        document_id="",
                        expected_modal_ir_hash=expected_hash,
                        actual_modal_ir_hash="",
                        accepted=False,
                        reasons=("missing_source_text",),
                    ),
                    "span_checks": (),
                    "sample": None,
                }
            base = build_us_code_sample(
                title=str(reference["title"] or "0"),
                section=str(reference["section"] or example_id),
                text=text,
                citation=str(reference["citation"] or f"0 U.S.C. {example_id}"),
            )
            sample = self._recompile_sample(base)
        else:
            sample = self._recompile_sample(sample)

        actual_hash = sample.modal_ir.canonical_hash()
        compiler_reasons: List[str] = []
        if not expected_hash:
            compiler_reasons.append("missing_expected_modal_ir_hash")
        elif expected_hash != actual_hash:
            compiler_reasons.append("modal_ir_hash_mismatch")

        span_checks = _check_source_spans(
            sample,
            example_id=example_id,
            expected_spans=expected_spans,
            hash_format=source_span_hash_format,
        )
        if (
            not expected_spans
            and sample.modal_ir.formulas
            and not self.config.allow_partial_source_span_evidence
        ):
            compiler_reasons.append("missing_expected_source_span_hashes")

        return {
            "compiler_check": LeanstralCompilerCheck(
                example_id=example_id,
                document_id=sample.sample_id,
                expected_modal_ir_hash=expected_hash,
                actual_modal_ir_hash=actual_hash,
                accepted=not compiler_reasons,
                reasons=tuple(dict.fromkeys(compiler_reasons)),
            ),
            "span_checks": span_checks,
            "sample": sample,
        }

    def _recompile_sample(self, sample: LegalSample) -> LegalSample:
        backend = str(self.config.canonical_recompile_backend or "codec").strip().lower()
        cache_key = hashlib.sha256(
            f"{backend}\0{sample.sample_id}\0{sample.citation}\0{sample.text}".encode(
                "utf-8"
            )
        ).hexdigest()
        cached = self._recompiled_sample_cache.get(cache_key)
        if cached is not None:
            return cached
        if backend in {"legal", "legal_modal_parser", "packet_canonical"}:
            recompiled = build_us_code_sample(
                title=sample.title,
                section=sample.section,
                text=sample.text,
                citation=sample.citation,
                embedding_model=sample.embedding_model,
                embedding_vector=sample.embedding_vector,
            )
        else:
            encoded = self.codec.encode(
                sample.text,
                document_id=sample.sample_id,
                citation=sample.citation,
                source=sample.source,
                source_embedding=sample.embedding_vector,
            )
            recompiled = replace(
                sample,
                modal_ir=encoded.modal_ir,
                frame_candidates=encoded.frame_candidates,
                selected_frame=encoded.selected_frame,
                losses=encoded.losses,
            )
        self._recompiled_sample_cache[cache_key] = recompiled
        return recompiled

    def _check_modal_ir_syntax(self, sample: LegalSample) -> LeanstralLocalCheck:
        started = time.time()
        reasons: List[str] = []
        modal_ir = sample.modal_ir
        if not str(modal_ir.document_id).strip():
            reasons.append("missing_modal_ir_document_id")
        if modal_ir.normalized_text != sample.normalized_text:
            reasons.append("modal_ir_normalized_text_mismatch")
        if not modal_ir.formulas:
            reasons.append("missing_modal_ir_formulas")
        formula_ids: set[str] = set()
        for formula in modal_ir.formulas:
            formula_id = str(getattr(formula, "formula_id", "") or "").strip()
            if not formula_id:
                reasons.append("missing_formula_id")
            elif formula_id in formula_ids:
                reasons.append("duplicate_formula_id")
            formula_ids.add(formula_id)
            operator = getattr(formula, "operator", None)
            predicate = getattr(formula, "predicate", None)
            if not str(getattr(operator, "family", "") or "").strip():
                reasons.append("missing_operator_family")
            if not str(getattr(operator, "system", "") or "").strip():
                reasons.append("missing_operator_system")
            if not str(getattr(operator, "symbol", "") or "").strip():
                reasons.append("missing_operator_symbol")
            if not str(getattr(predicate, "name", "") or "").strip():
                reasons.append("missing_predicate_name")
            provenance = getattr(formula, "provenance", None)
            start = int(getattr(provenance, "start_char", -1))
            end = int(getattr(provenance, "end_char", -1))
            if start < 0 or end <= start or end > len(sample.normalized_text):
                reasons.append("invalid_formula_source_span")
        return _cheap_check(
            "syntax",
            started,
            reasons,
            {
                "document_id": modal_ir.document_id,
                "formula_count": len(modal_ir.formulas),
            },
        )

    def _check_modal_ir_graph(self, sample: LegalSample) -> LeanstralLocalCheck:
        started = time.time()
        reasons: List[str] = []
        details: Dict[str, Any] = {"document_id": sample.modal_ir.document_id}
        try:
            triples = modal_ir_to_flogic_triples(
                sample.modal_ir,
                selected_frame=sample.selected_frame,
            )
            graph = modal_ir_to_neo4j_graph_data(
                sample.modal_ir,
                selected_frame=sample.selected_frame,
                triples=triples,
            )
        except Exception as exc:  # deterministic projection failures reject the audit
            return _cheap_check(
                "graph",
                started,
                (f"graph_projection_error:{exc.__class__.__name__}",),
                details,
            )

        node_ids = {str(getattr(node, "id", "") or "") for node in graph.nodes}
        for triple in triples:
            if not str(triple.get("subject", "")).strip():
                reasons.append("empty_flogic_subject")
            if not str(triple.get("predicate", "")).strip():
                reasons.append("empty_flogic_predicate")
            if not str(triple.get("object", "")).strip():
                reasons.append("empty_flogic_object")
        if not triples:
            reasons.append("missing_flogic_triples")
        if not graph.nodes:
            reasons.append("missing_graph_nodes")
        if sample.modal_ir.formulas and not graph.relationships:
            reasons.append("missing_graph_relationships")
        for relationship in graph.relationships:
            start_id = str(
                getattr(
                    relationship,
                    "start_node_id",
                    getattr(relationship, "source", ""),
                )
                or ""
            )
            end_id = str(
                getattr(
                    relationship,
                    "end_node_id",
                    getattr(relationship, "target", ""),
                )
                or ""
            )
            if start_id and start_id not in node_ids:
                reasons.append("dangling_graph_relationship_start")
            if end_id and end_id not in node_ids:
                reasons.append("dangling_graph_relationship_end")
        details.update(
            {
                "graph_id": getattr(graph, "id", ""),
                "node_count": len(graph.nodes),
                "relationship_count": len(graph.relationships),
                "triple_count": len(triples),
            }
        )
        return _cheap_check("graph", started, reasons, details)

    def _check_modal_ir_provenance(
        self,
        sample: LegalSample,
        span_checks: Sequence[LeanstralSourceSpanCheck],
    ) -> LeanstralLocalCheck:
        started = time.time()
        reasons: List[str] = []
        checks_by_formula = {
            check.formula_id: check
            for check in span_checks
        }
        for formula in sample.modal_ir.formulas:
            provenance = formula.provenance
            if provenance.source_id != sample.sample_id:
                reasons.append("formula_source_id_mismatch")
            if provenance.citation and provenance.citation != sample.citation:
                reasons.append("formula_citation_mismatch")
            span = sample.normalized_text[
                max(0, int(provenance.start_char)) : max(0, int(provenance.end_char))
            ].strip()
            if not span:
                reasons.append("empty_formula_source_span")
            if (
                span_checks
                and formula.formula_id not in checks_by_formula
                and not self.config.allow_partial_source_span_evidence
            ):
                reasons.append("missing_formula_source_span_check")
        return _cheap_check(
            "provenance",
            started,
            reasons,
            {
                "document_id": sample.modal_ir.document_id,
                "formula_count": len(sample.modal_ir.formulas),
                "source_span_check_count": len(checks_by_formula),
            },
        )

    def _check_lean_registry(self, sample: LegalSample) -> LeanstralLocalCheck:
        executable = resolve_lean_executable(self.config.lean_executable)
        toolchain = self._lean_toolchain_identity(executable)
        cache_key = hashlib.sha256(
            (
                f"{sample.modal_ir.canonical_hash()}\0{toolchain['identity_hash']}\0"
                f"{self._lean_theorem_generator_hash}\0{self.config.lean_timeout_seconds}\0"
                f"{self.config.lean_max_formulas}\0{self.config.lean_slice_size}"
            ).encode("utf-8")
        ).hexdigest()
        cached = self._lean_check_cache.get(cache_key)
        if cached is not None:
            details = dict(cached.details)
            details.update(
                {
                    "cache_hit_count": int(details.get("slice_count") or 1),
                    "cache_miss_count": 0,
                    "process_cache_hit": True,
                }
            )
            return replace(cached, elapsed_seconds=0.0, details=details)
        result = self._run_lean_registry_check(
            sample,
            executable=executable,
            toolchain=toolchain,
        )
        self._lean_check_cache[cache_key] = result
        return result

    def _lean_toolchain_identity(self, executable: str) -> Dict[str, str]:
        cached = self._lean_toolchain_identities.get(executable)
        if cached is not None:
            return cached
        resolved = str(Path(executable).resolve()) if executable else ""
        executable_hash = _file_sha256(Path(resolved)) if resolved else ""
        version = ""
        if executable:
            try:
                process = subprocess.run(
                    [executable, "--version"],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=min(
                        2.0,
                        max(0.1, float(self.config.lean_timeout_seconds)),
                    ),
                )
                version = ((process.stdout or "") + (process.stderr or "")).strip()
            except (OSError, subprocess.TimeoutExpired):
                version = "unavailable"
        payload = {
            "executable_hash": executable_hash,
            "executable_path": resolved,
            "version": version,
        }
        payload["identity_hash"] = hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self._lean_toolchain_identities[executable] = payload
        return payload

    def _run_lean_registry_check(
        self,
        sample: LegalSample,
        *,
        executable: str,
        toolchain: Mapping[str, str],
    ) -> LeanstralLocalCheck:
        start = time.time()
        timeout = max(0.001, float(self.config.lean_timeout_seconds))
        if not executable:
            return LeanstralLocalCheck(
                checker_name="lean",
                status=LeanstralVerificationOutcome.UNSUPPORTED,
                route_available=False,
                theorem_valid=False,
                timeout_seconds=timeout,
                elapsed_seconds=time.time() - start,
                error_message="lean_executable_unavailable",
            )
        full_formula_count = len(sample.modal_ir.formulas)
        max_formulas = max(0, int(self.config.lean_max_formulas or 0))
        selected_formulas = sorted(
            sample.modal_ir.formulas,
            key=lambda formula: formula.formula_id,
        )
        if max_formulas and full_formula_count > max_formulas:
            selected_formulas = selected_formulas[:max_formulas]
        slice_size = max(0, int(self.config.lean_slice_size or 0))
        if not slice_size:
            slice_size = max(1, len(selected_formulas))
        formula_slices = [
            selected_formulas[index : index + slice_size]
            for index in range(0, len(selected_formulas), slice_size)
        ] or [[]]
        workers = min(
            len(formula_slices),
            max(1, int(self.config.lean_parallel_workers or 1)),
        )
        results: Dict[int, LeanstralLocalCheck] = {}
        if workers == 1:
            for index, formulas in enumerate(formula_slices):
                results[index] = self._run_lean_registry_slice(
                    sample,
                    formulas=formulas,
                    executable=executable,
                    toolchain=toolchain,
                    timeout=timeout,
                )
        else:
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="lean-registry",
            ) as executor:
                futures = {
                    executor.submit(
                        self._run_lean_registry_slice,
                        sample,
                        formulas=formulas,
                        executable=executable,
                        toolchain=toolchain,
                        timeout=timeout,
                    ): index
                    for index, formulas in enumerate(formula_slices)
                }
                for future in as_completed(futures):
                    results[futures[future]] = future.result()
        ordered_results = [results[index] for index in range(len(formula_slices))]
        statuses = {result.status for result in ordered_results}
        if LeanstralVerificationOutcome.REJECTED in statuses:
            status = LeanstralVerificationOutcome.REJECTED
        elif LeanstralVerificationOutcome.TIMED_OUT in statuses:
            status = LeanstralVerificationOutcome.TIMED_OUT
        elif LeanstralVerificationOutcome.UNSUPPORTED in statuses:
            status = LeanstralVerificationOutcome.UNSUPPORTED
        else:
            status = LeanstralVerificationOutcome.ACCEPTED
        error_messages = tuple(
            dict.fromkeys(
                result.error_message
                for result in ordered_results
                if result.error_message
            )
        )
        return LeanstralLocalCheck(
            checker_name="lean",
            status=status,
            route_available=all(result.route_available for result in ordered_results),
            theorem_valid=all(result.theorem_valid for result in ordered_results),
            timeout_seconds=timeout,
            elapsed_seconds=time.time() - start,
            details={
                "cache_hit_count": sum(
                    1 for result in ordered_results if result.details.get("proof_cache_hit")
                ),
                "cache_miss_count": sum(
                    1 for result in ordered_results if not result.details.get("proof_cache_hit")
                ),
                "full_formula_count": full_formula_count,
                "lean_toolchain_hash": toolchain.get("identity_hash", ""),
                "parallel_workers": workers,
                "process_cache_hit": False,
                "selected_formula_count": len(selected_formulas),
                "slice_count": len(formula_slices),
                "slice_size": slice_size,
                "slices": [result.to_dict() for result in ordered_results],
                "theorem_generator_hash": self._lean_theorem_generator_hash,
                "theorem_count": sum(
                    int(result.details.get("theorem_count") or 0)
                    for result in ordered_results
                ),
                "verified_formula_count": sum(
                    int(result.details.get("verified_formula_count") or 0)
                    for result in ordered_results
                    if result.status == LeanstralVerificationOutcome.ACCEPTED
                ),
            },
            error_message=error_messages[0] if error_messages else "",
        )

    def _run_lean_registry_slice(
        self,
        sample: LegalSample,
        *,
        formulas: Sequence[Any],
        executable: str,
        toolchain: Mapping[str, str],
        timeout: float,
    ) -> LeanstralLocalCheck:
        start = time.time()
        theorem_sample = replace(
            sample,
            modal_ir=replace(sample.modal_ir, formulas=list(formulas)),
        )
        slice_hash = theorem_sample.modal_ir.canonical_hash()
        cache_key_payload = {
            "cache_schema": LEANSTRAL_LEAN_CACHE_SCHEMA_VERSION,
            "formula_ids": [formula.formula_id for formula in formulas],
            "full_modal_ir_hash": sample.modal_ir.canonical_hash(),
            "slice_modal_ir_hash": slice_hash,
            "theorem_generator_hash": self._lean_theorem_generator_hash,
            "toolchain_hash": toolchain.get("identity_hash", ""),
        }
        cache_key = json.dumps(
            cache_key_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        if self._lean_proof_cache is not None:
            cached = self._lean_proof_cache.get(
                cache_key,
                prover_name="leanstral_lean_registry",
            )
            if (
                isinstance(cached, Mapping)
                and cached.get("theorem_valid") is True
                and cached.get("status") == LeanstralVerificationOutcome.ACCEPTED.value
            ):
                try:
                    check = _local_check_from_mapping(cached)
                except (TypeError, ValueError):
                    check = None
                if check is None:
                    cached = None
                else:
                    details = dict(check.details)
                    details.update(
                        {
                            "cached_proof_elapsed_seconds": check.elapsed_seconds,
                            "proof_cache_hit": True,
                        }
                    )
                    return replace(
                        check,
                        elapsed_seconds=time.time() - start,
                        details=details,
                    )
        registry = generate_legal_semantics_theorem_registry(theorem_sample)
        proofs = {theorem.theorem_id: "by decide" for theorem in registry.theorems}
        try:
            with tempfile.TemporaryDirectory(prefix="legal-ir-audit-lean-") as directory:
                source_path = Path(directory) / "Audit.lean"
                source_path.write_text(registry.render_lean_source(proofs), encoding="utf-8")
                process = subprocess.run(
                    [executable, str(source_path)],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=timeout,
                )
        except subprocess.TimeoutExpired:
            return LeanstralLocalCheck(
                checker_name="lean",
                status=LeanstralVerificationOutcome.TIMED_OUT,
                route_available=True,
                theorem_valid=False,
                timeout_seconds=timeout,
                elapsed_seconds=time.time() - start,
                details={"registry_hash": registry.registry_hash},
                error_message="lean_timeout",
            )
        except OSError as exc:
            return LeanstralLocalCheck(
                checker_name="lean",
                status=LeanstralVerificationOutcome.UNSUPPORTED,
                route_available=False,
                theorem_valid=False,
                timeout_seconds=timeout,
                elapsed_seconds=time.time() - start,
                details={"registry_hash": registry.registry_hash},
                error_message=f"lean_execution_error:{exc.__class__.__name__}",
            )
        output = ((process.stdout or "") + (process.stderr or "")).strip()
        accepted = process.returncode == 0 and "sorry" not in output.lower()
        result = LeanstralLocalCheck(
            checker_name="lean",
            status=LeanstralVerificationOutcome.ACCEPTED
            if accepted
            else LeanstralVerificationOutcome.REJECTED,
            route_available=True,
            theorem_valid=accepted,
            timeout_seconds=timeout,
            elapsed_seconds=time.time() - start,
            details={
                "lean_output": output,
                "formula_ids": [formula.formula_id for formula in formulas],
                "proof_cache_hit": False,
                "registry_hash": registry.registry_hash,
                "theorem_count": registry.theorem_count,
                "verified_formula_count": len(formulas),
            },
            error_message="" if accepted else "lean_rejected_theorem_registry",
        )
        if accepted and self._lean_proof_cache is not None:
            self._lean_proof_cache.set(
                cache_key,
                result.to_dict(),
                prover_name="leanstral_lean_registry",
            )
        return result

    def _check_modal_bridge(self, sample: LegalSample) -> Sequence[LeanstralLocalCheck]:
        adapter = self.prover_adapter
        if adapter is None:
            adapter = ProverIntegrationAdapter(
                use_provers=list(self.config.use_provers),
                enable_cache=False,
                default_timeout=float(self.config.prover_timeout_seconds),
            )
        checks: List[LeanstralLocalCheck] = []
        for formula in sample.modal_ir.formulas:
            statement = _logical_statement_for_formula(formula)
            started = time.time()
            result = adapter.verify_statement(
                statement,
                timeout=float(self.config.prover_timeout_seconds),
            )
            checks.extend(
                _local_checks_from_prover_result(
                    result,
                    formula_id=formula.formula_id,
                    elapsed=time.time() - started,
                    require_proof=self.config.modal_bridge_require_proof,
                    timeout=float(self.config.prover_timeout_seconds),
                )
            )
        return tuple(checks)

    def _result(
        self,
        outcome: LeanstralVerificationOutcome,
        reasons: Sequence[str],
        audit_validation: LeanstralAuditValidation,
        *,
        compiler_checks: Sequence[LeanstralCompilerCheck] = (),
        source_span_checks: Sequence[LeanstralSourceSpanCheck] = (),
        local_checks: Sequence[LeanstralLocalCheck] = (),
        response: Optional[LeanstralAuditResponse] = None,
        request_id: str = "",
    ) -> LeanstralAuditVerificationResult:
        verified_by = [
            check.checker_name
            for check in local_checks
            if check.status == LeanstralVerificationOutcome.ACCEPTED
            and check.theorem_valid
            and not _is_cheap_check(check)
        ]
        return LeanstralAuditVerificationResult(
            schema_version=LEANSTRAL_VERIFIER_SCHEMA_VERSION,
            outcome=outcome,
            accepted=outcome == LeanstralVerificationOutcome.ACCEPTED,
            reasons=tuple(dict.fromkeys(str(reason) for reason in reasons if reason)),
            audit_validation=audit_validation,
            compiler_checks=tuple(compiler_checks),
            source_span_checks=tuple(source_span_checks),
            local_checks=tuple(local_checks),
            response_hash=response.content_hash if response is not None else "",
            request_id=request_id,
            verified_by=tuple(dict.fromkeys(verified_by)),
        )


def verify_leanstral_audit(
    request: LeanstralAuditRequest,
    response: Optional[LeanstralAuditResponse],
    *,
    examples: Sequence[LegalSample | Mapping[str, Any]] = (),
    config: Optional[LeanstralVerifierConfig] = None,
    prover_adapter: Optional[ProverIntegrationAdapter] = None,
) -> LeanstralAuditVerificationResult:
    """Convenience wrapper for ``LeanstralAuditVerifier.verify``."""

    return LeanstralAuditVerifier(
        config,
        prover_adapter=prover_adapter,
    ).verify(request, response, examples=examples)


def verify_leanstral_hammer_candidates(
    task: LegalIRLeanTask,
    proposal: Optional[LeanstralProposal],
    *,
    sample_or_document: Any = None,
    config: Optional[LeanstralHammerVerifierConfig] = None,
    backends: Optional[Sequence[HammerBackendRunner]] = None,
    kernel_verifier: Optional[KernelVerifier] = None,
) -> LeanstralHammerVerificationReport:
    """Verify Leanstral drafted logic candidates through deterministic checks and hammer."""

    return LeanstralHammerCandidateVerifier(
        config=config,
        backends=backends,
        kernel_verifier=kernel_verifier,
    ).verify(task, proposal, sample_or_document=sample_or_document)


_REQUIRED_HAMMER_CANDIDATE_FIELDS = (
    "candidate",
    "compiler_surface",
    "confidence",
    "contract_id",
    "expected_failure_mode",
    "logic_family",
    "premise_hints",
    "proof_obligation_ids",
    "repair_scope",
    "schema_version",
    "source_copy_policy",
    "source_copy_rejected",
    "target_view",
)


def _check_hammer_candidate_syntax(candidate: Mapping[str, Any]) -> LeanstralLocalCheck:
    started = time.time()
    reasons: List[str] = []
    for field_name in _REQUIRED_HAMMER_CANDIDATE_FIELDS:
        if field_name not in candidate:
            reasons.append(f"missing_drafted_logic_{field_name}")
    if not str(candidate.get("candidate") or "").strip():
        reasons.append("missing_drafted_logic_candidate")
    else:
        typed_reason = _typed_logic_rejection_reason(str(candidate.get("candidate") or ""))
        if typed_reason:
            reasons.append(typed_reason)
    if not _string_sequence(candidate.get("proof_obligation_ids")):
        reasons.append("missing_drafted_logic_proof_obligation_ids")
    if not _string_sequence(candidate.get("premise_hints")):
        reasons.append("missing_drafted_logic_premise_hints")
    if str(candidate.get("source_copy_policy") or "") != "reject_full_span_copy":
        reasons.append("invalid_source_copy_policy")
    if _bool_value(candidate.get("source_copy_rejected")):
        reasons.append("source_copy_rejected")
    try:
        confidence = float(candidate.get("confidence"))
    except (TypeError, ValueError):
        reasons.append("invalid_drafted_logic_confidence")
        confidence = 0.0
    if confidence < 0.0 or confidence > 1.0:
        reasons.append("invalid_drafted_logic_confidence")
    if candidate.get("schema_version") != LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION:
        reasons.append("unexpected_drafted_logic_schema_version")
    if candidate.get("repair_scope") != "failed_obligation_subtree":
        reasons.append("invalid_repair_scope")
    return _cheap_check(
        "leanstral_hammer_candidate_syntax",
        started,
        reasons,
        {
            "logic_family": str(candidate.get("logic_family") or ""),
            "target_view": str(candidate.get("target_view") or ""),
        },
    )


def _check_hammer_candidate_contract(
    task: LegalIRLeanTask,
    candidate: Mapping[str, Any],
) -> LeanstralLocalCheck:
    started = time.time()
    reasons: List[str] = []
    contract_id = str(candidate.get("contract_id") or "").strip()
    selected = _candidate_obligations(task, candidate)
    if not contract_id:
        reasons.append("missing_contract_id")
    elif not selected:
        reasons.append("missing_matching_proof_obligation")
    else:
        expected_ids = {_obligation_contract_id(item) for item in selected}
        expected_ids.discard("")
        if not expected_ids or contract_id not in expected_ids:
            reasons.append("unknown_contract_id")
    return _cheap_check(
        "leanstral_hammer_candidate_contract",
        started,
        reasons,
        {
            "contract_id": contract_id,
            "obligation_ids": [
                str(item.get("obligation_id") or "") for item in selected
            ],
        },
    )


def _check_hammer_candidate_provenance(
    task: LegalIRLeanTask,
    candidate: Mapping[str, Any],
) -> LeanstralLocalCheck:
    started = time.time()
    reasons: List[str] = []
    source_span_hash = hashlib.sha256(str(task.source_span or "").encode("utf-8")).hexdigest()
    candidate_hash = str(candidate.get("source_span_hash") or "").strip()
    if candidate_hash and candidate_hash != source_span_hash:
        reasons.append("source_span_hash_mismatch")
    candidate_text = str(candidate.get("candidate") or "")
    if _drafted_logic_candidate_copies_source_span(candidate_text, task.source_span):
        reasons.append("drafted_logic_candidate_copies_source_span")
    return _cheap_check(
        "leanstral_hammer_candidate_provenance",
        started,
        reasons,
        {
            "source_span_hash": source_span_hash,
            "source_span_hash_supplied": bool(candidate_hash),
        },
    )


def _check_hammer_candidate_graph_shape(candidate: Mapping[str, Any]) -> LeanstralLocalCheck:
    started = time.time()
    reasons: List[str] = []
    target_view = str(candidate.get("target_view") or candidate.get("legal_ir_view") or "")
    candidate_text = str(candidate.get("candidate") or "").lower()
    kg_target = "knowledge_graph" in target_view or "neo4j" in target_view
    if kg_target:
        has_subject = "subject:" in candidate_text or "subject(" in candidate_text
        has_predicate = "predicate:" in candidate_text or "predicate(" in candidate_text
        has_object = "object:" in candidate_text or "object(" in candidate_text
        if not (has_subject and has_predicate and has_object):
            reasons.append("invalid_kg_candidate_shape")
    return _cheap_check(
        "leanstral_hammer_candidate_graph",
        started,
        reasons,
        {"target_view": target_view, "kg_target": kg_target},
    )


def _candidate_obligations(
    task: LegalIRLeanTask,
    candidate: Mapping[str, Any],
) -> Sequence[Mapping[str, Any]]:
    obligations = [
        dict(item)
        for item in (task.proof_obligations or ())
        if isinstance(item, Mapping)
    ]
    wanted = set(
        _string_sequence(
            candidate.get("proof_obligation_ids")
            or candidate.get("proof_obligation_id")
            or candidate.get("obligation_id")
        )
    )
    if not wanted:
        return ()
    return tuple(
        obligation
        for obligation in obligations
        if str(obligation.get("obligation_id") or "") in wanted
    )


def _string_sequence(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        values: Sequence[Any] = (value,)
    elif isinstance(value, Sequence):
        values = value
    else:
        values = (value,)
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def _normalize_reference_example(
    example: LegalSample | Mapping[str, Any],
) -> Dict[str, Any]:
    if isinstance(example, LegalSample):
        return {
            "citation": example.citation,
            "example_id": example.sample_id,
            "expected_modal_ir_hash": example.modal_ir.canonical_hash(),
            "sample": example,
            "section": example.section,
            "source_span_hashes": _source_span_hashes_for_sample(example),
            "source_span_hash_format": "raw_span_v1",
            "text": example.text,
            "title": example.title,
        }
    expected_spans = example.get(
        "source_span_hashes",
        example.get("expected_source_span_hashes", {}),
    )
    return {
        "citation": example.get("citation", ""),
        "example_id": str(
            example.get("example_id", example.get("sample_id", example.get("id", "")))
        ).strip(),
        "expected_modal_ir_hash": str(
            example.get(
                "expected_modal_ir_hash",
                example.get("modal_ir_hash", example.get("target_modal_ir_hash", "")),
            )
        ).strip(),
        "sample": None,
        "section": str(example.get("section", "")),
        "source_span_hashes": {
            str(key): str(value)
            for key, value in expected_spans.items()
        }
        if isinstance(expected_spans, Mapping)
        else {},
        "source_span_hash_format": str(
            example.get("source_span_hash_format", "raw_span_v1")
        ),
        "text": str(
            example.get(
                "source_text",
                example.get("text", example.get("source", example.get("source_span", ""))),
            )
        ),
        "title": str(example.get("title", "")),
    }


def _examples_from_response(
    response: LeanstralAuditResponse,
) -> Iterable[Mapping[str, Any]]:
    for payload in (response.counterexample, response.witness):
        if not isinstance(payload, Mapping):
            continue
        text = payload.get("source_text", payload.get("text", payload.get("source")))
        if text:
            yield payload


def _examples_from_request(
    request: LeanstralAuditRequest,
    *,
    response: LeanstralAuditResponse,
) -> Iterable[Mapping[str, Any]]:
    evidence = request.evidence if isinstance(request.evidence, Mapping) else {}
    referenced_examples = [
        item
        for item in evidence.get("referenced_examples", []) or []
        if isinstance(item, Mapping)
    ]
    if not referenced_examples:
        referenced_examples = list(_examples_from_evidence_packets(evidence))
    if not referenced_examples:
        return

    referenced_ids = _response_referenced_ids(response)
    emitted = False
    for example in referenced_examples:
        example_ids = {
            str(example.get("example_id") or "").strip(),
            str(example.get("sample_id") or "").strip(),
            str(example.get("evidence_id") or "").strip(),
        }
        if referenced_ids and not (referenced_ids & {value for value in example_ids if value}):
            continue
        emitted = True
        yield example
    if not emitted and len(referenced_examples) == 1:
        yield referenced_examples[0]


def _examples_from_evidence_packets(
    evidence: Mapping[str, Any],
) -> Iterable[Mapping[str, Any]]:
    for packet in evidence.get("evidence_packets", []) or []:
        if not isinstance(packet, Mapping):
            continue
        sample_hashes = packet.get("sample_hashes")
        if not isinstance(sample_hashes, Mapping):
            sample_hashes = {}
        evidence_hashes = packet.get("evidence_hashes")
        if not isinstance(evidence_hashes, Mapping):
            evidence_hashes = {}
        legal_ir_views = packet.get("legal_ir_views")
        if not isinstance(legal_ir_views, Mapping):
            legal_ir_views = {}
        canonical = legal_ir_views.get("canonical")
        if not isinstance(canonical, Mapping):
            canonical = {}
        example: Dict[str, Any] = {
            "example_id": str(
                sample_hashes.get("sample_id") or packet.get("evidence_id") or ""
            ).strip(),
            "evidence_id": str(packet.get("evidence_id") or "").strip(),
            "expected_modal_ir_hash": str(
                sample_hashes.get("modal_ir_hash")
                or evidence_hashes.get("canonical_modal_ir_hash")
                or canonical.get("modal_ir_hash")
                or ""
            ).strip(),
            "sample_id": str(sample_hashes.get("sample_id") or "").strip(),
        }
        span_hashes = sample_hashes.get("source_span_hashes")
        if isinstance(span_hashes, Mapping):
            example["source_span_hashes"] = {
                str(key): str(value)
                for key, value in span_hashes.items()
                if str(key).strip()
            }
            example["source_span_hash_format"] = "introspection_packet_v1"
        for key in ("citation", "section", "title"):
            value = str(packet.get(key) or "").strip()
            if value:
                example[key] = value
        text = str(
            packet.get("source_text")
            or packet.get("text")
            or packet.get("sample_text")
            or ""
        ).strip()
        if text:
            example["source_text"] = text
        yield example


def _response_referenced_ids(response: LeanstralAuditResponse) -> set[str]:
    values: set[str] = set()
    for payload in (response.counterexample, response.witness):
        _collect_response_reference_ids(payload, values)
    return values


def _collect_response_reference_ids(payload: Any, values: set[str]) -> None:
    if isinstance(payload, Mapping):
        for key in ("evidence_id", "example_id", "sample_id", "id"):
            value = str(payload.get(key) or "").strip()
            if value:
                values.add(value)
        for child in payload.values():
            _collect_response_reference_ids(child, values)
    elif isinstance(payload, (list, tuple)):
        for child in payload:
            _collect_response_reference_ids(child, values)


def _source_span_hashes_for_sample(sample: LegalSample) -> Dict[str, str]:
    return {
        formula.formula_id: _source_span_hash(
            sample,
            formula.provenance.start_char,
            formula.provenance.end_char,
        )
        for formula in sample.modal_ir.formulas
    }


def _check_source_spans(
    sample: LegalSample,
    *,
    example_id: str,
    expected_spans: Mapping[str, str],
    hash_format: str = "raw_span_v1",
) -> Sequence[LeanstralSourceSpanCheck]:
    if not expected_spans:
        return ()
    formulas = {formula.formula_id: formula for formula in sample.modal_ir.formulas}
    checks: List[LeanstralSourceSpanCheck] = []
    for formula_id, expected_hash in sorted(expected_spans.items()):
        formula = formulas.get(str(formula_id))
        if formula is None:
            checks.append(
                LeanstralSourceSpanCheck(
                    example_id=example_id,
                    formula_id=str(formula_id),
                    expected_hash=str(expected_hash),
                    actual_hash="",
                    start_char=-1,
                    end_char=-1,
                    accepted=False,
                    reason="source_span_formula_missing",
                )
            )
            continue
        if str(hash_format).strip().lower() == "introspection_packet_v1":
            actual = _source_span_attestation_hash(sample, formula)
        else:
            actual = _source_span_hash(
                sample,
                formula.provenance.start_char,
                formula.provenance.end_char,
            )
        accepted = str(expected_hash) == actual
        checks.append(
            LeanstralSourceSpanCheck(
                example_id=example_id,
                formula_id=str(formula_id),
                expected_hash=str(expected_hash),
                actual_hash=actual,
                start_char=int(formula.provenance.start_char),
                end_char=int(formula.provenance.end_char),
                accepted=accepted,
                reason="" if accepted else "source_span_hash_mismatch",
            )
        )
    return tuple(checks)


def _source_span_hash(sample: LegalSample, start_char: int, end_char: int) -> str:
    start = max(0, int(start_char))
    end = max(start, int(end_char))
    span = sample.normalized_text[start:end].strip() or sample.text[start:end].strip()
    return hashlib.sha256(span.encode("utf-8")).hexdigest()


def _source_span_attestation_hash(sample: LegalSample, formula: Any) -> str:
    start = int(formula.provenance.start_char)
    end = int(formula.provenance.end_char)
    span_text_hash = hashlib.sha256(sample.text[start:end].encode("utf-8")).hexdigest()
    payload = {
        "end_char": end,
        "formula_id": formula.formula_id,
        "span_text_hash": span_text_hash,
        "start_char": start,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _logical_statement_for_formula(formula: Any) -> LogicalStatement:
    operator = formula.operator
    predicate = formula.predicate
    formula_text = (
        f"{operator.symbol}[{operator.family}:{operator.system}]"
        f"({predicate.name})"
    )
    return LogicalStatement(
        formula=formula_text,
        natural_language=predicate.name,
        confidence=1.0,
        formalism="modal",
        metadata={
            "formula_id": formula.formula_id,
            "modal_family": operator.family,
            "modal_system": operator.system,
            "operator": operator.symbol,
        },
    )


def _local_checks_from_prover_result(
    result: AggregatedProverResult,
    *,
    formula_id: str,
    elapsed: float,
    require_proof: bool,
    timeout: float,
) -> Sequence[LeanstralLocalCheck]:
    checks: List[LeanstralLocalCheck] = []
    for prover_result in result.prover_results:
        status = _outcome_from_prover_status(prover_result.status, prover_result.is_valid)
        route_available = prover_result.status not in {
            ProverStatus.UNAVAILABLE,
            ProverStatus.ERROR,
        }
        details = dict(prover_result.details)
        details["formula_id"] = formula_id
        modal_compiled = details.get("modal_route_status") == "available"
        if modal_compiled and not require_proof:
            status = LeanstralVerificationOutcome.ACCEPTED
            details["modal_bridge_validation_mode"] = "compilation"
            details["formula_assertion_proved"] = bool(prover_result.is_valid)
        checks.append(
            LeanstralLocalCheck(
                checker_name=prover_result.prover_name,
                status=status,
                route_available=route_available,
                theorem_valid=bool(prover_result.is_valid),
                timeout_seconds=timeout,
                elapsed_seconds=elapsed,
                details=details,
                error_message=(
                    ""
                    if modal_compiled and not require_proof
                    else prover_result.error_message or ""
                ),
            )
        )
    if not checks:
        checks.append(
            LeanstralLocalCheck(
                checker_name="prover",
                status=LeanstralVerificationOutcome.UNSUPPORTED,
                route_available=False,
                theorem_valid=False,
                timeout_seconds=timeout,
                elapsed_seconds=elapsed,
                details={"formula_id": formula_id},
                error_message="no_prover_results",
            )
        )
    return tuple(checks)


def _cheap_check(
    name: str,
    started: float,
    reasons: Sequence[str],
    details: Optional[Mapping[str, Any]] = None,
) -> LeanstralLocalCheck:
    unique_reasons = tuple(
        dict.fromkeys(str(reason) for reason in reasons if str(reason).strip())
    )
    accepted = not unique_reasons
    return LeanstralLocalCheck(
        checker_name=name,
        status=LeanstralVerificationOutcome.ACCEPTED
        if accepted
        else LeanstralVerificationOutcome.REJECTED,
        route_available=True,
        theorem_valid=accepted,
        timeout_seconds=0.0,
        elapsed_seconds=time.time() - started,
        details={"check_phase": "cheap", **dict(details or {})},
        error_message=";".join(unique_reasons),
    )


def _outcome_from_prover_status(
    status: ProverStatus,
    is_valid: bool,
) -> LeanstralVerificationOutcome:
    if status == ProverStatus.TIMEOUT:
        return LeanstralVerificationOutcome.TIMED_OUT
    if status == ProverStatus.UNAVAILABLE:
        return LeanstralVerificationOutcome.UNSUPPORTED
    if status == ProverStatus.ERROR:
        return LeanstralVerificationOutcome.UNSUPPORTED
    if status == ProverStatus.VALID and is_valid:
        return LeanstralVerificationOutcome.ACCEPTED
    return LeanstralVerificationOutcome.REJECTED


def _failed_deterministic_reasons(
    compiler_checks: Sequence[LeanstralCompilerCheck],
    span_checks: Sequence[LeanstralSourceSpanCheck],
) -> Sequence[str]:
    reasons: List[str] = []
    for check in compiler_checks:
        if not check.accepted:
            reasons.extend(check.reasons)
    for check in span_checks:
        if not check.accepted and check.reason:
            reasons.append(check.reason)
    return tuple(dict.fromkeys(reasons))


def _outcome_from_local_checks(
    checks: Sequence[LeanstralLocalCheck],
) -> tuple[LeanstralVerificationOutcome, Sequence[str]]:
    if not checks:
        return LeanstralVerificationOutcome.UNSUPPORTED, ("no_local_checker_results",)
    if any(check.status == LeanstralVerificationOutcome.REJECTED for check in checks):
        return (
            LeanstralVerificationOutcome.REJECTED,
            tuple(
                dict.fromkeys(
                    check.error_message or f"{check.checker_name}_rejected"
                    for check in checks
                    if check.status == LeanstralVerificationOutcome.REJECTED
                )
            ),
        )
    if any(check.status == LeanstralVerificationOutcome.TIMED_OUT for check in checks):
        return (
            LeanstralVerificationOutcome.TIMED_OUT,
            tuple(
                dict.fromkeys(
                    check.error_message or f"{check.checker_name}_timed_out"
                    for check in checks
                    if check.status == LeanstralVerificationOutcome.TIMED_OUT
                )
            ),
        )
    proof_checks = [check for check in checks if not _is_cheap_check(check)]
    acceptance_checks = proof_checks or list(checks)
    if any(
        check.status == LeanstralVerificationOutcome.ACCEPTED
        for check in acceptance_checks
    ):
        return LeanstralVerificationOutcome.ACCEPTED, ()
    return (
        LeanstralVerificationOutcome.UNSUPPORTED,
        tuple(
            dict.fromkeys(
                check.error_message or f"{check.checker_name}_unsupported"
                for check in acceptance_checks
            )
        ),
    )


def _is_cheap_check(check: LeanstralLocalCheck) -> bool:
    return check.details.get("check_phase") == "cheap" or check.checker_name in {
        "graph",
        "provenance",
        "syntax",
    }


__all__ = [
    "LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION",
    "LEANSTRAL_VERIFIER_SCHEMA_VERSION",
    "LeanstralAuditVerificationResult",
    "LeanstralAuditVerifier",
    "LeanstralHammerCandidateResult",
    "LeanstralHammerCandidateVerifier",
    "LeanstralHammerVerificationReport",
    "LeanstralHammerVerifierConfig",
    "LeanstralFailureBranchCandidateValidation",
    "LeanstralFailureBranchSanitization",
    "LeanstralCompilerCheck",
    "LeanstralLocalCheck",
    "LeanstralSourceSpanCheck",
    "LeanstralVerificationOutcome",
    "LeanstralVerifierConfig",
    "verify_leanstral_hammer_candidates",
    "verify_leanstral_audit",
    "sanitize_leanstral_failure_branch_candidates",
    "validate_leanstral_failure_branch_candidate",
]
