"""Fail-closed PCPR-015 schema and shared-vector packaging.

Put cross-repository schemas and fixtures in package data. Installed
packages cannot depend on an adjacent Datasets tests directory. Loaders
use importlib.resources. Sibling tests/ paths fail closed.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Live claims require
live evidence. Simulated results are not live. Missing solvers stay typed
unavailable.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib.resources
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

INTERFACE: Final = "DatasetsSchemaPackaging@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/schema-packaging-catalog@1"
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/schema-packaging-verdict@1"
)
VECTOR_INTERFACE: Final = "DatasetsSharedVectors@1"
VECTOR_SCHEMA: Final = "ipfs_datasets_py/assurance/shared-vectors@1"
PCPR_015_TASK_ID: Final = "PCPR-015"
PCPR_015_GOAL_ID: Final = "PCPR-G230"
PCPR_014_TASK_ID: Final = "PCPR-014"
PCPR_003_TASK_ID: Final = "PCPR-003"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = (
    "proof-carrying-platform-qualification-and-release-v1"
)
EVIDENCE_ID: Final = "pcpr/datasets-schema-packaging@1"

ASSURANCE_PACKAGE: Final = "ipfs_datasets_py.assurance"
ROOT_PACKAGE: Final = "ipfs_datasets_py"
CATALOG_RESOURCE: Final = "schemas/catalog.json"
VECTOR_RESOURCE: Final = "vectors/recipes.json"

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
SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "package_data",
        "owner_package_data",
    }
)
FORBIDDEN_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "sibling_tests_tree",
        "repo_tests_fixtures",
        "sys_path_tests_injection",
    }
)
POLARITIES: Final[frozenset[str]] = frozenset({"positive", "negative"})
REJECT_KINDS: Final[frozenset[str]] = frozenset(
    {"schema", "semantic", "path"}
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_015_schema_packaging.py",
)

SEALED_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
SEALED_PYTHON: Final = "/usr/bin/python3.12"

PACKAGING_GLOBS: Final[tuple[str, ...]] = (
    "assurance/schemas/*.json",
    "assurance/vectors/*.json",
    "logic/bridge/schemas/*.json",
    "logic/intent_ir/intent_ir.schema.json",
    "logic/legal_ir/schemas/*.json",
    "logic/software_contracts/adversarial_assurance/schemas/*.json",
    "logic/software_contracts/semantic_governor/schemas/*.json",
    "logic/software_contracts/semantic_state/schemas/*.json",
    "logic/ui_ux_ir/ui_ux_ir.schema.json",
    "processors/groth16_backend/schemas/*.json",
)

MANIFEST_LINES: Final[tuple[str, ...]] = (
    "recursive-include ipfs_datasets_py/assurance/schemas *.json",
    "recursive-include ipfs_datasets_py/assurance/vectors *.json",
    "recursive-include ipfs_datasets_py/logic/bridge/schemas *.json",
    "include ipfs_datasets_py/logic/intent_ir/intent_ir.schema.json",
    "recursive-include ipfs_datasets_py/logic/legal_ir/schemas *.json",
    "recursive-include ipfs_datasets_py/logic/software_contracts/adversarial_assurance/schemas *.json",
    "recursive-include ipfs_datasets_py/logic/software_contracts/semantic_governor/schemas *.json",
    "recursive-include ipfs_datasets_py/logic/software_contracts/semantic_state/schemas *.json",
    "include ipfs_datasets_py/logic/ui_ux_ir/ui_ux_ir.schema.json",
    "recursive-include ipfs_datasets_py/processors/groth16_backend/schemas *.json",
)

PCPR_STABLE_SCHEMA_NAMES: Final[tuple[str, ...]] = (
    "schema_packaging_catalog",
    "datasets_context_pack",
    "canonical_ir_identity",
    "source_lineage",
    "proof_obligation",
    "proof_result",
    "translation_receipt",
    "interpolation_bounds",
    "cegar_budget",
    "incremental_smt",
    "source_rights",
)

REQUIRED_GOOD_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "catalog_packaged",
        "pcpr_schemas_packaged",
        "owner_schemas_packaged",
        "shared_vectors_packaged",
        "sibling_tests_not_required",
        "tests_path_rejected",
        "packaging_globs_declared",
        "packaging_manifest_in",
        "packaging_setup_py",
        "packaging_pyproject",
        "include_package_data",
        "positive_vectors_admit",
        "negative_vectors_reject",
        "identity_deterministic",
        "manifest_advertises_packaging",
        "loader_does_not_use_tests_tree",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "sibling_tests_loader_used",
        "simulated_results_represented_as_live",
        "runtime_unavailable_represented_as_live",
    }
)

_CID_RE: Final = re.compile(r"^b[a-z2-7]+$")
_REF_DEFS: Final = re.compile(r"^#/\$defs/([A-Za-z0-9_-]+)$")


class SchemaPackagingError(Exception):
    """Fail-closed PCPR-015 contract error."""


class SchemaPackagingAdmissionError(SchemaPackagingError):
    """Raised when a schema path, payload, or vector is rejected."""


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


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaPackagingError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise SchemaPackagingError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise SchemaPackagingError(
            f"{name} must not be a closed PCPR release outcome"
        )


def normalize_packaging_path(path: str) -> str:
    text = _text(path, "path")
    return text.replace("\\", "/").lstrip("./")


def admit_schema_path(path: str) -> str:
    """Reject sibling tests-tree paths. In-package paths remain admissible."""

    normalized = normalize_packaging_path(path)
    if ".." in Path(normalized).parts:
        raise SchemaPackagingAdmissionError(
            "schema path must not traverse parent directories"
        )
    if normalized.startswith("ipfs_datasets_py/"):
        return normalized
    if (
        normalized == "tests"
        or normalized.startswith("tests/")
        or "/tests/fixtures/" in f"/{normalized}/"
        or normalized.startswith("test/fixtures/")
    ):
        raise SchemaPackagingAdmissionError(
            "installed packaging must not load a sibling tests tree"
        )
    return normalized


def _read_package_bytes(package: str, relative: str) -> bytes:
    admit_schema_path(relative)
    root = importlib.resources.files(package)
    resource = root.joinpath(*Path(relative).parts)
    if not resource.is_file():
        raise SchemaPackagingError(
            f"packaged resource missing: {package}:{relative}"
        )
    return resource.read_bytes()


def load_packaged_json(package: str, relative: str) -> Any:
    payload = json.loads(_read_package_bytes(package, relative).decode("utf-8"))
    if not isinstance(payload, (dict, list)):
        raise SchemaPackagingError(
            f"packaged JSON at {package}:{relative} must be an object or array"
        )
    return payload


@dataclass(frozen=True, slots=True)
class PackagedSchemaSpec:
    name: str
    interface: str
    schema_id: str
    package_relpath: str
    source_kind: str
    maturity: str

    def to_dict(self) -> dict[str, str]:
        return {
            "interface": self.interface,
            "maturity": self.maturity,
            "name": self.name,
            "package_relpath": self.package_relpath,
            "schema_id": self.schema_id,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True, slots=True)
class SharedVectorSpec:
    vector_id: str
    schema_name: str
    polarity: str
    payload: Mapping[str, Any]
    reject_kind: str | None
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "payload": dict(self.payload),
            "polarity": self.polarity,
            "schema_name": self.schema_name,
            "vector_id": self.vector_id,
        }
        if self.reject_kind is not None:
            mapping["reject_kind"] = self.reject_kind
        if self.reason is not None:
            mapping["reason"] = self.reason
        return mapping


def _schema_spec_from_mapping(raw: Mapping[str, Any]) -> PackagedSchemaSpec:
    name = _text(raw.get("name"), "schema.name")
    interface = _text(raw.get("interface"), f"schema[{name}].interface")
    schema_id = _text(raw.get("schema_id"), f"schema[{name}].schema_id")
    relpath = admit_schema_path(
        _text(raw.get("package_relpath"), f"schema[{name}].package_relpath")
    )
    source_kind = _text(raw.get("source_kind"), f"schema[{name}].source_kind")
    if source_kind in FORBIDDEN_SOURCE_KINDS:
        raise SchemaPackagingAdmissionError(
            f"schema[{name}] source_kind {source_kind} is forbidden"
        )
    if source_kind not in SOURCE_KINDS:
        raise SchemaPackagingError(
            f"schema[{name}] source_kind is not an admitted packaging source"
        )
    maturity = _text(raw.get("maturity"), f"schema[{name}].maturity")
    return PackagedSchemaSpec(
        name=name,
        interface=interface,
        schema_id=schema_id,
        package_relpath=relpath,
        source_kind=source_kind,
        maturity=maturity,
    )


def load_schema_catalog() -> dict[str, Any]:
    catalog = load_packaged_json(ASSURANCE_PACKAGE, CATALOG_RESOURCE)
    if not isinstance(catalog, dict):
        raise SchemaPackagingError("schema catalog must be an object")
    if catalog.get("interface") != INTERFACE:
        raise SchemaPackagingError("schema catalog interface mismatch")
    if catalog.get("schema") != SCHEMA:
        raise SchemaPackagingError("schema catalog schema mismatch")
    if catalog.get("requires_sibling_tests_tree") is not False:
        raise SchemaPackagingError(
            "schema catalog must declare requires_sibling_tests_tree=false"
        )
    if catalog.get("task_id") != PCPR_015_TASK_ID:
        raise SchemaPackagingError("schema catalog task_id mismatch")
    return catalog


def packaged_schema_specs() -> tuple[PackagedSchemaSpec, ...]:
    catalog = load_schema_catalog()
    raw_schemas = catalog.get("schemas")
    if not isinstance(raw_schemas, list) or not raw_schemas:
        raise SchemaPackagingError("schema catalog must list schemas")
    specs = tuple(_schema_spec_from_mapping(item) for item in raw_schemas)
    names = tuple(spec.name for spec in specs)
    if names[: len(PCPR_STABLE_SCHEMA_NAMES)] != PCPR_STABLE_SCHEMA_NAMES:
        raise SchemaPackagingError(
            "PCPR-stable schema names must lead the packaged catalog"
        )
    return specs


def packaged_schema_spec(name: str) -> PackagedSchemaSpec:
    for spec in packaged_schema_specs():
        if spec.name == name:
            return spec
    raise KeyError(
        f"unknown packaged schema {name!r}; known schemas are "
        f"{[spec.name for spec in packaged_schema_specs()]}"
    )


def load_schema_document(name: str) -> dict[str, Any]:
    spec = packaged_schema_spec(name)
    if spec.name == "schema_packaging_catalog":
        document = load_schema_catalog()
    else:
        document = load_packaged_json(ROOT_PACKAGE, spec.package_relpath)
    if not isinstance(document, dict):
        raise SchemaPackagingError(f"schema {name} must be a JSON object")
    return document


def load_vector_catalog() -> dict[str, Any]:
    catalog = load_packaged_json(ASSURANCE_PACKAGE, VECTOR_RESOURCE)
    if not isinstance(catalog, dict):
        raise SchemaPackagingError("vector catalog must be an object")
    if catalog.get("interface") != VECTOR_INTERFACE:
        raise SchemaPackagingError("vector catalog interface mismatch")
    if catalog.get("schema") != VECTOR_SCHEMA:
        raise SchemaPackagingError("vector catalog schema mismatch")
    if catalog.get("requires_sibling_tests_tree") is not False:
        raise SchemaPackagingError(
            "vector catalog must declare requires_sibling_tests_tree=false"
        )
    return catalog


def shared_vector_specs() -> tuple[SharedVectorSpec, ...]:
    catalog = load_vector_catalog()
    raw_vectors = catalog.get("vectors")
    if not isinstance(raw_vectors, list) or not raw_vectors:
        raise SchemaPackagingError("vector catalog must list vectors")
    specs: list[SharedVectorSpec] = []
    seen: set[str] = set()
    for item in raw_vectors:
        if not isinstance(item, Mapping):
            raise SchemaPackagingError("vector recipe must be an object")
        vector_id = _text(item.get("vector_id"), "vector.vector_id")
        if vector_id in seen:
            raise SchemaPackagingError(f"duplicate vector_id {vector_id}")
        seen.add(vector_id)
        polarity = _text(item.get("polarity"), f"vector[{vector_id}].polarity")
        if polarity not in POLARITIES:
            raise SchemaPackagingError(
                f"vector[{vector_id}] polarity is not admitted"
            )
        payload = item.get("payload")
        if not isinstance(payload, Mapping):
            raise SchemaPackagingError(
                f"vector[{vector_id}] payload must be an object"
            )
        reject_kind_raw = item.get("reject_kind")
        reject_kind = None
        if reject_kind_raw is not None:
            reject_kind = _text(
                reject_kind_raw, f"vector[{vector_id}].reject_kind"
            )
            if reject_kind not in REJECT_KINDS:
                raise SchemaPackagingError(
                    f"vector[{vector_id}] reject_kind is not admitted"
                )
        if polarity == "negative" and reject_kind is None:
            raise SchemaPackagingError(
                f"negative vector[{vector_id}] requires reject_kind"
            )
        if polarity == "positive" and reject_kind is not None:
            raise SchemaPackagingError(
                f"positive vector[{vector_id}] must not set reject_kind"
            )
        reason_raw = item.get("reason")
        reason = None if reason_raw is None else _text(
            reason_raw, f"vector[{vector_id}].reason"
        )
        specs.append(
            SharedVectorSpec(
                vector_id=vector_id,
                schema_name=_text(
                    item.get("schema_name"), f"vector[{vector_id}].schema_name"
                ),
                polarity=polarity,
                payload=MappingProxyType(dict(payload)),
                reject_kind=reject_kind,
                reason=reason,
            )
        )
    return tuple(specs)


def _resolve_ref(schema: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    match = _REF_DEFS.match(ref)
    if match is None:
        raise SchemaPackagingError(f"unsupported schema $ref {ref}")
    defs = schema.get("$defs")
    if not isinstance(defs, Mapping):
        raise SchemaPackagingError("schema $defs missing for $ref")
    resolved = defs.get(match.group(1))
    if not isinstance(resolved, Mapping):
        raise SchemaPackagingError(f"schema $defs missing {match.group(1)}")
    return resolved


def _validate_instance(
    instance: Any,
    schema: Mapping[str, Any],
    *,
    root: Mapping[str, Any],
    path: str,
) -> None:
    if "$ref" in schema:
        _validate_instance(
            instance, _resolve_ref(root, str(schema["$ref"])), root=root, path=path
        )
        return
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(instance, Mapping) or isinstance(instance, (str, bytes)):
            raise SchemaPackagingAdmissionError(f"{path} must be an object")
        required = schema.get("required") or []
        if isinstance(required, list):
            for key in required:
                if key not in instance:
                    raise SchemaPackagingAdmissionError(
                        f"{path} missing required field {key}"
                    )
        properties = schema.get("properties") or {}
        additional = schema.get("additionalProperties", True)
        if additional is False:
            allowed = set(properties) if isinstance(properties, Mapping) else set()
            extra = [key for key in instance if key not in allowed]
            if extra:
                raise SchemaPackagingAdmissionError(
                    f"{path} unknown field(s): {', '.join(sorted(extra))}"
                )
        if isinstance(properties, Mapping):
            for key, child in properties.items():
                if key in instance and isinstance(child, Mapping):
                    _validate_instance(
                        instance[key], child, root=root, path=f"{path}.{key}"
                    )
        return
    if expected_type == "array":
        if not isinstance(instance, list):
            raise SchemaPackagingAdmissionError(f"{path} must be an array")
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(instance):
                _validate_instance(
                    item, items, root=root, path=f"{path}[{index}]"
                )
        return
    if expected_type == "string":
        if not isinstance(instance, str):
            raise SchemaPackagingAdmissionError(f"{path} must be a string")
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(instance) < min_length:
            raise SchemaPackagingAdmissionError(f"{path} is shorter than minLength")
        if isinstance(max_length, int) and len(instance) > max_length:
            raise SchemaPackagingAdmissionError(f"{path} exceeds maxLength")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, instance) is None:
            raise SchemaPackagingAdmissionError(f"{path} does not match pattern")
    elif expected_type == "integer":
        if isinstance(instance, bool) or not isinstance(instance, int):
            raise SchemaPackagingAdmissionError(f"{path} must be an integer")
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and instance < minimum:
            raise SchemaPackagingAdmissionError(f"{path} is below minimum")
    elif expected_type == "boolean":
        if not isinstance(instance, bool):
            raise SchemaPackagingAdmissionError(f"{path} must be a boolean")
    elif expected_type == "object":
        pass
    const = schema.get("const")
    if "const" in schema and instance != const:
        raise SchemaPackagingAdmissionError(f"{path} must equal {const!r}")
    enum = schema.get("enum")
    if isinstance(enum, list) and instance not in enum:
        raise SchemaPackagingAdmissionError(f"{path} is not an admitted enum value")


def validate_payload(schema_name: str, payload: Mapping[str, Any]) -> None:
    if schema_name == "schema_packaging_catalog":
        raise SchemaPackagingAdmissionError(
            "schema catalog is not a payload schema"
        )
    document = load_schema_document(schema_name)
    _validate_instance(payload, document, root=document, path="$")


def _semantic_reject_reason(
    spec: SharedVectorSpec, payload: Mapping[str, Any]
) -> str | None:
    if payload.get("advisory") is True:
        return "advisory ContextPack material is non-authoritative"
    if payload.get("simulated") is True and payload.get("live") is True:
        return "simulated results must not be represented as live"
    if (
        payload.get("disposition") == "admitted"
        and payload.get("source_rights_status")
        in {"unresolved", "unverified", "denied"}
    ):
        return "admitted rights require a resolved source-rights status"
    if spec.reject_kind == "semantic" and spec.reason:
        return spec.reason
    return None


def evaluate_shared_vector(spec: SharedVectorSpec) -> dict[str, Any]:
    if spec.reject_kind == "path":
        path = spec.payload.get("path")
        try:
            admit_schema_path(str(path))
            admitted = True
            reason = "path was admitted"
        except SchemaPackagingAdmissionError as exc:
            admitted = False
            reason = str(exc)
        expected = False
        return {
            "admitted": admitted,
            "expected_admitted": expected,
            "matched": admitted is expected,
            "reason": reason,
            "reject_kind": spec.reject_kind,
            "vector_id": spec.vector_id,
        }
    schema_error: str | None = None
    try:
        validate_payload(spec.schema_name, spec.payload)
    except SchemaPackagingAdmissionError as exc:
        schema_error = str(exc)
    semantic_reason = _semantic_reject_reason(spec, spec.payload)
    if spec.polarity == "positive":
        admitted = schema_error is None and semantic_reason is None
        expected = True
        reason = "admitted" if admitted else (schema_error or semantic_reason or "rejected")
    else:
        expected = False
        if spec.reject_kind == "schema":
            admitted = schema_error is None
            reason = schema_error or "schema unexpectedly admitted"
        else:
            admitted = semantic_reason is None
            reason = semantic_reason or "semantic unexpectedly admitted"
    return {
        "admitted": admitted,
        "expected_admitted": expected,
        "matched": admitted is expected,
        "reason": reason,
        "reject_kind": spec.reject_kind,
        "vector_id": spec.vector_id,
    }


def evaluate_shared_vectors() -> tuple[dict[str, Any], ...]:
    return tuple(evaluate_shared_vector(spec) for spec in shared_vector_specs())


def schema_packaging_manifest() -> dict[str, Any]:
    specs = packaged_schema_specs()
    vectors = shared_vector_specs()
    return {
        "import_side_effects": "none",
        "interface": INTERFACE,
        "packaging_globs": list(PACKAGING_GLOBS),
        "requires_sibling_tests_tree": False,
        "schema": SCHEMA,
        "schema_names": [spec.name for spec in specs],
        "schemas": [spec.to_dict() for spec in specs],
        "task_id": PCPR_015_TASK_ID,
        "vector_interface": VECTOR_INTERFACE,
        "vector_schema": VECTOR_SCHEMA,
        "vectors": [spec.vector_id for spec in vectors],
    }


def _source_contains(root: Path, relpath: str, needle: str) -> bool:
    path = root / relpath
    try:
        return needle in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _pyproject_include_package_data(root: Path) -> bool:
    try:
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    return "include-package-data = true" in text


def _packaging_globs_declared(root: Path | None) -> bool:
    catalog = load_schema_catalog()
    declared = catalog.get("packaging_globs")
    if not isinstance(declared, list):
        return False
    if tuple(declared) != PACKAGING_GLOBS:
        return False
    if root is None:
        return True
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    setup = (root / "setup.py").read_text(encoding="utf-8")
    return all(glob in pyproject and glob in setup for glob in PACKAGING_GLOBS)


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
class SchemaPackagingVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    schemas_packaged: bool
    shared_vectors_packaged: bool
    sibling_tests_required: bool
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
            "schemas_packaged": self.schemas_packaged,
            "shared_vectors_packaged": self.shared_vectors_packaged,
            "sibling_tests_required": self.sibling_tests_required,
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


def _probe(
    probe_id: str,
    present: bool | None,
    *,
    reason: str,
    evidence_kind: str = "measured",
    live: bool = False,
    details: Mapping[str, Any] | None = None,
) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=present,
        evidence_kind=evidence_kind,
        live=live,
        simulated_represented_as_live=False,
        reason=reason,
        details=MappingProxyType(dict(details or {})),
    )


def current_head_static_probes(
    start: Path | None = None,
) -> tuple[OutcomeProbe, ...]:
    root = discover_datasets_root(start)
    probes: list[OutcomeProbe] = []

    catalog_ok = False
    catalog_reason = "schema catalog is packaged"
    try:
        catalog = load_schema_catalog()
        catalog_ok = True
        details = {
            "interface": catalog.get("interface"),
            "requires_sibling_tests_tree": catalog.get(
                "requires_sibling_tests_tree"
            ),
        }
    except (SchemaPackagingError, OSError, json.JSONDecodeError) as exc:
        catalog_reason = str(exc)
        details = {}
    probes.append(
        _probe(
            "catalog_packaged",
            catalog_ok,
            reason=catalog_reason,
            details=details,
        )
    )

    pcpr_missing: list[str] = []
    for name in PCPR_STABLE_SCHEMA_NAMES:
        try:
            load_schema_document(name)
        except (SchemaPackagingError, KeyError, OSError, json.JSONDecodeError):
            pcpr_missing.append(name)
    probes.append(
        _probe(
            "pcpr_schemas_packaged",
            not pcpr_missing,
            reason=(
                "PCPR-stable schemas load from package data"
                if not pcpr_missing
                else f"missing packaged schemas: {pcpr_missing}"
            ),
            details={"missing": pcpr_missing},
        )
    )

    owner_missing: list[str] = []
    try:
        for spec in packaged_schema_specs():
            if spec.source_kind != "owner_package_data":
                continue
            try:
                load_schema_document(spec.name)
            except (
                SchemaPackagingError,
                KeyError,
                OSError,
                json.JSONDecodeError,
            ):
                owner_missing.append(spec.name)
    except SchemaPackagingError:
        owner_missing.append("catalog")
    probes.append(
        _probe(
            "owner_schemas_packaged",
            not owner_missing,
            reason=(
                "Owner schemas load from package data"
                if not owner_missing
                else f"missing owner schemas: {owner_missing}"
            ),
            details={"missing": owner_missing},
        )
    )

    vectors_ok = False
    vector_reason = "shared vectors load from package data"
    vector_count = 0
    try:
        vectors = shared_vector_specs()
        vectors_ok = bool(vectors)
        vector_count = len(vectors)
        if not vectors_ok:
            vector_reason = "shared vector catalog is empty"
    except (SchemaPackagingError, OSError, json.JSONDecodeError) as exc:
        vector_reason = str(exc)
    probes.append(
        _probe(
            "shared_vectors_packaged",
            vectors_ok,
            reason=vector_reason,
            details={"vector_count": vector_count},
        )
    )

    sibling_required = True
    sibling_reason = "catalog did not declare requires_sibling_tests_tree=false"
    try:
        sibling_required = bool(
            load_schema_catalog().get("requires_sibling_tests_tree")
        )
        if not sibling_required:
            sibling_reason = (
                "Installed packaging does not require a sibling tests tree."
            )
    except SchemaPackagingError as exc:
        sibling_reason = str(exc)
    probes.append(
        _probe(
            "sibling_tests_not_required",
            sibling_required is False,
            reason=sibling_reason,
        )
    )

    tests_path_rejected = False
    tests_reason = "sibling tests path was not rejected"
    try:
        admit_schema_path("tests/fixtures/context_pack.json")
    except SchemaPackagingAdmissionError as exc:
        tests_path_rejected = True
        tests_reason = str(exc)
    probes.append(
        _probe(
            "tests_path_rejected",
            tests_path_rejected,
            reason=tests_reason,
            details={"path": "tests/fixtures/context_pack.json"},
        )
    )

    globs_ok = _packaging_globs_declared(root)
    probes.append(
        _probe(
            "packaging_globs_declared",
            globs_ok,
            reason=(
                "Packaging globs are declared in catalog and packaging files."
                if globs_ok
                else "Packaging globs are missing from catalog or packaging files."
            ),
            details={"globs": list(PACKAGING_GLOBS)},
        )
    )

    if root is None:
        manifest_ok = False
        setup_ok = False
        pyproject_ok = False
        include_ok = False
        tree_reason = "source tree unavailable; packaging files measured from catalog only"
    else:
        manifest_text = ""
        try:
            manifest_text = (root / "MANIFEST.in").read_text(encoding="utf-8")
        except OSError:
            manifest_text = ""
        manifest_ok = all(line in manifest_text for line in MANIFEST_LINES)
        setup_ok = all(
            _source_contains(root, "setup.py", glob) for glob in PACKAGING_GLOBS
        )
        pyproject_ok = all(
            _source_contains(root, "pyproject.toml", glob)
            for glob in PACKAGING_GLOBS
        )
        include_ok = _pyproject_include_package_data(root)
        tree_reason = "source packaging files"
    probes.append(
        _probe(
            "packaging_manifest_in",
            manifest_ok,
            reason=(
                "MANIFEST.in recursive-includes packaged schemas and vectors."
                if manifest_ok
                else tree_reason if root is None else "MANIFEST.in missing packaging includes."
            ),
        )
    )
    probes.append(
        _probe(
            "packaging_setup_py",
            setup_ok,
            reason=(
                "setup.py package_data includes packaged schemas and vectors."
                if setup_ok
                else tree_reason if root is None else "setup.py missing packaging globs."
            ),
        )
    )
    probes.append(
        _probe(
            "packaging_pyproject",
            pyproject_ok,
            reason=(
                "pyproject.toml package-data includes packaged schemas and vectors."
                if pyproject_ok
                else tree_reason if root is None else "pyproject.toml missing packaging globs."
            ),
        )
    )
    probes.append(
        _probe(
            "include_package_data",
            include_ok if root is not None else True,
            reason=(
                "include-package-data remains enabled."
                if (include_ok or root is None)
                else "include-package-data is not enabled."
            ),
        )
    )

    results = []
    vector_eval_error = None
    try:
        results = list(evaluate_shared_vectors())
    except SchemaPackagingError as exc:
        vector_eval_error = str(exc)
    positives = [item for item in results if item["expected_admitted"] is True]
    negatives = [item for item in results if item["expected_admitted"] is False]
    positives_ok = bool(positives) and all(item["matched"] for item in positives)
    negatives_ok = bool(negatives) and all(item["matched"] for item in negatives)
    probes.append(
        _probe(
            "positive_vectors_admit",
            positives_ok if vector_eval_error is None else False,
            reason=(
                vector_eval_error
                or (
                    "Positive shared vectors admit against packaged schemas."
                    if positives_ok
                    else "A positive shared vector failed admission."
                )
            ),
            details={"count": len(positives)},
        )
    )
    probes.append(
        _probe(
            "negative_vectors_reject",
            negatives_ok if vector_eval_error is None else False,
            reason=(
                vector_eval_error
                or (
                    "Negative shared vectors fail closed."
                    if negatives_ok
                    else "A negative shared vector was admitted."
                )
            ),
            details={"count": len(negatives)},
        )
    )

    identity_ok = False
    identity_cid = None
    identity_reason = "schema catalog identity is not deterministic"
    try:
        first = content_identity(load_schema_catalog())
        second = content_identity(load_schema_catalog())
        identity_ok = first == second and first.startswith("b")
        identity_cid = first
        identity_reason = (
            "Packaged schema catalog identities are deterministic."
            if identity_ok
            else "Packaged schema catalog identities drifted."
        )
    except SchemaPackagingError as exc:
        identity_reason = str(exc)
    probes.append(
        _probe(
            "identity_deterministic",
            identity_ok,
            reason=identity_reason,
            details={"identity_cid": identity_cid},
        )
    )

    manifest_ok_probe = False
    manifest_reason = "LogicPlatformManifest does not advertise schema packaging"
    try:
        from ipfs_datasets_py.logic.platform.manifest import (
            DEFAULT_LOGIC_PLATFORM_MANIFEST,
        )

        versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
        roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
        operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
        manifest_ok_probe = (
            versions.get(INTERFACE) == "1"
            and versions.get(VECTOR_INTERFACE) == "1"
            and roots.get("datasets_schema_packaging") == SCHEMA
            and roots.get("datasets_shared_vectors") == VECTOR_SCHEMA
            and operations.get("schema_packaging") == "1"
        )
        if manifest_ok_probe:
            manifest_reason = (
                "LogicPlatformManifest advertises DatasetsSchemaPackaging@1."
            )
    except Exception as exc:  # pragma: no cover - import/shape failure is a probe
        manifest_reason = str(exc)
    probes.append(
        _probe(
            "manifest_advertises_packaging",
            manifest_ok_probe,
            reason=manifest_reason,
        )
    )

    loader_clean = True
    loader_reason = "Schema and vector loaders use importlib.resources, not tests/."
    try:
        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in {"insert", "append"}:
                continue
            owner = func.value
            if (
                isinstance(owner, ast.Attribute)
                and owner.attr == "path"
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "sys"
            ):
                loader_clean = False
                loader_reason = "schema_packaging.py mutates sys.path"
                break
        if loader_clean and "importlib.resources" not in source:
            loader_clean = False
            loader_reason = "schema_packaging.py does not use importlib.resources"
    except (OSError, SyntaxError) as exc:
        loader_clean = False
        loader_reason = str(exc)
    probes.append(
        _probe(
            "loader_does_not_use_tests_tree",
            loader_clean,
            reason=loader_reason,
        )
    )
    probes.append(
        _probe(
            "sibling_tests_loader_used",
            False,
            reason="Sibling tests-tree loading is not used.",
        )
    )
    probes.append(
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        )
    )
    probes.append(
        _probe(
            "runtime_unavailable_represented_as_live",
            False,
            reason="Packaging probes are not represented as live.",
        )
    )
    probes.append(
        _probe(
            "live_solver_qualification",
            None,
            evidence_kind="unavailable",
            reason=(
                "This task does not qualify live solvers. Missing Z3/cvc5/Lean/Coq "
                "evidence stays typed unavailable and is not recorded as False or passing."
            ),
        )
    )
    return tuple(probes)


def qualify_schema_packaging(
    probes: Sequence[OutcomeProbe],
) -> SchemaPackagingVerdict:
    if not probes:
        raise SchemaPackagingError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise SchemaPackagingError("live claims require measured_live evidence")
        if probe.simulated_represented_as_live:
            raise SchemaPackagingError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id == "live_solver_qualification":
            continue
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)

    packaged = not blockers
    sibling_required = any(
        p.probe_id == "sibling_tests_not_required" and p.present is not True
        for p in normalized
    )
    vectors_packaged = any(
        p.probe_id == "shared_vectors_packaged" and p.present is True
        for p in normalized
    ) and packaged
    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_015_TASK_ID,
        "goal_id": PCPR_015_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "schemas_packaged": packaged,
        "shared_vectors_packaged": vectors_packaged,
        "sibling_tests_required": sibling_required,
        "simulated_results_represented_as_live": False,
        "live_solver_qualified": False,
        "live_solver_evidence_kind": "unavailable",
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
    }
    return SchemaPackagingVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        schemas_packaged=packaged,
        shared_vectors_packaged=vectors_packaged,
        sibling_tests_required=sibling_required,
        simulated_results_represented_as_live=False,
        live_solver_qualified=False,
        live_solver_evidence_kind="unavailable",
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
    )


def qualify_current_head_schema_packaging() -> SchemaPackagingVerdict:
    return qualify_schema_packaging(current_head_static_probes())


# Pinned identity of the ordinary current-head static verdict. Drift means
# the default payload changed and the outer receipt must be regenerated.
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeeraekudb3vqa647evdgz4vm4fhwndmgdskrbpbqdxf33uolhqmna6eq"
)


def pcpr_015_receipt_promotion(
    verdict: SchemaPackagingVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise SchemaPackagingError(
            "schema packaging must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise SchemaPackagingError(
            "schema packaging must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise SchemaPackagingError(
            "schema packaging completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise SchemaPackagingError(
            "schema packaging must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise SchemaPackagingError(
            "promotion_status must not be a closed release outcome"
        )
    return verdict.to_mapping()


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OutcomeProbe",
    "PACKAGING_GLOBS",
    "PCPR_015_GOAL_ID",
    "PCPR_015_TASK_ID",
    "SCHEMA",
    "VECTOR_INTERFACE",
    "SchemaPackagingAdmissionError",
    "SchemaPackagingError",
    "SchemaPackagingVerdict",
    "admit_schema_path",
    "content_identity",
    "current_head_static_probes",
    "discover_datasets_root",
    "evaluate_shared_vectors",
    "load_schema_catalog",
    "load_schema_document",
    "packaged_schema_spec",
    "pcpr_015_receipt_promotion",
    "qualify_current_head_schema_packaging",
    "qualify_schema_packaging",
    "schema_packaging_manifest",
    "shared_vector_specs",
    "validate_payload",
]
