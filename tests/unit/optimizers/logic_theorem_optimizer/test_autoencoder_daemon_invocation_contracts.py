"""Native parser/codec contract tests; no daemon, bridge, or model inference."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import struct

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as contracts
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
    read_checkpoint_input_metadata, serialize_checkpoint,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import encode_manifest


@pytest.fixture
def sealed_environment(monkeypatch):
    environment = contracts.execution_environment()
    for key in tuple(os.environ):
        if key not in environment:
            monkeypatch.delenv(key)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    return environment


@pytest.fixture
def native_argv(tmp_path):
    # Descriptor-only parsing fixture; it is not a production input capsule.
    snapshot = tmp_path / "input.json"
    snapshot.write_bytes(b"{}")
    descriptor = contracts.describe(snapshot)
    return ["--run-id", "owned-contract-test", "--loop-role", "autoencoder", "--max-cycles", "1",
        "--duration-seconds", "60", "--autoencoder-device", "python", "--autoencoder-canonical-warm-start", "off",
        "--validation-canary-count", "0", "--bridge-evaluate-provers", "false", "--autoencoder-bridge-workers", "1",
        "--leanstral-rule-gap-wait-seconds", "0", "--leanstral-rule-gap-projection-enabled", "false",
        "--leanstral-direct-guidance-projection-enabled", "false", "--leanstral-direct-guidance-train-autoencoder", "false",
        "--daemon-hammer-guidance-enabled", "false", "--daemon-hammer-guidance-train-autoencoder", "false",
        "--codex-exec-mode", "packet_only", "--codex-commit-mode", "none",
        "--autoencoder-corpus-input", descriptor["path"], "--autoencoder-corpus-input-sha256", descriptor["sha256"],
        "--autoencoder-corpus-input-bytes", str(descriptor["bytes"])]


def replace_argument(argv, flag, value):
    result = list(argv)
    if flag in result:
        result[result.index(flag) + 1] = value
    else:
        result.extend([flag, value])
    return result


def test_effective_config_uses_native_parser_and_retains_default_async_policy(native_argv, sealed_environment):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import build_uscode_modal_daemon_arg_parser
    direct = vars(build_uscode_modal_daemon_arg_parser().parse_args(native_argv))
    actual = contracts.effective_configuration(native_argv)
    assert actual == {key:str(value) if isinstance(value,Path) else value for key,value in direct.items()}
    assert actual["snapshot_evaluation_enabled"] is True
    assert actual["autoencoder_bridge_workers"] == 1
    assert actual["bridge_evaluate_provers"] is False
    assert "--snapshot-evaluation-enabled" not in native_argv


def test_native_projection_policy_is_not_silently_replaced(native_argv, sealed_environment):
    argv = replace_argument(native_argv,"--generalizable-projection-max-update-families","4")
    argv = replace_argument(argv,"--learning-rate","0.125")
    argv = replace_argument(argv,"--autoencoder-todo-supervisor-mode","every_cycle")
    actual = contracts.effective_configuration(argv)
    assert actual["generalizable_projection_max_update_families"] == 4
    assert actual["learning_rate"] == 0.125
    assert actual["autoencoder_todo_supervisor_mode"] == "every_cycle"


@pytest.mark.parametrize("flag,value", [
    ("--run-id","../escape"), ("--max-cycles","2"), ("--bridge-evaluate-provers","true"),
    ("--autoencoder-canonical-warm-start","auto"), ("--warm-start-state","/tmp/unbound-state"),
    ("--leanstral-rule-gap-wait-seconds","1"), ("--leanstral-rule-gap-projection-enabled","true"),
    ("--leanstral-direct-guidance-train-autoencoder","true"), ("--daemon-hammer-guidance-enabled","true"),
    ("--autoencoder-bridge-workers","2"),
])
def test_native_config_rejects_unbound_effects_or_policy_mismatch(native_argv,sealed_environment,flag,value):
    with pytest.raises(contracts.DaemonInvocationError):
        contracts.effective_configuration(replace_argument(native_argv,flag,value))


def test_verified_local_input_triplet_required(native_argv,sealed_environment):
    argv=list(native_argv)
    for flag in ("--autoencoder-corpus-input","--autoencoder-corpus-input-sha256","--autoencoder-corpus-input-bytes"):
        index=argv.index(flag);del argv[index:index+2]
    with pytest.raises(contracts.DaemonInvocationError,match="local corpus"):
        contracts.effective_configuration(argv)


def test_child_environment_excludes_credentials_and_preserves_explicit_scheduler(monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY","must-not-propagate")
    monkeypatch.setenv("OPENAI_API_KEY","must-not-propagate")
    monkeypatch.setenv("PYTHONPATH","/tmp/untrusted-package")
    monkeypatch.setenv("IPFS_DATASETS_RESOURCE_SCHEDULER_PATH","/tmp/explicit-shared-ledger.json")
    monkeypatch.setenv("IPFS_DATASETS_RESOURCE_MEMORY_MB","4096")
    env=contracts.execution_environment()
    assert "AWS_SECRET_ACCESS_KEY" not in env and "OPENAI_API_KEY" not in env
    assert env["PYTHONPATH"]==str(contracts.ROOT)
    assert env["IPFS_DATASETS_RESOURCE_SCHEDULER_PATH"]=="/tmp/explicit-shared-ledger.json"
    assert env["IPFS_DATASETS_RESOURCE_MEMORY_MB"]=="4096"
    assert env["CUDA_VISIBLE_DEVICES"]==""
    assert env["HF_HUB_OFFLINE"]==env["TRANSFORMERS_OFFLINE"]=="1"


@pytest.mark.parametrize("override", [
    {"HOME":"/tmp/other"},{"PYTHONPATH":"/tmp/other"},{"CUDA_VISIBLE_DEVICES":"0"},
    {"OMP_NUM_THREADS":"0"},{"OMP_NUM_THREADS":"33"},{"OMP_NUM_THREADS":True},
    {"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE":"2"},
])
def test_environment_override_allowlist_and_bounds(override):
    with pytest.raises(contracts.DaemonInvocationError):contracts.execution_environment(override)


@pytest.fixture
def full_states(tmp_path):
    state=ModalAutoencoderTrainingState(
        feature_embedding_weights={"shall":[-0.0,0.125,-1.75]},
        family_logits={"sample":{"deontic":0.75}},applied_todo_ids=["already-applied"])
    legacy=tmp_path/"base.json";legacy.write_bytes(contracts.canonical(state.to_dict()))
    metadata={"corpus_input_identity":{"sha256":"b"*64,"bytes":17}}
    compact=tmp_path/"candidate.bin";compact.write_bytes(serialize_checkpoint(state,
        metric_lineage=contracts.METRIC_LINEAGE,metadata=metadata))
    return state,contracts.describe(legacy),contracts.describe(compact),metadata


def test_legacy_and_compact_full_state_parity_uses_native_loader(full_states):
    state,legacy,compact,metadata=full_states
    a=contracts.load_full_checkpoint(legacy)
    b=contracts.load_full_checkpoint(compact,compact_only=True)
    assert contracts.canonical(a.state.to_dict())==contracts.canonical(b.state.to_dict())==contracts.canonical(state.to_dict())
    assert a.state.state_identity(metric_lineage=contracts.METRIC_LINEAGE)==b.state.state_identity(metric_lineage=contracts.METRIC_LINEAGE)
    assert a.state.component_digests==b.state.component_digests
    assert struct.pack("<d",b.state.feature_embedding_weights["shall"][0])==struct.pack("<d",-0.0)
    assert read_checkpoint_input_metadata(compact["path"])==(metadata,)
    assert read_checkpoint_input_metadata(legacy["path"])==({},)
    assert contracts.describe(legacy["path"])==legacy and contracts.describe(compact["path"])==compact


def test_candidate_requires_full_float64_compact(full_states,tmp_path):
    state,legacy,_,_=full_states
    with pytest.raises(contracts.DaemonInvocationError,match="full compact"):
        contracts.load_full_checkpoint(legacy,compact_only=True)
    quantized=tmp_path/"float32.bin";quantized.write_bytes(serialize_checkpoint(state,float_precision="float32"))
    with pytest.raises(contracts.DaemonInvocationError,match="float64"):
        contracts.load_full_checkpoint(contracts.describe(quantized),compact_only=True)


def test_real_sparse_manifest_cannot_load_as_an_empty_full_state(full_states,tmp_path):
    state,legacy,compact,_=full_states
    no_path=lambda ref:{key:ref[key] for key in ("sha256","bytes")}
    raw=encode_manifest(parent=no_path(legacy),base_version_id="registered-base",patches=[],
        materialized_checkpoint=no_path(compact),state_identity=state.state_identity(),result_revision=0)
    sparse=tmp_path/"sparse.json";sparse.write_bytes(raw)
    with pytest.raises(contracts.DaemonInvocationError,match="sparse manifests"):
        contracts.load_full_checkpoint(contracts.describe(sparse))


@pytest.mark.parametrize("raw",[b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}',b'\xff',b'{'])
def test_strict_json_rejects_duplicates_nonfinite_and_invalid_bytes(raw):
    with pytest.raises(contracts.DaemonInvocationError):contracts.parse_json(raw)


@pytest.mark.parametrize("change",[{"bytes":True},{"bytes":0},{"bytes":5},{"sha256":"A"*64},{"extra":1}])
def test_bounded_descriptor_has_closed_fields_and_exact_integer_size(tmp_path,change):
    path=tmp_path/"value";path.write_bytes(b"data")
    descriptor=contracts.describe(path)
    with pytest.raises(contracts.DaemonInvocationError):
        contracts.reference({**descriptor,**change},4,with_path=True)


def test_descriptor_rejects_same_length_content_tamper_and_alias(tmp_path):
    path=tmp_path/"value";path.write_bytes(b"data")
    descriptor=contracts.describe(path)
    path.write_bytes(b"evil")
    with pytest.raises(contracts.DaemonInvocationError):contracts.verify(descriptor)
    alias=tmp_path/"alias";alias.symlink_to(path)
    with pytest.raises(contracts.DaemonInvocationError):contracts.describe(alias)


def test_new_json_artifact_cannot_overwrite_and_is_hash_bound(tmp_path):
    path=tmp_path/"new.json"
    ref=contracts.write_new(path,{"sample":"exact","value":-0.0})
    assert contracts.verify(ref)==contracts.canonical({"sample":"exact","value":-0.0})
    assert hashlib.sha256(path.read_bytes()).hexdigest()==ref["sha256"]
    with pytest.raises(FileExistsError):contracts.write_new(path,{"replacement":True})


@pytest.fixture
def sealed_request(native_argv,sealed_environment,full_states,tmp_path):
    _,base,_,_=full_states
    parsed=contracts.effective_configuration(native_argv)
    snapshot=contracts.describe(parsed["autoencoder_corpus_input"])
    return {"schema":contracts.REQUEST_SCHEMA,"run_id":"owned-contract-test","variant_id":"native-english",
        "base_version_id":"registered-base","base_artifact":base,"base_identity":{},
        "input_snapshot":snapshot,"variant_manifest_sha256":"c"*64,"daemon_argv":native_argv,
        "effective_arguments":parsed,"environment":sealed_environment,"producer_identity":{},
        "output_directory":str(tmp_path),"resource_policy":{}}


def test_closed_request_roundtrip(sealed_request):
    assert contracts.validate_request(contracts.parse_json(contracts.canonical(sealed_request)))==sealed_request


def test_v1_wire_shape_does_not_gain_an_opt_out_field(sealed_request):
    original = contracts.canonical(sealed_request)
    assert sealed_request["schema"] == "autoencoder-daemon-invocation-request-v1"
    assert set(sealed_request) == {
        "schema", "run_id", "variant_id", "base_version_id", "base_artifact",
        "base_identity", "input_snapshot", "variant_manifest_sha256", "daemon_argv",
        "effective_arguments", "environment", "producer_identity", "output_directory",
        "resource_policy",
    }
    assert contracts.canonical(contracts.validate_request(contracts.parse_json(original))) == original


def test_v2_seals_shadow_policy_and_preserves_all_other_request_values(sealed_request):
    request = {**sealed_request, "schema": contracts.SHADOW_REQUEST_SCHEMA, "sparse_shadow": True}
    encoded = contracts.canonical(request)
    assert request["schema"] == "autoencoder-daemon-invocation-request-v2"
    restored = contracts.validate_request(contracts.parse_json(encoded))
    assert contracts.canonical(restored) == encoded
    assert {key: value for key, value in restored.items() if key not in ("schema", "sparse_shadow")} == {
        key: value for key, value in sealed_request.items() if key != "schema"
    }


@pytest.mark.parametrize("shadow", [False, True])
def test_v3_seals_explicit_feature_weights_without_changing_daemon_configuration(sealed_request, shadow):
    # Descriptor-shape fixture; worker validation still must decode its IPC.
    descriptor = dict(sealed_request["base_artifact"])
    request = {**sealed_request, "schema": contracts.WEIGHT_REQUEST_SCHEMA,
               "sparse_shadow": shadow, "arrow_feature_weights": descriptor}
    raw = contracts.canonical(request)
    assert contracts.canonical(contracts.validate_request(contracts.parse_json(raw))) == raw
    assert request["effective_arguments"] == sealed_request["effective_arguments"]
    assert set(request) == contracts.REQUEST_FIELDS | {"sparse_shadow", "arrow_feature_weights"}


@pytest.mark.parametrize("mutation", ["missing_weights", "missing_shadow", "null_weights", "extra", "size_bool",
    "size_float", "oversize", "bad_hash", "shadow_int", "shadow_null", "v1_weights", "v2_weights"])
def test_v3_rejects_incomplete_or_nonexact_feature_weight_policy(sealed_request, mutation):
    request = {**sealed_request, "schema": contracts.WEIGHT_REQUEST_SCHEMA,
               "sparse_shadow": False, "arrow_feature_weights": dict(sealed_request["base_artifact"])}
    if mutation == "missing_weights":
        del request["arrow_feature_weights"]
    elif mutation == "missing_shadow":
        del request["sparse_shadow"]
    elif mutation == "null_weights":
        request["arrow_feature_weights"] = None
    elif mutation == "extra":
        request["extra"] = True
    elif mutation in {"size_bool", "size_float", "oversize"}:
        request["arrow_feature_weights"]["bytes"] = {"size_bool": True, "size_float": 1.0,
            "oversize": contracts.MAX_ARROW_FEATURE_WEIGHT_BYTES + 1}[mutation]
    elif mutation == "bad_hash":
        request["arrow_feature_weights"]["sha256"] = "bad"
    elif mutation.startswith("shadow_"):
        request["sparse_shadow"] = 1 if mutation == "shadow_int" else None
    else:
        request["schema"] = contracts.REQUEST_SCHEMA if mutation == "v1_weights" else contracts.SHADOW_REQUEST_SCHEMA
        if mutation == "v1_weights":
            del request["sparse_shadow"]
        else:
            request["sparse_shadow"] = True
    with pytest.raises(contracts.DaemonInvocationError):
        contracts.validate_request(request)


@pytest.mark.parametrize("value", [False, None, 0, 1, "true", [], {}])
def test_v2_requires_exact_true_not_truthiness(sealed_request, value):
    request = {**sealed_request, "schema": contracts.SHADOW_REQUEST_SCHEMA, "sparse_shadow": value}
    with pytest.raises(contracts.DaemonInvocationError, match="closed daemon request"):
        contracts.validate_request(request)


@pytest.mark.parametrize("value", [False, True, None])
def test_v1_rejects_shadow_field_even_when_false(sealed_request, value):
    with pytest.raises(contracts.DaemonInvocationError, match="closed daemon request"):
        contracts.validate_request({**sealed_request, "sparse_shadow": value})


@pytest.mark.parametrize("change", [
    {"schema": contracts.SHADOW_REQUEST_SCHEMA},
    {"schema": contracts.SHADOW_REQUEST_SCHEMA, "sparse_shadow": True, "extra": 1},
    {"schema": []}, {"schema": {}}, {"schema": None}, {"schema": True},
])
def test_version_dispatch_rejects_missing_policy_unknown_fields_and_non_string_schemas(sealed_request, change):
    with pytest.raises(contracts.DaemonInvocationError, match="closed daemon request"):
        contracts.validate_request({**sealed_request, **change})


@pytest.mark.parametrize("key,value",[("extra",1),("schema","other"),("run_id","../other"),
    ("variant_id","invalid variant"),("variant_manifest_sha256","c"*63),
    ("base_version_id",""),("effective_arguments",[]),("environment",[]),("resource_policy",[])])
def test_closed_request_and_invalid_variant_fields(sealed_request,key,value):
    changed=deepcopy(sealed_request);changed[key]=value
    with pytest.raises(contracts.DaemonInvocationError):contracts.validate_request(changed)


def test_request_missing_field_fails(sealed_request):
    del sealed_request["producer_identity"]
    with pytest.raises(contracts.DaemonInvocationError):contracts.validate_request(sealed_request)


def test_launch_binds_run_settings_base_and_immediate_attempt_directory(sealed_request,tmp_path):
    request=sealed_request
    attempt=tmp_path/"attempt";attempt.mkdir()
    request_ref=contracts.write_new(tmp_path/"request.json",request)
    launch={"schema":contracts.LAUNCH_SCHEMA,"request":request_ref,"lease":{"run_id":request["run_id"]},
        "attempt_directory":str(attempt),"daemon_argv":request["daemon_argv"],
        "environment":request["environment"],"base_artifact":request["base_artifact"],
        "resource_reservation_id":"reservation-test"}
    assert contracts.validate_launch(launch,request)==launch
    for key,value in [("lease",{"run_id":"other"}),("daemon_argv",[]),("environment",{}),
                      ("base_artifact",{}),("attempt_directory",str(tmp_path)),("extra",True)]:
        changed=deepcopy(launch);changed[key]=value
        with pytest.raises(contracts.DaemonInvocationError):contracts.validate_launch(changed,request)
