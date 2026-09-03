"""Fail-closed PCPR-061 Datasets-owned semantic ContextPack.

Datasets owns semantic ContextPack construction. This module inspects
the typed formal-logic API (LogicProviderProtocol@2), admits
DatasetsContextPack@1 from exact source CIDs, declares proof
obligations, selects impacted tests, and rejects stale-tree evidence.

It does not import sibling Accelerate or Kit packages, does not store
bytes or publish a current root (PCPR-062), does not write DuckDB or
Quack state, and does not admit the pack into a live supervisor
session. Live solver-backed impact stays typed unavailable. Simulated
results are not live.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.assurance.dependency_locks import (
    CLOSED_RELEASE_OUTCOMES,
    PACKAGE_NAME,
    PACKAGE_VERSION,
    SEALED_PATH,
    SEALED_PYTHON,
    content_identity,
    discover_datasets_root,
    pretty_json,
    sha256_bytes,
    typed_unavailable,
)
from ipfs_datasets_py.logic.ir_core.claims import ProofObligation
from ipfs_datasets_py.logic.ir_core.identity import cid_v1
from ipfs_datasets_py.proof_context.context_pack import (
    CANONICAL_INTERFACE,
    CANONICAL_SCHEMA,
    ContextPackAdmissionError,
    StaleContextError,
    UnavailableContextError,
    admit_datasets_context_pack,
)

INTERFACE: Final = "DatasetsSemanticContextPack@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/semantic-context-pack@1"
PACK_DOCUMENT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/declared-semantic-context-pack@1"
)
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/semantic-context-pack-verdict@1"
)
OWNER_INTERFACE: Final = "DatasetsContextPack@1"
OWNER_SCHEMA: Final = "ipfs_datasets_py/datasets-context-pack@1"
NORMATIVE_OBJECTIVE_SOURCE: Final = (
    "ipfs_accelerate_py/assurance/declared-reference-objective@1"
)
PCPR_061_TASK_ID: Final = "PCPR-061"
PCPR_061_GOAL_ID: Final = "PCPR-G700"
PCPR_062_TASK_ID: Final = "PCPR-062"
PCPR_060_TASK_ID: Final = "PCPR-060"
PCPR_014_TASK_ID: Final = "PCPR-014"
PCPR_013_TASK_ID: Final = "PCPR-013"
PCPR_001_TASK_ID: Final = "PCPR-001"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"
OBJECTIVE_KIND: Final = "declared_semantic_context_pack"
PORTFOLIO_ID: Final = "portfolio:pcpr-v1"
PORTFOLIO_VERSION: Final = "proof-carrying-platform-0.1.0"
LANGUAGE: Final = "Python"
OBJECTIVE_ID: Final = "PCPR-G700"
TASK_CLASS: Final = "typed_formal_logic_api_modification"
OPERATOR_BLOCKING_TASK_ID: Final = "pcpr-061-operator-live-context-pack-admission"
SOURCE_DATE_EPOCH: Final = "0"

PINNED_IDEA_DIGEST: Final = (
    "baguqeeracbayojdov4jmqiirx22pavrg6nabazcocru6y3scrdx5e54mw2zq"
)
PINNED_OBJECTIVE_CID: Final = (
    "baguqeeraynsn7tjr3iaggnreylzxo3akaooqwp5bf5oheaa6eubth2zwqeba"
)
PINNED_LOCK_CID: Final = (
    "baguqeerawsekbbbt5ccctjt4tydzeahfkahsatb6q5x7k6cy4inrii5lhqmq"
)

PACK_DIR_RELPATH: Final = "packaging/pcpr/reference-workflow/cpython312"
PACK_JSON_NAME: Final = "reference.context-pack.json"
PACK_README_RELPATH: Final = "packaging/pcpr/reference-workflow/CONTEXT_PACK.md"

REFERENCE_OBJECTIVE_IDEA: Final = (
    "Modify a typed formal-logic API while reusing unaffected proofs, "
    "selecting only impacted tests, rejecting stale-tree evidence, and "
    "producing a complete proof-carrying execution receipt."
)

TARGET_RELPATH: Final = "ipfs_datasets_py/logic/backends/protocol_v2.py"
SURROUNDING_RELPATH: Final = (
    "ipfs_datasets_py/assurance/logic_provider_protocol.py"
)
TEST_RELPATH: Final = "tests/unit/test_pcpr_013_logic_provider_protocol.py"
CAPSULE_RELPATHS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/assurance/semantic_apis.py",
    "ipfs_datasets_py/proof_context/context_pack.py",
    "ipfs_datasets_py/logic/ir_core/claims.py",
)
SELECTED_TESTS: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_013_logic_provider_protocol.py",
    "tests/unit/test_pcpr_014_semantic_apis.py",
)
REUSABLE_UNIMPACTED: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_017_solver_qualification.py",
    "ipfs_datasets_py/assurance/solver_qualification.py",
)
EXPECTED_PROTOCOL_METHODS: Final[tuple[str, ...]] = (
    "capability",
    "translate",
    "prove",
    "check",
    "reconstruct",
    "verify",
    "attest",
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_061_semantic_context_pack.py",
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

REQUIRED_GOOD_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "pack_files_match_generator",
        "pyproject_semantic_context_pack_table",
        "manifest_advertises_semantic_context_pack",
        "datasets_context_pack_admitted",
        "pack_cid_matches_pin",
        "objective_cid_matches_pin",
        "idea_digest_matches_pin",
        "semantic_impact_inspected",
        "stale_tree_rejected",
        "selected_tests_only",
        "unaffected_proofs_marked_reusable",
        "proof_obligations_declared_not_verified",
        "storage_deferred_to_pcpr_062",
        "duckdb_or_quack_not_written",
        "operator_blocking_task_emitted",
        "no_closed_release_outcome",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "simulated_results_represented_as_live",
        "live_context_pack_admission_represented_as_live",
        "live_solver_impact_represented_as_live",
        "closed_release_represented_as_live",
        "compatibility_identities_reminted",
        "sibling_import_observed",
        "current_root_published",
    }
)

PACK_README: Final = """# PCPR-061 Datasets semantic ContextPack

These files are the Datasets-owned *declared* semantic ContextPack for
the PCPR-060 reference idea:

    Modify a typed formal-logic API while reusing unaffected proofs,
    selecting only impacted tests, rejecting stale-tree evidence, and
    producing a complete proof-carrying execution receipt.

DatasetsContextPack@1 is minted from exact source CIDs of
LogicProviderProtocol@2, the PCPR-013 canonical cutover, and the
PCPR-013 hermetic tests. Capsules bind semantic APIs, the ContextPack
contract, and ProofObligation declarations. Semantic-impact inspection
is hermetic AST analysis. Live solver-backed impact, live supervisor
admission, DuckDB/Quack writes, and Kit current-root CAS are not
performed.

- `cpython312/reference.context-pack.json` is the declared pack
  document. Exact commit and tree are bound by the PCPR-061 receipt
  `current_tree_binding` because nested admission rewrites HEAD.
  `origin/main` is not the release identity.
- Durable storage and current-root CAS remain PCPR-062.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-061-operator-live-context-pack-admission`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
"""


class DatasetsSemanticContextPackError(ValueError):
    """Datasets ContextPack construction or identity error."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetsSemanticContextPackError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise DatasetsSemanticContextPackError(
            f"{name} is not an admitted evidence kind"
        )
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsSemanticContextPackError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def parse_pyproject_context_pack_table(text: str) -> dict[str, Any]:
    import tomllib

    table = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(table, dict):
        raise DatasetsSemanticContextPackError("pyproject.toml must be a table")
    tool = table.get("tool")
    payload: dict[str, Any] = {}
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            raw = datasets.get("semantic-context-pack")
            if isinstance(raw, dict):
                payload = dict(raw)
    return payload


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
class DatasetsSemanticContextPackVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    sibling_source_required: bool
    live_context_pack_admission: bool
    live_solver_impact: bool
    live_storage: bool
    operator_blocking_task: str
    simulated_results_represented_as_live: bool
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str
    pack_cid: str
    pack_document_cid: str
    objective_cid: str
    idea_digest: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "pack_cid": self.pack_cid,
            "pack_document_cid": self.pack_document_cid,
            "objective_cid": self.objective_cid,
            "idea_digest": self.idea_digest,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "sibling_source_required": self.sibling_source_required,
            "live_context_pack_admission": self.live_context_pack_admission,
            "live_solver_impact": self.live_solver_impact,
            "live_storage": self.live_storage,
            "operator_blocking_task": self.operator_blocking_task,
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
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


def _operator_blocking_task() -> dict[str, Any]:
    return {
        "task_id": OPERATOR_BLOCKING_TASK_ID,
        "status": "typed_blocked",
        "evidence_kind": "unavailable",
        "live": False,
        "applied": False,
        "requires": (
            "An admitted Quack-fenced state-owner session before the "
            "DatasetsContextPack@1 identity is admitted into live supervisor state"
        ),
        "action": (
            "Keep this declared pack identity. Do not write DuckDB or Quack "
            "state. PCPR-062 stores exact bytes and publishes the current root."
        ),
        "reason": (
            "Hermetic DatasetsContextPack@1 construction is not live supervisor "
            "admission. Sealed validation has no admitted Quack-fenced session."
        ),
    }


def _source_binding() -> dict[str, Any]:
    return {
        "kind": "git",
        "repository": "endomorphosis/ipfs_datasets_py",
        "binding": "current_head_not_mutable_main",
        "mutable_main_reference": False,
        "commit": {
            "status": "observed_at_evaluation",
            "evidence_kind": "measured",
            "live": False,
            "field": "PCPR-061 receipt current_tree_binding",
            "reason": (
                "Exact commit and tree are bound by the task receipt "
                "because nested admission rewrites HEAD."
            ),
        },
    }


def _measure_file(root: Path, relpath: str, role: str) -> dict[str, Any]:
    path = root / relpath
    if not path.is_file():
        raise DatasetsSemanticContextPackError(
            f"{role} source {relpath} is missing"
        )
    data = path.read_bytes()
    return {
        "role": role,
        "path": relpath,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "cid": cid_v1(data),
        "present": True,
        "live": False,
        "evidence_kind": "measured",
    }


def measure_pack_sources(root: Path) -> dict[str, Any]:
    target = _measure_file(root, TARGET_RELPATH, "target_source")
    surrounding = _measure_file(root, SURROUNDING_RELPATH, "surrounding_source")
    test = _measure_file(root, TEST_RELPATH, "test_source")
    capsules = [
        _measure_file(root, relpath, f"capsule_{index}")
        for index, relpath in enumerate(CAPSULE_RELPATHS)
    ]
    members = (target, surrounding, test, *capsules)
    tree_preimage = "\n".join(
        f"{item['path']}:{item['sha256']}" for item in members
    ).encode("utf-8")
    return {
        "target": target,
        "surrounding": surrounding,
        "test": test,
        "capsules": capsules,
        "scanned_tree_oid": sha256_bytes(tree_preimage),
        "evidence_kind": "measured",
    }


def inspect_semantic_impact(source_text: str) -> dict[str, Any]:
    """Hermetic AST inspection of LogicProviderProtocol@2. Not a live solver."""

    tree = ast.parse(_text(source_text, "target_source"))
    methods: list[str] = []
    aliases: list[str] = []
    protocol_classes: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in {
            "LogicProviderProtocolV2",
            "LogicProviderProtocol",
        }:
            protocol_classes.append(node.name)
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                    methods.append(item.name)
        if isinstance(node, ast.Assign):
            names = [
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            ]
            if "LogicProviderProtocol" in names:
                aliases.append("LogicProviderProtocol")
    unique_methods = tuple(dict.fromkeys(methods))
    return {
        "kind": "hermetic_ast",
        "target_interface": "LogicProviderProtocol@2",
        "protocol_classes": protocol_classes,
        "canonical_alias_present": "LogicProviderProtocol" in aliases
        or "LogicProviderProtocol" in protocol_classes,
        "impacted_methods": list(unique_methods),
        "expected_methods": list(EXPECTED_PROTOCOL_METHODS),
        "methods_match_expected": unique_methods == EXPECTED_PROTOCOL_METHODS,
        "impacted_symbols": [
            "LogicProviderProtocol",
            "LogicProviderProtocolV2",
            "admit_canonical_provider_request",
            "require_executable_bounds",
        ],
        "selected_tests": list(SELECTED_TESTS),
        "reusable_unimpacted": list(REUSABLE_UNIMPACTED),
        "stale_tree_policy": "reject",
        "live": False,
        "solver_backed": False,
        "evidence_kind": "measured_hermetic",
        "reason": (
            "AST inspection of the typed formal-logic API is hermetic. "
            "Live solver-backed semantic impact stays typed unavailable."
        ),
    }


def declared_proof_obligations() -> tuple[dict[str, Any], ...]:
    payloads = (
        {
            "obligation_id": "pcpr-061-free-form-cannot-mint-executable",
            "statement": (
                "Free-form payloads cannot mint executable BackendRequest "
                "values on LogicProviderProtocol@2."
            ),
            "logic_family": "typed-formal-logic",
            "source_refs": (TARGET_RELPATH,),
            "assumption_ids": (),
        },
        {
            "obligation_id": "pcpr-061-v1-adapter-explicit",
            "statement": (
                "The LogicProviderProtocol v1 adapter remains explicit and "
                "fail-closed; it is not a silent success path."
            ),
            "logic_family": "typed-formal-logic",
            "source_refs": (SURROUNDING_RELPATH,),
            "assumption_ids": (),
        },
        {
            "obligation_id": "pcpr-061-stale-tree-rejected",
            "statement": (
                "Stale-tree evidence cannot mint DatasetsContextPack@1."
            ),
            "logic_family": "typed-formal-logic",
            "source_refs": ("ipfs_datasets_py/proof_context/context_pack.py",),
            "assumption_ids": (),
        },
        {
            "obligation_id": "pcpr-061-selected-tests-only",
            "statement": (
                "Only impacted tests are selected for this typed-API "
                "modification; the full suite is not implied."
            ),
            "logic_family": "typed-formal-logic",
            "source_refs": SELECTED_TESTS,
            "assumption_ids": (),
        },
        {
            "obligation_id": "pcpr-061-unaffected-proofs-reusable",
            "statement": (
                "Unaffected solver-qualification proofs remain reusable and "
                "are not invalidated by this ContextPack."
            ),
            "logic_family": "typed-formal-logic",
            "source_refs": REUSABLE_UNIMPACTED,
            "assumption_ids": (),
        },
    )
    admitted: list[dict[str, Any]] = []
    for payload in payloads:
        obligation = ProofObligation.from_dict(payload)
        record = obligation.to_dict()
        record["digest"] = obligation.digest
        record["verified"] = False
        record["live"] = False
        record["evidence_kind"] = "measured"
        record["verification"] = typed_unavailable(
            reason=(
                "ProofObligation@1 is a declaration. Live solver verification "
                "was not performed and is not represented as passing."
            )
        )
        admitted.append(record)
    return tuple(admitted)


def _stale_rejected(sources: Mapping[str, Any]) -> bool:
    payload = {
        "repository_state_cid": sources["target"]["cid"],
        "scanned_tree_oid": sources["scanned_tree_oid"],
        "surrounding_source_cid": sources["surrounding"]["cid"],
        "target_source_cid": sources["target"]["cid"],
        "test_source_cid": sources["test"]["cid"],
        "task_id": PCPR_061_TASK_ID,
        "freshness": "stale",
    }
    try:
        admit_datasets_context_pack(payload)
    except StaleContextError:
        return True
    except (ContextPackAdmissionError, UnavailableContextError):
        return False
    return False


def mint_datasets_context_pack(root: Path) -> dict[str, Any]:
    sources = measure_pack_sources(root)
    repository_state_cid = content_identity(
        {
            "idea_digest": PINNED_IDEA_DIGEST,
            "objective_cid": PINNED_OBJECTIVE_CID,
            "scanned_tree_oid": sources["scanned_tree_oid"],
            "task_id": PCPR_061_TASK_ID,
        }
    )
    request = {
        "interface": CANONICAL_INTERFACE,
        "schema": CANONICAL_SCHEMA,
        "repository_state_cid": repository_state_cid,
        "scanned_tree_oid": sources["scanned_tree_oid"],
        "source_tree_oid": sources["scanned_tree_oid"],
        "surrounding_source_cid": sources["surrounding"]["cid"],
        "target_source_cid": sources["target"]["cid"],
        "test_source_cid": sources["test"]["cid"],
        "capsule_cids": [item["cid"] for item in sources["capsules"]],
        "task_id": PCPR_061_TASK_ID,
        "task_class": TASK_CLASS,
        "freshness": "fresh",
        "opaque": False,
        "executable": False,
        "advisory": False,
    }
    pack = admit_datasets_context_pack(request)
    identity = pack.identity_payload()
    replay = admit_datasets_context_pack(request)
    return {
        "pack_cid": pack.pack_cid,
        "deterministic": pack.pack_cid == replay.pack_cid,
        "repository_state_cid": pack.repository_state_cid,
        "scanned_tree_oid": pack.scanned_tree_oid,
        "task_id": pack.task_id,
        "task_class": pack.task_class,
        "freshness": pack.freshness,
        "opaque": pack.opaque,
        "capsule_cids": list(pack.capsule_cids),
        "required_source_cids": dict(pack.required_source_cids),
        "interface": pack.interface,
        "schema": pack.schema,
        "producer": pack.producer,
        "identity": identity,
        "sources": sources,
        "stale_rejected": _stale_rejected(sources),
        "constructed": True,
        "live": False,
        "admitted_live": False,
        "evidence_kind": "measured",
    }


def render_declared_context_pack(root: Path | None = None) -> dict[str, Any]:
    package_root = root or discover_datasets_root()
    if package_root is None:
        raise DatasetsSemanticContextPackError(
            "Datasets package root was not found"
        )
    minted = mint_datasets_context_pack(package_root)
    target_text = (package_root / TARGET_RELPATH).read_text(encoding="utf-8")
    impact = inspect_semantic_impact(target_text)
    obligations = declared_proof_obligations()
    document = {
        "schema": PACK_DOCUMENT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_061_TASK_ID,
        "goal_id": PCPR_061_GOAL_ID,
        "program_id": PCPR_PROGRAM_ID,
        "owner_repository": OWNER_REPOSITORY,
        "normative_objective_source": NORMATIVE_OBJECTIVE_SOURCE,
        "owner_interface": OWNER_INTERFACE,
        "owner_schema": OWNER_SCHEMA,
        "portfolio_id": PORTFOLIO_ID,
        "portfolio_version": PORTFOLIO_VERSION,
        "objective_kind": OBJECTIVE_KIND,
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "language": LANGUAGE,
        "objective_id": OBJECTIVE_ID,
        "idea": REFERENCE_OBJECTIVE_IDEA,
        "idea_digest": PINNED_IDEA_DIGEST,
        "objective_cid": PINNED_OBJECTIVE_CID,
        "lock_cid": PINNED_LOCK_CID,
        "prerequisite_task_id": PCPR_060_TASK_ID,
        "context_pack": {
            "task_id": PCPR_061_TASK_ID,
            "interface": minted["interface"],
            "schema": minted["schema"],
            "pack_cid": minted["pack_cid"],
            "repository_state_cid": minted["repository_state_cid"],
            "scanned_tree_oid": minted["scanned_tree_oid"],
            "required_source_cids": minted["required_source_cids"],
            "capsule_cids": minted["capsule_cids"],
            "task_class": minted["task_class"],
            "freshness": minted["freshness"],
            "opaque": minted["opaque"],
            "producer": minted["producer"],
            "deterministic": minted["deterministic"],
            "constructed": True,
            "live": False,
            "admitted_live": False,
            "stored": False,
            "current_root_published": False,
            "evidence_kind": "measured",
        },
        "sources": {
            "target": minted["sources"]["target"],
            "surrounding": minted["sources"]["surrounding"],
            "test": minted["sources"]["test"],
            "capsules": minted["sources"]["capsules"],
            "scanned_tree_oid": minted["sources"]["scanned_tree_oid"],
        },
        "semantic_impact": impact,
        "proof_obligations": [dict(item) for item in obligations],
        "selected_tests": list(SELECTED_TESTS),
        "reusable_unimpacted": list(REUSABLE_UNIMPACTED),
        "stale_tree_rejected": minted["stale_rejected"],
        "storage": {
            "task_id": PCPR_062_TASK_ID,
            "stored": False,
            "current_root_published": False,
            "live": False,
            "deferred": True,
            "reason": "Durable ContextPack storage remains PCPR-062.",
        },
        "materialization": {
            "kind": "declared_context_pack_not_live_admission",
            "admitted": False,
            "live": False,
            "applied": False,
            "duckdb_or_quack_state_written": False,
            "evidence_kind": "unavailable",
        },
        "live_solver_impact": typed_unavailable(
            reason=(
                "Sealed PATH has no admitted live solver session for "
                "semantic-impact proofs. AST inspection is not live proving."
            )
        ),
        "live_context_pack_admission": typed_unavailable(
            reason=(
                "No admitted Quack-fenced supervisor session was observed. "
                "Declared DatasetsContextPack@1 is not live admission."
            )
        ),
        "source": _source_binding(),
        "operator_blocking_task": _operator_blocking_task(),
        "live": False,
        "applied": False,
        "submitted_live": False,
        "release_claim": False,
        "closed_release_outcome": None,
        "contracts_frozen": False,
        "hashes_invented": False,
        "signatures_invented": False,
        "sibling_source_required": False,
        "this_task_created_competing_authority": False,
        "duckdb_or_quack_state_written": False,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "evidence_kind": "measured",
    }
    document["pack_document_cid"] = content_identity(
        {key: value for key, value in document.items() if key != "pack_document_cid"}
    )
    return document


def refuse_pack_cid_remint(cid: str) -> str:
    if cid != PINNED_PACK_CID:
        raise DatasetsSemanticContextPackError(
            f"ContextPack CID {cid} remints {PINNED_PACK_CID}"
        )
    return cid


def refuse_objective_remint(cid: str) -> str:
    if cid != PINNED_OBJECTIVE_CID:
        raise DatasetsSemanticContextPackError(
            f"objective CID {cid} remints {PINNED_OBJECTIVE_CID}"
        )
    return cid


def refuse_idea_digest_remint(cid: str) -> str:
    if cid != PINNED_IDEA_DIGEST:
        raise DatasetsSemanticContextPackError(
            f"idea digest {cid} remints {PINNED_IDEA_DIGEST}"
        )
    return cid


def artifact_paths(root: Path) -> dict[str, Path]:
    return {
        "pack": root / PACK_DIR_RELPATH / PACK_JSON_NAME,
        "readme": root / PACK_README_RELPATH,
    }


def write_semantic_context_pack_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsSemanticContextPackError(
            "Datasets package root was not found"
        )
    document = render_declared_context_pack(root)
    paths = artifact_paths(root)
    _atomic_write(paths["pack"], pretty_json(document))
    readme = PACK_README if PACK_README.endswith("\n") else PACK_README + "\n"
    _atomic_write(paths["readme"], readme)
    return {
        "document": document,
        "paths": {name: str(path) for name, path in paths.items()},
    }


def verify_semantic_context_pack_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsSemanticContextPackError(
            "Datasets package root was not found"
        )
    document = render_declared_context_pack(root)
    paths = artifact_paths(root)
    missing: list[str] = []
    pack_ok = False
    readme_ok = False
    expected_readme = PACK_README if PACK_README.endswith("\n") else PACK_README + "\n"
    for name, path in paths.items():
        if not path.is_file():
            missing.append(name)
            continue
        if name == "pack":
            pack_ok = json.loads(path.read_text(encoding="utf-8")) == document
        elif name == "readme":
            readme_ok = path.read_text(encoding="utf-8") == expected_readme
    return {
        "ok": not missing and pack_ok and readme_ok,
        "missing": missing,
        "pack_ok": pack_ok,
        "readme_ok": readme_ok,
        "pack_cid": document["context_pack"]["pack_cid"],
        "pack_document_cid": document["pack_document_cid"],
        "objective_cid": document["objective_cid"],
        "idea_digest": document["idea_digest"],
        "pack_sha256": (
            sha256_bytes(paths["pack"].read_bytes())
            if paths["pack"].is_file()
            else "unavailable"
        ),
    }


def current_head_static_probes(
    start: Path | None = None,
) -> tuple[OutcomeProbe, ...]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsSemanticContextPackError(
            "Datasets package root was not found"
        )
    document = render_declared_context_pack(root)
    verified = verify_semantic_context_pack_files(root)
    table = parse_pyproject_context_pack_table(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST

    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    schema_roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
    operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
    remint = (
        document["context_pack"]["pack_cid"] != PINNED_PACK_CID
        or document["objective_cid"] != PINNED_OBJECTIVE_CID
        or document["idea_digest"] != PINNED_IDEA_DIGEST
        or document["lock_cid"] != PINNED_LOCK_CID
    )
    pack = document["context_pack"]
    impact = document["semantic_impact"]
    probes = [
        _probe(
            "pack_files_match_generator",
            verified.get("ok") is True and verified.get("pack_ok") is True,
            reason=(
                "Committed Datasets ContextPack matches the generator."
                if verified.get("pack_ok") is True
                else "Committed Datasets ContextPack is missing or drifts."
            ),
        ),
        _probe(
            "pyproject_semantic_context_pack_table",
            table.get("interface") == INTERFACE
            and table.get("schema") == SCHEMA
            and table.get("task-id") == PCPR_061_TASK_ID
            and table.get("objective-kind") == OBJECTIVE_KIND,
            reason=(
                "pyproject.toml declares DatasetsSemanticContextPack@1."
                if table.get("interface") == INTERFACE
                else "pyproject.toml does not declare DatasetsSemanticContextPack@1."
            ),
        ),
        _probe(
            "manifest_advertises_semantic_context_pack",
            versions.get(INTERFACE) == "1"
            and schema_roots.get("datasets_semantic_context_pack") == SCHEMA
            and operations.get("semantic_context_pack") == "1"
            and DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False,
            reason="LogicPlatformManifest advertises DatasetsSemanticContextPack@1.",
        ),
        _probe(
            "datasets_context_pack_admitted",
            pack["constructed"] is True
            and pack["interface"] == OWNER_INTERFACE
            and pack["schema"] == OWNER_SCHEMA
            and pack["deterministic"] is True
            and pack["live"] is False,
            reason="DatasetsContextPack@1 is admitted from exact source CIDs.",
        ),
        _probe(
            "pack_cid_matches_pin",
            pack["pack_cid"] == PINNED_PACK_CID,
            reason="The Datasets-owned ContextPack CID is pinned and not reminted.",
        ),
        _probe(
            "objective_cid_matches_pin",
            document["objective_cid"] == PINNED_OBJECTIVE_CID,
            reason="The PCPR-060 objective CID is bound without remint.",
        ),
        _probe(
            "idea_digest_matches_pin",
            document["idea_digest"] == PINNED_IDEA_DIGEST,
            reason="The PCPR-060 idea digest is bound without remint.",
        ),
        _probe(
            "semantic_impact_inspected",
            impact["kind"] == "hermetic_ast"
            and impact["methods_match_expected"] is True
            and impact["live"] is False
            and impact["solver_backed"] is False,
            reason="Hermetic AST inspection covers LogicProviderProtocol@2.",
        ),
        _probe(
            "stale_tree_rejected",
            document["stale_tree_rejected"] is True,
            reason="Stale-tree evidence cannot mint DatasetsContextPack@1.",
        ),
        _probe(
            "selected_tests_only",
            document["selected_tests"] == list(SELECTED_TESTS)
            and TEST_RELPATH in document["selected_tests"],
            reason="Only impacted tests are selected for this modification.",
        ),
        _probe(
            "unaffected_proofs_marked_reusable",
            document["reusable_unimpacted"] == list(REUSABLE_UNIMPACTED),
            reason="Unaffected solver-qualification proofs remain reusable.",
        ),
        _probe(
            "proof_obligations_declared_not_verified",
            bool(document["proof_obligations"])
            and all(
                item.get("verified") is False and item.get("live") is False
                for item in document["proof_obligations"]
            ),
            reason="ProofObligation@1 records are declarations, not live proofs.",
        ),
        _probe(
            "storage_deferred_to_pcpr_062",
            document["storage"]["task_id"] == PCPR_062_TASK_ID
            and document["storage"]["stored"] is False
            and document["storage"]["current_root_published"] is False,
            reason="Durable storage and current-root CAS remain PCPR-062.",
        ),
        _probe(
            "current_root_published",
            False,
            reason="This task must not publish a current ContextPack root.",
        ),
        _probe(
            "duckdb_or_quack_not_written",
            document["duckdb_or_quack_state_written"] is False
            and document["materialization"]["duckdb_or_quack_state_written"] is False,
            reason="This task does not write DuckDB or Quack state.",
        ),
        _probe(
            "operator_blocking_task_emitted",
            document["operator_blocking_task"]["task_id"] == OPERATOR_BLOCKING_TASK_ID
            and document["operator_blocking_task"]["status"] == "typed_blocked",
            reason="Missing live admission emits the operator-blocking task.",
        ),
        _probe(
            "no_closed_release_outcome",
            document["closed_release_outcome"] is None
            and document["release_claim"] is False,
            reason="This task does not emit a closed PCPR release outcome.",
        ),
        _probe(
            "compatibility_identities_reminted",
            remint,
            reason="A reminted pack, objective, idea, or lock CID is forbidden.",
        ),
        _probe(
            "sibling_import_observed",
            False,
            reason="This builder does not import sibling Accelerate or Kit packages.",
        ),
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        ),
        _probe(
            "live_context_pack_admission_represented_as_live",
            False,
            reason="Declared construction is not live supervisor admission.",
        ),
        _probe(
            "live_solver_impact_represented_as_live",
            False,
            reason="Hermetic AST inspection is not live solver-backed impact.",
        ),
        _probe(
            "closed_release_represented_as_live",
            False,
            reason="This task does not publish a PCPR release.",
        ),
        _probe(
            "live_context_pack_admission",
            None,
            evidence_kind="unavailable",
            reason="Live supervisor ContextPack admission was not performed.",
        ),
        _probe(
            "live_solver_impact",
            None,
            evidence_kind="unavailable",
            reason="Live solver-backed semantic impact stays typed unavailable.",
        ),
    ]
    return tuple(probes)


def qualify_semantic_context_pack(
    probes: Sequence[OutcomeProbe],
    *,
    pack_cid: str,
    pack_document_cid: str,
    objective_cid: str,
    idea_digest_cid: str,
) -> DatasetsSemanticContextPackVerdict:
    if not probes:
        raise DatasetsSemanticContextPackError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise DatasetsSemanticContextPackError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise DatasetsSemanticContextPackError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)

    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_061_TASK_ID,
        "goal_id": PCPR_061_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": False,
        "live_context_pack_admission": False,
        "live_solver_impact": False,
        "live_storage": False,
        "operator_blocking_task": OPERATOR_BLOCKING_TASK_ID,
        "simulated_results_represented_as_live": False,
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
        "pack_cid": pack_cid,
        "pack_document_cid": pack_document_cid,
        "objective_cid": objective_cid,
        "idea_digest": idea_digest_cid,
    }
    return DatasetsSemanticContextPackVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        sibling_source_required=False,
        live_context_pack_admission=False,
        live_solver_impact=False,
        live_storage=False,
        operator_blocking_task=OPERATOR_BLOCKING_TASK_ID,
        simulated_results_represented_as_live=False,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
        pack_cid=pack_cid,
        pack_document_cid=pack_document_cid,
        objective_cid=objective_cid,
        idea_digest=idea_digest_cid,
    )


def qualify_current_head_semantic_context_pack(
    start: Path | None = None,
) -> DatasetsSemanticContextPackVerdict:
    document = render_declared_context_pack(start)
    return qualify_semantic_context_pack(
        current_head_static_probes(start),
        pack_cid=str(document["context_pack"]["pack_cid"]),
        pack_document_cid=str(document["pack_document_cid"]),
        objective_cid=str(document["objective_cid"]),
        idea_digest_cid=str(document["idea_digest"]),
    )


def pcpr_061_receipt_promotion(
    verdict: DatasetsSemanticContextPackVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise DatasetsSemanticContextPackError(
            "semantic ContextPack must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise DatasetsSemanticContextPackError(
            "semantic ContextPack must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise DatasetsSemanticContextPackError(
            "semantic ContextPack completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise DatasetsSemanticContextPackError(
            "semantic ContextPack must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsSemanticContextPackError(
            "promotion_status must not be a closed release outcome"
        )
    if verdict.live_context_pack_admission or verdict.live_solver_impact:
        raise DatasetsSemanticContextPackError(
            "live ContextPack admission and solver impact require measured_live evidence"
        )
    if verdict.live_storage:
        raise DatasetsSemanticContextPackError(
            "durable storage remains PCPR-062"
        )
    return verdict.to_mapping()


# Pinned after the encoder is measured. Drift is a remint.
PINNED_PACK_CID: Final = (
    "bafkreih72d3nncekez43wmtlczq5mdtymzniluujypwybpgu3mtt7i4v2e"
)
PINNED_PACK_DOCUMENT_CID: Final = (
    "baguqeera5ykn6pm3xvty6taigxxjtnguutg7oznw4ez52jv676igcif4wkda"
)
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeerabzzftwdkmqkpfn7fhbeutohsy2qf2iojeexux6hmhomsvwaj6zsq"
)


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "DatasetsSemanticContextPackError",
    "DatasetsSemanticContextPackVerdict",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OPERATOR_BLOCKING_TASK_ID",
    "OBJECTIVE_KIND",
    "OutcomeProbe",
    "PCPR_061_GOAL_ID",
    "PCPR_061_TASK_ID",
    "PINNED_IDEA_DIGEST",
    "PINNED_LOCK_CID",
    "PINNED_OBJECTIVE_CID",
    "PINNED_PACK_CID",
    "PINNED_PACK_DOCUMENT_CID",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "current_head_static_probes",
    "pcpr_061_receipt_promotion",
    "qualify_current_head_semantic_context_pack",
    "qualify_semantic_context_pack",
    "refuse_idea_digest_remint",
    "refuse_objective_remint",
    "refuse_pack_cid_remint",
    "render_declared_context_pack",
    "verify_semantic_context_pack_files",
    "write_semantic_context_pack_files",
]
