"""Compact generators for PATLAW-072 offline end-to-end replay.

Materializes public and synthetic private matter receipts into SDK-ready
pipeline results without bulk golden dumps or live network I/O.
"""

from __future__ import annotations

import contextlib
import json
import socket
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Iterator, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
    ANALYSIS_BUNDLE_RULESET_VERSION,
    AnalysisBundleBuilder,
    BundleDisposition,
    BundleSectionKind,
    UsptoAnalysisBundle,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.gap_report import (
    GapReportInput,
    GapReportRenderer,
    OutputPolicyMode,
    OutputRedactionPolicy,
    RequirementEvidenceGapReport,
)
from ipfs_datasets_py.processors.domains.uspto.api import USPTOAnalysisAPI
from ipfs_datasets_py.processors.domains.uspto.application_status_processor import (
    ApplicationStatusProcessor,
    InMemoryStatusSnapshotStore,
    StatusSyncResult,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.document_extraction_processor import (
    DocumentExtractionInput,
    DocumentExtractionProcessor,
    DocumentExtractionResult,
)
from ipfs_datasets_py.processors.domains.uspto.dossier_processor import (
    ApplicationDossier,
    CompactSectionInput,
    DossierInput,
    DossierProcessor,
)
from ipfs_datasets_py.processors.domains.uspto.artifact_manifest import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactManifest,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    AuthorityRelation,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    PrivateArtifactStore,
    TenantKeyMaterial,
    generate_tenant_key,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    HttpRequest,
    ProviderError,
    RetryPolicy,
    load_recorded_exchanges,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_center_export import (
    ImportBatchResult,
    load_fixture_authorization,
    load_fixture_manifest,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PatentFileWrapperClient,
)
from ipfs_datasets_py.processors.domains.uspto.span_validator import (
    SPAN_VALIDATOR_SCHEMA_VERSION,
    SpanValidationDisposition,
    SpanValidationPolicy,
    SpanValidationResult,
    SpanValidator,
)
from ipfs_datasets_py.processors.domains.uspto.workflow_processor import (
    PreflightPackageInput,
    PreflightResult,
)
from tests.fixtures.uspto.documents.generators import (
    NATIVE_CANARY,
    build_native_pdf_with_metadata,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPLAY_FIXTURE_DIR: Path = Path(__file__).resolve().parent
REPLAY_MANIFEST_PATH: Path = REPLAY_FIXTURE_DIR / "replay_manifest.json"
USPTO_FIXTURE_ROOT: Path = REPLAY_FIXTURE_DIR.parent

_FIXED_WALL = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Network guard (fail closed for accidental live I/O)
# ---------------------------------------------------------------------------


class NetworkBlockedError(RuntimeError):
    """Raised when a test attempts a live network socket connection."""


class _BlockedSocket(socket.socket):
    def connect(self, address):  # type: ignore[no-untyped-def]
        raise NetworkBlockedError(
            f"network blocked during offline USPTO replay: connect({address!r})"
        )

    def connect_ex(self, address):  # type: ignore[no-untyped-def]
        raise NetworkBlockedError(
            f"network blocked during offline USPTO replay: connect_ex({address!r})"
        )


@contextlib.contextmanager
def network_guard() -> Iterator[None]:
    """Temporarily replace ``socket.socket`` so live connects fail closed."""
    original = socket.socket
    socket.socket = _BlockedSocket  # type: ignore[misc, assignment]
    try:
        yield
    finally:
        socket.socket = original  # type: ignore[misc, assignment]


# ---------------------------------------------------------------------------
# Sticky recorded ODP transport
# ---------------------------------------------------------------------------


class StickyRecordedHttpTransport:
    """Non-consuming fixture transport for multi-step offline status replay."""

    def __init__(self, recipe_path: Path) -> None:
        with recipe_path.open(encoding="utf-8") as handle:
            recipe = json.load(handle)
        self._exchanges = load_recorded_exchanges(recipe)
        self.requests: list[HttpRequest] = []

    def request(self, request: HttpRequest):
        self.requests.append(request)
        first_any = None
        for exchange in self._exchanges:
            if not exchange.matches(request):
                continue
            if first_any is None:
                first_any = exchange
            if 200 <= int(exchange.status) < 300:
                return exchange.as_response()
        if first_any is not None:
            return first_any.as_response()
        raise ProviderError(
            f"no recorded exchange for {request.method} {request.url}",
            code="fixture_miss",
        )


def sticky_odp_client(
    recipe_path: Path | None = None,
    *,
    api_key: str = "synthetic-replay-key",
) -> PatentFileWrapperClient:
    path = recipe_path or (USPTO_FIXTURE_ROOT / "odp" / "http" / "odp_http_recipe.json")
    if not path.is_file():
        raise FileNotFoundError(f"missing ODP HTTP recipe: {path}")
    return PatentFileWrapperClient(
        StickyRecordedHttpTransport(path),
        api_key=api_key,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        wall_clock=lambda: _FIXED_WALL,
        sleep=lambda _s: None,
        random_sample=lambda: 0.0,
    )


# ---------------------------------------------------------------------------
# IDs / loaders
# ---------------------------------------------------------------------------


def fixed_id_factory(prefix: str = "replay") -> Callable[[], str]:
    counter = {"n": 0}

    def _next() -> str:
        counter["n"] += 1
        return f"{prefix}{counter['n']:04d}"

    return _next


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_replay_manifest() -> dict[str, Any]:
    return load_json(REPLAY_MANIFEST_PATH)


def load_recipe(name: str) -> dict[str, Any]:
    path = REPLAY_FIXTURE_DIR / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return load_json(path)


def _resolve_relative(base: Path, relative: str) -> Path:
    return (base / relative).resolve()


# ---------------------------------------------------------------------------
# Binding projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplayBinding:
    """Explicit binding of output to input/parser/model/ruleset/config/tree."""

    input_artifact_ids: tuple[str, ...]
    parser_versions: Mapping[str, str]
    model_versions: Mapping[str, str]
    ruleset_versions: Mapping[str, str]
    config_versions: Mapping[str, str]
    tree_id: str
    tree_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_versions": dict(self.config_versions),
            "input_artifact_ids": list(self.input_artifact_ids),
            "model_versions": dict(self.model_versions),
            "parser_versions": dict(self.parser_versions),
            "ruleset_versions": dict(self.ruleset_versions),
            "tree_digest": self.tree_digest,
            "tree_id": self.tree_id,
        }

    def content_digest(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))


def _pins_from_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return dict(manifest.get("version_pins") or {})


def build_binding(
    *,
    input_artifact_ids: Sequence[str] | tuple[str, ...] = (),
    manifest: Mapping[str, Any] | None = None,
    extra_rulesets: Mapping[str, str] | None = None,
    extra_models: Mapping[str, str] | None = None,
    extra_parsers: Mapping[str, str] | None = None,
) -> ReplayBinding:
    pins = _pins_from_manifest(manifest or load_replay_manifest())
    parser_versions = {
        "document_extraction": str(pins.get("parser") or "patlaw-031.document-extraction.v1"),
        "pdf": "patlaw-pdf@1",
        **dict(extra_parsers or {}),
    }
    model_versions = {
        **{str(k): str(v) for k, v in (pins.get("model") or {}).items()},
        **dict(extra_models or {}),
    }
    ruleset_versions = {
        **{str(k): str(v) for k, v in (pins.get("ruleset") or {}).items()},
        "analysis_bundle": ANALYSIS_BUNDLE_RULESET_VERSION,
        **dict(extra_rulesets or {}),
    }
    config_versions = {
        str(k): str(v) for k, v in (pins.get("config") or {}).items()
    }
    tree = pins.get("tree") or {}
    return ReplayBinding(
        input_artifact_ids=tuple(str(x) for x in input_artifact_ids),
        parser_versions=parser_versions,
        model_versions=model_versions,
        ruleset_versions=ruleset_versions,
        config_versions=config_versions,
        tree_id=str(tree.get("tree_id") or "replay-tree:unknown"),
        tree_digest=str(
            tree.get("tree_digest")
            or ("0" * 64)
        ),
    )


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


@dataclass
class ReplayPipelineResult:
    """One full offline replay through identity → preflight surfaces."""

    matter_id: str
    classification: DisclosureClassification
    binding: ReplayBinding
    status: StatusSyncResult | None = None
    extraction: DocumentExtractionResult | None = None
    span_validation: SpanValidationResult | None = None
    dossier: ApplicationDossier | None = None
    analysis_bundle: UsptoAnalysisBundle | None = None
    gap_report: RequirementEvidenceGapReport | None = None
    preflight: PreflightResult | None = None
    private_import: ImportBatchResult | None = None
    labels: dict[str, str] = field(default_factory=dict)
    span_ids: tuple[str, ...] = ()
    unknown_ids: tuple[str, ...] = ()

    def material_digest(self) -> str:
        payload = {
            "binding": self.binding.to_dict(),
            "bundle_digest": (
                None
                if self.analysis_bundle is None
                else self.analysis_bundle.bundle_digest
            ),
            "classification": self.classification.value,
            "gap_content_digest": (
                None if self.gap_report is None else self.gap_report.content_digest
            ),
            "matter_id": self.matter_id,
            "package_digest": (
                None if self.preflight is None else self.preflight.package_digest
            ),
            "span_ids": list(self.span_ids),
            "status_digest": (
                None
                if self.status is None or self.status.snapshot is None
                else self.status.snapshot.content_digest
            ),
            "unknown_ids": list(self.unknown_ids),
        }
        return sha256_hex(canonical_json(payload))

    def public_projection(self) -> dict[str, Any]:
        return {
            "binding_digest": self.binding.content_digest(),
            "bundle_digest": (
                None
                if self.analysis_bundle is None
                else self.analysis_bundle.bundle_digest
            ),
            "classification": self.classification.value,
            "is_private": bool(
                self.analysis_bundle.is_private if self.analysis_bundle else False
            ),
            "labels": dict(self.labels),
            "material_digest": self.material_digest(),
            "matter_id": self.matter_id,
            "package_digest": (
                None if self.preflight is None else self.preflight.package_digest
            ),
            "span_count": len(self.span_ids),
            "unknown_ids": list(self.unknown_ids),
        }


# ---------------------------------------------------------------------------
# Public matter materialization
# ---------------------------------------------------------------------------


def _extract_native(
    artifact_id: str,
    *,
    id_factory: Callable[[], str],
    application_number: str = "16/123,456",
) -> tuple[DocumentExtractionResult, str, bytes]:
    pdf = build_native_pdf_with_metadata(application_number=application_number)
    digest = sha256_hex(pdf)
    proc = DocumentExtractionProcessor(id_factory=id_factory)
    result = proc.extract(
        DocumentExtractionInput(
            artifact_id=artifact_id,
            content_bytes=pdf,
            declared_mime="application/pdf",
            filename=f"{artifact_id.replace(':', '_')}.pdf",
            classification=DisclosureClassification.PUBLIC_USER,
            content_sha256=digest,
            labels={"fixture": "replay_native_pdf", "suite": "patlaw-072"},
        )
    )
    return result, digest, pdf


def _span_validate(
    extraction: DocumentExtractionResult,
    content_sha256: str,
    *,
    id_factory: Callable[[], str],
    recipe: Mapping[str, Any],
) -> SpanValidationResult:
    policy_raw = recipe.get("span_policy") or {}
    policy = SpanValidationPolicy(
        min_coverage_ratio=float(policy_raw.get("min_coverage_ratio", 0.01)),
        min_overall_coverage=float(policy_raw.get("min_overall_coverage", 0.01)),
        min_readability=float(policy_raw.get("min_readability", 0.15)),
    )
    return SpanValidator(policy=policy, id_factory=id_factory).validate(
        extraction, expected_content_sha256=content_sha256
    )


def materialize_public_bundle(
    *,
    recipe: Mapping[str, Any] | None = None,
    manifest: Mapping[str, Any] | None = None,
    id_factory: Callable[[], str] | None = None,
    include_unknown: bool = False,
) -> tuple[UsptoAnalysisBundle, ReplayBinding, tuple[str, ...], tuple[str, ...]]:
    """Build a content-addressed public analysis bundle from the replay recipe."""
    recipe = recipe or load_recipe("public_matter_recipe.json")
    manifest = manifest or load_replay_manifest()
    ids = id_factory or fixed_id_factory("pub")

    art_oa = str(recipe["artifacts"][0]["artifact_id"])
    art_sub = str(recipe["artifacts"][1]["artifact_id"])
    authorities = tuple(str(a) for a in (recipe.get("authority_ids") or ()))
    classification = DisclosureClassification(
        str(recipe.get("classification") or "public_user")
    )

    binding = build_binding(
        input_artifact_ids=(art_oa, art_sub),
        manifest=manifest,
    )

    seed_labels = {
        **{str(k): str(v) for k, v in (recipe.get("labels") or {}).items()},
        "tree_id": binding.tree_id,
        "tree_digest": binding.tree_digest[:32],
        "config_digest": sha256_hex(
            canonical_json(dict(binding.config_versions))
        )[:32],
        "parser": binding.parser_versions["document_extraction"],
    }
    builder = AnalysisBundleBuilder(
        matter_id=str(recipe["matter_id"]),
        analysis_id=str(recipe.get("analysis_id") or f"analysis:{ids()}"),
        seed_classification=classification,
        labels=seed_labels,
        id_factory=ids,
    )
    builder.add_input_artifact_ids(art_oa, art_sub)
    builder.add_validation_receipt_ids("rcpt:replay:val:1", "rcpt:replay:span:1")
    builder.add_model_versions(binding.model_versions)
    builder.add_ruleset_versions(
        {
            **dict(binding.ruleset_versions),
            "parser": binding.parser_versions["document_extraction"],
            "config": sha256_hex(canonical_json(dict(binding.config_versions)))[
                :32
            ],
            "tree": binding.tree_id,
            "tree_digest": binding.tree_digest[:64],
        }
    )

    # Stable content digests from recipe seeds (not wall-clock).
    dig_oa = sha256_hex(f"replay-oa-bytes:{art_oa}".encode())
    dig_sub = sha256_hex(f"replay-sub-bytes:{art_sub}".encode())
    dig_req = sha256_hex(b"replay-requirement-compilation-v1")
    dig_status = sha256_hex(b"replay-status-snapshot-v1")
    dig_span = sha256_hex(b"replay-span-validation-v1")

    span_ids = (
        "span:replay:oa:112b",
        "span:replay:oa:abstract",
        "span:replay:sub:ack",
    )

    builder.bind_section(
        kind=BundleSectionKind.ARTIFACT_MANIFEST,
        record_id=art_oa,
        schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
        content_digest=dig_oa,
        classification=classification,
        source_artifact_ids=(art_oa,),
        ruleset_versions={"parser": binding.parser_versions["pdf"]},
        span_ids=(span_ids[0],),
    )
    builder.bind_section(
        kind=BundleSectionKind.STATUS_SNAPSHOT,
        record_id="status:replay:public:1",
        schema_version="uspto.application-status.v1",
        content_digest=dig_status,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        source_artifact_ids=(art_oa,),
        span_ids=(),
        require_provenance=True,
    )
    builder.bind_section(
        kind=BundleSectionKind.OFFICE_ACTION,
        record_id="oa:replay:public:1",
        schema_version="uspto.office-action-analysis.v1",
        content_digest=sha256_hex(b"replay-office-action-v1"),
        classification=classification,
        source_artifact_ids=(art_oa,),
        authority_ids=authorities,
        span_ids=(span_ids[0], span_ids[1]),
    )
    builder.bind_section(
        kind=BundleSectionKind.REQUIREMENT,
        record_id="req:replay:112b",
        schema_version="uspto.requirement-processor.v1",
        content_digest=dig_req,
        classification=classification,
        source_artifact_ids=(art_oa,),
        authority_ids=authorities,
        ruleset_versions={"section": "requirement-compiler-rules@1"},
        span_ids=(span_ids[0],),
        labels={"requirement_type": "rejection_112b"},
    )
    builder.bind_section(
        kind=BundleSectionKind.SUBMISSION_EVIDENCE,
        record_id="evid:replay:public:1",
        schema_version="uspto.submission-evidence.v1",
        content_digest=sha256_hex(b"replay-evidence-v1"),
        classification=classification,
        source_artifact_ids=(art_sub,),
        span_ids=(span_ids[2],),
    )
    builder.bind_section(
        kind=BundleSectionKind.COMPLIANCE,
        record_id="cmpl:replay:public:1",
        schema_version="uspto.submission-compliance.v1",
        content_digest=sha256_hex(b"replay-compliance-v1"),
        classification=classification,
        source_artifact_ids=(art_oa, art_sub),
        authority_ids=authorities,
        span_ids=(span_ids[0], span_ids[2]),
    )
    builder.bind_section(
        kind=BundleSectionKind.ASSESSMENT,
        record_id="assess:replay:public:1",
        schema_version="uspto.submission-compliance.v1",
        content_digest=sha256_hex(b"replay-assessment-v1"),
        classification=classification,
        source_artifact_ids=(art_sub,),
        authority_ids=authorities,
        span_ids=(span_ids[2],),
    )
    builder.bind_section(
        kind=BundleSectionKind.AUTHORITY,
        record_id="auth-bind:replay:public:1",
        schema_version="uspto.authority.v1",
        content_digest=sha256_hex(b"replay-authority-v1"),
        classification=classification,
        source_artifact_ids=(art_oa,),
        authority_ids=authorities,
        span_ids=(span_ids[0],),
    )
    builder.bind_section(
        kind=BundleSectionKind.REJECTION_MAPPING,
        record_id="rej:replay:public:1",
        schema_version="uspto.rejection-mapping.v1",
        content_digest=sha256_hex(b"replay-rejection-v1"),
        classification=classification,
        source_artifact_ids=(art_oa,),
        authority_ids=authorities,
        span_ids=(span_ids[0],),
    )
    builder.bind_section(
        kind=BundleSectionKind.CANDIDATE_DATE,
        record_id="deadline:replay:public:1",
        schema_version="uspto.deadline-processor.v1",
        content_digest=sha256_hex(b"replay-deadline-v1"),
        classification=classification,
        source_artifact_ids=(art_oa,),
        authority_ids=authorities,
        span_ids=(span_ids[0],),
    )
    builder.bind_section(
        kind=BundleSectionKind.SPAN_VALIDATION,
        record_id="spanval:replay:public:1",
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        content_digest=dig_span,
        classification=classification,
        source_artifact_ids=(art_oa, art_sub),
        span_ids=span_ids,
    )
    builder.bind_section(
        kind=BundleSectionKind.VALIDATION_RECEIPT,
        record_id="vr:replay:public:1",
        schema_version="uspto.office-action-analysis.v1",
        content_digest=sha256_hex(b"replay-validation-receipt-v1"),
        classification=classification,
        source_artifact_ids=(art_oa,),
        span_ids=span_ids,
    )

    unknown_ids: tuple[str, ...] = ()
    if include_unknown or bool((recipe.get("unknown_variant") or {}).get("enabled")):
        unk = str(
            (recipe.get("unknown_variant") or {}).get("unknown_id")
            or "unk:replay:low-ocr"
        )
        unknown_ids = (unk,)
        builder.add_unsupported_check("check:readability-threshold")
        builder.add_ruleset_versions({"unknown_gate": unk})

    bundle = builder.build(bundle_id=str(recipe.get("bundle_id") or f"bundle:{ids()}"))
    if include_unknown and unknown_ids:
        # Annotate unknowns as first-class labels; recompute content digest.
        from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
            compute_bundle_digest,
        )

        data = bundle.to_dict()
        data["disposition"] = BundleDisposition.PARTIAL.value
        data["review_state"] = ReviewState.REQUIRED.value
        data["labels"] = {
            **dict(data.get("labels") or {}),
            "unknown_ids": ",".join(unknown_ids),
        }
        restored = UsptoAnalysisBundle.from_dict(data)
        digest = compute_bundle_digest(
            schema_version=restored.schema_version,
            matter_id=restored.matter_id,
            disposition=restored.disposition,
            review_state=restored.review_state,
            classification=restored.classification,
            input_artifact_ids=restored.input_artifact_ids,
            output_artifact_ids=restored.output_artifact_ids,
            sections=restored.sections,
            provenance=restored.provenance,
            warnings=restored.warnings,
            warning_codes=restored.warning_codes,
            unsupported_checks=restored.unsupported_checks,
            model_versions=restored.model_versions,
            ruleset_versions=restored.ruleset_versions,
            validation_receipt_ids=restored.validation_receipt_ids,
            labels=restored.labels,
            analysis_id=restored.analysis_id,
        )
        data["bundle_digest"] = digest
        bundle = UsptoAnalysisBundle.from_dict(data)

    return bundle, binding, span_ids, unknown_ids


def materialize_unknown_bundle(
    *,
    id_factory: Callable[[], str] | None = None,
) -> tuple[UsptoAnalysisBundle, ReplayBinding, tuple[str, ...], tuple[str, ...]]:
    recipe = load_recipe("public_matter_recipe.json")
    recipe = dict(recipe)
    recipe["matter_id"] = "matter:replay:unknown:low-ocr"
    recipe["analysis_id"] = "analysis:replay:unknown:1"
    recipe["bundle_id"] = "bundle:replay:unknown:1"
    return materialize_public_bundle(
        recipe=recipe,
        id_factory=id_factory or fixed_id_factory("unk"),
        include_unknown=True,
    )


def materialize_private_bundle(
    *,
    recipe: Mapping[str, Any] | None = None,
    manifest: Mapping[str, Any] | None = None,
    id_factory: Callable[[], str] | None = None,
    imported_artifact_ids: Sequence[str] = (),
) -> tuple[UsptoAnalysisBundle, ReplayBinding, tuple[str, ...]]:
    recipe = recipe or load_recipe("private_matter_recipe.json")
    manifest = manifest or load_replay_manifest()
    ids = id_factory or fixed_id_factory("priv")
    classification = DisclosureClassification.CONFIDENTIAL_APPLICATION
    tenant = str(recipe.get("tenant_id") or "tenant-replay-a")

    if imported_artifact_ids:
        art_ids = tuple(str(a) for a in imported_artifact_ids)
    else:
        art_ids = tuple(
            str(a["artifact_id"]) for a in (recipe.get("artifacts") or ())
        )
    if not art_ids:
        art_ids = ("art:replay:priv:spec", "art:replay:priv:pdf")

    binding = build_binding(input_artifact_ids=art_ids, manifest=manifest)
    authorities = tuple(str(a) for a in (recipe.get("authority_ids") or ()))
    span_ids = ("span:replay:priv:claim", "span:replay:priv:spec")

    seed_labels = {
        **{str(x): str(y) for x, y in (recipe.get("labels") or {}).items()},
        "tree_id": binding.tree_id,
        "tenant_id": tenant,
    }
    builder = AnalysisBundleBuilder(
        matter_id=str(recipe["matter_id"]),
        analysis_id=str(recipe.get("analysis_id") or f"analysis:{ids()}"),
        seed_classification=classification,
        labels=seed_labels,
        id_factory=ids,
    )
    builder.add_input_artifact_ids(*art_ids)
    builder.add_validation_receipt_ids("rcpt:replay:priv:val:1")
    builder.add_model_versions(binding.model_versions)
    builder.add_ruleset_versions(
        {
            **dict(binding.ruleset_versions),
            "parser": binding.parser_versions["document_extraction"],
            "tree": binding.tree_id,
            "tree_digest": binding.tree_digest[:64],
            "tenant": tenant,
        }
    )

    builder.bind_section(
        kind=BundleSectionKind.ARTIFACT_MANIFEST,
        record_id=art_ids[0],
        schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
        content_digest=sha256_hex(f"priv-art:{art_ids[0]}".encode()),
        classification=classification,
        source_artifact_ids=(art_ids[0],),
        span_ids=(span_ids[0],),
    )
    builder.bind_section(
        kind=BundleSectionKind.REQUIREMENT,
        record_id="req:replay:priv:112b",
        schema_version="uspto.requirement-processor.v1",
        content_digest=sha256_hex(b"priv-req-v1"),
        classification=classification,
        source_artifact_ids=(art_ids[0],),
        authority_ids=authorities,
        span_ids=(span_ids[0],),
    )
    builder.bind_section(
        kind=BundleSectionKind.SUBMISSION_EVIDENCE,
        record_id="evid:replay:priv:1",
        schema_version="uspto.submission-evidence.v1",
        content_digest=sha256_hex(b"priv-evid-v1"),
        classification=classification,
        source_artifact_ids=art_ids,
        span_ids=span_ids,
    )
    builder.bind_section(
        kind=BundleSectionKind.ASSESSMENT,
        record_id="assess:replay:priv:1",
        schema_version="uspto.submission-compliance.v1",
        content_digest=sha256_hex(b"priv-assess-v1"),
        classification=classification,
        source_artifact_ids=art_ids,
        authority_ids=authorities,
        span_ids=span_ids,
    )
    builder.bind_section(
        kind=BundleSectionKind.AUTHORITY,
        record_id="auth-bind:replay:priv:1",
        schema_version="uspto.authority.v1",
        content_digest=sha256_hex(b"priv-auth-v1"),
        classification=classification,
        source_artifact_ids=(art_ids[0],),
        authority_ids=authorities,
        span_ids=(span_ids[0],),
    )
    builder.bind_section(
        kind=BundleSectionKind.SPAN_VALIDATION,
        record_id="spanval:replay:priv:1",
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        content_digest=sha256_hex(b"priv-spanval-v1"),
        classification=classification,
        source_artifact_ids=art_ids,
        span_ids=span_ids,
    )
    builder.bind_section(
        kind=BundleSectionKind.VALIDATION_RECEIPT,
        record_id="vr:replay:priv:1",
        schema_version="uspto.office-action-analysis.v1",
        content_digest=sha256_hex(b"priv-vr-v1"),
        classification=classification,
        source_artifact_ids=art_ids,
        span_ids=span_ids,
    )

    bundle = builder.build(bundle_id=str(recipe.get("bundle_id") or f"bundle:{ids()}"))
    return bundle, binding, span_ids


# ---------------------------------------------------------------------------
# Full pipelines
# ---------------------------------------------------------------------------


def build_public_replay_pipeline(
    *,
    store_tmp: Path | None = None,  # unused; kept for call-site symmetry
    include_unknown: bool = True,
    id_prefix: str = "pub",
) -> ReplayPipelineResult:
    """Replay public matter: status → extract → spans → analyze → explain → preflight."""
    del store_tmp
    manifest = load_replay_manifest()
    recipe = load_recipe("public_matter_recipe.json")
    ids = fixed_id_factory(id_prefix)

    client = sticky_odp_client()
    status_proc = ApplicationStatusProcessor(
        client=client,
        store=InMemoryStatusSnapshotStore(),
        wall_clock=lambda: _FIXED_WALL,
        max_freshness_age=timedelta(
            days=int((manifest.get("version_pins") or {}).get("config", {}).get(
                "freshness_max_days", 7300
            ))
        ),
        fetch_transactions=True,
    )
    app_no = str(recipe["application_number"])
    status = status_proc.sync(app_no, matter_id=str(recipe["matter_id"]))

    art_oa = str(recipe["artifacts"][0]["artifact_id"])
    extraction, content_sha, _pdf = _extract_native(
        art_oa, id_factory=ids, application_number="16/123,456"
    )
    assert NATIVE_CANARY in (extraction.full_text or ""), "fixture canary missing"
    span_val = _span_validate(extraction, content_sha, id_factory=ids, recipe=recipe)

    # Real extraction span ids for resolve checks.
    live_span_ids = tuple(s.span_id for s in extraction.spans if getattr(s, "span_id", None))

    bundle, binding, recipe_span_ids, unknown_ids = materialize_public_bundle(
        recipe=recipe,
        manifest=manifest,
        id_factory=ids,
        include_unknown=include_unknown,
    )
    # Merge live extraction span ids into resolve set.
    all_span_ids = tuple(dict.fromkeys((*recipe_span_ids, *live_span_ids)))

    api = USPTOAnalysisAPI(client=client, id_factory=ids)
    analyzed = api.analyze(analysis_bundle=bundle, labels=dict(recipe.get("labels") or {}))
    report = api.explain(
        analyzed.analysis_bundle,
        assessments=(
            {
                "requirement_id": "req:replay:112b",
                "status": "unsatisfied",
                "assessment_id": "assess:replay:public:1",
                "evidence_span_ids": list(recipe_span_ids[:1]),
                "counter_evidence_span_ids": (),
                "authority_ids": list(recipe.get("authority_ids") or ()),
                "reason_codes": ("missing_evidence",),
                "confidence": 0.4,
                "source_artifact_ids": [art_oa],
                "labels": {},
            },
        ),
        candidate_dates=(
            {
                "candidate_id": "deadline:replay:public:1",
                "status": "unknown",
                "candidate_utc": "2024-09-01T00:00:00Z",
                "uncertainty_summary": "entity-status unconfirmed",
                "uncertainty_kinds": ("entity_status",),
                "assumptions": {"entity_status": "undiscounted"},
                "is_unknown": True,
                "is_review_only": True,
                "human_review_question": "Confirm response period?",
                "classification": DisclosureClassification.PUBLIC_USER.value,
                "rule_chain": ("37-cfr-1.134",),
                "source_artifact_ids": [art_oa],
                "authority_ids": list(recipe.get("authority_ids") or ()),
                "labels": {},
            },
        ),
        output_policy=OutputRedactionPolicy(mode=OutputPolicyMode.REDACT_PRIVATE),
        labels={"suite": "patlaw-072"},
    )

    if include_unknown:
        unknown_ids = tuple(
            dict.fromkeys(
                (
                    *unknown_ids,
                    *(
                        getattr(u, "statement_id", None)
                        or (u.get("statement_id") if isinstance(u, Mapping) else None)
                        for u in (report.unknowns or ())
                    ),
                )
            )
        )
        unknown_ids = tuple(u for u in unknown_ids if u)
        if not unknown_ids:
            unknown_ids = (
                str(
                    (recipe.get("unknown_variant") or {}).get("unknown_id")
                    or "unk:replay:low-ocr"
                ),
            )

    package = PreflightPackageInput(
        matter_id=str(recipe["matter_id"]),
        source_bundle_id=analyzed.analysis_bundle.bundle_id,
        source_bundle_digest=analyzed.analysis_bundle.bundle_digest,
        gap_report_id=report.report_id,
        gap_report_digest=report.content_digest,
        analysis_id=analyzed.analysis_bundle.analysis_id,
        open_unknown_ids=unknown_ids,
        open_gap_ids=("gap:replay:req:112b",),
        open_candidate_date_ids=("deadline:replay:public:1",),
        mandatory_review_remaining=True,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"suite": "patlaw-072", "tree_id": binding.tree_id},
        gap_report=report,
        analysis_bundle=analyzed.analysis_bundle,
    )
    preflight = api.preflight(package)

    # Optional dossier binding (compact sections + artifact with parser pins).
    dossier = DossierProcessor(id_factory=ids).assemble(
        DossierInput(
            matter_id=str(recipe["matter_id"]),
            artifacts=(
                ArtifactManifest(
                    schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
                    artifact_id=art_oa,
                    sha256=content_sha,
                    size_bytes=max(1, int(getattr(extraction, "size_bytes", 0) or 0)
                                  or len(extraction.full_text or "")
                                  or 1),
                    classification=DisclosureClassification.PUBLIC_USER,
                    media_type="application/pdf",
                    media_signature="pdf",
                    private_cid=None,
                    public_cid=None,
                    encryption_namespace=None,
                    matter_id=str(recipe["matter_id"]),
                    source_receipt_id="rcpt:replay:extract:1",
                    authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
                    parent_artifact_ids=(),
                    parser_versions=dict(binding.parser_versions),
                    labels={"suite": "patlaw-072"},
                ),
            ),
            compact_sections=(
                CompactSectionInput(
                    kind=BundleSectionKind.REQUIREMENT,
                    record_id="req:replay:112b",
                    schema_version="uspto.requirement-processor.v1",
                    content_digest=sha256_hex(b"replay-requirement-compilation-v1"),
                    classification=DisclosureClassification.PUBLIC_USER,
                    source_artifact_ids=(art_oa,),
                    authority_ids=tuple(
                        str(a) for a in (recipe.get("authority_ids") or ())
                    ),
                    ruleset_versions={"section": "requirement-compiler-rules@1"},
                ),
            ),
            seed_classification=DisclosureClassification.PUBLIC_USER,
            model_versions=dict(binding.model_versions),
            ruleset_versions=dict(binding.ruleset_versions),
            labels={"tree_id": binding.tree_id, "suite": "patlaw-072"},
            analysis_id=str(recipe.get("analysis_id")),
            as_of_utc="2026-08-03T12:00:00Z",
        )
    )

    return ReplayPipelineResult(
        matter_id=str(recipe["matter_id"]),
        classification=DisclosureClassification.PUBLIC_USER,
        binding=binding,
        status=status,
        extraction=extraction,
        span_validation=span_val,
        dossier=dossier,
        analysis_bundle=analyzed.analysis_bundle,
        gap_report=report,
        preflight=preflight,
        labels={
            "suite": "patlaw-072",
            "channel": "public",
            "tree_id": binding.tree_id,
            "application_number": app_no,
        },
        span_ids=all_span_ids,
        unknown_ids=unknown_ids,
    )


def build_private_replay_pipeline(
    *,
    store_root: Path,
    id_prefix: str = "priv",
) -> ReplayPipelineResult:
    """Replay synthetic private matter: authorized import → analyze → explain → preflight."""
    manifest = load_replay_manifest()
    recipe = load_recipe("private_matter_recipe.json")
    ids = fixed_id_factory(id_prefix)
    tenant = str(recipe["tenant_id"])

    import_root = _resolve_relative(
        REPLAY_FIXTURE_DIR,
        str((recipe.get("private_import") or {}).get("fixture_root") or "../private_import"),
    )
    key = generate_tenant_key(tenant)
    store = PrivateArtifactStore(
        store_root / f"store-{tenant}",
        TenantKeyMaterial(tenant_id=tenant, key_bytes=key.key_bytes),
    )
    api = USPTOAnalysisAPI(private_store=store, id_factory=ids)
    auth = load_fixture_authorization(
        import_root, import_root=import_root, tenant_id=tenant
    )
    export_manifest = load_fixture_manifest(import_root)
    imported = api.import_private(
        tenant_id=tenant,
        import_path=import_root,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        authorization=auth,
        manifest=export_manifest,
    )
    imported_ids = tuple(
        r.artifact_id
        for r in (imported.results or ())
        if getattr(r, "status", None) == "imported" and r.artifact_id
    )

    bundle, binding, span_ids = materialize_private_bundle(
        recipe=recipe,
        manifest=manifest,
        id_factory=ids,
        imported_artifact_ids=imported_ids or (),
    )
    analyzed = api.analyze(
        analysis_bundle=bundle,
        labels={"tenant_id": tenant, "suite": "patlaw-072"},
    )
    report = api.explain(
        analyzed.analysis_bundle,
        output_policy=OutputRedactionPolicy(mode=OutputPolicyMode.REDACT_PRIVATE),
        labels={"tenant_id": tenant},
    )
    package = PreflightPackageInput(
        matter_id=str(recipe["matter_id"]),
        source_bundle_id=analyzed.analysis_bundle.bundle_id,
        source_bundle_digest=analyzed.analysis_bundle.bundle_digest,
        gap_report_id=report.report_id,
        gap_report_digest=report.content_digest,
        analysis_id=analyzed.analysis_bundle.analysis_id,
        open_unknown_ids=(),
        open_gap_ids=("gap:replay:priv:req",),
        mandatory_review_remaining=True,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        labels={"tenant_id": tenant, "tree_id": binding.tree_id},
        gap_report=report,
        analysis_bundle=analyzed.analysis_bundle,
    )
    preflight = api.preflight(package)

    return ReplayPipelineResult(
        matter_id=str(recipe["matter_id"]),
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        binding=binding,
        analysis_bundle=analyzed.analysis_bundle,
        gap_report=report,
        preflight=preflight,
        private_import=imported,
        labels={
            "suite": "patlaw-072",
            "channel": "private",
            "tenant_id": tenant,
            "tree_id": binding.tree_id,
        },
        span_ids=span_ids,
        unknown_ids=(),
    )


__all__ = [
    "REPLAY_FIXTURE_DIR",
    "REPLAY_MANIFEST_PATH",
    "NetworkBlockedError",
    "ReplayBinding",
    "ReplayPipelineResult",
    "build_binding",
    "build_private_replay_pipeline",
    "build_public_replay_pipeline",
    "fixed_id_factory",
    "load_recipe",
    "load_replay_manifest",
    "materialize_private_bundle",
    "materialize_public_bundle",
    "materialize_unknown_bundle",
    "network_guard",
    "sticky_odp_client",
]
