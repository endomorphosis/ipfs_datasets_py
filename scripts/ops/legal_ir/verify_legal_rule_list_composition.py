#!/usr/bin/env python3
"""Demonstrate source-order/multiplicity preservation with a native Lean build.

The fixture is explicitly authored and already declared as independent clauses.
No learned segmentation, statutory interpretation, or legal truth is claimed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as composition
from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as policy
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as independent


def file_ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return file_ref(path)


def authored_fixture():
    def rule(actor, modality, action, obj, *, conditions=(), exceptions=(), temporal=()):
        return {"modality": modality, "actor": actor, "action": action, "object": obj,
            "conditions": list(conditions), "exceptions": list(exceptions), "temporal": list(temporal)}
    clauses = [
        ("Zulu Agency must retain reports if approval holds.", rule("Zulu Agency", "O", "retain", "reports", conditions=["approval holds"])),
        ("Alpha Board may publish notices before 2075-01-01.", rule("Alpha Board", "P", "publish", "notices", temporal=["before 2075-01-01"])),
        ("Zulu Agency must retain reports if approval holds.", rule("Zulu Agency", "O", "retain", "reports", conditions=["approval holds"])),
        ("Beta Office must not disclose records unless consent remains valid.", rule("Beta Office", "F", "disclose", "records", exceptions=["consent remains valid"]))]
    text = "\n".join(clause for clause, _ in clauses)
    source = {"candidate_id": "authored:four-flat-rule-occurrences", "source_text": text, "source_sha256": composition.text_sha256(text)}
    declarations, predictions, cursor = [], [], 0
    for index, (clause, rule) in enumerate(clauses):
        identity = f"authored-clause-{index}"
        declarations.append({"clause_id": identity, "char_start": cursor, "char_end": cursor + len(clause),
            "scope": deepcopy(composition.FLAT_SCOPE)})
        attachments = {}
        for field in composition.SPAN_FIELDS:
            atoms = rule[field] if field in composition.QUALIFIERS else ([rule[field]] if rule[field] else [])
            pointers = []
            for atom in atoms:
                if clause.count(atom) != 1:
                    raise ValueError("fixture author must choose explicit occurrences when atoms repeat")
                start = cursor + clause.index(atom)
                pointers.append({"char_start": start, "char_end": start + len(atom)})
            attachments[field] = pointers
        predictions.append({"clause_id": identity, "clause_source_sha256": composition.text_sha256(clause),
            "rule": rule, "attachments": attachments, "scope": deepcopy(composition.FLAT_SCOPE)})
        cursor += len(clause) + 1
    return source, declarations, predictions


def run(output, *, toolchain, lake_executable):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source, clauses, predictions = authored_fixture()
    inputs_ref = write(output / "authored-inputs.json", {"source": source, "clause_declarations": clauses,
        "clause_predictions": predictions, "origin": "explicitly_authored_fixture", "learned_generation_executed": False})
    source_plan = composition.prepare_source_plan(source, clauses)
    plan_ref = write(output / "source-plan.json", source_plan)
    result = composition.compose_rule_list(source_plan, predictions, expected_plan_sha256=source_plan["plan_sha256"])
    result_ref = write(output / "composition.json", result)
    recovered = composition.reconstruct_source_rule_list(result, expected_plan_sha256=source_plan["plan_sha256"])
    if recovered != [row["rule"] for row in predictions] or result["canonical_to_source_ordinal"] != [3, 0, 2, 1]:
        raise ValueError("source occurrence order or multiplicity did not round-trip")
    candidate = composition.calendar_candidate(result, expected_plan_sha256=source_plan["plan_sha256"])
    interpretation = policy.synthetic_interpretation(candidate, policy=policy.POLICY)
    if interpretation != independent.expected_interpretation(candidate):
        raise ValueError("independent explicit interpretation replay differs")
    lowered = composition.prepare_calendar_composition(result, interpretation, expected_plan_sha256=source_plan["plan_sha256"])
    lowering_ref = write(output / "calendar-composition.json", lowered)
    if len(lowered["lowering"]["native_projection"]["payload"]["formulas"]) != 4:
        raise ValueError("native projection dropped rule occurrences")
    entries = [{"candidate": candidate, "interpretation": interpretation}]
    receipt = gate.build_qualified_legal(entries, toolchain=toolchain, lake_executable=lake_executable,
        timeout_seconds=60, output_directory=output / "lake").to_dict()
    receipt_ref = file_ref(output / "lake/qualified-receipt.json")
    verified = independent.verify_receipt({"path": receipt_ref["path"], "sha256": receipt_ref["sha256"]}, entries)
    if verified != receipt or receipt["build_passed"] is not True:
        raise ValueError("native multi-rule legal build failed or independent receipt replay differed")
    code = (output / "lake/LegalCalendar/Candidate0000.lean").read_text()
    if code.count("def qualifiedLegalFormula_") != 4:
        raise ValueError("compiled source lost a rule declaration")
    test_path = ROOT / "tests/unit/logic/autoformal/test_legal_rule_list_composition.py"
    report = {"schema": "legal-source-rule-list-composition-demonstration/v1", "status": "built_authored_flat_rule_list",
        "inputs": inputs_ref, "source_plan": plan_ref, "composition": result_ref, "calendar_lowering": lowering_ref,
        "lake_receipt": receipt_ref, "command": receipt["command"], "toolchain": toolchain,
        "rule_occurrence_count": 4, "distinct_rule_payload_count": 3,
        "canonical_to_source_ordinal": result["canonical_to_source_ordinal"],
        "source_order_roundtrip_verified": True, "duplicate_occurrences_preserved": True,
        "all_non_whitespace_source_characters_accounted_for": True, "native_formula_count": 4,
        "compiled_rule_declaration_count": 4, "actual_lake_build_executed": receipt["backend_executed"],
        "build_passed": receipt["build_passed"], "manifest_coverage_passed": receipt["manifest_coverage_passed"],
        "independent_build_receipt_replayed": True, "compiled_artifact_bytes_reverified": False,
        "compiled_artifact_evidence": "Native runner recorded complete olean module hashes; its temporary compiled bytes were cleaned up.",
        "implementation": [file_ref(__file__), file_ref(composition.__file__), file_ref(test_path)],
        "interpretation_policy": deepcopy(policy.POLICY_DESCRIPTION),
        "scope": "Authored independent flat clauses with explicit copied-atom pointers. Canonical IR sorts rule order; occurrence ledger reverses that sorting without merging duplicates. This is output composition, not learned segmentation or a proof of clause independence, complete legal norm extraction, or statutory truth.",
        "nested_scope_supported": False, "cross_clause_shared_scope_supported": False,
        "qualifier_normalization_performed": False, "learned_generation_executed": False,
        **composition.FALSE}
    ref = write(output / "summary.json", report)
    print(json.dumps({"summary": ref, "rule_occurrences": 4, "distinct_payloads": 3, "build_passed": True}, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--lake-executable", required=True)
    args = parser.parse_args()
    run(args.output_directory, toolchain=args.toolchain, lake_executable=args.lake_executable)


if __name__ == "__main__":
    main()
