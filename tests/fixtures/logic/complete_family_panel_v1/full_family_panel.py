"""Authored integration assumptions, not source-inferred or proved models."""
from collections import Counter
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as original
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v2 as api


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load("ipfs_datasets_py.optimizers.logic_theorem_optimizer._complete_training_panel", Path(__file__).with_name("fresh_panel.py"))
tests = Path(original.__file__).resolve().parents[3] / "tests/unit/logic"
fixtures = load("complete_family_fixtures", tests / "formalization/autoencoder/test_family_training_v2.py")
EXPECTED = {
    "intent_ir": {"first_order", "deontic", "intention_agency", "program", "temporal", "dcec", "tdfol", "event_calculus", "frame_logic", "datalog", "horn_chc", "transition_system", "higher_order", "refinement", "authorization"},
    "security_ir": {"program", "transition_system", "temporal", "separation_logic", "hyperproperty", "authorization", "cryptographic_protocol", "concurrency", "refinement"},
    "ui_ux_ir": {"frame_logic", "event_calculus", "tdfol", "dcec", "transition_system", "temporal", "program", "authorization"},
    "legal_ir": {"deontic", "tdfol", "frame_logic", "event_calculus", "authorization", "temporal"},
}


def policy(source, row):
    from ipfs_datasets_py.logic.software_verification.authorization import AuthorizationIR, AuthorizationPrincipal, AuthorizationFact, AuthorizationAtom, AuthorizationTerm, PredicateSignature
    actor, action = base.ACTORS[row["actor"]], base.ACTIONS[row["action"]]
    principal, predicate = "principal:" + actor, "predicate:" + action
    refs = {"source_ref_ids": (source.ref_id,)}
    return AuthorizationIR(sources=(source,), principals=(AuthorizationPrincipal(principal, actor, **refs),),
        trust_root_principal_ids=(principal,), predicates=(PredicateSignature(predicate, "can_" + action, 1, ("principal",), **refs),),
        facts=(AuthorizationFact("fact:allowed", AuthorizationAtom(predicate, (AuthorizationTerm.constant(principal, "principal"),)), **refs),))


def protocol(source, raw):
    model = fixtures.protocol_fixtures._document()
    value = model.to_dict()
    previous = value["sources"][0]["ref_id"]
    def visit(item):
        if isinstance(item, dict):
            if "ref_id" in item and "content_sha256" in item: return source.to_dict()
            result = {key: visit(child) for key, child in item.items()}
            if "start_byte" in result and "end_byte" in result:
                result.update(start_byte=0, end_byte=len(raw))
            return result
        if isinstance(item, list): return [visit(child) for child in item]
        return source.ref_id if item == previous else item
    value = visit(value)
    value["document_id"] = ""
    return type(model).from_dict(value)


def legal_document(row, text):
    from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
    from ipfs_datasets_py.logic.bridge.types import BridgeEvaluationReport, LegalIRDocument, LogicIRView, RoundTripMetrics
    actor, action, ref = base.ACTORS[row["actor"]], base.ACTIONS[row["action"]], row["source_id"]
    payloads = {
        "deontic_norms": {
            "deontic_ir": {"norms": [{"action": action, "action_object": "record", "actor": actor, "conditions": ["within 10 days"], "exceptions": [], "norm_type": "permission" if row["variant"] else "obligation", "source_id": ref}]},
            "deontic_formula_records": {"records": [{"formula_id": "formula:norm", "source_id": ref}]},
            "deontic_decoder_reconstructions": {"records": [{"reconstruction_id": "authored:norm", "semantic_family": "deontic", "source_id": ref}]},
            "frame_logic": {"triples": [{"object": "record", "predicate": "permits" if row["variant"] else "obliges", "subject": ref}]}},
        "fol_tdfol": {"tdfol_formula": {"records": [{"formula": f"forall x. {action}(x)", "quantifiers": ["forall"], "source_id": ref}]}},
        "cec_dcec": {"cec_events": {"events": [{"event_id": "event:completion", "event_role": "completion", "source_id": ref}]},
            "event_calculus": {"records": [{"event_formula_fingerprint": "fluent:completion", "selected_frame": action, "source_id": ref}]}}}
    reports = {}
    for name, payload in payloads.items():
        views = {key: LogicIRView(name=key, payload=value, source_component=name) for key, value in payload.items()}
        document = LegalIRDocument("authored:" + name + ":" + ref, text, text, views=views)
        reports[name] = BridgeEvaluationReport(name, name, document, RoundTripMetrics(), status="partial")
    return MultiViewLegalIRReport(tuple(reports), LegalIRDocument("authored:merged:" + ref, text, text), reports=reports)


def source_inputs(row):
    original = base.source_inputs(row)
    domain = row["domain_id"]
    if domain == "intent_ir":
        from ipfs_datasets_py.logic.intent_ir.formalize.rich_logic import _native_document
        from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256
        from ipfs_datasets_py.logic.intent_ir.schema import IntentStatement, IntentModality, StatementKind, NodeGrounding
        ast = original["document"]
        text = original["source_text"] + f" {ast['actor']} intends to {ast['action']} {ast['object']}. The record remains stable. The declared action occurs at time {row['variant']}. A typed refinement and authorization model are supplied as assumptions."
        document = _native_document(ast, text)
        source_id = document.sources[0].ref_id
        intended = replace(document.statements[0], statement_id="goal:intended", modality=IntentModality.INTENDED,
            normalized_text=f"{ast['actor']} intends to {ast['action']} {ast['object']}.")
        invariant = IntentStatement("invariant:stable", StatementKind.INVARIANT, IntentModality.ASSERTED,
            "The record remains stable.", (source_id,), predicate="stable", arguments=("record",), grounding=NodeGrounding.INFERRED)
        document = replace(document, statements=(*document.statements, intended, invariant))
        document.validate()
        refinement = fixtures.concurrency_fixtures._counter_refinement()
        result = {"document": document, "source_text": text, "context": {
            "modal": {"event_occurrences": [{"action_id": document.actions[0].action_id, "time": row["variant"], "evidence_ref": source_id}]},
            "structural": {"refinement_evidence": {"source_ir_sha256": source_ir_sha256(document), "document": refinement.to_dict()}}}}
    elif domain == "legal_ir":
        from ipfs_datasets_py.logic.software_verification.temporal import TemporalFormula
        text = original["source_text"] + " An authored completion event updates the completion frame. The stable property holds at every position. A separate authorization policy is supplied as an assumption."
        result = {"document": legal_document(row, text), "source_text": text}
        source = api.supplemental_source_ref(domain, **result)
        refs = {"source_ref_ids": (source.ref_id,)}
        temporal = TemporalFormula("always", operands=(TemporalFormula("atom", proposition="declared_stable", **refs),), **refs)
        result["supplemental_inputs"] = [api.TypedFamilyEvidence(policy(source, row), source), api.TypedFamilyEvidence(temporal, source)]
        return result
    else:
        result = original
    source = api.supplemental_source_ref(domain, **result)
    models = [policy(source, row)]
    if domain == "security_ir":
        models += [fixtures.concurrency_fixtures._producer_consumer(), fixtures.concurrency_fixtures._counter_refinement(), protocol(source, result["source_bytes"])]
    elif domain == "ui_ux_ir":
        models += [fixtures.fixtures._security.program(source), fixtures.fixtures._security.contract(source)]
    result["supplemental_inputs"] = [api.TypedFamilyEvidence(model, source) for model in models]
    return result


def prepare_partition(domain, split):
    results = []
    for row in base.rows(domain, split):
        inputs = source_inputs(row)
        report = api.prepare_family_training_targets_v2(domain, **inputs)
        api.validate_family_training_report_v2(report, **inputs)
        results.append(report)
    return results


def coverage(reports):
    counts = Counter(p["logic_family"] for row in reports for p in row["projections"] if p["ready_for_training"])
    return dict(sorted(counts.items()))
