"""LPC-130: Python / CLI / MCP channel parity (unit).

Derives and checks ``LogicOperationCatalog@1`` against the live datasets
service. Channels must agree on operation names, schemas, status, authority,
failure codes, and opt-in. Installation is not an ordinary verify operation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest

from ipfs_datasets_py.logic import cli as logic_cli
from ipfs_datasets_py.logic.verification_api import (
    FeatureAvailability,
    GOAL_TACTICIAN_CLI_TO_OPERATION,
    GOAL_TACTICIAN_OPERATIONS,
    GOAL_TACTICIAN_TOOL_TO_OPERATION,
    LOGIC_VERIFICATION_API_INTERFACE,
    LOGIC_VERIFICATION_RESPONSE_SCHEMA,
    STABLE_OPERATIONS,
    VerificationAuthority,
    VerificationStatus,
    get_verification_api,
    list_stable_features,
)
from ipfs_datasets_py.mcp_server.tools import logic_verification as lv


LOGIC_OPERATION_CATALOG_INTERFACE: Final = "LogicOperationCatalog@1"

ENVELOPE_KEYS: Final[frozenset[str]] = frozenset(
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

# Closed CLI projection of the stable verification catalog (LogicVerificationCLI@1).
VERIFICATION_CLI_TO_OPERATION: Final[dict[str, str]] = {
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

OPT_IN_STABLE_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "probe_provider",
        "install_provider",
        "attest_receipt",
    }
)

SUPERVISOR_ONLY_CONTROLS: Final[frozenset[str]] = frozenset(
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

INSTALL_NOT_VERIFY_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "check",
        "verify_receipt",
        "run_portfolio",
        "monitor",
        "compile_verification_artifact",
    }
)


def _catalog_note_path() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "operation_catalog.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[4] / note_relative


def _cli_choices() -> set[str]:
    parser = logic_cli.create_parser()
    # argparse stores subparsers on the first group action.
    return set(parser._subparsers._group_actions[0].choices)  # type: ignore[attr-defined]


def _assert_envelope(payload: dict[str, Any], *, operation: str | None = None) -> None:
    missing = ENVELOPE_KEYS - set(payload)
    assert not missing, f"missing envelope keys: {sorted(missing)}"
    assert payload["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert payload["status"] in {member.value for member in VerificationStatus}
    assert payload["authority"] in {member.value for member in VerificationAuthority}
    assert isinstance(payload["result"], dict)
    assert isinstance(payload["unsupported_features"], list)
    assert isinstance(payload["diagnostics"], list)
    if operation is not None:
        assert payload["operation"] == operation


# ---------------------------------------------------------------------------
# Catalog note / interface
# ---------------------------------------------------------------------------


def test_operation_catalog_note_documents_logic_operation_catalog() -> None:
    path = _catalog_note_path()
    assert path.is_file(), f"missing catalog note: {path}"
    text = path.read_text(encoding="utf-8")
    assert LOGIC_OPERATION_CATALOG_INTERFACE in text
    assert "LogicVerificationAPI@1" in text
    assert "LogicVerificationCLI@1" in text
    assert "LogicVerificationMCP@1" in text
    assert "install_without_opt_in" in text
    assert "Installation is not an ordinary verify" in text or (
        "Installation is **not** an ordinary" in text
    )
    for operation in STABLE_OPERATIONS:
        assert f"`{operation}`" in text or operation in text, operation


def test_channel_interfaces_are_stable() -> None:
    assert LOGIC_VERIFICATION_API_INTERFACE == "LogicVerificationAPI@1"
    assert logic_cli.LOGIC_VERIFICATION_CLI_INTERFACE == "LogicVerificationCLI@1"
    assert lv.LOGIC_VERIFICATION_MCP_INTERFACE == "LogicVerificationMCP@1"
    assert lv.LOGIC_VERIFICATION_CLI_INTERFACE == "LogicVerificationCLI@1"
    assert LOGIC_VERIFICATION_RESPONSE_SCHEMA == "logic-verification-response/v1"


# ---------------------------------------------------------------------------
# Name / schema parity
# ---------------------------------------------------------------------------


def test_mcp_tool_mapping_covers_stable_operations() -> None:
    mapped = set(lv.TOOL_TO_OPERATION.values())
    missing = set(STABLE_OPERATIONS) - mapped
    assert not missing, f"MCP missing operations: {sorted(missing)}"
    for tool_name, operation in lv.TOOL_TO_OPERATION.items():
        assert tool_name in lv.TOOL_NAMES
        schema = lv.TOOL_SCHEMAS[tool_name]
        assert schema["interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
        assert schema["python_operation"] == operation
        assert schema["returns"]["envelope"] == LOGIC_VERIFICATION_RESPONSE_SCHEMA
        assert schema["name"] == tool_name


def test_cli_commands_cover_stable_operations() -> None:
    choices = _cli_choices()
    for command, operation in VERIFICATION_CLI_TO_OPERATION.items():
        assert command in choices, f"CLI missing command {command}"
        if operation != "list_features":
            assert operation in STABLE_OPERATIONS or operation == "list_features"
    # Every stable operation has a CLI projection.
    projected = set(VERIFICATION_CLI_TO_OPERATION.values())
    missing = set(STABLE_OPERATIONS) - projected
    assert not missing, f"CLI map missing operations: {sorted(missing)}"


def test_python_cli_mcp_share_operation_names() -> None:
    mcp_ops = {
        op for op in lv.TOOL_TO_OPERATION.values() if op in STABLE_OPERATIONS
    }
    cli_ops = {
        op for op in VERIFICATION_CLI_TO_OPERATION.values() if op in STABLE_OPERATIONS
    }
    assert mcp_ops == set(STABLE_OPERATIONS)
    assert cli_ops == set(STABLE_OPERATIONS)
    # Install must not be aliased onto ordinary verify ops.
    install_tools = [
        tool
        for tool, op in lv.TOOL_TO_OPERATION.items()
        if op == "install_provider"
    ]
    assert install_tools == ["verification_install_provider"]
    for verify_op in INSTALL_NOT_VERIFY_OPERATIONS:
        assert VERIFICATION_CLI_TO_OPERATION.get("install-provider") != verify_op
        assert lv.TOOL_TO_OPERATION["verification_install_provider"] != verify_op


def test_goal_tactician_maps_are_closed_and_additive() -> None:
    assert set(GOAL_TACTICIAN_TOOL_TO_OPERATION.values()) == set(GOAL_TACTICIAN_OPERATIONS)
    assert set(GOAL_TACTICIAN_CLI_TO_OPERATION.values()) == set(GOAL_TACTICIAN_OPERATIONS)
    # Additive: goal ops are not required on the closed LFV MCP tool set.
    mcp_stable = set(lv.TOOL_TO_OPERATION.values())
    for operation in GOAL_TACTICIAN_OPERATIONS:
        if operation != "list_goal_tactician_operations":
            assert operation not in mcp_stable or operation in STABLE_OPERATIONS


# ---------------------------------------------------------------------------
# Status, authority, opt-in
# ---------------------------------------------------------------------------


def test_status_and_authority_vocabularies_are_closed() -> None:
    statuses = {member.value for member in VerificationStatus}
    authorities = {member.value for member in VerificationAuthority}
    assert {
        "succeeded",
        "partial",
        "unsupported",
        "unavailable",
        "invalid",
        "error",
        "declarative",
    } <= statuses
    assert {
        "none",
        "advisory",
        "bounded",
        "declarative",
        "attestation",
    } <= authorities


def test_feature_descriptors_agree_on_opt_in_and_authority() -> None:
    features = {item.feature_id: item for item in list_stable_features()}
    for operation in STABLE_OPERATIONS:
        assert operation in features, f"feature missing for {operation}"
        feature = features[operation]
        if operation in OPT_IN_STABLE_OPERATIONS:
            assert feature.availability is FeatureAvailability.OPT_IN
            assert feature.requires_opt_in is True
        else:
            assert feature.availability is FeatureAvailability.DECLARED
            assert feature.requires_opt_in is False

    install = features["install_provider"]
    assert install.authority_ceiling is VerificationAuthority.NONE
    assert "opt-in" in install.description.lower() or install.requires_opt_in

    check = features["check"]
    assert check.availability is FeatureAvailability.DECLARED
    assert check.requires_opt_in is False
    assert check.authority_ceiling is VerificationAuthority.BOUNDED

    verify = features["verify_receipt"]
    assert verify.requires_opt_in is False
    assert verify.feature_id != "install_provider"


def test_list_features_superset_of_stable_operations() -> None:
    api = get_verification_api(reset=True)
    response = api.list_features()
    payload = response.to_dict()
    _assert_envelope(payload, operation="list_features")
    assert payload["status"] == VerificationStatus.DECLARATIVE.value
    assert payload["authority"] == VerificationAuthority.DECLARATIVE.value
    ops = set(payload["result"]["operations"])
    assert set(STABLE_OPERATIONS) <= ops
    feature_items = payload["result"]["features"]
    assert isinstance(feature_items, list)
    feature_map = {item["feature_id"]: item for item in feature_items}
    assert set(STABLE_OPERATIONS) <= set(feature_map)
    assert feature_map["install_provider"]["availability"] == FeatureAvailability.OPT_IN.value
    assert feature_map["install_provider"]["requires_opt_in"] is True
    assert feature_map["check"]["requires_opt_in"] is False


# ---------------------------------------------------------------------------
# Failure codes and installation boundary
# ---------------------------------------------------------------------------


def test_install_without_opt_in_failure_code_is_stable() -> None:
    api = get_verification_api(reset=True)
    denied = api.install_provider("z3").to_dict()
    _assert_envelope(denied, operation="install_provider")
    assert denied["status"] == VerificationStatus.UNSUPPORTED.value
    assert denied["authority"] == VerificationAuthority.NONE.value
    assert "install_without_opt_in" in denied["unsupported_features"]
    assert denied["result"].get("install_attempted") is False
    assert denied["result"].get("mutation_authorized") is False
    assert denied["result"].get("installed") is False


def test_install_dry_run_is_declarative_not_verify() -> None:
    api = get_verification_api(reset=True)
    planned = api.install_provider("z3", dry_run=True).to_dict()
    _assert_envelope(planned, operation="install_provider")
    assert planned["status"] == VerificationStatus.DECLARATIVE.value
    assert planned["authority"] == VerificationAuthority.NONE.value
    assert planned["result"]["status"] == "planned"
    assert planned["result"]["install_attempted"] is False
    assert planned["operation"] == "install_provider"
    assert planned["operation"] != "check"
    assert planned["operation"] != "verify_receipt"


def test_install_is_not_ordinary_verify_operation() -> None:
    api = get_verification_api(reset=True)
    install = api.install_provider("z3", dry_run=True).to_dict()
    receipt = api.verify_receipt(
        {
            "receipt_id": "rcpt:parity",
            "authority": "bounded",
            "digest": "a" * 64,
            "kind": "proof_receipt",
        }
    ).to_dict()
    _assert_envelope(install, operation="install_provider")
    _assert_envelope(receipt, operation="verify_receipt")
    assert install["operation"] != receipt["operation"]
    assert install["authority"] == VerificationAuthority.NONE.value
    # verify_receipt is structural validation, never an installer.
    assert receipt["result"].get("install_attempted") is None
    assert "plan" not in receipt["result"] or receipt["operation"] != "install_provider"


def test_unknown_provider_capability_failure_code() -> None:
    api = get_verification_api(reset=True)
    missing = api.provider_capabilities("not-a-backend").to_dict()
    _assert_envelope(missing, operation="provider_capabilities")
    assert missing["status"] == VerificationStatus.UNSUPPORTED.value
    assert any(
        code == "provider:not-a-backend" or "not-a-backend" in code
        for code in missing["unsupported_features"]
    )


def test_supervisor_only_controls_are_not_public_operations() -> None:
    public_ops = set(STABLE_OPERATIONS) | set(GOAL_TACTICIAN_OPERATIONS)
    public_ops |= set(lv.TOOL_TO_OPERATION.values())
    public_ops |= set(VERIFICATION_CLI_TO_OPERATION.values())
    public_ops |= set(GOAL_TACTICIAN_TOOL_TO_OPERATION)
    public_ops |= set(GOAL_TACTICIAN_CLI_TO_OPERATION)
    public_ops |= set(GOAL_TACTICIAN_TOOL_TO_OPERATION.values())
    public_ops |= set(GOAL_TACTICIAN_CLI_TO_OPERATION.values())
    leaked = SUPERVISOR_ONLY_CONTROLS & public_ops
    assert not leaked, f"supervisor-only controls exposed: {sorted(leaked)}"
    # Also ensure none appear as MCP tool names or CLI commands.
    tools = set(lv.TOOL_NAMES)
    commands = _cli_choices()
    for control in SUPERVISOR_ONLY_CONTROLS:
        assert control not in tools
        assert control not in commands
        assert control.replace("_", "-") not in commands


def test_mcp_capabilities_report_shared_catalog() -> None:
    import anyio

    meta = anyio.run(lv.verification_capabilities)
    assert meta["success"] is True
    assert meta["python_interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert meta["mcp_interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
    assert meta["cli_interface"] == logic_cli.LOGIC_VERIFICATION_CLI_INTERFACE
    assert set(meta["operations"]) >= set(STABLE_OPERATIONS)
    assert meta["tool_to_operation"] == dict(lv.TOOL_TO_OPERATION)
    for schema in meta["schemas"]:
        assert schema["returns"]["envelope"] == LOGIC_VERIFICATION_RESPONSE_SCHEMA


@pytest.mark.parametrize(
    "operation",
    [
        "list_providers",
        "list_logic_families",
        "provider_capabilities",
    ],
)
def test_discovery_operations_are_declarative_on_python(operation: str) -> None:
    api = get_verification_api(reset=True)
    method = getattr(api, operation)
    payload = method().to_dict()
    _assert_envelope(payload, operation=operation)
    assert payload["status"] == VerificationStatus.DECLARATIVE.value
    assert payload["authority"] == VerificationAuthority.DECLARATIVE.value
