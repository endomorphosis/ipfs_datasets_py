"""Bind explicit unreviewed definition declarations to retained source subjects.

Run only through the active repository's admitted owned-validation resource path.
The existing empty owned export directory is the sole write destination. This
driver performs no network, model, training, native Lean build or publication.
The chosen head, opaque body and title scope are caller declarations; exact
source custody does not settle their legal meaning, completeness or application.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
ACTIVE = ROOT / "ipfs_datasets_py"
PRIOR = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/legal-ir-sampled-source-review-20261015-01/actual-source-review-01/exports")
HISTORICAL_DRIVER_SHA256 = "3c7facd701f90231cb63f637f2cc01a9ba08c720bae16609d1bd43637e73d9b5"
RAW_SHA = "4e8d017794220f192668d5313fc537fbb7140652ac4a00faaf93a6c921c2c08b"
DESC_SHA = "00cdd9452ada9005ad30fa4e548a98a73914324cb99ec3d10c2911a878f86bfe"
DESC_CANONICAL_SHA = "431a4da4edc59bed35841256a9e13a56c52715b227e5d0a036b55ae255df07c8"
ACQUISITION_SHA = "7d9852fd175ae48dc057f2b879ed176e7b26a394e92e6ae13f4824df894228bf"
SAMPLING_SHA = "be524c7822f5e19a16ee56740560b19b0311001c553bd7ca9c2c9ed989af98b1"
BUNDLE_FILE_SHA = "2c2bb4ce302568feb014cc6abb28501bd3b453600d696a19588bbb14b55d2846"
BUNDLE_CANONICAL_SHA = "62bbead449c5e1d10cbdb23957f3a6325ad6cb830b86106086fd1ccd66134b33"
PRIOR_RECEIPT_SHA = "10e6cf392bfe00fa175de5d3dc931a20a63517594ea3eed89d40a5a5c185ec93"
SYNTHETIC_RESPONSE_FILE_SHA = "1dec69d5b92f46d03feb1b692cd95826111edaf04d3353566f0be99804a3cc7a"
MAX_OUTPUT_BYTES = 30_000_000
SOURCE_VERSION_REF = {
    "record_cid": "baguqeerave77xhahqkwfznpcifxg2axl3uesrac7yiuaginwxxvqj7aghmza",
    "schema": "legal-corpus-source-version/v1",
    "sha256": "7894137f375a07b3c263964e9524ac6e6a6acc7111694f5d7c9c8c2f9b5b2af4",
}
DEFINITION_UNIT_REF = {
    "record_cid": "baguqeeran22n7il4qlsb7jktsskotwbs75eat7ebdubjwex6rrtvexedefga",
    "schema": "legal-source-structured-sample-unit/v1",
    "sha256": "26391def5297187ea881ce3602609ce10a39d7bbca1f13d4857c984673b9ac0b",
}
SCOPE_UNIT_REF = {
    "record_cid": "baguqeerahdfpg6hzil7fbc45vksgjzsqdq7uh4dmch4bwt3oo3cybch7btpa",
    "schema": "legal-source-structured-sample-unit/v1",
    "sha256": "8cf40c47c26e77e5721b7bd124740b21c0a81f10239963b7ba5c195de04e7706",
}
VIEW_ID = "legal-official-markup-view:sha256:6a4190668d49d48b72067e555ff274380e76d58a3501088f43137f41dabe7973"


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return sha(wire(value))


def load(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "duplicate input JSON key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite input JSON")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=nonfinite)


def pinned(path, length, expected):
    need(path.is_absolute() and path.resolve() == path, "real absolute input path required")
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and before.st_size == length, "unaliased input length/type differs")
        raw = stream.read(length + 1)
        after = os.fstat(stream.fileno())
    need(identity(before) == identity(after) == identity(path.lstat())
         and len(raw) == length and sha(raw) == expected,
         "independent input pin or file identity differs")
    return raw


def no_authority(value):
    if type(value) is dict:
        if "authority" in value:
            need(type(value["authority"]) is dict and bool(value["authority"])
                 and all(flag is False for flag in value["authority"].values()),
                 "an authority flag changed")
        for field in ("training_mask", "evaluation_gold_mask"):
            if field in value:
                need(type(value[field]) is int and value[field] == 0,
                     "a training or evaluation gold mask changed")
        for child in value.values():
            no_authority(child)
    elif type(value) is list:
        for child in value:
            no_authority(child)


def reference(record):
    return {"record_cid": record["record_cid"], "schema": record["schema"],
            "sha256": digest(record)}


def declared_request(family):
    """Select fixed literals explicitly; this is not extraction or a review."""
    return {
        "schema": "legal-source-definition-request/v2",
        "profile": "declared-scope-v2-source-unary-predicate-definition/v1",
        "family": family,
        "declaration": {
            "declaration_id": "unreviewed-navigation-2024-title10-section101-block54-enlisted-member",
            "interpretation_status": "unreviewed_caller_declaration",
            "source_version_ref": deepcopy(SOURCE_VERSION_REF),
            "normalized_view_id": VIEW_ID,
            "contributor_unit_refs": [deepcopy(DEFINITION_UNIT_REF)],
            "scope_unit_ref": deepcopy(SCOPE_UNIT_REF),
            "scope_span": {"char_start": 6513, "char_end": 6527,
                           "text": "in this title:"},
            "head": {"char_start": 7165, "char_end": 7180,
                     "text": "enlisted member"},
            "definition_cue": {"char_start": 7182, "char_end": 7187,
                               "text": "means"},
            "body": {"op": "atom", "span": {
                "char_start": 7188, "char_end": 7217,
                "text": "a person in an enlisted grade"}},
            "applicability": {
                "scope_kind": "title",
                "scope_id": "callerdeclaredusc:title10:personnel:2024",
                "jurisdiction_id": "us", "instrument_id": "usc:us:10",
                "legal_as_of_civil_date": None, "source_edition": 2024,
                "source_release_id": "govinfo-markup-v2-edition:2024",
            },
        },
    }


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True)
    destination = Path(parser.parse_args().output_directory)
    need(destination.is_absolute() and destination.resolve() == destination
         and destination.is_dir(), "absolute existing real export directory required")
    initial = destination.stat()
    need(initial.st_uid == os.getuid() and stat.S_IMODE(initial.st_mode) == 0o700
         and not any(destination.iterdir()), "owned empty 0700 export directory required")
    temporary = Path(os.environ.get("TMPDIR", ""))
    need(temporary.is_absolute() and temporary.resolve() == temporary and temporary.is_dir()
         and temporary.name == "tmp" and destination == temporary.parent / "exports",
         "export directory must match the native launcher's existing attempt layout")
    driver_sha = sha(Path(__file__).read_bytes())
    checks, refusals, calls = [], [], []

    def passed(label):
        checks.append(label)

    def invoke(label, function, *args, **kwargs):
        calls.append(label)
        return function(*args, **kwargs)

    def refuse(label, function, *args, **kwargs):
        try:
            invoke(label, function, *args, **kwargs)
        except ValueError as error:
            refusals.append({"check": label, "refused": True,
                             "exception_type": type(error).__name__,
                             "reason": str(error)[:2000]})
            passed(label)
        else:
            raise ValueError("negative control unexpectedly accepted: " + label)

    passed("owned_empty_real_output_directory")
    prior_raw = pinned(PRIOR / "replay-receipt.json", 7705, PRIOR_RECEIPT_SHA)
    prior = load(prior_raw)
    need(prior["schema"] == "legal-ir-sampled-source-review-replay/v1"
         and prior["all_checks_passed"] is True
         and prior["actual_response_count"] == prior["actual_reviews"] == 0
         and prior["actual_population_pending"] == 560
         and prior["bundle_full_canonical_sha256"] == BUNDLE_CANONICAL_SHA
         and prior["original_sampling_full_canonical_sha256"] == SAMPLING_SHA,
         "pinned prior successful actual-source replay differs")
    prior_files = {row["path"]: row for row in prior["outputs"]}
    inputs = (
        ("review-bundle.json", 5664497, BUNDLE_FILE_SHA),
        ("source.html", 98879, RAW_SHA),
        ("acquisition-descriptor.json", 926, DESC_SHA),
        ("acquisition-receipt.json", 1069, ACQUISITION_SHA),
        ("synthetic-diagnostic-block-0054-unresolved-response.json", 7311,
         SYNTHETIC_RESPONSE_FILE_SHA),
    )
    retained = {}
    for name, size, pin in inputs:
        need(prior_files[name] == {"path": name, "bytes": size, "sha256": pin},
             "prior receipt output binding differs")
        retained[name] = pinned(PRIOR / name, size, pin)
    bundle_raw, raw = retained["review-bundle.json"], retained["source.html"]
    bundle = load(bundle_raw)
    descriptor = load(retained["acquisition-descriptor.json"])
    acquisition = load(retained["acquisition-receipt.json"])
    need(digest(bundle) == BUNDLE_CANONICAL_SHA
         and digest(bundle["sampling_report"]) == SAMPLING_SHA
         and digest(descriptor) == DESC_CANONICAL_SHA
         and acquisition["descriptor_canonical_sha256"] == DESC_CANONICAL_SHA
         and acquisition["source_or_meaning_reviewed"] is False,
         "independent full canonical source/bundle commitment differs")
    passed("prior_success_receipt_and_original_transport_canonical_source_pins")

    need("ipfs_datasets_py" not in sys.modules, "fresh validation process required")
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.logic.autoformal import corpus_contracts, corpus_graph
    from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
    from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge_v2 as bridge
    from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampling
    from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as intake
    from ipfs_datasets_py.logic.autoformal import legal_source_sampling_definition_binding_v2 as owner

    modules = (owner, intake, sampling, bridge, adapter, corpus_contracts, corpus_graph)

    def module_pins():
        pins = []
        for module in modules:
            path = Path(module.__file__).resolve()
            need(path.is_relative_to(ACTIVE.resolve()),
                 "public operation owner imported outside active repository")
            pins.append({"module": module.__name__, "path": str(path),
                         "sha256": sha(path.read_bytes())})
        return pins

    producers = module_pins()
    need(intake.sampling_review_bundle_sha256(bundle) == BUNDLE_CANONICAL_SHA
         and sampling.source_sampling_report_sha256(bundle["sampling_report"]) == SAMPLING_SHA,
         "public full canonical input hashes differ")
    replay = dict(descriptor=descriptor, expected_descriptor_sha256=DESC_CANONICAL_SHA,
                  expected_raw_sha256=RAW_SHA, expected_raw_bytes=98879,
                  expected_sampling_report_sha256=SAMPLING_SHA)
    common = dict(expected_bundle_sha256=BUNDLE_CANONICAL_SHA,
                  expected_response_sha256s=[], **replay)
    report = bundle["sampling_report"]
    records = {row["record_cid"]: row for row in report["records"]}
    for expected in (SOURCE_VERSION_REF, DEFINITION_UNIT_REF, SCOPE_UNIT_REF):
        need(reference(records[expected["record_cid"]]) == expected,
             "explicit retained original source/unit identity differs")
    need(records[DEFINITION_UNIT_REF["record_cid"]]["ordinal"] == 54
         and records[SCOPE_UNIT_REF["record_cid"]]["ordinal"] == 48,
         "explicit navigation block identity differs")
    units = [row for row in report["records"] if row["schema"] == sampling.UNIT_SCHEMA]
    contexts = [row for row in report["records"]
                if row["schema"] == "legal-corpus-context-declaration/v1"]
    need(report["counts"]["blocks"] == len(units) == len(bundle["guides"]) == 560
         and len(report["records"]) == 1681
         and sum(bool(unit["candidate_input"]) for unit in units) == 134
         and sum(len(context["missing_requirements"]) for context in contexts) == 3360
         and sum(len(guide["unanswered_question_ids"]) for guide in bundle["guides"]) == 8400,
         "complete original source and blank-guide population differs")
    no_authority(bundle)
    passed("complete_source_retained_560_pending_guides_8400_blanks_3360_open_requirements")

    outputs = {
        "prior-replay-receipt.json": prior_raw,
        "review-bundle.json": bundle_raw,
        "source.html": raw,
        "acquisition-descriptor.json": retained["acquisition-descriptor.json"],
        "acquisition-receipt.json": retained["acquisition-receipt.json"],
        "actual-responses.json": b"[]\n",
    }
    results, requests, request_bytes = {}, {}, {}
    summaries = []
    for family in ("fol", "tdfol"):
        request = declared_request(family)
        request_raw = wire(request) + b"\n"
        request_sha = sha(request_raw)
        arguments = dict(expected_request_sha256=request_sha, **common)
        result = invoke("prepare_actual_" + family, owner.prepare_definition_binding_v2,
                        request_raw, bundle, [], raw, **arguments)
        result_sha = digest(result)
        need(owner.definition_binding_sha256(result) == result_sha,
             "public binding canonical hash differs")
        need(invoke("validate_actual_" + family, owner.validate_definition_binding_v2,
                    result, request_raw, bundle, [], raw,
                    expected_binding_sha256=result_sha, **arguments) == result,
             "complete public binding regeneration differs")
        population, binding = result["population"], result["binding"]
        definition, candidate = result["definition_report"], result["candidate"]
        need(population["subject_count"] == population["counts"]["pending"] == 560
             and population["response_count"] == 0
             and population["review_completed"] is False
             and population["adjudication_performed"] is False,
             "actual response-free population is no longer wholly pending")
        need(binding["status"] == "pending" and binding["response_count"] == 0
             and binding["selected_subject_count"] == 2
             and len(binding["required_subjects"]) == 2
             and all(subject["state"] == "pending" and subject["response_refs"] == []
                     for subject in binding["required_subjects"]),
             "selected scope/contributor subjects acquired review or completion")
        need(definition["declaration"] == request["declaration"]
             and definition["explicit_universal_biconditional"] is True
             and definition["definition_lexical_coverage_complete"] is False
             and definition["native"]["exact_native_ast_roundtrip"] is True
             and definition["native_ast"]["quantifier"]["value"] == "∀"
             and definition["native_ast"]["formula"]["operator"]["value"] == "↔"
             and len(definition["symbols"]) == 2,
             "explicit caller unary biconditional or opaque-body structure differs")
        frontier = definition["source_context_frontier"]
        need(frontier["original_blocks"] == frontier["original_units"] == 560
             and frontier["original_open_context_obligations"] == 3360
             and frontier["selected_original_occurrences"] == 2
             and frontier["derived_role_occurrences"] == 4
             and frontier["selected_physical_occurrences"] == 6
             and frontier["selected_open_context_obligations"] == 36
             and frontier["unselected_original_occurrences"] == 558
             and frontier["whole_source_context_retained_externally"] is True,
             "full source/context frontier was silently reduced")
        graph = candidate["graph"]
        node_ids = {node["record_cid"] for node in graph["nodes"]}
        need(all(edge["src_cid"] in node_ids and edge["dst_cid"] in node_ids
                 for edge in graph["edges"])
             and sum(edge["relation"] == "DEFINES" for edge in graph["edges"]) == 1
             and not any(edge["relation"] == "USES_DEFINITION" for edge in graph["edges"])
             and not any(node["node_type"] in {"entity", "norm_assertion"}
                         for node in graph["nodes"]),
             "candidate graph acquired dangling endpoints, identity, norm or definition use")
        need(candidate["view"] == "candidate"
             and all(candidate[field] is False for field in adapter.FALSE_FLAGS)
             and candidate["term_record"]["kind"] == "declared_unary_category"
             and candidate["term_record"]["resolved_entity_identity"] is False,
             "candidate acquired review, identity, model, proof or training authority")
        no_authority(result)
        prefix = "actual-" + family
        for name, value in (("request", request), ("definition-report", definition),
                            ("candidate", candidate), ("binding", binding),
                            ("population", population), ("result", result)):
            outputs[prefix + "-" + name + ".json"] = (
                request_raw if name == "request" else wire(value) + b"\n")
        results[family], requests[family], request_bytes[family] = result, request, request_raw
        summaries.append({"family": family, "request_transport_sha256": request_sha,
                          "result_full_canonical_sha256": result_sha,
                          "definition_report_full_canonical_sha256": digest(definition),
                          "candidate_full_canonical_sha256": digest(candidate),
                          "native_ast_sha256": digest(definition["native_ast"]),
                          "lean_body_sha256": sha(definition["lean_body"].encode()),
                          "selected_subject_count": 2, "actual_response_count": 0,
                          "population_pending": 560, "graph_nodes": len(graph["nodes"]),
                          "graph_edges": len(graph["edges"]),
                          "source_context_frontier": frontier})
        passed("actual_" + family + "_public_prepare_regeneration_and_candidate_only_graph")
    need(results["fol"]["definition_report"]["native_ast"]
         == results["tdfol"]["definition_report"]["native_ast"]
         and results["fol"]["definition_report"]["lean_body"]
         == results["tdfol"]["definition_report"]["lean_body"]
         and results["fol"]["definition_report"]["symbols"]
         == results["tdfol"]["definition_report"]["symbols"],
         "pure FOL subset differs between declared FOL and TDFOL projections")
    passed("two_declared_family_routes_preserve_same_supported_unary_structure")

    base_raw = request_bytes["fol"]
    base_arguments = dict(expected_request_sha256=sha(base_raw), **common)
    refuse("negative_request_transport_pin_refused", owner.prepare_definition_binding_v2,
           base_raw, bundle, [], raw,
           **dict(base_arguments, expected_request_sha256="0" * 64))
    for label, mutate in (
        ("foreign_source", lambda value: value["declaration"]["source_version_ref"].update(sha256="0" * 64)),
        ("foreign_scope", lambda value: value["declaration"].update(scope_unit_ref=deepcopy(DEFINITION_UNIT_REF))),
    ):
        bad = deepcopy(requests["fol"])
        mutate(bad)
        bad_raw = wire(bad) + b"\n"
        outputs["negative-" + label + "-request.json"] = bad_raw
        refuse("negative_" + label + "_refused", owner.prepare_definition_binding_v2,
               bad_raw, bundle, [], raw,
               **dict(base_arguments, expected_request_sha256=sha(bad_raw)))
    synthetic_raw = retained["synthetic-diagnostic-block-0054-unresolved-response.json"]
    synthetic = load(synthetic_raw)
    need(synthetic["reviewer_declaration"]["principal_id"].startswith(
        "synthetic-driver-fixture-not-an-actual-reviewer-")
         and all(answer["disposition"] == "unresolved"
                 for answer in synthetic["source_answers"] + synthetic["meaning_proposals"]),
         "retained synthetic negative input acquired substantive review")
    outputs["negative-input-only-prior-synthetic-unresolved-response.json"] = synthetic_raw
    refuse("negative_response_pin_refused", owner.prepare_definition_binding_v2,
           base_raw, bundle, [synthetic], raw,
           **dict(base_arguments, expected_response_sha256s=["0" * 64]))

    def reseal(record):
        return corpus_contracts.seal_record({key: deepcopy(value)
                                            for key, value in record.items()
                                            if key not in {"record_cid", "cid_scope"}})

    tampered = deepcopy(results["fol"])
    tampered["candidate"]["ast_record"]["native_ast"]["formula"]["operator"]["value"] = "→"
    tampered["candidate"]["ast_record"] = reseal(tampered["candidate"]["ast_record"])
    tampered["candidate"] = reseal(tampered["candidate"])
    outputs["negative-resealed-candidate-ast-result.json"] = wire(tampered) + b"\n"
    refuse("negative_resealed_candidate_ast_refused", owner.validate_definition_binding_v2,
           tampered, base_raw, bundle, [], raw,
           expected_binding_sha256=digest(tampered), **base_arguments)
    tampered = deepcopy(results["fol"])
    tampered["candidate"]["proof_authority"] = True
    tampered["candidate"] = reseal(tampered["candidate"])
    outputs["negative-resealed-candidate-authority-result.json"] = wire(tampered) + b"\n"
    refuse("negative_resealed_candidate_authority_refused", owner.validate_definition_binding_v2,
           tampered, base_raw, bundle, [], raw,
           expected_binding_sha256=digest(tampered), **base_arguments)
    need(len(refusals) == 6, "negative control population differs")
    outputs["negative-control-results.json"] = wire({
        "schema": "legal-definition-candidate-binding-negative-controls/v1",
        "controls": refusals, "rejected_payloads_are_primary_results": False,
        "synthetic_input_is_an_actual_response": False,
        "actual_responses_for_each_primary_result": 0}) + b"\n"

    source_index = {
        "schema": "legal-definition-candidate-binding-source-index/v1",
        "bundle_file": "review-bundle.json", "bundle_original_file_sha256": BUNDLE_FILE_SHA,
        "bundle_full_canonical_sha256": BUNDLE_CANONICAL_SHA,
        "complete_sampler_json_pointer": "/sampling_report",
        "complete_sampler_full_canonical_sha256": SAMPLING_SHA,
        "full_source_view_json_pointer": "/sampling_report/document_view_report",
        "all_guides_json_pointer": "/guides",
        "source_file": "source.html", "source_raw_sha256": RAW_SHA,
        "source_version_ref": SOURCE_VERSION_REF, "normalized_view_id": VIEW_ID,
        "contributor_unit_refs": [DEFINITION_UNIT_REF], "scope_unit_ref": SCOPE_UNIT_REF,
        "coordinate_profile": "normalized_V2_unicode_and_UTF8_half_open_not_raw_HTML",
        "request_interpretation_status": "unreviewed_caller_declaration",
        "declared_title_scope_is_verified_applicability": False,
        "body_phrase_is_an_opaque_unary_predicate": True,
        "person_or_grade_sorts_inferred": False,
        "source_meaning_completeness_verified": False,
        "primary_actual_response_count": 0,
        "synthetic_negative_input_counted_as_actual_review": False,
    }
    outputs["source-context-index.json"] = wire(source_index) + b"\n"
    need(module_pins() == producers and sha(Path(__file__).read_bytes()) == driver_sha,
         "driver or active operation owner changed during replay")
    passed("driver_and_active_operation_owner_sources_unchanged")
    for name, size, pin in (("replay-receipt.json", 7705, PRIOR_RECEIPT_SHA), *inputs):
        pinned(PRIOR / name, size, pin)
    passed("all_retained_original_input_transport_pins_unchanged")
    passed("bounded_exclusive_flat_exports_and_exact_readback")
    receipt = {
        "schema": "legal-ir-definition-candidate-binding-replay/v1",
        "all_checks_passed": True, "checks": checks,
        "driver_sha256": driver_sha, "producer_modules": producers,
        "historical_driver_sha256": HISTORICAL_DRIVER_SHA256,
        "source_repository": str(ROOT), "retained_input_directory": str(PRIOR),
        "prior_receipt_sha256": PRIOR_RECEIPT_SHA,
        "bundle_original_file_sha256": BUNDLE_FILE_SHA,
        "bundle_full_canonical_sha256": BUNDLE_CANONICAL_SHA,
        "source_raw_sha256": RAW_SHA, "source_raw_bytes": 98879,
        "descriptor_original_file_sha256": DESC_SHA,
        "descriptor_full_canonical_sha256": DESC_CANONICAL_SHA,
        "original_sampling_full_canonical_sha256": SAMPLING_SHA,
        "source_counts": report["counts"], "blank_guides": 560,
        "blank_question_slots": 8400, "original_open_context_requirements": 3360,
        "declared_candidate_families": summaries,
        "actual_response_count": 0, "actual_reviews": 0,
        "actual_population_pending_each_family": 560,
        "synthetic_positive_binding_runs": 0,
        "retained_synthetic_negative_inputs": 1,
        "negative_controls_refused": len(refusals), "public_operation_calls": calls,
        "explicit_unreviewed_unary_definition_requests": 2,
        "learned_translations": 0, "definition_use_bindings": 0,
        "resolved_entity_identities": 0, "norms_created": 0,
        "reviewed_meanings_created": 0, "semantic_admissions": 0,
        "training_gold": 0, "evaluation_gold": 0, "Lean_admissions": 0,
        "training_model_network_native_Lean_publication_actions": 0,
        "direct_native_compiler_execution": False,
        "aggregate_export_byte_limit": MAX_OUTPUT_BYTES,
        "outputs": [{"path": name, "bytes": len(body), "sha256": sha(body)}
                    for name, body in outputs.items()],
    }
    outputs["replay-receipt.json"] = wire(receipt) + b"\n"
    need(sum(len(body) for body in outputs.values()) <= MAX_OUTPUT_BYTES,
         "complete export byte bound exceeded before writing")
    written = set()
    for name, body in outputs.items():
        need(Path(name).name == name, "flat export name required")
        current = destination.stat()
        need((current.st_dev, current.st_ino, current.st_uid)
             == (initial.st_dev, initial.st_ino, initial.st_uid)
             and {path.name for path in destination.iterdir()} == written,
             "owned empty export directory changed before write")
        with (destination / name).open("xb") as stream:
            stream.write(body)
        need((destination / name).read_bytes() == body, "exact export readback differs")
        written.add(name)
    need(sum(path.stat().st_size for path in destination.iterdir()) <= MAX_OUTPUT_BYTES,
         "actual aggregate export byte bound exceeded")
    need(module_pins() == producers and sha(Path(__file__).read_bytes()) == driver_sha,
         "driver or operation owner changed during export")
    for name, size, pin in (("replay-receipt.json", 7705, PRIOR_RECEIPT_SHA), *inputs):
        pinned(PRIOR / name, size, pin)
    print(json.dumps({"output_directory": str(destination),
                      "receipt_sha256": sha(outputs["replay-receipt.json"]),
                      "all_checks_passed": True, "actual_reviews": 0,
                      "candidate_families": ["fol", "tdfol"],
                      "negative_controls_refused": len(refusals)}))


if __name__ == "__main__":
    main()
