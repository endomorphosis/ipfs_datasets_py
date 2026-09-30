"""Fail-closed qualification of an immutable autoencoder candidate and its pipeline.

Model embedding reconstruction, deterministic text semantics, family syntax,
full family/schema coverage and
source-locked Lake admission are separate observations. An embedding decoder is
not a text/formula generator. Training acceptance never supplies these gates.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import types
from typing import Any, Mapping, Sequence

SCHEMA = "autoencoder-candidate-qualification/v1"
MIN_COSINE = 0.72
MAX_RECONSTRUCTION_LOSS = 0.20
MAX_SAMPLES = 1024
LEAN_TOOLCHAIN = "leanprover/lean4:v4.26.0"
STRUCTURAL_GATES = ("semantic_gate", "family_syntax_gate", "family_coverage_gate", "lake_gate")
ROW_GATES = ("metric_gate", *STRUCTURAL_GATES)
# Version the actual syntax consumers and their local contracts as well as the
# top-level exporter. Hash before any family parsing and again before sealing;
# a parser's self-reported post-import hash alone cannot detect concurrent edits.
QUALIFICATION_DEPENDENCIES = (
    "logic/TDFOL/tdfol_parser.py", "logic/TDFOL/tdfol_core.py",
    "logic/parsers/flogic.py", "logic/parsers/legacy_modal.py",
    "logic/parsers/modal.py", "logic/parsers/event_calculus.py",
    "logic/syntax_core/algebra.py", "logic/syntax_core/ast.py",
    "logic/syntax_core/contracts.py", "logic/syntax_core/signatures.py",
    "logic/backends/results.py", "logic/backends/toolchain_roles.py",
    "logic/ir_core/claims.py", "logic/deontic/prover_syntax.py",
    "logic/deontic/ir.py", "logic/deontic/formula_builder.py",
    "logic/deontic/decoder.py", "logic/legal_ir/canonical_contracts.py",
    "logic/legal_ir/canonical_roundtrip.py",
    "logic/autoformal/semantic_integrity.py",
    "optimizers/logic_theorem_optimizer/autoencoder_paths.py",
)


class CandidateQualificationError(ValueError):
    """The caller's candidate/evidence binding cannot be verified."""


def _raw(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write(path: Path, value: Any) -> dict[str, Any]:
    raw = _raw(value) + b"\n"
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def metric_gate(evaluation: Mapping[str, Any], *, min_cosine: float = MIN_COSINE,
                max_reconstruction_loss: float = MAX_RECONSTRUCTION_LOSS) -> dict[str, Any]:
    """Require both absolute metrics; missing, nonfinite and impossible values fail."""
    cosine = evaluation.get("embedding_cosine_similarity")
    raw_cosine = cosine
    loss = evaluation.get("reconstruction_loss")
    reasons, diagnostics = [], []
    # Dot products and vector norms can differ by a few machine ULPs for
    # identical vectors. Correct only that representational overflow, preserve
    # the measured value, and never relax the actual quality threshold.
    cosine_roundoff_clamped = False
    roundoff_tolerance = 8 * math.ulp(1.0)
    if (_finite(cosine) and abs(cosine) > 1.0
            and abs(cosine) - 1.0 <= roundoff_tolerance):
        cosine = math.copysign(1.0, cosine)
        cosine_roundoff_clamped = True
        diagnostics.append({"code": "cosine_roundoff_clamped", "raw": raw_cosine,
                            "used": cosine, "tolerance": roundoff_tolerance})
    if type(evaluation.get("sample_count")) is not int or evaluation.get("sample_count") != 1:
        reasons.append("one_sample_evaluation_required")
    if not _finite(cosine) or not -1.0 <= cosine <= 1.0:
        reasons.append("invalid_embedding_cosine_similarity")
    elif cosine < min_cosine:
        reasons.append("embedding_cosine_below_threshold")
    if not _finite(loss) or loss < 0:
        reasons.append("invalid_reconstruction_loss")
    elif loss > max_reconstruction_loss:
        reasons.append("reconstruction_loss_above_threshold")
    return {"passed": not reasons, "reasons": reasons,
            "embedding_cosine_similarity": cosine if _finite(cosine) else None,
            "embedding_cosine_similarity_raw": raw_cosine if _finite(raw_cosine) else None,
            "cosine_roundoff_clamped": cosine_roundoff_clamped, "diagnostics": diagnostics,
            "reconstruction_loss": loss if _finite(loss) else None,
            "min_cosine": min_cosine, "max_reconstruction_loss": max_reconstruction_loss,
            "metric_scope": "model_encode_decode_embedding_reconstruction",
            "text_roundtrip_equivalence": False, "admitted": False}


def _is_constitution(sample: Mapping[str, Any]) -> bool:
    # Avoid running AutoformalSession.roundtrip_clause at all for this corpus.
    metadata = " ".join(str(sample.get(key) or "") for key in
                        ("title", "section", "citation", "source", "document_id", "corpus"))
    return bool(re.search(r"constitution|const\.|us_const|us-const", metadata, re.I))


def _statement_lock():
    path = Path(__file__).resolve().parents[5] / "JevOps/jevops/statement_lock.py"
    if not path.is_file():
        raise CandidateQualificationError("workspace JevOps statement lock is unavailable")
    raw = path.read_bytes()
    name = "_autoencoder_qualification_statement_lock"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    # Execute precisely the bytes recorded in provenance, not a stale pyc.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module, path, _sha(raw)


def _lake_gate(rule: Mapping[str, Any] | None, *, roundtrip_ok: bool,
               output_directory: Path, timeout_seconds: float,
               statement_lock: Any) -> dict[str, Any]:
    result = {"passed": False, "lake_ok": False, "admitted": False,
              "command": ["lake", "build", "Legal"], "toolchain": LEAN_TOOLCHAIN,
              "scope": "source_locked_numeric_pattern", "formalized": False}
    if not roundtrip_ok:
        return {**result, "reason": "source_semantic_roundtrip_failed"}
    pattern = statement_lock.pattern_from_rule(dict(rule) if rule is not None else None)
    if not pattern or pattern.get("kind") not in {"threshold", "conjunction", "amount"}:
        return {**result, "reason": "source_rule_not_renderable"}
    # A deadline cannot be admitted by a co-occurring minimum-duration theorem.
    if any(isinstance(item, Mapping) and item.get("temporal_kind") == "within_duration"
           for item in (rule or {}).get("temporal_records", ())):
        return {**result, "reason": "within_duration_not_renderable"}
    source = statement_lock.render_lean(pattern)
    lock = statement_lock.lock_statement(source, source)
    if lock.get("ok") is not True:
        return {**result, "reason": "source_statement_lock_failed", "source_lock": lock}
    # An installed binary is required. Do not ask elan to fetch a toolchain.
    binary = Path.home() / ".elan/toolchains/leanprover--lean4---v4.26.0/bin/lake"
    if not binary.is_file():
        return {**result, "reason": "installed_lake_toolchain_missing", "source_lock": lock}
    output_directory.mkdir(parents=True, exist_ok=False)
    lean_bytes = (source.rstrip() + "\n").encode()
    (output_directory / "Legal.lean").write_bytes(lean_bytes)
    (output_directory / "lean-toolchain").write_text(LEAN_TOOLCHAIN + "\n")
    (output_directory / "lakefile.lean").write_text(
        "import Lake\nopen Lake DSL\npackage «legal»\n@[default_target]\nlean_lib Legal\n")
    env = dict(os.environ)
    env["PATH"] = str(binary.parent) + os.pathsep + env.get("PATH", "")
    env["ELAN_TOOLCHAIN"] = LEAN_TOOLCHAIN
    started = time.monotonic()
    try:
        process = subprocess.run([str(binary), "build", "Legal"], cwd=output_directory,
                                 capture_output=True, text=True, timeout=timeout_seconds, env=env)
        output = (process.stdout or "") + (process.stderr or "")
        ok = process.returncode == 0 and "error:" not in output and "Built Legal" in output
        reason = "" if ok else "lake_build_failed"
        returncode = process.returncode
    except subprocess.TimeoutExpired as exc:
        output = str(exc.stdout or "") + str(exc.stderr or "")
        ok, reason, returncode = False, "lake_build_timeout", None
    except OSError as exc:
        output = str(exc)
        ok, reason, returncode = False, "lake_execution_error", None
    output_bytes = output.encode()
    (output_directory / "lake.log").write_bytes(output_bytes)
    # This admits only the generated locked numeric theorem, never the entire
    # legal rule or an output claimed to have been decoded from the model.
    return {**result, "passed": ok, "lake_ok": ok, "admitted": ok, "reason": reason,
            "pattern": pattern, "source_lock": lock, "lean_source_sha256": _sha(lean_bytes),
            "source_file": str(output_directory / "Legal.lean"), "binary": str(binary),
            "returncode": returncode, "elapsed_seconds": time.monotonic() - started,
            "log": {"path": str(output_directory / "lake.log"), "sha256": _sha(output_bytes),
                    "bytes": len(output_bytes)}}


def _structural_gates(sample: Mapping[str, Any], sample_id: str, directory: Path,
                      statement_lock: Any, lake_timeout_seconds: float) -> dict[str, Any]:
    from ...logic.autoformal import AutoformalSession, compile_span
    from ...logic.autoformal.family_qualification import qualify_logic_families

    if _is_constitution(sample):
        failure = {"passed": False, "reason": "constitution_not_formalized", "admitted": False}
        return {**{name: failure for name in STRUCTURAL_GATES},
                "compiler": {"compiler_status": "not_evaluated", "reason": "constitution_not_formalized",
                             "roundtrip": False, "admitted": False}}
    session = AutoformalSession()
    compile_started = time.monotonic()
    compiled = compile_span(session, sample["text"], sample_id, allow_partial=False)
    compile_seconds = time.monotonic() - compile_started
    # compile_span may emit more than one clause and exposes only its first rule.
    # Inspect every resulting row; an any-row roundtrip flag is insufficient.
    rows = list(session.rows)
    semantic_ok = (compiled.get("compiler_status") == "compiled" and bool(rows)
                   and bool(compiled.get("decompiled")) and not compiled.get("fields")
                   and all(row.status == "roundtrip_ok" and isinstance(row.rule, dict)
                           and bool(row.decompiled) for row in rows))
    semantic = {"passed": semantic_ok, "reason": "" if semantic_ok else
                str(compiled.get("reason") or "incomplete_source_semantic_roundtrip"),
                "scope": "deterministic_compiler_decompiler_source_roundtrip",
                "model_generated_text": False, "rows": [row.public() for row in rows], "admitted": False,
                "compile_decompile_elapsed_seconds": compile_seconds}
    family_rows, lake_rows = [], []
    for index, row in enumerate(rows):
        if row.status not in {"compiled", "roundtrip_ok"} or not isinstance(row.rule, dict):
            continue
        clause = session.documents.clause(row.document_id, row.clause_id)
        if clause is None:
            continue
        family_rows.append(qualify_logic_families(clause.text, row.rule, source_id=row.clause_id))
        lake_rows.append(_lake_gate(row.rule, roundtrip_ok=semantic_ok,
                         output_directory=directory / f"lake-{index}",
                         timeout_seconds=lake_timeout_seconds, statement_lock=statement_lock))
    family_ok = semantic_ok and len(family_rows) == len(rows) and all(
        row.get("passed") is True and row.get("full_floor_passed") is True
        and row.get("schema") == "autoformal-family-qualification/v2" for row in family_rows)
    coverage_rows = [{"source_id": row.get("source_id"),
                      "source_sha256": row.get("source_sha256"), "rule_sha256": row.get("rule_sha256"),
                      "passed": (row.get("full_family_semantics_covered") is True
                                 and row.get("schema_capability_coverage_complete") is True),
                      "full_family_semantics_covered": row.get("full_family_semantics_covered") is True,
                      "schema_capability_coverage_complete": row.get("schema_capability_coverage_complete") is True,
                      "coverage_limitations": row.get("coverage_limitations", []),
                      "admitted": False, "formalized": False} for row in family_rows]
    coverage_ok = family_ok and bool(coverage_rows) and all(row["passed"] for row in coverage_rows)
    lake_ok = semantic_ok and len(lake_rows) == len(rows) and all(
        row.get("passed") is True for row in lake_rows)
    return {"compiler": compiled, "semantic_gate": semantic,
            "family_syntax_gate": {"passed": family_ok, "rows": family_rows, "admitted": False,
                                   "reason": "" if family_ok else "required_family_syntax_failed"},
            "family_coverage_gate": {"passed": coverage_ok, "rows": coverage_rows,
                "scope": "required_logic_family_semantics_and_output_schema_coverage",
                "reason": "" if coverage_ok else "required_family_semantics_or_schema_coverage_incomplete",
                "syntax_pass_satisfies_coverage": False, "numeric_lake_pass_satisfies_coverage": False,
                "admitted": False, "formalized": False},
            "lake_gate": {"passed": lake_ok, "rows": lake_rows, "admitted": bool(lake_ok),
                          "reason": "" if lake_ok else "source_locked_lake_gate_failed"}}


def _load_candidate(candidate_artifact: Mapping[str, Any], dependencies: Sequence[Mapping[str, Any]]):
    from .modal_autoencoder_sparse_checkpoint import artifact_ref, resolve_checkpoint
    descriptors = {}
    for descriptor in [candidate_artifact, *dependencies]:
        ref = artifact_ref(descriptor)
        if not isinstance(descriptor.get("path"), str) or not descriptor["path"]:
            raise CandidateQualificationError("candidate dependency requires an owner-provided path")
        prior = descriptors.get(ref["sha256"])
        if prior is not None and prior != dict(descriptor):
            raise CandidateQualificationError("conflicting candidate dependency")
        descriptors[ref["sha256"]] = dict(descriptor)

    def resolver(reference):
        descriptor = descriptors.get(reference["sha256"])
        if descriptor is None or descriptor["bytes"] != reference["bytes"]:
            raise CandidateQualificationError("missing or mismatched candidate dependency")
        return descriptor["path"]

    resolved = resolve_checkpoint(artifact_ref(candidate_artifact), resolver=resolver)
    if {item["sha256"] for item in resolved.artifacts} != set(descriptors):
        raise CandidateQualificationError("unreferenced candidate dependencies")
    return resolved


def qualify_candidate(candidate_artifact: Mapping[str, Any], candidate_version_id: str,
                      samples: Sequence[Mapping[str, Any]], output_directory: str | Path, *,
                      checkpoint_dependencies: Sequence[Mapping[str, Any]] = (),
                      model_config: Mapping[str, Any] | None = None,
                      heldout_samples: Sequence[Mapping[str, Any]] = (),
                      min_cosine: float = MIN_COSINE,
                      max_reconstruction_loss: float = MAX_RECONSTRUCTION_LOSS,
                      lake_timeout_seconds: float = 120) -> dict[str, Any]:
    """Evaluate exact registered bytes, every row and every required gate.

    The registry owner must obtain version/artifacts from its verified registry;
    this function never mutates it. The receipt binds that version to verified
    artifact content. A held-out set disjoint by identity *and normalized text*
    is mandatory for qualification; in-sample success has a separate field.
    Output is exclusive so receipts from earlier attempts cannot be overwritten.
    """
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree
    from . import legal_samples, modal_autoencoder
    from .autoencoder_paths import INFERENCE_PATH, gated_evaluate
    from .autoencoder_training_worker import (SampleRecord, _effective_constructor_config,
                                               _worker_environment)

    if not isinstance(candidate_version_id, str) or not 1 <= len(candidate_version_id) <= 256:
        raise CandidateQualificationError("candidate version ID is required")
    if not _finite(min_cosine) or not MIN_COSINE <= min_cosine <= 1:
        raise CandidateQualificationError("cosine threshold cannot weaken the qualification floor")
    if not _finite(max_reconstruction_loss) or not 0 <= max_reconstruction_loss <= MAX_RECONSTRUCTION_LOSS:
        raise CandidateQualificationError("reconstruction threshold cannot weaken the qualification ceiling")
    if not _finite(lake_timeout_seconds) or not 1 <= lake_timeout_seconds <= 600:
        raise CandidateQualificationError("Lake timeout must be between 1 and 600 seconds")
    if not samples or len(samples) + len(heldout_samples) > MAX_SAMPLES:
        raise CandidateQualificationError("qualification requires 1 to 1024 samples")
    # SampleRecord rejects implicit external-model downloads and nonfinite vectors.
    training = [asdict(SampleRecord.from_dict(dict(sample))) for sample in samples]
    validation = [asdict(SampleRecord.from_dict(dict(sample))) for sample in heldout_samples]
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with _worker_environment():
        paths = require_workspace_logic_tree()
        lock, lock_path, lock_sha = _statement_lock()
        root = Path(__file__).resolve().parents[3]
        paths.update({"autoencoder": str(Path(modal_autoencoder.__file__).resolve()),
                      "samples": str(Path(legal_samples.__file__).resolve()),
                      "qualification": str(Path(__file__).resolve()),
                      "autoformal": str(root / "ipfs_datasets_py/logic/autoformal/__init__.py"),
                      "family_syntax": str(root / "ipfs_datasets_py/logic/autoformal/family_qualification.py"),
                      "statement_lock": str(lock_path)})
        paths.update({"dependency:" + relative: str(root / "ipfs_datasets_py" / relative)
                      for relative in QUALIFICATION_DEPENDENCIES})
        for name in ("autoencoder", "samples"):
            if root not in Path(paths[name]).parents:
                raise CandidateQualificationError(f"{name} resolved outside workspace")
        hashes = {key: _sha(Path(path).read_bytes()) for key, path in paths.items()}
        if hashes["statement_lock"] != lock_sha:
            raise CandidateQualificationError("statement lock changed during loading")
        resolved = _load_candidate(candidate_artifact, checkpoint_dependencies)
        candidate_state_identity = resolved.state.state_identity_record().to_dict()
        constructor = _effective_constructor_config(modal_autoencoder.AdaptiveModalAutoencoder,
                                                     dict(model_config or {}))
        model = modal_autoencoder.AdaptiveModalAutoencoder(state=resolved.state, **constructor)
        train_samples = [legal_samples.build_us_code_sample(**sample) for sample in training]
        hold_samples = [legal_samples.build_us_code_sample(**sample) for sample in validation]
        identities = lambda rows: {row.sample_id for row in rows}
        texts = lambda rows: {_sha(row.normalized_text.casefold().encode()) for row in rows}
        if len(identities(train_samples)) != len(train_samples) or len(identities(hold_samples)) != len(hold_samples):
            raise CandidateQualificationError("duplicate sample identity within a qualification split")
        overlap = bool(identities(train_samples) & identities(hold_samples) or
                       texts(train_samples) & texts(hold_samples))
        heldout_valid = bool(hold_samples) and not overlap
        records, todos = [], []
        for split, input_rows, built_rows in (("training", training, train_samples),
                                             ("heldout", validation, hold_samples)):
            for index, (input_row, sample) in enumerate(zip(input_rows, built_rows)):
                row_directory = directory / f"{split}-{index}"
                row_directory.mkdir()
                metric_started = time.monotonic()
                try:
                    evaluation = gated_evaluate(model, [sample], execution_mode=INFERENCE_PATH,
                        legal_ir_bridge_names=(),
                        legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1,
                        use_sample_memory=False).to_dict()
                except Exception as exc:
                    evaluation = {"evaluation_error": type(exc).__name__ + ": " + str(exc)[:2000]}
                metric_seconds = time.monotonic() - metric_started
                metrics = metric_gate(evaluation, min_cosine=min_cosine,
                                      max_reconstruction_loss=max_reconstruction_loss)
                decoded = evaluation.get("decoded_embeddings", {}).get(sample.sample_id)
                if (not isinstance(decoded, list) or len(decoded) != len(sample.embedding_vector)
                        or not all(_finite(value) for value in decoded)):
                    metrics["passed"] = False
                    metrics["reasons"].append("invalid_decoded_embedding")
                if "evaluation_error" in evaluation:
                    metrics["evaluation_error"] = evaluation["evaluation_error"]
                structural_started = time.monotonic()
                try:
                    structure = _structural_gates(input_row, sample.sample_id, row_directory,
                                                  lock, lake_timeout_seconds)
                except Exception as exc:
                    failure = {"passed": False, "reason": "qualification_execution_error",
                               "error_type": type(exc).__name__, "error": str(exc)[:2000], "admitted": False}
                    structure = {**{name: failure for name in STRUCTURAL_GATES},
                                 "compiler": {"compiler_status": "error"}}
                # Old or incomplete structural producers cannot waive a new gate.
                for gate in STRUCTURAL_GATES:
                    if not isinstance(structure.get(gate), Mapping):
                        structure[gate] = {"passed": False, "reason": "required_gate_evidence_missing",
                                           "gate": gate, "admitted": False}
                row = {"sample_id": sample.sample_id, "split": split, "source": input_row,
                       "source_sha256": _sha(sample.text.encode()), "metric_gate": metrics,
                       "model_evaluation_elapsed_seconds": metric_seconds,
                       "structural_elapsed_seconds": time.monotonic() - structural_started,
                       "decoded_embedding": decoded if isinstance(decoded, list) and all(_finite(v) for v in decoded) else None,
                       "model_generated_text": None, **structure, "formalized": False,
                       "admitted": False}
                row["qualified"] = all(row[key].get("passed") is True for key in ROW_GATES)
                records.append(row)
                for gate in STRUCTURAL_GATES:
                    if row[gate].get("passed") is not True:
                        todos.append({"kind": "source_repair", "sample_id": sample.sample_id,
                                      "source_text": sample.text, "source_sha256": row["source_sha256"],
                                      "candidate_version_id": candidate_version_id, "gate": gate,
                                      "evidence": row[gate], "admitted": False,
                                      "acceptance": (
                                          "Supply source-bound evidence of every required family semantics and typed output schema; syntax fragments and numeric Lake theorems cannot substitute for coverage."
                                          if gate == "family_coverage_gate" else
                                          "Preserve source meaning and pass the unchanged qualification gate.")})
        if not heldout_valid:
            todos.append({"kind": "validation_data", "gate": "heldout_gate",
                          "reason": "heldout_overlap" if overlap else "heldout_samples_missing",
                          "acceptance": "Supply source-backed held-out samples disjoint by identity and normalized text.",
                          "candidate_version_id": candidate_version_id, "admitted": False})
        if hashes != {key: _sha(Path(path).read_bytes()) for key, path in paths.items()}:
            raise CandidateQualificationError("qualification producer source changed during evaluation")
        if resolved.state.state_identity_record().to_dict() != candidate_state_identity:
            raise CandidateQualificationError("candidate state changed during qualification")
        gate_names = ROW_GATES
        gates = {name: {"passed": all(row[name].get("passed") is True for row in records),
                        "failed_sample_ids": [row["sample_id"] for row in records if row[name].get("passed") is not True]}
                 for name in gate_names}
        gates["heldout_gate"] = {"passed": heldout_valid, "sample_count": len(hold_samples),
                                 "reason": "heldout_overlap" if overlap else "" if hold_samples else "heldout_samples_missing"}
        receipt = {"schema_version": SCHEMA, "candidate_version_id": candidate_version_id,
                   "candidate_artifact": {key: candidate_artifact[key] for key in ("sha256", "bytes")},
                   "checkpoint_artifacts": list(resolved.artifacts),
                   "materialized_checkpoint": dict(resolved.materialized_checkpoint),
                   "candidate_state_identity": candidate_state_identity,
                   "requested_model_config": dict(model_config or {}),
                   "model_config": constructor, "source_files": paths, "source_sha256": hashes,
                   "sample_count": len(train_samples), "heldout_sample_count": len(hold_samples),
                   "heldout_role": "tuning_validation", "heldout_canary": False,
                   "sample_set_sha256": _sha(_raw({"training": training, "heldout": validation})),
                   "required_gate_names": [*ROW_GATES, "heldout_gate"],
                   "gate_policy_version": "family_semantics_and_schema_coverage/v1",
                   "gate_results": gates, **gates,
                   "qualified": all(gate["passed"] for gate in gates.values()),
                   "training_qualified": all(row["qualified"] for row in records if row["split"] == "training"),
                   "needs_training": not gates["metric_gate"]["passed"],
                   "repair_todos": todos, "rows": records,
                   "elapsed_seconds": time.monotonic() - started,
                   "admitted": False, "formalized": False, "promotion_performed": False,
                   "execution_mode": "native_candidate_qualification",
                   "execution_path": INFERENCE_PATH, "training_executed": False,
                   "execution_gate_applied": True,
                   "qualification_scope": "embedding_model_and_deterministic_source_compiler_pipeline",
                   "model_emits_text_or_formulas": False,
                   "metric_evaluation": {"bridge_names": [], "legal_ir_target_count": 0,
                                         "legal_ir_evaluate_provers": False, "cache_enabled": False,
                                         "legal_ir_parallel_workers": 1, "use_sample_memory": False,
                                         "scope": "embedding_metrics_only_not_a_legal_ir_evaluate"}}
        artifact = _write(directory / "qualification.json", receipt)
        return {**receipt, "receipt_artifact": artifact}
