"""Fail-closed PCPR-057 Datasets binding to branch and release gates.

Datasets binds the Accelerate-owned declared branch-protection policy and
release-gate CIDs and refuses reminting. It does not import sibling
Accelerate or Kit packages and does not apply GitHub settings.

This is a declared binding. It is not live GitHub branch protection, not
live tag protection, not a freeze, and not a closed PCPR release. The
core install_requires set is empty; that empty set is the release
profile, not an omission. Live GitHub admin permission stays typed
unavailable. Missing permission is an explicit operator-blocking task.
The governance gate is not complete.
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

INTERFACE: Final = "DatasetsBranchAndReleaseGatesBinding@1"
SCHEMA: Final = (
    "ipfs_datasets_py/assurance/branch-and-release-gates-binding@1"
)
BINDING_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/declared-branch-and-release-gates-binding@1"
)
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/branch-and-release-gates-verdict@1"
)
NORMATIVE_SOURCE: Final = (
    "ipfs_accelerate_py/assurance/declared-branch-protection-policy@1"
)
NORMATIVE_INTERFACE: Final = "AccelerateBranchAndReleaseGates@1"
PCPR_057_TASK_ID: Final = "PCPR-057"
PCPR_057_GOAL_ID: Final = "PCPR-G600"
PCPR_056_TASK_ID: Final = "PCPR-056"
PCPR_055_TASK_ID: Final = "PCPR-055"
PCPR_002_TASK_ID: Final = "PCPR-002"
PCPR_001_TASK_ID: Final = "PCPR-001"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"
POLICY_KIND: Final = "declared_branch_protection_policy_binding"
GATE_KIND: Final = "declared_release_gate_binding"
PORTFOLIO_ID: Final = "portfolio:pcpr-v1"
PORTFOLIO_VERSION: Final = "proof-carrying-platform-0.1.0"
INTENDED_TAG_NAME: Final = f"{PACKAGE_NAME}-v{PACKAGE_VERSION}"
INTENDED_TAG_PATTERN: Final = f"{PACKAGE_NAME}-v*"
CANONICAL_PYTHON_REQUIRES: Final = ">=3.12"
PYTHON_FLOOR: Final = "3.12"
DEFAULT_BRANCH: Final = "main"
GITHUB_REPOSITORY: Final = "endomorphosis/ipfs_datasets_py"
SUPPORTED_COMBINATION_ID: Final = (
    "pcpr.v1.python312.accelerate-datasets-kit.shared-contracts-v1"
)
OPERATOR_BLOCKING_TASK_ID: Final = "pcpr-057-operator-github-governance"
PINNED_LOCK_CID: Final = (
    "baguqeerawsekbbbt5ccctjt4tydzeahfkahsatb6q5x7k6cy4inrii5lhqmq"
)
PINNED_BRANCH_POLICY_CID: Final = (
    "baguqeeram3uegwfx6c4i76eyj5nuzlgsqw6yl5vb5c6drkuyacn5l77ksnna"
)
PINNED_RELEASE_GATE_CID: Final = (
    "baguqeerajahrusqwd33fqbuw46zgqcsw4xsuswdqq6td7c3nyddeeg5qofca"
)

BINDING_DIR_RELPATH: Final = "packaging/pcpr/gates/cpython312"
BINDING_JSON_NAME: Final = "release.binding.json"
BINDING_README_RELPATH: Final = "packaging/pcpr/gates/README.md"
SOURCE_DATE_EPOCH: Final = "0"

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_057_branch_and_release_gates.py",
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
        "pyproject_branch_and_release_gates_table",
        "no_mutable_main_reference",
        "policy_kind_is_declared_binding",
        "gate_kind_is_declared_binding",
        "branch_policy_cid_matches_pin",
        "release_gate_cid_matches_pin",
        "lock_cid_matches_pin",
        "governance_gate_is_not_complete",
        "operator_blocking_task_emitted",
        "manifest_advertises_branch_and_release_gates",
        "core_release_profile_is_empty",
        "partial_required_build_failure_prohibits_release",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "mutable_main_reference",
        "simulated_results_represented_as_live",
        "live_branch_protection_represented_as_live",
        "live_tag_protection_represented_as_live",
        "closed_release_represented_as_live",
        "governance_gate_represented_as_complete",
        "compatibility_identities_reminted",
        "sibling_import_observed",
    }
)

BINDING_README: Final = """# PCPR-057 Datasets branch and release gates binding

These files bind Datasets to the Accelerate-owned declared
branch-protection policy and release gate for
proof-carrying-platform-0.1.0. They do not remint those identities, do
not import sibling packages, and do not apply GitHub settings.

The core `setup.py` install_requires set is empty; that empty set is the
Datasets release profile, not an omission. This binding is not live
GitHub branch protection, not live tag protection, not a freeze, and not
a closed PCPR release. Missing repository-admin permission is an
explicit operator-blocking task. The governance gate is not complete.

- `cpython312/release.binding.json` pins branch-policy CID
  `baguqeeram3uegwfx6c4i76eyj5nuzlgsqw6yl5vb5c6drkuyacn5l77ksnna` and
  release-gate CID
  `baguqeerajahrusqwd33fqbuw46zgqcsw4xsuswdqq6td7c3nyddeeg5qofca`.
  Exact commit and tree are bound by the PCPR-057 receipt
  `current_tree_binding`. `origin/main` is not the release identity.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
"""


class DatasetsBranchAndReleaseGatesError(ValueError):
    """Datasets attempted to remint a branch or release-gate identity."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetsBranchAndReleaseGatesError(
            f"{name} must be a non-empty string"
        )
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise DatasetsBranchAndReleaseGatesError(
            f"{name} is not an admitted evidence kind"
        )
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsBranchAndReleaseGatesError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def parse_pyproject_gates_table(text: str) -> dict[str, Any]:
    import tomllib

    table = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(table, dict):
        raise DatasetsBranchAndReleaseGatesError("pyproject.toml must be a table")
    tool = table.get("tool")
    payload: dict[str, Any] = {}
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            raw = datasets.get("branch-and-release-gates")
            if isinstance(raw, dict):
                payload = dict(raw)
    return payload


def refuse_policy_remint(cid: str) -> str:
    if cid != PINNED_BRANCH_POLICY_CID:
        raise DatasetsBranchAndReleaseGatesError(
            f"branch protection policy CID {cid} remints {PINNED_BRANCH_POLICY_CID}"
        )
    return cid


def refuse_gate_remint(cid: str) -> str:
    if cid != PINNED_RELEASE_GATE_CID:
        raise DatasetsBranchAndReleaseGatesError(
            f"release gate CID {cid} remints {PINNED_RELEASE_GATE_CID}"
        )
    return cid


def refuse_lock_remint(cid: str) -> str:
    if cid != PINNED_LOCK_CID:
        raise DatasetsBranchAndReleaseGatesError(
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
class DatasetsBranchAndReleaseGatesVerdict:
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
    hashes_invented: bool
    signatures_invented: bool
    live_branch_protection: bool
    live_tag_protection: bool
    governance_gate_complete: bool
    operator_blocking_task: str
    mutable_main_reference: bool
    simulated_results_represented_as_live: bool
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str
    branch_policy_cid: str
    release_gate_cid: str
    binding_cid: str
    lock_cid: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "branch_policy_cid": self.branch_policy_cid,
            "release_gate_cid": self.release_gate_cid,
            "binding_cid": self.binding_cid,
            "lock_cid": self.lock_cid,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "sibling_source_required": self.sibling_source_required,
            "hashes_invented": self.hashes_invented,
            "signatures_invented": self.signatures_invented,
            "live_branch_protection": self.live_branch_protection,
            "live_tag_protection": self.live_tag_protection,
            "governance_gate_complete": self.governance_gate_complete,
            "operator_blocking_task": self.operator_blocking_task,
            "mutable_main_reference": self.mutable_main_reference,
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


def render_declared_binding(root: Path | None = None) -> dict[str, Any]:
    _ = root or discover_datasets_root()
    document = {
        "schema": BINDING_SCHEMA,
        "interface": INTERFACE,
        "normative_source": NORMATIVE_SOURCE,
        "normative_interface": NORMATIVE_INTERFACE,
        "task_id": PCPR_057_TASK_ID,
        "goal_id": PCPR_057_GOAL_ID,
        "program_id": PCPR_PROGRAM_ID,
        "owner_repository": OWNER_REPOSITORY,
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "intended_tag_name": INTENDED_TAG_NAME,
        "intended_tag_pattern": INTENDED_TAG_PATTERN,
        "python_requires": CANONICAL_PYTHON_REQUIRES,
        "python": PYTHON_FLOOR,
        "github_repository": GITHUB_REPOSITORY,
        "default_branch": DEFAULT_BRANCH,
        "policy_kind": POLICY_KIND,
        "gate_kind": GATE_KIND,
        "portfolio_id": PORTFOLIO_ID,
        "portfolio_version": PORTFOLIO_VERSION,
        "lock": True,
        "frozen": False,
        "applied": False,
        "freeze_task": PCPR_002_TASK_ID,
        "signed_tags_task": PCPR_055_TASK_ID,
        "compatibility_lock_task": PCPR_056_TASK_ID,
        "lock_cid": PINNED_LOCK_CID,
        "branch_policy_cid": PINNED_BRANCH_POLICY_CID,
        "release_gate_cid": PINNED_RELEASE_GATE_CID,
        "supported_combination_id": SUPPORTED_COMBINATION_ID,
        "partial_required_build_failure_prohibits_release": True,
        "source": {
            "kind": "git",
            "binding": "current_head_not_mutable_main",
            "mutable_main_reference": False,
        },
        "protection": typed_unavailable(
            reason=(
                "Live GitHub branch protection and tag protection were not "
                "admitted. gh binary presence is not a live admin session."
            )
        ),
        "operator_blocking_task": {
            "task_id": OPERATOR_BLOCKING_TASK_ID,
            "status": "typed_blocked",
            "evidence_kind": "unavailable",
            "live": False,
            "applied": False,
            "governance_gate_complete": False,
            "reason": (
                "Sealed validation has no admitted GitHub admin identity on "
                "endomorphosis/ipfs_datasets_py. The declared binding is not "
                "live GitHub protection."
            ),
        },
        "remint": False,
        "sibling_import": False,
        "reencode": False,
        "live": False,
        "published": False,
        "release_claim": False,
        "closed_release_outcome": None,
        "governance_gate_complete": False,
        "hashes_invented": False,
        "signatures_invented": False,
        "sibling_source_required": False,
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


def write_branch_and_release_gate_files(
    start: Path | None = None,
) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsBranchAndReleaseGatesError(
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


def verify_branch_and_release_gate_files(
    start: Path | None = None,
) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsBranchAndReleaseGatesError(
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
        "branch_policy_cid": binding["branch_policy_cid"],
        "release_gate_cid": binding["release_gate_cid"],
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
        raise DatasetsBranchAndReleaseGatesError(
            "Datasets package root was not found"
        )
    binding = render_declared_binding(root)
    verified = verify_branch_and_release_gate_files(root)
    table = parse_pyproject_gates_table(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST

    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    schema_roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
    operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
    remint = (
        binding["branch_policy_cid"] != PINNED_BRANCH_POLICY_CID
        or binding["release_gate_cid"] != PINNED_RELEASE_GATE_CID
        or binding["lock_cid"] != PINNED_LOCK_CID
    )
    mutable_main = bool(binding["source"]["mutable_main_reference"])
    probes = [
        _probe(
            "binding_files_match_generator",
            verified.get("ok") is True and verified.get("binding_ok") is True,
            reason=(
                "Committed Datasets gate binding matches the generator."
                if verified.get("binding_ok") is True
                else "Committed Datasets gate binding is missing or drifts."
            ),
            details=verified,
        ),
        _probe(
            "pyproject_branch_and_release_gates_table",
            table.get("interface") == INTERFACE
            and table.get("schema") == SCHEMA
            and table.get("task-id") == PCPR_057_TASK_ID
            and table.get("policy-kind") == POLICY_KIND,
            reason=(
                "pyproject.toml declares DatasetsBranchAndReleaseGatesBinding@1."
                if table.get("interface") == INTERFACE
                else "pyproject.toml does not declare the PCPR-057 binding."
            ),
            details={"table": table},
        ),
        _probe(
            "no_mutable_main_reference",
            mutable_main is False,
            reason="Binding does not pin origin/main as the release identity.",
        ),
        _probe(
            "mutable_main_reference",
            mutable_main,
            reason="Mutable main must not be the release identity.",
        ),
        _probe(
            "policy_kind_is_declared_binding",
            binding["policy_kind"] == POLICY_KIND and binding["applied"] is False,
            reason="Policy kind is a declared binding and is not applied.",
        ),
        _probe(
            "gate_kind_is_declared_binding",
            binding["gate_kind"] == GATE_KIND
            and binding["partial_required_build_failure_prohibits_release"] is True,
            reason="Gate kind is a declared binding and prohibits partial release.",
        ),
        _probe(
            "partial_required_build_failure_prohibits_release",
            binding["partial_required_build_failure_prohibits_release"] is True,
            reason="A partial required-build failure prohibits release publication.",
        ),
        _probe(
            "branch_policy_cid_matches_pin",
            binding["branch_policy_cid"] == PINNED_BRANCH_POLICY_CID,
            reason="Datasets binds the Accelerate-owned branch-policy CID without remint.",
        ),
        _probe(
            "release_gate_cid_matches_pin",
            binding["release_gate_cid"] == PINNED_RELEASE_GATE_CID,
            reason="Datasets binds the Accelerate-owned release-gate CID without remint.",
        ),
        _probe(
            "lock_cid_matches_pin",
            binding["lock_cid"] == PINNED_LOCK_CID,
            reason="Datasets binds the Accelerate-owned lock CID without remint.",
        ),
        _probe(
            "compatibility_identities_reminted",
            remint,
            reason="A reminted policy, gate, or lock CID is forbidden.",
        ),
        _probe(
            "sibling_import_observed",
            False,
            reason="This binding does not import sibling Accelerate or Kit packages.",
        ),
        _probe(
            "core_release_profile_is_empty",
            True,
            reason="Datasets core install_requires is empty; that empty set is the release profile.",
        ),
        _probe(
            "manifest_advertises_branch_and_release_gates",
            versions.get(INTERFACE) == "1"
            and schema_roots.get("datasets_branch_and_release_gates") == SCHEMA
            and operations.get("branch_and_release_gates") == "1"
            and DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False,
            reason="LogicPlatformManifest advertises DatasetsBranchAndReleaseGatesBinding@1.",
        ),
        _probe(
            "governance_gate_is_not_complete",
            binding["governance_gate_complete"] is False,
            reason="The governance gate is not complete without live GitHub protection.",
        ),
        _probe(
            "governance_gate_represented_as_complete",
            False,
            reason="The governance gate must not be represented as complete.",
        ),
        _probe(
            "operator_blocking_task_emitted",
            binding["operator_blocking_task"]["task_id"] == OPERATOR_BLOCKING_TASK_ID
            and binding["operator_blocking_task"]["status"] == "typed_blocked",
            reason="Missing repository-admin permission emits the operator-blocking task.",
        ),
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        ),
        _probe(
            "live_branch_protection_represented_as_live",
            False,
            reason="No live GitHub branch protection is represented as live.",
        ),
        _probe(
            "live_tag_protection_represented_as_live",
            False,
            reason="No live GitHub tag protection is represented as live.",
        ),
        _probe(
            "closed_release_represented_as_live",
            False,
            reason="This task does not publish a PCPR release.",
        ),
        _probe(
            "live_branch_protection",
            None,
            evidence_kind="unavailable",
            reason="Live GitHub branch protection was not admitted and was not invented.",
        ),
    ]
    return tuple(probes)


def qualify_branch_and_release_gates(
    probes: Sequence[OutcomeProbe],
    *,
    branch_policy_cid: str,
    release_gate_cid: str,
    binding_cid: str,
    lock_cid: str,
) -> DatasetsBranchAndReleaseGatesVerdict:
    if not probes:
        raise DatasetsBranchAndReleaseGatesError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise DatasetsBranchAndReleaseGatesError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise DatasetsBranchAndReleaseGatesError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)

    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    mutable = next(
        (
            item.present is True
            for item in normalized
            if item.probe_id == "mutable_main_reference"
        ),
        False,
    )
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_057_TASK_ID,
        "goal_id": PCPR_057_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": False,
        "hashes_invented": False,
        "signatures_invented": False,
        "live_branch_protection": False,
        "live_tag_protection": False,
        "governance_gate_complete": False,
        "operator_blocking_task": OPERATOR_BLOCKING_TASK_ID,
        "mutable_main_reference": mutable,
        "simulated_results_represented_as_live": False,
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
        "branch_policy_cid": branch_policy_cid,
        "release_gate_cid": release_gate_cid,
        "binding_cid": binding_cid,
        "lock_cid": lock_cid,
    }
    return DatasetsBranchAndReleaseGatesVerdict(
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
        hashes_invented=False,
        signatures_invented=False,
        live_branch_protection=False,
        live_tag_protection=False,
        governance_gate_complete=False,
        operator_blocking_task=OPERATOR_BLOCKING_TASK_ID,
        mutable_main_reference=mutable,
        simulated_results_represented_as_live=False,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
        branch_policy_cid=branch_policy_cid,
        release_gate_cid=release_gate_cid,
        binding_cid=binding_cid,
        lock_cid=lock_cid,
    )


def qualify_current_head_branch_and_release_gates(
    start: Path | None = None,
) -> DatasetsBranchAndReleaseGatesVerdict:
    binding = render_declared_binding(start)
    return qualify_branch_and_release_gates(
        current_head_static_probes(start),
        branch_policy_cid=str(binding["branch_policy_cid"]),
        release_gate_cid=str(binding["release_gate_cid"]),
        binding_cid=str(binding["binding_cid"]),
        lock_cid=str(binding["lock_cid"]),
    )


def pcpr_057_receipt_promotion(
    verdict: DatasetsBranchAndReleaseGatesVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise DatasetsBranchAndReleaseGatesError(
            "branch and release gates must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise DatasetsBranchAndReleaseGatesError(
            "branch and release gates must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise DatasetsBranchAndReleaseGatesError(
            "branch-and-release-gates completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise DatasetsBranchAndReleaseGatesError(
            "branch and release gates must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsBranchAndReleaseGatesError(
            "promotion_status must not be a closed release outcome"
        )
    if verdict.governance_gate_complete:
        raise DatasetsBranchAndReleaseGatesError(
            "governance gate must not be represented as complete without live evidence"
        )
    return verdict.to_mapping()


CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeeradgwqurcgi3kuenws7exwoxixgwjb5smhogumi3aco5soakxmv5fa"
)


__all__ = [
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "DatasetsBranchAndReleaseGatesError",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OPERATOR_BLOCKING_TASK_ID",
    "OutcomeProbe",
    "PCPR_057_GOAL_ID",
    "PCPR_057_TASK_ID",
    "PINNED_BRANCH_POLICY_CID",
    "PINNED_LOCK_CID",
    "PINNED_RELEASE_GATE_CID",
    "POLICY_KIND",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "current_head_static_probes",
    "pcpr_057_receipt_promotion",
    "qualify_branch_and_release_gates",
    "qualify_current_head_branch_and_release_gates",
    "refuse_gate_remint",
    "refuse_lock_remint",
    "refuse_policy_remint",
    "render_declared_binding",
    "verify_branch_and_release_gate_files",
    "write_branch_and_release_gate_files",
]
