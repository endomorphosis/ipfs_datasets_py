"""Authored threshold-language controls; no source, numerical or Lean authority.

The existing owning test's finite()/truth() functions below were copied by AST
source extraction during preparation. They are never imported from that test
at runtime, and interpret only the serialized existing typed AST.
"""
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_counted_frame_threshold_v2 as subject
from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as legacy
from ipfs_datasets_py.logic.syntax_core import algebra, ast


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


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


def nodes(root):
    yield root
    for child in root["arguments"]:
        yield from nodes(child)


def prepare(maximum):
    request = subject.authored_counted_threshold_request_v2(maximum)
    raw = wire(request)
    return subject.prepare_counted_threshold_v2(raw, expected_request_sha256=sha(raw))


@pytest.fixture(scope="module")
def reports():
    return {maximum:prepare(maximum) for maximum in (1, 2, 3)}


def report_truth(report, rows, **domains):
    return truth({"expression":report["typed_expression"]}, rows, **domains)


def direct_distinct_cap(maximum, rows, *, events=("e",), times=("t",)):
    """Independent cardinality oracle, with no AST or declaration inspection."""
    return all(len({obj for obj, row_event, row_time in rows
                    if row_event == event and row_time == time}) <= maximum
               for event in events for time in times)


@pytest.mark.parametrize("maximum,expected", [
    (1, (17, 4, 2, 1, 8, 1, 0)),
    (2, (31, 5, 3, 3, 15, 2, 2)),
    (3, (49, 6, 4, 6, 24, 3, 5)),
], ids=["maximum_one", "maximum_two", "maximum_three"])
def test_threshold_constructs_three_real_closed_many_sorted_trees(reports, maximum, expected):
    report = reports[maximum]
    expression = report["typed_expression"]
    rebuilt = ast.TypedExpression.from_dict(expression)
    assert rebuilt.to_dict() == expression
    assert rebuilt.is_formula and not rebuilt.root.free_variable_names()
    assert rebuilt.family.value == "first_order" and rebuilt.profile.value == "many_sorted"
    assert rebuilt.metadata == {} and expression["signature"]["metadata"] == {}
    physical = list(nodes(expression["root"]))
    counts = {kind:sum(node["kind"] == kind for node in physical)
              for kind in ("forall", "predicate", "equality", "variable", "and", "or", "implies")}
    amount, binders, members, identities, variables, conjunctions, disjunctions = expected
    assert len(physical) == amount
    assert len({node["node_id"] for node in physical}) == amount
    assert counts == {"forall":binders, "predicate":members, "equality":identities,
                      "variable":variables, "and":conjunctions, "or":disjunctions, "implies":1}
    assert report["counts"] == {"nodes":amount, "quantifiers":binders,
        "membership_occurrences":members, "equality_occurrences":identities,
        "variable_occurrences":variables}
    expected_binders = [("event", "EventFrame"), ("time", "TimeFrame")]
    expected_binders += [("x"+str(index), "Object") for index in range(maximum+1)]
    root = expression["root"]
    for name, sort in expected_binders:
        assert root["kind"] == "forall" and len(root["binders"]) == 1
        assert root["binders"][0]["name"] == name
        assert root["binders"][0]["sort"]["name"] == sort
        root = root["arguments"][0]
    assert root["kind"] == "implies"
    assert root["arguments"][1]["kind"] == ("equality" if maximum == 1 else "or")
    assert [(item["variable"], item["sort"]) for item in report["binder_ledger"]] == expected_binders
    assert len(report["structural_mapping"]) == amount
    expected_pairs = list(itertools.combinations(["x"+str(i) for i in range(maximum+1)], 2))
    assert report["identity_pairs"] == [list(pair) for pair in expected_pairs]
    actual_members = [node for node in physical if node["kind"] == "predicate"]
    assert [node["symbol"] for node in actual_members] == ["Member"] * members
    assert [[child["symbol"] for child in node["arguments"]] for node in actual_members] == [
        ["x"+str(i), "event", "time"] for i in range(maximum+1)]
    assert all([child["sort"]["name"] for child in node["arguments"]] ==
               ["Object", "EventFrame", "TimeFrame"] for node in actual_members)
    assert report["maximum"] == maximum and type(report["maximum"]) is int
    assert report["schema"] == "legal-counted-frame-threshold-report/v2"
    assert report["profile"] == "authored-at-most-one-to-three-distinct-per-event-and-time/v2"
    assert report["source_binding"] is None
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert "lean_body" not in report and "codec" not in report and "model_state" not in report
    assert report["lowering_route"] == "existing_typed_FOL_no_native_lowering"
    for flag in ("model_executed", "training_executed", "native_build_executed",
                 "native_TDFOL_route_used", "source_translation_performed", "codec_compatibility_verified"):
        assert report[flag] is False
    receipt = report["fol_receipt"]
    for field in ("binary_connective_grouping_preserved", "original_to_first_alpha_equivalent",
                  "first_to_second_alpha_equivalent", "original_to_second_alpha_equivalent",
                  "canonical_print_stable"):
        assert receipt[field] is True
    assert sha(report["canonical_fol"].encode()) == report["canonical_fol_sha256"]


@pytest.mark.parametrize("maximum", [1, 2, 3], ids=["maximum_one", "maximum_two", "maximum_three"])
def test_threshold_all_sixteen_relations_match_independent_cardinality(reports, maximum):
    report = reports[maximum]
    for subset_bits in range(16):
        rows = [(obj, "e", "t") for obj in range(4) if subset_bits & (1 << obj)]
        expected = direct_distinct_cap(maximum, rows)
        assert expected is (len(rows) <= maximum)
        assert report_truth(report, rows) is expected
    # An unused domain inhabitant is not a member and cannot tighten the cap.
    rows = [(obj, "e", "t") for obj in range(maximum)]
    assert report_truth(report, rows, objects=(0, 1, 2, 3, 4))
    assert report_truth(report, [])
    assert not report_truth(report, [(obj, "e", "t") for obj in range(maximum+1)])


@pytest.mark.parametrize("amount,expected", [
    (2, [False, True, True]), (3, [False, False, True]),
], ids=["two_distinct_members", "three_distinct_members"])
def test_threshold_two_and_three_members_distinguish_the_languages(reports, amount, expected):
    rows = [(obj, "e", "t") for obj in range(amount)]
    assert [report_truth(reports[maximum], rows) for maximum in (1, 2, 3)] == expected
    assert len({wire(reports[maximum]["typed_expression"]["root"]) for maximum in (1, 2, 3)}) == 3


@pytest.mark.parametrize("maximum", [1, 2, 3], ids=["maximum_one", "maximum_two", "maximum_three"])
def test_threshold_duplicate_occurrences_do_not_increase_identity_count(reports, maximum):
    rows = [(obj, "e", "t") for obj in range(maximum)]
    repeated = rows + rows + rows[:1]
    assert len(repeated) > maximum and len(set(repeated)) == maximum
    assert direct_distinct_cap(maximum, repeated)
    assert report_truth(reports[maximum], repeated)
    assert not report_truth(reports[maximum], repeated+[(maximum, "e", "t")])


@pytest.mark.parametrize("axis", ["event", "time"], ids=["distinct_events", "distinct_times"])
def test_threshold_frames_are_local_and_do_not_aggregate_members(reports, axis):
    for maximum in (1, 2, 3):
        first = [(obj, "e0", "t0") for obj in range(maximum)]
        other = (maximum, "e1" if axis == "event" else "e0", "t1" if axis == "time" else "t0")
        rows = first+[other]
        domains = dict(events=("e0", "e1"), times=("t0", "t1"))
        assert direct_distinct_cap(maximum, rows, **domains)
        assert report_truth(reports[maximum], rows, **domains)
        collapsed = [(obj, "e0", "t0") for obj, _, _ in rows]
        assert not direct_distinct_cap(maximum, collapsed, **domains)
        assert not report_truth(reports[maximum], collapsed, **domains)


@pytest.mark.parametrize("maximum", [1, 2, 3], ids=["one_equality", "three_equalities", "six_equalities"])
def test_threshold_every_equality_pair_has_an_independent_necessity_witness(reports, maximum):
    report = reports[maximum]
    matrix = report["typed_expression"]["root"]
    for _ in range(maximum+3):
        assert matrix["kind"] == "forall"
        matrix = matrix["arguments"][0]
    equalities = [node for node in nodes(matrix) if node["kind"] == "equality"]
    expected_pairs = list(itertools.combinations(["x"+str(i) for i in range(maximum+1)], 2))
    assert len(equalities) == len(expected_pairs)
    domains = {"Object":tuple(range(maximum)), "EventFrame":("e",), "TimeFrame":("t",)}
    members = {(obj, "e", "t") for obj in range(maximum)}
    for pair_index, (left, right) in enumerate(expected_pairs):
        environment = {"event":"e", "time":"t", left:0, right:0}
        others = sorted(set("x"+str(i) for i in range(maximum+1)) - {left, right})
        environment.update({name:index+1 for index, name in enumerate(others)})
        observed = [finite(node, members, domains, environment) for node in equalities]
        assert observed == [index == pair_index for index in range(len(equalities))]
        assert finite(matrix, members, domains, environment)
        assert not any(value for index, value in enumerate(observed) if index != pair_index)


def test_threshold_all_contexts_are_identical_and_contain_no_cap_or_target_tree(reports):
    contexts = [report["signature_context"] for report in reports.values()]
    assert len({wire(context) for context in contexts}) == 1
    assert set(contexts[0]) == {"schema", "sorts", "predicate", "frame", "membership", "distinctness"}
    assert contexts[0]["schema"] == "legal-counted-frame-signature-context/v2"
    for report in reports.values():
        assert sha(wire(report["signature_context"])) == report["signature_context_sha256"]
        assert report["signature_context_role"] == "authored_syntactic_context_permission_unreviewed"
    forbidden = {"maximum", "object_variables", "binders", "binder_ledger", "counts", "expression",
                 "typed_expression", "root", "tree", "node_id", "content_digest", "identity_pairs"}
    def inspect(value):
        if type(value) is dict:
            assert forbidden.isdisjoint(value)
            for child in value.values():
                inspect(child)
        elif type(value) is list:
            for child in value:
                inspect(child)
        elif type(value) is str:
            assert value not in {"x0", "x1", "x2", "x3"}
    inspect(contexts[0])


def test_threshold_maximum_three_reuses_existing_semantics_without_widening_v1(reports, monkeypatch):
    legacy_request = legacy.authored_counted_frame_request()
    assert algebra.alpha_equivalent(ast.TypedExpression.from_dict(legacy_request["expression"]).root,
        ast.TypedExpression.from_dict(reports[3]["typed_expression"]).root)
    owner_sha = sha(Path(legacy.__file__).read_bytes())
    assert owner_sha == "df91798d11e2b0da36afc75e0bc1a8b6d0a3d08bc255e7362d1c200e5e9baa13"
    codec_before = legacy.build_counted_frame_token_codec_v1()
    codec_raw = wire(codec_before)
    assert len(codec_before["vocabulary"]) == 28
    for maximum in (1, 2):
        old_request = deepcopy(legacy_request)
        old_request["maximum"] = maximum
        old_request["object_variables"] = ["x"+str(i) for i in range(maximum+1)]
        old_request["expression"] = reports[maximum]["typed_expression"]
        raw = wire(old_request)
        with monkeypatch.context() as patch:
            patch.setattr(legacy, "_owners", lambda:pytest.fail("v1 widened before rejecting a different cap"))
            with pytest.raises(ValueError):
                legacy.prepare_counted_frame(raw, expected_request_sha256=sha(raw))
    assert wire(legacy.build_counted_frame_token_codec_v1()) == codec_raw
    assert sha(Path(legacy.__file__).read_bytes()) == owner_sha


def test_threshold_authored_factory_is_a_detached_declaration_not_a_caller_ast():
    first = subject.authored_counted_threshold_request_v2(2)
    expected = deepcopy(first)
    assert first["schema"] == "legal-counted-frame-threshold-request/v2"
    assert first["interpretation_status"] == "authored_unreviewed_declaration"
    assert "expression" not in first and "typed_expression" not in first
    assert first["object_variables"] == ["x0", "x1", "x2"]
    assert first["source_binding"] is None
    first["frame"]["event"]["variable"] = "changed"
    first["object_variables"].append("injected")
    assert subject.authored_counted_threshold_request_v2(2) == expected
    raw = (json.dumps(expected, ensure_ascii=False, indent=2)+"\n").encode()
    report = subject.prepare_counted_threshold_v2(raw, expected_request_sha256=sha(raw))
    assert report["request"] == expected and report["request_raw_utf8"] == raw.decode()
    assert report["request_sha256"] == sha(raw)
    assert subject.validate_counted_threshold_v2(wire(report), raw,
        expected_request_sha256=sha(raw),
        expected_report_sha256=subject.counted_threshold_report_sha256(report)) == report


@pytest.mark.parametrize("maximum", [True, False, 0, 4, -1, 1.0, 3.0, "1", None, []],
    ids=["bool_true", "bool_false", "zero", "four", "negative", "float_one", "float_three",
         "string_one", "null", "list"])
def test_threshold_wrong_maximum_types_refuse_before_syntax_owners(monkeypatch, maximum):
    request = subject.authored_counted_threshold_request_v2(1)
    monkeypatch.setattr(subject, "_owners", lambda:pytest.fail("invalid cap reached syntax owners"))
    with pytest.raises(ValueError):
        subject.authored_counted_threshold_request_v2(maximum)
    request["maximum"] = maximum
    raw = wire(request)
    with pytest.raises(ValueError):
        subject.prepare_counted_threshold_v2(raw, expected_request_sha256=sha(raw))


@pytest.mark.parametrize("damage", ["extra_field", "caller_expression", "old_schema", "source_binding",
    "frame_policy", "membership_roles", "object_variables", "distinctness"],
    ids=["extra_field", "caller_expression", "old_schema", "source_binding", "frame_policy",
         "membership_roles", "object_variables", "distinctness"])
def test_threshold_altered_declarations_refuse_before_syntax_owners(monkeypatch, damage):
    request = subject.authored_counted_threshold_request_v2(2)
    if damage == "extra_field": request["unknown"] = None
    elif damage == "caller_expression": request["expression"] = {"root":"injected"}
    elif damage == "old_schema": request["schema"] = "legal-counted-frame-request/v1"
    elif damage == "source_binding": request["source_binding"] = {"legal_id":"authored:not_a_statute"}
    elif damage == "frame_policy": request["frame"]["policy"] = "global_lifetime"
    elif damage == "membership_roles": request["membership"]["argument_roles"] = ["object", "time", "event"]
    elif damage == "object_variables": request["object_variables"] = ["x0", "x2", "x1"]
    else: request["distinctness"] = "occurrence_multiplicity"
    raw = wire(request)
    monkeypatch.setattr(subject, "_owners", lambda:pytest.fail("bad declaration reached syntax owners"))
    with pytest.raises(ValueError):
        subject.prepare_counted_threshold_v2(raw, expected_request_sha256=sha(raw))


@pytest.mark.parametrize("damage", ["empty", "duplicate_key", "invalid_utf8", "bytearray", "oversized"],
    ids=["empty", "duplicate_key", "invalid_utf8", "bytearray", "oversized"])
def test_threshold_malformed_transport_refuses_before_syntax_owners(monkeypatch, damage):
    raw = wire(subject.authored_counted_threshold_request_v2(1))
    if damage == "empty": offered = b""
    elif damage == "duplicate_key": offered = raw.replace(b'"maximum":1', b'"maximum":1,"maximum":1')
    elif damage == "invalid_utf8": offered = b"\xff"
    elif damage == "bytearray": offered = bytearray(raw)
    else: offered = b" " * (legacy.MAX_REQUEST_BYTES+1)
    digest = sha(bytes(offered))
    monkeypatch.setattr(subject, "_owners", lambda:pytest.fail("bad transport reached syntax owners"))
    with pytest.raises(ValueError):
        subject.prepare_counted_threshold_v2(offered, expected_request_sha256=digest)


@pytest.mark.parametrize("pin", ["request", "report"], ids=["independent_request_pin", "independent_report_pin"])
def test_threshold_wrong_independent_pins_precede_replay(reports, monkeypatch, pin):
    report = reports[2]
    raw = report["request_raw_utf8"].encode()
    report_sha = subject.counted_threshold_report_sha256(report)
    monkeypatch.setattr(subject, "_owners", lambda:pytest.fail("wrong independent pin reached replay"))
    with pytest.raises(ValueError):
        subject.validate_counted_threshold_v2(report, raw,
            expected_request_sha256="0"*64 if pin == "request" else sha(raw),
            expected_report_sha256="0"*64 if pin == "report" else report_sha)


@pytest.mark.parametrize("damage", ["maximum_bool", "cross_maximum", "authority", "gold_mask",
    "typed_tree", "fol_text", "context", "producer_path"],
    ids=["maximum_bool", "cross_maximum", "authority", "gold_mask", "typed_tree", "fol_text",
         "context", "producer_path"])
def test_threshold_resealed_report_cannot_replace_complete_request_replay(reports, monkeypatch, damage):
    report = reports[2]
    offered = deepcopy(report)
    if damage == "maximum_bool": offered["maximum"] = True
    elif damage == "cross_maximum":
        offered["typed_expression"] = deepcopy(reports[1]["typed_expression"])
        offered["counts"] = deepcopy(reports[1]["counts"])
    elif damage == "authority": offered["authority"]["source_semantics_verified"] = True
    elif damage == "gold_mask": offered["evaluation_gold_mask"] = True
    elif damage == "typed_tree": offered["typed_expression"]["root"]["binders"][0]["name"] = "injected"
    elif damage == "fol_text": offered["canonical_fol"] = "forall injected. injected = injected"
    elif damage == "context": offered["signature_context"]["maximum"] = 2
    else:
        offered["producer_pins"]["/must/not/read/an/offered/producer.py"] = "0"*64
        actual_read = Path.read_bytes
        def guarded_read(path):
            assert str(path) != "/must/not/read/an/offered/producer.py"
            return actual_read(path)
        monkeypatch.setattr(Path, "read_bytes", guarded_read)
    raw = report["request_raw_utf8"].encode()
    with pytest.raises(ValueError):
        subject.validate_counted_threshold_v2(offered, raw, expected_request_sha256=sha(raw),
            expected_report_sha256=subject.counted_threshold_report_sha256(offered))


@pytest.mark.parametrize("boundary", ["self_hash", "base_hash", "closing_generation"],
    ids=["self_hash", "base_hash", "closing_generation"])
def test_threshold_producer_generation_is_fenced_at_open_and_close(reports, monkeypatch, boundary):
    if boundary == "self_hash":
        monkeypatch.setattr(subject, "_SELF_PIN", "0"*64)
        with pytest.raises(ValueError):
            subject.counted_threshold_report_sha256(reports[1])
    elif boundary == "base_hash":
        monkeypatch.setattr(subject, "_BASE_SHA", "0"*64)
        with pytest.raises(ValueError):
            subject.authored_counted_threshold_request_v2(1)
    else:
        raw = wire(subject.authored_counted_threshold_request_v2(1))
        actual = subject._expression
        def changed_generation(*args, **kwargs):
            expression = actual(*args, **kwargs)
            monkeypatch.setattr(subject, "_SELF_PIN", "0"*64)
            return expression
        monkeypatch.setattr(subject, "_expression", changed_generation)
        with pytest.raises(ValueError):
            subject.prepare_counted_threshold_v2(raw, expected_request_sha256=sha(raw))


def test_threshold_validator_closing_check_preserves_the_callers_offered_report(reports, monkeypatch):
    offered = deepcopy(reports[2])
    raw = offered["request_raw_utf8"].encode()
    report_sha = subject.counted_threshold_report_sha256(offered)
    actual = subject.prepare_counted_threshold_v2
    def changed_caller(*args, **kwargs):
        regenerated = actual(*args, **kwargs)
        offered["training_mask"] = True
        return regenerated
    monkeypatch.setattr(subject, "prepare_counted_threshold_v2", changed_caller)
    with pytest.raises(ValueError):
        subject.validate_counted_threshold_v2(offered, raw, expected_request_sha256=sha(raw),
            expected_report_sha256=report_sha)
    assert offered["training_mask"] is True


def test_threshold_panel_retains_complete_requests_reports_and_finite_witnesses(reports, tmp_path):
    cases, finite_checks = [], []
    for maximum in (1, 2, 3):
        report = reports[maximum]
        raw = report["request_raw_utf8"].encode()
        report_sha = subject.counted_threshold_report_sha256(report)
        assert subject.validate_counted_threshold_v2(report, raw,
            expected_request_sha256=sha(raw), expected_report_sha256=report_sha) == report
        cases.append(dict(maximum=maximum, request=report["request"], request_raw_utf8=raw.decode(),
            request_sha256=sha(raw), report=report, report_sha256=report_sha))
        for membership_mask in range(16):
            members = [obj for obj in range(4) if membership_mask & (1 << obj)]
            rows = [(obj, "e", "t") for obj in members]
            expected = direct_distinct_cap(maximum, rows)
            observed = report_truth(report, rows)
            assert observed is expected
            finite_checks.append(dict(maximum=maximum, membership_mask=membership_mask,
                members=members, expected=expected, observed=observed))
    context = reports[1]["signature_context"]
    panel = dict(schema="legal-authored-counted-threshold-test-panel/v2", cases=cases,
        finite_checks=finite_checks, finite_check_count=len(finite_checks),
        distinct_tree_count=len({wire(report["typed_expression"]["root"]) for report in reports.values()}),
        distinct_signature_context_count=len({wire(report["signature_context"]) for report in reports.values()}),
        signature_context=context, signature_context_sha256=sha(wire(context)),
        model_executed=False, training_executed=False, native_build_executed=False, codec_changed=False,
        training_mask=0, evaluation_gold_mask=0, authority={key:False for key in reports[1]["authority"]})
    assert panel["finite_check_count"] == 48 and panel["distinct_tree_count"] == 3
    assert panel["distinct_signature_context_count"] == 1
    payload = wire(panel)
    assert len(payload) < 1048576
    path = tmp_path/"authored-threshold-panel-v2.json"
    path.write_bytes(payload)
    assert path.read_bytes() == payload
