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
        assert node["symbol"] == "Member"
        return tuple(finite(child, members, domains, environment)
                     for child in node["arguments"]) in members
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
