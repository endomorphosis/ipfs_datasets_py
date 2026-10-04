#!/usr/bin/env python3
"""Audit inherited codec ceilings without running models or assigning legal gold.

Only completed, already-exposed synthetic references are admitted. Source-only
statutory diagnostics describe input bounds and literal inventories, never
semantic coverage. An interface checkpoint cannot enlarge its inherited codec.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.formalization.autoencoder import gte_decoder_transfer_batch as batch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as legacy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span

FACETS = batch._FACETS
QUALIFIERS = FACETS[4:]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return batch.digest(value)


def file_ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def read(path):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("nonfinite JSON: " + value)
    require(Path(path).stat().st_size <= 128 * 1024**2, "artifact exceeds audit byte bound")
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=invalid)


def verify_ref(ref):
    actual = file_ref(ref["path"])
    require(actual["sha256"] == ref["sha256"] and actual["bytes"] == ref["bytes"], "artifact binding differs")
    return read(ref["path"])


def string_inventory(codec, kind):
    if kind == "primary384":
        batch._TEACHER._codec({"codec": codec})
        return sorted(json.loads(token) for token in codec["target_vocabulary"][3:] if token.startswith('"'))
    legacy.validate_codec(codec)
    result = {field: [] for field in FACETS}
    for token in codec["target_vocabulary"][3:]:
        atom = json.loads(token)
        if atom[0] == "atom":
            result[atom[1]].append(atom[2])
    return {field: sorted(values) for field, values in result.items()}


def missing_atoms(target, codec, kind):
    rule = batch._rule(target)
    values = string_inventory(codec, kind)
    return {field: [atom for atom in (rule[field] if field in QUALIFIERS else [rule[field]])
                    if atom not in (values if kind == "primary384" else values[field])]
            for field in FACETS}


def target_coverage(examples, codec, kind, max_tokens):
    rows = []
    missing = Counter({field: 0 for field in FACETS})
    for row in examples:
        absent = missing_atoms(row["canonical_ir"], codec, kind)
        missing.update(field for field, values in absent.items() if values)
        try:
            ids = batch._encode(row["canonical_ir"], codec["target_vocabulary"], kind)
            require(len(ids) <= max_tokens, "inherited target token budget exceeded")
            require(batch._decode(ids, codec["target_vocabulary"], kind) == row["canonical_ir"], "codec round-trip differs")
            encoded, reason, token_count = True, None, len(ids)
        except ValueError as error:
            encoded, reason, token_count = False, str(error), None
        rows.append({"id": row["id"], "source_sha256": row["source_sha256"],
            "target_sha256": digest(row["canonical_ir"]), "exact_target_representable": encoded,
            "missing_atoms_by_facet": absent, "reason": reason, "encoded_token_count": token_count})
    count = sum(row["exact_target_representable"] for row in rows)
    return {"count": len(rows), "exact_target_representable": count,
        "theoretical_maximum_exact_matches_on_this_panel": count,
        "rows_with_unknown_atoms_by_facet": dict(missing), "rows": rows,
        "measured_model_accuracy": None, "model_execution_performed": False}


def source_diagnostics(groups, primary_codec, legacy_codec):
    primary = set(string_inventory(primary_codec, "primary384"))
    legacy_atoms = set(itertools.chain.from_iterable(string_inventory(legacy_codec, "legacy8").values()))
    rows = []
    for group in groups:
        source = group["source_text"]
        require(hashlib.sha256(source.encode()).hexdigest() == group["source_text_sha256"], "review source hash differs")
        require(group["gold_target"] is None and not group["training_qualified"], "audit expects unreviewed packet")
        try:
            tokens = span.tokenize_source(source)
            accepted, reason, token_count = True, None, len(tokens)
            starts, ends = {t["start"] for t in tokens}, {t["end"] for t in tokens}
            def occurs(atom):
                return any(source.startswith(atom, start) and start + len(atom) in ends for start in starts)
            primary_matches = sorted(atom for atom in primary if occurs(atom))
            legacy_matches = sorted(atom for atom in legacy_atoms if occurs(atom))
        except ValueError as error:
            accepted, reason, token_count = False, str(error), None
            primary_matches, legacy_matches = None, None
        rows.append({"source_text_sha256": group["source_text_sha256"], "source_text": source,
            "source_observation_count": len(group["source_observations"]),
            "span_source_tokenizer_accepted": accepted, "span_source_token_count": token_count,
            "source_rejection_reason": reason,
            "primary384_string_values_found_as_exact_token_aligned_spans": primary_matches,
            "legacy8_string_values_found_as_exact_token_aligned_spans": legacy_matches,
            "semantic_coverage": None, "exact_target_representability": None})
    return {"text_groups": len(rows), "source_observations": sum(r["source_observation_count"] for r in rows),
        "span_tokenizer_accepted_groups": sum(r["span_source_tokenizer_accepted"] for r in rows),
        "span_tokenizer_accepted_observations": sum(r["source_observation_count"] for r in rows if r["span_source_tokenizer_accepted"]),
        "max_span_source_tokens": max((r["span_source_token_count"] or 0) for r in rows),
        "groups_with_primary384_literal_atom_occurrence": sum(bool(r["primary384_string_values_found_as_exact_token_aligned_spans"]) for r in rows),
        "groups_with_legacy8_literal_atom_occurrence": sum(bool(r["legacy8_string_values_found_as_exact_token_aligned_spans"]) for r in rows),
        "no_target_labels_inferred": True, "neural_generation_performed": False,
        "interpretation": "Tokenizer acceptance is an input-bound check only. Literal inventory overlap is not meaning or target coverage. Empty overlap cannot prove semantic failure without a reviewed target.",
        "legacy_source_vocabulary_note": "The stored legacy source vocabulary contains latent; it is provenance-only in this inherited latent decoder and is not a statutory source input gate.",
        "rows": rows}


def assert_interface_codecs(initialization, checkpoints):
    expected = {name: digest(initialization[nested]["codec"]) for name, nested in (("primary384", "primary"), ("legacy8", "legacy8"))}
    require(expected["primary384"] == initialization["donor_pins"]["teacher384_codec_sha256"], "primary donor codec hash differs")
    require(expected["legacy8"] == initialization["donor_pins"]["legacy8_codec_sha256"], "legacy donor codec hash differs")
    for checkpoint in checkpoints:
        require(checkpoint["codec_sha256"] == expected, "trained interface output codec changed")
    return expected


def audit(base):
    base = Path(base).resolve()
    paths = {"aligned_decoder": base / "native768/aligned-decoder/aligned-student.json",
        "original_interfaces": base / "native768/original-interface-precise-01/trained-interfaces.json",
        "aligned_interfaces": base / "native768/aligned-interface-precise-01/trained-interfaces.json",
        "corpus": base / "prepared/corpus.json", "challenge_targets": base / "prepared/sealed-evaluation-targets.json",
        "completed_experiment": base / "run-01/summary.json", "review_packet": base / "review-packet.json"}
    inputs = {key: read(path) for key, path in paths.items()}
    require(inputs["completed_experiment"]["challenge_targets_read_after_all_training_selection_and_generation"] is True,
            "only completed already-exposed target panels may be audited")
    initialization = inputs["aligned_decoder"]["initialization"]
    codec_hashes = assert_interface_codecs(initialization, [inputs["original_interfaces"], inputs["aligned_interfaces"]])
    corpus, target_blob = inputs["corpus"], inputs["challenge_targets"]
    require(verify_ref(corpus["sealed_targets"]) == target_blob, "corpus challenge target binding differs")
    require(target_blob["frozen_plan"] == corpus["frozen_plan"], "challenge plan binding differs")
    targets = {row["id"]: row for row in target_blob["targets"]}
    require(len(targets) == len(target_blob["targets"]), "duplicate target IDs")
    examples = []
    for source in corpus["splits"]["challenge"]:
        target = targets.pop(source["id"])
        require(source["source_sha256"] == target["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(), "target source binding differs")
        require(source["canonical_target_sha256"] == target["canonical_target_sha256"] == digest(target["canonical_ir"]), "target hash differs")
        examples.append({"id": source["id"], "source_text": source["source_text"], "source_sha256": source["source_sha256"], "canonical_ir": target["canonical_ir"]})
    require(not targets, "unused challenge targets")
    primary = initialization["primary"]["codec"]
    legacy_codec = initialization["legacy8"]["codec"]
    primary_strings = string_inventory(primary, "primary384")
    legacy_values = string_inventory(legacy_codec, "legacy8")
    # The strict primary reference codec permits untyped known strings in any
    # string field. A finite training inventory is not field-specific grammar.
    n = len(primary_strings)
    combinations = sum(math.comb(n, size) for size in range(5))
    legacy_candidates = [{"rules": [{"modality": m, "actor": a, "action": v, "object": o,
        "conditions": [], "exceptions": [], "temporal": []}]}
        for m, a, v, o in itertools.product(*(legacy_values[f] for f in FACETS[:4]))]
    require(all(not legacy_values[f] for f in QUALIFIERS), "explicit legacy enumeration requires empty qualifier inventories")
    for target in legacy_candidates:
        ids = batch._encode(target, legacy_codec["target_vocabulary"], "legacy8")
        require(batch._decode(ids, legacy_codec["target_vocabulary"], "legacy8") == target, "legacy enumeration fails codec")
    copy_audit = span.audit_examples(examples)
    packet = inputs["review_packet"]
    actual = source_diagnostics(packet["groups"], primary, legacy_codec)
    require(actual["source_observations"] == packet["deduplication"]["source_observations"], "review observation coverage differs")
    require(actual["text_groups"] == packet["deduplication"]["unique_text_groups"], "review text-group coverage differs")
    return {"schema": "legal-decoder-codec-scope-audit/v1", "input_artifacts": {key: file_ref(path) for key, path in paths.items()},
        "implementation": {"audit": file_ref(__file__), "transfer_codec": file_ref(batch.__file__),
            "legacy_codec": file_ref(legacy.__file__), "span_decoder": file_ref(span.__file__),
            "primary_codec_validator": file_ref(batch._TEACHER.__file__)},
        "codec_hashes_equal_in_both_trained_768_interfaces": codec_hashes,
        "scope": "Post-hoc structural expressivity audit. No models run or trained. No independently reviewed statutory gold supplied.",
        "primary384": {"codec_schema": primary["schema"], "vocabulary_size": len(primary["target_vocabulary"]),
            "complete_string_atom_count": n, "complete_string_atoms": primary_strings,
            "string_atom_encoding": "One token per complete JSON string; unseen strings cannot be composed from characters, pieces, or adjacent string tokens.",
            "string_values_are_field_typed": False, "grammar_scope": "The inherited strict reference encoder/scorer requires exactly one rule, three nonempty scalar strings, modality O/P/F, and at most four sorted unique atoms per qualifier facet.",
            "inherited_max_target_tokens": initialization["primary"]["config"]["max_target_tokens"],
            "strict_reference_grammar_admissible_rule_count": 3 * n**3 * combinations**3,
            "count_derivation": "3 modalities * n^3 actor/action/object strings * (sum(comb(n,k), k=0..4))^3 qualifier lists. All possible sequences fit the inherited 512-token budget. This is grammar expressivity, not learned or meaningful output coverage.",
            "challenge": target_coverage(examples, primary, "primary384", initialization["primary"]["config"]["max_target_tokens"])},
        "legacy8": {"codec_schema": legacy_codec["schema"], "vocabulary_size": len(legacy_codec["target_vocabulary"]),
            "field_typed_atoms": legacy_values, "exact_supported_canonical_rules": legacy_candidates,
            "strict_reference_grammar_admissible_rule_count": len(legacy_candidates),
            "inherited_max_target_tokens": initialization["legacy8"]["config"]["max_target_tokens"],
            "lineage_note": "This is the inherited 8D residual-projection GRU formula head, not the historical 8D linguistic-feature autoencoder itself.",
            "challenge": target_coverage(examples, legacy_codec, "legacy8", initialization["legacy8"]["config"]["max_target_tokens"])},
        "source_copy": {"architecture": span.ARCHITECTURE, "challenge_count": len(examples),
            "exact_targets_supported_by_existing_training_interface": len(copy_audit["accepted_ids"]), "audit": copy_audit,
            "fixed_byte_alphabet": 257, "fitted_target_vocabulary": False,
            "max_source_characters": span.MAX_SOURCE_CHARACTERS, "max_source_tokens": span.MAX_SOURCE_TOKENS,
            "max_token_utf8_bytes_after_casefold": span.MAX_TOKEN_BYTES,
            "output_scope": "One O/P/F rule; nonempty actor/action, optional object; at most one contiguous source span per qualifier facet; exact token boundaries; non-overlapping facet spans; canonical validator restrictions also apply.",
            "training_label_scope": "Training labels additionally require a unique matching occurrence of each nonempty copied atom. Repeated identical mentions may be representable at inference yet rejected as ambiguous training labels.",
            "paraphrase_or_implicit_atom_output_supported": False,
            "measured_model_accuracy": None},
        "authored_panel_scope": "192 previously exposed authored challenge rows from existing templates with new actor/qualifier values. This is not independent statutory evaluation or new grammar coverage.",
        "statutory_diagnostic": {"repository": packet["repository"], "revision": packet["revision"], "scope": packet["scope"], **actual},
        "recommendations": [
            {"priority": 1, "change": "Keep the inherited closed-vocabulary heads for regression tests; test native768 context in an open-vocabulary source-copy or byte/subword AST decoder.", "reason": "Input adaptation cannot add target atoms to frozen output embeddings/logits. Both inherited heads have a zero exact-target ceiling on this panel."},
            {"priority": 2, "change": "Add an explicit rule-list decoder and typed scope/operator nodes with source-span arguments; train rule boundaries and scope attachment with independently authored minimal pairs.", "reason": "The existing span head emits one rule and opaque qualifier strings. More latent dimensions cannot remove that output restriction."},
            {"priority": 3, "change": "Use pointer spans for explicit text and a separately supervised byte/subword path for declared paraphrases or inherited-context atoms, with provenance on every output atom.", "reason": "Current span copying handles unseen explicit values but cannot express normalization, implicit actors, or noncontiguous atoms. Do not invent these during decoding or turn schema validity into legal correctness."},
            {"priority": 4, "change": "Score source-only free generation before reading references and separate expressibility, syntax, Lean build, facet retention, and independently reviewed semantic accuracy.", "reason": "Closed-vocabulary regression and authored span tests answer different questions; the 45-observation packet has no qualified gold and is not a full dataset census."}],
        "qualified": False, "proof_authority": False, "training_executed": False, "model_execution_performed": False,
        "statutory_semantic_accuracy": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.base)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"artifact": file_ref(args.output), "primary384_exact_ceiling": report["primary384"]["challenge"]["exact_target_representable"],
        "legacy8_exact_ceiling": report["legacy8"]["challenge"]["exact_target_representable"],
        "source_copy_supported": report["source_copy"]["exact_targets_supported_by_existing_training_interface"],
        "statutory_source_groups": report["statutory_diagnostic"]["text_groups"]}, sort_keys=True))


if __name__ == "__main__":
    main()
