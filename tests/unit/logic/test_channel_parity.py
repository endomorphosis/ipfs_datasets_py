"""LPC-130 unit gates for LogicOperationCatalog@1 channel parity.

Acceptance:

* Python, CLI, and MCP agree on operation names, request/response schemas,
  status, authority, failure codes, and opt-in requirements;
* installation is not an ordinary verification operation;
* supervisor-only mutation controls are not exposed from datasets logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.cli import LOGIC_VERIFICATION_CLI_INTERFACE
from ipfs_datasets_py.logic.verification_api import (
    FORMAL_VERIFICATION_MCP_PARITY_INTERFACE,
    GOAL_TACTICIAN_CLI_MCP_INTERFACE,
    GOAL_TACTICIAN_CLI_TO_OPERATION,
    GOAL_TACTICIAN_OPERATIONS,
    GOAL_TACTICIAN_TOOL_TO_OPERATION,
    LOGIC_VERIFICATION_API_INTERFACE,
    LOGIC_VERIFICATION_FEATURE_SCHEMA,
    LOGIC_VERIFICATION_REQUEST_SCHEMA,
    LOGIC_VERIFICATION_RESPONSE_SCHEMA,
    STABLE_OPERATIONS,
    FeatureAvailability,
    VerificationAuthority,
    VerificationStatus,
    get_verification_api,
    list_stable_features,
)
from ipfs_datasets_py.mcp_server.tools import logic_verification as lv


LOGIC_OPERATION_CATALOG_INTERFACE = "LogicOperationCatalog@1"

ENVELOPE_KEYS = frozenset(
    {
        "status",
        "authority",
        "operation",
        "result",
        "assumptions",
        "bounds",
        "translations",
        "witnesses",
        "unsupported_features",
        "diagnostics",
        "cache",
        "interface",
    }
)

# Closed CLI projection of the Python facade (LogicVerificationCLI@1).
CLI_TO_OPERATION: dict[str, str] = {
    "list-features": "list_features",
    "list-families": "list_logic_families",
    "list-providers": "list_providers",
    "provider-capabilities": "provider_capabilities",
    "compile": "compile_verification_artifact",
    "check": "check",
    "monitor": "monitor",
    "portfolio": "run_portfolio",
    "counterexample": "explain_counterexample",
    "verify-receipt": "verify_receipt",
    "advise": "advise",
    "attest-receipt": "attest_receipt",
    "probe-provider": "probe_provider",
    "install-provider": "install_provider",
}

ORDINARY_VERIFY_OPERATIONS = frozenset(
    {
        "compile_verification_artifact",
        "check",
        "monitor",
        "run_portfolio",
        "explain_counterexample",
        "verify_receipt",
        "advise",
    }
)

INSTALLER_OPERATION = "install_provider"

SUPERVISOR_ONLY_CONTROLS = frozenset(
    {
        "admit_goal",
        "close_plan",
        "mutate_supervisor",
        "force_complete",
        "lease_steal",
        "rewrite_event_log",
        "bypass_resource_policy",
        "promote_proof_authority",
        "supervisor_mutate",
        "supervisor_only",
    }
)

STATUS_VALUES = frozenset(item.value for item in VerificationStatus)
AUTHORITY_VALUES = frozenset(item.value for item in VerificationAuthority)

CATALOG_NOTE_RELATIVE = Path(
    "data/agent_supervisor/logic_platform_canonicalization/notes/operation_catalog.md"
)


def _catalog_note_path() -> Path | None:
    """Resolve the LPC-130 operation catalog evidence note."""

    candidates: list[Path] = []
    here = Path(__file__).resolve()
    # Prefer ancestors that already contain the evidence note on disk.
    for parent in here.parents:
        note = parent / CATALOG_NOTE_RELATIVE
        if note.is_file():
            return note
        candidates.append(note)
    candidates.append(Path.cwd() / CATALOG_NOTE_RELATIVE)
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file():
            return path
    return None


def _feature_map() -> dict[str, Any]:
    return {item.feature_id: item for item in list_stable_features()}


def test_logic_operation_catalog_interface_and_schema_identities() -> None:
    assert LOGIC_OPERATION_CATALOG_INTERFACE == "LogicOperationCatalog@1"
    assert LOGIC_VERIFICATION_API_INTERFACE == "LogicVerificationAPI@1"
    assert LOGIC_VERIFICATION_CLI_INTERFACE == "LogicVerificationCLI@1"
    assert lv.LOGIC_VERIFICATION_MCP_INTERFACE == "LogicVerificationMCP@1"
    assert lv.LOGIC_VERIFICATION_CLI_INTERFACE == LOGIC_VERIFICATION_CLI_INTERFACE
    assert LOGIC_VERIFICATION_RESPONSE_SCHEMA == "logic-verification-response/v1"
    assert LOGIC_VERIFICATION_REQUEST_SCHEMA == "logic-verification-request/v1"
    assert LOGIC_VERIFICATION_FEATURE_SCHEMA == "logic-verification-feature/v1"
    assert FORMAL_VERIFICATION_MCP_PARITY_INTERFACE == "FormalVerificationMCPParity@1"
    assert GOAL_TACTICIAN_CLI_MCP_INTERFACE == "GoalTacticianCLIMCP@1"


def test_stable_operations_are_closed_and_channel_covered() -> None:
    assert INSTALLER_OPERATION in STABLE_OPERATIONS
    assert "list_features" not in STABLE_OPERATIONS

    mcp_ops = {
        op
        for tool, op in lv.TOOL_TO_OPERATION.items()
        if tool != "verification_capabilities"
    }
    cli_ops = set(CLI_TO_OPERATION.values())
    for operation in STABLE_OPERATIONS:
        assert operation in mcp_ops, f"MCP missing mapping for {operation}"
        assert operation in cli_ops, f"CLI missing mapping for {operation}"

    # Exactly one MCP tool and one CLI command per stable operation.
    for operation in STABLE_OPERATIONS:
        mcp_names = [
            name
            for name, op in lv.TOOL_TO_OPERATION.items()
            if op == operation and name != "verification_capabilities"
        ]
        cli_names = [name for name, op in CLI_TO_OPERATION.items() if op == operation]
        assert len(mcp_names) == 1, mcp_names
        assert len(cli_names) == 1, cli_names

    # MCP tool schemas advertise the same python_operation as TOOL_TO_OPERATION.
    for tool_name, operation in lv.TOOL_TO_OPERATION.items():
        if tool_name == "verification_capabilities":
            continue
        schema = lv.TOOL_SCHEMAS[tool_name]
        assert schema["name"] == tool_name
        assert schema["interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
        assert schema["python_operation"] == operation
        assert schema["returns"]["envelope"] == LOGIC_VERIFICATION_RESPONSE_SCHEMA


def test_cli_parser_registers_closed_verification_commands() -> None:
    from ipfs_datasets_py.logic import cli as logic_cli

    parser = logic_cli.create_parser()
    choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
    for command in CLI_TO_OPERATION:
        assert command in choices, f"CLI missing command {command}"
    assert "verification-capabilities" in choices


def test_status_and_authority_vocabularies_are_closed() -> None:
    expected_status = {
        "succeeded",
        "partial",
        "unsupported",
        "unavailable",
        "invalid",
        "error",
        "declarative",
    }
    expected_authority = {
        "none",
        "advisory",
        "bounded",
        "satisfiability",
        "model_check",
        "monitor",
        "authorization",
        "protocol",
        "hyperproperty",
        "candidate",
        "reconstruction",
        "attestation",
        "theorem",
        "declarative",
    }
    assert STATUS_VALUES == expected_status
    assert AUTHORITY_VALUES == expected_authority


def test_opt_in_and_authority_ceilings_from_stable_features() -> None:
    features = _feature_map()
    for operation in STABLE_OPERATIONS:
        assert operation in features, f"list_stable_features missing {operation}"

    opt_in = {
        feature_id
        for feature_id, item in features.items()
        if feature_id in STABLE_OPERATIONS and item.requires_opt_in
    }
    assert opt_in == {"probe_provider", "install_provider", "attest_receipt"}

    for feature_id in opt_in:
        assert features[feature_id].availability is FeatureAvailability.OPT_IN

    assert features["list_providers"].availability is FeatureAvailability.DECLARED
    assert features["check"].authority_ceiling is VerificationAuthority.BOUNDED
    assert features["advise"].authority_ceiling is VerificationAuthority.ADVISORY
    assert features["attest_receipt"].authority_ceiling is VerificationAuthority.ATTESTATION
    assert features["install_provider"].authority_ceiling is VerificationAuthority.NONE
    assert features["probe_provider"].authority_ceiling is VerificationAuthority.NONE

    # Ordinary verify ops are declared, not opt-in installers.
    for operation in ORDINARY_VERIFY_OPERATIONS:
        assert features[operation].requires_opt_in is False
        assert features[operation].availability is FeatureAvailability.DECLARED


def test_installation_is_not_an_ordinary_verify_operation() -> None:
    features = _feature_map()
    install = features[INSTALLER_OPERATION]
    verify = features["verify_receipt"]
    check = features["check"]

    assert install.requires_opt_in is True
    assert install.availability is FeatureAvailability.OPT_IN
    assert install.authority_ceiling is VerificationAuthority.NONE

    assert verify.requires_opt_in is False
    assert check.requires_opt_in is False
    assert verify.authority_ceiling is VerificationAuthority.BOUNDED
    assert check.authority_ceiling is VerificationAuthority.BOUNDED

    # Installer tool schema is distinct from check / verify-receipt tools.
    assert lv.TOOL_TO_OPERATION["verification_install_provider"] == INSTALLER_OPERATION
    assert lv.TOOL_TO_OPERATION["verification_check"] == "check"
    assert lv.TOOL_TO_OPERATION["verification_verify_receipt"] == "verify_receipt"
    assert CLI_TO_OPERATION["install-provider"] == INSTALLER_OPERATION
    assert CLI_TO_OPERATION["check"] == "check"
    assert CLI_TO_OPERATION["verify-receipt"] == "verify_receipt"

    install_schema = lv.TOOL_SCHEMAS["verification_install_provider"]
    assert install_schema["parameters"]["properties"]["allow_install"]["default"] is False
    assert "allow_install" in install_schema["parameters"]["properties"]
    check_schema = lv.TOOL_SCHEMAS["verification_check"]
    assert "allow_install" not in check_schema["parameters"].get("properties", {})
    verify_schema = lv.TOOL_SCHEMAS["verification_verify_receipt"]
    assert "allow_install" not in verify_schema["parameters"].get("properties", {})

    # Installer is not aliased onto ordinary verify operation names.
    assert INSTALLER_OPERATION not in ORDINARY_VERIFY_OPERATIONS
    assert INSTALLER_OPERATION != "verify_receipt"
    assert INSTALLER_OPERATION != "check"


def test_install_failure_codes_and_authority_are_installer_scoped() -> None:
    api = get_verification_api(reset=True)

    denied = api.install_provider("z3")
    assert denied.status is VerificationStatus.UNSUPPORTED
    assert denied.authority is VerificationAuthority.NONE
    assert "install_without_opt_in" in denied.unsupported_features
    assert denied.operation == INSTALLER_OPERATION

    planned = api.install_provider("z3", dry_run=True)
    assert planned.status is VerificationStatus.DECLARATIVE
    assert planned.authority is VerificationAuthority.NONE
    assert planned.result.get("install_attempted") is False
    assert planned.operation == INSTALLER_OPERATION

    offline = api.install_provider("z3", allow_install=True, offline=True)
    assert offline.status is VerificationStatus.UNAVAILABLE
    assert offline.authority is VerificationAuthority.NONE
    assert "offline_install" in offline.unsupported_features

    # Ordinary verify path never returns installer opt-in codes.
    receipt = api.verify_receipt(None)
    assert receipt.operation == "verify_receipt"
    assert "install_without_opt_in" not in receipt.unsupported_features
    assert "offline_install" not in receipt.unsupported_features
    assert "mcp_provider_install_operator_policy" not in receipt.unsupported_features


def test_discovery_envelope_uses_shared_status_authority_schema() -> None:
    api = get_verification_api(reset=True)
    response = api.list_providers()
    payload = response.to_dict()
    missing = ENVELOPE_KEYS - set(payload)
    assert not missing, f"missing envelope keys: {sorted(missing)}"
    assert payload["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert payload["schema_version"] == LOGIC_VERIFICATION_RESPONSE_SCHEMA
    assert payload["status"] == VerificationStatus.DECLARATIVE.value
    assert payload["authority"] == VerificationAuthority.DECLARATIVE.value
    assert payload["operation"] == "list_providers"
    assert payload["status"] in STATUS_VALUES
    assert payload["authority"] in AUTHORITY_VALUES


def test_list_features_is_superset_of_stable_operations() -> None:
    api = get_verification_api(reset=True)
    payload = api.list_features().to_dict()
    assert payload["status"] == "declarative"
    assert set(payload["result"]["operations"]) >= set(STABLE_OPERATIONS)
    feature_ids = {item["feature_id"] for item in payload["result"]["features"]}
    assert set(STABLE_OPERATIONS) <= feature_ids


def test_supervisor_only_controls_are_not_in_public_catalog() -> None:
    public_ops = set(STABLE_OPERATIONS) | set(lv.TOOL_TO_OPERATION.values()) | set(
        CLI_TO_OPERATION.values()
    )
    for control in SUPERVISOR_ONLY_CONTROLS:
        assert control not in public_ops
        assert control not in STABLE_OPERATIONS
        assert f"verification_{control}" not in lv.TOOL_NAMES
        assert control not in CLI_TO_OPERATION
        assert control not in GOAL_TACTICIAN_OPERATIONS


def test_goal_tactician_maps_are_additive_and_preserve_stable_ops() -> None:
    assert set(GOAL_TACTICIAN_OPERATIONS).isdisjoint(set(STABLE_OPERATIONS))
    assert set(GOAL_TACTICIAN_TOOL_TO_OPERATION.values()) == set(GOAL_TACTICIAN_OPERATIONS)
    assert set(GOAL_TACTICIAN_CLI_TO_OPERATION.values()) == set(GOAL_TACTICIAN_OPERATIONS)

    # Goal tactician tools are not merged into the closed LFV verification MCP set.
    for tool_name in GOAL_TACTICIAN_TOOL_TO_OPERATION:
        assert tool_name not in lv.TOOL_NAMES

    # Closed 1:1 maps.
    assert len(GOAL_TACTICIAN_TOOL_TO_OPERATION) == len(GOAL_TACTICIAN_OPERATIONS)
    assert len(GOAL_TACTICIAN_CLI_TO_OPERATION) == len(GOAL_TACTICIAN_OPERATIONS)


def test_shared_failure_code_provider_unknown_is_stable() -> None:
    api = get_verification_api(reset=True)
    missing = api.provider_capabilities("not-a-backend")
    assert missing.status is VerificationStatus.UNSUPPORTED
    assert "provider:not-a-backend" in missing.unsupported_features


def test_operation_catalog_note_documents_parity_contract() -> None:
    note_path = _catalog_note_path()
    assert note_path is not None, "operation_catalog.md evidence note is required"
    text = note_path.read_text(encoding="utf-8")
    for needle in (
        "LogicOperationCatalog@1",
        "STABLE_OPERATIONS",
        "install_without_opt_in",
        "Installation is not an ordinary verify operation",
        "LogicVerificationAPI@1",
        "LogicVerificationCLI@1",
        "LogicVerificationMCP@1",
        "supervisor_only_control",
        "requires_opt_in",
        "mcp_provider_install_operator_policy",
        "offline_install",
        "VerificationStatus",
        "VerificationAuthority",
    ):
        assert needle in text, f"catalog note missing {needle!r}"


@pytest.mark.parametrize(
    "operation",
    [
        "list_logic_families",
        "list_providers",
        "provider_capabilities",
        "compile_verification_artifact",
        "check",
        "monitor",
        "run_portfolio",
        "explain_counterexample",
        "verify_receipt",
        "advise",
        "install_provider",
        "probe_provider",
        "attest_receipt",
    ],
)
def test_each_stable_operation_has_one_mcp_and_cli_name(operation: str) -> None:
    mcp_names = [
        name
        for name, op in lv.TOOL_TO_OPERATION.items()
        if op == operation and name != "verification_capabilities"
    ]
    cli_names = [name for name, op in CLI_TO_OPERATION.items() if op == operation]
    assert len(mcp_names) == 1, mcp_names
    assert len(cli_names) == 1, cli_names
    assert mcp_names[0] in lv.TOOL_SCHEMAS
    assert lv.TOOL_SCHEMAS[mcp_names[0]]["python_operation"] == operation
    assert lv.TOOL_SCHEMAS[mcp_names[0]]["returns"]["envelope"] == (
        LOGIC_VERIFICATION_RESPONSE_SCHEMA
    )
