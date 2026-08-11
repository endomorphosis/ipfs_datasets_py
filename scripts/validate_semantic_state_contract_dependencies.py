#!/usr/bin/env python3
"""Fail-closed validator for the semantic-state dependency seal.

This is a control-plane drift gate, not a content-identity implementation.  Git
object IDs and a SHA-256 fingerprint over the reviewed source, interface, test,
and timeout contract are used only to prove which external authority was
reviewed.  Semantic payload CIDs remain owned exclusively by
``ipfs_datasets_py.logic.software_contracts.content``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

SEAL_SCHEMA = "ipfs-datasets.software-contracts.semantic-state-dependency-seal@1"
EXPECTED_ROLES = (
    "accelerate_harness",
    "incremental_semantic_index",
    "kit_state_roots",
    "mcp_plus_plus",
)
EXPECTED_REPOSITORIES = {
    "accelerate_harness": "endomorphosis/ipfs_accelerate_py",
    "incremental_semantic_index": "endomorphosis/ipfs_datasets_py",
    "kit_state_roots": "endomorphosis/ipfs_kit_py",
    "mcp_plus_plus": "endomorphosis/Mcp-Plus-Plus",
}
EXPECTED_ORIGINS = {
    role: f"https://github.com/{repository}"
    for role, repository in EXPECTED_REPOSITORIES.items()
}
TOP_LEVEL_FIELDS = frozenset(
    {"schema", "status", "target", "wire_contract", "authorities"}
)
TARGET_FIELDS = frozenset({"language", "python_minor", "test_framework"})
WIRE_FIELDS = frozenset(
    {
        "authority_role",
        "profiles",
        "payload_role",
        "generic_envelope_types_owned_externally",
        "local_envelope_hasher_forbidden",
    }
)
AUTHORITY_FIELDS = frozenset(
    {
        "role",
        "repository",
        "origin",
        "reachability_policy",
        "commit",
        "tree",
        "interface_fingerprint",
        "interface_contract",
        "required_blobs",
        "required_test_commands",
        "test_timeout_seconds",
    }
)
BLOB_FIELDS = frozenset({"path", "oid"})
INTERFACE_FIELDS = frozenset({"contract_name", "schema_versions", "public_api"})
HEX40 = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
PLACEHOLDER = re.compile(r"(?:UNRESOLVED|PLACEHOLDER|\bTODO\b)", re.IGNORECASE)

REACHABILITY_POLICY = "exact_clean_head"
EXPECTED_TEST_TIMEOUT_SECONDS = {
    "accelerate_harness": 900,
    "incremental_semantic_index": 1800,
    "kit_state_roots": 1800,
    "mcp_plus_plus": 900,
}
EXPECTED_REQUIRED_BLOB_PATHS = {
    "accelerate_harness": (
        "docs/architecture/SEMANTIC_COMPRESSION_HARNESS_PLAN.md",
        "docs/architecture/semantic_compression_harness.objectives.md",
        "docs/architecture/semantic_compression_harness.todo.md",
        "ipfs_accelerate_py/agent_supervisor/todo_daemon/production_context_slice.py",
        "ipfs_accelerate_py/agent_supervisor/validation/proposal_validation.py",
        "test/api/test_agent_supervisor_production_context_slice.py",
        "test/api/test_agent_supervisor_proposal_validation.py",
    ),
    "incremental_semantic_index": (
        "docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md",
        "ipfs_datasets_py/logic/software_contracts/content.py",
        "ipfs_datasets_py/logic/software_contracts/semantic_index/__init__.py",
        "ipfs_datasets_py/logic/software_contracts/semantic_index/delta.py",
        "ipfs_datasets_py/logic/software_contracts/semantic_index/index.py",
        "ipfs_datasets_py/logic/software_contracts/semantic_index/invalidation.py",
        "ipfs_datasets_py/logic/software_contracts/semantic_index/models.py",
        "ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py",
        "ipfs_datasets_py/logic/software_contracts/semantic_index/snapshot.py",
        "tests/cli/test_semantic_index_cli.py",
        "tests/unit/logic/software_contracts/semantic_index/test_acceptance.py",
        "tests/unit/logic/software_contracts/semantic_index/test_import_safety.py",
    ),
    "kit_state_roots": (
        "ipfs_kit_py/mcp_server/mcplusplus/coordination_storage.py",
        "ipfs_kit_py/mcp_server/mcplusplus/state_root_adapter.py",
        "ipfs_kit_py/mcp_server/mcplusplus/state_root_contracts.py",
        "tests/test_coordination_storage.py",
        "tests/test_semantic_state_root_acceptance.py",
        "tests/test_semantic_state_root_adapter.py",
        "tests/test_semantic_state_root_cas.py",
        "tests/test_semantic_state_root_contracts.py",
        "tests/test_semantic_state_root_recovery.py",
    ),
    "mcp_plus_plus": (
        "conformance/vectors/dag_event_epoch.json",
        "conformance/vectors/execution_receipt.json",
        "docs/spec/cid-native-artifacts.md",
        "docs/spec/event-dag-ordering.md",
        "docs/spec/mcp++-profiles-draft.md",
        "docs/spec/mcp-idl.md",
        "tests-py/integration/test_cid_envelopes.py",
        "tests-py/integration/test_conformance_vectors.py",
        "tests-py/integration/test_event_dag.py",
        "tests-py/integration/test_mcp_idl.py",
        "tests-py/validators/cid_artifacts.py",
        "tests-py/validators/event_dag.py",
        "tests-py/validators/mcp_idl.py",
    ),
}
EXPECTED_REQUIRED_TEST_COMMANDS = {
    "accelerate_harness": (
        (
            "python3.12",
            "-m",
            "pytest",
            "-q",
            "test/api/test_agent_supervisor_production_context_slice.py",
            "test/api/test_agent_supervisor_proposal_validation.py",
        ),
    ),
    "incremental_semantic_index": (
        (
            "python3.12",
            "-m",
            "pytest",
            "-q",
            "tests/unit/logic/software_contracts/semantic_index",
            "tests/cli/test_semantic_index_cli.py",
        ),
    ),
    "kit_state_roots": (
        (
            "python3.12",
            "-m",
            "pytest",
            "-q",
            "tests/test_coordination_storage.py",
            "tests/test_semantic_state_root_contracts.py",
            "tests/test_semantic_state_root_adapter.py",
            "tests/test_semantic_state_root_cas.py",
            "tests/test_semantic_state_root_recovery.py",
            "tests/test_semantic_state_root_acceptance.py",
        ),
    ),
    "mcp_plus_plus": (
        (
            "python3.12",
            "-m",
            "pytest",
            "-q",
            "tests-py/integration/test_mcp_idl.py",
            "tests-py/integration/test_cid_envelopes.py",
            "tests-py/integration/test_conformance_vectors.py",
            "tests-py/integration/test_event_dag.py",
        ),
    ),
}
EXPECTED_INTERFACE_CONTRACTS = {
    "accelerate_harness": {
        "contract_name": "SemanticCompressionHarnessConsumerPlan@1",
        "schema_versions": [
            ["board_namespace", "semantic-compression-harness-v1"],
            ["wire_boundary", "mcp-plus-plus-profiles-a-b-f"],
        ],
        "public_api": [
            "SemanticCapsuleRef(capsule_cid,semantic_state_root_cid,stable_symbol_id,version_cid,source_cid,confidence,validity_bindings,raw_source_required)",
            "SemanticStateRootManifest(repository_id,base_tree_cid,candidate_tree_cid,datasets_state_cid,datasets_semantic_state_root_cid,capsule_index_cid,delta_cid,invalidation_cid,obligation_set_cid,test_selection_cid,receipt_index_cid,environment_binding_cids,event_head_cid,versions,acceptance_disposition)",
            "TestSelectionRef(selection_cid,previous_semantic_state_root_cid_or_null,current_semantic_state_root_cid)",
        ],
    },
    "incremental_semantic_index": {
        "contract_name": "SemanticCapsuleIndexConsumer@2",
        "schema_versions": [
            ["extractor_name", "UNRESOLVED_FINAL_ISI_EXTRACTOR_NAME"],
            ["extractor_version", "UNRESOLVED_FINAL_ISI_EXTRACTOR_VERSION"],
            ["semantic_index_schema", "UNRESOLVED_FINAL_ISI_SCHEMA"],
        ],
        "public_api": [
            "SemanticIndexForCapsules.incoming_edges(stable_symbol_id:str)->tuple[DependencyEdge,...]",
            "SemanticIndexForCapsules.outgoing_edges(stable_symbol_id:str)->tuple[DependencyEdge,...]",
            "SemanticIndexForCapsules.read_source_blob(source_cid:str)->bytes",
            "SemanticIndexForCapsules.read_source_span(stable_symbol_id:str)->bytes",
            "SemanticIndexForCapsules.source_slice(stable_symbol_id:str)->SourceSliceRef",
            "SemanticIndexForCapsules.state_root_cid:str",
            "SemanticIndexForCapsules.symbol(stable_symbol_id:str)->SymbolRecord",
            "calculate_invalidation(previous_state,current_state,delta)->InvalidationPlan",
            "diff_repository_states(previous_state,current_state)->RepositoryStateDelta",
            "scan_repository(repo_path,previous_state=None)->RepositoryState",
        ],
    },
    "kit_state_roots": {
        "contract_name": "DurableStateRoots@1",
        "schema_versions": [
            ["state_root_transition_schema", "mcp++/coordination/state-root-transition@1"],
            ["transport_cid_profile", "cidv1-dag-json-sha2-256"],
        ],
        "public_api": [
            "DurableStateRoots.compare_and_swap_root(namespace:str,expected_revision:int,expected_root_cid:str|None,new_root_cid:str,operation_id:str)->StateRootCASResult",
            "DurableStateRoots.current_root(namespace:str)->StateRootSnapshot",
            "DurableStateRoots.get_verified(cid:str)->Mapping[str,Any]",
            "DurableStateRoots.put_verified(payload:Mapping[str,Any],expected_cid:str,replicate:bool=True)->ArtifactWriteResult",
            "DurableStateRoots.recover_roots()->StateRootRecoveryReport",
        ],
    },
    "mcp_plus_plus": {
        "contract_name": "McpPlusPlusProfilesABF@dc316465",
        "schema_versions": [
            ["profile_a", "interface-description"],
            ["profile_b", "cid-native-artifacts"],
            ["profile_f", "event-dag-ordering"],
        ],
        "public_api": [
            "ProfileA.InterfaceDescriptor(application_schema_cid)",
            "ProfileB.ExecutionEnvelope(payload_or_payload_cid)",
            "ProfileB.ExecutionReceipt(content_addressed_result)",
            "ProfileF.DAGEvent(parent_event_cids,payload_cid)",
        ],
    },
}


class DuplicateKeyError(ValueError):
    """Raised when JSON contains an object with repeated member names."""


def _closed_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON member {key!r}")
        result[key] = value
    return result


def load_seal(path: Path) -> Mapping[str, Any]:
    """Load one seal while rejecting duplicate JSON object keys."""

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_closed_object)
    if not isinstance(value, Mapping):
        raise ValueError("seal must be a JSON object")
    return value


def authority_fingerprint(authority: Mapping[str, Any]) -> str:
    """Bind one reviewed authority, interface, tests, and blob manifest."""

    projection = {
        "role": authority["role"],
        "repository": authority["repository"],
        "origin": _normal_origin(authority["origin"]),
        "reachability_policy": authority["reachability_policy"],
        "commit": authority["commit"],
        "tree": authority["tree"],
        "interface_contract": authority["interface_contract"],
        "required_blobs": [
            [item["path"], item["oid"]] for item in authority["required_blobs"]
        ],
        "required_test_commands": authority["required_test_commands"],
        "test_timeout_seconds": authority["test_timeout_seconds"],
    }
    encoded = json.dumps(
        projection,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _unknown_fields(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> list[str]:
    unknown = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    errors: list[str] = []
    if unknown:
        errors.append(f"{label}: unknown fields: {', '.join(unknown)}")
    if missing:
        errors.append(f"{label}: missing fields: {', '.join(missing)}")
    return errors


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return bool(PLACEHOLDER.search(value))
    if isinstance(value, Mapping):
        return any(_contains_placeholder(key) or _contains_placeholder(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    return False


def _safe_repo_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\x00" not in value


def _normal_origin(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def validate_document(seal: Mapping[str, Any]) -> list[str]:
    """Validate the closed, portable portion of a dependency seal."""

    errors = _unknown_fields(seal, TOP_LEVEL_FIELDS, "seal")
    if seal.get("schema") != SEAL_SCHEMA:
        errors.append(f"seal: schema must equal {SEAL_SCHEMA!r}")
    if seal.get("status") != "sealed":
        errors.append("seal: status must be 'sealed'")
    if _contains_placeholder(seal):
        errors.append("seal: unresolved placeholder present")

    target = seal.get("target")
    if not isinstance(target, Mapping):
        errors.append("target: must be an object")
    else:
        errors.extend(_unknown_fields(target, TARGET_FIELDS, "target"))
        if target != {
            "language": "python",
            "python_minor": "3.12",
            "test_framework": "pytest",
        }:
            errors.append("target: must be exactly Python 3.12 with pytest")

    wire = seal.get("wire_contract")
    if not isinstance(wire, Mapping):
        errors.append("wire_contract: must be an object")
    else:
        errors.extend(_unknown_fields(wire, WIRE_FIELDS, "wire_contract"))
        expected_wire = {
            "authority_role": "mcp_plus_plus",
            "profiles": ["A", "B", "F"],
            "payload_role": "datasets_application_payload_only",
            "generic_envelope_types_owned_externally": True,
            "local_envelope_hasher_forbidden": True,
        }
        if wire != expected_wire:
            errors.append("wire_contract: must preserve the exact generic Profile A/B/F payload boundary")

    authorities = seal.get("authorities")
    if not isinstance(authorities, list):
        errors.append("authorities: must be a list")
        return errors
    roles = [item.get("role") for item in authorities if isinstance(item, Mapping)]
    if roles != list(EXPECTED_ROLES):
        errors.append("authorities: roles must be unique and sorted as " + ", ".join(EXPECTED_ROLES))

    for index, item in enumerate(authorities):
        label = f"authorities[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{label}: must be an object")
            continue
        errors.extend(_unknown_fields(item, AUTHORITY_FIELDS, label))
        role = item.get("role")
        if role not in EXPECTED_ROLES:
            errors.append(f"{label}: unknown role {role!r}")
            continue
        if item.get("repository") != EXPECTED_REPOSITORIES[role]:
            errors.append(f"{label}: repository does not match role {role!r}")
        if _normal_origin(str(item.get("origin", ""))) != EXPECTED_ORIGINS[role]:
            errors.append(f"{label}: origin does not match {EXPECTED_ORIGINS[role]!r}")
        if item.get("reachability_policy") != REACHABILITY_POLICY:
            errors.append(
                f"{label}: reachability_policy must equal {REACHABILITY_POLICY!r}"
            )
        for field in ("commit", "tree"):
            if not HEX40.fullmatch(str(item.get(field, ""))):
                errors.append(f"{label}: {field} must be a lowercase 40-hex Git object ID")

        interface = item.get("interface_contract")
        if not isinstance(interface, Mapping):
            errors.append(f"{label}: interface_contract must be an object")
        else:
            errors.extend(
                _unknown_fields(interface, INTERFACE_FIELDS, f"{label}.interface_contract")
            )
            if interface != EXPECTED_INTERFACE_CONTRACTS[role]:
                errors.append(
                    f"{label}: interface_contract must equal the reviewed role contract"
                )

        blobs = item.get("required_blobs")
        if not isinstance(blobs, list) or not blobs:
            errors.append(f"{label}: required_blobs must be a non-empty list")
            blobs = []
        blob_paths: list[str] = []
        valid_blobs: list[Mapping[str, str]] = []
        for blob_index, blob in enumerate(blobs):
            blob_label = f"{label}.required_blobs[{blob_index}]"
            if not isinstance(blob, Mapping):
                errors.append(f"{blob_label}: must be an object")
                continue
            errors.extend(_unknown_fields(blob, BLOB_FIELDS, blob_label))
            path = str(blob.get("path", ""))
            oid = str(blob.get("oid", ""))
            if not _safe_repo_path(path):
                errors.append(f"{blob_label}: path must be a safe repository-relative POSIX path")
            if not HEX40.fullmatch(oid):
                errors.append(f"{blob_label}: oid must be a lowercase 40-hex Git blob ID")
            blob_paths.append(path)
            if _safe_repo_path(path) and HEX40.fullmatch(oid):
                valid_blobs.append({"path": path, "oid": oid})
        if blob_paths != sorted(set(blob_paths)):
            errors.append(f"{label}: required_blobs must be sorted by unique path")
        if tuple(blob_paths) != EXPECTED_REQUIRED_BLOB_PATHS[role]:
            errors.append(f"{label}: required_blobs paths do not equal the reviewed role manifest")

        commands = item.get("required_test_commands")
        if not isinstance(commands, list) or not commands:
            errors.append(f"{label}: required_test_commands must be a non-empty list")
        else:
            for command_index, command in enumerate(commands):
                command_label = f"{label}.required_test_commands[{command_index}]"
                if not isinstance(command, list) or not command or not all(
                    isinstance(part, str) and part and "\x00" not in part for part in command
                ):
                    errors.append(f"{command_label}: must be a non-empty argv string list")
                elif command[0] != "python3.12":
                    errors.append(f"{command_label}: executable must be exactly 'python3.12'")
            expected_commands = [list(command) for command in EXPECTED_REQUIRED_TEST_COMMANDS[role]]
            if commands != expected_commands:
                errors.append(
                    f"{label}: required_test_commands do not equal the reviewed bounded commands"
                )

        timeout = item.get("test_timeout_seconds")
        if isinstance(timeout, bool) or timeout != EXPECTED_TEST_TIMEOUT_SECONDS[role]:
            errors.append(
                f"{label}: test_timeout_seconds must equal "
                f"{EXPECTED_TEST_TIMEOUT_SECONDS[role]}"
            )

        fingerprint = str(item.get("interface_fingerprint", ""))
        if not FINGERPRINT.fullmatch(fingerprint):
            errors.append(
                f"{label}: interface_fingerprint must be sha256 plus 64 lowercase hex digits"
            )
        elif len(valid_blobs) == len(blobs) and isinstance(interface, Mapping):
            try:
                expected_fingerprint = authority_fingerprint(item)
            except (KeyError, TypeError, ValueError):
                expected_fingerprint = ""
            if fingerprint != expected_fingerprint:
                errors.append(
                    f"{label}: interface_fingerprint does not bind the complete authority contract"
                )
    return errors


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", os.fspath(path), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def validate_checkout(authority: Mapping[str, Any], checkout: Path) -> list[str]:
    """Verify one canonical clean checkout against the sealed Git objects."""

    role = str(authority.get("role", "unknown"))
    label = f"checkout[{role}]"
    errors: list[str] = []
    if not checkout.is_dir():
        return [f"{label}: repository path does not exist: {checkout}"]
    inside = _git(checkout, "rev-parse", "--is-inside-work-tree")
    if inside.returncode or inside.stdout.strip() != "true":
        return [f"{label}: path is not a Git worktree"]
    top_level = _git(checkout, "rev-parse", "--show-toplevel")
    if top_level.returncode:
        return [f"{label}: cannot resolve the Git worktree root"]
    try:
        canonical_top_level = Path(top_level.stdout.strip()).resolve(strict=True)
        canonical_checkout = checkout.resolve(strict=True)
    except OSError:
        return [f"{label}: cannot resolve the canonical checkout path"]
    if canonical_top_level != canonical_checkout:
        return [f"{label}: path must be the canonical Git worktree root"]

    status = _git(checkout, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode:
        errors.append(f"{label}: cannot inspect cleanliness")
    elif status.stdout:
        errors.append(f"{label}: checkout is dirty")

    head = _git(checkout, "rev-parse", "HEAD")
    expected_commit = str(authority.get("commit", ""))
    if head.returncode or head.stdout.strip() != expected_commit:
        errors.append(f"{label}: HEAD does not equal sealed commit")
    commit = _git(checkout, "cat-file", "-e", f"{expected_commit}^{{commit}}")
    if commit.returncode:
        errors.append(f"{label}: sealed commit is not a commit object in this checkout")
    tree = _git(checkout, "rev-parse", f"{expected_commit}^{{tree}}")
    if tree.returncode or tree.stdout.strip() != str(authority.get("tree", "")):
        errors.append(f"{label}: commit tree does not equal sealed tree")

    origin = _git(checkout, "remote", "get-url", "origin")
    if origin.returncode or _normal_origin(origin.stdout) != _normal_origin(str(authority.get("origin", ""))):
        errors.append(f"{label}: origin does not equal sealed origin")

    for blob in authority.get("required_blobs", []):
        if not isinstance(blob, Mapping):
            continue
        blob_path = str(blob.get("path", ""))
        expected_oid = str(blob.get("oid", ""))
        entry = _git(checkout, "ls-tree", expected_commit, "--", blob_path)
        parts = entry.stdout.strip().split(None, 3)
        actual_oid = parts[2] if not entry.returncode and len(parts) == 4 and parts[1] == "blob" else ""
        if actual_oid != expected_oid:
            errors.append(f"{label}: required blob mismatch or missing: {blob_path}")
    return errors


def _forbidden_local_wire_authority(repo: Path) -> list[str]:
    """Reject generic MCP++ types/imports/hashers in the DSS production package."""

    package = repo / "ipfs_datasets_py/logic/software_contracts/semantic_state"
    if not package.is_dir():
        return []
    forbidden_types = {
        "InterfaceDescriptor",
        "ExecutionEnvelope",
        "ExecutionReceipt",
        "DAGEvent",
    }
    generic_terms = ("interface_descriptor", "execution_envelope", "execution_receipt", "dag_event", "envelope", "receipt")
    violations: list[str] = []
    for path in sorted(package.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=os.fspath(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            violations.append(
                f"wire boundary: cannot AST-audit {path.relative_to(repo)}: {exc}"
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                lowered = name.lower()
                if name in forbidden_types or (
                    any(term in lowered for term in generic_terms)
                    and any(term in lowered for term in ("cid", "hash", "canonical", "encode", "decode"))
                ):
                    violations.append(
                        f"wire boundary: forbidden local generic authority at "
                        f"{path.relative_to(repo)}:{node.lineno}"
                    )
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                targets: list[ast.expr] = []
                if isinstance(node, ast.Assign):
                    targets.extend(node.targets)
                else:
                    targets.append(node.target)
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in forbidden_types:
                        violations.append(
                            f"wire boundary: forbidden local generic type alias at "
                            f"{path.relative_to(repo)}:{node.lineno}"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.lower().replace("-", "_")
                    if "mcplusplus" in module or "mcp_plus_plus" in module:
                        violations.append(
                            f"wire boundary: forbidden MCP++ import at "
                            f"{path.relative_to(repo)}:{node.lineno}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").lower().replace("-", "_")
                imported = {alias.name for alias in node.names}
                if (
                    "mcplusplus" in module
                    or "mcp_plus_plus" in module
                    or imported & forbidden_types
                ):
                    violations.append(
                        f"wire boundary: forbidden MCP++ import at "
                        f"{path.relative_to(repo)}:{node.lineno}"
                    )
    return violations


def _parse_repo_bindings(values: Iterable[str]) -> tuple[dict[str, Path], list[str]]:
    bindings: dict[str, Path] = {}
    errors: list[str] = []
    for value in values:
        role, separator, raw_path = value.partition("=")
        if not separator or role not in EXPECTED_ROLES or not raw_path:
            errors.append(f"--repo must be ROLE=PATH for one of {', '.join(EXPECTED_ROLES)}: {value!r}")
            continue
        if role in bindings:
            errors.append(f"duplicate --repo binding for {role}")
            continue
        bindings[role] = Path(raw_path).expanduser().resolve()
    return bindings, errors


def _run_required_tests(authority: Mapping[str, Any], checkout: Path) -> list[str]:
    errors: list[str] = []
    role = str(authority["role"])
    environment = dict(os.environ)
    environment.update(
        {
            "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
            "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
            "IPFS_DATASETS_AUTO_INSTALL": "0",
            "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
        }
    )
    timeout_seconds = int(authority["test_timeout_seconds"])
    for command in authority["required_test_commands"]:
        try:
            completed = subprocess.run(
                command,
                cwd=checkout,
                env=environment,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            errors.append(
                f"checkout[{role}]: required test timed out after "
                f"{timeout_seconds}s: {' '.join(command)}"
            )
            continue
        except OSError as exc:
            errors.append(
                f"checkout[{role}]: required test could not start: "
                f"{' '.join(command)}: {exc}"
            )
            continue
        if completed.returncode:
            errors.append(f"checkout[{role}]: required test failed ({completed.returncode}): {' '.join(command)}")
    return errors


def validate_seal(
    seal_path: Path,
    *,
    repositories: Mapping[str, Path] | None = None,
    run_tests: bool = False,
) -> list[str]:
    """Return every bounded validation error; an empty list is the only pass."""

    try:
        seal = load_seal(seal_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"seal: cannot load: {exc}"]
    errors = validate_document(seal)
    if seal.get("status") == "sealed" and not run_tests:
        errors.append("seal: sealed validation requires --run-tests")
    repositories = dict(repositories or {})
    missing = sorted(set(EXPECTED_ROLES) - set(repositories))
    unexpected = sorted(set(repositories) - set(EXPECTED_ROLES))
    if missing:
        errors.append("checkout bindings missing: " + ", ".join(missing))
    if unexpected:
        errors.append("checkout bindings unknown: " + ", ".join(unexpected))

    by_role = {
        str(item.get("role")): item
        for item in seal.get("authorities", [])
        if isinstance(item, Mapping) and item.get("role") in EXPECTED_ROLES
    }
    for role in EXPECTED_ROLES:
        if role not in repositories or role not in by_role:
            continue
        errors.extend(validate_checkout(by_role[role], repositories[role]))
    if run_tests and not errors:
        for role in EXPECTED_ROLES:
            if role not in repositories or role not in by_role:
                continue
            errors.extend(_run_required_tests(by_role[role], repositories[role]))
            errors.extend(validate_checkout(by_role[role], repositories[role]))
    if "incremental_semantic_index" in repositories:
        errors.extend(_forbidden_local_wire_authority(repositories["incremental_semantic_index"]))
    if sys.version_info[:2] != (3, 12):
        errors.append(
            f"runtime: validator must run under Python 3.12, got {sys.version_info.major}.{sys.version_info.minor}"
        )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", type=Path, required=True, help="dependency seal JSON")
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="ROLE=PATH",
        help="bind a sealed authority role to the exact clean checkout",
    )
    parser.add_argument("--run-tests", action="store_true", help="run every sealed argv test after source checks")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repositories, errors = _parse_repo_bindings(args.repo)
    errors.extend(validate_seal(args.check.resolve(), repositories=repositories, run_tests=args.run_tests))
    if errors:
        for error in dict.fromkeys(errors):
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"semantic-state dependency seal verified: {args.check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
