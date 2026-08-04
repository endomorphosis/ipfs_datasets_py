"""Unified USPTO Python SDK surface (PATLAW-060).

Exposes typed status / sync-public / import-private / analyze / preflight /
explain operations that all return the same versioned domain contracts.

Design constraints
------------------
* Credentials are **references** (``CredentialRef`` / ``ApiKeySecret.reference_id``),
  never plain-text arguments or result fields.
* Private import requires explicit ``tenant_id``, import path, and classification.
* No method signs, pays, files, or automates a browser.
* Clients, stores, and privacy policy are injected — never read from ambient
  process environment for secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Final, Mapping, Sequence

from .analysis.analysis_bundle import (
    UsptoAnalysisBundle,
    build_analysis_bundle,
)
from .analysis.gap_report import (
    DEFAULT_OUTPUT_POLICY,
    GapReportInput,
    GapReportRenderer,
    OutputRedactionPolicy,
    RequirementEvidenceGapReport,
)
from .application_status_processor import (
    ApplicationStatusProcessor,
    InMemoryStatusSnapshotStore,
    StatusSnapshotStore,
    StatusSyncResult,
)
from .contracts import DisclosureClassification
from .document_sync_processor import (
    DocumentSyncProcessor,
    DocumentSyncResult,
)
from .dossier_processor import (
    ApplicationDossier,
    DossierInput,
    DossierProcessor,
)
from .privacy import DEFAULT_PRIVACY_POLICY, UsptoPrivacyPolicy
from .private_store import PrivateArtifactStore
from .providers.base import ApiKeySecret, HttpTransport
from .providers.patent_center_export import (
    AuthorizationError,
    ExportManifest,
    ImportAuthorization,
    ImportBatchResult,
    PatentCenterExportProvider,
)
from .providers.patent_file_wrapper import PatentFileWrapperClient
from .submission_assurance_processor import (
    SUBMISSION_ASSURANCE_INTERFACE,
    SUBMISSION_ASSURANCE_SCHEMA_VERSION,
    SubmissionAssuranceInput,
    SubmissionAssuranceProcessor,
    SubmissionAssuranceResult,
    create_submission_assurance_processor,
)
from .workflow_processor import (
    FORBIDDEN_WORKFLOW_ACTIONS,
    PreflightPackageInput,
    PreflightResult,
    WorkflowProcessor,
    is_forbidden_action,
)

USPTO_API_SCHEMA_VERSION: Final = "uspto.analysis-api.v1"
USPTO_API_INTERFACE: Final = "USPTOAnalysisAPI@1"

# Operations exposed on the stable public surface (PATLAW-060).
# submission_assurance is additive (PATLAW-140) and listed in
# ASSURANCE_OPERATIONS so the v1 PUBLIC_OPERATIONS contract remains stable.
PUBLIC_OPERATIONS: Final[tuple[str, ...]] = (
    "status",
    "sync_public",
    "import_private",
    "analyze",
    "preflight",
    "explain",
)

# Additive assurance workflow surface (PATLAW-140).
ASSURANCE_OPERATIONS: Final[tuple[str, ...]] = (
    "submission_assurance",
    "assure",
)

# Explicitly never offered (acceptance + plan §14).
FORBIDDEN_API_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        *FORBIDDEN_WORKFLOW_ACTIONS,
        "sign",
        "pay",
        "file",
        "submit",
        "browser",
        "automate_browser",
        "scrape",
        "login",
        "session",
        "mfa",
        "api_key",
        "password",
        "cookie",
    }
)

_CREDENTIAL_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "x-api-key",
        "bearer",
        "session",
        "mfa",
    }
)


class UsptoAPIError(ValueError):
    """Raised for fail-closed API contract violations."""

    def __init__(self, message: str, *, code: str = "uspto_api_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class ForbiddenAPIOperationError(UsptoAPIError):
    """Raised when a forbidden capability (sign/pay/file/browser) is requested."""

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"forbidden USPTO operation: {operation!r}",
            code="forbidden_operation",
        )
        self.operation = operation


@dataclass(frozen=True, slots=True)
class CredentialRef:
    """Opaque credential reference — never carries secret material.

    Resolvers may map ``reference_id`` to a vault entry. The reference itself
    is safe to log, serialize, and return from public surfaces.
    """

    reference_id: str
    kind: str = "api_key"

    def __post_init__(self) -> None:
        ref = str(self.reference_id or "").strip()
        if not ref or len(ref) > 128:
            raise UsptoAPIError(
                "credential reference_id must be a non-empty string ≤128 chars",
                code="invalid_credential_ref",
            )
        if any(ch in ref for ch in ("\x00", "\r", "\n")) or any(
            ch.isspace() for ch in ref
        ):
            raise UsptoAPIError(
                "credential reference_id contains invalid characters",
                code="invalid_credential_ref",
            )
        kind = str(self.kind or "api_key").strip().lower()
        if not kind or len(kind) > 64:
            raise UsptoAPIError(
                "credential kind must be a non-empty string ≤64 chars",
                code="invalid_credential_ref",
            )
        object.__setattr__(self, "reference_id", ref)
        object.__setattr__(self, "kind", kind)

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "reference_id": self.reference_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CredentialRef":
        if not isinstance(value, Mapping):
            raise TypeError("CredentialRef must be a mapping")
        return cls(
            reference_id=str(value.get("reference_id") or value.get("id") or ""),
            kind=str(value.get("kind") or "api_key"),
        )

    @classmethod
    def from_secret(cls, secret: ApiKeySecret) -> "CredentialRef":
        return cls(reference_id=secret.reference_id, kind="api_key")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value)
        except ValueError as exc:
            raise UsptoAPIError(
                f"unknown classification: {value!r}",
                code="invalid_classification",
            ) from exc
    raise UsptoAPIError(
        "classification is required and must be a DisclosureClassification",
        code="invalid_classification",
    )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        payload = value.to_dict()
        if isinstance(payload, Mapping):
            return payload
    raise TypeError(f"expected mapping or to_dict() object, got {type(value)!r}")


def _contract_payload(value: Any) -> dict[str, Any]:
    """Serialize a domain contract to a plain dict (no secrets)."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        out = dict(value)
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        out = dict(value.to_dict())
    else:
        raise TypeError(f"cannot serialize {type(value)!r} as contract")
    return scrub_credential_fields(out)


def scrub_credential_fields(payload: Any) -> Any:
    """Recursively strip secret-bearing keys; keep reference_id-only dicts."""
    if isinstance(payload, Mapping):
        # Pure credential reference: keep only kind + reference_id.
        keys = {str(k).lower() for k in payload.keys()}
        if "reference_id" in keys and keys <= {
            "kind",
            "reference_id",
            "id",
            "credential_ref",
        }:
            return {
                "kind": str(payload.get("kind") or "api_key"),
                "reference_id": str(
                    payload.get("reference_id") or payload.get("id") or ""
                ),
            }
        out: dict[str, Any] = {}
        for key, val in payload.items():
            key_l = str(key).lower()
            if key_l in _CREDENTIAL_RESULT_KEYS or key_l.endswith("_secret"):
                # Drop raw secret material; never echo.
                continue
            if key_l in {"api_key", "credential", "credentials"} and isinstance(
                val, Mapping
            ):
                # Nested secret holder → reference-only projection.
                if "reference_id" in val:
                    out[str(key)] = {
                        "kind": str(val.get("kind") or "api_key"),
                        "reference_id": str(val["reference_id"]),
                    }
                continue
            out[str(key)] = scrub_credential_fields(val)
        return out
    if isinstance(payload, (list, tuple)):
        return [scrub_credential_fields(item) for item in payload]
    return payload


def assert_operation_allowed(operation: str) -> None:
    """Fail closed if *operation* is a forbidden capability."""
    key = str(operation or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        raise UsptoAPIError("operation is required", code="missing_operation")
    if key in FORBIDDEN_API_OPERATIONS or is_forbidden_action(key):
        raise ForbiddenAPIOperationError(key)
    if key.startswith(
        (
            "sign_",
            "pay_",
            "file_",
            "submit_",
            "scrape_",
            "browser_",
            "automate_",
            "login_",
        )
    ):
        raise ForbiddenAPIOperationError(key)


@dataclass
class PublicSyncResult:
    """Combined public status + document sync outcome (canonical contracts)."""

    schema_version: str
    status: StatusSyncResult
    documents: DocumentSyncResult | None = None
    credential_ref: CredentialRef | None = None
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "documents": None if self.documents is None else self.documents.to_dict(),
            "labels": dict(self.labels),
            "schema_version": self.schema_version,
            "status": self.status.to_dict(),
        }
        if self.credential_ref is not None:
            payload["credential_ref"] = self.credential_ref.to_dict()
        return scrub_credential_fields(payload)


@dataclass
class AnalyzeResult:
    """Dossier + analysis-bundle pair for the analyze surface."""

    schema_version: str
    dossier: ApplicationDossier | None
    analysis_bundle: UsptoAnalysisBundle
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return scrub_credential_fields(
            {
                "analysis_bundle": self.analysis_bundle.to_dict(),
                "dossier": None if self.dossier is None else self.dossier.to_dict(),
                "labels": dict(self.labels),
                "schema_version": self.schema_version,
            }
        )


class USPTOAnalysisAPI:
    """Single injected Python API for USPTO status/sync/import/analyze flows.

    Construction accepts optional client, store, privacy policy, and processor
    instances. Missing collaborators are created lazily when an operation needs
    them; secret material is never accepted as a bare string argument on the
    public methods — use :class:`CredentialRef` or a pre-built
    :class:`ApiKeySecret` / client.
    """

    schema_version: str = USPTO_API_SCHEMA_VERSION
    interface: str = USPTO_API_INTERFACE

    def __init__(
        self,
        *,
        client: PatentFileWrapperClient | None = None,
        status_processor: ApplicationStatusProcessor | None = None,
        document_sync_processor: DocumentSyncProcessor | None = None,
        status_store: StatusSnapshotStore | None = None,
        private_store: PrivateArtifactStore | None = None,
        private_import_provider: PatentCenterExportProvider | None = None,
        dossier_processor: DossierProcessor | None = None,
        workflow_processor: WorkflowProcessor | None = None,
        gap_report_renderer: GapReportRenderer | None = None,
        submission_assurance_processor: SubmissionAssuranceProcessor | None = None,
        privacy_policy: UsptoPrivacyPolicy | None = None,
        credential_ref: CredentialRef | ApiKeySecret | str | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._client = client
        self._status_store = status_store
        self._status_processor = status_processor
        self._document_sync_processor = document_sync_processor
        self._private_store = private_store
        self._private_import_provider = private_import_provider
        self._dossier_processor = dossier_processor or DossierProcessor(
            id_factory=id_factory
        )
        self._workflow_processor = workflow_processor or WorkflowProcessor(
            id_factory=id_factory
        )
        self._gap_report_renderer = gap_report_renderer or GapReportRenderer(
            id_factory=id_factory
        )
        self._submission_assurance_processor = submission_assurance_processor
        self._privacy_policy = privacy_policy or DEFAULT_PRIVACY_POLICY
        self._credential_ref = self._coerce_credential_ref(credential_ref)
        self._id_factory = id_factory

    # ------------------------------------------------------------------
    # Credential / config surface
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_credential_ref(
        value: CredentialRef | ApiKeySecret | str | None,
    ) -> CredentialRef | None:
        if value is None:
            return None
        if isinstance(value, CredentialRef):
            return value
        if isinstance(value, ApiKeySecret):
            return CredentialRef.from_secret(value)
        if isinstance(value, str):
            # String is treated as a *reference id*, never as a secret value.
            return CredentialRef(reference_id=value)
        raise UsptoAPIError(
            "credential_ref must be CredentialRef, ApiKeySecret, or reference id string",
            code="invalid_credential_ref",
        )

    @property
    def credential_ref(self) -> CredentialRef | None:
        return self._credential_ref

    def safe_config(self) -> dict[str, Any]:
        """Serializable configuration with credential *references* only."""
        cfg: dict[str, Any] = {
            "interface": self.interface,
            "operations": list(PUBLIC_OPERATIONS),
            "schema_version": self.schema_version,
            "forbidden_operations": sorted(FORBIDDEN_API_OPERATIONS),
        }
        if self._credential_ref is not None:
            cfg["credential_ref"] = self._credential_ref.to_dict()
        if self._client is not None and hasattr(self._client, "safe_config"):
            client_cfg = scrub_credential_fields(self._client.safe_config())
            cfg["client"] = client_cfg
        if self._private_store is not None:
            cfg["private_store"] = {
                "tenant_id": self._private_store.tenant_id,
                "key_id": self._private_store.key_id,
            }
        return scrub_credential_fields(cfg)

    def bind_client(self, client: PatentFileWrapperClient) -> "USPTOAnalysisAPI":
        """Return a shallow copy with a different public ODP client."""
        return USPTOAnalysisAPI(
            client=client,
            status_processor=self._status_processor,
            document_sync_processor=self._document_sync_processor,
            status_store=self._status_store,
            private_store=self._private_store,
            private_import_provider=self._private_import_provider,
            dossier_processor=self._dossier_processor,
            workflow_processor=self._workflow_processor,
            gap_report_renderer=self._gap_report_renderer,
            submission_assurance_processor=self._submission_assurance_processor,
            privacy_policy=self._privacy_policy,
            credential_ref=self._credential_ref,
            id_factory=self._id_factory,
        )

    def bind_private_store(
        self, store: PrivateArtifactStore
    ) -> "USPTOAnalysisAPI":
        return USPTOAnalysisAPI(
            client=self._client,
            status_processor=self._status_processor,
            document_sync_processor=self._document_sync_processor,
            status_store=self._status_store,
            private_store=store,
            private_import_provider=None,  # rebuild against new store
            dossier_processor=self._dossier_processor,
            workflow_processor=self._workflow_processor,
            gap_report_renderer=self._gap_report_renderer,
            submission_assurance_processor=self._submission_assurance_processor,
            privacy_policy=self._privacy_policy,
            credential_ref=self._credential_ref,
            id_factory=self._id_factory,
        )

    # ------------------------------------------------------------------
    # Collaborator resolution
    # ------------------------------------------------------------------

    def _require_client(self) -> PatentFileWrapperClient:
        if self._client is None:
            raise UsptoAPIError(
                "PatentFileWrapperClient is required for public status/sync; "
                "inject via USPTOAnalysisAPI(client=...) or bind_client()",
                code="missing_client",
            )
        return self._client

    def _status_proc(self) -> ApplicationStatusProcessor:
        if self._status_processor is None:
            self._status_processor = ApplicationStatusProcessor(
                client=self._require_client(),
                store=self._status_store or InMemoryStatusSnapshotStore(),
            )
        return self._status_processor

    def _doc_sync_proc(self) -> DocumentSyncProcessor:
        if self._document_sync_processor is None:
            self._document_sync_processor = DocumentSyncProcessor(
                client=self._require_client()
            )
        return self._document_sync_processor

    def _import_provider(self) -> PatentCenterExportProvider:
        if self._private_import_provider is not None:
            return self._private_import_provider
        if self._private_store is None:
            raise UsptoAPIError(
                "private import requires an injected PrivateArtifactStore "
                "(tenant-bound encrypted store)",
                code="missing_private_store",
            )
        self._private_import_provider = PatentCenterExportProvider(
            self._private_store,
            privacy_policy=self._privacy_policy,
        )
        return self._private_import_provider

    def _assurance_proc(self) -> SubmissionAssuranceProcessor:
        if self._submission_assurance_processor is None:
            self._submission_assurance_processor = (
                create_submission_assurance_processor(id_factory=self._id_factory)
            )
        return self._submission_assurance_processor

    # ------------------------------------------------------------------
    # Forbidden surface (explicit for tests / audit)
    # ------------------------------------------------------------------

    def sign(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenAPIOperationError("sign")

    def pay(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenAPIOperationError("pay")

    def file(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenAPIOperationError("file")

    def submit(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenAPIOperationError("submit")

    def automate_browser(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenAPIOperationError("automate_browser")

    def scrape(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenAPIOperationError("scrape")

    def login(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenAPIOperationError("login")

    def perform_operation(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        """Dispatch a named public operation or raise ForbiddenAPIOperationError."""
        assert_operation_allowed(operation)
        key = str(operation).strip().lower().replace("-", "_")
        dispatch = {
            "status": self.status,
            "sync_public": self.sync_public,
            "import_private": self.import_private,
            "analyze": self.analyze,
            "preflight": self.preflight,
            "explain": self.explain,
            "submission_assurance": self.submission_assurance,
            "assure": self.submission_assurance,
        }
        if key not in dispatch:
            raise UsptoAPIError(
                f"unknown operation: {operation!r}",
                code="unknown_operation",
            )
        return dispatch[key](*args, **kwargs)

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    def status(
        self,
        application_number: str,
        *,
        matter_id: str | None = None,
        force_refresh: bool = False,
        credential_ref: CredentialRef | str | None = None,
    ) -> StatusSyncResult:
        """Fetch/normalize public application status (canonical StatusSyncResult).

        ``credential_ref`` is accepted only as a reference id for audit labels;
        secrets never enter this method.
        """
        assert_operation_allowed("status")
        _ = self._coerce_credential_ref(credential_ref)  # validate if provided
        proc = self._status_proc()
        return proc.sync(
            application_number,
            matter_id=matter_id,
            force_refresh=force_refresh,
        )

    def sync_public(
        self,
        application_number: str,
        *,
        matter_id: str | None = None,
        force_refresh: bool = False,
        sync_documents: bool = True,
        document_codes: str | Sequence[str] | None = None,
        force_download: bool = False,
        credential_ref: CredentialRef | str | None = None,
    ) -> PublicSyncResult:
        """Synchronize public status (and optionally document inventory/bytes)."""
        assert_operation_allowed("sync_public")
        ref = self._coerce_credential_ref(credential_ref) or self._credential_ref
        status_result = self.status(
            application_number,
            matter_id=matter_id,
            force_refresh=force_refresh,
            credential_ref=ref,
        )
        doc_result: DocumentSyncResult | None = None
        if sync_documents:
            doc_result = self._doc_sync_proc().sync_application(
                application_number,
                document_codes=document_codes,
                force_download=force_download,
            )
        return PublicSyncResult(
            schema_version=self.schema_version,
            status=status_result,
            documents=doc_result,
            credential_ref=ref,
            labels={"operation": "sync_public"},
        )

    def import_private(
        self,
        *,
        tenant_id: str,
        import_path: str | Path,
        classification: DisclosureClassification | str,
        authorization: ImportAuthorization | Mapping[str, Any],
        manifest: ExportManifest | Mapping[str, Any] | str | Path,
        fail_fast: bool = False,
    ) -> ImportBatchResult:
        """Import an authorized local Patent Center export into private storage.

        Requires explicit ``tenant_id``, filesystem ``import_path``, and a
        disclosure ``classification``. Credentials/sessions are never accepted.
        """
        assert_operation_allowed("import_private")
        tenant = str(tenant_id or "").strip()
        if not tenant:
            raise UsptoAPIError(
                "import_private requires tenant_id",
                code="missing_tenant",
            )
        path = Path(import_path).expanduser()
        if not str(import_path).strip():
            raise UsptoAPIError(
                "import_private requires import_path",
                code="missing_import_path",
            )
        classification_enum = _coerce_classification(classification)
        if classification_enum is DisclosureClassification.UNKNOWN:
            raise UsptoAPIError(
                "import_private refuses unknown classification (quarantine only)",
                code="classification_unknown",
            )

        auth = (
            authorization
            if isinstance(authorization, ImportAuthorization)
            else ImportAuthorization.from_dict(authorization)
        )
        if auth.tenant_id != tenant:
            raise AuthorizationError(
                "authorization.tenant_id does not match tenant_id argument",
                code="tenant_mismatch",
            )

        provider = self._import_provider()
        if provider.tenant_id != tenant:
            raise AuthorizationError(
                "private store tenant_id does not match tenant_id argument",
                code="tenant_mismatch",
            )

        # Classification is enforced at the API boundary and recorded on labels;
        # the provider already applies per-entry classifications from the manifest.
        result = provider.import_export(
            import_root=path,
            manifest=manifest,
            authorization=auth,
            fail_fast=fail_fast,
        )
        # Attach classification audit via source receipt metadata is already
        # sanitized; ensure result serializes without secrets.
        _ = classification_enum  # boundary check complete
        return result

    def analyze(
        self,
        dossier_input: DossierInput | Mapping[str, Any] | None = None,
        *,
        matter_id: str | None = None,
        analysis_bundle: UsptoAnalysisBundle | Mapping[str, Any] | None = None,
        seed_classification: DisclosureClassification | str = (
            DisclosureClassification.PUBLIC_USER
        ),
        labels: Mapping[str, str] | None = None,
    ) -> AnalyzeResult:
        """Assemble a dossier and/or bind an analysis bundle (canonical contracts)."""
        assert_operation_allowed("analyze")
        dossier: ApplicationDossier | None = None
        bundle: UsptoAnalysisBundle | None = None

        if analysis_bundle is not None:
            if isinstance(analysis_bundle, UsptoAnalysisBundle):
                bundle = analysis_bundle
            elif isinstance(analysis_bundle, Mapping):
                bundle = UsptoAnalysisBundle.from_dict(analysis_bundle)
            else:
                raise UsptoAPIError(
                    "analysis_bundle must be UsptoAnalysisBundle or mapping",
                    code="invalid_analysis_bundle",
                )

        if dossier_input is not None:
            if isinstance(dossier_input, DossierInput):
                d_input = dossier_input
            elif isinstance(dossier_input, Mapping):
                raise UsptoAPIError(
                    "dossier_input mapping construction is not supported; "
                    "pass a DossierInput instance",
                    code="invalid_dossier_input",
                )
            else:
                raise UsptoAPIError(
                    "dossier_input must be DossierInput",
                    code="invalid_dossier_input",
                )
            dossier = self._dossier_processor.assemble(d_input)
            if bundle is None:
                # Dossier already embeds a UsptoAnalysisBundle.
                embedded = getattr(dossier, "analysis_bundle", None)
                if isinstance(embedded, UsptoAnalysisBundle):
                    bundle = embedded
                else:
                    bundle = build_analysis_bundle(
                        matter_id=dossier.matter_id,
                        analysis_id=getattr(dossier, "analysis_id", None),
                        seed_classification=dossier.classification,
                        input_artifact_ids=tuple(
                            getattr(dossier, "input_artifact_ids", ()) or ()
                        ),
                        labels=labels or {},
                        id_factory=self._id_factory,
                    )

        if bundle is None:
            mid = matter_id or (
                dossier.matter_id if dossier is not None else None
            )
            if not mid:
                raise UsptoAPIError(
                    "analyze requires dossier_input, analysis_bundle, or matter_id",
                    code="missing_analyze_input",
                )
            bundle = build_analysis_bundle(
                matter_id=mid,
                seed_classification=seed_classification,
                labels=labels or {},
                id_factory=self._id_factory,
            )

        return AnalyzeResult(
            schema_version=self.schema_version,
            dossier=dossier,
            analysis_bundle=bundle,
            labels=dict(labels or {"operation": "analyze"}),
        )

    def preflight(
        self,
        package_input: PreflightPackageInput | Mapping[str, Any],
    ) -> PreflightResult:
        """Run package preflight (never signs/pays/files)."""
        assert_operation_allowed("preflight")
        if isinstance(package_input, PreflightPackageInput):
            pkg = package_input
        elif isinstance(package_input, Mapping):
            if hasattr(PreflightPackageInput, "from_dict"):
                pkg = PreflightPackageInput.from_dict(package_input)  # type: ignore[attr-defined]
            else:
                pkg = PreflightPackageInput(**dict(package_input))  # type: ignore[arg-type]
        else:
            raise UsptoAPIError(
                "package_input must be PreflightPackageInput or mapping",
                code="invalid_preflight_input",
            )
        return self._workflow_processor.run_preflight(pkg)

    def explain(
        self,
        analysis_bundle: UsptoAnalysisBundle | Mapping[str, Any] | None = None,
        *,
        gap_report: RequirementEvidenceGapReport | Mapping[str, Any] | None = None,
        assessments: Sequence[Any] = (),
        candidate_dates: Sequence[Any] = (),
        reviewer_actions: Sequence[Any] = (),
        requirements: Sequence[Any] = (),
        output_policy: OutputRedactionPolicy | Mapping[str, Any] | None = None,
        matter_id: str | None = None,
        analysis_id: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> RequirementEvidenceGapReport:
        """Produce an explainable requirement/evidence gap report.

        Pass an existing gap report to re-validate/re-serialize it, or an
        analysis bundle to render a fresh report.
        """
        assert_operation_allowed("explain")
        if gap_report is not None:
            if isinstance(gap_report, RequirementEvidenceGapReport):
                return gap_report
            if isinstance(gap_report, Mapping):
                return RequirementEvidenceGapReport.from_dict(gap_report)
            raise UsptoAPIError(
                "gap_report must be RequirementEvidenceGapReport or mapping",
                code="invalid_gap_report",
            )
        if analysis_bundle is None:
            raise UsptoAPIError(
                "explain requires analysis_bundle or gap_report",
                code="missing_explain_input",
            )
        if isinstance(analysis_bundle, UsptoAnalysisBundle):
            bundle = analysis_bundle
        elif isinstance(analysis_bundle, Mapping):
            bundle = UsptoAnalysisBundle.from_dict(analysis_bundle)
        else:
            raise UsptoAPIError(
                "analysis_bundle must be UsptoAnalysisBundle or mapping",
                code="invalid_analysis_bundle",
            )
        policy: OutputRedactionPolicy
        if output_policy is None:
            policy = DEFAULT_OUTPUT_POLICY
        elif isinstance(output_policy, OutputRedactionPolicy):
            policy = output_policy
        elif isinstance(output_policy, Mapping):
            policy = OutputRedactionPolicy.from_dict(output_policy)
        else:
            raise UsptoAPIError(
                "output_policy must be OutputRedactionPolicy or mapping",
                code="invalid_output_policy",
            )
        report_input = GapReportInput(
            analysis_bundle=bundle,
            assessments=assessments,
            candidate_dates=candidate_dates,
            reviewer_actions=reviewer_actions,
            requirements=requirements,
            output_policy=policy,
            labels=labels or {},
            matter_id=matter_id,
            analysis_id=analysis_id,
        )
        return self._gap_report_renderer.render(report_input)

    def submission_assurance(
        self,
        assurance_input: SubmissionAssuranceInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SubmissionAssuranceResult:
        """Run the serialized submission-assurance workflow (PATLAW-140).

        Accepts tenant/matter plus authorized documents (or a mapping recipe).
        No hand-built middle-stage dossier/compliance objects are required.
        Domain ``success``/``ok`` is False for outage, quarantine, incomplete
        analysis, proof-unknown, and mandatory review even when transport
        completed. Never files, pays, signs, or claims legal advice.
        """
        assert_operation_allowed("submission_assurance")
        proc = self._assurance_proc()
        if assurance_input is None and not kwargs:
            raise UsptoAPIError(
                "submission_assurance requires SubmissionAssuranceInput, "
                "mapping, or keyword arguments (tenant_id, matter_id, ...)",
                code="missing_assurance_input",
            )
        if assurance_input is None:
            return proc.assure(**kwargs)
        if kwargs:
            return proc.assure(assurance_input, **kwargs)
        return proc.assure(assurance_input)

    # Alias preferred by some adapters / CLI surfaces.
    assure = submission_assurance

    # ------------------------------------------------------------------
    # Convenience serialization
    # ------------------------------------------------------------------

    def to_contract_dict(self, result: Any) -> dict[str, Any]:
        """Convert any API result to a scrubbed canonical dict."""
        return _contract_payload(result)


def create_api(
    *,
    client: PatentFileWrapperClient | None = None,
    transport: HttpTransport | None = None,
    api_key: ApiKeySecret | None = None,
    credential_ref: CredentialRef | str | None = None,
    private_store: PrivateArtifactStore | None = None,
    privacy_policy: UsptoPrivacyPolicy | None = None,
    **kwargs: Any,
) -> USPTOAnalysisAPI:
    """Factory for :class:`USPTOAnalysisAPI` with optional ODP client wiring.

    ``api_key`` must be an :class:`ApiKeySecret` (never a bare string secret).
    Use ``credential_ref`` for reference-only labeling when the secret is held
    inside a pre-built client.
    """
    if api_key is not None and not isinstance(api_key, ApiKeySecret):
        raise UsptoAPIError(
            "api_key must be ApiKeySecret (use CredentialRef for references)",
            code="invalid_api_key",
        )
    built_client = client
    if built_client is None and transport is not None:
        built_client = PatentFileWrapperClient(transport, api_key=api_key)
    ref = credential_ref
    if ref is None and api_key is not None:
        ref = CredentialRef.from_secret(api_key)
    return USPTOAnalysisAPI(
        client=built_client,
        private_store=private_store,
        privacy_policy=privacy_policy,
        credential_ref=ref,
        **kwargs,
    )


__all__ = [
    "ASSURANCE_OPERATIONS",
    "FORBIDDEN_API_OPERATIONS",
    "PUBLIC_OPERATIONS",
    "SUBMISSION_ASSURANCE_INTERFACE",
    "SUBMISSION_ASSURANCE_SCHEMA_VERSION",
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
]
