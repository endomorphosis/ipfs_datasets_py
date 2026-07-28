"""WALPROC-G020 migration baseline contract tests.

Freezes World ID golden vectors, route/import/snapshot shapes, Xaman assurance
links, and the security baseline that marks known gaps as failures to fix
(not compatibility guarantees).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
WORLDCOIN_FIXTURES = REPO_ROOT / "ipfs_datasets_py" / "tests" / "fixtures" / "wallets" / "worldcoin"
XAMAN_FIXTURES = REPO_ROOT / "ipfs_datasets_py" / "tests" / "fixtures" / "wallets" / "xaman"
SECURITY_BASELINE = REPO_ROOT / "data" / "wallet_processor_migration" / "audit" / "security-baseline.json"

REQUIRED_WORLDCOIN_FILES = {
    "manifest.json",
    "README.md",
    "golden_vectors.json",
    "idkit_v3_legacy.json",
    "idkit_v4_uniqueness.json",
    "idkit_v4_session.json",
    "verify_success.json",
    "verify_failure.json",
    "redaction_cases.json",
    "route_shapes.json",
    "import_identities.json",
    "snapshot_shapes.json",
    "public_projections.json",
}

REQUIRED_XAMAN_FILES = {
    "manifest.json",
    "README.md",
    "assurance_links.json",
    "runtime_projection_boundary.json",
    "sample_ledger_records.json",
}

REQUIRED_SECURITY_ACCEPTANCE_TERMS = [
    "legacy-default-on",
    "unenforced user presence/signal/provider context",
    "unissued challenge acceptance",
    "optional status authentication",
    "raw/process-local nullifier state",
    "v3-as-v4 receipt labeling",
    "stale proof receipts after revoke/expiry",
    "unsafe configurable endpoints",
    "plaintext snapshots",
]

GOLDEN_ACCEPTANCE_KEYS = [
    "world_id_signing",
    "hash_to_field",
    "idkit_v3_legacy",
    "idkit_v4_uniqueness",
    "idkit_v4_session",
    "verify_success",
    "verify_failure",
    "redaction",
    "old_snapshot_import",
    "route_shapes",
    "old_import_identities",
]


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _repo_on_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


@pytest.fixture(scope="module")
def worldcoin_manifest() -> dict[str, Any]:
    return _load_json(WORLDCOIN_FIXTURES / "manifest.json")


@pytest.fixture(scope="module")
def golden_vectors() -> dict[str, Any]:
    return _load_json(WORLDCOIN_FIXTURES / "golden_vectors.json")


@pytest.fixture(scope="module")
def security_baseline() -> dict[str, Any]:
    return _load_json(SECURITY_BASELINE)


@pytest.fixture(scope="module")
def xaman_manifest() -> dict[str, Any]:
    return _load_json(XAMAN_FIXTURES / "manifest.json")


# ---------------------------------------------------------------------------
# Fixture presence and manifests
# ---------------------------------------------------------------------------


def test_worldcoin_fixture_directory_contains_required_files() -> None:
    assert WORLDCOIN_FIXTURES.is_dir(), f"missing worldcoin fixtures dir: {WORLDCOIN_FIXTURES}"
    present = {path.name for path in WORLDCOIN_FIXTURES.iterdir() if path.is_file()}
    missing = REQUIRED_WORLDCOIN_FILES - present
    assert not missing, f"worldcoin fixtures missing files: {sorted(missing)}"


def test_xaman_fixture_directory_contains_required_files() -> None:
    assert XAMAN_FIXTURES.is_dir(), f"missing xaman fixtures dir: {XAMAN_FIXTURES}"
    present = {path.name for path in XAMAN_FIXTURES.iterdir() if path.is_file()}
    missing = REQUIRED_XAMAN_FILES - present
    assert not missing, f"xaman fixtures missing files: {sorted(missing)}"


def test_security_baseline_file_exists() -> None:
    assert SECURITY_BASELINE.is_file(), f"missing security baseline: {SECURITY_BASELINE}"


def test_worldcoin_manifest_covers_acceptance_keys(worldcoin_manifest: dict[str, Any]) -> None:
    assert worldcoin_manifest["goal_id"] == "WALPROC-G020"
    assert worldcoin_manifest["task_id"] == "WALPROC-003"
    assert worldcoin_manifest["classification"]["security_vulnerabilities_frozen_as_ok"] is False
    keys = set(worldcoin_manifest["acceptance_keys"])
    missing = set(GOLDEN_ACCEPTANCE_KEYS) - keys
    assert not missing, f"manifest missing acceptance keys: {sorted(missing)}"
    for relative in worldcoin_manifest["files"]:
        assert (WORLDCOIN_FIXTURES / relative).is_file(), relative


def test_xaman_manifest_declares_formal_not_runtime(xaman_manifest: dict[str, Any]) -> None:
    assert xaman_manifest["goal_id"] == "WALPROC-G020"
    classification = xaman_manifest["classification"]
    assert classification["formal_assurance_is_not_runtime_correctness"] is True
    assert classification["offline_default"] is True
    for relative in xaman_manifest["files"]:
        assert (XAMAN_FIXTURES / relative).is_file(), relative


# ---------------------------------------------------------------------------
# Golden vectors (structural freeze + live recompute when available)
# ---------------------------------------------------------------------------


def test_golden_hash_to_field_and_signing_structure(golden_vectors: dict[str, Any]) -> None:
    empty = golden_vectors["hash_to_field"]["empty_bytes"]
    assert empty["field_hex"].startswith("0x")
    assert empty["leading_byte_is_zero"] is True
    assert len(empty["field_hex"]) == 66

    action = golden_vectors["hash_to_field"]["test_action"]
    assert action["input_utf8"] == "test-action"
    assert action["field_hex"].startswith("0x")

    signing = golden_vectors["rp_signing"]
    without = signing["without_action"]
    assert without["message_length_bytes"] == 49
    assert without["nonce"] == "0x008ae1aa597fa146ebd3aa2ceddf360668dea5e526567e92b0321816a4e895bd"
    assert without["protocol_dict"]["sig"] == without["signature"]
    assert set(without["protocol_dict"]) == {"sig", "nonce", "created_at", "expires_at"}

    with_action = signing["with_action_test_action"]
    assert with_action["message_length_bytes"] == 81
    assert with_action["action"] == "test-action"

    constants = golden_vectors["default_constants"]
    assert constants["DEFAULT_WORLD_ID_ACTION"] == "wallet-attach-world-id-v1"
    assert constants["DEFAULT_WORLD_ID_VERIFY_BASE_URL"] == "https://developer.world.org"
    assert set(constants["SUPPORTED_WORLD_ID_ENVIRONMENTS"]) == {"staging", "production"}


def test_golden_vectors_match_live_world_id_implementation(golden_vectors: dict[str, Any]) -> None:
    """Recompute official-style vectors against pre-move module when importable."""

    _repo_on_path()
    try:
        from wallet_interface.world_id import (  # type: ignore
            DEFAULT_WORLD_ID_ACTION,
            DEFAULT_WORLD_ID_VERIFY_BASE_URL,
            compute_rp_signature_message,
            hash_to_field,
            hash_to_field_hex,
            sign_world_id_request,
        )
    except Exception as exc:  # pragma: no cover - environment without wallet_interface
        pytest.skip(f"wallet_interface.world_id unavailable for live recompute: {exc}")

    empty = golden_vectors["hash_to_field"]["empty_bytes"]
    assert hash_to_field_hex(b"") == empty["field_hex"]
    assert hash_to_field(b"")[0] == 0

    action_vec = golden_vectors["hash_to_field"]["test_action"]
    assert hash_to_field_hex(action_vec["input_utf8"]) == action_vec["field_hex"]

    signing = golden_vectors["rp_signing"]
    signature = sign_world_id_request(
        signing["signing_key_hex"],
        ttl_seconds=signing["ttl_seconds"],
        random_bytes=bytes.fromhex(signing["random_bytes_hex"]),
        created_at=signing["created_at"],
    )
    without = signing["without_action"]
    assert signature.nonce == without["nonce"]
    assert signature.signature == without["signature"]
    assert signature.to_protocol_dict() == without["protocol_dict"]

    message = compute_rp_signature_message(
        without["nonce"],
        signing["created_at"],
        signing["expires_at"],
    )
    assert message.hex() == without["message_hex"]
    assert len(message) == without["message_length_bytes"]

    with_action = signing["with_action_test_action"]
    action_signature = sign_world_id_request(
        signing["signing_key_hex"],
        ttl_seconds=signing["ttl_seconds"],
        random_bytes=bytes.fromhex(signing["random_bytes_hex"]),
        created_at=signing["created_at"],
        action=with_action["action"],
    )
    assert action_signature.signature == with_action["signature"]
    action_message = compute_rp_signature_message(
        without["nonce"],
        signing["created_at"],
        signing["expires_at"],
        with_action["action"],
    )
    assert action_message.hex() == with_action["message_hex"]
    assert len(action_message) == with_action["message_length_bytes"]

    constants = golden_vectors["default_constants"]
    assert DEFAULT_WORLD_ID_ACTION == constants["DEFAULT_WORLD_ID_ACTION"]
    assert DEFAULT_WORLD_ID_VERIFY_BASE_URL == constants["DEFAULT_WORLD_ID_VERIFY_BASE_URL"]


@pytest.mark.parametrize(
    "fixture_name,proof_type",
    [
        ("idkit_v3_legacy.json", "legacy"),
        ("idkit_v4_uniqueness.json", "uniqueness"),
        ("idkit_v4_session.json", "session"),
    ],
)
def test_idkit_fixture_shapes_and_live_normalization(fixture_name: str, proof_type: str) -> None:
    fixture = _load_json(WORLDCOIN_FIXTURES / fixture_name)
    assert fixture["proof_type"] == proof_type
    assert "payload" in fixture
    assert "expected_normalization" in fixture
    expected = fixture["expected_normalization"]
    assert expected["proof_type"] == proof_type

    _repo_on_path()
    try:
        from wallet_interface.world_id import normalize_idkit_response  # type: ignore
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"wallet_interface.world_id unavailable: {exc}")

    normalized = normalize_idkit_response(fixture["payload"])
    assert normalized.protocol_version == expected["protocol_version"]
    assert normalized.proof_type == expected["proof_type"]
    assert normalized.action == expected.get("action", normalized.action)
    assert list(normalized.credential_identifiers) == list(expected["credential_identifiers"])
    if "nullifiers" in expected:
        assert list(normalized.nullifiers) == list(expected["nullifiers"])
    if "session_id" in expected:
        assert normalized.session_id == expected["session_id"]
    if "session_actions" in expected:
        assert list(normalized.session_actions) == list(expected["session_actions"])
    if "verification_timestamps" in expected:
        assert list(normalized.verification_timestamps) == list(expected["verification_timestamps"])

    public_json = json.dumps(normalized.public_dict(), sort_keys=True)
    for token in fixture.get("sensitive_tokens_must_not_appear_in_public_dict", []):
        assert token not in public_json
    for token in fixture.get("sensitive_tokens_must_not_appear_in_repr_or_public_dict", []):
        assert token not in public_json
        assert token not in repr(normalized)


def test_verify_success_and_failure_fixtures() -> None:
    success = _load_json(WORLDCOIN_FIXTURES / "verify_success.json")
    failure = _load_json(WORLDCOIN_FIXTURES / "verify_failure.json")

    assert success["request"]["method"] == "POST"
    assert success["request"]["body_is_idkit_payload_as_is"] is True
    assert "{verify_base_url}/api/v4/verify/{rp_id}" == success["request"]["url_template"]
    assert success["expected_normalization"]["success"] is True
    assert failure["expected_normalization"]["success"] is False
    assert failure["application_behavior"]["register_world_id_verification_must_raise"] is True

    _repo_on_path()
    try:
        from wallet_interface.world_id import (  # type: ignore
            normalize_world_id_verification_response,
        )
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"wallet_interface.world_id unavailable: {exc}")

    ok = normalize_world_id_verification_response(success["raw_response"])
    assert ok.success is True
    assert ok.nullifier == success["expected_normalization"]["nullifier"]
    assert ok.action == success["expected_normalization"]["action"]
    assert len(ok.successful_results) == success["expected_normalization"]["successful_results_count"]

    bad = normalize_world_id_verification_response(failure["raw_response"])
    assert bad.success is False
    assert bad.message == failure["expected_normalization"]["message"]
    assert len(bad.successful_results) == 0


def test_redaction_fixture_matches_live_redactor() -> None:
    cases = _load_json(WORLDCOIN_FIXTURES / "redaction_cases.json")
    payload = _load_json(WORLDCOIN_FIXTURES / "idkit_v3_legacy.json")["payload"]

    _repo_on_path()
    try:
        from wallet_interface.world_id import redact_world_id_payload  # type: ignore
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"wallet_interface.world_id unavailable: {exc}")

    redacted = redact_world_id_payload(payload)
    rendered = json.dumps(redacted, sort_keys=True)
    case = cases["cases"][0]
    for token in case["must_not_appear_in_redacted_json"]:
        assert token not in rendered
    assert case["expected_redacted_responses_marker"] in rendered


def test_route_shapes_cover_world_id_surface() -> None:
    routes = _load_json(WORLDCOIN_FIXTURES / "route_shapes.json")
    paths = {item["path"] for item in routes["routes"]}
    required_paths = {
        "/wallets/{wallet_id}/world-id/config",
        "/wallets/{wallet_id}/world-id/status",
        "/wallets/{wallet_id}/world-id/rp-signature",
        "/wallets/{wallet_id}/world-id/provider-staff/rp-signature",
        "/wallets/{wallet_id}/world-id/verifications",
        "/wallets/{wallet_id}/world-id/bindings/{binding_id}/revoke",
    }
    assert required_paths <= paths
    status_route = next(item for item in routes["routes"] if item["path"].endswith("/status"))
    assert status_route["query_params"]["actor_did"]["required"] is False
    assert "OPTIONAL authentication" in status_route["query_params"]["actor_did"]["notes"]


def test_import_identities_freeze_public_api() -> None:
    identities = _load_json(WORLDCOIN_FIXTURES / "import_identities.json")
    exports = set(identities["public_exports"])
    for symbol in identities["ast_query_symbols"]:
        if symbol == "get_world_id_status":
            assert symbol in identities["application_orchestration_exports_not_in_world_id_module"]
            continue
        assert symbol in exports, f"AST query symbol missing from public exports: {symbol}"

    _repo_on_path()
    try:
        import wallet_interface.world_id as world_id  # type: ignore
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"wallet_interface.world_id unavailable: {exc}")

    for name in identities["public_exports"]:
        assert hasattr(world_id, name), f"missing import identity: {name}"


def test_snapshot_shapes_support_old_import_without_raw_nullifier() -> None:
    snapshots = _load_json(WORLDCOIN_FIXTURES / "snapshot_shapes.json")
    rules = snapshots["old_snapshot_import_rules"]
    assert rules["wallets_without_world_id_fields_must_load"] is True
    assert rules["raw_nullifier_must_not_appear_in_public_binding_dict"] is True
    assert rules["nullifier_ref_prefix"] == "worldid-nullifier-ref:v1:"

    example = snapshots["legacy_snapshot_example"]
    assert "world_id_bindings" in example
    binding = example["world_id_bindings"][0]
    for field in snapshots["world_id_binding_public_fields"]:
        assert field in binding, f"legacy snapshot missing field: {field}"
    assert "raw_nullifier" not in binding
    assert binding["nullifier_ref"].startswith(rules["nullifier_ref_prefix"])

    labels = snapshots["proof_receipt_labels"]
    assert labels["current_hardcoded_proof_system"] == "world_id_idkit_v4"
    assert "failure" in labels["notes"].lower() or "not a frozen" in labels["notes"].lower()


def test_public_projections_forbid_secret_material() -> None:
    projections = _load_json(WORLDCOIN_FIXTURES / "public_projections.json")
    config_proj = projections["projections"]["WorldIdConfig.public_dict"]
    assert "enabled" in config_proj["allowed_keys"]
    assert any("signing_key" in item for item in config_proj["forbidden_substrings"])
    export = projections["projections"]["export_proof_receipt"]
    assert "raw_nullifier" in export["private_keys_forbidden_in_public_export"]
    assert "nullifier" in export["private_keys_forbidden_in_public_export"]


# ---------------------------------------------------------------------------
# Xaman assurance boundary
# ---------------------------------------------------------------------------


def test_xaman_assurance_links_and_boundary() -> None:
    links = _load_json(XAMAN_FIXTURES / "assurance_links.json")
    boundary = _load_json(XAMAN_FIXTURES / "runtime_projection_boundary.json")
    samples = _load_json(XAMAN_FIXTURES / "sample_ledger_records.json")

    assert links["policy"]["formal_assurance_is_not_runtime_correctness"] is True
    assert links["policy"]["runtime_must_not_import_report_generators"] is True
    assert len(links["formal_assets"]) >= 4
    bridge_ids = {item["id"] for item in links["bridge_rules"]}
    assert "BRIDGE-XAMAN-002" in bridge_ids
    assert "BRIDGE-XAMAN-003" in bridge_ids

    forbidden = boundary["boundary"]["formal_import_prefixes_forbidden_in_runtime_processor"]
    assert any("security_models.crypto_exchange.reports" in item for item in forbidden)
    assert "transaction_signing" in boundary["boundary"]["custodial_operations_forbidden"]

    assert samples["network"]["chain"] == "xrpl"
    assert len(samples["records"]) >= 3
    for record in samples["records"]:
        assert record["schema_version"] == 1
        assert "raw_payload_digest" in record
        assert "finality_state" in record
        amount = record["amount"]
        if amount.get("currency") == "XRP":
            assert isinstance(amount["value_drops"], str)


def test_xaman_formal_asset_paths_exist_when_present_in_repo() -> None:
    links = _load_json(XAMAN_FIXTURES / "assurance_links.json")
    missing = []
    for asset in links["formal_assets"]:
        path = REPO_ROOT / asset["path"]
        if not path.is_file():
            missing.append(asset["path"])
    # Formal assets are inventory evidence; at least the majority should exist.
    assert len(missing) <= 1, f"unexpected missing xaman formal assets: {missing}"


# ---------------------------------------------------------------------------
# Security baseline: failures to fix, not compatibility guarantees
# ---------------------------------------------------------------------------


def test_security_baseline_marks_all_required_gaps_as_failures(
    security_baseline: dict[str, Any],
) -> None:
    assert security_baseline["schema"] == "wallet_processor_migration/security-baseline@1"
    assert security_baseline["goal_id"] == "WALPROC-G020"
    assert security_baseline["task_id"] == "WALPROC-003"
    assert security_baseline["policy"]["blessing_as_compatibility_guarantee_forbidden"] is True
    assert security_baseline["policy"]["default_classification_for_listed_gaps"] == "failure_to_fix"
    assert "vulnerabilities" in security_baseline["policy"]["compatibility_does_not_freeze"]

    required = list(security_baseline["required_acceptance_terms"])
    assert required == REQUIRED_SECURITY_ACCEPTANCE_TERMS

    coverage = security_baseline["acceptance_term_coverage"]
    findings_by_id = {item["id"]: item for item in security_baseline["findings"]}
    for term in REQUIRED_SECURITY_ACCEPTANCE_TERMS:
        finding_id = coverage[term]
        finding = findings_by_id[finding_id]
        assert finding["classification"] == "failure_to_fix", finding_id
        assert finding["not_compatibility_guarantee"] is True, finding_id
        assert finding["status"] == "open", finding_id
        assert finding["acceptance_term"] == term
        assert finding["evidence"], finding_id
        assert finding["severity"] in {"low", "medium", "high", "critical"}

    assert security_baseline["xaman_boundary"]["formal_assurance_is_not_runtime_correctness"] is True
    assert security_baseline["freeze_status"] == "frozen"


def test_security_baseline_does_not_list_gaps_as_compatibility_vectors(
    security_baseline: dict[str, Any],
) -> None:
    for finding in security_baseline["findings"]:
        classification = finding["classification"].lower()
        assert classification != "compatibility_guarantee"
        assert "compat" not in classification or "not" in classification
        assert finding.get("not_compatibility_guarantee") is True


def test_security_baseline_cross_references_fixture_dirs(
    security_baseline: dict[str, Any],
) -> None:
    refs = set(security_baseline["fixture_refs"])
    assert "ipfs_datasets_py/tests/fixtures/wallets/worldcoin" in refs
    assert "ipfs_datasets_py/tests/fixtures/wallets/xaman" in refs
    for ref in security_baseline["source_inventory_refs"]:
        assert (REPO_ROOT / ref).is_file(), ref


def test_baseline_bundle_is_cohesive(
    worldcoin_manifest: dict[str, Any],
    xaman_manifest: dict[str, Any],
    security_baseline: dict[str, Any],
) -> None:
    """All four evidence outputs form one WALPROC-G020 freeze package."""

    assert worldcoin_manifest["goal_id"] == security_baseline["goal_id"] == "WALPROC-G020"
    assert xaman_manifest["goal_id"] == "WALPROC-G020"
    assert worldcoin_manifest["task_id"] == security_baseline["task_id"] == "WALPROC-003"
    assert WORLDCOIN_FIXTURES.is_dir()
    assert XAMAN_FIXTURES.is_dir()
    assert SECURITY_BASELINE.is_file()
