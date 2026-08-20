"""LPC-130 / LogicOperationCatalog@1 — datasets-side channel closure.

Proves that Python ``LogicVerificationAPI@1`` / ``GoalTacticianAPI@1``,
datasets MCP ``LogicVerificationMCP@1`` / ``GoalTacticianCLIMCP@1``, and
CLI ``LogicVerificationCLI@1`` project one closed operation catalog:

* stable and goal-tactician operation names
* MCP tool and CLI command maps (total, bijective onto their ops)
* shared response envelope keys
* status / authority vocabularies
* opt-in probe / install / attest boundaries
* supervisor-only mutation controls never exposed
* installation is not ordinary verify
* discovery never claims live prover availability
"""

from __future__ import annotations

import argparse
from typing import Any

import anyio
import pytest

from ipfs_datasets_py.logic.cli import LOGIC_VERIFICATION_CLI_INTERFACE, create_parser
from ipfs_datasets_py.logic.verification_api import (
    GOAL_TACTICIAN_CLI_COMMANDS,
    GOAL_TACTICIAN_CLI_MCP_INTERFACE,
    GOAL_TACTICIAN_CLI_TO_OPERATION,
    GOAL_TACTICIAN_OPERATIONS,
    GOAL_TACTICIAN_TOOL_NAMES,
    GOAL_TACTICIAN_TOOL_TO_OPERATION,
    LOGIC_VERIFICATION_API_INTERFACE,
    MIGRATION_OPERATIONS,
    PRODUCTION_AUTHORIZATION_OPERATIONS,
    PROVIDER_ROLE_CLOSURE_OPERATIONS,
    STABLE_OPERATIONS,
    VerificationAuthority,
    VerificationStatus,
    get_verification_api,
    list_goal_tactician_cli_mcp_surface,
)
from ipfs_datasets_py.mcp_server.tools import logic_verification as lv


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

# CLI verification commands sealed by LogicVerificationCLI@1 (cli.py).
STABLE_CLI_COMMANDS: dict[str, str] = {
    "list-families": "list_logic_families",
    "list-providers": "list_providers",
    "provider-capabilities": "provider_capabilities",
    "compile": "compile_verification_artifact",
    "check": "check",
    "monitor": "monitor",
    "portfolio": "run_portfolio",
    "counterexample": "explain_counterexample",
    "verify-receipt": "verify_receipt",
    "attest-receipt": "attest_receipt",
    "advise": "advise",
    "probe-provider": "probe_provider",
    "install-provider": "install_provider",
}

# Discovery helpers on CLI/MCP that are not members of STABLE_OPERATIONS.
DISCOVERY_CLI_COMMANDS = frozenset({"list-features", "verification-capabilities"})


def _run(coro: Any) -> Any:
    return anyio.run(lambda: coro)


def _assert_envelope(payload: dict[str, Any], *, operation: str | None = None) -> None:
    missing = ENVELOPE_KEYS - set(payload)
    assert not missing, f"missing envelope keys: {sorted(missing)}"
    assert payload["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert isinstance(payload["status"], str) and payload["status"]
    assert isinstance(payload["authority"], str) and payload["authority"]
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
# Closed catalog identity
# ---------------------------------------------------------------------------


def test_stable_operations_closed_set() -> None:
    assert STABLE_OPERATIONS == (
        "list_logic_families",
        "list_providers",
        "provider_capabilities",
        "compile_verification_artifact",
        "check",
        "monitor",
        "run_portfolio",
        "explain_counterexample",
        "verify_receipt",
        "attest_receipt",
        "advise",
        "probe_provider",
        "install_provider",
    )
    assert len(STABLE_OPERATIONS) == len(set(STABLE_OPERATIONS))


def test_goal_tactician_operations_closed_and_disjoint_from_stable() -> None:
    assert set(GOAL_TACTICIAN_OPERATIONS) == {
        "formalize_goal",
        "compare_interpretations",
        "discover_missing_proofs",
        "plan_proof",
        "validate_proof_candidate",
        "execute_proof_plan",
        "proof_status",
        "minimize_counterexample",
        "explain_counterexample_causal",
        "replay_counterexample",
        "list_goal_tactician_operations",
    }
    assert set(GOAL_TACTICIAN_OPERATIONS).isdisjoint(set(STABLE_OPERATIONS))
    assert set(MIGRATION_OPERATIONS).isdisjoint(set(STABLE_OPERATIONS))
    assert set(PROVIDER_ROLE_CLOSURE_OPERATIONS).isdisjoint(set(STABLE_OPERATIONS))
    assert set(PRODUCTION_AUTHORIZATION_OPERATIONS).isdisjoint(set(STABLE_OPERATIONS))


def test_mcp_tool_map_covers_stable_operations() -> None:
    assert lv.LOGIC_VERIFICATION_MCP_INTERFACE == "LogicVerificationMCP@1"
    mapped = set(lv.TOOL_TO_OPERATION.values())
    for operation in STABLE_OPERATIONS:
        assert operation in mapped, f"MCP missing mapping for {operation}"
    # Discovery helpers project to list_features and must not invent new ops.
    assert lv.TOOL_TO_OPERATION["verification_list_features"] == "list_features"
    assert lv.TOOL_TO_OPERATION["verification_capabilities"] == "list_features"
    for tool, operation in lv.TOOL_TO_OPERATION.items():
        assert tool in lv.TOOL_NAMES
        assert tool in lv.TOOL_SCHEMAS
        assert lv.TOOL_SCHEMAS[tool]["interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
        if operation in STABLE_OPERATIONS:
            assert lv.TOOL_SCHEMAS[tool]["returns"]["envelope"] == (
                "logic-verification-response/v1"
            )


def test_cli_parser_exposes_stable_and_discovery_commands() -> None:
    parser = create_parser()
    # Walk registered subparsers.
    actions = [
        action
        for action in parser._actions  # noqa: SLF001 — argparse has no public map
        if isinstance(action, argparse._SubParsersAction)  # type: ignore[attr-defined]
    ]
    assert actions, "CLI has no subparsers"
    choices = set(actions[0].choices or {})
    for command in STABLE_CLI_COMMANDS:
        assert command in choices, f"CLI missing verification command {command}"
    for command in DISCOVERY_CLI_COMMANDS:
        assert command in choices, f"CLI missing discovery command {command}"
    assert LOGIC_VERIFICATION_CLI_INTERFACE == "LogicVerificationCLI@1"
    assert lv.LOGIC_VERIFICATION_CLI_INTERFACE == LOGIC_VERIFICATION_CLI_INTERFACE


def test_goal_tactician_maps_are_bijective() -> None:
    surface = list_goal_tactician_cli_mcp_surface()
    assert surface["interface"] == GOAL_TACTICIAN_CLI_MCP_INTERFACE
    assert set(surface["operations"]) == set(GOAL_TACTICIAN_OPERATIONS)
    assert set(GOAL_TACTICIAN_TOOL_TO_OPERATION.values()) == set(GOAL_TACTICIAN_OPERATIONS)
    assert set(GOAL_TACTICIAN_CLI_TO_OPERATION.values()) == set(GOAL_TACTICIAN_OPERATIONS)
    assert set(GOAL_TACTICIAN_TOOL_TO_OPERATION) == set(GOAL_TACTICIAN_TOOL_NAMES)
    assert set(GOAL_TACTICIAN_CLI_TO_OPERATION) == set(GOAL_TACTICIAN_CLI_COMMANDS)
    assert len(GOAL_TACTICIAN_TOOL_TO_OPERATION) == len(GOAL_TACTICIAN_OPERATIONS)
    assert len(GOAL_TACTICIAN_CLI_TO_OPERATION) == len(GOAL_TACTICIAN_OPERATIONS)
    assert surface["transport_success_implies_proof_success"] is False
    assert set(surface["legacy_operations_preserved"]) == set(STABLE_OPERATIONS)
    # Forbidden supervisor-only controls stay out of public maps.
    forbidden = set(surface["forbidden_controls"])
    assert forbidden == {
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
    for name in forbidden:
        assert name not in GOAL_TACTICIAN_OPERATIONS
        assert name not in STABLE_OPERATIONS
        assert name not in lv.TOOL_TO_OPERATION
        assert name not in lv.TOOL_TO_OPERATION.values()


def test_status_and_authority_vocabularies_are_closed() -> None:
    assert {member.value for member in VerificationStatus} == {
        "succeeded",
        "partial",
        "unsupported",
        "unavailable",
        "invalid",
        "error",
        "declarative",
    }
    assert {member.value for member in VerificationAuthority} == {
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


# ---------------------------------------------------------------------------
# Live channel agreement (discovery / opt-in / envelope)
# ---------------------------------------------------------------------------


def test_list_providers_python_mcp_envelope_parity() -> None:
    api = get_verification_api(reset=True)
    py = api.list_providers().to_dict()
    _assert_envelope(py, operation="list_providers")
    assert py["status"] == "declarative"
    assert py["authority"] == "declarative"

    mcp = _run(lv.verification_list_providers())
    _assert_envelope(mcp, operation="list_providers")
    assert mcp["status"] == py["status"]
    assert mcp["authority"] == py["authority"]
    assert mcp["mcp_interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
    assert mcp["python_operation"] == "list_providers"
    py_ids = {item["provider_id"] for item in py["result"]["providers"]}
    mcp_ids = {item["provider_id"] for item in mcp["result"]["providers"]}
    assert py_ids == mcp_ids
    assert len(py_ids) >= 1


def test_verification_capabilities_projects_catalog_without_probe() -> None:
    caps = _run(lv.verification_capabilities())
    assert caps["status"] == "declarative"
    assert caps["authority"] == "declarative"
    assert set(caps["operations"]) == set(STABLE_OPERATIONS)
    assert set(caps["tools"]) == set(lv.TOOL_NAMES)
    assert caps["tool_to_operation"] == dict(lv.TOOL_TO_OPERATION)
    assert caps["bounds"] == {
        "max_json_bytes": 256_000,
        "max_string_chars": 64_000,
        "max_diagnostic_chars": 2_000,
        "max_result_depth": 12,
        "max_collection_items": 500,
    }
    # Presence of the catalog is not a live availability claim.
    assert "available_providers" not in caps
    assert caps.get("success") is True


def test_install_provider_requires_opt_in_and_is_not_verify() -> None:
    api = get_verification_api(reset=True)
    denied = api.install_provider("z3", allow_install=False)
    payload = denied.to_dict()
    _assert_envelope(payload, operation="install_provider")
    assert payload["status"] == "unsupported"
    assert "install_without_opt_in" in payload["unsupported_features"]
    assert payload["result"].get("install_attempted") is False
    # Never silently succeeds without opt-in.
    assert payload["status"] != "succeeded"

    dry = api.install_provider("z3", dry_run=True).to_dict()
    _assert_envelope(dry, operation="install_provider")
    assert dry["status"] == "declarative"
    assert dry["result"]["install_attempted"] is False
    assert dry["result"]["mutation_authorized"] is False


def test_mcp_install_without_opt_in_matches_python() -> None:
    api = get_verification_api(reset=True)
    py = api.install_provider("z3").to_dict()
    mcp = _run(lv.verification_install_provider(provider_id="z3", allow_install=False))
    _assert_envelope(py, operation="install_provider")
    _assert_envelope(mcp, operation="install_provider")
    assert mcp["status"] == py["status"] == "unsupported"
    assert "install_without_opt_in" in mcp["unsupported_features"]
    assert mcp["result"].get("install_attempted") is False


def test_list_features_declares_stable_operations() -> None:
    api = get_verification_api(reset=True)
    py = api.list_features().to_dict()
    _assert_envelope(py, operation="list_features")
    assert set(py["result"]["operations"]) >= set(STABLE_OPERATIONS)

    mcp = _run(lv.verification_list_features())
    _assert_envelope(mcp, operation="list_features")
    assert set(mcp["result"]["operations"]) >= set(STABLE_OPERATIONS)


@pytest.mark.parametrize(
    "tool,operation",
    [
        ("verification_list_logic_families", "list_logic_families"),
        ("verification_list_providers", "list_providers"),
        ("verification_provider_capabilities", "provider_capabilities"),
    ],
)
def test_discovery_mcp_tools_use_python_operation_name(
    tool: str, operation: str
) -> None:
    handler = getattr(lv, tool)
    payload = _run(handler())
    _assert_envelope(payload, operation=operation)
    assert payload["python_operation"] == operation
    assert payload["status"] in {"declarative", "succeeded", "partial"}
    # Discovery must not upgrade to theorem/proof authority.
    assert payload["authority"] in {
        "none",
        "advisory",
        "declarative",
        "bounded",
    }


def test_goal_tactician_list_operations_channel_parity() -> None:
    from ipfs_datasets_py.logic.verification_api import (
        invoke_goal_tactician,
        invoke_goal_tactician_cli,
        invoke_goal_tactician_mcp_tool,
    )

    py = invoke_goal_tactician("list_goal_tactician_operations").to_dict()
    mcp = invoke_goal_tactician_mcp_tool("goal_tactician_list_operations")
    cli = invoke_goal_tactician_cli("goal-list-operations")
    for payload, channel in ((py, "python"), (mcp, "mcp"), (cli, "cli")):
        _assert_envelope(payload, operation="list_goal_tactician_operations")
        assert payload["status"] == "declarative"
        assert set(payload["result"]["operations"]) == set(GOAL_TACTICIAN_OPERATIONS)
        if channel != "python":
            assert payload["channel"] == channel
            assert payload["python_operation"] == "list_goal_tactician_operations"


def test_goal_tactician_refuses_supervisor_only_controls() -> None:
    from ipfs_datasets_py.logic.verification_api import (
        invoke_goal_tactician,
        invoke_goal_tactician_cli,
        invoke_goal_tactician_mcp_tool,
    )

    request = {
        "plan_id": "plan:forbidden",
        "steps": [{"step_id": "s", "obligation_id": "o", "statement": "x"}],
        "controls": {"mutate_supervisor": True},
    }
    py = invoke_goal_tactician("execute_proof_plan", request).to_dict()
    mcp = invoke_goal_tactician_mcp_tool(
        "goal_tactician_execute_proof_plan", request
    )
    cli = invoke_goal_tactician_cli("goal-execute-plan", request)
    for payload in (py, mcp, cli):
        assert payload["status"] == "invalid"
        assert "supervisor_only_control" in payload["unsupported_features"]
