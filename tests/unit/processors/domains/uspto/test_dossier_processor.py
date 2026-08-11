"""Unit tests for versioned application dossier orchestration (PATLAW-050).

Acceptance focus:
  - Bundle digest changes for any material input/version
  - All facts and conclusions trace to artifacts/authority
  - Unsupported and missing checks appear in warnings
  - Private classification propagates to every derived record
"""

from __future__ import annotations

import itertools
from typing import Any, Iterator

import pytest

from ipfs_datasets_py.processors.domains.uspto.artifact_manifest import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactManifest,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AnalysisBundle as ContractAnalysisBundle,
    AuthorityRelation,
    DisclosureClassification,
    MatterEvent,
    MatterEventKind,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
    ANALYSIS_BUNDLE_SCHEMA_VERSION,
    AnalysisBundleBuilder,
    BundleSectionKind,
    BundleSectionRef,
    BundleWarningCode,
    ProvenanceLink,
    UsptoAnalysisBundle,
    build_analysis_bundle,
    compute_bundle_digest,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.dossier_processor import (
    DOSSIER_SCHEMA_VERSION,
    OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER,
    ApplicationDossier,
    CompactSectionInput,
    DossierDisposition,
    DossierInput,
    DossierProcessor,
    DossierReasonCode,
    assemble_application_dossier,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DIGEST_A = sha256_hex(b"artifact-bytes-a")
_DIGEST_B = sha256_hex(b"artifact-bytes-b")
_DIGEST_SEC = sha256_hex(b"section-payload-v1")
_DIGEST_SEC2 = sha256_hex(b"section-payload-v2")
_AUTH = "auth:usc-112b-2011"

_seq: Iterator[int] = itertools.count(1)


def _reset_seq() -> None:
    global _seq
    _seq = itertools.count(1)


def _id_factory() -> str:
    return f"{next(_seq):04d}"


def _processor(**kwargs: Any) -> DossierProcessor:
    _reset_seq()
    return DossierProcessor(id_factory=_id_factory, **kwargs)


def _artifact(
    *,
    artifact_id: str = "art:oa:1",
    sha256: str = _DIGEST_A,
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
    encryption_namespace: str | None = None,
) -> ArtifactManifest:
    if (
        classification
        in (
            DisclosureClassification.CONFIDENTIAL_APPLICATION,
            DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
            DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
            DisclosureClassification.UNKNOWN,
        )
        and encryption_namespace is None
    ):
        encryption_namespace = "tenant:test-enc"
    return ArtifactManifest(
        schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
        artifact_id=artifact_id,
        sha256=sha256,
        size_bytes=128,
        classification=classification,
        media_type="application/pdf",
        media_signature="pdf",
        private_cid=None,
        public_cid=None,
        encryption_namespace=encryption_namespace,
        matter_id="matter:unit-1",
        source_receipt_id="rcpt:1",
        authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
        parent_artifact_ids=(),
        parser_versions={"pdf": "1.0"},
        labels={},
    )


def _event(
    *,
    event_id: str = "evt:1",
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_OFFICIAL,
    related: tuple[str, ...] = ("art:oa:1",),
) -> MatterEvent:
    return MatterEvent(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        event_id=event_id,
        matter_id="matter:unit-1",
        kind=MatterEventKind.STATUS,
        event_utc="2024-06-01T12:00:00Z",
        source_receipt_id="rcpt:status:1",
        description_digest=sha256_hex("status:awaiting response"),
        related_artifact_ids=related,
        classification=classification,
        metadata={},
    )


def _compact(
    *,
    kind: BundleSectionKind = BundleSectionKind.REQUIREMENT,
    record_id: str = "req:1",
    digest: str = _DIGEST_SEC,
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
    artifacts: tuple[str, ...] = ("art:oa:1",),
    authority: tuple[str, ...] = (_AUTH,),
    schema_version: str = "uspto.requirement-processor.v1",
    ruleset: MappingLike | None = None,
    require_provenance: bool = True,
) -> CompactSectionInput:
    return CompactSectionInput(
        kind=kind,
        record_id=record_id,
        schema_version=schema_version,
        content_digest=digest,
        classification=classification,
        source_artifact_ids=artifacts,
        authority_ids=authority,
        ruleset_versions=ruleset or {"requirement": "requirement-compiler-rules@1"},
        require_provenance=require_provenance,
    )


# typing helper without importing Mapping for the default
MappingLike = dict[str, str]


def _full_input(**overrides: Any) -> DossierInput:
    base: dict[str, Any] = {
        "matter_id": "matter:unit-1",
        "artifacts": (_artifact(),),
        "events": (_event(),),
        "compact_sections": (
            _compact(kind=BundleSectionKind.REQUIREMENT, record_id="req:1"),
            _compact(
                kind=BundleSectionKind.SUBMISSION_EVIDENCE,
                record_id="evid:1",
                digest=sha256_hex(b"evidence-v1"),
                artifacts=("art:sub:1",),
                authority=(),
                schema_version="uspto.submission-evidence.v1",
            ),
            _compact(
                kind=BundleSectionKind.ASSESSMENT,
                record_id="assess:1",
                digest=sha256_hex(b"assess-v1"),
                authority=(_AUTH,),
                schema_version="uspto.submission-compliance.v1",
            ),
            _compact(
                kind=BundleSectionKind.CANDIDATE_DATE,
                record_id="deadline:1",
                digest=sha256_hex(b"deadline-v1"),
                schema_version="uspto.deadline-processor.v1",
            ),
            _compact(
                kind=BundleSectionKind.CLAIM_SET,
                record_id="claims:1",
                digest=sha256_hex(b"claims-v1"),
                schema_version="uspto.matter-ledger.v1",
            ),
            _compact(
                kind=BundleSectionKind.STATUS_SNAPSHOT,
                record_id="status:v1",
                digest=sha256_hex(b"status-v1"),
                classification=DisclosureClassification.PUBLIC_OFFICIAL,
                schema_version="uspto.application-status.v1",
            ),
            _compact(
                kind=BundleSectionKind.VALIDATION_RECEIPT,
                record_id="vr:1",
                digest=sha256_hex(b"vr-v1"),
                schema_version="uspto.span-validator.v1",
                require_provenance=False,
            ),
        ),
        "validation_receipt_ids": ("vr:1",),
        "seed_classification": DisclosureClassification.PUBLIC_USER,
        "model_versions": {"extractor": "patlaw-extract@1"},
        "labels": {"fixture": "unit"},
    }
    base.update(overrides)
    return DossierInput(**base)


# ---------------------------------------------------------------------------
# Analysis bundle unit surface
# ---------------------------------------------------------------------------


class TestAnalysisBundle:
    def test_digest_stable_for_identical_material(self) -> None:
        section = BundleSectionRef(
            section_id="sec:1",
            kind=BundleSectionKind.REQUIREMENT,
            record_id="req:1",
            schema_version="uspto.requirement-processor.v1",
            content_digest=_DIGEST_SEC,
            classification=DisclosureClassification.PUBLIC_USER,
            source_artifact_ids=("art:oa:1",),
            authority_ids=(_AUTH,),
        )
        a = build_analysis_bundle(
            matter_id="matter:1",
            sections=(section,),
            input_artifact_ids=("art:oa:1",),
            id_factory=lambda: "fixed",
            bundle_id="bundle:fixed",
        )
        b = build_analysis_bundle(
            matter_id="matter:1",
            sections=(section,),
            input_artifact_ids=("art:oa:1",),
            id_factory=lambda: "fixed",
            bundle_id="bundle:fixed",
        )
        assert a.bundle_digest == b.bundle_digest
        assert a.to_dict() == b.to_dict()

    def test_digest_changes_when_section_version_changes(self) -> None:
        s1 = BundleSectionRef(
            section_id="sec:1",
            kind=BundleSectionKind.REQUIREMENT,
            record_id="req:1",
            schema_version="uspto.requirement-processor.v1",
            content_digest=_DIGEST_SEC,
            classification=DisclosureClassification.PUBLIC_USER,
            source_artifact_ids=("art:1",),
            authority_ids=(_AUTH,),
        )
        s2 = BundleSectionRef(
            section_id="sec:1",
            kind=BundleSectionKind.REQUIREMENT,
            record_id="req:1",
            schema_version="uspto.requirement-processor.v1",
            content_digest=_DIGEST_SEC2,
            classification=DisclosureClassification.PUBLIC_USER,
            source_artifact_ids=("art:1",),
            authority_ids=(_AUTH,),
        )
        a = build_analysis_bundle(matter_id="m", sections=(s1,), id_factory=_id_factory)
        _reset_seq()
        b = build_analysis_bundle(matter_id="m", sections=(s2,), id_factory=_id_factory)
        assert a.bundle_digest != b.bundle_digest

    def test_digest_changes_when_ruleset_version_changes(self) -> None:
        section = BundleSectionRef(
            section_id="sec:1",
            kind=BundleSectionKind.REQUIREMENT,
            record_id="req:1",
            schema_version="uspto.requirement-processor.v1",
            content_digest=_DIGEST_SEC,
            classification=DisclosureClassification.PUBLIC_USER,
            source_artifact_ids=("art:1",),
            authority_ids=(_AUTH,),
            ruleset_versions={"requirement": "rules@1"},
        )
        a = build_analysis_bundle(
            matter_id="m",
            sections=(section,),
            ruleset_versions={"extra": "v1"},
            id_factory=_id_factory,
        )
        _reset_seq()
        b = build_analysis_bundle(
            matter_id="m",
            sections=(section,),
            ruleset_versions={"extra": "v2"},
            id_factory=_id_factory,
        )
        assert a.bundle_digest != b.bundle_digest

    def test_unsupported_checks_appear_in_warnings(self) -> None:
        bundle = build_analysis_bundle(
            matter_id="m",
            unsupported_checks=("check:fee-prover", "check:entity-status"),
            input_artifact_ids=("art:1",),
            id_factory=_id_factory,
        )
        assert "check:fee-prover" in bundle.unsupported_checks
        assert BundleWarningCode.UNSUPPORTED_CHECK.value in bundle.warning_codes
        assert any("Unsupported check" in w.message for w in bundle.warnings)

    def test_missing_provenance_emits_warning(self) -> None:
        builder = AnalysisBundleBuilder(matter_id="m", id_factory=_id_factory)
        builder.add_provenance(
            ProvenanceLink(
                link_id="prov:1",
                subject_id="fact:orphan",
                subject_kind="assessment",
                artifact_ids=(),
                authority_ids=(),
                span_ids=(),
            )
        )
        bundle = builder.build()
        assert BundleWarningCode.MISSING_PROVENANCE.value in bundle.warning_codes
        assert "fact:orphan" in bundle.untraced_subjects()

    def test_projects_to_contract_analysis_bundle(self) -> None:
        section = BundleSectionRef(
            section_id="sec:1",
            kind=BundleSectionKind.REQUIREMENT,
            record_id="req:1",
            schema_version="uspto.requirement-processor.v1",
            content_digest=_DIGEST_SEC,
            classification=DisclosureClassification.PUBLIC_USER,
            source_artifact_ids=("art:1",),
            authority_ids=(_AUTH,),
        )
        bundle = build_analysis_bundle(
            matter_id="m",
            sections=(section,),
            input_artifact_ids=("art:1",),
            validation_receipt_ids=("vr:1",),
            unsupported_checks=("check:x",),
            id_factory=_id_factory,
        )
        contract = bundle.to_contract_bundle()
        assert isinstance(contract, ContractAnalysisBundle)
        assert contract.bundle_id == bundle.bundle_id
        assert contract.input_artifact_ids == bundle.input_artifact_ids
        assert "check:x" in contract.unsupported_checks
        assert contract.classification is bundle.classification

    def test_round_trip_dict(self) -> None:
        section = BundleSectionRef(
            section_id="sec:1",
            kind=BundleSectionKind.AUTHORITY,
            record_id="auth:1",
            schema_version="uspto.authority.v1",
            content_digest=_DIGEST_SEC,
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            authority_ids=(_AUTH,),
            source_artifact_ids=("art:statute:1",),
        )
        bundle = build_analysis_bundle(
            matter_id="m", sections=(section,), id_factory=_id_factory
        )
        restored = UsptoAnalysisBundle.from_dict(bundle.to_dict())
        assert restored.bundle_digest == bundle.bundle_digest
        assert restored.to_dict() == bundle.to_dict()
        assert canonical_json(restored.to_dict()) == bundle.to_canonical_json()

    def test_compute_bundle_digest_matches_built_bundle(self) -> None:
        section = BundleSectionRef(
            section_id="sec:1",
            kind=BundleSectionKind.REQUIREMENT,
            record_id="req:1",
            schema_version="uspto.requirement-processor.v1",
            content_digest=_DIGEST_SEC,
            classification=DisclosureClassification.PUBLIC_USER,
            source_artifact_ids=("art:1",),
            authority_ids=(_AUTH,),
        )
        bundle = build_analysis_bundle(
            matter_id="m",
            sections=(section,),
            input_artifact_ids=("art:1",),
            id_factory=lambda: "x",
            bundle_id="bundle:x",
        )
        recomputed = compute_bundle_digest(
            matter_id=bundle.matter_id,
            disposition=bundle.disposition,
            review_state=bundle.review_state,
            classification=bundle.classification,
            input_artifact_ids=bundle.input_artifact_ids,
            output_artifact_ids=bundle.output_artifact_ids,
            sections=bundle.sections,
            provenance=bundle.provenance,
            warnings=bundle.warnings,
            warning_codes=bundle.warning_codes,
            unsupported_checks=bundle.unsupported_checks,
            model_versions=bundle.model_versions,
            ruleset_versions=bundle.ruleset_versions,
            validation_receipt_ids=bundle.validation_receipt_ids,
            labels=bundle.labels,
            analysis_id=bundle.analysis_id,
        )
        assert recomputed == bundle.bundle_digest


# ---------------------------------------------------------------------------
# Dossier processor
# ---------------------------------------------------------------------------


class TestDossierProcessor:
    def test_assemble_binds_material_inputs(self) -> None:
        proc = _processor()
        dossier = proc.assemble(_full_input())
        assert dossier.schema_version == DOSSIER_SCHEMA_VERSION
        assert dossier.output_kind == OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER
        assert dossier.matter_id == "matter:unit-1"
        assert "art:oa:1" in dossier.input_artifact_ids
        assert "req:1" in dossier.section_record_ids
        assert "assess:1" in dossier.section_record_ids
        assert dossier.bundle_digest == dossier.analysis_bundle.bundle_digest
        assert len(dossier.bundle_digest) == 64
        assert dossier.human_review_required is True
        assert DossierReasonCode.ASSEMBLED.value in dossier.reason_codes

    def test_bundle_digest_changes_for_material_section_change(self) -> None:
        proc = _processor()
        d1 = proc.assemble(_full_input())
        _reset_seq()
        proc2 = _processor()
        sections = list(_full_input().compact_sections)
        # replace requirement digest
        sections[0] = _compact(
            kind=BundleSectionKind.REQUIREMENT,
            record_id="req:1",
            digest=_DIGEST_SEC2,
        )
        d2 = proc2.assemble(_full_input(compact_sections=tuple(sections)))
        assert d1.bundle_digest != d2.bundle_digest
        assert d1.content_digest != d2.content_digest

    def test_bundle_digest_changes_for_artifact_version_change(self) -> None:
        proc = _processor()
        d1 = proc.assemble(_full_input())
        _reset_seq()
        proc2 = _processor()
        d2 = proc2.assemble(
            _full_input(artifacts=(_artifact(sha256=_DIGEST_B),))
        )
        assert d1.bundle_digest != d2.bundle_digest

    def test_missing_checks_appear_in_warnings(self) -> None:
        proc = _processor()
        # Minimal: only matter_id → many missing warnings
        dossier = proc.assemble(
            DossierInput(matter_id="matter:sparse")
        )
        codes = set(dossier.analysis_bundle.warning_codes)
        assert BundleWarningCode.MISSING_ARTIFACT_MANIFEST.value in codes
        assert BundleWarningCode.MISSING_REQUIREMENTS.value in codes
        assert BundleWarningCode.MISSING_EVIDENCE.value in codes
        assert BundleWarningCode.MISSING_ASSESSMENTS.value in codes
        assert BundleWarningCode.MISSING_CANDIDATE_DATES.value in codes
        assert dossier.disposition in (
            DossierDisposition.PARTIAL,
            DossierDisposition.EMPTY,
            DossierDisposition.REVIEW,
        )
        assert dossier.requires_review is True
        assert any("No requirements" in w or "missing" in w.lower() for w in dossier.warnings)

    def test_unsupported_checks_surface_on_dossier(self) -> None:
        proc = _processor()
        dossier = proc.assemble(
            _full_input(unsupported_checks=("check:foreign-priority",))
        )
        assert "check:foreign-priority" in dossier.unsupported_checks
        assert DossierReasonCode.UNSUPPORTED_CHECKS_PRESENT.value in dossier.reason_codes
        assert any(
            "Unsupported check" in w or "foreign-priority" in w
            for w in dossier.warnings
        )

    def test_facts_trace_to_artifacts_and_authority(self) -> None:
        proc = _processor()
        dossier = proc.assemble(_full_input())
        bundle = dossier.analysis_bundle
        # Requirement and assessment must be traced
        req_links = [
            p
            for p in bundle.provenance
            if p.subject_id == "req:1"
        ]
        assert req_links
        assert req_links[0].is_traced
        assert "art:oa:1" in req_links[0].artifact_ids
        assert _AUTH in req_links[0].authority_ids

        assess_links = [p for p in bundle.provenance if p.subject_id == "assess:1"]
        assert assess_links
        assert assess_links[0].is_traced

        # Untraced subjects should be empty for fully-traced sections
        # (evidence without authority is still traced via artifacts)
        untraced = set(bundle.untraced_subjects())
        assert "req:1" not in untraced
        assert "assess:1" not in untraced

    def test_untraced_compact_section_emits_provenance_warning(self) -> None:
        proc = _processor()
        orphan = CompactSectionInput(
            kind=BundleSectionKind.ASSESSMENT,
            record_id="assess:orphan",
            schema_version="uspto.submission-compliance.v1",
            content_digest=sha256_hex(b"orphan"),
            classification=DisclosureClassification.PUBLIC_USER,
            source_artifact_ids=(),
            authority_ids=(),
            require_provenance=True,
        )
        dossier = proc.assemble(
            DossierInput(
                matter_id="matter:orphan",
                artifacts=(_artifact(),),
                compact_sections=(orphan,),
            )
        )
        assert BundleWarningCode.MISSING_PROVENANCE.value in (
            dossier.analysis_bundle.warning_codes
        )
        assert "assess:orphan" in dossier.analysis_bundle.untraced_subjects()
        assert DossierReasonCode.PROVENANCE_GAPS.value in dossier.reason_codes

    def test_private_classification_propagates_to_every_derived_record(self) -> None:
        proc = _processor()
        private_art = _artifact(
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        )
        # Public-looking compact sections must be reclassified on the bundle
        dossier = proc.assemble(
            _full_input(
                artifacts=(private_art,),
                seed_classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert (
            dossier.classification
            is DisclosureClassification.CONFIDENTIAL_APPLICATION
        )
        assert (
            dossier.analysis_bundle.classification
            is DisclosureClassification.CONFIDENTIAL_APPLICATION
        )
        for section in dossier.analysis_bundle.sections:
            assert (
                section.classification
                is DisclosureClassification.CONFIDENTIAL_APPLICATION
            ), f"section {section.record_id} not private"
        assert dossier.is_private is True
        assert dossier.review_state is ReviewState.REQUIRED
        assert DossierReasonCode.PRIVATE_CLASSIFICATION.value in dossier.reason_codes
        assert BundleWarningCode.PRIVATE_MATERIAL.value in (
            dossier.analysis_bundle.warning_codes
        )
        assert BundleWarningCode.CLASSIFICATION_PROPAGATED.value in (
            dossier.analysis_bundle.warning_codes
        )

    def test_unknown_classification_quarantines(self) -> None:
        proc = _processor()
        unknown_art = _artifact(
            classification=DisclosureClassification.UNKNOWN,
        )
        dossier = proc.assemble(
            DossierInput(
                matter_id="matter:q",
                artifacts=(unknown_art,),
                seed_classification=DisclosureClassification.UNKNOWN,
            )
        )
        assert dossier.classification is DisclosureClassification.UNKNOWN
        assert dossier.disposition is DossierDisposition.QUARANTINE
        assert dossier.review_state is ReviewState.REQUIRED
        assert DossierReasonCode.QUARANTINE.value in dossier.reason_codes

    def test_contract_bundle_projection(self) -> None:
        proc = _processor()
        dossier = proc.assemble(_full_input())
        contract = dossier.to_contract_bundle()
        assert isinstance(contract, ContractAnalysisBundle)
        assert contract.classification is dossier.classification
        assert set(contract.input_artifact_ids) >= {"art:oa:1"}

    def test_round_trip_dossier(self) -> None:
        proc = _processor()
        dossier = proc.assemble(_full_input())
        restored = ApplicationDossier.from_dict(dossier.to_dict())
        assert restored.dossier_id == dossier.dossier_id
        assert restored.bundle_digest == dossier.bundle_digest
        assert restored.content_digest == dossier.content_digest
        assert restored.analysis_bundle.bundle_digest == (
            dossier.analysis_bundle.bundle_digest
        )
        # Full canonical equality
        assert restored.to_dict() == dossier.to_dict()

    def test_public_projection_omits_body_payloads(self) -> None:
        proc = _processor()
        dossier = proc.assemble(_full_input())
        pub = dossier.public_projection()
        assert "analysis_bundle" in pub
        assert pub["matter_id"] == "matter:unit-1"
        assert "disclaimer" in pub
        # Nested public projection is counts/ids, not full sections list content
        assert "section_count" in pub["analysis_bundle"]
        assert "sections" not in pub["analysis_bundle"]

    def test_module_level_assemble_helper(self) -> None:
        _reset_seq()
        dossier = assemble_application_dossier(
            _full_input(), id_factory=_id_factory
        )
        assert isinstance(dossier, ApplicationDossier)
        assert dossier.matter_id == "matter:unit-1"

    def test_process_alias(self) -> None:
        proc = _processor()
        d1 = proc.assemble(_full_input())
        _reset_seq()
        proc2 = _processor()
        d2 = proc2.process(_full_input())
        assert d1.bundle_digest == d2.bundle_digest

    def test_events_bound_into_sections(self) -> None:
        proc = _processor()
        dossier = proc.assemble(_full_input())
        assert "evt:1" in dossier.event_ids
        kinds = {s.kind for s in dossier.analysis_bundle.sections}
        assert BundleSectionKind.MATTER_EVENT in kinds
        assert BundleSectionKind.ARTIFACT_MANIFEST in kinds

    def test_schema_version_on_analysis_bundle(self) -> None:
        proc = _processor()
        dossier = proc.assemble(_full_input())
        assert (
            dossier.analysis_bundle.schema_version == ANALYSIS_BUNDLE_SCHEMA_VERSION
        )


class TestDossierInputValidation:
    def test_rejects_non_artifact_manifest(self) -> None:
        with pytest.raises(TypeError, match="ArtifactManifest"):
            DossierInput(matter_id="m", artifacts=("not-an-artifact",))  # type: ignore[arg-type]

    def test_rejects_bad_matter_id(self) -> None:
        with pytest.raises(ValueError):
            DossierInput(matter_id="")

    def test_compact_section_requires_digest(self) -> None:
        with pytest.raises(ValueError, match="content_digest|SHA-256|sha256"):
            CompactSectionInput(
                kind=BundleSectionKind.OTHER,
                record_id="x",
                schema_version="v1",
                content_digest="not-a-digest",
            )
