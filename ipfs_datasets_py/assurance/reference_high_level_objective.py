"""Fail-closed PCPR-060 Datasets binding to the reference objective.

Datasets binds the Accelerate-owned declared reference high-level
objective CID and idea digest and refuses reminting. It does not import
sibling Accelerate or Kit packages, does not construct a ContextPack
(PCPR-061), and does not write DuckDB or Quack state.

This is a declared binding. It is not a live Supervisor submission, not
live materialization, not a freeze, and not a closed PCPR release. Live
semantic-impact inspection stays deferred to PCPR-061. Missing a live
Quack-fenced session is an explicit operator-blocking task.
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

INTERFACE: Final = "DatasetsReferenceHighLevelObjectiveBinding@1"
SCHEMA: Final = (
    "ipfs_datasets_py/assurance/reference-high-level-objective-binding@1"
)
BINDING_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/declared-reference-objective-binding@1"
)
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/reference-high-level-objective-verdict@1"
)
NORMATIVE_SOURCE: Final = (
    "ipfs_accelerate_py/assurance/declared-reference-objective@1"
)
NORMATIVE_INTERFACE: Final = "AccelerateReferenceHighLevelObjective@1"
PCPR_060_TASK_ID: Final = "PCPR-060"
PCPR_060_GOAL_ID: Final = "PCPR-G700"
PCPR_061_TASK_ID: Final = "PCPR-061"
PCPR_062_TASK_ID: Final = "PCPR-062"
PCPR_057_TASK_ID: Final = "PCPR-057"
PCPR_002_TASK_ID: Final = "PCPR-002"
PCPR_001_TASK_ID: Final = "PCPR-001"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"
OBJECTIVE_KIND: Final = "declared_reference_high_level_objective_binding"
PORTFOLIO_ID: Final = "portfolio:pcpr-v1"
PORTFOLIO_VERSION: Final = "proof-carrying-platform-0.1.0"
LANGUAGE: Final = "Python"
OBJECTIVE_ID: Final = "PCPR-G700"
OPERATOR_BLOCKING_TASK_ID: Final = (
    "pcpr-060-operator-live-objective-materialization"
)
PINNED_LOCK_CID: Final = (
    "baguqeerawsekbbbt5ccctjt4tydzeahfkahsatb6q5x7k6cy4inrii5lhqmq"
)
PINNED_BRANCH_POLICY_CID: Final = (
    "baguqeeram3uegwfx6c4i76eyj5nuzlgsqw6yl5vb5c6drkuyacn5l77ksnna"
)
PINNED_RELEASE_GATE_CID: Final = (
    "baguqeerajahrusqwd33fqbuw46zgqcsw4xsuswdqq6td7c3nyddeeg5qofca"
)
# Filled after Accelerate encoder measurement. Must match Accelerate pins.
PINNED_IDEA_DIGEST: Final = (
    "baguqeeracbayojdov4jmqiirx22pavrg6nabazcocru6y3scrdx5e54mw2zq"
)
PINNED_OBJECTIVE_CID: Final = (
    "baguqeeraynsn7tjr3iaggnreylzxo3akaooqwp5bf5oheaa6eubth2zwqeba"
)

BINDING_DIR_RELPATH: Final = "packaging/pcpr/reference-workflow/cpython312"
BINDING_JSON_NAME: Final = "reference.binding.json"
BINDING_README_RELPATH: Final = "packaging/pcpr/reference-workflow/README.md"
SOURCE_DATE_EPOCH: Final = "0"

REFERENCE_OBJECTIVE_IDEA: Final = (
    "Modify a typed formal-logic API while reusing unaffected proofs, "
    "selecting only impacted tests, rejecting stale-tree evidence, and "
    "producing a complete proof-carrying execution receipt."
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_060_reference_high_level_objective.py",
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
        "pyproject_reference_high_level_objective_table",
        "objective_cid_matches_pin",
        "idea_digest_matches_pin",
        "lock_cid_matches_pin",
        "context_pack_not_constructed",
        "duckdb_or_quack_not_written",
        "operator_blocking_task_emitted",
        "manifest_advertises_reference_high_level_objective",
        "no_closed_release_outcome",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "simulated_results_represented_as_live",
        "live_materialization_represented_as_live",
        "closed_release_represented_as_live",
        "compatibility_identities_reminted",
        "sibling_import_observed",
        "context_pack_constructed",
    }
)

BINDING_README: Final = """# PCPR-060 Datasets reference high-level objective binding

These files bind Datasets to the Accelerate-owned declared reference
high-level objective for proof-carrying-platform-0.1.0. They do not
remint that identity, do not import sibling packages, and do not
construct a ContextPack.

Semantic-impact inspection and ContextPack construction remain
PCPR-061. This binding is not a live Supervisor submission, not live
materialization, not a freeze, and not a closed PCPR release. Missing a
live Quack-fenced session is an explicit operator-blocking task.

Exact commit and tree are bound by the PCPR-060 receipt
`current_tree_binding`. `origin/main` is not the release identity.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
"""


class DatasetsReferenceHighLevelObjectiveError(ValueError):
    """Datasets attempted to remint a reference-objective identity."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetsReferenceHighLevelObjectiveError(
            f"{name} must be a non-empty string"
        )
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise DatasetsReferenceHighLevelObjectiveError(
            f"{name} is not an admitted evidence kind"
        )
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsReferenceHighLevelObjectiveError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def parse_pyproject_objective_table(text: str) -> dict[str, Any]:
    import tomllib

    table = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(table, dict):
        raise DatasetsReferenceHighLevelObjectiveError(
            "pyproject.toml must be a table"
        )
    tool = table.get("tool")
    payload: dict[str, Any] = {}
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            raw = datasets.get("reference-high-level-objective")
            if isinstance(raw, dict):
                payload = dict(raw)
    return payload


def refuse_objective_remint(cid: str) -> str:
    if cid != PINNED_OBJECTIVE_CID:
        raise DatasetsReferenceHighLevelObjectiveError(
            f"reference objective CID {cid} remints {PINNED_OBJECTIVE_CID}"
        )
    return cid


def refuse_idea_digest_remint(cid: str) -> str:
    if cid != PINNED_IDEA_DIGEST:
        raise DatasetsReferenceHighLevelObjectiveError(
            f"idea digest {cid} remints {PINNED_IDEA_DIGEST}"
        )
    return cid


def refuse_lock_remint(cid: str) -> str:
    if cid != PINNED_LOCK_CID:
        raise DatasetsReferenceHighLevelObjectiveError(
            f"portfolio compatibility lock CID {cid} remints {PINNED_LOCK_CID}"
        )
    return cid


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
class DatasetsReferenceHighLevelObjectiveVerdict:
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
    live_objective_submission: bool
    live_materialization: bool
    live_context_pack: bool
    operator_blocking_task: str
    simulated_results_represented_as_live: bool
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str
    objective_cid: str
    idea_digest: str
    binding_cid: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "objective_cid": self.objective_cid,
            "idea_digest": self.idea_digest,
            "binding_cid": self.binding_cid,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "sibling_source_required": self.sibling_source_required,
            "live_objective_submission": self.live_objective_submission,
            "live_materialization": self.live_materialization,
            "live_context_pack": self.live_context_pack,
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
            "An admitted Quack-fenced state-owner session on the repaired "
            "PCPR-004 path before Datasets inspects live semantic impact"
        ),
        "action": (
            "Do not construct a ContextPack in this task. PCPR-061 inspects "
            "semantic impact after the declared objective identity is bound."
        ),
        "reason": (
            "This binding does not perform live materialization or ContextPack "
            "construction. Missing live submission stays typed unavailable."
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
            "field": "PCPR-060 receipt current_tree_binding",
            "reason": (
                "Exact commit and tree are bound by the task receipt "
                "because nested admission rewrites HEAD."
            ),
        },
    }


def render_declared_binding(root: Path | None = None) -> dict[str, Any]:
    package_root = root or discover_datasets_root()
    if package_root is None:
        raise DatasetsReferenceHighLevelObjectiveError(
            "Datasets package root was not found"
        )
    _ = package_root
    document = {
        "schema": BINDING_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_060_TASK_ID,
        "goal_id": PCPR_060_GOAL_ID,
        "program_id": PCPR_PROGRAM_ID,
        "owner_repository": OWNER_REPOSITORY,
        "normative_source": NORMATIVE_SOURCE,
        "normative_interface": NORMATIVE_INTERFACE,
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
        "branch_policy_cid": PINNED_BRANCH_POLICY_CID,
        "release_gate_cid": PINNED_RELEASE_GATE_CID,
        "owned_contracts": ["SupervisorContextPack", "SemanticArtifactIdentity"],
        "context_pack": {
            "task_id": PCPR_061_TASK_ID,
            "constructed": False,
            "live": False,
            "deferred": True,
            "reason": "Datasets ContextPack construction remains PCPR-061.",
        },
        "storage": {
            "task_id": PCPR_062_TASK_ID,
            "stored": False,
            "deferred": True,
        },
        "materialization": {
            "kind": "declared_binding_not_live",
            "admitted": False,
            "live": False,
            "applied": False,
            "duckdb_or_quack_state_written": False,
            "evidence_kind": "unavailable",
        },
        "live_semantic_impact": typed_unavailable(
            reason="Semantic-impact inspection is PCPR-061, not this binding."
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
    document["binding_cid"] = content_identity(
        {key: value for key, value in document.items() if key != "binding_cid"}
    )
    return document


def artifact_paths(root: Path) -> dict[str, Path]:
    return {
        "binding": root / BINDING_DIR_RELPATH / BINDING_JSON_NAME,
        "readme": root / BINDING_README_RELPATH,
    }


def write_reference_objective_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsReferenceHighLevelObjectiveError(
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


def verify_reference_objective_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsReferenceHighLevelObjectiveError(
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
        "objective_cid": binding["objective_cid"],
        "idea_digest": binding["idea_digest"],
        "binding_cid": binding["binding_cid"],
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
        raise DatasetsReferenceHighLevelObjectiveError(
            "Datasets package root was not found"
        )
    binding = render_declared_binding(root)
    verified = verify_reference_objective_files(root)
    table = parse_pyproject_objective_table(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST

    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    schema_roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
    operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
    remint = (
        binding["objective_cid"] != PINNED_OBJECTIVE_CID
        or binding["idea_digest"] != PINNED_IDEA_DIGEST
        or binding["lock_cid"] != PINNED_LOCK_CID
    )
    probes = [
        _probe(
            "binding_files_match_generator",
            verified.get("ok") is True and verified.get("binding_ok") is True,
            reason=(
                "Committed Datasets objective binding matches the generator."
                if verified.get("binding_ok") is True
                else "Committed Datasets objective binding is missing or drifts."
            ),
            details=verified,
        ),
        _probe(
            "pyproject_reference_high_level_objective_table",
            table.get("interface") == INTERFACE
            and table.get("schema") == SCHEMA
            and table.get("task-id") == PCPR_060_TASK_ID
            and table.get("objective-kind") == OBJECTIVE_KIND,
            reason=(
                "pyproject.toml declares DatasetsReferenceHighLevelObjectiveBinding@1."
                if table.get("interface") == INTERFACE
                else "pyproject.toml does not declare the PCPR-060 binding."
            ),
            details={"table": table},
        ),
        _probe(
            "objective_cid_matches_pin",
            binding["objective_cid"] == PINNED_OBJECTIVE_CID,
            reason="Datasets binds the Accelerate-owned objective CID without remint.",
        ),
        _probe(
            "idea_digest_matches_pin",
            binding["idea_digest"] == PINNED_IDEA_DIGEST,
            reason="Datasets binds the Accelerate-owned idea digest without remint.",
        ),
        _probe(
            "lock_cid_matches_pin",
            binding["lock_cid"] == PINNED_LOCK_CID,
            reason="Datasets binds the Accelerate-owned lock CID without remint.",
        ),
        _probe(
            "context_pack_not_constructed",
            binding["context_pack"]["constructed"] is False
            and binding["context_pack"]["task_id"] == PCPR_061_TASK_ID,
            reason="ContextPack construction remains PCPR-061.",
        ),
        _probe(
            "context_pack_constructed",
            False,
            reason="This binding must not construct a ContextPack.",
        ),
        _probe(
            "duckdb_or_quack_not_written",
            binding["duckdb_or_quack_state_written"] is False,
            reason="This binding does not write DuckDB or Quack state.",
        ),
        _probe(
            "operator_blocking_task_emitted",
            binding["operator_blocking_task"]["task_id"] == OPERATOR_BLOCKING_TASK_ID
            and binding["operator_blocking_task"]["status"] == "typed_blocked",
            reason="Missing live materialization emits the operator-blocking task.",
        ),
        _probe(
            "manifest_advertises_reference_high_level_objective",
            versions.get(INTERFACE) == "1"
            and schema_roots.get("datasets_reference_high_level_objective") == SCHEMA
            and operations.get("reference_high_level_objective") == "1"
            and DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False,
            reason="LogicPlatformManifest advertises DatasetsReferenceHighLevelObjectiveBinding@1.",
        ),
        _probe(
            "no_closed_release_outcome",
            binding["closed_release_outcome"] is None
            and binding["release_claim"] is False,
            reason="This binding does not emit a closed PCPR release outcome.",
        ),
        _probe(
            "compatibility_identities_reminted",
            remint,
            reason="A reminted objective, idea, or lock CID is forbidden.",
        ),
        _probe(
            "sibling_import_observed",
            False,
            reason="This binding does not import sibling Accelerate or Kit packages.",
        ),
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        ),
        _probe(
            "live_materialization_represented_as_live",
            False,
            reason="No live materialization is represented as live.",
        ),
        _probe(
            "closed_release_represented_as_live",
            False,
            reason="This task does not publish a PCPR release.",
        ),
        _probe(
            "live_objective_submission",
            None,
            evidence_kind="unavailable",
            reason="Live objective submission was not performed.",
        ),
        _probe(
            "live_materialization",
            None,
            evidence_kind="unavailable",
            reason="Live DuckDB/Quack materialization stays typed unavailable.",
        ),
    ]
    return tuple(probes)


def qualify_reference_high_level_objective(
    probes: Sequence[OutcomeProbe],
    *,
    objective_cid: str,
    idea_digest_cid: str,
    binding_cid: str,
) -> DatasetsReferenceHighLevelObjectiveVerdict:
    if not probes:
        raise DatasetsReferenceHighLevelObjectiveError(
            "at least one probe is required"
        )
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise DatasetsReferenceHighLevelObjectiveError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise DatasetsReferenceHighLevelObjectiveError(
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
        "task_id": PCPR_060_TASK_ID,
        "goal_id": PCPR_060_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": False,
        "live_objective_submission": False,
        "live_materialization": False,
        "live_context_pack": False,
        "operator_blocking_task": OPERATOR_BLOCKING_TASK_ID,
        "simulated_results_represented_as_live": False,
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
        "objective_cid": objective_cid,
        "idea_digest": idea_digest_cid,
        "binding_cid": binding_cid,
    }
    return DatasetsReferenceHighLevelObjectiveVerdict(
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
        live_objective_submission=False,
        live_materialization=False,
        live_context_pack=False,
        operator_blocking_task=OPERATOR_BLOCKING_TASK_ID,
        simulated_results_represented_as_live=False,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
        objective_cid=objective_cid,
        idea_digest=idea_digest_cid,
        binding_cid=binding_cid,
    )


def qualify_current_head_reference_high_level_objective(
    start: Path | None = None,
) -> DatasetsReferenceHighLevelObjectiveVerdict:
    binding = render_declared_binding(start)
    return qualify_reference_high_level_objective(
        current_head_static_probes(start),
        objective_cid=str(binding["objective_cid"]),
        idea_digest_cid=str(binding["idea_digest"]),
        binding_cid=str(binding["binding_cid"]),
    )


def pcpr_060_receipt_promotion(
    verdict: DatasetsReferenceHighLevelObjectiveVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise DatasetsReferenceHighLevelObjectiveError(
            "reference objective binding must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise DatasetsReferenceHighLevelObjectiveError(
            "reference objective binding must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise DatasetsReferenceHighLevelObjectiveError(
            "reference-objective binding completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise DatasetsReferenceHighLevelObjectiveError(
            "reference objective binding must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsReferenceHighLevelObjectiveError(
            "promotion_status must not be a closed release outcome"
        )
    if verdict.live_context_pack:
        raise DatasetsReferenceHighLevelObjectiveError(
            "ContextPack construction remains PCPR-061"
        )
    return verdict.to_mapping()


CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeerap4yktrcoukl42455auhc7dqwrrjgm5n4hpfbf6cibepzzfwcdenq"
)
PINNED_BINDING_CID: Final = (
    "baguqeera3eu7bvbep4tq3j3f26ra6qtcgro26nu74yqsabe5meflruyq76eq"
)


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "DatasetsReferenceHighLevelObjectiveError",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OPERATOR_BLOCKING_TASK_ID",
    "OutcomeProbe",
    "PCPR_060_GOAL_ID",
    "PCPR_060_TASK_ID",
    "PINNED_BINDING_CID",
    "PINNED_IDEA_DIGEST",
    "PINNED_LOCK_CID",
    "PINNED_OBJECTIVE_CID",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "current_head_static_probes",
    "pcpr_060_receipt_promotion",
    "qualify_current_head_reference_high_level_objective",
    "qualify_reference_high_level_objective",
    "refuse_idea_digest_remint",
    "refuse_lock_remint",
    "refuse_objective_remint",
    "render_declared_binding",
    "verify_reference_objective_files",
    "write_reference_objective_files",
]
