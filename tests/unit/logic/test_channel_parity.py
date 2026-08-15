"""LPC-130 unit gate: Python / CLI / MCP channel parity (LogicOperationCatalog@1).

Acceptance:

* Channels agree on operation names, request/response schemas, status,
  authority, failure codes, and opt-in requirements.
* Installation is not an ordinary verify operation.
* Supervisor-only mutation controls are never exposed from datasets logic.
"""

from __future__ import annotations

import argparse
from typing import Any

import anyio

from ipfs_datasets_py.logic import cli as logic_cli
from ipfs_datasets_py.logic.cli import LOGIC_VERIFICATION_CLI_INTERFACE, create_parser
from ipfs_datasets_py.logic.verification_api import (
    GOAL_TACTICIAN_CLI_COMMANDS,
    GOAL_TACTICIAN_CLI_MCP_INTERFACE,
    GOAL_TACTICIAN_CLI_TO_OPERATION,
    GOAL_TACTICIAN_OPERATIONS,
    GOAL_TACTICIAN_TOOL_NAMES,
    GOAL_TACTICIAN_TOOL_TO_OPERATION,
    LOGIC_VERIFICATION_API_INTERFACE,
    LOGIC_VERIFICATION_REQUEST_SCHEMA,
    LOGIC_VERIFICATION_RESPONSE_SCHEMA,
    STABLE_OPERATIONS,
    FeatureAvailability,
    VerificationAuthority,
    VerificationStatus,
    get_verification_api,
    list_goal_tactician_cli_mcp_surface,
    list_stable_features,
)
from ipfs_datasets_py.mcp_server.tools import logic_verification as lv


# Closed CLI projection of LogicVerificationCLI@1 (mirrors cli.py dispatch).
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
    "verification-capabilities": "list_features",
}

OPT_IN_OPERATIONS = frozenset(
    {"probe_provider", "install_provider", "attest_receipt"}
)

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

STATUS_VOCABULARY = frozenset(item.value for item in VerificationStatus)
AUTHORITY_VOCABULARY = frozenset(item.value for item in VerificationAuthority)

FORBIDDEN_SUPERVISOR_CONTROLS = frozenset(
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


def _run(coro):
    async def _awaiter():
        return await coro

    return anyio.run(_awaiter)


def _assert_envelope(payload: dict[str, Any], *, operation: str | None = None) -> None:
    missing = ENVELOPE_KEYS - set(payload)
    assert not missing, f"missing envelope keys: {sorted(missing)}"
    assert payload["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert payload.get("schema_version") in {
        None,
        LOGIC_VERIFICATION_RESPONSE_SCHEMA,
        "logic-verification-response/v1",
    } or isinstance(payload.get("schema_version"), str)
    assert payload["status"] in STATUS_VOCABULARY
    assert payload["authority"] in AUTHORITY_VOCABULARY
    assert isinstance(payload["result"], dict)
    assert isinstance(payload["assumptions"], list)
    assert isinstance(payload["bounds"], dict)
    assert isinstance(payload["translations"], list)
    assert isinstance(payload["witnesses"], list)
    assert isinstance(payload["unsupported_features"], list)
    assert isinstance(payload["diagnostics"], list)
    assert isinstance(payload["cache"], dict)
    if operation is not None:
        assert payload["operation"] == operation


# ---------------------------------------------------------------------------
# Catalog projection: names and schemas
# ---------------------------------------------------------------------------


def test_stable_operations_are_closed_and_projected_to_mcp() -> None:
    assert lv.LOGIC_VERIFICATION_MCP_INTERFACE == "LogicVerificationMCP@1"
    assert lv.LOGIC_VERIFICATION_CLI_INTERFACE == LOGIC_VERIFICATION_CLI_INTERFACE
    assert set(STABLE_OPERATIONS).isdisjoint(FORBIDDEN_SUPERVISOR_CONTROLS)

    mapped = set(lv.TOOL_TO_OPERATION.values())
    for operation in STABLE_OPERATIONS:
        assert operation in mapped, f"MCP missing mapping for {operation}"

    for tool, operation in lv.TOOL_TO_OPERATION.items():
        assert tool in lv.TOOL_NAMES
        assert tool in lv.TOOL_SCHEMAS
        schema = lv.TOOL_SCHEMAS[tool]
        assert schema["name"] == tool
        assert schema["interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
        assert schema["python_operation"] == operation
        assert schema["returns"]["envelope"] == LOGIC_VERIFICATION_RESPONSE_SCHEMA


def test_cli_command_map_covers_stable_operations_and_discovery() -> None:
    parser = create_parser()
    subparsers_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    registered = set(subparsers_action.choices)

    for command, operation in CLI_TO_OPERATION.items():
        assert command in registered, f"CLI missing command {command}"
        if operation != "list_features":
            assert operation in STABLE_OPERATIONS

    # Every stable operation has a dedicated CLI command (not only capabilities).
    stable_cli_ops = {
        op for cmd, op in CLI_TO_OPERATION.items() if cmd != "verification-capabilities"
    }
    for operation in STABLE_OPERATIONS:
        assert operation in stable_cli_ops, f"CLI missing dedicated command for {operation}"
    assert "list_features" in stable_cli_ops


def test_goal_tactician_channel_maps_are_closed_and_complete() -> None:
    surface = list_goal_tactician_cli_mcp_surface()
    assert surface["interface"] == GOAL_TACTICIAN_CLI_MCP_INTERFACE
    assert set(surface["operations"]) == set(GOAL_TACTICIAN_OPERATIONS)
    assert set(surface["tools"]) == set(GOAL_TACTICIAN_TOOL_NAMES)
    assert set(surface["cli_commands"]) == set(GOAL_TACTICIAN_CLI_COMMANDS)
    assert set(GOAL_TACTICIAN_TOOL_TO_OPERATION.values()) == set(GOAL_TACTICIAN_OPERATIONS)
    assert set(GOAL_TACTICIAN_CLI_TO_OPERATION.values()) == set(GOAL_TACTICIAN_OPERATIONS)
    assert surface["transport_success_implies_proof_success"] is False
    assert set(surface["legacy_operations_preserved"]) == set(STABLE_OPERATIONS)
    assert set(surface["forbidden_controls"]) == FORBIDDEN_SUPERVISOR_CONTROLS

    # Goal-tactician ops stay additive to LogicVerificationMCP@1.
    mcp_ops = set(lv.TOOL_TO_OPERATION.values())
    for operation in GOAL_TACTICIAN_OPERATIONS:
        if operation == "list_goal_tactician_operations":
            continue
        assert operation not in mcp_ops


def test_forbidden_supervisor_controls_never_appear_on_datasets_channels() -> None:
    public_names = set(STABLE_OPERATIONS) | set(GOAL_TACTICIAN_OPERATIONS)
    public_names |= set(lv.TOOL_TO_OPERATION.values())
    public_names |= set(lv.TOOL_NAMES)
    public_names |= set(CLI_TO_OPERATION)
    public_names |= set(CLI_TO_OPERATION.values())
    public_names |= set(GOAL_TACTICIAN_TOOL_NAMES)
    public_names |= set(GOAL_TACTICIAN_CLI_COMMANDS)
    public_names |= set(GOAL_TACTICIAN_TOOL_TO_OPERATION.values())
    public_names |= set(GOAL_TACTICIAN_CLI_TO_OPERATION.values())

    leaked = FORBIDDEN_SUPERVISOR_CONTROLS & public_names
    assert not leaked, f"supervisor-only controls leaked into public catalogs: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# Status, authority, opt-in, install-is-not-verify
# ---------------------------------------------------------------------------


def test_status_and_authority_vocabularies_are_shared() -> None:
    assert STATUS_VOCABULARY == {
        "succeeded",
        "partial",
        "unsupported",
        "unavailable",
        "invalid",
        "error",
        "declarative",
    }
    assert "declarative" in AUTHORITY_VOCABULARY
    assert "none" in AUTHORITY_VOCABULARY
    assert "theorem" in AUTHORITY_VOCABULARY
    assert LOGIC_VERIFICATION_REQUEST_SCHEMA == "logic-verification-request/v1"
    assert LOGIC_VERIFICATION_RESPONSE_SCHEMA == "logic-verification-response/v1"


def test_opt_in_features_are_marked_consistently() -> None:
    features = {item.feature_id: item for item in list_stable_features()}
    for operation in OPT_IN_OPERATIONS:
        assert operation in STABLE_OPERATIONS
        feature = features[operation]
        assert feature.requires_opt_in is True
        assert feature.availability is FeatureAvailability.OPT_IN

    # Install schema documents the allow_install gate on MCP.
    install_schema = lv.TOOL_SCHEMAS["verification_install_provider"]
    assert install_schema["python_operation"] == "install_provider"
    props = install_schema["parameters"]["properties"]
    assert props["allow_install"]["default"] is False

    # CLI requires an explicit --allow-install flag (store_true, default False).
    parser = create_parser()
    ns = parser.parse_args(["install-provider", "z3"])
    assert getattr(ns, "allow_install", False) is False
    ns_allowed = parser.parse_args(["install-provider", "z3", "--allow-install", "--dry-run"])
    assert ns_allowed.allow_install is True
    assert ns_allowed.dry_run is True


def test_install_provider_is_not_ordinary_verify() -> None:
    api = get_verification_api(reset=True)

    denied = api.install_provider("z3", request_id="req:unit-deny").to_dict()
    _assert_envelope(denied, operation="install_provider")
    assert denied["status"] == "unsupported"
    assert denied["authority"] == "none"
    assert denied["result"]["install_attempted"] is False
    assert denied["result"]["mutation_authorized"] is False
    assert denied["result"]["status"] == "authorization_required"
    assert "install_without_opt_in" in denied["unsupported_features"]
    # Must never look like ordinary verify success.
    assert denied["status"] != "succeeded"
    assert denied["result"].get("installed") is not True

    planned = api.install_provider(
        "z3", dry_run=True, request_id="req:unit-plan"
    ).to_dict()
    _assert_envelope(planned, operation="install_provider")
    assert planned["status"] == "declarative"
    assert planned["authority"] == "none"
    assert planned["result"]["status"] == "planned"
    assert planned["result"]["install_attempted"] is False
    assert planned["result"]["mutation_authorized"] is False

    # Ordinary verify discovery stays non-mutating and separate.
    providers = api.list_providers().to_dict()
    _assert_envelope(providers, operation="list_providers")
    assert providers["status"] == "declarative"
    assert providers["operation"] != "install_provider"


def test_python_and_mcp_agree_on_discovery_envelope() -> None:
    api = get_verification_api(reset=True)
    py = api.list_providers().to_dict()
    mcp = _run(lv.verification_list_providers())
    _assert_envelope(py, operation="list_providers")
    _assert_envelope(mcp, operation="list_providers")
    assert mcp["status"] == py["status"]
    assert mcp["authority"] == py["authority"]
    assert mcp["python_operation"] == "list_providers"
    assert mcp["mcp_interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
    py_ids = {item["provider_id"] for item in py["result"]["providers"]}
    mcp_ids = {item["provider_id"] for item in mcp["result"]["providers"]}
    assert py_ids == mcp_ids


def test_mcp_capabilities_project_stable_catalog() -> None:
    caps = _run(lv.verification_capabilities())
    assert caps["status"] == "declarative"
    assert caps["authority"] == "declarative"
    assert caps["python_interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert caps["mcp_interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
    assert caps["cli_interface"] == LOGIC_VERIFICATION_CLI_INTERFACE
    assert set(caps["operations"]) == set(STABLE_OPERATIONS)
    assert set(caps["tools"]) == set(lv.TOOL_NAMES)
    assert caps["tool_to_operation"] == dict(lv.TOOL_TO_OPERATION)
    assert "max_json_bytes" in caps["bounds"]


def test_cli_list_providers_matches_python_envelope() -> None:
    api = get_verification_api(reset=True)
    py = api.list_providers().to_dict()
    ns = create_parser().parse_args(["list-providers"])
    cli = _run(logic_cli._run_async(ns))
    _assert_envelope(cli, operation="list_providers")
    assert cli["status"] == py["status"]
    assert cli["authority"] == py["authority"]
    py_ids = {item["provider_id"] for item in py["result"]["providers"]}
    cli_ids = {item["provider_id"] for item in cli["result"]["providers"]}
    assert py_ids == cli_ids


def test_cli_and_mcp_install_without_opt_in_stay_non_mutating() -> None:
    api = get_verification_api(reset=True)
    py = api.install_provider("z3").to_dict()
    mcp = _run(lv.verification_install_provider(provider_id="z3", allow_install=False))
    ns = create_parser().parse_args(["install-provider", "z3"])
    cli = _run(logic_cli._run_async(ns))

    for payload, channel in ((py, "python"), (mcp, "mcp"), (cli, "cli")):
        _assert_envelope(payload, operation="install_provider")
        assert payload["status"] == "unsupported", channel
        assert payload["authority"] == "none", channel
        assert payload["result"]["install_attempted"] is False, channel
        assert payload["result"]["mutation_authorized"] is False, channel
        assert payload["result"]["status"] == "authorization_required", channel
        assert payload["status"] != "succeeded", channel
