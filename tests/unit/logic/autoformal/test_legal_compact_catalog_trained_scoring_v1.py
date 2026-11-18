"""Two retained-checkpoint forwards under an explicitly new catalog policy.

The catalog and supplied prefixes are frozen fictional engineering controls.
Exactly two actual trained GRU forwards and two independent manual recurrent
computations are enrolled here. No training, optimizer, encoder or holdout.
The unchanged trained-runtime cohort separately owns its existing eleven GRUs.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import stat

import pytest
import torch
from torch.nn import functional as functional

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_trained_scoring_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as trained
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_tokens_v1 as tokens
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as old_tokens
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

FIXTURE_SHA = "1c4b7c37eba6870c2a746cb3e3191013a1d25906cb75427d4f7be0ca6583dab7"
CHECKPOINT_SHA = "0ba5bb1d941c83e4695b6ec7e971c042d6e0419f1dc8c24bfb5cc509b0c6bac0"
# Frozen before admission: reduction ordering may differ from fused native GRU.
REFERENCE_RTOL, REFERENCE_ATOL = 1e-5, 2e-6
LEXICAL = re.compile(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]')


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(value): return hashlib.sha256(value).hexdigest()
def digest(value): return sha(wire(value))


def snapshot(path):
    assert path.is_absolute() and path.resolve(strict=True) == path
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 16 * 1024**2
    raw = path.read_bytes()
    after = path.lstat()
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    assert identity(before) == identity(after) and len(raw) == before.st_size
    return raw


def identity(namespace, value):
    return {"interface": "LogicIdentityNamespaces@1", "namespace": namespace,
            "schema_version": "logic-identity-namespaces/v1", "value": value, "version": "1.0.0"}


def context():
    obj = {"arguments": [], "kind": "atomic", "name": "Object", "schema_version": "syntax-logic-sort/v1"}
    boolean = {"arguments": [], "kind": "bool", "name": "Bool", "schema_version": "syntax-logic-sort/v1"}
    symbols = [{"schema_version": "syntax-symbol-declaration/v1", "name": name,
        "kind": "predicate", "metadata": {}, "domain": [deepcopy(obj) for _ in range(arity)],
        "range": deepcopy(boolean)} for name, arity in (("Alpha", 1), ("Beta", 1), ("Gamma", 2))]
    return {"schema": "legal-relational-compact-catalog-context/v1",
        "selection_policy": "referenced_predicates_in_catalog_order/v1", "catalog": {
        "schema": "legal-relational-compact-context/v1", "signature": {
            "schema_version": "syntax-logic-signature/v1", "interface": "LogicSignature@1",
            "family": identity("family", "tdfol"), "profile": identity("profile", "tdfol_default"),
            "features": [], "metadata": {}, "sorts": [boolean, obj], "symbols": symbols},
        "argument_roles": [{"symbol": "Gamma", "roles": ["sender", "receiver"]},
                           {"symbol": "Alpha", "roles": ["subject"]},
                           {"symbol": "Beta", "roles": ["observer"]}]}}


def content():
    return {"schema": "legal-relational-compact-content/v1", "tree": ["forall", 0,
        ["exists", 1, ["and", ["predicate", 2, [["variable", 1], ["variable", 0]]],
                     ["extension", "P", ["predicate", 0, [["variable", 0]]]]]]]}


def prefixes(codec):
    raw = wire(content()).decode()
    lexical = LEXICAL.findall(raw)
    assert "".join(lexical) == raw
    table = {token: index for index, token in enumerate(codec["vocabulary"])}
    # Before the first constructor beneath two binders: never selected from scores.
    nontrivial = [1, *(table[token] for token in lexical[:lexical.index('"and"')])]
    full = [1, *(table[token] for token in lexical), 2]
    return {"nontrivial": nontrivial, "subset_eos": full[:-1], "complete": full, "rejected": [1, 2]}


@pytest.fixture(scope="module", autouse=True)
def no_optimizer_or_training():
    attempts = []
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    assert torch.get_num_interop_threads() == 20
    def forbidden(*args, **kwargs):
        attempts.append("optimizer or training")
        pytest.fail("catalog inference must not construct/restore/update an optimizer or train")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(torch.optim.Optimizer, "__init__", forbidden)
        patch.setattr(torch.optim.Adam, "__init__", forbidden)
        patch.setattr(torch.optim.Adam, "step", forbidden)
        patch.setattr(numerical, "_optimizer", forbidden)
        patch.setattr(trainer, "_restore", forbidden)
        patch.setattr(trainer, "train_compact_content_v2", forbidden)
        patch.setattr(trainer, "build_compact_content_training_v2", forbidden)
        try: yield attempts
        finally: torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def retained(no_optimizer_or_training):
    spelling = os.environ.get("LEGAL_COMPACT_TRAINED_INFERENCE_FIXTURE")
    assert spelling, "native admission must supply the exact previously exposed fixture"
    path = Path(spelling)
    manifest_raw = snapshot(path)
    assert sha(manifest_raw) == FIXTURE_SHA
    manifest = json.loads(manifest_raw)
    assert manifest["schema"] == "authored-compact-training-fixture/v2" and len(manifest["artifacts"]) == 27
    bodies = {}
    for name, item in manifest["artifacts"].items():
        selected = Path(item["path"])
        assert selected.parent == path.parent and selected.name == name
        raw = snapshot(selected)
        assert len(raw) == item["bytes"] and sha(raw) == item["sha256"]
        bodies[name] = raw
    checkpoint = json.loads(bodies["resumed-checkpoint.json"])
    assert sha(bodies["resumed-checkpoint.json"]) == digest(checkpoint) == CHECKPOINT_SHA
    assert checkpoint["progress"] == {"optimizer_steps": 2, "epochs_completed": 1, "row_cursor": 0}
    assert checkpoint["weights_sha256"] != checkpoint["initial_weights_sha256"]
    assert checkpoint["initial_checkpoint"] == json.loads(bodies["initial-parent-v1.json"])
    rows, population = json.loads(bodies["input-rows.json"]), json.loads(bodies["population.json"])
    row, bound = rows[0], population["rows"][0]
    assert row["id"] == bound["id"] == "fictional-retention"
    assert digest(row["conditioning"]) == bound["conditioning_sha256"]
    codec = tokens.build_compact_catalog_token_codec_v1()
    return {"checkpoint": checkpoint, "checkpoint_raw": bodies["resumed-checkpoint.json"],
        "conditioning": row["conditioning"], "codec": codec, "context_raw": wire(context()),
        "prefixes": prefixes(codec), "manifest_raw": manifest_raw, "manifest_path": str(path)}


def args(case, kind="nontrivial"):
    return [deepcopy(case["checkpoint"]), deepcopy(case["conditioning"]),
            list(case["prefixes"][kind]), case["context_raw"]]


def options(case):
    return {"expected_checkpoint_sha256": CHECKPOINT_SHA,
            "expected_catalog_context_sha256": sha(case["context_raw"])}


def prefix_report(case, kind):
    return tokens.compact_catalog_allowed_token_ids_v1(case["prefixes"][kind], case["context_raw"],
        expected_context_sha256=sha(case["context_raw"]), codec=case["codec"],
        expected_codec_sha256=digest(case["codec"]))


def manual_logits(checkpoint, conditioning, prefix):
    """Independent retained-tensor arithmetic: no nn.Module, GRU or model helper."""
    state = {name: torch.tensor(value, dtype=torch.float32, device="cpu")
             for name, value in checkpoint["model_state"].items()}
    with torch.inference_mode():
        vector = torch.tensor([conditioning], dtype=torch.float32, device="cpu")
        projected = vector + functional.linear(torch.tanh(functional.linear(vector,
            state["projection_down.weight"], state["projection_down.bias"])),
            state["projection_up.weight"], state["projection_up.bias"])
        hidden = torch.tanh(functional.linear(projected, state["condition.weight"], state["condition.bias"]))
        embedded = functional.embedding(torch.tensor(prefix, dtype=torch.long, device="cpu"),
                                         state["target_embedding.weight"], padding_idx=0)
        for value in embedded:
            ir, iz, inn = functional.linear(value.unsqueeze(0), state["decoder.weight_ih_l0"],
                                            state["decoder.bias_ih_l0"]).chunk(3, dim=1)
            hr, hz, hn = functional.linear(hidden, state["decoder.weight_hh_l0"],
                                           state["decoder.bias_hh_l0"]).chunk(3, dim=1)
            reset, update = torch.sigmoid(ir + hr), torch.sigmoid(iz + hz)
            candidate = torch.tanh(inn + reset * hn)
            hidden = candidate + update * (hidden - candidate)
        result = functional.linear(hidden, state["output.weight"], state["output.bias"])[0]
        assert list(result.shape) == [537] and bool(torch.isfinite(result).all())
        return result.tolist()


def forbid_models(patch, *, dispatch=True):
    def forbidden(*args, **kwargs): pytest.fail("non-numerical control reached model allocation/forward")
    patch.setattr(torch.nn.Module, "__init__", forbidden)
    patch.setattr(torch.nn.GRU, "forward", forbidden)
    patch.setattr(numerical, "_model", forbidden)
    patch.setattr(numerical, "_tensor", forbidden)
    if dispatch: patch.setattr(trained, "_forward", forbidden)


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    for name in ("training_mask", "evaluation_gold_mask"):
        assert type(report[name]) is int and report[name] == 0
    for name in ("optimizer_constructed", "optimizer_state_restored", "optimizer_executed", "training_executed"):
        assert report[name] is False
    assert report["catalog_training_verified"] is False
    for name in ("numerical_forward_count", "original_forward_count", "replay_forward_count", "reference_forward_count"):
        assert type(report[name]) is int
    assert report["replay_forward_count"] == report["reference_forward_count"] == 0


@pytest.fixture(scope="module")
def evidence(retained, no_optimizer_or_training, tmp_path_factory):
    case, records, events = retained, {}, []
    original = deepcopy(case)
    real_forward, real_gru = trained._forward, torch.nn.GRU.forward
    active = {"phase": None, "prefix": None}
    def observed_gru(model, inputs, *values, **kwargs):
        result = real_gru(model, inputs, *values, **kwargs)
        events.append({"event": "gru_forward", "phase": active["phase"], "prefix_ids": active["prefix"],
            "input_shape": list(inputs.shape), "output_shape": list(result[0].shape)})
        return result
    def observed_forward(checkpoint, conditioning, prefix_ids):
        assert digest(checkpoint) == CHECKPOINT_SHA
        active["prefix"] = list(prefix_ids)
        result = real_forward(checkpoint, conditioning, prefix_ids)
        events.append({"event": "trained_forward", "phase": active["phase"], "prefix_ids": list(prefix_ids),
            "checkpoint_sha256": digest(checkpoint), "weights_sha256": checkpoint["weights_sha256"],
            "conditioning_sha256": digest(conditioning), "logits_sha256": digest(result["logits"]),
            "output_shape": result["output_shape"]})
        return result
    allowed = prefix_report(case, "nontrivial")["allowed_token_ids"]
    constructor_ids = {case["codec"]["vocabulary"].index('"' + name + '"') for name in
                       ("predicate", "not", "and", "or", "implies", "iff", "forall", "exists", "extension")}
    assert len(set(allowed) & constructor_ids) >= 2
    assert prefix_report(case, "subset_eos")["allowed_token_ids"] == [2]
    rng, manual = torch.get_rng_state().clone(), {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(trained, "_forward", observed_forward)
        patch.setattr(torch.nn.GRU, "forward", observed_gru)
        for kind in ("nontrivial", "subset_eos"):
            active["phase"], active["prefix"] = "manual_" + kind, case["prefixes"][kind]
            reference = manual_logits(case["checkpoint"], case["conditioning"], case["prefixes"][kind])
            events.append({"event": "manual_reference", "phase": active["phase"], "prefix_ids": list(active["prefix"]),
                "checkpoint_sha256": CHECKPOINT_SHA, "logits_sha256": digest(reference)})
            active["phase"] = kind
            report = subject.score_compact_catalog_trained_v1(*args(case, kind), **options(case))
            logits = report["logits"]
            assert len(logits) == 537 and all(type(x) is float and math.isfinite(x) for x in logits)
            differences = [abs(a - b) for a, b in zip(logits, reference)]
            assert all(d <= REFERENCE_ATOL + REFERENCE_RTOL * abs(b) for d, b in zip(differences, reference))
            manual[kind] = {"logits": reference, "max_absolute_difference": max(differences),
                "exact_equal": logits == reference, "rtol": REFERENCE_RTOL, "atol": REFERENCE_ATOL,
                "comparison": "abs(actual-reference)<=atol+rtol*abs(reference)", "all_537_within_tolerance": True}
            records[kind] = report
    with pytest.MonkeyPatch.context() as patch:
        forbid_models(patch)
        for kind in ("complete", "rejected"):
            records[kind] = subject.score_compact_catalog_trained_v1(*args(case, kind), **options(case))
    assert sum(event["event"] == "gru_forward" for event in events) == 2
    assert sum(event["event"] == "trained_forward" for event in events) == 2
    assert sum(event["event"] == "manual_reference" for event in events) == 2
    assert case == original and no_optimizer_or_training == []
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    assert torch.get_num_interop_threads() == 20
    old_codec = old_tokens.build_compact_content_token_codec_v1()
    old_raw = wire(context()["catalog"])
    old_prefix = old_tokens.compact_content_allowed_token_ids_v1(case["prefixes"]["subset_eos"], old_raw,
        expected_context_sha256=sha(old_raw), codec=old_codec, expected_codec_sha256=digest(old_codec))
    assert old_prefix["status"] == "rejected" and old_prefix["allowed_token_ids"] == []
    candidate = tokens.decode_compact_catalog_tokens_v1(records["subset_eos"]["next_prefix_ids"], case["context_raw"],
        expected_context_sha256=sha(case["context_raw"]), codec=case["codec"], expected_codec_sha256=digest(case["codec"]))
    assert candidate["status"] == "valid_candidate"
    assert candidate["selection"]["selected_catalog_indices"] == [0, 2]
    assert candidate["selection"]["unused_catalog_indices"] == [1]
    scope = {"schema": "authored-catalog-trained-scoring-scope/v1", "actual_gru_forward_count": 2,
        "trained_runtime_forward_count": 2, "manual_reference_pass_count": 2,
        "manual_reference_gru_forward_count": 0, "counter_categories_overlap": True,
        "optimizer_allocations": 0, "optimizer_updates": 0, "training_executed": False,
        "historical_checkpoint_optimizer_steps": 2, "supplied_prefixes": True,
        "nontrivial_allowed_constructor_ids": sorted(set(allowed) & constructor_ids),
        "proper_subset_eos_is_grammar_forced": True, "free_running_formula_generated": False,
        "catalog_training_verified": False, "source_encoder_verified": False,
        "inference_context_permission_verified": False, "legal_meaning_verified": False,
        "training_mask": 0, "evaluation_gold_mask": 0}
    bodies = {"prior-training-manifest.json": case["manifest_raw"], "checkpoint.json": case["checkpoint_raw"],
        "conditioning.json": wire(case["conditioning"]), "catalog-context.json": case["context_raw"],
        "training-codec.json": wire(old_codec), "inference-codec.json": wire(case["codec"]),
        "authored-content.json": wire(content()), "prefixes.json": wire(case["prefixes"]),
        "nontrivial-score.json": wire(records["nontrivial"]), "subset-eos-score.json": wire(records["subset_eos"]),
        "independent-reference.json": wire(manual), "catalog-candidate.json": wire(candidate),
        "old-content-prefix.json": wire(old_prefix), "complete-no-forward.json": wire(records["complete"]),
        "rejected-no-forward.json": wire(records["rejected"]), "observed-calls.json": wire(events),
        "scope.json": wire(scope), "inputs.json": wire({"checkpoint_sha256": CHECKPOINT_SHA,
            "original_fixture_sha256": FIXTURE_SHA, "conditioning_sha256": digest(case["conditioning"]),
            "catalog_context_sha256": sha(case["context_raw"]), "prefixes_sha256": digest(case["prefixes"]),
            "training_codec_sha256": digest(old_codec), "inference_codec_sha256": digest(case["codec"]),
            "checkpoint_exposure": "previously exposed authored two-update training fixture",
            "prefix_origin": "fixed_authored_fixture", "context_origin": "authored_fixture"})}
    directory = tmp_path_factory.mktemp("catalog-trained-scoring-v1", numbered=False)
    artifacts = {}
    for name, raw in bodies.items():
        path = directory / name
        with path.open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        artifacts[name] = {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}
    assert len(artifacts) == 18 and sum(row["bytes"] for row in artifacts.values()) < 8 * 1024**2
    manifest = {"schema": "authored-catalog-trained-scoring-fixture/v1", "artifacts": artifacts}
    path = directory / "manifest.json"
    with path.open("xb") as stream:
        stream.write(wire(manifest)); stream.flush(); os.fsync(stream.fileno())
    return {"records": records, "manual": manual, "events": events, "scope": scope,
            "manifest": {"path": str(path), "sha256": digest(manifest)}}


def test_nontrivial_actual_trained_scores_match_independent_gate_arithmetic_and_selector(retained, evidence, record_property):
    record_property("catalog_trained_scoring_fixture_manifest", json.dumps(evidence["manifest"], sort_keys=True))
    score = evidence["records"]["nontrivial"]
    assert score["schema"] == "legal-compact-catalog-trained-score/v1"
    assert score["profile"] == "original-trained-content-weights-catalog-selection/v1"
    assert score["status"] == "scored" and score["reason"] is None
    assert score["checkpoint_sha256"] == CHECKPOINT_SHA
    assert score["weights_sha256"] == retained["checkpoint"]["weights_sha256"]
    assert score["conditioning"] == retained["conditioning"]
    assert score["conditioning_sha256"] == digest(retained["conditioning"])
    assert score["prefix_ids"] == retained["prefixes"]["nontrivial"]
    assert score["output_shape"] == [1, len(score["prefix_ids"]), 537]
    assert score["prefix_report"] == prefix_report(retained, "nontrivial")
    allowed = score["prefix_report"]["allowed_token_ids"]
    assert len(evidence["scope"]["nontrivial_allowed_constructor_ids"]) >= 2
    selected = min(allowed, key=lambda i: (-score["logits"][i], i))
    raw_maximum = min(range(537), key=lambda i: (-score["logits"][i], i))
    assert score["selection"]["selected_token_id"] == selected
    assert score["selection"]["raw_argmax_token_id"] == raw_maximum
    assert score["selection"]["tie_breaker"] == "lowest_token_id"
    assert score["selection"]["logits"] == score["logits"]
    assert score["logits_sha256"] == score["selection"]["logits_sha256"] == digest(score["logits"])
    assert score["next_prefix_ids"] == score["prefix_ids"] + [selected]
    assert score["runtime_verified"] is score["runtime_torch_version_verified"] is True
    assert score["numerical_forward_executed"] is score["model_restore_performed"] is score["model_executed"] is True
    assert score["actual_runtime"] == score["declared_runtime"] == retained["checkpoint"]["runtime"]
    assert score["numerical_forward_count"] == score["original_forward_count"] == 1
    assert score["training_codec"] == retained["checkpoint"]["codec"]
    assert score["training_codec_sha256"] == retained["checkpoint"]["codec_sha256"]
    assert score["inference_codec"] == retained["codec"]
    assert score["inference_codec_sha256"] == digest(retained["codec"]) != score["training_codec_sha256"]
    assert score["training_codec"]["vocabulary"] == score["inference_codec"]["vocabulary"]
    assert score["bridge_sha256"] == digest(score["bridge"])
    bridge = score["bridge"]
    assert bridge["ordered_vocabulary_equal"] is True
    assert bridge["ordered_vocabulary_sha256"] == digest(score["training_codec"]["vocabulary"])
    assert bridge["special_ids"] == {"pad_id": 0, "bos_id": 1, "eos_id": 2}
    assert bridge["policy_difference"] == "complete_predicate_use_to_nonempty_catalog_subset/v1"
    assert bridge["catalog_training_verified"] is False
    for name, value in bridge["sequence_geometry"].items():
        assert value == score["training_codec"][name] == score["inference_codec"][name]
    checkpoint = retained["checkpoint"]
    for name in ("initial_checkpoint_sha256", "initial_weights_sha256", "parent_checkpoint_sha256",
                 "optimizer_config", "optimizer_policy"):
        assert score[name] == checkpoint[name]
    assert score["compact_training_steps"] == 2 and score["training_progress"] == checkpoint["progress"]
    assert score["optimizer_state_sha256"] == digest(checkpoint["optimizer_state"])
    assert score["training_population_sha256"] == checkpoint["population_sha256"]
    assert score["training_population_count"] == checkpoint["population_count"]
    assert score["catalog_context_raw_utf8"].encode() == retained["context_raw"]
    assert score["catalog_context_raw_sha256"] == sha(retained["context_raw"])
    no_authority(score)


def test_subset_eos_is_one_scored_but_forced_step_under_explicit_new_policy(retained, evidence):
    score = evidence["records"]["subset_eos"]
    assert score["status"] == "scored" and score["prefix_report"]["allowed_token_ids"] == [2]
    assert score["selection"]["selected_token_id"] == 2
    assert score["next_prefix_ids"] == retained["prefixes"]["complete"]
    assert score["output_shape"] == [1, len(retained["prefixes"]["subset_eos"]), 537]
    assert score["numerical_forward_count"] == score["original_forward_count"] == 1
    no_authority(score)


@pytest.mark.parametrize("kind", ["complete", "rejected"])
def test_supplied_terminal_prefix_retains_null_scores_and_zero_numeric_credit(retained, evidence, kind):
    score = evidence["records"][kind]
    assert score["status"] == "no_forward"
    assert score["prefix_ids"] == score["next_prefix_ids"] == retained["prefixes"][kind]
    for name in ("logits", "logits_sha256", "selection", "output_shape", "actual_runtime"):
        assert score[name] is None
    for name in ("runtime_verified", "runtime_torch_version_verified", "model_restore_performed", "numerical_forward_executed", "model_executed"):
        assert score[name] is False
    assert score["numerical_forward_count"] == score["original_forward_count"] == 0
    no_authority(score)


def test_public_api_accepts_only_original_checkpoint_conditioning_prefix_and_catalog():
    assert set(inspect.signature(subject.score_compact_catalog_trained_v1).parameters) == {
        "checkpoint", "conditioning", "prefix_ids", "catalog_context_raw",
        "expected_checkpoint_sha256", "expected_catalog_context_sha256"}


@pytest.mark.parametrize("damage", ["checkpoint_pin", "original_weights_pin", "catalog_pin", "dimension", "nan", "infinity", "bool_conditioning",
    "magnitude", "empty_prefix", "bool_prefix", "long_prefix", "tuple_prefix", "context_bytes", "context_utf8", "context_type"])
def test_input_bindings_and_limits_refuse_before_numerical_dispatch(retained, monkeypatch, damage):
    forbid_models(monkeypatch)
    values, kwargs = args(retained), options(retained)
    if damage == "checkpoint_pin": kwargs["expected_checkpoint_sha256"] = "0" * 64
    elif damage == "original_weights_pin":
        values[0]["model_state"]["output.bias"][0] += .125
        values[0]["weights_sha256"] = digest(values[0]["model_state"])
        # The independent original checkpoint pin remains unchanged.
    elif damage == "catalog_pin": kwargs["expected_catalog_context_sha256"] = "0" * 64
    elif damage == "dimension": values[1].append(0.)
    elif damage in {"nan", "infinity", "bool_conditioning", "magnitude"}:
        values[1][0] = {"nan": float("nan"), "infinity": float("inf"), "bool_conditioning": True, "magnitude": 1e9}[damage]
    elif damage == "empty_prefix": values[2] = []
    elif damage == "bool_prefix": values[2] = [True]
    elif damage == "long_prefix": values[2] = [1] * 513
    elif damage == "tuple_prefix": values[2] = tuple(values[2])
    elif damage == "context_type": values[3] = values[3].decode()
    else:
        values[3] = b" " * (524288 + 1) if damage == "context_bytes" else b"\xff"
        kwargs["expected_catalog_context_sha256"] = sha(values[3])
    if damage != "context_utf8":
        def no_operation_imports(): pytest.fail("malformed preflight reached operation owners")
        monkeypatch.setattr(subject, "_owners", no_operation_imports)
    with pytest.raises(ValueError): subject.score_compact_catalog_trained_v1(*values, **kwargs)


@pytest.mark.parametrize("damage", ["weights_pin", "weights_content", "initial_parent", "trained_parent", "progress",
    "missing_optimizer_moment", "vocabulary_order", "codec_profile", "authority", "mask_bool"])
def test_resealed_checkpoint_corruption_never_creates_catalog_training_profile(retained, monkeypatch, damage):
    forbid_models(monkeypatch)
    values, kwargs = args(retained), options(retained)
    checkpoint = values[0]
    if damage == "weights_pin": checkpoint["weights_sha256"] = "0" * 64
    elif damage == "weights_content": checkpoint["model_state"]["output.bias"][0] += .125
    elif damage == "initial_parent": checkpoint["initial_checkpoint_sha256"] = "0" * 64
    elif damage == "trained_parent": checkpoint["parent_checkpoint_sha256"] = "invalid"
    elif damage == "progress": checkpoint["progress"]["row_cursor"] = 1
    elif damage == "missing_optimizer_moment": checkpoint["optimizer_state"]["parameters"].pop(next(iter(checkpoint["optimizer_state"]["parameters"])))
    elif damage == "vocabulary_order":
        vocabulary = checkpoint["codec"]["vocabulary"]
        vocabulary[3], vocabulary[4] = vocabulary[4], vocabulary[3]
        checkpoint["codec_sha256"] = digest(checkpoint["codec"])
    elif damage == "codec_profile":
        checkpoint["codec"] = deepcopy(retained["codec"])
        checkpoint["codec_sha256"] = digest(checkpoint["codec"])
    elif damage == "authority": checkpoint["authority"][next(iter(checkpoint["authority"]))] = True
    else: checkpoint["training_mask"] = False
    kwargs["expected_checkpoint_sha256"] = digest(checkpoint)
    with pytest.raises(ValueError): subject.score_compact_catalog_trained_v1(*values, **kwargs)


@pytest.mark.parametrize("damage", ["unused_roles", "old_context", "wrong_policy", "duplicate_field"])
def test_full_catalog_validation_includes_unused_entries_and_wrapper(retained, monkeypatch, damage):
    forbid_models(monkeypatch)
    values, kwargs = args(retained), options(retained)
    ctx = context()
    if damage == "unused_roles": ctx["catalog"]["argument_roles"][2]["roles"] = []
    elif damage == "old_context": ctx = ctx["catalog"]
    elif damage == "wrong_policy": ctx["selection_policy"] = "caller_selected_subset"
    raw = wire(ctx)
    if damage == "duplicate_field": raw = b'{"schema":"invalid",' + raw[1:]
    values[3], kwargs["expected_catalog_context_sha256"] = raw, sha(raw)
    with pytest.raises(ValueError): subject.score_compact_catalog_trained_v1(*values, **kwargs)


def test_resealed_recorded_runtime_mismatch_refuses_before_model_allocation(retained, monkeypatch):
    forbid_models(monkeypatch, dispatch=False)
    values, kwargs = args(retained), options(retained)
    values[0]["runtime"]["machine"] = "authored-incompatible-runtime"
    kwargs["expected_checkpoint_sha256"] = digest(values[0])
    with pytest.raises(ValueError, match="actual inference runtime differs"):
        subject.score_compact_catalog_trained_v1(*values, **kwargs)


@pytest.mark.parametrize("damage", ["vocabulary_order", "special_id", "sequence_geometry", "old_codec"])
def test_inference_codec_bridge_refuses_nonidentical_order_special_ids_and_geometry(retained, monkeypatch, damage):
    forbid_models(monkeypatch)
    actual = tokens.build_compact_catalog_token_codec_v1
    calls = []
    def damaged_codec():
        value = actual()
        calls.append(True)
        if damage == "vocabulary_order": value["vocabulary"][3], value["vocabulary"][4] = value["vocabulary"][4], value["vocabulary"][3]
        elif damage == "special_id": value["bos_id"] = 2
        elif damage == "sequence_geometry": value["max_sequence_tokens"] = 513
        else: value = deepcopy(retained["checkpoint"]["codec"])
        return value
    # Negative return-value boundary control only: no successful forged receipt.
    monkeypatch.setattr(tokens, "build_compact_catalog_token_codec_v1", damaged_codec)
    with pytest.raises(ValueError): subject.score_compact_catalog_trained_v1(*args(retained), **options(retained))
    assert calls


@pytest.mark.parametrize("damage", ["authority", "mask_bool", "allowed_bool", "owner_duplicate", "owner_missing",
    "context_pin", "offered_bool"])
def test_genuine_terminal_prefix_receipt_tampering_aborts_without_forward(retained, monkeypatch, damage):
    forbid_models(monkeypatch)
    actual, calls = tokens.compact_catalog_allowed_token_ids_v1, []
    def damaged_prefix(*args, **kwargs):
        report = actual(*args, **kwargs)
        calls.append(report["status"])
        if damage == "authority": report["authority"][next(iter(report["authority"]))] = True
        elif damage == "mask_bool": report["training_mask"] = False
        elif damage == "allowed_bool": report["allowed_token_ids"] = [True]
        elif damage == "owner_duplicate": report["owner_pins"][-1] = deepcopy(report["owner_pins"][0])
        elif damage == "owner_missing": report["owner_pins"].pop()
        elif damage == "context_pin": report["context_raw_sha256"] = "0" * 64
        else: report["offered_ids"][0] = True
        return report
    monkeypatch.setattr(tokens, "compact_catalog_allowed_token_ids_v1", damaged_prefix)
    with pytest.raises(ValueError): subject.score_compact_catalog_trained_v1(*args(retained, "complete"), **options(retained))
    assert calls == ["complete"]


@pytest.mark.parametrize("anchor", ["scoring", "trained", "catalog"])
def test_changed_import_anchor_refuses_even_supplied_complete_prefix(retained, monkeypatch, anchor):
    forbid_models(monkeypatch)
    module = {"scoring": subject, "trained": trained, "catalog": tokens}[anchor]
    if anchor == "trained": monkeypatch.setattr(module, "_SELF_SHA", "0" * 64)
    else: monkeypatch.setattr(module, "_SELF_SNAPSHOT", ("0" * 64, module._SELF_SNAPSHOT[1]))
    with pytest.raises(ValueError): subject.score_compact_catalog_trained_v1(*args(retained, "complete"), **options(retained))


@pytest.mark.parametrize("error_type,closing_failure", [(RuntimeError, False), (KeyboardInterrupt, False),
    (RuntimeError, True), (KeyboardInterrupt, True)])
def test_first_operational_error_or_interrupt_survives_secondary_closing_failure(retained, monkeypatch, error_type, closing_failure):
    forbid_models(monkeypatch)
    failure, calls = error_type("authored operation failure; no model forward"), []
    def dispatch_failure(*args, **kwargs):
        calls.append(True)
        if closing_failure:
            monkeypatch.setattr(subject, "_SELF_SNAPSHOT", ("0" * 64, subject._SELF_SNAPSHOT[1]))
        raise failure
    monkeypatch.setattr(trained, "_forward", dispatch_failure)
    with pytest.raises(error_type) as caught:
        subject.score_compact_catalog_trained_v1(*args(retained), **options(retained))
    assert caught.value is failure and calls == [True]
    if closing_failure:
        assert any("closing" in note.lower() for note in getattr(failure, "__notes__", []))


@pytest.mark.parametrize("which", ["original", "detached"])
def test_input_custody_refuses_mutation_after_genuine_terminal_owner_return(retained, monkeypatch, which):
    forbid_models(monkeypatch)
    values, kwargs = args(retained, "complete"), options(retained)
    actual, calls = tokens.compact_catalog_allowed_token_ids_v1, []
    def changed_input(offered, *args, **kwargs):
        report = actual(offered, *args, **kwargs)
        calls.append(True)
        if which == "original": values[1][0] += .125
        else: offered.append(2)
        return report
    monkeypatch.setattr(tokens, "compact_catalog_allowed_token_ids_v1", changed_input)
    with pytest.raises(ValueError, match="inputs changed"):
        subject.score_compact_catalog_trained_v1(*values, **kwargs)
    assert calls == [True]


@pytest.mark.parametrize("failure_mode", ["whole_bound", "final_source_fence"])
def test_full_serialization_refuses_bound_or_late_source_change_without_partial_report(retained, evidence, monkeypatch, failure_mode):
    forbid_models(monkeypatch)
    actual, calls = subject._wire, []
    # Declared reduced-bound mechanics, not an actual 4 MiB size benchmark.
    smaller_bound = len(wire(evidence["records"]["complete"])) - 1
    def complete_report_wire(value, maximum=subject.MAX_REPORT_BYTES):
        if type(value) is dict and value.get("schema") == "legal-compact-catalog-trained-score/v1":
            calls.append(True)
            if failure_mode == "whole_bound": return actual(value, smaller_bound)
            raw = actual(value, maximum)
            monkeypatch.setattr(subject, "_SELF_SNAPSHOT", ("0" * 64, subject._SELF_SNAPSHOT[1]))
            return raw
        return actual(value, maximum)
    monkeypatch.setattr(subject, "_wire", complete_report_wire)
    with pytest.raises(ValueError): subject.score_compact_catalog_trained_v1(*args(retained, "complete"), **options(retained))
    assert calls == [True]
