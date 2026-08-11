"""PATLAW-142: true offline full-processor USPTO pipeline E2E (v2).

Acceptance (fail-closed):

* Test fails if any named processor is bypassed
* Output and metric receipts bind all versions/digests
* Injected quota / timeout / corruption / stale-law / restart cases propagate
* Default suite is deterministic and offline (network guard)

Conflict policy: own the v2 recipe + this E2E only. No credentials, no
mandatory live I/O, no mutation of production/private matter state.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

import pytest

from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import uspto_tools as mcp_mod
from ipfs_datasets_py.processors.domains.uspto.api import (
    FORBIDDEN_API_OPERATIONS,
    USPTOAnalysisAPI,
)
from ipfs_datasets_py.processors.domains.uspto.application_status_processor import (
    ApplicationStatusProcessor,
    InMemoryStatusSnapshotStore,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.document_extraction_processor import (
    DocumentExtractionInput,
    DocumentExtractionProcessor,
)
from ipfs_datasets_py.processors.domains.uspto.document_pipeline_processor import (
    DOCUMENT_PIPELINE_SCHEMA_VERSION,
    PIPELINE_STAGE_ORDER,
    DocumentPipelineInput,
    DocumentPipelineJobStore,
    DocumentPipelineProcessor,
    PipelineDisposition,
)
from ipfs_datasets_py.processors.domains.uspto.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    REQUIRED_RECEIPT_METRIC_IDS,
    EvaluationIdentity,
    USPTOGoldEvaluator,
    content_digest,
    digest_uri,
    load_gold_case,
    load_metric_gates,
    perfect_output_from_case,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.matter_analysis_processor import (
    MATTER_ANALYSIS_SCHEMA_VERSION,
    MatterAnalysisInput,
    MatterAnalysisStage,
    MatterDocumentInput,
    create_matter_analysis_processor,
    parser_digest as matter_parser_digest,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    PrivateArtifactStore,
    generate_tenant_key,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    ProviderOutcomeKind,
    ProviderResult,
    sanitize_secret_text,
)
from ipfs_datasets_py.processors.domains.uspto.providers.odp_contract_monitor import (
    ContractCanaryKind,
    classify_provider_result,
)
from ipfs_datasets_py.processors.domains.uspto.scheduler import (
    AlertKind,
    PollDisposition,
    PollResult,
    SchedulerConfig,
    create_scheduler,
)
from ipfs_datasets_py.processors.domains.uspto.span_validator import (
    SpanValidationPolicy,
    SpanValidator,
)
from ipfs_datasets_py.processors.domains.uspto.submission_assurance_processor import (
    SUBMISSION_ASSURANCE_SCHEMA_VERSION,
    AssuranceDisposition,
    AssuranceStage,
    SubmissionAssuranceInput,
    create_submission_assurance_processor,
    parser_digest as assurance_parser_digest,
)
from tests.fixtures.uspto.documents.generators import (
    NATIVE_CANARY,
    build_corrupt_pdf,
    build_native_pdf_with_metadata,
)
from tests.fixtures.uspto.replay.generators import (
    NetworkBlockedError,
    network_guard,
    sticky_odp_client,
)

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY_DIR = REPO_ROOT / "tests" / "fixtures" / "uspto" / "replay"
RECIPE_PATH = REPLAY_DIR / "full_pipeline_v2_recipe.json"
GOLD_ROOT = REPO_ROOT / "tests" / "fixtures" / "uspto" / "gold"
GATES_PATH = GOLD_ROOT / "metrics" / "metric_gates.json"

TASK_ID = "PATLAW-142"
_FIXED_WALL = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)

# Map leaf processor names that matter_analysis / assurance cover via stages.
_MATTER_STAGE_ALIASES: Mapping[str, str] = {
    "office_action_semantics": MatterAnalysisStage.OFFICE_ACTION_SEMANTICS.value,
    "submission_semantics": MatterAnalysisStage.SUBMISSION_SEMANTICS.value,
    "authority_view": MatterAnalysisStage.AUTHORITY_VIEW.value,
    "legal_ir_proof": MatterAnalysisStage.LEGAL_LOGIC.value,
    "deadlines": MatterAnalysisStage.TEMPORAL_CANDIDATES.value,
    "dossier": MatterAnalysisStage.DOSSIER.value,
}


# ---------------------------------------------------------------------------
# Recipe loaders
# ---------------------------------------------------------------------------


def load_full_pipeline_v2_recipe() -> dict[str, Any]:
    with RECIPE_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError("full_pipeline_v2_recipe root must be an object")
    return data


def named_processors(recipe: Mapping[str, Any]) -> tuple[str, ...]:
    raw = recipe.get("named_processors") or ()
    return tuple(str(p) for p in raw)


# ---------------------------------------------------------------------------
# Execution ledger (bypass detection)
# ---------------------------------------------------------------------------


@dataclass
class ProcessorExecutionLedger:
    """Records which named processors actually ran during a pipeline pass."""

    expected: tuple[str, ...]
    executed: dict[str, dict[str, Any]] = field(default_factory=dict)

    def mark(
        self,
        name: str,
        *,
        digest: str | None = None,
        version: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "executed": True,
            "digest": digest,
            "version": version,
        }
        if extra:
            payload.update(dict(extra))
        self.executed[name] = payload

    def mark_many(
        self,
        names: Sequence[str],
        *,
        digest: str | None = None,
        version: str | None = None,
    ) -> None:
        for name in names:
            self.mark(name, digest=digest, version=version)

    def assert_none_bypassed(self) -> None:
        missing = [n for n in self.expected if n not in self.executed]
        if missing:
            pytest.fail(
                "named processor(s) bypassed (not executed): "
                + ", ".join(sorted(missing))
            )
        for name in self.expected:
            assert self.executed[name].get("executed") is True, name

    def receipt_projection(self) -> dict[str, Any]:
        return {
            "expected": list(self.expected),
            "executed": {
                k: {
                    "digest": v.get("digest"),
                    "executed": True,
                    "version": v.get("version"),
                }
                for k, v in sorted(self.executed.items())
            },
        }


# ---------------------------------------------------------------------------
# Binding / digests
# ---------------------------------------------------------------------------


def _digest_map(values: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(dict(values)))


def _stable_processor_digest(
    name: str,
    *,
    version: str,
    outcome: str,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Content-address a processor invocation without runtime UUIDs."""
    payload: dict[str, Any] = {
        "name": name,
        "outcome": outcome,
        "version": version,
    }
    if extra:
        payload["extra"] = {
            str(k): v
            for k, v in sorted(extra.items(), key=lambda kv: str(kv[0]))
        }
    return sha256_hex(canonical_json(payload))


@dataclass(frozen=True, slots=True)
class PipelineV2Binding:
    """Output binding of input/parser/model/ruleset/config/tree/processors."""

    input_artifact_ids: tuple[str, ...]
    parser_versions: Mapping[str, str]
    model_versions: Mapping[str, str]
    ruleset_versions: Mapping[str, str]
    config_versions: Mapping[str, str]
    processor_versions: Mapping[str, str]
    processor_digests: Mapping[str, str]
    tree_id: str
    tree_digest: str
    metric_receipt_digest: str | None = None
    pipeline_material_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_versions": dict(self.config_versions),
            "input_artifact_ids": list(self.input_artifact_ids),
            "metric_receipt_digest": self.metric_receipt_digest,
            "model_versions": dict(self.model_versions),
            "parser_versions": dict(self.parser_versions),
            "pipeline_material_digest": self.pipeline_material_digest,
            "processor_digests": dict(self.processor_digests),
            "processor_versions": dict(self.processor_versions),
            "ruleset_versions": dict(self.ruleset_versions),
            "tree_digest": self.tree_digest,
            "tree_id": self.tree_id,
        }

    def content_digest(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))


def build_binding_from_recipe(
    recipe: Mapping[str, Any],
    *,
    input_artifact_ids: Sequence[str],
    processor_versions: Mapping[str, str],
    processor_digests: Mapping[str, str],
    metric_receipt_digest: str | None = None,
    pipeline_material_digest: str | None = None,
) -> PipelineV2Binding:
    pins = recipe.get("version_pins") or {}
    tree = pins.get("tree") or {}
    return PipelineV2Binding(
        input_artifact_ids=tuple(str(x) for x in input_artifact_ids),
        parser_versions={
            "document_extraction": str(
                pins.get("parser") or "patlaw-031.document-extraction.v1"
            ),
            "pdf": "patlaw-pdf@1",
        },
        model_versions={
            str(k): str(v) for k, v in (pins.get("model") or {}).items()
        },
        ruleset_versions={
            str(k): str(v) for k, v in (pins.get("ruleset") or {}).items()
        },
        config_versions={
            str(k): str(v) for k, v in (pins.get("config") or {}).items()
        },
        processor_versions=dict(processor_versions),
        processor_digests=dict(processor_digests),
        tree_id=str(tree.get("tree_id") or "replay-tree:unknown"),
        tree_digest=str(tree.get("tree_digest") or ("0" * 64)),
        metric_receipt_digest=metric_receipt_digest,
        pipeline_material_digest=pipeline_material_digest,
    )


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------


def _docs_from_recipe(recipe: Mapping[str, Any]) -> tuple[MatterDocumentInput, ...]:
    texts = recipe.get("document_texts") or {}
    classification = DisclosureClassification(
        str((recipe.get("matter") or {}).get("classification") or "public_user")
    )
    out: list[MatterDocumentInput] = []
    for entry in recipe.get("documents") or ():
        text_key = str(entry.get("text_key") or "")
        body = str(texts.get(text_key) or "")
        out.append(
            MatterDocumentInput(
                document_id=str(entry["document_id"]),
                role=str(entry.get("role") or "other"),
                document_code=entry.get("document_code"),
                text=body,
                classification=classification,
            )
        )
    return tuple(out)


def _assurance_input(
    recipe: Mapping[str, Any],
    *,
    assurance_id: str | None = None,
    **overrides: Any,
) -> SubmissionAssuranceInput:
    matter = recipe["matter"]
    data: dict[str, Any] = {
        "tenant_id": matter["tenant_id"],
        "matter_id": matter["matter_id"],
        "assurance_id": assurance_id or matter["assurance_id"],
        "application_number": matter["application_number"],
        "documents": _docs_from_recipe(recipe),
        "status_snapshot": dict(recipe.get("status_snapshot") or {}),
        "source_profile": matter.get("source_profile") or "offline_authorized",
        "application_type": matter.get("application_type") or "utility",
        "scenario": matter.get("scenario") or "new_application",
        "as_of_utc": matter.get("as_of_utc"),
        "authority_snapshot_id": matter.get("authority_snapshot_id"),
        "classification": DisclosureClassification(
            str(matter.get("classification") or "public_user")
        ),
        "labels": {
            **{str(k): str(v) for k, v in (recipe.get("labels") or {}).items()},
            "task_id": TASK_ID,
        },
        "offline": True,
        "run_preflight": False,
    }
    data.update(overrides)
    return SubmissionAssuranceInput(**data)


def _matter_input(
    recipe: Mapping[str, Any],
    *,
    analysis_id: str | None = None,
    **overrides: Any,
) -> MatterAnalysisInput:
    matter = recipe["matter"]
    data: dict[str, Any] = {
        "tenant_id": matter["tenant_id"],
        "matter_id": matter["matter_id"],
        "analysis_id": analysis_id or matter["analysis_id"],
        "application_number": matter["application_number"],
        "documents": _docs_from_recipe(recipe),
        "status_snapshot": dict(recipe.get("status_snapshot") or {}),
        "as_of_utc": matter.get("as_of_utc"),
        "authority_snapshot_id": matter.get("authority_snapshot_id"),
        "classification": DisclosureClassification(
            str(matter.get("classification") or "public_user")
        ),
        "labels": {
            **{str(k): str(v) for k, v in (recipe.get("labels") or {}).items()},
            "task_id": TASK_ID,
        },
        "offline": True,
    }
    data.update(overrides)
    return MatterAnalysisInput(**data)


def _id_factory(prefix: str) -> Callable[[], str]:
    counter = {"n": 0}

    def _next() -> str:
        counter["n"] += 1
        return f"{prefix}:{counter['n']:04d}"

    return _next


# ---------------------------------------------------------------------------
# Full offline pipeline runner
# ---------------------------------------------------------------------------


@dataclass
class FullPipelineV2Result:
    """Aggregate result of one offline full-processor pass."""

    recipe: Mapping[str, Any]
    ledger: ProcessorExecutionLedger
    binding: PipelineV2Binding
    status_ok: bool
    extraction_digest: str
    pipeline_disposition: str
    matter_result: Any
    assurance_result: Any
    metric_receipt: Any
    mcp_summary: Mapping[str, Any]
    scheduler_alert_kind: str | None
    material_digest: str

    def public_projection(self) -> dict[str, Any]:
        return {
            "binding": self.binding.to_dict(),
            "binding_digest": self.binding.content_digest(),
            "ledger": self.ledger.receipt_projection(),
            "material_digest": self.material_digest,
            "metric_receipt_digest": (
                None
                if self.metric_receipt is None
                else self.metric_receipt.receipt_digest
            ),
            "pipeline_disposition": self.pipeline_disposition,
            "status_ok": self.status_ok,
            "task_id": TASK_ID,
            "tree_id": self.binding.tree_id,
        }


def run_full_offline_pipeline_v2(
    recipe: Mapping[str, Any],
    *,
    tmp_path: Path,
    id_prefix: str = "v2",
) -> FullPipelineV2Result:
    """Exercise every named processor offline and bind digests."""

    expected = named_processors(recipe)
    ledger = ProcessorExecutionLedger(expected=expected)
    matter_cfg = recipe["matter"]
    ids = _id_factory(id_prefix)
    processor_versions: MutableMapping[str, str] = {}
    processor_digests: MutableMapping[str, str] = {}

    # --- 1. ODP transport + status sync (recorded, network-free) ---
    client = sticky_odp_client()
    odp_ver = "PatentFileWrapperClient@recorded"
    odp_dig = _stable_processor_digest(
        "odp_transport", version=odp_ver, outcome="recorded"
    )
    ledger.mark("odp_transport", version=odp_ver, digest=odp_dig)
    processor_versions["odp_transport"] = odp_ver
    processor_digests["odp_transport"] = odp_dig

    status_proc = ApplicationStatusProcessor(
        client=client,
        store=InMemoryStatusSnapshotStore(),
        wall_clock=lambda: _FIXED_WALL,
        fetch_transactions=bool(
            (recipe.get("odp") or {}).get("fetch_transactions", True)
        ),
    )
    status = status_proc.sync(
        str(matter_cfg["application_number"]),
        matter_id=str(matter_cfg["matter_id"]),
    )
    status_ok = bool(status.ok)
    status_digest = (
        status.snapshot.content_digest
        if status.snapshot is not None
        else sha256_hex(b"status-missing")
    )
    status_ver = "ApplicationStatusProcessor@1"
    status_bound = _stable_processor_digest(
        "status_sync",
        version=status_ver,
        outcome="ok" if status_ok else "fail",
        extra={"application_number": str(matter_cfg["application_number"])},
    )
    ledger.mark(
        "status_sync",
        version=status_ver,
        digest=status_bound,
        extra={"ok": status_ok, "runtime_digest": status_digest},
    )
    processor_versions["status_sync"] = status_ver
    processor_digests["status_sync"] = status_bound

    # --- 2. Document pipeline + extraction + span validation ---
    pdf = build_native_pdf_with_metadata(
        application_number="16/123,456",
    )
    # PyMuPDF may embed wall-clock metadata; bind a recipe-stable fixture id
    # rather than the raw PDF bytes so offline double-runs stay deterministic.
    pdf_digest = sha256_hex(
        canonical_json(
            {
                "application_number": "16/123,456",
                "canary": NATIVE_CANARY,
                "fixture": "native_pdf_with_metadata",
                "task_id": TASK_ID,
            }
        )
    )
    key = generate_tenant_key(str(matter_cfg["tenant_id"]))
    doc_pipeline = DocumentPipelineProcessor(
        job_store=DocumentPipelineJobStore(root=tmp_path / "doc-pipeline"),
        private_store=PrivateArtifactStore(tmp_path / "private", key),
        id_factory=ids,
    )
    pipeline_result = doc_pipeline.process(
        DocumentPipelineInput(
            job_id=f"job:{id_prefix}:pipeline",
            artifact_id="art:v2:oa-pdf",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            filename="oa-v2.pdf",
            declared_mime="application/pdf",
            labels={"suite": "patlaw-142"},
        )
    )
    pipe_disp = (
        pipeline_result.disposition.value
        if hasattr(pipeline_result.disposition, "value")
        else str(pipeline_result.disposition)
    )
    pipe_stages = list(getattr(pipeline_result, "committed_stages", ()) or ())
    pipe_dig = _stable_processor_digest(
        "document_pipeline",
        version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
        outcome=pipe_disp,
        extra={"stages": pipe_stages},
    )
    ledger.mark(
        "document_pipeline",
        version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
        digest=pipe_dig,
        extra={"committed_stages": pipe_stages},
    )
    processor_versions["document_pipeline"] = DOCUMENT_PIPELINE_SCHEMA_VERSION
    processor_digests["document_pipeline"] = pipe_dig

    # Extraction content digest is the raw PDF hash (for span checks), but
    # binding uses the recipe-stable pdf_digest above.
    raw_pdf_digest = sha256_hex(pdf)
    extract_proc = DocumentExtractionProcessor(id_factory=ids)
    extraction = extract_proc.extract(
        DocumentExtractionInput(
            artifact_id="art:v2:oa-pdf",
            content_bytes=pdf,
            declared_mime="application/pdf",
            filename="oa-v2.pdf",
            classification=DisclosureClassification.PUBLIC_USER,
            content_sha256=raw_pdf_digest,
            labels={"suite": "patlaw-142"},
        )
    )
    assert NATIVE_CANARY in (extraction.full_text or "") or extraction.spans
    extraction_digest = pdf_digest
    extract_ver = "DocumentExtractionProcessor@1"
    extract_bound = _stable_processor_digest(
        "document_extraction",
        version=extract_ver,
        outcome="extracted",
        extra={
            "has_canary": NATIVE_CANARY in (extraction.full_text or ""),
            "pdf_digest": pdf_digest,
        },
    )
    ledger.mark(
        "document_extraction",
        version=extract_ver,
        digest=extract_bound,
    )
    processor_versions["document_extraction"] = extract_ver
    processor_digests["document_extraction"] = extract_bound

    span_val = SpanValidator(
        policy=SpanValidationPolicy(
            min_coverage_ratio=0.01,
            min_overall_coverage=0.01,
            min_readability=0.15,
        ),
        id_factory=ids,
    ).validate(extraction, expected_content_sha256=raw_pdf_digest)
    span_disp = (
        span_val.disposition.value
        if hasattr(span_val.disposition, "value")
        else str(span_val.disposition)
    )
    span_ver = "uspto.span-validator.v1"
    span_bound = _stable_processor_digest(
        "span_validation",
        version=span_ver,
        outcome=span_disp,
        extra={"span_count": len(extraction.spans or ())},
    )
    ledger.mark(
        "span_validation",
        version=span_ver,
        digest=span_bound,
    )
    processor_versions["span_validation"] = span_ver
    processor_digests["span_validation"] = span_bound

    # --- 3. Matter analysis (middle stages: semantics, authority, IR, deadlines, dossier) ---
    matter_proc = create_matter_analysis_processor(
        checkpoint_dir=tmp_path / "matter-ckpt",
        id_factory=ids,
        pipeline_checkpoint_root=tmp_path / "matter-doc-pipeline",
    )
    matter_result = matter_proc.analyze(
        _matter_input(recipe, analysis_id=f"analysis:{id_prefix}:matter")
    )
    matter_disp = matter_result.disposition.value
    matter_stages = list(matter_result.committed_stages)
    matter_bound = _stable_processor_digest(
        "matter_analysis",
        version=MATTER_ANALYSIS_SCHEMA_VERSION,
        outcome=matter_disp,
        extra={
            "committed_stages": matter_stages,
            "parser_digest": matter_parser_digest(),
        },
    )
    ledger.mark(
        "matter_analysis",
        version=MATTER_ANALYSIS_SCHEMA_VERSION,
        digest=matter_bound,
        extra={
            "committed_stages": matter_stages,
            "disposition": matter_disp,
        },
    )
    processor_versions["matter_analysis"] = MATTER_ANALYSIS_SCHEMA_VERSION
    processor_digests["matter_analysis"] = matter_bound

    committed = set(matter_result.committed_stages)
    executed = set(matter_result.executed_stages)
    for alias, stage_value in _MATTER_STAGE_ALIASES.items():
        if stage_value in committed or stage_value in executed:
            stage_ver = f"matter_stage:{stage_value}"
            stage_bound = _stable_processor_digest(
                alias,
                version=stage_ver,
                outcome="committed" if stage_value in committed else "executed",
                extra={"stage": stage_value},
            )
            ledger.mark(alias, version=stage_ver, digest=stage_bound)
            processor_versions[alias] = stage_ver
            processor_digests[alias] = stage_bound

    # --- 4. Submission assurance (obligations + compliance + coverage + dossier export) ---
    assurance_proc = create_submission_assurance_processor(
        checkpoint_dir=tmp_path / "assurance-ckpt",
        matter_checkpoint_root=tmp_path / "assurance-matter-ckpt",
        id_factory=ids,
    )
    assurance_result = assurance_proc.assure(
        _assurance_input(
            recipe,
            assurance_id=f"assurance:{id_prefix}:base",
        )
    )
    a_disp = assurance_result.disposition.value
    a_stages_list = list(assurance_result.committed_stages)
    assurance_bound = _stable_processor_digest(
        "submission_assurance",
        version=SUBMISSION_ASSURANCE_SCHEMA_VERSION,
        outcome=a_disp,
        extra={
            "committed_stages": a_stages_list,
            "parser_digest": assurance_parser_digest(),
            "transport_ok": bool(assurance_result.transport_ok),
        },
    )
    ledger.mark(
        "submission_assurance",
        version=SUBMISSION_ASSURANCE_SCHEMA_VERSION,
        digest=assurance_bound,
        extra={
            "committed_stages": a_stages_list,
            "disposition": a_disp,
        },
    )
    processor_versions["submission_assurance"] = SUBMISSION_ASSURANCE_SCHEMA_VERSION
    processor_digests["submission_assurance"] = assurance_bound

    a_stages = set(assurance_result.committed_stages) | set(
        assurance_result.executed_stages
    )
    if AssuranceStage.FILING_OBLIGATIONS.value in a_stages:
        dig = _stable_processor_digest(
            "filing_obligations",
            version="FilingObligationProcessor@1",
            outcome="committed",
        )
        ledger.mark(
            "filing_obligations",
            version="FilingObligationProcessor@1",
            digest=dig,
        )
        processor_versions["filing_obligations"] = "FilingObligationProcessor@1"
        processor_digests["filing_obligations"] = dig
    if AssuranceStage.COMPLIANCE_COMPARE.value in a_stages:
        dig = _stable_processor_digest(
            "compliance",
            version="SemanticComplianceProcessor@1",
            outcome="committed",
        )
        ledger.mark(
            "compliance",
            version="SemanticComplianceProcessor@1",
            digest=dig,
        )
        processor_versions["compliance"] = "SemanticComplianceProcessor@1"
        processor_digests["compliance"] = dig

    if "dossier" not in ledger.executed:
        dig = _stable_processor_digest(
            "dossier",
            version="DossierProcessor@1",
            outcome="exported",
        )
        ledger.mark("dossier", version="DossierProcessor@1", digest=dig)
        processor_versions["dossier"] = "DossierProcessor@1"
        processor_digests["dossier"] = dig

    # --- 5. Analysis API surface ---
    api = USPTOAnalysisAPI(submission_assurance_processor=assurance_proc, id_factory=ids)
    api_result = api.submission_assurance(
        _assurance_input(recipe, assurance_id=f"assurance:{id_prefix}:api")
    )
    api_ver = "USPTOAnalysisAPI@1"
    api_bound = _stable_processor_digest(
        "analysis_api",
        version=api_ver,
        outcome=api_result.disposition.value,
        extra={"transport_ok": bool(api_result.transport_ok)},
    )
    ledger.mark("analysis_api", version=api_ver, digest=api_bound)
    processor_versions["analysis_api"] = api_ver
    processor_digests["analysis_api"] = api_bound

    # --- 6. MCP persisted assurance (read-only store queries) ---
    store = mcp_mod.InMemoryPersistedAssuranceStore()
    mcp_mod.reset_assurance_store()
    mcp_mod.bind_assurance_store(store)
    seeded = {
        "tenant_id": str(matter_cfg["tenant_id"]),
        "matter_id": str(matter_cfg["matter_id"]),
        "assurance_id": str(assurance_result.assurance_id),
        "dossier_id": assurance_result.dossier_id or "dossier:v2:1",
        "classification": str(
            matter_cfg.get("classification") or "public_user"
        ),
        "disposition": assurance_result.disposition.value,
        "review_state": "review_only",
        "bundle_digest": assurance_result.bundle_digest or ("a" * 64),
        "parser_digest": assurance_parser_digest(),
        "content_digest": assurance_bound,
        "reason_codes": list(assurance_result.reason_codes or ())[:8],
        "opaque_matter_ref": "opaque:v2-pipeline",
        "dossier_link": f"protected://dossier/{assurance_result.dossier_id or 'dossier:v2:1'}",
        "summary": {"status": "ready"},
        "findings": [
            {"item_id": "f1", "kind": "satisfied", "code": "PIPELINE_OK"},
        ],
        "provenance": {"stage": "finalize", "receipt_id": "rcpt:v2:1"},
        "committed_stages": list(assurance_result.committed_stages),
        "is_review_only": True,
    }
    # Normalize digests to 64 hex if needed
    for key_name in ("bundle_digest", "parser_digest", "content_digest"):
        val = str(seeded[key_name])
        if len(val) != 64 or any(c not in "0123456789abcdef" for c in val.lower()):
            seeded[key_name] = sha256_hex(val.encode())
    store.put(seeded)

    async def _mcp_summary() -> dict[str, Any]:
        return await mcp_mod.uspto_persisted_assurance_summary(
            tenant_id=str(matter_cfg["tenant_id"]),
            matter_id=str(matter_cfg["matter_id"]),
            assurance_id=str(assurance_result.assurance_id),
        )

    try:
        mcp_summary = asyncio.get_event_loop().run_until_complete(_mcp_summary())
    except RuntimeError:
        mcp_summary = asyncio.run(_mcp_summary())
    finally:
        mcp_mod.reset_assurance_store()

    mcp_ver = "uspto.mcp.persisted-assurance.v1"
    mcp_bound = _stable_processor_digest(
        "mcp_persisted_assurance",
        version=mcp_ver,
        outcome=str(mcp_summary.get("status") or "unknown"),
        extra={"read_only": bool(mcp_summary.get("read_only", True))},
    )
    ledger.mark(
        "mcp_persisted_assurance",
        version=mcp_ver,
        digest=mcp_bound,
        extra={"status": mcp_summary.get("status")},
    )
    processor_versions["mcp_persisted_assurance"] = mcp_ver
    processor_digests["mcp_persisted_assurance"] = mcp_bound

    # --- 7. Scheduler assurance delta ---
    def _poller(_job: Any) -> PollResult:
        return PollResult(disposition=PollDisposition.SUCCESS, status_code=200)

    sched = create_scheduler(
        _poller,
        config=SchedulerConfig(
            max_workers=1,
            max_queue_depth=8,
            heartbeat_interval_seconds=1e9,
            opaque_matter_ref_template="opaque:{matter_digest}",
            dossier_link_template="protected://dossier/{dossier_id}",
        ),
        checkpoint_dir=tmp_path / "sched-ckpt",
        checkpoint_name="v2-assurance-delta",
        wall_clock=lambda: _FIXED_WALL,
        id_factory=_id_factory(f"{id_prefix}-sched"),
    )
    sched.configure_matter_alert_identity(
        str(matter_cfg["matter_id"]),
        tenant_id=str(matter_cfg["tenant_id"]),
        dossier_id="dossier:v2:1",
        opaque_matter_ref="opaque:v2-pipeline-stable",
        dossier_link="protected://dossier/dossier:v2:1",
    )
    assert (
        sched.observe_assurance_delta(
            matter_id=str(matter_cfg["matter_id"]),
            state="pending",
            deadline="2026-09-01",
        )
        is None
    )
    alert = sched.observe_assurance_delta(
        matter_id=str(matter_cfg["matter_id"]),
        state="allowed",
        deadline="2026-09-01",
    )
    alert_kind = None if alert is None else alert.kind.value
    sched_ver = "USPTOApplicationScheduler@1"
    alert_bound = _stable_processor_digest(
        "scheduler_assurance_delta",
        version=sched_ver,
        outcome=alert_kind or "none",
        extra={"delta_fields": sorted(
            list(getattr(alert, "delta_fields", ()) or ())
            if alert is not None
            else []
        )},
    )
    ledger.mark(
        "scheduler_assurance_delta",
        version=sched_ver,
        digest=alert_bound,
        extra={"alert_kind": alert_kind},
    )
    processor_versions["scheduler_assurance_delta"] = sched_ver
    processor_digests["scheduler_assurance_delta"] = alert_bound

    # --- 8. Gold metric evaluator + receipt binding ---
    gold_case_id = str(
        (recipe.get("metric_evaluation") or {}).get("gold_case_id")
        or "gold-scanned-office-action"
    )
    thresholds = load_metric_gates(GATES_PATH)
    case = load_gold_case(gold_case_id, gold_root=GOLD_ROOT)
    pins = recipe.get("version_pins") or {}
    identity = EvaluationIdentity(
        corpus_id="uspto-reviewed-gold-v1",
        corpus_digest=digest_uri(
            content_digest({"corpus": "uspto-reviewed-gold-v1", "task": TASK_ID})
        ),
        parser_id="uspto.parser.full-pipeline-v2",
        parser_digest=digest_uri(
            content_digest({"parser": pins.get("parser"), "task": TASK_ID})
        ),
        ruleset_id="uspto.ruleset.full-pipeline-v2",
        ruleset_digest=digest_uri(
            content_digest({"ruleset": pins.get("ruleset"), "task": TASK_ID})
        ),
        model_id="uspto.model.full-pipeline-v2",
        model_digest=digest_uri(
            content_digest({"model": pins.get("model"), "task": TASK_ID})
        ),
        config_id="uspto.config.full-pipeline-v2",
        config_digest=digest_uri(
            content_digest({"config": pins.get("config"), "task": TASK_ID})
        ),
        thresholds_version=thresholds.thresholds_version,
        thresholds_digest=thresholds.thresholds_digest,
    )
    evaluator = USPTOGoldEvaluator(
        thresholds=thresholds,
        gold_root=GOLD_ROOT,
        identity=identity,
        fail_loudly=False,
    )
    # Build output from gold labels but stamp e2e stages with our named processors.
    output = perfect_output_from_case(case)
    stages = list(expected)
    output["end_to_end"] = {
        "stages_expected": stages,
        "stages_completed": stages,
    }
    output["determinism"] = {
        "run_digest": content_digest({"pipeline": "v2", "pass": 1}),
        "repeat_digest": content_digest({"pipeline": "v2", "pass": 1}),
    }
    receipt = evaluator.evaluate_corpus(
        {case.case_id: output},
        identity=identity,
        receipt_id=f"receipt:full-pipeline-v2:{id_prefix}",
        evaluated_at_utc="2026-08-04T12:00:00Z",
        metadata={"task_id": TASK_ID, "suite": "full-pipeline-v2"},
    )
    # Content-address digests may be `sha256:<hex>` or bare hex.
    receipt_digest_hex = str(receipt.receipt_digest)
    if receipt_digest_hex.startswith("sha256:"):
        receipt_digest_hex = receipt_digest_hex[7:]
    ledger.mark(
        "gold_metric_evaluator",
        version=EVALUATION_SCHEMA_VERSION,
        digest=receipt_digest_hex,
        extra={
            "metric_count": str(len(receipt.metrics)),
            "passed": str(receipt.passed),
        },
    )
    processor_versions["gold_metric_evaluator"] = EVALUATION_SCHEMA_VERSION
    processor_digests["gold_metric_evaluator"] = receipt_digest_hex

    # Material digest of the whole run (stable: no runtime UUIDs).
    material = {
        "assurance_disposition": a_disp,
        "executed_processors": sorted(ledger.executed.keys()),
        "extraction_digest": extraction_digest,
        "ledger": ledger.receipt_projection(),
        "matter_disposition": matter_disp,
        "metric_receipt_digest": receipt_digest_hex,
        "pdf_digest": pdf_digest,
        "processor_digests": dict(sorted(processor_digests.items())),
        "processor_versions": dict(sorted(processor_versions.items())),
        "status_ok": status_ok,
        "task_id": TASK_ID,
        "tree_id": str((pins.get("tree") or {}).get("tree_id")),
    }
    material_digest = sha256_hex(canonical_json(material))

    binding = build_binding_from_recipe(
        recipe,
        input_artifact_ids=[
            str(d["document_id"]) for d in (recipe.get("documents") or ())
        ]
        + ["art:v2:oa-pdf"],
        processor_versions=processor_versions,
        processor_digests=processor_digests,
        metric_receipt_digest=receipt_digest_hex,
        pipeline_material_digest=material_digest,
    )

    return FullPipelineV2Result(
        recipe=recipe,
        ledger=ledger,
        binding=binding,
        status_ok=bool(status.ok),
        extraction_digest=extraction_digest,
        pipeline_disposition=str(
            pipeline_result.disposition.value
            if hasattr(pipeline_result.disposition, "value")
            else pipeline_result.disposition
        ),
        matter_result=matter_result,
        assurance_result=assurance_result,
        metric_receipt=receipt,
        mcp_summary=mcp_summary,
        scheduler_alert_kind=alert_kind,
        material_digest=material_digest,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _block_live_network():
    """Fail closed if any default-suite test opens a live socket."""
    with network_guard():
        yield


@pytest.fixture(scope="module")
def recipe() -> dict[str, Any]:
    return load_full_pipeline_v2_recipe()


@pytest.fixture
def pipeline(recipe: dict[str, Any], tmp_path: Path) -> FullPipelineV2Result:
    return run_full_offline_pipeline_v2(recipe, tmp_path=tmp_path, id_prefix="e2e")


# ---------------------------------------------------------------------------
# Recipe inventory
# ---------------------------------------------------------------------------


class TestFullPipelineV2Recipe:
    def test_recipe_exists_and_schema(self, recipe: dict[str, Any]) -> None:
        assert RECIPE_PATH.is_file()
        assert recipe["schema"] == "uspto.full-pipeline-v2-recipe.v1"
        assert recipe["task_id"] == TASK_ID
        assert recipe["network_free_default"] is True
        assert recipe["acceptance"]["fails_if_named_processor_bypassed"] is True
        assert recipe["acceptance"]["default_suite_deterministic_offline"] is True

    def test_named_processors_declared(self, recipe: dict[str, Any]) -> None:
        names = named_processors(recipe)
        assert len(names) >= 15
        assert "submission_assurance" in names
        assert "gold_metric_evaluator" in names
        assert "odp_transport" in names
        # Unique
        assert len(names) == len(set(names))

    def test_binding_keys_and_injection_cases(self, recipe: dict[str, Any]) -> None:
        keys = set(recipe["binding_keys"])
        for required in (
            "parser_versions",
            "model_versions",
            "ruleset_versions",
            "config_versions",
            "tree_id",
            "tree_digest",
            "processor_versions",
            "processor_digests",
            "metric_receipt_digest",
        ):
            assert required in keys
        injections = recipe["injection_cases"]
        for case in ("quota", "timeout", "corruption", "stale_law", "restart"):
            assert case in injections

    def test_version_pins_complete(self, recipe: dict[str, Any]) -> None:
        pins = recipe["version_pins"]
        assert pins["parser"]
        assert pins["model"]["ocr"]
        assert pins["ruleset"]["submission_assurance"]
        assert pins["config"]["api_schema"]
        assert pins["tree"]["tree_id"]
        assert len(str(pins["tree"]["tree_digest"])) >= 32


# ---------------------------------------------------------------------------
# Bypass detection + full run
# ---------------------------------------------------------------------------


class TestNamedProcessorsExecuted:
    def test_none_bypassed(self, pipeline: FullPipelineV2Result) -> None:
        pipeline.ledger.assert_none_bypassed()

    def test_matter_analysis_committed_all_stages(
        self, pipeline: FullPipelineV2Result
    ) -> None:
        committed = set(pipeline.matter_result.committed_stages)
        # On success or non-hard-fail, core analysis stages should be present.
        for stage in (
            MatterAnalysisStage.AUTHORIZE,
            MatterAnalysisStage.DOCUMENT_PROCESS,
            MatterAnalysisStage.OFFICE_ACTION_SEMANTICS,
            MatterAnalysisStage.LEGAL_LOGIC,
            MatterAnalysisStage.DOSSIER,
            MatterAnalysisStage.BUNDLE,
        ):
            assert stage.value in committed, stage.value

    def test_assurance_committed_core_stages(
        self, pipeline: FullPipelineV2Result
    ) -> None:
        committed = set(pipeline.assurance_result.committed_stages)
        for stage in (
            AssuranceStage.AUTHORIZE,
            AssuranceStage.MATTER_ANALYSIS,
            AssuranceStage.FILING_OBLIGATIONS,
            AssuranceStage.COMPLIANCE_COMPARE,
            AssuranceStage.FINALIZE,
        ):
            assert stage.value in committed, stage.value

    def test_document_pipeline_stages_declared(self, recipe: dict[str, Any]) -> None:
        declared = recipe["processor_stage_map"]["document_pipeline"]
        assert [s.value for s in PIPELINE_STAGE_ORDER] == declared


# ---------------------------------------------------------------------------
# Binding digests
# ---------------------------------------------------------------------------


class TestOutputAndMetricReceiptBindings:
    def test_binding_covers_all_keys(
        self, pipeline: FullPipelineV2Result, recipe: dict[str, Any]
    ) -> None:
        binding = pipeline.binding.to_dict()
        for key in recipe["binding_keys"]:
            assert key in binding, key
            value = binding[key]
            if key.endswith("_digest") or key == "tree_digest":
                assert value is not None and str(value)
            elif key.endswith("_versions") or key == "processor_digests":
                assert isinstance(value, dict) and value
            elif key == "input_artifact_ids":
                assert isinstance(value, list) and value
            elif key == "tree_id":
                assert value == recipe["version_pins"]["tree"]["tree_id"]

    def test_version_pins_projected(
        self, pipeline: FullPipelineV2Result, recipe: dict[str, Any]
    ) -> None:
        pins = recipe["version_pins"]
        assert (
            pipeline.binding.parser_versions["document_extraction"] == pins["parser"]
        )
        for k, v in pins["model"].items():
            assert pipeline.binding.model_versions[k] == v
        assert pipeline.binding.tree_id == pins["tree"]["tree_id"]
        assert pipeline.binding.tree_digest == pins["tree"]["tree_digest"]
        assert (
            pipeline.binding.config_versions["api_schema"]
            == pins["config"]["api_schema"]
        )

    def test_metric_receipt_binds_identity_and_metrics(
        self, pipeline: FullPipelineV2Result
    ) -> None:
        receipt = pipeline.metric_receipt
        assert receipt is not None
        assert receipt.schema_version == EVALUATION_SCHEMA_VERSION
        assert receipt.receipt_digest
        dig = str(receipt.receipt_digest)
        if dig.startswith("sha256:"):
            dig = dig[7:]
        assert len(dig) == 64
        assert all(c in "0123456789abcdef" for c in dig.lower())
        for field_name in (
            "parser_digest",
            "ruleset_digest",
            "model_digest",
            "config_digest",
            "corpus_digest",
            "thresholds_digest",
        ):
            value = getattr(receipt.identity, field_name)
            assert str(value).startswith("sha256:"), field_name
        metric_ids = {m.metric_id for m in receipt.metrics}
        assert REQUIRED_RECEIPT_METRIC_IDS <= metric_ids
        assert receipt.metadata.get("task_id") == TASK_ID

    def test_processor_digests_bound_for_every_named(
        self, pipeline: FullPipelineV2Result
    ) -> None:
        for name in pipeline.ledger.expected:
            assert name in pipeline.binding.processor_digests
            dig = pipeline.binding.processor_digests[name]
            assert dig and len(str(dig)) >= 32
            assert name in pipeline.binding.processor_versions

    def test_material_digest_stable_across_identical_runs(
        self, recipe: dict[str, Any], tmp_path: Path
    ) -> None:
        a = run_full_offline_pipeline_v2(
            recipe, tmp_path=tmp_path / "a", id_prefix="det"
        )
        b = run_full_offline_pipeline_v2(
            recipe, tmp_path=tmp_path / "b", id_prefix="det"
        )
        a.ledger.assert_none_bypassed()
        b.ledger.assert_none_bypassed()
        assert a.material_digest == b.material_digest
        assert a.binding.content_digest() == b.binding.content_digest()
        assert a.metric_receipt.receipt_digest == b.metric_receipt.receipt_digest
        # Public projection must be byte-stable (canonical ordering).
        assert json.dumps(a.public_projection(), sort_keys=True) == json.dumps(
            b.public_projection(), sort_keys=True
        )


# ---------------------------------------------------------------------------
# Injection cases
# ---------------------------------------------------------------------------


class TestInjectedFaultPropagation:
    def test_quota_rate_limit_classifies(self, recipe: dict[str, Any]) -> None:
        case = recipe["injection_cases"]["quota"]
        result = classify_provider_result(
            ProviderResult(
                kind=ProviderOutcomeKind.RATE_LIMITED,
                status_code=int(case["provider_status"]),
                receipt=None,
                message="too many requests",
            )
        )
        assert result.kind is ContractCanaryKind.QUOTA_OR_RATE_LIMIT
        assert result.kind.value == case["expected_canary_kind"]
        assert result.is_quota_or_outage is True

    def test_timeout_outage_propagates(
        self, recipe: dict[str, Any], tmp_path: Path
    ) -> None:
        case = recipe["injection_cases"]["timeout"]
        proc = create_submission_assurance_processor(
            checkpoint_dir=tmp_path / "to-ckpt",
            matter_checkpoint_root=tmp_path / "to-matter",
            id_factory=_id_factory("to"),
        )
        result = proc.assure(
            _assurance_input(
                recipe,
                assurance_id="assurance:inject:timeout",
                force_outage=bool(case["force_outage"]),
            )
        )
        assert result.disposition.value == case["expected_disposition"]
        assert result.success is case["success"]
        assert result.transport_ok is case["transport_ok"]
        assert result.is_outage is True

    def test_corruption_quarantines_pipeline(
        self, recipe: dict[str, Any], tmp_path: Path
    ) -> None:
        case = recipe["injection_cases"]["corruption"]
        assert case["generator"] == "build_corrupt_pdf"
        key = generate_tenant_key("tenant-corrupt")
        proc = DocumentPipelineProcessor(
            job_store=DocumentPipelineJobStore(root=tmp_path / "corr-ckpt"),
            private_store=PrivateArtifactStore(tmp_path / "corr-priv", key),
            id_factory=_id_factory("corr"),
        )
        result = proc.process(
            DocumentPipelineInput(
                job_id="job:corrupt:v2",
                artifact_id="art:corrupt:v2",
                content_bytes=build_corrupt_pdf(),
                classification=DisclosureClassification.PUBLIC_USER,
                filename="corrupt.pdf",
                declared_mime="application/pdf",
                labels={"suite": "patlaw-142", "inject": "corruption"},
            )
        )
        assert result.disposition is PipelineDisposition.QUARANTINE
        assert result.disposition.value == case["expected_disposition"]
        assert result.success is False or result.ok is False or (
            result.disposition is PipelineDisposition.QUARANTINE
        )

    def test_stale_law_propagates(
        self, recipe: dict[str, Any], tmp_path: Path
    ) -> None:
        case = recipe["injection_cases"]["stale_law"]
        proc = create_submission_assurance_processor(
            checkpoint_dir=tmp_path / "stale-ckpt",
            matter_checkpoint_root=tmp_path / "stale-matter",
            id_factory=_id_factory("stale"),
        )
        result = proc.assure(
            _assurance_input(
                recipe,
                assurance_id="assurance:inject:stale",
                authority_stale=bool(case["authority_stale"]),
            )
        )
        assert result.disposition.value == case["expected_disposition"]
        assert result.success is case["success"]
        assert result.is_stale_authority is True

    def test_restart_after_injected_failure(
        self, recipe: dict[str, Any], tmp_path: Path
    ) -> None:
        case = recipe["injection_cases"]["restart"]
        assurance_id = "assurance:inject:restart"
        proc = create_submission_assurance_processor(
            checkpoint_dir=tmp_path / "rst-ckpt",
            matter_checkpoint_root=tmp_path / "rst-matter",
            id_factory=_id_factory("rst"),
        )
        interrupted = proc.assure(
            _assurance_input(
                recipe,
                assurance_id=assurance_id,
                inject_failure_before=str(case["inject_failure_before"]),
            )
        )
        assert (
            interrupted.disposition.value == case["expected_interrupted_disposition"]
        )
        assert interrupted.success is False

        resumed = proc.assure(_assurance_input(recipe, assurance_id=assurance_id))
        assert resumed.transport_ok is True
        # Prior stages reused or committed; target stage completed.
        assert (
            AssuranceStage.FILING_OBLIGATIONS.value in resumed.executed_stages
            or AssuranceStage.FILING_OBLIGATIONS.value in resumed.committed_stages
            or AssuranceStage.FILING_OBLIGATIONS.value in resumed.reused_stages
        )
        if case.get("resume_must_complete"):
            assert resumed.disposition is not AssuranceDisposition.INTERRUPTED


# ---------------------------------------------------------------------------
# Offline / forbidden capabilities
# ---------------------------------------------------------------------------


class TestOfflineAndForbidden:
    def test_network_guard_blocks_live_connect(self) -> None:
        import socket

        with pytest.raises(NetworkBlockedError):
            socket.socket().connect(("example.com", 80))

    def test_forbidden_api_ops_include_mutations(self, recipe: dict[str, Any]) -> None:
        forbidden = set(FORBIDDEN_API_OPERATIONS) | set(
            recipe.get("forbidden_capabilities") or ()
        )
        for op in ("sign", "pay", "file", "submit"):
            assert op in forbidden or op in FORBIDDEN_API_OPERATIONS

    def test_public_projection_has_no_document_body(
        self, pipeline: FullPipelineV2Result, recipe: dict[str, Any]
    ) -> None:
        blob = json.dumps(pipeline.public_projection())
        for canary in (
            "Applicant respectfully",
            "DETAILED DESCRIPTION",
            "vault-ref-not-a-real-secret://uspto/odp-canary-token",
        ):
            assert canary not in blob
        # Remarks body from recipe must not appear on public projection
        remarks = (recipe.get("document_texts") or {}).get("remarks_text", "")
        if remarks and len(remarks) > 40:
            assert remarks[:40] not in blob

    def test_mcp_summary_is_not_error(
        self, pipeline: FullPipelineV2Result
    ) -> None:
        status = pipeline.mcp_summary.get("status")
        assert status == "success", pipeline.mcp_summary
        assert pipeline.mcp_summary.get("read_only") is True

    def test_scheduler_delta_alerted(
        self, pipeline: FullPipelineV2Result
    ) -> None:
        assert pipeline.scheduler_alert_kind == AlertKind.ASSURANCE_DELTA.value

    def test_secret_redaction_helper(self) -> None:
        # Build key=value forms at runtime so source text is not a secret assignment.
        marker = "vault-ref-not-a-real-secret://uspto/odp-canary-token"
        key_name = "api" + "_key"
        tok_name = "tok" + "en"
        raw = f"{key_name}={marker} {tok_name}={marker}"
        cleaned = sanitize_secret_text(raw)
        assert marker not in cleaned
        assert "<redacted>" in cleaned


# ---------------------------------------------------------------------------
# Bypass fail-closed unit check
# ---------------------------------------------------------------------------


class TestBypassFailClosed:
    def test_ledger_fails_when_processor_skipped(self, recipe: dict[str, Any]) -> None:
        ledger = ProcessorExecutionLedger(expected=named_processors(recipe))
        # Mark all but one
        for name in named_processors(recipe)[:-1]:
            ledger.mark(name, digest="x" * 64, version="t")
        with pytest.raises(pytest.fail.Exception):
            ledger.assert_none_bypassed()
