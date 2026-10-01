"""Higher-order candidate embedding and an explicit, bounded Lake syntax gate.

Modality operators are interpretation parameters, not invented axioms. Compiling
these declarations checks Lean syntax/types; it cannot prove the user's meaning
or establish that the underlying program satisfies the declarations.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from .projection_contracts import (make_projection, validated_document, safe_symbol,
                                   canonical_bytes, validate_projection)


def _string(value):
    if type(value) is not str or any(ord(c) < 32 and c not in "\n\t\r" for c in value):
        raise ValueError("Lean embedding requires printable source symbols")
    return json.dumps(value, ensure_ascii=False)


def project_lean_family(document, context=None):
    document = validated_document(document)
    lines = ["-- Generated candidate embedding. No semantic axioms or program proofs are asserted.",
        "namespace IntentProjection", "", "structure Interpretation where",
        "  atom : String → List String → Prop", "  intended : Prop → Prop",
        "  required : Prop → Prop", "  prohibited : Prop → Prop", "  permitted : Prop → Prop",
        "  recommended : Prop → Prop", ""]
    statements, losses, nodes = [], [], []
    for row in document.statements:
        if not row.predicate:
            losses.append({"node_id": row.statement_id, "reason": "opaque_statement_has_no_typed_predicate"})
            continue
        args = "[" + ", ".join(_string(v) for v in row.arguments) + "]"
        atom = f"i.atom {_string(row.predicate)} {args}"
        effective_modality = "intended" if row.kind.value == "goal" and row.modality.value == "asserted" else row.modality.value
        if effective_modality == "asserted":
            expression = atom
        else:
            expression = f"i.{effective_modality} ({atom})"
        name = safe_symbol(row.statement_id, prefix="statement")
        lines += [f"def {name} (i : Interpretation) : Prop :=", "  " + expression, ""]
        statements.append({"node_id": row.statement_id, "symbol": name, "kind": row.kind.value,
            "modality": row.modality.value, "effective_modality": effective_modality,
            "predicate": row.predicate, "arguments": list(row.arguments),
            "grounding": row.grounding.value, "source_ref_ids": list(row.source_ref_ids)})
        nodes.append(row.statement_id)
    # Action/workflow semantics require operational or trace interpretations.
    # Reporting each omission avoids mistaking compiled declarations for a
    # complete higher-order formalization of the intent procedure.
    losses.extend({"node_id": r.action_id, "reason": "action_operational_semantics_not_encoded_in_lean_embedding"}
                  for r in document.actions)
    losses.extend({"node_id": r.edge_id, "reason": "workflow_trace_semantics_not_encoded_in_lean_embedding"}
                  for r in document.control_edges)
    lines += ["end IntentProjection", ""]
    source = "\n".join(lines)
    return make_projection(document, family_id="higher_order", status=("partial" if losses else "projected") if statements else "unsupported",
        representation={"format": "lean4-source", "source": source, "payload": {"statements": statements,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "embedding": "proposition_valued_uninterpreted_modality_operators"}},
        source_node_ids=nodes,
        validation=[{"validator": "lean.lake_build", "status": "not_run", "details": {"reason": "explicit_external_validation_required"}}],
        unsupported=losses, semantics="higher_order_modal_declaration_embedding",
        assumptions=["Modality operators are uninterpreted parameters; no deontic or cognitive axioms are asserted.",
            "An asserted GOAL follows the native compiler convention: intended outcome, not achieved fact.",
            "An atomic declaration is interpreted as a proposition, not evidence that it holds.",
            "Successful Lean compilation checks syntax/types only; source meaning and program correctness remain unverified."])


def validate_lean_projection(report, document, *, lake_executable="lake", timeout_seconds=30,
                             runner=None, toolchain=None):
    """Build exactly the regenerated inert source in a temporary Lake project.

The public API never accepts caller-supplied Lean code for execution. A report
must match the installed deterministic generator byte-for-byte first. There are
no external package dependencies, custom build scripts, tactics, or downloads.
"""
    from ...backends.process import BoundedToolRunner, ToolRunRequest, ToolRunLimits
    validate_projection(report, document)
    expected = project_lean_family(document)
    if canonical_bytes(report) != canonical_bytes(expected):
        raise ValueError("only the exact generated Intent Lean embedding may be checked")
    if type(timeout_seconds) not in (float, int) or not 0 < timeout_seconds <= 60:
        raise ValueError("bounded Lake timeout required")
    source = report["representation"]["source"]
    receipt = {"schema": "intent-lean-syntax-receipt/v1", "projection_sha256": report["projection_sha256"],
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "status": "not_run", "syntax_valid": False,
        "typecheck_valid": False, "proof_authority": False, "source_semantics_verified": False,
        "program_correctness_verified": False, "proof_obligations_discharged": False,
        "command": [str(lake_executable), "build", "IntentProjection"], "toolchain": toolchain,
        "dependencies": [], "backend_executed": False, "observations": []}
    if report["status"] == "unsupported":
        receipt["reason"] = "no_supported_declarations"
        return receipt
    runtime = runner if runner is not None else BoundedToolRunner()
    if not runtime.is_available(str(lake_executable)):
        receipt["status"] = "unavailable"
        receipt["reason"] = "lake_executable_missing"
        return receipt
    executable = Path(shutil.which(str(lake_executable)) or str(lake_executable)).absolute()
    # Never ask an elan shim to install a missing toolchain. Resolve an explicit
    # selection to its already-installed native executable before any process.
    if executable.name == "lake" and executable.parent.name == "bin" and executable.parent.parent.name == ".elan":
        toolchain = toolchain or os.environ.get("ELAN_TOOLCHAIN")
        if type(toolchain) is not str or not re.fullmatch(r"[A-Za-z0-9_./:+-]{1,160}", toolchain):
            receipt["status"] = "unavailable"
            receipt["reason"] = "explicit_installed_toolchain_required_for_elan_shim"
            return receipt
        installed = executable.parent.parent / "toolchains" / toolchain.replace(":", "---").replace("/", "--") / "bin" / "lake"
        if not installed.is_file():
            receipt["status"] = "unavailable"
            receipt["reason"] = "requested_toolchain_not_installed_no_download_attempted"
            return receipt
        executable = installed
    probe = runtime.run(ToolRunRequest(argv=(str(executable), "--version"),
        limits=ToolRunLimits(timeout_seconds=min(timeout_seconds, 5), max_output_bytes=16384)))
    receipt["observations"].append({"stage": "version", "returncode": probe.returncode,
                                   "stdout": probe.stdout, "stderr": probe.stderr})
    if not probe.ok:
        receipt["status"] = "unavailable"
        receipt["reason"] = "lake_version_probe_failed"
        return receipt
    # Pin the installed toolchain selected by the Lake executable. Running the
    # resolved binary avoids an elan shim attempting to fetch another version.
    match = re.search(r"Lean version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)", probe.stdout)
    if toolchain is None:
        if not match:
            receipt["status"] = "unavailable"
            receipt["reason"] = "unable_to_identify_installed_lean_toolchain"
            return receipt
        toolchain = "leanprover/lean4:v" + match.group(1)
    if type(toolchain) is not str or not re.fullmatch(r"[A-Za-z0-9_./:+-]{1,160}", toolchain):
        raise ValueError("bounded explicit Lean toolchain identifier required")
    if match is None or toolchain != "leanprover/lean4:v" + match.group(1):
        receipt["status"] = "unavailable"
        receipt["reason"] = "requested_toolchain_does_not_match_installed_lake"
        return receipt
    receipt["toolchain"] = toolchain
    files = {"lakefile.toml": 'name = "intent_projection"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "IntentProjection"\n',
             "lean-toolchain": toolchain + "\n", "IntentProjection.lean": source}
    build = runtime.run(ToolRunRequest(argv=(str(executable), "build", "IntentProjection"),
        input_files=files, environment={"ELAN_TOOLCHAIN": toolchain},
        limits=ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
            max_output_bytes=262144, max_input_bytes=4 * 1024 * 1024, max_workspace_bytes=32 * 1024 * 1024)))
    receipt["command"] = [str(executable), "build", "IntentProjection"]
    receipt["backend_executed"] = True
    receipt["observations"].append({"stage": "build", "returncode": build.returncode,
        "stdout": build.stdout, "stderr": build.stderr, "timed_out": build.timed_out})
    passed = build.ok and not build.output_truncated and not build.workspace_limit_exceeded
    receipt.update(status="passed" if passed else "failed", syntax_valid=passed, typecheck_valid=passed)
    return receipt


__all__ = ["project_lean_family", "validate_lean_projection"]
