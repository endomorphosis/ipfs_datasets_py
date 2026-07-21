"""Tests for public LegalIR compiler API and CLI surfaces."""

from __future__ import annotations

import json
import subprocess
import sys

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_COMPILER_API_SCHEMA_VERSION,
    LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION,
    LegalIRCompilerExitCode,
    LegalIRCompilerOptions,
    benchmark_legal_ir,
    compile_legal_ir,
    decompile_legal_ir,
    diff_legal_ir,
    explain_legal_ir,
    export_legal_ir_artifact,
    legal_ir_lsp_diagnostics,
    validate_legal_ir,
)


SOURCE = {
    "citation": "42 U.S.C. 1983(a)",
    "raw_document": "The agency shall disclose records within 30 days.",
    "source_document_id": "doc-api",
}


def test_compile_validate_decompile_and_explain_emit_stable_json_surfaces() -> None:
    compile_result = compile_legal_ir(SOURCE)
    payload = compile_result.to_dict()

    assert payload["schema_version"] == LEGAL_IR_COMPILER_API_SCHEMA_VERSION
    assert payload["payload"]["schema_version"] == LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION
    assert payload["exit_code"] == LegalIRCompilerExitCode.OK.value
    assert payload["successful"] is True
    assert payload["payload"]["compiled"]["learned_guidance"]["active"] is False
    assert payload["payload"]["compiled"]["learned_guidance"]["production_default"] is True
    assert payload["payload"]["compiled"]["proof_obligations"][0]["statement"] == SOURCE["raw_document"]
    assert payload["source_map"]["source_map_id"]

    validate_result = validate_legal_ir(payload)
    assert validate_result.exit_code == LegalIRCompilerExitCode.OK.value
    assert validate_result.payload["valid"] is True
    assert validate_result.payload["source_map_validation"]["valid"] is True

    decompile_result = decompile_legal_ir(payload)
    assert decompile_result.exit_code == LegalIRCompilerExitCode.OK.value
    assert decompile_result.payload["decompiled_text"] == SOURCE["raw_document"]
    assert decompile_result.payload["lossless"] is True

    explain_result = explain_legal_ir(payload)
    assert explain_result.exit_code == LegalIRCompilerExitCode.OK.value
    assert explain_result.payload["diagnostic_report"]["valid"] is True
    assert isinstance(explain_result.payload["explanation_traces"], list)


def test_learned_guidance_is_explicit_and_lsp_diagnostics_are_machine_readable() -> None:
    options = LegalIRCompilerOptions(
        learned_guidance=True,
        learned_guidance_artifact={"export_id": "guidance-canary-1"},
        include_lsp_diagnostics=True,
    )
    compile_result = compile_legal_ir(SOURCE, options=options)

    learned = compile_result.payload["compiled"]["learned_guidance"]
    assert learned["active"] is True
    assert learned["activation_mode"] == "explicit_flag"
    assert learned["export_id"] == "guidance-canary-1"

    invalid = {
        "diagnostics": [
            {
                "diagnostic_type": "unresolved_symbol",
                "message": "Missing scoped agency definition.",
                "source_node_ids": ["formula-missing"],
            }
        ],
        "source_map": compile_result.source_map.to_dict(),
    }
    validation = validate_legal_ir(
        invalid,
        options=LegalIRCompilerOptions(include_lsp_diagnostics=True),
    )

    assert validation.exit_code == LegalIRCompilerExitCode.DIAGNOSTIC_ERROR.value
    assert validation.lsp_diagnostics
    lsp = legal_ir_lsp_diagnostics(validation)[0]
    assert lsp["source"] == "legal-ir-compiler"
    assert lsp["severity"] == 1
    assert lsp["code"] == "legal_ir.symbol.unresolved"


def test_diff_benchmark_and_artifact_export_are_json_ready_and_fail_closed() -> None:
    before = {
        "obligations": [
            {
                "conditions": ["public records request received"],
                "obligation_id": "obl-disclose",
                "operator": "shall",
                "proof_status": {"status": "proved"},
                "statement": "The agency shall disclose records.",
            }
        ]
    }
    after = {
        "obligations": [
            {
                "conditions": ["public records request received"],
                "obligation_id": "obl-disclose",
                "operator": "shall",
                "proof_status": {"status": "proved"},
                "statement": "The agency shall disclose records.",
            },
            {
                "conditions": ["denial issued"],
                "obligation_id": "obl-notice",
                "operator": "shall",
                "proof_status": {"status": "unknown"},
                "statement": "The agency shall notify requesters after denial.",
            },
        ]
    }

    diff_result = diff_legal_ir(before, after)
    assert diff_result.exit_code == LegalIRCompilerExitCode.OK.value
    assert diff_result.payload["changed"] is True
    assert "obligation_added" in diff_result.payload["change_kinds"]

    compile_result = compile_legal_ir(SOURCE)
    benchmark_result = benchmark_legal_ir(SOURCE, iterations=2)
    assert benchmark_result.exit_code == LegalIRCompilerExitCode.OK.value
    assert benchmark_result.payload["iterations"] == 2
    assert benchmark_result.payload["last_compile_digest"]

    export_result = export_legal_ir_artifact(compile_result.to_dict())
    assert export_result.exit_code == LegalIRCompilerExitCode.DIAGNOSTIC_ERROR.value
    assert export_result.payload["artifact_kind"] == "compiler_artifact"
    assert export_result.payload["artifact"]["proof_ready"] is False
    assert export_result.diagnostics.error_count

    # The full result must remain JSON serializable for API, CLI, and LSP clients.
    json.loads(json.dumps(export_result.to_dict(), sort_keys=True))


def test_cli_help_is_available() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ops/legal_ir/legal_ir_compile.py",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "compile" in completed.stdout
    assert "export-artifact" in completed.stdout
