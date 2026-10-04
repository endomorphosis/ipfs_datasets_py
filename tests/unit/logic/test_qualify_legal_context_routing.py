"""Independent accounting/phase-order tests; real diagnostic predictions stay sealed."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.ops.legal_ir import qualify_legal_context_routing as q


def source(index, prefix="source"):
    text = f"{prefix} text {index}"
    return {"id": f"{prefix}-{index}", "source_text": text,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest()}


def decision(src, eligible):
    return {"source_id": src["id"], "source_sha256": src["source_sha256"],
            "decoder_eligible": eligible, "route": "possible_norm" if eligible else "definition"}


def prediction(src, decoded):
    return {"source_sha256": src["source_sha256"], "status": "decoded" if decoded else "abstained",
            "canonical_ir": {"rules": [{"modality": "O", "action": "archive"}]} if decoded else None,
            "target_access": False, "teacher_forcing": False, "latent_input_enabled": False,
            "source_input_conditioned": True, "admitted": False, "semantic_correctness_verified": False}


def label(src, expected):
    return {"source_id": src["id"], "expected_eligible": expected, "control_family": "fixture",
            "origin": "independently_authored_routing_contract"}


def test_complete_accounting_preserves_candidates_and_abstentions():
    sources = [source(i) for i in range(4)]
    rows = [prediction(s, i < 2) for i, s in enumerate(sources)]
    original = deepcopy(rows)
    routes = [decision(s, i % 2 == 0) for i, s in enumerate(sources)]
    result = q.compare_routing(sources, rows, routes)
    assert result["counts"] == {"slots": 4, "before_decoded": 2, "before_abstained": 2,
        "retained_candidate": 1, "route_deferred_candidate": 1, "decoder_abstained": 2,
        "eligible_source_slots": 2, "deferred_source_slots": 2}
    assert rows == original
    assert [r["unchanged_candidate"] for r in result["rows"]] == [r["canonical_ir"] for r in rows]
    assert all(r["prediction_sha256"] == q.digest(old) for r, old in zip(result["rows"], rows))
    assert result["statutory_accuracy"] is None
    assert result["candidate_suppression_is_accuracy_improvement"] is False


@pytest.mark.parametrize("mutation", ["missing", "hash", "order", "boolean", "category"])
def test_route_contract_rejects_denominator_and_join_tampering(mutation):
    sources = [source(0), source(1)]
    routes = [decision(s, True) for s in sources]
    if mutation == "missing": routes.pop()
    if mutation == "hash": routes[0]["source_sha256"] = "0" * 64
    if mutation == "order": routes.reverse()
    if mutation == "boolean": routes[0]["decoder_eligible"] = 1
    if mutation == "category": routes[0]["route"] = "definition"
    with pytest.raises(ValueError): q.route_index(sources, routes)


@pytest.mark.parametrize("mutation", ["source_hash", "missing", "flatten", "target_access", "teacher_forcing",
                                    "latent_input_enabled", "admitted", "semantic_correctness_verified", "candidate"])
def test_saved_generation_requires_full_source_only_contract(mutation):
    sources = [source(0), source(1)]
    rows = [prediction(s, True) for s in sources]
    generation = {"target_access": False, "rows": rows, "reports": [{"rows": deepcopy(rows)}]}
    if mutation == "source_hash": generation["rows"][0]["source_sha256"] = "0" * 64
    elif mutation == "missing": generation["rows"].pop()
    elif mutation == "flatten": generation["reports"] = []
    elif mutation == "candidate": generation["rows"][0]["canonical_ir"] = None
    else: generation["rows"][0][mutation] = True
    if mutation != "flatten": generation["reports"] = [{"rows": deepcopy(generation["rows"])}]
    with pytest.raises(ValueError): q.prediction_rows(generation, sources)


@pytest.mark.parametrize("actual,retained,rejected,false_accept,passed", [
    ([False, False], 0, 1, 0, False),
    ([True, True], 1, 0, 1, False),
    ([True, False], 1, 0, 0, True),
])
def test_controls_report_false_rejection_and_all_reject_cannot_pass(actual, retained, rejected, false_accept, passed):
    sources = [source(0), source(1)]
    result = q.score_controls(sources, [decision(s, v) for s, v in zip(sources, actual)],
                             [label(sources[0], True), label(sources[1], False)])
    assert result["counts"]["valid_norm_retained"] == retained
    assert result["counts"]["valid_norm_false_rejection"] == rejected
    assert result["counts"]["deferred_type_false_acceptance"] == false_accept
    assert result["declared_control_contract_passed"] is passed
    assert result["all_reject_is_success"] is False
    assert result["statutory_accuracy"] is None


@pytest.mark.parametrize("expected", [[True, True], [False, False]])
def test_one_sided_controls_are_not_valid_evaluation(expected):
    sources = [source(0), source(1)]
    with pytest.raises(ValueError, match="include valid norms and deferred"):
        q.score_controls(sources, [decision(s, False) for s in sources],
                         [label(s, v) for s, v in zip(sources, expected)])


def test_control_expectations_must_be_independently_authored_and_joined():
    sources = [source(0), source(1)]
    labels = [label(sources[0], True), label(sources[1], False)]
    labels[1]["origin"] = "router_prediction"
    with pytest.raises(ValueError, match="provenance"):
        q.score_controls(sources, [decision(s, True) for s in sources], labels)


def test_authored_control_creation_preserves_real_offsets_and_no_government_claim(tmp_path):
    manifest = q.read(q.prepare_controls(tmp_path / "controls"))
    sources = q.read(manifest["sources"])
    labels = q.read(manifest["targets"])
    assert len(sources) == len(labels) == 30
    assert sum(row["expected_eligible"] for row in labels) == 18
    assert len({s["id"] for s in sources}) == 30
    assert manifest["statutory_gold"] is False
    for src, record in zip(sources, manifest["documents"]):
        doc = q.read(record["document"])
        assert src["source_text"] == doc["document_text"][src["char_start"]:src["char_end"]]
        assert src["document"] == record["document"]
        assert record["retrieved_from_government"] is False
        assert record["official_url_literal_is_parser_contract_only"] is True


def test_changed_artifact_rejected_even_if_json_still_parses(tmp_path):
    path = tmp_path / "evidence.json"
    pin = q.write(path, {"value": 1})
    path.write_text('{"value": 2}')
    with pytest.raises(ValueError, match="bytes changed"): q.read(pin)


@pytest.mark.parametrize("authority", [None, "context_resolved", "semantic_rejection", "source_semantics_verified",
                                       "independently_reviewed", "training_qualified"])
def test_route_inventory_reads_only_source_artifacts_and_disallows_authority(tmp_path, monkeypatch, authority):
    from ipfs_datasets_py.logic.autoformal import legal_statutory_routing as routing
    doc = {"document_id": "fictional-control"}
    doc_ref = q.write(tmp_path / "document.json", doc)
    raw_path = tmp_path / "raw.html"; raw_path.write_bytes(b"fixture")
    src = source(0); src.update(document_id=doc["document_id"], document=doc_ref)
    targets = {"path": str(tmp_path / "must-never-be-opened.json")}
    manifest = {"targets": targets, "documents": [{"document": doc_ref, "raw_html": q.reference(raw_path)}]}
    def route(source_arg, document_arg, raw_arg):
        assert source_arg == src and document_arg == doc and raw_arg == b"fixture"
        out = decision(src, True)
        out.update({k: False for k in ("context_resolved", "semantic_rejection", "source_semantics_verified",
                                       "independently_reviewed", "training_qualified")})
        out["reference_accuracy"] = None
        if authority: out[authority] = True
        return out
    monkeypatch.setattr(routing, "route_source", route)
    if authority:
        with pytest.raises(ValueError, match="semantic authority"):
            q.route_inventory(manifest, [src])
    else:
        assert q.route_inventory(manifest, [src])[0]["decoder_eligible"] is True
    assert not Path(targets["path"]).exists()


def fake_study(tmp_path):
    prior, controls = tmp_path / "prior", tmp_path / "controls"
    prior.mkdir(); controls.mkdir()
    sources = [source(i) for i in range(86)]
    single_ref = q.write(prior / "source-inputs.json", sources)
    manifest_ref = q.write(prior / "manifest.json", {"sources": single_ref, "documents": [],
        "views_are_independent_examples": False, "implementation": []})
    models = []
    for i in range(18):
        rows = [prediction(s, j % 2 == 0) for j, s in enumerate(sources)]
        generation = q.write(prior / f"model-{i}.json", {"rows": rows, "reports": [{"rows": rows}], "target_access": False})
        models.append({"name": f"arm{i//3}-{i%3}", "checkpoint": single_ref, "diagnostics": single_ref,
            "generation": generation, "decoded": 43, "abstained": 43, "exact_replay": True, "reference_accuracy": None})
    plan = q.write(prior / "plan.json", {"manifest": manifest_ref, "checkpoint_index": single_ref,
        "model_names": [m["name"] for m in models], "inference_fields": ["source_text"],
        "fitting_performed": False, "selection_performed": False, "implementation": []})
    prior_ref = q.write(prior / "summary.json", {"plan": plan, "models": models, "source_views": 86,
        "model_source_slots": 1548, "reference_accuracy_available": False, "independent_gold_count": 0,
        "fitting_performed": False, "training_qualified": False, "source_semantics_verified": False})
    control_sources = [source(i, "authored") for i in range(30)]
    control_sources_ref = q.write(controls / "sources.json", control_sources)
    targets = q.write(controls / "targets.json", [label(s, i < 18) for i, s in enumerate(control_sources)])
    controls_ref = q.write(controls / "manifest.json", {"schema": "legal-context-routing-independent-controls/v1",
        "sources": control_sources_ref, "targets": targets, "documents": [], "references_created_before_routing": True,
        "statutory_gold": False, "implementation": q.reference(q.__file__),
        "counts": {"sources": 30, "valid_norms": 18, "deferred_types": 12}})
    return prior_ref, controls_ref, targets


def test_full_prior_comparison_opens_controls_only_after_all_decisions_are_frozen(tmp_path, monkeypatch):
    prior, controls, targets = fake_study(tmp_path)
    output = tmp_path / "qualified"
    opened, old_read = [], q.read
    def checked_read(pin):
        if pin["path"] == targets["path"]:
            assert (output / "routing-decisions-frozen.json").exists()
            freeze = json.loads((output / "routing-decisions-frozen.json").read_text())
            assert freeze["control_expectations_opened"] is False
            assert len(freeze["model_comparisons"]) == 18
            assert all(Path(r["path"]).exists() for r in freeze["model_comparisons"])
            opened.append(pin)
        return old_read(pin)
    def route(_manifest, sources):
        limit = 43 if len(sources) == 86 else 18
        return [decision(s, i < limit) for i, s in enumerate(sources)]
    monkeypatch.setattr(q, "read", checked_read)
    monkeypatch.setattr(q, "route_inventory", route)
    summary = old_read(q.qualify_prior(prior["path"], controls["path"], output))
    assert opened == [targets]
    assert summary["counts"]["slots"] == 1548
    assert summary["counts"]["before_decoded"] == 774
    assert summary["counts"]["retained_candidate"] == 18 * 22
    assert summary["counts"]["route_deferred_candidate"] == 18 * 21
    assert summary["counts"]["decoder_abstained"] == 774
    assert len(summary["models"]) == 18
    assert len(summary["by_arm"]) == 6
    assert summary["model_inference_calls"] == summary["training_updates"] == summary["native_compiler_calls"] == 0
    assert summary["statutory_accuracy"] is None
    assert old_read(summary["controls"])["declared_control_contract_passed"] is True


def test_prior_comparison_rejects_missing_model_before_control_target_read(tmp_path, monkeypatch):
    prior, controls, targets = fake_study(tmp_path)
    value = q.read(prior); value["models"].pop()
    Path(prior["path"]).write_text(json.dumps(value))
    old_read = q.read
    def checked_read(pin):
        assert pin["path"] != targets["path"]
        return old_read(pin)
    monkeypatch.setattr(q, "read", checked_read)
    with pytest.raises(ValueError, match="model inventory"):
        q.qualify_prior(prior["path"], controls["path"], tmp_path / "qualified")
