"""Contract tests for immutable shared provenance, evidence, and diagnostics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.ir_core.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLocation,
    DiagnosticReport,
    DiagnosticSeverity,
    DiagnosticValidationError,
    canonical_diagnostics_json,
    validate_cross_references,
)
from ipfs_datasets_py.logic.ir_core.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceRef,
    EvidenceReviewStatus,
    EvidenceValidationError,
    canonical_evidence_json,
)
from ipfs_datasets_py.logic.ir_core.provenance import (
    ConfigBinding,
    ProducerBinding,
    Provenance,
    ProvenanceBinding,
    ProvenanceValidationError,
    SourceRef,
    SourceReviewStatus,
    SourceSpan,
    canonical_provenance_json,
)


def _records() -> tuple[Provenance, Evidence, DiagnosticReport]:
    source = SourceRef(
        ref_id="source:skill-1",
        source_uri="https://example.test/skills/one",
        source_id="skill-1",
        source_revision="commit:abc123",
        content_sha256="a" * 64,
        container_uri="hf://datasets/example/skills@abc/bundle.sqlite",
        container_sha256="b" * 64,
        license_expression="Apache-2.0",
        review_status=SourceReviewStatus.HUMAN_REVIEWED,
        metadata={"labels": ["fixture", {"domain": "intent"}]},
    )
    span = SourceSpan(
        span_id="span:goal",
        source_ref_id=source.ref_id,
        start_byte=8,
        end_byte=42,
        start_char=8,
        end_char=40,
        start_line=2,
        start_column=1,
        end_line=2,
        end_column=33,
    )
    producer = ProducerBinding(
        producer_id="producer:normalizer",
        name="intent-normalizer",
        version="1.2.0",
        implementation_sha256="c" * 64,
        repository_revision="commit:def456",
    )
    config = ConfigBinding(
        config_id="config:normalizer",
        content_sha256="d" * 64,
        schema_id="schema:normalizer-v1",
    )
    binding = ProvenanceBinding(
        binding_id="binding:goal",
        subject_id="statement:goal",
        source_ref_ids=(source.ref_id,),
        span_ids=(span.span_id,),
        evidence_ref_ids=("evidence:review",),
        producer_id=producer.producer_id,
        config_id=config.config_id,
    )
    provenance = Provenance(
        provenance_id="provenance:intent-1",
        sources=(source,),
        spans=(span,),
        producers=(producer,),
        configs=(config,),
        bindings=(binding,),
        metadata={"pipeline": {"passes": ["parse", "normalize"]}},
    )
    evidence_ref = EvidenceRef(
        evidence_id="evidence:review",
        kind=EvidenceKind.REVIEW,
        content_sha256="e" * 64,
        uri="ipfs://bafy-review",
        source_ref_ids=(source.ref_id,),
        span_ids=(span.span_id,),
        producer_id=producer.producer_id,
        config_id=config.config_id,
        review_status=EvidenceReviewStatus.ACCEPTED,
        metadata={"review": {"reviewers": ["alice"]}},
    )
    evidence = Evidence(
        evidence_set_id="evidence-set:intent-1",
        references=(evidence_ref,),
    )
    diagnostic = Diagnostic(
        code=DiagnosticCode.UNSUPPORTED_FEATURE,
        message="Conditional retry semantics remain explicit but unsupported.",
        severity=DiagnosticSeverity.WARNING,
        location=DiagnosticLocation(
            subject_ids=(binding.subject_id,),
            source_ref_ids=(source.ref_id,),
            span_ids=(span.span_id,),
            field_path="/actions/0/retry",
        ),
        evidence_ref_ids=(evidence_ref.evidence_id,),
        producer_id=producer.producer_id,
        config_id=config.config_id,
        remediation="Route the node to a compiler that supports bounded retries.",
    )
    report = DiagnosticReport(
        report_id="diagnostics:intent-1",
        diagnostics=(diagnostic,),
        provenance_id=provenance.provenance_id,
        evidence_set_id=evidence.evidence_set_id,
        producer_id=producer.producer_id,
        config_id=config.config_id,
    )
    return provenance, evidence, report


def test_complete_graph_validates_and_round_trips_canonically() -> None:
    provenance, evidence, report = _records()

    provenance.validate(evidence_ref_ids=("evidence:review",))
    evidence.validate(provenance=provenance)
    report.validate(provenance=provenance, evidence=evidence)
    assert validate_cross_references(provenance, evidence, report) == (
        provenance,
        evidence,
        report,
    )

    assert Provenance.from_json(provenance.to_json()) == provenance
    assert Evidence.from_json(evidence.to_json()) == evidence
    assert DiagnosticReport.from_json(report.to_json()) == report
    assert canonical_provenance_json(provenance) == provenance.to_json()
    assert canonical_evidence_json(evidence) == evidence.to_json()
    assert canonical_diagnostics_json(report) == report.to_json()
    assert report.warning_count == 1
    assert report.error_count == 0
    assert report.valid


def test_canonical_serialization_is_independent_of_registry_order() -> None:
    provenance, evidence, report = _records()
    second_source = replace(
        provenance.sources[0],
        ref_id="source:aux",
        source_id="aux",
        content_sha256="f" * 64,
    )
    second_evidence = replace(
        evidence.references[0],
        evidence_id="evidence:aux",
        content_sha256="0" * 64,
        source_ref_ids=("source:aux",),
        span_ids=(),
    )
    second_diagnostic = Diagnostic(
        code="intent.normalization.ambiguous",
        message="Multiple candidate actions were retained.",
        severity=DiagnosticSeverity.INFO,
    )

    forward_provenance = replace(
        provenance, sources=(provenance.sources[0], second_source)
    )
    reverse_provenance = replace(
        provenance, sources=(second_source, provenance.sources[0])
    )
    forward_evidence = replace(
        evidence, references=(evidence.references[0], second_evidence)
    )
    reverse_evidence = replace(
        evidence, references=(second_evidence, evidence.references[0])
    )
    forward_report = replace(
        report, diagnostics=(report.diagnostics[0], second_diagnostic)
    )
    reverse_report = replace(
        report, diagnostics=(second_diagnostic, report.diagnostics[0])
    )

    assert forward_provenance.to_json() == reverse_provenance.to_json()
    assert forward_evidence.to_json() == reverse_evidence.to_json()
    assert forward_report.to_json() == reverse_report.to_json()


def test_construction_defensively_copies_and_deeply_freezes_inputs() -> None:
    metadata = {
        "nested": {
            "labels": ["original"],
        }
    }
    source = SourceRef(
        ref_id="source:immutable",
        source_uri="https://example.test/source",
        source_id="immutable",
        source_revision="commit:1",
        content_sha256="1" * 64,
        metadata=metadata,
    )
    original = source.to_dict()

    metadata["nested"]["labels"].append("mutated")
    metadata["nested"]["new"] = True

    assert source.to_dict() == original
    assert source.metadata["nested"]["labels"] == ("original",)
    with pytest.raises(TypeError):
        source.metadata["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        source.metadata["nested"]["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        source.source_uri = "https://attacker.test"  # type: ignore[misc]

    mutable_ids = ["source:immutable"]
    binding = ProvenanceBinding(
        binding_id="binding:immutable",
        subject_id="subject:immutable",
        source_ref_ids=mutable_ids,  # type: ignore[arg-type]
    )
    mutable_ids.append("source:injected")
    assert binding.source_ref_ids == ("source:immutable",)


def test_source_bodies_and_config_payloads_are_not_embedded() -> None:
    provenance, evidence, report = _records()
    serialized = (
        provenance.to_json() + evidence.to_json() + report.to_json()
    )

    assert "normalized_text" not in serialized
    assert "source_body" not in serialized
    assert "config_payload" not in serialized
    assert provenance.sources[0].content_sha256 in serialized
    assert provenance.configs[0].content_sha256 in serialized


@pytest.mark.parametrize(
    ("replacement", "match"),
    [
        (
            lambda p: replace(
                p,
                spans=(
                    replace(p.spans[0], source_ref_id="source:missing"),
                ),
            ),
            "unknown ids",
        ),
        (
            lambda p: replace(
                p,
                bindings=(
                    replace(p.bindings[0], span_ids=("span:missing",)),
                ),
            ),
            "unknown ids",
        ),
        (
            lambda p: replace(
                p,
                bindings=(
                    replace(p.bindings[0], producer_id="producer:missing"),
                ),
            ),
            "unknown ids",
        ),
        (
            lambda p: replace(
                p,
                bindings=(
                    replace(p.bindings[0], config_id="config:missing"),
                ),
            ),
            "unknown ids",
        ),
    ],
)
def test_provenance_rejects_dangling_cross_references(
    replacement: object, match: str
) -> None:
    provenance, _, _ = _records()
    broken = replacement(provenance)  # type: ignore[operator]

    with pytest.raises(ProvenanceValidationError, match=match):
        broken.validate()


def test_span_must_belong_to_the_listed_source() -> None:
    provenance, _, _ = _records()
    alternate = replace(
        provenance.sources[0],
        ref_id="source:alternate",
        source_id="alternate",
        content_sha256="2" * 64,
    )
    broken = replace(
        provenance,
        sources=(*provenance.sources, alternate),
        bindings=(
            replace(
                provenance.bindings[0],
                source_ref_ids=(alternate.ref_id,),
            ),
        ),
    )

    with pytest.raises(ProvenanceValidationError, match="unlisted source"):
        broken.validate()


def test_evidence_rejects_dangling_source_and_parent_references() -> None:
    provenance, evidence, _ = _records()
    missing_source = replace(
        evidence.references[0], source_ref_ids=("source:missing",)
    )
    with pytest.raises(EvidenceValidationError, match="unknown ids"):
        replace(evidence, references=(missing_source,)).validate(
            provenance=provenance
        )

    missing_parent = replace(
        evidence.references[0],
        parent_evidence_ids=("evidence:missing",),
    )
    with pytest.raises(EvidenceValidationError, match="unknown ids"):
        replace(evidence, references=(missing_parent,)).validate()


def test_provenance_and_evidence_lineage_cycles_are_rejected() -> None:
    provenance, evidence, _ = _records()
    first = replace(
        provenance.bindings[0],
        parent_subject_ids=("statement:derived",),
        derived=True,
    )
    second = ProvenanceBinding(
        binding_id="binding:derived",
        subject_id="statement:derived",
        parent_subject_ids=(first.subject_id,),
        derived=True,
    )
    with pytest.raises(ProvenanceValidationError, match="cycle"):
        replace(provenance, bindings=(first, second)).validate()

    first_evidence = replace(
        evidence.references[0],
        parent_evidence_ids=("evidence:second",),
    )
    second_evidence = replace(
        evidence.references[0],
        evidence_id="evidence:second",
        content_sha256="3" * 64,
        parent_evidence_ids=(first_evidence.evidence_id,),
    )
    with pytest.raises(EvidenceValidationError, match="cycle"):
        replace(
            evidence, references=(first_evidence, second_evidence)
        ).validate()


def test_diagnostics_reject_dangling_source_evidence_and_related_ids() -> None:
    provenance, evidence, report = _records()
    diagnostic = report.diagnostics[0]

    bad_location = replace(
        diagnostic,
        location=replace(
            diagnostic.location, span_ids=("span:missing",)
        ),
    )
    with pytest.raises(DiagnosticValidationError, match="unknown ids"):
        replace(report, diagnostics=(bad_location,)).validate(
            provenance=provenance, evidence=evidence
        )

    bad_evidence = replace(
        diagnostic, evidence_ref_ids=("evidence:missing",)
    )
    with pytest.raises(DiagnosticValidationError, match="unknown ids"):
        replace(report, diagnostics=(bad_evidence,)).validate(
            provenance=provenance, evidence=evidence
        )

    bad_relation = replace(
        diagnostic, related_diagnostic_ids=("diagnostic:missing",)
    )
    with pytest.raises(DiagnosticValidationError, match="unknown ids"):
        replace(report, diagnostics=(bad_relation,)).validate()


def test_diagnostic_code_and_severity_are_stable_and_typed() -> None:
    diagnostic = Diagnostic(
        code="security.adapter.unsupported_field",
        message="Legacy field was retained as an extension.",
        severity=DiagnosticSeverity.WARNING,
    )
    diagnostic.validate()

    round_trip = Diagnostic.from_dict(diagnostic.to_dict())
    assert round_trip.code == "security.adapter.unsupported_field"
    assert round_trip.severity is DiagnosticSeverity.WARNING
    assert round_trip.diagnostic_id == diagnostic.diagnostic_id
    assert DiagnosticSeverity.FATAL.rank > DiagnosticSeverity.ERROR.rank
    assert DiagnosticSeverity.ERROR.rank > DiagnosticSeverity.WARNING.rank

    with pytest.raises(DiagnosticValidationError, match="namespaced"):
        replace(diagnostic, code="UNSTABLE CODE").validate()
    with pytest.raises(DiagnosticValidationError, match="DiagnosticSeverity"):
        replace(diagnostic, severity="warning").validate()  # type: ignore[arg-type]


def test_invalid_spans_and_noncanonical_digests_fail_closed() -> None:
    provenance, _, _ = _records()

    with pytest.raises(ProvenanceValidationError, match="start <= end"):
        replace(provenance.spans[0], start_byte=50, end_byte=20).validate()
    with pytest.raises(ProvenanceValidationError, match="lowercase"):
        replace(
            provenance.sources[0],
            content_sha256=provenance.sources[0].content_sha256.upper(),
        ).validate()


def test_serialized_derived_fields_are_checked_by_reconstruction() -> None:
    _, _, report = _records()
    payload = report.to_dict()
    payload["error_count"] = 99
    payload["valid"] = False

    decoded = DiagnosticReport.from_dict(payload)
    assert decoded.error_count == 0
    assert decoded.valid
