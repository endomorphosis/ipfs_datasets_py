"""Control-plane tests for the sealed DSS-000 dependency authority."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
SEAL_PATH = REPO_ROOT / "config/semantic_state_contract_dependencies.seal.json"
VALIDATOR_PATH = REPO_ROOT / "scripts/validate_semantic_state_contract_dependencies.py"
PLAN_PATH = REPO_ROOT / "docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md"
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _load_validator():
    spec = importlib.util.spec_from_file_location("dss_dependency_seal_validator", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_seal_is_sealed_with_final_isi_and_kit_pins() -> None:
    validator = _load_validator()
    seal = validator.load_seal(SEAL_PATH)
    authorities = {item["role"]: item for item in seal["authorities"]}

    assert seal["status"] == "sealed"
    assert HEX40.fullmatch(authorities["incremental_semantic_index"]["commit"])
    assert authorities["incremental_semantic_index"]["commit"] == (
        "b572255d5f8f4f4f8136df43f58dae44f8e1b941"
    )
    assert authorities["kit_state_roots"]["commit"] == (
        "05ba9375923cd5fb52e2c9c18b98b530d57d077f"
    )
    assert not any(
        "UNRESOLVED" in json.dumps(item) for item in seal["authorities"]
    )

    # Portable document contract is closed; checkout bindings remain required
    # for full operator validation via --repo / --run-tests.
    errors = validator.validate_document(seal)
    assert errors == []


def test_resolved_control_authority_fingerprints_bind_complete_contracts() -> None:
    validator = _load_validator()
    seal = validator.load_seal(SEAL_PATH)
    authorities = {item["role"]: item for item in seal["authorities"]}

    for role in (
        "accelerate_harness",
        "incremental_semantic_index",
        "kit_state_roots",
        "mcp_plus_plus",
    ):
        authority = authorities[role]
        assert authority["interface_fingerprint"] == validator.authority_fingerprint(authority)


def test_document_contract_rejects_unknown_fields_even_while_unresolved() -> None:
    validator = _load_validator()
    seal = copy.deepcopy(validator.load_seal(SEAL_PATH))
    seal["unexpected_relaxation"] = True

    errors = validator.validate_document(seal)

    assert "seal: unknown fields: unexpected_relaxation" in errors


def test_loader_rejects_duplicate_json_members(tmp_path: Path) -> None:
    validator = _load_validator()
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")

    try:
        validator.load_seal(duplicate)
    except validator.DuplicateKeyError as exc:
        assert "duplicate JSON member 'schema'" in str(exc)
    else:  # pragma: no cover - documents the fail-closed invariant
        raise AssertionError("duplicate JSON member was accepted")


def test_wire_boundary_is_exactly_generic_profiles_a_b_f() -> None:
    seal = json.loads(SEAL_PATH.read_text(encoding="utf-8"))

    assert seal["wire_contract"] == {
        "authority_role": "mcp_plus_plus",
        "profiles": ["A", "B", "F"],
        "payload_role": "datasets_application_payload_only",
        "generic_envelope_types_owned_externally": True,
        "local_envelope_hasher_forbidden": True,
    }


def test_exact_root_payload_uses_explicit_nullable_oid_field_names() -> None:
    plan = PLAN_PATH.read_text(encoding="utf-8")

    assert '"git_commit_oid_or_null"' in plan
    assert '"git_tree_oid_or_null"' in plan
    assert '"git_commit_oid":' not in plan
    assert '"git_tree_oid":' not in plan


def test_role_manifest_and_test_commands_cannot_be_replaced_with_smoke_noops() -> None:
    validator = _load_validator()
    seal = copy.deepcopy(validator.load_seal(SEAL_PATH))
    authority = seal["authorities"][0]
    authority["required_blobs"] = [{"path": "README.md", "oid": "a" * 40}]
    authority["required_test_commands"] = [["python3.12", "-c", "pass"]]
    authority["interface_fingerprint"] = validator.authority_fingerprint(authority)

    errors = validator.validate_document(seal)

    assert any("required_blobs paths do not equal" in error for error in errors)
    assert any("required_test_commands do not equal" in error for error in errors)


def test_interface_contract_and_complete_fingerprint_fail_closed() -> None:
    validator = _load_validator()
    seal = copy.deepcopy(validator.load_seal(SEAL_PATH))
    authority = seal["authorities"][0]
    authority["interface_contract"]["public_api"] = ["SyntheticBypass()"]

    errors = validator.validate_document(seal)

    assert any("interface_contract must equal" in error for error in errors)
    assert any("interface_fingerprint does not bind" in error for error in errors)


def test_checkout_binding_must_name_canonical_worktree_root(tmp_path: Path) -> None:
    validator = _load_validator()
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "seal@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Seal Test"], check=True)
    (repository / "nested").mkdir()
    source = repository / "README.md"
    source.write_text("sealed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-q", "-m", "sealed"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "remote",
            "add",
            "origin",
            "https://github.com/endomorphosis/ipfs_accelerate_py",
        ],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD^{tree}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    oid = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD:README.md"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    authority = {
        "role": "accelerate_harness",
        "origin": "https://github.com/endomorphosis/ipfs_accelerate_py",
        "commit": commit,
        "tree": tree,
        "required_blobs": [{"path": "README.md", "oid": oid}],
    }

    assert validator.validate_checkout(authority, repository) == []
    assert validator.validate_checkout(authority, repository / "nested") == [
        "checkout[accelerate_harness]: path must be the canonical Git worktree root"
    ]


def test_ast_wire_boundary_detects_alias_import_and_reversed_hasher_name(tmp_path: Path) -> None:
    validator = _load_validator()
    package = tmp_path / "ipfs_datasets_py/logic/software_contracts/semantic_state"
    package.mkdir(parents=True)
    (package / "bad.py").write_text(
        "from vendor import ExecutionEnvelope\n"
        "ExecutionReceipt = dict\n"
        "def cid_for_envelope(value):\n"
        "    return value\n",
        encoding="utf-8",
    )

    violations = validator._forbidden_local_wire_authority(tmp_path)

    assert len(violations) == 3
    assert any("forbidden MCP++ import" in item for item in violations)
    assert any("forbidden local generic type alias" in item for item in violations)
    assert any("forbidden local generic authority" in item for item in violations)


def test_sealed_validation_cannot_skip_required_test_execution(tmp_path: Path) -> None:
    validator = _load_validator()
    seal = copy.deepcopy(validator.load_seal(SEAL_PATH))
    seal["status"] = "sealed"
    path = tmp_path / "sealed.json"
    path.write_text(json.dumps(seal), encoding="utf-8")

    errors = validator.validate_seal(path, run_tests=False)

    assert "seal: sealed validation requires --run-tests" in errors


def test_required_test_timeout_is_bounded(tmp_path: Path) -> None:
    validator = _load_validator()
    authority = {
        "role": "accelerate_harness",
        "test_timeout_seconds": 1,
        "required_test_commands": [
            ["python3.12", "-c", "import time; time.sleep(5)"]
        ],
    }

    errors = validator._run_required_tests(authority, tmp_path)

    assert len(errors) == 1
    assert "timed out after 1s" in errors[0]
