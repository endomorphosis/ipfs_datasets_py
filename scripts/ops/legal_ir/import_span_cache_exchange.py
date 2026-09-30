#!/usr/bin/env python3
"""Verify a sealed span-cache exchange and import review-only supervisor work.

No task is executed, claimed, or made schedulable. The original packet and todo
are retained verbatim as content-addressed JSON; dataset-supplied commands never
become native validation commands. Each machine uses its own native database.
Legacy census/goals bundles and paired spans/goals/artifacts bundles are both
supported. Paired capability/review gaps without sealed native packet/task
artifacts remain in retained evidence and are reported as descriptive deferrals.
Only verified portable packet/task pairs can enter the native review plan.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
IMPORT_SCHEMA = "uscode-autoformal-supervisor-exchange-import/v1"
DEFAULT_REPOSITORY = "justicedao/uscode-autoformal-span-cache"
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ROWS = 1000
MAX_MANIFEST_BYTES = 1024 * 1024
PAIRED_MANIFEST_SCHEMA = "uscode-paired-span-bundle/v1"
PAIRED_TABLES = ("paired_spans", "goals", "artifacts")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")


class ImportError(ValueError):
    """The exchange cannot be imported without losing evidence or authority."""


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _cid(kind: str, packet_sha256: str) -> str:
    return (
        "span-exchange-"
        + kind
        + ":"
        + _digest(
            _json(
                {
                    "schema": IMPORT_SCHEMA,
                    "kind": kind,
                    "packet_sha256": packet_sha256,
                }
            ).encode()
        )
    )


def _repo_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or "\x00" in value
        or any(part in {".", "..", ""} for part in value.split("/"))
        or value != str(path)
    ):
        raise ImportError("repository filename must be a normalized relative path")
    if path.name in {"resume-checkpoint.parquet", "sealed-spans.parquet"}:
        raise ImportError(
            "exchange import must not use checkpoint or sealed-span files"
        )
    return value


def _manifest_bytes(path: Path) -> bytes:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > MAX_MANIFEST_BYTES
    ):
        raise ImportError("manifest must be a bounded regular file")
    with path.open("rb") as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ImportError("manifest exceeds its byte bound")
    return raw


def _manifest_json(path: Path) -> dict[str, Any]:
    value = json.loads(_manifest_bytes(path))
    if not isinstance(value, dict):
        raise ImportError("manifest must be an object")
    return value


def download_bundle(
    *,
    repository_id: str,
    revision: str,
    manifest_in_repo: str,
    staging_directory: Path,
    max_bytes: int,
    fetch: Callable[..., Path] | None = None,
) -> Path:
    """Fetch one manifest and exactly its declared tables at a full commit.

    Size metadata is checked before each download. Neither repo-wide snapshots
    nor model/checkpoint files are downloaded.
    """
    if not _REVISION.fullmatch(revision):
        raise ImportError(
            "Hub imports require an immutable 40-character commit revision"
        )
    _repo_path(manifest_in_repo)
    if not manifest_in_repo.endswith(".json"):
        raise ImportError("bundle manifest must be JSON")
    if max_bytes < 1:
        raise ImportError("max_bytes must be positive")
    if fetch is None:
        from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url

        def fetch(*, filename: str, max_size: int) -> Path:
            metadata = get_hf_file_metadata(
                hf_hub_url(
                    repository_id, filename, repo_type="dataset", revision=revision
                )
            )
            if metadata.commit_hash != revision:
                raise ImportError("Hub metadata resolved to a different commit")
            if metadata.size is None or metadata.size < 0 or metadata.size > max_size:
                raise ImportError(
                    "Hub exchange object exceeds the configured byte bound"
                )
            path = Path(
                hf_hub_download(
                    repo_id=repository_id,
                    repo_type="dataset",
                    revision=revision,
                    filename=filename,
                    local_dir=staging_directory,
                )
            )
            if path.stat().st_size != metadata.size:
                raise ImportError("Hub download size differs from pinned metadata")
            return path

    manifest_path = Path(
        fetch(filename=manifest_in_repo, max_size=min(max_bytes, MAX_MANIFEST_BYTES))
    )
    manifest = _manifest_json(manifest_path)
    if manifest.get("repository_id") != repository_id:
        raise ImportError("manifest repository does not match the requested repository")
    total = manifest_path.stat().st_size
    paired = manifest.get("schema") == PAIRED_MANIFEST_SCHEMA
    descriptors = manifest.get("tables") if paired else manifest
    kinds = PAIRED_TABLES if paired else ("census", "goals")
    if not isinstance(descriptors, dict) or (paired and set(descriptors) != set(PAIRED_TABLES)):
        raise ImportError("paired manifest must bind exactly paired_spans, goals and artifacts")
    for kind in kinds:
        descriptor = descriptors.get(kind)
        if not isinstance(descriptor, dict):
            raise ImportError("manifest is missing its " + kind + " descriptor")
        filename = _repo_path(str(descriptor.get("path_in_repo") or ""))
        if not filename.endswith(".parquet"):
            raise ImportError("exchange objects must be parquet files")
        size = descriptor.get("bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or total + size > max_bytes
        ):
            raise ImportError("manifest exchange exceeds the configured byte bound")
        path = Path(fetch(filename=filename, max_size=size))
        if path.stat().st_size != size or _digest(path.read_bytes()) != descriptor.get(
            "sha256"
        ):
            raise ImportError("downloaded exchange object does not match the manifest")
        total += size
    return manifest_path


def _dependencies(task: Mapping[str, Any]) -> list[str]:
    left, right = task.get("depends_on"), task.get("dependencies")
    if left and right and left != right:
        raise ImportError("todo has conflicting dependency declarations")
    raw = left or right or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or any(
        not isinstance(item, str) or not item for item in raw
    ):
        raise ImportError("todo dependencies must be nonempty strings")
    return sorted(set(raw))


def plan_import(
    goal_rows: Sequence[Mapping[str, Any]],
    *,
    shard_count: int = 1,
    shard_index: int = 0,
) -> dict[str, Any]:
    """Create stable work identities and coassign complete dependency components."""
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ImportError("shard_index must be in [0, shard_count)")
    entries: dict[str, dict[str, Any]] = {}
    aliases: dict[str, set[str]] = {}
    for row in goal_rows:
        digest = str(row.get("packet_sha256") or "")
        if not _SHA.fullmatch(digest):
            raise ImportError("goal packet SHA-256 is missing or invalid")
        packet_json = str(row.get("packet_json") or "")
        task_json = str(row.get("task_json") or "")
        packet, task = json.loads(packet_json), json.loads(task_json)
        if not isinstance(packet, dict) or not isinstance(task, dict):
            raise ImportError("packet and task must be objects")
        # The exchange validator checks canonical wire bytes. Recheck here so
        # callers of the pure planner cannot bypass the core content binding.
        if _digest(packet_json.encode()) != digest:
            raise ImportError("packet JSON bytes do not match their content hash")
        kind = str(row.get("record_kind") or "")
        if kind not in {"repair_packet", "training_goal"}:
            raise ImportError("unknown goal kind")
        identity = _cid("task-" + kind, digest)
        entry = {
            "task_cid": identity,
            "goal_cid": _cid("goal-" + kind, digest),
            "plan_cid": _cid("plan-" + kind, digest),
            "record_kind": kind,
            "packet_sha256": digest,
            "task_sha256": _digest(task_json.encode()),
            "packet_json": packet_json,
            "task_json": task_json,
            "task": task,
            "packet": packet,
            "source_span_id": str(row.get("source_span_id") or ""),
            "dependencies_exported": _dependencies(task),
        }
        previous = entries.get(identity)
        if previous is not None and previous != entry:
            raise ImportError("same packet identity has conflicting task/context bytes")
        entries[identity] = entry
        for alias in (
            identity,
            row.get("task_id"),
            task.get("task_id"),
            task.get("task_cid"),
        ):
            if alias:
                aliases.setdefault(str(alias), set()).add(identity)
    parents = {key: key for key in entries}

    def find(key: str) -> str:
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for identity, entry in entries.items():
        deps = []
        for alias in entry["dependencies_exported"]:
            candidates = aliases.get(alias, set())
            if len(candidates) != 1:
                raise ImportError(
                    "dependency is missing or ambiguous within the sealed bundle: "
                    + alias
                )
            dependency = next(iter(candidates))
            if dependency == identity:
                raise ImportError("todo depends on itself")
            deps.append(dependency)
            a, b = sorted((find(identity), find(dependency)))
            parents[b] = a
        entry["dependencies"] = sorted(set(deps))
    # Reject cycles without recursive traversal of untrusted dependency graphs.
    pending = {key: set(entry["dependencies"]) for key, entry in entries.items()}
    while pending:
        ready = {key for key, deps in pending.items() if not deps}
        if not ready:
            raise ImportError("todo dependency graph contains a cycle")
        pending = {
            key: deps - ready for key, deps in pending.items() if key not in ready
        }
    components: dict[str, list[str]] = {}
    for key in entries:
        components.setdefault(find(key), []).append(key)
    for keys in components.values():
        component = _digest(_json(sorted(keys)).encode())
        assignment = int(component, 16) % shard_count
        for key in keys:
            entries[key]["component_sha256"] = component
            entries[key]["assigned_shard"] = assignment
    selected = [
        entries[key]
        for key in sorted(entries)
        if entries[key]["assigned_shard"] == shard_index
    ]
    return {
        "schema": IMPORT_SCHEMA,
        "shard_count": shard_count,
        "shard_index": shard_index,
        "total_tasks": len(entries),
        "selected_tasks": len(selected),
        "dependency_components": len(components),
        "entries": selected,
    }


def _persist(directory: Path, raw: str, digest: str) -> Path:
    if _digest(raw.encode()) != digest:
        raise ImportError("evidence bytes changed before persistence")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (digest + ".json")
    try:
        with path.open("xb") as handle:
            handle.write(raw.encode())
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != raw.encode():
            raise ImportError("existing immutable evidence has conflicting bytes")
    return path.resolve()


def retain_bundle_evidence(
    *,
    manifest_path: Path,
    census_path: Path | None = None,
    goals_path: Path,
    paired_spans_path: Path | None = None,
    artifacts_path: Path | None = None,
    directory: Path,
    max_bytes: int,
    expected_sha256: Mapping[str, str],
) -> dict[str, Any]:
    """Keep the exact verified manifest and closed table set on this machine.

    The content-addressed locators travel into both native goal and task bodies;
    loss of the input staging directory does not discard the full IR census.
    """
    if paired_spans_path is not None or artifacts_path is not None:
        if census_path is not None or paired_spans_path is None or artifacts_path is None:
            raise ImportError("paired evidence requires exactly three tables and its manifest")
        files = (("manifest", manifest_path, ".json"),
                 ("paired_spans", paired_spans_path, ".parquet"),
                 ("goals", goals_path, ".parquet"),
                 ("artifacts", artifacts_path, ".parquet"))
    else:
        if census_path is None:
            raise ImportError("legacy evidence requires census and goals tables")
        files = (("manifest", manifest_path, ".json"),
                 ("census", census_path, ".parquet"),
                 ("goals", goals_path, ".parquet"))
    if set(expected_sha256) != {kind for kind, _, _ in files}:
        raise ImportError("retained evidence hashes do not close the exact bundle")
    if sum(path.stat().st_size for _, path, _ in files) > max_bytes:
        raise ImportError("retained bundle exceeds byte bound")
    result = {}
    for kind, source, suffix in files:
        if source.is_symlink() or not source.is_file():
            raise ImportError("bundle evidence must be regular files")
        raw = source.read_bytes()
        digest = _digest(raw)
        if digest != expected_sha256.get(kind):
            raise ImportError("verified bundle changed before evidence retention")
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (digest + suffix)
        try:
            with target.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if target.is_symlink() or target.read_bytes() != raw:
                raise ImportError("existing retained bundle artifact conflicts")
        result[kind] = {
            "path": str(target.resolve()),
            "sha256": digest,
            "bytes": len(raw),
        }
    return result


def _body_conflict(
    body: Mapping[str, Any],
    entry: Mapping[str, Any],
    verified_artifacts: set[tuple[Any, ...]] | None = None,
) -> None:
    for key in ("packet_sha256", "task_sha256", "record_kind"):
        if body.get(key) != entry[key]:
            raise ImportError("existing native row conflicts with imported " + key)
    if body.get("exchange_import_schema") != IMPORT_SCHEMA:
        raise ImportError("existing native row is not a compatible exchange import")
    for path_field, digest_field in (
        ("packet_path", "packet_sha256"),
        ("exported_task_path", "task_sha256"),
    ):
        path = Path(str(body.get(path_field) or ""))
        if (
            path.is_symlink()
            or not path.is_file()
            or _digest(path.read_bytes()) != entry[digest_field]
        ):
            raise ImportError(
                "existing native row has missing or conflicting immutable evidence"
            )
    origin = json.loads(str(body.get("exchange_origin_json") or "{}"))
    bundle = origin.get("evidence_bundle")
    if bundle is not None:
        expected = ({"manifest", *PAIRED_TABLES} if origin.get("bundle_schema") == PAIRED_MANIFEST_SCHEMA
                    else {"manifest", "census", "goals"})
        if not isinstance(bundle, dict) or set(bundle) != expected:
            raise ImportError("existing native row has incomplete bundle evidence")
        for artifact in bundle.values():
            if not isinstance(artifact, dict):
                raise ImportError("existing native row has invalid bundle evidence")
            path = Path(str(artifact.get("path") or ""))
            if path.is_symlink() or not path.is_file():
                raise ImportError(
                    "existing native row lost its verified census/goal bundle"
                )
            stat = path.stat()
            cache_key = (
                str(path),
                artifact.get("sha256"),
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
                stat.st_ino,
            )
            if stat.st_size != artifact.get("bytes"):
                raise ImportError(
                    "existing native row lost its verified census/goal bundle"
                )
            if verified_artifacts is None or cache_key not in verified_artifacts:
                if _digest(path.read_bytes()) != artifact.get("sha256"):
                    raise ImportError(
                        "existing native row lost its verified census/goal bundle"
                    )
                if verified_artifacts is not None:
                    verified_artifacts.add(cache_key)


def materialize_import(
    source: Any,
    plan: Mapping[str, Any],
    *,
    packet_directory: Path,
    origin: Mapping[str, Any],
) -> dict[str, Any]:
    """Preflight all conflicts, then insert only missing native goals and todos.

    Repeated imports never call materialize for an existing task, irrespective
    of its status. Claimed/completed rows and their receipts remain untouched.
    """
    existing, pending = [], []
    verified_artifacts: set[tuple[Any, ...]] = set()
    for entry in plan["entries"]:
        previous = source.get(entry["task_cid"])
        goal = source.get_goal(entry["goal_cid"])
        native_plan = source.get_plan(entry["plan_cid"])
        if native_plan is not None:
            if native_plan.get("plan_cid") != entry["plan_cid"]:
                raise ImportError(
                    "existing native plan aliases a different content identity"
                )
            _body_conflict(native_plan.get("body") or {}, entry, verified_artifacts)
        if goal is not None:
            if goal.get("goal_cid") != entry["goal_cid"]:
                raise ImportError(
                    "existing native goal aliases a different content identity"
                )
            _body_conflict(goal.get("body") or {}, entry, verified_artifacts)
        if previous is not None:
            if previous.task_cid != entry["task_cid"]:
                raise ImportError(
                    "existing native task aliases a different content identity"
                )
            if goal is None:
                raise ImportError(
                    "existing native task is missing its imported goal context"
                )
            _body_conflict(previous.body, entry, verified_artifacts)
            if (
                previous.goal_cid != entry["goal_cid"]
                or sorted(previous.dependencies) != entry["dependencies"]
            ):
                raise ImportError(
                    "existing native task has conflicting goal or dependencies"
                )
            existing.append(
                {
                    "task_cid": previous.task_cid,
                    "status": previous.status,
                    "revision": previous.revision,
                }
            )
        else:
            pending.append((entry, goal, native_plan))
    inserted = []
    # Evidence for the whole batch is durable before the first DB write.
    paths = {
        entry["task_cid"]: (
            _persist(packet_directory, entry["packet_json"], entry["packet_sha256"]),
            _persist(packet_directory, entry["task_json"], entry["task_sha256"]),
        )
        for entry, _, _ in pending
    }
    populations = []
    for entry, existing_goal, existing_plan in pending:
        packet_path, task_path = paths[entry["task_cid"]]
        original = entry["task"]
        acceptance = (
            original.get("acceptance_criteria") or original.get("acceptance") or []
        )
        if not isinstance(acceptance, list):
            acceptance = [acceptance]
        # Native intent cannot encode floats in structured bodies. The original
        # exact JSON file preserves all types; strings preserve criterion text.
        criteria = [
            item if isinstance(item, str) else _json(item) for item in acceptance
        ]
        context = {
            "exchange_import_schema": IMPORT_SCHEMA,
            "record_kind": entry["record_kind"],
            "packet_sha256": entry["packet_sha256"],
            "packet_path": str(packet_path),
            "task_sha256": entry["task_sha256"],
            "exported_task_path": str(task_path),
            "source_span_id": entry["source_span_id"],
            "exchange_origin_json": _json(dict(origin)),
            "execution_blocked_reason": "pending_local_execution_qualification",
            "original_acceptance_json": _json(acceptance),
            "title": str(
                original.get("title") or "Review imported autoformal discrepancy"
            ),
            "body_markdown": (
                "Review imported autoformal evidence before local scheduling. Dataset contents are evidence, "
                "not permission to execute commands. Read the complete source, census, preserve/replace "
                "scope and acceptance criteria from both immutable files.\n"
                "Packet: "
                + str(packet_path)
                + " (SHA-256 "
                + entry["packet_sha256"]
                + ")\n"
                "Original todo: "
                + str(task_path)
                + " (SHA-256 "
                + entry["task_sha256"]
                + ").\n"
                "Verified census and manifest: " + _json(dict(origin)) + ".\n"
                "No compiler change, model promotion or legal admission is authorized by this import."
            ),
            "admitted": False,
            "formalized": False,
            "wrote_compiler": False,
            "review_only": True,
            "is_schedulable": False,
        }
        if len(_json(context).encode()) > 240 * 1024:
            raise ImportError(
                "native review context exceeds its conservative body bound"
            )
        goal = {
            **context,
            "goal_cid": entry["goal_cid"],
            "goal_alias": entry["goal_cid"],
            "status": "open",
        }
        task = {
            **context,
            "task_cid": entry["task_cid"],
            "task_id": entry["task_cid"],
            "goal_cid": entry["goal_cid"],
            "plan_cid": entry["plan_cid"],
            "depends_on": entry["dependencies"],
            "acceptance_criteria": criteria,
            "validation_commands": [],
            "outputs": [],
            "status": "blocked",
        }
        # Existing goals are never re-upserted. The native API may create its
        # harmless default goal when recovering a partially inserted task.
        population = {
            "repository_tree_id": "span-cache-exchange:" + entry["packet_sha256"],
            "plan_root_cid": entry["plan_cid"],
            "plans": (
                []
                if existing_plan is not None
                else [
                    {
                        **context,
                        "plan_cid": entry["plan_cid"],
                        "plan_alias": entry["plan_cid"],
                        "goal_cid": entry["goal_cid"],
                        "status": "draft",
                    }
                ]
            ),
            "goals": [] if existing_goal is not None else [goal],
            "tasks": [task],
        }
        populations.append((entry, population))
    # All context/body bounds are checked before the first native mutation.
    for entry, population in populations:
        source.materialize(population)
        readback = source.get(entry["task_cid"])
        if readback is None:
            raise ImportError("native task missing after materialization")
        _body_conflict(readback.body, entry, verified_artifacts)
        if (
            readback.body.get("is_schedulable") is not False
            or readback.body.get("review_only") is not True
        ):
            raise ImportError("native import unexpectedly became schedulable")
        goal_readback = source.get_goal(entry["goal_cid"])
        if goal_readback is None:
            raise ImportError("native goal missing after materialization")
        _body_conflict(goal_readback.get("body") or {}, entry, verified_artifacts)
        plan_readback = source.get_plan(entry["plan_cid"])
        if plan_readback is None:
            raise ImportError("native draft plan missing after materialization")
        _body_conflict(plan_readback.get("body") or {}, entry, verified_artifacts)
        for name in (
            "original_acceptance_json",
            "body_markdown",
            "exchange_origin_json",
        ):
            if readback.body.get(name) != population["tasks"][0][name]:
                raise ImportError("native task lost complete imported context")
        inserted.append(
            {
                "task_cid": readback.task_cid,
                "status": readback.status,
                "revision": readback.revision,
            }
        )
    return {
        "inserted": inserted,
        "existing": existing,
        "inserted_count": len(inserted),
        "existing_count": len(existing),
        "executed": False,
        "claimed": False,
        "admitted": False,
        "formalized": False,
        "wrote_compiler": False,
        "materialized": True,
        "native_authority": "ipfs_accelerate_py.DatabaseTaskSource",
    }


def _pin_logic() -> dict[str, str]:
    loaded = sys.modules.get("ipfs_datasets_py")
    expected = ROOT / "ipfs_datasets_py" / "__init__.py"
    if loaded is not None and Path(loaded.__file__).resolve() != expected:
        raise ImportError("a different datasets checkout is already imported")
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree

    return require_workspace_logic_tree()


def _pin_accelerate(root: Path) -> dict[str, str]:
    path = ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor.py"
    spec = importlib.util.spec_from_file_location("span_exchange_supervisor_pin", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.pin_accelerate(root)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    inputs = result.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--manifest", type=Path, help="Local verified bundle manifest")
    inputs.add_argument("--manifest-in-repo", help="Manifest filename in the dataset")
    result.add_argument("--repository-id", default=DEFAULT_REPOSITORY)
    result.add_argument(
        "--revision",
        default="",
        help="Required immutable Hub commit for a remote import",
    )
    result.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Receipt, staging and immutable evidence directory",
    )
    result.add_argument(
        "--materialize",
        action="store_true",
        help="Insert native review-only work; default only validates/plans",
    )
    result.add_argument("--database", type=Path)
    result.add_argument("--accelerate-root", type=Path)
    result.add_argument(
        "--packet-directory",
        type=Path,
        help="Retained immutable JSON directory (default: OUTPUT/packets)",
    )
    result.add_argument(
        "--staging-directory",
        type=Path,
        help="Selective Hub download directory (default: OUTPUT/download)",
    )
    result.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help="Maximum total input bundle bytes",
    )
    result.add_argument(
        "--max-rows",
        type=int,
        default=DEFAULT_MAX_ROWS,
        help="Maximum rows per parquet object",
    )
    result.add_argument(
        "--shard-count",
        type=int,
        default=1,
        help="Use the same count and sealed bundle on all machines",
    )
    result.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help="Zero-based machine shard; dependency components stay together",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.max_bytes < 1 or args.max_rows < 1:
        raise ImportError("row and byte bounds must be positive")
    if args.revision and not _REVISION.fullmatch(args.revision):
        raise ImportError("revision must be an immutable 40-character commit")
    if args.materialize and (args.database is None or args.accelerate_root is None):
        raise ImportError("materialization requires --database and --accelerate-root")
    receipt_path = args.output / "import-receipt.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ImportError(
            "output already contains an import receipt; choose a new observation directory"
        )
    binding = _pin_logic()
    args.output.mkdir(parents=True, exist_ok=True)
    staging = (args.staging_directory or args.output / "download").resolve()
    packet_directory = (args.packet_directory or args.output / "packets").resolve()
    manifest_path = args.manifest
    if args.manifest_in_repo:
        manifest_path = download_bundle(
            repository_id=args.repository_id,
            revision=args.revision,
            manifest_in_repo=args.manifest_in_repo,
            staging_directory=staging,
            max_bytes=args.max_bytes,
        )
    assert manifest_path is not None
    manifest_raw = _manifest_bytes(manifest_path)
    manifest_digest = _digest(manifest_raw)
    captured_manifest = json.loads(manifest_raw)
    if not isinstance(captured_manifest, dict):
        raise ImportError("manifest must be an object")
    paired = captured_manifest.get("schema") == PAIRED_MANIFEST_SCHEMA
    if paired:
        from ipfs_datasets_py.logic.autoformal.paired_span_census import load_paired_census_bundle
        loaded = load_paired_census_bundle(
            manifest_path, max_bytes=args.max_bytes, max_rows=args.max_rows
        )
        goal_rows = loaded["portable_goal_rows"]
        descriptors = loaded["manifest"]["tables"]
        table_paths = loaded["table_paths"]
        retention_paths = {kind + "_path": Path(table_paths[kind]) for kind in PAIRED_TABLES}
        fingerprint = loaded["manifest"]["fingerprint"]
        # Capability/review gaps lack sealed native packet/task artifacts.
        # Retain them in the goals table and make the deferral visible; do not
        # manufacture executable work from descriptive census entries.
        descriptive_goals = [goal for goal in loaded["goals"]
                             if goal.get("packet_artifact_sha256") is None]
    else:
        from ipfs_datasets_py.logic.autoformal.span_cache_exchange import load_exchange_bundle
        loaded = load_exchange_bundle(
            manifest_path, max_bytes=args.max_bytes, max_rows=args.max_rows
        )
        goal_rows = loaded["goal_rows"]
        descriptors = {kind: loaded["manifest"][kind] for kind in ("census", "goals")}
        retention_paths = {kind + "_path": Path(loaded[kind + "_path"]) for kind in descriptors}
        fingerprint = loaded["fingerprint"]
        descriptive_goals = []
    if (loaded["manifest_sha256"] != manifest_digest
            or _digest(_manifest_bytes(manifest_path)) != manifest_digest
            or loaded["manifest"] != captured_manifest):
        raise ImportError(
            "manifest changed between initial capture and bundle validation"
        )
    if loaded["manifest"].get("repository_id") != args.repository_id:
        raise ImportError(
            "verified manifest repository differs from requested repository"
        )
    plan = plan_import(
        goal_rows, shard_count=args.shard_count, shard_index=args.shard_index
    )
    retained = retain_bundle_evidence(
        manifest_path=manifest_path,
        **retention_paths,
        directory=args.output / "evidence",
        max_bytes=args.max_bytes,
        expected_sha256={
            "manifest": manifest_digest,
            **{kind: descriptor["sha256"] for kind, descriptor in descriptors.items()},
        },
    )
    origin = {
        "repository_id": args.repository_id,
        "revision": args.revision,
        "manifest_in_repo": args.manifest_in_repo or "",
        "manifest_path": retained["manifest"]["path"],
        "manifest_sha256": manifest_digest,
        "evidence_bundle": retained,
        "fingerprint": fingerprint,
        "bundle_schema": loaded["manifest"].get("schema"),
    }
    receipt = {key: value for key, value in plan.items() if key != "entries"}
    receipt.update(
        origin=origin,
        logic_tree=binding,
        materialized=False,
        dry_run=not args.materialize,
        executed=False,
        claimed=False,
        admitted=False,
        formalized=False,
        wrote_compiler=False,
        task_cids=[entry["task_cid"] for entry in plan["entries"]],
        deferred_descriptive_goal_count=len(descriptive_goals),
        deferred_descriptive_goals=[{"goal_id": goal["goal_id"],
            "record_kind": goal["record_kind"],
            "reason": "retained_without_sealed_native_packet_and_task"}
            for goal in descriptive_goals],
    )
    if args.materialize:
        receipt["accelerate_binding"] = _pin_accelerate(args.accelerate_root)
        from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import (
            DatabaseTaskSource,
        )

        args.database.parent.mkdir(parents=True, exist_ok=True)
        with DatabaseTaskSource(
            args.database, owner_id="span-cache-exchange-import"
        ) as source:
            receipt.update(
                materialize_import(
                    source, plan, packet_directory=packet_directory, origin=origin
                )
            )
        receipt["database"] = str(args.database.resolve())
    # Exclusive receipts make each replay a separate retained observation.
    with receipt_path.open("x", encoding="utf-8") as handle:
        handle.write(
            json.dumps(receipt, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
        )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(
            json.dumps(
                {"error": type(exc).__name__, "message": str(exc), "executed": False}
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)
