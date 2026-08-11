"""Deterministic Wave-2 reachable-gap fixed-point evidence (LFP2-049).

``ObjectiveRefillFixedPoint@2`` is a sealing receipt, not an authority source.
It binds two serial, empty ``DerivedTaskAdmission@2`` epochs to the exact
current planning, semantic, corpus, provider, registry, and matrix identities.
The materializer refuses open work (apart from the LFP2-049/LFP2-050 sealing
cards), identity drift, a dirty/mismatched nested repository, and every
non-zero reachable-matrix safety floor.

The JSON receipt and JSONL ledger are canonical and content addressed.  They
never grant completion, mutation, seed-board-edit, theorem, or kernel
authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.logic.conformance.refill_v2 import (
    EpochDisposition,
    ScanIdentity,
    run_admission_epoch,
)

OBJECTIVE_REFILL_FIXED_POINT_INTERFACE: Final = "ObjectiveRefillFixedPoint@2"
OBJECTIVE_FIXED_POINT_RECEIPT_SCHEMA: Final = "objective-refill-fixed-point-receipt/v2"
FIXED_POINT_LEDGER_ENTRY_SCHEMA: Final = "logic-refill-fixed-point-ledger-entry/v2"
FIXED_POINT_VERSION: Final = "2.0.0"
TASK_ID: Final = "LFP2-049"
GOAL_ID: Final = "LFP2-G090"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v2"
PRODUCER_ID: Final = "objective-refill-fixed-point@2"

DEFAULT_FIXED_POINT_RELATIVE_PATH: Final = (
    "data/agent_supervisor/ipfs_datasets_logic_family_parser_v2/refill/fixed_point_receipt.json"
)
DEFAULT_LEDGER_RELATIVE_PATH: Final = (
    "data/agent_supervisor/ipfs_datasets_logic_family_parser_v2/refill/gap_ledger.jsonl"
)

TODO_RELATIVE_PATH: Final = "docs/architecture/ipfs_datasets_logic_family_parser_v2.todo.md"
OBJECTIVE_RELATIVE_PATH: Final = (
    "docs/architecture/ipfs_datasets_logic_family_parser_v2.objectives.md"
)
SCHEDULER_RELATIVE_PATH: Final = (
    "config/agent_supervisor_ipfs_datasets_logic_family_parser_v2_scheduler.json"
)
NESTED_REPOSITORY_PATH: Final = "ipfs_datasets_py"
MERGE_TARGET_BRANCH: Final = "agent/logic-family-parser-v2-supervisor"
RELEASE_SELF_OUTPUT_PATHS: Final[tuple[str, ...]] = (
    "data/logic/conformance/logic_family_parser_v2_release.json",
    "docs/architecture/logic/LOGIC_FAMILY_PARSER_V2_RELEASE.md",
)

# Wave-1 is the immutable predecessor of this seal.  The two runtime files are
# intentionally ignored by Git, so candidate worktrees cannot be trusted as
# their source.  All six anchors are resolved through the one exact
# merge-target worktree belonging to the same Git common directory.
PREDECESSOR_ANCHOR_SHA256: Final[Mapping[str, str]] = {
    "docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md": (
        "sha256:9d07ef064e80081a67d13f754fff10b84b6176facf687b88ed1164d71a90e9c0"
    ),
    "docs/architecture/ipfs_datasets_logic_family_parser.objectives.md": (
        "sha256:1bc111b24e44508d56f4932da4ce0a76357eaaf01bf5ea22842cf06621b24217"
    ),
    "docs/architecture/ipfs_datasets_logic_family_parser.todo.md": (
        "sha256:8e851a11e3fbd1a0b174e2077abaa398c15fecdf9b9bb8baf9592b3311f5aaa8"
    ),
    "ipfs_datasets_py/data/logic/conformance/logic_family_parser_release.json": (
        "sha256:86412a60bfde9b8a13156ab097b44443a4a8f70a7b286f1c7a707366c93757ce"
    ),
    (
        "data/agent_supervisor/ipfs_datasets_logic_family_parser/refill/fixed_point_receipt.json"
    ): "sha256:df389198f2f1a5982ede95ce775c468ad7a85abf8447f4d0cc51f8b6f5eddc2c",
    (
        "data/agent_supervisor/ipfs_datasets_logic_family_parser/refill/gap_ledger.jsonl"
    ): "sha256:6258dc0a9070fd531b77f96d1044f840454d02517022aa1c9e0f3e7b8debbcac",
}

_NESTED_BINDING_PATHS: Final[Mapping[str, str]] = {
    "corpus_manifest": "tests/fixtures/logic_conformance_v2/manifest.json",
    "profile_manifest": ("tests/fixtures/logic_conformance_v2/profile_manifest.json"),
    "provider_manifest": "tests/integration/logic_providers/manifest.json",
    "family_registry_source": "ipfs_datasets_py/logic/families/registry_v3.py",
    "family_profile_source": ("ipfs_datasets_py/logic/families/profile_catalog_v3.py"),
    "family_routes_source": ("ipfs_datasets_py/logic/translations/family_extensions.py"),
    "reachable_matrix": "data/logic/conformance/reachable_matrix_v2.json",
}

HARD_ZERO_FLOOR_NAMES: Final[tuple[str, ...]] = (
    "unexplained_reachable_gap",
    "silent_node_drop",
    "silent_node_loss",
    "raw_ingress",
    "family_drift",
    "false_capability",
    "authority_escalation",
    "kernel_trust_escape",
)
SEALING_EXCLUSIONS: Final[tuple[str, ...]] = ("LFP2-049", "LFP2-050")
_SEED_TASK_IDS: Final[tuple[str, ...]] = tuple(f"LFP2-{index:03d}" for index in range(51))
_TASK_HEADER_RE: Final = re.compile(r"(?m)^## (LFP2-([0-9]{3,})) .+$")
_STATUS_RE: Final = re.compile(r"(?m)^- Status: ([^\r\n]+)$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_OID_RE: Final = re.compile(r"^[0-9a-f]{40,64}$")

_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "interface",
        "version",
        "task_id",
        "goal_id",
        "program_id",
        "producer_id",
        "is_fixed_point",
        "consecutive_empty_scans",
        "sealing_exclusions",
        "open_nonsealing_task_ids",
        "open_nonsealing_task_count",
        "identity_bindings",
        "matrix_accounting",
        "scan_identity",
        "epochs",
        "ledger",
        "completion_authority",
        "mutation_authority",
        "seed_board_edit",
        "receipt_body_sha256",
    }
)
_LEDGER_SUMMARY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "raw_sha256",
        "entry_count",
        "head_entry_id",
        "head_entry_sha256",
    }
)


class FixedPointV2Error(ValueError):
    """A Wave-2 fixed-point input or artifact is malformed or stale."""


class FixedPointIdentityError(FixedPointV2Error):
    """The source/evidence repository identity is dirty or has drifted."""


class FixedPointMatrixError(FixedPointV2Error):
    """The reachable matrix fails a required hard-zero acceptance floor."""


class FixedPointOpenWorkError(FixedPointV2Error):
    """Non-sealing seed work or an appended derived task remains open."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FixedPointV2Error("value is not canonical-JSON encodable") from exc


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise FixedPointIdentityError(f"required identity input is unreadable: {path}") from exc


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FixedPointV2Error(f"{name} must be a JSON object")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], name: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise FixedPointV2Error(f"{name} keys differ (missing={missing}, extra={extra})")


def _require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise FixedPointV2Error(f"{name} must be a lowercase sha256 digest")
    return value


def _read_required_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FixedPointIdentityError(f"required UTF-8 input is unreadable: {path}") from exc


def normalize_seed_board(text: str) -> str:
    """Return the immutable 51-card seed board with ``Status`` normalized."""

    if not isinstance(text, str):
        raise FixedPointV2Error("task board must be text")
    first = re.search(r"(?m)^## LFP2-000 .+$", text)
    if first is None:
        raise FixedPointV2Error("task board has no LFP2-000 seed card")
    appended = re.search(
        r"(?m)^## LFP2-(?:05[1-9]|0[6-9][0-9]|[1-9][0-9]{2,}) .+$",
        text[first.start() :],
    )
    end = first.start() + appended.start() if appended else len(text)
    seed = text[first.start() : end].rstrip() + "\n"
    task_ids = tuple(match.group(1) for match in _TASK_HEADER_RE.finditer(seed))
    if task_ids != _SEED_TASK_IDS:
        raise FixedPointV2Error("seed task IDs/order differ from the sealed LFP2-000..LFP2-050 set")
    normalized = _STATUS_RE.sub("- Status: <normalized>", seed)
    if normalized.count("- Status: <normalized>") != len(_SEED_TASK_IDS):
        raise FixedPointV2Error("every seed task must have exactly one Status field")
    return normalized


def _normalized_task_board(text: str) -> str:
    """Normalize progress-only status fields while retaining derived cards."""

    headers = list(_TASK_HEADER_RE.finditer(text))
    if not headers:
        raise FixedPointV2Error("task board has no LFP2 task cards")
    normalized = _STATUS_RE.sub("- Status: <normalized>", text.rstrip() + "\n")
    return normalized


def _task_statuses_from_text(text: str) -> tuple[tuple[str, str], ...]:
    matches = list(_TASK_HEADER_RE.finditer(text))
    records: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        task_id = match.group(1)
        if task_id in seen:
            raise FixedPointV2Error(f"duplicate task card: {task_id}")
        seen.add(task_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.start() : end]
        statuses = _STATUS_RE.findall(block)
        if len(statuses) != 1:
            raise FixedPointV2Error(f"{task_id} must have exactly one Status field")
        records.append((task_id, statuses[0].strip().lower()))
    if tuple(task_id for task_id, _ in records[:51]) != _SEED_TASK_IDS:
        raise FixedPointV2Error("task board does not begin with the sealed seed set")
    return tuple(records)


def _coerce_task_statuses(tasks: Sequence[object]) -> tuple[tuple[str, str], ...]:
    records: list[tuple[str, str]] = []
    for task in tasks:
        if isinstance(task, Mapping):
            task_id = task.get("task_id", task.get("id", ""))
            status = task.get("status", "")
        else:
            task_id = getattr(task, "task_id", getattr(task, "id", ""))
            status = getattr(task, "status", "")
        if not isinstance(task_id, str) or not isinstance(status, str):
            raise FixedPointV2Error("tasks must expose string task_id and status")
        if re.fullmatch(r"LFP2-[0-9]{3,}", task_id):
            records.append((task_id, status.strip().lower()))
    return tuple(records)


def _assert_no_open_work(records: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    open_ids = tuple(task_id for task_id, status in records if status != "completed")
    forbidden = tuple(task_id for task_id in open_ids if task_id not in SEALING_EXCLUSIONS)
    if forbidden:
        derived = tuple(task_id for task_id in forbidden if int(task_id.removeprefix("LFP2-")) > 50)
        if derived:
            raise FixedPointOpenWorkError(f"appended derived tasks remain open: {list(derived)}")
        raise FixedPointOpenWorkError(f"non-sealing seed tasks remain open: {list(forbidden)}")
    return open_ids


def _git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=repo,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise FixedPointIdentityError("git is required for repository identity") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise FixedPointIdentityError(f"git {' '.join(args)} failed in {repo}: {detail}")
    return result.stdout


def _git_path(repo: Path, *args: str) -> Path:
    raw = _git(repo, *args).decode("utf-8", errors="strict").strip()
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (repo / path).resolve()


def _canonical_merge_target_worktree(repo_root: Path) -> Path:
    """Resolve the sole exact merge-target worktree in this common-dir."""

    common_dir = _git_path(repo_root, "rev-parse", "--git-common-dir")
    raw = _git(repo_root, "worktree", "list", "--porcelain").decode("utf-8", errors="strict")
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines() + [""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    target_ref = f"refs/heads/{MERGE_TARGET_BRANCH}"
    matches = [record for record in records if record.get("branch") == target_ref]
    if len(matches) != 1:
        raise FixedPointIdentityError(
            "expected exactly one worktree for merge-target branch "
            f"{MERGE_TARGET_BRANCH!r}; found {len(matches)}"
        )
    target_text = matches[0].get("worktree", "")
    if not target_text:
        raise FixedPointIdentityError("merge-target worktree has no filesystem path")
    target = Path(target_text).resolve()
    if not target.is_dir():
        raise FixedPointIdentityError("merge-target worktree path is missing")
    if _git_path(target, "rev-parse", "--git-common-dir") != common_dir:
        raise FixedPointIdentityError(
            "merge-target worktree does not share the candidate Git common-dir"
        )
    return target


def _collect_predecessor_bindings(repo_root: Path) -> dict[str, dict[str, str]]:
    canonical_root = _canonical_merge_target_worktree(repo_root)
    bindings: dict[str, dict[str, str]] = {}
    for index, (relative, expected) in enumerate(PREDECESSOR_ANCHOR_SHA256.items(), start=1):
        actual = _sha256_file(canonical_root / relative)
        if actual != expected:
            raise FixedPointIdentityError(f"Wave-1 predecessor anchor differs: {relative}")
        bindings[f"wave1_predecessor_{index:02d}"] = {
            "path": relative,
            "sha256": actual,
            "source": f"merge-target:{MERGE_TARGET_BRANCH}",
        }
    return bindings


def _collect_git_identity(repo_root: Path, nested_root: Path) -> dict[str, Any]:
    status = _git(nested_root, "status", "--porcelain=v1", "--untracked-files=all")
    dirty_paths: list[str] = []
    for line in status.decode("utf-8", errors="strict").splitlines():
        if len(line) < 4 or line[2] != " ":
            raise FixedPointIdentityError("nested Git status output is malformed")
        disposition = line[:2]
        path = line[3:]
        if "R" in disposition or "C" in disposition or " -> " in path:
            raise FixedPointIdentityError("nested renames/copies are not sealing-output exceptions")
        dirty_paths.append(path)
    forbidden_dirty = sorted(set(dirty_paths) - set(RELEASE_SELF_OUTPUT_PATHS))
    if forbidden_dirty:
        raise FixedPointIdentityError(
            f"nested semantic inputs must be clean before sealing; dirty paths: {forbidden_dirty}"
        )
    nested_head = _git(nested_root, "rev-parse", "HEAD").decode().strip()
    if not _OID_RE.fullmatch(nested_head):
        raise FixedPointIdentityError("nested repository returned a malformed object ID")
    stage = (
        _git(
            repo_root,
            "ls-files",
            "--stage",
            "--",
            NESTED_REPOSITORY_PATH,
        )
        .decode("utf-8", errors="strict")
        .strip()
    )
    match = re.fullmatch(
        rf"160000 ([0-9a-f]{{40,64}}) 0\t{re.escape(NESTED_REPOSITORY_PATH)}",
        stage,
    )
    if match is None:
        raise FixedPointIdentityError(
            "superproject must track ipfs_datasets_py as a mode-160000 gitlink"
        )
    gitlink = match.group(1)
    if gitlink != nested_head:
        raise FixedPointIdentityError(
            "superproject gitlink does not equal nested ipfs_datasets_py HEAD"
        )
    tree_listing = _git(nested_root, "ls-tree", "-r", "-z", "--full-tree", nested_head)
    projected_records: list[bytes] = []
    for record in tree_listing.split(b"\0"):
        if not record:
            continue
        try:
            _metadata, raw_path = record.split(b"\t", 1)
            path = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeError) as exc:
            raise FixedPointIdentityError("nested Git tree record is malformed") from exc
        if path not in RELEASE_SELF_OUTPUT_PATHS:
            projected_records.append(record + b"\0")
    projection = b"".join(projected_records)
    return {
        "nested_repository_path": NESTED_REPOSITORY_PATH,
        "semantic_projection_schema": "git-ls-tree-release-exclusion/v1",
        "semantic_tree_projection_sha256": _sha256_bytes(projection),
        "excluded_release_self_outputs": list(RELEASE_SELF_OUTPUT_PATHS),
        "gitlink_matches_nested_head": "true",
        "semantic_inputs_clean": "true",
    }


def _live_matrix_accounting(path: Path) -> dict[str, Any]:
    """Rematerialize the live matrix and bind its quantitative identity."""

    try:
        from ipfs_datasets_py.logic.conformance.matrix_v2 import (
            ensure_seal_matches_live,
        )

        live = ensure_seal_matches_live(path)
    except Exception as exc:
        raise FixedPointMatrixError(
            f"reachable matrix seal does not match live materialization: {exc}"
        ) from exc
    floors = live.hard_zero_floors.to_dict()
    return {
        "interface": live.interface,
        "content_id": live.content_id,
        "content_sha256": live.content_sha256,
        "cell_count": len(live.cells),
        "domain_count": len({cell.domain_id for cell in live.cells}),
        "domain_ids": sorted({cell.domain_id for cell in live.cells}),
        "provider_count": len({cell.provider_id for cell in live.cells}),
        "provider_ids": sorted({cell.provider_id for cell in live.cells}),
        "hard_zero_floors": floors,
        "acceptance_holds": live.acceptance_holds(),
    }


def _validate_matrix(path: Path) -> dict[str, Any]:
    try:
        matrix = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FixedPointMatrixError("reachable matrix is not valid UTF-8 JSON") from exc
    root = _require_mapping(matrix, "reachable matrix")
    acceptance = _require_mapping(root.get("acceptance"), "matrix.acceptance")
    floors = _require_mapping(root.get("hard_zero_floors"), "matrix.hard_zero_floors")
    summary = _require_mapping(root.get("summary"), "matrix.summary")
    for name in HARD_ZERO_FLOOR_NAMES:
        for container_name, container in (
            ("acceptance", acceptance),
            ("hard_zero_floors", floors),
        ):
            value = container.get(name)
            if isinstance(value, bool) or value != 0:
                raise FixedPointMatrixError(f"matrix.{container_name}.{name} must be integer zero")
    for container_name, container, names in (
        ("acceptance", acceptance, ("hard_zero_floors_clear", "sparse")),
        ("hard_zero_floors", floors, ("all_clear",)),
        (
            "summary",
            summary,
            (
                "acceptance_holds",
                "every_cell_has_all_join_dimensions",
                "hard_zero_floors_clear",
                "sparse",
            ),
        ),
    ):
        for name in names:
            if container.get(name) is not True:
                raise FixedPointMatrixError(f"matrix.{container_name}.{name} must be true")
    accounting = _live_matrix_accounting(path)
    if accounting.get("acceptance_holds") is not True:
        raise FixedPointMatrixError("live reachable matrix acceptance is not true")
    live_floors = _require_mapping(
        accounting.get("hard_zero_floors"), "live matrix hard_zero_floors"
    )
    if live_floors.get("all_clear") is not True:
        raise FixedPointMatrixError("live reachable matrix floors are not clear")
    for name in HARD_ZERO_FLOOR_NAMES:
        value = live_floors.get(name)
        if isinstance(value, bool) or value != 0:
            raise FixedPointMatrixError(f"live matrix {name} must be integer zero")
    return accounting


def collect_current_identity(repo_root: Path | str) -> dict[str, Any]:
    """Collect and validate every exact identity bound by the fixed point."""

    root = Path(repo_root).resolve()
    todo_path = root / TODO_RELATIVE_PATH
    todo_text = _read_required_text(todo_path)
    normalized_seed = normalize_seed_board(todo_text)
    records = _task_statuses_from_text(todo_text)
    open_ids = _assert_no_open_work(records)

    bindings: dict[str, dict[str, str]] = {
        "normalized_seed_board": {
            "path": TODO_RELATIVE_PATH + "#LFP2-000..LFP2-050-status-normalized",
            "sha256": _sha256_bytes(normalized_seed.encode("utf-8")),
        },
        "normalized_task_board": {
            "path": TODO_RELATIVE_PATH + "#all-task-status-normalized",
            "sha256": _sha256_bytes(_normalized_task_board(todo_text).encode("utf-8")),
        },
        "objective": {
            "path": OBJECTIVE_RELATIVE_PATH,
            "sha256": _sha256_file(root / OBJECTIVE_RELATIVE_PATH),
        },
        "scheduler_config": {
            "path": SCHEDULER_RELATIVE_PATH,
            "sha256": _sha256_file(root / SCHEDULER_RELATIVE_PATH),
        },
    }
    nested_root = root / NESTED_REPOSITORY_PATH
    for name, relative in _NESTED_BINDING_PATHS.items():
        bindings[name] = {
            "path": f"{NESTED_REPOSITORY_PATH}/{relative}",
            "sha256": _sha256_file(nested_root / relative),
        }
    matrix_accounting = _validate_matrix(nested_root / _NESTED_BINDING_PATHS["reachable_matrix"])
    git_identity = _collect_git_identity(root, nested_root)
    predecessor_bindings = _collect_predecessor_bindings(root)

    corpus_identity = _sha256_bytes(
        _canonical_bytes(
            {name: bindings[name]["sha256"] for name in ("corpus_manifest", "profile_manifest")}
        )
    )
    registry_identity = _sha256_bytes(
        _canonical_bytes(
            {
                name: bindings[name]["sha256"]
                for name in (
                    "family_registry_source",
                    "family_profile_source",
                    "family_routes_source",
                )
            }
        )
    )
    source_identity = _sha256_bytes(
        _canonical_bytes(
            {
                "normalized_seed_board": bindings["normalized_seed_board"]["sha256"],
                "normalized_task_board": bindings["normalized_task_board"]["sha256"],
                "reachable_matrix": bindings["reachable_matrix"]["sha256"],
                "semantic_tree_projection": git_identity["semantic_tree_projection_sha256"],
                "wave1_predecessor_anchors": _sha256_bytes(_canonical_bytes(predecessor_bindings)),
            }
        )
    )
    scan = ScanIdentity(
        source_identity=source_identity,
        config_identity=bindings["scheduler_config"]["sha256"],
        corpus_identity=corpus_identity,
        provider_identity=bindings["provider_manifest"]["sha256"],
        registry_identity=registry_identity,
        objective_identity=bindings["objective"]["sha256"],
        tree_id=(f"semantic-tree-projection:{git_identity['semantic_tree_projection_sha256']}"),
        repository_id=(
            "gitlink-verified-semantic-projection:"
            f"{git_identity['semantic_tree_projection_sha256']}"
        ),
    )
    return {
        "bindings": bindings,
        "predecessor_bindings": predecessor_bindings,
        "git": git_identity,
        "scan_identity": scan.to_dict(),
        "open_task_ids": list(open_ids),
        "matrix_accounting": matrix_accounting,
    }


def _empty_epochs(scan_identity: ScanIdentity) -> tuple[dict[str, Any], ...]:
    first = run_admission_epoch(
        (),
        scan_identity=scan_identity,
        epoch_id="lfp2-fixed-point-epoch-1",
        now_epoch_s=0,
    )
    if first.disposition is not EpochDisposition.EMPTY_INPUT or first.admits_work:
        raise FixedPointV2Error("first quiet epoch was not EMPTY_INPUT")
    second = run_admission_epoch(
        (),
        scan_identity=scan_identity,
        memory=first.memory,
        epoch_id="lfp2-fixed-point-epoch-2",
        now_epoch_s=0,
    )
    if second.disposition is not EpochDisposition.EMPTY_INPUT or second.admits_work:
        raise FixedPointV2Error("second quiet epoch was not EMPTY_INPUT")
    if not first.scan_identity.matches(second.scan_identity):
        raise FixedPointIdentityError("quiet epoch scan identities differ")
    return (first.to_dict(), second.to_dict())


def _ledger_entry(epoch: Mapping[str, Any], sequence: int, previous_sha256: str) -> dict[str, Any]:
    body = {
        "schema": FIXED_POINT_LEDGER_ENTRY_SCHEMA,
        "sequence": sequence,
        "previous_entry_sha256": previous_sha256,
        "epoch_id": epoch["epoch_id"],
        "epoch_receipt_sha256": _sha256_bytes(_canonical_bytes(epoch)),
        "scan_identity_sha256": _sha256_bytes(_canonical_bytes(epoch["scan_identity"])),
        "disposition": EpochDisposition.EMPTY_INPUT.value,
        "admitted_task_count": 0,
        "open_task_count": 0,
        "completion_authority": False,
        "mutation_authority": False,
        "seed_board_edit": False,
    }
    digest = _sha256_bytes(_canonical_bytes(body))
    return {**body, "entry_id": digest, "entry_sha256": digest}


def _render_ledger(epochs: Sequence[Mapping[str, Any]]) -> tuple[bytes, list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    previous = "sha256:" + ("0" * 64)
    for sequence, epoch in enumerate(epochs, start=1):
        entry = _ledger_entry(epoch, sequence, previous)
        entries.append(entry)
        previous = entry["entry_sha256"]
    raw = b"".join(_canonical_bytes(entry) + b"\n" for entry in entries)
    return raw, entries


def _receipt_body(
    identity: Mapping[str, Any],
    epochs: Sequence[Mapping[str, Any]],
    ledger_raw: bytes,
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": OBJECTIVE_FIXED_POINT_RECEIPT_SCHEMA,
        "interface": OBJECTIVE_REFILL_FIXED_POINT_INTERFACE,
        "version": FIXED_POINT_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer_id": PRODUCER_ID,
        "is_fixed_point": True,
        "consecutive_empty_scans": 2,
        "sealing_exclusions": list(SEALING_EXCLUSIONS),
        "open_nonsealing_task_ids": [],
        "open_nonsealing_task_count": 0,
        "identity_bindings": {
            "files": identity["bindings"],
            "nested_repository": identity["git"],
            "wave1_predecessor": identity["predecessor_bindings"],
        },
        "scan_identity": identity["scan_identity"],
        "matrix_accounting": identity["matrix_accounting"],
        "epochs": list(epochs),
        "ledger": {
            "raw_sha256": _sha256_bytes(ledger_raw),
            "entry_count": len(entries),
            "head_entry_id": entries[-1]["entry_id"],
            "head_entry_sha256": entries[-1]["entry_sha256"],
        },
        "completion_authority": False,
        "mutation_authority": False,
        "seed_board_edit": False,
    }


def _parse_json_object(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FixedPointV2Error(f"{name} is not canonical UTF-8 JSON") from exc
    return dict(_require_mapping(value, name))


def parse_fixed_point_receipt(
    value: Mapping[str, Any] | str | bytes | Path,
) -> dict[str, Any]:
    """Parse a receipt mapping, JSON bytes/text, or filesystem path."""

    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Path):
        try:
            return _parse_json_object(value.read_bytes(), "fixed-point receipt")
        except OSError as exc:
            raise FixedPointV2Error(f"fixed-point receipt is unreadable: {value}") from exc
    if isinstance(value, bytes):
        return _parse_json_object(value, "fixed-point receipt")
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped.startswith("{"):
            return _parse_json_object(value.encode("utf-8"), "fixed-point receipt")
        return parse_fixed_point_receipt(Path(value))
    raise FixedPointV2Error("unsupported fixed-point receipt input")


def _validate_task_argument(tasks: Sequence[object] | None, current: Mapping[str, Any]) -> None:
    del current
    if tasks is None:
        return
    _assert_no_open_work(_coerce_task_statuses(tasks))


def validate_fixed_point_receipt(
    receipt: Mapping[str, Any] | str | bytes | Path,
    *,
    repo_root: Path | str,
    ledger_bytes: bytes,
    tasks: Sequence[object] | None = None,
) -> dict[str, Any]:
    """Validate a receipt, ledger, current identities, and open-work posture."""

    parsed = parse_fixed_point_receipt(receipt)
    _require_exact_keys(parsed, _TOP_LEVEL_KEYS, "fixed-point receipt")
    expected_scalars = {
        "schema": OBJECTIVE_FIXED_POINT_RECEIPT_SCHEMA,
        "interface": OBJECTIVE_REFILL_FIXED_POINT_INTERFACE,
        "version": FIXED_POINT_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer_id": PRODUCER_ID,
        "is_fixed_point": True,
        "consecutive_empty_scans": 2,
        "sealing_exclusions": list(SEALING_EXCLUSIONS),
        "open_nonsealing_task_ids": [],
        "open_nonsealing_task_count": 0,
        "completion_authority": False,
        "mutation_authority": False,
        "seed_board_edit": False,
    }
    for key, expected in expected_scalars.items():
        if parsed.get(key) != expected or type(parsed.get(key)) is not type(expected):
            raise FixedPointV2Error(f"fixed-point receipt {key} differs")

    current = collect_current_identity(repo_root)
    _validate_task_argument(tasks, current)
    expected_bindings = {
        "files": current["bindings"],
        "nested_repository": current["git"],
        "wave1_predecessor": current["predecessor_bindings"],
    }
    if parsed.get("identity_bindings") != expected_bindings:
        raise FixedPointIdentityError("receipt content/repository identities have drifted")
    if parsed.get("scan_identity") != current["scan_identity"]:
        raise FixedPointIdentityError("receipt ScanIdentity has drifted")
    if parsed.get("matrix_accounting") != current["matrix_accounting"]:
        raise FixedPointMatrixError("receipt live matrix accounting has drifted")

    scan = ScanIdentity.from_dict(current["scan_identity"])
    expected_epochs = list(_empty_epochs(scan))
    if parsed.get("epochs") != expected_epochs:
        raise FixedPointV2Error("receipt does not contain the two exact EMPTY_INPUT epochs")
    expected_ledger, entries = _render_ledger(expected_epochs)
    if ledger_bytes != expected_ledger:
        raise FixedPointV2Error("gap ledger bytes or hash chain differ")
    ledger = _require_mapping(parsed.get("ledger"), "receipt.ledger")
    _require_exact_keys(ledger, _LEDGER_SUMMARY_KEYS, "receipt.ledger")
    expected_summary = {
        "raw_sha256": _sha256_bytes(expected_ledger),
        "entry_count": 2,
        "head_entry_id": entries[-1]["entry_id"],
        "head_entry_sha256": entries[-1]["entry_sha256"],
    }
    if dict(ledger) != expected_summary:
        raise FixedPointV2Error("receipt ledger summary/digest differs")
    _require_digest(parsed.get("receipt_body_sha256"), "receipt_body_sha256")
    body = {key: value for key, value in parsed.items() if key != "receipt_body_sha256"}
    if parsed["receipt_body_sha256"] != _sha256_bytes(_canonical_bytes(body)):
        raise FixedPointV2Error("receipt body sha256 mismatch")
    return parsed


def validate_fixed_point_artifacts(
    fixed_path: Path | str,
    ledger_path: Path | str,
    *,
    repo_root: Path | str,
    tasks: Sequence[object] | None = None,
) -> dict[str, Any]:
    """Validate canonical on-disk receipt and JSONL ledger artifacts."""

    root = Path(repo_root).resolve()
    fixed = _safe_output(root, fixed_path)
    ledger = _safe_output(root, ledger_path)
    try:
        fixed_raw = fixed.read_bytes()
        ledger_raw = ledger.read_bytes()
    except OSError as exc:
        raise FixedPointV2Error("fixed-point receipt or ledger is unreadable") from exc
    parsed = _parse_json_object(fixed_raw, "fixed-point receipt")
    if fixed_raw != _canonical_bytes(parsed) + b"\n":
        raise FixedPointV2Error("fixed-point receipt is not strict canonical JSON")
    return validate_fixed_point_receipt(
        parsed,
        repo_root=root,
        ledger_bytes=ledger_raw,
        tasks=tasks,
    )


def _safe_output(repo_root: Path, value: Path | str) -> Path:
    path = Path(value)
    target = path.resolve() if path.is_absolute() else (repo_root / path).resolve()
    if not target.is_relative_to(repo_root):
        raise FixedPointV2Error("artifact output must remain inside repo_root")
    return target


def materialize_fixed_point_evidence(
    *,
    repo_root: Path | str,
    fixed_point_path: Path | str = DEFAULT_FIXED_POINT_RELATIVE_PATH,
    ledger_path: Path | str = DEFAULT_LEDGER_RELATIVE_PATH,
    tasks: Sequence[object] | None = None,
) -> dict[str, Any]:
    """Materialize, then independently validate, the Wave-2 seal artifacts."""

    root = Path(repo_root).resolve()
    identity = collect_current_identity(root)
    _validate_task_argument(tasks, identity)
    scan = ScanIdentity.from_dict(identity["scan_identity"])
    epochs = list(_empty_epochs(scan))
    ledger_raw, entries = _render_ledger(epochs)
    body = _receipt_body(identity, epochs, ledger_raw, entries)
    receipt = {
        **body,
        "receipt_body_sha256": _sha256_bytes(_canonical_bytes(body)),
    }
    fixed = _safe_output(root, fixed_point_path)
    ledger = _safe_output(root, ledger_path)
    if fixed == ledger:
        raise FixedPointV2Error("receipt and ledger paths must differ")
    fixed.parent.mkdir(parents=True, exist_ok=True)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_bytes(ledger_raw)
    fixed.write_bytes(_canonical_bytes(receipt) + b"\n")
    return validate_fixed_point_artifacts(
        fixed,
        ledger,
        repo_root=root,
        tasks=tasks,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("materialize", "validate"))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--fixed-point-path", default=DEFAULT_FIXED_POINT_RELATIVE_PATH)
    parser.add_argument("--ledger-path", default=DEFAULT_LEDGER_RELATIVE_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "materialize":
            receipt = materialize_fixed_point_evidence(
                repo_root=args.repo_root,
                fixed_point_path=args.fixed_point_path,
                ledger_path=args.ledger_path,
            )
        else:
            receipt = validate_fixed_point_artifacts(
                args.fixed_point_path,
                args.ledger_path,
                repo_root=args.repo_root,
            )
    except FixedPointV2Error as exc:
        print(f"fixed-point-v2: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "valid": True,
                "is_fixed_point": receipt["is_fixed_point"],
                "consecutive_empty_scans": receipt["consecutive_empty_scans"],
                "receipt_body_sha256": receipt["receipt_body_sha256"],
                "ledger_raw_sha256": receipt["ledger"]["raw_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "DEFAULT_FIXED_POINT_RELATIVE_PATH",
    "DEFAULT_LEDGER_RELATIVE_PATH",
    "FIXED_POINT_LEDGER_ENTRY_SCHEMA",
    "FIXED_POINT_VERSION",
    "FixedPointIdentityError",
    "FixedPointMatrixError",
    "FixedPointOpenWorkError",
    "FixedPointV2Error",
    "GOAL_ID",
    "OBJECTIVE_FIXED_POINT_RECEIPT_SCHEMA",
    "OBJECTIVE_REFILL_FIXED_POINT_INTERFACE",
    "PROGRAM_ID",
    "RELEASE_SELF_OUTPUT_PATHS",
    "SEALING_EXCLUSIONS",
    "TASK_ID",
    "collect_current_identity",
    "main",
    "materialize_fixed_point_evidence",
    "normalize_seed_board",
    "parse_fixed_point_receipt",
    "validate_fixed_point_artifacts",
    "validate_fixed_point_receipt",
]


if __name__ == "__main__":
    raise SystemExit(main())
