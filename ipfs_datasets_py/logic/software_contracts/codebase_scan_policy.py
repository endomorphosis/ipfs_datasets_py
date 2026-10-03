"""Frozen single-root scan policy over the existing structural source owner.

This derived receipt never owns a source head and never admits a training sample
or proof. It makes scope, exclusions, unsupported boundaries and independent
candidate selections explicit without changing the complete native inventory.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time

from .codebase_ir import CodebaseScanLimits, RepositoryCodebaseIndex
from .content import canonical_dag_json_bytes, cid_for_structured
from .semantic_index import snapshot as snapshots
from .codebase_git_operation import GitOperationError, GitScanOperation, current_git_operation

PROFILE = "codebase-single-root-python-structural@1"
POLICY_SCHEMA = "codebase-scan-policy@1"
RECEIPT_SCHEMA = "codebase-scan-policy-receipt@1"
MAX_ENTRIES = 256
MAX_FILE_BYTES = 64 * 1024


class CodebaseScanPolicyError(ValueError):
    """A scope declaration or its complete structural evidence differs."""


def _require(condition, message):
    if not condition:
        raise CodebaseScanPolicyError(message)


def _path(value):
    _require(type(value) is str and value and len(value.encode("utf-8")) <= 1024
             and PurePosixPath(value).as_posix() == value
             and not PurePosixPath(value).is_absolute() and "\\" not in value
             and all(part not in {"", ".", ".."} for part in value.split("/"))
             and not any(ord(c) < 32 or ord(c) == 127 for c in value),
             "bounded canonical repository-relative path required")
    return value


def _paths(values, label):
    _require(type(values) in (tuple, list) and len(values) <= MAX_ENTRIES,
             label + " must be an explicit bounded path sequence")
    result = tuple(sorted(_path(value) for value in values))
    _require(len(set(result)) == len(result), label + " contains duplicate paths")
    return result


def _capabilities():
    return {
        "python_pytest": {
            "exact_source_capture": True, "structural_ast": True,
            "semantic_index": "conservative_static_observations",
            "runtime_semantics": False, "target_execution": False,
        },
        "other_utf8_files": {
            "exact_source_capture": True, "structural_ast": False,
            "semantic_index": "artifact_metadata_only",
            "runtime_semantics": False, "target_execution": False,
        },
        "submodules_and_nested_repositories": {
            "boundary_inventory": True, "content_capture": False,
            "recursive_analysis": False, "disposition": "opaque_nonregular_boundary",
        },
        "opaque_entries": {
            "boundary_inventory": True, "content_capture": False,
            "structural_ast": False, "selection_eligible": False,
        },
        "training": "selection_references_only_no_label_or_sample_admission",
        "proof": "selection_references_only_no_obligation_or_evidence_admission",
    }


@dataclass(frozen=True, slots=True)
class CodebaseScanPolicy:
    """The bounded committed-Git profile; dirty captured overlays are included."""

    max_entries: int = MAX_ENTRIES
    max_file_bytes: int = MAX_FILE_BYTES
    exclusions: tuple[str, ...] = ()

    def __post_init__(self):
        for value, maximum in ((self.max_entries, MAX_ENTRIES),
                               (self.max_file_bytes, MAX_FILE_BYTES)):
            _require(type(value) is int and 0 < value <= maximum,
                     "scan limit is outside the frozen bounded profile")
        object.__setattr__(self, "exclusions", _paths(self.exclusions, "exclusions"))

    def to_dict(self):
        effective = tuple(raw.decode("utf-8") for raw in
                          snapshots._exclusion_raw(self.exclusions))
        return {
            "schema": POLICY_SCHEMA, "profile": PROFILE,
            "max_entries": self.max_entries, "max_file_bytes": self.max_file_bytes,
            "custom_exclusions": list(self.exclusions),
            "effective_exclusions": list(effective),
            "exclusion_matching": "raw_path_component_or_repository_relative_subtree",
            "admitted_modes": ["git-clean", "git-working"],
            "source_forest": "one_committed_git_root_with_opaque_nested_boundaries",
            "dirty_overlay": "exact_head_index_disposition_and_captured_source_identity",
            "inventory": "all_nonexcluded_entries_no_training_or_proof_filter",
            "untracked_population": "git_standard_untracked_with_captured_repository_ignore_files",
            "external_ignore_policy": "reject_active_patterns_and_fence_configuration_and_exact_bytes",
            "capabilities": _capabilities(),
        }

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict, "policy must be a closed dictionary")
        try:
            result = cls(value["max_entries"], value["max_file_bytes"],
                         tuple(value["custom_exclusions"]))
        except (KeyError, TypeError) as error:
            raise CodebaseScanPolicyError("policy fields are incomplete") from error
        _require(canonical_dag_json_bytes(result.to_dict()) == canonical_dag_json_bytes(value),
                 "policy fields or capabilities differ from the frozen profile")
        return result

    @property
    def cid(self):
        return cid_for_structured(self.to_dict())


def _implementation():
    from . import ast_ir, cache, codebase_git_operation, codebase_ir, codebase_path_boundary, content, duckdb_ast_store, duckdb_ingest, python_frontend
    from .semantic_index import models, python_analysis, pytest_analysis, scanner, symbol_graph
    from ipfs_datasets_py.duckdb_control import codebase_catalog
    from ..backends import process
    return {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (sys.modules[__name__], ast_ir, cache, codebase_ir, content,
                           duckdb_ast_store, duckdb_ingest, python_frontend, snapshots,
                           models, python_analysis, pytest_analysis, scanner, symbol_graph,
                           codebase_catalog, codebase_git_operation, codebase_path_boundary, process)}


def _owner(index):
    _require(type(index) is RepositoryCodebaseIndex and index.catalog is not None
             and index.artifacts is not None, "native durable source and artifact owner required")


def _bounded_git(root, arguments, *, allowed=(0,)):
    operation = current_git_operation()
    _require(operation is not None, "Git scope inspection requires scan admission")
    result = operation.run(root, arguments, max_output_bytes=MAX_FILE_BYTES)
    _require(result.returncode in allowed and not result.stderr,
             "Git scope query failed or exceeded its bounded process profile")
    try:
        result.stdout.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise CodebaseScanPolicyError("non-UTF8 Git scope metadata is outside profile") from error
    return result.returncode, result.stdout


def _external_ignore_scope(index, root):
    """Admit no ambient ignore patterns; bind even inactive configuration bytes."""
    returncode, output = _bounded_git(root, ("config", "--path", "--null", "--get", "core.excludesfile"),
                                    allowed=(0, 1))
    _require(len(output) <= 4096,
             "external ignore configuration is unavailable or oversized")
    if returncode == 0:
        _require(output.endswith(b"\0") and output.count(b"\0") == 1,
                 "external ignore configuration is ambiguous")
        configured_path = os.fsdecode(output[:-1])
        _require(bool(configured_path), "empty external ignore configuration is outside profile")
        global_path = Path(configured_path)
        if not global_path.is_absolute():
            global_path = root / global_path
        selector = "core.excludesfile"
    else:
        _require(not output, "absent ignore configuration returned data")
        configured_path = None
        environment = current_git_operation().environment
        xdg = environment.get("XDG_CONFIG_HOME")
        home = environment.get("HOME")
        _require(bool(xdg) or bool(home), "external ignore default requires HOME or XDG_CONFIG_HOME")
        config_root = Path(xdg) if xdg else Path(home) / ".config"
        _require(config_root.is_absolute(), "external ignore default root must be absolute")
        global_path = config_root / "git" / "ignore"
        selector = "XDG_CONFIG_HOME" if xdg else "HOME_default"
    _, info = _bounded_git(root, ("rev-parse", "--git-path", "info/exclude"))
    _require(0 < len(info) <= 4096 and info.endswith(b"\n") and info.count(b"\n") == 1,
             "repository ignore location is ambiguous")
    info_path = Path(os.fsdecode(info[:-1]))
    if not info_path.is_absolute():
        info_path = root / info_path
    rows = []
    from .codebase_path_boundary import PathBoundary, PathBoundaryError
    for kind, path in (("repository_info", info_path), ("global", global_path)):
        current_git_operation().remaining()
        # Preserve the selected leaf: resolving it would silently dereference a
        # symlink before O_NOFOLLOW has a chance to reject it.
        _require(".." not in path.parts, "external ignore path cannot traverse parent components")
        path = Path(os.path.abspath(path))
        try:
            with PathBoundary(path, allow_missing=True) as boundary:
                try:
                    leaf = boundary.stat_leaf()
                except FileNotFoundError:
                    raw, present = b"", False
                    boundary.verify()
                    try:
                        boundary.stat_leaf()
                    except FileNotFoundError:
                        pass
                    else:
                        raise CodebaseScanPolicyError("absent external ignore file appeared during capture")
                else:
                    _require(not stat.S_ISLNK(leaf.st_mode),
                             "external ignore file must be regular without a symlink")
                    _require(stat.S_ISREG(leaf.st_mode), "external ignore file must be regular")
                    descriptor = boundary.open_leaf()
                    with os.fdopen(descriptor, "rb") as stream:
                        before = os.fstat(stream.fileno())
                        _require(stat.S_ISREG(before.st_mode), "external ignore file must be regular")
                        raw = stream.read(MAX_FILE_BYTES + 1)
                        after = os.fstat(stream.fileno())
                    witness = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                    _require(witness(leaf) == witness(before) == witness(after) == witness(boundary.stat_leaf()),
                             "external ignore bytes changed during capture")
                    boundary.verify()
                    present = True
        except PathBoundaryError as exc:
            raise CodebaseScanPolicyError("external ignore ancestor binding is unsafe or changed") from exc
        current_git_operation().remaining()
        _require(len(raw) <= MAX_FILE_BYTES and all(not line or line.startswith(b"#") for line in raw.splitlines()),
                 "active or oversized external ignore patterns are outside the frozen profile")
        rows.append(dict(kind=kind, path=str(path), present=present,
                         source_cid=index.artifacts.put_bytes(raw),
                         sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)))
    return dict(schema="codebase-external-ignore-scope@1", selector=selector,
                configured_path=configured_path, files=rows)


def _validate_external_scope(index, value):
    _require(type(value) is dict and set(value) == {"schema", "selector", "configured_path", "files"}
             and value["schema"] == "codebase-external-ignore-scope@1"
             and value["selector"] in {"core.excludesfile", "XDG_CONFIG_HOME", "HOME_default"}
             and type(value["files"]) is list and len(value["files"]) == 2,
             "external ignore scope fields differ")
    configured = value["configured_path"]
    _require((type(configured) is str and bool(configured)) if value["selector"] == "core.excludesfile"
             else configured is None, "external ignore configuration selector differs")
    for kind, row in zip(("repository_info", "global"), value["files"]):
        _require(type(row) is dict and set(row) == {"kind", "path", "present", "source_cid", "sha256", "bytes"}
                 and row["kind"] == kind and type(row["path"]) is str
                 and Path(row["path"]).is_absolute() and type(row["present"]) is bool
                 and type(row["bytes"]) is int and 0 <= row["bytes"] <= MAX_FILE_BYTES,
                 "external ignore artifact fields differ")
        raw = index.artifacts.get_bytes(row["source_cid"])
        _require(len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"]
                 and (row["present"] or not raw)
                 and all(not line or line.startswith(b"#") for line in raw.splitlines()),
                 "external ignore artifact is not an admitted inactive pattern file")
    return value


def _repository_rule_paths(root, policy):
    """Detect ignored ignore-files too; they cannot silently define admitted scope."""
    paths = set()
    exclusions = snapshots._exclusion_raw(policy.exclusions)
    for mode in (("--cached", "--others"), ("--others", "--ignored")):
        _, raw = _bounded_git(root,
            ("ls-files", "-z", *mode, "--exclude-standard", "--", ".gitignore", "**/.gitignore"))
        _require(len(raw) <= MAX_FILE_BYTES, "repository ignore inventory exceeds its byte bound")
        for item in raw.split(b"\0"):
            if not item:
                continue
            parent = item.rpartition(b"/")[0]
            if parent and snapshots._ignored_raw(parent, exclusions):
                continue  # An excluded subtree cannot set rules for admitted siblings.
            _require(snapshots._safe_raw_path(item) is not None,
                     "repository ignore rule path is unsupported")
            paths.add(item.decode("utf-8"))
    _require(len(paths) <= policy.max_entries, "repository ignore inventory exceeds entry bound")
    return sorted(paths)


def _derive(index, *, publication, policy, external_ignores, repository_rules, training_paths, proof_paths):
    """Reconstruct every row from native immutable owners; no live-source claim."""
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebasePublicationReceipt
    from .duckdb_ast_store import classify_parse_status
    _owner(index)
    _validate_external_scope(index, external_ignores)
    _require(type(publication) is CodebasePublicationReceipt and type(policy) is CodebaseScanPolicy,
             "canonical source publication and scan policy required")
    _require(index.catalog.resolve_operation(publication.operation_id, publication.request_cid)
             == publication, "source publication does not replay from its native owner")
    head = publication.head
    manifest = index.load(head.manifest_cid)
    captured = manifest.snapshot
    _require(captured.repository_id == head.repository_id
             and captured.snapshot_cid == head.snapshot_cid
             and manifest.ast_revision_id == head.ast_revision_id,
             "source head and complete native manifest differ")
    declared = policy.to_dict()
    _require(captured.mode in declared["admitted_modes"]
             and captured.max_entries == policy.max_entries
             and captured.max_file_bytes == policy.max_file_bytes
             and list(captured.exclusions) == sorted(declared["effective_exclusions"]),
             "captured scope differs from the frozen scan policy")
    rule_paths = sorted(entry.path for entry in captured.entries
                        if PurePosixPath(entry.path).name == ".gitignore")
    _require(type(repository_rules) is list and repository_rules == rule_paths,
             "repository ignore rules must be included in the complete captured inventory")
    _require(all(not entry.is_opaque for entry in captured.entries
                 if entry.path in rule_paths),
             "repository ignore rules require exact captured bytes")
    units = {unit.source_key: unit for unit in manifest.units}
    rows, available = [], {}
    for entry in captured.entries:
        unit = units[entry.source_key]
        ast = index.load_ast_artifact(manifest, entry.path)
        if entry.is_opaque:
            _require(unit.ast_cid is None and ast is None and unit.parse_status == "opaque",
                     "opaque boundary cannot acquire captured source or an AST")
            disposition = "opaque_unanalyzed"
        else:
            raw = index.artifacts.get_bytes(entry.source_cid)
            _require(len(raw) == entry.size_bytes and len(raw) <= policy.max_file_bytes,
                     "captured source size differs")
            if entry.kind == "python":
                _require(ast is not None and unit.ast_cid is not None,
                         "Python source lacks its structural extraction record")
                _require(classify_parse_status(ast) == unit.parse_status,
                         "native AST parse status differs from the inventory")
                disposition = "python_ast_" + unit.parse_status
            else:
                _require(ast is None and unit.ast_cid is None,
                         "unsupported language acquired an advertised Python AST")
                disposition = "captured_unindexed"
        row = dict(path=entry.path, source_key=entry.source_key, entry_cid=entry.entry_cid,
                   source_cid=entry.source_cid, ast_cid=unit.ast_cid,
                   capture_disposition=entry.disposition, analysis_disposition=disposition,
                   opaque_reason=entry.opaque_reason,
                   captured_for_analysis=not entry.is_opaque,
                   candidate_selectable=disposition == "python_ast_ok")
        rows.append(row)
        available[entry.path] = row

    def selection(paths, label):
        result = []
        for path in _paths(paths, label):
            _require(path in available and available[path]["candidate_selectable"],
                     label + " requires captured successfully parsed Python; unsupported regions remain inventory")
            row = available[path]
            result.append({key: row[key] for key in
                           ("path", "source_key", "entry_cid", "source_cid", "ast_cid")})
        return result

    training = selection(training_paths, "training selection")
    proof = selection(proof_paths, "proof selection")
    forest = {
        "root_count": 1, "repository_view_id": head.repository_id,
        "commit": captured.git_commit, "tree": captured.git_tree,
        "snapshot_cid": head.snapshot_cid, "mode": captured.mode,
        "nested_content_captured": False,
        "opaque_boundaries": [row["source_key"] for row in rows if not row["captured_for_analysis"]],
        "excluded_scope": declared["effective_exclusions"],
        "exclusion_claim": "excluded_content_is_outside_the_admitted_population",
    }
    return {
        "schema": RECEIPT_SCHEMA, "profile": PROFILE,
        "policy": declared, "policy_cid": policy.cid, "producer": _implementation(),
        "external_ignores": external_ignores,
        "repository_ignore_rules": repository_rules,
        "head": head.to_dict(), "publication": publication.to_dict(),
        "source_forest": forest, "inventory": rows,
        "coverage": {**manifest.coverage, "training_selected": len(training),
                     "proof_selected": len(proof)},
        "training_selection": training, "proof_selection": proof,
        "inventory_complete_for_declared_scope": True,
        "source_observed_live": False, "source_runtime_semantics_verified": False,
        "training_executed": False, "training_admitted": False,
        "proof_authority": False, "execution_authority": False,
    }


def prepare_policy_current(index, repository, *, repository_id, operation_id,
                           expected_head, policy=None, training_paths=(), proof_paths=(),
                           scheduler=None, parent_lease=None, cancel_event=None,
                           timeout_seconds=120.0, memory_mb=512):
    """Prepare through the native owner, seal scope, then independently reobserve.

    Policy-sealing failure never makes a partial native head: any earlier head
    publication remains complete structural source without policy authority.
    The returned live observation is point-in-time, not a lock on later edits.
    """
    _owner(index)
    policy = CodebaseScanPolicy() if policy is None else policy
    _require(type(policy) is CodebaseScanPolicy, "canonical scan policy required")
    training_paths = _paths(training_paths, "training selection")
    proof_paths = _paths(proof_paths, "proof selection")
    from .codebase_resources import acquire_codebase_resources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        LeaseCancelledError, LeaseTimeoutError,
    )
    bounds = CodebaseScanLimits(policy.max_entries, policy.max_file_bytes)
    bounds.validate_reservation(memory_mb)
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
             and timeout_seconds > 0, "scan timeout must be finite and positive")
    root = Path(repository).resolve()
    deadline = time.monotonic() + timeout_seconds
    try:
        with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, timeout_seconds=min(30.0, timeout_seconds),
                memory_mb=memory_mb) as lease:
            cancelled = lease.combined_cancellation_signal(cancel_event)
            def remaining():
                if cancelled.is_set():
                    raise LeaseCancelledError("codebase policy scan cancelled")
                seconds = deadline - time.monotonic()
                if seconds <= 0:
                    raise LeaseTimeoutError("codebase policy scan deadline exceeded")
                return seconds
            remaining()
            with GitScanOperation(root, checkpoint=remaining, cancellation=cancelled,
                                  max_file_bytes=policy.max_file_bytes, memory_mb=memory_mb):
                def resources():
                    seconds = remaining()
                    return dict(parent_lease=lease, cancel_event=cancelled,
                                admission_timeout_seconds=min(30.0, seconds),
                                timeout_seconds=seconds, memory_mb=memory_mb)
                return _prepare_policy_admitted(index, root, repository_id=repository_id,
                    operation_id=operation_id, expected_head=expected_head, policy=policy,
                    training_paths=training_paths, proof_paths=proof_paths,
                    resources=resources, checkpoint=remaining)
    except GitOperationError as error:
        raise CodebaseScanPolicyError(str(error)) from error


def _prepare_policy_admitted(index, root, *, repository_id, operation_id, expected_head,
                             policy, training_paths, proof_paths, resources, checkpoint):
    checkpoint()
    _require(snapshots._git_root(root) == root, "profile requires the exact committed Git root")
    commit, _ = snapshots._captured_head(root)
    _require(commit is not None, "profile requires a committed Git root")
    external_ignores = _external_ignore_scope(index, root)
    repository_rules = _repository_rule_paths(root, policy)
    checkpoint()
    publication = index.prepare_current(root, repository_id=repository_id,
        operation_id=operation_id, expected_head=expected_head,
        limits=CodebaseScanLimits(policy.max_entries, policy.max_file_bytes),
        exclusions=policy.exclusions, **resources())
    index.observe_current(root, expected_head=publication.head, **resources())
    _require(_external_ignore_scope(index, root) == external_ignores,
             "external ignore scope changed during source preparation")
    _require(_repository_rule_paths(root, policy) == repository_rules,
             "repository ignore scope changed during source preparation")
    checkpoint()
    receipt = _derive(index, publication=publication, policy=policy,
                      external_ignores=external_ignores,
                      repository_rules=repository_rules,
                      training_paths=training_paths, proof_paths=proof_paths)
    checkpoint()
    receipt_cid = index.artifacts.put(receipt)
    checkpoint()
    index.observe_current(root, expected_head=publication.head, **resources())
    _require(_external_ignore_scope(index, root) == external_ignores,
             "external ignore scope changed during policy publication")
    _require(_repository_rule_paths(root, policy) == repository_rules,
             "repository ignore scope changed during policy publication")
    index.observe_current(root, expected_head=publication.head, **resources())
    checkpoint()
    return {"receipt_cid": receipt_cid, "head": publication.head.to_dict(),
            "source_observed_live": True, "proof_authority": False,
            "training_admitted": False}


def load_policy_receipt(index, receipt_cid):
    """Public historical replay from native CAS; never scan, fit or execute source."""
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebasePublicationReceipt
    _owner(index)
    value = index.artifacts.get(receipt_cid, expected_schema=RECEIPT_SCHEMA)
    _require(type(value) is dict, "closed policy receipt required")
    try:
        expected = _derive(index, publication=CodebasePublicationReceipt.from_dict(value["publication"]),
            policy=CodebaseScanPolicy.from_dict(value["policy"]),
            external_ignores=value["external_ignores"],
            repository_rules=value["repository_ignore_rules"],
            training_paths=[row["path"] for row in value["training_selection"]],
            proof_paths=[row["path"] for row in value["proof_selection"]])
    except (KeyError, TypeError) as error:
        raise CodebaseScanPolicyError("policy receipt fields are incomplete") from error
    _require(canonical_dag_json_bytes(expected) == canonical_dag_json_bytes(value),
             "policy receipt does not reconstruct from complete native source owners")
    return expected


__all__ = ["CodebaseScanPolicy", "CodebaseScanPolicyError", "prepare_policy_current",
           "load_policy_receipt", "PROFILE", "POLICY_SCHEMA", "RECEIPT_SCHEMA"]
