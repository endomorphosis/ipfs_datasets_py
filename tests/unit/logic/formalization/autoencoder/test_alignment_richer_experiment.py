"""Richer construction boundaries, frozen codec losses, and honest evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_projection import (
    fit_legal_feature_codec,
)

ROOT = Path(__file__).resolve().parents[5]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def binding(path, workspace):
    return {"path": str(path.relative_to(workspace)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def configuration():
    return {"schema": "alignment-richer-experiment-config/v1",
            "study_id": "autoformalization-richer-development-v1",
            "study_config": {"path": "study.json", "sha256": "a" * 64}, "max_seconds": 120}


def target(*, conditions=(), exceptions=(), temporal=(), modality="O", actor="clerk"):
    return {"rules": [{"modality": modality, "actor": actor, "action": "retain", "object": "certificate",
                       "conditions": sorted(conditions), "exceptions": sorted(exceptions), "temporal": sorted(temporal)}]}


@pytest.mark.parametrize("field,value", [
    ("schema", "alignment-richer-experiment-config/v99"),
    ("study_id", "sealed-final-study"),
    ("max_seconds", True), ("max_seconds", 0), ("max_seconds", 121),
    ("max_seconds", float("nan")), ("max_seconds", float("inf")), ("max_seconds", 10**400),
    ("study_config", {"path": "study.json", "sha256": "a" * 63}),
    ("study_config", {"path": "study.json", "sha256": "A" * 64}),
    ("study_config", {"path": "", "sha256": "a" * 64}),
    ("study_config", {"path": "study.json", "sha256": "a" * 64, "admitted": True}),
])
def test_closed_configuration_rejects_wrong_scope_or_bounds(tmp_path, field, value):
    config = configuration()
    config[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        subject.load_richer_config(path)


def test_config_binds_exact_parsed_bytes_and_rejects_unknown_fields(tmp_path):
    config = configuration()
    path = tmp_path / "config.json"
    original = (json.dumps(config, indent=3) + "\n").encode()
    path.write_bytes(original)
    settings, observed = subject.load_richer_config(path)
    assert settings == config
    assert observed["sha256"] == hashlib.sha256(original).hexdigest()
    assert observed["bytes"] == len(original)
    config["dev_target_vocabulary"] = True
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="closed"):
        subject.load_richer_config(path)


def test_config_binding_is_the_parsed_generation_when_file_changes(tmp_path, monkeypatch):
    config = configuration()
    path = tmp_path / "config.json"
    original = json.dumps(config).encode()
    path.write_bytes(original)
    changed = {**config, "max_seconds": 60}
    read = subject._bounded_bytes

    def capture_then_change(supplied, limit):
        captured = read(supplied, limit)
        path.write_text(json.dumps(changed))
        return captured

    monkeypatch.setattr(subject, "_bounded_bytes", capture_then_change)
    settings, observed = subject.load_richer_config(path)
    assert settings == config and json.loads(path.read_bytes()) == changed
    assert observed["sha256"] == hashlib.sha256(original).hexdigest()


def test_duplicate_config_fields_are_rejected(tmp_path):
    path = tmp_path / "config.json"
    raw = json.dumps(configuration())
    path.write_text(raw[:-1] + ', "max_seconds": 1}')
    with pytest.raises(ValueError):
        subject.load_richer_config(path)


def test_distinct_unknown_payload_collisions_do_not_count_duplicate_wordings():
    codec = fit_legal_feature_codec([target(conditions=["public interest"])])
    row_targets = [target(conditions=["red"]), target(conditions=["red"]),
                   target(conditions=["blue"]), target(conditions=["blue", "red"]),
                   target(conditions=["green", "yellow"]), target(exceptions=["red"]),
                   target(temporal=["red"]), target(conditions=["public interest"]), target()]
    rows = [{"id": str(index), "target": value} for index, value in enumerate(row_targets)]
    result = subject.representation_collision_assay(rows, codec)
    assert result["rows"] == 9 and result["distinct_target_payloads"] == 8
    assert result["distinct_feature_vectors"] == 6 and result["collision_groups"] == 2
    assert result["distinct_target_collision_pairs"] == 2 and result["rows_in_collision_groups"] == 5
    assert result["same_core_distinct_target_collision_pairs"] == 2
    assert all(item["differing_facets"] == ["conditions"] for item in result["collisions"])
    assert result["unknown_atom_counts"]["conditions"] == 7
    assert result["unknown_atom_counts"]["exceptions"] == 1
    assert result["unknown_atom_counts"]["temporal"] == 1
    rows_by_id = {row["id"]: row for row in result["row_bindings"]}
    assert rows_by_id["0"]["feature_sha256"] == rows_by_id["1"]["feature_sha256"] == rows_by_id["2"]["feature_sha256"]
    assert rows_by_id["0"]["target_sha256"] == rows_by_id["1"]["target_sha256"] != rows_by_id["2"]["target_sha256"]
    assert rows_by_id["0"]["feature_sha256"] != rows_by_id["3"]["feature_sha256"]
    assert len({rows_by_id[str(index)]["feature_sha256"] for index in (0, 5, 6, 7, 8)}) == 5
    assert result["qualified"] is False and result["projection_weights_loaded"] is False
    assert result["binder_or_scope_semantics_evaluated"] is False


def test_known_training_atoms_distinguish_targets_without_development_refit():
    train = [target(conditions=["red"]), target(conditions=["blue"])]
    codec = fit_legal_feature_codec(train)
    original = copy.deepcopy(codec)
    rows = [{"id": "red", "target": train[0]}, {"id": "blue", "target": train[1]},
            {"id": "unseen-one", "target": target(conditions=["green"])},
            {"id": "unseen-two", "target": target(conditions=["yellow"])}]
    result = subject.representation_collision_assay(rows, codec)
    assert codec == original and codec["training_target_count"] == 2
    assert result["collision_groups"] == 1 and result["distinct_target_collision_pairs"] == 1
    ids = {identity for item in result["collisions"][0]["targets"] for identity in item["row_ids"]}
    assert ids == {"unseen-one", "unseen-two"}
    assert result["unknown_atom_counts"]["conditions"] == 2


def test_categorical_unknown_collisions_are_separate_from_same_core_qualifier_collisions():
    codec = fit_legal_feature_codec([target()])
    rows = [{"id": "one", "target": target(actor="officer")},
            {"id": "two", "target": target(actor="custodian")}]
    result = subject.representation_collision_assay(rows, codec)
    assert result["distinct_target_collision_pairs"] == 1
    assert result["same_core_distinct_target_collision_pairs"] == 0
    assert result["collisions"][0]["differing_facets"] == ["actor"]
    assert result["unknown_atom_counts"]["actor"] == 2


@pytest.mark.parametrize("rows", [[], [{"id": "same", "target": target()}, {"id": "same", "target": target()}],
                                  [{"id": "many", "target": {"rules": [target()["rules"][0], target()["rules"][0]]}}]])
def test_assay_rejects_empty_duplicate_or_out_of_codec_scope(rows):
    with pytest.raises(ValueError):
        subject.representation_collision_assay(rows, fit_legal_feature_codec([target()]))


def test_existing_output_or_foreign_tree_fail_before_input_access(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="executing"):
        subject.run_richer_experiment(missing, tmp_path, tmp_path, tmp_path / "fresh")
    with pytest.raises(ValueError, match="fresh output"):
        subject.run_richer_experiment(missing, ROOT, tmp_path, tmp_path)


def test_preloaded_evaluator_must_match_the_recorded_source_tree(tmp_path, monkeypatch):
    relative = "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_evaluation.py"
    monkeypatch.setitem(sys.modules, relative[:-3].replace("/", "."),
                        SimpleNamespace(__file__=str(tmp_path / "foreign.py")))
    with pytest.raises(ValueError, match="another tree"):
        subject._verify_origins(ROOT, [{"path": relative}])


@pytest.fixture
def configured_study(tmp_path):
    base = json.loads((ROOT / "configs/autoencoders/alignment_study_development_v1.json").read_text())
    (tmp_path / "protocol.md").write_text("protected fixture protocol")
    (tmp_path / "provenance.json").write_text("{}")
    base["protected_protocols"] = [binding(tmp_path / "protocol.md", tmp_path)]
    base["corpus"]["provenance"] = [binding(tmp_path / "provenance.json", tmp_path)]
    source = "The clerk must retain the certificate."
    vector = [1.] + [0.] * 383
    row = {"id": "original-train", "group_id": "original-train", "split": "train", "source_text": source,
           "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
           "embedding": vector, "embedding_sha256": digest(vector), "target": target()}
    (tmp_path / "train.json").write_text(json.dumps({"rows": [row]}))
    base["corpus"]["train"] = binding(tmp_path / "train.json", tmp_path)
    # The configured original validation split deliberately does not exist.
    # Its declared identity is valid; opening it would make the test fail.
    base["corpus"]["development"] = {"path": "validation.json", "sha256": "b" * 64}
    base_path = tmp_path / "study.json"
    base_path.write_text(json.dumps(base))
    config = configuration()
    config["study_config"] = binding(base_path, tmp_path)
    config_path = tmp_path / "richer.json"
    config_path.write_text(json.dumps(config))
    return config_path, tmp_path


def test_panel_construction_boundary_passes_only_source_and_declared_context(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_evaluation as evaluation,
    )
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_panel as panel_owner,
    )

    panel = panel_owner.build_alignment_richer_panel()
    vocabulary = panel_owner.richer_training_vocabulary(panel)
    captured = []

    def construct(source_text, frozen_vocabulary, *, request_id, context_premises, requires_context_resolution):
        assert frozen_vocabulary is vocabulary
        captured.append({"source": source_text, "id": request_id, "premises": context_premises,
                         "needs_context": requires_context_resolution})
        return {"source_only_boundary_observed": True}

    monkeypatch.setattr(evaluation, "construct_source", construct)
    result = subject.construct_panel_sources(panel, vocabulary, float("inf"))
    assert len(result) == len(captured) == 34
    for row, call, observed in zip(panel["rows"], captured, result, strict=True):
        assert call["source"] == row["source_text"] and call["id"] == row["id"]
        assert observed["input_sha256"] == row["input_sha256"]
        assert call["needs_context"] is (row["context"]["role"] == "explicit_assumptions")
        if call["needs_context"]:
            assert call["premises"] == ({"id": row["id"] + ":context", "text": row["context"]["text"]},)
        else:
            assert call["premises"] == ()
    # The public construction boundary has no argument for query references.
    with pytest.raises(TypeError):
        subject.construct_panel_sources(panel, vocabulary, float("inf"), authored_targets=[target()])


def read_artifact(report, name):
    record = report[name]
    path = Path(record["path"])
    raw = path.read_bytes()
    assert record["sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["bytes"] == len(raw)
    return json.loads(raw)


def test_real_richer_run_keeps_failures_and_context_unavailable_with_bound_evidence(configured_study):
    config_path, workspace = configured_study
    output = workspace / "real-run"
    report = subject.run_richer_experiment(config_path, ROOT, workspace, output)
    assert report["status"] == "completed" and report["original_training_rows"] == 1
    assert report["qualified"] is False and report["production_admitted"] is False
    assert report["primary_fidelity"]["value"] is None
    assert report["native_useful_proof_coverage"] == {"status": "unrun", "value": None}
    assert report["sealed_final_test_accessed"] is False and report["original_validation_accessed"] is False
    assert report["query_targets_used_in_construction"] is False and report["development_used_in_fit"] is False
    assert report["complete_dependency_manifest"] is False
    assert all(report["resource_scope"][name] == 0 for name in
               ("model_loads", "provider_calls", "prover_calls", "optimizer_steps", "model_embeddings_computed"))
    assert report["report_sha256"] == digest({key: value for key, value in report.items() if key != "report_sha256"})
    assert json.loads((output / "report.json").read_bytes()) == report
    panel = read_artifact(report, "panel_binding")
    rows = read_artifact(report, "construction_binding")["rows"]
    assays = read_artifact(report, "representation_assay_binding")
    assert len(rows) == len(panel["rows"]) == report["summaries"]["all"]["rows"] == 34
    assert report["summaries"]["development"]["positive_rows"] == 8
    assert report["summaries"]["train"]["positive_rows"] == 16
    assert report["summaries"]["all"]["negative_rows"] == 8
    assert report["summaries"]["all"]["explicit_context_rows"] == 2
    assert report["summaries"]["all"]["explicit_context_ir_emissions"] == 0
    context_rows = [row for row in rows if row["row_kind"] == "explicit_context"]
    assert len({row["input_sha256"] for row in context_rows}) == 2
    for row in context_rows:
        construction = row["construction"]
        assert construction["construction_status"] == "unavailable" and construction["canonical_ir"] is None
        assert construction["roundtrip"]["native_result"] is None
        assert construction["input_policy"]["requires_context_resolution"] is True
    assert report["summaries"]["all"]["positive_ir_emitted"] > 0
    emitted = [row["construction"] for row in rows if row["construction"]["canonical_ir"] is not None]
    assert all(item["roundtrip"]["native_result"] is not None for item in emitted)
    assert all(item["roundtrip"]["source_fidelity_established"] is False for item in emitted)
    assert all(all(scope["status"] == "unrun" for scope in row["construction"]["proof_scopes"].values()) for row in rows)
    assert assays["original_training_codec"]["codec"]["training_target_count"] == 1
    assert assays["richer_training_codec"]["codec"]["training_target_count"] == 16
    assert "identity_verified" not in report["training_vocabulary"]["qualifiers"]
    for assay in assays.values():
        assert assay["codec"]["development_fit"] is False and assay["development_rows"]["rows"] == 8


def test_development_target_mutation_cannot_change_construction_training_vocabulary_or_codecs(configured_study, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_panel as panel_owner,
    )

    config_path, workspace = configured_study
    first = subject.run_richer_experiment(config_path, ROOT, workspace, workspace / "before-mutation")
    first_rows = read_artifact(first, "construction_binding")["rows"]
    exact = next(row for row in first_rows if row["split"] == "validation" and row["row_kind"] == "positive"
                 and row["posthoc_authored_score"]["exact_ir"])
    original_builder = panel_owner.build_alignment_richer_panel

    def changed_reference():
        panel = original_builder()
        row = next(row for row in panel["rows"] if row["id"] == exact["id"])
        modality = row["target"]["rules"][0]["modality"]
        row["target"]["rules"][0]["modality"] = "P" if modality != "P" else "F"
        row["target_sha256"] = digest(row["target"])
        panel["integrity"] = panel_owner._integrity(panel)
        panel_owner.validate_alignment_richer_panel(panel)
        return panel

    monkeypatch.setattr(panel_owner, "build_alignment_richer_panel", changed_reference)
    second = subject.run_richer_experiment(config_path, ROOT, workspace, workspace / "after-mutation")
    second_rows = read_artifact(second, "construction_binding")["rows"]
    assert first["training_vocabulary"] == second["training_vocabulary"]
    assert first["training_vocabulary_sha256"] == second["training_vocabulary_sha256"]
    first_assays, second_assays = (read_artifact(report, "representation_assay_binding") for report in (first, second))
    for name in first_assays:
        assert first_assays[name]["codec"] == second_assays[name]["codec"]
        assert first_assays[name]["training_rows"] == second_assays[name]["training_rows"]
    for before, after in zip(first_rows, second_rows, strict=True):
        assert before["id"] == after["id"] and before["input_sha256"] == after["input_sha256"]
        assert before["construction"] == after["construction"]
    changed = next(row for row in second_rows if row["id"] == exact["id"])
    assert changed["posthoc_authored_score"]["exact_ir"] is False
    assert first["summaries"]["development"]["positive_exact_authored_ir"] == (
        second["summaries"]["development"]["positive_exact_authored_ir"] + 1)


def test_deadline_before_construction_cannot_publish_completed_evidence(configured_study, monkeypatch):
    config_path, workspace = configured_study
    clock_values = iter([0., 1000.])
    monkeypatch.setattr(subject, "time", SimpleNamespace(perf_counter=lambda: next(clock_values, 1000.)))
    calls = []

    def forbid_construction(*args, **kwargs):
        calls.append(True)
        raise AssertionError("expired experiment cannot construct a row")

    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_evaluation as evaluation,
    )

    monkeypatch.setattr(evaluation, "construct_source", forbid_construction)
    output = workspace / "expired"
    with pytest.raises(ValueError, match="deadline"):
        subject.run_richer_experiment(config_path, ROOT, workspace, output)
    assert calls == [] and not output.exists()


def test_protocol_change_during_construction_prevents_publication(configured_study, monkeypatch):
    config_path, workspace = configured_study
    construct = subject.construct_panel_sources

    def construct_then_drift(*args, **kwargs):
        value = construct(*args, **kwargs)
        (workspace / "protocol.md").write_text("changed protected fixture protocol")
        return value

    monkeypatch.setattr(subject, "construct_panel_sources", construct_then_drift)
    output = workspace / "protocol-drift"
    with pytest.raises(ValueError, match="input digest mismatch"):
        subject.run_richer_experiment(config_path, ROOT, workspace, output)
    assert not output.exists()
