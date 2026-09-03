"""Fail-closed PCPR-070 Datasets binding to Accelerate state-owner restart.

Datasets owns DatasetsContextPack@1 identity, LogicProviderProtocol@2,
and semantic-identity survival across restart. This module binds those
identities to the Accelerate-owned authoritative state-owner restart
without reminting pack, protocol, route, patch, run, unrelated-change,
reuse, relevant-interface, or PlanDelta identities.

The sidecar `ipfs_datasets_py/logic/platform/state_owner_restart.py`
records that stale ContextPack and protocol-test identities remain
rejected and that unaffected solver-qualification proofs remain current.
Restart remains owned by Accelerate. LogicProviderProtocol@2 is not
reminted.

It does not import sibling Accelerate or Kit packages, does not write
DuckDB or Quack state, and does not admit live restart. Simulated
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
from ipfs_datasets_py.logic.platform.state_owner_restart import (
    NEXT_TASK_ID as SIDECAR_NEXT_TASK_ID,
    PLAN_EPOCH as SIDECAR_PLAN_EPOCH,
    PROTOCOL_INTERFACE as SIDECAR_PROTOCOL_INTERFACE,
    RELEVANT_INTERFACE_CHANGE,
    REMINTS_PROTOCOL,
    RESTART_OWNED_BY,
    SEMANTIC_FRONTIER as SIDECAR_SEMANTIC_FRONTIER,
    STALE_IDENTITIES as SIDECAR_STALE_IDENTITIES,
    STALE_REJECTED,
    STATE_OWNER_RESTART_INTERFACE,
    STATE_OWNER_RESTART_KIND,
    STATE_OWNER_RESTART_NOTE,
    STATE_OWNER_RESTART_SCHEMA,
    SURVIVES_RESTART,
    UNAFFECTED as SIDECAR_UNAFFECTED,
    UNAFFECTED_PRESERVED,
    WHOLE_PLAN_REGENERATION_REQUIRED,
    state_owner_restart_record,
)


INTERFACE: Final = "DatasetsAuthoritativeStateOwnerRestartBinding@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/state-owner-restart-binding@1"
BINDING_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/declared-state-owner-restart-binding@1"
)
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/state-owner-restart-verdict@1"
)
OWNER_INTERFACE: Final = "DatasetsContextPack@1"
OWNER_SCHEMA: Final = "ipfs_datasets_py/datasets-context-pack@1"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"
EXECUTION_OWNER_REPOSITORY: Final = "ipfs_accelerate_py"
EXECUTION_OWNER_INTERFACE: Final = "AccelerateAuthoritativeStateOwnerRestart@1"
PATCH_OWNER_INTERFACE: Final = "AccelerateBoundedPatch@1"
ROUTE_OWNER_INTERFACE: Final = "AccelerateDeterministicFirstRoute@1"
RUN_OWNER_INTERFACE: Final = "AccelerateSelectedTestsAndProofs@1"
DELTA_OWNER_INTERFACE: Final = "AccelerateStaleRejectionAndPlanDelta@1"
STORAGE_OWNER_REPOSITORY: Final = "ipfs_kit_py"
STORAGE_OWNER_INTERFACE: Final = "KitContextPackStorage@1"
PROTOCOL_INTERFACE: Final = "LogicProviderProtocol@2"
PCPR_070_TASK_ID: Final = "PCPR-070"
PCPR_070_GOAL_ID: Final = "PCPR-G700"
PCPR_069_TASK_ID: Final = "PCPR-069"
PCPR_068_TASK_ID: Final = "PCPR-068"
PCPR_067_TASK_ID: Final = "PCPR-067"
PCPR_066_TASK_ID: Final = "PCPR-066"
PCPR_065_TASK_ID: Final = "PCPR-065"
PCPR_064_TASK_ID: Final = "PCPR-064"
PCPR_063_TASK_ID: Final = "PCPR-063"
PCPR_062_TASK_ID: Final = "PCPR-062"
PCPR_061_TASK_ID: Final = "PCPR-061"
PCPR_071_TASK_ID: Final = "PCPR-071"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
OBJECTIVE_KIND: Final = "declared_state_owner_restart_binding"
PORTFOLIO_ID: Final = "portfolio:pcpr-v1"
PORTFOLIO_VERSION: Final = "proof-carrying-platform-0.1.0"
LANGUAGE: Final = "Python"
OBJECTIVE_ID: Final = "PCPR-G700"
OPERATOR_BLOCKING_TASK_ID: Final = (
    "pcpr-070-operator-live-authoritative-state-owner-restart"
)
SOURCE_DATE_EPOCH: Final = "0"
STATE_OWNER_RESTART_RELPATH: Final = (
    "ipfs_datasets_py/logic/platform/state_owner_restart.py"
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
PINNED_INTERFACE_CID: Final = (
    "baguqeera3k54j374af37kxdvkfgkjdfdofbdtg3x5vckpsceemy4lyklw3dq"
)
PINNED_DELTA_CID: Final = (
    "baguqeerahbxnuho3jdzkwaar6yx4ers7ns3p73mm3ghhgc5mhmn5r2fg3pga"
)

BINDING_DIR_RELPATH: Final = "packaging/pcpr/reference-workflow/cpython312"
BINDING_JSON_NAME: Final = "reference.state-owner-restart.binding.json"
BINDING_README_RELPATH: Final = (
    "packaging/pcpr/reference-workflow/STATE_OWNER_RESTART.md"
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
    "tests/unit/test_pcpr_070_state_owner_restart.py",
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
        "pyproject_state_owner_restart_table",
        "manifest_advertises_state_owner_restart",
        "owner_pack_cid_matches_pin",
        "restart_owned_by_accelerate",
        "protocol_identity_not_reminted",
        "sidecar_is_state_owner_restart",
        "stale_identities_remain_rejected",
        "unaffected_completion_preserved",
        "semantic_identities_survive_restart",
        "model_assertion_cannot_complete_work",
        "duckdb_or_quack_not_written",
        "operator_blocking_task_emitted",
        "no_closed_release_outcome",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "simulated_results_represented_as_live",
        "live_restart_represented_as_live",
        "closed_release_represented_as_live",
        "compatibility_identities_reminted",
        "sibling_import_observed",
        "datasets_identity_reminted",
        "kit_identity_reminted",
        "model_assertion_completed_work",
        "stale_identity_admitted_as_current",
        "unaffected_marked_stale",
        "database_edited",
    }
)

BINDING_README: Final = """# PCPR-070 Datasets state-owner-restart binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
authoritative state-owner restart. Datasets does not remint the pack CID,
does not remint the canonical protocol identity, and does not claim live
Quack restart.

- `cpython312/reference.state-owner-restart.binding.json` binds the
  Datasets pack identity to the Accelerate restart. Exact commit and
  tree are bound by the PCPR-070 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive restart. Stale
  identities remain rejected. Unaffected solver-qualification proofs
  remain current. Restart is owned by Accelerate. Recovery remains
  PCPR-071.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-070-operator-live-authoritative-state-owner-restart`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
"""


class DatasetsStateOwnerRestartError(ValueError):
    """Datasets attempted to remint or claim live state-owner restart."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetsStateOwnerRestartError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise DatasetsStateOwnerRestartError(
            f"{name} is not an admitted evidence kind"
        )
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsStateOwnerRestartError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def parse_pyproject_state_owner_restart_table(text: str) -> dict[str, Any]:
    import tomllib

    table = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(table, dict):
        raise DatasetsStateOwnerRestartError("pyproject.toml must be a table")
    tool = table.get("tool")
    payload: dict[str, Any] = {}
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            raw = datasets.get("state-owner-restart")
            if isinstance(raw, dict):
                payload = dict(raw)
    return payload


def refuse_pack_cid_remint(cid: str) -> str:
    if cid != PINNED_PACK_CID:
        raise DatasetsStateOwnerRestartError(
            f"ContextPack CID {cid} remints {PINNED_PACK_CID}"
        )
    return cid


def refuse_current_root_remint(cid: str) -> str:
    if cid != PINNED_CURRENT_ROOT_CID:
        raise DatasetsStateOwnerRestartError(
            f"current root CID {cid} remints {PINNED_CURRENT_ROOT_CID}"
        )
    return cid


def refuse_route_cid_remint(cid: str) -> str:
    if cid != PINNED_ROUTE_CID:
        raise DatasetsStateOwnerRestartError(
            f"route CID {cid} remints {PINNED_ROUTE_CID}"
        )
    return cid


def refuse_patch_cid_remint(cid: str) -> str:
    if cid != PINNED_PATCH_CID:
        raise DatasetsStateOwnerRestartError(
            f"patch CID {cid} remints {PINNED_PATCH_CID}"
        )
    return cid


def refuse_run_cid_remint(cid: str) -> str:
    if cid != PINNED_RUN_CID:
        raise DatasetsStateOwnerRestartError(
            f"run CID {cid} remints {PINNED_RUN_CID}"
        )
    return cid


def refuse_interface_cid_remint(cid: str) -> str:
    if cid != PINNED_INTERFACE_CID:
        raise DatasetsStateOwnerRestartError(
            f"interface CID {cid} remints {PINNED_INTERFACE_CID}"
        )
    return cid


def refuse_delta_cid_remint(cid: str) -> str:
    if cid != PINNED_DELTA_CID:
        raise DatasetsStateOwnerRestartError(
            f"delta CID {cid} remints {PINNED_DELTA_CID}"
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
        raise DatasetsStateOwnerRestartError(
            f"model assertion at {stage} cannot complete work"
        )


def refuse_stale_as_current(*, identity: str, admitted_as_current: bool) -> str:
    name = _text(identity, "identity")
    if name in SIDECAR_STALE_IDENTITIES and admitted_as_current:
        raise DatasetsStateOwnerRestartError(
            f"stale identity {name} is rejected and cannot be admitted as current"
        )
    return name


def refuse_unaffected_as_stale(*, identity: str, rejected: bool) -> str:
    name = _text(identity, "identity")
    if name in SIDECAR_UNAFFECTED and rejected:
        raise DatasetsStateOwnerRestartError(
            f"unaffected identity {name} is not stale and must be preserved"
        )
    return name


def refuse_database_edit(*, edited: bool) -> None:
    if edited:
        raise DatasetsStateOwnerRestartError(
            "state owner restart cannot write DuckDB or Quack state"
        )


def sidecar_owned_by_datasets() -> bool:
    root = discover_datasets_root()
    if root is None:
        return False
    return (root / STATE_OWNER_RESTART_RELPATH).is_file()


def semantic_identities_survive_restart() -> bool:
    record = state_owner_restart_record()
    return (
        record["protocol_interface"] == PROTOCOL_INTERFACE
        and record["remints_protocol"] is False
        and record["adds_protocol_operation"] is False
        and record["stale_rejected"] is True
        and record["unaffected_preserved"] is True
        and record["survives_restart"] is True
        and record["stale_identities"] == list(SIDECAR_STALE_IDENTITIES)
        and record["kind"] == STATE_OWNER_RESTART_KIND
        and SIDECAR_PROTOCOL_INTERFACE == PROTOCOL_INTERFACE
        and REMINTS_PROTOCOL is False
        and STALE_REJECTED is True
        and UNAFFECTED_PRESERVED is True
        and SURVIVES_RESTART is True
        and RELEVANT_INTERFACE_CHANGE is False
        and WHOLE_PLAN_REGENERATION_REQUIRED is False
        and tuple(SIDECAR_STALE_IDENTITIES) != ()
        and tuple(SIDECAR_UNAFFECTED) != ()
        and SIDECAR_NEXT_TASK_ID == PCPR_071_TASK_ID
        and RESTART_OWNED_BY == EXECUTION_OWNER_REPOSITORY
        and SIDECAR_PLAN_EPOCH == 2
        and bool(STATE_OWNER_RESTART_NOTE)
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
class DatasetsStateOwnerRestartVerdict:
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
    live_restart: bool
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
            "live_restart": self.live_restart,
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
            "authoritative owner is restarted as live supervisor work"
        ),
        "action": (
            "Keep the Datasets pack identity, LogicProviderProtocol@2, and "
            "state-owner-restart sidecar bound to the Accelerate restart. "
            "Do not remint the protocol. Do not write DuckDB or Quack state."
        ),
        "reason": (
            "Datasets binds the Accelerate hermetic state-owner restart. "
            "That binding is not live Quack restart."
        ),
    }


def render_declared_binding(root: Path | None = None) -> dict[str, Any]:
    package_root = root or discover_datasets_root()
    if package_root is None:
        raise DatasetsStateOwnerRestartError("Datasets package root was not found")
    _ = package_root
    refuse_stale_as_current(
        identity=SIDECAR_STALE_IDENTITIES[0], admitted_as_current=False
    )
    refuse_unaffected_as_stale(identity=SIDECAR_UNAFFECTED[0], rejected=False)
    refuse_database_edit(edited=False)
    sidecar = state_owner_restart_record()
    document = {
        "schema": BINDING_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_070_TASK_ID,
        "goal_id": PCPR_070_GOAL_ID,
        "program_id": PCPR_PROGRAM_ID,
        "owner_repository": OWNER_REPOSITORY,
        "execution_owner_repository": EXECUTION_OWNER_REPOSITORY,
        "execution_owner_interface": EXECUTION_OWNER_INTERFACE,
        "storage_owner_repository": STORAGE_OWNER_REPOSITORY,
        "storage_owner_interface": STORAGE_OWNER_INTERFACE,
        "owner_interface": OWNER_INTERFACE,
        "owner_schema": OWNER_SCHEMA,
        "protocol_interface": PROTOCOL_INTERFACE,
        "documentation_interface": STATE_OWNER_RESTART_INTERFACE,
        "documentation_schema": STATE_OWNER_RESTART_SCHEMA,
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
        "prerequisite_task_id": PCPR_069_TASK_ID,
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
            "stale": True,
            "rejected": True,
            "survives_restart": True,
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
            "survives_restart": True,
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
            "survives_restart": True,
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
            "remints_protocol": False,
            "patch_cid": PINNED_PATCH_CID,
            "owner_interface": PATCH_OWNER_INTERFACE,
            "survives_restart": True,
            "evidence_kind": "measured_hermetic",
        },
        "selected_tests": {
            "task_id": PCPR_065_TASK_ID,
            "run": True,
            "live": False,
            "deferred": False,
            "hermetic": True,
            "executed_by": EXECUTION_OWNER_REPOSITORY,
            "owner_interface": RUN_OWNER_INTERFACE,
            "run_cid": PINNED_RUN_CID,
            "reminted": False,
            "survives_restart": True,
            "evidence_kind": "measured_hermetic",
        },
        "state_owner_restart": {
            "task_id": PCPR_070_TASK_ID,
            "kind": STATE_OWNER_RESTART_KIND,
            "owned_by": OWNER_REPOSITORY,
            "classified_by": EXECUTION_OWNER_REPOSITORY,
            "restart_owned_by": EXECUTION_OWNER_REPOSITORY,
            "path": STATE_OWNER_RESTART_RELPATH,
            "sidecar": sidecar,
            "semantic_frontier": list(SIDECAR_SEMANTIC_FRONTIER),
            "stale_identities": list(SIDECAR_STALE_IDENTITIES),
            "unaffected": list(SIDECAR_UNAFFECTED),
            "remints_protocol": False,
            "adds_protocol_operation": False,
            "relevant_interface_change": False,
            "stale_rejected": True,
            "unaffected_completion_preserved": True,
            "survives_restart": True,
            "plan_epoch": 2,
            "history_mutated": False,
            "interface_cid": PINNED_INTERFACE_CID,
            "delta_cid": PINNED_DELTA_CID,
            "next_task_id": PCPR_071_TASK_ID,
            "stale_rejection_task_id": PCPR_069_TASK_ID,
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
                "Datasets binds the Accelerate state-owner restart and "
                "does not restart Quack."
            )
        ),
        "live_restart": typed_unavailable(
            reason=(
                "Live Quack owner restart remains typed unavailable. "
                "Recovery and idempotency remain PCPR-071."
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
                "field": "PCPR-070 receipt current_tree_binding",
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


def write_state_owner_restart_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsStateOwnerRestartError("Datasets package root was not found")
    binding = render_declared_binding(root)
    paths = artifact_paths(root)
    _atomic_write(paths["binding"], pretty_json(binding))
    readme = BINDING_README if BINDING_README.endswith("\n") else BINDING_README + "\n"
    _atomic_write(paths["readme"], readme)
    return {
        "binding": binding,
        "paths": {name: str(path) for name, path in paths.items()},
    }


def verify_state_owner_restart_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsStateOwnerRestartError("Datasets package root was not found")
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
        raise DatasetsStateOwnerRestartError("Datasets package root was not found")
    binding = render_declared_binding(root)
    verified = verify_state_owner_restart_files(root)
    table = parse_pyproject_state_owner_restart_table(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST

    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    schema_roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
    operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
    sidecar_ok = sidecar_owned_by_datasets() and semantic_identities_survive_restart()
    restart = binding["state_owner_restart"]
    remint = (
        binding["context_pack"]["pack_cid"] != PINNED_PACK_CID
        or binding["objective_cid"] != PINNED_OBJECTIVE_CID
        or binding["idea_digest"] != PINNED_IDEA_DIGEST
        or binding["lock_cid"] != PINNED_LOCK_CID
        or binding["storage"]["current_root_cid"] != PINNED_CURRENT_ROOT_CID
        or binding["route"]["route_cid"] != PINNED_ROUTE_CID
        or binding["bounded_patch"]["patch_cid"] != PINNED_PATCH_CID
        or binding["selected_tests"]["run_cid"] != PINNED_RUN_CID
        or restart["interface_cid"] != PINNED_INTERFACE_CID
        or restart["delta_cid"] != PINNED_DELTA_CID
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
                "Committed Datasets state-owner-restart binding matches the generator."
                if verified.get("binding_ok") is True
                else "Committed Datasets state-owner-restart binding is missing or drifts."
            ),
        ),
        _probe(
            "pyproject_state_owner_restart_table",
            table.get("interface") == INTERFACE
            and table.get("schema") == SCHEMA
            and table.get("task-id") == PCPR_070_TASK_ID
            and table.get("objective-kind") == OBJECTIVE_KIND,
            reason=(
                "pyproject.toml declares DatasetsAuthoritativeStateOwnerRestartBinding@1."
                if table.get("interface") == INTERFACE
                else "pyproject.toml does not declare the PCPR-070 binding."
            ),
        ),
        _probe(
            "manifest_advertises_state_owner_restart",
            versions.get(INTERFACE) == "1"
            and schema_roots.get("datasets_state_owner_restart") == SCHEMA
            and operations.get("state_owner_restart") == "1",
            reason="LogicPlatformManifest advertises the PCPR-070 binding.",
        ),
        _probe(
            "owner_pack_cid_matches_pin",
            binding["context_pack"]["pack_cid"] == PINNED_PACK_CID,
            reason="Datasets binds its own pack CID without remint.",
        ),
        _probe(
            "restart_owned_by_accelerate",
            binding["execution_owner_repository"] == EXECUTION_OWNER_REPOSITORY
            and binding["execution_owner_interface"] == EXECUTION_OWNER_INTERFACE
            and restart["classified_by"] == EXECUTION_OWNER_REPOSITORY
            and restart["restart_owned_by"] == EXECUTION_OWNER_REPOSITORY,
            reason="Datasets binds the Accelerate-owned restart and does not remint it.",
        ),
        _probe(
            "protocol_identity_not_reminted",
            binding["protocol_interface"] == PROTOCOL_INTERFACE
            and restart["remints_protocol"] is False,
            reason="LogicProviderProtocol@2 is bound and not reminted.",
        ),
        _probe(
            "sidecar_is_state_owner_restart",
            sidecar_ok
            and restart["kind"] == STATE_OWNER_RESTART_KIND
            and restart["owned_by"] == OWNER_REPOSITORY
            and restart["path"] == STATE_OWNER_RESTART_RELPATH
            and restart["survives_restart"] is True,
            reason="Datasets owns the state-owner-restart sidecar.",
        ),
        _probe(
            "stale_identities_remain_rejected",
            list(restart["stale_identities"]) == list(SIDECAR_STALE_IDENTITIES)
            and restart["stale_rejected"] is True
            and binding["context_pack"]["rejected"] is True,
            reason="Stale ContextPack and protocol-test identities remain rejected.",
        ),
        _probe(
            "unaffected_completion_preserved",
            list(restart["unaffected"]) == list(SIDECAR_UNAFFECTED)
            and restart["unaffected_completion_preserved"] is True,
            reason="Unaffected solver-qualification completion is preserved.",
        ),
        _probe(
            "semantic_identities_survive_restart",
            restart["survives_restart"] is True
            and binding["context_pack"]["survives_restart"] is True,
            reason="Semantic identities survive owner restart without remint.",
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
            reason="Missing live restart emits the operator-blocking task.",
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
            "live_restart_represented_as_live",
            False,
            reason="Hermetic classification is not represented as live restart.",
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
            "stale_identity_admitted_as_current",
            False,
            reason="Stale identities remain rejected across restart.",
        ),
        _probe(
            "unaffected_marked_stale",
            False,
            reason="Unaffected solver-qualification completion is not marked stale.",
        ),
        _probe(
            "database_edited",
            False,
            reason="DuckDB and Quack state were not written.",
        ),
        _probe(
            "live_application",
            None,
            evidence_kind="unavailable",
            reason="Live supervisor application stays typed unavailable.",
        ),
        _probe(
            "live_restart",
            None,
            evidence_kind="unavailable",
            reason="Live Quack owner restart stays typed unavailable.",
        ),
    ]
    return tuple(probes)


def qualify_state_owner_restart(
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
) -> DatasetsStateOwnerRestartVerdict:
    if not probes:
        raise DatasetsStateOwnerRestartError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise DatasetsStateOwnerRestartError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise DatasetsStateOwnerRestartError(
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
        "task_id": PCPR_070_TASK_ID,
        "goal_id": PCPR_070_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": False,
        "live_application": False,
        "live_restart": False,
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
    return DatasetsStateOwnerRestartVerdict(
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
        live_restart=False,
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


def qualify_current_head_state_owner_restart(
    start: Path | None = None,
) -> DatasetsStateOwnerRestartVerdict:
    binding = render_declared_binding(start)
    return qualify_state_owner_restart(
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


def pcpr_070_receipt_promotion(
    verdict: DatasetsStateOwnerRestartVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise DatasetsStateOwnerRestartError(
            "state-owner restart must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise DatasetsStateOwnerRestartError(
            "state-owner restart must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise DatasetsStateOwnerRestartError(
            "state-owner restart completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise DatasetsStateOwnerRestartError(
            "state-owner restart must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsStateOwnerRestartError(
            "promotion_status must not be a closed release outcome"
        )
    if verdict.live_application or verdict.live_restart:
        raise DatasetsStateOwnerRestartError(
            "live restart claims require measured_live evidence"
        )
    return verdict.to_mapping()


PINNED_BINDING_CID: Final = (
    "baguqeeras67qogccjls6gt3yqltkdzdodbtasylgqggajptpppbi5dvapvba"
)
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeera2q4fsvbwojcemoj3kf35g23jlargzjljkusjv2ozmhkwinpqhysa"
)


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "DatasetsStateOwnerRestartError",
    "ESCALATION_ORDER",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OBJECTIVE_KIND",
    "OPERATOR_BLOCKING_TASK_ID",
    "OutcomeProbe",
    "PCPR_070_GOAL_ID",
    "PCPR_070_TASK_ID",
    "PINNED_BINDING_CID",
    "PINNED_CURRENT_ROOT_CID",
    "PINNED_DELTA_CID",
    "PINNED_IDEA_DIGEST",
    "PINNED_INTERFACE_CID",
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
    "pcpr_070_receipt_promotion",
    "qualify_current_head_state_owner_restart",
    "qualify_state_owner_restart",
    "refuse_current_root_remint",
    "refuse_database_edit",
    "refuse_delta_cid_remint",
    "refuse_interface_cid_remint",
    "refuse_model_completion",
    "refuse_pack_cid_remint",
    "refuse_patch_cid_remint",
    "refuse_route_cid_remint",
    "refuse_run_cid_remint",
    "refuse_stale_as_current",
    "refuse_unaffected_as_stale",
    "render_declared_binding",
    "semantic_identities_survive_restart",
    "sidecar_owned_by_datasets",
    "verify_state_owner_restart_files",
    "write_state_owner_restart_files",
]
