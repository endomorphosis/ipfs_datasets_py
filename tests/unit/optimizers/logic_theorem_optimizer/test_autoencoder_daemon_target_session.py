"""Bounded session contracts; declared fixture provenance is not qualification."""
from dataclasses import replace
import os
from pathlib import Path
import weakref

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_target_session as sessions
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import (
    RichLegalIRTarget, TargetSnapshotConfig, TargetSnapshotError, _encode, _json,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    sample = build_us_code_sample(title="5", section="session-fixture", text="The agency shall retain records.")
    other = replace(sample, sample_id=sample.sample_id + "-other")
    third = replace(sample, sample_id=sample.sample_id + "-third")
    config = TargetSnapshotConfig(("deontic_norms",), False, 1, {"fixture": "a" * 64})
    calls = []

    def current(settings):
        calls.append(settings)
        return replace(config, bridge_names=settings.legal_ir_bridge_names,
                       evaluate_provers=settings.legal_ir_evaluate_provers,
                       parallel_workers=settings.legal_ir_parallel_workers)

    monkeypatch.setattr(sessions, "target_snapshot_config", current)

    def target(row):
        document = LegalIRDocument(
            document_id=row.sample_id, source_text=row.text, normalized_text=row.normalized_text,
            citation=row.citation, views={"rule": LogicIRView("rule", {"rules": [{"value": -0.0}]})},
            metadata={"timestamp": "2026-09-25T00:00:00Z"},
        )
        return LegalIRTrainingTarget(("deontic_norms",), document,
                                     {"legal_ir_multiview_total_loss": 0.25}, {}, {"rule": 1.0}, False)

    def write(rows=None, targets=None, bound_config=None, name="fixture.bundle"):
        rows = rows or [sample, other, third]
        data = codec.write_target_bundle(
            tmp_path / name, [(row, targets[index] if targets is not None else target(row), None)
                             for index, row in enumerate(rows)], config=bound_config or config)
        return sessions.DaemonTargetDescriptor.from_options(data["path"], data["sha256"],
                                                           data["bytes"], data["snapshot_id"])

    descriptor = write()
    return sample, other, third, config, calls, target, write, descriptor


def open_session(fixture, descriptor=None, **kwargs):
    return sessions.VerifiedDaemonTargetSession(
        descriptor or fixture[-1], bridge_names=kwargs.pop("bridge_names", ("deontic_norms",)),
        evaluate_provers=kwargs.pop("evaluate_provers", False),
        parallel_workers=kwargs.pop("parallel_workers", 1), **kwargs)


def test_descriptor_all_or_none_and_exact_validation():
    assert sessions.DaemonTargetDescriptor.from_options() is None
    valid = ("/tmp/fixture.bundle", "a" * 64, 32, "sha256:" + "b" * 64)
    descriptor = sessions.DaemonTargetDescriptor(*valid)
    serialized = descriptor.to_dict()
    assert serialized == {"path": valid[0], "sha256": valid[1], "bytes": 32, "snapshot_id": valid[3]}
    serialized["bytes"] = 999
    assert descriptor.size_bytes == 32
    for index in range(4):
        values = list(valid)
        values[index] = None
        with pytest.raises(TargetSnapshotError, match="all four"):
            sessions.DaemonTargetDescriptor.from_options(*values)
    for index, value in [(0, ""), (1, "not-sha"), (2, True), (2, 0),
                         (2, sessions.DEFAULT_MAX_BYTES + 1), (3, "b" * 64)]:
        values = list(valid)
        values[index] = value
        with pytest.raises(TargetSnapshotError):
            sessions.DaemonTargetDescriptor(*values)


@pytest.mark.parametrize("settings", [
    {"evaluate_provers": None}, {"evaluate_provers": 0}, {"parallel_workers": True},
    {"parallel_workers": 0}, {"bridge_names": "deontic_norms"},
    {"bridge_names": ("deontic_norms", "deontic_norms")}, {"max_expanded_bytes": True},
])
def test_settings_never_silently_coerce(fixture, settings):
    with pytest.raises(TargetSnapshotError):
        open_session(fixture, **settings)


def test_exact_union_hydrates_once_reuses_reordered_identical_payloads_and_parity(fixture):
    sample, other, _, _, _, target, _, _ = fixture
    with open_session(fixture) as session:
        first = session.begin_cycle([sample], [other, sample])
        assert first is not None and len(first) == 2
        for row in (sample, other):
            assert _json(_encode(first[row.sample_id])) == _json(_encode(target(row)))
        with pytest.raises(TypeError):
            first["extra"] = target(sample)
        original = first[sample.sample_id]
        lineage = session.lineage_identity
        lineage["snapshot_id"] = "tampered"
        assert session.lineage_identity["snapshot_id"] != "tampered"
        assert session.finish_cycle()["status"] == "completed"
        second = session.begin_cycle([other, sample], [])
        assert second is first and second[sample.sample_id] is original
        assert session.finish_cycle()["cache_hit"] is True
        summary = session.verify_shutdown()
        assert summary["counts"] == {"cycles_started": 2, "cycles_completed": 2,
                                     "hydrations": 1, "cache_hits": 1, "skipped_cycles": 0}
        assert summary["bundle_statistics"]["decompressed_shards"] == 2
        summary["counts"]["hydrations"] = 999
        assert session.summary()["counts"]["hydrations"] == 1
    assert session.summary()["bundle_statistics"]["closed"] is True


def test_selection_change_releases_previous_graphs_before_next_hydration(fixture, monkeypatch):
    sample, other = fixture[:2]
    with open_session(fixture) as session:
        first = session.begin_cycle([sample], [])
        reference = weakref.ref(first[sample.sample_id])
        del first
        session.finish_cycle()
        original = session._bundle.targets_for
        def hydrate(*args, **kwargs):
            assert reference() is None
            return original(*args, **kwargs)
        monkeypatch.setattr(session._bundle, "targets_for", hydrate)
        session.begin_cycle([other], [])
        session.finish_cycle()
        assert session.summary()["counts"]["hydrations"] == 2


def test_skip_all_or_none_clears_warm_selection_and_lineage(fixture):
    sample = fixture[0]
    with open_session(fixture) as session:
        session.begin_cycle([sample], [])
        session.finish_cycle()
        assert session.begin_cycle([object()], [], skip_reason="bounded_sample_clone") is None
        assert session.lineage_identity is None and session._targets is None
        assert session.finish_cycle()["skip_reason"] == "bounded_sample_clone"
        session.begin_cycle([sample], [])
        session.finish_cycle()
        assert session.summary()["counts"]["hydrations"] == 2


def test_bridge_off_never_opens_descriptor_or_producer(fixture, monkeypatch):
    descriptor = replace(fixture[-1], path="/missing/unused.bundle")
    def forbidden(*args, **kwargs):
        raise AssertionError("bridge-off must not consume targets")
    monkeypatch.setattr(sessions, "target_snapshot_config", forbidden)
    monkeypatch.setattr(codec, "load_target_bundle", forbidden)
    with open_session(fixture, descriptor, bridge_names=()) as session:
        assert session.begin_cycle([object()], []) is None
        assert session.finish_cycle()["skip_reason"] == "bridge_off"
        assert session.verify_shutdown()["bundle_statistics"] is None


def test_explicit_true_provers_and_workers_are_bound_without_worker_coercion(fixture):
    config, calls, write = fixture[3], fixture[4], fixture[6]
    descriptor = write(bound_config=replace(config, evaluate_provers=True, parallel_workers=3), name="true.bundle")
    with open_session(fixture, descriptor, evaluate_provers=True, parallel_workers=3) as session:
        session.begin_cycle([fixture[0]], [])
        session.finish_cycle()
    assert calls and all(c.legal_ir_evaluate_provers is True and c.legal_ir_parallel_workers == 3 for c in calls)


@pytest.mark.parametrize("change", ["missing", "vector", "nested", "conflict"])
def test_missing_or_changed_coverage_fails_closed_without_hydration(fixture, change):
    sample = fixture[0]
    changed = replace(sample, sample_id="unknown") if change == "missing" else replace(sample)
    if change == "vector":
        changed = replace(sample, embedding_vector=[*sample.embedding_vector[:-1], 0.999999])
    if change == "nested":
        changed = replace(sample, parser_trace={**sample.parser_trace, "changed": [1]})
    if change == "conflict":
        changed = replace(sample, losses={**sample.losses, "changed": 1.0})
    with open_session(fixture) as session:
        with pytest.raises(TargetSnapshotError, match="sample|aliases"):
            session.begin_cycle([sample] if change == "conflict" else [changed],
                                [changed] if change == "conflict" else [])
        assert session.summary()["poisoned"]
        assert session.summary()["bundle_statistics"]["decompressed_shards"] == 0
        with pytest.raises(TargetSnapshotError, match="poisoned"):
            session.begin_cycle([sample], [])


def test_referenced_expanded_bound_precedes_any_hydration(fixture):
    sample, other = fixture[:2]
    with open_session(fixture) as probe:
        bound = sum(row["uncompressed_bytes"] for row in probe._bundle._shards.values())
    with open_session(fixture, max_expanded_bytes=bound // 3) as session:
        with pytest.raises(TargetSnapshotError, match="expanded"):
            session.begin_cycle([sample, other], [])
        assert session.summary()["bundle_statistics"]["decompressed_shards"] == 0


def test_nested_sample_mutation_during_cycle_prevents_completion(fixture):
    sample = fixture[0]
    with open_session(fixture) as session:
        session.begin_cycle([sample], [])
        sample.parser_trace["nested_change"] = {"value": 1}
        with pytest.raises(TargetSnapshotError, match="changed during"):
            session.finish_cycle()
        assert session.summary()["current_cycle"]["status"] == "failed"
        assert session.summary()["counts"]["cycles_completed"] == 0


def test_mutation_of_distinct_equal_duplicate_input_is_not_hidden_by_union(fixture):
    sample = fixture[0]
    equal_sample = replace(sample, parser_trace=dict(sample.parser_trace))
    with open_session(fixture) as session:
        targets = session.begin_cycle([sample], [equal_sample])
        assert len(targets) == 1
        equal_sample.parser_trace["changed_only_in_validation"] = 1
        with pytest.raises(TargetSnapshotError, match="aliases"):
            session.finish_cycle()
        assert session.summary()["poisoned"]


@pytest.mark.parametrize("boundary", ["begin", "finish", "shutdown"])
def test_changed_producer_poisoning_at_every_boundary(fixture, monkeypatch, boundary):
    with open_session(fixture) as session:
        if boundary != "begin":
            session.begin_cycle([fixture[0]], [])
        if boundary == "shutdown":
            session.finish_cycle()
        def changed(settings):
            raise ValueError("target producer changed; start a fresh process")
        monkeypatch.setattr(sessions, "target_snapshot_config", changed)
        with pytest.raises(ValueError, match="fresh process"):
            {"begin": lambda: session.begin_cycle([fixture[0]], []),
             "finish": session.finish_cycle, "shutdown": session.verify_shutdown}[boundary]()
        assert session.summary()["poisoned"]


@pytest.mark.parametrize("mutation", ["same_inode", "replacement"])
def test_changed_artifact_rejected_at_finish_and_file_always_closed(fixture, mutation):
    path = Path(fixture[-1].path)
    session = open_session(fixture)
    descriptor = session._bundle._descriptor
    session.begin_cycle([fixture[0]], [])
    if mutation == "same_inode":
        with path.open("r+b") as handle:
            handle.seek(-1, os.SEEK_END)
            byte = handle.read(1)
            handle.seek(-1, os.SEEK_END)
            handle.write(bytes([byte[0] ^ 1]))
    else:
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    with pytest.raises(TargetSnapshotError, match="changed"):
        session.finish_cycle()
    session.close()
    with pytest.raises(OSError):
        os.fstat(descriptor)
    assert session.summary()["poisoned"] and session.summary()["closed"]


def test_abort_and_provisional_shutdown_never_claim_completion(fixture):
    with open_session(fixture) as session:
        session.begin_cycle([fixture[0]], [])
        with pytest.raises(TargetSnapshotError, match="provisional"):
            session.verify_shutdown()
        error = RuntimeError("original")
        session.abort_cycle(error)
        assert session.summary()["failure"] == {"exception_type": "RuntimeError"}
        with pytest.raises(TargetSnapshotError, match="poisoned"):
            session.verify_shutdown()


def test_rich_target_uses_complete_live_path_fallback(fixture):
    sample, _, _, _, _, target, write, _ = fixture
    rich = RichLegalIRTarget({**vars(target(sample)), "candidate_ir": {"custom": True}})
    descriptor = write([sample], [rich], name="rich.bundle")
    with open_session(fixture, descriptor) as session:
        assert session.begin_cycle([sample], []) is None
        assert session.finish_cycle()["skip_reason"] == "non_native_target"
        assert session.lineage_identity is None and session._targets is None


@pytest.mark.parametrize("field,value", [("size_bytes", 1), ("snapshot_id", "sha256:" + "f" * 64)])
def test_descriptor_mismatch_closes_newly_opened_bundle(fixture, monkeypatch, field, value):
    opened = []
    original = codec.load_target_bundle
    def load(*args, **kwargs):
        result = original(*args, **kwargs)
        opened.append(result)
        return result
    monkeypatch.setattr(codec, "load_target_bundle", load)
    with pytest.raises(TargetSnapshotError, match="descriptor"):
        open_session(fixture, replace(fixture[-1], **{field: value}))
    assert opened[0].statistics["closed"] is True
