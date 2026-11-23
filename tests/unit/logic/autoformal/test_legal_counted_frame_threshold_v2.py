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


# Explicit Nat profile controls; none widens the retained v1/v2 schemas.
def _nat_report(maximum):
    request = subject.authored_counted_threshold_request_v3(maximum)
    raw = wire(request)
    report = subject.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    assert subject.validate_counted_threshold_v3(report, raw,
        expected_request_sha256=sha(raw), expected_report_sha256=sha(wire(report))) == report
    return report


def _nat_denote(node, members, domains, environment=None):
    """Independent finite semantics, including the zero bound's false node."""
    environment = {} if environment is None else environment
    kind = node['kind']
    if kind == 'false':
        return False
    if kind == 'true':
        return True
    if kind == 'variable':
        return environment[node['symbol']]
    if kind == 'predicate':
        return tuple(_nat_denote(c, members, domains, environment) for c in node['arguments']) in members
    if kind == 'equality':
        return _nat_denote(node['arguments'][0], members, domains, environment) == _nat_denote(
            node['arguments'][1], members, domains, environment)
    if kind == 'forall':
        binder = node['binders'][0]
        return all(_nat_denote(node['arguments'][0], members, domains,
            environment | {binder['name']: v}) for v in domains[binder['sort']['name']])
    left, right = (_nat_denote(c, members, domains, environment) for c in node['arguments'])
    if kind == 'and':
        return left and right
    if kind == 'or':
        return left or right
    assert kind == 'implies'
    return not left or right


def _nat_truth(report, rows, objects, events=('e',), times=('t',)):
    return _nat_denote(report['typed_expression']['root'], set(rows),
        {'Object': tuple(objects), 'EventFrame': events, 'TimeFrame': times})


@pytest.mark.parametrize('maximum', [0, 1, 3, 4])
def test_parametric_threshold_distinguishes_n_and_n_plus_one_members(maximum):
    report = _nat_report(maximum)
    objects = tuple(range(maximum + 1))
    for count in (maximum, maximum + 1):
        rows = [(i, 'e', 't') for i in range(count)]
        assert _nat_truth(report, rows, objects) == (count <= maximum)
        assert _nat_truth(report, rows + rows, objects) == (count <= maximum)
    assert report['profile'] == subject.PARAMETRIC_PROFILE
    assert not any(report['authority'].values())
    assert report['training_mask'] == report['evaluation_gold_mask'] == 0
    assert not report['native_build_executed']
    assert 'def countedAtMostThreshold' in report['lean_body']


def test_parametric_zero_and_empty_carriers_have_no_inhabitation_assumption():
    report = _nat_report(0)
    assert _nat_truth(report, [], ())
    assert _nat_truth(report, [], (0,))
    assert not _nat_truth(report, [(0, 'e', 't')], (0,))
    assert _nat_truth(report, [(0, 'e', 't')], (0,), events=())
    assert _nat_truth(report, [(0, 'e', 't')], (0,), times=())


def test_parametric_frame_locality_and_nonmembers_remain_distinct():
    report = _nat_report(1)
    rows = [(0, 'e0', 't'), (1, 'e1', 't')]
    assert _nat_truth(report, rows, (0, 1, 2), events=('e0', 'e1'))
    assert not _nat_truth(report, [(0, 'e0', 't'), (1, 'e0', 't')], (0, 1, 2), events=('e0', 'e1'))


def test_parametric_n4_missing_equality_pair_has_a_semantic_countermodel():
    report = _nat_report(4)
    changed = deepcopy(report)
    first_equality = next(n for n in nodes(changed['typed_expression']['root']) if n['kind'] == 'equality')
    first_equality.update(kind='false', symbol='', arguments=[], binders=[])
    rows = [(i, 'e', 't') for i in range(4)]
    assert _nat_truth(report, rows, range(4))
    assert not _nat_truth(changed, rows, range(4))


def test_parametric_changed_roles_cannot_hide_an_overfull_frame():
    report = _nat_report(1)
    changed = deepcopy(report)
    for n in nodes(changed['typed_expression']['root']):
        if n['kind'] == 'predicate':
            n['arguments'][0], n['arguments'][1] = n['arguments'][1], n['arguments'][0]
    rows = [(0, 'e', 't'), (1, 'e', 't')]
    assert not _nat_truth(report, rows, (0, 1))
    assert _nat_truth(changed, rows, (0, 1))


def test_parametric_report_mutation_cannot_replace_complete_request_replay():
    request = subject.authored_counted_threshold_request_v3(4)
    raw = wire(request)
    report = subject.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    changed = deepcopy(report)
    changed['maximum'] = 3
    with pytest.raises(ValueError):
        subject.validate_counted_threshold_v3(changed, raw,
            expected_request_sha256=sha(raw), expected_report_sha256=sha(wire(changed)))


@pytest.mark.parametrize('maximum', [True, -1, 1.0, '4', 10**100])
def test_parametric_type_and_capacity_refusal_precede_lazy_owner_access(monkeypatch, maximum):
    monkeypatch.setattr(subject, '_base', lambda: pytest.fail('invalid/capacity input reached owners'))
    with pytest.raises(ValueError):
        subject.authored_counted_threshold_request_v3(maximum)


def test_parametric_opt_in_preserves_existing_v2_targets_and_closed_thresholds():
    new = _nat_report(3)
    old = prepare(3)
    assert new['typed_expression'] == old['typed_expression']
    assert new['canonical_fol'] == old['canonical_fol']
    for maximum in (0, 4):
        with pytest.raises(ValueError):
            subject.authored_counted_threshold_request_v2(maximum)
    assert subject._BASE_SHA == 'df91798d11e2b0da36afc75e0bc1a8b6d0a3d08bc255e7362d1c200e5e9baa13'


@pytest.mark.parametrize('maximum', [True, -1, 10**100])
def test_parametric_raw_prepare_and_validate_preflight_before_base_import(monkeypatch, maximum):
    request = subject.authored_counted_threshold_request_v3(1)
    request['maximum'] = maximum
    raw = wire(request)
    monkeypatch.setattr(subject, '_base', lambda: pytest.fail('raw invalid/capacity input reached base owner'))
    with pytest.raises(ValueError):
        subject.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    with pytest.raises(ValueError):
        subject.validate_counted_threshold_v3({}, raw,
            expected_request_sha256=sha(raw), expected_report_sha256='0'*64)


@pytest.mark.parametrize('raw', [b'{', b'{"schema":"legal-counted-frame-threshold-request/v3","maximum":1,"maximum":4}', b'x'*131073])
def test_parametric_malformed_raw_transport_refuses_before_base_import(monkeypatch, raw):
    monkeypatch.setattr(subject, '_base', lambda: pytest.fail('bad transport reached base owner'))
    with pytest.raises(ValueError):
        subject.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    with pytest.raises(ValueError):
        subject.validate_counted_threshold_v3({}, raw,
            expected_request_sha256=sha(raw), expected_report_sha256='0'*64)


def test_parametric_entry_points_are_explicit_public_exports():
    assert {'authored_counted_threshold_request_v3', 'prepare_counted_threshold_v3',
            'validate_counted_threshold_v3'} <= set(subject.__all__)


def test_parametric_preflight_accounts_for_existing_transport_depth_and_items():
    # AST depth alone cannot admit a tree whose serialized wrapper exceeds64.
    with pytest.raises(ValueError):
        subject._parametric_budget(6)
    with pytest.raises(ValueError):
        subject._parametric_budget(4, max_json_depth=1)
    with pytest.raises(ValueError):
        subject._parametric_budget(4, max_json_items=1)
    assert subject._parametric_budget(4)['json_depth_upper_bound'] <= 64


# Additive opt-in quantity controls; all preceding v1/v2/v3 tests remain exact.
def _quantity_capture(quantity, threshold):
    request = subject.authored_counted_quantity_request_v4(quantity, threshold)
    raw = wire(request)
    report = subject.prepare_counted_quantity_v4(raw, expected_request_sha256=sha(raw))
    assert subject.validate_counted_quantity_v4(report, raw,
        expected_request_sha256=sha(raw), expected_report_sha256=sha(wire(report))) == report
    return report, raw


def _quantity_model(root, objects, events, times, members, environment=None):
    """Finite countermodel interpreter, independent of producer declarations."""
    environment = {} if environment is None else environment
    kind, children = root['kind'], root['arguments']
    if kind == 'variable':
        return environment[root['symbol']]
    if kind == 'predicate':
        assert root['symbol'] == 'Member' and len(children) == 3
        return tuple(_quantity_model(x, objects, events, times, members, environment) for x in children) in members
    if kind == 'equality':
        return _quantity_model(children[0],objects,events,times,members,environment) == _quantity_model(children[1],objects,events,times,members,environment)
    if kind == 'not':
        return not _quantity_model(children[0],objects,events,times,members,environment)
    if kind in ('and','or','implies','iff'):
        left = _quantity_model(children[0],objects,events,times,members,environment)
        right = _quantity_model(children[1],objects,events,times,members,environment)
        return {'and':left and right,'or':left or right,'implies':not left or right,'iff':left == right}[kind]
    assert kind in ('forall','exists') and len(root['binders']) == 1
    binder = root['binders'][0]
    values = {'Object':objects,'EventFrame':events,'TimeFrame':times}[binder['sort']['name']]
    observations = (_quantity_model(children[0],objects,events,times,members,dict(environment,**{binder['name']:value})) for value in values)
    return all(observations) if kind == 'forall' else any(observations)


def _quantity_cardinality_oracle(quantity, threshold, objects, events, times, members):
    """Count distinct members directly; inspect no generated AST or report fields."""
    return all((len({x for x in objects if (x,event,time) in members}) >= threshold
                if quantity == 'at_least' else
                len({x for x in objects if (x,event,time) in members}) == threshold)
               for event in events for time in times)


@pytest.mark.parametrize('quantity', ['at_least','exactly'])
@pytest.mark.parametrize('threshold', [0,1,2,4])
def test_positive_quantity_same_sorted_source_matches_independent_cardinality(quantity, threshold):
    report, raw = _quantity_capture(quantity,threshold)
    assert report['quantity'] == quantity and report['threshold'] == threshold
    assert report['source_binding'] is None and not any(report['authority'].values())
    assert report['training_mask'] == report['evaluation_gold_mask'] == 0
    assert report['lowering_route'] == 'existing_mixed_TypedIR_and_sorted_relational_emitter'
    assert report['typed_expression'] == report['mixed_report']['typed_expression']
    assert report['lean_body'] == report['mixed_report']['lean_body']
    assert report['argument_roles'] == [{'symbol':'Member','roles':['object','event','time']}]
    objects, events, times = tuple(range(threshold+1)), ('event',), ('time',)
    for size in sorted({0,max(0,threshold-1),threshold,threshold+1}):
        members = {(x,'event','time')for x in objects[:size]}
        assert _quantity_model(report['typed_expression']['root'],objects,events,times,members) == _quantity_cardinality_oracle(quantity,threshold,objects,events,times,members)
    assert report['budget']['ast_nodes'] == report['counts']['nodes']


@pytest.mark.parametrize('quantity', ['at_least','exactly'])
@pytest.mark.parametrize('empty', ['Object','EventFrame','TimeFrame'])
def test_positive_quantity_empty_carriers_add_no_inhabitation_axiom(quantity, empty):
    report, _ = _quantity_capture(quantity,2)
    carriers = {'Object':(0,1),'EventFrame':('e',),'TimeFrame':('t',)}
    carriers[empty] = ()
    actual = _quantity_model(report['typed_expression']['root'],carriers['Object'],carriers['EventFrame'],carriers['TimeFrame'],set())
    assert actual == (empty != 'Object')
    zero, _ = _quantity_capture(quantity,0)
    assert _quantity_model(zero['typed_expression']['root'],carriers['Object'],carriers['EventFrame'],carriers['TimeFrame'],set())


@pytest.mark.parametrize('quantity', ['at_least','exactly'])
def test_positive_quantity_frame_locality_and_duplicate_occurrences(quantity):
    report, _ = _quantity_capture(quantity,2)
    root = report['typed_expression']['root']
    assert not _quantity_model(root,(0,1),('a','b'),('t',),{(0,'a','t'),(1,'a','t')})
    assert _quantity_model(root,(0,1),('a','b'),('t',),{(x,e,'t')for x in (0,1)for e in ('a','b')})
    repeated = [(0,'a','t'),(0,'a','t')]
    assert not _quantity_model(root,(0,1),('a',),('t',),repeated)


def _quantity_first(root, predicate):
    if predicate(root):
        return root
    for child in root['arguments']:
        found = _quantity_first(child,predicate)
        if found is not None:
            return found
    return None


@pytest.mark.parametrize('quantity', ['at_least','exactly'])
def test_positive_quantity_pairwise_distinctness_has_an_independent_countermodel(quantity):
    report, _ = _quantity_capture(quantity,2)
    root = deepcopy(report['typed_expression']['root'])
    not_equal = _quantity_first(root,lambda node:node['kind']=='not' and node['arguments'][0]['kind']=='equality')
    assert not_equal is not None
    # A same-variable equality is a tautology.  Replacing the disequality permits duplicate witnesses.
    equality = not_equal['arguments'][0]
    equality['arguments'][1] = deepcopy(equality['arguments'][0])
    not_equal.clear();not_equal.update(equality)
    members = {(0,'e','t')}
    assert not _quantity_model(report['typed_expression']['root'],(0,),('e',),('t',),members)
    assert _quantity_model(root,(0,),('e',),('t',),members)


def test_positive_quantity_exact_coverage_and_lower_membership_have_separate_countermodels():
    lower, _ = _quantity_capture('at_least',2)
    damaged = deepcopy(lower['typed_expression']['root'])
    member = _quantity_first(damaged,lambda node:node['kind']=='predicate')
    # Keep the first object variable but replace its membership leaf with x=x.
    variable = deepcopy(member['arguments'][0])
    member.update(kind='equality',symbol='',arguments=[variable,deepcopy(variable)])
    sparse = {(1,'e','t')}
    assert not _quantity_model(lower['typed_expression']['root'],(0,1),('e',),('t',),sparse)
    assert _quantity_model(damaged,(0,1),('e',),('t',),sparse)
    exact, _ = _quantity_capture('exactly',2)
    damaged = deepcopy(exact['typed_expression']['root'])
    coverage = _quantity_first(damaged,lambda node:node['kind']=='forall' and node['binders'][0]['name']=='candidate')
    tautology = deepcopy(_quantity_first(damaged,lambda node:node['kind']=='equality'))
    tautology['arguments'][1] = deepcopy(tautology['arguments'][0])
    coverage.clear();coverage.update(tautology)
    overfull = {(x,'e','t')for x in (0,1,2)}
    assert not _quantity_model(exact['typed_expression']['root'],(0,1,2),('e',),('t',),overfull)
    assert _quantity_model(damaged,(0,1,2),('e',),('t',),overfull)


@pytest.mark.parametrize('quantity', ['at_least','exactly'])
@pytest.mark.parametrize('damage', ['frame_sort','member_roles','distinctness','source_binding'])
def test_positive_quantity_closed_declaration_refuses_before_mixed_owners(monkeypatch, quantity, damage):
    request = subject.authored_counted_quantity_request_v4(quantity,2)
    if damage == 'frame_sort':request['frame']['event']['sort'] = 'Object'
    elif damage == 'member_roles':request['membership']['argument_roles'] = ['event','object','time']
    elif damage == 'distinctness':request['distinctness'] = 'occurrence_multiplicity'
    else:request['source_binding'] = {'claimed_source':'not-an-authored-declaration'}
    raw = wire(request)
    monkeypatch.setattr(subject,'_quantity_owners',lambda *a:pytest.fail('altered declaration reached mixed owners'))
    with pytest.raises(ValueError):subject.prepare_counted_quantity_v4(raw,expected_request_sha256=sha(raw))


@pytest.mark.parametrize('damage', ['member','sort','coverage','roles','frame_order','relation'])
def test_positive_quantity_resealed_report_requires_whole_original_replay(damage):
    report, raw = _quantity_capture('exactly',2)
    altered = deepcopy(report)
    if damage == 'roles':altered['argument_roles'][0]['roles'] = ['event','object','time']
    elif damage == 'relation':altered['quantity'] = 'at_least'
    else:
        root = altered['typed_expression']['root']
        if damage == 'sort':root['binders'][0]['sort']['name'] = 'Object'
        elif damage == 'coverage':_quantity_first(root,lambda node:node['kind']=='iff')['kind'] = 'implies'
        elif damage == 'frame_order':
            member = _quantity_first(root,lambda node:node['kind']=='predicate')
            member['arguments'][1],member['arguments'][2] = member['arguments'][2],member['arguments'][1]
        else:
            # Exact full coverage makes one membership leaf redundant semantically;
            # complete replay still retains it as part of the selected source.
            _quantity_first(root,lambda node:node['kind']=='predicate')['symbol'] = 'Other'
    with pytest.raises(ValueError):subject.validate_counted_quantity_v4(altered,raw,
        expected_request_sha256=sha(raw),expected_report_sha256=sha(wire(altered)))


@pytest.mark.parametrize('quantity,threshold', [('at_least',True),('exactly',-1),('at_least',1.5),('exactly',None),('at_most',2),('at_least',10**100)])
def test_positive_quantity_invalid_or_overbudget_refuses_before_lazy_owners(monkeypatch,quantity,threshold):
    monkeypatch.setattr(subject,'_base',lambda:pytest.fail('refused quantity reached lazy owners'))
    with pytest.raises(ValueError):subject.authored_counted_quantity_request_v4(quantity,threshold)


def test_positive_quantity_budget_is_resource_derived_not_four_case_semantic_ceiling():
    assert subject._quantity_budget('at_least',6)['threshold'] == 6
    assert subject._quantity_budget('exactly',5)['threshold'] == 5
    with pytest.raises(ValueError,match='capacity'):subject._quantity_budget('exactly',6)
    with pytest.raises(ValueError,match='capacity'):subject._quantity_budget('at_least',4,max_json_depth=1)


def test_positive_quantity_opt_in_keeps_every_existing_threshold_profile_replay_exact():
    captures = []
    for version, maximum in [(2,1),(2,2),(2,3),(3,0),(3,4)]:
        request = getattr(subject,'authored_counted_threshold_request_v'+str(version))(maximum)
        raw = wire(request)
        report = getattr(subject,'prepare_counted_threshold_v'+str(version))(raw,expected_request_sha256=sha(raw))
        captures.append((version,raw,report))
    _quantity_capture('at_least',2);_quantity_capture('exactly',2)
    for version,raw,report in captures:
        assert getattr(subject,'prepare_counted_threshold_v'+str(version))(raw,expected_request_sha256=sha(raw)) == report
        assert getattr(subject,'validate_counted_threshold_v'+str(version))(report,raw,
            expected_request_sha256=sha(raw),expected_report_sha256=sha(wire(report))) == report
    assert {'authored_counted_quantity_request_v4','prepare_counted_quantity_v4','validate_counted_quantity_v4'} <= set(subject.__all__)



# Explicit capacity-only opt-in; mathematical expansion/default wire stay unchanged.
def test_expanded_nat_capacity_is_explicit_and_unknown_null_profiles_refuse(monkeypatch):
    profile = subject.PARAMETRIC_EXPANDED_CAPACITY_PROFILE
    default = subject.authored_counted_threshold_request_v3(4)
    assert 'capacity_profile' not in default
    assert default == subject.authored_counted_threshold_request_v3(4, capacity_profile=None)
    for value in ('unknown', False, {}, 1):
        with pytest.raises(ValueError):
            subject.authored_counted_threshold_request_v3(10, capacity_profile=value)
    request = subject.authored_counted_threshold_request_v3(10, capacity_profile=profile)
    assert request['capacity_profile'] == profile and request['maximum'] == 10
    altered = deepcopy(default); altered['capacity_profile'] = None
    raw = wire(altered)
    with pytest.raises(ValueError):
        subject.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    monkeypatch.setattr(subject, '_base', lambda: pytest.fail('overbudget reached base owner'))
    with pytest.raises(ValueError):subject.authored_counted_threshold_request_v3(10)
    with pytest.raises(ValueError):subject.authored_counted_threshold_request_v3(14, capacity_profile=profile)


def test_expanded_nat_ten_replays_real_ir_full_fol_and_same_cardinality():
    profile = subject.PARAMETRIC_EXPANDED_CAPACITY_PROFILE
    request = subject.authored_counted_threshold_request_v3(10, capacity_profile=profile)
    raw = wire(request)
    report = subject.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    assert report['maximum'] == 10 and report['capacity_profile'] == profile
    assert report['counts']['nodes'] == 287 and report['parametric_budget']['ast_depth'] == 69
    assert ast.TypedExpression.from_dict(report['typed_expression']).to_dict() == report['typed_expression']
    assert report['fol_receipt']['binary_connective_grouping_preserved'] is True
    assert subject.validate_counted_threshold_v3(report, raw,
        expected_request_sha256=sha(raw), expected_report_sha256=sha(wire(report))) == report
    assert subject.validate_counted_threshold_v3(wire(report), raw,
        expected_request_sha256=sha(raw), expected_report_sha256=sha(wire(report))) == report
    damaged = deepcopy(report); damaged['capacity_profile'] = 'unknown'
    with pytest.raises(ValueError):subject.validate_counted_threshold_v3(damaged, raw,
        expected_request_sha256=sha(raw), expected_report_sha256=sha(wire(damaged)))
    assert not any(report['authority'].values())


def test_expanded_nat_capacity_does_not_change_default_replay():
    request = subject.authored_counted_threshold_request_v3(4)
    raw = wire(request)
    prior = subject.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    subject.authored_counted_threshold_request_v3(10, capacity_profile=subject.PARAMETRIC_EXPANDED_CAPACITY_PROFILE)
    assert subject.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw)) == prior
    assert 'capacity_profile' not in prior


def test_expanded_capacity_private_numeric_overrides_remain_plain_integers():
    profile = subject.PARAMETRIC_EXPANDED_CAPACITY_PROFILE
    for key,value in (("max_nodes",4096.0),("max_depth",32.0),("max_bytes",131072.0),("max_json_depth",64.0),("max_json_items",20000.0)):
        with pytest.raises(ValueError):subject._parametric_budget(10,capacity_profile=profile,**{key:value})
