"""Contract tests for shared provenance, evidence, and diagnostics."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.ir_core.diagnostics import (
    Diagnostic,
    DiagnosticReport,
    DiagnosticSeverity,
    DiagnosticValidationError,
    diagnostics_from_validation,
)
from ipfs_datasets_py.logic.ir_core.evidence import (
    EvidenceCollection,
    EvidenceKind,
    EvidenceReference,
    EvidenceValidationError,
)
from ipfs_datasets_py.logic.ir_core.provenance import (
    ConfigurationBinding,
    ProducerBinding,
    ProvenanceBinding,
    ProvenanceBundle,
    ProvenanceValidationError,
    ReviewStatus,
    SourceReference,
    SourceSpan,
    SpanUnit,
    canonical_json_bytes,
)


def _provenance() -> ProvenanceBundle:
    source = SourceReference(
        reference_id="source:skill:1",
        source_uri="https://example.test/repository/SKILL.md",
        source_id="repository/SKILL.md",
        revision="8c2dbbc",
        content_sha256="1" * 64,
        content_cid="bafy-source",
        bundle_sha256="2" * 64,
        bundle_uri="hf://datasets/example/bundle@8c2dbbc/data.sqlite",
        byte_length=128,
        media_type="text/markdown",
        license_expression="Apache-2.0",
        review_status=ReviewStatus.HUMAN_REVIEWED,
        metadata={"labels": ["security", "procedure"]},
    )
    span = SourceSpan(
        span_id="span:skill:1:0",
        source_reference_id=source.reference_id,
        start=12,
        end=42,
        unit=SpanUnit.BYTE,
        start_line=2,
        start_column=0,
        end_line=3,
        end_column=4,
    )
    producer = ProducerBinding(
        producer_id="producer:intent-parser:1",
        name="intent-parser",
        version="1.2.0",
        executable_sha256="3" * 64,
        repository_revision="8c2dbbc",
    )
    configuration = ConfigurationBinding(
        configuration_id="configuration:intent-parser:strict",
        content_sha256="4" * 64,
        schema_id="intent-parser-config/v1",
        profile="strict",
    )
    root = ProvenanceBinding(
        subject_id="statement:install",
        source_reference_ids=(source.reference_id,),
        source_span_ids=(span.span_id,),
        producer_id=producer.producer_id,
        configuration_id=configuration.configuration_id,
    )
    derived = ProvenanceBinding(
        subject_id="formula:install",
        parent_subject_ids=(root.subject_id,),
        producer_id=producer.producer_id,
        configuration_id=configuration.configuration_id,
    )
    return ProvenanceBundle(
        sources=(source,),
        spans=(span,),
        producers=(producer,),
        configurations=(configuration,),
        bindings=(root, derived),
        bundle_id="provenance:intent:1",
        metadata={"profile": {"name": "shared", "flags": [True, False]}},
    )


def _evidence() -> EvidenceCollection:
    return EvidenceCollection(
        evidence=(
            EvidenceReference(
                evidence_id="evidence:parser-receipt:1",
                kind=EvidenceKind.RECEIPT,
                content_sha256="5" * 64,
                uri="ipfs://bafy-receipt",
                content_cid="bafy-receipt",
                media_type="application/json",
                schema_id="parser-receipt/v1",
                description="Deterministic parser receipt",
                source_reference_ids=("source:skill:1",),
                source_span_ids=("span:skill:1:0",),
                subject_ids=("statement:install", "formula:install"),
                producer_id="producer:intent-parser:1",
                configuration_id="configuration:intent-parser:strict",
                review_status=ReviewStatus.MACHINE_REVIEWED,
            ),
        ),
        collection_id="evidence-collection:intent:1",
    )


def _report() -> DiagnosticReport:
    return DiagnosticReport(
        diagnostics=(
            Diagnostic(
                code="intent.compiler.unsupported_retry",
                message="The retry bound cannot be represented by this backend.",
                severity=DiagnosticSeverity.WARNING,
                subject_id="formula:install",
                field_path="actions.0.retry",
                source_reference_ids=("source:skill:1",),
                source_span_ids=("span:skill:1:0",),
                evidence_reference_ids=("evidence:parser-receipt:1",),
                producer_id="producer:intent-parser:1",
                configuration_id="configuration:intent-parser:strict",
                remediation="Retain the retry as a grounded opaque term.",
            ),
        ),
        artifact_id="artifact:intent:1",
        provenance_bundle_id="provenance:intent:1",
        evidence_collection_id="evidence-collection:intent:1",
    )


def test_source_references_spans_and_bindings_round_trip_without_source_body() -> None:
    provenance = _provenance()
    payload = provenance.to_dict()

    assert provenance.validate_cross_references().valid
    assert ProvenanceBundle.from_dict(
        json.loads(json.dumps(payload))
    ).canonical_bytes() == provenance.canonical_bytes()
    assert provenance.span_by_id["span:skill:1:0"].unit is SpanUnit.BYTE
    assert provenance.binding_by_subject_id["formula:install"].derived
    assert payload["sources"][0]["byte_length"] == 128
    assert payload["sources"][0]["content_sha256"] == "1" * 64
    serialized = provenance.canonical_bytes()
    assert b"normalized_text" not in serialized
    assert b"source_body" not in serialized
    assert b"SKILL.md content" not in serialized


def test_all_artifacts_have_canonical_order_independent_serialization() -> None:
    provenance = _provenance()
    evidence = _evidence()
    report = _report()

    reversed_provenance = ProvenanceBundle(
        sources=reversed(provenance.sources),
        spans=reversed(provenance.spans),
        producers=reversed(provenance.producers),
        configurations=reversed(provenance.configurations),
        bindings=reversed(provenance.bindings),
        bundle_id=provenance.bundle_id,
        metadata={"profile": {"flags": [True, False], "name": "shared"}},
    )
    diagnostic = report.diagnostics[0]
    reordered_diagnostic = Diagnostic(
        code=diagnostic.code,
        message=diagnostic.message,
        severity=diagnostic.severity,
        subject_id=diagnostic.subject_id,
        field_path=diagnostic.field_path,
        source_reference_ids=tuple(reversed(diagnostic.source_reference_ids)),
        source_span_ids=tuple(reversed(diagnostic.source_span_ids)),
        evidence_reference_ids=tuple(
            reversed(diagnostic.evidence_reference_ids)
        ),
        producer_id=diagnostic.producer_id,
        configuration_id=diagnostic.configuration_id,
        remediation=diagnostic.remediation,
        metadata={},
    )

    assert reversed_provenance.canonical_bytes() == provenance.canonical_bytes()
    assert reordered_diagnostic.diagnostic_id == diagnostic.diagnostic_id
    assert evidence.canonical_bytes() == EvidenceCollection.from_dict(
        evidence.to_dict()
    ).canonical_bytes()
    assert report.canonical_bytes() == DiagnosticReport.from_dict(
        report.to_dict()
    ).canonical_bytes()
    assert provenance.canonical_bytes() == canonical_json_bytes(
        provenance.to_dict()
    )
    assert b" " not in provenance.canonical_bytes()


def test_construction_defensively_copies_and_deeply_freezes_caller_data() -> None:
    metadata = {
        "policy": {"labels": ["reviewed"], "limits": {"tokens": 32}}
    }
    source_ids = ["source:skill:1"]
    source = SourceReference(
        reference_id="source:skill:1",
        source_uri="https://example.test/SKILL.md",
        source_id="SKILL.md",
        revision="8c2dbbc",
        content_sha256="1" * 64,
        metadata=metadata,
    )
    binding = ProvenanceBinding(
        subject_id="statement:1",
        source_reference_ids=source_ids,
        metadata=metadata,
    )
    before_source = source.to_dict()
    before_binding = binding.to_dict()

    metadata["policy"]["labels"].append("mutated")
    metadata["policy"]["limits"]["tokens"] = 999
    source_ids.append("source:injected")

    assert source.to_dict() == before_source
    assert binding.to_dict() == before_binding
    assert binding.source_reference_ids == ("source:skill:1",)
    with pytest.raises(TypeError):
        source.metadata["replacement"] = True
    with pytest.raises(TypeError):
        source.metadata["policy"]["limits"]["tokens"] = 1
    with pytest.raises(AttributeError):
        source.metadata["policy"]["labels"].append("x")
    with pytest.raises(FrozenInstanceError):
        source.source_uri = "https://attacker.invalid"

    exported = source.to_dict()
    exported["metadata"]["policy"]["labels"].append("export-only")
    assert source.to_dict() == before_source


def test_complete_cross_reference_graph_validates() -> None:
    provenance = _provenance()
    evidence = _evidence()
    report = _report()

    assert evidence.validate_cross_references(provenance).valid
    result = report.validate_cross_references(provenance, evidence)
    assert result.valid, result.to_dict()
    assert report.valid
    assert report.warning_count == 1
    assert report.error_count == 0
    assert report.diagnostics[0].severity is DiagnosticSeverity.WARNING


def test_provenance_validation_reports_duplicates_dangling_refs_cycles_and_bounds() -> None:
    provenance = _provenance()
    bad = ProvenanceBundle(
        sources=provenance.sources,
        spans=(
            SourceSpan(
                span_id="span:too-far",
                source_reference_id="source:skill:1",
                start=100,
                end=200,
            ),
        ),
        producers=provenance.producers,
        configurations=provenance.configurations,
        bindings=(
            ProvenanceBinding(
                subject_id="node:a",
                source_reference_ids=("source:missing",),
                source_span_ids=("span:missing",),
                parent_subject_ids=("node:b",),
                producer_id="producer:missing",
                configuration_id="configuration:missing",
            ),
            ProvenanceBinding(
                subject_id="node:b",
                parent_subject_ids=("node:a",),
            ),
            ProvenanceBinding(
                subject_id="node:b",
                source_reference_ids=("source:skill:1",),
            ),
        ),
    )
    result = bad.validate_cross_references()
    codes = {issue.code for issue in result.issues}

    assert not result.valid
    assert {
        "ir.reference.duplicate",
        "ir.provenance.source_reference.missing",
        "ir.provenance.span.missing",
        "ir.provenance.parent_subject.cycle",
        "ir.provenance.producer.missing",
        "ir.provenance.configuration.missing",
        "ir.provenance.span.out_of_bounds",
    } <= codes
    assert {issue.severity for issue in result.issues} == {"error"}
    with pytest.raises(ProvenanceValidationError):
        bad.assert_valid()


def test_evidence_validation_reports_all_external_and_lineage_errors() -> None:
    first = EvidenceReference(
        evidence_id="evidence:a",
        kind="receipt",
        content_sha256="a" * 64,
        uri="memory://a",
        source_reference_ids=("source:missing",),
        source_span_ids=("span:missing",),
        subject_ids=("subject:missing",),
        parent_evidence_ids=("evidence:b",),
        producer_id="producer:missing",
        configuration_id="configuration:missing",
    )
    second = EvidenceReference(
        evidence_id="evidence:b",
        kind="receipt",
        content_sha256="b" * 64,
        uri="memory://b",
        parent_evidence_ids=("evidence:a",),
    )
    collection = EvidenceCollection((first, second, second))
    result = collection.validate_cross_references(_provenance())
    codes = {issue.code for issue in result.issues}

    assert not result.valid
    assert {
        "ir.reference.duplicate",
        "ir.evidence.parent.cycle",
        "ir.evidence.source_reference.missing",
        "ir.evidence.span.missing",
        "ir.evidence.subject.missing",
        "ir.evidence.producer.missing",
        "ir.evidence.configuration.missing",
    } <= codes
    with pytest.raises(EvidenceValidationError):
        collection.assert_valid(_provenance())


def test_diagnostic_cross_reference_and_content_address_tampering_is_detected() -> None:
    provenance = _provenance()
    evidence = _evidence()
    original = _report().diagnostics[0]
    tampered_payload = original.to_dict()
    tampered_payload["message"] = "Message changed after identifier assignment."
    tampered_payload["source_reference_ids"] = ["source:missing"]
    tampered_payload["source_span_ids"] = ["span:missing"]
    tampered_payload["evidence_reference_ids"] = ["evidence:missing"]
    tampered_payload["subject_id"] = "subject:missing"
    tampered_payload["producer_id"] = "producer:missing"
    tampered_payload["configuration_id"] = "configuration:missing"
    tampered = Diagnostic.from_dict(tampered_payload)
    result = DiagnosticReport((tampered,)).validate_cross_references(
        provenance, evidence
    )
    codes = {issue.code for issue in result.issues}

    assert not result.valid
    assert {
        "ir.diagnostic.content_id.mismatch",
        "ir.diagnostic.source_reference.missing",
        "ir.diagnostic.span.missing",
        "ir.diagnostic.evidence.missing",
        "ir.diagnostic.subject.missing",
        "ir.diagnostic.producer.missing",
        "ir.diagnostic.configuration.missing",
    } <= codes
    converted = diagnostics_from_validation(result)
    assert converted
    assert all(item.severity is DiagnosticSeverity.ERROR for item in converted)


def test_diagnostic_code_and_severity_are_strict_and_stable() -> None:
    warning = Diagnostic(
        code="security.migration.loss",
        message="One extension could not be migrated.",
        severity="warning",
    )
    assert warning.severity is DiagnosticSeverity.WARNING
    assert Diagnostic.from_dict(warning.to_dict()).diagnostic_id == (
        warning.diagnostic_id
    )
    assert DiagnosticReport((warning,)).valid

    with pytest.raises(DiagnosticValidationError):
        Diagnostic(code="not namespaced", message="bad")
    with pytest.raises(DiagnosticValidationError):
        Diagnostic(
            code="security.migration.loss",
            message="bad",
            severity="success",
        )


def test_invalid_scalar_and_json_values_fail_closed() -> None:
    with pytest.raises(ProvenanceValidationError):
        SourceSpan("span:bad", "source:skill:1", True, 2)
    with pytest.raises(ProvenanceValidationError):
        SourceReference(
            reference_id="source:bad",
            source_uri="https://example.test",
            source_id="source",
            revision="main",
            content_sha256="0" * 64,
        )
    with pytest.raises(ProvenanceValidationError):
        SourceReference(
            reference_id="source:bad-digest",
            source_uri="https://example.test",
            source_id="source",
            revision="8c2dbbc",
            content_sha256="not-a-digest",
        )
    with pytest.raises(ProvenanceValidationError):
        ConfigurationBinding(
            configuration_id="configuration:bad",
            content_sha256="0" * 64,
            metadata={"temperature": float("nan")},
        )
    with pytest.raises(EvidenceValidationError):
        EvidenceReference(
            evidence_id="evidence:no-location",
            kind="artifact",
            content_sha256="0" * 64,
        )
