"""Original-bound catalog continuation with eight predeclared genuine forwards.

Three original, four successful replay and one rejected-validation replay are
separate purposes. No new manual reference, training, optimizer or encoder.
Fictional supplied prefixes grant neither source permission nor semantic credit.
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

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_trained_generation_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as trained
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_trained_scoring_v1 as scoring
from ipfs_datasets_py.logic.autoformal import legal_relational_catalog_batch_evaluation_v1 as batch
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_tokens_v1 as tokens
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as old_tokens
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

FIXTURE_SHA = "1c4b7c37eba6870c2a746cb3e3191013a1d25906cb75427d4f7be0ca6583dab7"
CHECKPOINT_SHA = "0ba5bb1d941c83e4695b6ec7e971c042d6e0419f1dc8c24bfb5cc509b0c6bac0"
# Frozen comparison to prior admitted vectors; no new reference computation.
REFERENCE_RTOL, REFERENCE_ATOL = 1e-5, 2e-6
PRIOR_SCORING_SHA = "527322d78f2f1c479ee9eba3f8dac8b8ba5ce45a474cbb9205571524924d2538"
PRIOR_SCORES = {"nontrivial-score.json": "d7db55a4a51b9c59327887a9bd1429c61b34beae1938597f01834cd73626dc31",
                "subset-eos-score.json": "5abe79a8effa693a2f25dafc6d84dac82a1614cc5e6aba6c29dc3a37e13f2f0e"}
POPULATION_IDS = ("runtime", "missing", "duplicate", "malformed", "error", "timeout", "cancellation", "not_started", "unsupported")
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
    leaf = ["predicate", 0, [["variable", 0]]]
    tree = [deepcopy(leaf) for _ in range(64)]
    while len(tree) > 1:
        tree = [["and", tree[i], tree[i + 1]] for i in range(0, len(tree), 2)]
    long_content = {"schema": "legal-relational-compact-content/v1", "tree": ["forall", 0, tree[0]]}
    long_text = wire(long_content).decode()
    long_lexical = LEXICAL.findall(long_text)
    assert "".join(long_lexical) == long_text
    long_ids = [1, *(table[token] for token in long_lexical), 2]
    assert len(long_ids) > 512
    return {"nontrivial": nontrivial, "subset_eos": full[:-1], "complete": full,
            "rejected": [1, 2], "token_budget": long_ids[:512]}



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
    prior_path = Path(os.environ["LEGAL_COMPACT_CATALOG_SCORING_FIXTURE"])
    prior_raw = snapshot(prior_path)
    assert sha(prior_raw) == PRIOR_SCORING_SHA
    prior = json.loads(prior_raw)
    assert prior["schema"] == "authored-catalog-trained-scoring-fixture/v1"
    prior_bodies = {}
    for name, expected in PRIOR_SCORES.items():
        item = prior["artifacts"][name]
        selected = Path(item["path"])
        assert selected.parent == prior_path.parent and selected.name == name
        raw = snapshot(selected)
        assert len(raw) == item["bytes"] and sha(raw) == item["sha256"] == expected
        prior_bodies[name] = raw
    codec = tokens.build_compact_catalog_token_codec_v1()
    return {"prior_raw": prior_raw, "prior_bodies": prior_bodies,"checkpoint": checkpoint, "checkpoint_raw": bodies["resumed-checkpoint.json"],
        "conditioning": row["conditioning"], "codec": codec, "context_raw": wire(context()),
        "prefixes": prefixes(codec), "manifest_raw": manifest_raw, "manifest_path": str(path)}


def args(case, kind="nontrivial"):
    return [deepcopy(case["checkpoint"]), deepcopy(case["conditioning"]),
            list(case["prefixes"][kind]), case["context_raw"]]


def options(case, *, maximum=2):
    return {"expected_checkpoint_sha256": CHECKPOINT_SHA,
            "expected_catalog_context_sha256": sha(case["context_raw"]),
            "max_new_tokens": maximum, "prefix_origin": "authored_fixture",
            "catalog_context_origin": "authored_fixture"}


def prefix_report(case, kind):
    return tokens.compact_catalog_allowed_token_ids_v1(case["prefixes"][kind], case["context_raw"],
        expected_context_sha256=sha(case["context_raw"]), codec=case["codec"],
        expected_codec_sha256=digest(case["codec"]))


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
        if name in report: assert report[name] is False
    if "catalog_training_verified" in report: assert report["catalog_training_verified"] is False


def population():
    return {"schema": "legal-relational-batch-population/v1", "partition": "authored-catalog-continuation-controls",
        "selection_sha256": sha(b"frozen complete nine-occurrence engineering population"),
        "rows": [{"id": name, "source_sha256": sha(("fictional source:" + name).encode()),
                  "context_sha256": sha(("fictional source context:" + name).encode())} for name in POPULATION_IDS]}


def references(population_raw):
    return {"schema": "legal-relational-batch-references/v1", "population_sha256": sha(population_raw),
        "rows": [{"id": name, "status": "unavailable", "request_utf8": None, "request_sha256": None,
                  "report": None, "report_sha256": None, "reason": "No reviewed reference supplied"}
                 for name in POPULATION_IDS]}


def batch_prepare(population_raw, references_raw, predictions_raw):
    pins = {"expected_population_sha256": sha(population_raw), "expected_references_sha256": sha(references_raw),
            "expected_predictions_sha256": sha(predictions_raw)}
    report = batch.prepare_relational_catalog_batch_evaluation_v1(population_raw, references_raw, predictions_raw, **pins)
    replay = batch.validate_relational_catalog_batch_evaluation_v1(report, population_raw, references_raw,
        predictions_raw, expected_evaluation_sha256=digest(report), **pins)
    assert replay == report
    return report


def mixed_predictions(adapter, eos, selected):
    by_id = {row["id"]: row for row in selected["rows"]}
    predictions = deepcopy(adapter["predictions"])
    prototype = predictions["rows"][0]
    def generated(name, ids=None):
        row = {**deepcopy(prototype), **by_id[name]}
        if ids is not None:
            row["generated_ids"] = list(ids)
            row["generated_ids_sha256"] = digest(ids)
        return row
    damaged = generated("malformed")
    damaged["unexpected"] = "retain the original malformed observation"
    declared = [{**by_id[name], "status": name, "teacher_forcing": False, "target_access": False,
        "generated_ids": None, "generated_ids_sha256": None, "reason": "Authored terminal disposition",
        "catalog_context_utf8": None, "catalog_context_sha256": None, "catalog_context_origin": None}
        for name in POPULATION_IDS[4:]]
    outside, unidentifiable = generated("runtime"), generated("runtime")
    outside["id"] = "outside"
    unidentifiable.pop("id")
    # The second duplicate is a raw declared EOS observation, not a second
    # verified adapter operation. Its original full trace is separately retained.
    predictions["rows"] = [generated("runtime"), generated("duplicate"),
        generated("duplicate", eos["generated_ids"]), damaged, *declared, outside, unidentifiable]
    return predictions


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
    selected = population()
    population_raw = wire(selected)
    allowed = prefix_report(case, "nontrivial")["allowed_token_ids"]
    constructors = {case["codec"]["vocabulary"].index('"' + name + '"') for name in
                    ("predicate", "not", "and", "or", "implies", "iff", "forall", "exists", "extension")}
    assert len(set(allowed) & constructors) >= 2
    assert prefix_report(case, "subset_eos")["allowed_token_ids"] == [2]
    assert prefix_report(case, "token_budget")["status"] == "budget_exhausted"
    rng = torch.get_rng_state().clone()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(trained, "_forward", observed_forward)
        patch.setattr(torch.nn.GRU, "forward", observed_gru)
        active["phase"] = "original_continuation"
        records["continuation"] = subject.generate_compact_catalog_trained_v1(*args(case), **options(case))
        active["phase"] = "original_forced_eos"
        records["eos"] = subject.generate_compact_catalog_trained_v1(*args(case, "subset_eos"), **options(case, maximum=1))
        active["phase"] = "successful_validator_replay"
        records["validation"] = subject.validate_compact_catalog_trained_generation_v1(records["continuation"],
            *args(case), expected_report_sha256=digest(records["continuation"]), **options(case))
        active["phase"] = "successful_adapter_replay"
        records["adapter"] = subject.prepare_compact_catalog_trained_batch_prediction_v1(records["continuation"],
            *args(case), population_raw, expected_generation_sha256=digest(records["continuation"]),
            expected_population_sha256=sha(population_raw), occurrence_id="runtime", **options(case))
        tampered = deepcopy(records["eos"])
        score = tampered["trace"][0]
        changed = min((i for i in range(537) if i != 2), key=lambda i: score["logits"][i])
        score["logits"][changed] -= .125
        score["logits_sha256"] = digest(score["logits"])
        score["selection"]["logits"] = list(score["logits"])
        score["selection"]["logits_sha256"] = score["logits_sha256"]
        active["phase"] = "failed_validator_replay"
        before = len(events)
        with pytest.raises(ValueError, match="generation differs from complete original-bound replay") as caught:
            subject.validate_compact_catalog_trained_generation_v1(tampered, *args(case, "subset_eos"),
                expected_report_sha256=digest(tampered), **options(case, maximum=1))
        failed = {"schema": "authored-catalog-generation-failed-replay/v1", "report_returned": False,
            "exception_type": type(caught.value).__name__, "exception_message": str(caught.value), "expected_refusal": "replayed_complete_trace_differs",
            "original_generation_sha256": digest(records["eos"]), "tampered_generation_sha256": digest(tampered),
            "changed_logit_index": changed, "independent_pin_resealed": True,
            "observed_gru_forward_count": sum(row["event"] == "gru_forward" for row in events[before:]),
            "observed_trained_forward_count": sum(row["event"] == "trained_forward" for row in events[before:])}
    with pytest.MonkeyPatch.context() as patch:
        forbid_models(patch)
        for kind in ("complete", "rejected", "token_budget"):
            records[kind] = subject.generate_compact_catalog_trained_v1(*args(case, kind), **options(case))
        references_raw = wire(references(population_raw))
        adapter_predictions_raw = wire(records["adapter"]["predictions"])
        adapter_batch = batch_prepare(population_raw, references_raw, adapter_predictions_raw)
        mixed_raw = wire(mixed_predictions(records["adapter"], records["eos"], selected))
        mixed_batch = batch_prepare(population_raw, references_raw, mixed_raw)
    assert sum(row["event"] == "gru_forward" for row in events) == 8
    assert sum(row["event"] == "trained_forward" for row in events) == 8
    assert failed["observed_gru_forward_count"] == failed["observed_trained_forward_count"] == 1
    assert case == original and no_optimizer_or_training == []
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    assert torch.get_num_interop_threads() == 20
    parity = {}
    for kind, prior_name in (("continuation", "nontrivial-score.json"), ("eos", "subset-eos-score.json")):
        current, prior = records[kind]["trace"][0], json.loads(case["prior_bodies"][prior_name])
        for key in ("checkpoint_sha256", "weights_sha256", "conditioning", "conditioning_sha256", "prefix_ids",
                    "catalog_context_raw_utf8", "catalog_context_raw_sha256", "context_sha256", "catalog_sha256",
                    "training_codec", "training_codec_sha256", "inference_codec", "inference_codec_sha256",
                    "bridge", "bridge_sha256", "actual_runtime", "declared_runtime", "prefix_report"):
            assert current[key] == prior[key]
        differences = [abs(a - b) for a, b in zip(current["logits"], prior["logits"])]
        assert len(differences) == 537
        within = all(d <= REFERENCE_ATOL + REFERENCE_RTOL * abs(b) for d, b in zip(differences, prior["logits"]))
        assert within
        parity[kind] = {"prior_artifact_sha256": sha(case["prior_bodies"][prior_name]),
            "current_score_sha256": digest(current), "max_absolute_difference": max(differences),
            "all_537_within_tolerance": within, "exact_equal": current["logits"] == prior["logits"],
            "rtol": REFERENCE_RTOL, "atol": REFERENCE_ATOL, "new_manual_reference_pass_count": 0}
    scope = {"schema": "authored-catalog-trained-generation-scope/v1", "actual_gru_forward_count": 8,
        "trained_runtime_forward_count": 8, "original_generation_forward_count": 3,
        "successful_validation_replay_forward_count": 2, "successful_adapter_replay_forward_count": 2,
        "failed_validation_replay_forward_count": 1, "new_manual_reference_pass_count": 0,
        "counter_categories_overlap": True, "optimizer_allocations": 0, "optimizer_updates": 0,
        "training_executed": False, "historical_checkpoint_optimizer_steps": 2,
        "supplied_prefixes": True, "free_running_formula_generated": False,
        "proper_subset_eos_is_grammar_forced": True, "encoder_authenticated": False,
        "context_permission_verified": False, "legal_accuracy_evaluated": False,
        "batch_selected_count": 9, "mixed_observation_count": 11,
        "raw_eos_observation_is_verified_adapter_output": False,
        "unchanged_old_scoring_cohort_accounted_separately": True}
    inputs = {"schema": "authored-catalog-trained-generation-inputs/v1", "checkpoint_sha256": CHECKPOINT_SHA,
        "conditioning_sha256": digest(case["conditioning"]), "catalog_context_sha256": sha(case["context_raw"]),
        "population_sha256": sha(population_raw), "original_checkpoint_exposed": True,
        "generation_settings": options(case), "eos_generation_settings": options(case, maximum=1),
        "unreviewed_fictional_fixture": True, "raw_source_context_is_catalog_context": False}
    bodies = {"prior-training-manifest.json": case["manifest_raw"], "prior-scoring-manifest.json": case["prior_raw"],
        "prior-nontrivial-score.json": case["prior_bodies"]["nontrivial-score.json"],
        "prior-subset-eos-score.json": case["prior_bodies"]["subset-eos-score.json"],
        "checkpoint.json": case["checkpoint_raw"], "conditioning.json": wire(case["conditioning"]),
        "catalog-context.json": case["context_raw"], "training-codec.json": wire(case["checkpoint"]["codec"]),
        "inference-codec.json": wire(case["codec"]), "authored-content.json": wire(content()),
        "prefixes.json": wire(case["prefixes"]), "continuation.json": wire(records["continuation"]),
        "forced-eos.json": wire(records["eos"]), "validation.json": wire(records["validation"]),
        "adapter.json": wire(records["adapter"]), "complete-no-forward.json": wire(records["complete"]),
        "rejected-no-forward.json": wire(records["rejected"]), "token-budget-no-forward.json": wire(records["token_budget"]),
        "tampered-eos.json": wire(tampered), "failed-replay.json": wire(failed), "observed-calls.json": wire(events),
        "scope.json": wire(scope), "inputs.json": wire(inputs), "population.json": population_raw,
        "references.json": references_raw, "adapter-predictions.json": adapter_predictions_raw,
        "adapter-batch-report.json": wire(adapter_batch), "mixed-predictions.json": mixed_raw,
        "mixed-batch-report.json": wire(mixed_batch), "prior-score-parity.json": wire(parity)}
    directory = tmp_path_factory.getbasetemp() / "catalog-trained-generation-v1"
    directory.mkdir()
    artifacts = {}
    for name, raw in bodies.items():
        path = directory / name
        with path.open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        artifacts[name] = {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}
    assert len(artifacts) == 30 and sum(row["bytes"] for row in artifacts.values()) < 8 * 1024**2
    manifest = {"schema": "authored-catalog-trained-generation-fixture/v1", "artifacts": artifacts}
    path = directory / "manifest.json"
    with path.open("xb") as stream:
        stream.write(wire(manifest)); stream.flush(); os.fsync(stream.fileno())
    return {"records": records, "events": events, "scope": scope, "failed": failed, "tampered": tampered,
        "population_raw": population_raw, "references_raw": references_raw, "mixed_raw": mixed_raw,
        "adapter_batch": adapter_batch, "mixed_batch": mixed_batch, "parity": parity,
        "manifest": {"path": str(path), "sha256": digest(manifest)}}


def test_two_step_continuation_preserves_actual_full_scores_and_input_trajectory(retained, evidence, record_property):
    record_property("catalog_trained_generation_fixture_manifest", json.dumps(evidence["manifest"], sort_keys=True))
    report = evidence["records"]["continuation"]
    assert report["schema"] == "legal-compact-catalog-trained-generation/v1"
    assert report["profile"] == "bounded-trained-catalog-generation-384/v1"
    assert report["status"] == "step_budget_exhausted"
    assert report["initial_prefix_ids"] == retained["prefixes"]["nontrivial"]
    assert report["emitted_token_count"] == report["score_call_count"] == len(report["trace"]) == 2
    expected, selected, raw_maxima = list(report["initial_prefix_ids"]), [], []
    for step in report["trace"]:
        assert step["schema"] == "legal-compact-catalog-trained-score/v1" and step["status"] == "scored"
        assert step["prefix_ids"] == expected
        assert len(step["logits"]) == 537 and all(type(x) is float and math.isfinite(x) for x in step["logits"])
        allowed = step["prefix_report"]["allowed_token_ids"]
        winner = min(allowed, key=lambda i: (-step["logits"][i], i))
        raw_winner = min(range(537), key=lambda i: (-step["logits"][i], i))
        assert step["selection"]["selected_token_id"] == winner
        assert step["selection"]["raw_argmax_token_id"] == raw_winner
        assert step["selection"]["logits"] == step["logits"]
        assert step["logits_sha256"] == step["selection"]["logits_sha256"] == digest(step["logits"])
        expected.append(winner); selected.append(winner); raw_maxima.append(raw_winner)
        assert step["next_prefix_ids"] == expected
        assert step["output_shape"] == [1, len(expected) - 1, 537]
        assert step["numerical_forward_count"] == step["original_forward_count"] == 1
        no_authority(step)
    assert report["generated_ids"] == expected
    assert report["selected_token_ids"] == selected and report["raw_argmax_ids_by_step"] == raw_maxima
    assert report["total_token_count"] == len(expected)
    assert report["numerical_forward_count"] == report["original_forward_count"] == 2
    assert report["replay_forward_count"] == report["reference_forward_count"] == 0
    assert report["final_prefix_report"]["offered_ids"] == expected
    assert report["final_decoding"]["generated_ids"] == expected and report["final_decoding"]["status"] == "incomplete"
    assert report["settings"]["max_new_tokens"] == 2 and report["settings"]["max_total_ids"] == 512
    assert report["settings_sha256"] == digest(report["settings"])
    assert report["checkpoint_sha256"] == CHECKPOINT_SHA
    assert report["conditioning_sha256"] == digest(retained["conditioning"])
    assert report["catalog_context_raw_sha256"] == sha(retained["context_raw"])
    assert report["training_codec"] == retained["checkpoint"]["codec"]
    assert report["inference_codec"] == retained["codec"]
    assert report["training_codec_sha256"] != report["inference_codec_sha256"]
    assert report["bridge_sha256"] == digest(report["bridge"])
    assert report["exposure"]["teacher_forcing"] is True and report["exposure"]["target_access"] is False
    assert report["exposure"]["encoder_sha256"] is None
    assert report["actual_runtime"] == report["declared_runtime"] == retained["checkpoint"]["runtime"]
    assert report["runtime_verified"] is report["runtime_torch_version_verified"] is True
    no_authority(report)


def test_actual_forced_eos_completes_subset_without_claiming_a_learned_structure(retained, evidence):
    report = evidence["records"]["eos"]
    assert report["status"] == "complete" and report["selected_token_ids"] == [2]
    assert report["generated_ids"] == retained["prefixes"]["complete"]
    assert report["score_call_count"] == report["emitted_token_count"] == report["numerical_forward_count"] == 1
    assert report["trace"][0]["prefix_report"]["allowed_token_ids"] == [2]
    assert report["final_decoding"]["status"] == "valid_candidate"
    selection = report["final_decoding"]["selection"]
    assert selection["selected_catalog_indices"] == [0, 2] and selection["unused_catalog_indices"] == [1]
    assert selection["catalog_content"] == content()
    old_codec = old_tokens.build_compact_content_token_codec_v1()
    old_raw = wire(context()["catalog"])
    old_prefix = old_tokens.compact_content_allowed_token_ids_v1(retained["prefixes"]["subset_eos"], old_raw,
        expected_context_sha256=sha(old_raw), codec=old_codec, expected_codec_sha256=digest(old_codec))
    assert old_prefix["status"] == "rejected" and old_prefix["allowed_token_ids"] == []
    assert evidence["scope"]["proper_subset_eos_is_grammar_forced"] is True
    assert evidence["scope"]["free_running_formula_generated"] is False
    no_authority(report)


def test_original_bound_validator_receipt_counts_only_this_calls_replay(evidence):
    validation, original = evidence["records"]["validation"], evidence["records"]["continuation"]
    assert validation["schema"] == "legal-compact-catalog-trained-generation-validation/v1"
    assert validation["generation_report"] == original and validation["generation_sha256"] == digest(original)
    assert validation["generation_regenerated"] is True
    assert validation["original_generation_forward_count"] == 2
    assert validation["numerical_replay_forward_count"] == validation["numerical_forward_count"] == 2
    assert validation["original_forward_count"] == validation["reference_forward_count"] == 0
    assert validation["replay_forward_count"] == 2 and validation["count_categories_overlap"] is True
    no_authority(validation)


def test_mandatory_adapter_replay_preserves_source_context_and_full_population_denominator(retained, evidence):
    report = evidence["records"]["adapter"]
    assert report["schema"] == "legal-compact-catalog-trained-batch-prediction/v1"
    assert report["generation_validation"] == evidence["records"]["validation"]
    assert report["original_generation_forward_count"] == 2
    assert report["numerical_replay_forward_count"] == report["numerical_forward_count"] == report["replay_forward_count"] == 2
    assert report["original_forward_count"] == report["reference_forward_count"] == 0
    assert report["population_sha256"] == sha(evidence["population_raw"])
    predictions, row = report["predictions"], report["prediction_row"]
    assert report["predictions_sha256"] == digest(predictions)
    assert predictions["rows"] == [row]
    assert predictions["generation"]["kind"] == "decoder_declared" and predictions["generation"]["encoder_sha256"] is None
    assert predictions["generation"]["teacher_forcing"] is True
    assert row["generated_ids"] == evidence["records"]["continuation"]["generated_ids"]
    source = json.loads(evidence["population_raw"])["rows"][0]
    for key in ("id", "source_sha256", "context_sha256"): assert row[key] == source[key]
    assert row["context_sha256"] != row["catalog_context_sha256"] == sha(retained["context_raw"])
    assert row["catalog_context_utf8"].encode() == retained["context_raw"]
    evaluated = evidence["adapter_batch"]
    assert evaluated["population"]["ordered_ids"] == list(POPULATION_IDS)
    assert evaluated["terminal_counts"]["unverifiable_generation"] == 1
    assert evaluated["terminal_counts"]["missing"] == 8
    assert sum(evaluated["terminal_counts"].values()) == 9
    assert evaluated["valid_typed_output"] == {"count": 0, "total": 9, "fraction": 0.0}
    assert evaluated["observation_ledger"][0]["catalog_decoding"]["status"] == "incomplete"
    no_authority(report); no_authority(evaluated)


def test_mixed_raw_dispositions_and_duplicates_never_receive_comparison_credit(evidence):
    report, predictions = evidence["mixed_batch"], json.loads(evidence["mixed_raw"])
    assert report["coverage"] == {"valid": False, "expected_count": 9, "prediction_row_count": 11,
        "missing_ids": ["missing"], "duplicate_ids": {"duplicate": [1, 2]},
        "unexpected_ids": {"outside": [9]}, "unidentifiable_indices": [10]}
    assert report["population"]["ordered_ids"] == list(POPULATION_IDS)
    expected = dict.fromkeys(report["terminal_counts"], 0)
    expected.update(unverifiable_generation=6, missing=1, duplicate=1, malformed=1)
    assert report["terminal_counts"] == expected and sum(expected.values()) == 9
    assert report["valid_typed_output"] == {"count": 0, "total": 9, "fraction": 0.0}
    assert report["reference_availability"] == {"available": 0, "unavailable": 9, "total": 9, "fraction": 0.0}
    ledger = report["observation_ledger"]
    assert [row["raw_observation"] for row in ledger] == predictions["rows"]
    assert [row["declared_status"] for row in ledger[4:9]] == list(POPULATION_IDS[4:])
    assert all(row["outcome"] == "unverifiable_generation" for row in ledger[4:9])
    assert ledger[1]["catalog_decoding"]["status"] == "incomplete"
    assert ledger[2]["catalog_decoding"]["status"] == "valid_candidate"
    assert [row["outcome"] for row in ledger[-2:]] == ["unexpected", "unidentifiable"]
    assert report["occurrences"][2]["status"] == "duplicate" and report["occurrences"][2]["pair_diagnostic"] is None
    for row in ledger[4:9]: assert "generation_declaration_invalid" in row["provenance_reasons"]
    assert all(item["total"] == 9 and item["matched"] == 0 for item in report["full_selected_structure_diagnostics"].values())
    no_authority(report)


def test_resealed_tampered_trace_requires_actual_refusing_replay_and_is_accounted(evidence):
    assert digest(evidence["tampered"]) != digest(evidence["records"]["eos"])
    score = evidence["tampered"]["trace"][0]
    assert score["logits_sha256"] == score["selection"]["logits_sha256"] == digest(score["logits"])
    assert score["selection"]["logits"] == score["logits"]
    assert evidence["failed"]["report_returned"] is False
    phases = ("original_continuation", "original_forced_eos", "successful_validator_replay", "successful_adapter_replay", "failed_validator_replay")
    assert [sum(row["event"] == "gru_forward" and row["phase"] == phase for row in evidence["events"]) for phase in phases] == [2, 1, 2, 2, 1]
    assert evidence["scope"]["actual_gru_forward_count"] == 8


@pytest.mark.parametrize("kind,status", [("complete", "supplied_complete"), ("rejected", "blocked"), ("token_budget", "token_budget_exhausted")])
def test_genuine_terminal_prefixes_have_distinct_zero_forward_dispositions(retained, evidence, kind, status):
    report = evidence["records"][kind]
    assert report["status"] == status
    assert report["generated_ids"] == report["initial_prefix_ids"] == retained["prefixes"][kind]
    assert report["selected_token_ids"] == report["raw_argmax_ids_by_step"] == []
    assert report["emitted_token_count"] == report["numerical_forward_count"] == report["original_forward_count"] == 0
    assert report["score_call_count"] == len(report["trace"]) == 1
    assert report["trace"][0]["status"] == "no_forward" and report["trace"][0]["logits"] is None
    assert report["actual_runtime"] is None
    for key in ("runtime_verified", "runtime_torch_version_verified", "model_executed"):
        assert report[key] is False
    for key in ("model_restore_performed", "numerical_forward_executed"):
        assert report["trace"][0][key] is False
    if kind == "token_budget":
        assert report["total_token_count"] == 512
        assert report["final_prefix_report"]["status"] == "budget_exhausted"
        assert report["final_prefix_report"]["reason"] == "output_limit_without_eos"
    no_authority(report)


def test_public_entrypoints_accept_only_original_bound_inputs_and_no_target_model_or_decoded_override():
    common = {"checkpoint", "conditioning", "prefix_ids", "catalog_context_raw", "expected_checkpoint_sha256",
        "expected_catalog_context_sha256", "max_new_tokens", "prefix_origin", "catalog_context_origin"}
    assert set(inspect.signature(subject.generate_compact_catalog_trained_v1).parameters) == common
    assert set(inspect.signature(subject.validate_compact_catalog_trained_generation_v1).parameters) == common | {"report", "expected_report_sha256"}
    assert set(inspect.signature(subject.prepare_compact_catalog_trained_batch_prediction_v1).parameters) == common | {
        "report", "population_raw", "expected_generation_sha256", "expected_population_sha256", "occurrence_id"}


@pytest.mark.parametrize("damage", ["checkpoint_pin", "original_weights_pin", "catalog_pin", "dimension", "nan", "bool_conditioning",
    "empty_prefix", "bool_prefix", "long_prefix", "tuple_prefix", "context_bytes", "context_type",
    "steps_zero", "steps_bool", "steps_over", "prefix_origin", "bos_origin", "catalog_origin"])
def test_input_bindings_bounds_and_origins_refuse_before_owner_or_numerical_dispatch(retained, monkeypatch, damage):
    forbid_models(monkeypatch)
    values, kwargs = args(retained), options(retained)
    if damage == "checkpoint_pin": kwargs["expected_checkpoint_sha256"] = "0" * 64
    elif damage == "original_weights_pin":
        values[0]["model_state"]["output.bias"][0] += .125
        values[0]["weights_sha256"] = digest(values[0]["model_state"])
    elif damage == "catalog_pin": kwargs["expected_catalog_context_sha256"] = "0" * 64
    elif damage == "dimension": values[1].append(0.)
    elif damage == "nan": values[1][0] = float("nan")
    elif damage == "bool_conditioning": values[1][0] = True
    elif damage == "empty_prefix": values[2] = []
    elif damage == "bool_prefix": values[2] = [True]
    elif damage == "long_prefix": values[2] = [1] * 513
    elif damage == "tuple_prefix": values[2] = tuple(values[2])
    elif damage == "context_bytes":
        values[3] = b" " * (524288 + 1)
        kwargs["expected_catalog_context_sha256"] = sha(values[3])
    elif damage == "context_type": values[3] = values[3].decode()
    elif damage.startswith("steps_"): kwargs["max_new_tokens"] = {"steps_zero": 0, "steps_bool": True, "steps_over": 13}[damage]
    elif damage == "prefix_origin": kwargs["prefix_origin"] = "independently_verified"
    elif damage == "bos_origin": kwargs["prefix_origin"] = "bos_seed"
    else: kwargs["catalog_context_origin"] = "independently_verified"
    def no_owners(): pytest.fail("malformed original preflight reached operation owners")
    monkeypatch.setattr(subject, "_owners", no_owners)
    with pytest.raises(ValueError): subject.generate_compact_catalog_trained_v1(*values, **kwargs)


@pytest.mark.parametrize("damage", ["codec_profile", "lineage", "mask_bool", "unused_roles", "old_context", "context_utf8"])
def test_resealed_incompatible_state_or_full_catalog_refuses_without_a_model(retained, monkeypatch, damage):
    forbid_models(monkeypatch)
    values, kwargs = args(retained), options(retained)
    if damage == "codec_profile":
        values[0]["codec"] = deepcopy(retained["codec"])
        values[0]["codec_sha256"] = digest(values[0]["codec"])
    elif damage == "lineage": values[0]["initial_checkpoint_sha256"] = "0" * 64
    elif damage == "mask_bool": values[0]["training_mask"] = False
    else:
        ctx = context()
        if damage == "unused_roles": ctx["catalog"]["argument_roles"][2]["roles"] = []
        elif damage == "old_context": ctx = ctx["catalog"]
        values[3] = b"\xff" if damage == "context_utf8" else wire(ctx)
        kwargs["expected_catalog_context_sha256"] = sha(values[3])
    kwargs["expected_checkpoint_sha256"] = digest(values[0])
    with pytest.raises(ValueError): subject.generate_compact_catalog_trained_v1(*values, **kwargs)


@pytest.mark.parametrize("prefix_origin,catalog_origin,target", [("authored_fixture", "authored_fixture", False),
    ("target_derived_label", "authored_fixture", True), ("authored_fixture", "target_derived_label", True),
    ("caller_supplied_unverified", "caller_supplied_unverified", False)])
def test_declared_exposure_is_preserved_without_inventing_independence(retained, monkeypatch, prefix_origin, catalog_origin, target):
    forbid_models(monkeypatch)
    kwargs = options(retained)
    kwargs.update(prefix_origin=prefix_origin, catalog_context_origin=catalog_origin)
    report = subject.generate_compact_catalog_trained_v1(*args(retained, "complete"), **kwargs)
    assert report["prefix_origin"] == prefix_origin and report["catalog_context_origin"] == catalog_origin
    assert report["exposure"]["target_access"] is target and report["exposure"]["teacher_forcing"] is True
    assert report["exposure"]["encoder_sha256"] is None
    assert report["exposure"]["source_encoder_authenticated"] is False
    assert report["exposure"]["context_permission_verified"] is False
    assert report["numerical_forward_count"] == 0
    no_authority(report)


@pytest.mark.parametrize("damage", ["pin", "unknown_field", "mask_bool", "authority"])
def test_report_preflight_refuses_before_replay_and_hashing_is_not_validation(retained, evidence, monkeypatch, damage):
    forbid_models(monkeypatch)
    report = deepcopy(evidence["records"]["complete"])
    expected = digest(report)
    if damage == "pin": expected = "0" * 64
    elif damage == "unknown_field": report["unrecognized"] = True
    elif damage == "mask_bool": report["training_mask"] = False
    else: report["authority"][next(iter(report["authority"]))] = True
    if damage != "pin": expected = digest(report)
    def no_owners(): pytest.fail("invalid report preflight reached lazy owners")
    monkeypatch.setattr(subject, "_owners", no_owners)
    with pytest.raises(ValueError):
        subject.validate_compact_catalog_trained_generation_v1(report, *args(retained, "complete"),
            expected_report_sha256=expected, **options(retained))


def test_hash_only_helper_and_resealed_terminal_trace_differ_from_original_bound_replay(retained, evidence, monkeypatch):
    forbid_models(monkeypatch)
    report = deepcopy(evidence["records"]["complete"])
    report["exposure"]["teacher_forcing"] = False
    sealed = subject.compact_catalog_trained_generation_sha256(report)
    assert sealed == digest(report) != digest(evidence["records"]["complete"])
    with pytest.raises(ValueError, match="complete original-bound replay"):
        subject.validate_compact_catalog_trained_generation_v1(report, *args(retained, "complete"),
            expected_report_sha256=sealed, **options(retained))


@pytest.mark.parametrize("damage", ["population_pin", "missing_id", "duplicate_id", "source_pin", "unknown_field", "too_many", "duplicate_json_key"])
def test_adapter_original_population_refusals_precede_mandatory_numerical_replay(retained, evidence, monkeypatch, damage):
    forbid_models(monkeypatch)
    selected = population()
    occurrence = "runtime"
    if damage == "missing_id": occurrence = "not-in-population"
    elif damage == "duplicate_id": selected["rows"][1] = deepcopy(selected["rows"][0])
    elif damage == "source_pin": selected["rows"][0]["source_sha256"] = "invalid"
    elif damage == "unknown_field": selected["rows"][0]["catalog_context_sha256"] = sha(retained["context_raw"])
    elif damage == "too_many": selected["rows"] = [{**selected["rows"][0], "id": str(i)} for i in range(65)]
    raw = wire(selected)
    if damage == "duplicate_json_key": raw = b'{"partition":"duplicate",' + raw[1:]
    expected = "0" * 64 if damage == "population_pin" else sha(raw)
    def no_owners(): pytest.fail("invalid population reached replay owners")
    monkeypatch.setattr(subject, "_owners", no_owners)
    with pytest.raises(ValueError):
        subject.prepare_compact_catalog_trained_batch_prediction_v1(evidence["records"]["continuation"],
            *args(retained), raw, expected_generation_sha256=digest(evidence["records"]["continuation"]),
            expected_population_sha256=expected, occurrence_id=occurrence, **options(retained))


@pytest.mark.parametrize("anchor", ["generation", "scoring", "catalog"])
def test_changed_source_anchor_refuses_even_zero_forward_input(retained, monkeypatch, anchor):
    forbid_models(monkeypatch)
    module = {"generation": subject, "scoring": scoring, "catalog": tokens}[anchor]
    monkeypatch.setattr(module, "_SELF_SNAPSHOT", ("0" * 64, module._SELF_SNAPSHOT[1]))
    with pytest.raises(ValueError): subject.generate_compact_catalog_trained_v1(*args(retained, "complete"), **options(retained))


@pytest.mark.parametrize("damage", ["mask_bool", "count_bool", "authority", "prefix_bool", "owner_missing", "catalog_pin", "codec_profile"])
def test_changed_genuine_zero_forward_score_is_never_adopted_as_a_valid_trace(retained, monkeypatch, damage):
    forbid_models(monkeypatch)
    actual, calls = scoring.score_compact_catalog_trained_v1, []
    def changed(*values, **kwargs):
        report = actual(*values, **kwargs)
        calls.append(report["status"])
        if damage == "mask_bool": report["training_mask"] = False
        elif damage == "count_bool": report["numerical_forward_count"] = False
        elif damage == "authority": report["authority"][next(iter(report["authority"]))] = True
        elif damage == "prefix_bool": report["prefix_ids"][0] = True
        elif damage == "owner_missing": report["owner_pins"].pop()
        elif damage == "catalog_pin": report["catalog_sha256"] = "0" * 64
        else: report["inference_codec"] = deepcopy(report["training_codec"])
        return report
    # Negative return-boundary fault injection; the underlying score is genuine
    # and no successful numerical observation is fabricated.
    monkeypatch.setattr(scoring, "score_compact_catalog_trained_v1", changed)
    with pytest.raises(ValueError): subject.generate_compact_catalog_trained_v1(*args(retained, "complete"), **options(retained))
    assert calls == ["no_forward"]


@pytest.mark.parametrize("error_type,closing_failure", [(RuntimeError, False), (KeyboardInterrupt, False),
    (RuntimeError, True), (KeyboardInterrupt, True)])
def test_first_operational_failure_or_interrupt_survives_secondary_fence_failure(retained, monkeypatch, error_type, closing_failure):
    forbid_models(monkeypatch)
    failure, calls = error_type("authored refusal before model allocation"), []
    def failed_forward(*values, **kwargs):
        calls.append(True)
        if closing_failure: monkeypatch.setattr(subject, "_SELF_SNAPSHOT", ("0" * 64, subject._SELF_SNAPSHOT[1]))
        raise failure
    monkeypatch.setattr(trained, "_forward", failed_forward)
    with pytest.raises(error_type) as caught: subject.generate_compact_catalog_trained_v1(*args(retained), **options(retained))
    assert caught.value is failure and calls == [True]
    if closing_failure: assert any("closing" in note.lower() for note in getattr(failure, "__notes__", []))


@pytest.mark.parametrize("which", ["original", "cross_owner"])
def test_original_and_cross_owner_input_mutation_refuses_without_partial_report(retained, monkeypatch, which):
    forbid_models(monkeypatch)
    values, kwargs = args(retained, "complete"), options(retained)
    actual, calls = scoring.score_compact_catalog_trained_v1, []
    def changed(checkpoint, conditioning, prefix_ids, raw, **kw):
        result = actual(checkpoint, conditioning, prefix_ids, raw, **kw)
        calls.append(True)
        if which == "original": values[1][0] += .125
        else: prefix_ids.append(2)
        return result
    monkeypatch.setattr(scoring, "score_compact_catalog_trained_v1", changed)
    with pytest.raises(ValueError, match="inputs changed"):
        subject.generate_compact_catalog_trained_v1(*values, **kwargs)
    assert calls == [True]


@pytest.mark.parametrize("failure_mode", ["whole_bound", "trace_bound", "final_source_fence"])
def test_complete_serialization_and_trace_bounds_refuse_without_truncation(retained, evidence, monkeypatch, failure_mode):
    forbid_models(monkeypatch)
    if failure_mode == "trace_bound":
        # Deliberately reduced bound tests mechanics, not an 8MiB size benchmark.
        monkeypatch.setattr(subject, "MAX_TRACE_BYTES", 2)
        with pytest.raises(ValueError, match="whole trace byte bound"):
            subject.generate_compact_catalog_trained_v1(*args(retained, "complete"), **options(retained))
        return
    actual, calls = subject._wire, []
    reduced = len(wire(evidence["records"]["complete"])) - 1
    def final_wire(value, maximum=subject.MAX_REPORT_BYTES):
        if type(value) is dict and value.get("schema") == "legal-compact-catalog-trained-generation/v1":
            calls.append(True)
            if failure_mode == "whole_bound": return actual(value, reduced)
            raw = actual(value, maximum)
            monkeypatch.setattr(subject, "_SELF_SNAPSHOT", ("0" * 64, subject._SELF_SNAPSHOT[1]))
            return raw
        return actual(value, maximum)
    monkeypatch.setattr(subject, "_wire", final_wire)
    with pytest.raises(ValueError): subject.generate_compact_catalog_trained_v1(*args(retained, "complete"), **options(retained))
    assert calls == [True]


@pytest.mark.parametrize("wrapper", ["validation", "adapter"])
def test_enclosing_replay_receipt_whole_bound_refuses_without_partial_wrapper(retained, evidence, monkeypatch, wrapper):
    forbid_models(monkeypatch)
    report = evidence["records"]["complete"]
    def operation():
        if wrapper == "validation":
            return subject.validate_compact_catalog_trained_generation_v1(report, *args(retained, "complete"),
                expected_report_sha256=digest(report), **options(retained))
        return subject.prepare_compact_catalog_trained_batch_prediction_v1(report, *args(retained, "complete"),
            evidence["population_raw"], expected_generation_sha256=digest(report),
            expected_population_sha256=sha(evidence["population_raw"]), occurrence_id="runtime", **options(retained))
    baseline = operation()
    assert baseline["numerical_forward_count"] == baseline["replay_forward_count"] == 0
    reduced = len(wire(baseline)) - 1
    actual, calls = subject._wire, []
    def final_wire(value, maximum=subject.MAX_REPORT_BYTES):
        if type(value) is dict and value.get("schema") == baseline["schema"]:
            calls.append(True)
            return actual(value, reduced)
        return actual(value, maximum)
    # Deliberate smaller bound, not a full-size allocation/performance claim.
    monkeypatch.setattr(subject, "_wire", final_wire)
    with pytest.raises(ValueError): operation()
    assert calls == [True]
