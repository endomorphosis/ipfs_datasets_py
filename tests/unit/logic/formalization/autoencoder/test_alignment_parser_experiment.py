"""Actual parser comparison, immutable baseline replay, and evidence boundaries."""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_parser_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_experiment import (
    run_richer_experiment,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary

ROOT = Path(__file__).resolve().parents[5]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def binding(path, workspace):
    return {"path": str(path.relative_to(workspace)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def configuration():
    return {"schema": subject.CONFIG_SCHEMA, "study_id": "autoformalization-parser-development-v1",
            "richer_report": {"path": "richer/report.json", "sha256": "a" * 64}, "max_seconds": 120}


@pytest.mark.parametrize("field,value", [("schema", "unknown"), ("study_id", "final-test"), ("max_seconds", True),
    ("max_seconds", 0), ("max_seconds", 121), ("max_seconds", float("nan")), ("max_seconds", 10**400),
    ("richer_report", {"path": "x", "sha256": "A" * 64}), ("richer_report", {"path": "", "sha256": "a" * 64}),
    ("richer_report", {"path": "x", "sha256": "a" * 64, "allow_unpinned": True})])
def test_configuration_rejects_altered_scope_and_invalid_resource_or_evidence_identity(tmp_path, field, value):
    settings = configuration()
    settings[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        subject.load_parser_config(path)


def test_config_digest_uses_exact_parsed_bytes_and_closed_keys(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    raw = (json.dumps(configuration(), indent=3) + "\n").encode()
    path.write_bytes(raw)
    read = subject._bounded_bytes

    def read_then_change(supplied, limit):
        captured = read(supplied, limit)
        path.write_text(json.dumps({**configuration(), "max_seconds": 60}))
        return captured

    monkeypatch.setattr(subject, "_bounded_bytes", read_then_change)
    settings, observed = subject.load_parser_config(path)
    assert settings["max_seconds"] == 120 and observed["sha256"] == hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(subject, "_bounded_bytes", read)
    path.write_text(json.dumps({**configuration(), "gold_supplied": True}))
    with pytest.raises(ValueError, match="closed"):
        subject.load_parser_config(path)


@pytest.fixture
def predecessor(tmp_path):
    base = json.loads((ROOT / "configs/autoencoders/alignment_study_development_v1.json").read_text())
    (tmp_path / "protocol.md").write_text("protected parser test protocol")
    (tmp_path / "provenance.json").write_text("{}")
    base["protected_protocols"] = [binding(tmp_path / "protocol.md", tmp_path)]
    base["corpus"]["provenance"] = [binding(tmp_path / "provenance.json", tmp_path)]
    target = {"rules": [{"modality": "O", "actor": "clerk", "action": "retain", "object": "certificate",
                         "conditions": [], "exceptions": [], "temporal": []}]}
    source, vector = "The clerk must retain the certificate.", [1.] + [0.] * 383
    row = {"id": "original-train", "group_id": "original-train", "split": "train", "source_text": source,
           "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "embedding": vector,
           "embedding_sha256": digest(vector), "target": target}
    (tmp_path / "train.json").write_text(json.dumps({"rows": [row]}))
    base["corpus"]["train"] = binding(tmp_path / "train.json", tmp_path)
    base["corpus"]["development"] = {"path": "validation.json", "sha256": "b" * 64}
    (tmp_path / "study.json").write_text(json.dumps(base))
    richer = {"schema": "alignment-richer-experiment-config/v1", "study_id": "autoformalization-richer-development-v1",
              "study_config": binding(tmp_path / "study.json", tmp_path), "max_seconds": 120}
    (tmp_path / "richer.json").write_text(json.dumps(richer))
    report = run_richer_experiment(tmp_path / "richer.json", ROOT, tmp_path, tmp_path / "richer")
    settings = configuration()
    settings["richer_report"] = binding(tmp_path / "richer/report.json", tmp_path)
    (tmp_path / "parser.json").write_text(json.dumps(settings))
    return tmp_path, tmp_path / "parser.json", report


def test_actual_new_composition_replays_old_receipts_and_improves_known_qualifier_cases(predecessor):
    workspace, config, prior = predecessor
    old_bytes = (workspace / "richer/constructions.json").read_bytes()
    report = subject.run_parser_experiment(config, ROOT, workspace, workspace / "parser")
    assert report["status"] == "completed" and report["baseline_exact_replay_records"] == 34
    assert (workspace / "richer/constructions.json").read_bytes() == old_bytes
    assert not (workspace / "validation.json").exists()
    assert report["baseline_summaries"] == prior["summaries"]
    assert report["summaries"]["all"]["positive_exact_authored_ir"] == 22
    assert report["summaries"]["development"]["positive_exact_authored_ir"] == 6
    assert report["summaries"]["train"]["positive_exact_authored_ir"] == 16
    assert report["exact_authored_gains"] == 18 and report["exact_authored_regressions"] == 0
    assert report["summaries"]["all"]["negative_ir_emissions"] == 0
    assert report["summaries"]["all"]["explicit_context_ir_emissions"] == 0
    assert len(report["clarification_pattern_rows"]) == 1
    assert "identity_verified" not in report["training_vocabulary"]["qualifiers"]
    assert report["development_used_to_design_grammar"] is True
    assert report["development_used_in_vocabulary_fit"] is False
    assert report["default_compiler_replaced"] is False and report["frozen_roundtrip_composition_admitted"] is False
    assert report["qualified"] is False and report["production_admitted"] is False
    assert report["native_useful_proof_coverage"] == {"status": "unrun", "value": None}
    assert report["report_sha256"] == digest({key: value for key, value in report.items() if key != "report_sha256"})
    rows = json.loads(Path(report["construction_binding"]["path"]).read_text())["rows"]
    assert len(rows) == 34
    for row in rows:
        construction = subject.validate_explicit_construction(row["construction"])
        assert subject.score_explicit_reference(construction, row["authored_target"]) == row["posthoc_authored_score"]
        if construction["canonical_ir"] is not None:
            assert construction["roundtrip"]["exact_ir"] is True
            assert construction["roundtrip"]["renderer_request"]["canonical_ir"] == construction["canonical_ir"]
        if row["row_kind"] == "explicit_context":
            assert construction["compiler_result"] is None and construction["construction_status"] == "unavailable"


def simple_construction():
    vocabulary = CanonicalAtomVocabulary(actors=("clerk",), actions=("retain",), objects=("record",), qualifiers=("public_interest",))
    return subject.construct_explicit_source("The clerk must retain the record if public interest.", vocabulary, request_id="independent-query")


def test_reference_mutation_cannot_change_sealed_source_construction():
    before = simple_construction()
    expected = json.loads(json.dumps(before["canonical_ir"]))
    assert subject.score_explicit_reference(before, expected)["exact_ir"] is True
    expected["rules"][0]["modality"] = "P"
    assert subject.score_explicit_reference(before, expected)["exact_ir"] is False
    assert simple_construction() == before
    assert "authored_target" not in inspect.signature(subject.construct_explicit_source).parameters


@pytest.mark.parametrize("fault", ["content", "source", "vocabulary", "roundtrip", "candidate", "proof", "context", "composition", "bridge", "outcome", "extra_authority"])
def test_rehashed_evidence_cannot_hide_stage_or_authority_changes(fault):
    record = simple_construction()
    if fault == "content":
        record["content_sha256"] = "a" * 64
    elif fault == "source":
        record["source_sha256"] = "a" * 64
    elif fault == "vocabulary":
        record["vocabulary_sha256"] = "a" * 64
    elif fault == "roundtrip":
        record["roundtrip"]["exact_ir"] = False
    elif fault == "candidate":
        record["canonical_ir"]["rules"][0]["actor"] = "officer"
    elif fault == "proof":
        record["proof_scopes"]["native_proof"]["status"] = "proved"
    elif fault == "context":
        record["context"]["requires_resolution"] = True
    elif fault == "composition":
        record["composition"]["frozen_roundtrip_composition_admitted"] = True
    elif fault == "bridge":
        assert record["native_projection"]["status"] == "executed"
        record["native_projection"]["artifact_sha256"] = "a" * 64
    elif fault == "outcome":
        record["admission_outcome"] = "proved"
    elif fault == "extra_authority":
        record["production_admitted"] = True
    if fault != "content":
        record["content_sha256"] = digest({key: value for key, value in record.items() if key != "content_sha256"})
    with pytest.raises(ValueError):
        subject.validate_explicit_construction(record)


def test_context_role_cannot_be_silently_discarded_or_inferred():
    vocabulary = CanonicalAtomVocabulary(actors=("clerk",), actions=("retain",), objects=("record",))
    with pytest.raises(ValueError, match="context role"):
        subject.construct_explicit_source("The clerk must retain record.", vocabulary, request_id="context", context_text="Assume clerk.")
    record = subject.construct_explicit_source("The clerk must retain record.", vocabulary, request_id="context",
                                               requires_context_resolution=True, context_text="The role denotes the clerk.")
    assert record["compiler_result"] is None and record["native_projection"]["status"] == "unrun"
    subject.validate_explicit_construction(record)


def test_existing_output_and_foreign_tree_fail_before_reading_evidence(tmp_path):
    with pytest.raises(ValueError, match="executing"):
        subject.run_parser_experiment(tmp_path / "missing", tmp_path, tmp_path, tmp_path / "new")
    with pytest.raises(ValueError, match="fresh output"):
        subject.run_parser_experiment(tmp_path / "missing", ROOT, tmp_path, tmp_path)


def test_loaded_guard_origin_must_match_the_bound_source(predecessor, monkeypatch):
    workspace, config, _ = predecessor
    name = "ipfs_datasets_py.logic.legal_ir.canonical_source_guards"
    monkeypatch.setitem(sys.modules, name, SimpleNamespace(__file__=str(workspace / "foreign.py")))
    with pytest.raises(ValueError, match="another tree"):
        subject.run_parser_experiment(config, ROOT, workspace, workspace / "foreign")


def test_protocol_drift_during_new_construction_prevents_report_publication(predecessor, monkeypatch):
    workspace, config, _ = predecessor
    construct = subject.construct_explicit_source

    def mutate_protocol(*args, **kwargs):
        result = construct(*args, **kwargs)
        (workspace / "protocol.md").write_text("concurrent protected protocol change")
        return result

    monkeypatch.setattr(subject, "construct_explicit_source", mutate_protocol)
    output = workspace / "drift"
    with pytest.raises(ValueError, match="input digest mismatch"):
        subject.run_parser_experiment(config, ROOT, workspace, output)
    assert not output.exists()


def test_expired_deadline_prevents_query_execution_and_publication(predecessor, monkeypatch):
    workspace, config, _ = predecessor
    monkeypatch.setattr(subject, "time", SimpleNamespace(perf_counter=lambda: 1000.))
    original = subject.construct_panel_sources

    def expired(panel, vocabulary, deadline):
        subject._deadline(0.)
        return original(panel, vocabulary, deadline)

    monkeypatch.setattr(subject, "construct_panel_sources", expired)
    with pytest.raises(ValueError, match="deadline"):
        subject.run_parser_experiment(config, ROOT, workspace, workspace / "expired")
    assert not (workspace / "expired").exists()


def test_promoted_predecessor_is_rejected_even_with_recomputed_digests(predecessor):
    workspace, config, _ = predecessor
    path = workspace / "richer/report.json"
    report = json.loads(path.read_text())
    report["qualified"] = True
    report["report_sha256"] = digest({key: value for key, value in report.items() if key != "report_sha256"})
    path.write_text(json.dumps(report))
    settings = json.loads(config.read_text())
    settings["richer_report"] = binding(path, workspace)
    config.write_text(json.dumps(settings))
    with pytest.raises(ValueError, match="scope"):
        subject.run_parser_experiment(config, ROOT, workspace, workspace / "promoted")


def test_rehashed_baseline_change_cannot_pass_exact_replay(predecessor):
    workspace, config, _ = predecessor
    path = workspace / "richer/constructions.json"
    old = json.loads(path.read_text())
    old["rows"][0]["construction"]["model_call_count"] = 1
    path.write_text(json.dumps(old))
    prior_path = workspace / "richer/report.json"
    prior = json.loads(prior_path.read_text())
    prior["construction_binding"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    prior["construction_binding"]["bytes"] = path.stat().st_size
    prior["report_sha256"] = digest({key: value for key, value in prior.items() if key != "report_sha256"})
    prior_path.write_text(json.dumps(prior))
    settings = json.loads(config.read_text())
    settings["richer_report"] = binding(prior_path, workspace)
    config.write_text(json.dumps(settings))
    with pytest.raises(ValueError, match="baseline replay"):
        subject.run_parser_experiment(config, ROOT, workspace, workspace / "changed-baseline")
