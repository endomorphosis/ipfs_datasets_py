"""Lossless shared-target tests; no network, weight downloads or training."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
    LegalIRGrammarDecoder, LegalIRGrammarRejection, LegalIRGrammarValidation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import (
    RichLegalIRTarget, TargetSnapshot, TargetSnapshotConfig, TargetSnapshotError,
    build_target_snapshot, load_target_snapshot,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder, _CachedLegalIRDocument, _CachedLegalIRTrainingTarget,
    _legal_ir_target_payload,
)


@pytest.fixture(scope="module")
def sample():
    return build_us_code_sample(title="5", section="fixture", text="The agency shall not disclose records.")


@pytest.fixture
def config():
    return TargetSnapshotConfig(("deontic_norms",), False, 1, {"compiler": "a" * 64}, {"python": "fixture"})


def target_for(sample):
    doc = LegalIRDocument(
        document_id=sample.sample_id, source_text=sample.text,
        normalized_text=sample.normalized_text, source=sample.source, citation=sample.citation,
        views={"deontic.ir": LogicIRView("deontic.ir", {"rules": [{"actor": "agency", "amount": -0.0}]},
            metadata={"created_at": "2026-09-25T12:34:56.123456Z", "tuple": (1.0, 2.0)})},
        frame_logic_triples=({"subject": "agency", "relation": "forbidden", "object": "records"},),
        metadata={"last_updated": "2026-09-25T12:35:00Z", "nested": {"value": 0.12345678912345678}},
    )
    return LegalIRTrainingTarget(("deontic_norms",), doc, {"legal_ir_multiview_total_loss": 0.25},
                                {"deontic_norms": {"error": 0.125}}, {"deontic.ir": 1.0}, False)


def test_full_document_preserves_fields_timestamps_and_numeric_payload(sample, config, tmp_path):
    target = target_for(sample)
    snapshot = build_target_snapshot([sample], {sample.sample_id: target}, config=config)
    assert snapshot.to_bytes() == build_target_snapshot([sample], {sample.sample_id: target}, config=config).to_bytes()
    descriptor = snapshot.save(tmp_path / "targets.json")
    loaded = load_target_snapshot(descriptor["path"], expected_sha256=descriptor["sha256"], samples=[sample], config=config)
    restored = loaded.targets_for([sample], config=config)[sample.sample_id]
    assert type(restored) is LegalIRTrainingTarget
    assert restored == target
    assert restored.document.to_json() == target.document.to_json()
    assert restored.document.canonical_hash() == target.document.canonical_hash()
    assert loaded.snapshot_id == snapshot.snapshot_id
    assert loaded.sample_count == 1
    assert loaded.statuses == {sample.sample_id: "ready"}
    with pytest.raises(FileExistsError):
        snapshot.save(tmp_path / "targets.json")


def test_fresh_and_reopened_targets_have_exact_evaluation_outputs(sample, config, tmp_path):
    target = target_for(sample)
    snapshot = build_target_snapshot([sample], {sample.sample_id: target}, config=config)
    descriptor = snapshot.save(tmp_path / "targets.json")
    mapping = load_target_snapshot(descriptor["path"], expected_sha256=descriptor["sha256"]).targets_for([sample], config=config)
    before = AdaptiveModalAutoencoder(compute_device="python").evaluate([sample], legal_ir_targets={sample.sample_id: target}, use_sample_memory=False)
    after = AdaptiveModalAutoencoder(compute_device="python").evaluate([sample], legal_ir_targets=mapping, use_sample_memory=False)
    assert before.to_dict() == after.to_dict()
    assert after.legal_ir_target_count == 1
    assert after.legal_ir_losses["legal_ir_multiview_total_loss"] == 0.25
    assert after.legal_ir_target_hashes == {sample.sample_id: target.document.canonical_hash()}


@pytest.mark.parametrize("explicit", [False, True])
def test_rich_grammar_payload_is_not_reduced_to_cache_summary(sample, config, explicit):
    values = target_for(sample).__dict__.copy()
    candidate = {"family": "deontic", "rules": [{"modality": "invalid", "subject": "agency", "action": "disclose"}]}
    values.update(candidate_ir=candidate, family="deontic", production_scores={"keep": -0.0})
    if explicit:
        values["grammar_validation"] = LegalIRGrammarValidation(
            False, "deontic", candidate, (LegalIRGrammarRejection("fixture_error", "$.rules[0]", "deontic", "rule", "exact"),),
            ("chosen",), ("masked",),
        )
    target = RichLegalIRTarget(values)
    snapshot = build_target_snapshot([sample], {sample.sample_id: target}, config=config)
    restored = snapshot.targets_for([sample], config=config)[sample.sample_id]
    assert restored.to_dict() == target.to_dict()
    before = _legal_ir_target_payload([sample], legal_ir_targets={sample.sample_id: target})
    after = _legal_ir_target_payload([sample], legal_ir_targets={sample.sample_id: restored})
    assert before == after
    assert after["grammar_losses"]["legal_ir_grammar_accepted"] == 0.0
    assert after["grammar_rejection_reasons_by_sample"][sample.sample_id]


def test_plain_dict_and_unknown_object_targets_fail_closed(sample, config):
    for target in ({"losses": {"fake": 1.0}}, SimpleNamespace(losses={}), object()):
        with pytest.raises(TargetSnapshotError):
            build_target_snapshot([sample], {sample.sample_id: target}, config=config)
    with pytest.raises(TargetSnapshotError):
        build_target_snapshot([sample], {sample.sample_id: RichLegalIRTarget({"candidate_ir": object()})}, config=config)


def test_timeout_fallback_is_explicit_and_ordinary_summary_is_rejected(sample, config):
    target = _CachedLegalIRTrainingTarget(config.bridge_names,
        _CachedLegalIRDocument("timeout:" + "b" * 64, sample.sample_id, "timeout-v1"),
        {"legal_ir_target_timeout_loss": 1.0}, accepted=False)
    snapshot = build_target_snapshot([sample], {sample.sample_id: target}, config=config)
    assert snapshot.statuses == {sample.sample_id: "timeout"}
    restored = snapshot.targets_for([sample], config=config)[sample.sample_id]
    assert restored == target
    assert _legal_ir_target_payload([sample], legal_ir_targets={sample.sample_id: restored}) == _legal_ir_target_payload([sample], legal_ir_targets={sample.sample_id: target})
    with pytest.raises(TargetSnapshotError):
        build_target_snapshot([sample], {sample.sample_id: target}, config=config, statuses={sample.sample_id: "ready"})
    summary = replace(target, document=replace(target.document, document_hash="c" * 64), losses={})
    with pytest.raises(TargetSnapshotError, match="lossy"):
        build_target_snapshot([sample], {sample.sample_id: summary}, config=config)


def test_exact_embeddings_and_all_sample_fields_are_bound(sample, config):
    snapshot = build_target_snapshot([sample], {sample.sample_id: target_for(sample)}, config=config)
    changed = replace(sample, embedding_vector=[sample.embedding_vector[0] + 1e-12, *sample.embedding_vector[1:]])
    for row in (changed, replace(sample, parser_trace={"changed": "value"}), replace(sample, citation="different")):
        with pytest.raises(TargetSnapshotError, match="changed sample"):
            snapshot.targets_for([row], config=config)


def test_subset_of_union_and_config_changes(sample, config):
    other = replace(sample, sample_id=sample.sample_id + "-other", section="other")
    snapshot = build_target_snapshot([sample, other], {s.sample_id: target_for(s) for s in (sample, other)}, config=config)
    assert list(snapshot.targets_for([other], config=config)) == [other.sample_id]
    for modified in (
        replace(config, parallel_workers=2), replace(config, evaluate_provers=True),
        replace(config, code_sha256={"compiler": "b" * 64}), replace(config, dependency_provenance={"python": "changed"}),
        replace(config, target_timeout_seconds=16.0), replace(config, bridge_names=("other",)),
    ):
        with pytest.raises(TargetSnapshotError, match="configuration"):
            snapshot.targets_for([sample], config=modified)


def test_membership_and_failures_cannot_be_silently_skipped(sample, config):
    target = target_for(sample)
    for samples, mapping in (([sample, sample], {sample.sample_id: target}), ([sample], {}), ([sample], {sample.sample_id: target, "extra": target})):
        with pytest.raises(TargetSnapshotError):
            build_target_snapshot(samples, mapping, config=config)
    snapshot = build_target_snapshot([sample], {sample.sample_id: None}, config=config, statuses={sample.sample_id: "unavailable"})
    assert snapshot.statuses == {sample.sample_id: "unavailable"}
    with pytest.raises(TargetSnapshotError, match="no injectable"):
        snapshot.targets_for([sample], config=config)
    with pytest.raises(TargetSnapshotError):
        build_target_snapshot([sample], {sample.sample_id: replace(target, document=replace(target.document, document_id="wrong"))}, config=config)
    with pytest.raises(TargetSnapshotError, match="source text"):
        build_target_snapshot([sample], {sample.sample_id: replace(target, document=replace(target.document, source_text="Other source"))}, config=config)


def test_tamper_external_hash_record_hash_duplicate_json_and_bound(sample, config, tmp_path):
    snapshot = build_target_snapshot([sample], {sample.sample_id: target_for(sample)}, config=config)
    descriptor = snapshot.save(tmp_path / "original.json")
    with pytest.raises(TargetSnapshotError):
        load_target_snapshot(descriptor["path"], expected_sha256="0" * 64)
    with pytest.raises(TargetSnapshotError):
        load_target_snapshot(descriptor["path"], expected_sha256=descriptor["sha256"], max_bytes=10)
    data = json.loads(snapshot.to_bytes())
    data["records"][0]["target_sha256"] = "0" * 64
    for raw in (json.dumps(data).encode(), b'{"schema_version":1,"schema_version":2}', b'{"number":NaN}'):
        path = tmp_path / "bad.json"
        path.write_bytes(raw)
        with pytest.raises(TargetSnapshotError):
            load_target_snapshot(path, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_record_hash_and_unknown_codec_fail_even_if_outer_seal_is_recomputed(sample, config):
    snapshot = build_target_snapshot([sample], {sample.sample_id: target_for(sample)}, config=config)
    for mutation in ("hash", "type", "status"):
        data = json.loads(snapshot.to_bytes())
        if mutation == "hash":
            data["records"][0]["target_sha256"] = "0" * 64
        elif mutation == "type":
            data["records"][0]["target"]["type"] = "arbitrary.module.Class"
            data["records"][0]["target_sha256"] = hashlib.sha256(json.dumps(data["records"][0]["target"],
                ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        else:
            data["records"][0]["status"] = {}
        body = {k: v for k, v in data.items() if k != "snapshot_id"}
        data["snapshot_id"] = "sha256:" + hashlib.sha256(json.dumps(body, ensure_ascii=True, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        with pytest.raises(TargetSnapshotError):
            TargetSnapshot(json.dumps(data).encode())


def test_hydrated_mutation_cannot_change_snapshot(sample, config):
    snapshot = build_target_snapshot([sample], {sample.sample_id: target_for(sample)}, config=config)
    original = snapshot.to_bytes()
    target = snapshot.targets_for([sample], config=config)[sample.sample_id]
    target.losses["injected"] = 999.0
    target.document.metadata["last_updated"] = "modified"
    assert snapshot.to_bytes() == original
    restored = snapshot.targets_for([sample], config=config)[sample.sample_id]
    assert "injected" not in restored.losses
    assert restored.document.metadata["last_updated"] != "modified"


def test_cross_process_reload_preserves_document_and_losses(sample, config, tmp_path):
    snapshot = build_target_snapshot([sample], {sample.sample_id: target_for(sample)}, config=config)
    descriptor = snapshot.save(tmp_path / "snapshot.json")
    package_root = Path(__file__).resolve().parents[4]
    program = '''
import sys
sys.path.insert(0, sys.argv[1])
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import load_target_snapshot
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
sample=build_us_code_sample(title="5",section="fixture",text="The agency shall not disclose records.")
snapshot=load_target_snapshot(sys.argv[2],expected_sha256=sys.argv[3],samples=[sample])
target=snapshot.targets_for([sample],config=snapshot.config)[sample.sample_id]
print(target.document.canonical_hash(),target.losses["legal_ir_multiview_total_loss"])
'''
    env = {**os.environ, "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0"}
    completed = subprocess.run([sys.executable, "-c", program, str(package_root), descriptor["path"], descriptor["sha256"]],
                               capture_output=True, text=True, env=env, timeout=30, check=True)
    assert f"{target_for(sample).document.canonical_hash()} 0.25" in completed.stdout
