"""Immutable four-domain parents and native, explicitly scoped projections."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import profiles as api
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384
from tests.fixtures.logic.source_reconstruction_v3 import rows


DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")


def sample(domain):
    return deepcopy(rows(domain, "train")[0])


def projection(domain, *, families=None, target=None, source=None):
    row = sample(domain)
    return api.project_candidate(domain, row["target"] if target is None else target,
        row["source_text"] if source is None else source, families)


def inventory(report):
    return {row["family_id"]: row for row in report["families"]}


@pytest.mark.parametrize("domain,count", [("intent_ir", 15), ("security_ir", 9), ("ui_ux_ir", 8), ("legal_ir", 6)])
def test_profile_pins_match_published_evidence_and_native_catalog(domain, count):
    profile = api.get_profile(domain)
    root = Path(__file__).resolve().parents[5]
    descriptors = json.loads((root / "docs/implementation/reports/evidence/structured-ir-release-20261001/verified-descriptors.json").read_text())
    expected = next(p for p in descriptors if p["domain_id"] == domain and p["profile"] == "structured_native_v3")
    assert profile["checkpoint_descriptor"] == expected
    assert len(profile["family_inventory"]) == 40
    assert len(profile["native_family_ids"]) == count
    assert profile["default_required_families"] == profile["native_family_ids"]
    assert not profile["parent_training_data"]["real_world_corpus"]
    assert profile["parent_training_data"]["role"] == "authored_control"
    assert all(source["typed_export_required"] for source in profile["candidate_training_sources"])
    assert all(source["role"] != "training_completed" for source in profile["candidate_training_sources"])
    assert not profile["proof_authority"]


def test_profile_is_independent_of_caller_mutation():
    profile = api.get_profile("intent_ir")
    profile["checkpoint_descriptor"]["revision"] = "changed"
    profile["native_family_ids"].clear()
    profile["candidate_training_sources"][0]["repository_id"] = "changed"
    again = api.get_profile("intent_ir")
    assert again["checkpoint_descriptor"]["revision"] != "changed"
    assert len(again["native_family_ids"]) == 15
    assert again["candidate_training_sources"][0]["repository_id"] == "Publicus/skillcenter-ir"


@pytest.mark.parametrize("domain", DOMAINS)
def test_all_native_routes_are_not_faked_for_small_scalar_targets(domain):
    report = projection(domain)
    assert report["candidate_valid"]
    assert any(row["status"] == "supported" for row in report["families"])
    assert any(row["status"] == "missing_context" for row in report["families"])
    assert not report["all_required_families_supported"]
    assert not any(report[key] for key in ("proof_authority", "source_semantics_verified",
        "execution_authority", "lake_build_executed", "target_rewritten"))
    assert report["continue_training_if_target_valid"]
    assert report["report_sha256"] == api.digest({k: v for k, v in report.items() if k != "report_sha256"})


@pytest.mark.parametrize("domain,families", [
    ("intent_ir", ["deontic", "dcec", "tdfol", "frame_logic"]),
    ("security_ir", ["program"]), ("ui_ux_ir", ["frame_logic"]), ("legal_ir", ["deontic"]),
])
def test_explicit_subset_runs_actual_native_projections(domain, families):
    row = sample(domain)
    original = deepcopy(row["target"])
    report = api.project_candidate(domain, row["target"], row["source_text"], families)
    assert report["all_required_families_supported"]
    assert row["target"] == original
    assert all(item["projections"] for item in report["families"])
    assert report["qualification_scope"] == "typed_projection_only"


def test_security_predicted_operator_must_match_real_source():
    row = sample("security_ir")
    row["target"]["document"]["operator"] = ">"
    report = projection("security_ir", target=row["target"], families=["program"])
    assert report["candidate_valid"]
    assert inventory(report)["program"]["status"] == "failed"
    assert report["source_qualification"]["status"] == "mismatch"
    assert not report["all_required_families_supported"]


def test_security_program_contains_exact_source_and_completed_effect_evidence():
    report = projection("security_ir", families=["program"])
    native = inventory(report)["program"]["projections"][0]
    assert native["native_document"]["sources"][0]["content_sha256"] == report["source_sha256"]
    assert native["bridge"]["status"] == "ok"
    assert native["bridge"]["preservation"] == "exact"
    assert not native["bridge"]["losses"] and not native["bridge"]["unsupported"]
    assert report["source_qualification"]["source_binding"]["effect_summary_refinements"]
    assert not report["source_qualification"]["whole_program_semantics_verified"]


def test_security_unannotated_input_cannot_supply_missing_type_context():
    row = sample("security_ir")
    source = row["source_text"].replace(": int", "")
    report = projection("security_ir", source=source, families=["program"])
    assert inventory(report)["program"]["status"] == "missing_context"
    assert not report["all_required_families_supported"]


def test_intent_different_predicted_action_fails_exact_source_agreement():
    row = sample("intent_ir")
    row["target"]["document"]["action"] = "erase"
    report = projection("intent_ir", target=row["target"], families=["deontic"])
    assert report["candidate_valid"]
    assert inventory(report)["deontic"]["status"] == "failed"


def test_unknown_intent_surface_is_context_gap_not_invalid_training_target():
    report = projection("intent_ir", source="Under this unusual policy, assemble according to plan.", families=["deontic"])
    assert report["candidate_valid"]
    assert inventory(report)["deontic"]["status"] == "missing_context"
    assert report["continue_training_if_target_valid"]


def test_partial_intent_transition_projection_does_not_satisfy_policy():
    report = projection("intent_ir", families=["transition_system"])
    assert not report["all_required_families_supported"]
    assert inventory(report)["transition_system"]["status"] == "missing_context"


def test_ui_facts_never_claim_other_facets_or_source_fidelity():
    report = projection("ui_ux_ir", families=["frame_logic", "authorization"])
    frame = inventory(report)["frame_logic"]
    assert frame["status"] == "supported"
    assert frame["projections"][0]["facts"][0]["predicate"] == "ui_component"
    assert frame["projections"][0]["unsupported"]
    assert "privacy_policy" in frame["unprojected_facets"]
    assert not frame["complete_target_semantics"]
    assert inventory(report)["authorization"]["status"] == "missing_context"
    assert report["source_qualification"]["source_fidelity_check_required"]


def test_invalid_ui_semantic_vocabulary_is_rejected_before_training():
    row = sample("ui_ux_ir")
    row["target"]["document"]["privacy_sensitivity"] = "invented-value"
    report = projection("ui_ux_ir", target=row["target"], families=["frame_logic"])
    assert not report["candidate_valid"]
    assert inventory(report)["frame_logic"]["status"] == "failed"


@pytest.mark.parametrize("domain", DOMAINS)
def test_invalid_target_never_satisfies_a_projection(domain):
    report = projection(domain, target={"forged": True})
    assert not report["candidate_valid"]
    assert all(item["status"] == "failed" for item in report["families"])


def test_known_family_without_domain_adapter_remains_missing():
    report = projection("legal_ir", families=["cryptographic_protocol"])
    assert inventory(report)["cryptographic_protocol"]["status"] == "missing_context"
    assert not report["all_required_families_supported"]


@pytest.mark.parametrize("families", [[], ["Lean4"], ["deontic", "deontic"], "deontic"])
def test_rejects_invalid_or_empty_required_family_policy(families):
    with pytest.raises(ValueError, match="family selection"):
        projection("legal_ir", families=families)


def fake_download(monkeypatch, tmp_path):
    hub = pytest.importorskip("huggingface_hub")
    checkpoint, manifest = b'{"test":"checkpoint"}', b'{"test":"manifest"}'
    original = api.get_profile
    def test_profile(domain):
        result = original(domain)
        result["checkpoint_descriptor"]["checkpoint_sha256"] = hashlib.sha256(checkpoint).hexdigest()
        result["checkpoint_descriptor"]["manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
        return result
    monkeypatch.setattr(api, "get_profile", test_profile)
    downloads, loads = [], []
    def download(**kwargs):
        downloads.append(kwargs)
        name = Path(kwargs["filename"]).name
        blob = tmp_path / (name + ".blob")
        blob.write_bytes(checkpoint if name == "checkpoint.json" else manifest)
        link = tmp_path / name
        if not link.is_symlink():
            link.symlink_to(blob)
        return str(link)
    monkeypatch.setattr(hub, "hf_hub_download", download)
    monkeypatch.setattr(structured_source_384, "load_checkpoint",
        lambda path, **kwargs: loads.append((Path(path), kwargs)))
    return checkpoint, downloads, loads


def test_hub_loader_copies_symlink_and_preserves_immutable_offline_pins(monkeypatch, tmp_path):
    checkpoint, downloads, loads = fake_download(monkeypatch, tmp_path)
    result = api.load_parent("intent_ir", cache_dir=tmp_path / "cache", local_files_only=True)
    assert result.is_file() and not result.is_symlink()
    assert result.read_bytes() == checkpoint
    assert [Path(call["filename"]).name for call in downloads] == ["manifest.json", "checkpoint.json"]
    assert all(call["local_files_only"] and call["repo_type"] == "model" for call in downloads)
    assert all(call["revision"] == "809155ad4d34d67fadca2bef68ee74079bcc3074" for call in downloads)
    assert loads == [(result, {"expected_sha256": hashlib.sha256(checkpoint).hexdigest(), "expected_domain": "intent_ir"})]
    assert api.load_parent("intent_ir", cache_dir=tmp_path / "cache", local_files_only=True) == result


def test_local_parent_avoids_hub_and_still_invokes_strict_runtime(monkeypatch, tmp_path):
    checkpoint, downloads, loads = fake_download(monkeypatch, tmp_path)
    path = tmp_path / "parent.json"
    path.write_bytes(checkpoint)
    assert api.load_parent("security_ir", local_path=path) == path
    assert not downloads
    assert loads[0][1]["expected_domain"] == "security_ir"


def test_local_parent_hash_or_symlink_is_rejected(monkeypatch, tmp_path):
    checkpoint, downloads, loads = fake_download(monkeypatch, tmp_path)
    path = tmp_path / "bad.json"
    path.write_bytes(checkpoint + b" ")
    with pytest.raises(ValueError, match="SHA256"):
        api.load_parent("security_ir", local_path=path)
    path.write_bytes(checkpoint)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular checkpoint"):
        api.load_parent("security_ir", local_path=link)
    assert not downloads and not loads


def test_hub_artifact_tampering_rejected_before_runtime(monkeypatch, tmp_path):
    _, _, loads = fake_download(monkeypatch, tmp_path)
    original = api.get_profile
    def tampered(domain):
        profile = original(domain)
        profile["checkpoint_descriptor"]["manifest_sha256"] = "0" * 64
        return profile
    monkeypatch.setattr(api, "get_profile", tampered)
    with pytest.raises(ValueError, match="SHA256"):
        api.load_parent("intent_ir", cache_dir=tmp_path / "cache")
    assert not loads


def test_loader_propagates_strict_implementation_pin_failure(monkeypatch, tmp_path):
    checkpoint, _, _ = fake_download(monkeypatch, tmp_path)
    path = tmp_path / "parent.json"
    path.write_bytes(checkpoint)
    def strict(*args, **kwargs):
        raise ValueError("runtime implementation differs")
    monkeypatch.setattr(structured_source_384, "load_checkpoint", strict)
    with pytest.raises(ValueError, match="implementation differs"):
        api.load_parent("intent_ir", local_path=path)
