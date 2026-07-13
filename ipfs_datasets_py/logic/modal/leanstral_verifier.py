"""Local verification for structured Leanstral legal-IR audits.

Leanstral audit responses are useful only as hypotheses.  This module verifies
those hypotheses against deterministic compilation, canonical evidence hashes,
source provenance spans, verifier-owned Lean theorem statements, and local
bridge/prover routes.  A model assertion is never treated as proof.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
    build_us_code_sample,
    stable_mock_embedding,
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
from .leanstral_theorems import generate_legal_semantics_theorem_registry
from .kg_bridge import modal_ir_to_neo4j_graph_data


LEANSTRAL_VERIFIER_SCHEMA_VERSION = "legal-ir-leanstral-verifier-v1"


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
    lean_executable: Optional[str] = None
    lean_timeout_seconds: float = 5.0
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
            "details": dict(self.details),
            "elapsed_seconds": self.elapsed_seconds,
            "error_message": self.error_message,
            "route_available": self.route_available,
            "status": self.status.value,
            "theorem_valid": self.theorem_valid,
            "timeout_seconds": self.timeout_seconds,
        }


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
        carry source text.
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

        reference_examples = tuple(examples) or tuple(
            _examples_from_response(response)
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
            encoded = self.codec.encode(
                text,
                document_id=base.sample_id,
                citation=base.citation,
                source=base.source,
                source_embedding=stable_mock_embedding(base.normalized_text),
            )
            sample = replace(
                base,
                modal_ir=encoded.modal_ir,
                frame_candidates=encoded.frame_candidates,
                selected_frame=encoded.selected_frame,
                losses=encoded.losses,
            )
        else:
            encoded = self.codec.encode(
                sample.text,
                document_id=sample.sample_id,
                citation=sample.citation,
                source=sample.source,
                source_embedding=sample.embedding_vector,
            )
            sample = replace(
                sample,
                modal_ir=encoded.modal_ir,
                frame_candidates=encoded.frame_candidates,
                selected_frame=encoded.selected_frame,
                losses=encoded.losses,
            )

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
        )
        if not expected_spans:
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
            if span_checks and formula.formula_id not in checks_by_formula:
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
        start = time.time()
        executable = self.config.lean_executable or shutil.which("lean")
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
        registry = generate_legal_semantics_theorem_registry(sample)
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
        return LeanstralLocalCheck(
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
                "registry_hash": registry.registry_hash,
                "theorem_count": registry.theorem_count,
            },
            error_message="" if accepted else "lean_rejected_theorem_registry",
        )

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
        checks.append(
            LeanstralLocalCheck(
                checker_name=prover_result.prover_name,
                status=status,
                route_available=route_available,
                theorem_valid=bool(prover_result.is_valid),
                timeout_seconds=timeout,
                elapsed_seconds=elapsed,
                details=details,
                error_message=prover_result.error_message or "",
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
    "LEANSTRAL_VERIFIER_SCHEMA_VERSION",
    "LeanstralAuditVerificationResult",
    "LeanstralAuditVerifier",
    "LeanstralCompilerCheck",
    "LeanstralLocalCheck",
    "LeanstralSourceSpanCheck",
    "LeanstralVerificationOutcome",
    "LeanstralVerifierConfig",
    "verify_leanstral_audit",
]
