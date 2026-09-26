"""Pure codec tests; no model, registry, preparation, resource or execution work."""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_training_request as codec


def _ref(number=1, size=64):
    return {"sha256": f"{number:064x}", "bytes": size}


def _batch(ordinal=3):
    return {"plan_ordinal": ordinal, "batch_id": f"sha256:{ordinal + 10:064x}",
        "run_id": f"run-{ordinal}", "job_id": f"job-{ordinal}",
        "job_spec_artifact": _ref(ordinal + 20, 1024), "job_spec_sha256": f"{ordinal + 30:064x}",
        "base_version_id": "base-v1", "output_directory": f"/owner/workers/batch-{ordinal}",
        "target_snapshot_id": "", "target_snapshot_artifact": None, "arrow_feature_weights_artifact": None,
        "training_config_sha256": "4" * 64, "autoencoder_config_sha256": "5" * 64}


def _request():
    return {"schema_version": codec.SCHEMA,
        "owner": {"database_path": "/owner/control.db", "artifact_root": "/owner/cas"},
        "plan_artifact": _ref(2, 4096), "worker_id": "campaign-worker", "output_root": "/owner/prepared",
        "variant_id": "en-uscode", "variant_manifest_sha256": "6" * 64,
        "source_campaign_binding": {name: _ref(index + 100) for index, name in enumerate(sorted(codec.ROOT_NAMES))},
        "parent_policy": "common_fixed_parent", "batches": [_batch(3), _batch(8)],
        "resource_policy": {"ledger_path": "/owner/resources.json", "roots": ["/owner", "/shared"],
                            "storage_bytes": 50_000_000, "memory_mb": 1536, "cpu_slots": 1},
        "execution_policy": {"max_workers": 2, "lease_seconds": 300.0, "poll_seconds": 0.25,
            "timeout_seconds": 900.0, "defer_target_hydration_gc": False, "reduce_native_targets": False,
            "sparse_checkpoint_policy": {"max_depth": 8, "max_patch_fraction": 0.5}},
        **{name: False for name in codec.FALSE_FIELDS}}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def _set(value, path, replacement):
    parent = _at(value, path[:-1])
    parent[path[-1]] = replacement


def test_canonical_roundtrip_preserves_values_and_returns_detached_objects():
    value = _request()
    previous = deepcopy(value)
    encoded = codec.encode_campaign_training_request(value)
    assert encoded == _raw(value)
    assert not encoded.endswith(b"\n")
    assert value == previous
    decoded = codec.decode_campaign_training_request(encoded)
    assert decoded == previous and decoded is not value
    decoded["batches"][0]["run_id"] = "changed"
    assert value == previous
    assert codec.encode_campaign_training_request(value) == encoded
    assert hashlib.sha256(encoded).digest() == hashlib.sha256(_raw(previous)).digest()


def test_nonzero_gapped_selection_optional_artifacts_and_explicit_parents():
    value = _request()
    value["batches"][0].update(target_snapshot_id="sha256:" + "a" * 64,
                               target_snapshot_artifact=_ref(400), arrow_feature_weights_artifact=_ref(500))
    value["batches"][1]["base_version_id"] = "different-registered-base"
    value["parent_policy"] = "explicit_registered_parents"
    value["execution_policy"].update(max_workers=4, defer_target_hydration_gc=True, reduce_native_targets=True)
    assert codec.decode_campaign_training_request(codec.encode_campaign_training_request(value)) == value
    value["batches"] = value["batches"][:1]
    assert codec.decode_campaign_training_request(codec.encode_campaign_training_request(value)) == value


def test_codec_performs_no_path_or_resource_operations(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("pure codec must not access filesystem or admission")
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        for name in ("open", "stat", "lstat", "exists", "resolve", "mkdir"):
            patch.setattr(Path, name, forbidden)
        value = _request()
        assert codec.decode_campaign_training_request(codec.encode_campaign_training_request(value)) == value


@pytest.mark.parametrize("path", [(), ("owner",), ("plan_artifact",), ("source_campaign_binding",),
    ("source_campaign_binding", "source_inventory"), ("batches", 0), ("batches", 0, "job_spec_artifact"),
    ("resource_policy",), ("execution_policy",), ("execution_policy", "sparse_checkpoint_policy")])
@pytest.mark.parametrize("kind", ["unknown", "missing"])
def test_every_object_has_closed_fields(path, kind):
    value = _request()
    target = _at(value, path)
    if kind == "unknown":
        target["unexpected"] = None
    else:
        del target[next(iter(target))]
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)


@pytest.mark.parametrize("flag", sorted(codec.FALSE_FIELDS))
@pytest.mark.parametrize("replacement", [True, 0])
def test_preparation_cannot_claim_authority_or_execution(flag, replacement):
    value = _request()
    value[flag] = replacement
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)


@pytest.mark.parametrize("path,replacement", [
    (("schema_version",), "autoencoder-campaign-training-request-v2"),
    (("worker_id",), "worker/remote"), (("worker_id",), "x" * 129),
    (("variant_id",), ""), (("variant_manifest_sha256",), "A" * 64),
    (("parent_policy",), "sequential_previous_candidate"),
    (("batches", 0, "batch_id"), "sha256:" + "a" * 63),
    (("batches", 0, "job_spec_sha256"), "sha256:" + "a" * 64),
    (("batches", 0, "plan_ordinal"), True), (("batches", 0, "plan_ordinal"), -1),
    (("batches", 0, "plan_ordinal"), 128), (("batches", 0, "plan_ordinal"), 3.0),
    (("batches", 0, "job_spec_artifact", "bytes"), True),
    (("batches", 0, "job_spec_artifact", "bytes"), 64.0),
    (("batches", 0, "job_spec_artifact", "bytes"), 0),
    (("batches", 0, "job_spec_artifact", "bytes"), 64 * 1024 * 1024 + 1),
    (("plan_artifact", "bytes"), 4 * 1024 * 1024 + 1),
    (("source_campaign_binding", "source_inventory", "bytes"), 64 * 1024 * 1024 + 1),
    (("batches", 0, "target_snapshot_id"), "sha256:" + "a" * 64),
    (("batches", 0, "target_snapshot_artifact"), _ref(400)),
    (("batches", 0, "arrow_feature_weights_artifact"), {"sha256": "a" * 64, "bytes": 1, "path": "/extra"}),
])
def test_identifiers_and_descriptors_reject_drift(path, replacement):
    value = _request()
    _set(value, path, replacement)
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)


@pytest.mark.parametrize("path", [("owner", "database_path"), ("owner", "artifact_root"), ("output_root",),
    ("batches", 0, "output_directory"), ("resource_policy", "ledger_path"), ("resource_policy", "roots", 0)])
@pytest.mark.parametrize("replacement", ["relative/path", "/owner/../outside", "//owner/cas", "/owner//cas", "/owner/cas/", "/owner/./cas", "/owner/\x00cas"])
def test_paths_are_lexically_absolute_normalized_and_bounded(path, replacement):
    value = _request()
    _set(value, path, replacement)
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)


@pytest.mark.parametrize("key", ["plan_ordinal", "run_id", "job_id", "batch_id", "output_directory"])
def test_duplicate_selections_are_rejected(key):
    value = _request()
    value["batches"][1][key] = value["batches"][0][key]
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)


@pytest.mark.parametrize("replacement", ["/owner/prepared", "/owner/prepared/job", "/owner", "/owner/workers/batch-3/nested"])
def test_outputs_cannot_overlap_controls_or_other_jobs(replacement):
    value = _request()
    value["batches"][1]["output_directory"] = replacement
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)


def test_selection_order_and_fixed_parent_policy_are_enforced():
    value = _request()
    value["batches"].reverse()
    with pytest.raises(codec.CampaignTrainingRequestError, match="order"):
        codec.encode_campaign_training_request(value)
    value = _request()
    value["batches"][1]["base_version_id"] = "another-base"
    with pytest.raises(codec.CampaignTrainingRequestError, match="fixed-parent"):
        codec.encode_campaign_training_request(value)


@pytest.mark.parametrize("path,replacement", [
    (("resource_policy", "roots"), []), (("resource_policy", "roots"), ["/owner", "/owner"]),
    (("resource_policy", "roots"), ["/owner", "/owner/subdir"]),
    (("resource_policy", "roots"), ["/owner/subdir", "/owner"]),
    (("resource_policy", "storage_bytes"), 0), (("resource_policy", "storage_bytes"), 50_000_000_001),
    (("resource_policy", "memory_mb"), True), (("resource_policy", "memory_mb"), 2**31),
    (("resource_policy", "cpu_slots"), 0), (("resource_policy", "cpu_slots"), 33),
    (("execution_policy", "max_workers"), 0), (("execution_policy", "max_workers"), 5),
    (("execution_policy", "max_workers"), True), (("execution_policy", "lease_seconds"), 0),
    (("execution_policy", "lease_seconds"), 86401), (("execution_policy", "timeout_seconds"), True),
    (("execution_policy", "timeout_seconds"), 86401), (("execution_policy", "poll_seconds"), 30.1),
    (("execution_policy", "defer_target_hydration_gc"), 1), (("execution_policy", "reduce_native_targets"), None),
    (("execution_policy", "sparse_checkpoint_policy", "max_depth"), 0),
    (("execution_policy", "sparse_checkpoint_policy", "max_depth"), 9),
    (("execution_policy", "sparse_checkpoint_policy", "max_patch_fraction"), False),
    (("execution_policy", "sparse_checkpoint_policy", "max_patch_fraction"), 0),
    (("execution_policy", "sparse_checkpoint_policy", "max_patch_fraction"), 1.01),
])
def test_resource_and_execution_policy_bounds(path, replacement):
    value = _request()
    _set(value, path, replacement)
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)


def test_policy_cross_bounds_and_numeric_identity_remain_exact():
    value = _request()
    value["execution_policy"].update(lease_seconds=0.5, poll_seconds=0.126)
    with pytest.raises(codec.CampaignTrainingRequestError, match="poll"):
        codec.encode_campaign_training_request(value)
    value["execution_policy"]["poll_seconds"] = 0.125
    codec.encode_campaign_training_request(value)
    value = _request()
    integer = codec.encode_campaign_training_request(value)
    value["execution_policy"]["lease_seconds"] = 300
    assert integer != codec.encode_campaign_training_request(value)


def test_batch_root_aggregate_and_encoded_byte_boundaries(monkeypatch):
    value = _request()
    value["batches"] = [_batch(index) for index in range(codec.MAX_BATCHES)]
    value["resource_policy"]["roots"] = [f"/root-{index}" for index in range(64)]
    codec.encode_campaign_training_request(value)
    value["batches"].append(_batch(64))
    with pytest.raises(codec.CampaignTrainingRequestError, match="batch"):
        codec.encode_campaign_training_request(value)
    value["batches"].pop()
    value["resource_policy"]["roots"].append("/root-64")
    with pytest.raises(codec.CampaignTrainingRequestError, match="roots"):
        codec.encode_campaign_training_request(value)
    value = _request()
    for row in value["batches"]:
        row["job_spec_artifact"]["bytes"] = codec.MAX_TOTAL_JOB_BYTES // 2
    raw = codec.encode_campaign_training_request(value)
    value["batches"][1]["job_spec_artifact"]["bytes"] += 1
    with pytest.raises(codec.CampaignTrainingRequestError, match="aggregate"):
        codec.encode_campaign_training_request(value)
    value["batches"][1]["job_spec_artifact"]["bytes"] -= 1
    monkeypatch.setattr(codec, "MAX_REQUEST_BYTES", len(raw))
    assert codec.encode_campaign_training_request(value) == raw
    assert codec.decode_campaign_training_request(raw) == value
    monkeypatch.setattr(codec, "MAX_REQUEST_BYTES", len(raw) - 1)
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.decode_campaign_training_request(raw)


def test_path_byte_bound_is_utf8_not_character_count():
    value = _request()
    value["output_root"] = "/" + "a" * (codec.MAX_PATH_BYTES - 1)
    codec.encode_campaign_training_request(value)
    value["output_root"] += "a"
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)
    value["output_root"] = "/" + "é" * (codec.MAX_PATH_BYTES // 2)
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)


@pytest.mark.parametrize("replacement", [(), set(), b"bytes", float("nan"), float("inf"), float("-inf"), 2**63, -(2**63), "\ud800"])
def test_nonordinary_or_unbounded_json_rejected(replacement):
    value = _request()
    value["variant_id"] = replacement
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)


def test_custom_containers_scalar_subclasses_keys_and_cycles_rejected():
    class CustomDict(dict):
        pass
    class CustomList(list):
        pass
    class CustomInt(int):
        pass
    class CustomString(str):
        pass
    for value in (CustomDict(_request()), {**_request(), "batches": CustomList(_request()["batches"])},
                  {**_request(), "worker_id": CustomString("worker")},
                  {**_request(), CustomString("extra"): None}):
        with pytest.raises(codec.CampaignTrainingRequestError):
            codec.encode_campaign_training_request(value)
    value = _request()
    value["resource_policy"]["cpu_slots"] = CustomInt(1)
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.encode_campaign_training_request(value)
    value = _request()
    value["batches"].append(value)
    with pytest.raises(codec.CampaignTrainingRequestError, match="structural"):
        codec.encode_campaign_training_request(value)


def test_structural_depth_and_node_bounds_before_encoding(monkeypatch):
    value = _request()
    nested = []
    for _ in range(codec.MAX_JSON_DEPTH + 1):
        nested = [nested]
    value["worker_id"] = nested
    with pytest.raises(codec.CampaignTrainingRequestError, match="structural"):
        codec.encode_campaign_training_request(value)
    monkeypatch.setattr(codec, "MAX_JSON_NODES", 8)
    with pytest.raises(codec.CampaignTrainingRequestError, match="structural"):
        codec.encode_campaign_training_request(_request())


@pytest.mark.parametrize("kind", ["whitespace", "newline", "duplicate_root", "duplicate_nested", "nonfinite", "exponent_overflow", "integer_overflow", "long_integer", "long_float", "malformed_utf8", "deep"])
def test_decoder_rejects_noncanonical_duplicate_and_malformed_json(kind):
    raw = codec.encode_campaign_training_request(_request())
    if kind == "whitespace":
        raw = b" " + raw
    elif kind == "newline":
        raw += b"\n"
    elif kind == "duplicate_root":
        raw = b'{"worker_id":"other",' + raw[1:]
    elif kind == "duplicate_nested":
        raw = raw.replace(b'"owner":{', b'"owner":{"artifact_root":"/other",', 1)
    elif kind == "nonfinite":
        raw = raw.replace(b'"lease_seconds":300.0', b'"lease_seconds":NaN', 1)
    elif kind == "exponent_overflow":
        raw = raw.replace(b'"lease_seconds":300.0', b'"lease_seconds":1e9999', 1)
    elif kind == "integer_overflow":
        raw = raw.replace(b'"cpu_slots":1', b'"cpu_slots":9223372036854775808', 1)
    elif kind == "long_integer":
        raw = raw.replace(b'"cpu_slots":1', b'"cpu_slots":' + b"9" * 5000, 1)
    elif kind == "long_float":
        raw = raw.replace(b'"lease_seconds":300.0', b'"lease_seconds":0.' + b"1" * 5000, 1)
    elif kind == "malformed_utf8":
        raw = b'"\xff"'
    else:
        raw = b"[" * 2000 + b"null" + b"]" * 2000
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.decode_campaign_training_request(raw)


@pytest.mark.parametrize("raw", [b"", "{}", bytearray(b"{}"), memoryview(b"{}"), b"null", b"[]", b"{}"])
def test_decoder_requires_nonempty_bytes_of_exact_schema(raw):
    with pytest.raises(codec.CampaignTrainingRequestError):
        codec.decode_campaign_training_request(raw)
