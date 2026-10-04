"""Admission tests for study identity and unavailable evidence boundaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_study import (
    MANIFEST_SCHEMA,
    AlignmentStudyError,
    load_alignment_config,
    validate_alignment_config,
    write_alignment_manifest,
)

CONFIG = Path(__file__).resolve().parents[5] / "configs/autoencoders/alignment_study_development_v1.json"
REPOSITORY = CONFIG.parents[2]


def configuration():
    return json.loads(CONFIG.read_text())


def test_admitted_config_does_not_claim_independent_fidelity_or_encoder_authentication():
    admitted = validate_alignment_config(configuration())
    assert admitted["corpus"]["independent_source_review_available"] is False
    assert admitted["corpus"]["encoder_execution_authenticated"] is False
    assert admitted["resource_policy"]["optimizer_steps"] == 0
    assert admitted["retrieval"]["kind"] == "source_to_source_demonstrations"


@pytest.mark.parametrize("role", ["test", "final", "sealed", "independent_validation"])
def test_sealed_roles_cannot_be_admitted_by_relabeling_config(role):
    config = configuration()
    config["corpus"]["evaluation_role"] = role
    with pytest.raises(AlignmentStudyError, match="sealed or final-test"):
        validate_alignment_config(config)


@pytest.mark.parametrize("field", ["encoder_execution_authenticated", "independent_source_review_available"])
def test_configuration_cannot_upgrade_target_or_encoder_authority(field):
    config = configuration()
    config["corpus"][field] = True
    with pytest.raises(AlignmentStudyError, match="authentication"):
        validate_alignment_config(config)


def test_cross_modal_claim_cannot_be_assigned_to_cached_source_only_vectors():
    config = configuration()
    config["retrieval"]["kind"] = "source_to_formal"
    with pytest.raises(AlignmentStudyError, match="formal embeddings"):
        validate_alignment_config(config)


@pytest.mark.parametrize("field", ["model_loads", "provider_calls", "prover_calls", "optimizer_steps"])
def test_offline_preparation_rejects_compute_scope_changes(field):
    config = configuration()
    config["resource_policy"][field] = 1
    with pytest.raises(AlignmentStudyError, match="no model/prover/training"):
        validate_alignment_config(config)


def test_boolean_row_budget_is_not_an_integer_budget():
    config = configuration()
    config["corpus"]["max_rows"] = True
    with pytest.raises(AlignmentStudyError, match="max_rows"):
        validate_alignment_config(config)


def test_duplicate_arms_are_rejected():
    config = configuration()
    config["arms"].append(config["arms"][0])
    with pytest.raises(AlignmentStudyError, match="unique"):
        validate_alignment_config(config)


def test_raw_config_digest_is_bound_before_execution(tmp_path):
    path = tmp_path / "config.json"
    raw = json.dumps(configuration()).encode()
    path.write_bytes(raw)
    config, binding = load_alignment_config(path, expected_sha256=hashlib.sha256(raw).hexdigest())
    assert binding["digest_verified"] and config["schema"] == "alignment-study-config/v1"
    with pytest.raises(AlignmentStudyError, match="digest mismatch"):
        load_alignment_config(path, expected_sha256="0" * 64)


def test_duplicate_json_keys_and_nonfinite_constants_fail_closed(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(AlignmentStudyError, match="duplicate JSON"):
        load_alignment_config(path)
    path.write_text('{"value":NaN}')
    with pytest.raises(AlignmentStudyError, match="nonfinite"):
        load_alignment_config(path)


def test_config_symlink_is_rejected(tmp_path):
    path = tmp_path / "linked.json"
    path.symlink_to(CONFIG)
    with pytest.raises(AlignmentStudyError, match="regular bounded file"):
        load_alignment_config(path)


def test_manifest_publication_binds_content_and_preserves_previous_evidence(tmp_path):
    payload = {"schema": MANIFEST_SCHEMA, "qualified": False, "measured": None}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode()
    manifest = {**payload, "manifest_sha256": hashlib.sha256(canonical).hexdigest()}
    output = tmp_path / "run"
    path = write_alignment_manifest(output, manifest)
    assert json.loads(path.read_text()) == manifest
    with pytest.raises(AlignmentStudyError, match="overwrite"):
        write_alignment_manifest(output, manifest)
    manifest["qualified"] = True
    with pytest.raises(AlignmentStudyError, match="digest mismatch"):
        write_alignment_manifest(tmp_path / "changed", manifest)


def test_unknown_fields_cannot_silently_change_experiment_inputs():
    config = configuration()
    config["final_test"] = "secret.json"
    with pytest.raises(AlignmentStudyError, match="unexpected"):
        validate_alignment_config(config)


def test_protocol_binding_failure_prevents_inventory_execution(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_inventory
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_study import (
        prepare_alignment_study,
    )

    config = configuration()
    protocol = tmp_path / "protocol.md"
    protocol.write_text("unchanged protected protocol")
    config["protected_protocols"] = [{"path": "protocol.md", "sha256": "0" * 64}]
    spec = tmp_path / "config.json"
    spec.write_text(json.dumps(config))
    called = []
    monkeypatch.setattr(alignment_inventory, "describe_alignment_assets", lambda *a: called.append(a))
    with pytest.raises(AlignmentStudyError, match="input digest mismatch"):
        prepare_alignment_study(spec, REPOSITORY, tmp_path)
    assert not called
    assert protocol.read_text() == "unchanged protected protocol"


@pytest.mark.parametrize("relative", ["../outside.md", "/absolute.md", "link/protocol.md"])
def test_bound_inputs_cannot_escape_declared_workspace(tmp_path, relative):
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_study import (
        prepare_alignment_study,
    )

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "protocol.md").write_text("protected")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    config = configuration()
    config["protected_protocols"] = [{"path": relative, "sha256": "0" * 64}]
    spec = workspace / "config.json"
    spec.write_text(json.dumps(config))
    with pytest.raises(AlignmentStudyError, match="inside the workspace|symlink input"):
        prepare_alignment_study(spec, REPOSITORY, workspace)


def test_concurrent_source_change_prevents_manifest_seal(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_baseline,
        alignment_capabilities,
        alignment_inventory,
        alignment_study,
    )

    repository = tmp_path / "repo"
    repository.mkdir()
    source = repository / "source.py"
    source.write_text("original source bytes")
    protocol = tmp_path / "protocol.md"
    protocol.write_text("protected")
    evidence = tmp_path / "provenance.json"
    evidence.write_text("{}")
    config = configuration()
    config["protected_protocols"] = [{"path": "protocol.md", "sha256": hashlib.sha256(protocol.read_bytes()).hexdigest()}]
    config["corpus"]["provenance"] = [{"path": "provenance.json", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]
    spec = tmp_path / "config.json"
    spec.write_text(json.dumps(config))
    monkeypatch.setattr(alignment_study, "_executing_repository_root", lambda: repository)
    monkeypatch.setattr(alignment_study, "_SOURCE_FILES", ("source.py",))
    monkeypatch.setattr(alignment_inventory, "describe_alignment_assets", lambda *a: {})
    monkeypatch.setattr(alignment_capabilities, "describe_alignment_capabilities", lambda *a: {})

    def baseline(*args):
        source.write_text("changed during execution")
        return {"status": "completed"}

    monkeypatch.setattr(alignment_baseline, "run_alignment_baseline", baseline)
    with pytest.raises(AlignmentStudyError, match="source changed during execution"):
        alignment_study.prepare_alignment_study(spec, repository, tmp_path, baseline=True)
    assert protocol.read_text() == "protected"


def test_repository_identity_failure_prevents_inventory_and_input_reads(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_inventory,
        alignment_study,
    )

    monkeypatch.setattr(alignment_inventory, "describe_alignment_assets",
                        lambda *a: pytest.fail("inventory must not execute"))
    with pytest.raises(AlignmentStudyError, match="executing study package"):
        alignment_study.prepare_alignment_study(tmp_path / "missing.json", tmp_path, tmp_path)


def test_loaded_dependency_origin_must_match_bound_repository(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_study

    name = "ipfs_datasets_py.logic.legal_ir.canonical_compiler"
    monkeypatch.setitem(alignment_study.sys.modules, name,
                        SimpleNamespace(__file__=str(tmp_path / "canonical_compiler.py")))
    with pytest.raises(AlignmentStudyError, match="another tree"):
        alignment_study._verify_loaded_source_origins(REPOSITORY)
