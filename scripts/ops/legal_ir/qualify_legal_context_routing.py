#!/usr/bin/env python3
"""Independent context-routing accounting over immutable decoder observations.

Every source/model slot is retained. Authored controls measure valid candidate
retention as well as deferred-type rejection. Neither compilation nor routing
is a statutory-fidelity oracle, and this script does not train or decode text.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
SCHEMA = "legal-context-routing-independent-qualification/v1"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def read(ref):
    check_ref(ref)
    return json.loads(Path(ref["path"]).read_text())


def check_ref(ref):
    actual = reference(ref["path"])
    require(actual == {key: ref[key] for key in actual}, "artifact bytes changed: " + str(ref["path"]))
    return actual


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return reference(path)


def source_rows(value):
    require(type(value) is list and value, "nonempty source inventory required")
    seen = set()
    for source in value:
        require(type(source) is dict and type(source.get("id")) is str and source["id"] not in seen,
                "unique source identities required")
        seen.add(source["id"])
        require(type(source.get("source_text")) is str and
            hashlib.sha256(source["source_text"].encode()).hexdigest() == source.get("source_sha256"),
            "exact source text hash required")
    return value


def prediction_rows(generation, sources):
    """Independently check all source-only rows and producer-report coverage."""
    require(type(generation) is dict and generation.get("target_access") is False,
            "target-free generation required")
    rows, reports = generation.get("rows"), generation.get("reports")
    require(type(rows) is list and len(rows) == len(sources), "complete source denominator required")
    require(type(reports) is list and rows == [row for report in reports for row in report.get("rows", [])],
            "flattened saved reports differ from generation rows")
    for source, row in zip(sources, rows):
        require(row.get("source_sha256") == source["source_sha256"], "prediction/source join differs")
        require(all(row.get(k) is False for k in ("target_access", "teacher_forcing", "latent_input_enabled"))
                and row.get("source_input_conditioned") is True, "source-only inference contract differs")
        require(row.get("status") in {"decoded", "abstained"}, "unknown decoder status")
        require((row.get("canonical_ir") is not None) == (row["status"] == "decoded"),
                "candidate/status disagreement")
        require(row.get("admitted") is False and row.get("semantic_correctness_verified") is False,
                "unexpected decoder authority claim")
    return rows


def route_index(sources, decisions):
    require(type(decisions) is list and len(decisions) == len(sources), "complete route denominator required")
    by_id = {}
    for source, decision in zip(sources, decisions):
        require(type(decision) is dict and decision.get("source_id") == source["id"], "route source identity differs")
        require(decision.get("source_sha256") == source["source_sha256"], "route source hash differs")
        require(type(decision.get("decoder_eligible")) is bool and type(decision.get("route")) is str,
                "explicit route category and boolean eligibility required")
        require(decision["decoder_eligible"] == (decision["route"] == "possible_norm"),
                "route/eligibility contract differs")
        require(source["id"] not in by_id, "duplicate route identity")
        by_id[source["id"]] = decision
    return by_id


def compare_routing(sources, rows, decisions):
    """Routing may suppress a candidate, but never silently change or create it."""
    indexed = route_index(sources, decisions)
    require(len(rows) == len(sources), "full prediction denominator required")
    output, counts = [], Counter()
    for source, prediction in zip(sources, rows):
        require(prediction.get("source_sha256") == source["source_sha256"], "prediction/source join differs")
        decision = indexed[source["id"]]
        before = prediction["status"]
        require(before in {"decoded", "abstained"}, "unknown decoder status")
        after = "retained_candidate" if before == "decoded" and decision["decoder_eligible"] else (
            "route_deferred_candidate" if before == "decoded" else "decoder_abstained")
        counts["slots"] += 1
        counts["before_" + before] += 1
        counts[after] += 1
        counts["eligible_source_slots" if decision["decoder_eligible"] else "deferred_source_slots"] += 1
        output.append({"source_id": source["id"], "source_sha256": source["source_sha256"],
            "before_status": before, "after_status": after, "route": decision["route"],
            "decoder_eligible": decision["decoder_eligible"], "route_reasons": decision.get("reasons", []),
            "unchanged_candidate": prediction.get("canonical_ir"),
            "candidate_sha256": digest(prediction.get("canonical_ir")),
            "prediction_sha256": digest(prediction), "route_decision_sha256": digest(decision),
            "source_semantics_verified": False})
    for name in ("slots", "before_decoded", "before_abstained", "retained_candidate",
                 "route_deferred_candidate", "decoder_abstained", "eligible_source_slots", "deferred_source_slots"):
        counts.setdefault(name, 0)
    require(counts["slots"] == counts["retained_candidate"] + counts["route_deferred_candidate"] + counts["decoder_abstained"],
            "routing terminal denominators differ")
    return {"counts": dict(counts), "rows": output, "statutory_accuracy": None,
            "candidate_suppression_is_accuracy_improvement": False}


def score_controls(sources, decisions, labels):
    """Report both sides of the authored routing contract, including all-reject."""
    indexed = route_index(sources, decisions)
    require(type(labels) is list and len(labels) == len(sources), "complete independent control labels required")
    counts, rows = Counter(), []
    for source, label in zip(sources, labels):
        require(label.get("source_id") == source["id"] and type(label.get("expected_eligible")) is bool,
                "control label identity or expectation differs")
        require(label.get("origin") == "independently_authored_routing_contract", "authored control provenance required")
        expected, actual = label["expected_eligible"], indexed[source["id"]]["decoder_eligible"]
        category = ("valid_norm_retained" if actual else "valid_norm_false_rejection") if expected else (
            "deferred_type_false_acceptance" if actual else "deferred_type_correctly_deferred")
        counts[category] += 1
        counts["valid_norm_controls" if expected else "deferred_type_controls"] += 1
        rows.append({"source_id": source["id"], "expected_eligible": expected, "actual_eligible": actual,
            "category": category, "control_family": label["control_family"], "route": indexed[source["id"]]["route"]})
    for name in ("valid_norm_retained", "valid_norm_false_rejection", "deferred_type_false_acceptance",
                 "deferred_type_correctly_deferred", "valid_norm_controls", "deferred_type_controls"):
        counts.setdefault(name, 0)
    require(counts["valid_norm_controls"] > 0 and counts["deferred_type_controls"] > 0,
            "controls must include valid norms and deferred types")
    return {"counts": dict(counts), "rows": rows,
        "valid_norm_retention_rate": counts["valid_norm_retained"] / counts["valid_norm_controls"],
        "valid_norm_false_rejection_rate": counts["valid_norm_false_rejection"] / counts["valid_norm_controls"],
        "deferred_type_false_acceptance_rate": counts["deferred_type_false_acceptance"] / counts["deferred_type_controls"],
        "all_reject_baseline": {"valid_norm_retained": 0, "valid_norm_false_rejection": counts["valid_norm_controls"],
            "deferred_type_correctly_deferred": counts["deferred_type_controls"], "deferred_type_false_acceptance": 0},
        "all_reject_is_success": False,
        "declared_control_contract_passed": counts["valid_norm_false_rejection"] == 0 and counts["deferred_type_false_acceptance"] == 0,
        "statutory_accuracy": None}


def _control_specs():
    rows = []
    for cue in ("shall", "may", "shall not"):
        for family, text in (
            ("plain", f"The registrar {cue} archive the notice."),
            ("condition", f"If registration is complete, the registrar {cue} archive the notice."),
            ("exception", f"The registrar {cue} archive the notice unless an exemption is granted."),
            ("calendar", f"The registrar {cue} archive the notice before January 1, 2032."),
            ("practicability", f"To the extent practicable, the registrar {cue} archive the notice."),
        ):
            rows.append((family, text, True, "codified_body"))
    for text in ("The definition officer shall archive the notice.",
                 "The applicability analyst may archive the notice.",
                 "The interpretation clerk shall not disclose the notice."):
        rows.append(("actor_keyword_trap", text, True, "codified_body"))
    for family, text in (
        ("definition", 'The term "registrar" means the officer responsible for maintaining the register.'),
        ("definition", 'The term "notice" means a written message delivered to the registrar.'),
        ("definition", 'The term "public register" means the record described in the application.'),
        ("constitutive", 'Receipt of the completed form shall be deemed to be registration.'),
        ("constitutive", 'An electronic record shall be deemed to be an original document.'),
        ("constitutive", 'A notice delivered by courier shall be deemed to have been received on delivery.'),
        ("unresolved_reference", 'Except as provided in subsection (c), the registrar shall archive the notice.'),
        ("unresolved_reference", 'The registrar shall comply with section 702 of title 41.'),
        ("incomplete_list", '(a) The registrar may approve an application if—'),
    ):
        rows.append((family, text, False, "codified_body"))
    for text in ('Prior section 9001 was renumbered section 9002.',
                 'The former provision used the words "shall archive" before amendment.',
                 'Based on the earlier version of this provision, as amended in 1998.'):
        rows.append(("notes", text, False, "notes"))
    require(len(rows) == 30, "control inventory changed")
    return rows


def prepare_controls(output):
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
    from scripts.ops.legal_ir import evaluate_legal_uscode_fidelity as evaluation
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources, labels, documents = [], [], []
    for index, (family, text, eligible, kind) in enumerate(_control_specs()):
        section = str(9000 + index)
        # The URL is a parser-contract fixture only, never a fetched authority.
        url = f"https://www.govinfo.gov/content/pkg/USCODE-2024-title99/html/USCODE-2024-title99-chap1-sec{section}.htm"
        body = (f'<p class="statutory-body">{escape(text)}</p>' if kind == "codified_body" else
                '<p class="statutory-body">The registrar shall archive the notice.</p>'
                '<h4>Historical Notes</h4><p>' + escape(text) + '</p>')
        html = ('<html><meta charset="utf-8"><h3 class="section-head">§' + section +
                '. Authored routing fixture</h3>' + body + '</html>').encode()
        raw_path = output / f"control-{index:03d}.html"
        raw_path.write_bytes(html)
        document = context.extract_document(html, url=url, edition=2024, legal_id="usc:us:99:" + section)
        doc_ref = write(output / f"control-{index:03d}.json", document)
        views = evaluation.make_sources(document, doc_ref)
        source = next(row for row in views if row["kind"] == ("paragraph" if kind == "codified_body" else "notes_control"))
        sources.append(source)
        labels.append({"source_id": source["id"], "expected_eligible": eligible,
            "control_family": family, "origin": "independently_authored_routing_contract"})
        documents.append({"document": doc_ref, "raw_html": reference(raw_path), "origin": "authored_synthetic_fixture",
            "official_url_literal_is_parser_contract_only": True, "retrieved_from_government": False})
    source_ref = write(output / "sources.json", sources)
    target_ref = write(output / "expected-routing.json", labels)
    return write(output / "manifest.json", {"schema": "legal-context-routing-independent-controls/v1",
        "sources": source_ref, "targets": target_ref, "documents": documents,
        "counts": {"sources": len(sources), "valid_norms": 18, "deferred_types": 12},
        "origin": "authored_synthetic_fixture_not_US_Code", "reference_scope": "routing contract only",
        "statutory_gold": False, "references_created_before_routing": True,
        "implementation": reference(__file__)})


def route_inventory(manifest, sources):
    """Read only source artifacts, never the control expectation reference."""
    from ipfs_datasets_py.logic.autoformal import legal_statutory_routing as routing
    documents = {}
    for item in manifest["documents"]:
        document = read(item["document"])
        check_ref(item["raw_html"])
        raw = Path(item["raw_html"]["path"]).read_bytes()
        require(document["document_id"] not in documents, "duplicate document identity")
        documents[document["document_id"]] = (item["document"], document, raw)
    decisions = []
    for source in source_rows(sources):
        require(source["document_id"] in documents, "source document missing")
        pin, document, raw = documents[source["document_id"]]
        require(source["document"] == pin, "source document provenance differs")
        decision = routing.route_source(source, document, raw)
        require(all(decision.get(key) is False for key in ("context_resolved", "semantic_rejection",
                "source_semantics_verified", "independently_reviewed", "training_qualified")),
                "routing must not claim semantic authority")
        require(decision.get("reference_accuracy") is None, "routing cannot supply reference accuracy")
        decisions.append(decision)
    route_index(sources, decisions)
    return decisions


def qualify_prior(prior_summary, controls_manifest, output):
    """Compare frozen predictions; independent routing is the only computation."""
    from ipfs_datasets_py.logic.autoformal import legal_statutory_routing as routing
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    prior_ref, controls_ref = reference(prior_summary), reference(controls_manifest)
    prior, controls = read(prior_ref), read(controls_ref)
    require(prior.get("source_views") == 86 and prior.get("model_source_slots") == 1548,
            "expected frozen 18-model by 86-view study")
    require(prior.get("reference_accuracy_available") is False and prior.get("independent_gold_count") == 0,
            "real-source study must not assert gold")
    require(prior.get("fitting_performed") is False and prior.get("training_qualified") is False
            and prior.get("source_semantics_verified") is False, "prior source-only authority flags differ")
    plan = read(prior["plan"])
    require(plan.get("inference_fields") == ["source_text"] and plan.get("fitting_performed") is False
            and plan.get("selection_performed") is False, "prior source-only plan differs")
    manifest = read(plan["manifest"])
    sources = source_rows(read(manifest["sources"]))
    require(len(sources) == 86 and manifest.get("views_are_independent_examples") is False,
            "exposed correlated-view inventory differs")
    require(len(prior["models"]) == 18 and [model["name"] for model in prior["models"]] == plan["model_names"]
            and len(set(plan["model_names"])) == 18, "complete unique model inventory required")
    check_ref(plan["checkpoint_index"])
    for producer in plan["implementation"] + manifest["implementation"]:
        check_ref(producer)
    require(controls.get("schema") == "legal-context-routing-independent-controls/v1"
            and controls.get("references_created_before_routing") is True and controls.get("statutory_gold") is False,
            "independent authored control protocol differs")
    check_ref(controls["implementation"])
    control_sources = source_rows(read(controls["sources"]))
    require(controls["counts"] == {"sources": 30, "valid_norms": 18, "deferred_types": 12}
            and len(control_sources) == 30, "complete 30-control denominator required")
    require(not ({s["source_sha256"] for s in sources} & {s["source_sha256"] for s in control_sources}),
            "authored controls must be separate from real diagnostic views")
    frozen_plan = write(output / "qualification-plan.json", {
        "schema": SCHEMA + "/plan", "prior_summary": prior_ref, "controls_manifest": controls_ref,
        "producers": [reference(__file__), reference(routing.__file__)],
        "control_expectations_opened": False, "model_inference_calls": 0, "training_updates": 0,
        "native_compiler_calls": 0, "real_source_labels_available": False,
        "comparison_rule": "retain an unchanged candidate only when the source-only route permits decoding",
        "control_references_used_to_change_router": False})
    routed = route_inventory(manifest, sources)
    control_routed = route_inventory(controls, control_sources)
    route_ref = write(output / "real-source-routes.json", routed)
    control_route_ref = write(output / "authored-control-routes.json", control_routed)
    models, aggregate, by_arm = [], Counter(), {}
    for model in prior["models"]:
        check_ref(model["checkpoint"])
        check_ref(model["diagnostics"])
        require(model.get("exact_replay") is True and model.get("reference_accuracy") is None,
                "prior inference replay/authority contract differs")
        rows = prediction_rows(read(model["generation"]), sources)
        compared = compare_routing(sources, rows, routed)
        require(compared["counts"]["before_decoded"] == model["decoded"]
                and compared["counts"]["before_abstained"] == model["abstained"],
                "prior candidate counts differ from actual rows")
        details = write(output / (model["name"] + "-comparison.json"), compared)
        models.append({"name": model["name"], "checkpoint": model["checkpoint"],
            "prior_generation": model["generation"], "counts": compared["counts"], "details": details})
        aggregate.update(compared["counts"])
        arm = model["name"].rsplit("-", 1)[0]
        by_arm.setdefault(arm, Counter()).update(compared["counts"])
    require(aggregate["slots"] == 1548, "full model-source denominator differs")
    decisions_freeze = write(output / "routing-decisions-frozen.json", {
        "schema": SCHEMA + "/decisions-frozen", "plan": frozen_plan,
        "real_routes": route_ref, "control_routes": control_route_ref,
        "model_comparisons": [model["details"] for model in models],
        "control_expectations_opened": False, "all_decisions_and_comparisons_complete": True,
        "real_gold_available": False, "model_inference_calls": 0, "training_updates": 0})
    for producer in read(frozen_plan)["producers"]:
        check_ref(producer)
    # This is the first read of the independent control expectation file.
    labels = read(controls["targets"])
    control_score = score_controls(control_sources, control_routed, labels)
    control_score_ref = write(output / "authored-control-score.json", control_score)
    route_counts = Counter(row["route"] for row in routed)
    summary = {"schema": SCHEMA, "plan": frozen_plan, "decisions_freeze": decisions_freeze,
        "real_routes": route_ref, "control_routes": control_route_ref, "controls": control_score_ref,
        "models": models, "counts": dict(aggregate), "by_arm": {k: dict(v) for k, v in by_arm.items()},
        "source_views": len(sources), "unique_source_texts": len({s["source_sha256"] for s in sources}),
        "route_counts": dict(route_counts), "eligible_source_views": sum(r["decoder_eligible"] for r in routed),
        "all_original_candidates_preserved_in_details": True,
        "control_expectations_opened_after_decisions_freeze": True,
        "control_references_used_to_change_router": False, "model_inference_calls": 0, "training_updates": 0,
        "native_compiler_calls": 0, "statutory_accuracy": None, "source_semantics_verified": False,
        "candidate_suppression_is_accuracy_improvement": False, "independent_statutory_gold_count": 0,
        "limitations": ["The 86 views are exposed, correlated diagnostic observations from five sections.",
            "Authored controls test declared routing behavior, not statutory interpretation accuracy.",
            "Possible norm is a structural candidate; retained outputs remain unverified.",
            "Context bundles retain evidence but do not change the old decoder's source-only input.",
            "No training, new model inference, compiler build, or legal adjudication occurs here."]}
    return write(output / "summary.json", summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-controls")
    prepare.add_argument("--output", required=True)
    qualify = sub.add_parser("qualify-prior")
    qualify.add_argument("--prior-summary", required=True)
    qualify.add_argument("--controls-manifest", required=True)
    qualify.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "prepare-controls":
        print(json.dumps(prepare_controls(args.output)))
    elif args.command == "qualify-prior":
        print(json.dumps(qualify_prior(args.prior_summary, args.controls_manifest, args.output)))


if __name__ == "__main__":
    main()
