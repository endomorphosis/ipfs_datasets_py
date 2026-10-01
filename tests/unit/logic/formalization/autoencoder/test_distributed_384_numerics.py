"""Actual four-domain ridge equivalence and hostile shard rejection."""
from copy import deepcopy

import numpy as np
import pytest

from .test_structured_source_384 import parent, rows
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as reference
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import numerics as n
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.contracts import digest, write_json


def grouped(domain, split):
    return [{**row, "split": split, "group_id": split + str(i // 2)}
            for i, row in enumerate(rows(domain, split))]


@pytest.fixture(params=reference.DOMAINS)
def round_data(request, parent, tmp_path):
    domain = request.param
    train, tune = grouped(domain, "train"), grouped(domain, "validation")
    base = reference.train(domain, rows(domain, "train"), rows(domain, "validation"),
                           parent_projection=parent)["checkpoint"]
    path = write_json(tmp_path / "base.json", base)
    plan = n.make_plan(path, train, tune, source_descriptor={"schema": "ir384-corpus-source/v1",
        "description": "authored unit controls, synthetic vectors"}, shard_size=2, machine_count=2)
    updates = [n.compute_update(plan, base, n.shard_rows(plan, train, s["shard_id"]), s["shard_id"])
               for s in plan["shards"]]
    return domain, train, tune, base, plan, updates


def test_distributed_fit_matches_existing_central_ridge(round_data):
    domain, train, tune, base, plan, updates = round_data
    before = deepcopy((base, plan, updates, tune))
    result = n.merge_updates(plan, base, updates, tune)
    actual = result["checkpoint"]
    np.testing.assert_allclose(actual["head_state"]["weights"], base["head_state"]["weights"], atol=2e-9, rtol=2e-8)
    np.testing.assert_allclose(actual["input_transform"]["mean"], base["input_transform"]["mean"], atol=1e-12)
    assert actual["input_transform"]["scale"] == pytest.approx(base["input_transform"]["scale"], rel=1e-12)
    assert actual["head_state"]["bias"] == base["head_state"]["bias"]
    assert actual["projection_state"] == base["projection_state"]
    assert actual["parent_sha256"] == base["parent_sha256"]
    assert actual["training"]["selected_validation"] == base["training"]["selected_validation"]
    assert actual["training"]["head_weights_averaged"] is False
    assert n.merge_updates(plan, base, list(reversed(updates)), tune) == result
    assert before == (base, plan, updates, tune)
    assert [s["machine_index"] for s in plan["shards"]] == [0, 1, 0]


def test_frozen_projection_weights_actually_condition_worker_updates(round_data):
    _, train, _, base, plan, updates = round_data
    changed = deepcopy(base)
    changed["projection_state"]["projection_up.bias"][0] += .1
    changed["projection_sha256"] = reference.digest(changed["projection_state"])
    with pytest.raises(ValueError, match="base checkpoint"):
        n.compute_update(plan, changed, n.shard_rows(plan, train, plan["shards"][0]["shard_id"]),
                         plan["shards"][0]["shard_id"])


@pytest.mark.parametrize("change", ["missing", "duplicate", "foreign", "nan", "bad_label", "tuning", "weight_tamper"])
def test_reject_incompatible_or_corrupt_updates(round_data, change):
    _, train, tune, base, plan, updates = deepcopy(round_data)
    if change == "missing": updates.pop()
    elif change == "duplicate": updates[1] = deepcopy(updates[0])
    elif change == "foreign": updates[0]["plan_id"] = "f" * 64
    elif change == "nan": updates[0]["statistics"]["projected"][0][0] = float("nan")
    elif change == "bad_label": updates[0]["statistics"]["class_ids"][0][0] = 99999
    elif change == "tuning": tune[0]["source_text"] += " altered"
    else: base["head_state"]["weights"][0][0] += .1
    if change in ("foreign", "bad_label"):
        updates[0]["update_id"] = digest({k:v for k,v in updates[0].items() if k != "update_id"})
    with pytest.raises(ValueError):
        n.merge_updates(plan, base, updates, tune)


def test_no_tuning_rows_may_be_given_to_worker(round_data):
    _, train, tune, base, plan, _ = round_data
    with pytest.raises(ValueError, match="shard inputs"):
        n.compute_update(plan, base, tune[:2], plan["shards"][0]["shard_id"])


def test_source_and_group_leakage_rejected_before_dispatch(round_data, tmp_path):
    _, train, tune, base, _, _ = deepcopy(round_data)
    tune[0]["group_id"] = train[0]["group_id"]
    with pytest.raises(ValueError, match="group_id overlap"):
        n.make_plan(write_json(tmp_path / "leak-parent.json", base), train, tune,
                    source_descriptor={"schema":"ir384-corpus-source/v1", "description":"test"})


def test_no_unseen_scalar_classes_added_from_tuning(round_data, tmp_path):
    domain, train, tune, base, _, _ = deepcopy(round_data)
    if domain != "intent_ir": pytest.skip("Intent representative of frozen scalar vocabulary")
    tune[0]["target"]["document"]["actor"] = "never-in-training"
    with pytest.raises(ValueError, match="outside training vocabulary"):
        n.make_plan(write_json(tmp_path / "vocab-parent.json", base), train, tune,
                    source_descriptor={"schema":"ir384-corpus-source/v1", "description":"test"})
