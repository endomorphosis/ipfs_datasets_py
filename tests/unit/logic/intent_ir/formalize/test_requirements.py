"""Candidate ledgers preserve source frontiers and native semantic distinctions."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import requirements as sut
from ipfs_datasets_py.logic.intent_ir.formalize import roundtrip
from ipfs_datasets_py.logic.intent_ir.schema import (
    ControlEdgeKind, IntentModality, IntentStatement, NodeGrounding, StatementKind,
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def stamp(report):
    report.pop("report_sha256", None)
    report["report_sha256"] = sha(json.dumps(report, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=True, allow_nan=False).encode())
    return report


def native(source, *, modality="required"):
    return roundtrip.frame_to_intent_ir({"actor": "agent", "action": "write",
        "object": "report", "modality": modality}, instruction=source)


def reviewed_report(source, document=None, *, left=0, right=None):
    right = len(source) if right is None else right
    text = source[left:right]
    document = native(text) if document is None else document
    return stamp({"schema": sut.REVIEWED_REPORT_SCHEMA,
        "source_sha256": sha(source.encode()), "source_bytes": len(source.encode()),
        "source_characters": len(source), "producer": {"name": "explicit-test-review", "revision": "1"},
        "interpretation_status": "reviewed_candidate", "units": [{"unit_id": "unit:reviewed",
            "start_char": left, "end_char": right, "start_byte": len(source[:left].encode()),
            "end_byte": len(source[:right].encode()), "text": text, "sha256": sha(text.encode()),
            "disposition": "interpreted_candidate", "reason": "explicit_reviewed_native_fixture"}],
        "candidates": [{"unit_id": "unit:reviewed", "candidate_intent_ir": document.to_dict()}],
        "proof_authority": False, "execution_authority": False, "completion_authority": False,
        "source_semantics_verified": False})


def ledger(source="The agent must write report.", report=None):
    return sut.build_intent_requirement_ledger(source,
        source_report=reviewed_report(source) if report is None else report,
        source_identity={"path": "public/instruction.txt", "revision": "test:1"})


def test_reviewed_candidate_is_native_and_never_grants_semantic_or_execution_authority():
    source = "The agent must write report."
    report = reviewed_report(source)
    result = ledger(source, report)
    requirement = result["requirements"][0]
    assert requirement["statement_ids"] == ["goal"]
    assert requirement["native_document_id"] == native(source).document_id
    assert requirement["kind"] == "goal"
    assert requirement["modality"] == "required"
    assert requirement["representation"] == "native_statement"
    assert requirement["interpretation_status"] == "reviewed_candidate"
    assert requirement["compound"] is None
    assert result["source_report"] == report
    assert result["source_report_sha256"] != report["report_sha256"]
    assert result["source_accounting_complete"] is True
    assert result["semantic_support_complete"] is False
    for flag in ("semantic_alignment_verified", "proof_authority", "execution_authority", "completion_authority"):
        assert result[flag] is False
    assert sut.validate_intent_requirement_ledger(result, source_text=source, source_report=report) is result


@pytest.mark.parametrize("modality", ["required", "prohibited", "permitted", "recommended", "intended"])
def test_native_modality_survives_without_inventing_effects(modality):
    source = "Reviewed instruction."
    result = ledger(source, reviewed_report(source, native(source, modality=modality)))
    assert result["requirements"][0]["modality"] == modality
    assert "effects" not in result["requirements"][0]


def test_native_contract_roles_are_retained_and_references_are_document_scoped():
    source = "Require output, a precondition, its effect, and verification."
    document = native(source)
    statements = tuple(IntentStatement("statement:" + kind.value, kind, IntentModality.REQUIRED,
        "Explicitly reviewed " + kind.value, ("source",), predicate="predicate:" + kind.value,
        grounding=NodeGrounding.INFERRED) for kind in (
            StatementKind.GOAL, StatementKind.PRECONDITION, StatementKind.EFFECT, StatementKind.VERIFICATION))
    document = replace(document, statements=statements)
    result = ledger(source, reviewed_report(source, document))
    assert {r["kind"] for r in result["requirements"]} == {"goal", "precondition", "effect", "verification"}
    assert len({r["requirement_id"] for r in result["requirements"]}) == 4
    assert result["source_units"][0]["requirement_ids"] == [r["requirement_id"] for r in result["requirements"]]


def test_unicode_partial_report_retains_exact_bytes_and_unreported_regions():
    source = "保存数据。\n\nThe agent must write report.\n备注。"
    left = source.index("The agent")
    right = source.index("\n备注")
    result = ledger(source, reviewed_report(source, left=left, right=right))
    assert "".join(unit["text"] for unit in result["source_units"]) == source
    assert [u["disposition"] for u in result["source_units"]] == ["unsupported", "interpreted_candidate", "unsupported"]
    assert result["source_units"][1]["start_byte"] > result["source_units"][1]["start_char"]
    assert result["source_units"][0]["unsupported_reason"] == "outside_reported_intent_inventory"
    assert result["source"]["bytes"] == len(source.encode())
    assert sut.validate_intent_requirement_ledger(result, source_text=source) is result


def test_whitespace_gaps_are_accounted_under_non_requirement_rule():
    source = "\n\nThe agent must write report.\n"
    result = ledger(source, reviewed_report(source, left=2, right=len(source) - 1))
    assert [u["disposition"] for u in result["source_units"]] == ["non_requirement", "interpreted_candidate", "non_requirement"]
    assert "".join(u["text"] for u in result["source_units"]) == source


def test_unsupported_report_unit_remains_visible_and_does_not_acquire_requirement():
    source = "If useful, maybe do the thing mentioned above."
    report = reviewed_report(source)
    report["units"][0].update(disposition="unsupported", reason="unresolved_reference")
    report["candidates"] = []
    result = ledger(source, stamp(report))
    assert result["requirements"] == []
    assert result["source_units"][0]["unsupported_reason"] == "unresolved_reference"


@pytest.mark.parametrize("mutate", [
    lambda x: x.update(unrecognized=True),
    lambda x: x["source"].update(extra_identity=True),
    lambda x: x["source_units"][0].update(end_byte=1),
    lambda x: x["source_units"][0].update(text="changed source"),
    lambda x: x["source_units"][0].update(disposition="non_requirement"),
    lambda x: x["requirements"][0].update(modality="permitted"),
    lambda x: x["requirements"][0].update(statement_ids=["dangling"]),
    lambda x: x["requirements"].append(deepcopy(x["requirements"][0])),
    lambda x: x.update(semantic_support_complete=True),
    lambda x: x.update(execution_authority=True),
])
def test_recomputed_digest_cannot_hide_ledger_tampering(mutate):
    result = ledger()
    mutate(result)
    result.pop("ledger_sha256")
    result["ledger_sha256"] = sha(sut._wire(result))
    with pytest.raises(ValueError):
        sut.validate_intent_requirement_ledger(result, source_text="The agent must write report.")


@pytest.mark.parametrize("mutate", [
    lambda x: x["units"].append(deepcopy(x["units"][0])),
    lambda x: x["candidates"].append(deepcopy(x["candidates"][0])),
    lambda x: x["candidates"][0].update(unit_id="dangling"),
    lambda x: x["units"][0].update(start_byte=True),
    lambda x: x["units"][0].update(extra=True),
    lambda x: x.update(extra=True),
    lambda x: x.update(proof_authority=True),
    lambda x: x["candidates"][0]["candidate_intent_ir"]["statements"][0].update(source_ref_ids=["missing"]),
])
def test_source_report_duplicates_dangling_refs_and_unknown_fields_rejected(mutate):
    source = "The agent must write report."
    report = reviewed_report(source)
    mutate(report)
    with pytest.raises(ValueError):
        ledger(source, stamp(report))


def test_original_source_and_report_identity_are_required():
    source = "The agent must write report."
    result = ledger(source)
    with pytest.raises(ValueError, match="different original source"):
        sut.validate_intent_requirement_ledger(result, source_text=source + "\n")
    changed = deepcopy(result["source_report"])
    changed["producer"]["revision"] = "2"
    with pytest.raises(ValueError, match="supplied source report"):
        sut.validate_intent_requirement_ledger(result, source_text=source, source_report=stamp(changed))
    changed = deepcopy(result["source_report"])
    changed["producer"]["revision"] = "2"
    with pytest.raises(ValueError, match="report identity"):
        ledger(source, changed)


def test_whole_prompt_wrapper_cannot_qualify_decomposition():
    source = "Write a report, preserve logs, and verify it."
    document = native(source)
    document = replace(document, statements=(replace(document.statements[0], predicate=""),),
                       actions=(replace(document.actions[0], actor="user", verb="request", object_refs=()),))
    with pytest.raises(ValueError, match="whole prompt wrappers"):
        ledger(source, reviewed_report(source, document))


def test_existing_native_document_report_is_reused_without_frontend_replay(monkeypatch):
    from ipfs_datasets_py.logic.intent_ir.formalize import document_roundtrip as frontend
    calls = []
    def predict(source, descriptor):
        calls.append(source)
        frame = {"actor": "agent", "action": "write", "object": "report", "modality": "required"}
        return {"status": "semantic_candidate_advice", "learned": {
            "encoder": {}, "decoder": {}, "frame": frame},
            "candidate_intent_ir": native(source).to_dict(), "projections": {},
            "extended_projections": {}, "report_sha256": "a" * 64}
    monkeypatch.setattr(frontend.copy_roundtrip, "prepare_copy_intent_instruction", predict)
    source = "The agent must write report.\n\nUnsupported reference above."
    report = frontend.prepare_intent_document(source, search_recovery=False)
    inference_calls = len(calls)
    result = ledger(source, report)
    sut.validate_intent_requirement_ledger(result, source_text=source)
    assert len(calls) == inference_calls
    assert len(result["requirements"]) == 1
    assert any(u["disposition"] == "unsupported" for u in result["source_units"])
    assert result["requirements"][0]["interpretation_status"] == "source_supported_candidate"


@pytest.mark.parametrize("source,kind", [
    ("If tests is valid, the agent must write report.", "if"),
    ("The agent must write report or the agent may delete cache.", "or"),
    ("The agent must write report and the agent must delete cache.", "and"),
    ("The agent must write report then the agent must delete cache.", "then"),
])
def test_existing_rich_compounds_remain_one_scoped_requirement(monkeypatch, source, kind):
    from ipfs_datasets_py.logic.intent_ir.formalize import rich_document as frontend
    from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_logic import _native_document
    def predict(instruction, descriptor, **kwargs):
        rich = {"schema": "intent-rich-ir/v1", "ast": rich_grammar.parse_instruction(instruction),
                "source_sha256": sha(instruction.encode())}
        native_view = _native_document(rich["ast"], instruction).to_dict() if kind == "then" else None
        return {"status": "semantic_candidate_advice", "rich_ir": rich,
                "logic": {"projections": [], "native_intent_ir": native_view},
                "counts": {"encoder_executions": 1, "decoder_executions": 1},
                "report_sha256": "b" * 64}
    monkeypatch.setattr(frontend, "prepare_rich_intent_instruction", predict)
    report = frontend.prepare_rich_intent_document(source,
        {"schema": "intent-rich-copy-checkpoint/v1"}, requested_families=["first_order"])
    result = ledger(source, report)
    assert len(result["requirements"]) == 1
    requirement = result["requirements"][0]
    assert requirement["representation"] == "rich_ast"
    assert requirement["kind"] == kind
    assert requirement["modality"] == "compound"
    assert requirement["compound"] == report["candidates"][0]["rich_ir"]
    if kind == "then":
        assert requirement["statement_ids"] == ["goal:0", "goal:1"]
        assert requirement["native_document_id"].startswith("intent-rich:")
    assert sut.validate_intent_requirement_ledger(result, source_text=source) is result


def rich_atom_report(source):
    from ipfs_datasets_py.logic.intent_ir.formalize import rich_document
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_logic import _native_document
    ast = parse_instruction(source)
    rich = {"schema": "intent-rich-ir/v1", "ast": ast, "source_sha256": sha(source.encode())}
    inference = {"status": "semantic_candidate_advice", "rich_ir": rich,
        "logic": {"native_intent_ir": _native_document(ast, source).to_dict(), "projections": []},
        "counts": {"encoder_executions": 1, "decoder_executions": 1}, "report_sha256": "b" * 64}
    with patch.object(rich_document, "prepare_rich_intent_instruction", return_value=inference):
        return rich_document.prepare_rich_intent_document(source,
            {"schema": "intent-rich-copy-checkpoint/v1"}, requested_families=["frame_logic"])


def test_rich_atomic_native_statement_preserves_dotted_identifier_and_modality():
    source = "The agent must write report.json."
    report = rich_atom_report(source)
    result = ledger(source, report)
    assert result["requirements"][0]["representation"] == "native_statement"
    assert result["requirements"][0]["modality"] == "required"
    assert result["requirements"][0]["statement_ids"] == ["goal:0"]
    assert result["requirements"][0]["compound"] is None


def test_rich_atomic_native_view_cannot_contradict_candidate_ast():
    source = "The agent must write report.json."
    report = rich_atom_report(source)
    report["units"][0]["inference"]["logic"]["native_intent_ir"]["statements"][0]["modality"] = "permitted"
    with pytest.raises(ValueError, match="native view differs"):
        ledger(source, stamp(report))


def test_inferred_native_statement_cannot_omit_source_reference():
    source = "Reviewed instruction."
    document = native(source)
    document = replace(document, statements=(replace(document.statements[0], source_ref_ids=()),))
    with pytest.raises(ValueError, match="source-bound statements"):
        ledger(source, reviewed_report(source, document))


def test_nonphysical_unicode_separators_keep_native_unsupported_frontier():
    from ipfs_datasets_py.logic.intent_ir.formalize.document_roundtrip import prepare_intent_document
    source = "```text\nQuoted\u2028```\u2028The agent must write report.\n```\n"
    report = prepare_intent_document(source, search_recovery=False)
    result = ledger(source, report)
    assert result["requirements"] == []
    assert result["source_units"][0]["unsupported_reason"] == "nonphysical_line_separator_requires_safe_parser"
    assert result["source_units"][0]["text"] == source


def test_nested_source_document_report_retains_full_outer_report(monkeypatch):
    from ipfs_datasets_py.logic.intent_ir.formalize import document_roundtrip as frontend
    from ipfs_datasets_py.logic.formalization.autoencoder.source_document import prepare_source_document
    source = "The agent must write report."
    monkeypatch.setattr(frontend.copy_roundtrip, "prepare_copy_intent_instruction", lambda instruction, _: {
        "status": "semantic_candidate_advice", "candidate_intent_ir": native(instruction).to_dict(),
        "learned": {"encoder": {}, "decoder": {}, "frame": {
            "actor": "agent", "action": "write", "object": "report", "modality": "required"}},
        "projections": {}, "extended_projections": {}, "report_sha256": "a" * 64})
    report = prepare_source_document(source, source_path="instruction.txt", source_format="intent")
    result = ledger(source, report)
    assert result["source_report"] == report
    assert len(result["requirements"]) == 1


def test_unavailable_intent_report_still_accounts_original_source():
    from ipfs_datasets_py.logic.formalization.autoencoder.source_document import prepare_source_document
    source = "Unsupported source."
    report = prepare_source_document(source, source_path="instruction.diff", source_format="diff")
    result = ledger(source, report)
    assert result["source_units"][0]["text"] == source
    assert result["source_units"][0]["disposition"] == "unsupported"
    assert result["requirements"] == []


def test_reviewed_native_ordering_preserves_scope_in_every_statement_requirement():
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_logic import _native_document
    source = "The agent must write report then the agent must delete cache."
    document = _native_document(parse_instruction(source), source)
    result = ledger(source, reviewed_report(source, document))
    assert len(result["requirements"]) == 2
    for requirement in result["requirements"]:
        assert requirement["representation"] == "native_statement"
        assert requirement["compound"]["schema"] == "intent-native-requirement-scope@1"
        assert requirement["compound"]["control_edges"] == [e.to_dict() for e in document.control_edges]
        assert requirement["compound"]["actions"] == [a.to_dict() for a in document.actions]
    assert sut.validate_intent_requirement_ledger(result, source_text=source) is result


def test_reviewed_native_conditional_and_action_contract_cannot_disappear():
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_logic import _native_document
    source = "The agent must write report then the agent must delete cache."
    document = _native_document(parse_instruction(source), source)
    guard = IntentStatement("guard:ready", StatementKind.GUARD, IntentModality.ASSERTED,
        "Review: cleanup only when report is ready", ("source",), predicate="report_ready",
        grounding=NodeGrounding.INFERRED)
    document = replace(document, statements=(*document.statements, guard),
        actions=(document.actions[0], replace(document.actions[1], precondition_ids=(guard.statement_id,))),
        control_edges=(replace(document.control_edges[0], kind=ControlEdgeKind.CONDITIONAL,
                               guard_statement_id=guard.statement_id),))
    result = ledger(source, reviewed_report(source, document))
    for requirement in result["requirements"]:
        context = requirement["compound"]
        assert context["control_edges"][0]["guard_statement_id"] == "guard:ready"
        assert context["actions"][1]["precondition_ids"] == ["guard:ready"]


def test_large_native_context_is_rejected_before_per_requirement_serialization(monkeypatch):
    source = "The agent must write report."
    document = native(source)
    document = replace(document,
        statements=tuple(replace(document.statements[0], statement_id=f"goal:{index}") for index in range(40)),
        actions=(replace(document.actions[0], input_refs=("input:" + "x" * (2 * 1_048_576),)),))
    report = reviewed_report(source, document)
    assert len(sut._wire(report)) < sut.MAX_REPORT_BYTES
    def unexpected_requirement_expansion(*args, **kwargs):
        pytest.fail("oversized repeated scope reached per-requirement serialization")
    monkeypatch.setattr(sut, "_requirement", unexpected_requirement_expansion)
    with pytest.raises(ValueError, match="scope expansion"):
        ledger(source, report)


@pytest.mark.parametrize("field", ["selection", "checkpoint_descriptor", "composition_recovery",
                                  "grammar_search_recovery", "projection_mode", "requested_families"])
def test_native_rich_report_cannot_drop_required_frontend_configuration(field):
    source = "The agent must write report.json."
    report = rich_atom_report(source)
    report.pop(field)
    with pytest.raises(ValueError, match="closed Intent source report"):
        ledger(source, stamp(report))


@pytest.mark.parametrize("field", ["scope", "inference", "selected_native_targets", "selected_projections"])
def test_native_rich_unit_cannot_drop_required_scope_and_trace(field):
    source = "The agent must write report.json."
    report = rich_atom_report(source)
    report["units"][0].pop(field)
    with pytest.raises(ValueError, match="closed source unit"):
        ledger(source, stamp(report))


def test_rich_candidate_needs_complete_reported_scope_and_identical_inference_ast():
    source = "The agent must write report.json."
    report = rich_atom_report(source)
    report["units"][0]["scope"]["complete_source_consumption"] = False
    with pytest.raises(ValueError, match="complete source scope"):
        ledger(source, stamp(report))
    report = rich_atom_report(source)
    report["units"][0]["inference"]["rich_ir"]["ast"]["modality"] = "permitted"
    with pytest.raises(ValueError, match="source surface|unit inference"):
        ledger(source, stamp(report))


@pytest.mark.parametrize("identity", ["", {}, [], {"non_json": object()}])
def test_invalid_source_identity_rejected(identity):
    source = "The agent must write report."
    with pytest.raises(ValueError):
        sut.build_intent_requirement_ledger(source, source_report=reviewed_report(source), source_identity=identity)
