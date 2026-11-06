"""Fixed counting structure and authored finite controls, without source truth."""
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def original():
    return counted.authored_counted_frame_request()


def prepare(request):
    raw = wire(request)
    return counted.prepare_counted_frame(raw, expected_request_sha256=sha(raw))


def reseal(request):
    """Reidentify a raw typed tree without repairing its shape or annotations."""
    expression = request["expression"]
    identity = {key: expression[key] for key in (
        "expression_id", "family", "interface", "profile", "root", "schema_version", "signature")}
    expression["content_digest"] = sha(json.dumps(identity, sort_keys=True,
        separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii"))
    return request


def nodes(root):
    yield root
    for child in root["arguments"]:
        yield from nodes(child)


def selected(request, kind):
    return [node for node in nodes(request["expression"]["root"]) if node["kind"] == kind]


def matrix(request):
    root = request["expression"]["root"]
    for _ in range(6):
        assert root["kind"] == "forall"
        root = root["arguments"][0]
    return root


def finite(node, members, domains, environment=None):
    """Independent finite interpretation of the serialized existing AST."""
    environment = {} if environment is None else environment
    kind = node["kind"]
    if kind == "variable":
        return environment[node["symbol"]]
    if kind == "predicate":
        if isinstance(members, dict):
            relation = members[node["symbol"]]
        else:
            assert node["symbol"] == "Member"
            relation = members
        return tuple(finite(child, members, domains, environment)
                     for child in node["arguments"]) in relation
    if kind == "equality":
        return finite(node["arguments"][0], members, domains, environment) == finite(
            node["arguments"][1], members, domains, environment)
    if kind == "forall":
        binder = node["binders"][0]
        return all(finite(node["arguments"][0], members, domains,
            environment | {binder["name"]: item}) for item in domains[binder["sort"]["name"]])
    left, right = (finite(child, members, domains, environment) for child in node["arguments"])
    if kind == "and":
        return left and right
    if kind == "or":
        return left or right
    assert kind == "implies"
    return not left or right


def truth(request, rows, *, objects=(0, 1, 2, 3), events=("e",), times=("t",)):
    return finite(request["expression"]["root"], set(rows),
                  {"Object": objects, "EventFrame": events, "TimeFrame": times})


def test_public_replay_retains_complete_fixed_ast_and_zero_authority(original):
    request = deepcopy(original)
    before = deepcopy(request)
    report = prepare(request)
    raw = wire(request)
    replayed = counted.validate_counted_frame(report, raw,
        expected_request_sha256=sha(raw), expected_report_sha256=counted.counted_frame_report_sha256(report))
    assert replayed == report and request == before
    assert report["request"] == request and report["request_raw_utf8"].encode() == raw
    assert report["typed_expression"] == request["expression"]
    assert report["typed_expression_content_digest"] == request["expression"]["content_digest"]
    assert report["typed_expression_sha256"] == sha(wire(request["expression"]))
    assert report["counts"] == {"nodes": 49, "quantifiers": 6,
        "membership_occurrences": 4, "equality_occurrences": 6, "variable_occurrences": 24}
    assert len(report["structural_mapping"]) == 49
    assert len({row["typed_path"] for row in report["structural_mapping"]}) == 49
    assert len({row["node_id"] for row in report["structural_mapping"]}) == 49
    assert [(row["variable"], row["sort"]) for row in report["binder_ledger"]] == [
        ("event", "EventFrame"), ("time", "TimeFrame"), ("x0", "Object"),
        ("x1", "Object"), ("x2", "Object"), ("x3", "Object")]
    assert report["identity_pairs"] == [["x0", "x1"], ["x0", "x2"], ["x0", "x3"],
        ["x1", "x2"], ["x1", "x3"], ["x2", "x3"]]
    assert report["source_binding"] is None
    assert not report["source_bound"] and not report["source_translation_performed"]
    assert not report["native_TDFOL_route_used"] and not report["native_build_executed"]
    assert not any(report["authority"].values())
    assert all(type(value) is bool for value in report["authority"].values())
    for field in ("human_reviews", "signatures_constructed", "admissions", "graph_admissions",
                  "training_mask", "evaluation_gold_mask"):
        assert type(report[field]) is int and report[field] == 0
    assert report["frame"] == request["frame"] and report["membership"] == request["membership"]
    assert all(Path(path).is_file() and sha(Path(path).read_bytes()) == digest
               for path, digest in report["producer_pins"].items())


def test_canonical_fol_preserves_original_identity_and_specialized_lean_text(original):
    report = prepare(original)
    receipt = report["fol_receipt"]
    assert receipt["notation"] == "canonical_fol"
    assert receipt["binary_connective_grouping_preserved"] is True
    assert receipt["first_parse_status"] == receipt["second_parse_status"] == "ok"
    assert all(receipt[key] is True for key in ("original_to_first_alpha_equivalent",
        "first_to_second_alpha_equivalent", "original_to_second_alpha_equivalent", "canonical_print_stable"))
    assert report["canonical_fol"].count(" = ") == 6
    assert report["canonical_fol_sha256"] == sha(report["canonical_fol"].encode())
    assert "def countedAtMostThree" in report["lean_body"]
    assert "{Object EventFrame TimeFrame : Type}" in report["lean_body"]
    assert "Object → EventFrame → TimeFrame → Prop" in report["lean_body"]
    assert "∀ (event : EventFrame) (time : TimeFrame)" in report["lean_body"]
    assert report["lean_body"].count(" = ") == 6
    assert "i.atom" not in report["lean_body"] and "Eq(" not in report["lean_body"]
    assert report["lean_body_sha256"] == sha(report["lean_body"].encode())


def test_grouped_fol_retains_binary_shape_that_the_shared_default_printer_flattens(original):
    from ipfs_datasets_py.logic.parsers import fol
    from ipfs_datasets_py.logic.syntax_core import algebra, ast

    expression = ast.TypedExpression.from_dict(original["expression"])
    default_text = fol.print_fol(expression)
    flattened = fol.parse_fol(default_text, expression.signature)
    assert flattened.ok and flattened.root is not None
    assert not algebra.alpha_equivalent(expression.root, flattened.root)
    report = prepare(original)
    grouped = fol.parse_fol(report["canonical_fol"], expression.signature)
    assert grouped.ok and grouped.root is not None
    assert algebra.alpha_equivalent(expression.root, grouped.root)
    assert len(tuple(grouped.root.walk())) == 49
    assert all(len(node.arguments) == 2 for node in grouped.root.walk()
               if node.kind.value in {"and", "or"})


def test_report_bytes_replay_and_noncanonical_input_formatting_preserve_exact_request(original):
    raw = json.dumps(original, indent=2, ensure_ascii=True).encode()
    report = counted.prepare_counted_frame(raw, expected_request_sha256=sha(raw))
    assert report["request_raw_utf8"].encode() == raw
    assert report["request_sha256"] == sha(raw)
    assert counted.validate_counted_frame(wire(report), raw,
        expected_request_sha256=sha(raw), expected_report_sha256=counted.counted_frame_report_sha256(report)) == report


def test_unique_physical_ids_are_not_required_to_match_authored_fixture_ids(original):
    request = deepcopy(original)
    for index, node in enumerate(nodes(request["expression"]["root"])):
        node["node_id"] = "independent:counting:node:" + str(index)
    request["expression"]["expression_id"] = "independent:counting:expression"
    request["expression"]["signature"]["signature_id"] = "independent:counting:signature"
    report = prepare(reseal(request))
    assert report["typed_expression"] == request["expression"]
    assert report["counts"]["nodes"] == 49


@pytest.mark.parametrize("amount", [0, 1, 2, 3])
def test_at_most_three_does_not_require_exactly_three_or_nonempty_membership(original, amount):
    rows = [(item, "e", "t") for item in range(amount)]
    assert truth(original, rows)
    if amount != 3:
        assert len(set(rows)) != 3


def test_four_distinct_objects_in_one_explicit_frame_fail(original):
    assert not truth(original, [(item, "e", "t") for item in range(4)])


def test_repeated_occurrences_of_the_same_object_do_not_increase_identity_count(original):
    rows = [(0, "e", "t"), (0, "e", "t"), (1, "e", "t"), (2, "e", "t")]
    assert len(rows) == 4 and len(set(rows)) == 3
    assert truth(original, rows)


@pytest.mark.parametrize("axis", ["event", "time"])
def test_explicit_frame_partition_distinguishes_local_bound_from_global_or_cumulative_bound(original, axis):
    rows = [(0, "e0", "t0"), (1, "e0", "t0"), (2, "e0", "t0"),
            (3, "e1" if axis == "event" else "e0", "t1" if axis == "time" else "t0")]
    assert truth(original, rows, events=("e0", "e1"), times=("t0", "t1"))
    aggregated = [(item, "e0", "t0") for item, _, _ in rows]
    assert not truth(original, aggregated, events=("e0", "e1"), times=("t0", "t1"))


def test_objects_not_in_membership_relation_are_not_counted(original):
    assert truth(original, [(0, "e", "t"), (1, "e", "t"), (2, "e", "t")],
                 objects=tuple(range(8)))


@pytest.mark.parametrize("pair_index", range(6))
def test_every_identity_pair_has_a_three_object_countermodel_if_omitted(original, pair_index):
    request = deepcopy(original)
    equalities = selected(request, "equality")
    left, right = [argument["symbol"] for argument in equalities[pair_index]["arguments"]]
    environment = {"event": "e", "time": "t"}
    environment[left] = environment[right] = 0
    remaining = sorted(set(("x0", "x1", "x2", "x3")) - {left, right})
    environment.update({remaining[0]: 1, remaining[1]: 2})
    members = {(item, "e", "t") for item in range(3)}
    domains = {"Object": (0, 1, 2), "EventFrame": ("e",), "TimeFrame": ("t",)}
    assert finite(matrix(request), members, domains, environment)
    another = equalities[(pair_index + 1) % 6]
    for argument, replacement in zip(equalities[pair_index]["arguments"], another["arguments"], strict=True):
        argument["symbol"] = replacement["symbol"]
    assert not finite(matrix(request), members, domains, environment)
    with pytest.raises(ValueError, match="fixed counted-frame expansion"):
        prepare(reseal(request))


@pytest.mark.parametrize("kind", ["header", "frame", "membership", "expression", "signature", "node", "sort", "binder"])
def test_offered_unknown_paths_fail_before_operation_owner_load(original, monkeypatch, kind):
    request = deepcopy(original)
    targets = {"header": request, "frame": request["frame"], "membership": request["membership"],
        "expression": request["expression"], "signature": request["expression"]["signature"],
        "node": request["expression"]["root"], "sort": request["expression"]["root"]["sort"],
        "binder": request["expression"]["root"]["binders"][0]}
    targets[kind]["offered_path"] = "/must/not/be/read/private-review.json"
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("operation owner loaded before closed request rejection"))
    with pytest.raises(ValueError, match="closed exact fields|unsupported or altered"):
        prepare(request)


@pytest.mark.parametrize("key", ["schema", "interpretation_status", "maximum", "distinctness",
    "frame", "membership", "object_variables", "source_binding", "expression"])
def test_no_missing_request_field_gets_a_silent_default(original, monkeypatch, key):
    request = deepcopy(original)
    del request[key]
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for missing request field"))
    with pytest.raises(ValueError, match="closed exact fields"):
        prepare(request)


@pytest.mark.parametrize("maximum", [True, False, 0, 2, 4, "3", None, 3.0])
def test_only_exact_integer_three_is_admitted(original, monkeypatch, maximum):
    request = deepcopy(original)
    request["maximum"] = maximum
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for unsupported maximum"))
    with pytest.raises(ValueError):
        prepare(request)


@pytest.mark.parametrize("field,value", [
    ("interpretation_status", "reviewed"), ("distinctness", "occurrence_multiplicity"),
    ("source_binding", {"path": "/must/not/be/read/source.json"}),
    ("object_variables", ["x0", "x1", "x2"]),
    ("membership", {"symbol": "Eq", "argument_roles": ["object", "event", "time"]}),
    ("membership", {"symbol": "Member", "argument_roles": ["event", "object", "time"]}),
])
def test_altered_declarations_fail_before_owner_load(original, monkeypatch, field, value):
    request = deepcopy(original)
    request[field] = value
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for unsupported declaration"))
    with pytest.raises(ValueError, match="unsupported or altered"):
        prepare(request)


@pytest.mark.parametrize("target,key,value", [
    ("frame", "policy", "global_lifetime"), ("time", "semantics", "calendar_order"),
    ("time", "sort", "Object"), ("event", "variable", "other_event"),
])
def test_frame_aggregation_or_order_is_not_silently_selected(original, monkeypatch, target, key, value):
    request = deepcopy(original)
    row = request["frame"] if target == "frame" else request["frame"][target]
    row[key] = value
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for undeclared frame semantics"))
    with pytest.raises(ValueError, match="unsupported or altered"):
        prepare(request)


@pytest.mark.parametrize("where,key", [
    ("expression", "metadata"), ("expression", "interface"), ("expression", "schema_version"),
    ("signature", "metadata"), ("signature", "features"), ("signature", "interface"),
    ("root", "metadata"), ("root", "schema_version"), ("root", "sort"), ("root", "arguments"),
])
def test_serialized_expression_defaults_are_not_accepted(original, where, key):
    request = deepcopy(original)
    row = request["expression"] if where == "expression" else request["expression"][where]
    del row[key]
    with pytest.raises(ValueError, match="closed exact fields"):
        prepare(request)


@pytest.mark.parametrize("mutation", ["range", "metadata", "extension", "duplicate_ids", "too_many_nodes"])
def test_unsupported_annotations_and_physical_shape_fail_before_owner_load(original, monkeypatch, mutation):
    request = deepcopy(original)
    root = request["expression"]["root"]
    if mutation == "range":
        root["range"] = {"path": "/must/not/be/read/source"}
    elif mutation == "metadata":
        root["metadata"] = {"reviewed": True}
    elif mutation == "extension":
        root["extension"] = {"payload": "O(Member)"}
    elif mutation == "duplicate_ids":
        root["arguments"][0]["node_id"] = root["node_id"]
    else:
        root["arguments"].append(deepcopy(root["arguments"][0]))
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for unsupported physical shape"))
    with pytest.raises(ValueError):
        prepare(request)


@pytest.mark.parametrize("mutation", ["member_order", "reverse_equality", "scope_direction", "unbound", "shadowing",
                                     "wrong_sort", "profile", "identity_version", "signature_features"])
def test_typed_or_logical_mutations_do_not_become_the_fixed_profile(original, mutation):
    request = deepcopy(original)
    if mutation == "member_order":
        atom = selected(request, "predicate")[0]
        atom["arguments"][0]["symbol"] = "x1"
    elif mutation == "reverse_equality":
        equality = selected(request, "equality")[0]
        equality["arguments"].reverse()
    elif mutation == "scope_direction":
        matrix(request)["arguments"].reverse()
    elif mutation == "unbound":
        selected(request, "variable")[0]["symbol"] = "outside"
    elif mutation == "shadowing":
        selected(request, "forall")[1]["binders"][0]["name"] = "event"
    elif mutation == "wrong_sort":
        selected(request, "equality")[0]["arguments"][0]["sort"] = deepcopy(
            next(sort for sort in request["expression"]["signature"]["sorts"]
                 if sort["name"] == "EventFrame"))
    elif mutation == "profile":
        request["expression"]["profile"]["value"] = "classical"
        request["expression"]["signature"]["profile"]["value"] = "classical"
    elif mutation == "identity_version":
        request["expression"]["family"]["version"] = "2.0.0"
    else:
        request["expression"]["signature"]["features"] = ["first_order"]
    with pytest.raises(ValueError):
        prepare(reseal(request))


@pytest.mark.parametrize("raw", [b"", b"{", b"[]", b'{"x":1,"x":2}', b'{"x":NaN}',
    b'{"x":Infinity}', b'{"x":1.5}', b'{"x":"\xff"}', b'{"x":"\\ud800"}',
    b" " * (counted.MAX_REQUEST_BYTES + 1)])
def test_invalid_bounded_json_fails_before_owner_load(monkeypatch, raw):
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for invalid bytes"))
    with pytest.raises(ValueError):
        counted.prepare_counted_frame(raw, expected_request_sha256=sha(raw))


def test_nested_duplicate_and_nonordinary_objects_are_rejected(original, monkeypatch):
    raw = wire(original).replace(b'"maximum":3', b'"maximum":3,"maximum":3')
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for duplicate declaration"))
    with pytest.raises(ValueError, match="duplicate-free"):
        counted.prepare_counted_frame(raw, expected_request_sha256=sha(raw))
    with pytest.raises(ValueError):
        counted.prepare_counted_frame(bytearray(wire(original)), expected_request_sha256=sha(wire(original)))
    with pytest.raises(ValueError):
        counted.counted_frame_report_sha256({"ordinary": (1, 2)})


@pytest.mark.parametrize("digest", [None, "0" * 64, "A" * 64, True, 1])
def test_independent_request_hash_is_required_before_owner_load(original, monkeypatch, digest):
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for incorrect request hash"))
    with pytest.raises(ValueError):
        counted.prepare_counted_frame(wire(original), expected_request_sha256=digest)


@pytest.mark.parametrize("field,value", [
    ("maximum", 4), ("native_build_executed", True), ("training_mask", 1),
    ("canonical_fol", "Member(x0,event,time)"), ("lean_body", "axiom accepted : True"),
    ("source_binding", {"path": "/must/not/be/read/source"}),
])
def test_rehashed_report_mutation_fails_complete_authoritative_replay(original, field, value):
    report = prepare(original)
    report[field] = value
    raw = wire(original)
    with pytest.raises(ValueError, match="complete authoritative replay"):
        counted.validate_counted_frame(report, raw, expected_request_sha256=sha(raw),
            expected_report_sha256=counted.counted_frame_report_sha256(report))


def test_untrusted_offered_report_paths_are_never_opened(original, monkeypatch):
    report = prepare(original)
    offered = "/must/not/be/read/checkpoint-or-private-review.json"
    report["producer_pins"][offered] = "0" * 64
    real_read = Path.read_bytes
    opened = []

    def guarded_read(path):
        opened.append(str(path))
        assert str(path) != offered
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    raw = wire(original)
    with pytest.raises(ValueError, match="complete authoritative replay"):
        counted.validate_counted_frame(report, raw, expected_request_sha256=sha(raw),
            expected_report_sha256=counted.counted_frame_report_sha256(report))
    assert offered not in opened


def test_owner_file_freshness_is_checked_before_preparation(original, monkeypatch):
    report = prepare(original)
    owner = next(path for path in report["producer_pins"] if path.endswith("/parsers/fol.py"))
    real_read = Path.read_bytes

    def changed(path):
        value = real_read(path)
        return value + b"\nchanged" if str(path.resolve()) == owner else value

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="operation owner changed"):
        prepare(original)


def test_owner_file_freshness_is_checked_after_preparation(original, monkeypatch):
    report = prepare(original)
    owner = next(path for path in report["producer_pins"] if path.endswith("/parsers/fol.py"))
    real_read, real_lean = Path.read_bytes, counted._lean_body
    changed_after_lowering = False

    def changed(path):
        value = real_read(path)
        return value + b"\nchanged" if changed_after_lowering and str(path.resolve()) == owner else value

    def lean():
        nonlocal changed_after_lowering
        result = real_lean()
        changed_after_lowering = True
        return result

    monkeypatch.setattr(Path, "read_bytes", changed)
    monkeypatch.setattr(counted, "_lean_body", lean)
    with pytest.raises(ValueError, match="operation owner changed"):
        prepare(original)


def test_producer_self_pin_is_not_supplied_by_the_request(original, monkeypatch):
    monkeypatch.setattr(counted, "_SELF_PIN", "0" * 64)
    with pytest.raises(ValueError, match="producer changed since import"):
        prepare(original)


def test_original_to_parsed_alpha_check_is_required(original, monkeypatch):
    from ipfs_datasets_py.logic.syntax_core import algebra

    monkeypatch.setattr(algebra, "alpha_equivalent", lambda *_: False)
    with pytest.raises(ValueError, match="original typed tree differs"):
        prepare(original)


def test_native_processes_are_not_part_of_prepare_or_replay(original, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("native process launched"))
    report = prepare(original)
    raw = wire(original)
    assert counted.validate_counted_frame(report, raw, expected_request_sha256=sha(raw),
        expected_report_sha256=counted.counted_frame_report_sha256(report)) == report


def test_finite_fixture_axis_renaming_does_not_assert_time_order(original):
    rows = [(0, "a", "later"), (1, "a", "later"), (2, "a", "later"), (3, "a", "earlier")]
    renamed = [(item, event, {"later": "z", "earlier": "a"}[time]) for item, event, time in rows]
    assert truth(original, rows, events=("a",), times=("later", "earlier"))
    assert truth(original, renamed, events=("a",), times=("a", "z"))


def test_all_declared_small_membership_sets_match_distinct_count_definition(original):
    # Exhaustive authored finite control, not a theorem about arbitrary carriers.
    universe = tuple(itertools.product(range(4), ("e",), ("t",)))
    for mask in range(1 << len(universe)):
        rows = [row for index, row in enumerate(universe) if mask & (1 << index)]
        assert truth(original, rows) is (len({row[0] for row in rows}) <= 3)


# The following controls qualify a new serialization profile, independently of
# the retained model, original native build and statutory-meaning evidence.
@pytest.fixture(scope="module")
def compact_projection(original):
    raw = wire(original)
    return counted.project_counted_frame_request_v1(raw, expected_request_sha256=sha(raw))


@pytest.fixture(scope="module")
def compact_codec():
    return counted.build_counted_frame_token_codec_v1()


def _compact_parts(projection):
    return tuple(wire(projection[key]) for key in ("content", "context", "identity_sidecar"))


def _compact_decode(projection):
    content_raw, context_raw, _ = _compact_parts(projection)
    return counted.decode_counted_frame_content_v1(content_raw, context_raw,
        expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw))


def _compact_restore(projection, original_raw):
    content_raw, context_raw, identity_raw = _compact_parts(projection)
    return counted.reconstruct_counted_frame_request_v1(
        content_raw, context_raw, identity_raw, original_raw,
        expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw),
        expected_identity_sha256=sha(identity_raw), expected_original_request_sha256=sha(original_raw))


def _compact_encode(projection, codec):
    content_raw, context_raw, _ = _compact_parts(projection)
    return counted.encode_counted_frame_tokens_v1(content_raw, context_raw,
        expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw),
        codec=codec, expected_codec_sha256=counted.counted_frame_token_codec_sha256(codec))


def _compact_tokens_decode(ids, projection, codec):
    context_raw = wire(projection["context"])
    return counted.decode_counted_frame_tokens_v1(ids, context_raw,
        expected_context_sha256=sha(context_raw), codec=codec,
        expected_codec_sha256=counted.counted_frame_token_codec_sha256(codec))


def _compact_assert_no_authority(report):
    assert report["authority"] and all(type(flag) is bool and flag is False
                                       for flag in report["authority"].values())
    for key in ("training_mask", "evaluation_gold_mask"):
        assert type(report[key]) is int and report[key] == 0


def test_compact_projection_and_validation_replay_genuine_complete_requests(
        original, compact_projection, monkeypatch):
    actual, replayed = counted.prepare_counted_frame, []

    def observed(raw, **kwargs):
        result = actual(raw, **kwargs)
        replayed.append(deepcopy(result))
        return result

    monkeypatch.setattr(counted, "prepare_counted_frame", observed)
    raw = wire(original)
    projection = counted.project_counted_frame_request_v1(raw, expected_request_sha256=sha(raw))
    assert projection == compact_projection
    assert replayed and replayed[0]["request"] == original
    assert len(replayed) >= 2, "original and decoded requests both require the public counted owner"
    assert counted.validate_counted_frame_projection_v1(projection, raw,
        expected_report_sha256=counted.counted_frame_report_sha256(projection),
        expected_request_sha256=sha(raw)) == projection
    assert projection["counts"] == {"nodes": 49, "quantifiers": 6,
        "membership_occurrences": 4, "equality_occurrences": 6, "variable_occurrences": 24}
    for key, pin in (("content", "content_sha256"), ("context", "context_sha256"),
                     ("identity_sidecar", "identity_sha256")):
        assert sha(wire(projection[key])) == projection[pin]
    _compact_assert_no_authority(projection)


def test_compact_identity_sidecar_restores_all_arbitrary_physical_ids(original):
    request = deepcopy(original)
    request["expression"]["expression_id"] = "independent:counted:expression:ascii_omega"
    request["expression"]["signature"]["signature_id"] = "independent:counted:signature:ascii_omega"
    for index, node in enumerate(nodes(request["expression"]["root"])):
        node["node_id"] = "independent:counted:physical:ascii_omega:" + str(index)
    request = reseal(request)
    raw = wire(request)
    projection = counted.project_counted_frame_request_v1(raw, expected_request_sha256=sha(raw))
    restored = _compact_restore(projection, raw)
    assert restored["identity_mode"] == "restored"
    assert restored["request"] == request
    assert restored["request_sha256"] == sha(wire(request))
    assert restored["original_request_sha256"] == sha(raw)
    assert [row["node_id"] for row in nodes(restored["request"]["expression"]["root"])] == [
        row["node_id"] for row in nodes(request["expression"]["root"])]
    _compact_assert_no_authority(restored)


def test_compact_same_content_is_independent_of_expression_signature_and_node_ids(
        original, compact_projection):
    request = deepcopy(original)
    request["expression"]["expression_id"] = "independent:different-expression"
    request["expression"]["signature"]["signature_id"] = "independent:different-signature"
    for index, node in enumerate(nodes(request["expression"]["root"])):
        node["node_id"] = "independent:different-node:" + str(index)
    raw = wire(reseal(request))
    other = counted.project_counted_frame_request_v1(raw, expected_request_sha256=sha(raw))
    assert other["content"] == compact_projection["content"]
    assert other["context"] == compact_projection["context"]
    assert other["content_sha256"] == compact_projection["content_sha256"]
    assert other["identity_sidecar"] != compact_projection["identity_sidecar"]
    assert other["original_expression_sha256"] != compact_projection["original_expression_sha256"]
    predicted = _compact_decode(other)
    assert predicted["identity_mode"] == "generated"
    assert predicted["request"] != request
    assert predicted["counts"] == compact_projection["counts"]
    _compact_assert_no_authority(predicted)


def test_compact_exact_recovery_is_canonical_and_retains_separate_raw_transport_pin(original):
    raw = json.dumps(original, indent=2, ensure_ascii=True).encode("utf-8")
    assert raw != wire(original)
    projection = counted.project_counted_frame_request_v1(raw, expected_request_sha256=sha(raw))
    restored = _compact_restore(projection, raw)
    assert restored["request"] == original
    assert restored["request_sha256"] == sha(wire(original))
    assert projection["original_request_sha256"] == sha(raw)
    assert projection["original_request_canonical_sha256"] == sha(wire(original))
    assert restored["original_request_sha256"] != restored["request_sha256"]
    content_raw = json.dumps(projection["content"], indent=2).encode()
    context_raw = json.dumps(projection["context"], indent=2).encode()
    identity_raw = json.dumps(projection["identity_sidecar"], indent=2).encode()
    prediction = counted.decode_counted_frame_content_v1(content_raw, context_raw,
        expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw))
    assert prediction["content_sha256"] == projection["content_sha256"]
    assert prediction["context_sha256"] == projection["context_sha256"]
    assert prediction["content_raw_sha256"] == sha(content_raw) != projection["content_sha256"]
    assert prediction["context_raw_sha256"] == sha(context_raw) != projection["context_sha256"]
    restored_pretty = counted.reconstruct_counted_frame_request_v1(
        content_raw, context_raw, identity_raw, raw,
        expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw),
        expected_identity_sha256=sha(identity_raw), expected_original_request_sha256=sha(raw))
    assert restored_pretty["request"] == original
    assert restored_pretty["identity_sha256"] == projection["identity_sha256"]
    assert restored_pretty["identity_raw_sha256"] == sha(identity_raw) != projection["identity_sha256"]


def test_compact_prediction_accepts_no_identity_sidecar_or_original_reference(compact_projection):
    content_raw, context_raw, identity_raw = _compact_parts(compact_projection)
    args = dict(expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw))
    with pytest.raises(TypeError):
        counted.decode_counted_frame_content_v1(content_raw, context_raw, identity_raw=identity_raw, **args)
    with pytest.raises(TypeError):
        counted.decode_counted_frame_content_v1(content_raw, context_raw,
            original_request_raw=b"reference must not be a prediction input", **args)
    prediction = counted.decode_counted_frame_content_v1(content_raw, context_raw, **args)
    assert prediction["counted_report"]["request"] == prediction["request"]
    assert prediction["counted_report"]["counts"] == prediction["counts"]
    _compact_assert_no_authority(prediction)


@pytest.mark.parametrize("part", ["content", "context", "identity_sidecar", "counts", "authority", "producer_pins"])
def test_compact_resealed_projection_cannot_replace_original_public_regeneration(
        original, compact_projection, part):
    offered = deepcopy(compact_projection)
    if part == "counts": offered[part]["nodes"] -= 1
    elif part == "authority": offered[part][next(iter(offered[part]))] = True
    elif part == "producer_pins": offered[part] = {}
    else: offered[part]["unsupported_projection_field"] = "must not be authenticated by resealing"
    raw = wire(original)
    with pytest.raises(ValueError):
        counted.validate_counted_frame_projection_v1(offered, raw,
            expected_report_sha256=counted.counted_frame_report_sha256(offered),
            expected_request_sha256=sha(raw))


@pytest.mark.parametrize("part", ["request", "content", "context", "identity", "original", "codec", "projection"])
def test_compact_independent_input_pins_fail_before_operation_owner_discovery(
        original, compact_projection, compact_codec, monkeypatch, part):
    raw = wire(original)
    content_raw, context_raw, identity_raw = _compact_parts(compact_projection)
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("operation owner loaded for wrong independent pin"))
    with pytest.raises(ValueError):
        if part == "request":
            counted.project_counted_frame_request_v1(raw, expected_request_sha256="0" * 64)
        elif part in {"content", "context"}:
            counted.decode_counted_frame_content_v1(content_raw, context_raw,
                expected_content_sha256="0" * 64 if part == "content" else sha(content_raw),
                expected_context_sha256="0" * 64 if part == "context" else sha(context_raw))
        elif part in {"identity", "original"}:
            counted.reconstruct_counted_frame_request_v1(content_raw, context_raw, identity_raw, raw,
                expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw),
                expected_identity_sha256="0" * 64 if part == "identity" else sha(identity_raw),
                expected_original_request_sha256="0" * 64 if part == "original" else sha(raw))
        elif part == "codec":
            counted.encode_counted_frame_tokens_v1(content_raw, context_raw,
                expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw),
                codec=compact_codec, expected_codec_sha256="0" * 64)
        else:
            counted.validate_counted_frame_projection_v1(compact_projection, raw,
                expected_report_sha256="0" * 64, expected_request_sha256=sha(raw))


@pytest.mark.parametrize("damage", ["maximum_bool", "maximum_four", "roles", "sorts", "frame", "distinctness", "predicate_domain"])
def test_compact_context_changes_are_not_silently_repaired_or_defaulted(
        compact_projection, monkeypatch, damage):
    context = deepcopy(compact_projection["context"])
    if damage == "maximum_bool": context["maximum"] = True
    elif damage == "maximum_four": context["maximum"] = 4
    elif damage == "roles": context["membership"]["argument_roles"].reverse()
    elif damage == "sorts": context["sorts"].reverse()
    elif damage == "frame": context["frame"]["policy"] = "unreviewed_global_lifetime"
    elif damage == "distinctness": context["distinctness"] = "occurrence_multiplicity"
    else: context["predicate"]["domain"].reverse()
    content_raw, context_raw = wire(compact_projection["content"]), wire(context)
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("operation owner loaded for altered counted context"))
    with pytest.raises(ValueError):
        counted.decode_counted_frame_content_v1(content_raw, context_raw,
            expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw))


@pytest.mark.parametrize("raw", [b"", b"{", b"[]", b'{"schema":1,"schema":2}',
    b'{"schema":NaN}', b'{"schema":"\\ud800"}'])
def test_compact_malformed_content_is_refused_before_operation_owner_load(
        compact_projection, monkeypatch, raw):
    context_raw = wire(compact_projection["context"])
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for malformed compact content"))
    with pytest.raises(ValueError):
        counted.decode_counted_frame_content_v1(raw, context_raw,
            expected_content_sha256=sha(raw), expected_context_sha256=sha(context_raw))


def test_compact_fixed_lexical_codec_roundtrip_retains_full_many_sorted_counted_tree(
        compact_projection, compact_codec, monkeypatch):
    before = deepcopy(compact_codec)
    with monkeypatch.context() as patch:
        patch.setattr(counted, "_owners", lambda: pytest.fail("fixed codec construction or hashing imported operation owners"))
        assert counted.build_counted_frame_token_codec_v1() == compact_codec
        assert counted.counted_frame_token_codec_sha256(compact_codec) == sha(wire(compact_codec))
        patch.setattr(counted, "_SELF_PIN", "0" * 64)
        with pytest.raises(ValueError):
            counted.build_counted_frame_token_codec_v1()
    encoded = _compact_encode(compact_projection, compact_codec)
    ids = encoded["target_ids"]
    assert ids[0] == 1 and ids[-1] == 2
    assert all(type(item) is int and item >= 3 for item in ids[1:-1])
    assert len(ids) == encoded["total_token_count"] <= 512
    assert encoded["lexical_token_count"] == len(encoded["lexical_tokens"]) == len(ids) - 2
    decoded = _compact_tokens_decode(ids, compact_projection, compact_codec)
    assert decoded["status"] == "valid_candidate"
    assert decoded["generated_ids"] == ids
    assert decoded["prediction"]["identity_mode"] == "generated"
    assert decoded["counts"] == compact_projection["counts"]
    assert decoded["canonical_content_raw_utf8"].encode() == wire(compact_projection["content"])
    assert decoded["content_sha256"] == compact_projection["content_sha256"]
    assert decoded["framing"] == {"bos_present": True, "eos_terminal": True,
        "token_ids_valid": True, "interior_special_tokens": False, "terminated": True}
    malformed = ids[:2] + ids[3:]
    assert malformed[0] == 1 and malformed[-1] == 2
    with monkeypatch.context() as patch:
        patch.setattr(counted, "_owners", lambda: pytest.fail("malformed lexical content reached operation owners"))
        with pytest.raises(ValueError):
            _compact_tokens_decode(malformed, compact_projection, compact_codec)
    assert compact_codec == before
    _compact_assert_no_authority(encoded)
    _compact_assert_no_authority(decoded)


@pytest.mark.parametrize("damage", ["missing_bos", "missing_eos", "pad", "interior_bos", "interior_eos", "after_eos", "bool", "out_of_range", "empty", "over_budget"])
def test_compact_generated_lexical_tokens_require_exact_complete_framing(
        compact_projection, compact_codec, damage):
    ids = list(_compact_encode(compact_projection, compact_codec)["target_ids"])
    if damage == "missing_bos": ids = ids[1:]
    elif damage == "missing_eos": ids = ids[:-1]
    elif damage == "pad": ids.insert(2, 0)
    elif damage == "interior_bos": ids.insert(2, 1)
    elif damage == "interior_eos": ids.insert(2, 2)
    elif damage == "after_eos": ids.append(ids[1])
    elif damage == "bool": ids[2] = True
    elif damage == "out_of_range": ids[2] = 1_000_000
    elif damage == "empty": ids = []
    else: ids = [1] + [ids[1]] * 511 + [2]
    with pytest.raises(ValueError):
        _compact_tokens_decode(ids, compact_projection, compact_codec)


def test_compact_wrong_legacy_codec_cannot_be_rehashed_as_counted_codec(
        compact_projection, compact_codec, monkeypatch):
    codec = deepcopy(compact_codec)
    codec["schema"] = "legal-compact-content-token-codec/v1"
    content_raw, context_raw, _ = _compact_parts(compact_projection)
    pin = sha(wire(codec))
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded for wrong fixed codec profile"))
    with pytest.raises(ValueError):
        counted.encode_counted_frame_tokens_v1(content_raw, context_raw,
            expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw),
            codec=codec, expected_codec_sha256=pin)


def _compact_independent_tree(node, bound=()):
    """Serialize the original AST independently of the projection's helpers."""
    kind = node["kind"]
    if kind == "forall":
        binder = node["binders"][0]
        return [kind, len(bound), binder["sort"]["name"],
                _compact_independent_tree(node["arguments"][0], bound + (binder["name"],))]
    if kind == "variable":
        return [kind, bound.index(node["symbol"])]
    if kind == "predicate":
        assert node["symbol"] == "Member"
        return [kind, 0, [_compact_independent_tree(child, bound) for child in node["arguments"]]]
    assert kind in {"equality", "and", "or", "implies"}
    assert len(node["arguments"]) == 2
    return [kind, *[_compact_independent_tree(child, bound) for child in node["arguments"]]]


def _compact_tagged_nodes(value):
    if type(value) is list:
        if value and type(value[0]) is str and value[0] in {
                "forall", "variable", "predicate", "equality", "and", "or", "implies"}:
            yield value
        for child in value:
            yield from _compact_tagged_nodes(child)


def test_compact_projection_preserves_independently_derived_ordered_tree_and_context(
        original, compact_projection):
    content = compact_projection["content"]
    assert set(content) == {"schema", "tree"}
    assert content["tree"] == _compact_independent_tree(original["expression"]["root"])
    tree_nodes = list(_compact_tagged_nodes(content["tree"]))
    assert len(tree_nodes) == 49
    assert [(row[1], row[2]) for row in tree_nodes if row[0] == "forall"] == [
        (0, "EventFrame"), (1, "TimeFrame"), (2, "Object"),
        (3, "Object"), (4, "Object"), (5, "Object")]
    assert [[row[1][1], row[2][1]] for row in tree_nodes if row[0] == "equality"] == [
        [2, 3], [2, 4], [2, 5], [3, 4], [3, 5], [4, 5]]
    assert [[term[1] for term in row[2]] for row in tree_nodes if row[0] == "predicate"] == [
        [2, 0, 1], [3, 0, 1], [4, 0, 1], [5, 0, 1]]
    context = compact_projection["context"]
    assert context["sorts"] == ["Object", "EventFrame", "TimeFrame"]
    assert context["predicate"] == {"name": "Member", "domain": ["Object", "EventFrame", "TimeFrame"], "range": "Bool"}
    for key in ("frame", "membership", "distinctness", "maximum", "object_variables"):
        assert context[key] == original[key]


@pytest.mark.parametrize("damage", ["reversed_equality", "swapped_member_roles", "binder_sort", "binder_bool", "unbound", "predicate_index", "missing_node"])
def test_compact_resealed_tree_mutations_cannot_change_counting_or_binding_meaning(
        compact_projection, damage):
    content = deepcopy(compact_projection["content"])
    rows = list(_compact_tagged_nodes(content["tree"]))
    if damage == "reversed_equality":
        row = next(row for row in rows if row[0] == "equality")
        row[1], row[2] = row[2], row[1]
    elif damage == "swapped_member_roles":
        row = next(row for row in rows if row[0] == "predicate")
        row[2][0], row[2][1] = row[2][1], row[2][0]
    elif damage == "binder_sort": next(row for row in rows if row[0] == "forall")[2] = "Object"
    elif damage == "binder_bool": next(row for row in rows if row[0] == "forall")[1] = False
    elif damage == "unbound": next(row for row in rows if row[0] == "variable")[1] = 6
    elif damage == "predicate_index": next(row for row in rows if row[0] == "predicate")[1] = 1
    else: content["tree"].pop()
    content_raw, context_raw = wire(content), wire(compact_projection["context"])
    with pytest.raises(ValueError):
        counted.decode_counted_frame_content_v1(content_raw, context_raw,
            expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw))


@pytest.mark.parametrize("damage", ["duplicate_node_id", "missing_node_id", "foreign_original_pin"])
def test_compact_resealed_identity_sidecar_requires_complete_exact_original_identity(
        original, compact_projection, damage):
    identity = deepcopy(compact_projection["identity_sidecar"])
    if damage == "duplicate_node_id": identity["node_ids"][1] = identity["node_ids"][0]
    elif damage == "missing_node_id": identity["node_ids"].pop()
    else: identity["original_request_sha256"] = "0" * 64
    content_raw, context_raw, identity_raw = wire(compact_projection["content"]), wire(compact_projection["context"]), wire(identity)
    raw = wire(original)
    with pytest.raises(ValueError):
        counted.reconstruct_counted_frame_request_v1(content_raw, context_raw, identity_raw, raw,
            expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw),
            expected_identity_sha256=sha(identity_raw), expected_original_request_sha256=sha(raw))


@pytest.mark.parametrize("boundary", ["public_replay", "final_wire"])
def test_compact_producer_fences_cover_public_replay_and_final_serialization(
        original, compact_projection, monkeypatch, boundary):
    source_path = next(path for path in compact_projection["producer_pins"] if path.endswith("/parsers/fol.py"))
    actual_read, actual_prepare = Path.read_bytes, counted.prepare_counted_frame
    actual_wire = counted._compact_wire
    changed = False

    def read(path):
        raw = actual_read(path)
        return raw + b"\n# Authored post-boundary change\n" if changed and str(path.resolve()) == source_path else raw

    def replay(*args, **kwargs):
        nonlocal changed
        result = actual_prepare(*args, **kwargs)
        if boundary == "public_replay": changed = True
        return result

    def serialize(value, *args, **kwargs):
        nonlocal changed
        result = actual_wire(value, *args, **kwargs)
        if boundary == "final_wire" and type(value) is dict and value.get("schema") == "legal-counted-compact-projection/v1":
            changed = True
        return result

    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr(counted, "prepare_counted_frame", replay)
    monkeypatch.setattr(counted, "_compact_wire", serialize)
    raw = wire(original)
    with pytest.raises(ValueError):
        counted.project_counted_frame_request_v1(raw, expected_request_sha256=sha(raw))


@pytest.mark.parametrize("target", ["generated_ids", "codec"])
def test_compact_mutable_prediction_inputs_are_fenced_around_genuine_replay(
        compact_projection, compact_codec, monkeypatch, target):
    ids = list(_compact_encode(compact_projection, compact_codec)["target_ids"])
    codec = deepcopy(compact_codec)
    actual = counted.prepare_counted_frame

    def replay(*args, **kwargs):
        result = actual(*args, **kwargs)
        if target == "generated_ids": ids.append(2)
        else: codec["mutation_after_replay"] = True
        return result

    monkeypatch.setattr(counted, "prepare_counted_frame", replay)
    with pytest.raises(ValueError):
        _compact_tokens_decode(ids, compact_projection, codec)


def test_compact_projection_validator_fences_offered_report_during_regeneration(
        original, compact_projection, monkeypatch):
    offered = deepcopy(compact_projection)
    actual = counted.project_counted_frame_request_v1

    def regenerate(*args, **kwargs):
        result = actual(*args, **kwargs)
        offered["counts"]["nodes"] -= 1
        return result

    monkeypatch.setattr(counted, "project_counted_frame_request_v1", regenerate)
    raw = wire(original)
    pin = counted.counted_frame_report_sha256(offered)
    with pytest.raises(ValueError):
        counted.validate_counted_frame_projection_v1(offered, raw,
            expected_report_sha256=pin, expected_request_sha256=sha(raw))


def test_compact_lowered_content_bound_refuses_complete_input_without_truncation(
        compact_projection, monkeypatch):
    content_raw, context_raw, _ = _compact_parts(compact_projection)
    monkeypatch.setattr(counted, "MAX_REQUEST_BYTES", len(content_raw) - 1)
    monkeypatch.setattr(counted, "_owners", lambda: pytest.fail("owner loaded beyond lowered content bound"))
    with pytest.raises(ValueError):
        counted.decode_counted_frame_content_v1(content_raw, context_raw,
            expected_content_sha256=sha(content_raw), expected_context_sha256=sha(context_raw))


# Pointwise relation-to-count transport is a caller-authored conditional theorem.
from ipfs_datasets_py.logic.autoformal import legal_counted_relation_binding_v1 as binding

# These fixtures do not interpret a statute or assert its inclusion premise.
@pytest.fixture(scope="module")
def relation_binding_request():
    return binding.authored_counted_relation_binding_request_v1()


def _relation_binding_prepare(request):
    raw = wire(request)
    return binding.prepare_counted_relation_binding_v1(
        raw, expected_request_sha256=sha(raw))


def _relation_binding_parts(request):
    root = request["expression"]["root"]
    for expected in ("actor", "event", "time"):
        assert root["kind"] == "forall"
        assert root["binders"][0]["name"] == expected
        root = root["arguments"][0]
    assert root["kind"] == "implies"
    premises, conclusion = root["arguments"]
    assert premises["kind"] == "and"
    cap_member, bridge = premises["arguments"]
    assert bridge["kind"] == "forall"
    assert bridge["binders"][0]["name"] == "object"
    return cap_member, bridge, conclusion


def _relation_binding_domains(*, objects=(0, 1, 2, 3), events=("e0",), times=("t0",)):
    return {"Object": objects, "EventFrame": events, "TimeFrame": times}


def _relation_binding_table(member_objects, detail_objects, *, actor=0, event="e0", time="t0"):
    return {"Member": {(item, event, time) for item in member_objects},
            "Detail": {(actor, item, event, time) for item in detail_objects}}


def test_relation_binding_public_replay_preserves_114_nodes_12_binders_and_cap_lineage(
        original, relation_binding_request):
    request = deepcopy(relation_binding_request)
    before = deepcopy(request)
    raw = wire(request)
    report = _relation_binding_prepare(request)
    replay = binding.validate_counted_relation_binding_v1(
        report, raw, expected_request_sha256=sha(raw),
        expected_report_sha256=binding.counted_relation_binding_report_sha256(report))
    assert replay == report and request == before
    assert report["schema"] == "legal-counted-relation-binding-report/v1"
    assert report["profile"] == "explicit-pointwise-actor-frame-subrelation-cap3/v1"
    assert report["request"] == request and report["request_raw_utf8"].encode() == raw
    assert report["request_sha256"] == sha(raw)
    assert report["typed_expression"] == request["expression"]
    physical = list(nodes(request["expression"]["root"]))
    assert len(physical) == 114 and len({row["node_id"] for row in physical}) == 114
    assert sum(row["kind"] == "forall" for row in physical) == 12
    assert sum(row["kind"] == "equality" for row in physical) == 12
    assert sum(row["kind"] == "predicate" for row in physical) == 10
    assert sum(row["kind"] == "variable" for row in physical) == 59
    assert report["counts"] == {"nodes": 114, "quantifiers": 12,
        "predicate_occurrences": 10, "equality_occurrences": 12,
        "variable_occurrences": 59, "binder_rows": 12}
    assert len(report["binder_ledger"]) == 12
    cap_member, bridge, cap_detail = _relation_binding_parts(request)
    original_root = original["expression"]["root"]
    original_core = original_root["arguments"][0]["arguments"][0]
    assert len(list(nodes(original_root))) == 49
    assert len(list(nodes(cap_member))) == 47 and cap_member == original_core
    assert len(list(nodes(cap_detail))) == 51
    assert json.loads(request["counted_request_raw_utf8"]) == original
    assert report["original_counted_report"]["typed_expression"] == original["expression"]
    lineage = report["cap_lineage"]
    assert lineage["original_nodes"] == 49 and lineage["retained_core_nodes"] == 47
    assert lineage["original_root_sha256"] == sha(wire(original_root))
    assert lineage["retained_core_sha256"] == sha(wire(original_core))
    assert lineage["source_core_original_typed_path"] == "/root/arguments/0/arguments/0"
    assert lineage["frame_variable_renamings"] == []
    assert request["scope"]["modal_transport"] == "none"
    assert report["source_binding"] is None and not report["source_bound"]
    assert not report["native_build_executed"] and not any(report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0


def test_relation_binding_empty_member_exposes_old_loophole_without_asserting_the_premise(
        original, relation_binding_request):
    cap_member, bridge, cap_detail = _relation_binding_parts(relation_binding_request)
    domains = _relation_binding_domains()
    env = {"actor": 0, "event": "e0", "time": "t0"}
    table = _relation_binding_table((), (0, 1, 2, 3))
    assert finite(original["expression"]["root"], set(), domains) is True
    assert finite(cap_member, table, domains, env) is True
    assert finite(cap_detail, table, domains, env) is False
    assert finite(bridge, table, domains, env) is False
    # The new expression is conditional: this model violates its inclusion premise.
    assert finite(relation_binding_request["expression"]["root"], table, domains) is True


def test_relation_binding_nonempty_three_and_four_separate_premises_and_conclusion(
        relation_binding_request):
    cap_member, bridge, cap_detail = _relation_binding_parts(relation_binding_request)
    domains = _relation_binding_domains()
    env = {"actor": 0, "event": "e0", "time": "t0"}
    three = _relation_binding_table((0, 1, 2), (0, 1, 2))
    assert finite(cap_member, three, domains, env) is True
    assert finite(bridge, three, domains, env) is True
    assert finite(cap_detail, three, domains, env) is True
    four = _relation_binding_table((0, 1, 2, 3), (0, 1, 2, 3))
    assert finite(bridge, four, domains, env) is True
    assert finite(cap_member, four, domains, env) is False
    assert finite(cap_detail, four, domains, env) is False
    assert finite(relation_binding_request["expression"]["root"], three, domains) is True
    assert finite(relation_binding_request["expression"]["root"], four, domains) is True


def test_relation_binding_reverse_only_has_a_nonempty_four_detail_countermodel(
        relation_binding_request):
    cap_member, bridge, cap_detail = _relation_binding_parts(relation_binding_request)
    domains = _relation_binding_domains()
    env = {"actor": 0, "event": "e0", "time": "t0"}
    table = _relation_binding_table((0, 1, 2), (0, 1, 2, 3))
    reverse = deepcopy(bridge)
    reverse["arguments"][0]["arguments"].reverse()
    assert finite(cap_member, table, domains, env) is True
    assert finite(reverse, table, domains, env) is True
    assert finite(bridge, table, domains, env) is False
    assert finite(cap_detail, table, domains, env) is False
    wrong_conditional = deepcopy(relation_binding_request)
    _, wrong_bridge, _ = _relation_binding_parts(wrong_conditional)
    wrong_bridge["arguments"][0]["arguments"].reverse()
    assert finite(wrong_conditional["expression"]["root"], table, domains) is False


def test_relation_binding_actor_fiber_does_not_substitute_another_actor(
        relation_binding_request):
    cap_member, bridge, cap_detail = _relation_binding_parts(relation_binding_request)
    domains = _relation_binding_domains()
    table = _relation_binding_table((0, 1, 2), (0, 1, 2), actor=1)
    table["Detail"] |= {(0, item, "e0", "t0") for item in (0, 1, 2, 3)}
    target = {"actor": 0, "event": "e0", "time": "t0"}
    other = target | {"actor": 1}
    assert finite(cap_member, table, domains, target) is True
    assert finite(bridge, table, domains, other) is True
    assert finite(cap_detail, table, domains, other) is True
    assert finite(bridge, table, domains, target) is False
    assert finite(cap_detail, table, domains, target) is False


def test_relation_binding_event_crossing_does_not_transport_a_local_cap(
        relation_binding_request):
    cap_member, bridge, cap_detail = _relation_binding_parts(relation_binding_request)
    domains = _relation_binding_domains(events=("e0", "e1"))
    table = _relation_binding_table((0, 1, 2), (0, 1, 2, 3))
    table["Member"] |= {(item, "e1", "t0") for item in (0, 1, 2, 3)}
    env = {"actor": 0, "event": "e0", "time": "t0", "other_event": "e1"}
    wrong = deepcopy(bridge)
    member = wrong["arguments"][0]["arguments"][1]
    assert member["symbol"] == "Member"
    member["arguments"][1]["symbol"] = "other_event"
    assert finite(cap_member, table, domains, env) is True
    assert finite(wrong, table, domains, env) is True
    assert finite(bridge, table, domains, env) is False
    assert finite(cap_detail, table, domains, env) is False
    # This is a LOCAL-premise counterexample, not a counterexample to global cap transport.
    assert finite(cap_member, table, domains, env | {"event": "e1"}) is False


def test_relation_binding_time_crossing_does_not_transport_a_local_cap(
        relation_binding_request):
    cap_member, bridge, cap_detail = _relation_binding_parts(relation_binding_request)
    domains = _relation_binding_domains(times=("t0", "t1"))
    table = _relation_binding_table((0, 1, 2), (0, 1, 2, 3))
    table["Member"] |= {(item, "e0", "t1") for item in (0, 1, 2, 3)}
    env = {"actor": 0, "event": "e0", "time": "t0", "other_time": "t1"}
    wrong = deepcopy(bridge)
    member = wrong["arguments"][0]["arguments"][1]
    assert member["symbol"] == "Member"
    member["arguments"][2]["symbol"] = "other_time"
    assert finite(cap_member, table, domains, env) is True
    assert finite(wrong, table, domains, env) is True
    assert finite(bridge, table, domains, env) is False
    assert finite(cap_detail, table, domains, env) is False
    assert finite(cap_member, table, domains, env | {"time": "t1"}) is False


def test_relation_binding_per_frame_cap_does_not_become_a_global_lifetime_cap(
        original, relation_binding_request):
    cap_member, bridge, cap_detail = _relation_binding_parts(relation_binding_request)
    domains = _relation_binding_domains(objects=(0, 1, 2, 3, 4, 5), events=("e0", "e1"))
    table = _relation_binding_table((0, 1, 2), (0, 1, 2))
    table["Member"] |= {(item, "e1", "t0") for item in (3, 4, 5)}
    table["Detail"] |= {(0, item, "e1", "t0") for item in (3, 4, 5)}
    assert finite(original["expression"]["root"], table["Member"], domains) is True
    for event in ("e0", "e1"):
        env = {"actor": 0, "event": event, "time": "t0"}
        assert finite(cap_member, table, domains, env) is True
        assert finite(bridge, table, domains, env) is True
        assert finite(cap_detail, table, domains, env) is True
    assert len({row[1] for row in table["Detail"]}) == 6


def test_relation_binding_has_no_implicit_permission_or_world_transport(
        relation_binding_request):
    cap_member, bridge, _ = _relation_binding_parts(relation_binding_request)
    assert relation_binding_request["scope"]["evaluation"] == "single_interpretation"
    assert relation_binding_request["scope"]["modal_transport"] == "none"
    assert not any(row["kind"] == "extension"
                   for row in nodes(relation_binding_request["expression"]["root"]))
    domains = _relation_binding_domains()
    env = {"actor": 0, "event": "e0", "time": "t0"}
    worlds = (_relation_binding_table((0, 1, 2), (0, 1, 2)),
              _relation_binding_table((0, 1, 2, 3), (0, 1, 2, 3)))
    caps = tuple(finite(cap_member, table, domains, env) for table in worlds)
    inclusions = tuple(finite(bridge, table, domains, env) for table in worlds)
    assert caps == (True, False) and inclusions == (True, True)
    # Explicit finite fixture only: P chooses world1. It is not an interpreter for
    # the whole mixed proposal and does not select legal permission semantics.
    permission = lambda values: values[1]
    assert (not caps[0] or permission(inclusions)) is True
    assert permission(tuple(cap and inclusion for cap, inclusion in zip(caps, inclusions))) is False
    # An unconstrained P need not preserve a mere one-way implication.
    unconstrained_P = lambda value: not value
    assert (not False or True) is True
    assert unconstrained_P(False) is True and unconstrained_P(True) is False


def test_relation_binding_invalid_json_and_independent_hash_fail_before_owner_discovery(
        relation_binding_request, monkeypatch):
    monkeypatch.setattr(binding, "_relation_binding_owners", lambda:
        pytest.fail("operation owner discovered before raw input rejection"))
    for raw in (b"", b"{", b"[]", b'{"schema":1,"schema":2}', b'{"x":NaN}',
                b'{"x":"\\ud800"}', b" " * (binding.MAX_REQUEST_BYTES + 1)):
        with pytest.raises(ValueError):
            binding.prepare_counted_relation_binding_v1(raw, expected_request_sha256=sha(raw))
    raw = wire(relation_binding_request)
    with pytest.raises(ValueError):
        binding.prepare_counted_relation_binding_v1(raw, expected_request_sha256="0" * 64)


def test_relation_binding_direction_roles_frame_masks_and_inner_bytes_are_closed_before_owners(
        relation_binding_request, monkeypatch):
    damaged = []
    request = deepcopy(relation_binding_request)
    request["relation_binding"]["direction"] = "counted_implies_target"
    damaged.append(request)
    request = deepcopy(relation_binding_request)
    request["relation_binding"]["target_argument_roles"] = ["object", "actor", "event", "time"]
    damaged.append(request)
    request = deepcopy(relation_binding_request)
    request["scope"]["frame_binding"] = "different_event_and_time"
    damaged.append(request)
    request = deepcopy(relation_binding_request)
    request["scope"]["modal_transport"] = "permission_monotonicity"
    damaged.append(request)
    request = deepcopy(relation_binding_request)
    request["training_mask"] = 1
    damaged.append(request)
    request = deepcopy(relation_binding_request)
    request["source_binding"] = {"claimed": "reviewed"}
    damaged.append(request)
    request = deepcopy(relation_binding_request)
    request["counted_request_raw_utf8"] += " "
    damaged.append(request)
    request = deepcopy(relation_binding_request)
    _, bridge, _ = _relation_binding_parts(request)
    bridge["arguments"][0]["arguments"].reverse()
    reseal(request)
    damaged.append(request)
    request = deepcopy(relation_binding_request)
    _, bridge, _ = _relation_binding_parts(request)
    bridge["arguments"][0]["arguments"][1]["arguments"][1]["symbol"] = "other_event"
    reseal(request)
    damaged.append(request)
    monkeypatch.setattr(binding, "_relation_binding_owners", lambda:
        pytest.fail("operation owner discovered before fixed declaration/typed-shape rejection"))
    for request in damaged:
        with pytest.raises(ValueError):
            _relation_binding_prepare(request)


def test_relation_binding_resealed_reports_and_final_serialization_mutations_are_refused(
        relation_binding_request, monkeypatch):
    report = _relation_binding_prepare(relation_binding_request)
    raw = wire(relation_binding_request)
    for field, value in (("training_mask", 1), ("source_bound", True)):
        changed = deepcopy(report)
        changed[field] = value
        with pytest.raises(ValueError):
            binding.validate_counted_relation_binding_v1(
                changed, raw, expected_request_sha256=sha(raw),
                expected_report_sha256=binding.counted_relation_binding_report_sha256(changed))
    source = next(path for path in report["producer_pins"] if path.endswith("/syntax_core/ast.py"))
    actual_read, actual_wire = Path.read_bytes, binding._relation_binding_wire
    for boundary in ("producer", "output"):
        changed_after_wire = False

        def read(path):
            result = actual_read(path)
            return result + b"\n# changed after final binding serialization\n" if (
                changed_after_wire and str(path.resolve()) == source) else result

        def serialize(value, *args, **kwargs):
            nonlocal changed_after_wire
            result = actual_wire(value, *args, **kwargs)
            if type(value) is dict and value.get("schema") == "legal-counted-relation-binding-report/v1":
                if boundary == "producer":
                    changed_after_wire = True
                else:
                    value["training_mask"] = 1
            return result

        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", read)
            patch.setattr(binding, "_relation_binding_wire", serialize)
            with pytest.raises(ValueError):
                _relation_binding_prepare(relation_binding_request)
