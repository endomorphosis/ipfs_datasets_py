"""Control-plane tests for the deliberately unresolved DSS-000 seal."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
SEAL_PATH = REPO_ROOT / "config/semantic_state_contract_dependencies.seal.json"
VALIDATOR_PATH = REPO_ROOT / "scripts/validate_semantic_state_contract_dependencies.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("dss_dependency_seal_validator", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_seal_is_intentionally_unresolved_and_fails_closed(capsys) -> None:
    validator = _load_validator()
    seal = validator.load_seal(SEAL_PATH)

    assert seal["status"] == "unresolved"
    assert seal["authorities"][1]["commit"] == "UNRESOLVED_FINAL_ISI_COMMIT"
    assert seal["authorities"][2]["commit"] == "UNRESOLVED_FINAL_KSR_COMMIT"

    errors = validator.validate_seal(SEAL_PATH)
    assert "seal: status must be 'sealed'" in errors
    assert "seal: unresolved placeholder present" in errors
    assert any(error.startswith("checkout bindings missing:") for error in errors)

    assert validator.main(["--check", str(SEAL_PATH)]) == 1
    assert "ERROR: seal: unresolved placeholder present" in capsys.readouterr().err


def test_resolved_control_authority_fingerprints_are_self_consistent() -> None:
    validator = _load_validator()
    seal = validator.load_seal(SEAL_PATH)
    authorities = {item["role"]: item for item in seal["authorities"]}

    for role in ("accelerate_harness", "mcp_plus_plus"):
        authority = authorities[role]
        assert authority["interface_fingerprint"] == validator.manifest_fingerprint(
            authority["required_blobs"]
        )


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
