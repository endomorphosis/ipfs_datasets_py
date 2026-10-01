#!/usr/bin/env python3
"""Exercise preserved 8D linguistic features and historical projection training.

Only fresh smoke artifacts are written. No existing checkpoint is selected,
downloaded, or rewritten. Linguistic vectors and target-aware historical losses
are diagnostic; neither this smoke nor a text reconstruction grants admission.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import resource
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKENDS = ("historical_blank_en", "local_en_core_web_sm")
SCHEMA = "legacy-linguistic-autoencoder-smoke/v1"
GATE_TEXTS = (
    "Company A shall submit backup report within 10 days unless emergency.",
    "The agency shall not disclose records.",
    "The officer shall retain the file for at least 20 days.",
)
FALSE_AUTHORITY = {
    "admitted": False, "formalized": False, "roundtrip_ok": False,
    "semantic_qualification": False, "lake_executed": False,
}


def _write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _forbidden_modules() -> list[str]:
    names = ("modal_joint_formula", "modal_latent_formula", "legal_formula_learning",
             "native_formula_training")
    return sorted(name for name in sys.modules if any(
        name.rsplit(".", 1)[-1] == forbidden for forbidden in names))


def _source_files(jevops_root: Path) -> dict[str, str]:
    prefix = "ipfs_datasets_py/"
    relatives = (
        "logic/deontic/utils/deontic_parser.py",
        "logic/autoformal/__init__.py",
        "logic/legal_ir/canonical_compiler.py",
        "logic/legal_ir/canonical_decompiler.py",
        "logic/modal/decompiler.py",
        "optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1/__init__.py",
        "optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1/linguistic.py",
        "optimizers/logic_theorem_optimizer/autoencoder_lineages/_contract.py",
    )
    paths = [REPO_ROOT / (prefix + relative) for relative in relatives]
    lineage = REPO_ROOT / prefix / "optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1"
    for name in ("_snapshot", "_linguistic_snapshot"):
        paths.extend(sorted((lineage / name).glob("*.py")))
        paths.append(lineage / name / "MANIFEST.json")
    paths.append(jevops_root / "jevops/statement_lock.py")
    paths.append(Path(__file__).resolve())
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _typed_gates(jevops_root: Path) -> dict[str, Any]:
    from ipfs_datasets_py.logic.autoformal import _temporal_records, vocabulary_from_clause
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
        CanonicalAtomVocabulary, CompilerRequest, OperationStatus,
    )
    from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import decompile_rule

    lock_path = jevops_root / "jevops/statement_lock.py"
    spec = importlib.util.spec_from_file_location("_legacy_smoke_statement_lock", lock_path)
    _require(spec is not None and spec.loader is not None, "JevOps statement lock unavailable")
    lock = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = lock
    spec.loader.exec_module(lock)
    compiler, rows = TypedDeonticCanonicalCompiler(), []
    for index, source in enumerate(GATE_TEXTS):
        started = time.monotonic()
        vocabulary = vocabulary_from_clause(source)
        vocabulary_seconds = time.monotonic() - started
        _require(bool(vocabulary), f"gate {index}: parser returned no atoms")
        _require(all(type(atom) is str for atoms in vocabulary.values() for atom in atoms),
                 "vocabulary must contain parser-supplied string atoms")
        started = time.monotonic()
        result = compiler.compile(CompilerRequest(source, f"legacy-smoke-{index}",
                                                   CanonicalAtomVocabulary(**vocabulary)))
        compile_seconds = time.monotonic() - started
        _require(result.status is OperationStatus.SUCCESS and bool(result.canonical_ir.rules),
                 f"gate {index}: compiler abstained")
        rule = result.canonical_ir.rules[0]
        wire = {**rule.to_dict(), "temporal_records": _temporal_records(source)}
        rendered = decompile_rule(rule)
        pattern = lock.pattern_from_rule(wire)
        if index == 0:
            _require(wire["modality"] == "O", "deadline gate lost obligation")
            _require("10 days" in rendered and "emergency" in rendered,
                     "deadline gate lost duration or exception")
            _require(any(item.get("temporal_kind") == "within_duration"
                         for item in wire.get("temporal_records", [])), "deadline kind changed")
            _require(pattern is None, "deadline became a renderable minimum")
        elif index == 1:
            _require(wire["modality"] == "F", "prohibition gate changed")
        else:
            _require("at least 20 days" in rendered and "at least days" not in rendered,
                     "minimum gate lost duration quantity")
            _require(any(item.get("temporal_kind") == "minimum_duration"
                         and type(item.get("quantity")) is int and item["quantity"] == 20
                         for item in wire.get("temporal_records", [])), "minimum kind changed")
            _require(pattern == {"kind": "threshold", "fail": 19, "meet": 20},
                     "minimum-duration threshold rendering changed")
        empty = compiler.compile(CompilerRequest(source, f"legacy-smoke-empty-{index}",
                                                 CanonicalAtomVocabulary()))
        _require(empty.status is OperationStatus.ABSTAINED and empty.canonical_ir is None,
                 "empty vocabulary must abstain")
        rows.append({"source_text": source, "parser_vocabulary": vocabulary,
                     "vocabulary_seconds": vocabulary_seconds, "compile_seconds": compile_seconds,
                     "compiler": result.to_dict(), "rule_with_parser_sidecars": wire,
                     "decompiled_text": rendered,
                     "lean_pattern": pattern, "empty_vocabulary": empty.to_dict(),
                     **FALSE_AUTHORITY})
    return {"rows": rows, "sample_count": len(rows), "passed": True,
            "statement_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
            "wall_seconds_per_span": sum(row["vocabulary_seconds"] + row["compile_seconds"]
                                           for row in rows) / len(rows), **FALSE_AUTHORITY}


def _predictions(model: Any, samples: list[Any]) -> list[dict[str, Any]]:
    outputs = []
    for sample in samples:
        encoded = model.encode(sample, use_sample_memory=False)
        decoded = model.decode(encoded)
        _require(len(decoded) == 8 and all(math.isfinite(value) for value in decoded),
                 "legacy decoder must return finite 8D values")
        outputs.append({"sample_id": sample.sample_id, "encoded": encoded, "decoded": decoded})
    return outputs


def _semantic_audit(observations: list[dict[str, Any]], typed_gates: dict[str, Any]) -> dict[str, Any]:
    """Expose narrow, observable conflicts without treating source copying as fidelity.

    Operator inspection is family-qualified: temporal F is not prohibition F.
    Quantity inspection is only a coverage inventory of formula content. Even
    finding the expected token would not establish its correct scope or meaning.
    """
    by_text = {row["source_text"]: row for row in observations}
    rows, issues = [], []
    for gate in typed_gates["rows"]:
        text = gate["source_text"]
        _require(text in by_text, "semantic audit is missing a canonical gate observation")
        observation = by_text[text]
        formulas = observation["linguistic_observation"]["modal_ir"]["formulas"]
        expected = gate["rule_with_parser_sidecars"]
        operators = sorted({formula["operator"]["symbol"] for formula in formulas
                            if formula["operator"]["family"] == "deontic"})
        row_issues = []
        if expected["modality"] == "F" and "O" in operators and "F" not in operators:
            row_issues.append({
                "code": "prohibition_operator_conflict", "severity": "semantic_conflict",
                "expected_deontic_operator": "F", "observed_deontic_operators": operators,
                "detail": "Typed compiler emits prohibition; frozen linguistic IR emits only obligation.",
            })
        quantities = []
        # Source text, provenance, formula identifiers and metadata are withheld
        # from this inventory: they cannot repair absent semantic formula fields.
        content = [{key: value for key, value in formula.items()
                    if key not in {"provenance", "metadata", "formula_id"}} for formula in formulas]
        semantic_tokens = set(re.findall(r"[A-Za-z0-9]+", json.dumps(content, sort_keys=True)))
        for temporal in expected.get("temporal_records", []):
            quantity = temporal.get("quantity")
            if type(quantity) is not int:
                continue
            found = str(quantity) in semantic_tokens
            quantities.append({"temporal_kind": temporal["temporal_kind"], "quantity": quantity,
                               "quantity_token_in_formula_content": found,
                               "scope_and_meaning_verified": False})
            if not found:
                row_issues.append({
                    "code": "quantitative_fields_not_explicit", "severity": "coverage_gap",
                    "temporal_kind": temporal["temporal_kind"], "quantity": quantity,
                    "detail": "Expected quantity is absent from explicit linguistic formula content; source provenance is not a substitute.",
                })
        rows.append({"source_text": text,
                     "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                     "typed_compiler_modality": expected["modality"],
                     "linguistic_deontic_operators": operators,
                     "quantitative_inventory": quantities,
                     "decompiled_text_matches_source": observation["decompiled"]["text"] == text,
                     "source_text_reconstruction_is_fidelity_evidence": False,
                     "known_issues": row_issues, "formula_fidelity_verified": False})
        issues.extend({"source_text": text, **issue} for issue in row_issues)
    return {"scope": "three authored gates; explicit deontic operators and quantity-token coverage only",
            "rows": rows, "known_issues": issues, "known_issue_count": len(issues),
            "semantic_conflict_count": sum(issue["severity"] == "semantic_conflict" for issue in issues),
            "coverage_gap_count": sum(issue["severity"] == "coverage_gap" for issue in issues),
            "formula_fidelity_verified": False, "complete_semantic_equivalence_check": False,
            "preserved_frozen_implementation": True, **FALSE_AUTHORITY}


def _profile(backend: str, output: Path, max_seconds: float,
             typed_gates: dict[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.logic.modal.decompiler import decode_modal_ir_document
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import (
        LinguisticAutoencoder, load_training_checkpoint,
    )

    began = time.monotonic()
    model = LinguisticAutoencoder(backend=backend, compute_device="cpu",
                                 max_codec_feature_keys=64, feature_family_logit_scale=1.0)
    _require(not _forbidden_modules(), "legacy profile imported an experimental formula runtime")
    texts = ["The agency shall submit reports.", "The agency shall submit notices.", *GATE_TEXTS]
    samples, observations = [], []
    prepared = time.monotonic()
    for index, text in enumerate(texts):
        row_started = time.monotonic()
        sample = model.build_sample(title="smoke", section=str(index + 1), text=text,
                                    citation=f"Authored diagnostic fixture {index + 1}")
        observed = model.linguistic_observation(sample)
        linguistic_ir = model.feature_codec.compile_sample_ir(sample)
        _require(linguistic_ir.to_dict() == observed["modal_ir"],
                 "linguistic compilation differs from captured IR")
        rendered = decode_modal_ir_document(linguistic_ir).to_dict()
        _require(bool(observed["feature_keys"]), "linguistic features were empty")
        _require(bool(rendered["formulas"]), "linguistic IR emitted no formulas")
        observations.append({"source_text": text, "source_kind": "authored_diagnostic_fixture",
                             "sample": sample.to_dict(), "linguistic_observation": observed,
                             "decompiled": rendered, "elapsed_seconds": time.monotonic() - row_started,
                             "decompiled_from": "frozen_spacy_linguistic_modal_ir",
                             "text_reconstruction_is_independent_validation": False,
                             **FALSE_AUTHORITY})
        samples.append(sample)
    preparation_seconds = time.monotonic() - prepared
    training, validation = samples[:1], samples[1:2]
    started = time.monotonic()
    before_outputs = _predictions(model, samples)
    inference_seconds = time.monotonic() - started
    before_state = model.state.to_dict()
    started = time.monotonic()
    before = model.evaluate(validation, legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
                            legal_ir_parallel_workers=1, use_sample_memory=False).to_dict()
    before_evaluate_seconds = time.monotonic() - started
    options = dict(epochs=1, learning_rate=0.01, max_seconds=max_seconds,
                   max_line_search_attempts=1, projection_update_backend="python_sparse_batch",
                   projection_max_update_families=4, legal_ir_bridge_names=(),
                   legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    started = time.monotonic()
    first = model.train_generalizable_projection(training, validation_samples=validation, **options)
    training_seconds = time.monotonic() - started
    _require(first["accepted_epochs"] > 0, f"{backend}: old projection training accepted no update")
    after_state = model.state.to_dict()
    changed = sorted(key for key in before_state if before_state[key] != after_state[key])
    _require(bool(changed), "accepted old projection did not change reusable state")
    _require(not model.state.decoded_embeddings, "old projection training memorized source rows")
    _require(model.formula_decoder_description().get("attached", False) is False,
             "experimental decoder attached to historical profile")
    after_outputs = _predictions(model, samples)
    checkpoint = output / "checkpoint-after-one-epoch"
    saved = model.save_training_checkpoint(checkpoint)
    resumed = load_training_checkpoint(checkpoint)
    restored_state_equal = model.state.to_dict() == resumed.state.to_dict()
    restored_outputs_equal = after_outputs == _predictions(resumed, samples)
    _require(restored_state_equal and restored_outputs_equal, "checkpoint reload changed old state or outputs")
    second = model.train_generalizable_projection(training, validation_samples=validation, **options)
    replay = resumed.train_generalizable_projection(training, validation_samples=validation, **options)
    resumed_equal = model.state.to_dict() == resumed.state.to_dict()
    outputs_equal = _predictions(model, samples) == _predictions(resumed, samples)
    _require(resumed_equal and outputs_equal, "resumed update differs from uninterrupted update")
    _require(not _forbidden_modules(), "historical training imported a new formula runtime")
    final_checkpoint = resumed.save_training_checkpoint(output / "checkpoint-after-two-epochs")
    started = time.monotonic()
    final = resumed.evaluate(validation, legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
                              legal_ir_parallel_workers=1, use_sample_memory=False).to_dict()
    final_evaluate_seconds = time.monotonic() - started
    _require(before["legal_ir_target_count"] == final["legal_ir_target_count"] == 0,
             "unexpected legal-IR bridge targets in bridge-off smoke")
    receipt = {
        "backend": backend, "description": model.describe(), "sample_count": len(samples),
        "compute_backend": model.compute_backend,
        "training_sample_count": 1, "validation_sample_count": 1, "observations": observations,
        "before_outputs": before_outputs, "after_first_epoch_outputs": after_outputs,
        "before_validation": before, "after_validation": final,
        "before_evaluate_seconds": before_evaluate_seconds,
        "after_evaluate_seconds": final_evaluate_seconds,
        "evaluate_sample_count": len(validation), "evaluate_bridge_names": [],
        "timing_scope": "one model in one process; preparation precedes inference and evaluation",
        "first_training_report": first, "second_training_report": second,
        "resumed_training_report": replay, "training_options": options,
        "changed_state_components": changed, "first_checkpoint": saved,
        "second_checkpoint": final_checkpoint, "reload_state_equal": restored_state_equal,
        "reload_outputs_equal": restored_outputs_equal, "resumed_state_equal": resumed_equal,
        "resumed_outputs_equal": outputs_equal, "sample_memory_used": False,
        "new_formula_modules_loaded": _forbidden_modules(),
        "preparation_seconds": preparation_seconds, "inference_seconds": inference_seconds,
        "wall_seconds_per_span": inference_seconds / len(samples),
        "preparation_wall_seconds_per_span": preparation_seconds / len(samples),
        "first_training_seconds": training_seconds, "elapsed_seconds": time.monotonic() - began,
        "reconstruction_objective": "historical_target_aware_safety_projection",
        "representation": "deterministic_linguistic_feature_hash_8d_not_verified_semantic_embedding",
        "target_equals_deterministic_base": all(
            row["sample"]["embedding_vector"] == row["linguistic_observation"]["decoded_feature_vector"]
            for row in observations),
        "semantic_audit": _semantic_audit(observations, typed_gates),
        "formula_fidelity_verified": False, "fidelity_claim": False,
        "operational_passed": True, "passed": True,
        "passed_scope": "operational execution, old training, checkpoint reload and resume only",
        **FALSE_AUTHORITY,
    }
    _write_new(output / "receipt.json", receipt)
    return receipt


def run(output_directory: Path, *, backends: tuple[str, ...] = BACKENDS,
        max_seconds: float = 30, jevops_root: Path | None = None) -> dict[str, Any]:
    _require(bool(backends) and len(backends) == len(set(backends)) and set(backends) <= set(BACKENDS),
             "choose distinct supported backends")
    _require(math.isfinite(max_seconds) and 0 < max_seconds <= 180,
             "max_seconds must be positive and at most 180")
    output = output_directory.absolute()
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(REPO_ROOT))
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    began = time.monotonic()
    jevops = (jevops_root or REPO_ROOT.parents[1] / "JevOps").resolve()
    receipt: dict[str, Any] = {
        "schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
        "output_directory": str(output), "profiles": [], "passed": False,
        "operational_passed": False, "formula_fidelity_verified": False,
        "passed_scope": "operational execution, old training, checkpoint reload and resume only",
        "bridge_names": [], "legal_ir_target_count": 0, "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1, "metric_disk_cache": False,
        "bridge_on_timing_measured": False,
        "package_imports_cold_at_start": not any(
            name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.") for name in sys.modules),
        "temperature": 0, "compute_device": "cpu", "weights_downloaded": False,
        "existing_checkpoints_modified": False, **FALSE_AUTHORITY,
    }
    try:
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        receipt["tree_pin"] = require_workspace_logic_tree()
        original_source = _source_files(jevops)
        receipt["source_sha256"] = original_source
        receipt["source_guard_scope"] = (
            "listed canonical compiler/parser/decompiler, autoformal and statement lock; "
            "lineage facade and complete frozen numerical/linguistic module snapshots; smoke script")
        receipt["typed_compiler_gates"] = _typed_gates(jevops)
        for backend in backends:
            profile_output = output / backend
            profile_output.mkdir()
            receipt["profiles"].append(_profile(
                backend, profile_output, max_seconds, receipt["typed_compiler_gates"]))
        _require(original_source == _source_files(jevops), "source files changed during smoke")
        receipt["source_unchanged"] = True
        receipt["passed"] = True
        receipt["operational_passed"] = True
        receipt["known_semantic_issues"] = [
            {"backend": profile["backend"], **issue}
            for profile in receipt["profiles"] for issue in profile["semantic_audit"]["known_issues"]]
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        receipt["elapsed_seconds"] = time.monotonic() - began
        receipt["process_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        _write_new(output / "receipt.json", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--backend", action="append", choices=BACKENDS,
                        help="Repeat to select profiles; default runs both sequentially")
    parser.add_argument("--max-seconds", type=float, default=30,
                        help="Bound each historical one-epoch call (maximum 180)")
    parser.add_argument("--jevops-root", type=Path,
                        help="Existing JevOps tree for the minimum-duration rendering gate")
    args = parser.parse_args(argv)
    try:
        receipt = run(args.output_directory, backends=tuple(args.backend or BACKENDS),
                      max_seconds=args.max_seconds, jevops_root=args.jevops_root)
    except Exception as exc:
        print(f"Legacy linguistic smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"operational_passed": receipt["operational_passed"],
                      "formula_fidelity_verified": receipt["formula_fidelity_verified"],
                      "known_semantic_issue_count": len(receipt["known_semantic_issues"]),
                      "profiles": len(receipt["profiles"]),
                      "receipt": str(args.output_directory / "receipt.json"),
                      "elapsed_seconds": receipt["elapsed_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
