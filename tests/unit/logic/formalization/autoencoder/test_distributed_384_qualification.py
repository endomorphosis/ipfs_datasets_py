"""Actual checkpoint predictions are reprojected; labels cannot replace them."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from .test_structured_source_384 import parent, rows
from .test_distributed_384_numerics import grouped
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as decoder
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import contracts as c, numerics, runner
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import qualification as api
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context

REPO = Path(__file__).resolve().parents[5]
CLI = REPO / "scripts/ops/autoencoder/run_distributed_384.py"


@pytest.fixture
def campaign(parent, tmp_path):
    domain = "legal_ir"
    base = decoder.train(domain, rows(domain, "train"), rows(domain, "validation"), parent_projection=parent)["checkpoint"]
    train, tune = grouped(domain, "train"), grouped(domain, "validation")
    root = tmp_path / "round"
    runner.prepare_round(domain, c.write_json(tmp_path / "train.json", train),
        c.write_json(tmp_path / "tune.json", tune), root,
        base_path=c.write_json(tmp_path / "base.json", base),
        source_descriptor=dict(schema="ir384-corpus-source/v1", description="authored unit vectors and declarations"), shard_size=2)
    plan = c.read_json(root / "plan.json")
    updates = [numerics.compute_update(plan, base, numerics.shard_rows(plan, train, s["shard_id"]), s["shard_id"])
               for s in plan["shards"]]
    checkpoint = numerics.merge_updates(plan, base, updates, tune)["checkpoint"]
    checkpoint_path = c.write_json(tmp_path / "merged.json", checkpoint)
    return root, checkpoint_path, plan, checkpoint, tune


def context_file(tmp_path, campaign):
    root, path, plan, checkpoint, rows = campaign
    selected = rows[0]
    target_free = [{k: selected[k] for k in ("id", "source_text", "embedding")}]
    predicted = decoder.Runtime(checkpoint).infer(target_free)["rows"][0]["candidate_ir"]
    context = bind_context("legal_ir", predicted, selected["source_text"],
        {"formula_inputs": [{"requirement_id": "FOL", "formula": "forall x. reviewed(x)"}]})
    value = dict(schema=api.CONTEXTS_SCHEMA, plan_id=plan["plan_id"], checkpoint_sha256=c.file_ref(path)["sha256"],
                 rows=[dict(id=selected["id"], context=context)], **c.FALSE)
    return c.write_json(tmp_path / "context.json", value)


def test_real_checkpoint_inference_then_explicit_context_projection(campaign, tmp_path):
    root, checkpoint_path, plan, checkpoint, rows = campaign
    before = c.file_ref(checkpoint_path)
    contexts = context_file(tmp_path, campaign)
    summary = api.qualify_round(root, checkpoint_path, tmp_path / "reports", contexts_path=contexts,
        row_ids=[rows[0]["id"]], required_families=["deontic", "first_order"])
    assert summary["rows"] == 1 and summary["full_validation_rows"] == 6 and summary["selected_subset"]
    assert summary["all_required_families_supported"]
    assert not summary["all_requested_native_checks_passed"] and not summary["target_access"]
    assert not summary["context_inferred_by_model"] and all(summary[k] is False for k in c.FALSE)
    inference = c.read_json(tmp_path / "reports" / "inference-inputs.json")
    assert all(set(row) == {"id", "source_text", "embedding"} for row in inference)
    observed = c.read_json(summary["records"][0]["report_path"])
    predicted = c.read_json(tmp_path / "reports" / "inference.json")[0]
    assert observed["candidate_sha256"] == c.digest(predicted["candidate_ir"])
    assert summary["records"][0]["candidate_sha256"] == observed["candidate_sha256"]
    assert before == c.file_ref(checkpoint_path)


@pytest.mark.parametrize("change", ["checkpoint", "plan", "row_id", "candidate", "authority", "duplicate", "extra", "null"])
def test_context_batch_cannot_cross_checkpoint_source_or_row_boundaries(campaign, tmp_path, change):
    root, checkpoint_path, plan, checkpoint, rows = campaign
    value = c.read_json(context_file(tmp_path, campaign))
    if change == "checkpoint": value["checkpoint_sha256"] = "f" * 64
    elif change == "plan": value["plan_id"] = "f" * 64
    elif change == "row_id": value["rows"][0]["id"] = "unknown"
    elif change == "candidate": value["rows"][0]["context"]["candidate_sha256"] = "f" * 64
    elif change == "authority": value["proof_authority"] = True
    elif change == "duplicate": value["rows"].append(deepcopy(value["rows"][0]))
    elif change == "null": value["rows"][0]["context"] = None
    else: value["gold_targets"] = []
    bad = c.write_json(tmp_path / "bad.json", value)
    output = tmp_path / "never-created"
    with pytest.raises(ValueError):
        api.qualify_round(root, checkpoint_path, output, contexts_path=bad)
    assert not output.exists()


def test_detached_base_cannot_impersonate_completed_round(campaign, tmp_path):
    root, _, _, _, _ = campaign
    with pytest.raises(ValueError, match="round differs"):
        api.qualify_round(root, root / "base.json", tmp_path / "never-created")


def test_contextless_report_stays_incomplete_and_requires_fresh_evidence_directory(campaign, tmp_path):
    root, checkpoint_path, _, _, _ = campaign
    result = api.qualify_round(root, checkpoint_path, tmp_path / "reports")
    assert result["rows"] == 6 and not result["selected_subset"]
    assert not result["all_required_families_supported"]
    with pytest.raises(ValueError, match="fresh projection"):
        api.qualify_round(root, checkpoint_path, tmp_path / "reports")


def test_actual_project_cli(campaign, tmp_path):
    root, checkpoint_path, _, _, rows = campaign
    contexts = context_file(tmp_path, campaign)
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    process = subprocess.run([sys.executable, str(CLI), "project", "--round-dir", str(root),
        "--checkpoint", str(checkpoint_path), "--output-dir", str(tmp_path / "cli-report"),
        "--contexts", str(contexts), "--row-id", rows[0]["id"], "--require-family", "first_order"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["family_counts"]["first_order"]["supported"] == 1
    assert report["family_counts"]["first_order"]["native_checks_passed"] == 0


def test_actual_projection_family_catalog_cli():
    process = subprocess.run([sys.executable, str(CLI), "projection-families", "--domain", "security_ir"],
        cwd=REPO, capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert len(report["family_inventory"]) == 40
    assert {"program", "first_order", "deontic", "tdfol", "dcec", "frame_logic"} <= set(report["default_required_families"])
