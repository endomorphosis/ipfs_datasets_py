"""Tests for local Leanstral audit verification."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass, replace

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LeanstralAuditRequest,
    LeanstralAuditResponse,
    LeanstralLocalCheck,
    LeanstralVerificationOutcome,
    LeanstralVerifierConfig,
    ModalLogicCodecConfig,
    verify_leanstral_audit,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
    AggregatedProverResult,
    ProverStatus,
    ProverVerificationResult,
)


@dataclass(frozen=True)
class _NestedProverDetail:
    accepted: bool
    labels: tuple[str, ...]


class _FakeProverAdapter:
    def __init__(self, status: ProverStatus, *, is_valid: bool = False) -> None:
        self.status = status
        self.is_valid = is_valid
        self.calls = []

    def verify_statement(self, statement, timeout=None):
        self.calls.append((statement, timeout))
        return AggregatedProverResult(
            overall_valid=self.is_valid,
            confidence=1.0 if self.is_valid else 0.0,
            prover_results=[
                ProverVerificationResult(
                    prover_name="fake",
                    status=self.status,
                    is_valid=self.is_valid,
                    confidence=1.0 if self.is_valid else 0.0,
                    proof_time=0.001,
                    details={"formula": getattr(statement, "formula", "")},
                    error_message=None
                    if self.is_valid
                    else self.status.value,
                )
            ],
            agreement_rate=1.0 if self.is_valid else 0.0,
            verified_by=["fake"] if self.is_valid else [],
        )


def test_local_check_serializes_dataclass_prover_details() -> None:
    check = LeanstralLocalCheck(
        checker_name="tableaux",
        status=LeanstralVerificationOutcome.ACCEPTED,
        route_available=True,
        theorem_valid=True,
        timeout_seconds=1.0,
        elapsed_seconds=0.1,
        details={
            "outcome": LeanstralVerificationOutcome.ACCEPTED,
            "result": _NestedProverDetail(True, ("modal", "valid")),
        },
    )

    payload = check.to_dict()

    assert payload["details"]["outcome"] == "accepted"
    assert payload["details"]["result"] == {
        "accepted": True,
        "labels": ["modal", "valid"],
    }
    json.dumps(payload)


def _sample():
    text = "The agency must provide notice within 30 days after application."
    base = build_us_code_sample(title="5", section="552", text=text)
    result = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    ).encode(
        text,
        document_id=base.sample_id,
        citation=base.citation,
        source=base.source,
        source_embedding=base.embedding_vector,
    )
    return replace(
        base,
        modal_ir=result.modal_ir,
        frame_candidates=result.frame_candidates,
        selected_frame=result.selected_frame,
        losses=result.losses,
    )


def _request(sample):
    return LeanstralAuditRequest.build(
        evidence={
            "evidence_id": "projection-abc",
            "modal_ir_hash": sample.modal_ir.canonical_hash(),
            "source_span_hashes": {
                formula.formula_id: _span_hash(sample, formula)
                for formula in sample.modal_ir.formulas
            },
        },
        prompt={"template": "audit"},
        model={
            "provider": "mistral_vibe",
            "model": "Leanstral",
            "vibe_agent": "lean",
        },
        theorem_registry={"registry_id": "legal-ir-theorems-v1"},
        proof_obligation_ids=("PO-modal-001",),
    )


def _response(request, **overrides):
    payload = {
        "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
        "request_id": request.request_id,
        "request_cache_key": request.cache_key,
        "classification": "witness_confirmed",
        "missing_semantic_rule": {},
        "counterexample": None,
        "witness": {
            "source": "The agency must provide notice within 30 days after application.",
        },
        "affected_ir_families": ["deontic"],
        "proposed_compiler_surface": [
            {"component": "modal.compiler.registry", "operation": "review"}
        ],
        "confidence": 0.7,
        "proof_obligation_ids": ["PO-modal-001"],
        "abstention_reason": "",
    }
    payload.update(overrides)
    return LeanstralAuditResponse.from_mapping(payload)


def _span_hash(sample, formula):
    span = sample.normalized_text[
        formula.provenance.start_char : formula.provenance.end_char
    ].strip()
    import hashlib

    return hashlib.sha256(span.encode("utf-8")).hexdigest()


def _lean_script(tmp_path, body: str):
    path = tmp_path / "lean-shim"
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_verifier_accepts_only_after_deterministic_checks_and_local_checker(tmp_path) -> None:
    sample = _sample()
    request = _request(sample)
    response = _response(request)

    result = verify_leanstral_audit(
        request,
        response,
        examples=[sample],
        config=LeanstralVerifierConfig(
            lean_executable=_lean_script(tmp_path, "#!/bin/sh\nexit 0\n"),
            lean_timeout_seconds=0.5,
            prover_timeout_seconds=0.5,
        ),
        prover_adapter=_FakeProverAdapter(ProverStatus.VALID, is_valid=True),
    )

    assert result.outcome == LeanstralVerificationOutcome.ACCEPTED
    assert result.accepted is True
    assert result.audit_validation.verified is True
    assert result.compiler_checks[0].accepted is True
    assert all(check.accepted for check in result.source_span_checks)
    assert [check.checker_name for check in result.local_checks[:3]] == [
        "syntax",
        "graph",
        "provenance",
    ]
    assert result.local_checks[3].checker_name == "lean"
    assert set(result.verified_by) == {"lean", "fake"}


def test_verifier_recompiles_packet_canonical_legal_parser_ir() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days after application.",
    )
    request = _request(sample)
    response = _response(request)

    result = verify_leanstral_audit(
        request,
        response,
        examples=[sample],
        config=LeanstralVerifierConfig(
            canonical_recompile_backend="packet_canonical",
            run_lean=False,
            run_modal_bridge=False,
        ),
    )

    assert result.outcome == LeanstralVerificationOutcome.ACCEPTED
    assert result.compiler_checks[0].actual_modal_ir_hash == sample.modal_ir.canonical_hash()
    assert all(check.accepted for check in result.source_span_checks)


def test_verifier_reproduces_introspection_packet_span_attestations() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days after application.",
    )
    request = _request(sample)
    response = _response(request)
    expected_spans = {}
    for formula in sample.modal_ir.formulas:
        start = formula.provenance.start_char
        end = formula.provenance.end_char
        span_text_hash = hashlib.sha256(
            sample.text[start:end].encode("utf-8")
        ).hexdigest()
        payload = {
            "end_char": end,
            "formula_id": formula.formula_id,
            "span_text_hash": span_text_hash,
            "start_char": start,
        }
        expected_spans[formula.formula_id] = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    result = verify_leanstral_audit(
        request,
        response,
        examples=[
            {
                "citation": sample.citation,
                "example_id": sample.sample_id,
                "expected_modal_ir_hash": sample.modal_ir.canonical_hash(),
                "section": sample.section,
                "source_span_hash_format": "introspection_packet_v1",
                "source_span_hashes": expected_spans,
                "source_text": sample.text,
                "title": sample.title,
            }
        ],
        config=LeanstralVerifierConfig(
            canonical_recompile_backend="packet_canonical",
            run_lean=False,
            run_modal_bridge=False,
        ),
    )

    assert result.outcome == LeanstralVerificationOutcome.ACCEPTED
    assert all(check.accepted for check in result.source_span_checks)


def test_verifier_allows_explicitly_capped_packet_span_evidence() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days after application.",
    )
    request = LeanstralAuditRequest.build(
        evidence={
            "evidence_id": "projection-capped",
            "modal_ir_hash": sample.modal_ir.canonical_hash(),
        },
        prompt={"template": "audit"},
        model={
            "provider": "mistral_vibe",
            "model": "Leanstral",
            "vibe_agent": "lean",
        },
        theorem_registry={"registry_id": "legal-ir-theorems-v1"},
        proof_obligation_ids=("PO-modal-001",),
    )
    response = _response(request)
    result = verify_leanstral_audit(
        request,
        response,
        examples=[
            {
                "citation": sample.citation,
                "example_id": sample.sample_id,
                "expected_modal_ir_hash": sample.modal_ir.canonical_hash(),
                "section": sample.section,
                "source_span_hash_format": "introspection_packet_v1",
                "source_span_hashes": {},
                "source_text": sample.text,
                "title": sample.title,
            }
        ],
        config=LeanstralVerifierConfig(
            allow_partial_source_span_evidence=True,
            canonical_recompile_backend="packet_canonical",
            run_lean=False,
            run_modal_bridge=False,
        ),
    )

    assert result.outcome == LeanstralVerificationOutcome.ACCEPTED
    assert result.source_span_checks == ()


def test_verifier_rejects_canonical_hash_or_source_span_mismatch() -> None:
    sample = _sample()
    request = _request(sample)
    response = _response(request)
    bad_example = {
        "example_id": sample.sample_id,
        "text": sample.text,
        "title": sample.title,
        "section": sample.section,
        "citation": sample.citation,
        "expected_modal_ir_hash": "0" * 64,
        "source_span_hashes": {
            sample.modal_ir.formulas[0].formula_id: "1" * 64,
        },
    }

    result = verify_leanstral_audit(
        request,
        response,
        examples=[bad_example],
        config=LeanstralVerifierConfig(run_lean=False, run_modal_bridge=False),
    )

    assert result.outcome == LeanstralVerificationOutcome.REJECTED
    assert "modal_ir_hash_mismatch" in result.reasons
    assert "source_span_hash_mismatch" in result.reasons
    assert result.local_checks == ()


def test_verifier_reports_unsupported_when_routes_are_unavailable(tmp_path) -> None:
    sample = _sample()
    request = _request(sample)
    response = _response(request)

    result = verify_leanstral_audit(
        request,
        response,
        examples=[sample],
        config=LeanstralVerifierConfig(
            lean_executable=str(tmp_path / "missing-lean"),
            run_lean=True,
            run_modal_bridge=True,
        ),
        prover_adapter=_FakeProverAdapter(ProverStatus.UNAVAILABLE),
    )

    assert result.outcome == LeanstralVerificationOutcome.UNSUPPORTED
    assert any(check.route_available is False for check in result.local_checks)
    assert "lean_execution_error:FileNotFoundError" in result.reasons
    assert "unavailable" in result.reasons


def test_verifier_reports_timed_out_without_accepting_llm_assertion(tmp_path) -> None:
    sample = _sample()
    request = _request(sample)
    response = _response(request, rationale="Leanstral says this is valid.")
    slow_lean = _lean_script(tmp_path, "#!/bin/sh\nsleep 1\n")

    result = verify_leanstral_audit(
        request,
        response,
        examples=[sample],
        config=LeanstralVerifierConfig(
            lean_executable=slow_lean,
            lean_timeout_seconds=0.01,
            run_lean=True,
            run_modal_bridge=False,
        ),
    )

    assert result.outcome == LeanstralVerificationOutcome.TIMED_OUT
    assert result.accepted is False
    assert result.reasons == ("lean_timeout",)
    assert result.local_checks[0].route_available is True


def test_verifier_parallel_slices_reuse_successful_proofs_after_restart(tmp_path) -> None:
    sample = _sample()
    request = _request(sample)
    response = _response(request)
    counter_path = tmp_path / "lean-runs.txt"
    lean = _lean_script(
        tmp_path,
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "Lean fake-v1"; exit 0; fi\n'
        f'printf x >> "{counter_path}"\n'
        "exit 0\n",
    )
    config = LeanstralVerifierConfig(
        lean_executable=lean,
        lean_parallel_workers=2,
        lean_proof_cache_path=str(tmp_path / "proof-cache.json"),
        lean_slice_size=1,
        run_lean=True,
        run_modal_bridge=False,
    )

    cold = verify_leanstral_audit(
        request,
        response,
        examples=[sample],
        config=config,
    )
    warm = verify_leanstral_audit(
        request,
        response,
        examples=[sample],
        config=config,
    )

    assert cold.accepted is True
    assert warm.accepted is True
    cold_lean = cold.local_checks[-1]
    warm_lean = warm.local_checks[-1]
    assert cold_lean.details["slice_count"] == 2
    assert cold_lean.details["parallel_workers"] == 2
    assert cold_lean.details["cache_miss_count"] == 2
    assert warm_lean.details["cache_hit_count"] == 2
    assert warm_lean.details["cache_miss_count"] == 0
    assert counter_path.read_text(encoding="utf-8") == "xx"


def test_verifier_requires_referenced_examples_even_for_well_formed_audit() -> None:
    sample = _sample()
    request = _request(sample)
    response = _response(request, witness=None, counterexample=None)
    raw = response.to_dict()
    raw["witness"] = {"note": "No source text or canonical hash."}
    response = LeanstralAuditResponse.from_mapping(raw)

    result = verify_leanstral_audit(
        request,
        response,
        config=LeanstralVerifierConfig(run_lean=False, run_modal_bridge=False),
    )

    assert result.outcome == LeanstralVerificationOutcome.UNSUPPORTED
    assert result.reasons == ("missing_referenced_examples",)


def test_verifier_report_is_json_ready(tmp_path) -> None:
    sample = _sample()
    request = _request(sample)
    response = _response(request)

    result = verify_leanstral_audit(
        request,
        response,
        examples=[sample],
        config=LeanstralVerifierConfig(
            lean_executable=_lean_script(tmp_path, "#!/bin/sh\nexit 0\n"),
            run_modal_bridge=False,
        ),
    )

    encoded = json.dumps(result.to_dict(), sort_keys=True)
    assert "accepted" in encoded
    assert result.outcome == LeanstralVerificationOutcome.ACCEPTED
