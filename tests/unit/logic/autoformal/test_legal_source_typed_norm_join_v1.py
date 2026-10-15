"""Fictional correspondence proposals retain syntax without source authority."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_typed_norm_join_v1 as subject
from ipfs_datasets_py.logic.autoformal import legal_source_norm_scope_v1 as source_scope
from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampling
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.legal_ir import canonical_statement_scope as lexical_scope


def _fixture_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_source_fixtures = _fixture_module("_join_source_fixtures", "test_legal_source_norm_scope_v1.py")
_typed_fixtures = _fixture_module("_join_typed_fixtures", "test_legal_relational_norm_v1.py")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def raw_digest(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return raw_digest(wire(value))


def source_case(*, duplicate=False, edition=2024):
    text = "Clérks may be assigned or transferred to café duties only with approval."
    paragraph = '<p class="statutory-body">' + text + "</p>"
    raw = _source_fixtures._fixture.fixture(statute=paragraph * (2 if duplicate else 1), notes="")
    args = _source_fixtures._fixture.inputs(raw)
    if edition != 2024:
        descriptor = args["descriptor"]
        descriptor["edition"] = edition
        for field in ("package_id", "granule_id", "url"):
            descriptor[field] = descriptor[field].replace("2024", str(edition))
        for field in ("requested_url", "final_url"):
            descriptor["http_provenance"][field] = descriptor["url"]
        args["expected_descriptor_sha256"] = custody.acquisition_descriptor_sha256(descriptor)
    sampled = sampling.prepare_source_sampling(raw, **args)
    units = [row for row in sampled["records"]
             if row["schema"] == sampling.UNIT_SCHEMA and row["candidate_input"]]
    request = {"source_text": text,
               "context": {"role": "required_unavailable", "text": "", "bindings": {},
                           "sha256": raw_digest(b"")}}
    occurrences = []
    for identity, facet, literal, symbol in (
        ("subject", "actor", "Clérks", "Clérks"),
        ("modal", "modality", "may", "P"),
        ("action", "action", "be assigned or transferred", "be assigned or transferred"),
        ("duties", "object", "to café duties", "to café duties"),
    ):
        start = text.index(literal)
        occurrences.append({"occurrence_id": identity, "facet": facet,
                            "canonical_symbol": symbol,
                            "anchor": _source_fixtures.anchor(text, start, start + len(literal))})
    approval_start = text.index("only with")
    declaration = {
        "schema": lexical_scope.SCHEMA, "family": "deontic", "profile": lexical_scope.PROFILE,
        "input": deepcopy(request), "input_sha256": digest(request),
        "occurrences": occurrences,
        "rules": [{"rule_id": "r1",
                   "body": {"actor": "subject", "modality": "modal", "action": "action", "object": "duties"},
                   "qualifiers": {"conditions": None, "exceptions": None, "temporal": None}}],
        "statement_structure": {"op": "rule", "rule_id": "r1"}, "binders": [],
        "coverage": {"declared_status": "partial", "segments": [{
            "span": _source_fixtures.anchor(text, 0, len(text)), "disposition": "unresolved", "rule_ids": ["r1"],
            "occurrence_ids": [row["occurrence_id"] for row in occurrences],
            "reason": "Complete fictional source retained without selecting a legal interpretation."}]},
        "unresolved": [
            {"code": "passive_subject_agent_unresolved",
             "span": _source_fixtures.anchor(text, 0, len("Clérks")),
             "reason": "A legacy actor slot records the passive subject; agent and recipient identity remain unreviewed."},
            {"code": "approval_necessity_unresolved",
             "span": _source_fixtures.anchor(text, approval_start, len(text) - 1),
             "reason": "The proposed modal and implication placements remain unreviewed."},
        ],
    }
    return {"raw": raw, "sampling": sampled, "args": args, "request": request,
            "declaration": _source_fixtures.seal(declaration), "units": units, "unit": units[0]}


def typed_request(*, swapped_arguments=False, swapped_roles=False, reverse_binders=False,
                  quantifier="forall", operator="P", inside_modal=False):
    builder = _typed_fixtures.Builder()
    arguments = ("recipient", "agent") if swapped_arguments else ("agent", "recipient")
    actions = builder.binary("or", builder.atom("Assign", *arguments),
                             builder.atom("Transfer", *arguments))
    approval = builder.atom("Approve", "approver", "recipient")
    body = (builder.modal(operator, builder.binary("implies", actions, approval)) if inside_modal
            else builder.binary("implies", builder.modal(operator, actions), approval))
    roles = ("recipient", "agent") if swapped_roles else ("agent", "recipient")
    binders = [("agent", "forall"), ("recipient", quantifier), ("approver", "forall")]
    if reverse_binders:
        binders.reverse()
    return _typed_fixtures.request_for(builder, body,
        [("Assign", roles), ("Transfer", roles), ("Approve", ("approver", "recipient"))], binders)


def pointer(value, path):
    for piece in path.split("/")[1:]:
        value = value[int(piece)] if type(value) is list else value[piece]
    return value


def correspondences(scope_report, relational_report):
    all_paths = [row["typed_path"] for row in relational_report["structural_mapping"]]
    rows = []
    code = "parameter_roles_and_quantifiers_unreviewed"
    for mapped in relational_report["structural_mapping"]:
        kind, path = mapped["kind"], mapped["typed_path"]
        anchors = []
        if kind == "variable":
            name = pointer(relational_report["typed_expression"], path)["symbol"]
            if name == "recipient":
                anchors = ["/occurrences/0/anchor"]
            elif name == "approver":
                anchors = ["/unresolved/1/span"]
        elif kind == "predicate":
            symbol = pointer(relational_report["typed_expression"], path)["symbol"]
            anchors = ["/unresolved/1/span" if symbol == "Approve" else "/occurrences/2/anchor"]
        elif kind in {"extension", "legacy.deontic/v1"}:
            anchors = ["/occurrences/1/anchor"]
        elif kind in {"or", "and"}:
            anchors = ["/occurrences/2/anchor"]
        elif kind in {"implies", "iff", "not"}:
            anchors = ["/unresolved/1/span"]
        rows.append({"typed_path": path, "source_anchor_paths": anchors,
                     "disposition": "lexical_hypothesis" if anchors else "introduced_unresolved",
                     "unresolved_codes": [code] + (["passive_subject_agent_unresolved"] if anchors else []),
                     "rationale": "Caller hypothesis only; source roles, bindings, quantifiers and modal interpretation remain unresolved."})
    return rows, [{"code": code,
                   "rationale": "All introduced parameters, predicate arities, quantifiers and role identities are unreviewed assumptions.",
                   "affected_typed_paths": all_paths}]


def case(*, source_only=False, source=None, **typed_options):
    value = source_case() if source is None else source
    scope_request_raw, scope_declaration_raw, kwargs = _source_fixtures.preparation_inputs(value)
    scope_report = source_scope.prepare_sampled_norm_scope_v1(
        value["sampling"], value["raw"], scope_request_raw, scope_declaration_raw, **kwargs)
    replay = {"sampling_report": value["sampling"], "raw_html": value["raw"],
              "scope_request_raw": scope_request_raw, "scope_declaration_raw": scope_declaration_raw, **kwargs}
    relational_request_raw = None if source_only else wire(typed_request(**typed_options))
    relational_report = None if source_only else relational.prepare_relational_norm_v1(
        relational_request_raw, expected_request_sha256=raw_digest(relational_request_raw))
    rows, issues = ([], []) if source_only else correspondences(scope_report, relational_report)
    join_request = {"schema": subject.REQUEST_SCHEMA,
                    "interpretation_status": "unreviewed_correspondence_proposal",
                    "component_id": "fictional:connected:one", "alternative_id": "source_only" if source_only else "hypothesis",
                    "selected_unit_ref": deepcopy(kwargs["selected_unit_ref"]),
                    "node_correspondences": rows, "introduced_unresolved": issues}
    return {"scope_report": scope_report, "relational_report": relational_report,
            "join_request": join_request,
            "kwargs": {"expected_scope_report_sha256": source_scope.sampled_norm_scope_report_sha256(scope_report),
                       "expected_relational_report_sha256": (None if source_only else relational.relational_norm_report_sha256(relational_report)),
                       "scope_replay_inputs": replay,
                       "relational_request_raw": relational_request_raw,
                       "expected_relational_request_sha256": (None if source_only else raw_digest(relational_request_raw))}}


def prepare(value):
    raw = wire(value["join_request"])
    return subject.prepare_source_typed_norm_join_v1(
        value["scope_report"], value["relational_report"], raw,
        expected_join_request_sha256=raw_digest(raw), **value["kwargs"])


def validate(report, value):
    raw = wire(value["join_request"])
    return subject.validate_source_typed_norm_join_v1(
        report, value["scope_report"], value["relational_report"], raw,
        expected_report_sha256=subject.source_typed_norm_join_sha256(report),
        expected_join_request_sha256=raw_digest(raw), **value["kwargs"])


@pytest.fixture(scope="module")
def base_case():
    return case()


@pytest.fixture(scope="module")
def base_report(base_case):
    return prepare(base_case)


def test_public_import_needs_only_standard_library_and_hashing_needs_no_owners():
    script = r'''
import importlib.util, json, sys
blocked = ("ipfs_datasets_py", "torch", "numpy", "transformers", "pyarrow", "cryptography", "multiformats", "requests")
attempts = []
class Deny:
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in blocked):
            attempts.append(fullname)
            raise AssertionError(fullname)
sys.meta_path.insert(0, Deny())
spec = importlib.util.spec_from_file_location("_cold_join", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert len(module.__all__) == 3
assert len(module.source_typed_norm_join_sha256({"ordinary": True})) == 64
assert not attempts
print(json.dumps({"operation_owner_import_attempts": attempts}))
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script, subject.__file__],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"operation_owner_import_attempts": []}


def test_complete_original_owner_replay_retains_exact_source_and_external_syntax(base_case, base_report):
    before = deepcopy(base_case)
    report = validate(base_report, base_case)
    assert report == base_report and base_case == before
    assert report["source_scope_report"] == base_case["scope_report"]
    assert report["source_custody"]["source_selector"] == base_case["scope_report"]["source_selector"]
    assert report["typed_candidate"]["expression"] == base_case["relational_report"]["typed_expression"]
    assert report["typed_candidate"]["source_binding"] is None
    assert report["external_relational_source_binding"] is None
    assert report["original_unresolved"] == base_case["scope_report"]["scope_declaration"]["unresolved"]
    assert report["introduced_unresolved"] == base_case["join_request"]["introduced_unresolved"]
    assert [row["typed_path"] for row in report["provenance_ledger"]] == [
        row["typed_path"] for row in base_case["relational_report"]["structural_mapping"]]
    assert report["source_custody_linked"] and not report["source_meaning_selected"]
    assert not any(report["authority"].values()) and not any(report["masks"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["human_reviews"] == report["signatures_constructed"] == report["admissions"] == 0
    assert report["model_calls"] == report["training_calls"] == report["native_processes"] == 0
    for field in ("formal_norm_ast", "lowered_IR", "native_output_for_source", "graph", "lookup",
                  "governing_use", "accepted_lookup", "governing_definition_use"):
        assert report[field] is None
    assert "lean_body" not in report and "native_ast" not in report and "native_formula" not in report
    assert report["declared_semantic_coverage"] == "partial" and report["original_context_preserved"]
    assert not report["external_context_nominations_applied"] and not report["native_build_executed"]


def test_passive_subject_to_recipient_is_explicit_hypothesis_with_exact_unicode_anchor(base_report):
    rows = [row for row in base_report["provenance_ledger"]
            if row["kind"] == "variable" and row["variable_name"] == "recipient"]
    assert rows and any(row["predicate_argument"]["declared_role"] == "recipient" for row in rows)
    for row in rows:
        assert row["disposition"] == "lexical_hypothesis" and not row["source_meaning_verified"]
        assert row["source_anchor_paths"] == ["/occurrences/0/anchor"]
        anchor = row["source_anchors"][0]
        assert anchor["local_anchor"]["text"] == "Clérks"
        selector = anchor["document_selector"]
        assert selector["utf8_byte_end"] - selector["utf8_byte_start"] == len("Clérks".encode("utf-8"))
        assert "passive_subject_agent_unresolved" in row["unresolved_codes"]
        binding = row["binding_quantifier"]
        assert binding["variable_name"] == "recipient" and binding["quantifier_kind"] == "forall"
        assert binding["scope_body_typed_path"].startswith(binding["quantifier_typed_path"] + "/arguments/")
    assert base_report["original_unresolved"][0]["code"] == "passive_subject_agent_unresolved"
    assert not base_report["authority"]["legal_roles_verified"]


def test_derived_binder_and_modal_rows_retain_exact_scope_and_payload(base_report):
    rows = base_report["provenance_ledger"]
    binders = [row for row in rows if row["kind"] == "binder"]
    assert {row["binder_name"] for row in binders} == {"agent", "recipient", "approver"}
    for row in binders:
        assert row["typed_path"] == row["binding_quantifier"]["binder_typed_path"]
        assert row["source_anchor_paths"] == [] and row["disposition"] == "introduced_unresolved"
    modal = [row for row in rows if row["kind"] == "legacy.deontic/v1"]
    assert len(modal) == 1 and modal[0]["modal_operator"] == "P"
    assert modal[0]["modal_child_typed_path"] == modal[0]["typed_path"] + "/children/0"
    assert all(row["native_mapping_scope"] == "syntax_metadata_only" for row in rows)


@pytest.mark.parametrize("option", ["swapped_arguments", "swapped_roles", "reverse_binders", "quantifier", "operator", "inside_modal"])
def test_changed_role_argument_binding_or_modal_choice_remains_distinct_declared_hypothesis(base_report, option):
    setting = {option: ("exists" if option == "quantifier" else "O" if option == "operator" else True)}
    changed = prepare(case(**setting))
    assert changed["provenance_ledger"] != base_report["provenance_ledger"]
    assert not changed["source_meaning_selected"] and not any(changed["authority"].values())
    if option == "swapped_arguments":
        row = next(row for row in changed["provenance_ledger"] if row["kind"] == "variable"
                   and row["predicate_argument"]["predicate_symbol"] == "Assign"
                   and row["predicate_argument"]["argument_index"] == 0)
        assert row["predicate_argument"]["declared_role"] == "agent"
        assert row["variable_name"] == row["binding_quantifier"]["variable_name"] == "recipient"
    elif option == "swapped_roles":
        row = next(row for row in changed["provenance_ledger"] if row["kind"] == "variable"
                   and row["predicate_argument"]["predicate_symbol"] == "Assign"
                   and row["predicate_argument"]["argument_index"] == 0)
        assert row["predicate_argument"]["declared_role"] == "recipient" and row["variable_name"] == "agent"
    elif option == "quantifier":
        assert all(row["binding_quantifier"]["quantifier_kind"] == "exists" for row in changed["provenance_ledger"]
                   if row["kind"] == "variable" and row["variable_name"] == "recipient")
    elif option == "operator":
        assert {row["modal_operator"] for row in changed["provenance_ledger"]
                if row["kind"] == "legacy.deontic/v1"} == {"O"}


@pytest.mark.parametrize("damage", ["missing", "duplicate", "reverse", "metadata_pointer", "wrong_kind_pointer",
                                    "unknown_anchor", "invented_subspan", "empty_lexical", "unknown_issue",
                                    "unanchored_original_only", "new_code_collides", "duplicate_issue",
                                    "issue_unknown_path", "issue_unused", "affected_path_omitted", "affected_path_unreferenced"])
def test_resealed_requests_cannot_hide_incomplete_or_invented_correspondence(base_case, damage):
    value = deepcopy(base_case)
    request = value["join_request"]
    rows, issues = request["node_correspondences"], request["introduced_unresolved"]
    if damage == "missing": rows.pop()
    elif damage == "duplicate": rows[-1] = deepcopy(rows[0])
    elif damage == "reverse": rows.reverse()
    elif damage == "metadata_pointer": rows[0]["typed_path"] = "/root/metadata"
    elif damage == "wrong_kind_pointer": rows[0]["typed_path"] = "/root/binders/0/name"
    elif damage == "unknown_anchor": rows[-1]["source_anchor_paths"] = ["/occurrences/0/anchor/text"]
    elif damage == "invented_subspan": rows[-1]["source_anchor_paths"] = ["/occurrences/2/anchor:0:8"]
    elif damage == "empty_lexical": rows[0].update(disposition="lexical_hypothesis", source_anchor_paths=[])
    elif damage == "unknown_issue": rows[0]["unresolved_codes"] = ["absent_issue"]
    elif damage == "unanchored_original_only": rows[0]["unresolved_codes"] = ["passive_subject_agent_unresolved"]
    elif damage == "new_code_collides": issues[0]["code"] = "passive_subject_agent_unresolved"
    elif damage == "duplicate_issue": issues.append(deepcopy(issues[0]))
    elif damage == "issue_unknown_path": issues[0]["affected_typed_paths"].append("/root/metadata")
    elif damage == "issue_unused": issues.append({"code": "unused", "rationale": "Not used by a row.", "affected_typed_paths": [rows[0]["typed_path"]]})
    elif damage == "affected_path_omitted": issues[0]["affected_typed_paths"].pop()
    elif damage == "affected_path_unreferenced":
        row = next(row for row in rows if row["source_anchor_paths"])
        row["unresolved_codes"] = ["passive_subject_agent_unresolved"]
    with pytest.raises(ValueError):
        prepare(value)


@pytest.mark.parametrize("damage", ["ledger_order", "ledger_drop", "argument_role", "binding", "modal", "connective",
                                    "original_issue", "introduced_issue", "typed_candidate", "context", "coverage",
                                    "source_geometry", "authority", "mask", "native_output", "graph", "meaning"])
def test_repaired_output_hashes_cannot_authorize_output_mutations(base_case, base_report, damage):
    report = deepcopy(base_report)
    rows = report["provenance_ledger"]
    if damage == "ledger_order": rows.reverse()
    elif damage == "ledger_drop": rows.pop()
    elif damage == "argument_role": next(row for row in rows if row["kind"] == "variable")["predicate_argument"]["declared_role"] = "invented"
    elif damage == "binding": next(row for row in rows if row["kind"] == "variable")["binding_quantifier"]["variable_name"] = "invented"
    elif damage == "modal": next(row for row in rows if row["kind"] == "legacy.deontic/v1")["modal_operator"] = "O"
    elif damage == "connective": next(row for row in rows if row["kind"] == "implies")["connective_operator"] = "iff"
    elif damage == "original_issue": report["original_unresolved"].pop()
    elif damage == "introduced_issue": report["introduced_unresolved"].pop()
    elif damage == "typed_candidate": report["typed_candidate"]["source_meaning_verified"] = True
    elif damage == "context": report["source_custody"]["source_records"]["context"]["availability"] = "complete"
    elif damage == "coverage": report["source_scope_report"]["scope_declaration"]["coverage"]["declared_status"] = "complete"
    elif damage == "source_geometry": report["source_custody"]["source_selector"]["char_start"] += 1
    elif damage == "authority": report["authority"]["legal_roles_verified"] = True
    elif damage == "mask": report["training_mask"] = 1
    elif damage == "native_output": report["native_output_for_source"] = "invented source Lean output"
    elif damage == "graph": report["graph"] = {"admitted": True}
    elif damage == "meaning": report["source_meaning_selected"] = True
    with pytest.raises(ValueError, match="authoritative regeneration"):
        validate(report, base_case)


@pytest.mark.parametrize("damage", ["source_record", "context", "coverage", "authority", "source_geometry", "issue"])
def test_repaired_scope_report_pin_cannot_replace_original_source_replay(base_case, damage):
    value = deepcopy(base_case)
    report = value["scope_report"]
    if damage == "source_record": report["source_records"]["source_version"]["edition"] = 2025
    elif damage == "context": report["source_records"]["context"]["availability"] = "complete"
    elif damage == "coverage": report["scope_declaration"]["coverage"]["declared_status"] = "complete"
    elif damage == "authority": report["authority"]["legal_roles_verified"] = True
    elif damage == "source_geometry": report["source_selector"]["char_start"] += 1
    elif damage == "issue": report["scope_declaration"]["unresolved"].pop()
    value["kwargs"]["expected_scope_report_sha256"] = source_scope.sampled_norm_scope_report_sha256(report)
    with pytest.raises(ValueError):
        prepare(value)


@pytest.mark.parametrize("damage", ["structural_mapping", "roles", "expression", "native_ast", "source_binding"])
def test_repaired_relational_pin_still_requires_complete_original_typed_replay(base_case, damage):
    value = deepcopy(base_case)
    report = value["relational_report"]
    if damage == "structural_mapping": report["structural_mapping"].pop()
    elif damage == "roles": report["argument_roles"][0]["roles"].reverse()
    elif damage == "expression": report["typed_expression"]["root"]["kind"] = "exists"
    elif damage == "native_ast": report["native_ast"]["quantifier"]["value"] = "∃"
    elif damage == "source_binding": report["source_binding"] = {"source": "invented"}
    value["kwargs"]["expected_relational_report_sha256"] = relational.relational_norm_report_sha256(report)
    with pytest.raises(ValueError):
        prepare(value)


@pytest.mark.parametrize("substitution", ["edition", "physical_occurrence"])
def test_identical_paragraph_text_cannot_substitute_for_original_selected_unit(base_case, substitution):
    original = deepcopy(base_case)
    source = source_case(edition=2025) if substitution == "edition" else source_case(duplicate=True)
    if substitution == "physical_occurrence":
        source["unit"] = source["units"][1]
    replacement = case(source=source)
    assert replacement["scope_report"]["source_selector"]["text"] == original["scope_report"]["source_selector"]["text"]
    assert replacement["scope_report"]["input_pins"]["selected_unit_ref"] != original["join_request"]["selected_unit_ref"]
    replacement["join_request"] = original["join_request"]
    with pytest.raises(ValueError, match="selected unit differs"):
        prepare(replacement)


def test_pending_source_only_state_has_no_typed_or_introduced_target():
    value = case(source_only=True)
    report = prepare(value)
    assert validate(report, value) == report
    assert report["status"] == "source_only_pending_typed_interpretation_retained"
    assert report["typed_candidate"] is None and report["provenance_ledger"] == []
    assert report["introduced_unresolved"] == []
    assert report["original_unresolved"] == value["scope_report"]["scope_declaration"]["unresolved"]
    assert report["input_pins"]["relational_report_full_canonical_sha256"] is None
    assert report["input_pins"]["relational_request_raw_sha256"] is None
    assert report["formal_norm_ast"] is report["native_output_for_source"] is report["graph"] is None
    assert not any(report["authority"].values()) and report["training_mask"] == report["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("field", ["relational_report", "relational_request_raw", "expected_relational_request_sha256",
                                   "expected_relational_report_sha256"])
def test_partially_missing_relational_inputs_are_refused_before_owner_imports(base_case, monkeypatch, field):
    value = deepcopy(base_case)
    if field == "relational_report": value[field] = None
    else: value["kwargs"][field] = None
    monkeypatch.setattr(subject, "_owners", lambda: (_ for _ in ()).throw(AssertionError("owners imported")))
    with pytest.raises(ValueError, match="all be present or null"):
        prepare(value)


@pytest.mark.parametrize("field", ["node_correspondences", "introduced_unresolved"])
def test_pending_source_only_cannot_retain_a_fabricated_typed_target(base_case, monkeypatch, field):
    value = deepcopy(base_case)
    value["relational_report"] = None
    for key in ("relational_request_raw", "expected_relational_request_sha256", "expected_relational_report_sha256"):
        value["kwargs"][key] = None
    for key in ("node_correspondences", "introduced_unresolved"):
        if key != field: value["join_request"][key] = []
    monkeypatch.setattr(subject, "_owners", lambda: (_ for _ in ()).throw(AssertionError("owners imported")))
    with pytest.raises(ValueError, match="empty typed declarations"):
        prepare(value)


@pytest.mark.parametrize("damage", ["duplicate", "nested_duplicate", "nan", "utf8", "oversize", "hash", "not_bytes",
                                    "extra_field", "wrong_status", "bool_component", "blank_alternative", "extra_row",
                                    "bad_disposition", "bool_path", "empty_issue_codes", "duplicate_anchor", "extra_issue"])
def test_malformed_join_bytes_and_closed_contract_fail_before_operation_imports(base_case, monkeypatch, damage):
    value = deepcopy(base_case)
    request = value["join_request"]
    if damage == "extra_field": request["unexpected"] = True
    elif damage == "wrong_status": request["interpretation_status"] = "reviewed"
    elif damage == "bool_component": request["component_id"] = True
    elif damage == "blank_alternative": request["alternative_id"] = " "
    elif damage == "extra_row": request["node_correspondences"][0]["kind"] = "predicate"
    elif damage == "bad_disposition": request["node_correspondences"][0]["disposition"] = []
    elif damage == "bool_path": request["node_correspondences"][0]["typed_path"] = True
    elif damage == "empty_issue_codes": request["node_correspondences"][0]["unresolved_codes"] = []
    elif damage == "duplicate_anchor": request["node_correspondences"][0]["source_anchor_paths"] = ["/coverage/segments/0/span"] * 2
    elif damage == "extra_issue": request["introduced_unresolved"][0]["reviewed"] = True
    raw = wire(request)
    if damage == "duplicate": raw = b'{"schema":"x","schema":"y"}'
    elif damage == "nested_duplicate": raw = b'{"nested":{"a":1,"a":2}}'
    elif damage == "nan": raw = b'{"value":NaN}'
    elif damage == "utf8": raw = b'\xff'
    elif damage == "oversize": raw = b" " * (subject.MAX_REQUEST_BYTES + 1)
    expected = raw_digest(raw)
    if damage == "hash": expected = "0" * 64
    elif damage == "not_bytes": raw = raw.decode("utf-8")
    monkeypatch.setattr(subject, "_owners", lambda: (_ for _ in ()).throw(AssertionError("owners imported")))
    with pytest.raises(ValueError):
        subject.prepare_source_typed_norm_join_v1(value["scope_report"], value["relational_report"], raw,
            expected_join_request_sha256=expected, **value["kwargs"])


@pytest.mark.parametrize("damage", ["scope_pin", "scope_nonordinary", "sampling_pin", "scope_request_json",
                                    "raw_hash", "extra_replay_field", "relational_pin", "relational_json"])
def test_original_input_pins_and_json_are_checked_before_operation_imports(base_case, monkeypatch, damage):
    value = deepcopy(base_case)
    kwargs, replay = value["kwargs"], value["kwargs"]["scope_replay_inputs"]
    if damage == "scope_pin": kwargs["expected_scope_report_sha256"] = "0" * 64
    elif damage == "scope_nonordinary": value["scope_report"]["unexpected"] = object()
    elif damage == "sampling_pin": replay["expected_sampling_report_sha256"] = "0" * 64
    elif damage == "scope_request_json":
        replay["scope_request_raw"] = b'{"source_text":"x","source_text":"y"}'
        replay["expected_scope_request_sha256"] = raw_digest(replay["scope_request_raw"])
    elif damage == "raw_hash": replay["expected_raw_sha256"] = "0" * 64
    elif damage == "extra_replay_field": replay["unexpected"] = 1
    elif damage == "relational_pin": kwargs["expected_relational_report_sha256"] = "0" * 64
    elif damage == "relational_json":
        kwargs["relational_request_raw"] = b'{"expression":{},"expression":{}}'
        kwargs["expected_relational_request_sha256"] = raw_digest(kwargs["relational_request_raw"])
    monkeypatch.setattr(subject, "_owners", lambda: (_ for _ in ()).throw(AssertionError("owners imported")))
    with pytest.raises(ValueError):
        prepare(value)


def test_independent_join_and_output_pins_remain_required(base_case, base_report, monkeypatch):
    raw = wire(base_case["join_request"])
    monkeypatch.setattr(subject, "_owners", lambda: (_ for _ in ()).throw(AssertionError("owners imported")))
    with pytest.raises(ValueError, match="independent byte pin"):
        subject.prepare_source_typed_norm_join_v1(base_case["scope_report"], base_case["relational_report"], raw,
            expected_join_request_sha256="0" * 64, **base_case["kwargs"])
    with pytest.raises(ValueError, match="independent canonical pin"):
        subject.validate_source_typed_norm_join_v1(base_report, base_case["scope_report"],
            base_case["relational_report"], raw, expected_report_sha256="0" * 64,
            expected_join_request_sha256=raw_digest(raw), **base_case["kwargs"])


def test_request_raw_bytes_and_canonical_commitment_remain_distinct(base_case):
    raw = json.dumps(base_case["join_request"], ensure_ascii=False, indent=2).encode("utf-8")
    report = subject.prepare_source_typed_norm_join_v1(base_case["scope_report"], base_case["relational_report"], raw,
        expected_join_request_sha256=raw_digest(raw), **base_case["kwargs"])
    assert report["input_pins"]["join_request_raw_sha256"] == raw_digest(raw)
    assert report["input_pins"]["join_request_canonical_sha256"] == digest(base_case["join_request"])
    assert report["input_pins"]["join_request_raw_sha256"] != report["input_pins"]["join_request_canonical_sha256"]
    assert report["join_request_raw_utf8"].encode("utf-8") == raw


def test_inputs_and_detached_output_cannot_mutate_each_other(base_case):
    value = deepcopy(base_case)
    before = deepcopy(value)
    report = prepare(value)
    assert value == before
    report["source_scope_report"]["scope_declaration"]["unresolved"].clear()
    report["typed_candidate"]["argument_roles"][0]["roles"].reverse()
    report["join_request"]["node_correspondences"].clear()
    assert value == before
    other = prepare(value)
    value["scope_report"]["scope_declaration"]["unresolved"].clear()
    value["join_request"]["introduced_unresolved"].clear()
    assert other["source_scope_report"]["scope_declaration"]["unresolved"]
    assert other["introduced_unresolved"]


def test_changed_source_producer_during_relational_replay_is_detected(base_case, monkeypatch):
    original_validate = relational.validate_relational_norm_v1
    original_read = Path.read_bytes
    target = Path(source_scope.__file__).resolve()

    def changed_read(path):
        return b"changed after source replay" if path.resolve() == target else original_read(path)

    def validate_then_change(*args, **kwargs):
        report = original_validate(*args, **kwargs)
        monkeypatch.setattr(Path, "read_bytes", changed_read)
        return report

    monkeypatch.setattr(relational, "validate_relational_norm_v1", validate_then_change)
    with pytest.raises(ValueError, match="changed|commitments differ"):
        prepare(base_case)


def test_changed_direct_producer_after_correspondence_is_detected_before_return(base_case, monkeypatch):
    original_correspondences = subject._correspondences
    original_read = Path.read_bytes
    target = Path(relational.__file__).resolve()

    def changed_read(path):
        return b"changed after correspondence" if path.resolve() == target else original_read(path)

    def correspond_then_change(*args, **kwargs):
        ledger = original_correspondences(*args, **kwargs)
        monkeypatch.setattr(Path, "read_bytes", changed_read)
        return ledger

    monkeypatch.setattr(subject, "_correspondences", correspond_then_change)
    with pytest.raises(ValueError, match="producer changed"):
        prepare(base_case)


def test_resealed_producer_pin_changes_fail_before_prior_operations(base_case, monkeypatch):
    value = deepcopy(base_case)
    target = str(Path(source_scope.__file__).resolve())
    value["scope_report"]["producer_pins"][target] = "0" * 64
    value["kwargs"]["expected_scope_report_sha256"] = source_scope.sampled_norm_scope_report_sha256(value["scope_report"])
    monkeypatch.setattr(source_scope, "validate_sampled_norm_scope_v1",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("source operation ran")))
    with pytest.raises(ValueError, match="producer commitments differ"):
        prepare(value)


@pytest.mark.parametrize("report_kind", ["scope", "relational"])
@pytest.mark.parametrize("mutation", ["insert", "replace"])
def test_resealed_reports_cannot_nominate_foreign_files_before_authoritative_replay(
    base_case, monkeypatch, report_kind, mutation,
):
    value = deepcopy(base_case)
    report = value["scope_report" if report_kind == "scope" else "relational_report"]
    foreign = Path("/tmp/legal_join_foreign_producer_must_not_be_read")
    pins = report["producer_pins"]
    if mutation == "replace":
        pins.pop(next(iter(pins)))
    pins[str(foreign)] = "0" * 64
    if report_kind == "scope":
        value["kwargs"]["expected_scope_report_sha256"] = source_scope.sampled_norm_scope_report_sha256(report)
    else:
        value["kwargs"]["expected_relational_report_sha256"] = relational.relational_norm_report_sha256(report)
    original_read = Path.read_bytes
    foreign_reads = []
    prior_operations = []

    def guarded_read(path):
        if path.resolve() == foreign:
            foreign_reads.append(str(path))
            raise AssertionError("caller-nominated foreign producer was read")
        return original_read(path)

    def prior_validate(*args, **kwargs):
        prior_operations.append(True)
        raise AssertionError("prior validation ran before producer map rejection")

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    monkeypatch.setattr(source_scope, "validate_sampled_norm_scope_v1", prior_validate)
    monkeypatch.setattr(relational, "validate_relational_norm_v1", prior_validate)
    with pytest.raises(ValueError, match="producer commitments differ from trusted owners"):
        prepare(value)
    assert foreign_reads == [] and prior_operations == []
