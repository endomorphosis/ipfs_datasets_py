"""Expanded-size optimization preserves the frozen arithmetic and wire contract."""

import gc
import hashlib
import json
import weakref

import pytest

from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
from ipfs_datasets_py.logic.bridge.types import (
    BridgeEvaluationReport, LegalIRDocument, LogicIRView, RoundTripMetrics,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_report_bundle as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import (
    TargetSnapshotError, _encode,
)


# Exact function from legal_ir_report_bundle.py before the optimization:
# source SHA256 0e86cccef95373ed19329fd27b77a7fda106bcb6e5561f17c63e66f429c17059.
# This literal is self-contained; tests never read an audit/workspace artifact.
_ORIGINAL_NODE_LIMITS_SOURCE = '''def _node_limits(node, prior, string_sizes=()):
    """Exact tagged-tree size arithmetic without expanding shared references."""
    kind = node["type"]
    pairs = kind not in {"list", "tuple"}
    items = node["items" if kind in {"dict", "list", "tuple"} else "fields"]
    if kind == "dict":
        size = len(_json({"type": "mapping", "items": []}))
    elif pairs:
        size = len(_json({"type": kind, "fields": {"type": "mapping", "items": []}}))
    else:
        size = len(_json({"type": kind, "items": []}))
    size += max(0, len(items) - 1)
    height = 0
    for entry in items:
        value = entry[1] if pairs else entry
        if type(value) is dict and "str" in value:
            child_height, child_size = 0, string_sizes[value["str"]]
        elif type(value) is dict:
            child_height, child_size = prior[value["ref"]]
        else:
            child_height, child_size = 0, len(_json(value))
        height = max(height, child_height + 1)
        if pairs:
            key = entry[0]
            key_size = string_sizes[key["str"]] if type(key) is dict else len(_json(key))
        else:
            key_size = 0
        size += child_size + (key_size + 3 if pairs else 0)
        if size > MAX_EXPANDED_GRAPH_BYTES:
            raise ReportBundleError("expanded report graph exceeds traversal byte bound")
    if height > MAX_DEPTH:
        raise ReportBundleError("report nesting limit exceeded")
    return height, size
'''


def _frozen_json(value):
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TargetSnapshotError("unsupported JSON payload") from exc


def _reference(node, prior, string_sizes=(), **unused):
    namespace = {
        "_json": _frozen_json, "ReportBundleError": codec.ReportBundleError,
        "MAX_EXPANDED_GRAPH_BYTES": codec.MAX_EXPANDED_GRAPH_BYTES,
        "MAX_DEPTH": codec.MAX_DEPTH,
    }
    exec(compile(_ORIGINAL_NODE_LIMITS_SOURCE, "frozen_report_node_limits.py", "exec"), namespace)
    return namespace["_node_limits"](node, prior, string_sizes)


def _outcome(function, *args, **kwargs):
    try:
        return "accepted", function(*args, **kwargs)
    except Exception as exc:
        cause = None if exc.__cause__ is None else (type(exc.__cause__), str(exc.__cause__))
        return "rejected", type(exc), str(exc), cause


def _candidate(mode, node, prior, string_sizes=()):
    if mode == "memo":
        return codec._node_limits(node, prior, string_sizes, scalar_size=codec._ScalarJsonSizeMemo())
    return codec._node_limits(node, prior, string_sizes)


def test_frozen_reference_digest_is_not_silently_replaced():
    assert hashlib.sha256(_ORIGINAL_NODE_LIMITS_SOURCE.encode()).hexdigest() == (
        "22829ced222f738c89e2beaca258c5087a9a1c8943a20c18c887e55ea8dd3045"
    )


_SCALARS = [None, False, True, 0, 1, -1, 2**63, 10**100, 0.0, -0.0,
            1.0, 1e-300, 1e300, "", "plain", "é汉😀", "\n\r\t\b\f\x00\\\"",
            "\ud800", "\udfff", "\ud800\udfff", "same " * 100]


@pytest.mark.parametrize("mode", ["default", "memo"])
@pytest.mark.parametrize("kind", ["dict", "list", "tuple", *codec._CLASSES, "unknown-native-kind"])
def test_all_framing_kinds_empty_and_scalar_nodes_match_frozen_reference(mode, kind):
    field = "items" if kind in {"dict", "list", "tuple"} else "fields"
    items = _SCALARS if kind in {"list", "tuple"} else [
        [f"field-{i}", value] for i, value in enumerate(_SCALARS)
    ]
    for values in ([], items):
        node = {"type": kind, field: values}
        assert _outcome(_candidate, mode, node, []) == _outcome(_reference, node, [])


@pytest.mark.parametrize("mode", ["default", "memo"])
@pytest.mark.parametrize("node, prior, strings", [
    ({"type": "list", "items": [{"ref": 0}, {"ref": 0}, {"ref": 1}]}, [(3, 111), (1, 57)], ()),
    ({"type": "dict", "items": [[{"str": 0}, {"str": 1}], ["key", {"str": 1}]]}, [], (17, 23)),
    ({"type": "tuple", "items": [{"str": 0}] * 7}, [], (41,)),
    ({"type": "list", "items": [float("nan")]}, [], ()),
    ({"type": "list", "items": [float("inf")]}, [], ()),
    ({"type": "list", "items": [float("-inf")]}, [], ()),
    ({"type": "list", "items": [{"ref": 2}]}, [(0, 2)], ()),
    ({"type": "list", "items": [{"str": 1}]}, [], (2,)),
    ({"type": "list", "items": [{}]}, [], ()),
    ({"type": "dict", "items": [["missing-value"]]}, [], ()),
    ({"type": "list"}, [], ()),
    ({"items": []}, [], ()),
    ({"type": [], "fields": []}, [], ()),
])
def test_reference_arithmetic_and_existing_low_level_errors_match(mode, node, prior, strings):
    # Structural validity is enforced by the public reader, not this arithmetic
    # helper. Compare existing errors as well as valid heights and byte totals.
    assert _outcome(_candidate, mode, node, prior, strings) == _outcome(_reference, node, prior, strings)


@pytest.mark.parametrize("mode", ["default", "memo"])
def test_repeated_string_and_child_references_charge_every_occurrence(mode, monkeypatch):
    key = "é\n\ud800"
    child = {"type": "list", "items": ["payload", -0.0]}
    child_limits = _reference(child, [])
    string_size = len(_frozen_json(key))
    node = {"type": "dict", "items": [[{"str": 0}, {"ref": 0}]] * 7}
    expected_size = len(_frozen_json({"type": "mapping", "items": []})) + 6
    expected_size += 7 * (string_size + 3 + child_limits[1])
    expected = (child_limits[0] + 1, expected_size)
    assert _reference(node, [child_limits], (string_size,)) == expected
    for bound in (expected_size - 1, expected_size, expected_size + 1):
        monkeypatch.setattr(codec, "MAX_EXPANDED_GRAPH_BYTES", bound)
        assert _outcome(_candidate, mode, node, [child_limits], (string_size,)) == (
            _outcome(_reference, node, [child_limits], (string_size,))
        )
    monkeypatch.setattr(codec, "MAX_EXPANDED_GRAPH_BYTES", expected_size)
    for depth in (expected[0] - 1, expected[0], expected[0] + 1):
        monkeypatch.setattr(codec, "MAX_DEPTH", depth)
        assert _outcome(_candidate, mode, node, [child_limits], (string_size,)) == (
            _outcome(_reference, node, [child_limits], (string_size,))
        )


def test_memo_preserves_scalar_types_signed_zero_and_encoder_failures(monkeypatch):
    calls = []
    original = codec._json

    def counted(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(codec, "_json", counted)
    memo = codec._ScalarJsonSizeMemo()
    values = _SCALARS + [float("nan"), float("inf"), float("-inf")]
    for value in values * 2:
        assert _outcome(memo, value) == _outcome(lambda item: len(_frozen_json(item)), value)
    assert memo(0.0) == 3 and memo(-0.0) == 4
    # No numeric-value dictionary key collisions: bool/int/float all bypass.
    for value in (False, 0, 0.0, -0.0, True, 1, 1.0):
        before = len(calls)
        memo(value)
        memo(value)
        assert len(calls) == before + 2


@pytest.mark.parametrize("cap, limit, first, overflow", [
    ("_MAX_SIZE_CACHE_ENTRIES", 1, "first", "second"),
    ("_MAX_SIZE_CACHE_BYTES", 6, "\ud800", "x"),
    ("_MAX_SIZE_CACHE_BYTES", 6, "aaa", "b"),
    ("_MAX_SIZE_CACHE_STRING_CHARS", 3, "yes", "long"),
])
def test_cache_caps_fall_back_without_changing_sizes(cap, limit, first, overflow, monkeypatch):
    monkeypatch.setattr(codec, cap, limit)
    calls = []
    original = codec._json

    def counted(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(codec, "_json", counted)
    memo = codec._ScalarJsonSizeMemo()
    for value in (first, overflow, first, overflow):
        assert memo(value) == len(_frozen_json(value))
    # A one-character surrogate encodes to eight JSON bytes; its cache budget
    # must use encoded size, not character count. It cannot fit the six-byte cap.
    if first == "\ud800":
        assert calls.count(first) == 2
    else:
        assert calls.count(first) == 1
        assert calls.count(overflow) == 2


def test_string_subclasses_use_ordinary_encoder_without_hashing_or_caching(monkeypatch):
    class UnhashableString(str):
        __hash__ = None

    calls = []
    original = codec._json

    def counted(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(codec, "_json", counted)
    memo = codec._ScalarJsonSizeMemo()
    for value in (UnhashableString("same"), UnhashableString("same")):
        assert memo(value) == len(_frozen_json(value))
    assert len(calls) == 2


def test_full_cache_still_rejects_expanded_graph_overflow(monkeypatch):
    monkeypatch.setattr(codec, "_MAX_SIZE_CACHE_ENTRIES", 1)
    memo = codec._ScalarJsonSizeMemo()
    memo("occupied")
    node = {"type": "list", "items": ["large repeated uncached value"] * 40}
    expected = _reference(node, [])
    monkeypatch.setattr(codec, "MAX_EXPANDED_GRAPH_BYTES", expected[1] - 1)
    assert _outcome(codec._node_limits, node, [], scalar_size=memo) == _outcome(_reference, node, [])


def _report():
    long = "é\n\\\"\x00\ud800" * 30
    shared = [None, True, 0, 0.0, -0.0, long, long, ("last", "first")]
    payload = {"left": shared, "right": shared, long: {long: shared}}
    view = LogicIRView("deontic.ir", payload, "unit-v1", "deontic.ir")
    document = LegalIRDocument("size-fixture", "The agency shall retain records.",
                              "the agency shall retain records.", views={"deontic.ir": view},
                              metadata={"shared": shared})
    bridge = BridgeEvaluationReport("deontic_norms", "deontic.ir", document,
                                    RoundTripMetrics(extra_losses={"signed_zero": -0.0}))
    return MultiViewLegalIRReport(("deontic_norms",), document, {"deontic_norms": bridge}, {})


def _wire_versions(raw):
    compact = json.loads(raw)
    tagged = codec._expand_positional(compact)
    tagged["nodes"] = list(tagged["nodes"])

    def inline(value):
        if type(value) is dict:
            if set(value) == {"str"}:
                return tagged["strings"][value["str"]]
            return {key: inline(item) for key, item in value.items()}
        if type(value) is list:
            return [inline(item) for item in value]
        return value

    legacy = {"schema_version": "legal-ir-native-report-dag-v1",
              "nodes": inline(tagged["nodes"]), "root": tagged["root"]}
    return [_frozen_json(legacy), _frozen_json(tagged), raw]


def test_native_wire_and_derived_target_bytes_match_original_accounting_in_all_versions(monkeypatch):
    report = _report()
    expected_target = _frozen_json(_encode(report.training_target()))
    optimized_raw = codec.report_to_bytes(report)
    with monkeypatch.context() as patched:
        patched.setattr(codec, "_node_limits", _reference)
        original_raw = codec.report_to_bytes(report)
    assert optimized_raw == original_raw
    for raw in _wire_versions(original_raw):
        restored = codec.report_from_bytes(raw)
        with monkeypatch.context() as patched:
            patched.setattr(codec, "_node_limits", _reference)
            baseline = codec.report_from_bytes(raw)
        assert codec.report_to_bytes(restored) == codec.report_to_bytes(baseline) == original_raw
        assert _frozen_json(_encode(restored.training_target())) == expected_target
        assert _frozen_json(_encode(baseline.training_target())) == expected_target
        assert restored.document is restored.reports["deontic_norms"].ir_document
        payload = restored.document.views["deontic.ir"].payload
        assert payload["left"] is payload["right"] is restored.document.metadata["shared"]


def test_memo_lifetime_is_one_successful_or_failed_codec_operation(monkeypatch):
    references = []
    original = codec._ScalarJsonSizeMemo

    class Tracked(original):
        def __init__(self):
            super().__init__()
            references.append(weakref.ref(self))

    monkeypatch.setattr(codec, "_ScalarJsonSizeMemo", Tracked)
    report = _report()
    raw = codec.report_to_bytes(report)
    # The encoder already contains a self-recursive visit closure. Allow its
    # ordinary cyclic-GC lifetime; this is not a claim of immediate release.
    gc.collect()
    assert len(references) == 1 and references[-1]() is None
    codec.report_from_bytes(raw)
    gc.collect()
    assert len(references) == 2 and references[-1]() is None
    monkeypatch.setattr(codec, "MAX_EXPANDED_GRAPH_BYTES", 1)
    with pytest.raises(codec.ReportBundleError, match="expanded report graph"):
        codec.report_to_bytes(report)
    with pytest.raises(codec.ReportBundleError, match="expanded report graph"):
        codec.report_from_bytes(raw)
    gc.collect()
    assert len(references) == 4
    assert all(reference() is None for reference in references)
