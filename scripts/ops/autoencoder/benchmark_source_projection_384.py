#!/usr/bin/env python3
"""Diagnose native projections of frozen learned source-decoder outputs.

This post-evaluation diagnostic never trains or selects model parameters. It
replays target-free inference, then checks only the views supported by the
decoded fragments. Native validation and Lean syntax checks grant no authority.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")
AUTHORITY = dict(proof_authority=False, source_semantics_verified=False,
                 execution_authority=False, claim_proved=False)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def require(value, reason):
    if not value:
        raise ValueError(reason)


def guard_freeze(directory):
    frozen = read(directory / "freeze.json")
    for name, expected in frozen.items():
        require(sha(directory / name) == expected, "frozen artifact differs: " + name)
    return sha(directory / "freeze.json")


def intent_projection(candidate, source):
    from ipfs_datasets_py.logic.intent_ir.formalize import rich_logic
    require(candidate.get("kind") == "intent_rich_ast", "Intent rich AST fragment required")
    report = rich_logic.project_rich_intent_logic(candidate["document"], instruction=source)
    for projection in report["projections"]:
        if projection["family_id"] in ("dcec", "tdfol") and projection["status"] == "projected":
            payload = projection["representation"]
            require(all(payload[key] is True for key in (
                "native_parse_passed", "native_structure_checked", "native_reparse_passed")),
                "native modal parse/reparse did not pass")
    return dict(status="projected_candidate", scope="parameterized_modal_formula_not_source_fidelity",
                projection=report, **AUTHORITY)


def ui_projection(candidate):
    from ipfs_datasets_py.logic.ui_ux_ir.schema import UIComponent
    from ipfs_datasets_py.logic.ui_ux_ir.model.components import SemanticComponent, UIComponentGraph
    from ipfs_datasets_py.logic.ui_ux_ir.formalize.flogic import compile_component_graph_to_flogic
    require(candidate.get("kind") == "ui_component", "UI component fragment required")
    fields = deepcopy(candidate["document"])
    for key, value in tuple(fields.items()):
        if key.endswith("_ids"):
            fields[key] = tuple(value)
    component = UIComponent(**fields)
    component.validate()
    graph = UIComponentGraph((SemanticComponent.from_envelope(component),))
    compiled = compile_component_graph_to_flogic(graph)
    facts = [dict(predicate=fact.predicate, args=list(fact.args), source_ref_ids=list(fact.source_ref_ids))
             for fact in compiled.facts]
    require(any(fact["predicate"] == "ui_component" and
                fact["args"] == [component.component_id, component.role] for fact in facts),
            "predicted component ID or role lost during projection")
    return dict(status="projected_candidate", family_id="frame_logic", compiler=compiled.compiler,
        scope="component_identity_role_and_relationship_facts", facts=facts,
        unsupported=list(compiled.unsupported),
        omitted_candidate_facets=[name for name in candidate["document"] if name not in
            {"component_id", "role", "parent_id", "child_ids", "source_ref_ids"}],
        defaults_in_graph_are_not_learned=True, **AUTHORITY)


def legal_projection(candidate):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import LegalIRGrammarDecoder
    rule = legal_formula_codec._rule(candidate)
    grammar_input = {"rules": [{**rule, "modality": legal_formula_codec._MODALITIES[rule["modality"]],
                               "subject": rule["actor"]}]}
    validation = LegalIRGrammarDecoder().validate(grammar_input, family="deontic")
    require(validation.accepted, "canonical Legal rule failed native deontic grammar")
    return dict(status="native_grammar_validated", family_id="deontic",
        scope="single_canonical_rule_structural_grammar_not_backend_proof",
        grammar_input=grammar_input, validation=validation.to_dict(), **AUTHORITY)


def security_projection(candidate):
    from ipfs_datasets_py.logic.formalization.autoencoder.source_training_v2 import validate_target
    require(candidate.get("kind") == "program_expression", "ProgramExpression fragment required")
    validation = validate_target("security_ir", candidate)
    require(validation["valid"], "native Security fragment validation failed")
    return dict(status="fragment_validated_missing_program_context", family_id=None,
        scope="local_ProgramExpression_fields_only", native_validation=validation,
        missing_context=["enclosing_ProgramIR", "operand_and_symbol_bindings", "function_and_CFG_context",
                         "source_bound_whole_program_model"],
        full_family_projection_executed=False, invented_context=False, **AUTHORITY)


def run(source_dir, candidate_dir, output, lake_executable=None):
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as runtime
    require(not output.exists(), "fresh diagnostic output required")
    source_freeze, candidate_freeze = guard_freeze(source_dir), guard_freeze(candidate_dir)
    plan = read(candidate_dir / "plan.json")
    require(Path(plan["baseline_directory"]).resolve() == source_dir.resolve(), "baseline directory differs")
    require(plan["baseline_freeze_sha256"] == source_freeze, "baseline freeze binding differs")
    report = read(candidate_dir / "report.json")
    require(report["structured_freeze_sha256"] == candidate_freeze, "evaluation freeze binding differs")
    artifacts = {row["domain"]: row["artifact"] for row in report["comparisons"] if row["arm"] == "structured"}
    fits = {row["domain"]: row for row in read(candidate_dir / "fits.json")}
    results, lake_representatives, evidence = {}, {}, {}
    started = time.perf_counter()
    for domain in DOMAINS:
        source_path = source_dir / domain / "test.json"
        evaluation_path = candidate_dir / domain / "evaluation.json"
        require(sha(evaluation_path) == artifacts[domain]["sha256"], "evaluation artifact digest differs")
        checkpoint_path = Path(fits[domain]["checkpoint"]["path"])
        checkpoint = runtime.load_checkpoint(checkpoint_path,
            expected_sha256=fits[domain]["checkpoint"]["sha256"], expected_domain=domain)
        rows = read(source_path)["rows"]
        recorded = read(evaluation_path)["results"]["test"]["rows"]
        require(len(rows) == len(recorded), "evaluation row count differs")
        predicted = checkpoint.infer([{key: row[key] for key in ("id", "source_text", "embedding")} for row in rows])["rows"]
        output_rows = []
        for source, original, replay in zip(rows, recorded, predicted):
            for key in ("id", "source_sha256", "head_sha256", "projection_sha256", "candidate_ir"):
                require(raw(original[key]) == raw(replay[key]), "target-free inference replay differs: " + key)
            require(source["id"] == replay["id"] and hashlib.sha256(source["source_text"].encode()).hexdigest() == replay["source_sha256"],
                    "source binding differs")
            exact = replay["candidate_ir"] is not None and raw(replay["candidate_ir"]) == raw(source["target"])
            require(original["exact_target"] is exact, "recorded exactness differs")
            row = dict(id=source["id"], source_sha256=replay["source_sha256"], exact_target=exact,
                target_free_replay_passed=True, candidate_ir=replay["candidate_ir"], **AUTHORITY)
            if not exact:
                row.update(status="skipped_inexact_decode", reason="Projection requires an exact authored reference match in this diagnostic.")
            else:
                try:
                    candidate = replay["candidate_ir"]
                    if domain == "intent_ir":
                        row.update(intent_projection(candidate, source["source_text"]))
                        modality = candidate["document"].get("modality")
                        lake_representatives.setdefault(modality, (row, source["source_text"]))
                    elif domain == "ui_ux_ir":
                        row.update(ui_projection(candidate))
                    elif domain == "legal_ir":
                        row.update(legal_projection(candidate))
                    else:
                        row.update(security_projection(candidate))
                except (ValueError, TypeError, KeyError, IndexError) as exc:
                    row.update(status="projection_failed", reason=str(exc)[:1024])
            output_rows.append(row)
        results[domain] = dict(total_decoded_rows=len(rows), exact_reference_matches=sum(row["exact_target"] for row in output_rows),
            status_counts=dict(Counter(row["status"] for row in output_rows)), rows=output_rows)
        evidence[domain] = dict(source_inputs_sha256=sha(source_path), decoded_evaluation_sha256=sha(evaluation_path),
                               checkpoint_sha256=sha(checkpoint_path))
        print(json.dumps({"domain": domain, "status_counts": results[domain]["status_counts"]}), flush=True)
    lake_rows = []
    from ipfs_datasets_py.logic.intent_ir.formalize import rich_logic
    for modality in ("required", "permitted", "prohibited"):
        if modality not in lake_representatives:
            lake_rows.append(dict(modality=modality, status="unavailable_exact_learned_representative", **AUTHORITY))
            continue
        row, source = lake_representatives[modality]
        if lake_executable is None:
            result = dict(status="lake_unavailable", backend_executed=False, syntax_verified=False, **AUTHORITY)
        else:
            result = rich_logic.validate_rich_intent_logic(row["projection"], instruction=source,
                ast=row["candidate_ir"]["document"], lake_executable=str(lake_executable), timeout_seconds=45)
        lake_rows.append(dict(modality=modality, decoded_row_id=row["id"], result=result))
        print(json.dumps({"lake_modality": modality, "status": result.get("status"),
                          "syntax_verified": result.get("syntax_verified")}), flush=True)
    require(guard_freeze(source_dir) == source_freeze and guard_freeze(candidate_dir) == candidate_freeze,
            "frozen experiment changed during diagnostic")
    value = dict(schema="learned-source-native-projection-diagnostic/v1", partition="test",
        source_freeze_sha256=source_freeze, candidate_freeze_sha256=candidate_freeze,
        diagnostic_driver_sha256=sha(__file__), evidence=evidence, results=results, lake=lake_rows,
        elapsed_seconds=time.perf_counter()-started, trained_or_selected_models=False,
        prior_complete_native_family_counts_are_separate=True,
        projection_scope="only supported views of exact learned local fragments; missing world/program context remains explicit",
        lake_scope="three modality representatives; parameterized syntax/typechecking, not all rows or semantic correctness",
        **AUTHORITY)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw(value))
    print(json.dumps({"output": str(output), "sha256": sha(output)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--candidate-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lake-executable", type=Path, default=shutil.which("lake"))
    args = parser.parse_args()
    run(args.source_directory.resolve(), args.candidate_directory.resolve(), args.output.resolve(), args.lake_executable)
