"""Independent authored content-token batch controls, with no trained-model claim.

Contexts are explicitly projected from authored reference declarations here.
They are target-derived fixtures, not qualified source-only inference context.
Only public prediction decoding may feed comparison; archival IDs stay outside
prediction intake. All execution belongs to the admitted parent qualifier.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import legal_compact_content_v1 as content_owner
from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_compact_codec_v1 as byte_compact


def _fixtures():
    name = "_content_token_batch_authored_fixtures"
    path = Path(__file__).with_name("test_legal_relational_batch_evaluation_v1.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


legacy = _fixtures()
wire, sha, transport = legacy.wire, legacy.sha, legacy.transport
PREDICTIONS_SCHEMA = "legal-relational-content-token-batch-predictions/v1"
REPORT_SCHEMA = "legal-relational-content-token-batch-evaluation/v1"
REPORT_PROFILE = "full-selected-context-bound-content-token-output-diagnostics/v1"
ORIGIN = "target_derived_label"
LEXICAL = re.compile(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]')
TERMINALS = {"missing", "duplicate", "malformed", "unverifiable_generation", "abstained",
    "unsupported", "invalid_typed_output", "valid_without_reference", "compared", "incomplete",
    "invalid_frame", "invalid_content_output", "budget_exhausted", "error", "timeout", "cancellation", "not_started"}


def ids_for(content, codec, *, eos=True):
    """Independent lexical oracle from the fixed published vocabulary."""
    text = wire(content).decode("utf-8")
    lexical = LEXICAL.findall(text)
    assert "".join(lexical) == text
    index = {piece: position for position, piece in enumerate(codec["vocabulary"])}
    return [1, *(index[piece] for piece in lexical), *([2] if eos else [])]


def project(request):
    raw = wire(request)
    return content_owner.project_request_v1(raw, expected_request_sha256=sha(raw))


def generated(row, ids, context, *, origin=ORIGIN, **changes):
    context_raw = wire(context)
    return {**row, "status": "generated", "teacher_forcing": False, "target_access": False,
        "generated_ids": deepcopy(ids), "generated_ids_sha256": sha(wire(ids)), "reason": None,
        "content_context_utf8": context_raw.decode("utf-8"), "content_context_sha256": sha(context_raw),
        "content_context_origin": origin, **changes}


def declared(row, status):
    return {**row, "status": status, "teacher_forcing": False, "target_access": False,
        "generated_ids": None, "generated_ids_sha256": None, "reason": "Explicit authored disposition",
        "content_context_utf8": None, "content_context_sha256": None, "content_context_origin": None}


@pytest.fixture(scope="module")
def material():
    request = legacy._FIXTURE._FIXTURE.approval_request()
    projection = project(request)
    codec = tokens.build_compact_content_token_codec_v1()
    return {"request": request, "content": projection["content"], "context": projection["context"],
        "codec": codec, "codec_sha256": tokens.compact_content_token_codec_sha256(codec),
        "ids": ids_for(projection["content"], codec)}


def make_case(material, ids=("one",), *, unavailable=(), repeated_source=False):
    case = legacy.case_for(list(ids), material["request"], unavailable=unavailable, repeated_source=repeated_source)
    case["predictions"] = {"schema": PREDICTIONS_SCHEMA, "codec": deepcopy(material["codec"]),
        "codec_sha256": material["codec_sha256"], "generation": legacy.generation(sha(case["population_raw"])),
        "rows": [generated(row, material["ids"], material["context"]) for row in case["population"]["rows"]]}
    return case


def prepare(case, **overrides):
    raw, pins = legacy.originals(case)
    return owner.prepare_relational_content_token_batch_evaluation_v1(*raw, **{**pins, **overrides})


def validate(case, report):
    raw, pins = legacy.originals(case)
    return owner.validate_relational_content_token_batch_evaluation_v1(report, *raw,
        expected_evaluation_sha256=sha(wire(report)), **pins)


def direct(row, material):
    return tokens.decode_compact_content_tokens_v1(row["generated_ids"], row["content_context_utf8"].encode("utf-8"),
        expected_context_sha256=row["content_context_sha256"], codec=material["codec"],
        expected_codec_sha256=material["codec_sha256"])


def assert_no_authority(report):
    assert report["schema"] == REPORT_SCHEMA and report["profile"] == REPORT_PROFILE
    assert report["generation_claims_are_declarations_only"] is True
    assert report["declared_operational_statuses_are_unverified"] is True
    assert report["content_context_claims_are_declarations_only"] is True
    assert all(value is False for value in report["authority"].values())
    for field in ("permitted_inference_context_verified", "content_context_origin_verified",
                  "content_context_independence_verified", "checkpoint_compatibility_verified"):
        assert report["authority"][field] is False
    for field in ("training_mask", "evaluation_gold_mask"):
        assert type(report[field]) is int and report[field] == 0
    assert set(report["terminal_counts"]) == TERMINALS
    assert sum(report["terminal_counts"].values()) == len(report["occurrences"])
    for row in report["observation_ledger"]:
        decoded = row["content_decoding"]
        assert "compact_decoding" not in row
        if decoded is not None:
            assert row["content_decoding_sha256"] == sha(wire(decoded))
            assert all(value is False for value in decoded["authority"].values())
            assert decoded["authority"]["permitted_inference_context_verified"] is False


def retain(case, report, directory, record_property):
    """Retain complete authored inputs/results for independent admitted readback."""
    directory.mkdir()
    original_raw, _ = legacy.originals(case)
    artifacts = dict(zip(("population.json", "references.json", "predictions.json"), original_raw))
    artifacts.update({"request.json": wire(case["request"]), "report.json": wire(report)})
    source_declarations = {"schema": "authored-content-token-batch-source-declarations/v1",
        "authored_fixture": True, "statutory_source": False, "context_origin": ORIGIN,
        "context_permission_verified": False, "model_executed": False,
        "rows": [{"id": row["id"], "source_text": "source:" + row["id"],
                  "source_context_text": "context:" + row["id"], "source_sha256": row["source_sha256"],
                  "source_context_sha256": row["context_sha256"]} for row in case["population"]["rows"]]}
    assert all(sha(row["source_text"].encode()) == row["source_sha256"] and
               sha(row["source_context_text"].encode()) == row["source_context_sha256"]
               for row in source_declarations["rows"])
    artifacts["source-declarations.json"] = wire(source_declarations)
    manifest = {}
    for name, raw in artifacts.items():
        path = directory / name
        path.write_bytes(raw)
        manifest[name] = {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}
    manifest_raw = wire({"schema": "authored-content-token-batch-fixture/v1", "artifacts": manifest})
    manifest_path = directory / "manifest.json"
    manifest_path.write_bytes(manifest_raw)
    record_property("content_token_batch_fixture", json.dumps({"path": str(manifest_path), "sha256": sha(manifest_raw)}, sort_keys=True))


def test_same_authored_content_is_alpha_equal_with_fresh_ids_and_exact_original_observations(material, tmp_path, record_property):
    case = make_case(material)
    before = deepcopy(case)
    report = prepare(case)
    assert case == before and validate(case, report) == report
    assert owner.relational_content_token_batch_evaluation_sha256(report) == sha(wire(report))
    row, observed = case["predictions"]["rows"][0], report["observation_ledger"][0]
    decoded = observed["content_decoding"]
    assert decoded == direct(row, material)
    assert observed["raw_observation"] == row
    assert observed["sha256"] == sha(wire(row))
    assert row["content_context_sha256"] != row["context_sha256"]
    assert row["content_context_origin"] == ORIGIN
    assert decoded["generated_ids"] == material["ids"]
    assert decoded["prediction"]["identity_mode"] == "generated"
    assert decoded["prediction"]["request"]["expression"]["expression_id"] != material["request"]["expression"]["expression_id"]
    assert "identity_sidecar" not in decoded["prediction"]
    assert report["occurrences"][0]["status"] == "compared"
    assert report["occurrences"][0]["pair_diagnostic"]["comparisons"] == {
        "exact_typed_expression_equal": False, "family_profile_equal": True,
        "signature_declarations_equal": True, "argument_roles_equal": True,
        "declared_structure_equal": False, "lexical_alpha_structure_equal": True}
    assert report["full_selected_structure_diagnostics"]["lexical_alpha_structure_equal"] == {
        "matched": 1, "total": 1, "fraction": 1.0}
    assert_no_authority(report)
    retain(case, report, tmp_path / "single-authored", record_property)


def walk_tree(tree):
    yield tree
    if tree[0] == "predicate": children = tree[2]
    elif tree[0] in {"forall", "exists", "extension"}: children = [tree[2]]
    elif tree[0] in {"and", "or", "implies", "iff"}: children = tree[1:]
    elif tree[0] == "not": children = [tree[1]]
    else: children = []
    for child in children:
        yield from walk_tree(child)


@pytest.mark.parametrize("variation", ["modal_scope", "ordered_arguments", "ordered_roles", "quantifier", "binding_topology"])
def test_valid_rival_structures_and_contexts_are_compared_without_reference_repair(material, variation):
    case = make_case(material)
    content, context = deepcopy((material["content"], material["context"]))
    if variation == "modal_scope":
        body = content["tree"]
        while body[0] in {"forall", "exists"}: body = body[2]
        _, permission, approval = deepcopy(body)
        body[:] = ["extension", permission[1], ["implies", permission[2], approval]]
    elif variation == "ordered_roles": context["argument_roles"][-1]["roles"].reverse()
    elif variation == "quantifier": content["tree"][0] = "exists"
    elif variation == "ordered_arguments":
        predicate = next(row for row in walk_tree(content["tree"]) if row[0] == "predicate" and row[1] == 2)
        predicate[2].reverse()
    else:
        variable = next(row for row in walk_tree(content["tree"]) if row[0] == "variable")
        variable[1] = (variable[1] + 1) % 3
    offered_ids = ids_for(content, material["codec"])
    case["predictions"]["rows"] = [generated(case["population"]["rows"][0], offered_ids, context)]
    report = prepare(case)
    decoded = report["observation_ledger"][0]["content_decoding"]
    assert decoded["status"] == "valid_candidate"
    assert decoded["prediction"]["content"] == content
    assert decoded["prediction"]["context"] == context
    assert decoded["generated_ids"] == offered_ids
    comparison = report["occurrences"][0]["pair_diagnostic"]["comparisons"]
    assert comparison["lexical_alpha_structure_equal"] is False
    assert comparison["argument_roles_equal"] is (variation != "ordered_roles")
    assert_no_authority(report)


def budget_material(codec):
    unary = legacy._FIXTURE.relation_request(name="Eligible", arguments=("actor",), roles=("actor",))
    context = project(unary)["context"]
    rows = [["predicate", 0, [["variable", 0]]] for _ in range(27)]
    while len(rows) > 1:
        rows = [["and", rows[i], rows[i + 1]] for i in range(0, len(rows) - 1, 2)] + (rows[-1:] if len(rows) % 2 else [])
    content = {"schema": "legal-relational-compact-content/v1",
        "tree": ["forall", 0, ["exists", 1, ["not", ["not", ["not", rows[0]]]]]]}
    complete = ids_for(content, codec)
    assert len(complete) == 515
    return complete[:512], context


def test_mixed_population_retains_every_raw_observation_and_full_denominator(material, tmp_path, record_property):
    names = ["missing", "duplicate", "malformed", "unverifiable_generation", "valid_without_reference", "compared",
        "incomplete", "invalid_frame", "invalid_content_output", "budget_exhausted",
        "abstained", "unsupported", "error", "timeout", "cancellation", "not_started"]
    case = make_case(material, names, unavailable={"valid_without_reference"})
    rows = {row["id"]: row for row in case["population"]["rows"]}
    malformed_content = deepcopy(material["content"])
    next(row for row in walk_tree(malformed_content["tree"]) if row[0] == "variable")[1] = 511
    budget_ids, budget_context = budget_material(material["codec"])
    ctx = material["context"]
    observations = [generated(rows["duplicate"], [1, 999, 2], ctx), generated(rows["duplicate"], [], ctx),
        generated(rows["malformed"], material["ids"], ctx, unexpected="retained"),
        generated(rows["unverifiable_generation"], [], ctx, target_access=True),
        generated(rows["valid_without_reference"], material["ids"], ctx), generated(rows["compared"], material["ids"], ctx),
        generated(rows["incomplete"], material["ids"][:-1], ctx), generated(rows["invalid_frame"], [1, 999, 2], ctx),
        generated(rows["invalid_content_output"], ids_for(malformed_content, material["codec"]), ctx),
        generated(rows["budget_exhausted"], budget_ids, budget_context),
        *[declared(rows[status], status) for status in ("abstained", "unsupported", "error", "timeout", "cancellation", "not_started")],
        generated({**rows["compared"], "id": "unexpected"}, material["ids"], ctx),
        generated({k: v for k, v in rows["compared"].items() if k != "id"}, [], ctx),
        ["unidentifiable", True, 7]]
    case["predictions"]["rows"] = observations
    before = deepcopy(case)
    report = prepare(case)
    assert case == before and report["coverage"]["prediction_row_count"] == len(observations) == 19
    assert report["terminal_counts"] == {status: int(status != "invalid_typed_output") for status in TERMINALS}
    assert report["population"]["ordered_ids"] == names
    assert report["coverage"]["missing_ids"] == ["missing"]
    assert report["coverage"]["duplicate_ids"] == {"duplicate": [0, 1]}
    assert report["coverage"]["unexpected_ids"] == {"unexpected": [16]}
    assert report["coverage"]["unidentifiable_indices"] == [17, 18]
    assert report["coverage"]["valid"] is False
    assert [row["raw_observation"] for row in report["observation_ledger"]] == observations
    assert [row["outcome"] for row in report["observation_ledger"][-3:]] == ["unexpected", "unidentifiable", "unidentifiable"]
    budget = report["observation_ledger"][9]["content_decoding"]
    assert budget["generated_ids"] == budget_ids and budget["reason"] == "output_limit_without_eos"
    assert budget["prediction"] is None
    assert report["valid_typed_output"] == {"count": 2, "total": 16, "fraction": 2 / 16}
    for name in owner.COMPARISON_FIELDS:
        assert report["full_selected_structure_diagnostics"][name]["total"] == 16
        assert report["comparable_pair_structure_diagnostics"][name]["total"] == 1
    assert report["full_selected_structure_diagnostics"]["lexical_alpha_structure_equal"]["matched"] == 1
    assert report["full_selected_structure_diagnostics"]["exact_typed_expression_equal"]["matched"] == 0
    assert_no_authority(report)
    retain(case, report, tmp_path / "mixed-authored", record_property)


@pytest.mark.parametrize("damage", ["empty", "missing_eos", "missing_bos", "interior_eos", "pad", "unknown", "closed_incomplete"])
def test_frame_and_prefix_outcomes_remain_distinct_and_preserve_ids(material, damage):
    case = make_case(material)
    ids = list(material["ids"])
    expected = "incomplete" if damage in {"empty", "missing_eos"} else "invalid_frame"
    if damage == "empty": ids = []
    elif damage == "missing_eos": ids.pop()
    elif damage == "missing_bos": ids.pop(0)
    elif damage == "interior_eos": ids.insert(10, 2)
    elif damage == "pad": ids.insert(10, 0)
    elif damage == "unknown": ids[10] = 537
    else: ids = ids[:10] + [2]; expected = "invalid_content_output"
    case["predictions"]["rows"][0] = generated(case["population"]["rows"][0], ids, material["context"])
    report = prepare(case)
    assert report["occurrences"][0]["status"] == expected
    assert report["observation_ledger"][0]["content_decoding"]["generated_ids"] == ids
    assert report["valid_typed_output"]["count"] == 0 and report["valid_typed_output"]["total"] == 1


@pytest.mark.parametrize("damage", ["bool_id", "float_id", "missing_context", "bad_origin", "extra_sidecar"])
def test_malformed_observations_stay_in_denominator_without_invented_context(material, damage):
    case = make_case(material)
    row = case["predictions"]["rows"][0]
    if damage in {"bool_id", "float_id"}:
        row["generated_ids"] = [True] if damage == "bool_id" else [1.0]
        row["generated_ids_sha256"] = sha(wire(row["generated_ids"]))
    elif damage == "missing_context": row["content_context_utf8"] = None
    elif damage == "bad_origin": row["content_context_origin"] = "verified_source_only"
    else: row["identity_sidecar"] = {"expression_id": "must-not-be-restored"}
    report = prepare(case)
    assert report["occurrences"][0]["status"] == "malformed"
    assert report["observation_ledger"][0]["raw_observation"] == row
    assert report["valid_typed_output"]["count"] == 0 and report["valid_typed_output"]["total"] == 1
    if damage in {"bool_id", "float_id", "missing_context", "bad_origin"}:
        assert report["observation_ledger"][0]["content_decoding"] is None


@pytest.mark.parametrize("damage", ["wrong_context_pin", "wrong_pin_with_bad_ids", "bad_context_shape", "identity_in_context",
    "over_512_ids", "over_512_bad_ids", "oversize_context_with_bad_pin"])
def test_context_asset_and_whole_sequence_failures_abort_instead_of_model_outcomes(material, damage):
    case = make_case(material)
    row = case["predictions"]["rows"][0]
    if damage in {"wrong_context_pin", "wrong_pin_with_bad_ids"}:
        row["content_context_sha256"] = "0" * 64
        if damage == "wrong_pin_with_bad_ids":
            row["generated_ids"] = [True]
            row["generated_ids_sha256"] = sha(wire(row["generated_ids"]))
    elif damage in {"over_512_ids", "over_512_bad_ids"}:
        row["generated_ids"] = [True if damage == "over_512_bad_ids" else 1] * 513
        row["generated_ids_sha256"] = sha(wire(row["generated_ids"]))
    elif damage == "oversize_context_with_bad_pin":
        row["content_context_utf8"] = "x" * (tokens.MAX_CONTEXT_BYTES + 1)
        row["content_context_sha256"] = None
    else:
        context = deepcopy(material["context"])
        if damage == "bad_context_shape": context.pop("argument_roles")
        else: context["signature"]["signature_id"] = "archival-signature-forbidden"
        raw = wire(context)
        row.update(content_context_utf8=raw.decode(), content_context_sha256=sha(raw))
    before = deepcopy(case)
    with pytest.raises(ValueError): prepare(case)
    assert case == before


def test_source_context_and_content_context_commitments_are_not_interchangeable(material):
    case = make_case(material)
    row = case["predictions"]["rows"][0]
    row["context_sha256"] = row["content_context_sha256"]
    report = prepare(case)
    assert report["occurrences"][0]["status"] == "unverifiable_generation"
    assert report["observation_ledger"][0]["content_decoding"]["status"] == "valid_candidate"
    assert "prediction_context_sha256_mismatch" in report["occurrences"][0]["reasons"]
    assert report["valid_typed_output"]["count"] == 0


@pytest.mark.parametrize("origin", ["authored_fixture", "target_derived_label", "caller_supplied_unverified"])
def test_each_context_origin_is_a_preserved_declaration_without_permission_or_accuracy_credit(material, origin):
    case = make_case(material)
    case["predictions"]["rows"][0]["content_context_origin"] = origin
    report = prepare(case)
    assert report["observation_ledger"][0]["raw_observation"]["content_context_origin"] == origin
    assert report["occurrences"][0]["status"] == "compared"
    assert_no_authority(report)


def test_decoder_declared_generation_cannot_receive_comparison_credit_with_target_derived_context(material):
    case = make_case(material)
    case["predictions"]["generation"] = legacy.generation(sha(case["population_raw"]), kind="decoder_declared",
        latent_dimension=384, checkpoint_sha256=sha(b"declared checkpoint only"), encoder_sha256=sha(b"declared encoder only"))
    report = prepare(case)
    observed = report["observation_ledger"][0]
    assert observed["content_decoding"]["status"] == "valid_candidate"
    assert observed["raw_observation"]["content_context_origin"] == "target_derived_label"
    assert report["occurrences"][0]["status"] == "unverifiable_generation"
    assert "decoder_declared_target_derived_context" in report["occurrences"][0]["reasons"]
    assert report["occurrences"][0]["pair_diagnostic"] is None
    assert report["valid_typed_output"]["count"] == 0
    assert report["full_selected_structure_diagnostics"]["lexical_alpha_structure_equal"] == {
        "matched": 0, "total": 1, "fraction": 0.0}
    assert_no_authority(report)


def test_prediction_intake_has_no_reference_or_archival_sidecar(material, monkeypatch):
    case = make_case(material)
    decode = tokens.decode_compact_content_tokens_v1
    calls = []
    def observed(ids, context_raw, **options):
        assert set(options) == {"expected_context_sha256", "codec", "expected_codec_sha256"}
        context = json.loads(context_raw)
        assert set(context) == {"schema", "signature", "argument_roles"}
        assert "signature_id" not in context["signature"]
        calls.append((deepcopy(ids), context_raw))
        return decode(ids, context_raw, **options)
    monkeypatch.setattr(tokens, "decode_compact_content_tokens_v1", observed)
    monkeypatch.setattr(content_owner, "reconstruct_request_v1", lambda *a, **k: pytest.fail("archival reconstruction reached prediction intake"))
    report = prepare(case)
    assert len(calls) == 1 and calls[0][0] == material["ids"]
    assert report["occurrences"][0]["pair_diagnostic"]["comparisons"]["exact_typed_expression_equal"] is False


@pytest.mark.parametrize("phase,exception", [("decode", RuntimeError("authored decoder owner failure")),
    ("decode", KeyboardInterrupt("authored cancellation")), ("closing", ValueError("authored source drift"))])
def test_operational_owner_source_failures_and_cancellation_propagate_exactly(material, monkeypatch, phase, exception):
    case = make_case(material)
    def failed(*args, **kwargs): raise exception
    monkeypatch.setattr(tokens, "decode_compact_content_tokens_v1" if phase == "decode" else "_closing", failed)
    with pytest.raises(type(exception)) as caught: prepare(case)
    assert caught.value is exception


@pytest.mark.parametrize("damage", ["token_anchor", "content_anchor", "fixed_dependency", "module_origin"])
def test_changed_content_source_anchors_refuse_before_decoding(material, monkeypatch, damage):
    case = make_case(material)
    if damage == "token_anchor": monkeypatch.setattr(tokens, "_SELF_SHA", "0" * 64)
    elif damage == "content_anchor": monkeypatch.setattr(content_owner, "_SELF_SHA", "0" * 64)
    elif damage == "fixed_dependency": monkeypatch.setattr(tokens, "_OWNER_SHA", "0" * 64)
    else: monkeypatch.setattr(tokens, "__file__", owner.__file__)
    monkeypatch.setattr(tokens, "decode_compact_content_tokens_v1", lambda *a, **k: pytest.fail("changed owner reached decoding"))
    with pytest.raises(ValueError): prepare(case)


def test_complete_content_report_bound_refuses_atomically_without_truncating_observations(material, monkeypatch):
    case = make_case(material)
    before = deepcopy(case)
    reference = prepare(case)
    limit = len(wire(reference)) - 1
    decode, calls = tokens.decode_compact_content_tokens_v1, []
    def observed(*args, **options):
        calls.append(deepcopy(args[0]))
        return decode(*args, **options)
    monkeypatch.setattr(tokens, "decode_compact_content_tokens_v1", observed)
    monkeypatch.setattr(owner, "MAX_OUTPUT_BYTES", limit)
    with pytest.raises(ValueError): prepare(case)
    assert calls == [material["ids"]] and case == before


def test_absent_observations_leave_complete_selected_population_missing(material):
    case = make_case(material, ("first", "second"), unavailable={"second"})
    case["predictions"]["rows"] = []
    report = prepare(case)
    assert report["terminal_counts"]["missing"] == 2
    assert report["observation_ledger"] == []
    assert report["valid_typed_output"] == {"count": 0, "total": 2, "fraction": 0.0}
    assert report["reference_availability"]["unavailable"] == 1
    assert report["comparable_pair_structure_diagnostics"]["lexical_alpha_structure_equal"]["fraction"] is None
    assert_no_authority(report)


def test_resealed_report_cannot_relabel_context_or_drop_original_observations(material):
    case = make_case(material)
    report = prepare(case)
    report["observation_ledger"][0]["raw_observation"]["content_context_origin"] = "authored_fixture"
    with pytest.raises(ValueError): validate(case, report)


def test_existing_utf8_and_compact_byte_apis_remain_identical_before_and_after_content_use(material):
    legacy_case = legacy.case_for(["one"], material["request"])
    old_before = legacy.prepare(legacy_case)
    byte_case = deepcopy(legacy_case)
    codec = byte_compact.build_relational_compact_codec_v1()
    codec_sha = byte_compact.relational_compact_codec_sha256(codec)
    raw = wire(material["request"])
    encoded = byte_compact.encode_relational_compact_target_v1(raw, expected_request_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha)
    byte_case["predictions"] = {"schema": "legal-relational-compact-batch-predictions/v1", "codec": codec, "codec_sha256": codec_sha,
        "generation": legacy.generation(sha(byte_case["population_raw"])), "rows": [{**byte_case["population"]["rows"][0],
        "status": "generated", "teacher_forcing": False, "target_access": False,
        "generated_ids": encoded["target_ids"], "generated_ids_sha256": sha(wire(encoded["target_ids"])), "reason": None}]}
    byte_raw, byte_pins = legacy.originals(byte_case)
    byte_before = owner.prepare_relational_compact_batch_evaluation_v1(*byte_raw, **byte_pins)
    structural = prepare(make_case(material))
    assert legacy.prepare(legacy_case) == old_before
    assert owner.prepare_relational_compact_batch_evaluation_v1(*byte_raw, **byte_pins) == byte_before
    assert old_before["full_selected_structure_diagnostics"]["exact_typed_expression_equal"]["matched"] == 1
    assert byte_before["full_selected_structure_diagnostics"]["exact_typed_expression_equal"]["matched"] == 1
    assert structural["full_selected_structure_diagnostics"]["exact_typed_expression_equal"]["matched"] == 0
    assert structural["full_selected_structure_diagnostics"]["lexical_alpha_structure_equal"]["matched"] == 1
