#!/usr/bin/env python3
"""Compile frozen source-only generations before post-hoc reference comparison.

The immutable numerical receipts are inspected, not numerically replayed here.
Every model/source row stays in the denominator. Literal source support and Lean
compilation are separate checks; neither establishes legal meaning.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import audit_legal_decoder_codec_scope as audit
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary
from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
from ipfs_datasets_py.logic.formalization.autoencoder import gte_decoder_source_generation as raw_generation
from ipfs_datasets_py.logic.formalization.autoencoder import gte_decoder_grammar_generation as grammar_generation
from ipfs_datasets_py.logic.formalization.autoencoder import gte_decoder_interface_checkpoint as interfaces
from ipfs_datasets_py.logic.formalization.autoencoder import gte_aligned_decoder as aligned
from ipfs_datasets_py.logic.formalization.autoencoder import gte_decoder_source_evaluation as scorer

require, digest, read, file_ref = audit.require, audit.digest, audit.read, audit.file_ref
VARIANTS = ("original_donor", "original_initialization", "aligned_initialization", "original_trained", "aligned_trained")
HEADS = ("primary384", "legacy8")
CONTROLS = ("source", "zero", "cross_source")
SOURCE_FIELDS = {"id", "source_text", "source_sha256", "evaluation_role", "generation_input", "native_generation_input", "native_receipt_sha256"}


def read_ref(ref):
    require(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}, "closed file reference required")
    require(file_ref(ref["path"]) == ref, "file reference changed")
    return read(ref["path"])


def write(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode())
    return file_ref(path)


def sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def vector_hash(vector):
    require(type(vector) is list and all(raw_generation._finite_number(x) for x in vector), "finite vector required")
    return digest(vector)


def lexical_support(source, target):
    """Casefold only; exact contiguous token boundaries, without legal inference."""
    normalized = source.casefold()
    tokens = list(re.finditer(r"\w+|[^\w\s]", normalized, re.UNICODE))
    starts, ends = {m.start() for m in tokens}, {m.end() for m in tokens}
    records, by_field = [], {}
    for field in audit.FACETS[1:]:
        value = target["rules"][0][field]
        atoms = value if field in audit.QUALIFIERS else ([value] if value else [])
        support = []
        for atom in atoms:
            folded = atom.casefold()
            offsets = [[start, start + len(folded)] for start in sorted(starts)
                       if normalized.startswith(folded, start) and start + len(folded) in ends]
            records.append({"facet": field, "atom": atom, "casefolded_source_offsets": offsets,
                            "literal_source_supported": bool(offsets)})
            support.append(bool(offsets))
        by_field[field] = all(support)
    return {"policy": "unicode-casefold-exact-contiguous-token-boundaries/v1", "atoms": records,
        "offset_domain": "casefolded source character offsets; not original source offsets",
        "all_nonmodal_atoms_supported": all(by_field.values()),
        "core_atoms_supported": all(by_field[f] for f in ("actor", "action", "object")),
        "facet_literal_support": by_field, "modality_checked": False, "semantic_correctness_verified": False}


def decode_without_reference(receipt, codec, head, mode):
    if mode == "raw":
        raw_generation.inspect_source_only_generation(receipt)
        require(receipt["vocabulary_size"] == len(codec["target_vocabulary"]), "generation codec width differs")
    else:
        require(mode == "grammar", "known decoding mode required")
        grammar_generation.inspect_source_only_generation(receipt, codec)
    ids, vocabulary = receipt["generated_ids"], codec["target_vocabulary"]
    if not receipt["terminated"]:
        return None, "token_limit_without_eos"
    if ids[0] != 1:
        return None, "invalid_start_token"
    if any(t >= len(vocabulary) or t in (0, 1) for t in ids[1:-1]):
        return None, "invalid_raw_token"
    try:
        target = audit.batch._decode(ids, vocabulary, head)
    except (ValueError, TypeError, IndexError, UnicodeError, RecursionError):
        return None, "invalid_canonical_target"
    if mode == "grammar":
        require(target == receipt["decoded_target"], "grammar target differs from independent token decode")
    return target, None


def source_inventory(inputs, native_receipts):
    require(set(inputs) == {"schema", "heads", "target_access", "contains_references", "independent_holdout"}
        and inputs["schema"] == "gte-native-source-control-inputs/v1"
        and all(inputs[k] is False for k in ("target_access", "contains_references", "independent_holdout")), "closed source-only inputs required")
    require(set(inputs["heads"]) == set(HEADS), "both source heads required")
    receipts = {digest(row): row for row in native_receipts}
    require(len(receipts) == len(native_receipts), "duplicate native receipt")
    result = {}
    for head, expected_count in (("primary384", 60), ("legacy8", 2)):
        rows = inputs["heads"][head]
        require(type(rows) is list and len(rows) == expected_count, "full source cohort required")
        for row in rows:
            require(type(row) is dict and set(row) == SOURCE_FIELDS, "closed source record required")
            key = head, row["id"]
            require(key not in result and sha_text(row["source_text"]) == row["source_sha256"], "source identity/hash differs")
            expected_role = "original_validation_exposed_regression_only" if head == "primary384" else "legacy_training_diagnostic_only"
            require(row["evaluation_role"] == expected_role, "source evaluation scope differs")
            for field, width in (("generation_input", 384 if head == "primary384" else 8), ("native_generation_input", 768)):
                record = row[field]
                origin = ("exact_cached_multilingual_768d_source_receipt" if field == "native_generation_input" else
                    "original_cached_384d_validation_input" if head == "primary384" else
                    "original_8d_raw_latent_reconstructed_from_cached_embedding")
                require(set(record) == {"input_dimension", "input_vector", "input_sha256", "input_origin"}
                    and type(record["input_dimension"]) is int and record["input_dimension"] == width
                    and len(record["input_vector"]) == width and vector_hash(record["input_vector"]) == record["input_sha256"]
                    and record["input_origin"] == origin, "source coordinate binding differs")
            native = receipts.get(row["native_receipt_sha256"])
            require(native is not None and native["source_sha256"] == row["source_sha256"]
                and native["embedding"] == row["native_generation_input"]["input_vector"]
                and native["dimension"] == 768 and native["normalized"] is True and native["truncated"] is False,
                "native source embedding receipt differs")
            result[key] = row
    return result


def checkpoint_bindings(plan):
    closure = {ref["path"]: ref for ref in plan["closure"]}
    require(len(closure) == len(plan["closure"]), "duplicate closure path")
    for ref in closure.values():
        require(file_ref(ref["path"]) == ref, "pinned parent closure changed")
    def named(filename):
        refs = [ref for ref in closure.values() if Path(ref["path"]).name == filename]
        require(len(refs) == 1, "unique parent artifact required: " + filename)
        return read_ref(refs[0]), refs[0]
    initialization, init_ref = named("student-initialization.json")
    aligned_checkpoint, aligned_ref = named("aligned-student.json")
    require(aligned_checkpoint["initialization"] == initialization, "aligned initializer differs")
    pins = initialization["donor_pins"]
    config = read_ref(plan["configuration"])
    originals = {key: read_ref(config[key]) for key in ("primary_checkpoint", "legacy8_checkpoint")}
    require(config["primary_checkpoint"]["sha256"] == pins["teacher384_checkpoint_sha256"]
        and config["legacy8_checkpoint"]["sha256"] == pins["legacy8_checkpoint_sha256"], "original donor file hashes differ")
    require(digest(originals["primary_checkpoint"]["model_state"]) == pins["teacher384_weights_sha256"]
        and digest(originals["legacy8_checkpoint"]["model_state"]) == pins["legacy8_weights_sha256"], "donor tensor hashes differ")
    states = {"original_initialization": interfaces._state(initialization),
              "aligned_initialization": aligned._state(initialization, aligned_checkpoint["bridge"])}
    require(digest(states["aligned_initialization"]) == aligned_checkpoint["model_state_sha256"], "aligned assembled state differs")
    model_refs = {"original_donor": [config["primary_checkpoint"], config["legacy8_checkpoint"]],
        "original_initialization": [init_ref], "aligned_initialization": [aligned_ref]}
    codec_hashes = {head: digest(initialization["primary" if head == "primary384" else "legacy8"]["codec"]) for head in HEADS}
    for label, runtime_key in (("original_trained", "original_runtime"), ("aligned_trained", "aligned_runtime")):
        runtime = read_ref(config[runtime_key])
        checkpoint_ref = runtime["checkpoint"]
        require(closure.get(checkpoint_ref["path"]) == checkpoint_ref, "trained checkpoint absent from closure")
        checkpoint = read_ref(checkpoint_ref)
        require(checkpoint["codec_sha256"] == codec_hashes and checkpoint["all_26_inherited_tensors_unchanged"] is True,
                "trained codec or inherited tensor declaration differs")
        require(set(checkpoint["interfaces"]) == {"primary.input_adapter.weight", "primary.input_adapter.bias",
            "auxiliary_connector.weight", "auxiliary_connector.bias"}, "exact four trained interface tensors required")
        state = interfaces._state(initialization, checkpoint["interfaces"])
        require(digest(state) == checkpoint["model_state_sha256"] and len(state) == 30, "trained assembled tensor state differs")
        states[label], model_refs[label] = state, [checkpoint_ref, config[runtime_key]]
    state_hashes = {label: {head: digest(state) for head in HEADS} for label, state in states.items()}
    state_hashes["original_donor"] = {"primary384": pins["teacher384_weights_sha256"], "legacy8": pins["legacy8_weights_sha256"]}
    native_refs = [r for r in closure.values() if Path(r["path"]).parts[-2:] == ("embeddings-complete", "receipts.json")]
    require(len(native_refs) == 1, "complete native embedding receipt file required")
    return initialization, state_hashes, model_refs, read_ref(native_refs[0])


def generation_inventory(frozen, directory, mode):
    require(frozen["all_variants_completed"] is True and frozen["scoring_started"] is False
        and frozen["reference_prefix_used"] is False, "generation must be completely frozen before scoring")
    controls = CONTROLS if mode == "raw" else ("source",)
    expected = {str(Path(directory).resolve() / ("generation-" + label + ("-" + control if mode == "raw" else "") + ".json"))
        for label in VARIANTS for control in controls}
    refs = frozen["generation_files"]
    require(type(refs) is list and len(refs) == len(expected) and {r["path"] for r in refs} == expected
        and frozen["generation_count"] == len(expected) * 62, "complete model/control generation coverage required")
    for ref in refs:
        require(file_ref(ref["path"]) == ref, "frozen generation file changed")
    return {label: next(r for r in refs if Path(r["path"]).name == "generation-" + label + ("-source" if mode == "raw" else "") + ".json")
            for label in VARIANTS}


def admit_row(row, source, label, codec, state_hash, budget, mode):
    expected_fields = {"id", "source_text", "source_sha256", "evaluation_role", "head", "variant", "intervention", "generation"}
    if mode == "grammar": expected_fields.add("control")
    require(type(row) is dict and set(row) == expected_fields and row["variant"] == label
        and (mode != "grammar" or row["control"] == "source"), "closed source generation row required")
    require(all(row[key] == source[key] for key in ("id", "source_text", "source_sha256", "evaluation_role")), "generation source differs")
    original = source["generation_input" if label == "original_donor" else "native_generation_input"]
    expected_intervention = {"control": "source", "receiving_id": source["id"], "receiving_source_sha256": source["source_sha256"],
        "original_input_sha256": original["input_sha256"], "effective_input_sha256": original["input_sha256"], "donor": None,
        "provenance": "original_donor_source_coordinates" if label == "original_donor" else "native_source_receipt",
        "zero_input_is_disabled_context": False, "target_access": False}
    require(row["intervention"] == expected_intervention, "source generation intervention differs")
    receipt = row["generation"]
    expected_variant = ("donor384" if row["head"] == "primary384" else "legacy8") if label == "original_donor" else "student768"
    require(receipt["variant"] == expected_variant and receipt["head"] == row["head"]
        and receipt["input_vector_sha256"] == original["input_sha256"]
        and receipt["model_state_sha256_before"] == receipt["model_state_sha256_after"] == state_hash
        and all(receipt[key] == value for key, value in budget.items()), "generation model/input/budget binding differs")
    rounded = [struct.unpack("!f", struct.pack("!f", value))[0] for value in original["input_vector"]]
    require(receipt["numerical_input_sha256"] == digest(rounded), "float32 source vector hash differs")
    return decode_without_reference(receipt, codec, row["head"], mode)


def verify_donor_coordinates(sources, reference_rows, legacy_inputs):
    """Rejoin original cached384 and reconstructed8 coordinates after builds."""
    _, legacy_training = scorer._NATIVE._legacy_sources(legacy_inputs)
    legacy_vectors = {row["id"]: row for row in legacy_training}
    for (head, identity), source in sources.items():
        if head == "primary384":
            original = reference_rows[head, identity]
            vector = original["embedding"]
        else:
            original = legacy_vectors[identity]
            vector = original["latent"]
        require(original["source_text"] == source["source_text"] and
            source["generation_input"]["input_vector"] == vector and
            source["generation_input"]["input_sha256"] == digest(vector), "original donor coordinates differ from source archive")


def posthoc_sources(plan, sources):
    refs = [ref for ref in plan["closure"] if Path(ref["path"]).name == "native-batch.json"]
    require(len(refs) == 1, "one native reference archive required")
    archive = read_ref(refs[0])
    require(len(archive["audit_rows"]) == 242, "original full archive row count differs")
    rows = {("primary384", r["id"]): r for r in archive["audit_rows"][180:240]}
    rows.update({("legacy8", r["id"]): r for r in archive["audit_rows"][240:]})
    require(set(rows) == set(sources) and len(rows) == 62, "original reference source cohort differs")
    for key, row in rows.items():
        require(row["source_text"] == sources[key]["source_text"] and sha_text(row["source_text"]) == sources[key]["source_sha256"],
                "post-hoc reference source differs")
    verify_donor_coordinates(sources, rows, archive["legacy8_inputs"])
    return rows, refs[0]


def posthoc_score(receipt, target, codec, head, *, builds_frozen):
    require(builds_frozen.get("all_builds_completed") is True and builds_frozen.get("scores_opened") is False,
            "completed score-blind builds must be frozen before reference scoring")
    ids = audit.batch._encode(target, codec["target_vocabulary"], head)
    reference = {"target": target, "target_sha256": digest(target), "token_ids": ids, "token_ids_sha256": digest(ids)}
    return scorer.score_generation({key: receipt[key] for key in ("generated_ids", "terminated", "truncated")}, reference, codec, head)


def run(directory, output, *, mode, toolchain, lake_executable, timeout=60):
    directory, output = Path(directory).resolve(), Path(output).resolve()
    require(mode in ("raw", "grammar") and not output.exists(), "known mode and fresh output required")
    freeze_ref = file_ref(directory / "generation-frozen.json")
    frozen = read_ref(freeze_ref)
    require(frozen["schema"] == ("gte-native-source-controls-frozen/v1" if mode == "raw" else "gte-grammar-controls-frozen/v1"), "generation freeze schema differs")
    generation_refs = generation_inventory(frozen, directory, mode)
    own_plan = read_ref(frozen["plan"])
    require(own_plan["inputs"] == frozen["inputs"] and own_plan["variants"] == list(VARIANTS) and own_plan["heads"] == list(HEADS), "plan source/model closure differs")
    if mode == "grammar":
        plan = read_ref(own_plan["baseline_plan"])
        baseline_freeze = read_ref(own_plan["baseline_generation_freeze"])
        require(baseline_freeze["plan"] == own_plan["baseline_plan"], "grammar baseline plan differs")
        for ref in own_plan["implementations"]:
            require(file_ref(ref["path"]) == ref, "grammar runner implementation changed")
        replay = read_ref(frozen["numerical_replay"])
        require(replay["rows_replayed"] == 310 and replay["all_generated_tokens_logits_and_receipts_exact"] is True
            and replay["generation_files"] == frozen["generation_files"], "complete grammar numerical replay required")
    else:
        plan = own_plan
    require(plan["variants"] == list(VARIANTS) and plan["controls"] == list(CONTROLS)
        and plan["per_head_rows"] == {"primary384": 60, "legacy8": 2}, "complete historical comparison plan required")
    initialization, state_hashes, model_refs, native_receipts = checkpoint_bindings(plan)
    inputs = read_ref(frozen["inputs"])
    sources = source_inventory(inputs, native_receipts)
    require(inputs == read_ref(plan["inputs"]), "grammar/base source coordinates differ")
    producer_refs = [file_ref(module.__file__) for module in (audit, calendar, calendar_summary, gate, raw_generation,
        grammar_generation, interfaces, aligned, scorer)] + [file_ref(__file__)]
    panels, selections, details = {}, [], []
    for label in VARIANTS:
        panel = read_ref(generation_refs[label])
        require(panel["variant"] == label and panel["control"] == "source" and panel["reference_prefix_used"] is False
            and panel["references_used_for_generation"] is False, "source-only generation panel required")
        rows = panel["rows"]
        require(len(rows) == 62 and len({(r["head"], r["id"]) for r in rows}) == 62
            and {(r["head"], r["id"]) for r in rows} == set(sources), "full unique panel source coverage required")
        selected_sources, predicted = [], []
        for row in rows:
            head, key = row["head"], (row["head"], row["id"])
            codec = initialization["primary" if head == "primary384" else "legacy8"]["codec"]
            target, reason = admit_row(row, sources[key], label, codec, state_hashes[label][head], plan["budgets"][head], mode)
            candidate_id = head + ":" + row["id"]
            source = {"id": candidate_id, "source_text": row["source_text"], "source_sha256": row["source_sha256"]}
            selected_sources.append(source)
            predicted.append({"id": candidate_id, "source_sha256": source["source_sha256"], "status": "decoded" if target is not None else "abstained",
                "canonical_ir": target, "reason": reason, "target_access": False, "teacher_forcing": False})
            details.append({"variant": label, "head": head, "id": row["id"], "candidate_id": candidate_id,
                "source_sha256": row["source_sha256"], "generation_sha256": digest(row["generation"]),
                "generated_ids_sha256": row["generation"]["generated_ids_sha256"], "syntax_valid": target is not None,
                "canonical_ir": target, "invalid_reason": reason,
                "literal_source_support": lexical_support(row["source_text"], target) if target is not None else None})
        selection = calendar.select_candidates(selected_sources, predicted, toolchain=toolchain, policy=calendar.POLICY)
        for entry in selection["rows"]:
            require(entry["interpretation"] == calendar_summary.expected_interpretation(entry["candidate"]), "independent caller-interpretation replay differs")
        selections.append({"variant": label, **selection})
        panels[label] = rows
    output.mkdir(parents=True, exist_ok=False)
    policy_ref = write(output / "interpretation-policy.json", calendar.POLICY_DESCRIPTION)
    selection_ref = write(output / "selected-candidates.json", {"schema": "gte-reference-free-candidate-selection/v1",
        "generation_freeze": freeze_ref, "mode": mode, "models": selections, "rows": details,
        "producer_files": producer_refs, "model_references": model_refs, "model_state_sha256": state_hashes,
        "canonical_references_used_for_selection": False, "semantic_scores_used_for_selection": False})
    builds, built = [], set()
    for selection in selections:
        label = selection["variant"]
        records = []
        for start in range(0, len(selection["rows"]), gate.MAX_ROWS):
            entries = selection["rows"][start:start + gate.MAX_ROWS]
            folder = output / label / f"lake-{start // gate.MAX_ROWS:03d}"
            receipt = gate.build_qualified_legal(entries, toolchain=toolchain, lake_executable=lake_executable,
                timeout_seconds=timeout, output_directory=folder).to_dict()
            ref = file_ref(folder / "qualified-receipt.json")
            verified = calendar_summary.verify_receipt({"path": ref["path"], "sha256": ref["sha256"]}, entries)
            require(verified == receipt, "build receipt replay differs")
            if receipt["build_passed"]:
                built.update((label, entry["candidate"]["candidate_id"]) for entry in entries)
            records.append({"candidate_count": len(entries), "receipt": ref,
                **{key: receipt[key] for key in ("build_passed", "backend_executed", "manifest_coverage_passed", "returncode", "command")}})
        builds.append({"variant": label, "builds": records})
        print(json.dumps({"phase": "built", "mode": mode, "variant": label,
            "syntax_valid": selection["decoded_count"], "supported": selection["supported_count"],
            "built": sum(v == label for v, _ in built)}), flush=True)
    build_ref = write(output / "builds-frozen.json", {"schema": "gte-reference-free-build-freeze/v1",
        "selections": selection_ref, "generation_freeze": freeze_ref, "models": builds, "all_builds_completed": True,
        "scores_opened": False, "references_used_for_selection_or_builds": False, "target": "legal", "toolchain": toolchain,
        "interpretation_policy": policy_ref, "proof_authority": False})
    frozen_builds = read_ref(build_ref)
    # This is the first evaluation-reference or score-file read in this checker.
    references, reference_ref = posthoc_sources(plan, sources)
    run_summary = read(directory / "summary.json")
    require(run_summary["generation_freeze"] == freeze_ref, "scored summary generation differs")
    score_ref = run_summary["scores"]
    scores = read_ref(score_ref)
    require(scores["generation_freeze"] == freeze_ref and len(scores["rows"]) == frozen["generation_count"], "scoring cohort differs")
    lookup = {(r["variant"], r["head"], r["id"]): r for r in scores["rows"] if r["control"] == "source"}
    require(len(lookup) == 310 and len([r for r in scores["rows"] if r["control"] == "source"]) == 310, "complete unique scored source cohort required")
    details_by_key = {(r["variant"], r["head"], r["id"]): r for r in details}
    selected_keys = {(m["variant"], e["candidate"]["candidate_id"]) for m in selections for e in m["rows"]}
    counts, evaluated = {}, []
    for label, rows in panels.items():
        for row in rows:
            head, identity = row["head"], row["id"]
            key = label, head, identity
            codec = initialization["primary" if head == "primary384" else "legacy8"]["codec"]
            score = posthoc_score(row["generation"], references[head, identity]["reference_target"], codec, head, builds_frozen=frozen_builds)
            recorded = lookup[key]
            require(recorded["source_text"] == row["source_text"] and recorded["source_sha256"] == row["source_sha256"]
                and recorded["generation_file"] == generation_refs[label] and recorded["generation_sha256"] == digest(row["generation"])
                and recorded["score"] == score, "independent post-hoc score/source/generation binding differs")
            detail = details_by_key[key]
            require(detail["syntax_valid"] == score["syntax_valid"] and detail["canonical_ir"] == score["decoded_target"]
                and detail["generated_ids_sha256"] == score["generated_ids_sha256"], "reference-free decode differs from scorer")
            was_built = (label, detail["candidate_id"]) in built
            supported = (label, detail["candidate_id"]) in selected_keys
            lexical = detail["literal_source_support"]
            exact = score["exact_target_match"]
            count = counts.setdefault((label, head), Counter())
            count.update({"source_count": 1, "syntax_valid": int(detail["syntax_valid"]), "unsupported_or_invalid": int(not supported),
                "supported": int(supported), "built": int(was_built), "exposed_reference_exact": int(exact),
                "built_and_exposed_reference_exact": int(was_built and exact), "built_but_exposed_reference_wrong": int(was_built and not exact),
                "all_nonmodal_atoms_literal_supported": int(lexical is not None and lexical["all_nonmodal_atoms_supported"]),
                "built_with_literal_unsupported_atom": int(was_built and lexical is not None and not lexical["all_nonmodal_atoms_supported"])})
            evaluated.append({**detail, "supported": supported, "built": was_built,
                "exposed_reference_exact": exact, "reference_target_sha256": score["reference_sha256"]})
    for ref in [*plan["closure"], *producer_refs, *frozen["generation_files"], freeze_ref, frozen["plan"], frozen["inputs"], selection_ref, build_ref, score_ref]:
        require(file_ref(ref["path"]) == ref, "input or checker changed during builds/scoring")
    models = [{"variant": label, "head": head, **dict(counts[label, head])} for label in VARIANTS for head in HEADS]
    report = {"schema": "gte-reference-free-output-build-audit/v1", "mode": mode, "generation_freeze": freeze_ref,
        "selection": selection_ref, "build_freeze": build_ref, "scored_report": score_ref, "reference_archive": reference_ref,
        "models": models, "rows": evaluated, "totals": {key: sum(m[key] for m in models) for key in models[0] if key not in {"variant", "head"}},
        "reference_scores_recomputed_after_build_freeze": True, "source_native_receipts_rejoined": True,
        "model_state_hashes_reconstructed_from_checkpoint_tensors": True, "generation_numerics_replayed_by_this_checker": False,
        "original_donor_coordinates_rejoined_after_builds": True,
        "actual_lake_build_executed": any(batch["backend_executed"] for model in builds for batch in model["builds"]),
        "compiled_artifact_bytes_reverified": False,
        "compiled_artifact_scope": "Receipt module hashes and coverage rechecked; temporary olean bytes were removed by the existing runner.",
        "scope": "60 exposed authored validation sources and two legacy training diagnostics per model; not independent statutory evaluation. Casefolded literal matches do not establish semantics; Lean builds check explicitly declared interpretations.",
        "target": "legal", "toolchain": toolchain, "qualified": False, "source_semantics_verified": False, "proof_authority": False}
    ref = write(output / "summary.json", report)
    print(json.dumps({"summary": ref, "totals": report["totals"]}, sort_keys=True), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--mode", required=True, choices=("raw", "grammar"))
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--lake-executable", required=True)
    args = parser.parse_args()
    run(args.run_directory, args.output_directory, mode=args.mode, toolchain=args.toolchain, lake_executable=args.lake_executable)


if __name__ == "__main__":
    main()
