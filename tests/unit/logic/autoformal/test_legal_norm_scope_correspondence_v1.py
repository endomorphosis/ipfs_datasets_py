"""Authored source/AST correspondence tests; no reviewed statutory meaning."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as subject
from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
from ipfs_datasets_py.logic.autoformal import legal_source_norm_scope_v1 as source_scope


def _fixture(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scope_fixture = _fixture("_correspondence_scope_fixture", "test_legal_source_norm_scope_v1.py")
relational_fixture = _fixture("_correspondence_relational_fixture", "test_legal_relational_norm_v1.py")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def pointer(document, path):
    for token in path.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        document = document[int(token)] if type(document) is list else document[token]
    return document


def authored_request(*, sufficient=False, operator="P", swapped=False):
    builder = relational_fixture.Builder()
    action = builder.atom("Retain", *( ("object", "actor") if swapped else ("actor", "object") ))
    approved = builder.atom("Approved", "actor")
    permitted = builder.modal(operator, action)
    body = builder.binary("implies", approved, permitted) if sufficient else \
        builder.binary("implies", permitted, approved)
    return relational_fixture.request_for(builder, body,
        [("Retain", ("actor", "object")), ("Approved", ("actor",))],
        [("actor", "forall"), ("object", "forall")])


def case(*, duplicate=False, edition=2024, sufficient=False, operator="P", swapped=False):
    source = scope_fixture.case(duplicate=duplicate, edition=edition)
    scope_report = scope_fixture.prepare(source)
    scope_request_raw, scope_declaration_raw, scope_keywords = scope_fixture.preparation_inputs(source)
    relational_request = authored_request(sufficient=sufficient, operator=operator, swapped=swapped)
    relational_raw = wire(relational_request)
    relational_report = relational.prepare_relational_norm_v1(relational_raw,
        expected_request_sha256=hashlib.sha256(relational_raw).hexdigest())
    value = {
        "source": source, "scope_report": scope_report, "relational_report": relational_report,
        "scope_replay_inputs": {"sampling_report": source["sampling"], "raw_html": source["raw"],
            "scope_request_raw": scope_request_raw, "scope_declaration_raw": scope_declaration_raw,
            **scope_keywords},
        "relational_request_raw": relational_raw,
    }
    mapping = relational_report["structural_mapping"]
    expression = relational_report["typed_expression"]

    def selected(kind=None, symbol=None, binder=None):
        result = []
        for target in mapping:
            if kind is not None and target["kind"] != kind:
                continue
            if binder is not None and target.get("binder_name") != binder:
                continue
            if symbol is not None and pointer(expression, target["typed_path"]).get("symbol") != symbol:
                continue
            result.append(deepcopy(target))
        return result

    choices = {
        "/occurrences/0/anchor": selected("binder", binder="actor") + selected("variable", "actor"),
        "/occurrences/1/anchor": selected("legacy.deontic/v1"),
        "/occurrences/2/anchor": selected("predicate", "Retain"),
        "/occurrences/3/anchor": selected("binder", binder="object") + selected("variable", "object"),
        "/unresolved/0/span": selected("predicate", "Approved") + selected("implies"),
    }
    source_rows = []
    for anchor in scope_report["anchor_mappings"]:
        path = anchor["declaration_path"]
        targets = choices.get(path, [])
        source_rows.append({"anchor_mapping": deepcopy(anchor),
            "disposition": "proposed_mapping" if targets else "literal_accounting",
            "targets": targets,
            "rationale": "Authored proposed association; uncertainty and all source text remain retained."})
    request = {"schema": "legal-norm-scope-correspondence-request/v1",
        "interpretation_status": "authored_unreviewed_correspondence",
        "alternative_id": "fictional-approval-" + ("sufficient" if sufficient else "necessary"),
        "scope_report_sha256": source_scope.sampled_norm_scope_report_sha256(scope_report),
        "relational_report_sha256": relational.relational_norm_report_sha256(relational_report),
        "source_rows": source_rows, "typed_rows": []}
    value["mapping"] = request
    rebuild_inverse(value)
    return value


def rebuild_inverse(value):
    source_rows = value["mapping"]["source_rows"]
    value["mapping"]["typed_rows"] = []
    for target in value["relational_report"]["structural_mapping"]:
        paths = [row["anchor_mapping"]["declaration_path"] for row in source_rows
                 if target in row["targets"]]
        value["mapping"]["typed_rows"].append({"target": deepcopy(target),
            "disposition": "source_linked" if paths else "authored_scaffolding",
            "source_paths": paths,
            "rationale": "Exact inverse association; the source meaning is not accepted."})


def source_row(value, path):
    return next(row for row in value["mapping"]["source_rows"]
                if row["anchor_mapping"]["declaration_path"] == path)


def arguments(value, mapping_raw=None):
    raw = wire(value["mapping"]) if mapping_raw is None else mapping_raw
    return (value["scope_report"], value["relational_report"], raw), {
        "expected_scope_report_sha256": source_scope.sampled_norm_scope_report_sha256(value["scope_report"]),
        "expected_relational_report_sha256": relational.relational_norm_report_sha256(value["relational_report"]),
        "expected_mapping_request_sha256": hashlib.sha256(raw).hexdigest(),
        "scope_replay_inputs": value["scope_replay_inputs"],
        "relational_request_raw": value["relational_request_raw"],
        "expected_relational_request_sha256": hashlib.sha256(value["relational_request_raw"]).hexdigest(),
    }


def prepare(value, mapping_raw=None):
    args, kwargs = arguments(value, mapping_raw)
    return subject.prepare_norm_scope_correspondence_v1(*args, **kwargs)


def validate(report, value):
    args, kwargs = arguments(value)
    return subject.validate_norm_scope_correspondence_v1(report, *args,
        expected_report_sha256=subject.norm_scope_correspondence_sha256(report), **kwargs)


def assert_no_authority(value):
    if type(value) is dict:
        for key, child in value.items():
            if key == "authority":
                assert type(child) is dict and child
                assert all(flag is False for flag in child.values())
            elif key == "masks":
                assert all(type(mask) is int and mask == 0 for mask in child.values())
            elif key in {"training_mask", "evaluation_gold_mask"}:
                assert type(child) is int and child == 0
            assert_no_authority(child)
    elif type(value) is list:
        for child in value:
            assert_no_authority(child)


def test_exact_source_and_typed_rows_replay_without_promoting_authored_meaning():
    value = case()
    before = deepcopy(value)
    report = prepare(value)
    receipt = validate(report, value)
    assert value == before
    assert_no_authority(report)
    assert_no_authority(receipt)
    assert value["scope_report"]["scope_declaration"]["unresolved"] == before["scope_report"]["scope_declaration"]["unresolved"]
    assert value["scope_report"]["declared_semantic_coverage"] == "partial"
    assert value["relational_report"]["source_binding"] is None
    assert value["relational_report"]["source_bound"] is False
    assert report["source_scope"] == before["scope_report"]
    assert report["relational_fragment"] == before["relational_report"]
    assert report["request"] == before["mapping"]
    assert report["retained_unresolved"] == before["source"]["declaration"]["unresolved"]
    assert report["declared_semantic_coverage"] == "partial"
    assert report["transport_checked"] is True
    assert report["source_bound"] is report["source_translation_performed"] is False
    assert report["original_signatures_cover_correspondence"] is False
    assert report["selected_interpretation"] is report["governing_definition_use"] is None
    assert report["human_reviews"] == report["signatures_constructed"] == report["admissions"] == 0
    assert report["counts"]["source_anchors"] == len(before["scope_report"]["anchor_mappings"])
    assert report["counts"]["typed_targets"] == len(before["relational_report"]["structural_mapping"])
    assert report["counts"]["proposed_links"] == sum(len(row["targets"]) for row in before["mapping"]["source_rows"])
    assert prepare(value) == report


@pytest.mark.parametrize("sufficient,swapped", [(False, False), (True, False), (False, True)])
def test_derived_inventory_preserves_bound_variables_roles_modal_and_implication_scope(sufficient, swapped):
    value = case(sufficient=sufficient, swapped=swapped)
    report = prepare(value)
    inventory = report["typed_context_inventory"]
    expression = value["relational_report"]["typed_expression"]
    assert [row["target"] for row in inventory] == value["relational_report"]["structural_mapping"]
    variable_count = 0
    for entry in inventory:
        target = entry["target"]
        if target["kind"] != "variable":
            assert entry["binding"] is entry["argument"] is None
            continue
        variable_count += 1
        variable = pointer(expression, target["typed_path"])
        binding, argument = entry["binding"], entry["argument"]
        assert variable["symbol"] == binding["name"]
        assert pointer(expression, binding["typed_path"])["name"] == binding["name"]
        assert binding["quantifier"] == "forall"
        predicate = pointer(expression, argument["predicate_path"])
        assert predicate["symbol"] == argument["symbol"]
        assert predicate["arguments"][argument["index"]] == variable
        roles = next(row["roles"] for row in value["relational_report"]["argument_roles"]
                     if row["symbol"] == argument["symbol"])
        assert roles[argument["index"]] == argument["role"]
        modal_ancestors = [ancestor for ancestor in entry["ancestry"] if ancestor["kind"] == "legacy.deontic/v1"]
        implication = next(ancestor for ancestor in entry["ancestry"] if ancestor["kind"] == "implies")
        if argument["symbol"] == "Retain":
            assert [ancestor["operator"] for ancestor in modal_ancestors] == ["P"]
            assert implication["relative_path"].startswith("/arguments/" + ("1" if sufficient else "0") + "/")
            expected_variable = ("object", "actor")[argument["index"]] if swapped else roles[argument["index"]]
            assert binding["name"] == expected_variable
        else:
            assert argument["symbol"] == "Approved" and modal_ancestors == []
            assert implication["relative_path"].startswith("/arguments/" + ("0" if sufficient else "1") + "/")
    assert variable_count == 3


def test_authored_necessity_and_sufficiency_have_distinct_formulas_and_correspondences():
    necessary, sufficient = case(), case(sufficient=True)
    first, second = prepare(necessary), prepare(sufficient)
    assert first != second
    assert subject.norm_scope_correspondence_sha256(first) != subject.norm_scope_correspondence_sha256(second)
    assert necessary["scope_report"] == sufficient["scope_report"]
    assert necessary["relational_report"]["native_ast"] != sufficient["relational_report"]["native_ast"]
    atoms = lambda name, args, at: name == "Approved"
    modal = lambda operator, body, at: False
    assert relational_fixture.evaluate(necessary["relational_report"]["native_ast"], atoms, modal=modal) is True
    assert relational_fixture.evaluate(sufficient["relational_report"]["native_ast"], atoms, modal=modal) is False
    assert_no_authority(first)
    assert_no_authority(second)


def test_argument_swap_is_retained_as_distinct_authored_choice_not_silently_corrected():
    original, swapped = case(), case(swapped=True)
    first, second = prepare(original), prepare(swapped)
    assert first != second
    assert original["relational_report"]["argument_roles"] == swapped["relational_report"]["argument_roles"]
    assert original["relational_report"]["native_ast"] != swapped["relational_report"]["native_ast"]
    assert_no_authority(first)
    assert_no_authority(second)


@pytest.mark.parametrize("disposition", ["unresolved", "unsupported"])
def test_unmapped_occurrences_and_issues_remain_explicit(disposition):
    value = case()
    for row in value["mapping"]["source_rows"]:
        if not row["anchor_mapping"]["declaration_path"].startswith("/coverage/"):
            row["disposition"], row["targets"] = disposition, []
    rebuild_inverse(value)
    report = prepare(value)
    validate(report, value)
    assert_no_authority(report)


@pytest.mark.parametrize("damage", ["missing_source", "extra_source", "source_order", "source_geometry",
    "source_path", "missing_typed", "extra_typed", "typed_order", "typed_node", "typed_native_path",
    "missing_inverse", "extra_inverse", "inverse_order", "wrong_disposition", "duplicate_target",
    "empty_target", "unresolved_target", "accounting_target", "occurrence_accounting", "unknown_disposition"])
def test_complete_ordered_accounting_refuses_forged_or_inconsistent_rows(damage):
    value = case()
    rows, typed = value["mapping"]["source_rows"], value["mapping"]["typed_rows"]
    actor_row = source_row(value, "/occurrences/0/anchor")
    object_row = source_row(value, "/occurrences/3/anchor")
    if damage == "missing_source": rows.pop()
    elif damage == "extra_source": rows.append(deepcopy(actor_row))
    elif damage == "source_order": rows.reverse()
    elif damage == "source_geometry": actor_row["anchor_mapping"]["local_anchor"]["start"] += 1
    elif damage == "source_path": actor_row["anchor_mapping"]["declaration_path"] = "/unavailable/anchor"
    elif damage == "missing_typed": typed.pop()
    elif damage == "extra_typed": typed.append(deepcopy(typed[0]))
    elif damage == "typed_order": typed.reverse()
    elif damage == "typed_node":
        next(row for row in typed if "node_id" in row["target"])["target"]["node_id"] = "invented:node"
    elif damage == "typed_native_path": typed[0]["target"]["native_path"] = "/different"
    elif damage == "missing_inverse": next(row for row in typed if row["source_paths"])["source_paths"] = []
    elif damage == "extra_inverse": typed[0]["source_paths"] = [actor_row["anchor_mapping"]["declaration_path"]]
    elif damage == "inverse_order":
        # Two source anchors may nominate the same variable, but the inverse
        # must remain in source order even if both authored links are legal.
        actor = actor_row["targets"][0]
        object_row["targets"].append(deepcopy(actor))
        rebuild_inverse(value)
        next(row for row in value["mapping"]["typed_rows"] if len(row["source_paths"]) == 2)["source_paths"].reverse()
    elif damage == "wrong_disposition": next(row for row in typed if row["source_paths"])["disposition"] = "authored_scaffolding"
    elif damage == "duplicate_target": actor_row["targets"].append(deepcopy(actor_row["targets"][0]))
    elif damage == "empty_target": actor_row["targets"] = []
    elif damage == "unresolved_target": actor_row["disposition"] = "unresolved"
    elif damage == "accounting_target":
        row = next(row for row in rows if row["disposition"] == "literal_accounting")
        row["disposition"], row["targets"] = "proposed_mapping", deepcopy(actor_row["targets"])
    elif damage == "occurrence_accounting": actor_row["disposition"], actor_row["targets"] = "literal_accounting", []
    else: actor_row["disposition"] = "reviewed"
    with pytest.raises(ValueError): prepare(value)


@pytest.mark.parametrize("damage", ["modal_to_predicate", "modal_to_extension_wrapper", "actor_to_predicate",
    "object_to_modal", "action_to_variable", "wrong_modal_O", "wrong_modal_F"])
def test_facets_refuse_incompatible_target_kinds_and_modal_letters(damage):
    value = case(operator=damage[-1]) if damage.startswith("wrong_modal_") else case()
    targets = value["relational_report"]["structural_mapping"]
    if damage == "modal_to_predicate": source_row(value, "/occurrences/1/anchor")["targets"] = [next(row for row in targets if row["kind"] == "predicate")]
    elif damage == "modal_to_extension_wrapper": source_row(value, "/occurrences/1/anchor")["targets"] = [next(row for row in targets if row["kind"] == "extension")]
    elif damage == "actor_to_predicate": source_row(value, "/occurrences/0/anchor")["targets"] = [next(row for row in targets if row["kind"] == "predicate")]
    elif damage == "object_to_modal": source_row(value, "/occurrences/3/anchor")["targets"] = [next(row for row in targets if row["kind"] == "legacy.deontic/v1")]
    elif damage == "action_to_variable": source_row(value, "/occurrences/2/anchor")["targets"] = [next(row for row in targets if row["kind"] == "variable")]
    rebuild_inverse(value)
    with pytest.raises(ValueError): prepare(value)


@pytest.mark.parametrize("field", ["scope_report_sha256", "relational_report_sha256"])
def test_request_must_bind_exact_independently_supplied_reports(field):
    value = case()
    value["mapping"][field] = "0" * 64
    with pytest.raises(ValueError): prepare(value)


@pytest.mark.parametrize("damage", ["extra_field", "missing_field", "wrong_schema", "wrong_status",
    "empty_alternative", "unsafe_alternative", "empty_rationale", "long_rationale", "padded_rationale", "extra_source_field",
    "extra_typed_field", "source_paths_string", "targets_string"])
def test_closed_request_and_bounded_explicit_rationales(damage):
    value = case()
    request = value["mapping"]
    if damage == "extra_field": request["approved"] = True
    elif damage == "missing_field": del request["alternative_id"]
    elif damage == "wrong_schema": request["schema"] = "other/v1"
    elif damage == "wrong_status": request["interpretation_status"] = "accepted"
    elif damage == "empty_alternative": request["alternative_id"] = ""
    elif damage == "unsafe_alternative": request["alternative_id"] = "../selected"
    elif damage == "empty_rationale": source_row(value, "/occurrences/0/anchor")["rationale"] = ""
    elif damage == "long_rationale": request["typed_rows"][0]["rationale"] = "x" * 2049
    elif damage == "padded_rationale": request["typed_rows"][0]["rationale"] = "x" + " " * 2048
    elif damage == "extra_source_field": source_row(value, "/occurrences/0/anchor")["approved"] = True
    elif damage == "extra_typed_field": request["typed_rows"][0]["approved"] = True
    elif damage == "source_paths_string": request["typed_rows"][0]["source_paths"] = "/root"
    else: source_row(value, "/occurrences/0/anchor")["targets"] = "/root"
    with pytest.raises(ValueError): prepare(value)


@pytest.mark.parametrize("replacement", ["occurrence", "edition"])
def test_same_spelling_is_not_an_interchangeable_source_identity(replacement):
    value = case(duplicate=replacement == "occurrence")
    report = prepare(value)
    if replacement == "edition":
        changed = case(edition=2023)
    else:
        changed = deepcopy(value)
        changed["scope_replay_inputs"]["selected_unit_ref"] = scope_fixture.reference(value["source"]["units"][1])
    with pytest.raises(ValueError): validate(report, changed)


@pytest.mark.parametrize("damage", ["scope_request_bytes", "scope_declaration_bytes", "raw_html", "descriptor",
    "relational_request", "source_coverage", "unresolved_issue", "native_tree", "typed_mapping"])
def test_repaired_outer_hashes_cannot_hide_changes_to_original_replay_inputs(damage):
    value = case()
    if damage == "scope_request_bytes": value["scope_replay_inputs"]["scope_request_raw"] += b" "
    elif damage == "scope_declaration_bytes": value["scope_replay_inputs"]["scope_declaration_raw"] += b" "
    elif damage == "raw_html": value["scope_replay_inputs"]["raw_html"] += b" "
    elif damage == "descriptor": value["scope_replay_inputs"]["descriptor"]["edition"] = 2023
    elif damage == "relational_request":
        request = json.loads(value["relational_request_raw"])
        request["interpretation_status"] = "reviewed"
        value["relational_request_raw"] = wire(request)
    elif damage == "source_coverage": value["scope_report"]["scope_declaration"]["coverage"]["segments"].pop()
    elif damage == "unresolved_issue": value["scope_report"]["scope_declaration"]["unresolved"].pop()
    elif damage == "native_tree": value["relational_report"]["native_ast"]["variable"]["name"] = "different"
    else: value["relational_report"]["structural_mapping"].pop()
    value["mapping"]["scope_report_sha256"] = source_scope.sampled_norm_scope_report_sha256(value["scope_report"])
    value["mapping"]["relational_report_sha256"] = relational.relational_norm_report_sha256(value["relational_report"])
    with pytest.raises(ValueError): prepare(value)


def test_report_change_with_repaired_checksum_still_fails_complete_replay():
    value = case()
    report = prepare(value)
    report["invented_acceptance"] = True
    with pytest.raises(ValueError): validate(report, value)


def test_outputs_are_detached_from_input_reports_and_mapping_declarations():
    value = case()
    before = deepcopy(value)
    report = prepare(value)
    report.clear()
    assert value == before
    assert prepare(value)


@pytest.mark.parametrize("damage", ["duplicate_json", "nested_duplicate", "nan", "bad_utf8", "oversize",
    "mapping_hash", "scope_hash", "relational_hash", "relational_request_hash", "raw_count_bool",
    "raw_hash", "descriptor_hash", "sampling_hash", "nonordinary_scope", "extra_replay", "missing_replay"])
def test_bounded_and_independently_pinned_preflight_precedes_operation_loading(monkeypatch, damage):
    value = case()
    args, kwargs = arguments(value)
    args = list(args)
    if damage == "duplicate_json": args[2] = b'{"schema":"first","schema":"second"}'
    elif damage == "nested_duplicate": args[2] = b'{"source_rows":[{"rationale":"a","rationale":"b"}]}'
    elif damage == "nan": args[2] = b'{"source_rows":NaN}'
    elif damage == "bad_utf8": args[2] = b'{"schema":"\xff"}'
    elif damage == "oversize": args[2] = b" " * (subject.MAX_REQUEST_BYTES + 1)
    elif damage == "mapping_hash": kwargs["expected_mapping_request_sha256"] = "0" * 64
    elif damage == "scope_hash": kwargs["expected_scope_report_sha256"] = "0" * 64
    elif damage == "relational_hash": kwargs["expected_relational_report_sha256"] = "0" * 64
    elif damage == "relational_request_hash": kwargs["expected_relational_request_sha256"] = "0" * 64
    elif damage == "raw_count_bool": kwargs["scope_replay_inputs"]["expected_raw_bytes"] = True
    elif damage == "raw_hash": kwargs["scope_replay_inputs"]["expected_raw_sha256"] = "0" * 64
    elif damage == "descriptor_hash": kwargs["scope_replay_inputs"]["expected_descriptor_sha256"] = "0" * 64
    elif damage == "sampling_hash": kwargs["scope_replay_inputs"]["expected_sampling_report_sha256"] = "0" * 64
    elif damage == "nonordinary_scope": args[0]["authority"] = object()
    elif damage == "extra_replay": kwargs["scope_replay_inputs"]["untrusted_loader"] = "unused"
    else: del kwargs["scope_replay_inputs"]["descriptor"]
    if damage in {"duplicate_json", "nested_duplicate", "nan", "bad_utf8", "oversize"}:
        kwargs["expected_mapping_request_sha256"] = hashlib.sha256(args[2]).hexdigest()

    def deny():
        raise AssertionError("operation owners loaded before preflight rejection")
    monkeypatch.setattr(subject, "_owners", deny)
    with pytest.raises(ValueError):
        subject.prepare_norm_scope_correspondence_v1(*args, **kwargs)


@pytest.mark.parametrize("field", ["scope_request_raw", "scope_declaration_raw", "relational_request_raw"])
def test_repaired_raw_pins_do_not_allow_duplicate_nested_json_before_operation_imports(monkeypatch, field):
    value = case()
    duplicate = b'{"nested":{"source":"first","source":"second"}}'
    if field == "relational_request_raw":
        value[field] = duplicate
    else:
        value["scope_replay_inputs"][field] = duplicate
        pin_field = {"scope_request_raw": "expected_scope_request_sha256",
                     "scope_declaration_raw": "expected_scope_declaration_sha256"}[field]
        value["scope_replay_inputs"][pin_field] = hashlib.sha256(duplicate).hexdigest()

    def deny(_):
        raise AssertionError("operation-owner loading reached for malformed retained JSON")
    monkeypatch.setattr(subject, "_pins", deny)
    with pytest.raises(ValueError):
        prepare(value)


@pytest.mark.parametrize("damage", ["bool_anchor", "float_anchor", "bool_target_index"])
def test_python_numeric_equality_does_not_substitute_for_exact_json_identity(damage):
    value = case()
    if damage == "bool_anchor":
        anchor = source_row(value, "/occurrences/0/anchor")["anchor_mapping"]["local_anchor"]
        assert anchor["start"] == 0
        anchor["start"] = False
    elif damage == "float_anchor":
        row = source_row(value, "/occurrences/0/anchor")["anchor_mapping"]["local_anchor"]
        row["end"] = float(row["end"])
    else:
        # Node IDs are identities; a bool cannot become a string-like ordinal.
        next(row for row in value["mapping"]["typed_rows"] if "node_id" in row["target"])["target"]["node_id"] = True
    with pytest.raises(ValueError): prepare(value)


@pytest.mark.parametrize("damage", ["retained_issue", "derived_binder", "derived_role", "derived_ancestry",
    "training_bool", "authority", "source_scope", "relational_fragment", "request", "producer_pin"])
def test_rehashed_output_cannot_change_retained_inputs_or_derived_structure(damage):
    value = case()
    report = prepare(value)
    if damage == "retained_issue": report["retained_unresolved"] = []
    elif damage == "derived_binder":
        next(row for row in report["typed_context_inventory"] if row["binding"] is not None)["binding"]["name"] = "object"
    elif damage == "derived_role":
        next(row for row in report["typed_context_inventory"] if row["argument"] is not None)["argument"]["role"] = "recipient"
    elif damage == "derived_ancestry":
        next(row for row in report["typed_context_inventory"] if row["ancestry"])["ancestry"] = []
    elif damage == "training_bool": report["training_mask"] = False
    elif damage == "authority": report["authority"]["accepted"] = True
    elif damage == "source_scope": report["source_scope"]["declared_semantic_coverage"] = "complete"
    elif damage == "relational_fragment": report["relational_fragment"]["source_bound"] = True
    elif damage == "request": report["request"]["alternative_id"] = "silently-selected"
    else: report["producer_pins"][str(Path(subject.__file__).resolve())] = "0" * 64
    with pytest.raises(ValueError, match="complete replay"):
        validate(report, value)


@pytest.mark.parametrize("location", ["caller", "detached"])
def test_inputs_changed_during_owner_replay_are_refused(monkeypatch, location):
    value = case()
    original = source_scope.validate_sampled_norm_scope_v1

    def mutate_after_validation(report, *args, **kwargs):
        result = original(report, *args, **kwargs)
        if location == "caller":
            value["scope_report"]["training_mask"] = False
        else:
            report["training_mask"] = False
        return result

    monkeypatch.setattr(source_scope, "validate_sampled_norm_scope_v1", mutate_after_validation)
    with pytest.raises(ValueError, match="inputs changed during"):
        prepare(value)


@pytest.mark.parametrize("moment", ["after_replay", "after_serialization"])
def test_producer_bytes_are_checked_after_owner_work_and_final_serialization(monkeypatch, tmp_path, moment):
    value = case()
    original_bytes = Path(subject.__file__).read_bytes()
    copied_owner = tmp_path / "legal_norm_scope_correspondence_v1.py"
    copied_owner.write_bytes(original_bytes)
    monkeypatch.setattr(subject, "__file__", str(copied_owner))
    monkeypatch.setattr(subject, "_OWNER_PINS", None)
    observed = []
    if moment == "after_replay":
        original = relational.validate_relational_norm_v1

        def mutate_after_replay(*args, **kwargs):
            result = original(*args, **kwargs)
            observed.append("relational_replay_completed")
            copied_owner.write_bytes(original_bytes + b"\n# changed during correspondence\n")
            return result
        monkeypatch.setattr(relational, "validate_relational_norm_v1", mutate_after_replay)
    else:
        original = subject._wire

        def mutate_after_serialization(value, maximum):
            raw = original(value, maximum)
            if type(value) is dict and value.get("schema") == subject.SCHEMA:
                observed.append("report_serialization_completed")
                copied_owner.write_bytes(original_bytes + b"\n# changed after serialization\n")
            return raw
        monkeypatch.setattr(subject, "_wire", mutate_after_serialization)
    with pytest.raises(ValueError, match="correspondence producer changed"):
        prepare(value)
    assert len(observed) == 1
    assert copied_owner.read_bytes() != original_bytes



# Parent correspondence uses genuine physical parent replay plus the unchanged
# relational typed owner. All proposed meaning remains authored and unreviewed.
def parent_correspondence_case(tmp_path, *, source_value=None):
    source = scope_fixture.parent_case(tmp_path) if source_value is None else source_value
    scope_report = scope_fixture.parent_prepare(source)
    scope_args,scope_kwargs = scope_fixture.parent_arguments(source)
    request = authored_request()
    request_raw = wire(request)
    relational_report = relational.prepare_relational_norm_v1(request_raw,
        expected_request_sha256=hashlib.sha256(request_raw).hexdigest())
    expression = relational_report["typed_expression"]
    def chosen(kind=None,symbol=None,binder=None):
        result = []
        for target in relational_report["structural_mapping"]:
            if kind is not None and target["kind"] != kind: continue
            if binder is not None and target.get("binder_name") != binder: continue
            if symbol is not None and pointer(expression,target["typed_path"]).get("symbol") != symbol: continue
            result.append(deepcopy(target))
        return result
    choices = {
        "/occurrences/0/anchor":chosen("binder",binder="actor")+chosen("variable","actor"),
        "/occurrences/1/anchor":chosen("legacy.deontic/v1"),
        "/occurrences/2/anchor":chosen("predicate","Retain"),
        "/occurrences/3/anchor":chosen("binder",binder="object")+chosen("variable","object"),
        "/unresolved/0/span":chosen("predicate","Approved")+chosen("implies")}
    source_rows = []
    for item in scope_report["anchor_mappings"]:
        targets = choices.get(item["declaration_path"],[])
        source_rows.append(dict(anchor_mapping=deepcopy(item),disposition="proposed_mapping" if targets else "literal_accounting",
            targets=targets,rationale="Authored correspondence; no reviewed source meaning."))
    value = dict(source=source,scope_report=scope_report,relational_report=relational_report,
        scope_replay_inputs=dict(parent_bundle=scope_args[0],scope_request_raw=scope_args[1],scope_declaration_raw=scope_args[2],**scope_kwargs),
        relational_request_raw=request_raw,
        mapping=dict(schema="legal-norm-scope-correspondence-request/v2",interpretation_status="authored_unreviewed_correspondence",
            alternative_id="parent-literal-authored-approval",source_rows=source_rows,typed_rows=[],
            scope_report_sha256=source_scope.parent_norm_scope_report_sha256(scope_report),
            relational_report_sha256=relational.relational_norm_report_sha256(relational_report)))
    rebuild_inverse(value)
    return value


def parent_correspondence_arguments(value,mapping_raw=None):
    raw = wire(value["mapping"]) if mapping_raw is None else mapping_raw
    return (value["scope_report"],value["relational_report"],raw),dict(
        expected_scope_report_sha256=source_scope.parent_norm_scope_report_sha256(value["scope_report"]),
        expected_relational_report_sha256=relational.relational_norm_report_sha256(value["relational_report"]),
        expected_mapping_request_sha256=hashlib.sha256(raw).hexdigest(),scope_replay_inputs=value["scope_replay_inputs"],
        relational_request_raw=value["relational_request_raw"],
        expected_relational_request_sha256=hashlib.sha256(value["relational_request_raw"]).hexdigest())


def parent_correspondence_prepare(value):
    args,kwargs = parent_correspondence_arguments(value)
    return subject.prepare_norm_scope_correspondence_v2(*args,**kwargs)


def parent_correspondence_validate(report,value):
    args,kwargs = parent_correspondence_arguments(value)
    return subject.validate_norm_scope_correspondence_v2(report,*args,
        expected_report_sha256=subject.norm_scope_correspondence_sha256(report),**kwargs)


def test_parent_correspondence_v2_accounts_for_all_literal_and_typed_paths_without_authority(tmp_path):
    value = parent_correspondence_case(tmp_path);report = parent_correspondence_prepare(value)
    assert report["schema"] == "legal-norm-scope-correspondence-report/v2"
    assert report["source_scope"] == value["scope_report"]
    assert report["relational_fragment"] == value["relational_report"]
    assert report["retained_unresolved"] == value["scope_report"]["scope_declaration"]["unresolved"]
    assert report["declared_semantic_coverage"] == "partial"
    assert report["counts"]["source_anchors"] == len(value["scope_report"]["anchor_mappings"])
    assert report["counts"]["typed_targets"] == len(value["relational_report"]["structural_mapping"])
    assert len(report["request"]["source_rows"]) == len(value["scope_report"]["anchor_mappings"])
    assert len(report["request"]["typed_rows"]) == len(value["relational_report"]["structural_mapping"])
    for row in report["request"]["typed_rows"]:
        paths = [item["anchor_mapping"]["declaration_path"] for item in report["request"]["source_rows"] if row["target"] in item["targets"]]
        assert row["source_paths"] == paths
    assert report["source_scope"]["parent_source_binding"]["context"]["availability"] == "required_unavailable"
    assert report["selected_interpretation"] is None and report["source_translation_performed"] is False
    assert_no_authority(report)
    assert parent_correspondence_validate(report,value) == report


def test_parent_correspondence_v2_identical_physical_text_does_not_alias_source_identity(tmp_path):
    first = parent_correspondence_case(tmp_path)
    source = first["source"]
    other = dict(source)
    companion = source["companions"][2]
    other["arguments"] = source["physical"].binding_arguments(source["original"],companion)
    other["source"] = source["physical"].bind(source["original"],companion)
    second = parent_correspondence_case(tmp_path,source_value=other)
    left,right = parent_correspondence_prepare(first),parent_correspondence_prepare(second)
    assert left["relational_fragment"] == right["relational_fragment"]
    assert left["source_scope"]["scope_request"] == right["source_scope"]["scope_request"]
    assert left["source_scope"]["source_selector"]["record_cid"] != right["source_scope"]["source_selector"]["record_cid"]
    assert subject.norm_scope_correspondence_sha256(left) != subject.norm_scope_correspondence_sha256(right)


@pytest.mark.parametrize("damage",["missing_source","missing_typed","cross_occurrence","semantic_promotion"])
def test_parent_correspondence_v2_resealed_mapping_cannot_drop_or_promote_source_meaning(tmp_path,damage):
    value = parent_correspondence_case(tmp_path)
    if damage == "missing_source": value["mapping"]["source_rows"].pop()
    elif damage == "missing_typed": value["mapping"]["typed_rows"].pop()
    elif damage == "cross_occurrence":
        value["mapping"]["source_rows"][0]["anchor_mapping"]["parent_selector"]["source_occurrence_cid"] = value["source"]["companions"][1]["source_occurrence_cid"]
    else: value["mapping"]["interpretation_status"] = "reviewed_source_translation"
    with pytest.raises(ValueError): parent_correspondence_prepare(value)


@pytest.mark.parametrize("damage",["report_bytes","parent_file"])
def test_parent_correspondence_v2_replays_original_parent_even_with_repaired_outer_pins(tmp_path,damage):
    value = parent_correspondence_case(tmp_path);replay = value["scope_replay_inputs"]
    if damage == "report_bytes":
        replay["report_bytes"]["parent_text_views"] += b" "
        replay["expected_report_pins"]["parent_text_views"]["raw_sha256"] = hashlib.sha256(
            replay["report_bytes"]["parent_text_views"]).hexdigest()
    else:
        path = Path(replay["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]["local_path"])
        path.write_bytes(path.read_bytes()+b"changed after scope preparation")
    with pytest.raises(ValueError): parent_correspondence_prepare(value)


@pytest.mark.parametrize("damage",["extra_replay_key","missing_replay_key"])
def test_parent_correspondence_v2_requires_closed_original_parent_replay_inputs(tmp_path,monkeypatch,damage):
    value = parent_correspondence_case(tmp_path)
    if damage == "extra_replay_key": value["scope_replay_inputs"]["loader_callback"] = "not accepted"
    else: del value["scope_replay_inputs"]["companion_record_cid"]
    monkeypatch.setattr(subject,"_parent_correspondence_pins",lambda *args:pytest.fail("physical operation owners loaded before closed replay preflight"))
    with pytest.raises(ValueError): parent_correspondence_prepare(value)


def test_parent_correspondence_v2_and_html_v1_remain_distinct_profiles(tmp_path):
    parent_value = parent_correspondence_case(tmp_path);parent_report = parent_correspondence_prepare(parent_value)
    html_value = case();html_report = prepare(html_value)
    args,kwargs = parent_correspondence_arguments(parent_value)
    with pytest.raises(ValueError): subject.prepare_norm_scope_correspondence_v1(*args,**kwargs)
    old_args,old_kwargs = arguments(html_value)
    with pytest.raises(ValueError): subject.prepare_norm_scope_correspondence_v2(*old_args,**old_kwargs)
    assert html_report["schema"] != parent_report["schema"]


@pytest.mark.parametrize("location",["caller","detached"])
def test_parent_correspondence_v2_refuses_late_scope_report_mutation(tmp_path,monkeypatch,location):
    value = parent_correspondence_case(tmp_path)
    real = source_scope.validate_parent_norm_scope_v1;observed = []
    def changed_after_real_validation(report,*args,**kwargs):
        result = real(report,*args,**kwargs)
        if not observed:
            observed.append("genuine_parent_validation_completed")
            target = value["scope_report"] if location == "caller" else report
            target["training_mask"] = False
        return result
    monkeypatch.setattr(source_scope,"validate_parent_norm_scope_v1",changed_after_real_validation)
    with pytest.raises(ValueError): parent_correspondence_prepare(value)
    assert observed == ["genuine_parent_validation_completed"]


def test_parent_correspondence_v2_producer_change_after_serialization_is_refused(tmp_path,monkeypatch):
    value = parent_correspondence_case(tmp_path)
    original_bytes = Path(subject.__file__).read_bytes()
    copied = tmp_path/"copied_legal_norm_scope_correspondence_v1.py"
    copied.write_bytes(original_bytes)
    monkeypatch.setattr(subject,"__file__",str(copied))
    monkeypatch.setattr(subject,"_PARENT_OWNER_PINS",None)
    real = subject._wire;observed = []
    def changed_after_serialization(report,maximum):
        raw = real(report,maximum)
        if type(report) is dict and report.get("schema") == subject.SCHEMA_V2 and not observed:
            observed.append("parent_correspondence_serialized")
            copied.write_bytes(original_bytes+b"\n# changed after correspondence serialization\n")
        return raw
    monkeypatch.setattr(subject,"_wire",changed_after_serialization)
    with pytest.raises(ValueError): parent_correspondence_prepare(value)
    assert observed == ["parent_correspondence_serialized"] and copied.read_bytes() != original_bytes


def test_parent_correspondence_v2_secondary_closeout_errors_preserve_primary_error(tmp_path,monkeypatch):
    value = parent_correspondence_case(tmp_path)
    real = relational.validate_relational_norm_v1;observed = []
    def real_relational_validation_then_primary(*args,**kwargs):
        real(*args,**kwargs)
        observed.append("genuine_relational_validation_completed")
        value["scope_report"]["training_mask"] = False
        raise ValueError("primary authored correspondence failure")
    monkeypatch.setattr(relational,"validate_relational_norm_v1",real_relational_validation_then_primary)
    with pytest.raises(ValueError) as caught:
        parent_correspondence_prepare(value)
    assert str(caught.value) == "primary authored correspondence failure"
    assert observed
    assert any("secondary parent custody failure" in note for note in getattr(caught.value,"__notes__",[]))
