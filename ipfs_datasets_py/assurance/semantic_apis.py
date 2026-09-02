"""Fail-closed PCPR-014 semantic API and ContextPack contract stabilization.

Publish stable versioned APIs for canonical IR identity, source lineage,
ContextPack construction, proof obligations, proof-result validation,
translation receipts, interpolation, CEGAR, incremental SMT, and source and
rights manifests. Free-form input cannot mint executable work. Advisory
material has no authority. Compatibility is explicit and fail-closed. Bounds
and identities are deterministic.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Live claims require
live evidence. Simulated results are not live. Missing solvers stay typed
unavailable.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

INTERFACE: Final = "DatasetsSemanticApiCatalog@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/semantic-api-catalog@1"
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/semantic-api-catalog-verdict@1"
)
PCPR_014_TASK_ID: Final = "PCPR-014"
PCPR_014_GOAL_ID: Final = "PCPR-G220"
PCPR_013_TASK_ID: Final = "PCPR-013"
PCPR_003_TASK_ID: Final = "PCPR-003"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = "proof-carrying-platform-qualification-and-release-v1"
EVIDENCE_ID: Final = "pcpr/datasets-semantic-api-catalog@1"

CONTEXT_PACK_INTERFACE: Final = "DatasetsContextPack@1"
CONTEXT_PACK_SCHEMA: Final = "ipfs_datasets_py/datasets-context-pack@1"
CONTEXT_PACK_V01_INTERFACE: Final = "DatasetsContextPackAuthority@0.1"
CANONICAL_IR_IDENTITY_INTERFACE: Final = "CanonicalIRIdentity@1"
PGIR_SEMANTIC_API_INTERFACE: Final = "SemanticPublicAPI@1"
PGIR_SEMANTIC_API_MATURITY: Final = "compatibility_only"

CLOSED_RELEASE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "release_candidate_qualified",
        "non_promoted_supervisor_unqualified",
        "non_promoted_import_or_false_success",
        "non_promoted_live_storage_gap",
        "non_promoted_live_compute_gap",
        "non_promoted_solver_gap",
        "non_promoted_packaging_gap",
        "non_promoted_dependency_reproducibility",
        "non_promoted_security_failure",
        "non_promoted_interoperability_gap",
        "non_promoted_reference_workflow_failure",
        "non_promoted_unmeasured",
        "non_promoted_operator_gate_required",
    }
)
PROMOTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "supervisor_promoted",
        "supervisor_non_promoted",
        "rnd_non_promoted",
        "typed_unavailable",
        "typed_blocked",
    }
)
EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "measured",
        "measured_live",
        "measured_hermetic",
        "estimated",
        "simulated",
        "unavailable",
    }
)
SURFACE_MATURITIES: Final[frozenset[str]] = frozenset(
    {
        "beta",
        "compatibility_only",
        "experimental",
        "simulation_only",
        "stable",
        "unavailable",
    }
)

IDENTITY_RELPATH: Final = "ipfs_datasets_py/logic/ir_core/identity.py"
LINEAGE_RELPATH: Final = "ipfs_datasets_py/logic/ir_core/source_lineage.py"
CLAIMS_RELPATH: Final = "ipfs_datasets_py/logic/ir_core/claims.py"
PROTOCOLS_RELPATH: Final = "ipfs_datasets_py/logic/ir_core/protocols.py"
RECEIPTS_RELPATH: Final = (
    "ipfs_datasets_py/logic/software_verification/receipts.py"
)
INTERPOLATION_RELPATH: Final = (
    "ipfs_datasets_py/logic/backends/smt/interpolation.py"
)
CEGAR_RELPATH: Final = "ipfs_datasets_py/logic/software_verification/cegar.py"
INCREMENTAL_RELPATH: Final = "ipfs_datasets_py/logic/backends/smt/incremental.py"
CONTEXT_PACK_RELPATH: Final = "ipfs_datasets_py/proof_context/context_pack.py"
CORPUS_RELPATH: Final = "ipfs_datasets_py/huggingface/corpus.py"
MANIFEST_RELPATH: Final = "ipfs_datasets_py/logic/platform/manifest.py"
PGIR_CATALOG_RELPATH: Final = "ipfs_datasets_py/logic/semantic/catalog.py"

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_014_semantic_apis.py",
)

SEALED_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
SEALED_PYTHON: Final = "/usr/bin/python3.12"


@dataclass(frozen=True, slots=True)
class SemanticApiSpec:
    """One PCPR-stable Datasets semantic API and its canonical owner."""

    name: str
    interface: str
    schema: str
    owner_module: str
    owner_symbol: str
    executable: bool
    requires_bounds: bool
    maturity: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "executable": self.executable,
            "interface": self.interface,
            "maturity": self.maturity,
            "name": self.name,
            "owner_module": self.owner_module,
            "owner_symbol": self.owner_symbol,
            "requires_bounds": self.requires_bounds,
            "schema": self.schema,
        }


SEMANTIC_API_SPECS: Final[tuple[SemanticApiSpec, ...]] = (
    SemanticApiSpec(
        name="canonical_ir_identity",
        interface=CANONICAL_IR_IDENTITY_INTERFACE,
        schema="ir-canonical-identity-v1",
        owner_module="ipfs_datasets_py.logic.ir_core.identity",
        owner_symbol="canonical_identity",
        executable=False,
        requires_bounds=False,
        maturity="stable",
        description="Deterministic CIDv1 identity over canonical IR JSON.",
    ),
    SemanticApiSpec(
        name="source_lineage",
        interface="SourceLineage@1",
        schema="ir-lineage-graph/v1",
        owner_module="ipfs_datasets_py.logic.ir_core.source_lineage",
        owner_symbol="SourceRelease.from_dict",
        executable=False,
        requires_bounds=False,
        maturity="stable",
        description="Versioned source, derivative, and lineage records. Unknown keys fail closed.",
    ),
    SemanticApiSpec(
        name="context_pack",
        interface=CONTEXT_PACK_INTERFACE,
        schema=CONTEXT_PACK_SCHEMA,
        owner_module="ipfs_datasets_py.proof_context.context_pack",
        owner_symbol="admit_datasets_context_pack",
        executable=False,
        requires_bounds=False,
        maturity="stable",
        description="Datasets-owned ContextPack@1 identity. v0.1 is compatibility-only.",
    ),
    SemanticApiSpec(
        name="proof_obligation",
        interface="ProofObligation@1",
        schema="ir-proof-obligation/v1",
        owner_module="ipfs_datasets_py.logic.ir_core.claims",
        owner_symbol="ProofObligation.from_dict",
        executable=False,
        requires_bounds=False,
        maturity="stable",
        description="Theorem-shaped obligation declaration with no implied verification.",
    ),
    SemanticApiSpec(
        name="proof_result_validation",
        interface="ProofResult@1",
        schema="bounded-result/v1",
        owner_module="ipfs_datasets_py.logic.ir_core.protocols",
        owner_symbol="ProofResult.from_dict",
        executable=False,
        requires_bounds=True,
        maturity="stable",
        description="Validate a bounded proof result. Free-form cannot mint theorem authority.",
    ),
    SemanticApiSpec(
        name="translation_receipt",
        interface="LogicTranslationReceipt@1",
        schema="logic-translation-receipt/v1",
        owner_module="ipfs_datasets_py.logic.software_verification.receipts",
        owner_symbol="require_current_translation_receipt",
        executable=False,
        requires_bounds=False,
        maturity="stable",
        description="Current translation receipts only. Missing or stale receipts have no authority.",
    ),
    SemanticApiSpec(
        name="interpolation",
        interface="ValidatedCraigInterpolation@1",
        schema="validated-craig-interpolant/v1",
        owner_module="ipfs_datasets_py.logic.backends.smt.interpolation",
        owner_symbol="InterpolationBounds",
        executable=True,
        requires_bounds=True,
        maturity="experimental",
        description="Admit interpolation requests with positive finite bounds. Live cvc5/z3 stay typed unavailable here.",
    ),
    SemanticApiSpec(
        name="cegar",
        interface="BoundedInterpolationCegar@1",
        schema="bounded-interpolation-cegar-receipt/v1",
        owner_module="ipfs_datasets_py.logic.software_verification.cegar",
        owner_symbol="CegarBudget",
        executable=True,
        requires_bounds=True,
        maturity="experimental",
        description="Admit CEGAR requests with a positive finite budget. Live solvers stay typed unavailable here.",
    ),
    SemanticApiSpec(
        name="incremental_smt",
        interface="IncrementalSmtSession@1",
        schema="incremental-smt-session/v1",
        owner_module="ipfs_datasets_py.logic.backends.smt.incremental",
        owner_symbol="IncrementalSmtFingerprint",
        executable=True,
        requires_bounds=True,
        maturity="experimental",
        description="Admit incremental SMT fingerprints with positive timeout and memory. Sessions are not opened here.",
    ),
    SemanticApiSpec(
        name="source_rights_manifest",
        interface="SourceRightsManifest@1",
        schema="ir-corpus-rights-manifest/v1",
        owner_module="ipfs_datasets_py.logic.ir_core.source_lineage",
        owner_symbol="RightsRecord.from_dict",
        executable=False,
        requires_bounds=False,
        maturity="stable",
        description="Source and transformation rights. Admitted+unresolved fails closed.",
    ),
)
SEMANTIC_API_NAMES: Final[tuple[str, ...]] = tuple(
    spec.name for spec in SEMANTIC_API_SPECS
)
_SPECS_BY_NAME: Final[Mapping[str, SemanticApiSpec]] = MappingProxyType(
    {spec.name: spec for spec in SEMANTIC_API_SPECS}
)

REQUIRED_GOOD_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "canonical_ir_identity_profile",
        "source_lineage_schemas",
        "context_pack_canonical_interface",
        "context_pack_v01_compatibility_only",
        "proof_obligation_schema",
        "proof_result_class",
        "translation_receipt_interface",
        "interpolation_interface",
        "cegar_interface",
        "incremental_smt_interface",
        "source_rights_record",
        "manifest_advertises_context_pack",
        "catalog_closed",
        "identity_deterministic",
        "context_pack_identity_deterministic",
        "pgir_semantic_api_not_canonical",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "freeform_context_pack_admitted",
        "freeform_proof_result_admitted",
        "freeform_translation_receipt_admitted",
        "advisory_context_pack_admitted",
        "executable_interpolation_missing_bounds_admitted",
        "executable_cegar_missing_bounds_admitted",
        "executable_incremental_smt_missing_bounds_admitted",
        "admitted_unresolved_rights",
        "runtime_unavailable_represented_as_live",
    }
)


class SemanticApiCanonicalError(Exception):
    """Fail-closed PCPR-014 contract error."""


class SemanticApiAdmissionError(SemanticApiCanonicalError):
    """Raised when a semantic request is free-form, advisory, or unbounded."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def content_identity(value: Any) -> str:
    """CIDv1 DAG-JSON/sha2-256 identity (baguqeera…)."""

    digest = hashlib.sha256(canonical_json_bytes(value)).digest()
    raw = b"\x01\xa9\x02\x12\x20" + digest
    return "b" + base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def discover_datasets_root(start: Path | None = None) -> Path | None:
    here = Path(start or __file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "ipfs_datasets_py").is_dir() and (
            candidate / "pyproject.toml"
        ).is_file():
            return candidate
    return None


def semantic_api_spec(name: str) -> SemanticApiSpec:
    try:
        return _SPECS_BY_NAME[name]
    except KeyError as exc:
        raise KeyError(
            f"unknown semantic operation {name!r}; known operations are "
            f"{list(SEMANTIC_API_NAMES)}"
        ) from exc


def semantic_api_manifest() -> dict[str, Any]:
    return {
        "import_side_effects": "none",
        "interface": INTERFACE,
        "operation_names": list(SEMANTIC_API_NAMES),
        "operations": [spec.to_dict() for spec in SEMANTIC_API_SPECS],
        "pgir_semantic_api_interface": PGIR_SEMANTIC_API_INTERFACE,
        "pgir_semantic_api_maturity": PGIR_SEMANTIC_API_MATURITY,
        "schema": SCHEMA,
        "task_id": PCPR_014_TASK_ID,
        "v01_context_pack_interface": CONTEXT_PACK_V01_INTERFACE,
        "v01_context_pack_maturity": "compatibility_only",
    }


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticApiCanonicalError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise SemanticApiCanonicalError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise SemanticApiCanonicalError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _read_source(root: Path, relpath: str) -> str | None:
    path = root / relpath
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _assign_str_constant(source: str, name: str) -> str | None:
    tree = ast.parse(source)
    for node in tree.body:
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        if isinstance(value, ast.Name) and value.id == "INTERFACE":
            return _assign_str_constant(source, "INTERFACE")
    return None


def _assign_bool_constant(source: str, name: str) -> bool | None:
    tree = ast.parse(source)
    for node in tree.body:
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, bool):
            return value.value
    return None


def _has_class(source: str, name: str) -> bool:
    tree = ast.parse(source)
    return any(isinstance(node, ast.ClassDef) and node.name == name for node in tree.body)


@dataclass(frozen=True)
class OutcomeProbe:
    probe_id: str
    present: bool | None
    evidence_kind: str
    live: bool
    simulated_represented_as_live: bool
    reason: str
    details: Mapping[str, Any] = MappingProxyType({})

    def to_mapping(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "present": self.present,
            "evidence_kind": self.evidence_kind,
            "live": self.live,
            "simulated_represented_as_live": self.simulated_represented_as_live,
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class SemanticAdmission:
    operation: str
    interface: str
    schema: str
    executable: bool
    advisory: bool
    live: bool
    identity_cid: str | None
    reason: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "advisory": self.advisory,
            "executable": self.executable,
            "identity_cid": self.identity_cid,
            "interface": self.interface,
            "live": self.live,
            "operation": self.operation,
            "reason": self.reason,
            "schema": self.schema,
        }


@dataclass(frozen=True)
class SemanticApiVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    semantic_apis_canonical: bool
    context_pack_canonical: bool
    simulated_results_represented_as_live: bool
    live_solver_qualified: bool
    live_solver_evidence_kind: str
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "semantic_apis_canonical": self.semantic_apis_canonical,
            "context_pack_canonical": self.context_pack_canonical,
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
            "live_solver_qualified": self.live_solver_qualified,
            "live_solver_evidence_kind": self.live_solver_evidence_kind,
            "this_task_created_competing_authority": (
                self.this_task_created_competing_authority
            ),
            "blocker_count": len(self.blockers),
            "blockers": list(self.blockers),
            "evidence_kind": "measured",
        }


def _unavailable_file_probe(probe_id: str, relpath: str) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=None,
        evidence_kind="unavailable",
        live=False,
        simulated_represented_as_live=False,
        reason=f"{relpath} is missing and is not recorded as empty.",
        details={"relpath": relpath},
    )


def _static_flag_probe(
    *,
    probe_id: str,
    present: bool,
    relpath: str,
    reason_present: str,
    reason_absent: str,
    extra: Mapping[str, Any] | None = None,
) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=present,
        evidence_kind="measured",
        live=False,
        simulated_represented_as_live=False,
        reason=reason_present if present else reason_absent,
        details={"relpath": relpath, **dict(extra or {})},
    )


def current_head_static_probes(
    *,
    datasets_root: Path | None = None,
) -> tuple[OutcomeProbe, ...]:
    """Measured current-tree AST/source probes. Missing files stay typed unavailable."""

    root = datasets_root or discover_datasets_root()
    if root is None or not root.is_dir():
        return (
            OutcomeProbe(
                probe_id="datasets_source_tree",
                present=None,
                evidence_kind="unavailable",
                live=False,
                simulated_represented_as_live=False,
                reason=(
                    "Datasets source tree is not present and is not recorded as empty."
                ),
            ),
        )

    probes: list[OutcomeProbe] = []

    identity_source = _read_source(root, IDENTITY_RELPATH)
    if identity_source is None:
        probes.append(_unavailable_file_probe("canonical_ir_identity_profile", IDENTITY_RELPATH))
    else:
        profile = _assign_str_constant(identity_source, "IDENTITY_PROFILE_NAME")
        probes.append(
            _static_flag_probe(
                probe_id="canonical_ir_identity_profile",
                present=profile == "ir-canonical-identity-v1",
                relpath=IDENTITY_RELPATH,
                reason_present="Canonical IR identity profile is ir-canonical-identity-v1.",
                reason_absent="Canonical IR identity profile is missing or drifted.",
                extra={"profile": profile},
            )
        )

    lineage_source = _read_source(root, LINEAGE_RELPATH)
    if lineage_source is None:
        probes.append(_unavailable_file_probe("source_lineage_schemas", LINEAGE_RELPATH))
        probes.append(_unavailable_file_probe("source_rights_record", LINEAGE_RELPATH))
    else:
        probes.append(
            _static_flag_probe(
                probe_id="source_lineage_schemas",
                present=(
                    'SOURCE_RECORD_SCHEMA: Final = "ir-source-record/v1"' in lineage_source
                    and 'LINEAGE_GRAPH_SCHEMA: Final = "ir-lineage-graph/v1"' in lineage_source
                    and _has_class(lineage_source, "SourceRelease")
                ),
                relpath=LINEAGE_RELPATH,
                reason_present="Source lineage v1 schemas and SourceRelease are present.",
                reason_absent="Source lineage v1 schemas or SourceRelease are missing.",
            )
        )
        probes.append(
            _static_flag_probe(
                probe_id="source_rights_record",
                present=_has_class(lineage_source, "RightsRecord")
                and "ADMITTED" in lineage_source,
                relpath=LINEAGE_RELPATH,
                reason_present="RightsRecord with fail-closed admission is present.",
                reason_absent="RightsRecord is missing.",
            )
        )

    pack_source = _read_source(root, CONTEXT_PACK_RELPATH)
    if pack_source is None:
        probes.append(
            _unavailable_file_probe("context_pack_canonical_interface", CONTEXT_PACK_RELPATH)
        )
        probes.append(
            _unavailable_file_probe("context_pack_v01_compatibility_only", CONTEXT_PACK_RELPATH)
        )
    else:
        canonical = _assign_str_constant(pack_source, "CANONICAL_INTERFACE")
        v01_maturity = _assign_str_constant(pack_source, "V01_MATURITY")
        flagged = _assign_bool_constant(pack_source, "DATASETS_CONTEXT_PACK_CANONICAL")
        probes.append(
            _static_flag_probe(
                probe_id="context_pack_canonical_interface",
                present=(
                    canonical == CONTEXT_PACK_INTERFACE
                    and flagged is True
                    and "def admit_datasets_context_pack" in pack_source
                ),
                relpath=CONTEXT_PACK_RELPATH,
                reason_present="DatasetsContextPack@1 is the canonical ContextPack contract.",
                reason_absent="DatasetsContextPack@1 is missing or not marked canonical.",
                extra={"canonical": canonical, "flagged": flagged},
            )
        )
        probes.append(
            _static_flag_probe(
                probe_id="context_pack_v01_compatibility_only",
                present=(
                    v01_maturity == "compatibility_only"
                    and CONTEXT_PACK_V01_INTERFACE in pack_source
                ),
                relpath=CONTEXT_PACK_RELPATH,
                reason_present="DatasetsContextPackAuthority@0.1 remains compatibility-only.",
                reason_absent="v0.1 ContextPack is missing the compatibility-only mark.",
                extra={"v01_maturity": v01_maturity},
            )
        )

    claims_source = _read_source(root, CLAIMS_RELPATH)
    if claims_source is None:
        probes.append(_unavailable_file_probe("proof_obligation_schema", CLAIMS_RELPATH))
    else:
        probes.append(
            _static_flag_probe(
                probe_id="proof_obligation_schema",
                present=(
                    _has_class(claims_source, "ProofObligation")
                    and 'IR_OBLIGATION_SCHEMA_VERSION: Final = "ir-proof-obligation/v1"'
                    in claims_source
                ),
                relpath=CLAIMS_RELPATH,
                reason_present="ProofObligation@1 schema ir-proof-obligation/v1 is present.",
                reason_absent="ProofObligation schema is missing or drifted.",
            )
        )

    protocols_source = _read_source(root, PROTOCOLS_RELPATH)
    if protocols_source is None:
        probes.append(_unavailable_file_probe("proof_result_class", PROTOCOLS_RELPATH))
    else:
        probes.append(
            _static_flag_probe(
                probe_id="proof_result_class",
                present=_has_class(protocols_source, "ProofResult")
                and "class ExecutionBounds" in protocols_source,
                relpath=PROTOCOLS_RELPATH,
                reason_present="ProofResult and ExecutionBounds are present.",
                reason_absent="ProofResult or ExecutionBounds is missing.",
            )
        )

    receipts_source = _read_source(root, RECEIPTS_RELPATH)
    if receipts_source is None:
        probes.append(
            _unavailable_file_probe("translation_receipt_interface", RECEIPTS_RELPATH)
        )
    else:
        interface = _assign_str_constant(
            receipts_source, "LOGIC_TRANSLATION_RECEIPT_INTERFACE"
        )
        probes.append(
            _static_flag_probe(
                probe_id="translation_receipt_interface",
                present=interface == "LogicTranslationReceipt@1"
                and "def require_current_translation_receipt" in receipts_source,
                relpath=RECEIPTS_RELPATH,
                reason_present="LogicTranslationReceipt@1 require-current path is present.",
                reason_absent="LogicTranslationReceipt@1 is missing or drifted.",
                extra={"interface": interface},
            )
        )

    interpolation_source = _read_source(root, INTERPOLATION_RELPATH)
    if interpolation_source is None:
        probes.append(
            _unavailable_file_probe("interpolation_interface", INTERPOLATION_RELPATH)
        )
    else:
        interface = _assign_str_constant(interpolation_source, "INTERPOLATION_INTERFACE")
        probes.append(
            _static_flag_probe(
                probe_id="interpolation_interface",
                present=interface == "ValidatedCraigInterpolation@1"
                and _has_class(interpolation_source, "InterpolationBounds"),
                relpath=INTERPOLATION_RELPATH,
                reason_present="ValidatedCraigInterpolation@1 with InterpolationBounds is present.",
                reason_absent="Interpolation interface or bounds are missing.",
                extra={"interface": interface},
            )
        )

    cegar_source = _read_source(root, CEGAR_RELPATH)
    if cegar_source is None:
        probes.append(_unavailable_file_probe("cegar_interface", CEGAR_RELPATH))
    else:
        interface = _assign_str_constant(cegar_source, "CEGAR_INTERFACE")
        probes.append(
            _static_flag_probe(
                probe_id="cegar_interface",
                present=interface == "BoundedInterpolationCegar@1"
                and _has_class(cegar_source, "CegarBudget"),
                relpath=CEGAR_RELPATH,
                reason_present="BoundedInterpolationCegar@1 with CegarBudget is present.",
                reason_absent="CEGAR interface or budget is missing.",
                extra={"interface": interface},
            )
        )

    incremental_source = _read_source(root, INCREMENTAL_RELPATH)
    if incremental_source is None:
        probes.append(
            _unavailable_file_probe("incremental_smt_interface", INCREMENTAL_RELPATH)
        )
    else:
        interface = _assign_str_constant(incremental_source, "INCREMENTAL_SMT_INTERFACE")
        probes.append(
            _static_flag_probe(
                probe_id="incremental_smt_interface",
                present=interface == "IncrementalSmtSession@1"
                and _has_class(incremental_source, "IncrementalSmtFingerprint"),
                relpath=INCREMENTAL_RELPATH,
                reason_present="IncrementalSmtSession@1 with fingerprint bounds is present.",
                reason_absent="Incremental SMT interface or fingerprint is missing.",
                extra={"interface": interface},
            )
        )

    manifest_source = _read_source(root, MANIFEST_RELPATH)
    if manifest_source is None:
        probes.append(
            _unavailable_file_probe("manifest_advertises_context_pack", MANIFEST_RELPATH)
        )
    else:
        probes.append(
            _static_flag_probe(
                probe_id="manifest_advertises_context_pack",
                present=(
                    f'"{CONTEXT_PACK_INTERFACE}"' in manifest_source
                    and "DATASETS_SEMANTIC_API_CATALOG_INTERFACE" in manifest_source
                ),
                relpath=MANIFEST_RELPATH,
                reason_present="LogicPlatformManifest advertises DatasetsContextPack@1.",
                reason_absent="LogicPlatformManifest does not advertise DatasetsContextPack@1.",
            )
        )

    pgir_source = _read_source(root, PGIR_CATALOG_RELPATH)
    if pgir_source is None:
        probes.append(
            _unavailable_file_probe("pgir_semantic_api_not_canonical", PGIR_CATALOG_RELPATH)
        )
    else:
        pgir_interface = _assign_str_constant(pgir_source, "SEMANTIC_API_INTERFACE")
        probes.append(
            _static_flag_probe(
                probe_id="pgir_semantic_api_not_canonical",
                present=(
                    pgir_interface == PGIR_SEMANTIC_API_INTERFACE
                    and "PGIR-080" in pgir_source
                    and CONTEXT_PACK_INTERFACE not in pgir_source
                ),
                relpath=PGIR_CATALOG_RELPATH,
                reason_present=(
                    "SemanticPublicAPI@1 remains the PGIR-080 catalog and is not "
                    "the PCPR ContextPack contract."
                ),
                reason_absent="PGIR SemanticPublicAPI@1 catalog is missing or collided with PCPR.",
                extra={"pgir_interface": pgir_interface},
            )
        )

    corpus_source = _read_source(root, CORPUS_RELPATH)
    rights_manifest_present = False
    if corpus_source is not None:
        rights_manifest_present = (
            'schema": "ir-corpus-rights-manifest/v1"' in corpus_source
            or "ir-corpus-rights-manifest/v1" in corpus_source
        )
    probes.append(
        _static_flag_probe(
            probe_id="corpus_rights_manifest_schema",
            present=rights_manifest_present,
            relpath=CORPUS_RELPATH,
            reason_present="ir-corpus-rights-manifest/v1 is present on the corpus builder.",
            reason_absent="ir-corpus-rights-manifest/v1 is missing from the corpus builder.",
        )
    )

    probes.append(
        _static_flag_probe(
            probe_id="catalog_closed",
            present=SEMANTIC_API_NAMES
            == (
                "canonical_ir_identity",
                "source_lineage",
                "context_pack",
                "proof_obligation",
                "proof_result_validation",
                "translation_receipt",
                "interpolation",
                "cegar",
                "incremental_smt",
                "source_rights_manifest",
            ),
            relpath="ipfs_datasets_py/assurance/semantic_apis.py",
            reason_present="PCPR-014 semantic API catalog is closed and versioned.",
            reason_absent="PCPR-014 semantic API catalog drifted.",
        )
    )
    probes.append(
        OutcomeProbe(
            probe_id="live_solver_qualification",
            present=None,
            evidence_kind="unavailable",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "This task does not qualify live solvers. Missing Z3/cvc5/Lean/Coq "
                "evidence stays typed unavailable and is not recorded as False or passing."
            ),
        )
    )
    return tuple(probes)


def _admission(spec: SemanticApiSpec, *, identity_cid: str | None, reason: str) -> SemanticAdmission:
    return SemanticAdmission(
        operation=spec.name,
        interface=spec.interface,
        schema=spec.schema,
        executable=spec.executable,
        advisory=False,
        live=False,
        identity_cid=identity_cid,
        reason=reason,
    )


def admit_semantic_request(operation: str, payload: Any) -> SemanticAdmission:
    """Admit one PCPR-stable semantic request without invoking a live solver.

    Free-form, advisory-as-authority, and executable-without-bounds requests
    fail closed. Successful admission is never represented as live solver
    qualification.
    """

    spec = semantic_api_spec(operation)
    if payload is not None and not isinstance(payload, Mapping) and operation not in {
        "translation_receipt",
        "proof_result_validation",
        "proof_obligation",
        "source_rights_manifest",
        "source_lineage",
        "context_pack",
        "canonical_ir_identity",
        "interpolation",
        "cegar",
        "incremental_smt",
    }:
        raise SemanticApiAdmissionError(f"{operation} payload must be a mapping")

    if operation == "canonical_ir_identity":
        if not isinstance(payload, Mapping):
            raise SemanticApiAdmissionError("canonical_ir_identity payload must be a mapping")
        extra = set(payload) - {"domain", "schema_version", "payload"}
        if extra:
            raise SemanticApiAdmissionError(
                "free-form identity field cannot mint CanonicalIRIdentity@1"
            )
        domain = payload.get("domain")
        schema_version = payload.get("schema_version")
        body = payload.get("payload")
        if not isinstance(domain, str) or not isinstance(schema_version, str):
            raise SemanticApiAdmissionError(
                "canonical_ir_identity requires domain and schema_version"
            )
        from ipfs_datasets_py.logic.ir_core.identity import canonical_identity

        identity = canonical_identity(body, domain=domain, schema_version=schema_version)
        return _admission(spec, identity_cid=identity.cid, reason="canonical IR identity admitted")

    if operation == "source_lineage":
        if not isinstance(payload, Mapping):
            raise SemanticApiAdmissionError("source_lineage payload must be a mapping")
        from ipfs_datasets_py.logic.ir_core.source_lineage import (
            SourceLineageError,
            SourceRelease,
        )

        kind = payload.get("kind")
        if kind != "source_release":
            raise SemanticApiAdmissionError(
                "source_lineage requires explicit kind source_release"
            )
        try:
            record = SourceRelease.from_dict(payload)
        except SourceLineageError as error:
            raise SemanticApiAdmissionError(str(error)) from error
        return _admission(
            spec,
            identity_cid=record.record_cid,
            reason="source release lineage admitted",
        )

    if operation == "context_pack":
        from ipfs_datasets_py.proof_context.context_pack import (
            ContextPackAdmissionError,
            OpaqueSourceRequiredError,
            StaleContextError,
            UnavailableContextError,
            admit_datasets_context_pack,
        )

        if not isinstance(payload, Mapping):
            raise SemanticApiAdmissionError("context_pack payload must be a mapping")
        try:
            pack = admit_datasets_context_pack(payload)
        except (
            ContextPackAdmissionError,
            OpaqueSourceRequiredError,
            StaleContextError,
            UnavailableContextError,
        ) as error:
            raise SemanticApiAdmissionError(str(error)) from error
        return _admission(
            spec, identity_cid=pack.pack_cid, reason="DatasetsContextPack@1 admitted"
        )

    if operation == "proof_obligation":
        from ipfs_datasets_py.logic.ir_core.claims import (
            ClaimValidationError,
            ProofObligation,
        )

        if not isinstance(payload, Mapping):
            raise SemanticApiAdmissionError("proof_obligation payload must be a mapping")
        try:
            obligation = ProofObligation.from_dict(payload)
        except ClaimValidationError as error:
            raise SemanticApiAdmissionError(str(error)) from error
        return _admission(
            spec,
            identity_cid=obligation.digest,
            reason="ProofObligation@1 admitted as a declaration",
        )

    if operation == "proof_result_validation":
        from ipfs_datasets_py.logic.ir_core.protocols import (
            AuthorityMismatchError,
            ProofResult,
            ProtocolValidationError,
        )

        if not isinstance(payload, Mapping):
            raise SemanticApiAdmissionError(
                "proof_result_validation payload must be a mapping"
            )
        try:
            ProofResult.from_dict(payload)
        except (ProtocolValidationError, AuthorityMismatchError, TypeError, ValueError) as error:
            raise SemanticApiAdmissionError(
                "free-form payload cannot mint ProofResult@1 theorem authority"
            ) from error
        return _admission(spec, identity_cid=None, reason="ProofResult@1 admitted")

    if operation == "translation_receipt":
        from ipfs_datasets_py.logic.software_verification.receipts import (
            LogicTranslationReceipt,
        )

        if payload is None:
            raise SemanticApiAdmissionError("translation receipt is required")
        if isinstance(payload, LogicTranslationReceipt):
            return _admission(
                spec,
                identity_cid=getattr(payload, "receipt_id", None),
                reason="LogicTranslationReceipt@1 admitted",
            )
        raise SemanticApiAdmissionError(
            "free-form translation payload cannot mint LogicTranslationReceipt@1"
        )

    if operation == "interpolation":
        if not isinstance(payload, Mapping):
            raise SemanticApiAdmissionError("interpolation payload must be a mapping")
        if "bounds" not in payload:
            raise SemanticApiAdmissionError(
                "executable interpolation requires positive finite bounds"
            )
        bounds = payload.get("bounds")
        if not isinstance(bounds, Mapping):
            raise SemanticApiAdmissionError("interpolation bounds must be a mapping")
        if "timeout_ms" not in bounds or "memory_limit_mib" not in bounds:
            raise SemanticApiAdmissionError(
                "executable interpolation requires positive finite bounds"
            )
        from ipfs_datasets_py.logic.backends.smt.interpolation import (
            InterpolationBounds,
            InterpolationError,
        )

        try:
            InterpolationBounds(
                timeout_ms=bounds.get("timeout_ms", 0),
                memory_limit_mib=bounds.get("memory_limit_mib", 0),
                max_symbols=bounds.get("max_symbols", 0),
                max_term_nodes=bounds.get("max_term_nodes", 0),
                theory=bounds.get("theory", "QF_LIA"),
            )
        except (InterpolationError, TypeError, ValueError) as error:
            raise SemanticApiAdmissionError(str(error)) from error
        return _admission(
            spec,
            identity_cid=None,
            reason="interpolation request admitted; live interpolant remains unavailable",
        )

    if operation == "cegar":
        if not isinstance(payload, Mapping):
            raise SemanticApiAdmissionError("cegar payload must be a mapping")
        if "budget" not in payload:
            raise SemanticApiAdmissionError(
                "executable CEGAR requires a positive finite budget"
            )
        budget = payload.get("budget")
        if not isinstance(budget, Mapping):
            raise SemanticApiAdmissionError("CEGAR budget must be a mapping")
        if "timeout_ms" not in budget:
            raise SemanticApiAdmissionError(
                "executable CEGAR requires a positive finite budget"
            )
        from ipfs_datasets_py.logic.software_verification.cegar import (
            CegarBudget,
            CegarError,
        )

        try:
            kwargs = {
                key: budget[key]
                for key in (
                    "max_iterations",
                    "max_predicates",
                    "max_abstract_states",
                    "max_trace_length",
                    "timeout_ms",
                    "memory_limit_mib",
                    "max_symbols",
                    "max_term_nodes",
                )
                if key in budget
            }
            CegarBudget(**kwargs)
        except (CegarError, TypeError, ValueError) as error:
            raise SemanticApiAdmissionError(str(error)) from error
        return _admission(
            spec,
            identity_cid=None,
            reason="CEGAR request admitted; live solver result remains unavailable",
        )

    if operation == "incremental_smt":
        if not isinstance(payload, Mapping):
            raise SemanticApiAdmissionError("incremental_smt payload must be a mapping")
        if "timeout_ms" not in payload or "memory_limit_mib" not in payload:
            raise SemanticApiAdmissionError(
                "executable incremental SMT requires positive timeout_ms and memory_limit_mib"
            )
        from ipfs_datasets_py.logic.backends.smt.incremental import (
            IncrementalSmtError,
            IncrementalSmtFingerprint,
        )

        try:
            fingerprint = IncrementalSmtFingerprint(
                provider=str(payload.get("provider") or ""),
                provider_version=str(payload.get("provider_version") or ""),
                logic=str(payload.get("logic") or ""),
                translator_identity=str(payload.get("translator_identity") or ""),
                theory_fingerprint=str(payload.get("theory_fingerprint") or ""),
                policy_root=str(payload.get("policy_root") or ""),
                configuration_root=str(payload.get("configuration_root") or ""),
                environment_root=str(payload.get("environment_root") or ""),
                timeout_ms=payload.get("timeout_ms", 0),
                memory_limit_mib=payload.get("memory_limit_mib", 0),
            )
        except (IncrementalSmtError, TypeError, ValueError) as error:
            raise SemanticApiAdmissionError(str(error)) from error
        return _admission(
            spec,
            identity_cid=fingerprint.digest,
            reason="incremental SMT fingerprint admitted; session was not opened",
        )

    if operation == "source_rights_manifest":
        from ipfs_datasets_py.logic.ir_core.source_lineage import (
            RightsRecord,
            SourceLineageError,
        )

        if not isinstance(payload, Mapping):
            raise SemanticApiAdmissionError(
                "source_rights_manifest payload must be a mapping"
            )
        try:
            RightsRecord.from_dict(payload)
        except SourceLineageError as error:
            raise SemanticApiAdmissionError(str(error)) from error
        return _admission(spec, identity_cid=None, reason="RightsRecord admitted")

    raise SemanticApiAdmissionError(f"unsupported semantic operation {operation!r}")


def _context_pack_payload(**overrides: Any) -> dict[str, Any]:
    from ipfs_datasets_py.logic.ir_core.identity import cid_v1

    def _cid(label: str) -> str:
        return cid_v1(label.encode("utf-8"))

    fields: dict[str, Any] = {
        "repository_state_cid": _cid("repo-state"),
        "task_id": "PCPR-014",
        "target_source_cid": _cid("target"),
        "surrounding_source_cid": _cid("surround"),
        "test_source_cid": _cid("test"),
        "scanned_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "source_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "capsule_cids": (_cid("capsule"),),
    }
    fields.update(overrides)
    return fields


def probe_semantic_runtime() -> dict[str, Any]:
    """Hermetic runtime observation of semantic API admission.

    No solver, network, installer, or live provider is invoked.
    """

    from ipfs_datasets_py.logic.semantic.catalog import SEMANTIC_API_INTERFACE
    from ipfs_datasets_py.proof_context.context_pack import (
        CANONICAL_INTERFACE,
        DATASETS_CONTEXT_PACK_CANONICAL,
        V01_MATURITY,
        admit_datasets_context_pack,
    )

    identity_a = admit_semantic_request(
        "canonical_ir_identity",
        {
            "domain": "pcpr.014.identity",
            "schema_version": "ir-claim/v1",
            "payload": {"statement": "P"},
        },
    )
    identity_b = admit_semantic_request(
        "canonical_ir_identity",
        {
            "domain": "pcpr.014.identity",
            "schema_version": "ir-claim/v1",
            "payload": {"statement": "P"},
        },
    )
    identity_deterministic = (
        identity_a.identity_cid is not None
        and identity_a.identity_cid == identity_b.identity_cid
        and identity_a.live is False
    )

    pack_a = admit_datasets_context_pack(_context_pack_payload())
    pack_b = admit_datasets_context_pack(_context_pack_payload())
    pack_deterministic = pack_a.pack_cid == pack_b.pack_cid and pack_a.interface == CANONICAL_INTERFACE

    freeform_pack = False
    freeform_pack_reason = ""
    try:
        admit_semantic_request(
            "context_pack",
            {**_context_pack_payload(), "formula": "P", "backend_request": {"id": "forged"}},
        )
        freeform_pack = True
        freeform_pack_reason = "free-form ContextPack was admitted"
    except SemanticApiAdmissionError as error:
        freeform_pack_reason = str(error)

    advisory_pack = False
    advisory_pack_reason = ""
    try:
        admit_semantic_request("context_pack", {**_context_pack_payload(), "advisory": True})
        advisory_pack = True
        advisory_pack_reason = "advisory ContextPack minted DatasetsContextPack@1"
    except SemanticApiAdmissionError as error:
        advisory_pack_reason = str(error)

    freeform_proof = False
    freeform_proof_reason = ""
    try:
        admit_semantic_request(
            "proof_result_validation",
            {"ok": True, "status": "proved", "live": True},
        )
        freeform_proof = True
        freeform_proof_reason = "free-form proof result minted theorem authority"
    except SemanticApiAdmissionError as error:
        freeform_proof_reason = str(error)

    freeform_translation = False
    freeform_translation_reason = ""
    try:
        admit_semantic_request("translation_receipt", {"preserved": True})
        freeform_translation = True
        freeform_translation_reason = "free-form translation payload minted a receipt"
    except SemanticApiAdmissionError as error:
        freeform_translation_reason = str(error)

    interpolation_missing = False
    interpolation_reason = ""
    try:
        admit_semantic_request("interpolation", {"theory": "QF_LIA"})
        interpolation_missing = True
        interpolation_reason = "interpolation was admitted without bounds"
    except SemanticApiAdmissionError as error:
        interpolation_reason = str(error)

    cegar_missing = False
    cegar_reason = ""
    try:
        admit_semantic_request("cegar", {"system": "QF_LIA"})
        cegar_missing = True
        cegar_reason = "CEGAR was admitted without a budget"
    except SemanticApiAdmissionError as error:
        cegar_reason = str(error)

    smt_missing = False
    smt_reason = ""
    try:
        admit_semantic_request(
            "incremental_smt",
            {
                "provider": "z3",
                "provider_version": "unavailable",
                "logic": "QF_LIA",
                "translator_identity": "pcpr-014",
                "theory_fingerprint": "QF_LIA@1",
                "policy_root": "policy",
                "configuration_root": "config",
                "environment_root": "env",
            },
        )
        smt_missing = True
        smt_reason = "incremental SMT was admitted without timeout/memory bounds"
    except SemanticApiAdmissionError as error:
        smt_reason = str(error)

    unresolved_admitted = False
    rights_reason = ""
    try:
        admit_semantic_request(
            "source_rights_manifest",
            {
                "disposition": "admitted",
                "license_expression": "cc0-1.0",
                "source_rights_status": "unresolved",
                "transformation_rights_status": "unresolved",
                "scope": "pcpr-014",
            },
        )
        unresolved_admitted = True
        rights_reason = "admitted+unresolved rights were accepted"
    except SemanticApiAdmissionError as error:
        rights_reason = str(error)

    obligation = admit_semantic_request(
        "proof_obligation",
        {
            "obligation_id": "obl:pcpr-014",
            "statement": "P",
            "logic_family": "unspecified",
        },
    )

    represented_as_live = bool(identity_a.live or obligation.live)
    return {
        "status": "observed",
        "evidence_kind": "measured",
        "live": False,
        "simulated_represented_as_live": represented_as_live,
        "identity_deterministic": identity_deterministic,
        "identity_cid": identity_a.identity_cid,
        "context_pack_deterministic": pack_deterministic,
        "context_pack_cid": pack_a.pack_cid,
        "context_pack_canonical": DATASETS_CONTEXT_PACK_CANONICAL is True,
        "context_pack_v01_maturity": V01_MATURITY,
        "freeform_pack": freeform_pack,
        "freeform_pack_reason": freeform_pack_reason,
        "advisory_pack": advisory_pack,
        "advisory_pack_reason": advisory_pack_reason,
        "freeform_proof": freeform_proof,
        "freeform_proof_reason": freeform_proof_reason,
        "freeform_translation": freeform_translation,
        "freeform_translation_reason": freeform_translation_reason,
        "interpolation_missing_bounds": interpolation_missing,
        "interpolation_reason": interpolation_reason,
        "cegar_missing_bounds": cegar_missing,
        "cegar_reason": cegar_reason,
        "smt_missing_bounds": smt_missing,
        "smt_reason": smt_reason,
        "unresolved_admitted": unresolved_admitted,
        "rights_reason": rights_reason,
        "obligation_admitted": obligation.identity_cid is not None,
        "pgir_interface": SEMANTIC_API_INTERFACE,
        "reason": (
            "DatasetsContextPack@1 and the closed semantic API catalog are "
            "fail-closed; live solvers remain typed unavailable."
        ),
    }


def current_head_runtime_probes() -> tuple[OutcomeProbe, ...]:
    observation = probe_semantic_runtime()
    live = bool(observation["live"] or observation["simulated_represented_as_live"])
    return (
        OutcomeProbe(
            probe_id="identity_deterministic",
            present=bool(observation["identity_deterministic"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Canonical IR identities are deterministic."
                if observation["identity_deterministic"]
                else "Canonical IR identities were not deterministic."
            ),
            details={"identity_cid": observation["identity_cid"]},
        ),
        OutcomeProbe(
            probe_id="context_pack_identity_deterministic",
            present=bool(observation["context_pack_deterministic"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "DatasetsContextPack@1 identities are deterministic."
                if observation["context_pack_deterministic"]
                else "DatasetsContextPack@1 identities were not deterministic."
            ),
            details={"pack_cid": observation["context_pack_cid"]},
        ),
        OutcomeProbe(
            probe_id="freeform_context_pack_admitted",
            present=bool(observation["freeform_pack"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Free-form ContextPack payloads cannot mint DatasetsContextPack@1."
                if not observation["freeform_pack"]
                else "Free-form ContextPack payload was admitted."
            ),
            details={"reason": observation["freeform_pack_reason"]},
        ),
        OutcomeProbe(
            probe_id="advisory_context_pack_admitted",
            present=bool(observation["advisory_pack"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Advisory ContextPack material remains non-authoritative."
                if not observation["advisory_pack"]
                else "Advisory ContextPack material minted DatasetsContextPack@1."
            ),
            details={"reason": observation["advisory_pack_reason"]},
        ),
        OutcomeProbe(
            probe_id="freeform_proof_result_admitted",
            present=bool(observation["freeform_proof"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Free-form payloads cannot mint ProofResult@1 theorem authority."
                if not observation["freeform_proof"]
                else "Free-form payload minted ProofResult@1."
            ),
            details={"reason": observation["freeform_proof_reason"]},
        ),
        OutcomeProbe(
            probe_id="freeform_translation_receipt_admitted",
            present=bool(observation["freeform_translation"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Free-form translation payloads cannot mint LogicTranslationReceipt@1."
                if not observation["freeform_translation"]
                else "Free-form translation payload minted a receipt."
            ),
            details={"reason": observation["freeform_translation_reason"]},
        ),
        OutcomeProbe(
            probe_id="executable_interpolation_missing_bounds_admitted",
            present=bool(observation["interpolation_missing_bounds"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Executable interpolation requires positive finite bounds."
                if not observation["interpolation_missing_bounds"]
                else "Interpolation was admitted without bounds."
            ),
            details={"reason": observation["interpolation_reason"]},
        ),
        OutcomeProbe(
            probe_id="executable_cegar_missing_bounds_admitted",
            present=bool(observation["cegar_missing_bounds"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Executable CEGAR requires a positive finite budget."
                if not observation["cegar_missing_bounds"]
                else "CEGAR was admitted without a budget."
            ),
            details={"reason": observation["cegar_reason"]},
        ),
        OutcomeProbe(
            probe_id="executable_incremental_smt_missing_bounds_admitted",
            present=bool(observation["smt_missing_bounds"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Executable incremental SMT requires positive timeout and memory bounds."
                if not observation["smt_missing_bounds"]
                else "Incremental SMT was admitted without bounds."
            ),
            details={"reason": observation["smt_reason"]},
        ),
        OutcomeProbe(
            probe_id="admitted_unresolved_rights",
            present=bool(observation["unresolved_admitted"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Admitted rights require a resolved source-rights status."
                if not observation["unresolved_admitted"]
                else "Admitted+unresolved rights were accepted."
            ),
            details={"reason": observation["rights_reason"]},
        ),
        OutcomeProbe(
            probe_id="runtime_unavailable_represented_as_live",
            present=live,
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Semantic API probes are not represented as live."
                if not live
                else "Semantic API probes were represented as live."
            ),
        ),
    )


def qualify_semantic_apis_canonical(
    probes: Sequence[OutcomeProbe],
) -> SemanticApiVerdict:
    if not probes:
        raise SemanticApiCanonicalError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise SemanticApiCanonicalError("live claims require measured_live evidence")
        if probe.simulated_represented_as_live:
            raise SemanticApiCanonicalError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in {"live_solver_qualification", "corpus_rights_manifest_schema"}:
            continue
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)
        if probe.present is None and probe.evidence_kind == "unavailable":
            if probe.probe_id == "datasets_source_tree":
                blockers.append(probe.probe_id)

    canonical = not blockers
    context_pack_canonical = any(
        p.probe_id == "context_pack_canonical_interface" and p.present is True
        for p in normalized
    ) and canonical
    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_014_TASK_ID,
        "goal_id": PCPR_014_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "semantic_apis_canonical": canonical,
        "context_pack_canonical": context_pack_canonical,
        "simulated_results_represented_as_live": False,
        "live_solver_qualified": False,
        "live_solver_evidence_kind": "unavailable",
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
    }
    return SemanticApiVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        semantic_apis_canonical=canonical,
        context_pack_canonical=context_pack_canonical,
        simulated_results_represented_as_live=False,
        live_solver_qualified=False,
        live_solver_evidence_kind="unavailable",
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
    )


def qualify_current_head_semantic_apis() -> SemanticApiVerdict:
    return qualify_semantic_apis_canonical(current_head_static_probes())


# Pinned identity of the ordinary current-head static verdict. Drift means
# the default payload changed and the outer receipt must be regenerated.
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeeraohwniavwmnp27wk2ztc74ucxlco4vxjmyrjz7uei57olqraxes6a"
)


def pcpr_014_receipt_promotion(verdict: SemanticApiVerdict) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise SemanticApiCanonicalError(
            "semantic-api canonicalization must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise SemanticApiCanonicalError(
            "semantic-api canonicalization must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise SemanticApiCanonicalError(
            "semantic-api canonicalization completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise SemanticApiCanonicalError(
            "semantic-api canonicalization must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise SemanticApiCanonicalError(
            "promotion_status must not be a closed release outcome"
        )
    return verdict.to_mapping()


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CONTEXT_PACK_INTERFACE",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OutcomeProbe",
    "PCPR_014_GOAL_ID",
    "PCPR_014_TASK_ID",
    "SCHEMA",
    "SEMANTIC_API_NAMES",
    "SEMANTIC_API_SPECS",
    "SemanticAdmission",
    "SemanticApiAdmissionError",
    "SemanticApiCanonicalError",
    "SemanticApiSpec",
    "SemanticApiVerdict",
    "admit_semantic_request",
    "content_identity",
    "current_head_runtime_probes",
    "current_head_static_probes",
    "discover_datasets_root",
    "pcpr_014_receipt_promotion",
    "probe_semantic_runtime",
    "qualify_current_head_semantic_apis",
    "qualify_semantic_apis_canonical",
    "semantic_api_manifest",
    "semantic_api_spec",
]
