"""LPC-130 unit gate: LogicOperationCatalog@1 channel parity.

Asserts that Python ``LogicVerificationAPI@1``, CLI
``LogicVerificationCLI@1``, and MCP ``LogicVerificationMCP@1`` share one
closed operation catalog: names, envelope identity, status/authority
vocabularies, opt-in flags, install boundary, and supervisor-control refusal.
"""

from __future__ import annotations

from typing import Any

import anyio
import pytest

from ipfs_datasets_py.logic import cli as logic_cli
from ipfs_datasets_py.logic.verification_api import (
    FeatureAvailability,
    LOGIC_VERIFICATION_API_INTERFACE,
    STABLE_OPERATIONS,
    VerificationAuthority,
    VerificationStatus,
    get_verification_api,
    list_stable_features,
)
from ipfs_datasets_py.mcp_server.tools import logic_verification as lv


ENVELOPE_KEYS = {
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

# Closed CLI projection of STABLE_OPERATIONS (+ discovery helpers).
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
        "check",
        "verify_receipt",
        "run_portfolio",
        "compile_verification_artifact",
        "monitor",
        "explain_counterexample",
        "advise",
    }
)

SUPERVISOR_ONLY_CONTROLS = (
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
)


def _assert_envelope(payload: dict[str, Any], *, operation: str | None = None) -> None:
    missing = ENVELOPE_KEYS - set(payload)
    assert not missing, f"missing envelope keys: {sorted(missing)}"
    assert payload["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert isinstance(payload["status"], str) and payload["status"]
    assert payload["status"] in {item.value for item in VerificationStatus}
    assert isinstance(payload["authority"], str)
    assert payload["authority"] in {item.value for item in VerificationAuthority}
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


def _run(coro):
    return anyio.run(lambda: coro)


def _cli(argv: list[str]) -> dict[str, Any]:
    ns = logic_cli.create_parser().parse_args(argv)
    data = anyio.run(logic_cli._run_async, ns)
    assert isinstance(data, dict)
    return data


def test_interface_identities_and_catalog_constants() -> None:
    assert LOGIC_VERIFICATION_API_INTERFACE == "LogicVerificationAPI@1"
    assert logic_cli.LOGIC_VERIFICATION_CLI_INTERFACE == "LogicVerificationCLI@1"
    assert lv.LOGIC_VERIFICATION_MCP_INTERFACE == "LogicVerificationMCP@1"
    assert lv.LOGIC_VERIFICATION_CLI_INTERFACE == "LogicVerificationCLI@1"
    assert set(STABLE_OPERATIONS) == {
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
    }


def test_mcp_tool_map_covers_stable_operations() -> None:
    mapped = set(lv.TOOL_TO_OPERATION.values())
    for operation in STABLE_OPERATIONS:
        assert operation in mapped, f"MCP missing mapping for {operation}"

    for tool, operation in lv.TOOL_TO_OPERATION.items():
        assert tool in lv.TOOL_NAMES
        schema = lv.TOOL_SCHEMAS[tool]
        assert schema["interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
        assert schema["python_operation"] == operation
        assert schema["returns"]["envelope"] == "logic-verification-response/v1"


def test_cli_commands_cover_stable_operations() -> None:
    parser = logic_cli.create_parser()
    choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
    for command in CLI_TO_OPERATION:
        assert command in choices, f"CLI missing command {command}"

    # Every stable operation has a CLI projection.
    projected = set(CLI_TO_OPERATION.values())
    for operation in STABLE_OPERATIONS:
        assert operation in projected, f"CLI missing projection for {operation}"


def test_list_stable_features_opt_in_and_authority_ceilings() -> None:
    features = {item.feature_id: item for item in list_stable_features()}
    for operation in STABLE_OPERATIONS:
        assert operation in features, f"list_stable_features missing {operation}"

    for operation in ("probe_provider", "install_provider", "attest_receipt"):
        descriptor = features[operation]
        assert descriptor.availability is FeatureAvailability.OPT_IN
        assert descriptor.requires_opt_in is True

    assert features["install_provider"].authority_ceiling is VerificationAuthority.NONE
    assert features["probe_provider"].authority_ceiling is VerificationAuthority.NONE
    assert features["attest_receipt"].authority_ceiling is VerificationAuthority.ATTESTATION
    assert features["check"].availability is FeatureAvailability.DECLARED
    assert features["check"].requires_opt_in is False
    assert features["check"].authority_ceiling is VerificationAuthority.BOUNDED


def test_list_features_superset_of_stable_operations() -> None:
    api = get_verification_api(reset=True)
    py = api.list_features().to_dict()
    _assert_envelope(py, operation="list_features")
    assert set(py["result"]["operations"]) >= set(STABLE_OPERATIONS)

    mcp = _run(lv.verification_list_features())
    _assert_envelope(mcp, operation="list_features")
    assert set(mcp["result"]["operations"]) >= set(STABLE_OPERATIONS)
    assert mcp["status"] == py["status"]
    assert mcp["authority"] == py["authority"]

    cli = _cli(["list-features"])
    _assert_envelope(cli, operation="list_features")
    assert set(cli["result"]["operations"]) >= set(STABLE_OPERATIONS)
    assert cli["status"] == py["status"]
    assert cli["authority"] == py["authority"]


def test_discovery_parity_python_cli_mcp() -> None:
    api = get_verification_api(reset=True)
    py = api.list_providers().to_dict()
    mcp = _run(lv.verification_list_providers())
    cli = _cli(["list-providers"])

    for payload, operation in (
        (py, "list_providers"),
        (mcp, "list_providers"),
        (cli, "list_providers"),
    ):
        _assert_envelope(payload, operation=operation)

    assert py["status"] == mcp["status"] == cli["status"] == "declarative"
    assert py["authority"] == mcp["authority"] == cli["authority"]
    assert py["result"]["count"] == mcp["result"]["count"] == cli["result"]["count"]
    py_ids = {item["provider_id"] for item in py["result"]["providers"]}
    mcp_ids = {item["provider_id"] for item in mcp["result"]["providers"]}
    cli_ids = {item["provider_id"] for item in cli["result"]["providers"]}
    assert py_ids == mcp_ids == cli_ids


def test_installation_is_not_ordinary_verify_operation() -> None:
    api = get_verification_api(reset=True)

    # install_provider is in the closed catalog but opt-in / authority-none.
    assert "install_provider" in STABLE_OPERATIONS
    assert "install_provider" not in ORDINARY_VERIFY_OPERATIONS
    features = {item.feature_id: item for item in list_stable_features()}
    install = features["install_provider"]
    assert install.requires_opt_in is True
    assert install.authority_ceiling is VerificationAuthority.NONE

    denied = api.install_provider("z3").to_dict()
    _assert_envelope(denied, operation="install_provider")
    assert denied["status"] == "unsupported"
    assert denied["authority"] == "none"
    assert "install_without_opt_in" in denied["unsupported_features"]

    mcp_denied = _run(lv.verification_install_provider("z3"))
    _assert_envelope(mcp_denied, operation="install_provider")
    assert mcp_denied["status"] == "unsupported"
    assert "install_without_opt_in" in mcp_denied["unsupported_features"]
    assert mcp_denied["authority"] == "none"

    cli_denied = _cli(["install-provider", "z3"])
    _assert_envelope(cli_denied, operation="install_provider")
    assert cli_denied["status"] == "unsupported"
    assert "install_without_opt_in" in cli_denied["unsupported_features"]
    assert cli_denied["authority"] == "none"

    planned = api.install_provider("z3", allow_install=True, dry_run=True).to_dict()
    _assert_envelope(planned, operation="install_provider")
    assert planned["status"] == "declarative"
    assert planned["authority"] == "none"
    assert planned["result"]["install_attempted"] is False

    # MCP/CLI must not alias install onto check or verify_receipt.
    assert lv.TOOL_TO_OPERATION["verification_install_provider"] == "install_provider"
    assert lv.TOOL_TO_OPERATION["verification_check"] == "check"
    assert lv.TOOL_TO_OPERATION["verification_verify_receipt"] == "verify_receipt"
    assert CLI_TO_OPERATION["install-provider"] == "install_provider"
    assert CLI_TO_OPERATION["check"] == "check"
    assert CLI_TO_OPERATION["verify-receipt"] == "verify_receipt"


def test_mcp_live_install_requires_host_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_MCP_ALLOW_PROVIDER_INSTALLS", raising=False)
    denied = _run(lv.verification_install_provider("z3", allow_install=True))
    assert denied["status"] == "unsupported"
    assert "mcp_provider_install_operator_policy" in denied["unsupported_features"]


def test_supervisor_only_controls_refused_on_public_api() -> None:
    api = get_verification_api(reset=True)
    forbidden = api.execute_proof_plan(
        {
            "plan_id": "plan:bad",
            "steps": [{"step_id": "s", "obligation_id": "o"}],
            "controls": {name: True for name in SUPERVISOR_ONLY_CONTROLS[:3]},
        }
    ).to_dict()
    _assert_envelope(forbidden, operation="execute_proof_plan")
    assert forbidden["status"] == "invalid"
    assert "supervisor_only_control" in forbidden["unsupported_features"]

    # Supervisor mutation controls are not MCP verification tools or CLI commands.
    tool_ops = set(lv.TOOL_TO_OPERATION.values()) | set(lv.TOOL_NAMES)
    cli_choices = set(
        logic_cli.create_parser()._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
    )
    for control in SUPERVISOR_ONLY_CONTROLS:
        assert control not in STABLE_OPERATIONS
        assert control not in tool_ops
        assert control not in cli_choices
        assert control.replace("_", "-") not in cli_choices


def test_failure_codes_agree_for_unknown_provider() -> None:
    api = get_verification_api(reset=True)
    py = api.provider_capabilities("not-a-backend").to_dict()
    mcp = _run(lv.verification_provider_capabilities(provider_id="not-a-backend"))
    cli = _cli(["provider-capabilities", "--provider-id", "not-a-backend"])

    for payload in (py, mcp, cli):
        _assert_envelope(payload, operation="provider_capabilities")
        assert payload["status"] == "unsupported"
        assert "provider:not-a-backend" in payload["unsupported_features"]
