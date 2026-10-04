"""Exact cached receipt reuse without model assets or encoder execution."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_embedding_reuse.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_embedding_reuse_subject", PATH)
corpus_fixture = read_module("gte_embedding_reuse_corpus_fixture",
                            Path(__file__).with_name("test_gte_multilingual_corpus.py"))
ASSET_PIN = "b" * 64
FIELDS = {
    "schema", "profile_id", "asset_manifest_sha256", "task_count", "cached_receipt_count",
    "missing_task_count", "status", "reused_receipts", "missing_tasks", "binding",
    "reused_receipts_sha256", "missing_tasks_sha256", "embeddings_generated",
    "encoder_inference_executed", "source_vectors_relabelled", "producer_execution_authenticated",
    "proof_authority",
}


@pytest.fixture
def inputs():
    rows = [corpus_fixture.row("train", document_id="original:train", group_id="family:train"),
        corpus_fixture.row("validation", split="validation", source_text="\ufeff \tCafe\u0301\n exact source ",
                           document_id="original:validation", group_id="family:validation"),
        corpus_fixture.row("sealed", split="test", evaluation_role="sealed", source_language="fr",
                           document_id="original:test", group_id="family:test")]
    tasks = corpus_fixture.prepare(rows)
    receipts = [corpus_fixture.receipt(task) for task in tasks["tasks"]]
    return {"rows": rows, "tasks": tasks, "receipts": receipts}


def prepare(tasks, receipts, **changes):
    arguments = {"expected_asset_manifest_sha256": ASSET_PIN}
    arguments.update(changes)
    return subject.prepare_cached_embedding_reuse(tasks, receipts, **arguments)


def test_complete_cache_is_ready_and_reuses_all_exact_receipts(inputs):
    result = prepare(inputs["tasks"], list(reversed(inputs["receipts"])))
    assert set(result) == FIELDS and result["schema"] == subject.SCHEMA
    assert result["status"] == "ready" and result["task_count"] == result["cached_receipt_count"] == 3
    assert result["missing_task_count"] == 0 and result["missing_tasks"] == []
    assert result["binding"]["status"] == "complete"
    assert result["reused_receipts"] == inputs["receipts"]
    assert result["reused_receipts_sha256"] == subject._CORPUS._digest(inputs["receipts"])
    assert result["missing_tasks_sha256"] == subject._CORPUS._digest([])
    for flag in ("embeddings_generated", "encoder_inference_executed", "source_vectors_relabelled",
                 "producer_execution_authenticated", "proof_authority"):
        assert result[flag] is False


def test_partial_cache_emits_only_original_missing_sources_and_split_metadata(inputs):
    validation = next(task for task in inputs["tasks"]["tasks"] if task["metadata"]["split"] == "validation")
    cached = [receipt for receipt in inputs["receipts"] if receipt["id"] != validation["id"]]
    result = prepare(inputs["tasks"], cached)
    assert result["status"] == "partial" and result["cached_receipt_count"] == 2
    assert result["missing_task_count"] == 1 and result["binding"]["status"] == "incomplete"
    assert result["missing_tasks"] == [validation]
    assert result["missing_tasks"][0]["source_text"] == "\ufeff \tCafe\u0301\n exact source "
    assert result["missing_tasks"][0]["metadata"]["document_id"] == "original:validation"
    assert result["missing_tasks"][0]["metadata"]["group_id"] == "family:validation"
    assert result["reused_receipts"] == cached
    assert result["missing_tasks_sha256"] == subject._CORPUS._digest([validation])
    assert result["binding"]["missing_receipt_ids"] == [validation["id"]]


def test_empty_cache_is_unavailable_with_all_tasks_still_available(inputs):
    result = prepare(inputs["tasks"], [])
    assert result["status"] == "unavailable" and result["cached_receipt_count"] == 0
    assert result["missing_task_count"] == 3 and result["missing_tasks"] == inputs["tasks"]["tasks"]
    assert result["reused_receipts"] == []
    assert result["asset_manifest_sha256"] == ASSET_PIN
    assert result["binding"]["asset_manifest_sha256"] is None


def test_empty_task_cohort_is_complete_without_encoder(inputs):
    tasks = corpus_fixture.prepare([])
    result = prepare(tasks, [])
    assert result["status"] == "ready" and result["task_count"] == 0
    assert result["cached_receipt_count"] == result["missing_task_count"] == 0
    assert result["binding"]["status"] == "complete"


def test_cached_numeric_leaf_types_are_preserved_instead_of_float_reencoding(inputs):
    receipts = deepcopy(inputs["receipts"])
    receipts[0]["embedding"] = [1] + [0] * 767
    result = prepare(inputs["tasks"], receipts)
    assert result["reused_receipts"] == receipts
    assert all(type(value) is int for value in result["reused_receipts"][0]["embedding"])
    assert all(type(value) is float for value in result["binding"]["bound_rows"][0]["embedding"])
    assert result["reused_receipts_sha256"] == subject._CORPUS._digest(receipts)


def test_inputs_and_nested_results_do_not_alias_each_other(inputs):
    before = deepcopy(inputs)
    result = prepare(inputs["tasks"], inputs["receipts"][:1])
    assert inputs == before
    result["reused_receipts"][0]["embedding"][0] = 99
    result["missing_tasks"][0]["metadata"]["group_id"] = "changed"
    result["binding"]["bound_rows"][0]["metadata"]["group_id"] = "changed"
    assert inputs == before
    fresh = prepare(inputs["tasks"], inputs["receipts"][:1])
    inputs["receipts"][0]["embedding"][0] = 42
    inputs["tasks"]["tasks"][1]["source_text"] = "changed"
    assert fresh["reused_receipts"][0]["embedding"][0] == 1.
    assert fresh["missing_tasks"][0]["source_text"] == before["tasks"]["tasks"][1]["source_text"]


def test_bounded_iterables_are_consumed_once_and_keep_canonical_order(inputs):
    result = prepare((task for task in reversed(inputs["tasks"]["tasks"])),
                     (receipt for receipt in reversed(inputs["receipts"])), max_rows=3)
    assert result["status"] == "ready" and result["reused_receipts"] == inputs["receipts"]
    assert result["binding"]["corpus_inventory_sha256"] is None


@pytest.mark.parametrize("kind", ("tasks", "receipts"))
def test_bounded_iterables_stop_before_unbounded_input(kind, inputs):
    pulls = []
    base = inputs["tasks"]["tasks"] if kind == "tasks" else inputs["receipts"]
    def values():
        for index in range(1000):
            pulls.append(index)
            yield base[index % len(base)]
    arguments = {"tasks": inputs["tasks"]["tasks"][:2], "receipts": []}
    arguments[kind] = values()
    with pytest.raises(ValueError, match="exceeds max_rows"):
        prepare(arguments["tasks"], arguments["receipts"], max_rows=2)
    assert pulls == [0, 1, 2]


@pytest.mark.parametrize("limit", (0, -1, 4097, True, False, 3.0, None, "3"))
def test_row_bound_is_explicit_and_cannot_exceed_4096(limit, inputs):
    with pytest.raises(ValueError):
        prepare(inputs["tasks"], [], max_rows=limit)


def test_manifest_and_receipt_lists_both_obey_the_row_bound(inputs):
    with pytest.raises(ValueError, match="tasks exceeds max_rows"):
        prepare(inputs["tasks"], [], max_rows=2)
    with pytest.raises(ValueError, match="receipts exceeds max_rows"):
        prepare(inputs["tasks"]["tasks"][:1], inputs["receipts"] * 2, max_rows=3)


@pytest.mark.parametrize("pin", (None, "", "b" * 63, "b" * 65, "B" * 64, "g" * 64, True, 123))
def test_selected_asset_hash_is_required_even_for_empty_cache(pin, inputs):
    with pytest.raises(ValueError):
        prepare(inputs["tasks"], [], expected_asset_manifest_sha256=pin)


def test_cache_from_another_asset_generation_cannot_silently_replace_selection(inputs):
    with pytest.raises(ValueError, match="selected asset manifest"):
        prepare(inputs["tasks"], inputs["receipts"], expected_asset_manifest_sha256="c" * 64)


@pytest.mark.parametrize("field,value", (
    ("source_sha256", "c" * 64),
    ("profile_id", "thenlper/gte-small:d384"),
    ("profile_id", subject.PROFILE_ID.replace("tokens8192", "tokens32768")),
    ("dimension", 384), ("dimension", 8), ("dimension", True),
    ("embedding", [1.] + [0.] * 383), ("embedding", [1.] + [0.] * 7),
    ("embedding", [0.] * 768), ("embedding", [float("nan")] + [0.] * 767),
    ("token_count_including_special_tokens", 8193), ("token_count_including_special_tokens", True),
    ("token_input_sha256", "invalid"), ("truncated", True), ("normalized", False),
    ("asset_manifest_sha256", "c" * 64), ("schema", "unsupported/v1"),
))
def test_incompatible_cached_receipts_fail_entire_admission(field, value, inputs):
    receipts = deepcopy(inputs["receipts"])
    receipts[0][field] = value
    with pytest.raises(ValueError):
        prepare(inputs["tasks"], receipts)


@pytest.mark.parametrize("mutation", ("duplicate", "unexpected_id", "extra_field", "mixed_assets"))
def test_no_remapping_deduplication_or_silent_drops(mutation, inputs):
    receipts = deepcopy(inputs["receipts"])
    if mutation == "duplicate":
        receipts.append(deepcopy(receipts[0]))
    elif mutation == "unexpected_id":
        receipts[0]["id"] = "other-source"
    elif mutation == "extra_field":
        receipts[0]["unrecognized"] = True
    else:
        receipts[1]["asset_manifest_sha256"] = "c" * 64
    with pytest.raises(ValueError):
        prepare(inputs["tasks"], receipts)


@pytest.mark.parametrize("mutation", ("source", "id", "profile", "count", "digest", "split_role", "duplicate"))
def test_strict_original_task_contract_is_retained(mutation, inputs):
    tasks = deepcopy(inputs["tasks"])
    if mutation == "source":
        tasks["tasks"][0]["source_text"] += " changed"
    elif mutation == "id":
        tasks["tasks"][0]["id"] = "changed"
    elif mutation == "profile":
        tasks["profile_id"] = "other"
    elif mutation == "count":
        tasks["task_count"] = 2
    elif mutation == "digest":
        tasks["tasks_sha256"] = "0" * 64
    elif mutation == "split_role":
        tasks["tasks"][0]["metadata"].update(split="train", evaluation_role="sealed")
    else:
        tasks["tasks"].append(deepcopy(tasks["tasks"][0]))
        tasks["task_count"] += 1
    if mutation in ("source", "id", "split_role", "duplicate"):
        tasks["tasks_sha256"] = subject._CORPUS._digest(tasks["tasks"])
    with pytest.raises(ValueError):
        prepare(tasks, [])


@pytest.mark.parametrize("kind", ("tasks", "receipts"))
@pytest.mark.parametrize("value", (None, "rows", b"rows", 123))
def test_unsupported_iterables_fail_cleanly(kind, value, inputs):
    arguments = {"tasks": inputs["tasks"], "receipts": []}
    arguments[kind] = value
    with pytest.raises(ValueError):
        prepare(arguments["tasks"], arguments["receipts"])


def test_no_model_or_producer_imports_for_complete_cache_without_local_assets(inputs, tmp_path):
    task_path, receipt_path = tmp_path / "tasks.json", tmp_path / "receipts.json"
    task_path.write_text(json.dumps(inputs["tasks"]))
    receipt_path.write_text(json.dumps(inputs["receipts"]))
    program = """import builtins,importlib.util,json,sys
original_import=builtins.__import__
def guarded(name,*args,**kwargs):
    assert name.split('.')[0] not in ('torch','transformers','numpy','sentence_transformers')
    assert not name.endswith('source_embeddings_768')
    return original_import(name,*args,**kwargs)
builtins.__import__=guarded
spec=importlib.util.spec_from_file_location('isolated_cache',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
tasks=json.loads(open(sys.argv[2]).read());receipts=json.loads(open(sys.argv[3]).read())
result=module.prepare_cached_embedding_reuse(tasks,receipts,expected_asset_manifest_sha256='b'*64)
assert result['status']=='ready' and result['cached_receipt_count']==3
assert result['encoder_inference_executed'] is False and result['embeddings_generated'] is False
assert not any(name in sys.modules for name in ('torch','transformers','numpy','ipfs_datasets_py'))
assert not any('source_embeddings_768' in name or 'gte_multilingual_profile' in name for name in sys.modules)
"""
    subprocess.run([sys.executable, "-I", "-c", program, str(PATH), str(task_path), str(receipt_path)], check=True)
