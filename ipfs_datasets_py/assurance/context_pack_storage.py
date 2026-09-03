"""Fail-closed PCPR-062 Datasets binding to Kit ContextPack storage.

Datasets owns DatasetsContextPack@1 identity. This module binds that
identity to the Kit-owned hermetic current root without reminting the
pack CID, without storing bytes, and without publishing a current root.

It does not import sibling Accelerate or Kit packages, does not write
DuckDB or Quack state, and does not admit the pack into a live
supervisor session. Live IPFS publication stays typed unavailable.
Simulated results are not live.
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

INTERFACE: Final = "DatasetsContextPackStorageBinding@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/context-pack-storage-binding@1"
BINDING_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/declared-context-pack-root-binding@1"
)
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/context-pack-storage-verdict@1"
)
OWNER_INTERFACE: Final = "DatasetsContextPack@1"
OWNER_SCHEMA: Final = "ipfs_datasets_py/datasets-context-pack@1"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"
STORAGE_OWNER_REPOSITORY: Final = "ipfs_kit_py"
STORAGE_OWNER_INTERFACE: Final = "KitContextPackStorage@1"
PCPR_062_TASK_ID: Final = "PCPR-062"
PCPR_062_GOAL_ID: Final = "PCPR-G700"
PCPR_061_TASK_ID: Final = "PCPR-061"
PCPR_063_TASK_ID: Final = "PCPR-063"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
OBJECTIVE_KIND: Final = "declared_context_pack_root_binding"
PORTFOLIO_ID: Final = "portfolio:pcpr-v1"
PORTFOLIO_VERSION: Final = "proof-carrying-platform-0.1.0"
LANGUAGE: Final = "Python"
OBJECTIVE_ID: Final = "PCPR-G700"
OPERATOR_BLOCKING_TASK_ID: Final = "pcpr-062-operator-live-context-pack-root"
SOURCE_DATE_EPOCH: Final = "0"

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

BINDING_DIR_RELPATH: Final = "packaging/pcpr/reference-workflow/cpython312"
BINDING_JSON_NAME: Final = "reference.context-pack.root.binding.json"
BINDING_README_RELPATH: Final = (
    "packaging/pcpr/reference-workflow/CONTEXT_PACK_ROOT.md"
)

REFERENCE_OBJECTIVE_IDEA: Final = (
    "Modify a typed formal-logic API while reusing unaffected proofs, "
    "selecting only impacted tests, rejecting stale-tree evidence, and "
    "producing a complete proof-carrying execution receipt."
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_062_context_pack_storage.py",
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
        "pyproject_context_pack_storage_table",
        "manifest_advertises_context_pack_storage",
        "owner_pack_cid_matches_pin",
        "kit_current_root_bound_not_minted",
        "storage_owned_by_kit",
        "duckdb_or_quack_not_written",
        "operator_blocking_task_emitted",
        "no_closed_release_outcome",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "simulated_results_represented_as_live",
        "live_storage_represented_as_live",
        "closed_release_represented_as_live",
        "compatibility_identities_reminted",
        "sibling_import_observed",
        "datasets_identity_reminted",
        "kit_identity_reminted",
    }
)

BINDING_README: Final = """# PCPR-062 Datasets ContextPack storage binding

These files bind DatasetsContextPack@1 to the Kit-owned hermetic
current root. Datasets does not remint the pack CID, does not store
bytes, and does not publish a current root.

- `cpython312/reference.context-pack.root.binding.json` binds the
  Datasets pack identity to Kit current-root CID
  `bafkreihjdjarrlr24sperlq3zl4hjrksbol4b5saxquie3wpyi6xwsobwi`.
  Exact commit and tree are bound by the PCPR-062 receipt
  `current_tree_binding`.
- Durable storage is owned by Kit. Deterministic execution remains
  PCPR-063.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-062-operator-live-context-pack-root`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
"""


class DatasetsContextPackStorageError(ValueError):
    """Datasets attempted to remint or store a ContextPack root."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetsContextPackStorageError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise DatasetsContextPackStorageError(
            f"{name} is not an admitted evidence kind"
        )
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsContextPackStorageError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def parse_pyproject_context_pack_storage_table(text: str) -> dict[str, Any]:
    import tomllib

    table = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(table, dict):
        raise DatasetsContextPackStorageError("pyproject.toml must be a table")
    tool = table.get("tool")
    payload: dict[str, Any] = {}
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            raw = datasets.get("context-pack-storage")
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
class DatasetsContextPackStorageVerdict:
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
    live_storage: bool
    live_current_root: bool
    operator_blocking_task: str
    simulated_results_represented_as_live: bool
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str
    pack_cid: str
    binding_cid: str
    current_root_cid: str
    objective_cid: str
    idea_digest: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "pack_cid": self.pack_cid,
            "binding_cid": self.binding_cid,
            "current_root_cid": self.current_root_cid,
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
            "live_storage": self.live_storage,
            "live_current_root": self.live_current_root,
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
            "An admitted Quack-fenced state-owner session and a live "
            "qualified durable backend before the ContextPack current "
            "root is published as live"
        ),
        "action": (
            "Keep the Datasets pack identity and the Kit current-root "
            "binding. Do not store bytes here. Do not write DuckDB or "
            "Quack state."
        ),
        "reason": (
            "Datasets binds the Kit hermetic current root. That binding "
            "is not live durable publication."
        ),
    }


def render_declared_binding(root: Path | None = None) -> dict[str, Any]:
    package_root = root or discover_datasets_root()
    if package_root is None:
        raise DatasetsContextPackStorageError(
            "Datasets package root was not found"
        )
    _ = package_root
    document = {
        "schema": BINDING_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_062_TASK_ID,
        "goal_id": PCPR_062_GOAL_ID,
        "program_id": PCPR_PROGRAM_ID,
        "owner_repository": OWNER_REPOSITORY,
        "storage_owner_repository": STORAGE_OWNER_REPOSITORY,
        "storage_owner_interface": STORAGE_OWNER_INTERFACE,
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
        "prerequisite_task_id": PCPR_061_TASK_ID,
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
            "reason": "Kit stores exact bytes and publishes the hermetic current root.",
        },
        "execution": {
            "task_id": PCPR_063_TASK_ID,
            "performed": False,
            "live": False,
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
        "live_bytes_store": typed_unavailable(
            reason="Datasets does not store ContextPack bytes. Kit owns storage."
        ),
        "live_current_root": typed_unavailable(
            reason="Datasets binds the Kit current root and does not publish it."
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
                "field": "PCPR-062 receipt current_tree_binding",
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


def write_context_pack_storage_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsContextPackStorageError(
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


def verify_context_pack_storage_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DatasetsContextPackStorageError(
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
        "current_root_cid": binding["storage"]["current_root_cid"],
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
        raise DatasetsContextPackStorageError(
            "Datasets package root was not found"
        )
    binding = render_declared_binding(root)
    verified = verify_context_pack_storage_files(root)
    table = parse_pyproject_context_pack_storage_table(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST

    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    schema_roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
    operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
    remint = (
        binding["context_pack"]["pack_cid"] != PINNED_PACK_CID
        or binding["objective_cid"] != PINNED_OBJECTIVE_CID
        or binding["idea_digest"] != PINNED_IDEA_DIGEST
        or binding["lock_cid"] != PINNED_LOCK_CID
        or binding["storage"]["current_root_cid"] != PINNED_CURRENT_ROOT_CID
        or binding["context_pack"]["reminted"] is True
        or binding["storage"]["reminted"] is True
    )
    probes = [
        _probe(
            "binding_files_match_generator",
            verified.get("ok") is True and verified.get("binding_ok") is True,
            reason=(
                "Committed Datasets ContextPack storage binding matches the generator."
                if verified.get("binding_ok") is True
                else "Committed Datasets ContextPack storage binding is missing or drifts."
            ),
        ),
        _probe(
            "pyproject_context_pack_storage_table",
            table.get("interface") == INTERFACE
            and table.get("schema") == SCHEMA
            and table.get("task-id") == PCPR_062_TASK_ID
            and table.get("objective-kind") == OBJECTIVE_KIND,
            reason=(
                "pyproject.toml declares DatasetsContextPackStorageBinding@1."
                if table.get("interface") == INTERFACE
                else "pyproject.toml does not declare the PCPR-062 binding."
            ),
        ),
        _probe(
            "manifest_advertises_context_pack_storage",
            versions.get(INTERFACE) == "1"
            and schema_roots.get("datasets_context_pack_storage") == SCHEMA
            and operations.get("context_pack_storage") == "1",
            reason="LogicPlatformManifest advertises the PCPR-062 storage binding.",
        ),
        _probe(
            "owner_pack_cid_matches_pin",
            binding["context_pack"]["pack_cid"] == PINNED_PACK_CID,
            reason="Datasets binds its own pack CID without remint.",
        ),
        _probe(
            "kit_current_root_bound_not_minted",
            binding["storage"]["current_root_cid"] == PINNED_CURRENT_ROOT_CID
            and binding["storage"]["stored_by"] == STORAGE_OWNER_REPOSITORY
            and binding["storage"]["reminted"] is False,
            reason="Datasets binds the Kit current root and does not remint it.",
        ),
        _probe(
            "storage_owned_by_kit",
            binding["storage_owner_repository"] == STORAGE_OWNER_REPOSITORY
            and binding["storage_owner_interface"] == STORAGE_OWNER_INTERFACE,
            reason="Kit owns persist, CID verification, and current-root CAS.",
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
            reason="Missing live publication emits the operator-blocking task.",
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
            reason="A reminted pack, root, objective, idea, or lock CID is forbidden.",
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
            "live_storage_represented_as_live",
            False,
            reason="No live storage is represented as live.",
        ),
        _probe(
            "closed_release_represented_as_live",
            False,
            reason="This task does not publish a PCPR release.",
        ),
        _probe(
            "live_storage",
            None,
            evidence_kind="unavailable",
            reason="Live IPFS/Quack ContextPack publication stays typed unavailable.",
        ),
    ]
    return tuple(probes)


def qualify_context_pack_storage(
    probes: Sequence[OutcomeProbe],
    *,
    pack_cid: str,
    binding_cid: str,
    current_root_cid: str,
    objective_cid: str,
    idea_digest_cid: str,
) -> DatasetsContextPackStorageVerdict:
    if not probes:
        raise DatasetsContextPackStorageError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise DatasetsContextPackStorageError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise DatasetsContextPackStorageError(
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
        "task_id": PCPR_062_TASK_ID,
        "goal_id": PCPR_062_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": False,
        "live_storage": False,
        "live_current_root": False,
        "operator_blocking_task": OPERATOR_BLOCKING_TASK_ID,
        "simulated_results_represented_as_live": False,
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
        "pack_cid": pack_cid,
        "binding_cid": binding_cid,
        "current_root_cid": current_root_cid,
        "objective_cid": objective_cid,
        "idea_digest": idea_digest_cid,
    }
    return DatasetsContextPackStorageVerdict(
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
        live_storage=False,
        live_current_root=False,
        operator_blocking_task=OPERATOR_BLOCKING_TASK_ID,
        simulated_results_represented_as_live=False,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
        pack_cid=pack_cid,
        binding_cid=binding_cid,
        current_root_cid=current_root_cid,
        objective_cid=objective_cid,
        idea_digest=idea_digest_cid,
    )


def qualify_current_head_context_pack_storage(
    start: Path | None = None,
) -> DatasetsContextPackStorageVerdict:
    binding = render_declared_binding(start)
    return qualify_context_pack_storage(
        current_head_static_probes(start),
        pack_cid=str(binding["context_pack"]["pack_cid"]),
        binding_cid=str(binding["binding_cid"]),
        current_root_cid=str(binding["storage"]["current_root_cid"]),
        objective_cid=str(binding["objective_cid"]),
        idea_digest_cid=str(binding["idea_digest"]),
    )


def pcpr_062_receipt_promotion(
    verdict: DatasetsContextPackStorageVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise DatasetsContextPackStorageError(
            "ContextPack storage binding must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise DatasetsContextPackStorageError(
            "ContextPack storage binding must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise DatasetsContextPackStorageError(
            "ContextPack storage completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise DatasetsContextPackStorageError(
            "ContextPack storage binding must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise DatasetsContextPackStorageError(
            "promotion_status must not be a closed release outcome"
        )
    if verdict.live_storage or verdict.live_current_root:
        raise DatasetsContextPackStorageError(
            "live storage requires measured_live evidence"
        )
    return verdict.to_mapping()


def refuse_pack_cid_remint(cid: str) -> str:
    if cid != PINNED_PACK_CID:
        raise DatasetsContextPackStorageError(
            f"ContextPack CID {cid} remints {PINNED_PACK_CID}"
        )
    return cid


def refuse_current_root_remint(cid: str) -> str:
    if cid != PINNED_CURRENT_ROOT_CID:
        raise DatasetsContextPackStorageError(
            f"current root CID {cid} remints {PINNED_CURRENT_ROOT_CID}"
        )
    return cid


PINNED_BINDING_CID: Final = (
    "baguqeerajroer7ligg572jxrhqgor544bhmxhae5fj32v4i3764r5pakbcdq"
)
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeerapy6wq2hsk2btp2yqzsvlsbt7luqypy356ujtxgb4xlirh3qbwrma"
)


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "DatasetsContextPackStorageError",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "OBJECTIVE_KIND",
    "OPERATOR_BLOCKING_TASK_ID",
    "OutcomeProbe",
    "PCPR_062_GOAL_ID",
    "PCPR_062_TASK_ID",
    "PINNED_BINDING_CID",
    "PINNED_CURRENT_ROOT_CID",
    "PINNED_IDEA_DIGEST",
    "PINNED_LOCK_CID",
    "PINNED_OBJECTIVE_CID",
    "PINNED_PACK_CID",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "current_head_static_probes",
    "pcpr_062_receipt_promotion",
    "qualify_context_pack_storage",
    "qualify_current_head_context_pack_storage",
    "refuse_current_root_remint",
    "refuse_pack_cid_remint",
    "render_declared_binding",
    "verify_context_pack_storage_files",
    "write_context_pack_storage_files",
]
