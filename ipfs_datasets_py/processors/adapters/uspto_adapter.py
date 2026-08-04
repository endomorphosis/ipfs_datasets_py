"""USPTOProcessorAdapter — register USPTO analysis with the canonical registry.

Implements the core async :class:`ProcessorProtocol` (``can_handle`` /
``process`` / ``get_capabilities``) and delegates domain work to
:class:`~ipfs_datasets_py.processors.domains.uspto.api.USPTOAnalysisAPI`.

Credentials remain references only. Forbidden operations (sign/pay/file/
browser automation) are rejected at the adapter boundary.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Union

from ipfs_datasets_py.processors.core.protocol import (
    InputType,
    ProcessingContext,
    ProcessingResult,
    is_processor,
)
from ipfs_datasets_py.processors.domains.uspto.api import (
    FORBIDDEN_API_OPERATIONS,
    PUBLIC_OPERATIONS,
    USPTOAnalysisAPI,
    UsptoAPIError,
    assert_operation_allowed,
    scrub_credential_fields,
)

logger = logging.getLogger(__name__)

ADAPTER_NAME: Final = "USPTOProcessor"
ADAPTER_VERSION: Final = "1.0.0"
ADAPTER_PRIORITY: Final = 18

_USPTO_FORMATS: Final[frozenset[str]] = frozenset(
    {
        "uspto",
        "uspto_status",
        "uspto_sync",
        "uspto_import",
        "uspto_analyze",
        "uspto_preflight",
        "uspto_explain",
        "uspto_assurance",
        "uspto_submission_assurance",
        "patent_center_export",
        "odp",
    }
)

_OPERATION_ALIASES: Final[Mapping[str, str]] = {
    "status": "status",
    "sync": "sync_public",
    "sync_public": "sync_public",
    "sync-public": "sync_public",
    "import": "import_private",
    "import_private": "import_private",
    "import-private": "import_private",
    "analyze": "analyze",
    "preflight": "preflight",
    "explain": "explain",
    "assure": "submission_assurance",
    "assurance": "submission_assurance",
    "submission_assurance": "submission_assurance",
    "submission-assurance": "submission_assurance",
}


class USPTOProcessorAdapter:
    """Canonical-registry adapter for USPTO domain operations.

    Example:
        >>> from ipfs_datasets_py.processors.adapters.uspto_adapter import (
        ...     USPTOProcessorAdapter,
        ...     register_uspto_processors,
        ... )
        >>> register_uspto_processors()
        >>> adapter = USPTOProcessorAdapter(api=my_api)
    """

    def __init__(
        self,
        api: USPTOAnalysisAPI | None = None,
        *,
        priority: int = ADAPTER_PRIORITY,
        name: str = ADAPTER_NAME,
    ) -> None:
        self._api = api or USPTOAnalysisAPI()
        self._priority = int(priority)
        self._name = str(name)

    @property
    def api(self) -> USPTOAnalysisAPI:
        return self._api

    def get_name(self) -> str:
        return self._name

    def get_priority(self) -> int:
        return self._priority

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "version": ADAPTER_VERSION,
            "handles": sorted(_USPTO_FORMATS),
            "formats": sorted(_USPTO_FORMATS),
            "input_types": ["text", "file", "folder"],
            "outputs": [
                "status_sync_result",
                "document_sync_result",
                "import_batch_result",
                "analysis_bundle",
                "preflight_result",
                "gap_report",
                "submission_assurance_result",
            ],
            "operations": list(PUBLIC_OPERATIONS) + ["submission_assurance"],
            "forbidden_operations": sorted(FORBIDDEN_API_OPERATIONS),
            "priority": self._priority,
            "description": (
                "USPTO status, public sync, authorized private import, "
                "analyze, preflight, explain, and submission-assurance — "
                "credentials by reference only"
            ),
            "features": [
                "credential_references",
                "canonical_contracts",
                "no_sign_pay_file_browser",
                "tenant_bound_private_import",
                "submission_assurance",
                "domain_disposition_not_concealed",
            ],
            "interface": self._api.interface,
            "schema_version": self._api.schema_version,
        }

    async def can_handle(self, context: ProcessingContext) -> bool:
        """True when context targets a USPTO operation or format."""
        if context is None:
            return False
        meta = context.metadata or {}
        options = context.options or {}
        fmt = None
        if hasattr(context, "get_format"):
            fmt = context.get_format()
        fmt = (fmt or meta.get("format") or meta.get("extension") or "").lower()
        if fmt in _USPTO_FORMATS:
            return True
        domain = str(meta.get("domain") or options.get("domain") or "").lower()
        if domain in {"uspto", "patent_uspto", "odp"}:
            return True
        operation = self._resolve_operation(meta, options)
        if operation is not None:
            return True
        source = context.source
        if isinstance(source, str):
            lowered = source.lower()
            if lowered.startswith("uspto:") or lowered.startswith("odp:"):
                return True
            # Bare application-number-like tokens with explicit uspto hint
            if meta.get("uspto") or options.get("uspto"):
                return True
        return False

    async def process(self, context: ProcessingContext) -> ProcessingResult:
        """Dispatch the USPTO operation named in context options/metadata."""
        start = time.time()
        meta = dict(context.metadata or {})
        options = dict(context.options or {})
        operation = self._resolve_operation(meta, options)
        if operation is None:
            return ProcessingResult(
                success=False,
                metadata={
                    "processor_name": self._name,
                    "processor_version": ADAPTER_VERSION,
                    "processing_time_seconds": time.time() - start,
                },
                errors=[
                    "USPTO operation required in context.options['operation'] "
                    f"(one of {list(PUBLIC_OPERATIONS)})"
                ],
            )
        try:
            assert_operation_allowed(operation)
        except Exception as exc:
            return ProcessingResult(
                success=False,
                metadata={
                    "processor_name": self._name,
                    "processor_version": ADAPTER_VERSION,
                    "processing_time_seconds": time.time() - start,
                    "operation": operation,
                },
                errors=[str(exc)],
            )

        try:
            result_obj = self._dispatch(operation, context, meta, options)
            payload = scrub_credential_fields(
                result_obj.to_dict()
                if hasattr(result_obj, "to_dict")
                else dict(result_obj)
            )
            # Domain disposition must not be concealed by transport success
            # (PATLAW-140): outage / quarantine / incomplete / review → success=False.
            domain_ok = self._domain_success(operation, payload, result_obj)
            warnings: list[str] = []
            errors: list[str] = []
            if not domain_ok:
                disposition = payload.get("disposition") or payload.get(
                    "domain_disposition"
                )
                warnings.append(
                    "domain_disposition_not_success:"
                    f"{disposition or 'unknown'}"
                )
                if payload.get("is_quarantined"):
                    errors.append("quarantined")
                if payload.get("is_outage"):
                    errors.append("outage")
                if payload.get("is_review_required"):
                    errors.append("review_required")
                if payload.get("is_partial"):
                    errors.append("partial")
                if payload.get("is_proof_unknown"):
                    errors.append("proof_unknown")
                if payload.get("is_stale_authority"):
                    errors.append("stale_authority")
            return ProcessingResult(
                success=domain_ok,
                knowledge_graph={
                    "entities": [],
                    "relationships": [],
                    "properties": {
                        "uspto_operation": operation,
                        "schema_version": payload.get("schema_version"),
                        "domain_ok": domain_ok,
                        "transport_ok": payload.get("transport_ok", True),
                        "disposition": payload.get("disposition"),
                    },
                },
                vectors=[],
                metadata={
                    "processor_name": self._name,
                    "processor_version": ADAPTER_VERSION,
                    "processing_time_seconds": time.time() - start,
                    "operation": operation,
                    "schema_version": payload.get("schema_version"),
                    "domain_ok": domain_ok,
                    "transport_ok": payload.get("transport_ok", True),
                    "disposition": payload.get("disposition"),
                },
                warnings=warnings,
                errors=errors,
                raw_output=payload,
            )
        except Exception as exc:
            err_type = type(exc).__name__
            logger.error(
                "USPTO adapter operation %s failed: %s",
                operation,
                err_type,
            )
            return ProcessingResult(
                success=False,
                metadata={
                    "processor_name": self._name,
                    "processor_version": ADAPTER_VERSION,
                    "processing_time_seconds": time.time() - start,
                    "operation": operation,
                    "error_type": err_type,
                },
                errors=[f"{err_type}: {exc}"],
            )

    def _resolve_operation(
        self,
        meta: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> str | None:
        raw = (
            options.get("operation")
            or options.get("action")
            or meta.get("operation")
            or meta.get("action")
        )
        if raw is None:
            return None
        key = str(raw).strip().lower().replace(" ", "_")
        if key in _OPERATION_ALIASES:
            return _OPERATION_ALIASES[key]
        # Unknown keys fall through to assert_operation_allowed later.
        return key.replace("-", "_")

    def _dispatch(
        self,
        operation: str,
        context: ProcessingContext,
        meta: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        api = self._api
        source = context.source
        app_no = (
            options.get("application_number")
            or meta.get("application_number")
            or (source if isinstance(source, str) else None)
        )

        if operation == "status":
            if not app_no:
                raise UsptoAPIError(
                    "status requires application_number",
                    code="missing_application_number",
                )
            return api.status(
                str(app_no),
                matter_id=options.get("matter_id") or meta.get("matter_id"),
                force_refresh=bool(options.get("force_refresh", False)),
                credential_ref=options.get("credential_ref")
                or meta.get("credential_ref"),
            )

        if operation == "sync_public":
            if not app_no:
                raise UsptoAPIError(
                    "sync_public requires application_number",
                    code="missing_application_number",
                )
            return api.sync_public(
                str(app_no),
                matter_id=options.get("matter_id") or meta.get("matter_id"),
                force_refresh=bool(options.get("force_refresh", False)),
                sync_documents=bool(options.get("sync_documents", True)),
                document_codes=options.get("document_codes"),
                force_download=bool(options.get("force_download", False)),
                credential_ref=options.get("credential_ref")
                or meta.get("credential_ref"),
            )

        if operation == "import_private":
            tenant_id = options.get("tenant_id") or meta.get("tenant_id")
            import_path = (
                options.get("import_path")
                or options.get("path")
                or meta.get("import_path")
                or (source if isinstance(source, (str, Path)) else None)
            )
            classification = options.get("classification") or meta.get(
                "classification"
            )
            authorization = options.get("authorization") or meta.get(
                "authorization"
            )
            manifest = options.get("manifest") or meta.get("manifest")
            if not tenant_id or not import_path or classification is None:
                raise UsptoAPIError(
                    "import_private requires tenant_id, import_path/path, "
                    "and classification",
                    code="missing_private_import_args",
                )
            if authorization is None or manifest is None:
                raise UsptoAPIError(
                    "import_private requires authorization and manifest",
                    code="missing_private_import_args",
                )
            return api.import_private(
                tenant_id=str(tenant_id),
                import_path=import_path,
                classification=classification,
                authorization=authorization,
                manifest=manifest,
                fail_fast=bool(options.get("fail_fast", False)),
            )

        if operation == "analyze":
            dossier_input = options.get("dossier_input") or meta.get(
                "dossier_input"
            )
            analysis_bundle = options.get("analysis_bundle") or meta.get(
                "analysis_bundle"
            )
            return api.analyze(
                dossier_input=dossier_input,
                matter_id=options.get("matter_id") or meta.get("matter_id"),
                analysis_bundle=analysis_bundle,
                seed_classification=options.get("seed_classification")
                or meta.get("seed_classification")
                or "public_user",
                labels=options.get("labels") or meta.get("labels"),
            )

        if operation == "preflight":
            package_input = options.get("package_input") or meta.get(
                "package_input"
            )
            if package_input is None:
                raise UsptoAPIError(
                    "preflight requires package_input",
                    code="missing_preflight_input",
                )
            return api.preflight(package_input)

        if operation == "explain":
            return api.explain(
                analysis_bundle=options.get("analysis_bundle")
                or meta.get("analysis_bundle"),
                gap_report=options.get("gap_report") or meta.get("gap_report"),
                assessments=options.get("assessments") or (),
                candidate_dates=options.get("candidate_dates") or (),
                reviewer_actions=options.get("reviewer_actions") or (),
                requirements=options.get("requirements") or (),
                output_policy=options.get("output_policy"),
                matter_id=options.get("matter_id") or meta.get("matter_id"),
                analysis_id=options.get("analysis_id") or meta.get("analysis_id"),
                labels=options.get("labels") or meta.get("labels"),
            )

        if operation == "submission_assurance":
            assurance_input = (
                options.get("assurance_input")
                or options.get("submission_assurance_input")
                or meta.get("assurance_input")
                or meta.get("submission_assurance_input")
            )
            # Build kwargs from options when no full input object is provided.
            kwargs: dict[str, Any] = {}
            for key in (
                "tenant_id",
                "matter_id",
                "assurance_id",
                "application_number",
                "documents",
                "status_snapshot",
                "source_profile",
                "application_type",
                "scenario",
                "prosecution_stage",
                "filing_date",
                "as_of_utc",
                "authority_snapshot_id",
                "authority_digest",
                "authority_stale",
                "force_proof_unknown",
                "force_review_required",
                "force_partial",
                "force_quarantine",
                "force_outage",
                "classification",
                "labels",
                "offline",
                "run_preflight",
                "delta_token",
            ):
                if key in options:
                    kwargs[key] = options[key]
                elif key in meta:
                    kwargs[key] = meta[key]
            if assurance_input is not None:
                return api.submission_assurance(assurance_input, **kwargs)
            if not kwargs.get("tenant_id") or not kwargs.get("matter_id"):
                raise UsptoAPIError(
                    "submission_assurance requires tenant_id and matter_id "
                    "(plus documents/source profile) or assurance_input",
                    code="missing_assurance_input",
                )
            return api.submission_assurance(**kwargs)

        raise UsptoAPIError(
            f"unknown operation: {operation!r}",
            code="unknown_operation",
        )

    @staticmethod
    def _domain_success(
        operation: str,
        payload: Mapping[str, Any],
        result_obj: Any,
    ) -> bool:
        """Map domain disposition to adapter success (fail-closed for assurance).

        Legacy v1 operations without a domain ``success``/``ok`` field remain
        transport-success when no exception was raised. Assurance results must
        surface quarantine/outage/partial/review as ``success=False``.
        """
        if hasattr(result_obj, "success") and isinstance(
            getattr(result_obj, "success"), bool
        ):
            # Prefer explicit domain property when present.
            if operation in {"submission_assurance", "assure"}:
                return bool(result_obj.success)
            # For other result types with success, still honor it when False.
            if result_obj.success is False and operation in {
                "submission_assurance",
                "assure",
            }:
                return False
        if operation in {"submission_assurance", "assure"}:
            if "success" in payload:
                return bool(payload.get("success"))
            if "ok" in payload:
                return bool(payload.get("ok"))
            if "domain_ok" in payload:
                return bool(payload.get("domain_ok"))
            disposition = str(payload.get("disposition") or "").lower()
            if disposition and disposition != "completed":
                return False
        return True


def register_uspto_processors(
    registry: Any | None = None,
    *,
    api: USPTOAnalysisAPI | None = None,
    priority: int = ADAPTER_PRIORITY,
    name: str = ADAPTER_NAME,
    replace: bool = False,
) -> str:
    """Register :class:`USPTOProcessorAdapter` once on the canonical registry.

    Returns the registered processor name.
    """
    if registry is None:
        from ipfs_datasets_py.processors.core import get_global_registry

        registry = get_global_registry()

    adapter = USPTOProcessorAdapter(api=api, priority=priority, name=name)
    if not is_processor(adapter):
        raise TypeError(
            "USPTOProcessorAdapter failed is_processor() conformance check"
        )

    # Idempotent registration: skip or replace when name already present.
    already_registered = False
    try:
        if hasattr(registry, "list_processors"):
            listed = registry.list_processors() or {}
            if isinstance(listed, Mapping):
                already_registered = name in listed
            else:
                for entry in listed:
                    entry_name = (
                        str(entry.get("name") or "")
                        if isinstance(entry, Mapping)
                        else str(getattr(entry, "name", "") or "")
                    )
                    if entry_name == name:
                        already_registered = True
                        break
        elif hasattr(registry, "get_capabilities"):
            caps = registry.get_capabilities() or {}
            for item in caps.get("enabled", []) or []:
                if isinstance(item, Mapping) and item.get("name") == name:
                    already_registered = True
                    break
    except Exception:
        already_registered = False

    if already_registered:
        if not replace:
            logger.info("USPTO processor %r already registered; skipping", name)
            return name
        if hasattr(registry, "unregister"):
            registry.unregister(name)

    return registry.register(processor=adapter, priority=priority, name=name)


__all__ = [
    "ADAPTER_NAME",
    "ADAPTER_PRIORITY",
    "ADAPTER_VERSION",
    "USPTOProcessorAdapter",
    "register_uspto_processors",
]
