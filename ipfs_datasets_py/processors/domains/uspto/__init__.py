"""USPTO domain package — public contracts, providers, analysis, and SDK API.

Stable public imports for PATLAW-060. Domain processors are registered once
via :func:`register_uspto_processors`. Credentials are always references;
private import requires tenant, path, and classification. No exported surface
signs, pays, files, or automates a browser.
"""

from __future__ import annotations

from .api import (
    ASSURANCE_OPERATIONS,
    FORBIDDEN_API_OPERATIONS,
    PUBLIC_OPERATIONS,
    USPTO_API_INTERFACE,
    USPTO_API_SCHEMA_VERSION,
    AnalyzeResult,
    CredentialRef,
    ForbiddenAPIOperationError,
    PublicSyncResult,
    SubmissionAssuranceInput,
    SubmissionAssuranceResult,
    USPTOAnalysisAPI,
    UsptoAPIError,
    assert_operation_allowed,
    create_api,
    scrub_credential_fields,
)
from .submission_assurance_processor import (
    ASSURANCE_STAGE_ORDER,
    SUBMISSION_ASSURANCE_INTERFACE,
    SUBMISSION_ASSURANCE_SCHEMA_VERSION,
    AssuranceDisposition,
    AssuranceItem,
    AssuranceItemKind,
    CoverageDimension,
    CoverageReport,
    CoverageStatus,
    ProvenanceRef,
    REVIEW_ONLY_ASSURANCE_DISCLAIMER,
    SubmissionAssuranceProcessor,
    assure_submission,
    create_submission_assurance_processor,
)
from .application_status_processor import (
    ApplicationStatusProcessor,
    StatusSyncResult,
)
from .contracts import (
    CONTRACTS_INTERFACE,
    CONTRACTS_SCHEMA_VERSION,
    AnalysisBundle,
    ApplicationIdentity,
    AssessmentStatus,
    AuthorityRelation,
    CandidateDeadline,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    GovernmentRequirement,
    MatterEvent,
    MatterEventKind,
    RequirementAssessment,
    ReviewState,
    SourceReceipt,
    SubmissionFact,
    canonical_json,
    is_private_classification,
    is_public_classification,
    most_restrictive_classification,
    requires_quarantine,
)
from .document_sync_processor import DocumentSyncProcessor, DocumentSyncResult
from .dossier_processor import (
    ApplicationDossier,
    DossierInput,
    DossierProcessor,
)
from .privacy import (
    DEFAULT_PRIVACY_POLICY,
    PRIVACY_INTERFACE,
    PRIVACY_POLICY_SCHEMA_VERSION,
    ContentKind,
    PublicSink,
    UsptoPrivacyPolicy,
    VaultKind,
)
from .private_store import PrivateArtifactStore, TenantKeyMaterial
from .providers.base import ApiKeySecret
from .providers.patent_center_export import (
    ExportManifest,
    ImportAuthorization,
    ImportBatchResult,
    PatentCenterExportProvider,
)
from .providers.patent_file_wrapper import PatentFileWrapperClient
from .workflow_processor import (
    FORBIDDEN_WORKFLOW_ACTIONS,
    ForbiddenWorkflowActionError,
    PreflightPackageInput,
    PreflightResult,
    WorkflowProcessor,
)

# Adapter registration (lazy-safe re-export)
try:
    from ipfs_datasets_py.processors.adapters.uspto_adapter import (
        USPTOProcessorAdapter,
        register_uspto_processors,
    )
except ImportError:  # pragma: no cover - optional adapter path
    USPTOProcessorAdapter = None  # type: ignore[misc, assignment]

    def register_uspto_processors(*_a, **_k):  # type: ignore[misc]
        raise ImportError("USPTOProcessorAdapter is unavailable")


__all__ = [
    # API
    "ASSURANCE_OPERATIONS",
    "FORBIDDEN_API_OPERATIONS",
    "PUBLIC_OPERATIONS",
    "USPTO_API_INTERFACE",
    "USPTO_API_SCHEMA_VERSION",
    "AnalyzeResult",
    "CredentialRef",
    "ForbiddenAPIOperationError",
    "PublicSyncResult",
    "SubmissionAssuranceInput",
    "SubmissionAssuranceResult",
    "USPTOAnalysisAPI",
    "UsptoAPIError",
    "assert_operation_allowed",
    "create_api",
    "scrub_credential_fields",
    # Submission assurance (PATLAW-140)
    "ASSURANCE_STAGE_ORDER",
    "SUBMISSION_ASSURANCE_INTERFACE",
    "SUBMISSION_ASSURANCE_SCHEMA_VERSION",
    "AssuranceDisposition",
    "AssuranceItem",
    "AssuranceItemKind",
    "CoverageDimension",
    "CoverageReport",
    "CoverageStatus",
    "ProvenanceRef",
    "REVIEW_ONLY_ASSURANCE_DISCLAIMER",
    "SubmissionAssuranceProcessor",
    "assure_submission",
    "create_submission_assurance_processor",
    # Registry
    "USPTOProcessorAdapter",
    "register_uspto_processors",
    # Core contracts
    "CONTRACTS_INTERFACE",
    "CONTRACTS_SCHEMA_VERSION",
    "AnalysisBundle",
    "ApplicationIdentity",
    "AssessmentStatus",
    "AuthorityRelation",
    "CandidateDeadline",
    "DisclosureClassification",
    "ExtractedSpan",
    "ExtractionOrigin",
    "GovernmentRequirement",
    "MatterEvent",
    "MatterEventKind",
    "RequirementAssessment",
    "ReviewState",
    "SourceReceipt",
    "SubmissionFact",
    "canonical_json",
    "is_private_classification",
    "is_public_classification",
    "most_restrictive_classification",
    "requires_quarantine",
    # Privacy / store
    "DEFAULT_PRIVACY_POLICY",
    "PRIVACY_INTERFACE",
    "PRIVACY_POLICY_SCHEMA_VERSION",
    "ContentKind",
    "PublicSink",
    "UsptoPrivacyPolicy",
    "VaultKind",
    "PrivateArtifactStore",
    "TenantKeyMaterial",
    # Processors / providers
    "ApiKeySecret",
    "ApplicationStatusProcessor",
    "StatusSyncResult",
    "DocumentSyncProcessor",
    "DocumentSyncResult",
    "DossierInput",
    "DossierProcessor",
    "ApplicationDossier",
    "PatentFileWrapperClient",
    "PatentCenterExportProvider",
    "ExportManifest",
    "ImportAuthorization",
    "ImportBatchResult",
    "WorkflowProcessor",
    "PreflightPackageInput",
    "PreflightResult",
    "FORBIDDEN_WORKFLOW_ACTIONS",
    "ForbiddenWorkflowActionError",
]
