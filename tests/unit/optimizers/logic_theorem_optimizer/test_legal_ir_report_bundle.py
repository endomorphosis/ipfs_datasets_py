"""Lossless native report DAG, target binding, bounds and staged-file lifetime."""
from dataclasses import replace
import json
import os
from pathlib import Path
import struct
import zlib

import pytest

from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
from ipfs_datasets_py.logic.bridge.types import (
    BridgeEvaluationReport, GraphProjectionResult, LegalIRDocument, LogicIRView,
    ProofGateResult, RoundTripMetrics,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_report_bundle as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import (
    TargetSnapshotConfig, TargetSnapshotError, _encode, _json,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample


@pytest.fixture
def fixture():
    sample = build_us_code_sample(title="5", section="report-fixture", text="The agency shall retain records.")
    config = TargetSnapshotConfig(("deontic_norms", "fol_tdfol"), False, 1,
                                  {"synthetic-fixture": "a" * 64}, {"kind": "unit fixture"})
    shared = [1, -0.0, 0.12345678912345678, ("z", "a")]
    payload = {"right": shared, "left": shared, "nested": {"value": shared}}
    view = LogicIRView("deontic.ir", payload, "fixture-v1", "deontic.ir", {"count": 2, "tuple": (3, 2)})
    document = LegalIRDocument(sample.sample_id, sample.text, sample.normalized_text,
                              source=sample.source, citation=sample.citation,
                              views={"deontic.ir": view},
                              frame_logic_triples=({"subject": "agency", "predicate": "must", "object": "retain"},),
                              metadata={"created_at": "2026-09-25T00:00:00Z", "shared": shared})
    round_trip = RoundTripMetrics(cosine_similarity=0.8123456789123456, cosine_loss=0.1876543210876544,
                                 extra_losses={"z": -0.0, "a": 0.5})
    proof = ProofGateResult(4, 1, 1, 1, 1, ("z", "a"), ({"error": "retained exact error", "number": 3},))
    graph = GraphProjectionResult("graph", True, 3, 2, ["z", "a"], ("later", "earlier"), {"observed": True})
    reports = {name: BridgeEvaluationReport(name, component, document, round_trip, proof, graph,
                                           "decoded original text", "partial", {"diagnostic": "preserved"})
               for name, component in (("deontic_norms", "deontic.ir"), ("fol_tdfol", "TDFOL.prover"))}
    report = MultiViewLegalIRReport(config.bridge_names, document, reports, {})
    return sample, config, report


def write(tmp_path, fixture, *, report=None, status=None, name="reports.bundle"):
    sample, config, original = fixture
    return codec.write_report_bundle(tmp_path / name, [(sample, original if report is None else report, status)], config=config)


def load(ref, **kwargs):
    return codec.load_report_bundle(ref["path"], expected_sha256=ref["sha256"], expected_size_bytes=ref["bytes"], **kwargs)


def unpack(ref):
    raw = Path(ref["path"]).read_bytes()
    magic, length = codec._HEADER.unpack(raw[:codec._HEADER.size])
    assert magic == codec.MAGIC
    return json.loads(raw[codec._HEADER.size:codec._HEADER.size + length]), raw[codec._HEADER.size + length:]


def reseal(tmp_path, manifest, payload, name="changed.bundle"):
    body = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    manifest["snapshot_id"] = "sha256:" + codec._digest(body)
    encoded = _json(manifest)
    raw = codec._HEADER.pack(codec.MAGIC, len(encoded)) + encoded + payload
    path = tmp_path / name
    path.write_bytes(raw)
    return {"path": str(path), "sha256": codec._sha(raw), "bytes": len(raw)}


def test_native_roundtrip_preserves_all_fields_aliases_order_types_and_float_bits(fixture):
    original = fixture[2]
    raw = codec.report_to_bytes(original)
    restored = codec.report_from_bytes(raw)
    assert codec.report_to_bytes(restored) == raw
    assert restored == original and restored is not original
    assert restored.document is restored.reports["deontic_norms"].ir_document
    assert restored.document is restored.reports["fol_tdfol"].ir_document
    first, second = restored.reports.values()
    assert first.round_trip is second.round_trip and first.proof_gate is second.proof_gate
    assert first.graph_projection is second.graph_projection
    payload = restored.document.views["deontic.ir"].payload
    assert list(payload) == ["right", "left", "nested"]
    assert payload["left"] is payload["right"] is payload["nested"]["value"] is restored.document.metadata["shared"]
    assert type(payload["left"]) is list and type(payload["left"][3]) is tuple
    assert struct.pack("!d", payload["left"][1]) == struct.pack("!d", -0.0)
    assert struct.pack("!d", first.round_trip.cosine_similarity) == struct.pack("!d", original.reports["deontic_norms"].round_trip.cosine_similarity)
    assert first.graph_projection.node_labels == ["z", "a"]
    assert first.graph_projection.relationship_types == ("later", "earlier")
    assert first.proof_gate.details[0]["error"] == "retained exact error"
    assert first.status == "partial" and first.accepted is False


def test_one_hydrated_graph_derives_exact_target_and_fresh_requests_are_independent(fixture, tmp_path):
    sample, config, report = fixture
    ref = write(tmp_path, fixture)
    with load(ref, config=config) as bundle:
        assert bundle.statistics["decompressed_shards"] == 0
        selection = bundle.selection_for([sample], config=config)
        restored = selection.reports[sample.sample_id]
        target = selection.targets[sample.sample_id]
        assert target.document is restored.document
        assert _json(_encode(target)) == _json(_encode(report.training_target()))
        assert selection.metadata["target_sha256"][sample.sample_id] == codec._sha(_json(_encode(target)))
        assert selection.metadata["sample_ids"] == [sample.sample_id]
        with pytest.raises(TypeError):
            selection.reports["new"] = restored
        with pytest.raises(TypeError):
            selection.targets["new"] = target
        other = bundle.selection_for([sample], config=config)
        assert other.reports[sample.sample_id].document is not restored.document
        restored.document.metadata["changed"] = 1
        assert "changed" not in other.reports[sample.sample_id].document.metadata
        assert bundle.verify_unchanged()["sha256"] == ref["sha256"]
    assert bundle.statistics["closed"]
    with pytest.raises(codec.ReportBundleError, match="closed"):
        bundle.selection_for([sample], config=config)


def test_identity_changes_for_aliased_versus_equal_distinct_container_graphs(fixture):
    report = fixture[2]
    before = codec.report_to_bytes(report)
    payload = report.document.views["deontic.ir"].payload
    payload["left"] = list(payload["right"])
    after = codec.report_to_bytes(report)
    assert before != after
    restored = codec.report_from_bytes(after).document.views["deontic.ir"].payload
    assert restored["left"] == restored["right"] and restored["left"] is not restored["right"]


def test_partial_report_failure_strings_counts_and_target_semantics_survive(fixture, tmp_path):
    sample, config, original = fixture
    report = replace(original, reports={"deontic_norms": original.reports["deontic_norms"]},
                     failures={"fol_tdfol": "ValueError: exact original failure\nsecond line"})
    ref = write(tmp_path, fixture, report=report)
    assert ref["statuses"] == {sample.sample_id: "partial"}
    with load(ref) as bundle:
        loaded = bundle.selection_for([sample], config=config)
    restored = loaded.reports[sample.sample_id]
    assert restored.failures == report.failures and restored.attempted_count == 2
    assert len(restored.reports) == 1 and restored.accepted is False
    assert restored.loss_vector() == report.loss_vector()
    assert _json(_encode(loaded.targets[sample.sample_id])) == _json(_encode(report.training_target()))
    with pytest.raises(codec.ReportBundleError, match="disposition"):
        write(tmp_path, fixture, report=report, status="ready", name="false-ready.bundle")


def test_native_silent_missing_adapter_is_partial_without_inventing_failure(fixture, tmp_path):
    sample, config, original = fixture
    report = replace(original, reports={"deontic_norms": original.reports["deontic_norms"]}, failures={})
    ref = write(tmp_path, fixture, report=report)
    assert ref["statuses"][sample.sample_id] == "partial"
    with load(ref) as bundle:
        selection = bundle.selection_for([sample], config=config)
    restored = selection.reports[sample.sample_id]
    assert list(restored.reports) == ["deontic_norms"]
    assert restored.failures == {} and restored.attempted_count == 2
    assert restored.acceptance_rate == report.acceptance_rate and restored.accepted is False
    assert restored.loss_vector() == report.loss_vector()
    assert codec.report_to_bytes(restored) == codec.report_to_bytes(report)
    assert _json(_encode(selection.targets[sample.sample_id])) == _json(_encode(report.training_target()))


@pytest.mark.parametrize("status", ["timeout", "failed", "unavailable", "unsupported"])
def test_missing_report_dispositions_never_fabricate_reports_or_targets(fixture, tmp_path, status):
    sample, config, _ = fixture
    ref = codec.write_report_bundle(tmp_path / "missing.bundle", [(sample, None, status)], config=config)
    assert ref["report_count"] == 0 and ref["statuses"][sample.sample_id] == status
    with load(ref) as bundle:
        with pytest.raises(codec.ReportUnavailableError, match=status):
            bundle.selection_for([sample], config=config)
        assert bundle.statistics["decompressed_shards"] == 0


@pytest.mark.parametrize("status", [None, "ready", "partial", "invented"])
def test_missing_report_requires_explicit_absence_status(fixture, tmp_path, status):
    with pytest.raises(codec.ReportBundleError, match="missing report"):
        codec.write_report_bundle(tmp_path / "missing.bundle", [(fixture[0], None, status)], config=fixture[1])
    assert list(tmp_path.iterdir()) == []


class HostileDict(dict):
    def items(self):
        raise AssertionError("custom mapping must not be inspected")


@pytest.mark.parametrize("change", ["custom_mapping", "extra_field", "nan", "cycle", "bad_count", "unknown_adapter", "overlap"])
def test_unsupported_native_graphs_fail_without_summary_or_custom_serialization(fixture, change):
    report = fixture[2]
    if change == "custom_mapping":
        report.document.metadata["custom"] = HostileDict()
    elif change == "extra_field":
        object.__setattr__(report, "to_dict", lambda: pytest.fail("serializer override must not run"))
    elif change == "nan":
        report.document.metadata["nonfinite"] = float("nan")
    elif change == "cycle":
        report.document.metadata["cycle"] = report.document.metadata
    elif change == "bad_count":
        object.__setattr__(report.reports["deontic_norms"].proof_gate, "error_count", True)
    elif change == "unknown_adapter":
        report.failures["unknown_adapter"] = "unrequested"
    elif change == "overlap":
        report.failures["fol_tdfol"] = "error"
    with pytest.raises(codec.ReportBundleError):
        codec.report_to_bytes(report)


def test_node_depth_and_reference_amplification_bounds(fixture, monkeypatch):
    report = fixture[2]
    original = report.document.metadata
    nested = []
    for _ in range(codec.MAX_DEPTH + 1):
        nested = [nested]
    original["too_deep"] = nested
    with pytest.raises(codec.ReportBundleError, match="nesting"):
        codec.report_to_bytes(report)
    original.pop("too_deep")
    # Tiny acyclic shared DAG would explode when unchanged native target/JSON
    # code expands it as a tree. Reject before any such method is called.
    repeated = ["x"]
    for _ in range(30):
        repeated = [repeated, repeated]
    original["amplified"] = repeated
    with pytest.raises(codec.ReportBundleError, match="expanded report graph"):
        codec.report_to_bytes(report)
    original.pop("amplified")
    monkeypatch.setattr(codec, "MAX_NODES", 2)
    with pytest.raises(codec.ReportBundleError, match="node count"):
        codec.report_to_bytes(report)


def test_raw_dag_amplification_is_rejected_independently_during_decode(fixture, monkeypatch):
    repeated = ["x"]
    for _ in range(30):
        repeated = [repeated, repeated]
    fixture[2].document.metadata["amplified"] = repeated
    # Produce only the tiny DAG with arithmetic bounds temporarily relaxed;
    # never invoke training_target, canonical_hash or an expanding serializer.
    with monkeypatch.context() as patched:
        patched.setattr(codec, "MAX_EXPANDED_GRAPH_BYTES", 1 << 60)
        raw = codec.report_to_bytes(fixture[2])
    assert len(raw) < 8192
    with pytest.raises(codec.ReportBundleError, match="expanded report graph"):
        codec.report_from_bytes(raw)


def shift_refs(value):
    if isinstance(value, dict):
        if set(value) == {"ref"}:
            value["ref"] += 1
        else:
            for item in value.values():
                shift_refs(item)
    elif isinstance(value, list):
        for item in value:
            shift_refs(item)


def tagged_v2(raw):
    """Expose the common historical grammar for its existing rejection tests."""
    data = json.loads(raw)
    if data["schema_version"] == codec.DAG_SCHEMA_VERSION:
        data = codec._expand_positional(data)
        data["nodes"] = list(data["nodes"])
    return data


@pytest.mark.parametrize("change", ["extra", "unknown_class", "field_order", "duplicate_key", "forward", "self_ref", "unused", "bool_ref", "overflow_float"])
def test_malformed_dag_never_instantiates_unknown_or_cyclic_objects(fixture, change):
    data = tagged_v2(codec.report_to_bytes(fixture[2]))
    if change == "extra":
        data["unexpected"] = True
    elif change == "unknown_class":
        data["nodes"][-1]["type"] = "InjectedCallable"
    elif change == "field_order":
        data["nodes"][-1]["fields"].reverse()
    elif change == "duplicate_key":
        node = next(node for node in data["nodes"] if node["type"] == "dict" and node["items"])
        node["items"].append(node["items"][0])
    elif change in {"forward", "self_ref", "bool_ref"}:
        index, node = next((index, node) for index, node in enumerate(data["nodes"]) if node["type"] == "list" and node["items"])
        node["items"][0] = {"ref": len(data["nodes"]) if change == "forward" else index if change == "self_ref" else True}
    elif change == "unused":
        shift_refs(data)
        data["nodes"].insert(0, {"type": "list", "items": []})
    elif change == "overflow_float":
        node = next(node for node in data["nodes"] if node["type"] == "list" and node["items"])
        node["items"][0] = "OVERFLOW"
    raw = _json(data).replace(b'"OVERFLOW"', b'1e400')
    with pytest.raises(TargetSnapshotError):
        codec.report_from_bytes(raw)


def test_duplicate_json_keys_rejected(fixture):
    raw = codec.report_to_bytes(fixture[2])
    with pytest.raises(TargetSnapshotError, match="JSON"):
        codec.report_from_bytes(raw.replace(b'{"nodes":', b'{"nodes":[],"nodes":', 1))


@pytest.mark.parametrize("change", ["vector", "text", "missing", "duplicate", "config", "bound"])
def test_complete_selection_preflight_before_any_hydration(fixture, tmp_path, change):
    sample, config, _ = fixture
    ref = write(tmp_path, fixture)
    with load(ref) as bundle:
        samples, kwargs = [sample], {"config": config}
        if change == "vector":
            samples = [replace(sample, embedding_vector=[0.2] * len(sample.embedding_vector))]
        elif change == "text":
            samples = [replace(sample, text=sample.text + " Changed.")]
        elif change == "missing":
            samples.append(replace(sample, sample_id="absent"))
        elif change == "duplicate":
            samples.append(sample)
        elif change == "config":
            kwargs["config"] = replace(config, evaluate_provers=True)
        else:
            kwargs["max_expanded_bytes"] = 1
        with pytest.raises(TargetSnapshotError):
            bundle.selection_for(samples, **kwargs)
        assert bundle.statistics["decompressed_shards"] == 0


@pytest.mark.parametrize("change", ["target_hash", "status", "compressed_hash", "raw_hash", "oversize", "trailing_compressed"])
def test_resealed_outer_artifact_cannot_bypass_inner_report_or_target_bindings(fixture, tmp_path, change):
    ref = write(tmp_path, fixture)
    manifest, payload = unpack(ref)
    if change == "target_hash":
        manifest["records"][0]["target_sha256"] = "f" * 64
    elif change == "status":
        manifest["records"][0]["status"] = "partial"
    elif change == "compressed_hash":
        manifest["shards"][0]["compressed_sha256"] = "f" * 64
    elif change == "raw_hash":
        manifest["shards"][0]["report_sha256"] = manifest["records"][0]["report_sha256"] = "f" * 64
    elif change == "oversize":
        manifest["shards"][0]["uncompressed_bytes"] = codec.DEFAULT_MAX_SHARD_BYTES + 1
    elif change == "trailing_compressed":
        payload += zlib.compress(b"trailing")
        manifest["shards"][0]["compressed_bytes"] = len(payload)
        manifest["shards"][0]["compressed_sha256"] = codec._sha(payload)
    changed = reseal(tmp_path, manifest, payload)
    with pytest.raises(TargetSnapshotError):
        with load(changed) as bundle:
            bundle.selection_for([fixture[0]], config=fixture[1])


def test_publication_is_deterministic_exclusive_and_rolls_back_failed_producer(fixture, tmp_path):
    first = write(tmp_path, fixture)
    second = write(tmp_path, fixture, name="same.bundle")
    assert first["sha256"] == second["sha256"] and first["snapshot_id"] == second["snapshot_id"]
    with pytest.raises(FileExistsError):
        write(tmp_path, fixture)
    class ProducerFailure(RuntimeError):
        pass
    def broken():
        yield fixture[0], fixture[2], None
        raise ProducerFailure("final producer guard")
    with pytest.raises(ProducerFailure, match="producer guard"):
        codec.write_report_bundle(tmp_path / "failed.bundle", broken(), config=fixture[1])
    assert sorted(path.name for path in tmp_path.iterdir()) == ["reports.bundle", "same.bundle"]


@pytest.mark.parametrize("change", ["same_inode", "replacement", "symlink"])
def test_boundary_verification_detects_persistent_mutation_replacement_and_aliases(fixture, tmp_path, change):
    ref = write(tmp_path, fixture)
    path = Path(ref["path"])
    if change == "symlink":
        alias = path.with_name("alias.bundle")
        alias.symlink_to(path)
        with pytest.raises(OSError):
            load({**ref, "path": str(alias)})
        return
    with load(ref) as bundle:
        if change == "same_inode":
            with path.open("r+b") as handle:
                handle.seek(-1, os.SEEK_END)
                value = handle.read(1)[0]
                handle.seek(-1, os.SEEK_END)
                handle.write(bytes([value ^ 1]))
        else:
            replacement = path.with_name("replacement.bundle")
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        with pytest.raises(TargetSnapshotError, match="changed"):
            bundle.verify_unchanged()


@pytest.mark.parametrize("field,value", [("sha256", "f" * 64), ("bytes", 1), ("bytes", True)])
def test_external_descriptor_identity_is_required(fixture, tmp_path, field, value):
    ref = write(tmp_path, fixture)
    with pytest.raises(TargetSnapshotError):
        load({**ref, field: value})


def inline_v1(data):
    """Independent wire conversion for historical-format compatibility checks."""
    strings = data["strings"]

    def replace_strings(value):
        if type(value) is dict:
            if set(value) == {"str"}:
                return strings[value["str"]]
            return {key: replace_strings(item) for key, item in value.items()}
        if type(value) is list:
            return [replace_strings(item) for item in value]
        return value

    return {"schema_version": "legal-ir-native-report-dag-v1",
            "nodes": replace_strings(data["nodes"]), "root": data["root"]}


def string_table_report(fixture):
    report = fixture[2]
    first = ("é\n\\\"\x00\ud800" * 20) + "first"
    second = "second exact string " * 20
    report.document.metadata["strings"] = [first, second, first, second]
    report.document.metadata["keymaps"] = [{first: second}, {second: first}]
    return report


def test_repeated_strings_reduce_wire_size_without_losing_exact_values(fixture):
    report = string_table_report(fixture)
    repeated = "The agency shall retain the exact source text. " * 100
    report.document.metadata["many"] = [repeated] * 64
    report.document.metadata["unique"] = "This long unique value stays inline. " * 10
    raw = codec.report_to_bytes(report)
    assert json.loads(raw)["schema_version"] == "legal-ir-native-report-dag-v3"
    data = tagged_v2(raw)
    assert data["schema_version"] == "legal-ir-native-report-dag-v2"
    assert len(data["strings"]) == 3
    legacy_raw = _json(inline_v1(data))
    v2_raw = _json(data)
    assert len(raw) < len(legacy_raw) // 10
    # The small wire limit succeeds only due to representation, not a raised cap.
    assert codec.report_to_bytes(report, max_bytes=len(raw)) == raw
    with pytest.raises(codec.ReportBundleError, match="byte"):
        codec.report_from_bytes(legacy_raw, max_bytes=len(raw))
    restored = codec.report_from_bytes(raw)
    legacy = codec.report_from_bytes(legacy_raw)
    v2 = codec.report_from_bytes(v2_raw)
    assert restored == legacy == v2 == report
    assert list(restored.document.metadata["keymaps"][0]) == list(report.document.metadata["keymaps"][0])
    assert type(restored.document.metadata["strings"][0]) is str
    assert restored.document is restored.reports["deontic_norms"].ir_document
    assert codec.report_to_bytes(restored) == codec.report_to_bytes(legacy) == raw
    expected = _json(_encode(report.training_target()))
    assert _json(_encode(restored.training_target())) == _json(_encode(legacy.training_target())) == expected


@pytest.mark.parametrize("version", [1, 2])
def test_historical_bundles_load_and_manifest_body_versions_must_match(fixture, tmp_path, version):
    report = string_table_report(fixture)
    ref = write(tmp_path, fixture, report=report)
    manifest, compressed = unpack(ref)
    assert manifest["codec"] == "zlib:legal-ir-native-report-dag-v3"
    assert ref["statistics"]["codec"] == manifest["codec"]
    data = tagged_v2(zlib.decompress(compressed))
    raw = _json(inline_v1(data) if version == 1 else data)
    compressed = zlib.compress(raw, level=6)
    manifest["codec"] = f"zlib:legal-ir-native-report-dag-v{version}"
    manifest["shards"][0].update(report_sha256=codec._sha(raw), compressed_bytes=len(compressed),
                                  uncompressed_bytes=len(raw), compressed_sha256=codec._sha(compressed))
    manifest["records"][0]["report_sha256"] = codec._sha(raw)
    legacy = reseal(tmp_path, manifest, compressed, "v1.bundle")
    with load(legacy) as bundle:
        selected = bundle.selection_for([fixture[0]], config=fixture[1])
        assert selected.reports[fixture[0].sample_id] == report
        assert _json(_encode(selected.targets[fixture[0].sample_id])) == _json(_encode(report.training_target()))
        assert bundle.statistics["codec"] == manifest["codec"]
    manifest["codec"] = "zlib:legal-ir-native-report-dag-v3"
    mismatch = reseal(tmp_path, manifest, compressed, "mismatch.bundle")
    with load(mismatch) as bundle:
        with pytest.raises(codec.ReportBundleError, match="envelope"):
            bundle.selection_for([fixture[0]], config=fixture[1])
    with pytest.raises(codec.ReportBundleError, match="envelope"):
        codec.report_from_bytes(codec.report_to_bytes(report), expected_schema_version="legal-ir-native-report-dag-v1")


@pytest.mark.parametrize("change", [
    "missing_table", "table_type", "duplicate", "entry_type", "short", "unused", "single_use",
    "inline_pooled", "first_order", "bool_ref", "negative_ref", "out_of_range", "extra_ref_key",
    "mixed_ref", "duplicate_decoded_key", "field_name_ref", "v1_with_table", "v1_with_ref",
])
def test_malformed_v2_string_tables_and_references_reject(fixture, change):
    data = tagged_v2(codec.report_to_bytes(string_table_report(fixture)))
    node = next(node for node in data["nodes"] if node["type"] == "list"
                and node["items"] == [{"str": 0}, {"str": 1}, {"str": 0}, {"str": 1}])
    if change == "missing_table":
        data.pop("strings")
    elif change == "table_type":
        data["strings"] = {}
    elif change == "duplicate":
        data["strings"].append(data["strings"][0])
    elif change == "entry_type":
        data["strings"][0] = 123
    elif change == "short":
        data["strings"][0] = "short"
    elif change == "unused":
        data["strings"].append("unused long string " * 10)
    elif change == "single_use":
        data["strings"].append("single-use long string " * 10)
        node["items"].append({"str": 2})
    elif change == "inline_pooled":
        node["items"][0] = data["strings"][0]
    elif change == "first_order":
        node["items"][0] = {"str": 1}
    elif change == "bool_ref":
        node["items"][0] = {"str": False}
    elif change == "negative_ref":
        node["items"][0] = {"str": -1}
    elif change == "out_of_range":
        node["items"][0] = {"str": len(data["strings"])}
    elif change == "extra_ref_key":
        node["items"][0]["extra"] = 1
    elif change == "mixed_ref":
        node["items"][0]["ref"] = 0
    elif change == "duplicate_decoded_key":
        mapping = next(item for item in data["nodes"] if item["type"] == "dict"
                       and item["items"] and type(item["items"][0][0]) is dict)
        mapping["items"].append([dict(mapping["items"][0][0]), 123])
    elif change == "field_name_ref":
        data["nodes"][-1]["fields"][0][0] = {"str": 0}
    elif change == "v1_with_table":
        data["schema_version"] = "legal-ir-native-report-dag-v1"
    elif change == "v1_with_ref":
        data["schema_version"] = "legal-ir-native-report-dag-v1"
        data.pop("strings")
    with pytest.raises(codec.ReportBundleError):
        codec.report_from_bytes(_json(data))


def test_string_table_count_and_original_expanded_value_bounds_are_independent(fixture, monkeypatch):
    report = string_table_report(fixture)
    raw = codec.report_to_bytes(report)
    with monkeypatch.context() as bounded:
        bounded.setattr(codec, "MAX_STRINGS", 1)
        with pytest.raises(codec.ReportBundleError, match="string"):
            codec.report_to_bytes(report)
        with pytest.raises(codec.ReportBundleError, match="string|envelope"):
            codec.report_from_bytes(raw)
    # Pooled wire bytes are small, but all original long key/value occurrences
    # still count against the same expanded-tree traversal bound in the reader.
    report.document.metadata["expanded"] = ["large retained text " * 1000] * 50
    raw = codec.report_to_bytes(report)
    assert len(raw) < 40_000
    with monkeypatch.context() as bounded:
        bounded.setattr(codec, "MAX_EXPANDED_GRAPH_BYTES", 200_000)
        with pytest.raises(codec.ReportBundleError, match="expanded report graph"):
            codec.report_from_bytes(raw)
        with pytest.raises(codec.ReportBundleError, match="expanded report graph"):
            codec.report_to_bytes(report)


def test_positional_wire_reduces_framing_and_only_raw_bytes_use_shard_cap(fixture):
    report = string_table_report(fixture)
    report.document.metadata["small_records"] = [{"subject": f"agency-{i}", "predicate": "retain", "count": i}
                                                  for i in range(200)]
    raw = codec.report_to_bytes(report)
    data = json.loads(raw)
    assert set(data) == {"schema_version", "schema_sha256", "strings", "nodes", "root"}
    assert data["schema_version"] == "legal-ir-native-report-dag-v3"
    assert data["schema_sha256"] == codec._digest({"node_types": list(codec._NODE_TYPES),
        "fields": {kind: list(codec._FIELDS[kind]) for kind in codec._NODE_TYPES[3:]}})
    assert type(data["root"]) is int and data["root"] == len(data["nodes"]) - 1
    assert all(type(row) is list and len(row) == 2 and type(row[0]) is int for row in data["nodes"])
    common = codec._expand_positional(data)
    assert type(common["nodes"]) is not list  # One-node normalization after complete shape preflight.
    common["nodes"] = list(common["nodes"])
    tagged_raw = _json(common)
    assert len(raw) < len(tagged_raw)
    restored = codec.report_from_bytes(raw, max_bytes=len(raw))
    with pytest.raises(codec.ReportBundleError, match="byte"):
        codec.report_from_bytes(tagged_raw, max_bytes=len(raw))
    assert codec.report_to_bytes(restored) == raw
    assert _json(_encode(restored.training_target())) == _json(_encode(report.training_target()))


@pytest.mark.parametrize("change", [
    "extra_envelope", "missing_schema_hash", "schema_hash", "data_driven_fields", "root_bool", "root_ref",
    "root_wrong", "nodes_type", "node_count", "row_type", "row_extra", "tag_bool", "tag_negative",
    "tag_unknown", "payload_type", "odd_dict", "field_arity", "ref_kind_bool", "ref_kind_unknown",
    "ref_index_bool", "ref_negative", "ref_forward", "ref_self", "ref_extra", "ref_dict", "string_oob",
    "string_bool", "nonfinite", "duplicate_key", "unreachable", "schema_label",
])
def test_positional_closed_shapes_indices_and_common_validation(fixture, change, monkeypatch):
    data = json.loads(codec.report_to_bytes(string_table_report(fixture)))
    index, row = next((i, row) for i, row in enumerate(data["nodes"])
                      if row[0] == codec._NODE_TAGS["list"] and row[1])
    if change == "extra_envelope":
        data["extra"] = 1
    elif change == "missing_schema_hash":
        data.pop("schema_sha256")
    elif change == "schema_hash":
        data["schema_sha256"] = "0" * 64
    elif change == "data_driven_fields":
        data["fields"] = {"MultiViewLegalIRReport": ["injected"]}
    elif change == "root_bool":
        data["root"] = True
    elif change == "root_ref":
        data["root"] = [0, data["root"]]
    elif change == "root_wrong":
        data["root"] -= 1
    elif change == "nodes_type":
        data["nodes"] = {}
    elif change == "node_count":
        monkeypatch.setattr(codec, "MAX_NODES", len(data["nodes"]) - 1)
    elif change == "row_type":
        data["nodes"][0] = {"type": "dict", "items": []}
    elif change == "row_extra":
        data["nodes"][0].append(1)
    elif change == "tag_bool":
        row[0] = True
    elif change == "tag_negative":
        row[0] = -1
    elif change == "tag_unknown":
        row[0] = len(codec._NODE_TYPES)
    elif change == "payload_type":
        row[1] = {}
    elif change == "odd_dict":
        next(item for item in data["nodes"] if item[0] == codec._NODE_TAGS["dict"])[1].append("unpaired")
    elif change == "field_arity":
        data["nodes"][-1][1].append(0)
    elif change == "ref_kind_bool":
        row[1][0] = [False, 0]
    elif change == "ref_kind_unknown":
        row[1][0] = [2, 0]
    elif change == "ref_index_bool":
        row[1][0] = [0, False]
    elif change == "ref_negative":
        row[1][0] = [0, -1]
    elif change == "ref_forward":
        row[1][0] = [0, len(data["nodes"])]
    elif change == "ref_self":
        row[1][0] = [0, index]
    elif change == "ref_extra":
        row[1][0] = [0, 0, 0]
    elif change == "ref_dict":
        row[1][0] = {"ref": 0}
    elif change == "string_oob":
        row[1][0] = [1, len(data["strings"])]
    elif change == "string_bool":
        row[1][0] = [1, False]
    elif change == "nonfinite":
        row[1][0] = "OVERFLOW"
    elif change == "duplicate_key":
        mapping = next(item for item in data["nodes"] if item[0] == codec._NODE_TAGS["dict"] and item[1])
        mapping[1].extend(mapping[1][:2])
    elif change == "unreachable":
        # Appending a scalar to a formerly shared first list does not create a
        # reference to this extra zero-child tuple; its absence must be caught.
        for item in data["nodes"]:
            for value in item[1]:
                if type(value) is list and value[0] == 0:
                    value[1] += 1
        data["nodes"].insert(0, [codec._NODE_TAGS["tuple"], []])
        data["root"] += 1
    elif change == "schema_label":
        data["schema_version"] = "legal-ir-native-report-dag-v2"
    raw = _json(data).replace(b'"OVERFLOW"', b'1e400')
    with pytest.raises(codec.ReportBundleError):
        codec.report_from_bytes(raw)


def test_entire_positional_shape_preflight_precedes_any_native_constructor(fixture, monkeypatch):
    data = json.loads(codec.report_to_bytes(fixture[2]))
    data["nodes"][-1][1].append(None)  # Malformed last node, after all native-class nodes.
    calls = []
    def unexpected(**kwargs):
        calls.append(kwargs)
        raise AssertionError("native constructors must not precede full compact shape preflight")
    monkeypatch.setattr(codec, "_CLASSES", {kind: unexpected for kind in codec._CLASSES})
    with pytest.raises(codec.ReportBundleError, match="field count"):
        codec.report_from_bytes(_json(data))
    assert calls == []
