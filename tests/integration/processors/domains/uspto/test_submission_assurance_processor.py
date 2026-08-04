"""Integration tests for serialized submission-assurance workflow (PATLAW-140).

Acceptance:

* One call accepts tenant/matter + authorized documents without hand-built
  middle-stage objects
* Adapter/core success cannot conceal outage, quarantine, incomplete analysis,
  or mandatory review
* Result status reflects sync/extraction/authority/proof/compliance coverage
* Output lists satisfied/missing/contradictory/unknown/review items with exact
  provenance
* No command files, pays, signs, or claims legal advice
* Resume reuses stages by input digest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.core.protocol import (
    InputType,
    ProcessingContext,
)
from ipfs_datasets_py.processors.domains.uspto.api import (
    ASSURANCE_OPERATIONS,
    USPTOAnalysisAPI,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.matter_analysis_processor import (
    MatterDocumentInput,
)
from ipfs_datasets_py.processors.domains.uspto.submission_assurance_processor import (
    ASSURANCE_STAGE_ORDER,
    SUBMISSION_ASSURANCE_INTERFACE,
    SUBMISSION_ASSURANCE_SCHEMA_VERSION,
    AssuranceDisposition,
    AssuranceItemKind,
    CoverageDimension,
    CoverageStatus,
    SubmissionAssuranceCheckpointStore,
    SubmissionAssuranceInput,
    SubmissionAssuranceProcessor,
    SubmissionAssuranceResult,
    assert_assurance_action_allowed,
    create_submission_assurance_processor,
    parser_digest,
    stage_idempotency_key,
    AssuranceStage,
)
from ipfs_datasets_py.processors.adapters.uspto_adapter import USPTOProcessorAdapter

OA_TEXT = """UNITED STATES PATENT AND TRADEMARK OFFICE
NON-FINAL OFFICE ACTION
Application No. 16/123,456
Mailing Date: January 15, 2024

Claim Rejections - 35 USC 103
Claims 1-3 are rejected under 35 U.S.C. 103 as being unpatentable over Smith
in view of Jones.

A shortened statutory period for reply is set to expire THREE MONTHS from the
mailing date of this communication.
"""

REMARKS_TEXT = (
    "Applicant respectfully submits remarks and claim amendments. "
    "Claim 1 is amended to overcome the rejection under 35 U.S.C. 103."
)


def _processor(tmp_path: Path) -> SubmissionAssuranceProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"assurance:test:{counter['n']:04d}"

    return create_submission_assurance_processor(
        checkpoint_dir=tmp_path / "ckpt",
        matter_checkpoint_root=tmp_path / "matter-ckpt",
        id_factory=_ids,
    )


def _full_docs() -> tuple[MatterDocumentInput, ...]:
    pub = DisclosureClassification.PUBLIC_USER
    return (
        MatterDocumentInput(
            document_id="art:oa1",
            role="office_action",
            document_code="CTNF",
            text=OA_TEXT,
            classification=pub,
        ),
        MatterDocumentInput(
            document_id="art:spec",
            role="specification",
            text="DETAILED DESCRIPTION of the invention. Specification body.",
            classification=pub,
        ),
        MatterDocumentInput(
            document_id="art:claims",
            role="claims",
            text="1. A method comprising claim language.",
            classification=pub,
        ),
        MatterDocumentInput(
            document_id="art:draw",
            role="drawings",
            text="FIG. 1 is a drawing of the embodiment.",
            classification=pub,
        ),
        MatterDocumentInput(
            document_id="art:ads",
            role="ads",
            text="Application Data Sheet inventors and correspondence address.",
            classification=pub,
        ),
        MatterDocumentInput(
            document_id="art:oath",
            role="oath",
            text="Declaration and oath signed by inventor.",
            classification=pub,
        ),
        MatterDocumentInput(
            document_id="art:fee",
            role="fee",
            text="Fee payment receipt for utility filing fee.",
            classification=pub,
        ),
        MatterDocumentInput(
            document_id="art:seq",
            role="sequence_listing",
            text="<SequenceListing>SEQ ID NO:1</SequenceListing>",
            classification=pub,
        ),
        MatterDocumentInput(
            document_id="art:rem1",
            role="remarks",
            text=REMARKS_TEXT,
            classification=pub,
        ),
    )


def _base_input(
    *,
    assurance_id: str = "assurance:base-1",
    documents: tuple[MatterDocumentInput, ...] | None = None,
    **kwargs,
) -> SubmissionAssuranceInput:
    data = {
        "tenant_id": "tenant-patlaw-140",
        "matter_id": "matter:16-123456",
        "assurance_id": assurance_id,
        "application_number": "16123456",
        "documents": documents if documents is not None else _full_docs(),
        "status_snapshot": {
            "application_number": "16123456",
            "mailing_date": "2024-01-15",
            "status_code": "PEND",
            "phase": "examination",
        },
        "source_profile": "offline_authorized",
        "application_type": "utility",
        "scenario": "new_application",
        "as_of_utc": "2024-01-15T00:00:00Z",
        "authority_snapshot_id": "auth:snap-1",
        "classification": DisclosureClassification.PUBLIC_USER,
        "labels": {"suite": "submission-assurance"},
        "offline": True,
        "run_preflight": False,
    }
    data.update(kwargs)
    return SubmissionAssuranceInput(**data)


# ---------------------------------------------------------------------------
# Schema / helpers
# ---------------------------------------------------------------------------


def test_schema_and_idempotency_helpers() -> None:
    assert SUBMISSION_ASSURANCE_SCHEMA_VERSION.startswith("uspto.submission-assurance")
    assert SUBMISSION_ASSURANCE_INTERFACE.startswith("SubmissionAssuranceProcessor")
    digest = parser_digest()
    assert len(digest) == 64
    key_a = stage_idempotency_key(
        assurance_id="assurance:1",
        stage=AssuranceStage.AUTHORIZE,
        input_digest="a" * 64,
        parser_digest_value=digest,
    )
    key_b = stage_idempotency_key(
        assurance_id="assurance:1",
        stage=AssuranceStage.AUTHORIZE,
        input_digest="a" * 64,
        parser_digest_value=digest,
    )
    key_c = stage_idempotency_key(
        assurance_id="assurance:1",
        stage=AssuranceStage.MATTER_ANALYSIS,
        input_digest="a" * 64,
        parser_digest_value=digest,
    )
    assert key_a == key_b
    assert key_a != key_c
    assert len(ASSURANCE_STAGE_ORDER) == 8


def test_forbidden_actions_fail_closed() -> None:
    for action in ("sign", "pay", "file", "submit", "legal_advice"):
        with pytest.raises(Exception) as exc:
            assert_assurance_action_allowed(action)
        assert getattr(exc.value, "code", "") == "forbidden_action"


# ---------------------------------------------------------------------------
# One-shot without middle-stage objects
# ---------------------------------------------------------------------------


def test_one_shot_without_hand_built_middle_stages(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.assure(_base_input())
    assert isinstance(result, SubmissionAssuranceResult)
    assert result.schema_version == SUBMISSION_ASSURANCE_SCHEMA_VERSION
    assert result.transport_ok is True
    assert result.is_legal_advice is False
    assert result.is_review_only is True
    assert result.is_exhaustive is False
    assert "not legal advice" in result.disclaimer.lower()
    assert list(result.committed_stages) == [s.value for s in ASSURANCE_STAGE_ORDER]
    assert result.dossier_id is not None
    assert result.bundle_id is not None
    # Coverage axes present
    for dim in CoverageDimension:
        assert dim.value in result.coverage.statuses
    # Provenance-backed item buckets present on the public projection
    public = result.public_projection()
    for key in (
        "satisfied_items",
        "missing_items",
        "contradictory_items",
        "unknown_items",
        "review_items",
        "coverage",
        "transport_ok",
        "domain_ok",
        "success",
    ):
        assert key in public
    # Exact provenance on items
    for item in result.items:
        assert item.item_id
        assert item.kind in AssuranceItemKind
        for prov in item.provenance:
            assert prov.ref_id
            assert prov.kind
    # Body text must not leak into public projection
    blob = json.dumps(public)
    assert "Applicant respectfully" not in blob
    assert "DETAILED DESCRIPTION" not in blob


def test_result_lists_item_buckets_with_provenance(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    # Sparse docs → mandatory missing items with rule provenance
    sparse = (
        MatterDocumentInput(
            document_id="art:oa-only",
            role="office_action",
            text=OA_TEXT,
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    )
    result = proc.assure(
        _base_input(
            assurance_id="assurance:sparse-1",
            documents=sparse,
            run_preflight=False,
        )
    )
    assert result.missing_items or result.unknown_items
    for item in result.missing_items:
        assert item.kind is AssuranceItemKind.MISSING
        assert item.provenance
        assert item.obligation_rule_id or any(p.rule_id for p in item.provenance)
    # Domain must not report unconditional success when mandatory evidence missing
    assert result.success is False
    assert result.disposition is not AssuranceDisposition.COMPLETED


# ---------------------------------------------------------------------------
# Fail-closed dispositions
# ---------------------------------------------------------------------------


def test_unknown_classification_defaults_to_quarantine(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.assure(
        _base_input(
            assurance_id="assurance:quarantine-1",
            classification=None,  # omitted → UNKNOWN → quarantine
            documents=(
                MatterDocumentInput(
                    document_id="art:d1",
                    role="remarks",
                    text=REMARKS_TEXT,
                    # no classification on doc either
                ),
            ),
        )
    )
    assert result.is_quarantined is True
    assert result.disposition is AssuranceDisposition.QUARANTINED
    assert result.success is False
    assert result.ok is False
    assert result.domain_ok is False
    # Transport may still complete
    assert result.transport_ok is True
    assert result.classification is DisclosureClassification.UNKNOWN


def test_outage_is_not_domain_success(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.assure(
        _base_input(assurance_id="assurance:outage-1", force_outage=True)
    )
    assert result.disposition is AssuranceDisposition.OUTAGE
    assert result.is_outage is True
    assert result.success is False
    assert result.transport_ok is False
    assert "outage" in " ".join(result.reason_codes).lower() or result.is_outage


def test_proof_unknown_and_review_required_surface(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    proof = proc.assure(
        _base_input(
            assurance_id="assurance:proof-1",
            force_proof_unknown=True,
        )
    )
    assert proof.disposition is AssuranceDisposition.PROOF_UNKNOWN
    assert proof.success is False
    assert proof.is_proof_unknown is True

    review = proc.assure(
        _base_input(
            assurance_id="assurance:review-1",
            force_review_required=True,
        )
    )
    assert review.disposition is AssuranceDisposition.REVIEW_REQUIRED
    assert review.success is False
    assert review.is_review_required is True


def test_stale_authority_and_partial_surface(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    stale = proc.assure(
        _base_input(assurance_id="assurance:stale-1", authority_stale=True)
    )
    assert stale.disposition is AssuranceDisposition.STALE_AUTHORITY
    assert stale.success is False
    assert stale.is_stale_authority is True

    partial = proc.assure(
        _base_input(assurance_id="assurance:partial-1", force_partial=True)
    )
    assert partial.disposition is AssuranceDisposition.PARTIAL
    assert partial.success is False
    assert partial.is_partial is True


def test_coverage_status_reflects_dimensions(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.assure(_base_input(assurance_id="assurance:cov-1"))
    statuses = result.coverage.statuses
    assert statuses[CoverageDimension.SYNC.value] in {
        CoverageStatus.COVERED.value,
        CoverageStatus.PARTIAL.value,
        CoverageStatus.UNKNOWN.value,
    }
    assert statuses[CoverageDimension.EXTRACTION.value] == CoverageStatus.COVERED.value
    assert statuses[CoverageDimension.AUTHORITY.value] == CoverageStatus.COVERED.value
    assert CoverageDimension.PROOF.value in statuses
    assert CoverageDimension.COMPLIANCE.value in statuses


# ---------------------------------------------------------------------------
# Resume / reuse
# ---------------------------------------------------------------------------


def test_resume_reuses_stages_by_input_digest(tmp_path: Path) -> None:
    assurance_id = "assurance:resume-1"
    proc = _processor(tmp_path)
    first = proc.assure(_base_input(assurance_id=assurance_id))
    assert first.transport_ok is True
    first_counts = dict(proc.execution_counts)

    proc2 = SubmissionAssuranceProcessor(
        checkpoint_store=SubmissionAssuranceCheckpointStore(root=tmp_path / "ckpt"),
        matter_checkpoint_root=tmp_path / "matter-ckpt",
        id_factory=lambda: "assurance:should-not-use",
    )
    second = proc2.assure(_base_input(assurance_id=assurance_id))
    assert second.assurance_id == assurance_id
    assert set(second.reused_stages) == set(s.value for s in ASSURANCE_STAGE_ORDER)
    assert second.executed_stages == ()
    # No stage bodies re-executed on identical input
    assert sum(proc2.execution_counts.values()) == 0
    assert first_counts  # first run executed stages


def test_injected_failure_then_resume(tmp_path: Path) -> None:
    assurance_id = "assurance:inject-1"
    proc = _processor(tmp_path)
    interrupted = proc.assure(
        _base_input(
            assurance_id=assurance_id,
            inject_failure_before=AssuranceStage.FILING_OBLIGATIONS,
        )
    )
    assert interrupted.disposition is AssuranceDisposition.INTERRUPTED
    assert interrupted.success is False
    assert interrupted.transport_ok is False

    resumed = proc.assure(_base_input(assurance_id=assurance_id))
    assert resumed.transport_ok is True
    assert AssuranceStage.AUTHORIZE.value in resumed.reused_stages or (
        AssuranceStage.AUTHORIZE.value in resumed.committed_stages
    )
    assert AssuranceStage.FILING_OBLIGATIONS.value in resumed.executed_stages or (
        AssuranceStage.FILING_OBLIGATIONS.value in resumed.committed_stages
    )


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


def test_api_submission_assurance_without_middle_stages(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    api = USPTOAnalysisAPI(submission_assurance_processor=proc)
    result = api.submission_assurance(_base_input(assurance_id="assurance:api-1"))
    assert isinstance(result, SubmissionAssuranceResult)
    payload = result.to_dict()
    assert payload["schema_version"] == SUBMISSION_ASSURANCE_SCHEMA_VERSION
    assert payload["is_legal_advice"] is False
    assert "api_key" not in json.dumps(payload)

    # Alias
    result2 = api.assure(
        tenant_id="tenant-patlaw-140",
        matter_id="matter:api-kw",
        assurance_id="assurance:api-kw",
        documents=_full_docs(),
        classification=DisclosureClassification.PUBLIC_USER,
        authority_snapshot_id="auth:1",
        offline=True,
        run_preflight=False,
    )
    assert result2.matter_id == "matter:api-kw"
    assert "submission_assurance" in ASSURANCE_OPERATIONS
    assert "assure" in ASSURANCE_OPERATIONS


def test_api_perform_operation_dispatches_assurance(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    api = USPTOAnalysisAPI(submission_assurance_processor=proc)
    result = api.perform_operation(
        "submission_assurance",
        _base_input(assurance_id="assurance:perf-1"),
    )
    assert isinstance(result, SubmissionAssuranceResult)


# ---------------------------------------------------------------------------
# Adapter: domain disposition not concealed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_adapter_success_does_not_conceal_quarantine(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    api = USPTOAnalysisAPI(submission_assurance_processor=proc)
    adapter = USPTOProcessorAdapter(api=api)
    ctx = ProcessingContext(
        source="uspto:assurance",
        input_type=InputType.TEXT,
        metadata={"domain": "uspto"},
        options={
            "operation": "submission_assurance",
            "tenant_id": "tenant-patlaw-140",
            "matter_id": "matter:adapter-q",
            "assurance_id": "assurance:adapter-q",
            "classification": DisclosureClassification.UNKNOWN.value,
            "documents": [
                {
                    "document_id": "art:r1",
                    "role": "remarks",
                    "text": REMARKS_TEXT,
                }
            ],
            "offline": True,
            "run_preflight": False,
        },
    )
    result = await adapter.process(ctx)
    assert result.success is False
    assert result.raw_output is not None
    assert result.raw_output.get("is_quarantined") is True
    assert result.raw_output.get("transport_ok") is True
    assert "quarantined" in (result.errors or []) or any(
        "quarantine" in w for w in (result.warnings or [])
    )


@pytest.mark.anyio
async def test_adapter_success_does_not_conceal_outage(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    api = USPTOAnalysisAPI(submission_assurance_processor=proc)
    adapter = USPTOProcessorAdapter(api=api)
    ctx = ProcessingContext(
        source="uspto:assurance",
        input_type=InputType.TEXT,
        metadata={"domain": "uspto"},
        options={
            "operation": "assure",
            "tenant_id": "tenant-patlaw-140",
            "matter_id": "matter:adapter-outage",
            "assurance_id": "assurance:adapter-outage",
            "force_outage": True,
            "classification": DisclosureClassification.PUBLIC_USER.value,
            "documents": [
                {
                    "document_id": "art:oa1",
                    "role": "office_action",
                    "text": OA_TEXT,
                    "classification": DisclosureClassification.PUBLIC_USER.value,
                }
            ],
            "offline": True,
            "run_preflight": False,
        },
    )
    result = await adapter.process(ctx)
    assert result.success is False
    assert result.raw_output.get("is_outage") is True
    assert result.raw_output.get("transport_ok") is False


def test_never_legal_advice_or_file_pay_sign(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.assure(_base_input(assurance_id="assurance:legal-1"))
    assert result.is_legal_advice is False
    codes = set(result.reason_codes)
    assert "not_legal_advice" in codes
    assert "no_file_pay_sign" in codes
    assert "review_only" in codes
    # Forbidden methods on API
    api = USPTOAnalysisAPI()
    for method in ("sign", "pay", "file", "submit"):
        with pytest.raises(Exception):
            getattr(api, method)()
