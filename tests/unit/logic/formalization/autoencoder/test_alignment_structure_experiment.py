"""Pinned declaration diagnostics, no new source construction, and blind review."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_parser_experiment as parser_owner,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_structure_experiment as subject,
)
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_experiment import (
    run_richer_experiment,
)
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_review import (
    validate_richer_review_bundle,
)
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_structure import (
    restore_structural_ir,
)

ROOT = Path(__file__).resolve().parents[5]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def binding(path, workspace):
    return {"path": str(path.relative_to(workspace)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def configuration():
    return {"schema": "alignment-structure-experiment-config/v1",
            "study_id": "autoformalization-structure-development-v1",
            "parser_report": {"path": "parser/report.json", "sha256": "a" * 64}, "max_seconds": 120}


@pytest.mark.parametrize("field,value", [
    ("schema", "wrong"), ("study_id", "sealed-final-study"),
    ("max_seconds", True), ("max_seconds", 0), ("max_seconds", 121),
    ("max_seconds", float("nan")), ("max_seconds", float("inf")), ("max_seconds", 10**400),
    ("parser_report", {"path": "parser/report.json", "sha256": "A" * 64}),
    ("parser_report", {"path": "", "sha256": "a" * 64}),
    ("parser_report", {"path": "parser/report.json", "sha256": "a" * 64, "unbound": True}),
])
def test_closed_config_rejects_wrong_scope_or_bounds(tmp_path, field, value):
    settings = configuration()
    settings[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        subject.load_structure_config(path)


def test_config_binds_exact_parsed_bytes_and_rejects_new_keys(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    original = (json.dumps(configuration(), indent=3) + "\n").encode()
    path.write_bytes(original)
    read = subject._bounded_bytes

    def capture_then_change(supplied, limit):
        raw = read(supplied, limit)
        path.write_text(json.dumps({**configuration(), "max_seconds": 60}))
        return raw

    monkeypatch.setattr(subject, "_bounded_bytes", capture_then_change)
    settings, observed = subject.load_structure_config(path)
    assert settings == configuration() and observed["sha256"] == hashlib.sha256(original).hexdigest()
    assert observed["bytes"] == len(original)
    monkeypatch.setattr(subject, "_bounded_bytes", read)
    path.write_text(json.dumps({**configuration(), "reference_conditioned_generation": True}))
    with pytest.raises(ValueError, match="closed"):
        subject.load_structure_config(path)


def test_duplicate_config_fields_are_rejected(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(configuration())[:-1] + ',"max_seconds":1}')
    with pytest.raises(ValueError):
        subject.load_structure_config(path)


@pytest.fixture
def predecessor(tmp_path):
    """Build only synthetic public fixtures; original validation never exists."""
    base = json.loads((ROOT / "configs/autoencoders/alignment_study_development_v1.json").read_text())
    (tmp_path / "protocol.md").write_text("protected structure fixture protocol")
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
    run_richer_experiment(tmp_path / "richer.json", ROOT, tmp_path, tmp_path / "richer")
    parser = {"schema": "alignment-parser-experiment-config/v1", "study_id": "autoformalization-parser-development-v1",
              "richer_report": binding(tmp_path / "richer/report.json", tmp_path), "max_seconds": 120}
    (tmp_path / "parser.json").write_text(json.dumps(parser))
    prior = parser_owner.run_parser_experiment(tmp_path / "parser.json", ROOT, tmp_path, tmp_path / "parser")
    settings = configuration()
    settings["parser_report"] = binding(tmp_path / "parser/report.json", tmp_path)
    config = tmp_path / "structure.json"
    config.write_text(json.dumps(settings))
    return tmp_path, config, prior


def read_artifact(record):
    path = Path(record["path"])
    raw = path.read_bytes()
    assert record["sha256"] == hashlib.sha256(raw).hexdigest()
    if "bytes" in record:
        assert record["bytes"] == len(raw)
    return json.loads(raw)


def forbid_generation(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_evaluation as richer_evaluation,
    )
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_experiment as richer_runner,
    )
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    from ipfs_datasets_py.logic.legal_ir.canonical_explicit_qualifiers import (
        ExplicitQualifierCanonicalCompiler,
    )

    def fail(*args, **kwargs):
        raise AssertionError("structural replay must not construct source candidates or run a compiler")

    monkeypatch.setattr(parser_owner, "construct_explicit_source", fail)
    monkeypatch.setattr(richer_evaluation, "construct_source", fail)
    monkeypatch.setattr(richer_runner, "construct_panel_sources", fail)
    monkeypatch.setattr(TypedDeonticCanonicalCompiler, "compile", fail)
    monkeypatch.setattr(ExplicitQualifierCanonicalCompiler, "compile", fail)


def test_receipt_only_run_restores_all_declared_structures_and_prepares_blank34_review(predecessor, monkeypatch):
    workspace, config, prior = predecessor
    before = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    forbid_generation(monkeypatch)
    output = workspace / "structure-run"
    report = subject.run_structure_experiment(config, ROOT, workspace, output)
    assert report["status"] == "completed" and report["parser_receipts_validated"] == 34
    assert report["parser_summaries"] == prior["summaries"]
    assert not (workspace / "validation.json").exists()
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert report["report_sha256"] == digest({key: value for key, value in report.items() if key != "report_sha256"})
    assert json.loads((output / "report.json").read_bytes()) == report
    assert report["qualified"] is False and report["production_admitted"] is False
    assert report["complete_dependency_manifest"] is False
    assert report["source_encoder_lanes_exercised"] is False and report["leanstral_hidden_states_extracted"] is False
    assert report["original_validation_accessed"] is False and report["sealed_final_test_accessed"] is False
    assert report["model_training_executed"] is False and report["query_generation_executed"] is False
    assert report["vocabulary_fit"] is False and report["query_targets_used_in_construction"] is False
    assert report["primary_fidelity"]["value"] is None and report["native_useful_proof_coverage"]["status"] == "unrun"
    assert all(report["resource_scope"][name] == 0 for name in ("model_loads", "provider_calls", "prover_calls", "optimizer_steps"))
    assays = read_artifact(report["representation_assay_binding"])
    for name, count in (("authored_positive_references", 24), ("emitted_candidates", 22), ("structural_challenges", 6)):
        assay = assays[name]
        assert assay["rows"] == assay["exact_owner_restorations"] == count
        assert assay["exact_named_counts"]["collision_groups"] == 0
        assert assay["exact_named_counts"]["distinct_target_collision_pairs"] == 0
        assert assay["vocabulary_fit"] is False and assay["source_semantics_verified"] is False
        assert assay["qualified"] is False and assay["proof_authority"] is False
        assert set(assay["hashed_count_variants"]) == {"d2048-s0", "d2048-s1", "d4096-s0", "d4096-s1"}
        for record in assay["records"]:
            assert restore_structural_ir(record["features"]) == record["features"]["canonical_ir"]
            assert record["exact_owner_restoration"] is True
        assert report["structural_summaries"][name] == {key: value for key, value in assay.items() if key != "records"}
    pairs = {pair["pair_id"]: pair for pair in assays["challenge_pairs"]}
    assert pairs["same-core-coassociation"]["same_typed_atom_bag"] is True
    assert pairs["same-core-coassociation"]["same_core_qualifier_bag"] is True
    assert pairs["same-core-coassociation"]["same_complete_rule_bag"] is False
    assert pairs["same-core-coassociation"]["existing_ir_diagnostics"]["exact_ir"] is False
    assert pairs["actor-association"]["same_typed_atom_bag"] is True
    assert pairs["actor-association"]["same_core_qualifier_bag"] is False
    for pair in pairs.values():
        for codec in pair["legacy_codecs"].values():
            assert codec["multi_rule_pooling_invented"] is False
            if pair["pair_id"] == "unknown-identity":
                assert codec["status"] == "executed" and codec["same_vector"] is True
            else:
                assert codec["status"] == "not_applicable_single_rule_codec" and codec["same_vector"] is None
    review = read_artifact(report["review_bindings"]["full_bundle_private"])
    assert validate_richer_review_bundle(review) == report["review_preparation_validation"]
    for name in ("reviewer_payload", "reviewer_manifest", "organizer_payload", "organizer_manifest"):
        assert read_artifact(report["review_bindings"][name]) == review[name]
    assert len(review["reviewer_payload"]["items"]) == report["new_review_items_pending"] == 34
    assert all(all(value is None for value in item["annotation"].values()) for item in review["reviewer_payload"]["items"])
    assert report["completed_independent_reviews"] == 0 and report["review_admission_executed"] is False
    assert report["original_40_review_bundle_reusable"] is False
    for item in report["source_bindings"]:
        assert item["sha256"] == hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()


def rewrite_predecessor(workspace, config, prior):
    prior["report_sha256"] = digest({key: value for key, value in prior.items() if key != "report_sha256"})
    path = workspace / "parser/report.json"
    path.write_text(json.dumps(prior))
    settings = json.loads(config.read_bytes())
    settings["parser_report"] = binding(path, workspace)
    config.write_text(json.dumps(settings))


@pytest.mark.parametrize("fault", ["byte_digest", "payload_digest", "summary", "input", "reference_score", "scope", "vocabulary"])
def test_bound_predecessor_and_receipt_checks_reject_resealed_false_evidence(predecessor, monkeypatch, fault):
    workspace, config, prior = predecessor
    forbid_generation(monkeypatch)
    if fault == "byte_digest":
        (workspace / "parser/report.json").write_text("{}")
    elif fault == "payload_digest":
        prior["report_sha256"] = "0" * 64
        (workspace / "parser/report.json").write_text(json.dumps(prior))
        settings = json.loads(config.read_bytes())
        settings["parser_report"] = binding(workspace / "parser/report.json", workspace)
        config.write_text(json.dumps(settings))
    else:
        if fault == "summary":
            prior["summaries"]["all"]["positive_exact_authored_ir"] += 1
        elif fault in {"input", "reference_score"}:
            path = Path(prior["construction_binding"]["path"])
            saved = json.loads(path.read_bytes())
            if fault == "input":
                saved["rows"][0]["input_sha256"] = "0" * 64
            else:
                saved["rows"][0]["posthoc_authored_score"]["exact_ir"] = not saved["rows"][0]["posthoc_authored_score"]["exact_ir"]
            path.write_text(json.dumps(saved))
            prior["construction_binding"] = binding(path, workspace)
        elif fault == "scope":
            prior["query_targets_used_in_construction"] = True
        elif fault == "vocabulary":
            prior["training_vocabulary"]["actors"].append("development_oracle")
            prior["training_vocabulary_sha256"] = digest(prior["training_vocabulary"])
        rewrite_predecessor(workspace, config, prior)
    output = workspace / "rejected"
    with pytest.raises(ValueError):
        subject.run_structure_experiment(config, ROOT, workspace, output)
    assert not output.exists()


@pytest.mark.parametrize("fault", ["protocol", "configuration", "parser_receipts", "executing_source"])
def test_changed_bound_inputs_during_assay_prevent_publication(predecessor, monkeypatch, fault):
    workspace, config, prior = predecessor
    forbid_generation(monkeypatch)
    assay = subject.structural_collision_assay
    changed = False

    def assay_then_change(rows):
        nonlocal changed
        result = assay(rows)
        if not changed:
            changed = True
            if fault == "protocol":
                (workspace / "protocol.md").write_text("concurrent protocol mutation")
            elif fault == "configuration":
                settings = json.loads(config.read_bytes())
                settings["max_seconds"] = 60
                config.write_text(json.dumps(settings))
            elif fault == "parser_receipts":
                Path(prior["construction_binding"]["path"]).write_text("{}")
        return result

    monkeypatch.setattr(subject, "structural_collision_assay", assay_then_change)
    if fault == "executing_source":
        observed = subject._source_bindings
        calls = 0

        def changed_binding(*args):
            nonlocal calls
            calls += 1
            result = observed(*args)
            if calls > 1:
                result[-1]["sha256"] = "0" * 64
            return result

        monkeypatch.setattr(subject, "_source_bindings", changed_binding)
    output = workspace / "mutated"
    with pytest.raises(ValueError):
        subject.run_structure_experiment(config, ROOT, workspace, output)
    assert not output.exists()


def test_deadline_before_receipt_validation_prevents_assays_and_publication(predecessor, monkeypatch):
    workspace, config, _ = predecessor
    forbid_generation(monkeypatch)
    times = iter([0., 1000.])
    monkeypatch.setattr(subject, "time", SimpleNamespace(perf_counter=lambda: next(times, 1000.)))

    def forbidden_assay(*args, **kwargs):
        raise AssertionError("expired replay cannot start a structural assay")

    monkeypatch.setattr(subject, "structural_collision_assay", forbidden_assay)
    output = workspace / "expired"
    with pytest.raises(ValueError, match="deadline"):
        subject.run_structure_experiment(config, ROOT, workspace, output)
    assert not output.exists()


def test_fresh_output_and_executing_origin_boundaries_precede_input_access(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="executing"):
        subject.run_structure_experiment(missing, tmp_path, tmp_path, tmp_path / "new")
    with pytest.raises(ValueError, match="fresh output"):
        subject.run_structure_experiment(missing, ROOT, tmp_path, tmp_path)
    relative = "ipfs_datasets_py/logic/formalization/autoencoder/alignment_structure.py"
    monkeypatch.setitem(sys.modules, relative[:-3].replace("/", "."), SimpleNamespace(__file__=str(tmp_path / "foreign.py")))
    with pytest.raises(ValueError, match="another tree"):
        subject._verify_origins(ROOT, [{"path": relative}])
