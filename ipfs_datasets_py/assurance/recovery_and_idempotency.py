"""Fail-closed PCPR-071 Datasets binding to Accelerate recovery and idempotency.

Datasets owns DatasetsContextPack@1 identity, LogicProviderProtocol@2,
and semantic-identity survival across recovery. This module binds those
identities to the Accelerate-owned recovery and idempotency demonstration
without reminting pack, protocol, route, patch, run, unrelated-change,
reuse, relevant-interface, PlanDelta, or restart identities.

The sidecar `ipfs_datasets_py/logic/platform/recovery_and_idempotency.py`
records that stale ContextPack and protocol-test identities remain
rejected and that unaffected solver-qualification proofs remain current.
Recovery remains owned by Accelerate. LogicProviderProtocol@2 is not
reminted.

It does not import sibling Accelerate or Kit packages, does not write
DuckDB or Quack state, and does not admit live recovery. Simulated
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
from ipfs_datasets_py.logic.platform.recovery_and_idempotency import (
    IDEMPOTENT as SIDECAR_IDEMPOTENT,
    NEXT_TASK_ID as SIDECAR_NEXT_TASK_ID,
    OWNER_GENERATION as SIDECAR_OWNER_GENERATION,
    PLAN_EPOCH as SIDECAR_PLAN_EPOCH,
    PROTOCOL_INTERFACE as SIDECAR_PROTOCOL_INTERFACE,
    RECOVERY_AND_IDEMPOTENCY_INTERFACE,
    RECOVERY_AND_IDEMPOTENCY_KIND,
    RECOVERY_AND_IDEMPOTENCY_NOTE,
    RECOVERY_AND_IDEMPOTENCY_SCHEMA,
    RECOVERY_OWNED_BY,
    RELEVANT_INTERFACE_CHANGE,
    REMINTS_PROTOCOL,
    SEMANTIC_FRONTIER as SIDECAR_SEMANTIC_FRONTIER,
    STALE_IDENTITIES as SIDECAR_STALE_IDENTITIES,
    STALE_REJECTED,
    SURVIVES_RECOVERY,
    SURVIVES_RESTART,
    UNAFFECTED as SIDECAR_UNAFFECTED,
    UNAFFECTED_PRESERVED,
    WHOLE_PLAN_REGENERATION_REQUIRED,
    recovery_and_idempotency_record,
)


INTERFACE: Final = "DatasetsRecoveryAndIdempotencyBinding@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/recovery-and-idempotency-binding@1"
BINDING_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/declared-recovery-and-idempotency-binding@1"
)
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/recovery-and-idempotency-verdict@1"
)
OWNER_INTERFACE: Final = "DatasetsContextPack@1"
OWNER_SCHEMA: Final = "ipfs_datasets_py/datasets-context-pack@1"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"
EXECUTION_OWNER_REPOSITORY: Final = "ipfs_accelerate_py"
EXECUTION_OWNER_INTERFACE: Final = "AccelerateRecoveryAndIdempotency@1"
RESTART_OWNER_INTERFACE: Final = "AccelerateAuthoritativeStateOwnerRestart@1"
PATCH_OWNER_INTERFACE: Final = "AccelerateBoundedPatch@1"
ROUTE_OWNER_INTERFACE: Final = "AccelerateDeterministicFirstRoute@1"
RUN_OWNER_INTERFACE: Final = "AccelerateSelectedTestsAndProofs@1"
DELTA_OWNER_INTERFACE: Final = "AccelerateStaleRejectionAndPlanDelta@1"
STORAGE_OWNER_REPOSITORY: Final = "ipfs_kit_py"
STORAGE_OWNER_INTERFACE: Final = "KitContextPackStorage@1"
PROTOCOL_INTERFACE: Final = "LogicProviderProtocol@2"
PCPR_071_TASK_ID: Final = "PCPR-071"
PCPR_071_GOAL_ID: Final = "PCPR-G700"
PCPR_070_TASK_ID: Final = "PCPR-070"
PCPR_069_TASK_ID: Final = "PCPR-069"
PCPR_068_TASK_ID: Final = "PCPR-068"
PCPR_067_TASK_ID: Final = "PCPR-067"
PCPR_066_TASK_ID: Final = "PCPR-066"
PCPR_065_TASK_ID: Final = "PCPR-065"
PCPR_064_TASK_ID: Final = "PCPR-064"
PCPR_063_TASK_ID: Final = "PCPR-063"
PCPR_062_TASK_ID: Final = "PCPR-062"
PCPR_061_TASK_ID: Final = "PCPR-061"
PCPR_072_TASK_ID: Final = "PCPR-072"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
OBJECTIVE_KIND: Final = "declared_recovery_and_idempotency_binding"
PORTFOLIO_ID: Final = "portfolio:pcpr-v1"
PORTFOLIO_VERSION: Final = "proof-carrying-platform-0.1.0"
LANGUAGE: Final = "Python"
OBJECTIVE_ID: Final = "PCPR-G700"
OPERATOR_BLOCKING_TASK_ID: Final = (
    "pcpr-071-operator-live-recovery-and-idempotency"
)
SOURCE_DATE_EPOCH: Final = "0"
RECOVERY_AND_IDEMPOTENCY_RELPATH: Final = (
    "ipfs_datasets_py/logic/platform/recovery_and_idempotency.py"
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
PINNED_RESTART_CID: Final = (
    "baguqeeratw2evha3sv4ko5km5e5igcjprwfpkse4x2siwa5ldhyu5ugbjyja"
)

BINDING_DIR_RELPATH: Final = "packaging/pcpr/reference-workflow/cpython312"
BINDING_JSON_NAME: Final = "reference.recovery-and-idempotency.binding.json"
BINDING_README_RELPATH: Final = (
    "packaging/pcpr/reference-workflow/RECOVERY_AND_IDEMPOTENCY.md"
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
    "tests/unit/test_pcpr_071_recovery_and_idempotency.py",
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
        "pyproject_recovery_and_idempotency_table",
        "manifest_advertises_recovery_and_idempotency",
        "owner_pack_cid_matches_pin",
        "recovery_owned_by_accelerate",
        "protocol_identity_not_reminted",
        "sidecar_is_recovery_and_idempotency",
        "stale_identities_remain_rejected",
        "unaffected_completion_preserved",
        "semantic_identities_survive_recovery",
        "idempotent_binding",
        "model_assertion_cannot_complete_work",
        "duckdb_or_quack_not_written",
        "operator_blocking_task_emitted",
        "no_closed_release_outcome",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "simulated_results_represented_as_live",
        "live_recovery_represented_as_live",
        "closed_release_represented_as_live",
        "compatibility_identities_reminted",
        "sibling_import_observed",
        "datasets_identity_reminted",
        "kit_identity_reminted",
        "restart_identity_reminted",
        "model_assertion_completed_work",
        "stale_identity_admitted_as_current",
        "unaffected_marked_stale",
        "database_edited",
    }
)

BINDING_README: Final = """# PCPR-071 Datasets recovery-and-idempotency binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
recovery and idempotency demonstration. Datasets does not remint the pack
CID, does not remint the canonical protocol identity, and does not claim
live Quack recovery.

- `cpython312/reference.recovery-and-idempotency.binding.json` binds the
  Datasets pack identity to the Accelerate recovery. Exact commit and
  tree are bound by the PCPR-071 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive recovery. Stale
  identities remain rejected. Unaffected solver-qualification proofs
  remain current. Recovery is owned by Accelerate. The final receipt
  chain remains PCPR-072.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-071-operator-live-recovery-and-idempotency`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
"""


class DatasetsRecoveryAndIdempotencyError(ValueError):
    """Datasets attempted to remint or claim live recovery."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetsRecoveryAndIdempotencyError(
            f"{name} must be a non-empty string"
        )
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise DatasetsRecoveryAndIdempotencyError(
            f"{name} is not an admitted evidence kind"
        )
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsRecoveryAndIdempotencyError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def parse_pyproject_recovery_and_idempotency_table(text: str) -> dict[str, Any]:
    import tomllib

    table = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(table, dict):
        raise DatasetsRecoveryAndIdempotencyError("pyproject.toml must be a table")
    tool = table.get("tool")
    payload: dict[str, Any] = {}
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            raw = datasets.get("recovery-and-idempotency")
            if isinstance(raw, dict):
                payload = dict(raw)
    return payload


def refuse_pack_cid_remint(cid: str) -> str:
    if cid != PINNED_PACK_CID:
        raise DatasetsRecoveryAndIdempotencyError(
            f"ContextPack CID {cid} remints {PINNED_PACK_CID}"
        )
    return cid


def refuse_current_root_remint(cid: str) -> str:
    if cid != PINNED_CURRENT_ROOT_CID:
        raise DatasetsRecoveryAndIdempotencyError(
            f"current root CID {cid} remints {PINNED_CURRENT_ROOT_CID}"
        )
    return cid


def refuse_route_cid_remint(cid: str) -> str:
    if cid != PINNED_ROUTE_CID:
        raise DatasetsRecoveryAndIdempotencyError(
            f"route CID {cid} remints {PINNED_ROUTE_CID}"
        )
    return cid


def refuse_patch_cid_remint(cid: str) -> str:
    if cid != PINNED_PATCH_CID:
        raise DatasetsRecoveryAndIdempotencyError(
            f"patch CID {cid} remints {PINNED_PATCH_CID}"
        )
    return cid


def refuse_run_cid_remint(cid: str) -> str:
    if cid != PINNED_RUN_CID:
        raise DatasetsRecoveryAndIdempotencyError(
            f"run CID {cid} remints {PINNED_RUN_CID}"
        )
    return cid


def refuse_interface_cid_remint(cid: str) -> str:
    if cid != PINNED_INTERFACE_CID:
        raise DatasetsRecoveryAndIdempotencyError(
            f"interface CID {cid} remints {PINNED_INTERFACE_CID}"
        )
    return cid


def refuse_delta_cid_remint(cid: str) -> str:
    if cid != PINNED_DELTA_CID:
        raise DatasetsRecoveryAndIdempotencyError(
            f"delta CID {cid} remints {PINNED_DELTA_CID}"
        )
    return cid


def refuse_restart_cid_remint(cid: str) -> str:
    if cid != PINNED_RESTART_CID:
        raise DatasetsRecoveryAndIdempotencyError(
            f"restart CID {cid} remints {PINNED_RESTART_CID}"
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
        raise DatasetsRecoveryAndIdempotencyError(
            f"model assertion at {stage} cannot complete work"
        )


def refuse_stale_as_current(*, identity: str, admitted_as_current: bool) -> str:
    name = _text(identity, "identity")
    if name in SIDECAR_STALE_IDENTITIES and admitted_as_current:
        raise DatasetsRecoveryAndIdempotencyError(
            f"stale identity {name} is rejected and cannot be admitted as current"
        )
    return name


def refuse_unaffected_as_stale(*, identity: str, rejected: bool) -> str:
    name = _text(identity, "identity")
    if name in SIDECAR_UNAFFECTED and rejected:
        raise DatasetsRecoveryAndIdempotencyError(
            f"unaffected identity {name} is not stale and must be preserved"
        )
    return name


def refuse_database_edit(*, edited: bool) -> None:
    if edited:
        raise DatasetsRecoveryAndIdempotencyError(
            "recovery cannot write DuckDB or Quack state"
        )


def sidecar_owned_by_datasets() -> bool:
    root = discover_datasets_root()
    if root is None:
        return False
    return (root / RECOVERY_AND_IDEMPOTENCY_RELPATH).is_file()


def semantic_identities_survive_recovery() -> bool:
    record = recovery_and_idempotency_record()
    return (
        record["protocol_interface"] == PROTOCOL_INTERFACE
        and record["remints_protocol"] is False
        and record["adds_protocol_operation"] is False
        and record["stale_rejected"] is True
        and record["unaffected_preserved"] is True
        and record["survives_restart"] is True
        and record["survives_recovery"] is True
        and record["idempotent"] is True
        and record["stale_identities"] == list(SIDECAR_STALE_IDENTITIES)
        and record["kind"] == RECOVERY_AND_IDEMPOTENCY_KIND
        and SIDECAR_PROTOCOL_INTERFACE == PROTOCOL_INTERFACE
        and REMINTS_PROTOCOL is False
        and STALE_REJECTED is True
        and UNAFFECTED_PRESERVED is True
        and SURVIVES_RESTART is True
        and SURVIVES_RECOVERY is True
        and SIDECAR_IDEMPOTENT is True
        and RELEVANT_INTERFACE_CHANGE is False
        and WHOLE_PLAN_REGENERATION_REQUIRED is False
        and tuple(SIDECAR_STALE_IDENTITIES) != ()
        and tuple(SIDECAR_UNAFFECTED) != ()
        and SIDECAR_NEXT_TASK_ID == PCPR_072_TASK_ID
        and RECOVERY_OWNED_BY == EXECUTION_OWNER_REPOSITORY
        and SIDECAR_PLAN_EPOCH == 2
        and SIDECAR_OWNER_GENERATION == 2
        and bool(RECOVERY_AND_IDEMPOTENCY_NOTE)
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
class DatasetsRecoveryAndIdempotencyVerdict:
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
    live_recovery: bool
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
    restart_cid: str
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
            "restart_cid": self.restart_cid,
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
            "live_recovery": self.live_recovery,
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
            "An admitted Quack-fenced state-owner session before recovery "
            "and idempotency are demonstrated as live supervisor work"
        ),
        "action": (
            "Keep the Datasets pack identity, LogicProviderProtocol@2, and "
            "recovery-and-idempotency sidecar bound to the Accelerate "
            "recovery. Do not remint the protocol. Do not write DuckDB or "
            "Quack state."
        ),
        "reason": (
            "Datasets binds the Accelerate hermetic recovery and "
            "idempotency demonstration. That binding is not live Quack "
            "recovery."
        ),
    }


def render_declared_binding(root: Path | None = None) -> dict[str, Any]:
    package_root = root or discover_datasets_root()
    if package_root is None:
        raise DatasetsRecoveryAndIdempotencyError(
            "Datasets package root was not found"
        )
    _ = package_root
    refuse_stale_as_current(
        identity=SIDECAR_STALE_IDENTITIES[0], admitted_as_current=False
    )
    refuse_unaffected_as_stale(identity=SIDECAR_UNAFFECTED[0], rejected=False)
    refuse_database_edit(edited=False)
    sidecar = recovery_and_idempotency_record()
    document = {
        "schema": BINDING_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_071_TASK_ID,
        "goal_id": PCPR_071_GOAL_ID,
        "program_id": PCPR_PROGRAM_ID,
        "owner_repository": OWNER_REPOSITORY,
        "execution_owner_repository": EXECUTION_OWNER_REPOSITORY,
        "execution_owner_interface": EXECUTION_OWNER_INTERFACE,
        "storage_owner_repository": STORAGE_OWNER_REPOSITORY,
        "storage_owner_interface": STORAGE_OWNER_INTERFACE,
        "owner_interface": OWNER_INTERFACE,
        "owner_schema": OWNER_SCHEMA,
        "protocol_interface": PROTOCOL_INTERFACE,
        "documentation_interface": RECOVERY_AND_IDEMPOTENCY_INTERFACE,
        "documentation_schema": RECOVERY_AND_IDEMPOTENCY_SCHEMA,
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
        "prerequisite_task_id": PCPR_070_TASK_ID,
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
            "survives_recovery": True,
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
            "survives_recovery": True,
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
            "survives_recovery": True,
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
            "survives_recovery": True,
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
            "survives_recovery": True,
            "evidence_kind": "measured_hermetic",
        },
        "state_owner_restart": {
            "task_id": PCPR_070_TASK_ID,
            "owner_interface": RESTART_OWNER_INTERFACE,
            "restart_cid": PINNED_RESTART_CID,
            "classified_by": EXECUTION_OWNER_REPOSITORY,
            "live": False,
            "hermetic": True,
            "reminted": False,
            "survives_recovery": True,
            "evidence_kind": "measured_hermetic",
        },
        "recovery_and_idempotency": {
            "task_id": PCPR_071_TASK_ID,
            "kind": RECOVERY_AND_IDEMPOTENCY_KIND,
            "owned_by": OWNER_REPOSITORY,
            "classified_by": EXECUTION_OWNER_REPOSITORY,
            "recovery_owned_by": EXECUTION_OWNER_REPOSITORY,
            "path": RECOVERY_AND_IDEMPOTENCY_RELPATH,
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
            "survives_recovery": True,
            "idempotent": True,
            "plan_epoch": 2,
            "owner_generation": 2,
            "history_mutated": False,
            "interface_cid": PINNED_INTERFACE_CID,
            "delta_cid": PINNED_DELTA_CID,
            "restart_cid": PINNED_RESTART_CID,
            "next_task_id": PCPR_072_TASK_ID,
            "restart_task_id": PCPR_070_TASK_ID,
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
                "Datasets binds the Accelerate recovery and idempotency "
                "demonstration and does not recover Quack."
            )
        ),
        "live_recovery": typed_unavailable(
            reason=(
                "Live Quack recovery remains typed unavailable. The final "
                "receipt chain remains PCPR-072."
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
                "field": "PCPR-071 receipt current_tree_binding",
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


def write_recovery_and_idempotency_files(
    start: Path | None = None,
) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsRecoveryAndIdempotencyError(
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


def verify_recovery_and_idempotency_files(
    start: Path | None = None,
) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsRecoveryAndIdempotencyError(
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
        "restart_cid": binding["state_owner_restart"]["restart_cid"],
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
        raise DatasetsRecoveryAndIdempotencyError(
            "Datasets package root was not found"
        )
    binding = render_declared_binding(root)
    verified = verify_recovery_and_idempotency_files(root)
    table = parse_pyproject_recovery_and_idempotency_table(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST

    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    schema_roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
    operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
    sidecar_ok = sidecar_owned_by_datasets() and semantic_identities_survive_recovery()
    recovery = binding["recovery_and_idempotency"]
    remint = (
        binding["context_pack"]["pack_cid"] != PINNED_PACK_CID
        or binding["objective_cid"] != PINNED_OBJECTIVE_CID
        or binding["idea_digest"] != PINNED_IDEA_DIGEST
        or binding["lock_cid"] != PINNED_LOCK_CID
        or binding["storage"]["current_root_cid"] != PINNED_CURRENT_ROOT_CID
        or binding["route"]["route_cid"] != PINNED_ROUTE_CID
        or binding["bounded_patch"]["patch_cid"] != PINNED_PATCH_CID
        or binding["selected_tests"]["run_cid"] != PINNED_RUN_CID
        or recovery["interface_cid"] != PINNED_INTERFACE_CID
        or recovery["delta_cid"] != PINNED_DELTA_CID
        or recovery["restart_cid"] != PINNED_RESTART_CID
        or binding["state_owner_restart"]["restart_cid"] != PINNED_RESTART_CID
        or binding["context_pack"]["reminted"] is True
        or binding["storage"]["reminted"] is True
        or binding["route"]["reminted"] is True
        or binding["bounded_patch"]["remints_protocol"] is True
        or binding["selected_tests"]["reminted"] is True
        or binding["state_owner_restart"]["reminted"] is True
    )
    probes = [
        _probe(
            "binding_files_match_generator",
            verified.get("ok") is True and verified.get("binding_ok") is True,
            reason=(
                "Committed Datasets recovery binding matches the generator."
                if verified.get("binding_ok") is True
                else "Committed Datasets recovery binding is missing or drifts."
            ),
        ),
        _probe(
            "pyproject_recovery_and_idempotency_table",
            table.get("interface") == INTERFACE
            and table.get("schema") == SCHEMA
            and table.get("task-id") == PCPR_071_TASK_ID
            and table.get("objective-kind") == OBJECTIVE_KIND,
            reason=(
                "pyproject.toml declares DatasetsRecoveryAndIdempotencyBinding@1."
                if table.get("interface") == INTERFACE
                else "pyproject.toml does not declare the PCPR-071 binding."
            ),
        ),
        _probe(
            "manifest_advertises_recovery_and_idempotency",
            versions.get(INTERFACE) == "1"
            and schema_roots.get("datasets_recovery_and_idempotency") == SCHEMA
            and operations.get("recovery_and_idempotency") == "1",
            reason="LogicPlatformManifest advertises the PCPR-071 binding.",
        ),
        _probe(
            "owner_pack_cid_matches_pin",
            binding["context_pack"]["pack_cid"] == PINNED_PACK_CID,
            reason="Datasets binds its own pack CID without remint.",
        ),
        _probe(
            "recovery_owned_by_accelerate",
            binding["execution_owner_repository"] == EXECUTION_OWNER_REPOSITORY
            and binding["execution_owner_interface"] == EXECUTION_OWNER_INTERFACE
            and recovery["classified_by"] == EXECUTION_OWNER_REPOSITORY
            and recovery["recovery_owned_by"] == EXECUTION_OWNER_REPOSITORY,
            reason="Datasets binds the Accelerate-owned recovery and does not remint it.",
        ),
        _probe(
            "protocol_identity_not_reminted",
            binding["protocol_interface"] == PROTOCOL_INTERFACE
            and recovery["remints_protocol"] is False,
            reason="LogicProviderProtocol@2 is bound and not reminted.",
        ),
        _probe(
            "sidecar_is_recovery_and_idempotency",
            sidecar_ok
            and recovery["kind"] == RECOVERY_AND_IDEMPOTENCY_KIND
            and recovery["owned_by"] == OWNER_REPOSITORY
            and recovery["path"] == RECOVERY_AND_IDEMPOTENCY_RELPATH
            and recovery["survives_recovery"] is True,
            reason="Datasets owns the recovery-and-idempotency sidecar.",
        ),
        _probe(
            "stale_identities_remain_rejected",
            list(recovery["stale_identities"]) == list(SIDECAR_STALE_IDENTITIES)
            and recovery["stale_rejected"] is True
            and binding["context_pack"]["rejected"] is True,
            reason="Stale ContextPack and protocol-test identities remain rejected.",
        ),
        _probe(
            "unaffected_completion_preserved",
            list(recovery["unaffected"]) == list(SIDECAR_UNAFFECTED)
            and recovery["unaffected_completion_preserved"] is True,
            reason="Unaffected solver-qualification completion is preserved.",
        ),
        _probe(
            "semantic_identities_survive_recovery",
            recovery["survives_recovery"] is True
            and binding["context_pack"]["survives_recovery"] is True,
            reason="Semantic identities survive recovery without remint.",
        ),
        _probe(
            "idempotent_binding",
            recovery["idempotent"] is True
            and recovery["history_mutated"] is False,
            reason="Datasets binding is identity-preserving across recovery replay.",
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
            reason="Missing live recovery emits the operator-blocking task.",
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
            reason="A reminted pack, root, route, patch, run, restart, objective, idea, or lock CID is forbidden.",
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
            "restart_identity_reminted",
            recovery["restart_cid"] != PINNED_RESTART_CID,
            reason="Datasets must not remint the PCPR-070 restart CID.",
        ),
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        ),
        _probe(
            "live_recovery_represented_as_live",
            False,
            reason="Hermetic classification is not represented as live recovery.",
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
            reason="Stale identities remain rejected across recovery.",
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
            "live_recovery",
            None,
            evidence_kind="unavailable",
            reason="Live Quack recovery stays typed unavailable.",
        ),
    ]
    return tuple(probes)


def qualify_recovery_and_idempotency(
    probes: Sequence[OutcomeProbe],
    *,
    pack_cid: str,
    binding_cid: str,
    patch_cid: str,
    route_cid: str,
    current_root_cid: str,
    run_cid: str,
    restart_cid: str,
    objective_cid: str,
    idea_digest_cid: str,
) -> DatasetsRecoveryAndIdempotencyVerdict:
    if not probes:
        raise DatasetsRecoveryAndIdempotencyError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise DatasetsRecoveryAndIdempotencyError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise DatasetsRecoveryAndIdempotencyError(
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
        "task_id": PCPR_071_TASK_ID,
        "goal_id": PCPR_071_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": False,
        "live_application": False,
        "live_recovery": False,
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
        "restart_cid": restart_cid,
        "objective_cid": objective_cid,
        "idea_digest": idea_digest_cid,
    }
    return DatasetsRecoveryAndIdempotencyVerdict(
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
        live_recovery=False,
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
        restart_cid=restart_cid,
        objective_cid=objective_cid,
        idea_digest=idea_digest_cid,
    )


def qualify_current_head_recovery_and_idempotency(
    start: Path | None = None,
) -> DatasetsRecoveryAndIdempotencyVerdict:
    binding = render_declared_binding(start)
    return qualify_recovery_and_idempotency(
        current_head_static_probes(start),
        pack_cid=str(binding["context_pack"]["pack_cid"]),
        binding_cid=str(binding["binding_cid"]),
        patch_cid=str(binding["bounded_patch"]["patch_cid"]),
        route_cid=str(binding["route"]["route_cid"]),
        current_root_cid=str(binding["storage"]["current_root_cid"]),
        run_cid=str(binding["selected_tests"]["run_cid"]),
        restart_cid=str(binding["state_owner_restart"]["restart_cid"]),
        objective_cid=str(binding["objective_cid"]),
        idea_digest_cid=str(binding["idea_digest"]),
    )


def pcpr_071_receipt_promotion(
    verdict: DatasetsRecoveryAndIdempotencyVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise DatasetsRecoveryAndIdempotencyError(
            "recovery must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise DatasetsRecoveryAndIdempotencyError(
            "recovery must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise DatasetsRecoveryAndIdempotencyError(
            "recovery completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise DatasetsRecoveryAndIdempotencyError(
            "recovery must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsRecoveryAndIdempotencyError(
            "promotion_status must not be a closed release outcome"
        )
    if verdict.live_application or verdict.live_recovery:
        raise DatasetsRecoveryAndIdempotencyError(
            "live recovery claims require measured_live evidence"
        )
    return verdict.to_mapping()


PINNED_BINDING_CID: Final = (
    "baguqeeramxslr4agtguwhql4s73k2qdahet3ffkrty63ecckuyjaxbqtjioa"
)
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeera2mezkdxzqt4pqseafe74u7kubms6sektyqtytzrpvqothdrs56qq"
)


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "DatasetsRecoveryAndIdempotencyError",
    "ESCALATION_ORDER",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OBJECTIVE_KIND",
    "OPERATOR_BLOCKING_TASK_ID",
    "OutcomeProbe",
    "PCPR_071_GOAL_ID",
    "PCPR_071_TASK_ID",
    "PINNED_BINDING_CID",
    "PINNED_CURRENT_ROOT_CID",
    "PINNED_DELTA_CID",
    "PINNED_IDEA_DIGEST",
    "PINNED_INTERFACE_CID",
    "PINNED_OBJECTIVE_CID",
    "PINNED_PACK_CID",
    "PINNED_PATCH_CID",
    "PINNED_RESTART_CID",
    "PINNED_ROUTE_CID",
    "PINNED_RUN_CID",
    "PROTOCOL_INTERFACE",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "current_head_static_probes",
    "pcpr_071_receipt_promotion",
    "qualify_current_head_recovery_and_idempotency",
    "qualify_recovery_and_idempotency",
    "refuse_database_edit",
    "refuse_model_completion",
    "refuse_pack_cid_remint",
    "refuse_patch_cid_remint",
    "refuse_restart_cid_remint",
    "refuse_route_cid_remint",
    "refuse_run_cid_remint",
    "refuse_stale_as_current",
    "refuse_unaffected_as_stale",
    "render_declared_binding",
    "semantic_identities_survive_recovery",
    "sidecar_owned_by_datasets",
    "verify_recovery_and_idempotency_files",
    "write_recovery_and_idempotency_files",
]
