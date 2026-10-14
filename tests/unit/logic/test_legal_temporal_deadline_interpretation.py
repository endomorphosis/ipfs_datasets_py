"""Explicit triggered deadlines, exact source bindings and temporal semantics."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_deadline_interpretation as deadline
from ipfs_datasets_py.logic.autoformal import legal_temporal_event_interpretation as until
from ipfs_datasets_py.logic.autoformal import legal_temporal_event_proposer_v4 as proposer
from ipfs_datasets_py.logic.autoformal import legal_temporal_occurrence_provenance as occurrence
from ipfs_datasets_py.logic.legal_document import _clause_selector
from ipfs_datasets_py.logic.software_verification.temporal import TemporalFormula
from ipfs_datasets_py.logic.software_verification.trace import TraceIR, TraceKind


TEXT = "Registry shall submit the report not later than 2 days after receipt of notice."
RESPONSE = "Registry shall submit the report"
MEANINGS = {"response_source_span", "response_source_text", "trigger_atom", "response_atom",
            "ticks_per_source_unit", "trigger_scope", "deadline_origin", "lower_inclusive",
            "upper_inclusive", "time_domain", "evaluation_origin", "modal_scope", "response_reuse"}


def inputs(text=TEXT, **kwargs):
    return occurrence.build_occurrence_receipt(text, source_id="fictional", **kwargs), proposer.propose(text)


def requests(receipt, proposal, text=TEXT, document=None):
    return deadline.build_deadline_requests(receipt, proposal, source_text=text, document_text=document)


def declaration(inventory, text=TEXT, *, index=0, factor=1):
    supplied = deepcopy(inventory["requests"][index]["declaration_skeleton"])
    start = text.index(RESPONSE)
    supplied.update(
        response_source_span={"char_start": start, "char_end": start + len(RESPONSE)},
        response_source_text=RESPONSE, trigger_atom="notice_received", response_atom="report_submitted",
        ticks_per_source_unit=factor, trigger_scope="each_trigger_at_or_after_evaluation_origin",
        deadline_origin="each_trigger_occurrence_time", lower_inclusive=True, upper_inclusive=True,
        time_domain="discrete_unbounded_nat", evaluation_origin="caller_supplied_evaluation_time",
        modal_scope="temporal_property_only", response_reuse="one_response_may_satisfy_multiple_triggers")
    return supplied


def prepared(text=TEXT, *, factor=1):
    receipt, proposal = inputs(text)
    supplied = declaration(requests(receipt, proposal, text), text, factor=factor)
    return deadline.prepare_deadline_interpretation(receipt, proposal, supplied, source_text=text)


def evaluate(artifact, triggers=(), responses=(), *, origin=0):
    # End on a no-event state which repeats forever, so every listed trigger
    # is genuinely evaluated without inventing an infinite stream of triggers.
    size = max([origin, *triggers, *responses]) + artifact["deadline_ticks"] + 2
    states = [{"notice_received": index in triggers, "report_submitted": index in responses}
              for index in range(size)]
    trace = TraceIR.from_state_sequence(states, trace_kind=TraceKind.INFINITE,
        loop_start=len(states) - 1, proposition_adapter=lambda row: row)
    return TemporalFormula.from_dict(artifact["temporal_ast"]).evaluate(trace, position=origin).verdict.value


def resign(value):
    value["receipt_sha256"] = deadline.digest({key: item for key, item in value.items() if key != "receipt_sha256"})
    return value


def test_inventory_observes_deadline_tokens_but_leaves_all_choices_unsupplied():
    receipt, proposal = inputs()
    original = deepcopy((receipt, proposal))
    legacy_before = until.build_interpretation_requests(receipt, proposal, source_text=TEXT)
    inventory = requests(receipt, proposal)
    request = inventory["requests"][0]
    assert request["status"] == "awaiting_caller_interpretation"
    assert request["source_request_status"] == "unsupported_family"
    surface = request["deadline_surface"]
    assert surface["cue_source"]["source_text"] == "not later than"
    assert surface["quantity_source"]["source_text"] == "2"
    assert surface["quantity"] == 2 and surface["source_unit"] == "day"
    assert surface["unit_source"]["source_text"] == "days"
    assert surface["connector_source"]["source_text"] == "after"
    assert request["event_source"]["source_text"] == "receipt of notice"
    assert all(request["declaration_skeleton"][key] is None for key in MEANINGS)
    assert request["declaration_skeleton"]["deadline_surface"] == surface
    assert all(value is False for value in request["authority"].values())
    assert all(value is False for value in inventory["authority"].values())
    assert (receipt, proposal) == original
    assert until.build_interpretation_requests(receipt, proposal, source_text=TEXT) == legacy_before
    with pytest.raises(ValueError, match="complete caller deadline meaning"):
        deadline.prepare_deadline_interpretation(receipt, proposal, request["declaration_skeleton"], source_text=TEXT)


def test_fronted_deadline_response_can_follow_the_qualifier_without_owner_inference():
    text = "No later than 2 hours after receipt of notice, " + RESPONSE + "."
    artifact = prepared(text)
    assert artifact["request"]["deadline_surface"]["cue_source"]["source_text"] == "No later than"
    assert artifact["response_source"]["source_span"]["char_start"] > artifact["trigger_source"]["source_span"]["char_end"]
    assert artifact["response_anchor_scope"] == "source_anchor_only_not_canonical_legal_owner"
    assert artifact["authority"]["owner_occurrence_resolved"] is False
    assert artifact["semantics"]["source_unit"] == "hour"


def test_unsupported_families_units_and_excluded_boundaries_remain_in_inventory():
    text = (TEXT + " " + RESPONSE + " after receipt of notice. " + RESPONSE +
            " not later than 2 months after receipt of notice. " + RESPONSE +
            " not later than 31 days after receipt of notice. " + RESPONSE +
            " not later than 2 days after blue. The words \"after receipt of notice\" are quoted.")
    receipt, proposal = inputs(text)
    inventory = requests(receipt, proposal, text)
    assert len(inventory["requests"]) == len(proposal["proposals"])
    assert {item["status"] for item in inventory["requests"]} == {
        "awaiting_caller_interpretation", "unsupported_family", "unsupported_surface", "unsupported_budget", "excluded"}
    assert inventory["issues"] == proposal["issues"]
    assert inventory["issues"] and inventory["excluded"]
    for index, request in enumerate(inventory["requests"]):
        if request["status"] != "awaiting_caller_interpretation":
            with pytest.raises(ValueError, match="unsupported or excluded"):
                deadline.prepare_deadline_interpretation(receipt, proposal,
                    declaration(inventory, text, index=index), source_text=text)


def test_condition_contained_deadline_remains_excluded():
    text = RESPONSE + " if the agency acts not later than 2 days after receipt of notice."
    receipt, proposal = inputs(text)
    inventory = requests(receipt, proposal, text)
    request = inventory["requests"][0]
    assert request["parser_join"]["association_status"] == "parser_excluded"
    assert request["status"] == "excluded"
    with pytest.raises(ValueError, match="unsupported or excluded"):
        deadline.prepare_deadline_interpretation(receipt, proposal, declaration(inventory, text), source_text=text)


@pytest.mark.parametrize("prefix", ["not later than 0 days after", "not later than 2 business days after",
                                    "not later than 2 calendar days after", "not later than two days after"])
def test_unrecognized_quantities_and_calendar_qualifications_never_gain_supported_skeletons(prefix):
    text = RESPONSE + " " + prefix + " receipt of notice."
    receipt, proposal = inputs(text)
    inventory = requests(receipt, proposal, text)
    assert inventory["counts"]["awaiting_caller_interpretation"] == 0
    assert inventory["issues"] or inventory["requests"]


def test_explicit_positive_tick_conversion_and_actual_typed_family_expansion():
    artifact = prepared(factor=2)
    assert artifact["deadline_ticks"] == 4
    assert artifact["semantics"]["ticks_per_source_unit"] == 2
    assert artifact["temporal_ast"]["operator"] == "always"
    assert artifact["temporal_ast"]["logic"] == "ltl"
    assert TemporalFormula.from_dict(artifact["temporal_ast"]).to_dict() == artifact["temporal_ast"]
    assert artifact["ast_budget"] == {"nodes": 16, "maximum_depth": 10}
    assert all(item["passed"] and item["consumed_all_input"] for item in artifact["family_diagnostics"])
    assert artifact["atom_roles"] == {"notice_received": "trigger_occurs", "report_submitted": "response_occurs"}
    assert artifact["native_renderer_diagnostic"]["validator"] == "FormulaRenderer_exact_native_AST"
    assert 'trace.occurs "notice_received" triggerTick' in artifact["lean_declarations"]
    assert 'trace.occurs "report_submitted" responseTick' in artifact["lean_declarations"]
    assert "triggerTick + 4" in artifact["lean_declarations"]
    assert "deadlineNativeLTLProperty" in artifact["lean_declarations"]
    assert not any(token in artifact["lean_source"] for token in ("sorry", "admit", "axiom "))
    assert all(value is False for value in artifact["authority"].values())
    assert evaluate(artifact, (0,), (4,)) == "true"
    assert evaluate(artifact, (0,), (5,)) == "false"
    assert prepared(factor=1)["temporal_ast"]["formula_id"] != artifact["temporal_ast"]["formula_id"]


def test_maximum_expansion_fits_existing_native_renderer_and_overflow_is_rejected():
    text = TEXT.replace("2 days", str(deadline.MAX_DEADLINE_TICKS) + " days")
    artifact = prepared(text)
    assert artifact["deadline_ticks"] == 30
    assert artifact["ast_budget"] == {"nodes": 94, "maximum_depth": 62}
    assert artifact["native_renderer_diagnostic"]["operators"].count("X") == 30
    receipt, proposal = inputs()
    supplied = declaration(requests(receipt, proposal), factor=16)
    with pytest.raises(ValueError, match="exceed expansion budget"):
        deadline.prepare_deadline_interpretation(receipt, proposal, supplied, source_text=TEXT)


@pytest.mark.parametrize("triggers,responses,origin,expected", [
    ((), (), 0, "true"),                  # Disclosed vacuity, no event existence follows.
    ((0,), (0,), 0, "true"),             # Inclusive lower endpoint.
    ((0,), (2,), 0, "true"),             # Inclusive upper endpoint.
    ((0,), (3,), 0, "false"),            # One tick too late.
    ((1,), (0,), 0, "false"),            # A response before its trigger cannot satisfy it.
    ((2,), (4,), 0, "true"),             # Deadline is anchored at trigger, not evaluation time.
    ((0, 4), (2, 6), 0, "true"),        # Every trigger has its own interval.
    ((0, 4), (2,), 0, "false"),          # First response does not discharge a later trigger.
    ((0, 1), (2,), 0, "true"),           # Explicit response-reuse policy.
    ((0, 3), (2,), 0, "false"),
    ((0,), (), 2, "true"),               # Triggers before evaluation origin are out of scope.
    ((2,), (), 2, "false"),              # A trigger exactly at origin remains in scope.
])
def test_lasso_semantics_use_each_trigger_closed_window_and_declared_origin(triggers, responses, origin, expected):
    artifact = prepared()
    assert evaluate(artifact, triggers, responses, origin=origin) == expected
    if not triggers:
        assert artifact["semantics"]["trigger_existence_required"] is False
        assert artifact["semantics"]["absent_trigger_property_is_vacuously_true"] is True
    assert artifact["authority"]["qualified"] is False
    assert artifact["authority"]["formula_admission"] is False


@pytest.mark.parametrize("key,value", [
    ("ticks_per_source_unit", None), ("ticks_per_source_unit", True), ("ticks_per_source_unit", 0),
    ("ticks_per_source_unit", 1.0), ("ticks_per_source_unit", -1), ("ticks_per_source_unit", 31),
    ("trigger_scope", "only_first_trigger"), ("deadline_origin", "evaluation_origin"),
    ("lower_inclusive", False), ("lower_inclusive", 1), ("upper_inclusive", False),
    ("time_domain", "calendar_days"), ("evaluation_origin", "inferred_source_event"),
    ("modal_scope", "obligation"), ("response_reuse", "consume_once"),
    ("trigger_atom", "report_submitted"), ("trigger_atom", "until"),
    ("response_atom", "report) X injected"),
])
def test_choices_are_explicit_closed_and_never_silently_coerced(key, value):
    receipt, proposal = inputs()
    supplied = declaration(requests(receipt, proposal))
    supplied[key] = value
    with pytest.raises(ValueError):
        deadline.prepare_deadline_interpretation(receipt, proposal, supplied, source_text=TEXT)


def test_response_source_span_is_exact_token_aligned_and_nonoverlapping():
    receipt, proposal = inputs()
    inventory = requests(receipt, proposal)
    for span in ({"char_start": 1, "char_end": 8}, inventory["requests"][0]["event_source"]["source_span"],
                 {"char_start": True, "char_end": 8}):
        supplied = declaration(inventory)
        supplied["response_source_span"] = span
        with pytest.raises(ValueError):
            deadline.prepare_deadline_interpretation(receipt, proposal, supplied, source_text=TEXT)
    supplied = declaration(inventory)
    supplied["response_source_text"] = "another response"
    with pytest.raises(ValueError, match="exact lexical response"):
        deadline.prepare_deadline_interpretation(receipt, proposal, supplied, source_text=TEXT)


@pytest.mark.parametrize("field", ["request_sha256", "source_id", "document_id", "source_text_sha256",
                                   "document_text_sha256", "occurrence_receipt_sha256", "proposal_receipt_sha256"])
def test_source_and_request_bindings_reject_substitution(field):
    receipt, proposal = inputs()
    supplied = declaration(requests(receipt, proposal))
    supplied[field] = "foreign"
    with pytest.raises(ValueError, match="binding differs"):
        deadline.prepare_deadline_interpretation(receipt, proposal, supplied, source_text=TEXT)


@pytest.mark.parametrize("mutation", ["bool_quantity", "float_quantity", "bool_coordinate", "unknown_surface_key"])
def test_nested_source_bindings_require_exact_json_types(mutation):
    text = " Not later than 1 day after receipt of notice, " + RESPONSE + "."
    receipt, proposal = inputs(text)
    supplied = declaration(requests(receipt, proposal, text), text)
    surface = supplied["deadline_surface"]
    if mutation == "bool_quantity":
        surface["quantity"] = True
    elif mutation == "float_quantity":
        surface["quantity"] = 1.0
    elif mutation == "bool_coordinate":
        assert surface["cue_source"]["source_span"]["char_start"] == 1
        surface["cue_source"]["source_span"]["char_start"] = True
    else:
        surface["extra"] = "ignored?"
    with pytest.raises(ValueError, match="binding differs"):
        deadline.prepare_deadline_interpretation(receipt, proposal, supplied, source_text=text)


def test_repeated_sources_keep_distinct_event_and_request_spans():
    text = TEXT + " " + TEXT
    receipt, proposal = inputs(text)
    inventory = requests(receipt, proposal, text)
    left, right = inventory["requests"]
    assert left["event_source"]["source_text"] == right["event_source"]["source_text"]
    assert left["request_id"] != right["request_id"]
    assert left["event_source"]["document_observation_id"] != right["event_source"]["document_observation_id"]
    supplied = declaration(inventory, text)
    supplied["request_id"] = right["request_id"]
    with pytest.raises(ValueError, match="binding differs"):
        deadline.prepare_deadline_interpretation(receipt, proposal, supplied, source_text=text)


def test_raw_unicode_document_alignment_preserves_entire_prefix_and_event():
    text = "État. " + TEXT
    document = "Préface.\nÉtat. " + TEXT.replace("not later than", "not\nlater\tthan").replace("after receipt", "after  receipt") + "\nFin."
    start = document.index("État")
    offsets = [0]
    for char in document:
        offsets.append(offsets[-1] + len(char.encode()))
    selector = _clause_selector(document, text, start, offsets, hashlib.sha256(document.encode()).hexdigest())
    receipt, proposal = inputs(text, document_text=document, document_id="doc", clause_start=start,
                              clause_end=selector["end"], source_selector=selector)
    inventory = requests(receipt, proposal, text, document)
    surface = inventory["requests"][0]["deadline_surface"]
    assert surface["cue_source"]["source_text"] == "not later than"
    assert surface["cue_source"]["document_text"] == "not\nlater\tthan"
    artifact = deadline.prepare_deadline_interpretation(receipt, proposal, declaration(inventory, text),
                                                        source_text=text, document_text=document)
    assert artifact["trigger_source"]["document_span"]["char_start"] == document.index("receipt")
    with pytest.raises(ValueError):
        requests(receipt, proposal, text, document.replace("receipt", "delivery"))


def test_authentic_proposals_closed_declarations_and_exact_replay():
    receipt, proposal = inputs()
    inventory = requests(receipt, proposal)
    supplied = declaration(inventory)
    supplied["legal_owner"] = "Registry"
    with pytest.raises(ValueError, match="closed"):
        deadline.prepare_deadline_interpretation(receipt, proposal, supplied, source_text=TEXT)
    changed = deepcopy(proposal)
    changed["proposals"][0]["event_span"]["char_start"] += 1
    with pytest.raises(ValueError, match="authoritative regeneration"):
        requests(receipt, changed)
    artifact = prepared()
    copied = deadline.validate_deadline_interpretation(artifact, receipt, proposal, source_text=TEXT)
    assert copied == artifact
    copied["declaration"]["response_atom"] = "mutated"
    assert artifact["declaration"]["response_atom"] == "report_submitted"


@pytest.mark.parametrize("field", ["deadline_ticks", "temporal_ast", "tdfol_formula", "native_tdfol_ast",
                                   "lean_source", "authority", "producer_pins"])
def test_resigned_outputs_cannot_change_bounds_ast_code_or_authority(field):
    receipt, proposal = inputs()
    artifact = prepared()
    if field == "deadline_ticks":
        artifact[field] += 1
    elif field in {"temporal_ast", "native_tdfol_ast"}:
        artifact[field]["operator"] = "eventually"
    elif field == "authority":
        artifact[field]["source_semantics_verified"] = True
    elif field == "producer_pins":
        artifact[field][next(iter(artifact[field]))] = "0" * 64
    else:
        artifact[field] += " changed"
    with pytest.raises(ValueError, match="exact replay"):
        deadline.validate_deadline_interpretation(resign(artifact), receipt, proposal, source_text=TEXT)


def test_deadline_dependency_manifest_contains_entire_until_closure():
    pins = deadline.producer_pins()
    assert all(pins[path] == sha for path, sha in until.producer_pins().items())
    assert str(Path(deadline.modal_projections.__file__).resolve()) in pins
    assert str(Path(deadline.__file__).resolve()) in pins


def test_changed_native_ast_serializer_fails_closed(monkeypatch):
    receipt, proposal = inputs()
    target = Path(deadline.modal_projections.__file__).resolve()
    original = Path.read_bytes
    def changed(path):
        content = original(path)
        return content + b"\n# mutation" if path.resolve() == target else content
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="producer changed"):
        requests(receipt, proposal)


def test_dependency_change_mid_inventory_fails_closed(monkeypatch):
    receipt, proposal = inputs()
    original = deadline._dependency_pins
    calls = 0
    def changed():
        nonlocal calls
        calls += 1
        pins = original()
        if calls >= 2:
            pins[next(iter(pins))] = "0" * 64
        return pins
    monkeypatch.setattr(deadline, "_dependency_pins", changed)
    with pytest.raises(ValueError, match="producer changed"):
        requests(receipt, proposal)
