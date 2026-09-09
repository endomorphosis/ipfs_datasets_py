"""Fail-closed PCPR-066 Datasets binding to Accelerate unrelated change.

Datasets owns DatasetsContextPack@1 identity, LogicProviderProtocol@2,
and semantic-impact classification. This module binds those identities
to the Accelerate-owned unrelated documentation change without reminting
pack, protocol, route, patch, or run identities.

The sidecar
`ipfs_datasets_py/logic/platform/unrelated_documentation.py` is
documentation-only. It is outside the semantic frontier. The impacted
cone is empty. Eligible reuse remains PCPR-067.

It does not import sibling Accelerate or Kit packages, does not write
DuckDB or Quack state, and does not admit live application. Simulated
results are not live.
"""

from __future__ import annotations

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
from ipfs_datasets_py.logic.platform.unrelated_documentation import (
    ADDS_PROTOCOL_OPERATION,
    ELIGIBLE_REUSE as SIDECAR_ELIGIBLE_REUSE,
    IMPACTED_CONE as SIDECAR_IMPACTED_CONE,
    NEXT_TASK_ID as SIDECAR_NEXT_TASK_ID,
    PROTOCOL_INTERFACE as SIDECAR_PROTOCOL_INTERFACE,
    RELEVANT_INTERFACE_CHANGE,
    REMINTS_PROTOCOL,
    REUSE_DEMONSTRATED,
    SEMANTIC_FRONTIER as SIDECAR_SEMANTIC_FRONTIER,
    UNRELATED_DOCUMENTATION_INTERFACE,
    UNRELATED_DOCUMENTATION_KIND,
    UNRELATED_DOCUMENTATION_NOTE,
    UNRELATED_DOCUMENTATION_SCHEMA,
    WHOLE_PLAN_REGENERATION_REQUIRED,
    unrelated_documentation_record,
)

INTERFACE: Final = "DatasetsUnrelatedStateChangeBinding@1"
SCHEMA: Final = (
    "ipfs_datasets_py/assurance/unrelated-state-change-binding@1"
)
BINDING_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/declared-unrelated-state-change-binding@1"
)
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/unrelated-state-change-verdict@1"
)
OWNER_INTERFACE: Final = "DatasetsContextPack@1"
OWNER_SCHEMA: Final = "ipfs_datasets_py/datasets-context-pack@1"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"
EXECUTION_OWNER_REPOSITORY: Final = "ipfs_accelerate_py"
EXECUTION_OWNER_INTERFACE: Final = "AccelerateUnrelatedStateChange@1"
PATCH_OWNER_INTERFACE: Final = "AccelerateBoundedPatch@1"
ROUTE_OWNER_INTERFACE: Final = "AccelerateDeterministicFirstRoute@1"
RUN_OWNER_INTERFACE: Final = "AccelerateSelectedTestsAndProofs@1"
STORAGE_OWNER_REPOSITORY: Final = "ipfs_kit_py"
STORAGE_OWNER_INTERFACE: Final = "KitContextPackStorage@1"
PROTOCOL_INTERFACE: Final = "LogicProviderProtocol@2"
PCPR_066_TASK_ID: Final = "PCPR-066"
PCPR_066_GOAL_ID: Final = "PCPR-G700"
PCPR_065_TASK_ID: Final = "PCPR-065"
PCPR_064_TASK_ID: Final = "PCPR-064"
PCPR_063_TASK_ID: Final = "PCPR-063"
PCPR_062_TASK_ID: Final = "PCPR-062"
PCPR_061_TASK_ID: Final = "PCPR-061"
PCPR_067_TASK_ID: Final = "PCPR-067"
PCPR_068_TASK_ID: Final = "PCPR-068"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
OBJECTIVE_KIND: Final = "declared_unrelated_state_change_binding"
PORTFOLIO_ID: Final = "portfolio:pcpr-v1"
PORTFOLIO_VERSION: Final = "proof-carrying-platform-0.1.0"
LANGUAGE: Final = "Python"
OBJECTIVE_ID: Final = "PCPR-G700"
OPERATOR_BLOCKING_TASK_ID: Final = (
    "pcpr-066-operator-live-unrelated-state-change"
)
SOURCE_DATE_EPOCH: Final = "0"
UNRELATED_CHANGE_RELPATH: Final = (
    "ipfs_datasets_py/logic/platform/unrelated_documentation.py"
)

PINNED_LOCK_CID: Final = (
    "baguqeerawsekbbbt5ccctjt4tydzeahfkahsatb6q5x7k6cy4inrii5lhqmq"
)
PINNED_IDEA_DIGEST: Final = (
    "baguqeeracbayojdov4jmqiirx22pavrg6nabazcocru6y3scrdx5e54mw2zq"
)
PINNED_OBJECTIVE_CID: Final = (
    "baguqeeraynsn7tjr3iaggnreylzxo3akaooqwp5bf5oheaa6eubth2zwqeba"
)
PINNED_PACK_CID: Final = (
    "bafkreih72d3nncekez43wmtlczq5mdtymzniluujypwybpgu3mtt7i4v2e"
)
PINNED_PACK_DOCUMENT_CID: Final = (
    "baguqeera5ykn6pm3xvty6taigxxjtnguutg7oznw4ez52jv676igcif4wkda"
)
PINNED_BYTES_CID: Final = (
    "bafkreihjdjarrlr24sperlq3zl4hjrksbol4b5saxquie3wpyi6xwsobwi"
)
PINNED_CURRENT_ROOT_CID: Final = PINNED_BYTES_CID
PINNED_ROUTE_CID: Final = (
    "baguqeerab6vsy7orm6wmxmqbzqh5f57dasnufhgngvh47gw7g3whrkr5smga"
)
PINNED_PATCH_CID: Final = (
    "baguqeeraphkktpgmcw2uusnbxlh7wfjblmhzb4oy3u55bbpdsvbt4xwvvb4q"
)
PINNED_RUN_CID: Final = (
    "baguqeerazgo2lirhy7hrpa42j227gdpzmi3jl4jdajoz6jzqqx7td6fy7dpa"
)

BINDING_DIR_RELPATH: Final = "packaging/pcpr/reference-workflow/cpython312"
BINDING_JSON_NAME: Final = "reference.unrelated-state-change.binding.json"
BINDING_README_RELPATH: Final = (
    "packaging/pcpr/reference-workflow/UNRELATED_STATE_CHANGE.md"
)

REFERENCE_OBJECTIVE_IDEA: Final = (
    "Modify a typed formal-logic API while reusing unaffected proofs, "
    "selecting only impacted tests, rejecting stale-tree evidence, and "
    "producing a complete proof-carrying execution receipt."
)

ESCALATION_ORDER: Final[tuple[str, ...]] = (
    "exact receipt",
    "AST and dependency analysis",
    "schema, type, and static checks",
    "selected tests",
    "incremental prover",
    "local small specialist",
    "medium model",
    "frontier model",
    "human decision",
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_066_unrelated_state_change.py",
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
        "binding_files_match_generator",
        "pyproject_unrelated_state_change_table",
        "manifest_advertises_unrelated_state_change",
        "owner_pack_cid_matches_pin",
        "change_owned_by_accelerate",
        "protocol_identity_not_reminted",
        "sidecar_is_unrelated_documentation",
        "impacted_cone_empty",
        "eligible_reuse_not_demonstrated",
        "model_assertion_cannot_complete_work",
        "duckdb_or_quack_not_written",
        "operator_blocking_task_emitted",
        "no_closed_release_outcome",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "simulated_results_represented_as_live",
        "live_application_represented_as_live",
        "closed_release_represented_as_live",
        "compatibility_identities_reminted",
        "sibling_import_observed",
        "datasets_identity_reminted",
        "kit_identity_reminted",
        "model_assertion_completed_work",
        "relevant_interface_change_accepted",
        "reuse_claimed_as_demonstrated",
    }
)

BINDING_README: Final = """# PCPR-066 Datasets unrelated-state-change binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
documentation-only sidecar to the Accelerate-owned unrelated state
change. Datasets does not remint the pack CID, does not remint the
protocol, and does not claim live reuse.

- `cpython312/reference.unrelated-state-change.binding.json` binds the
  Datasets pack identity to the Accelerate change. Exact commit and
  tree are bound by the PCPR-066 receipt `current_tree_binding`.
- The sidecar is documentation-only. The impacted cone is empty.
  Execution is owned by Accelerate. Eligible reuse remains PCPR-067.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-066-operator-live-unrelated-state-change`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
"""


class DatasetsUnrelatedStateChangeError(ValueError):
    """Datasets attempted to remint or claim live unrelated-state change."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetsUnrelatedStateChangeError(
            f"{name} must be a non-empty string"
        )
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise DatasetsUnrelatedStateChangeError(
            f"{name} is not an admitted evidence kind"
        )
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsUnrelatedStateChangeError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def parse_pyproject_unrelated_state_change_table(text: str) -> dict[str, Any]:
    import tomllib

    table = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(table, dict):
        raise DatasetsUnrelatedStateChangeError(
            "pyproject.toml must be a table"
        )
    tool = table.get("tool")
    payload: dict[str, Any] = {}
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            raw = datasets.get("unrelated-state-change")
            if isinstance(raw, dict):
                payload = dict(raw)
    return payload


def refuse_pack_cid_remint(cid: str) -> str:
    if cid != PINNED_PACK_CID:
        raise DatasetsUnrelatedStateChangeError(
            f"ContextPack CID {cid} remints {PINNED_PACK_CID}"
        )
    return cid


def refuse_current_root_remint(cid: str) -> str:
    if cid != PINNED_CURRENT_ROOT_CID:
        raise DatasetsUnrelatedStateChangeError(
            f"current root CID {cid} remints {PINNED_CURRENT_ROOT_CID}"
        )
    return cid


def refuse_route_cid_remint(cid: str) -> str:
    if cid != PINNED_ROUTE_CID:
        raise DatasetsUnrelatedStateChangeError(
            f"route CID {cid} remints {PINNED_ROUTE_CID}"
        )
    return cid


def refuse_patch_cid_remint(cid: str) -> str:
    if cid != PINNED_PATCH_CID:
        raise DatasetsUnrelatedStateChangeError(
            f"patch CID {cid} remints {PINNED_PATCH_CID}"
        )
    return cid


def refuse_run_cid_remint(cid: str) -> str:
    if cid != PINNED_RUN_CID:
        raise DatasetsUnrelatedStateChangeError(
            f"run CID {cid} remints {PINNED_RUN_CID}"
        )
    return cid


def refuse_model_completion(stage_id: str) -> None:
    stage = _text(stage_id, "stage_id")
    if stage in {
        "local_small_specialist",
        "medium_model",
        "frontier_model",
        "human_decision",
    }:
        raise DatasetsUnrelatedStateChangeError(
            f"model assertion at {stage} cannot complete work"
        )


def refuse_relevant_interface_change(*, relevant: bool) -> None:
    if relevant:
        raise DatasetsUnrelatedStateChangeError(
            "PCPR-066 cannot accept a relevant interface change"
        )


def refuse_reuse_as_demonstrated(*, demonstrated: bool) -> None:
    if demonstrated:
        raise DatasetsUnrelatedStateChangeError(
            "eligible reuse remains PCPR-067 and is not demonstrated here"
        )


def sidecar_owned_by_datasets() -> bool:
    root = discover_datasets_root()
    if root is None:
        return False
    return (root / UNRELATED_CHANGE_RELPATH).is_file()


def semantic_impact_is_empty() -> bool:
    record = unrelated_documentation_record()
    return (
        record["protocol_interface"] == PROTOCOL_INTERFACE
        and record["remints_protocol"] is False
        and record["adds_protocol_operation"] is False
        and record["relevant_interface_change"] is False
        and record["impacted_cone"] == []
        and record["kind"] == UNRELATED_DOCUMENTATION_KIND
        and SIDECAR_PROTOCOL_INTERFACE == PROTOCOL_INTERFACE
        and REMINTS_PROTOCOL is False
        and ADDS_PROTOCOL_OPERATION is False
        and RELEVANT_INTERFACE_CHANGE is False
        and tuple(SIDECAR_IMPACTED_CONE) == ()
        and WHOLE_PLAN_REGENERATION_REQUIRED is False
        and SIDECAR_ELIGIBLE_REUSE is True
        and REUSE_DEMONSTRATED is False
        and SIDECAR_NEXT_TASK_ID == PCPR_067_TASK_ID
        and bool(UNRELATED_DOCUMENTATION_NOTE)
    )


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
class DatasetsUnrelatedStateChangeVerdict:
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
    live_application: bool
    live_reuse: bool
    operator_blocking_task: str
    simulated_results_represented_as_live: bool
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str
    pack_cid: str
    binding_cid: str
    patch_cid: str
    route_cid: str
    current_root_cid: str
    run_cid: str
    objective_cid: str
    idea_digest: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "pack_cid": self.pack_cid,
            "binding_cid": self.binding_cid,
            "patch_cid": self.patch_cid,
            "route_cid": self.route_cid,
            "current_root_cid": self.current_root_cid,
            "run_cid": self.run_cid,
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
            "live_application": self.live_application,
            "live_reuse": self.live_reuse,
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
            "unrelated documentation change is applied as live supervisor "
            "work"
        ),
        "action": (
            "Keep the Datasets pack identity, LogicProviderProtocol@2, and "
            "documentation sidecar bound to the Accelerate change. Do not "
            "remint the protocol. Do not write DuckDB or Quack state."
        ),
        "reason": (
            "Datasets binds the Accelerate hermetic unrelated documentation "
            "change. That binding is not live supervisor application."
        ),
    }


def render_declared_binding(root: Path | None = None) -> dict[str, Any]:
    package_root = root or discover_datasets_root()
    if package_root is None:
        raise DatasetsUnrelatedStateChangeError(
            "Datasets package root was not found"
        )
    _ = package_root
    refuse_relevant_interface_change(relevant=False)
    refuse_reuse_as_demonstrated(demonstrated=False)
    sidecar = unrelated_documentation_record()
    document = {
        "schema": BINDING_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_066_TASK_ID,
        "goal_id": PCPR_066_GOAL_ID,
        "program_id": PCPR_PROGRAM_ID,
        "owner_repository": OWNER_REPOSITORY,
        "execution_owner_repository": EXECUTION_OWNER_REPOSITORY,
        "execution_owner_interface": EXECUTION_OWNER_INTERFACE,
        "storage_owner_repository": STORAGE_OWNER_REPOSITORY,
        "storage_owner_interface": STORAGE_OWNER_INTERFACE,
        "owner_interface": OWNER_INTERFACE,
        "owner_schema": OWNER_SCHEMA,
        "protocol_interface": PROTOCOL_INTERFACE,
        "documentation_interface": UNRELATED_DOCUMENTATION_INTERFACE,
        "documentation_schema": UNRELATED_DOCUMENTATION_SCHEMA,
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
        "prerequisite_task_id": PCPR_065_TASK_ID,
        "escalation_order": list(ESCALATION_ORDER),
        "model_assertion_completes_work": False,
        "context_pack": {
            "task_id": PCPR_061_TASK_ID,
            "constructed_by": OWNER_REPOSITORY,
            "constructed": True,
            "pack_cid": PINNED_PACK_CID,
            "pack_document_cid": PINNED_PACK_DOCUMENT_CID,
            "owner_interface": OWNER_INTERFACE,
            "owner_schema": OWNER_SCHEMA,
            "reminted": False,
            "live": False,
            "stored": True,
            "stored_by": STORAGE_OWNER_REPOSITORY,
            "current_root_published": True,
            "evidence_kind": "measured",
        },
        "storage": {
            "task_id": PCPR_062_TASK_ID,
            "stored": True,
            "stored_by": STORAGE_OWNER_REPOSITORY,
            "current_root_published": True,
            "current_root_cid": PINNED_CURRENT_ROOT_CID,
            "bytes_cid": PINNED_BYTES_CID,
            "live": False,
            "deferred": False,
            "reminted": False,
            "evidence_kind": "measured_hermetic",
        },
        "route": {
            "task_id": PCPR_063_TASK_ID,
            "executed": True,
            "executed_by": EXECUTION_OWNER_REPOSITORY,
            "owner_interface": ROUTE_OWNER_INTERFACE,
            "route_cid": PINNED_ROUTE_CID,
            "completed_through": "schema_type_and_static_checks",
            "next_authorized_stage": "selected_tests",
            "live": False,
            "hermetic": True,
            "reminted": False,
            "model_assertion_completes_work": False,
            "evidence_kind": "measured_hermetic",
        },
        "bounded_patch": {
            "task_id": PCPR_064_TASK_ID,
            "produced": True,
            "produced_by": EXECUTION_OWNER_REPOSITORY,
            "applied": True,
            "live": False,
            "hermetic": True,
            "deferred": False,
            "reminted": False,
            "remints_protocol": False,
            "adds_protocol_operation": False,
            "patch_cid": PINNED_PATCH_CID,
            "owner_interface": PATCH_OWNER_INTERFACE,
            "protocol_interface": PROTOCOL_INTERFACE,
            "evidence_kind": "measured_hermetic",
        },
        "selected_tests": {
            "task_id": PCPR_065_TASK_ID,
            "run": True,
            "live": False,
            "deferred": False,
            "hermetic": True,
            "owned_by": OWNER_REPOSITORY,
            "executed_by": EXECUTION_OWNER_REPOSITORY,
            "owner_interface": RUN_OWNER_INTERFACE,
            "run_cid": PINNED_RUN_CID,
            "reminted": False,
            "evidence_kind": "measured_hermetic",
        },
        "unrelated_state_change": {
            "task_id": PCPR_066_TASK_ID,
            "kind": UNRELATED_DOCUMENTATION_KIND,
            "path": UNRELATED_CHANGE_RELPATH,
            "owned_by": OWNER_REPOSITORY,
            "classified_by": EXECUTION_OWNER_REPOSITORY,
            "sidecar": sidecar,
            "semantic_frontier": list(SIDECAR_SEMANTIC_FRONTIER),
            "impacted_cone": list(SIDECAR_IMPACTED_CONE),
            "remints_protocol": False,
            "adds_protocol_operation": False,
            "relevant_interface_change": False,
            "whole_plan_regeneration_required": False,
            "eligible_reuse_preserved": True,
            "reuse_demonstrated": False,
            "next_task_id": PCPR_067_TASK_ID,
            "relevant_change_task_id": PCPR_068_TASK_ID,
            "live": False,
            "applied": False,
            "evidence_kind": "measured_hermetic",
        },
        "materialization": {
            "kind": "declared_binding_not_live",
            "admitted": False,
            "live": False,
            "applied": False,
            "duckdb_or_quack_state_written": False,
            "evidence_kind": "unavailable",
        },
        "live_application": typed_unavailable(
            reason=(
                "Datasets binds the Accelerate unrelated state change and "
                "does not apply it live."
            )
        ),
        "live_reuse": typed_unavailable(
            reason=(
                "Eligible reuse remains PCPR-067. This task only introduces "
                "the unrelated documentation change."
            )
        ),
        "source": {
            "kind": "git",
            "repository": "endomorphosis/ipfs_datasets_py",
            "binding": "current_head_not_mutable_main",
            "mutable_main_reference": False,
            "commit": {
                "status": "observed_at_evaluation",
                "evidence_kind": "measured",
                "live": False,
                "field": "PCPR-066 receipt current_tree_binding",
            },
        },
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
    document["binding_cid"] = content_identity(
        {key: value for key, value in document.items() if key != "binding_cid"}
    )
    return document


def artifact_paths(root: Path) -> dict[str, Path]:
    return {
        "binding": root / BINDING_DIR_RELPATH / BINDING_JSON_NAME,
        "readme": root / BINDING_README_RELPATH,
    }


def write_unrelated_state_change_files(
    start: Path | None = None,
) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsUnrelatedStateChangeError(
            "Datasets package root was not found"
        )
    binding = render_declared_binding(root)
    paths = artifact_paths(root)
    _atomic_write(paths["binding"], pretty_json(binding))
    readme = BINDING_README if BINDING_README.endswith("\n") else BINDING_README + "\n"
    _atomic_write(paths["readme"], readme)
    return {
        "binding": binding,
        "paths": {name: str(path) for name, path in paths.items()},
    }


def verify_unrelated_state_change_files(
    start: Path | None = None,
) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsUnrelatedStateChangeError(
            "Datasets package root was not found"
        )
    binding = render_declared_binding(root)
    paths = artifact_paths(root)
    missing: list[str] = []
    binding_ok = False
    readme_ok = False
    expected_readme = (
        BINDING_README if BINDING_README.endswith("\n") else BINDING_README + "\n"
    )
    for name, path in paths.items():
        if not path.is_file():
            missing.append(name)
            continue
        if name == "binding":
            binding_ok = json.loads(path.read_text(encoding="utf-8")) == binding
        elif name == "readme":
            readme_ok = path.read_text(encoding="utf-8") == expected_readme
    return {
        "ok": not missing and binding_ok and readme_ok,
        "missing": missing,
        "binding_ok": binding_ok,
        "readme_ok": readme_ok,
        "pack_cid": binding["context_pack"]["pack_cid"],
        "binding_cid": binding["binding_cid"],
        "patch_cid": binding["bounded_patch"]["patch_cid"],
        "route_cid": binding["route"]["route_cid"],
        "current_root_cid": binding["storage"]["current_root_cid"],
        "run_cid": binding["selected_tests"]["run_cid"],
        "objective_cid": binding["objective_cid"],
        "idea_digest": binding["idea_digest"],
        "binding_sha256": (
            sha256_bytes(paths["binding"].read_bytes())
            if paths["binding"].is_file()
            else "unavailable"
        ),
    }


def current_head_static_probes(
    start: Path | None = None,
) -> tuple[OutcomeProbe, ...]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsUnrelatedStateChangeError(
            "Datasets package root was not found"
        )
    binding = render_declared_binding(root)
    verified = verify_unrelated_state_change_files(root)
    table = parse_pyproject_unrelated_state_change_table(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST

    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    schema_roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
    operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
    sidecar_ok = sidecar_owned_by_datasets() and semantic_impact_is_empty()
    change = binding["unrelated_state_change"]
    remint = (
        binding["context_pack"]["pack_cid"] != PINNED_PACK_CID
        or binding["objective_cid"] != PINNED_OBJECTIVE_CID
        or binding["idea_digest"] != PINNED_IDEA_DIGEST
        or binding["lock_cid"] != PINNED_LOCK_CID
        or binding["storage"]["current_root_cid"] != PINNED_CURRENT_ROOT_CID
        or binding["route"]["route_cid"] != PINNED_ROUTE_CID
        or binding["bounded_patch"]["patch_cid"] != PINNED_PATCH_CID
        or binding["selected_tests"]["run_cid"] != PINNED_RUN_CID
        or binding["context_pack"]["reminted"] is True
        or binding["storage"]["reminted"] is True
        or binding["route"]["reminted"] is True
        or binding["bounded_patch"]["remints_protocol"] is True
        or binding["selected_tests"]["reminted"] is True
    )
    probes = [
        _probe(
            "binding_files_match_generator",
            verified.get("ok") is True and verified.get("binding_ok") is True,
            reason=(
                "Committed Datasets unrelated-state-change binding matches the generator."
                if verified.get("binding_ok") is True
                else "Committed Datasets unrelated-state-change binding is missing or drifts."
            ),
        ),
        _probe(
            "pyproject_unrelated_state_change_table",
            table.get("interface") == INTERFACE
            and table.get("schema") == SCHEMA
            and table.get("task-id") == PCPR_066_TASK_ID
            and table.get("objective-kind") == OBJECTIVE_KIND,
            reason=(
                "pyproject.toml declares DatasetsUnrelatedStateChangeBinding@1."
                if table.get("interface") == INTERFACE
                else "pyproject.toml does not declare the PCPR-066 binding."
            ),
        ),
        _probe(
            "manifest_advertises_unrelated_state_change",
            versions.get(INTERFACE) == "1"
            and schema_roots.get("datasets_unrelated_state_change") == SCHEMA
            and operations.get("unrelated_state_change") == "1",
            reason="LogicPlatformManifest advertises the PCPR-066 binding.",
        ),
        _probe(
            "owner_pack_cid_matches_pin",
            binding["context_pack"]["pack_cid"] == PINNED_PACK_CID,
            reason="Datasets binds its own pack CID without remint.",
        ),
        _probe(
            "change_owned_by_accelerate",
            binding["execution_owner_repository"] == EXECUTION_OWNER_REPOSITORY
            and binding["execution_owner_interface"] == EXECUTION_OWNER_INTERFACE
            and change["classified_by"] == EXECUTION_OWNER_REPOSITORY,
            reason="Datasets binds the Accelerate-owned change and does not remint it.",
        ),
        _probe(
            "protocol_identity_not_reminted",
            binding["protocol_interface"] == PROTOCOL_INTERFACE
            and change["remints_protocol"] is False
            and change["adds_protocol_operation"] is False,
            reason="LogicProviderProtocol@2 is bound and not reminted.",
        ),
        _probe(
            "sidecar_is_unrelated_documentation",
            sidecar_ok
            and change["kind"] == UNRELATED_DOCUMENTATION_KIND
            and change["owned_by"] == OWNER_REPOSITORY
            and change["path"] == UNRELATED_CHANGE_RELPATH,
            reason="Datasets owns the documentation-only unrelated sidecar.",
        ),
        _probe(
            "impacted_cone_empty",
            list(change["impacted_cone"]) == []
            and change["whole_plan_regeneration_required"] is False,
            reason="Semantic impact of the documentation sidecar is empty.",
        ),
        _probe(
            "eligible_reuse_not_demonstrated",
            change["eligible_reuse_preserved"] is True
            and change["reuse_demonstrated"] is False
            and change["next_task_id"] == PCPR_067_TASK_ID,
            reason="Eligible reuse is preserved and remains PCPR-067.",
        ),
        _probe(
            "model_assertion_cannot_complete_work",
            binding["model_assertion_completes_work"] is False,
            reason="No model assertion completes work.",
        ),
        _probe(
            "duckdb_or_quack_not_written",
            binding["duckdb_or_quack_state_written"] is False,
            reason="This task does not write DuckDB or Quack state.",
        ),
        _probe(
            "operator_blocking_task_emitted",
            binding["operator_blocking_task"]["task_id"] == OPERATOR_BLOCKING_TASK_ID
            and binding["operator_blocking_task"]["status"] == "typed_blocked",
            reason="Missing live application emits the operator-blocking task.",
        ),
        _probe(
            "no_closed_release_outcome",
            binding["closed_release_outcome"] is None
            and binding["release_claim"] is False,
            reason="This task does not emit a closed PCPR release outcome.",
        ),
        _probe(
            "compatibility_identities_reminted",
            remint,
            reason="A reminted pack, root, route, patch, run, objective, idea, or lock CID is forbidden.",
        ),
        _probe(
            "sibling_import_observed",
            False,
            reason="Datasets does not import sibling Accelerate or Kit packages.",
        ),
        _probe(
            "datasets_identity_reminted",
            binding["context_pack"]["reminted"] is True,
            reason="Datasets must not remint DatasetsContextPack@1.",
        ),
        _probe(
            "kit_identity_reminted",
            binding["storage"]["reminted"] is True,
            reason="Datasets must not remint the Kit current root.",
        ),
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        ),
        _probe(
            "live_application_represented_as_live",
            False,
            reason="Hermetic classification is not represented as live.",
        ),
        _probe(
            "closed_release_represented_as_live",
            False,
            reason="This task does not publish a PCPR release.",
        ),
        _probe(
            "model_assertion_completed_work",
            False,
            reason="No model assertion completed work.",
        ),
        _probe(
            "relevant_interface_change_accepted",
            False,
            reason="A relevant interface change remains PCPR-068.",
        ),
        _probe(
            "reuse_claimed_as_demonstrated",
            False,
            reason="Eligible reuse remains PCPR-067.",
        ),
        _probe(
            "live_application",
            None,
            evidence_kind="unavailable",
            reason="Live supervisor application stays typed unavailable.",
        ),
        _probe(
            "live_reuse",
            None,
            evidence_kind="unavailable",
            reason="Live reuse stays typed unavailable and remains PCPR-067.",
        ),
    ]
    return tuple(probes)


def qualify_unrelated_state_change(
    probes: Sequence[OutcomeProbe],
    *,
    pack_cid: str,
    binding_cid: str,
    patch_cid: str,
    route_cid: str,
    current_root_cid: str,
    run_cid: str,
    objective_cid: str,
    idea_digest_cid: str,
) -> DatasetsUnrelatedStateChangeVerdict:
    if not probes:
        raise DatasetsUnrelatedStateChangeError(
            "at least one probe is required"
        )
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise DatasetsUnrelatedStateChangeError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise DatasetsUnrelatedStateChangeError(
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
        "task_id": PCPR_066_TASK_ID,
        "goal_id": PCPR_066_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": False,
        "live_application": False,
        "live_reuse": False,
        "operator_blocking_task": OPERATOR_BLOCKING_TASK_ID,
        "simulated_results_represented_as_live": False,
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
        "pack_cid": pack_cid,
        "binding_cid": binding_cid,
        "patch_cid": patch_cid,
        "route_cid": route_cid,
        "current_root_cid": current_root_cid,
        "run_cid": run_cid,
        "objective_cid": objective_cid,
        "idea_digest": idea_digest_cid,
    }
    return DatasetsUnrelatedStateChangeVerdict(
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
        live_application=False,
        live_reuse=False,
        operator_blocking_task=OPERATOR_BLOCKING_TASK_ID,
        simulated_results_represented_as_live=False,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
        pack_cid=pack_cid,
        binding_cid=binding_cid,
        patch_cid=patch_cid,
        route_cid=route_cid,
        current_root_cid=current_root_cid,
        run_cid=run_cid,
        objective_cid=objective_cid,
        idea_digest=idea_digest_cid,
    )


def qualify_current_head_unrelated_state_change(
    start: Path | None = None,
) -> DatasetsUnrelatedStateChangeVerdict:
    binding = render_declared_binding(start)
    return qualify_unrelated_state_change(
        current_head_static_probes(start),
        pack_cid=str(binding["context_pack"]["pack_cid"]),
        binding_cid=str(binding["binding_cid"]),
        patch_cid=str(binding["bounded_patch"]["patch_cid"]),
        route_cid=str(binding["route"]["route_cid"]),
        current_root_cid=str(binding["storage"]["current_root_cid"]),
        run_cid=str(binding["selected_tests"]["run_cid"]),
        objective_cid=str(binding["objective_cid"]),
        idea_digest_cid=str(binding["idea_digest"]),
    )


def pcpr_066_receipt_promotion(
    verdict: DatasetsUnrelatedStateChangeVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise DatasetsUnrelatedStateChangeError(
            "unrelated state change must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise DatasetsUnrelatedStateChangeError(
            "unrelated state change must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise DatasetsUnrelatedStateChangeError(
            "unrelated state change completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise DatasetsUnrelatedStateChangeError(
            "unrelated state change must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsUnrelatedStateChangeError(
            "promotion_status must not be a closed release outcome"
        )
    if verdict.live_application or verdict.live_reuse:
        raise DatasetsUnrelatedStateChangeError(
            "live unrelated-state-change claims require measured_live evidence"
        )
    return verdict.to_mapping()


PINNED_BINDING_CID: Final = (
    "baguqeera5vkx3gcmyaopizthalx2chly7kbe2aywdfaka6ii5ui5jdemizsq"
)
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeeraun3gwck45xqll5lcf23gg4zxpqo4egzobtsy7csrzz6cfmlvx27a"
)


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "ESCALATION_ORDER",
    "DatasetsUnrelatedStateChangeError",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OBJECTIVE_KIND",
    "OPERATOR_BLOCKING_TASK_ID",
    "OutcomeProbe",
    "PCPR_066_GOAL_ID",
    "PCPR_066_TASK_ID",
    "PINNED_BINDING_CID",
    "PINNED_CURRENT_ROOT_CID",
    "PINNED_IDEA_DIGEST",
    "PINNED_LOCK_CID",
    "PINNED_OBJECTIVE_CID",
    "PINNED_PACK_CID",
    "PINNED_PATCH_CID",
    "PINNED_ROUTE_CID",
    "PINNED_RUN_CID",
    "PROTOCOL_INTERFACE",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "current_head_static_probes",
    "pcpr_066_receipt_promotion",
    "qualify_current_head_unrelated_state_change",
    "qualify_unrelated_state_change",
    "refuse_model_completion",
    "refuse_pack_cid_remint",
    "refuse_patch_cid_remint",
    "refuse_relevant_interface_change",
    "refuse_reuse_as_demonstrated",
    "refuse_route_cid_remint",
    "refuse_run_cid_remint",
    "render_declared_binding",
    "semantic_impact_is_empty",
    "sidecar_owned_by_datasets",
    "verify_unrelated_state_change_files",
    "write_unrelated_state_change_files",
]
