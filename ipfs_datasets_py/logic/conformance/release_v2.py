"""Deterministic Wave-2 logic-family parser release evidence (LFP2-050).

The release receipt is an evidence join.  It deliberately grants no mutation,
completion, solver, theorem, or kernel authority.  Its two output paths are
excluded by the fixed-point semantic tree projection, which makes repeated
materialization byte-for-byte stable before and after those outputs are
committed.  Task and goal status fields are normalized for the same reason.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

LOGIC_PARSER_RELEASE_INTERFACE: Final = "LogicParserReleaseReceipt@2"
LOGIC_PARSER_RELEASE_SCHEMA: Final = "logic-parser-release-receipt/v2"
RELEASE_VERSION: Final = "2.0.0"
TASK_ID: Final = "LFP2-050"
GOAL_ID: Final = "LFP2-G100"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v2"
PRODUCER_ID: Final = "logic-parser-release@2"

DEFAULT_JSON_RELATIVE_PATH: Final = "data/logic/conformance/logic_family_parser_v2_release.json"
DEFAULT_MARKDOWN_RELATIVE_PATH: Final = "docs/architecture/logic/LOGIC_FAMILY_PARSER_V2_RELEASE.md"
FIXED_POINT_RELATIVE_PATH: Final = (
    "data/agent_supervisor/ipfs_datasets_logic_family_parser_v2/refill/fixed_point_receipt.json"
)
LEDGER_RELATIVE_PATH: Final = (
    "data/agent_supervisor/ipfs_datasets_logic_family_parser_v2/refill/gap_ledger.jsonl"
)
TODO_RELATIVE_PATH: Final = "docs/architecture/ipfs_datasets_logic_family_parser_v2.todo.md"
OBJECTIVE_RELATIVE_PATH: Final = (
    "docs/architecture/ipfs_datasets_logic_family_parser_v2.objectives.md"
)
PLAN_RELATIVE_PATH: Final = "docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_V2_PLAN.md"
SCHEDULER_RELATIVE_PATH: Final = (
    "config/agent_supervisor_ipfs_datasets_logic_family_parser_v2_scheduler.json"
)
NESTED_REPOSITORY_PATH: Final = "ipfs_datasets_py"

_NESTED_FILES: Final[Mapping[str, str]] = {
    "wave1_release": "data/logic/conformance/logic_family_parser_release.json",
    "reachable_matrix": "data/logic/conformance/reachable_matrix_v2.json",
    "corpus_manifest": "tests/fixtures/logic_conformance_v2/manifest.json",
    "profile_manifest": "tests/fixtures/logic_conformance_v2/profile_manifest.json",
    "provider_manifest": "tests/integration/logic_providers/manifest.json",
}

_EXPECTED_PREDECESSOR: Final[Mapping[str, str]] = {
    "predecessor_board_namespace": "ipfs-datasets-logic-family-parser-v1",
    "predecessor_terminal_task_id": "LFP-047",
    "predecessor_accelerator_commit": "e162c19d087d4e6511f8eb97fd34ecb449777897",
    "predecessor_datasets_commit": "fc49cbb3e0e96bf07b367859da32123187d706c1",
    "predecessor_seed_definition_sha256": (
        "sha256:f5d01bcc13c0b62d35b713cccb2e04abe49da454e9fa6f35cd28a5ad4b72eb44"
    ),
    "predecessor_release_receipt_path": (
        "ipfs_datasets_py/data/logic/conformance/logic_family_parser_release.json"
    ),
    "predecessor_release_receipt_sha256": (
        "sha256:86412a60bfde9b8a13156ab097b44443a4a8f70a7b286f1c7a707366c93757ce"
    ),
}

_EXPECTED_AUTHORITY_POLICY: Final[Mapping[str, object]] = {
    "parser_or_solver_success_is_completion_authority": False,
    "advisor_output_is_completion_authority": False,
    "official_kernel_check_required_for_kernel_proof": True,
    "independent_countermodel_validation_required_for_refutation": True,
    "silent_translation_loss_allowed": False,
    "raw_target_source_without_receipt_allowed": False,
    "differential_agreement_is_proof": False,
    "unknown_ambiguous_stale_or_unsupported_disposition": ("abstain_or_require_approval"),
}

_TASK_HEADER_RE: Final = re.compile(r"(?m)^## (LFP2-[0-9]{3,}) .+$")
_TASK_STATUS_RE: Final = re.compile(r"(?m)^- Status: ([^\r\n]+)$")
_GOAL_STATUS_RE: Final = re.compile(r"(?im)^- Status: [^\r\n]+$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_OID_RE: Final = re.compile(r"^[0-9a-f]{40,64}$")
_TERMINAL_STATUSES: Final = frozenset({"completed"})


class ReleaseV2Error(ValueError):
    """A Wave-2 release input, binding, or rendered artifact is invalid."""


class ReleaseStaleError(ReleaseV2Error):
    """The release evidence no longer matches the current semantic identity."""


class ReleaseOpenWorkError(ReleaseV2Error):
    """A non-sealing task remains open."""


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
        raise ReleaseV2Error("value is not canonical-JSON encodable") from exc


def _pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ReleaseV2Error(f"required artifact is unreadable: {path}") from exc


def _pairs_no_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseV2Error(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_number(value: str) -> object:
    raise ReleaseV2Error(f"non-integral or non-finite JSON number is forbidden: {value}")


def _parse_json_bytes(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseV2Error(f"{name} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseV2Error(f"{name} root must be an object")
    return value


def _load_json(path: Path, name: str) -> dict[str, Any]:
    try:
        return _parse_json_bytes(path.read_bytes(), name)
    except OSError as exc:
        raise ReleaseV2Error(f"{name} is unreadable: {path}") from exc


def _require_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseV2Error(f"{name} must be an object")
    return dict(value)


def _require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReleaseV2Error(f"{name} must be a lowercase sha256 digest")
    return value


def _git(repo: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        check=False,
        capture_output=True,
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseV2Error(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _resolve_roots(repo_root: Path | str) -> tuple[Path, Path]:
    root = Path(repo_root).resolve()
    if not (root / SCHEDULER_RELATIVE_PATH).is_file() and (
        (root / "ipfs_datasets_py/logic/conformance").is_dir()
        and (root.parent / SCHEDULER_RELATIVE_PATH).is_file()
        and root.name == NESTED_REPOSITORY_PATH
    ):
        nested = root
        root = root.parent
    else:
        nested = root / NESTED_REPOSITORY_PATH
    if not (root / SCHEDULER_RELATIVE_PATH).is_file():
        raise ReleaseV2Error("repo_root does not identify the supervisor repository")
    if not (nested / "ipfs_datasets_py/logic/conformance").is_dir():
        raise ReleaseV2Error("the nested ipfs_datasets_py repository is missing")
    return root, nested


def _safe_nested_output(nested: Path, value: Path | str, expected: str) -> Path:
    raw = Path(value)
    expected_target = nested / expected
    if ".." in raw.parts:
        raise ReleaseV2Error(f"release output must be exactly {expected}")
    if raw.is_absolute():
        if raw != expected_target:
            raise ReleaseV2Error(f"release output must be exactly {expected_target}")
        target = raw
    else:
        if raw.as_posix() != expected:
            raise ReleaseV2Error(f"release output must be exactly {expected}")
        target = nested / raw
    if nested.is_symlink():
        raise ReleaseV2Error("the nested repository must not be a symlink")
    cursor = nested
    for part in Path(expected).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ReleaseV2Error(f"release output path traverses a symlink: {cursor}")
    return target


def _task_board_binding(root: Path) -> dict[str, Any]:
    path = root / TODO_RELATIVE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReleaseV2Error("Wave-2 task board is unreadable") from exc
    matches = list(_TASK_HEADER_RE.finditer(text))
    if not matches:
        raise ReleaseV2Error("Wave-2 task board contains no task cards")
    records: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        task_id = match.group(1)
        if task_id in seen:
            raise ReleaseV2Error(f"duplicate task card: {task_id}")
        seen.add(task_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        statuses = _TASK_STATUS_RE.findall(text[match.end() : end])
        if len(statuses) != 1:
            raise ReleaseV2Error(f"{task_id} must have exactly one Status field")
        records.append((task_id, statuses[0].strip().lower()))
    required = {f"LFP2-{index:03d}" for index in range(51)}
    missing = sorted(required - seen)
    if missing:
        raise ReleaseV2Error(f"Wave-2 seed task cards are missing: {missing}")
    open_ids = sorted(
        task_id
        for task_id, status in records
        if task_id != TASK_ID and status not in _TERMINAL_STATUSES
    )
    if open_ids:
        raise ReleaseOpenWorkError(f"non-sealing tasks remain open: {open_ids}")
    sealing_status = dict(records)[TASK_ID]
    if sealing_status not in {"todo", "completed"}:
        raise ReleaseOpenWorkError("LFP2-050 must be todo or completed while sealing")
    try:
        from ipfs_datasets_py.logic.conformance.fixed_point_v2 import (
            normalize_seed_board,
        )

        normalized_seed = normalize_seed_board(text)
    except Exception as exc:
        raise ReleaseV2Error(f"seed-board normalization failed: {exc}") from exc
    normalized_all = _TASK_STATUS_RE.sub("- Status: <normalized>", text.rstrip() + "\n")
    return {
        "path": TODO_RELATIVE_PATH,
        "seed_task_count": 51,
        "derived_task_count": len(records) - 51,
        "open_nonsealing_task_ids": [],
        "sealing_status_normalized": True,
        "normalized_seed_sha256": _sha256_bytes(normalized_seed.encode("utf-8")),
        "normalized_all_tasks_sha256": _sha256_bytes(normalized_all.encode("utf-8")),
    }


def _control_bindings(root: Path) -> dict[str, Any]:
    board = _task_board_binding(root)
    try:
        objective = (root / OBJECTIVE_RELATIVE_PATH).read_text(encoding="utf-8")
        plan = (root / PLAN_RELATIVE_PATH).read_bytes()
    except (OSError, UnicodeError) as exc:
        raise ReleaseV2Error("Wave-2 plan/objective is unreadable") from exc
    normalized_objective = _GOAL_STATUS_RE.sub("- Status: <normalized>", objective.rstrip() + "\n")
    scheduler = _load_json(root / SCHEDULER_RELATIVE_PATH, "scheduler config")
    if scheduler.get("board_namespace") != PROGRAM_ID:
        raise ReleaseV2Error("scheduler board namespace drift")
    if scheduler.get("merge_target_branch") != "agent/logic-family-parser-v2-supervisor":
        raise ReleaseV2Error("scheduler merge-target branch drift")
    predecessor = _require_mapping(
        scheduler.get("predecessor_binding"), "scheduler.predecessor_binding"
    )
    if predecessor != dict(_EXPECTED_PREDECESSOR):
        raise ReleaseV2Error("scheduler Wave-1 predecessor binding drift")
    policy = _require_mapping(scheduler.get("authority_policy"), "authority_policy")
    if policy != dict(_EXPECTED_AUTHORITY_POLICY):
        raise ReleaseV2Error("scheduler authority policy drift")
    return {
        "task_board": board,
        "objective": {
            "path": OBJECTIVE_RELATIVE_PATH,
            "status_normalized": True,
            "sha256": _sha256_bytes(normalized_objective.encode("utf-8")),
        },
        "plan": {"path": PLAN_RELATIVE_PATH, "sha256": _sha256_bytes(plan)},
        "scheduler": {
            "path": SCHEDULER_RELATIVE_PATH,
            "canonical_sha256": _sha256_bytes(_canonical_bytes(scheduler)),
            "schema": scheduler.get("schema"),
        },
        "predecessor_config": predecessor,
        "authority_policy": policy,
    }


def _assert_ancestor(repo: Path, ancestor: str, name: str) -> None:
    if not _OID_RE.fullmatch(ancestor):
        raise ReleaseV2Error(f"{name} is not a Git object ID")
    result = subprocess.run(
        ["git", "-C", os.fspath(repo), "merge-base", "--is-ancestor", ancestor, "HEAD"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise ReleaseV2Error(f"{name} is not an ancestor of the current repository")


def _fixed_point_binding(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from ipfs_datasets_py.logic.conformance.fixed_point_v2 import (
            validate_fixed_point_artifacts,
        )

        receipt = validate_fixed_point_artifacts(
            root / FIXED_POINT_RELATIVE_PATH,
            root / LEDGER_RELATIVE_PATH,
            repo_root=root,
        )
    except Exception as exc:
        raise ReleaseV2Error(f"current fixed-point validation failed: {exc}") from exc
    if receipt.get("is_fixed_point") is not True:
        raise ReleaseV2Error("fixed-point receipt does not assert a fixed point")
    for field in ("completion_authority", "mutation_authority", "seed_board_edit"):
        if receipt.get(field) is not False:
            raise ReleaseV2Error(f"fixed-point {field} must be false")
    fixed_digest = _sha256_file(root / FIXED_POINT_RELATIVE_PATH)
    ledger_digest = _sha256_file(root / LEDGER_RELATIVE_PATH)
    fixed = {
        "interface": receipt.get("interface"),
        "schema": receipt.get("schema"),
        "receipt_body_sha256": _require_digest(
            receipt.get("receipt_body_sha256"), "fixed-point receipt body"
        ),
        "fixed_point_file_sha256": fixed_digest,
        "ledger_file_sha256": ledger_digest,
        "consecutive_empty_scans": receipt.get("consecutive_empty_scans"),
        "open_nonsealing_task_count": receipt.get("open_nonsealing_task_count"),
        "scan_identity": receipt.get("scan_identity"),
        "matrix_accounting": receipt.get("matrix_accounting"),
        "nested_repository": _require_mapping(
            _require_mapping(receipt.get("identity_bindings"), "identity_bindings").get(
                "nested_repository"
            ),
            "identity_bindings.nested_repository",
        ),
        "wave1_predecessor": _require_mapping(
            _require_mapping(receipt.get("identity_bindings"), "identity_bindings").get(
                "wave1_predecessor"
            ),
            "identity_bindings.wave1_predecessor",
        ),
    }
    return fixed, receipt


def _file_manifest_binding(
    path: Path,
    relative_path: str,
    name: str,
    interface: str,
    schema: str,
) -> dict[str, Any]:
    payload = _load_json(path, name)
    if payload.get("interface") != interface or payload.get("schema_version") != schema:
        raise ReleaseV2Error(f"{name} interface/schema drift")
    return {
        "path": relative_path,
        "sha256": _sha256_file(path),
        "interface": interface,
        "schema_version": schema,
        "item_count": len(
            payload.get("providers", payload.get("profiles", payload.get("fixtures", ())))
        ),
        "task_id": payload.get("task_id", payload.get("task")),
    }


def _semantic_evidence(nested: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from ipfs_datasets_py.logic.conformance.matrix_v2 import (
            HARD_ZERO_FLOOR_NAMES,
            ensure_seal_matches_live,
        )
        from ipfs_datasets_py.logic.conformance.replay_v2 import (
            build_logic_evidence_replay_report,
        )
        from ipfs_datasets_py.logic.families.profile_catalog_v3 import (
            DEFAULT_PROFILE_CATALOG_V3,
        )
        from ipfs_datasets_py.logic.families.registry_v3 import DEFAULT_REGISTRY_V3
        from ipfs_datasets_py.logic.translations.family_extensions import (
            DEFAULT_FAMILY_EXTENSION_ROUTES,
        )

        matrix = ensure_seal_matches_live(nested / _NESTED_FILES["reachable_matrix"])
        replay = build_logic_evidence_replay_report()
    except Exception as exc:
        raise ReleaseV2Error(f"live semantic evidence validation failed: {exc}") from exc
    if not matrix.acceptance_holds() or not replay.acceptance_holds():
        raise ReleaseV2Error("matrix/replay acceptance must hold")
    floors = matrix.hard_zero_floors.to_dict()
    for name in HARD_ZERO_FLOOR_NAMES:
        if type(floors.get(name)) is not int or floors[name] != 0:
            raise ReleaseV2Error(f"reachable matrix hard-zero floor {name} is not zero")
    registry = DEFAULT_REGISTRY_V3.to_dict()
    profiles = DEFAULT_PROFILE_CATALOG_V3.to_dict()
    routes = DEFAULT_FAMILY_EXTENSION_ROUTES.to_dict()
    authority_histogram = dict(
        sorted(Counter(cell.authority_ceiling for cell in matrix.cells).items())
    )
    evidence = {
        "reachable_matrix": {
            "path": _NESTED_FILES["reachable_matrix"],
            "seal_sha256": _sha256_file(nested / _NESTED_FILES["reachable_matrix"]),
            "interface": matrix.interface,
            "content_id": matrix.content_id,
            "content_sha256": matrix.content_sha256,
            "cell_count": len(matrix.cells),
            "hard_zero_floors": floors,
            "acceptance_holds": True,
            "authority_ceiling_histogram": authority_histogram,
        },
        "corpus_manifest": _file_manifest_binding(
            nested / _NESTED_FILES["corpus_manifest"],
            _NESTED_FILES["corpus_manifest"],
            "corpus manifest",
            "LogicConformanceCorpus@2",
            "logic-conformance-corpus/v2",
        ),
        "profile_manifest": _file_manifest_binding(
            nested / _NESTED_FILES["profile_manifest"],
            _NESTED_FILES["profile_manifest"],
            "profile manifest",
            "LogicConformanceCorpus@2",
            "logic-profile-manifest/v2",
        ),
        "provider_manifest": _file_manifest_binding(
            nested / _NESTED_FILES["provider_manifest"],
            _NESTED_FILES["provider_manifest"],
            "provider manifest",
            "ScheduledProviderTier@1",
            "scheduled-provider-tiers/v1",
        ),
        "family_registry": {
            "interface": registry.get("interface"),
            "schema_version": registry.get("schema_version"),
            "content_id": _sha256_bytes(_canonical_bytes(registry)),
        },
        "profile_catalog": {
            "interface": profiles.get("interface"),
            "schema_version": profiles.get("schema_version"),
            "content_id": _sha256_bytes(_canonical_bytes(profiles)),
        },
        "family_routes": {
            "interface": routes.get("interface"),
            "publication_interface": routes.get("publication_interface"),
            "schema_version": routes.get("schema_version"),
            "content_id": _sha256_bytes(_canonical_bytes(routes)),
        },
        "evidence_replay": {
            "interface": replay.interface,
            "schema_version": replay.schema_version,
            "content_id": replay.content_id,
            "content_sha256": replay.content_sha256,
            "acceptance_holds": True,
            "authority_disposition_count": replay.summary.get("authority_disposition_count"),
        },
    }
    return evidence, {"matrix": matrix, "replay": replay}


def _predecessor_binding(
    root: Path, nested: Path, controls: Mapping[str, Any], fixed_receipt: Mapping[str, Any]
) -> dict[str, Any]:
    predecessor = dict(_require_mapping(controls.get("predecessor_config"), "predecessor"))
    _assert_ancestor(
        root, predecessor["predecessor_accelerator_commit"], "Wave-1 accelerator commit"
    )
    _assert_ancestor(nested, predecessor["predecessor_datasets_commit"], "Wave-1 datasets commit")
    release_path = nested / _NESTED_FILES["wave1_release"]
    actual = _sha256_file(release_path)
    if actual != predecessor["predecessor_release_receipt_sha256"]:
        raise ReleaseV2Error("Wave-1 release receipt digest drift")
    identity = _require_mapping(fixed_receipt.get("identity_bindings"), "identity_bindings")
    wave1 = _require_mapping(identity.get("wave1_predecessor"), "wave1_predecessor")
    if not wave1:
        raise ReleaseV2Error("fixed point does not bind canonical Wave-1 anchors")
    return {
        **predecessor,
        "release_receipt_sha256": actual,
        "canonical_anchor_set_sha256": _sha256_bytes(_canonical_bytes(wave1)),
    }


def _receipt_body(root: Path, nested: Path) -> dict[str, Any]:
    controls = _control_bindings(root)
    fixed, fixed_receipt = _fixed_point_binding(root)
    evidence, _live = _semantic_evidence(nested)
    predecessor = _predecessor_binding(root, nested, controls, fixed_receipt)
    nested_identity = fixed["nested_repository"]
    if nested_identity.get("gitlink_matches_nested_head") != "true":
        raise ReleaseV2Error("superproject gitlink must equal nested HEAD")
    authority = {
        "policy": controls["authority_policy"],
        "completion_authority": False,
        "mutation_authority": False,
        "promotion_authority": False,
        "solver_success_is_theorem_authority": False,
        "release_receipt_is_kernel_authority": False,
        "official_kernel_acceptance_required": True,
        "independent_refutation_validation_required": True,
    }
    return {
        "schema": LOGIC_PARSER_RELEASE_SCHEMA,
        "interface": LOGIC_PARSER_RELEASE_INTERFACE,
        "version": RELEASE_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer_id": PRODUCER_ID,
        "binding_mode": "normalized-controls-and-semantic-tree-projection",
        "predecessor": predecessor,
        "controls": controls,
        "source_identity": {
            "nested_repository_path": NESTED_REPOSITORY_PATH,
            **nested_identity,
        },
        "fixed_point": fixed,
        "evidence": evidence,
        "authority": authority,
        "acceptance": {
            "all_nonsealing_tasks_terminal": True,
            "no_derived_open_tasks": True,
            "fixed_point_current": True,
            "two_quiet_epochs": fixed.get("consecutive_empty_scans") == 2,
            "reachable_matrix_hard_zero": True,
            "replay_acceptance_holds": True,
            "predecessor_exact": True,
            "gitlink_matches_nested_head": True,
            "status_transitions_normalized": True,
            "release_outputs_excluded_from_semantic_projection": True,
        },
        "markdown_binding": {
            "schema": "logic-parser-release-markdown/v2",
            "renderer": "release_v2.render_markdown@1",
            "path": DEFAULT_MARKDOWN_RELATIVE_PATH,
            "json_path": DEFAULT_JSON_RELATIVE_PATH,
        },
        "completion_authority": False,
        "mutation_authority": False,
        "theorem_authority": False,
        "kernel_authority": False,
    }


def _with_receipt_id(body: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(body)
    digest = _sha256_bytes(_canonical_bytes(payload))
    payload["receipt_body_sha256"] = digest
    payload["receipt_id"] = digest
    return payload


def render_markdown(receipt: Mapping[str, Any]) -> str:
    """Render the sole canonical human-readable view of a release receipt."""

    receipt_id = _require_digest(receipt.get("receipt_id"), "receipt_id")
    matrix = _require_mapping(
        _require_mapping(receipt.get("evidence"), "evidence").get("reachable_matrix"),
        "reachable_matrix",
    )
    fixed = _require_mapping(receipt.get("fixed_point"), "fixed_point")
    source = _require_mapping(receipt.get("source_identity"), "source_identity")
    predecessor = _require_mapping(receipt.get("predecessor"), "predecessor")
    floors = _require_mapping(matrix.get("hard_zero_floors"), "hard_zero_floors")
    floor_lines = "\n".join(
        f"- `{name}`: `{floors[name]}`" for name in sorted(floors) if name != "schema_version"
    )
    return (
        "# Logic-Family Parser Wave-2 Release\n\n"
        f"- Interface: `{LOGIC_PARSER_RELEASE_INTERFACE}`\n"
        f"- Receipt ID: `{receipt_id}`\n"
        f"- Machine receipt: `{DEFAULT_JSON_RELATIVE_PATH}`\n"
        f"- Wave-1 release: `{predecessor['release_receipt_sha256']}`\n"
        f"- Semantic tree projection: `{source['semantic_tree_projection_sha256']}`\n"
        f"- Fixed point: `{fixed['receipt_body_sha256']}`\n"
        f"- Reachable matrix: `{matrix['content_id']}` ({matrix['cell_count']} cells)\n\n"
        "## Acceptance\n\n"
        "Every task except the sealing card is terminal, no derived task is open, "
        "the two-scan fixed point is current, and all reachable-matrix safety floors "
        "are zero. The LFP2-050 todo-to-completed transition and these two release "
        "files are normalized/excluded from semantic identity.\n\n"
        "## Hard-zero floors\n\n"
        f"{floor_lines}\n\n"
        "## Authority\n\n"
        "This receipt grants no completion, mutation, promotion, solver, theorem, "
        "or kernel authority. Official kernel acceptance and independent refutation "
        "validation remain required by policy.\n"
    )


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def materialize_release_evidence(
    *,
    repo_root: Path | str,
    json_path: Path | str = DEFAULT_JSON_RELATIVE_PATH,
    markdown_path: Path | str = DEFAULT_MARKDOWN_RELATIVE_PATH,
) -> dict[str, Any]:
    """Materialize canonical JSON/Markdown and independently validate both."""

    root, nested = _resolve_roots(repo_root)
    json_target = _safe_nested_output(nested, json_path, DEFAULT_JSON_RELATIVE_PATH)
    markdown_target = _safe_nested_output(nested, markdown_path, DEFAULT_MARKDOWN_RELATIVE_PATH)
    receipt = _with_receipt_id(_receipt_body(root, nested))
    _atomic_write(json_target, _pretty_bytes(receipt))
    _atomic_write(markdown_target, render_markdown(receipt).encode("utf-8"))
    return validate_release_artifacts(markdown_path, json_path, repo_root=root)


def validate_release_artifacts(
    markdown_path: Path | str = DEFAULT_MARKDOWN_RELATIVE_PATH,
    json_path: Path | str = DEFAULT_JSON_RELATIVE_PATH,
    *,
    repo_root: Path | str,
) -> dict[str, Any]:
    """Fail closed unless both artifacts are canonical, current, and identical."""

    root, nested = _resolve_roots(repo_root)
    json_target = _safe_nested_output(nested, json_path, DEFAULT_JSON_RELATIVE_PATH)
    markdown_target = _safe_nested_output(nested, markdown_path, DEFAULT_MARKDOWN_RELATIVE_PATH)
    try:
        raw_json = json_target.read_bytes()
        raw_markdown = markdown_target.read_bytes()
    except OSError as exc:
        raise ReleaseV2Error("release JSON/Markdown artifact is unreadable") from exc
    parsed = _parse_json_bytes(raw_json, "release receipt")
    if raw_json != _pretty_bytes(parsed):
        raise ReleaseV2Error("release receipt is not strict canonical JSON")
    receipt_id = _require_digest(parsed.get("receipt_id"), "receipt_id")
    body_digest = _require_digest(parsed.get("receipt_body_sha256"), "receipt_body_sha256")
    body = {
        key: value
        for key, value in parsed.items()
        if key not in {"receipt_id", "receipt_body_sha256"}
    }
    expected_digest = _sha256_bytes(_canonical_bytes(body))
    if receipt_id != expected_digest or body_digest != expected_digest:
        raise ReleaseV2Error("release receipt content identity mismatch")
    expected = _with_receipt_id(_receipt_body(root, nested))
    if _canonical_bytes(parsed) != _canonical_bytes(expected):
        raise ReleaseStaleError("release receipt is stale or its evidence was altered")
    expected_markdown = render_markdown(parsed).encode("utf-8")
    if raw_markdown != expected_markdown:
        raise ReleaseV2Error("release Markdown binding differs from the receipt")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("materialize", "validate"):
        child = subparsers.add_parser(command)
        child.add_argument("--repo-root", required=True)
        child.add_argument("--json-path", default=DEFAULT_JSON_RELATIVE_PATH)
        child.add_argument("--markdown-path", default=DEFAULT_MARKDOWN_RELATIVE_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "materialize":
            receipt = materialize_release_evidence(
                repo_root=args.repo_root,
                json_path=args.json_path,
                markdown_path=args.markdown_path,
            )
        else:
            receipt = validate_release_artifacts(
                args.markdown_path,
                args.json_path,
                repo_root=args.repo_root,
            )
    except ReleaseV2Error as exc:
        print(f"release_v2: {exc}", file=sys.stderr)
        return 1
    print(receipt["receipt_id"])
    return 0


__all__ = [
    "LOGIC_PARSER_RELEASE_INTERFACE",
    "LOGIC_PARSER_RELEASE_SCHEMA",
    "ReleaseOpenWorkError",
    "ReleaseStaleError",
    "ReleaseV2Error",
    "main",
    "materialize_release_evidence",
    "render_markdown",
    "validate_release_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())
