"""Focused contract tests for deterministic Wave-2 release evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.conformance import release_v2


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _body(state: dict[str, str]) -> dict[str, object]:
    floors = {
        "all_clear": True,
        "schema_version": "reachable-conformance-hard-zero-floors/v2",
        "unexplained_reachable_gap": 0,
        "silent_node_drop": 0,
        "silent_node_loss": 0,
        "raw_ingress": 0,
        "family_drift": 0,
        "false_capability": 0,
        "authority_escalation": 0,
        "kernel_trust_escape": 0,
    }
    return {
        "schema": release_v2.LOGIC_PARSER_RELEASE_SCHEMA,
        "interface": release_v2.LOGIC_PARSER_RELEASE_INTERFACE,
        "version": release_v2.RELEASE_VERSION,
        "task_id": release_v2.TASK_ID,
        "goal_id": release_v2.GOAL_ID,
        "program_id": release_v2.PROGRAM_ID,
        "producer_id": release_v2.PRODUCER_ID,
        "binding_mode": "normalized-controls-and-semantic-tree-projection",
        "predecessor": {"release_receipt_sha256": _digest("1")},
        "controls": {"identity": state["identity"]},
        "source_identity": {
            "semantic_tree_projection_sha256": _digest("2"),
        },
        "fixed_point": {"receipt_body_sha256": _digest("3")},
        "evidence": {
            "reachable_matrix": {
                "content_id": _digest("4"),
                "cell_count": 228,
                "hard_zero_floors": floors,
            }
        },
        "authority": {
            "completion_authority": False,
            "mutation_authority": False,
        },
        "acceptance": {"fixed_point_current": True},
        "markdown_binding": {
            "schema": "logic-parser-release-markdown/v2",
            "renderer": "release_v2.render_markdown@1",
            "path": release_v2.DEFAULT_MARKDOWN_RELATIVE_PATH,
            "json_path": release_v2.DEFAULT_JSON_RELATIVE_PATH,
        },
        "completion_authority": False,
        "mutation_authority": False,
        "theorem_authority": False,
        "kernel_authority": False,
    }


@pytest.fixture
def release_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "super"
    nested = root / "ipfs_datasets_py"
    (nested / "ipfs_datasets_py/logic/conformance").mkdir(parents=True)
    state = {"identity": _digest("a")}
    monkeypatch.setattr(release_v2, "_resolve_roots", lambda _root: (root, nested))
    monkeypatch.setattr(release_v2, "_receipt_body", lambda _root, _nested: _body(state))
    return root, nested, state


def test_materialization_is_canonical_and_idempotent(release_tree) -> None:
    root, nested, _state = release_tree
    first = release_v2.materialize_release_evidence(repo_root=root)
    json_path = nested / release_v2.DEFAULT_JSON_RELATIVE_PATH
    markdown_path = nested / release_v2.DEFAULT_MARKDOWN_RELATIVE_PATH
    first_bytes = (json_path.read_bytes(), markdown_path.read_bytes())

    second = release_v2.materialize_release_evidence(repo_root=root)

    assert second == first
    assert (json_path.read_bytes(), markdown_path.read_bytes()) == first_bytes
    assert first["receipt_id"] == first["receipt_body_sha256"]
    assert first["completion_authority"] is False
    assert json_path.read_bytes() == release_v2._pretty_bytes(first)


def test_json_tampering_is_rejected(release_tree) -> None:
    root, nested, _state = release_tree
    release_v2.materialize_release_evidence(repo_root=root)
    path = nested / release_v2.DEFAULT_JSON_RELATIVE_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["completion_authority"] = True
    path.write_bytes(release_v2._pretty_bytes(payload))

    with pytest.raises(release_v2.ReleaseV2Error, match="content identity"):
        release_v2.validate_release_artifacts(repo_root=root)


def test_type_changed_payload_with_recomputed_id_is_still_rejected(release_tree) -> None:
    root, nested, _state = release_tree
    release_v2.materialize_release_evidence(repo_root=root)
    path = nested / release_v2.DEFAULT_JSON_RELATIVE_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["completion_authority"] = 0
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"receipt_id", "receipt_body_sha256"}
    }
    digest = release_v2._sha256_bytes(release_v2._canonical_bytes(body))
    payload["receipt_id"] = digest
    payload["receipt_body_sha256"] = digest
    path.write_bytes(release_v2._pretty_bytes(payload))

    with pytest.raises(release_v2.ReleaseStaleError, match="stale"):
        release_v2.validate_release_artifacts(repo_root=root)


def test_current_identity_staleness_is_rejected(release_tree) -> None:
    root, _nested, state = release_tree
    release_v2.materialize_release_evidence(repo_root=root)
    state["identity"] = _digest("b")

    with pytest.raises(release_v2.ReleaseStaleError, match="stale"):
        release_v2.validate_release_artifacts(repo_root=root)


def test_markdown_mismatch_is_rejected(release_tree) -> None:
    root, nested, _state = release_tree
    release_v2.materialize_release_evidence(repo_root=root)
    markdown = nested / release_v2.DEFAULT_MARKDOWN_RELATIVE_PATH
    markdown.write_text(markdown.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")

    with pytest.raises(release_v2.ReleaseV2Error, match="Markdown binding"):
        release_v2.validate_release_artifacts(repo_root=root)


def test_output_or_parent_symlink_is_rejected(release_tree, tmp_path: Path) -> None:
    root, nested, _state = release_tree
    outside = tmp_path / "outside"
    outside.mkdir()
    (nested / "data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(release_v2.ReleaseV2Error, match="traverses a symlink"):
        release_v2.materialize_release_evidence(repo_root=root)

    (nested / "data").unlink()
    output = nested / release_v2.DEFAULT_JSON_RELATIVE_PATH
    output.parent.mkdir(parents=True)
    decoy = nested / "decoy.json"
    decoy.write_text("{}\n", encoding="utf-8")
    output.symlink_to(decoy)
    with pytest.raises(release_v2.ReleaseV2Error, match="traverses a symlink"):
        release_v2.materialize_release_evidence(repo_root=root)


def test_exact_absolute_artifact_paths_are_supported(release_tree) -> None:
    root, nested, _state = release_tree
    release_v2.materialize_release_evidence(repo_root=root)
    receipt = release_v2.validate_release_artifacts(
        nested / release_v2.DEFAULT_MARKDOWN_RELATIVE_PATH,
        nested / release_v2.DEFAULT_JSON_RELATIVE_PATH,
        repo_root=root,
    )
    assert receipt["interface"] == release_v2.LOGIC_PARSER_RELEASE_INTERFACE


def _board(*, open_task: str | None = None, sealing_status: str = "todo") -> str:
    cards = []
    for index in range(51):
        task_id = f"LFP2-{index:03d}"
        status = sealing_status if task_id == "LFP2-050" else "completed"
        if task_id == open_task:
            status = "todo"
        cards.append(f"## {task_id} task {index}\n\n- Status: {status}\n")
    return "\n".join(cards)


def test_open_seed_or_derived_task_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    board_path = root / release_v2.TODO_RELATIVE_PATH
    board_path.parent.mkdir(parents=True)
    board_path.write_text(_board(open_task="LFP2-010"), encoding="utf-8")

    with pytest.raises(release_v2.ReleaseOpenWorkError, match="LFP2-010"):
        release_v2._task_board_binding(root)

    board_path.write_text(
        _board() + "\n## LFP2-051 derived\n\n- Status: todo\n",
        encoding="utf-8",
    )
    with pytest.raises(release_v2.ReleaseOpenWorkError, match="LFP2-051"):
        release_v2._task_board_binding(root)

    # The sealing transition itself is normalized and accepted in both states.
    board_path.write_text(_board(sealing_status="todo"), encoding="utf-8")
    todo = release_v2._task_board_binding(root)
    board_path.write_text(_board(sealing_status="completed"), encoding="utf-8")
    completed = release_v2._task_board_binding(root)
    assert todo == completed


@dataclass
class _FakeFloors:
    def to_dict(self) -> dict[str, object]:
        return {
            "all_clear": False,
            "schema_version": "reachable-conformance-hard-zero-floors/v2",
            "unexplained_reachable_gap": 1,
            "silent_node_drop": 0,
            "silent_node_loss": 0,
            "raw_ingress": 0,
            "family_drift": 0,
            "false_capability": 0,
            "authority_escalation": 0,
            "kernel_trust_escape": 0,
        }


@dataclass
class _FakeMatrix:
    hard_zero_floors: _FakeFloors = field(default_factory=_FakeFloors)
    cells: tuple[object, ...] = ()

    def acceptance_holds(self) -> bool:
        return True


def test_nonzero_reachable_matrix_floor_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ipfs_datasets_py.logic.conformance import matrix_v2

    monkeypatch.setattr(matrix_v2, "ensure_seal_matches_live", lambda _path: _FakeMatrix())
    with pytest.raises(release_v2.ReleaseV2Error, match="unexplained_reachable_gap"):
        release_v2._semantic_evidence(tmp_path)


def test_cli_accepts_exact_supervisor_command_shape() -> None:
    args = release_v2._parser().parse_args(
        [
            "materialize",
            "--repo-root",
            "..",
            "--json-path",
            release_v2.DEFAULT_JSON_RELATIVE_PATH,
            "--markdown-path",
            release_v2.DEFAULT_MARKDOWN_RELATIVE_PATH,
        ]
    )
    assert args.command == "materialize"
    assert args.repo_root == ".."


def test_manifest_binding_is_workspace_independent(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "interface": "ScheduledProviderTier@1",
                "schema_version": "scheduled-provider-tiers/v1",
                "task_id": "LFP2-045",
                "providers": [{"provider_id": "z3"}],
            }
        ),
        encoding="utf-8",
    )
    relative = "tests/integration/logic_providers/manifest.json"
    binding = release_v2._file_manifest_binding(
        manifest,
        relative,
        "provider manifest",
        "ScheduledProviderTier@1",
        "scheduled-provider-tiers/v1",
    )
    assert binding["path"] == relative
    assert str(tmp_path) not in json.dumps(binding)
