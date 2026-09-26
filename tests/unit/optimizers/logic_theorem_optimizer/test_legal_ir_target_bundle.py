"""Exact target parity, lazy selection, bounded decoding and durable publication."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import zlib

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
    LegalIRGrammarRejection, LegalIRGrammarValidation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import (
    RichLegalIRTarget, TargetSnapshotConfig, TargetSnapshotError, _encode, _json,
    build_target_snapshot,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder, _CachedLegalIRDocument, _CachedLegalIRTrainingTarget,
    _legal_ir_target_payload,
)


@pytest.fixture(scope="module")
def sample():
    return build_us_code_sample(title="5", section="bundle-fixture", text="The agency shall not disclose records.")


@pytest.fixture
def config():
    return TargetSnapshotConfig(("deontic_norms",), False, 1, {"compiler": "a" * 64}, {"python": "fixture"})


def target_for(sample):
    doc = LegalIRDocument(
        document_id=sample.sample_id, source_text=sample.text, normalized_text=sample.normalized_text,
        source=sample.source, citation=sample.citation,
        views={"deontic.ir": LogicIRView("deontic.ir", {"rules": [{"actor": "agency", "amount": -0.0}]},
            metadata={"timestamp": "2026-09-25T12:34:56.123456Z", "tuple": (1.0, 2.0)})},
        frame_logic_triples=({"subject": "agency", "relation": "forbidden", "object": "records"},),
        metadata={"ordered": {"z": 0.12345678912345678, "a": [1, 2]}, "updated": "2026-09-25T12:35:00Z"},
    )
    return LegalIRTrainingTarget(("deontic_norms",), doc, {"legal_ir_multiview_total_loss": 0.25},
                                {"deontic_norms": {"error": 0.125}}, {"deontic.ir": 1.0}, False)


def write(tmp_path, sample, config, target=None, name="target.bundle"):
    return codec.write_target_bundle(tmp_path / name, [(sample, target or target_for(sample), None)], config=config)


def unpack(path):
    raw = Path(path).read_bytes()
    magic, size = codec._HEADER.unpack(raw[:codec._HEADER.size])
    assert magic == codec.MAGIC
    return json.loads(raw[codec._HEADER.size:codec._HEADER.size + size]), raw[codec._HEADER.size + size:]


def reseal(tmp_path, manifest, payload, name="resealed.bundle"):
    body = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    manifest["snapshot_id"] = "sha256:" + hashlib.sha256(_json(body)).hexdigest()
    encoded = _json(manifest)
    raw = codec._HEADER.pack(codec.MAGIC, len(encoded)) + encoded + payload
    path = tmp_path / name
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def changed_shard(tmp_path, descriptor, raw, *, compressed=None, declared_bytes=None, name="changed.bundle"):
    manifest, _ = unpack(descriptor["path"])
    compressed = zlib.compress(raw) if compressed is None else compressed
    digest = hashlib.sha256(raw).hexdigest()
    manifest["records"][0]["target_sha256"] = digest
    manifest["shards"][0].update(target_sha256=digest, compressed_bytes=len(compressed),
                                 uncompressed_bytes=len(raw) if declared_bytes is None else declared_bytes,
                                 compressed_sha256=hashlib.sha256(compressed).hexdigest())
    return reseal(tmp_path, manifest, compressed, name)


def test_exact_full_target_payload_and_evaluation_parity(sample, config, tmp_path):
    target = target_for(sample)
    legacy = build_target_snapshot([sample], {sample.sample_id: target}, config=config)
    descriptor = write(tmp_path, sample, config, target)
    with codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"], config=config) as bundle:
        assert bundle.sample_count == 1
        assert bundle.statuses == {sample.sample_id: "ready"}
        assert bundle.snapshot_id == descriptor["snapshot_id"]
        assert bundle.snapshot_id != legacy.snapshot_id
        assert bundle.sha256 == descriptor["sha256"]
        assert bundle.statistics["decompressed_shards"] == 0
        restored = bundle.targets_for([sample], config=config)[sample.sample_id]
        assert _json(_encode(restored)) == _json(_encode(target))
        assert restored.document.to_json() == target.document.to_json()
        assert restored.document.canonical_hash() == target.document.canonical_hash()
        model = AdaptiveModalAutoencoder(compute_device="python")
        before = model.evaluate([sample], legal_ir_targets={sample.sample_id: target}, use_sample_memory=False)
        after = model.evaluate([sample], legal_ir_targets={sample.sample_id: restored}, use_sample_memory=False)
        assert before.to_dict() == after.to_dict()
        assert after.legal_ir_target_count == 1
    assert bundle.statistics["closed"] is True
    with pytest.raises(TargetSnapshotError, match="closed"):
        bundle.targets_for([sample], config=config)


def test_rich_grammar_rejections_and_tuple_fields_are_complete(sample, config, tmp_path):
    candidate = {"family": "deontic", "rules": [{"modality": "invalid", "subject": "agency", "action": "disclose"}]}
    values = target_for(sample).__dict__.copy()
    values.update(candidate_ir=candidate, family="deontic", production_scores={"keep": -0.0},
        grammar_validation=LegalIRGrammarValidation(False, "deontic", candidate,
            (LegalIRGrammarRejection("fixture_error", "$.rules[0]", "deontic", "rule", "exact"),), ("chosen",), ("masked",)))
    target = RichLegalIRTarget(values)
    descriptor = write(tmp_path, sample, config, target)
    with codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"]) as bundle:
        restored = bundle.targets_for([sample], config=config)[sample.sample_id]
    assert _json(_encode(restored)) == _json(_encode(target))
    assert _legal_ir_target_payload([sample], legal_ir_targets={sample.sample_id: restored}) == _legal_ir_target_payload([sample], legal_ir_targets={sample.sample_id: target})


def test_snapshot_identity_and_bytes_do_not_depend_on_destination(sample, config, tmp_path):
    first = write(tmp_path, sample, config, name="one.bundle")
    second = write(tmp_path, sample, config, name="two.bundle")
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["sha256"] == second["sha256"]
    assert Path(first["path"]).read_bytes() == Path(second["path"]).read_bytes()


def test_subset_loads_only_requested_target(sample, config, tmp_path, monkeypatch):
    other = replace(sample, sample_id=sample.sample_id + "-other")
    descriptor = codec.write_target_bundle(tmp_path / "union.bundle", [(s, target_for(s), None) for s in (sample, other)], config=config)
    calls = []
    original = codec._decode
    monkeypatch.setattr(codec, "_decode", lambda value: (calls.append(value), original(value))[1])
    with codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"]) as bundle:
        assert bundle.config.to_dict() == config.to_dict()
        assert bundle.sample_count == 2
        assert len(bundle.statuses) == 2
        assert calls == []
        assert list(bundle.targets_for([other], config=config)) == [other.sample_id]
        assert len(calls) == 1
        assert bundle.statistics["decompressed_shards"] == 1
        assert bundle.statistics["unique_decompressed_shards"] == 1
        assert bundle.statistics["shard_count"] == 2
        assert bundle.statistics["artifact_format"] == "bundle"
        assert bundle.statistics["open_hash_seconds"] >= 0
        assert bundle.statistics["hydrate_validate_seconds"] >= 0


def test_duplicate_payload_uses_one_shard_but_hydration_never_aliases(sample, config, tmp_path):
    other = replace(sample, sample_id=sample.sample_id + "-other")
    target = RichLegalIRTarget({"bridge_names": config.bridge_names, "losses": {"fixture": 0.25},
                              "candidate_ir": {"nested": [1, 2]}, "accepted": False})
    descriptor = codec.write_target_bundle(tmp_path / "dedup.bundle", [(s, target, None) for s in (sample, other)], config=config)
    assert descriptor["statistics"]["deduplicated_target_count"] == 1
    with codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"]) as bundle:
        targets = bundle.targets_for([sample, other], config=config)
        targets[sample.sample_id].candidate_ir["nested"].append(3)
        assert targets[other.sample_id].candidate_ir["nested"] == [1, 2]
        assert bundle.targets_for([sample], config=config)[sample.sample_id].candidate_ir["nested"] == [1, 2]
        assert bundle.statistics["unique_decompressed_shards"] == 1


def test_full_target_compression_reduces_repeated_graph_bytes(sample, config, tmp_path):
    target = target_for(sample)
    target.document.metadata["duplicated_graph"] = [{"node": "agency", "relation": "forbidden", "text": "records"} for _ in range(5000)]
    descriptor = write(tmp_path, sample, config, target)
    stats = descriptor["statistics"]
    assert stats["compressed_target_bytes"] < stats["unique_uncompressed_target_bytes"] // 20
    with codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"]) as bundle:
        assert _json(_encode(bundle.targets_for([sample], config=config)[sample.sample_id])) == _json(_encode(target))


def test_missing_records_keep_failure_inventory_and_cannot_inject(sample, config, tmp_path):
    descriptor = codec.write_target_bundle(tmp_path / "missing.bundle", [(sample, None, "unavailable")], config=config)
    assert descriptor["statistics"]["shard_count"] == 0
    with codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"]) as bundle:
        assert bundle.statuses == {sample.sample_id: "unavailable"}
        with pytest.raises(TargetSnapshotError, match="no injectable"):
            bundle.targets_for([sample], config=config)
    for status in (None, "ready", "invented"):
        with pytest.raises(TargetSnapshotError):
            codec.write_target_bundle(tmp_path / (str(status) + ".bundle"), [(sample, None, status)], config=config)


def test_timeout_is_preserved_and_ordinary_summary_rejected(sample, config, tmp_path):
    target = _CachedLegalIRTrainingTarget(config.bridge_names,
        _CachedLegalIRDocument("timeout:" + "b" * 64, sample.sample_id, "timeout-v1"),
        {"legal_ir_target_timeout_loss": 1.0}, accepted=False)
    descriptor = write(tmp_path, sample, config, target)
    with codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"]) as bundle:
        assert bundle.statuses[sample.sample_id] == "timeout"
        assert bundle.targets_for([sample], config=config)[sample.sample_id] == target
    for invalid, status in ((target, "ready"), (replace(target, document=replace(target.document, document_hash="c" * 64), losses={}), None)):
        with pytest.raises(TargetSnapshotError):
            codec.write_target_bundle(tmp_path / "invalid.bundle", [(sample, invalid, status)], config=config)


def test_exact_sample_and_config_changes_rejected(sample, config, tmp_path):
    descriptor = write(tmp_path, sample, config)
    with codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"]) as bundle:
        for changed in (replace(sample, embedding_vector=[sample.embedding_vector[0] + 1e-12, *sample.embedding_vector[1:]]),
                        replace(sample, parser_trace={"changed": "value"}), replace(sample, citation="different")):
            with pytest.raises(TargetSnapshotError, match="changed sample"):
                bundle.targets_for([changed], config=config)
        with pytest.raises(TargetSnapshotError, match="duplicate"):
            bundle.targets_for([sample, sample], config=config)
        with pytest.raises(TargetSnapshotError, match="configuration"):
            bundle.targets_for([sample], config=replace(config, parallel_workers=2))
        detached = bundle.config
        detached.dependency_provenance["python"] = "changed"
        assert bundle.config.dependency_provenance["python"] == "fixture"
    with pytest.raises(TargetSnapshotError, match="configuration"):
        codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"], config=replace(config, target_timeout_seconds=16))


@pytest.mark.parametrize("field", ["document_id", "source_text"])
def test_writer_rejects_misbound_document(sample, config, tmp_path, field):
    target = target_for(sample)
    target = replace(target, document=replace(target.document, **{field: "wrong"}))
    with pytest.raises(TargetSnapshotError):
        write(tmp_path, sample, config, target)
    assert list(tmp_path.iterdir()) == []


def test_writer_rejects_duplicate_empty_and_unknown_object(sample, config, tmp_path):
    target = target_for(sample)
    for records in ([], [(sample, target, None), (sample, target, None)], [(sample, object(), None)]):
        with pytest.raises(TargetSnapshotError):
            codec.write_target_bundle(tmp_path / "invalid.bundle", records, config=config)
    assert list(tmp_path.iterdir()) == []


def test_producer_exhaustion_precedes_publication_and_failure_leaves_no_file(sample, config, tmp_path):
    path = tmp_path / "published.bundle"
    reached = []
    def records():
        yield sample, target_for(sample), None
        assert not path.exists()
        reached.append(True)
        raise RuntimeError("provenance changed")
    with pytest.raises(RuntimeError, match="provenance"):
        codec.write_target_bundle(path, records(), config=config)
    assert reached == [True]
    assert list(tmp_path.iterdir()) == []


def test_existing_destination_is_never_replaced_or_consumes_generator(sample, config, tmp_path):
    path = tmp_path / "existing.bundle"
    path.write_bytes(b"keep")
    def records():
        raise AssertionError("must not consume producer")
        yield
    with pytest.raises(FileExistsError):
        codec.write_target_bundle(path, records(), config=config)
    assert path.read_bytes() == b"keep"
    assert len(list(tmp_path.iterdir())) == 1


def test_exclusive_publish_race_keeps_competing_destination(sample, config, tmp_path, monkeypatch):
    link = codec.os.link
    def race(source, destination, **kwargs):
        (tmp_path / destination).write_bytes(b"competitor")
        return link(source, destination, **kwargs)
    monkeypatch.setattr(codec.os, "link", race)
    with pytest.raises(FileExistsError):
        write(tmp_path, sample, config)
    assert (tmp_path / "target.bundle").read_bytes() == b"competitor"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("bound", ["max_bytes", "max_manifest_bytes", "max_shard_bytes"])
def test_writer_size_bounds_fail_without_artifact(sample, config, tmp_path, bound):
    with pytest.raises(TargetSnapshotError, match="bound"):
        codec.write_target_bundle(tmp_path / "small.bundle", [(sample, target_for(sample), None)], config=config, **{bound: 1})
    assert list(tmp_path.iterdir()) == []


def test_config_bound_fails_before_producer_is_consumed(config, tmp_path):
    def records():
        raise AssertionError("must check config bound first")
        yield
    with pytest.raises(TargetSnapshotError, match="configuration"):
        codec.write_target_bundle(tmp_path / "small.bundle", records(), config=config, max_manifest_bytes=1)


@pytest.mark.parametrize("bound", ["max_bytes", "max_manifest_bytes", "max_shard_bytes"])
def test_loader_size_bounds(sample, config, tmp_path, bound):
    descriptor = write(tmp_path, sample, config)
    with pytest.raises(TargetSnapshotError):
        codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"], **{bound: 1})
    with pytest.raises(TargetSnapshotError):
        codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"], **{bound: True})


def test_external_sha_covers_even_unrequested_payloads(sample, config, tmp_path):
    descriptor = write(tmp_path, sample, config)
    path = Path(descriptor["path"])
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(TargetSnapshotError, match="digest"):
        codec.load_target_bundle(path, expected_sha256=descriptor["sha256"])


def test_file_mutation_after_load_is_rejected(sample, config, tmp_path):
    descriptor = write(tmp_path, sample, config)
    with codec.load_target_bundle(descriptor["path"], expected_sha256=descriptor["sha256"]) as bundle:
        with open(descriptor["path"], "r+b") as handle:
            handle.seek(-1, os.SEEK_END)
            handle.write(b"x")
        with pytest.raises(TargetSnapshotError, match="changed after"):
            bundle.targets_for([sample], config=config)


@pytest.mark.parametrize("mutation", ["duplicate_record", "duplicate_shard", "dangling", "unused", "overlap", "trailing", "schema", "status", "target_hash", "snapshot_id"])
def test_resealed_invalid_manifests_fail_closed(sample, config, tmp_path, mutation):
    descriptor = write(tmp_path, sample, config)
    manifest, payload = unpack(descriptor["path"])
    if mutation == "duplicate_record":
        manifest["records"].append(manifest["records"][0].copy())
    elif mutation == "duplicate_shard":
        manifest["shards"].append(manifest["shards"][0].copy())
    elif mutation == "dangling":
        manifest["records"][0]["target_sha256"] = "0" * 64
    elif mutation == "unused":
        manifest["records"][0].update(has_target=False, status="failed", target_sha256=codec._NULL_SHA256)
    elif mutation == "overlap":
        manifest["shards"][0]["offset"] = 1
    elif mutation == "trailing":
        payload += b"garbage"
    elif mutation == "schema":
        manifest["shards"][0]["path"] = "../../escape"
    elif mutation == "status":
        manifest["records"][0]["status"] = {}
    elif mutation == "target_hash":
        manifest["records"][0]["target_sha256"] = "invalid"
    else:
        manifest["snapshot_id"] = "sha256:" + "0" * 64
        encoded = _json(manifest)
        raw = codec._HEADER.pack(codec.MAGIC, len(encoded)) + encoded + payload
        path = tmp_path / "bad-identity.bundle"
        path.write_bytes(raw)
        with pytest.raises(TargetSnapshotError, match="identity"):
            codec.load_target_bundle(path, expected_sha256=hashlib.sha256(raw).hexdigest())
        return
    path, digest = reseal(tmp_path, manifest, payload)
    with pytest.raises(TargetSnapshotError):
        codec.load_target_bundle(path, expected_sha256=digest)


@pytest.mark.parametrize("mutation", ["compressed_digest", "expanded_digest", "declared_huge", "declared_small", "truncated", "trailing", "concatenated", "unknown_type", "duplicate_json"])
def test_independent_shard_verification_and_expansion_bounds(sample, config, tmp_path, mutation):
    descriptor = write(tmp_path, sample, config)
    manifest, payload = unpack(descriptor["path"])
    raw = _json(_encode(target_for(sample)))
    if mutation == "compressed_digest":
        manifest["shards"][0]["compressed_sha256"] = "0" * 64
        path, digest = reseal(tmp_path, manifest, payload)
    elif mutation == "expanded_digest":
        manifest["shards"][0]["target_sha256"] = manifest["records"][0]["target_sha256"] = "0" * 64
        path, digest = reseal(tmp_path, manifest, payload)
    elif mutation == "declared_huge":
        manifest["shards"][0]["uncompressed_bytes"] = codec.DEFAULT_MAX_SHARD_BYTES + 1
        path, digest = reseal(tmp_path, manifest, payload)
        with pytest.raises(TargetSnapshotError, match="bound"):
            codec.load_target_bundle(path, expected_sha256=digest)
        return
    elif mutation == "declared_small":
        path, digest = changed_shard(tmp_path, descriptor, b"x" * 100000, declared_bytes=1)
    elif mutation == "truncated":
        path, digest = changed_shard(tmp_path, descriptor, raw, compressed=zlib.compress(raw)[:-1])
    elif mutation == "trailing":
        path, digest = changed_shard(tmp_path, descriptor, raw, compressed=zlib.compress(raw) + b"trailing")
    elif mutation == "concatenated":
        path, digest = changed_shard(tmp_path, descriptor, raw, compressed=zlib.compress(raw) + zlib.compress(b"second"))
    elif mutation == "unknown_type":
        encoded = _encode(target_for(sample))
        encoded["type"] = "untrusted.Class"
        path, digest = changed_shard(tmp_path, descriptor, _json(encoded))
    else:
        path, digest = changed_shard(tmp_path, descriptor, b'{"type":"mapping","type":"mapping","items":[]}')
    with codec.load_target_bundle(path, expected_sha256=digest) as bundle:
        # Unselected shard semantics are deliberately lazy; trusted outer digest
        # and manifest validation are complete without constructing target graphs.
        assert bundle.statistics["decompressed_shards"] == 0
        with pytest.raises(TargetSnapshotError):
            bundle.targets_for([sample], config=config)


def test_duplicate_manifest_json_and_invalid_header_rejected(sample, config, tmp_path):
    descriptor = write(tmp_path, sample, config)
    for raw in (codec._HEADER.pack(codec.MAGIC, 99), b"bad", codec._HEADER.pack(codec.MAGIC, 13) + b'{"a":1,"a":2}'):
        path = tmp_path / "bad.bundle"
        path.write_bytes(raw)
        with pytest.raises(TargetSnapshotError):
            codec.load_target_bundle(path, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_safe_paths_reject_symlink_ancestors_final_symlinks_traversal_and_fifo(sample, config, tmp_path):
    descriptor = write(tmp_path, sample, config)
    alias = tmp_path / "alias.bundle"
    alias.symlink_to(descriptor["path"])
    linked_dir = tmp_path / "linked-dir"
    linked_dir.symlink_to(tmp_path, target_is_directory=True)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    paths = [alias, linked_dir / "target.bundle", tmp_path / "unused" / ".." / "target.bundle", fifo]
    for path in paths:
        with pytest.raises((OSError, TargetSnapshotError)):
            codec.load_target_artifact(path, expected_sha256=descriptor["sha256"])
    with pytest.raises((OSError, TargetSnapshotError)):
        codec.write_target_bundle(linked_dir / "new.bundle", [(sample, target_for(sample), None)], config=config)


def test_unified_loader_retains_legacy_json_and_bundle_semantics(sample, config, tmp_path):
    target = target_for(sample)
    legacy = build_target_snapshot([sample], {sample.sample_id: target}, config=config)
    legacy_descriptor = legacy.save(tmp_path / "old.json")
    bundle_descriptor = write(tmp_path, sample, config)
    loaded = codec.load_target_artifact(legacy_descriptor["path"], expected_sha256=legacy_descriptor["sha256"], samples=[sample], config=config)
    assert loaded.to_bytes() == legacy.to_bytes()
    with codec.load_target_artifact(bundle_descriptor["path"], expected_sha256=bundle_descriptor["sha256"], samples=[sample], config=config) as bundle:
        assert _json(_encode(bundle.targets_for([sample], config=config)[sample.sample_id])) == _json(_encode(target))
