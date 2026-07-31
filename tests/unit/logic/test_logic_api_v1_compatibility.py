"""Executable compatibility contract for the reviewed logic API v1 surface."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import subprocess
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "tests" / "fixtures" / "logic" / "api_v1" / "manifest.json"
DOC_PATH = REPO_ROOT / "docs" / "logic" / "logic_api_v1_compatibility.md"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _enum_pairs(enum_type: Any) -> list[list[str]]:
    return [[member.name, member.value] for member in enum_type]


def _cli_contract() -> dict[str, list[dict[str, Any]]]:
    from ipfs_datasets_py.logic.cli import create_parser

    parser = create_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    observed: dict[str, list[dict[str, Any]]] = {}
    for command, command_parser in subparsers.choices.items():
        observed[command] = [
            {
                "dest": action.dest,
                "required": action.required,
                "default": action.default,
                "choices": list(action.choices) if action.choices is not None else None,
                "type": getattr(action.type, "__name__", None),
                "options": list(action.option_strings),
            }
            for action in command_parser._actions
            if action.dest != "help"
        ]
    return observed


def test_manifest_is_complete_and_documented() -> None:
    assert list(MANIFEST) == [
        "schema_version",
        "interface",
        "description",
        "review_scope",
        "python_api",
        "canonical_payloads",
        "cli",
        "mcp",
        "lazy_imports",
        "authority_semantics",
        "documentation_anchors",
    ]
    assert MANIFEST["schema_version"] == "logic-api-compatibility-manifest/v1"
    assert MANIFEST["interface"] == "LogicAPICompatibility@1"
    assert MANIFEST["review_scope"]["families"] == [
        "fol",
        "deontic",
        "modal",
        "cec_dcec",
        "tdfol",
        "flogic",
    ]
    assert MANIFEST["review_scope"]["access_paths"] == ["python", "cli", "mcp"]

    documentation = DOC_PATH.read_text(encoding="utf-8")
    for anchor in MANIFEST["documentation_anchors"]:
        assert anchor in documentation
    for required_term in (
        "FOL",
        "deontic",
        "modal",
        "CEC/DCEC",
        "TDFOL",
        "FLogic",
        "cache",
        "ZKP",
        "CLI",
        "MCP",
        "unavailable",
    ):
        assert required_term in documentation


def test_stable_api_exports_and_family_imports() -> None:
    api_contract = MANIFEST["python_api"]
    api = importlib.import_module(api_contract["module"])
    assert api.__all__ == api_contract["exact_exports"]

    for contract in api_contract["family_contracts"].values():
        module = importlib.import_module(contract["module"])
        declared = set(getattr(module, "__all__", ()))
        lazy_symbols = set(contract.get("lazy_optional_symbols", ()))
        for symbol in contract["symbols"]:
            assert symbol in declared or hasattr(module, symbol)
            if not contract.get("lazy") and symbol not in lazy_symbols:
                assert getattr(module, symbol) is not None

    from ipfs_datasets_py.logic import api as package_api
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        Constant,
        Formula,
        Predicate,
        ProofResult,
        ProofStatus,
        ProofStep,
        Variable,
    )

    assert package_api.Formula is Formula
    assert package_api.Predicate is Predicate
    assert package_api.Variable is Variable
    assert package_api.Constant is Constant
    assert package_api.ProofResult is ProofResult
    assert package_api.ProofStatus is ProofStatus
    assert package_api.ProofStep is ProofStep

    from ipfs_datasets_py.logic.modal.compiler import ModalCompilerConfig

    assert [item.name for item in fields(ModalCompilerConfig)] == (
        api_contract["family_contracts"]["modal"]["config_fields"]
    )


def test_operator_values_and_representative_tdfol_payloads() -> None:
    from ipfs_datasets_py.logic.api import DeonticOperator, TemporalOperator
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        Constant,
        Predicate,
        ProofResult,
        ProofStatus,
        Variable,
        create_implication,
        create_negation,
        create_universal,
    )

    expected = MANIFEST["canonical_payloads"]
    assert _enum_pairs(DeonticOperator) == expected["operator_values"]["deontic"]
    assert _enum_pairs(TemporalOperator) == expected["operator_values"]["temporal"]
    assert _enum_pairs(ProofStatus) == expected["operator_values"]["proof_status"]

    authorized_alice = Predicate("Authorized", (Constant("alice"),))
    audited_alice = Predicate("Audited", (Constant("alice"),))
    x = Variable("x")
    authorized_x = Predicate("Authorized", (x,))
    audited_x = Predicate("Audited", (x,))
    observed_formulas = {
        "predicate": str(authorized_alice),
        "negation": str(create_negation(authorized_alice)),
        "implication": str(create_implication(authorized_alice, audited_alice)),
        "universal": str(
            create_universal(x, create_implication(authorized_x, audited_x))
        ),
    }
    assert observed_formulas == expected["tdfol_formula"]

    result = ProofResult(
        status=ProofStatus.UNKNOWN,
        formula=authorized_alice,
        method="compatibility_fixture",
        message="optional prover unavailable",
    )
    assert {
        "status": result["status"],
        "proved": result.is_proved(),
        "disproved": result.is_disproved(),
        "conclusive": result.is_conclusive(),
        "method": result["method"],
        "strategy": result["strategy"],
        "time_ms": result["time_ms"],
        "message": result["message"],
        "proof_step_count": len(result["proof_steps"]),
    } == expected["proof_result_unknown"]


def test_flogic_cache_and_zkp_payloads_preserve_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.logic.common import CachedProofResult, ProofCache
    from ipfs_datasets_py.logic.flogic import (
        FLogicClass,
        FLogicFrame,
        FLogicProvingMethod,
        FLogicStatus,
        ZKPFLogicResult,
    )
    import ipfs_datasets_py.logic.zkp as zkp
    from ipfs_datasets_py.logic.zkp import SimulatedZKPProof, ZKPProof

    expected = MANIFEST["canonical_payloads"]
    assert _enum_pairs(FLogicStatus) == expected["operator_values"]["flogic_status"]
    assert _enum_pairs(FLogicProvingMethod) == expected["operator_values"]["flogic_method"]
    assert (
        FLogicFrame(
            "rex",
            scalar_methods={"name": "Rex"},
            set_methods={"friend": ["max"]},
            isa="Dog",
        ).to_ergo_string()
        == expected["flogic_frame"]
    )
    assert (
        FLogicClass(
            "Dog",
            superclasses=["Animal"],
            signature_methods={"name": "string"},
        ).to_ergo_string()
        == expected["flogic_class"]
    )

    flogic_result = ZKPFLogicResult(
        goal="?X : Dog",
        status=FLogicStatus.UNKNOWN,
        method=FLogicProvingMethod.CACHED,
        from_cache=True,
        error_message="optional ErgoAI binary unavailable",
        timestamp=0.0,
    )
    assert flogic_result.to_dict() == expected["flogic_result"]

    cached = CachedProofResult(
        result={"status": "unknown", "authority": "untrusted"},
        timestamp=0.0,
        **{
            key: value
            for key, value in expected["cached_proof_metadata"].items()
            if key != "timestamp"
        },
    )
    assert cached.to_dict() == expected["cached_proof_metadata"]

    cache = ProofCache(maxsize=2, ttl=60)
    original = {"status": "unknown", "authority": "untrusted"}
    cache.set("Authorized(alice)", original, prover_name="compat-prover")
    assert cache.get("Authorized(alice)", prover_name="compat-prover") == original
    assert cache.get("Authorized(alice)", prover_name="compat-prover") is original
    assert MANIFEST["authority_semantics"]["cache"]["authority_increase"] is False

    assert SimulatedZKPProof is ZKPProof
    monkeypatch.setattr(zkp, "_WARNED", False)
    with pytest.warns(UserWarning, match="SIMULATION"):
        proof = ZKPProof(
            proof_data=b"\x00\x01",
            public_inputs={"theorem": "Authorized(alice)"},
            metadata={
                "backend": "compatibility-fixture",
                "proof_system": "simulated",
            },
            timestamp=0.0,
            size_bytes=2,
        )
    assert proof.to_dict() == expected["zkp_proof"]
    assert (
        MANIFEST["authority_semantics"]["zkp"]["simulation_is_cryptographic_proof"]
        is False
    )
    assert MANIFEST["authority_semantics"]["zkp"]["attestation_increases_authority"] is False


def test_bridge_manifest_and_unavailable_gate_are_distinct_from_success() -> None:
    from ipfs_datasets_py.logic.bridge import ProofGateResult, logic_bridge_manifest

    expected = MANIFEST["canonical_payloads"]
    bridge_manifest = logic_bridge_manifest()
    assert bridge_manifest["manifest_version"] == 1
    assert bridge_manifest["bridge_count"] == len(expected["bridge_names"])
    assert bridge_manifest["implemented_bridges"] == expected["bridge_names"]

    unavailable = ProofGateResult(
        attempted_count=1,
        unavailable_count=1,
        details=({"reason": "optional prover unavailable"},),
    )
    assert unavailable.to_dict() == expected["bridge_unavailable_gate"]
    assert unavailable.compiles is False
    assert MANIFEST["authority_semantics"]["bridge"]["unavailable_is_success"] is False


def test_cli_parser_contract_and_error_envelope(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.logic.cli import create_parser, main
    from ipfs_datasets_py.logic import api

    parser = create_parser()
    assert parser.prog == MANIFEST["cli"]["prog"]
    assert _cli_contract() == MANIFEST["cli"]["commands"]

    def fail_conversion(_: str) -> None:
        raise RuntimeError("compatibility fixture failure")

    monkeypatch.setattr(api, "convert_text_to_fol", fail_conversion)
    exit_code = main(["--json", "convert-fol", "Every agent acts."])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == MANIFEST["cli"]["error_exit_code"]
    assert sorted(output) == MANIFEST["cli"]["error_envelope_keys"]
    assert output["success"] is False
    assert isinstance(output["error"], str) and output["error"]


def test_mcp_exports_and_optional_absence_envelopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logic_tools = importlib.import_module(MANIFEST["mcp"]["module"])
    assert logic_tools.__all__ == MANIFEST["mcp"]["exact_exports"]

    cec = importlib.import_module(
        "ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool"
    )
    tdfol = importlib.import_module(
        "ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_prove_tool"
    )
    health = importlib.import_module(
        "ipfs_datasets_py.mcp_server.tools.logic_tools.logic_capabilities_tool"
    )
    flogic = importlib.import_module(
        "ipfs_datasets_py.mcp_server.tools.logic_tools.flogic_tool"
    )
    monkeypatch.setattr(cec, "_AVAILABLE", False)
    monkeypatch.setattr(tdfol, "_AVAILABLE", False)
    monkeypatch.setattr(health, "_AVAILABLE", False)
    monkeypatch.setattr(flogic, "_FLOGIC_AVAILABLE", False)

    observed = {
        "cec_parse": asyncio.run(cec.cec_parse("Every agent acts.")),
        "tdfol_prove": asyncio.run(tdfol.tdfol_prove("P(a)")),
        "logic_health": asyncio.run(health.logic_health()),
        "flogic_query": asyncio.run(flogic.flogic_query("?X : Dog")),
    }
    assert observed == MANIFEST["mcp"]["optional_absence_envelopes"]
    assert all(payload["success"] is False for payload in observed.values())


@pytest.mark.parametrize("module_name", MANIFEST["lazy_imports"]["modules"])
def test_imports_are_quiet_lazy_and_side_effect_free(module_name: str) -> None:
    script = """
import importlib
import json
import sys
import warnings
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    importlib.import_module(sys.argv[1])
print(json.dumps({
    "loaded": sorted(sys.modules),
    "warnings": [str(item.message) for item in caught],
}))
"""
    environment = os.environ.copy()
    environment.pop("IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS", None)
    completed = subprocess.run(
        [sys.executable, "-c", script, module_name],
        cwd=REPO_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(completed.stdout)
    assert completed.stderr == MANIFEST["lazy_imports"]["observable_side_effects"]["stderr"]
    assert payload["warnings"] == MANIFEST["lazy_imports"]["observable_side_effects"]["warnings"]
    assert not (
        set(MANIFEST["lazy_imports"]["forbidden_after_import"])
        & set(payload["loaded"])
    )


def test_authority_matrix_fails_closed() -> None:
    authority = MANIFEST["authority_semantics"]
    theorem = authority["theorem_proof"]
    assert set(theorem["authoritative_success_states"]).isdisjoint(
        theorem["non_success_states"]
    )
    assert {"unknown", "timeout", "error", "unavailable", "unsupported"} <= set(
        theorem["non_success_states"]
    )
    assert authority["learned_or_shadow_output"]["candidate_is_proof"] is False
    assert authority["flogic"]["simulation_is_theorem_proof"] is False
