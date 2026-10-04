#!/usr/bin/env python3
"""Exercise learned clause outputs through the source-bound rule-list composer.

Documents are fixed authored concatenations A/newline/B/newline/A of the first
24 exposed challenge sources. Clause boundaries and independent flat scope are
explicitly supplied; neither segmentation nor document semantics is learned.
No reference targets or reference scores select documents, models, or builds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_open_vocabulary_experiment as experiment
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary
from scripts.ops.legal_ir.summarize_legal_structured_retrieval_experiment import verify_generation
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as compose
from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate

require, read, sha, write = experiment.require, experiment.read, experiment.sha, experiment.write


def read_ref(ref):
    require(type(ref) is dict and {"path", "sha256"} <= set(ref), "artifact reference required")
    require(sha(ref["path"]) == ref["sha256"], "artifact bytes changed")
    if "bytes" in ref:
        require(Path(ref["path"]).stat().st_size == ref["bytes"], "artifact length differs")
    return read(ref["path"])


def source_plans(sources, *, document_count=12):
    """Use every predeclared member of the bounded integration panel, no scores."""
    require(type(document_count) is int and 1 <= document_count <= 32
            and len(sources) >= document_count * 2, "bounded complete source panel required")
    selected = sources[:document_count * 2]
    require(len({row["id"] for row in selected}) == len(selected), "duplicate source identity")
    for row in selected:
        require(hashlib.sha256(row["source_text"].encode()).hexdigest() == row["source_sha256"], "source hash differs")
    result = []
    for ordinal in range(document_count):
        first, second = selected[2 * ordinal:2 * ordinal + 2]
        clause_sources = [first, second, first]
        text = "\n".join(row["source_text"] for row in clause_sources)
        source = {"candidate_id": f"declared-composition-{ordinal:02d}", "source_text": text,
                  "source_sha256": hashlib.sha256(text.encode()).hexdigest()}
        declarations, start = [], 0
        for index, row in enumerate(clause_sources):
            end = start + len(row["source_text"])
            declarations.append({"clause_id": f"clause-{index}", "char_start": start, "char_end": end,
                                 "scope": compose.FLAT_SCOPE})
            start = end + 1
        plan = compose.prepare_source_plan(source, declarations)
        result.append({"plan": plan, "clause_source_ids": [row["id"] for row in clause_sources]})
    return result


def compose_document(document, predictions):
    plan = document["plan"]
    sources = document["clause_source_ids"]
    require(len(sources) == plan["clause_count"], "complete declared source occurrences required")
    clauses = []
    for declaration, identity in zip(plan["clauses"], sources):
        require(identity in predictions, "missing frozen clause prediction")
        clauses.append(compose.attach_span_prediction(plan, declaration["clause_id"], predictions[identity],
            scope=compose.FLAT_SCOPE, expected_plan_sha256=plan["plan_sha256"]))
    result = compose.compose_rule_list(plan, clauses, expected_plan_sha256=plan["plan_sha256"])
    restored = compose.reconstruct_source_rule_list(result, expected_plan_sha256=plan["plan_sha256"])
    require(len(restored) == 3 and restored[0] == restored[2], "duplicate learned rule occurrence was lost")
    return result


def validate_heads(plan, heads):
    names = {f"{arm}-{seed}" for arm in plan["arms"] for seed in plan["seeds"]}
    require(type(heads) is list and len(heads) == len(names) and {head["name"] for head in heads} == names,
        "complete selected model coverage required")
    for head in heads:
        require(head["arm"] in plan["arms"] and head["seed"] in plan["seeds"]
            and head["name"] == f"{head['arm']}-{head['seed']}"
            and head["dimension"] == plan["arms"][head["arm"]], "selected model attribution differs")


def run(args):
    directory, output = Path(args.run_directory), Path(args.output)
    plan_ref = experiment.file_ref(directory / "plan.json")
    plan = read_ref(plan_ref)
    require(plan["schema"] == experiment.SCHEMA and plan["arms"] == {
        "source_only": 0, "trained384": 384, "native768": 768} and plan["seeds"] == [1729, 1730, 1731],
        "complete fixed three-arm three-seed experiment required")
    freeze_ref = experiment.file_ref(directory / "generation-frozen.json")
    frozen = read_ref(freeze_ref)
    require(frozen["all_generation_complete"] is True and frozen["challenge_targets_read_in_this_execution"] is False,
        "complete pre-score generation freeze required")
    heads = read_ref(frozen["frozen_heads"])
    validate_heads(plan, heads)
    sources_ref = experiment.file_ref(directory / "prepared-inputs.json")
    prepared = read_ref(sources_ref)
    sources = prepared["challenge"]
    context_manifest = read_ref(plan["context_manifest"])
    native_manifest = read_ref(context_manifest["native_production_manifest"])
    original_sources_ref = native_manifest["source_artifact"]
    original_sources = read_ref(original_sources_ref)
    require(sources == original_sources["challenge"], "composition source inventory differs from pinned native source artifact")
    require(len(sources) == 192 and len({r["id"] for r in sources}) == 192
        and all("canonical_ir" not in row for row in sources), "complete source-only regression input panel required")
    documents = source_plans(sources)
    output.mkdir(parents=True, exist_ok=False)
    pins = {str(Path(module.__file__).resolve()): sha(module.__file__)
            for module in (experiment, calendar, calendar_summary, compose, gate)}
    pins[str(Path(__file__).resolve())] = sha(__file__)
    document_ref = write(output / "frozen-source-plans.json", documents)
    selections, inputs = [], [plan_ref, freeze_ref, sources_ref, frozen["frozen_heads"],
        plan["context_manifest"], context_manifest["native_production_manifest"], original_sources_ref]
    for head in heads:
        name = head["name"]
        generation_ref = frozen["files"][name]["challenge"]
        generated = read_ref(generation_ref)
        inputs.extend([generation_ref, head["checkpoint"]])
        require(sha(head["checkpoint"]["path"]) == head["checkpoint"]["sha256"], "selected checkpoint changed")
        verify_generation(generated, head["checkpoint"]["sha256"])
        require(generated["control"] == "source" and len(generated["rows"]) == len(sources), "ordinary complete generation required")
        predictions = {}
        for source, prediction in zip(sources, generated["rows"]):
            require(source["source_sha256"] == prediction["source_sha256"], "frozen prediction source binding differs")
            predictions[source["id"]] = prediction
        accepted, rejected, compositions = [], [], []
        for document in documents:
            identifier = document["plan"]["source"]["candidate_id"]
            try:
                result = compose_document(document, predictions)
                candidate = compose.calendar_candidate(result, expected_plan_sha256=document["plan"]["plan_sha256"])
                sidecar = calendar.synthetic_interpretation(candidate, policy=calendar.POLICY)
                compose.prepare_calendar_composition(result, sidecar, expected_plan_sha256=document["plan"]["plan_sha256"])
                entry = {"candidate": candidate, "interpretation": sidecar}
                require(gate.prepare_qualified_legal([entry], toolchain=args.toolchain).to_dict()["all_candidates_supported"],
                    "composed rules unsupported by declared interpretation")
                accepted.append(entry)
                compositions.append(result)
            except (ValueError, KeyError, TypeError) as error:
                rejected.append({"candidate_id": identifier, "reason": str(error)})
        require(len(accepted) + len(rejected) == len(documents), "document denominator differs")
        selections.append({"name": name, "arm": head["arm"], "seed": head["seed"], "checkpoint": head["checkpoint"],
            "generation": generation_ref, "source_documents": len(documents), "source_rule_occurrences": 3 * len(documents),
            "entries": accepted, "compositions": compositions, "rejected": rejected})
    selection_ref = write(output / "frozen-compositions.json", selections)
    models = []
    for selected in selections:
        folder = output / selected["name"]
        folder.mkdir()
        receipts, built = [], 0
        for start in range(0, len(selected["entries"]), gate.MAX_ROWS):
            entries = selected["entries"][start:start + gate.MAX_ROWS]
            destination = folder / f"lake-{start // gate.MAX_ROWS:03d}"
            receipt = gate.build_qualified_legal(entries, toolchain=args.toolchain, lake_executable=args.lake_executable,
                timeout_seconds=60, output_directory=destination).to_dict()
            reference = experiment.file_ref(destination / "qualified-receipt.json")
            verified = calendar_summary.verify_receipt(reference, entries)
            require(verified == receipt, "independent build receipt replay differs")
            if receipt["build_passed"]:
                built += len(entries)
            receipts.append({"receipt": reference, "candidate_count": len(entries), "build_passed": receipt["build_passed"],
                "backend_executed": receipt["backend_executed"], "command": receipt["command"]})
        models.append({key: selected[key] for key in ("name", "arm", "seed", "source_documents", "source_rule_occurrences")} | {
            "composed_documents": len(selected["entries"]), "built_documents": built,
            "built_rule_occurrences": built * 3, "rejected_documents": len(selected["rejected"]), "builds": receipts})
    require(all(sha(path) == expected for path, expected in pins.items()), "composition/build producer changed")
    require(all(sha(ref["path"]) == ref["sha256"] for ref in inputs), "source/generation/checkpoint bytes changed")
    result = {"schema": "legal-learned-clause-composition-integration/v1", "source_plans": document_ref,
        "frozen_compositions": selection_ref, "inputs": inputs, "producer_pins": pins, "models": models,
        "totals": {key: sum(m[key] for m in models) for key in ("source_documents", "source_rule_occurrences",
            "composed_documents", "built_documents", "built_rule_occurrences", "rejected_documents")},
        "reference_targets_read": False, "models_or_documents_selected_by_semantic_score": False,
        "learned_clause_predictions_used": True, "segmentation_learned": False, "source_semantics_verified": False,
        "qualified": False, "proof_authority": False, "all_logic_families_supported": False,
        "scope": "Declared flat-clause integration on exposed authored inputs; no learned segmentation or independently reviewed document meaning.",
        "compiled_artifact_scope": "Build receipt/source/module coverage verified; temporary olean bytes are removed by the existing backend."}
    write(output / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run-directory", "output", "lake-executable"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--toolchain", default="leanprover/lean4:v4.34.1")
    print(json.dumps(run(parser.parse_args())["totals"]))
