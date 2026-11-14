"""Independent fictional full-population catalog batch controls.

All sources, vocabularies, references and generation declarations are authored
engineering fixtures. No historical/statutory fixtures, models or training are
used. Execution belongs to the existing admitted parent qualification owner.
"""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import re

import pytest

from ipfs_datasets_py.logic.autoformal import legal_compact_content_v1 as content_owner
from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as legacy
from ipfs_datasets_py.logic.autoformal import legal_relational_batch_core_v1 as core
from ipfs_datasets_py.logic.autoformal import legal_relational_catalog_batch_evaluation_v1 as owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_tokens_v1 as catalog_tokens
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as content_tokens
from ipfs_datasets_py.logic.syntax_core import ast, signatures


LEXICAL = re.compile(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]')
TERMINALS = {"missing", "duplicate", "malformed", "unverifiable_generation", "abstained",
    "unsupported", "invalid_typed_output", "valid_without_reference", "compared", "incomplete",
    "invalid_frame", "invalid_content_output", "budget_exhausted", "error", "timeout", "cancellation", "not_started"}
COMPARISONS = ("exact_typed_expression_equal", "family_profile_equal", "signature_declarations_equal",
    "argument_roles_equal", "declared_structure_equal", "lexical_alpha_structure_equal")
DECLARED = ("abstained", "unsupported", "error", "timeout", "cancellation", "not_started")
MIXED_IDS = ("match", "wrong", "no_reference", "missing", "duplicate", "malformed", "source_mismatch",
    "target_context", "teacher_forcing", *DECLARED, "incomplete", "invalid_frame", "invalid_content_output", "budget_exhausted")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def transport(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                      allow_nan=False).encode("utf-8") + b"\n"


def sha(raw): return hashlib.sha256(raw).hexdigest()


def authored_request():
    """Build an independent original reference, with authored archival IDs."""
    obj = signatures.LogicSort("Object")
    gamma = ast.mk_predicate("authored:gamma", "Gamma", [ast.mk_variable("authored:y", "y", obj),
        ast.mk_variable("authored:x1", "x", obj)])
    alpha = ast.mk_predicate("authored:alpha", "Alpha", [ast.mk_variable("authored:x2", "x", obj)])
    permission = ast.mk_extension("authored:permission", family="tdfol", profile="tdfol_default",
        features=("legacy.permission", "legacy.classic_letter"), payload_schema="legacy.deontic/v1",
        payload={"kind": "permission", "letter": "P", "resolution": "deontic", "schema_version": "legacy.deontic/v1"},
        children=(alpha,))
    body = ast.mk_and("authored:and", gamma, permission)
    body = ast.mk_exists("authored:exists", (ast.Binder("y", obj),), body)
    body = ast.mk_forall("authored:forall", (ast.Binder("x", obj),), body)
    signature = signatures.LogicSignature("authored:signature", family="tdfol", profile="tdfol_default",
        sorts=(obj,), symbols=(signatures.declare_predicate("Alpha", (obj,)),
                               signatures.declare_predicate("Gamma", (obj, obj))))
    expression = ast.TypedExpression("authored:expression", body, signature)
    return {"schema": "legal-relational-norm-request/v1", "interpretation_status": "authored_unreviewed_declaration",
        "source_binding": None, "expression": expression.to_dict(),
        "argument_roles": [{"symbol": "Alpha", "roles": ["subject"]},
                           {"symbol": "Gamma", "roles": ["sender", "receiver"]}]}


def walk(tree):
    yield tree
    if tree[0] == "predicate": children = tree[2]
    elif tree[0] in {"forall", "exists", "extension"}: children = [tree[2]]
    elif tree[0] in {"and", "or", "implies", "iff"}: children = tree[1:]
    elif tree[0] == "not": children = [tree[1]]
    else: children = []
    for child in children: yield from walk(child)


def ids_for(content, codec):
    text = wire(content).decode()
    lexical = LEXICAL.findall(text)
    assert "".join(lexical) == text
    lookup = {word: index for index, word in enumerate(codec["vocabulary"])}
    return [1, *(lookup[word] for word in lexical), 2]


@pytest.fixture(scope="module")
def material():
    request = authored_request()
    raw = wire(request)
    projection = content_owner.project_request_v1(raw, expected_request_sha256=sha(raw))
    full = deepcopy(projection["context"])
    unused = deepcopy(full["signature"]["symbols"][0])
    unused["name"] = "Beta"
    full["signature"]["symbols"].insert(1, unused)
    full["argument_roles"] = [deepcopy(full["argument_roles"][1]), deepcopy(full["argument_roles"][0]),
                              {"symbol": "Beta", "roles": ["observer"]}]
    catalog = {"schema": "legal-relational-compact-catalog-context/v1",
        "selection_policy": "referenced_predicates_in_catalog_order/v1", "catalog": full}
    catalog_content = deepcopy(projection["content"])
    for node in walk(catalog_content["tree"]):
        if node[0] == "predicate" and node[1] == 1: node[1] = 2
    ccodec, tcodec = catalog_tokens.build_compact_catalog_token_codec_v1(), content_tokens.build_compact_content_token_codec_v1()
    reference = relational.prepare_relational_norm_v1(raw, expected_request_sha256=sha(raw))
    return {"request": request, "reference": reference,
        "catalog": {"context": catalog, "content": catalog_content, "codec": ccodec,
                    "ids": ids_for(catalog_content, ccodec)},
        "content": {"context": projection["context"], "content": projection["content"], "codec": tcodec,
                    "ids": ids_for(projection["content"], tcodec)}}


def generation(pop_sha):
    return {"kind": "decoder_declared", "population_sha256": pop_sha, "latent_dimension": 384,
        "checkpoint_sha256": sha(b"authored checkpoint declaration; no model"),
        "encoder_sha256": sha(b"authored encoder declaration; no model"),
        "settings_sha256": sha(b"authored settings; no inference"), "teacher_forcing": False, "target_access": False}


def generated(row, ids, context, profile="catalog", **changes):
    raw = wire(context)
    return {**row, "status": "generated", "teacher_forcing": False, "target_access": False,
        "generated_ids": deepcopy(ids), "generated_ids_sha256": sha(wire(ids)), "reason": None,
        profile + "_context_utf8": raw.decode(), profile + "_context_sha256": sha(raw),
        profile + "_context_origin": "authored_fixture", **changes}


def declared(row, status, profile="catalog"):
    return {**row, "status": status, "teacher_forcing": False, "target_access": False,
        "generated_ids": None, "generated_ids_sha256": None, "reason": "Explicit fictional outcome",
        profile + "_context_utf8": None, profile + "_context_sha256": None, profile + "_context_origin": None}


def make_case(material, names=("one",), *, profile="catalog", unavailable=()):
    population = {"schema": "legal-relational-batch-population/v1", "partition": "authored-fictional-controls",
        "selection_sha256": sha(b"complete authored population selection"),
        "rows": [{"id": name, "source_sha256": sha(("source:" + name).encode()),
                  "context_sha256": sha(("source-context:" + name).encode())} for name in names]}
    population_raw = transport(population)
    request_raw = wire(material["request"])
    references = {"schema": "legal-relational-batch-references/v1", "population_sha256": sha(population_raw),
        "rows": [{"id": name, "status": "unavailable" if name in unavailable else "available",
                  "request_utf8": None if name in unavailable else request_raw.decode(),
                  "request_sha256": None if name in unavailable else sha(request_raw),
                  "report": None if name in unavailable else deepcopy(material["reference"]),
                  "report_sha256": None if name in unavailable else sha(wire(material["reference"])),
                  "reason": "No authored reference supplied" if name in unavailable else None} for name in names]}
    item = material[profile]
    predictions = {"schema": "legal-relational-" + profile + "-token-batch-predictions/v1",
        "codec": deepcopy(item["codec"]), "codec_sha256": sha(wire(item["codec"])),
        "generation": generation(sha(population_raw)),
        "rows": [generated(row, item["ids"], item["context"], profile) for row in population["rows"]]}
    return {"population": population, "population_raw": population_raw, "references": references, "predictions": predictions}


def originals(case):
    raws = (case["population_raw"], transport(case["references"]), transport(case["predictions"]))
    pins = {"expected_" + name + "_sha256": sha(raw) for name, raw in zip(("population", "references", "predictions"), raws)}
    return raws, pins


def prepare(case, **overrides):
    raws, pins = originals(case)
    return owner.prepare_relational_catalog_batch_evaluation_v1(*raws, **{**pins, **overrides})


def prepare_core(case, profile):
    raws, pins = originals(case)
    return core.prepare_relational_batch_core_v1(*raws, profile=profile, **pins)


def prepare_old(case):
    raws, pins = originals(case)
    return legacy.prepare_relational_content_token_batch_evaluation_v1(*raws, **pins)


def validate(case, report):
    raws, pins = originals(case)
    return owner.validate_relational_catalog_batch_evaluation_v1(report, *raws,
        expected_evaluation_sha256=sha(wire(report)), **pins)


def direct(row, material, profile="catalog"):
    module = catalog_tokens if profile == "catalog" else content_tokens
    operation = module.decode_compact_catalog_tokens_v1 if profile == "catalog" else module.decode_compact_content_tokens_v1
    item = material[profile]
    return operation(row["generated_ids"], row[profile + "_context_utf8"].encode(),
        expected_context_sha256=row[profile + "_context_sha256"], codec=item["codec"],
        expected_codec_sha256=sha(wire(item["codec"])))


def budget_output(material, profile):
    if profile == "catalog":
        ctx = deepcopy(material[profile]["context"])
    else:
        ctx = deepcopy(material[profile]["context"])
        ctx["signature"]["symbols"] = ctx["signature"]["symbols"][:1]
        ctx["argument_roles"] = ctx["argument_roles"][:1]
    rows = [["predicate", 0, [["variable", 0]]] for _ in range(27)]
    while len(rows) > 1:
        combined = [["and", rows[i], rows[i + 1]] for i in range(0, len(rows) - 1, 2)]
        if len(rows) % 2: combined.append(rows[-1])
        rows = combined
    value = {"schema": "legal-relational-compact-content/v1",
        "tree": ["forall", 0, ["exists", 1, ["not", ["not", ["not", rows[0]]]]]]}
    ids = ids_for(value, material[profile]["codec"])
    assert len(ids) == 515
    return ids[:512], ctx


def mixed_case(material, profile="catalog"):
    case = make_case(material, MIXED_IDS, profile=profile, unavailable={"no_reference"})
    by_id = {row["id"]: row for row in case["population"]["rows"]}
    item = material[profile]
    wrong, invalid = deepcopy(item["content"]), deepcopy(item["content"])
    next(node for node in walk(wrong["tree"]) if node[0] == "predicate")[2].reverse()
    next(node for node in walk(invalid["tree"]) if node[0] == "variable")[1] = 511
    budget, budget_ctx = budget_output(material, profile)
    def g(name, ids=None, ctx=None, **changes):
        return generated(by_id[name], item["ids"] if ids is None else ids,
            item["context"] if ctx is None else ctx, profile, **changes)
    case["predictions"]["rows"] = [g("match"), g("wrong", ids_for(wrong, item["codec"])), g("no_reference"),
        g("duplicate"), g("duplicate", []), g("malformed", unexpected="preserved"),
        g("source_mismatch", source_sha256=sha(b"different authored source")),
        g("target_context", **{profile + "_context_origin": "target_derived_label"}),
        g("teacher_forcing", teacher_forcing=True),
        *[declared(by_id[status], status, profile) for status in DECLARED],
        g("incomplete", item["ids"][:-1]), g("invalid_frame", [1, 999, 2]),
        g("invalid_content_output", ids_for(invalid, item["codec"])), g("budget_exhausted", budget, budget_ctx),
        g("match", id="outside"), g("match", [], id="outside"), g("match")]
    case["predictions"]["rows"][-1].pop("id")
    return case


def no_authority(report):
    assert report["generation_claims_are_declarations_only"] is True
    assert report["declared_operational_statuses_are_unverified"] is True
    assert report["catalog_context_claims_are_declarations_only"] is True
    assert report["authority"] and all(value is False for value in report["authority"].values())
    for key in ("training_mask", "evaluation_gold_mask"):
        assert type(report[key]) is int and report[key] == 0
    assert set(report["terminal_counts"]) == TERMINALS
    assert sum(report["terminal_counts"].values()) == len(report["occurrences"])
    for observed in report["observation_ledger"]:
        assert "content_decoding" not in observed and "compact_decoding" not in observed
        decoded = observed["catalog_decoding"]
        if decoded is not None:
            assert observed["catalog_decoding_sha256"] == sha(wire(decoded))
            assert all(value is False for value in decoded["authority"].values())


def assert_mixed_accounting(case, report, profile="catalog"):
    assert len(case["population"]["rows"]) == len(MIXED_IDS) == 19
    assert report["population"]["ordered_ids"] == list(MIXED_IDS)
    assert report["coverage"] == {"valid": False, "expected_count": 19, "prediction_row_count": 22,
        "missing_ids": ["missing"], "duplicate_ids": {"duplicate": [3, 4]},
        "unexpected_ids": {"outside": [19, 20]}, "unidentifiable_indices": [21]}
    expected = {name: 1 for name in TERMINALS}
    expected.update(compared=2, unverifiable_generation=3, invalid_typed_output=0)
    assert report["terminal_counts"] == expected
    assert report["valid_typed_output"] == {"count": 3, "total": 19, "fraction": 3 / 19}
    assert report["reference_availability"] == {"available": 18, "unavailable": 1, "total": 19, "fraction": 18 / 19}
    ledger = report["observation_ledger"]
    assert [row["raw_observation"] for row in ledger] == case["predictions"]["rows"]
    assert [row["index"] for row in ledger] == list(range(22))
    assert [row["outcome"] for row in ledger[-3:]] == ["unexpected", "unexpected", "unidentifiable"]
    assert ledger[3][profile + "_decoding"]["status"] == "valid_candidate"
    assert ledger[4][profile + "_decoding"]["status"] == "incomplete"
    assert ledger[5][profile + "_decoding"]["status"] == "valid_candidate"
    assert ledger[21][profile + "_decoding"]["status"] == "valid_candidate"
    assert all(ledger[i][profile + "_decoding"]["status"] == "valid_candidate" for i in (6, 7, 8))
    matching = dict(zip(COMPARISONS, (False, True, True, True, False, True)))
    wrong = {**matching, "lexical_alpha_structure_equal": False}
    assert report["occurrences"][0]["pair_diagnostic"]["comparisons"] == matching
    assert report["occurrences"][1]["pair_diagnostic"]["comparisons"] == wrong
    for name in COMPARISONS:
        successes = int(matching[name]) + int(wrong[name])
        assert report["full_selected_structure_diagnostics"][name] == {"matched": successes, "total": 19, "fraction": successes / 19}
        assert report["comparable_pair_structure_diagnostics"][name] == {"matched": successes, "total": 2, "fraction": successes / 2}


def test_catalog_first_preserves_existing_legacy_cache_state_before_old_public_intake(material):
    # This test intentionally precedes our first old batch call. It also works
    # when another selected file has already populated a legacy cache: no cache
    # resets, module replacements or order-dependent cold-state assumptions.
    names = ("_OPERATION_SNAPSHOTS", "_COMPACT_OPERATION_SNAPSHOTS", "_CONTENT_OPERATION_SNAPSHOTS")
    identities = {name: getattr(legacy, name) for name in names}
    before = deepcopy(identities)
    catalog_case, content_case = make_case(material), make_case(material, profile="content")
    first = prepare(catalog_case)
    for name in names:
        assert getattr(legacy, name) is identities[name]
        assert getattr(legacy, name) == before[name]
    old = prepare_old(content_case)
    assert prepare(catalog_case) == first
    assert prepare_old(content_case) == old


def test_complete_19_selected_22_observation_catalog_and_content_differential_fixture(material, tmp_path, record_property):
    catalog_case, content_case = mixed_case(material), mixed_case(material, "content")
    before = deepcopy((catalog_case, content_case))
    old = prepare_old(content_case)
    cache_names = ("_OPERATION_SNAPSHOTS", "_COMPACT_OPERATION_SNAPSHOTS", "_CONTENT_OPERATION_SNAPSHOTS")
    caches = {name: (getattr(legacy, name), deepcopy(getattr(legacy, name))) for name in cache_names}
    successor = prepare_core(content_case, "content_tokens_v1")
    report = prepare(catalog_case)
    assert (catalog_case, content_case) == before
    assert_mixed_accounting(catalog_case, report)
    assert_mixed_accounting(content_case, old, "content")
    assert_mixed_accounting(content_case, successor, "content")
    differences = {"schema", "producer_pins"}
    assert set(successor) == set(old) | {"accounting_core"}
    for key in set(old) - differences: assert successor[key] == old[key], key
    assert successor["schema"] == "legal-relational-content-token-batch-evaluation/v2"
    assert successor["accounting_core"]["profile"] == "content_tokens_v1"
    assert successor["accounting_core"]["schema"] == "legal-relational-batch-core/v1"
    assert successor["producer_pins"] == {**old["producer_pins"], str(Path(core.__file__).absolute()): successor["accounting_core"]["source_sha256"]}
    assert successor["limitations"] == old["limitations"]
    assert successor["accounting_core"]["legacy_accounting_source_sha256"] == old["producer_pins"][str(Path(legacy.__file__).absolute())]
    for name, (identity, snapshot) in caches.items():
        assert getattr(legacy, name) is identity and getattr(legacy, name) == snapshot
    assert prepare_old(content_case) == old
    assert report["schema"] == "legal-relational-catalog-token-batch-evaluation/v1"
    assert report["profile"] == "full-selected-catalog-token-output-diagnostics/v1"
    assert validate(catalog_case, report) == report
    assert owner.relational_catalog_batch_evaluation_sha256(report) == sha(wire(report))
    core_report = prepare_core(catalog_case, "catalog_tokens_v1")
    outer_without_pin = deepcopy(report)
    assert outer_without_pin["producer_pins"].pop(str(Path(owner.__file__).absolute()))
    assert outer_without_pin == core_report
    no_authority(report)
    artifacts = {}
    for label, case in (("catalog", catalog_case), ("content", content_case)):
        raw, _ = originals(case)
        artifacts.update({label + "-" + name + ".json": value for name, value in zip(("population", "references", "predictions"), raw)})
    artifacts.update({"catalog-report.json": wire(report), "content-core-report.json": wire(successor),
        "content-legacy-report.json": wire(old), "reference-request.json": wire(material["request"])})
    declarations = {"schema": "authored-catalog-batch-source-declarations/v1", "statutory_source": False,
        "model_executed": False, "inference_context_permission_verified": False,
        "rows": [{"id": name, "source_text": "source:" + name, "source_context_text": "source-context:" + name} for name in MIXED_IDS]}
    artifacts["source-declarations.json"] = wire(declarations)
    for name, raw in artifacts.items(): (tmp_path / name).write_bytes(raw)
    manifest = {"schema": "authored-catalog-batch-fixture/v1", "fixture_origin": "authored_fictional",
        "selected_count": 19, "observation_count": 22,
        "differential_allowed_fields": sorted(differences | {"accounting_core"}),
        "files": [{"name": name, "bytes": len(raw), "sha256": sha(raw)} for name, raw in artifacts.items()]}
    path = tmp_path / "manifest.json"
    path.write_bytes(wire(manifest))
    record_property("catalog_batch_fixture_manifest", str(path))


def test_public_core_dispatch_and_facade_accept_only_original_transports(material):
    case = make_case(material)
    raw, pins = originals(case)
    assert set(inspect.signature(core.prepare_relational_batch_core_v1).parameters) == {
        "population_raw", "references_raw", "predictions_raw", "profile", *pins}
    assert set(inspect.signature(owner.prepare_relational_catalog_batch_evaluation_v1).parameters) == {
        "population_raw", "references_raw", "predictions_raw", *pins}
    with pytest.raises(ValueError): core.prepare_relational_batch_core_v1(*raw, profile="raw_requests", **pins)
    with pytest.raises(TypeError): owner.prepare_relational_catalog_batch_evaluation_v1(*raw, decoded_observations=[], **pins)


@pytest.mark.parametrize("case_name", ["malformed_and_provenance", "duplicate_good", "bad_generation_timeout", "source_mismatch_invalid_grammar", "missing_generation"])
def test_precedence_never_promotes_favorable_or_unverifiable_observations(material, case_name):
    case = make_case(material)
    row = case["predictions"]["rows"][0]
    if case_name == "malformed_and_provenance": row.update(extra="retained", target_access=True); expected = "malformed"
    elif case_name == "duplicate_good": case["predictions"]["rows"].append(deepcopy(row)); expected = "duplicate"
    elif case_name == "bad_generation_timeout":
        case["predictions"]["generation"]["teacher_forcing"] = True
        case["predictions"]["rows"] = [declared(case["population"]["rows"][0], "timeout")]
        expected = "unverifiable_generation"
    elif case_name == "source_mismatch_invalid_grammar":
        row.update(source_sha256=sha(b"other source"), generated_ids=[1, 999, 2], generated_ids_sha256=sha(wire([1, 999, 2])))
        expected = "unverifiable_generation"
    else: case["predictions"].pop("generation"); expected = "unverifiable_generation"
    report = prepare(case)
    assert report["occurrences"][0]["status"] == expected
    assert report["occurrences"][0]["pair_diagnostic"] is None
    assert report["valid_typed_output"] == {"count": 0, "total": 1, "fraction": 0.0}
    assert [row["raw_observation"] for row in report["observation_ledger"]] == case["predictions"]["rows"]
    if case_name == "malformed_and_provenance":
        assert report["occurrences"][0]["reasons"] == ["prediction_fields_mismatch"]
        assert report["observation_ledger"][0]["catalog_decoding"]["status"] == "valid_candidate"
    if case_name == "source_mismatch_invalid_grammar":
        assert report["occurrences"][0]["reasons"] == ["prediction_source_sha256_mismatch"]
        assert report["observation_ledger"][0]["catalog_decoding"]["status"] == "rejected"
    no_authority(report)


@pytest.mark.parametrize("prediction_state", ["missing", "duplicate", "timeout"])
def test_corrupt_available_reference_aborts_even_without_comparable_output(material, prediction_state):
    case = make_case(material)
    reference = case["references"]["rows"][0]
    reference["report"]["counts"]["nodes"] -= 1
    reference["report_sha256"] = sha(wire(reference["report"]))
    if prediction_state == "missing": case["predictions"]["rows"] = []
    elif prediction_state == "duplicate": case["predictions"]["rows"] *= 2
    else: case["predictions"]["rows"] = [declared(case["population"]["rows"][0], "timeout")]
    with pytest.raises(ValueError): prepare(case)


def test_real_reference_replay_refusal_precedes_invalid_unused_catalog_declaration(material):
    case = make_case(material)
    reference = case["references"]["rows"][0]
    reference["report"]["counts"]["nodes"] -= 1
    reference["report_sha256"] = sha(wire(reference["report"]))
    with pytest.raises(ValueError) as first: prepare(case)
    ctx = deepcopy(material["catalog"]["context"])
    ctx["catalog"]["argument_roles"][2]["roles"] = []
    case["predictions"]["rows"][0] = generated(case["population"]["rows"][0], material["catalog"]["ids"], ctx)
    with pytest.raises(ValueError) as combined: prepare(case)
    assert type(combined.value) is type(first.value) and str(combined.value) == str(first.value)


def test_valid_alternate_reference_changes_comparison_without_changing_decoding(material):
    case = make_case(material)
    first = prepare(case)
    wrong = deepcopy(material["catalog"]["content"])
    next(node for node in walk(wrong["tree"]) if node[0] == "predicate")[2].reverse()
    offered = generated(case["population"]["rows"][0], ids_for(wrong, material["catalog"]["codec"]), material["catalog"]["context"])
    alternate = direct(offered, material)["selection"]["prediction"]["request"]
    raw = wire(alternate)
    reference = relational.prepare_relational_norm_v1(raw, expected_request_sha256=sha(raw))
    case["references"]["rows"][0].update(request_utf8=raw.decode(), request_sha256=sha(raw), report=reference, report_sha256=sha(wire(reference)))
    second = prepare(case)
    assert first["observation_ledger"] == second["observation_ledger"]
    assert first["occurrences"][0]["pair_diagnostic"]["comparisons"]["lexical_alpha_structure_equal"] is True
    assert second["occurrences"][0]["pair_diagnostic"]["comparisons"]["lexical_alpha_structure_equal"] is False


@pytest.mark.parametrize("damage", ["raw_catalog_hash", "bad_hash_and_ids", "unused_roles", "too_many_ids", "too_many_bool_ids", "old_codec", "old_context", "source_catalog_hash_swap"])
def test_catalog_and_whole_sequence_failures_are_atomic_or_provenance_not_silent_repair(material, damage):
    case = make_case(material)
    row = case["predictions"]["rows"][0]
    if damage in {"raw_catalog_hash", "bad_hash_and_ids"}:
        row["catalog_context_sha256"] = "0" * 64
        if damage == "bad_hash_and_ids": row.update(generated_ids=[True], generated_ids_sha256=sha(wire([True])))
    elif damage in {"too_many_ids", "too_many_bool_ids"}:
        ids = [True if damage == "too_many_bool_ids" else 1] * 513
        row.update(generated_ids=ids, generated_ids_sha256=sha(wire(ids)))
    elif damage == "old_codec":
        case["predictions"]["codec"] = deepcopy(material["content"]["codec"])
        case["predictions"]["codec_sha256"] = sha(wire(case["predictions"]["codec"]))
    elif damage == "source_catalog_hash_swap":
        row["context_sha256"] = row["catalog_context_sha256"]
        report = prepare(case)
        assert report["occurrences"][0]["status"] == "unverifiable_generation"
        assert report["occurrences"][0]["reasons"] == ["prediction_context_sha256_mismatch"]
        assert report["observation_ledger"][0]["catalog_decoding"]["status"] == "valid_candidate"
        return
    else:
        ctx = deepcopy(material["catalog"]["context"])
        if damage == "unused_roles": ctx["catalog"]["argument_roles"][2]["roles"] = []
        else: ctx = ctx["catalog"]
        raw = wire(ctx)
        row.update(catalog_context_utf8=raw.decode(), catalog_context_sha256=sha(raw))
    before = deepcopy(case)
    with pytest.raises(ValueError): prepare(case)
    assert case == before


@pytest.mark.parametrize("damage", ["id_hash", "id_bool", "missing_context", "bad_origin", "extra_sidecar"])
def test_row_malformation_retains_original_population_and_available_mechanical_evidence(material, damage):
    case = make_case(material)
    row = case["predictions"]["rows"][0]
    if damage == "id_hash": row["generated_ids_sha256"] = "0" * 64
    elif damage == "id_bool": row.update(generated_ids=[True], generated_ids_sha256=sha(wire([True])))
    elif damage == "missing_context": row["catalog_context_utf8"] = None
    elif damage == "bad_origin": row["catalog_context_origin"] = "permission_verified"
    else: row["identity_sidecar"] = {"authored": "not accepted as an original identity"}
    report = prepare(case)
    assert report["occurrences"][0]["status"] == "malformed"
    assert report["observation_ledger"][0]["raw_observation"] == row
    decoded = report["observation_ledger"][0]["catalog_decoding"]
    assert (decoded is None) is (damage != "extra_sidecar")
    assert report["valid_typed_output"] == {"count": 0, "total": 1, "fraction": 0.0}
    no_authority(report)


@pytest.mark.parametrize("mutation", ["unused_name", "unused_roles", "role_ledger_order", "whitespace"])
def test_full_catalog_identity_and_raw_context_binding_survive_unchanged_effective_formula(material, mutation):
    case = make_case(material)
    first = prepare(case)
    ctx = deepcopy(material["catalog"]["context"])
    if mutation == "unused_name":
        ctx["catalog"]["signature"]["symbols"][1]["name"] = "UnusedAlternative"
        ctx["catalog"]["argument_roles"][2]["symbol"] = "UnusedAlternative"
    elif mutation == "unused_roles": ctx["catalog"]["argument_roles"][2]["roles"] = ["witness"]
    elif mutation == "role_ledger_order": ctx["catalog"]["argument_roles"].reverse()
    raw = transport(ctx) if mutation == "whitespace" else wire(ctx)
    case["predictions"]["rows"][0].update(catalog_context_utf8=raw.decode(), catalog_context_sha256=sha(raw))
    second = prepare(case)
    left, right = [r["observation_ledger"][0]["catalog_decoding"] for r in (first, second)]
    assert left["selection"]["prediction"] == right["selection"]["prediction"]
    assert left["context_raw_sha256"] != right["context_raw_sha256"]
    assert (left["selection"]["catalog_prediction_id"] == right["selection"]["catalog_prediction_id"]) is (mutation == "whitespace")
    assert first["occurrences"] == second["occurrences"]
    no_authority(second)


@pytest.mark.parametrize("case_name", ["zero_predictions", "all_unavailable", "duplicates_only", "max_population_and_observations"])
def test_boundary_populations_keep_denominators_and_null_zero_comparison_fraction(material, case_name):
    names = ["row-" + str(i) for i in range(64 if case_name == "max_population_and_observations" else 2)]
    case = make_case(material, names, unavailable=names)
    if case_name == "zero_predictions": case["predictions"]["rows"] = []
    elif case_name in {"duplicates_only", "max_population_and_observations"}:
        case["predictions"]["rows"] = [declared(row, "timeout") for row in case["population"]["rows"]
            for _ in range(4 if case_name == "max_population_and_observations" else 2)]
    report = prepare(case)
    count = len(names)
    expected = "missing" if case_name == "zero_predictions" else "valid_without_reference" if case_name == "all_unavailable" else "duplicate"
    assert report["terminal_counts"][expected] == count
    assert report["valid_typed_output"]["total"] == count
    assert report["reference_availability"]["unavailable"] == count
    for metric in report["comparable_pair_structure_diagnostics"].values():
        assert metric == {"matched": 0, "total": 0, "fraction": None}
    if case_name == "max_population_and_observations":
        assert report["coverage"]["prediction_row_count"] == 256
        case["predictions"]["rows"].append(deepcopy(case["predictions"]["rows"][0]))
        with pytest.raises(ValueError): prepare(case)
    no_authority(report)


@pytest.mark.parametrize("damage", ["status", "drop_ledger", "catalog_origin", "producer_path", "selection_mapping"])
def test_resealed_report_tampering_cannot_replace_full_original_replay(material, damage):
    case = make_case(material)
    report = prepare(case)
    if damage == "status": report["occurrences"][0]["status"] = "valid_without_reference"
    elif damage == "drop_ledger": report["observation_ledger"].clear()
    elif damage == "catalog_origin": report["observation_ledger"][0]["raw_observation"]["catalog_context_origin"] = "caller_supplied_unverified"
    elif damage == "producer_path": report["producer_pins"]["/untrusted/not-an-owner.py"] = "0" * 64
    else: report["observation_ledger"][0]["catalog_decoding"]["selection"]["catalog_to_effective"] = [0, 1, None]
    with pytest.raises(ValueError): validate(case, report)


@pytest.mark.parametrize("field", ["expected_population_sha256", "expected_references_sha256", "expected_predictions_sha256"])
def test_each_independent_original_transport_pin_is_required(material, field):
    case = make_case(material)
    with pytest.raises(ValueError): prepare(case, **{field: "0" * 64})


@pytest.mark.parametrize("damage", ["reordered_references", "duplicate_population", "empty_population", "population_65", "shared_node_budget", "outer_depth", "population_bytes", "predictions_bytes"])
def test_complete_transport_bounds_and_population_order_refuse_without_truncation(material, damage):
    case = make_case(material, ("first", "second"))
    if damage == "reordered_references": case["references"]["rows"].reverse()
    elif damage in {"duplicate_population", "empty_population"}:
        case["population"]["rows"] = ([case["population"]["rows"][0]] * 2 if damage == "duplicate_population" else [])
        case["population_raw"] = transport(case["population"])
        case["references"]["population_sha256"] = sha(case["population_raw"])
        case["predictions"]["generation"]["population_sha256"] = sha(case["population_raw"])
    elif damage == "population_65":
        case = make_case(material, ["row-" + str(i) for i in range(65)], unavailable={"row-" + str(i) for i in range(65)})
    elif damage == "shared_node_budget":
        # Each separate payload fits500000nodes; the sum across references and
        # predictions exceeds the one shared intake budget. No owner can repair it.
        case = make_case(material, unavailable={"one"})
        case["references"]["rows"][0]["authored_overflow"] = [None] * 250001
        case["predictions"]["rows"][0]["authored_overflow"] = [None] * 250001
    elif damage == "outer_depth":
        nested = None
        for _ in range(98): nested = [nested]
        case["predictions"]["rows"].append(nested)
    raw, pins = originals(case)
    if damage in {"population_bytes", "predictions_bytes"}:
        raw = list(raw)
        index, limit = (0, 128 * 1024) if damage == "population_bytes" else (2, 16 * 1024 * 1024)
        raw[index] += b" " * (limit + 1 - len(raw[index]))
        pins["expected_" + ("population" if index == 0 else "predictions") + "_sha256"] = sha(raw[index])
    if damage == "shared_node_budget":
        # Individually these ordinary transports fit. Only their combined node
        # population exceeds the shared budget before semantic row validation.
        for index in (1, 2):
            legacy._transport(raw[index], sha(raw[index]), 16 * 1024 * 1024, [500000])
        with pytest.raises(ValueError, match="ordinary JSON (list|node/depth) bound exceeded"):
            owner.prepare_relational_catalog_batch_evaluation_v1(*raw, **pins)
    else:
        with pytest.raises(ValueError): owner.prepare_relational_catalog_batch_evaluation_v1(*raw, **pins)


def test_all_used_catalog_with_catalog_order_roles_matches_old_full_use_prediction(material):
    case = make_case(material)
    ctx = deepcopy(material["catalog"]["context"])
    roles = {row["symbol"]: row for row in ctx["catalog"]["argument_roles"]}
    ctx["catalog"]["argument_roles"] = [roles[symbol["name"]] for symbol in ctx["catalog"]["signature"]["symbols"]]
    value = deepcopy(material["catalog"]["content"])
    body = value["tree"][2][2]
    value["tree"][2][2] = ["and", ["predicate", 1, [["variable", 0]]], body]
    ids = ids_for(value, material["catalog"]["codec"])
    case["predictions"]["rows"][0] = generated(case["population"]["rows"][0], ids, ctx)
    report = prepare(case)
    decoded = report["observation_ledger"][0]["catalog_decoding"]
    assert decoded["selection"]["selected_catalog_indices"] == [0, 1, 2]
    assert decoded["selection"]["unused_catalog_indices"] == []
    assert decoded["selection"]["catalog_to_effective"] == [0, 1, 2]
    assert decoded["selection"]["selected_role_row_indices"] == [0, 1, 2]
    raw = wire(ctx["catalog"])
    old_codec = material["content"]["codec"]
    old = content_tokens.decode_compact_content_tokens_v1(ids, raw,
        expected_context_sha256=sha(raw), codec=old_codec, expected_codec_sha256=sha(wire(old_codec)))
    assert decoded["selection"]["prediction"] == old["prediction"]
    no_authority(report)


def test_catalog_reordering_retains_index_mapping_without_changing_effective_formula(material):
    case = make_case(material)
    first = prepare(case)
    ctx, value = deepcopy((material["catalog"]["context"], material["catalog"]["content"]))
    symbols = ctx["catalog"]["signature"]["symbols"]
    symbols[0], symbols[1] = symbols[1], symbols[0]
    for node in walk(value["tree"]):
        if node[0] == "predicate" and node[1] == 0: node[1] = 1
    case["predictions"]["rows"][0] = generated(case["population"]["rows"][0], ids_for(value, material["catalog"]["codec"]), ctx)
    second = prepare(case)
    left, right = [r["observation_ledger"][0]["catalog_decoding"]["selection"] for r in (first, second)]
    assert left["selected_catalog_indices"] == [0, 2] and right["selected_catalog_indices"] == [1, 2]
    assert right["catalog_to_effective"] == [None, 0, 1] and right["unused_catalog_indices"] == [0]
    assert left["prediction"] == right["prediction"]
    assert left["catalog_prediction_id"] != right["catalog_prediction_id"]
    assert first["occurrences"] == second["occurrences"]


def test_proper_subset_succeeds_only_under_new_profile_not_old_all_predicate_intake(material):
    case = make_case(material)
    result = prepare(case)
    assert result["terminal_counts"]["compared"] == 1
    row = case["predictions"]["rows"][0]
    old_case = make_case(material, profile="content")
    old_case["predictions"]["rows"][0] = generated(old_case["population"]["rows"][0], row["generated_ids"],
        material["catalog"]["context"]["catalog"], "content")
    old = prepare_old(old_case)
    assert old["terminal_counts"]["invalid_content_output"] == 1
    assert old["valid_typed_output"]["count"] == 0
    assert old["observation_ledger"][0]["content_decoding"]["prediction"] is None


@pytest.mark.parametrize("phase,error_type", [("decode", RuntimeError), ("decode", KeyboardInterrupt),
    ("decode_and_close", RuntimeError), ("decode_and_close", KeyboardInterrupt)])
def test_operational_failure_and_cancellation_preserve_first_exception_without_counted_partial_report(material, phase, error_type, monkeypatch):
    case = make_case(material)
    failure = error_type("authored private phase failure; no generated cancellation row")
    def failing_phase(*args, **kwargs):
        if phase == "decode_and_close":
            monkeypatch.setattr(core, "_SELF_SNAPSHOT", ("0" * 64, core._SELF_SNAPSHOT[1]))
        raise failure
    # Explicit new-core operation-failure seam. No original decoder, legacy
    # owner globals, source bytes or state are replaced or changed.
    monkeypatch.setattr(core, "_decode_observations", failing_phase)
    with pytest.raises(error_type) as caught: prepare(case)
    assert caught.value is failure
    if phase == "decode_and_close":
        assert any("closing" in note.lower() or "custody" in note.lower() for note in getattr(failure, "__notes__", []))


def test_core_complete_report_bound_refuses_instead_of_dropping_observations(material, monkeypatch):
    # Exercise complete-output bound mechanics using a declared smaller limit;
    # this is not an 8 MiB size/performance benchmark or cap increase.
    case = make_case(material)
    before = deepcopy(case)
    complete = prepare_core(case, "catalog_tokens_v1")
    monkeypatch.setattr(core, "MAX_OUTPUT_BYTES", len(wire(complete)) - 1)
    with pytest.raises(ValueError): prepare_core(case, "catalog_tokens_v1")
    assert case == before


def test_complete_serialization_precedes_final_core_source_custody_check(material, monkeypatch):
    case = make_case(material)
    original, seen = core._wire, []
    def changed_after_complete_serialization(value, maximum):
        raw = original(value, maximum)
        if type(value) is dict and value.get("schema") == "legal-relational-catalog-token-batch-evaluation/v1":
            seen.append(True)
            monkeypatch.setattr(core, "_SELF_SNAPSHOT", ("0" * 64, core._SELF_SNAPSHOT[1]))
        return raw
    monkeypatch.setattr(core, "_wire", changed_after_complete_serialization)
    with pytest.raises(ValueError): prepare_core(case, "catalog_tokens_v1")
    assert seen == [True]


@pytest.mark.parametrize("anchor", ["core", "catalog", "content"])
def test_changed_source_import_anchor_aborts_even_when_output_is_incomplete(material, anchor, monkeypatch):
    case = make_case(material)
    case["predictions"]["rows"][0].update(generated_ids=[], generated_ids_sha256=sha(wire([])))
    module = {"core": core, "catalog": catalog_tokens, "content": content_owner}[anchor]
    if anchor == "content": monkeypatch.setattr(module, "_SELF_SHA", "0" * 64)
    else: monkeypatch.setattr(module, "_SELF_SNAPSHOT", ("0" * 64, module._SELF_SNAPSHOT[1]))
    with pytest.raises(ValueError): prepare(case)


@pytest.mark.parametrize("damage", ["mapping", "roles", "effective_content", "prediction_request",
    "prediction_identity", "owner_path", "mask_bool", "authority"])
def test_genuine_nested_owner_report_cannot_substitute_effective_projection_or_authority(material, damage, monkeypatch):
    case = make_case(material)
    genuine = catalog_tokens.decode_compact_catalog_tokens_v1
    calls = []
    def damaged_return(*args, **kwargs):
        checked = genuine(*args, **kwargs)
        calls.append(checked["status"])
        selection = checked["selection"]
        if damage == "mapping": selection["catalog_to_effective"] = [0, 1, None]
        elif damage == "roles": selection["selected_role_row_indices"].reverse()
        elif damage == "effective_content":
            for node in walk(selection["effective_content"]["tree"]):
                if node[0] == "predicate" and len(node[2]) == 2: node[2].reverse()
            selection["effective_content_sha256"] = sha(wire(selection["effective_content"]))
        elif damage == "prediction_request":
            prediction = selection["prediction"]
            prediction["request"]["expression"]["expression_id"] = "forged:independent-id"
            prediction["request_sha256"] = sha(wire(prediction["request"]))
            selection["prediction_sha256"] = sha(wire(prediction))
        elif damage == "prediction_identity": selection["catalog_prediction_id"] = "compact-catalog-prediction-v1:" + "0" * 64
        elif damage == "owner_path": checked["owner_pins"][0]["path"] = "/authored/untrusted-owner-path.py"
        elif damage == "mask_bool": checked["training_mask"] = False
        elif damage == "authority": checked["authority"][next(iter(checked["authority"]))] = True
        return checked
    # Explicit report-intake fault injection after the genuine public decoder.
    # Its grammar, source files, caches and reference data are not replaced.
    monkeypatch.setattr(catalog_tokens, "decode_compact_catalog_tokens_v1", damaged_return)
    with pytest.raises(ValueError): prepare(case)
    assert calls == ["valid_candidate"]


def test_mutation_of_detached_input_by_genuine_owner_return_aborts_and_keeps_original_bytes(material, monkeypatch):
    case = make_case(material)
    before = originals(case)
    genuine = catalog_tokens.decode_compact_catalog_tokens_v1
    calls = []
    def altered_detached_input(*args, **kwargs):
        result = genuine(*args, **kwargs)
        calls.append(True)
        kwargs["codec"]["vocabulary"][3] = "authored altered detached vocabulary"
        return result
    monkeypatch.setattr(catalog_tokens, "decode_compact_catalog_tokens_v1", altered_detached_input)
    with pytest.raises(ValueError, match="detached original batch inputs changed"):
        prepare(case)
    assert calls == [True]
    assert originals(case) == before
