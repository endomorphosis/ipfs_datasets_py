"""Pure diagnostic framing and observation tests; no native report generation."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
from ipfs_datasets_py.logic.bridge.types import (
    BridgeEvaluationReport, GraphProjectionResult, LegalIRDocument, LogicIRView,
    ProofGateResult, RoundTripMetrics,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_report_bundle as codec

V2_SCHEMA = "legal-ir-native-report-dag-v2"


def v2_data(report):
    data = json.loads(codec.report_to_bytes(report))
    if data["schema_version"] != V2_SCHEMA:
        data = codec._expand_positional(data)
        data["nodes"] = list(data["nodes"])
    return data


@pytest.fixture
def historical_codec(native_report):
    """Keep the archived v2-only diagnostic tests scoped to its original wire."""
    data = v2_data(native_report)
    result = SimpleNamespace(_json=codec._json, _FIELDS=codec._FIELDS, MAX_NODES=codec.MAX_NODES,
        DAG_SCHEMA_VERSION=V2_SCHEMA, DEFAULT_MAX_SHARD_BYTES=codec.DEFAULT_MAX_SHARD_BYTES)
    def encode(report, *, max_bytes=None):
        assert report is native_report
        raw = result._json(data)
        if len(raw) > (result.DEFAULT_MAX_SHARD_BYTES if max_bytes is None else max_bytes):
            raise codec.ReportBundleError("encoded report exceeds shard byte bound")
        return raw
    result.report_to_bytes = encode
    return result


@pytest.fixture(scope="module")
def profile():
    root = Path(__file__).resolve().parents[4]
    directory = root / "scripts" / "ops" / "legal_ir"
    name = "_report_wire_profile_unit_fixture"
    spec = importlib.util.spec_from_file_location(name, directory / "profile_report_wire.py")
    module = importlib.util.module_from_spec(spec)
    before = list(sys.path)
    try:
        sys.path.insert(0, str(directory))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    return module


@pytest.fixture
def native_report():
    long_text = "Retain exact Unicode é and escapes\n\"\\. " * 5
    shared = [None, True, 1, 1.0, -0.0, long_text, long_text]
    payload = {"z": shared, "a": shared, long_text: (long_text, 0.0)}
    view = LogicIRView("fixture", payload, "fixture-v1", "fixture", {})
    document = LegalIRDocument("fixture", "Original text.", "original text.",
        views={"fixture": view}, metadata={"original": shared, "equal_distinct": list(shared)})
    adapter = BridgeEvaluationReport("fixture", "fixture", document,
        RoundTripMetrics(cosine_similarity=0.12345678912345678, extra_losses={"negative_zero": -0.0}),
        ProofGateResult.disabled(), GraphProjectionResult(node_labels=("later", "earlier")),
        "Original decoded text.", "partial", {})
    return MultiViewLegalIRReport(("fixture",), document, {"fixture": adapter}, {})


def test_candidate_actual_bytes_inverse_preserves_all_wire_values_and_aliases(profile, native_report):
    original = codec._json(v2_data(native_report))
    data = json.loads(original)
    compact = profile.compact_dag(data, codec._FIELDS)
    candidate_bytes = codec._json(compact)
    restored = profile.expand_compact_dag(json.loads(candidate_bytes), codec._FIELDS, V2_SCHEMA)
    assert codec._json(restored) == original
    assert len(candidate_bytes) < len(original)
    assert compact["schema_version"] != codec.DAG_SCHEMA_VERSION
    assert compact["strings"] == data["strings"]
    assert {row[0] for row in compact["nodes"]} == set(range(len(profile.NODE_TYPES)))
    values = codec.report_from_bytes(codec._json(restored)).document.views["fixture"].payload
    assert list(values)[:2] == ["z", "a"]
    assert values["z"] is values["a"]
    assert type(values["z"][1]) is bool and type(values["z"][2]) is int and type(values["z"][3]) is float
    assert struct.pack("!d", values["z"][4]) == struct.pack("!d", -0.0)
    assert type(values[next(reversed(values))]) is tuple
    refs = [value for _, payload in compact["nodes"] for value in payload if type(value) is list]
    assert {ref[0] for ref in refs} == {0, 1}


def test_histogram_exact_bytes_and_fixed_savings_arithmetic(profile, native_report):
    raw = codec._json(v2_data(native_report))
    data = json.loads(raw)
    histogram = profile.wire_histogram(data, len(raw), codec._json)
    assert histogram["calculated_exact_bytes"] == len(raw)
    assert histogram["node_count"] == len(data["nodes"])
    expected_nodes = sum(len(codec._json(node)) for node in data["nodes"])
    expected_strings = len(codec._json(data["strings"]))
    assert histogram["node_json_bytes"] == expected_nodes
    assert histogram["string_table_json_bytes"] == expected_strings
    assert histogram["envelope_and_nodes_array_bytes"] == len(raw) - expected_nodes - expected_strings
    for kind, row in histogram["node_types"].items():
        selected = [node for node in data["nodes"] if node["type"] == kind]
        assert row["nodes"] == len(selected)
        assert row["json_bytes"] == sum(len(codec._json(node)) for node in selected)
    pairs = sum(len(node["items"]) for node in data["nodes"] if node["type"] == "dict")
    assert histogram["dictionary_pairs"] == pairs
    assert histogram["flattened_dictionary_pair_savings_bytes"] == pairs * 2
    assert histogram["simple_ref_array_savings_bytes"] == 4 * sum(histogram["references"].values())
    assert histogram["payload_values_retained"] is False
    with pytest.raises(ValueError, match="byte arithmetic"):
        profile.wire_histogram(data, len(raw) + 1, codec._json)


@pytest.mark.parametrize("change", ["bool_tag", "mixed_reference", "odd_dict", "field_order"])
def test_compact_schema_rejects_ambiguous_types_and_field_order(profile, native_report, change):
    data = v2_data(native_report)
    if change == "field_order":
        data["nodes"][-1]["fields"].reverse()
        with pytest.raises(ValueError, match="field order"):
            profile.compact_dag(data, codec._FIELDS)
        return
    compact = profile.compact_dag(data, codec._FIELDS)
    if change == "bool_tag":
        compact["nodes"][0][0] = False
    elif change == "mixed_reference":
        row = next(row for row in compact["nodes"] if row[0] == profile.NODE_TYPES.index("list"))
        row[1][0] = [False, 0]
    else:
        row = next(row for row in compact["nodes"] if row[0] == profile.NODE_TYPES.index("dict"))
        row[1].append("unpaired")
    with pytest.raises(ValueError):
        profile.expand_compact_dag(compact, codec._FIELDS, V2_SCHEMA)


def test_observer_success_preserves_actual_bytes_and_restores_serializer(profile, native_report, historical_codec):
    expected = historical_codec.report_to_bytes(native_report)
    original = historical_codec._json
    observation = {}
    with profile.observe_final_dag(historical_codec, observation):
        assert historical_codec.report_to_bytes(native_report) == expected
    assert historical_codec._json is original and observation["wrapper_restored"]
    assert observation["final_envelope_calls"] == 1
    assert observation["original_wire"]["bytes"] == len(expected)
    assert observation["inverse_wire"]["exact_original_bytes_equal"] is True
    assert observation["candidate_wire"]["production_format_compatible"] is False
    assert "diagnostic_error" not in observation


@pytest.mark.parametrize("diagnostic_failure", [False, True])
def test_observer_keeps_production_size_rejection_even_if_diagnostic_fails(profile, native_report, historical_codec, monkeypatch, diagnostic_failure):
    raw = historical_codec.report_to_bytes(native_report)
    original = historical_codec._json
    bound = len(raw) - 1
    monkeypatch.setattr(historical_codec, "DEFAULT_MAX_SHARD_BYTES", bound)
    if diagnostic_failure:
        def fail(*args):
            raise LookupError("diagnostic candidate failed")
        monkeypatch.setattr(profile, "compact_dag", fail)
    observation = {}
    with pytest.raises(codec.ReportBundleError, match="^encoded report exceeds shard byte bound$"):
        with profile.observe_final_dag(historical_codec, observation):
            historical_codec.report_to_bytes(native_report, max_bytes=bound)
    assert historical_codec._json is original and observation["wrapper_restored"]
    assert observation["original_wire"]["within_production_shard_bound"] is False
    assert observation["original_wire"]["bytes"] == len(raw)
    if diagnostic_failure:
        assert observation["diagnostic_error"] == {"type": "builtins.LookupError", "message": "diagnostic candidate failed"}
    else:
        assert observation["inverse_wire"]["exact_original_bytes_equal"] is True


def test_observer_restores_and_preserves_original_serializer_exception(profile, native_report, historical_codec, monkeypatch):
    original = historical_codec._json
    primary = RuntimeError("original serializer failure")
    def fail_final(value):
        if type(value) is dict and value.get("schema_version") == V2_SCHEMA:
            raise primary
        return original(value)
    monkeypatch.setattr(historical_codec, "_json", fail_final)
    observation = {}
    with pytest.raises(RuntimeError) as caught:
        with profile.observe_final_dag(historical_codec, observation):
            historical_codec.report_to_bytes(native_report)
    assert caught.value is primary
    assert historical_codec._json is fail_final and observation["wrapper_restored"]
