"""Integration tests for CLI + MCP software-verification operations (LFV-G071).

Acceptance coverage for ``LogicVerificationCLI@1`` / ``LogicVerificationMCP@1``:

* CLI/MCP cover list, capability, compile, check, monitor, portfolio,
  counterexample, receipt, advisor, and attestation operations;
* schemas match the Python ``LogicVerificationAPI@1`` envelope;
* inputs/outputs are bounded;
* errors and unavailable tools are stable and secret-safe;
* existing logic CLI command names remain registered.
"""

from __future__ import annotations

import json
import re
from typing import Any

import anyio
import pytest

from ipfs_datasets_py.logic import cli as logic_cli
from ipfs_datasets_py.logic.verification_api import (
    LOGIC_VERIFICATION_API_INTERFACE,
    STABLE_OPERATIONS,
    get_verification_api,
)
from ipfs_datasets_py.mcp_server.tools import logic_verification as lv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _assert_python_envelope(payload: dict[str, Any], *, operation: str | None = None) -> None:
    missing = ENVELOPE_KEYS - set(payload)
    assert not missing, f"missing envelope keys: {sorted(missing)}"
    assert payload["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert isinstance(payload["status"], str) and payload["status"]
    assert isinstance(payload["authority"], str)
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
        assert payload.get("python_operation") in {None, operation, payload["operation"]}


def _run(coro):
    return anyio.run(lambda: coro)


def _cli(argv: list[str]) -> dict[str, Any]:
    ns = logic_cli.create_parser().parse_args(argv)
    data = anyio.run(logic_cli._run_async, ns)
    assert isinstance(data, dict)
    return data


# ---------------------------------------------------------------------------
# Discovery / registration
# ---------------------------------------------------------------------------


def test_mcp_module_interfaces_and_tool_surface() -> None:
    assert lv.LOGIC_VERIFICATION_MCP_INTERFACE == "LogicVerificationMCP@1"
    assert lv.LOGIC_VERIFICATION_CLI_INTERFACE == "LogicVerificationCLI@1"
    assert set(lv.TOOL_NAMES) >= {
        "verification_list_features",
        "verification_list_logic_families",
        "verification_list_providers",
        "verification_provider_capabilities",
        "verification_compile",
        "verification_check",
        "verification_monitor",
        "verification_portfolio",
        "verification_explain_counterexample",
        "verification_verify_receipt",
        "verification_advise",
        "verification_attest_receipt",
    }
    schemas = lv.list_tools()
    assert len(schemas) == len(lv.TOOL_NAMES)
    for schema in schemas:
        assert schema["interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
        assert "python_operation" in schema
        assert schema["name"] in lv.TOOL_SCHEMAS

    # Python STABLE_OPERATIONS are all represented in MCP tool mapping.
    mapped = set(lv.TOOL_TO_OPERATION.values())
    for operation in STABLE_OPERATIONS:
        assert operation in mapped, f"missing MCP mapping for {operation}"


def test_tools_package_lazy_exports_logic_verification() -> None:
    import ipfs_datasets_py.mcp_server.tools as tools_pkg
    import ipfs_datasets_py.mcp_server.tools.logic_tools as logic_tools

    assert "logic_verification" in tools_pkg.__all__
    module = tools_pkg.logic_verification
    assert module.LOGIC_VERIFICATION_MCP_INTERFACE == "LogicVerificationMCP@1"
    assert callable(logic_tools.verification_list_providers)
    assert callable(logic_tools.verification_check)


def test_cli_preserves_legacy_commands_and_adds_verification() -> None:
    parser = logic_cli.create_parser()
    # Legacy commands must remain.
    for name in (
        "convert-fol",
        "convert-deontic",
        "analyze-normative",
        "add-theorem",
        "query-theorems",
        "check-document",
    ):
        assert name in parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]

    # Verification commands (LFV-G071).
    for name in (
        "list-features",
        "list-families",
        "list-providers",
        "provider-capabilities",
        "compile",
        "check",
        "monitor",
        "portfolio",
        "counterexample",
        "verify-receipt",
        "advise",
        "attest-receipt",
        "probe-provider",
        "install-provider",
        "verification-capabilities",
    ):
        assert name in parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]

    assert logic_cli.LOGIC_VERIFICATION_CLI_INTERFACE == "LogicVerificationCLI@1"


# ---------------------------------------------------------------------------
# List / capability operations
# ---------------------------------------------------------------------------


def test_mcp_list_and_capability_match_python() -> None:
    python_api = get_verification_api(reset=True)
    py_families = python_api.list_logic_families().to_dict()
    mcp_families = _run(lv.verification_list_logic_families())
    _assert_python_envelope(mcp_families, operation="list_logic_families")
    assert mcp_families["status"] == py_families["status"]
    assert mcp_families["result"]["count"] == py_families["result"]["count"]
    assert mcp_families["success"] is True

    py_providers = python_api.list_providers().to_dict()
    mcp_providers = _run(lv.verification_list_providers())
    _assert_python_envelope(mcp_providers, operation="list_providers")
    assert mcp_providers["result"]["count"] == py_providers["result"]["count"]

    mcp_caps = _run(lv.verification_provider_capabilities())
    _assert_python_envelope(mcp_caps, operation="provider_capabilities")
    assert mcp_caps["status"] == "declarative"
    assert mcp_caps["result"]["count"] >= 2

    missing = _run(lv.verification_provider_capabilities(provider_id="not-a-backend"))
    assert missing["status"] == "unsupported"
    assert "provider:not-a-backend" in missing["unsupported_features"]

    features = _run(lv.verification_list_features())
    _assert_python_envelope(features, operation="list_features")
    assert set(features["result"]["operations"]) >= set(STABLE_OPERATIONS)

    meta = _run(lv.verification_capabilities())
    assert meta["success"] is True
    assert meta["mcp_interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
    assert meta["cli_interface"] == lv.LOGIC_VERIFICATION_CLI_INTERFACE
    assert "max_json_bytes" in meta["bounds"]


def test_cli_list_and_capability() -> None:
    families = _cli(["list-families"])
    _assert_python_envelope(families, operation="list_logic_families")
    assert families["result"]["count"] >= 1

    providers = _cli(["list-providers"])
    _assert_python_envelope(providers, operation="list_providers")
    provider_ids = {item["provider_id"] for item in providers["result"]["providers"]}
    assert {"z3", "cvc5"} <= provider_ids or providers["result"]["count"] >= 1

    caps = _cli(["provider-capabilities"])
    _assert_python_envelope(caps, operation="provider_capabilities")

    features = _cli(["list-features"])
    _assert_python_envelope(features, operation="list_features")

    v_caps = _cli(["verification-capabilities"])
    assert v_caps["success"] is True
    assert v_caps["cli_interface"] == logic_cli.LOGIC_VERIFICATION_CLI_INTERFACE


# ---------------------------------------------------------------------------
# Compile / check / portfolio / counterexample
# ---------------------------------------------------------------------------


def test_mcp_compile_check_portfolio_counterexample() -> None:
    compiled = _run(
        lv.verification_compile(
            {"obligation_id": "obl:cli-mcp", "statement": "true"},
            request_id="req:compile",
        )
    )
    _assert_python_envelope(compiled, operation="compile_verification_artifact")
    assert compiled["status"] in {"succeeded", "partial", "unavailable", "error"}
    if compiled["status"] in {"succeeded", "partial"}:
        assert compiled["result"]["obligation_id"] == "obl:cli-mcp"
        assert "compilation" in compiled["result"]

    unsupported = _run(
        lv.verification_compile(
            {"obligation_id": "obl:x"},
            target="not-a-target",
        )
    )
    assert unsupported["status"] == "unsupported"
    assert "compile_target:not-a-target" in unsupported["unsupported_features"]

    checked = _run(
        lv.verification_check(
            {
                "statement": "(assert true)",
                "source": "(assert true)",
                "logic_family": "first_order",
                "query_kind": "satisfiability",
                "assumption_ids": ("env:trusted",),
            },
            request_id="req:check",
        )
    )
    _assert_python_envelope(checked, operation="check")
    assert checked["status"] in {
        "succeeded",
        "unavailable",
        "error",
        "unsupported",
        "partial",
    }
    assert "assumptions" in checked

    portfolio = _run(
        lv.verification_portfolio(
            {
                "obligation_id": "obl:portfolio",
                "property_kind": "satisfiability",
                "statement": "P",
                "assumption_ids": ("a:1",),
            }
        )
    )
    _assert_python_envelope(portfolio, operation="run_portfolio")
    assert portfolio["status"] in {"succeeded", "partial", "unavailable", "error"}
    if portfolio["status"] in {"succeeded", "partial"}:
        assert portfolio["result"]["attempt_count"] >= 1
        assert portfolio["assumptions"] == ["a:1"]

    explained = _run(
        lv.verification_explain_counterexample(
            {"kind": "model", "model": {"x": "1"}, "summary": "x assigned 1"}
        )
    )
    _assert_python_envelope(explained, operation="explain_counterexample")
    assert explained["status"] == "succeeded"
    assert explained["result"]["model"] == {"x": "1"}
    assert explained["witnesses"]


def test_cli_compile_check_portfolio_counterexample() -> None:
    compiled = _cli(
        [
            "compile",
            "--artifact",
            json.dumps({"obligation_id": "obl:cli", "statement": "true"}),
            "--request-id",
            "req:cli-compile",
        ]
    )
    _assert_python_envelope(compiled, operation="compile_verification_artifact")

    checked = _cli(
        [
            "check",
            "--request",
            json.dumps(
                {
                    "statement": "(assert true)",
                    "logic_family": "first_order",
                    "query_kind": "satisfiability",
                }
            ),
        ]
    )
    _assert_python_envelope(checked, operation="check")

    portfolio = _cli(
        [
            "portfolio",
            "--obligation",
            json.dumps(
                {
                    "obligation_id": "obl:p",
                    "property_kind": "satisfiability",
                    "statement": "P",
                }
            ),
        ]
    )
    _assert_python_envelope(portfolio, operation="run_portfolio")

    cex = _cli(
        [
            "counterexample",
            "--witness",
            json.dumps({"kind": "model", "model": {"y": "2"}, "summary": "y=2"}),
        ]
    )
    _assert_python_envelope(cex, operation="explain_counterexample")
    assert cex["status"] == "succeeded"


# ---------------------------------------------------------------------------
# Monitor / receipt / advisor / attestation
# ---------------------------------------------------------------------------


def test_mcp_monitor_receipt_advisor_attestation() -> None:
    formula = {"operator": "atom", "proposition": "p"}
    observations = {
        "clock": {"clock_id": "c1"},
        "events": [
            {
                "event_id": "e1",
                "event_type": "obs",
                "time": 0,
                "true_propositions": ["p"],
            }
        ],
        "kind": "finite",
    }
    monitored = _run(
        lv.verification_monitor(formula, observations, request_id="req:mon")
    )
    _assert_python_envelope(monitored, operation="monitor")
    assert monitored["status"] in {"succeeded", "invalid", "unavailable", "error"}
    if monitored["status"] == "succeeded":
        assert monitored["authority"] == "monitor"
        assert "verdict" in monitored["result"]

    receipt = _run(
        lv.verification_verify_receipt(
            {
                "receipt_id": "rcpt:1",
                "authority": "bounded",
                "digest": "a" * 64,
                "kind": "proof_receipt",
            }
        )
    )
    _assert_python_envelope(receipt, operation="verify_receipt")
    assert receipt["status"] == "succeeded"
    assert receipt["authority"] == "bounded"

    missing = _run(lv.verification_verify_receipt(None))
    assert missing["status"] == "invalid"
    assert "receipt" in missing["unsupported_features"]

    advised = _run(
        lv.verification_advise({"goal_text": "prove P -> Q"}, provider="static")
    )
    _assert_python_envelope(advised, operation="advise")
    assert advised["status"] == "succeeded"
    assert advised["authority"] == "advisory"
    assert "never" in advised["result"]["authority_note"].lower()

    unknown = _run(
        lv.verification_advise({"goal_text": "prove P"}, provider="not-real")
    )
    assert unknown["status"] == "unsupported"
    assert "advisor:not-real" in unknown["unsupported_features"]

    disabled = _run(
        lv.verification_attest_receipt(
            {"receipt_id": "r"},
            backend_mode="disabled",
        )
    )
    _assert_python_envelope(disabled, operation="attest_receipt")
    assert disabled["status"] == "unavailable"
    assert "attestation_backend" in disabled["unsupported_features"]

    no_install = _run(lv.verification_install_provider("z3"))
    assert no_install["status"] == "unsupported"
    assert "install_without_opt_in" in no_install["unsupported_features"]

    probe = _run(lv.verification_probe_provider("z3"))
    _assert_python_envelope(probe, operation="probe_provider")
    assert probe["status"] in {"succeeded", "unavailable", "unsupported", "error"}


def test_cli_monitor_receipt_advisor_attestation() -> None:
    monitored = _cli(
        [
            "monitor",
            "--formula",
            json.dumps({"operator": "atom", "proposition": "p"}),
            "--observations",
            json.dumps(
                {
                    "clock": {"clock_id": "c1"},
                    "events": [
                        {
                            "event_id": "e1",
                            "event_type": "obs",
                            "time": 0,
                            "true_propositions": ["p"],
                        }
                    ],
                    "kind": "finite",
                }
            ),
        ]
    )
    _assert_python_envelope(monitored, operation="monitor")

    receipt = _cli(
        [
            "verify-receipt",
            "--receipt",
            json.dumps(
                {
                    "receipt_id": "rcpt:cli",
                    "authority": "bounded",
                    "digest": "b" * 64,
                }
            ),
        ]
    )
    _assert_python_envelope(receipt, operation="verify_receipt")
    assert receipt["status"] == "succeeded"

    advised = _cli(
        [
            "advise",
            "--request",
            json.dumps({"goal_text": "prove Q"}),
            "--provider",
            "static",
        ]
    )
    _assert_python_envelope(advised, operation="advise")
    assert advised["authority"] == "advisory"

    attest = _cli(
        [
            "attest-receipt",
            "--receipt",
            json.dumps({"receipt_id": "r"}),
            "--backend-mode",
            "disabled",
        ]
    )
    _assert_python_envelope(attest, operation="attest_receipt")
    assert attest["status"] == "unavailable"

    install = _cli(["install-provider", "z3"])
    assert install["status"] == "unsupported"


# ---------------------------------------------------------------------------
# Bounds, secret safety, schema parity
# ---------------------------------------------------------------------------


def test_inputs_are_bounded() -> None:
    huge = "x" * (lv.MAX_JSON_BYTES + 100)
    with pytest.raises(ValueError, match="max JSON size"):
        lv._parse_jsonish(huge, "payload")

    oversize_map = {"blob": "y" * (lv.MAX_JSON_BYTES // 2 + 1)}
    # Nested estimate may or may not exceed depending on encoding; force large.
    oversize_map = {"blob": "z" * (lv.MAX_JSON_BYTES + 10)}
    with pytest.raises(ValueError, match="max JSON size"):
        lv._parse_jsonish(oversize_map, "payload")


def test_errors_are_stable_and_secret_safe() -> None:
    # Invalid JSON string path via MCP helper.
    bad = _run(lv.verification_check("not-json{{{"))
    assert bad["success"] is False
    assert bad["status"] == "invalid"
    assert "error" in bad or bad["diagnostics"]

    # Diagnostics redact secret-like tokens.
    redacted = lv._redact_text("Authorization: Bearer sk-super-secret-token-value-12345")
    assert "sk-super-secret" not in redacted.lower() or "[REDACTED]" in redacted
    assert "Bearer sk-super" not in redacted
    assert "[REDACTED]" in redacted or "bearer [REDACTED]" in redacted.lower()

    api_key = lv._redact_text("api_key=abcd1234secret")
    assert "abcd1234secret" not in api_key
    assert "[REDACTED]" in api_key

    # Envelope from facade never upgrades authority on disabled attestation.
    disabled = _run(
        lv.verification_attest_receipt(
            {"receipt_id": "r", "authority": "theorem"},
            backend_mode="disabled",
        )
    )
    assert disabled["status"] == "unavailable"
    # Authority ceiling for attestation path is attestation, never theorem upgrade.
    assert disabled["authority"] in {"attestation", "none"}


def test_cli_main_returns_zero_for_list_providers(capsys) -> None:
    code = logic_cli.main(["--json", "list-providers"])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["operation"] == "list_providers"
    assert payload["status"] == "declarative"


def test_cli_main_invalid_json_is_stable(capsys) -> None:
    code = logic_cli.main(["check", "--request", "{not-json"])
    assert code == 2
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["success"] is False
    assert "error" in payload
    # No traceback secrets.
    assert "Traceback" not in out


def test_schema_operation_names_match_python() -> None:
    for tool_name, operation in lv.TOOL_TO_OPERATION.items():
        if tool_name == "verification_capabilities":
            continue
        schema = lv.get_tool_schema(tool_name)
        assert schema is not None
        assert schema["python_operation"] == operation
        # Python facade still exposes the operation (list_features is method-only).
        if operation == "list_features":
            assert hasattr(get_verification_api(), "list_features")
        else:
            assert operation in STABLE_OPERATIONS or hasattr(
                get_verification_api(), operation
            )


def test_bounded_result_depth() -> None:
    nested: Any = "leaf"
    for _ in range(lv.MAX_RESULT_DEPTH + 5):
        nested = {"child": nested}
    bounded = lv._bound_value(nested)
    # Walk until truncation marker or depth limit.
    depth = 0
    cursor = bounded
    while isinstance(cursor, dict) and "child" in cursor:
        cursor = cursor["child"]
        depth += 1
        if depth > lv.MAX_RESULT_DEPTH + 2:
            break
    assert depth <= lv.MAX_RESULT_DEPTH + 1
    # Either truncated or leaf string.
    assert cursor == "leaf" or (
        isinstance(cursor, dict) and cursor.get("_truncated") == "max_depth"
    )


def test_mcp_cli_parity_for_providers() -> None:
    mcp = _run(lv.verification_list_providers())
    cli = _cli(["list-providers"])
    assert mcp["status"] == cli["status"]
    assert mcp["result"]["count"] == cli["result"]["count"]
    assert mcp["interface"] == cli["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert mcp["mcp_interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
    assert cli["mcp_interface"] == lv.LOGIC_VERIFICATION_MCP_INTERFACE
