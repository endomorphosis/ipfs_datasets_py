"""Integration tests: analysis inputs → versioned application dossier (PATLAW-050).

Uses compact synthetic fixtures rather than bulk golden dumps. Exercises the
orchestration surface that binds artifacts, events, and analysis section
digests into one replayable dossier, verifying:

* material digest sensitivity
* provenance tracing
* missing/unsupported warnings
* private classification propagation across derived records
"""

from __future__ import annotations

import itertools
from typing import Iterator

from ipfs_datasets_py.processors.domains.uspto.artifact_manifest import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactManifest,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    MatterEvent,
    MatterEventKind,
    ReviewState,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
    BundleSectionKind,
    BundleWarningCode,
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
# Compact fixtures (synthetic matter)
# ---------------------------------------------------------------------------

_MATTER = "matter:int-dossier-1"
_ART_OA = "art:int-oa-1"
_ART_SUB = "art:int-sub-1"
_DIGEST_OA = sha256_hex(b"oa-bytes-int-v1")
_DIGEST_SUB = sha256_hex(b"sub-bytes-int-v1")
_AUTH = "auth:usc-112b-2011"

_seq: Iterator[int] = itertools.count(1)


def _reset() -> None:
    global _seq
    _seq = itertools.count(1)


def _ids() -> str:
    return f"int:{next(_seq):04d}"


def _artifact(
    artifact_id: str,
    sha: str,
    *,
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
) -> ArtifactManifest:
    enc = None
    if classification in (
        DisclosureClassification.CONFIDENTIAL_APPLICATION,
        DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
        DisclosureClassification.UNKNOWN,
    ):
        enc = "tenant:int-enc"
    return ArtifactManifest(
        schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
        artifact_id=artifact_id,
        sha256=sha,
        size_bytes=2048,
        classification=classification,
        media_type="application/pdf",
        media_signature="pdf",
        private_cid=None,
        public_cid=None,
        encryption_namespace=enc,
        matter_id=_MATTER,
        source_receipt_id=f"rcpt:{artifact_id}",
        authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
        parent_artifact_ids=(),
        parser_versions={"pdf": "patlaw-pdf@1"},
        labels={"channel": "integration"},
    )


def _event(event_id: str, *artifact_ids: str) -> MatterEvent:
    return MatterEvent(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        event_id=event_id,
        matter_id=_MATTER,
        kind=MatterEventKind.DOCUMENT,
        event_utc="2024-03-15T18:00:00Z",
        source_receipt_id="rcpt:evt",
        description_digest=sha256_hex(event_id),
        related_artifact_ids=tuple(artifact_ids),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        metadata={},
    )


def _sec(
    kind: BundleSectionKind,
    record_id: str,
    digest_seed: bytes,
    *,
    artifacts: tuple[str, ...] = (_ART_OA,),
    authority: tuple[str, ...] = (),
    schema: str = "uspto.analysis.v1",
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
    ruleset: str = "rules@1",
) -> CompactSectionInput:
    return CompactSectionInput(
        kind=kind,
        record_id=record_id,
        schema_version=schema,
        content_digest=sha256_hex(digest_seed),
        classification=classification,
        source_artifact_ids=artifacts,
        authority_ids=authority,
        ruleset_versions={"section": ruleset},
    )


def _synthetic_workflow_input(
    *,
    private: bool = False,
    extra_unsupported: tuple[str, ...] = (),
    mutate_requirement_digest: bytes | None = None,
) -> DossierInput:
    classification = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
        if private
        else DisclosureClassification.PUBLIC_USER
    )
    req_digest = mutate_requirement_digest or b"req-compilation-v1"
    return DossierInput(
        matter_id=_MATTER,
        artifacts=(
            _artifact(_ART_OA, _DIGEST_OA, classification=classification),
            _artifact(_ART_SUB, _DIGEST_SUB, classification=classification),
        ),
        events=(
            _event("evt:oa-mailed", _ART_OA),
            _event("evt:response-filed", _ART_SUB),
        ),
        compact_sections=(
            _sec(
                BundleSectionKind.STATUS_SNAPSHOT,
                "status:int-1",
                b"status-snap-v1",
                classification=DisclosureClassification.PUBLIC_OFFICIAL
                if not private
                else classification,
                schema="uspto.application-status.v1",
            ),
            _sec(
                BundleSectionKind.CLAIM_SET,
                "claims:int-1",
                b"claim-set-v1",
                artifacts=(_ART_SUB,),
                schema="uspto.matter-ledger.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.OFFICE_ACTION,
                "oa:int-1",
                b"office-action-v1",
                artifacts=(_ART_OA,),
                schema="uspto.office-action-analysis.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.REQUIREMENT,
                "req:int-1",
                req_digest,
                artifacts=(_ART_OA,),
                authority=(_AUTH,),
                schema="uspto.requirement-processor.v1",
                classification=classification,
                ruleset="requirement-compiler-rules@1",
            ),
            _sec(
                BundleSectionKind.SUBMISSION_EVIDENCE,
                "evid:int-1",
                b"evidence-map-v1",
                artifacts=(_ART_SUB,),
                schema="uspto.submission-evidence.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.COMPLIANCE,
                "cmpl:int-1",
                b"compliance-v1",
                artifacts=(_ART_OA, _ART_SUB),
                authority=(_AUTH,),
                schema="uspto.submission-compliance.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.ASSESSMENT,
                "assess:int-1",
                b"assessment-v1",
                artifacts=(_ART_SUB,),
                authority=(_AUTH,),
                schema="uspto.submission-compliance.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.AUTHORITY,
                "auth-bind:int-1",
                b"authority-v1",
                artifacts=(_ART_OA,),
                authority=(_AUTH,),
                schema="uspto.authority.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.REJECTION_MAPPING,
                "rej:int-1",
                b"rejection-map-v1",
                artifacts=(_ART_OA,),
                authority=(_AUTH,),
                schema="uspto.rejection-mapping.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.CANDIDATE_DATE,
                "deadline:int-1",
                b"deadline-v1",
                artifacts=(_ART_OA,),
                schema="uspto.deadline-processor.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.INSTRUCTION_CONSISTENCY,
                "ic:int-1",
                b"instr-consist-v1",
                artifacts=(_ART_OA,),
                authority=(_AUTH,),
                schema="uspto.instruction-consistency.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.SPAN_VALIDATION,
                "spanval:int-1",
                b"span-val-v1",
                artifacts=(_ART_OA,),
                schema="uspto.span-validator.v1",
                classification=classification,
            ),
            _sec(
                BundleSectionKind.VALIDATION_RECEIPT,
                "vr:int-1",
                b"validation-receipt-v1",
                artifacts=(_ART_OA,),
                schema="uspto.office-action-analysis.v1",
                classification=classification,
            ),
        ),
        validation_receipt_ids=("vr:int-1", "spanval:int-1"),
        unsupported_checks=extra_unsupported,
        seed_classification=classification,
        model_versions={"ocr": "tesseract@fixture"},
        ruleset_versions={"workflow": "dossier-workflow@1"},
        labels={"lane": "integration"},
        analysis_id="analysis:int-dossier-1",
        as_of_utc="2024-06-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDossierWorkflowIntegration:
    def test_end_to_end_assemble_replayable_dossier(self) -> None:
        _reset()
        proc = DossierProcessor(id_factory=_ids)
        dossier = proc.assemble(_synthetic_workflow_input())

        assert dossier.schema_version == DOSSIER_SCHEMA_VERSION
        assert dossier.output_kind == OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER
        assert dossier.matter_id == _MATTER
        assert dossier.analysis_id == "analysis:int-dossier-1"
        assert dossier.as_of_utc == "2024-06-01T00:00:00Z"

        # Inventory of bound material
        assert _ART_OA in dossier.input_artifact_ids
        assert _ART_SUB in dossier.input_artifact_ids
        for expected in (
            "req:int-1",
            "evid:int-1",
            "assess:int-1",
            "deadline:int-1",
            "rej:int-1",
            "ic:int-1",
            "cmpl:int-1",
            "claims:int-1",
            "status:int-1",
            "auth-bind:int-1",
        ):
            assert expected in dossier.section_record_ids, expected

        assert "evt:oa-mailed" in dossier.event_ids
        assert "evt:response-filed" in dossier.event_ids
        assert "vr:int-1" in dossier.validation_receipt_ids

        # Versions present
        assert "workflow" in dossier.ruleset_versions
        assert "ocr" in dossier.model_versions

        # Contract projection
        contract = dossier.to_contract_bundle()
        assert contract.bundle_id == dossier.analysis_bundle.bundle_id
        assert set(contract.input_artifact_ids) >= {_ART_OA, _ART_SUB}

        # Replay
        restored = ApplicationDossier.from_dict(dossier.to_dict())
        assert restored.content_digest == dossier.content_digest
        assert restored.bundle_digest == dossier.bundle_digest
        assert restored.to_dict() == dossier.to_dict()

    def test_material_input_change_shifts_bundle_digest(self) -> None:
        _reset()
        d1 = assemble_application_dossier(
            _synthetic_workflow_input(), id_factory=_ids
        )
        _reset()
        d2 = assemble_application_dossier(
            _synthetic_workflow_input(mutate_requirement_digest=b"req-compilation-v2"),
            id_factory=_ids,
        )
        assert d1.bundle_digest != d2.bundle_digest
        assert d1.content_digest != d2.content_digest

        # Artifact byte version change
        _reset()
        inp = _synthetic_workflow_input()
        arts = list(inp.artifacts)
        arts[0] = _artifact(_ART_OA, sha256_hex(b"oa-bytes-int-v2"))
        d3 = assemble_application_dossier(
            DossierInput(
                matter_id=inp.matter_id,
                artifacts=tuple(arts),
                events=inp.events,
                compact_sections=inp.compact_sections,
                validation_receipt_ids=inp.validation_receipt_ids,
                seed_classification=inp.seed_classification,
                model_versions=inp.model_versions,
                ruleset_versions=inp.ruleset_versions,
                labels=inp.labels,
                analysis_id=inp.analysis_id,
                as_of_utc=inp.as_of_utc,
            ),
            id_factory=_ids,
        )
        assert d3.bundle_digest != d1.bundle_digest

    def test_all_facts_trace_to_artifacts_or_authority(self) -> None:
        _reset()
        dossier = assemble_application_dossier(
            _synthetic_workflow_input(), id_factory=_ids
        )
        bundle = dossier.analysis_bundle
        # Every provenance link for analysis subjects must be traced
        analysis_subjects = {
            "req:int-1",
            "evid:int-1",
            "assess:int-1",
            "deadline:int-1",
            "rej:int-1",
            "ic:int-1",
            "cmpl:int-1",
            "auth-bind:int-1",
            "oa:int-1",
        }
        for link in bundle.provenance:
            if link.subject_id in analysis_subjects:
                assert link.is_traced, (
                    f"{link.subject_id} lacks artifact/authority provenance"
                )
        # Authority-bearing assessments must cite authority
        assess = next(p for p in bundle.provenance if p.subject_id == "assess:int-1")
        assert _AUTH in assess.authority_ids
        assert _ART_SUB in assess.artifact_ids

    def test_unsupported_and_missing_checks_in_warnings(self) -> None:
        _reset()
        # Sparse workflow: artifacts only + unsupported check
        sparse = DossierInput(
            matter_id=_MATTER,
            artifacts=(_artifact(_ART_OA, _DIGEST_OA),),
            unsupported_checks=("check:pct-national-stage",),
        )
        dossier = assemble_application_dossier(sparse, id_factory=_ids)
        codes = set(dossier.analysis_bundle.warning_codes)
        assert BundleWarningCode.UNSUPPORTED_CHECK.value in codes
        assert BundleWarningCode.MISSING_REQUIREMENTS.value in codes
        assert BundleWarningCode.MISSING_EVIDENCE.value in codes
        assert BundleWarningCode.MISSING_ASSESSMENTS.value in codes
        assert BundleWarningCode.MISSING_CANDIDATE_DATES.value in codes
        assert "check:pct-national-stage" in dossier.unsupported_checks
        assert DossierReasonCode.UNSUPPORTED_CHECKS_PRESENT.value in (
            dossier.reason_codes
        )
        assert dossier.disposition in (
            DossierDisposition.PARTIAL,
            DossierDisposition.REVIEW,
        )
        assert dossier.requires_review is True

    def test_private_classification_propagates_workflow(self) -> None:
        _reset()
        dossier = assemble_application_dossier(
            _synthetic_workflow_input(private=True), id_factory=_ids
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
            )
        # Contract projection also private
        contract = dossier.to_contract_bundle()
        assert (
            contract.classification
            is DisclosureClassification.CONFIDENTIAL_APPLICATION
        )
        assert dossier.review_state is ReviewState.REQUIRED
        assert dossier.is_private is True
        pub = dossier.public_projection()
        assert pub["is_private"] is True
        assert pub["classification"] == "confidential_application"

    def test_idempotent_reassembly_same_digest(self) -> None:
        _reset()
        inp = _synthetic_workflow_input()
        d1 = assemble_application_dossier(inp, id_factory=_ids)
        _reset()
        d2 = assemble_application_dossier(inp, id_factory=_ids)
        assert d1.bundle_digest == d2.bundle_digest
        assert d1.content_digest == d2.content_digest
        # Section ordering stable
        assert d1.section_record_ids == d2.section_record_ids

    def test_disclaimer_and_no_filing_surface(self) -> None:
        _reset()
        dossier = assemble_application_dossier(
            _synthetic_workflow_input(), id_factory=_ids
        )
        assert "not a legal opinion" in dossier.disclaimer.lower()
        assert "sign" in dossier.disclaimer.lower() or "filing" in dossier.disclaimer.lower()
        assert dossier.human_review_required is True
        # Public surface never claims all-clear for review-free filing
        pub = dossier.public_projection()
        assert pub["human_review_required"] is True
        assert pub["requires_review"] is True
