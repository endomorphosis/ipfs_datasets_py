"""Real bounded formula training/replay, with offline-only Hub transport fixtures."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_formula_exchange as exchange
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import native_formula_training as native
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_learning as legal
from tests.unit.huggingface.test_autoencoder_incremental import FakeHub
from tests.unit.huggingface.test_autoencoder_incremental_download import FakeClient

ROOT = Path(exchange.__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    import torch
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module", params=["intent_ir", "security_ir", "ui_ux_ir", "legal_ir"])
def trained(request):
    domain = request.param
    if domain == "legal_ir":
        corpus = json.loads((ROOT / "tests/fixtures/legal_formula_learning/v1.json").read_text())
        def train(parent=None):
            return legal.train_decoder(corpus["train"], corpus["tuning"], checkpoint=parent,
                epochs=1, max_seconds=30, hidden_size=8, embedding_dim=8)
        parent = train()
        child = train(parent["checkpoint"])
    else:
        file = ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_native_formula_training.py"
        spec = importlib.util.spec_from_file_location("_formula_exchange_training_fixture", file)
        fixtures = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixtures)
        cp, training, tuning = fixtures._build(domain)
        def train(parent=None):
            return native.train_native_formula(parent or cp, training, tuning, epochs=1,
                max_seconds=30, max_optimizer_steps=1)
        parent = train()
        child = train(parent["checkpoint"])
    return domain, parent, child, train


def test_anchor_update_exact_optimizer_selection_resume_and_idempotence(trained, tmp_path):
    domain, parent, child, train = trained
    anchor = exchange.stage_formula_anchor(parent, tmp_path / "anchor")
    stage = exchange.stage_formula_update(parent, child, tmp_path / "update")
    assert exchange.stage_formula_update(parent, child, tmp_path / "update") == stage
    loaded_parent = exchange.load_formula_bundle(anchor["manifest_path"])["result"]
    bundle = exchange.load_formula_bundle(stage["manifest_path"], parent_result=loaded_parent,
        expected_binding=exchange.formula_binding(parent))
    assert bundle["result"] == child
    assert bundle["binding"]["domain_id"] == domain
    assert train(bundle["result"]["checkpoint"])["checkpoint"] == train(child["checkpoint"])["checkpoint"]
    assert all(bundle[key] is False for key in exchange.FALSE)
    assert not bundle["registration_performed"]
    payload = json.loads(next(raw for path, raw in bundle["snapshots"].items() if "/artifacts/" in path))
    assert payload["schema"] == exchange.PATCH_SCHEMA
    assert all(op["path"][0] == "report" or op["path"][:2] in
        [["checkpoint", key] for key in exchange._MUTABLE[bundle["binding"]["runtime_version"]]]
        for op in payload["operations"])
    if domain != "legal_ir":
        assert loaded_parent["checkpoint"]["latest"]["progress"]["row_cursor"] == 1
        assert bundle["result"]["checkpoint"]["latest"]["adam"] == child["checkpoint"]["latest"]["adam"]
        assert bundle["result"]["checkpoint"]["selected"] == child["checkpoint"]["selected"]


def test_offline_transport_pinned_anchor_update_and_repeat_receive(trained, tmp_path):
    _, parent, child, _ = trained
    hub = FakeHub()
    anchor = exchange.stage_formula_anchor(parent, tmp_path / "anchor")
    stage = exchange.stage_formula_update(parent, child, tmp_path / "update")
    dry = exchange.publish_formula_bundle(stage["manifest_path"], parent_result=parent)
    assert not dry["uploaded"] and dry["formula_reference"] is None
    published_anchor = exchange.publish_formula_bundle(anchor["manifest_path"], upload=True, api=hub)
    published = exchange.publish_formula_bundle(stage["manifest_path"], parent_result=parent, upload=True, api=hub)
    again = exchange.publish_formula_bundle(stage["manifest_path"], parent_result=parent, upload=True, api=hub)
    assert again["remote_already_present"]
    assert published_anchor["full_checkpoint_uploaded"] and not published["full_checkpoint_uploaded"]
    client = FakeClient(hub.files)
    got_parent = exchange.receive_formula_bundle(published_anchor["formula_reference"], tmp_path / "receive-anchor",
        allow_weight_download=True, client=client)["result"]
    result = exchange.receive_formula_bundle(published["formula_reference"], tmp_path / "receive-update",
        parent_result=got_parent, expected_binding=exchange.formula_binding(parent),
        allow_weight_download=True, client=client)
    assert result["result"] == child and result["downloaded_files"] == 2
    calls = len(client.calls)
    retry = exchange.receive_formula_bundle(published["formula_reference"], tmp_path / "receive-update",
        parent_result=got_parent, allow_weight_download=True, client=client)
    assert retry["result"] == child and not retry["weights_downloaded"] and len(client.calls) == calls
    assert all(result[key] is False for key in exchange.FALSE)


def test_wrong_parent_or_frozen_config_never_stages(trained, tmp_path):
    _, parent, child, _ = trained
    with pytest.raises(ValueError, match="parent|progress"):
        exchange.stage_formula_update(child, parent, tmp_path / "backwards")
    altered = copy.deepcopy(child)
    altered["checkpoint"]["config"]["learning_rate"] /= 2
    altered["report"]["checkpoint_sha256"] = exchange._digest(altered["checkpoint"])
    with pytest.raises(ValueError, match="parent|config"):
        exchange.stage_formula_update(parent, altered, tmp_path / "config")
    assert not (tmp_path / "backwards").exists() and not (tmp_path / "config").exists()


@pytest.mark.parametrize("field", ["implementation", "lineage_id", "vocabulary", "training_manifest_sha256"])
def test_source_runtime_vocabulary_and_target_binding_cannot_drift(trained, tmp_path, field):
    domain, parent, child, _ = trained
    changed = copy.deepcopy(child)
    cp = changed["checkpoint"]
    if field == "implementation":
        cp[field] = {"scope": "foreign", "files": {}}
    elif field == "lineage_id":
        cp[field] = "legacy_hub_v1"
    elif field == "training_manifest_sha256":
        cp[field] = "e" * 64
    elif domain == "legal_ir":
        cp["codec"]["source_vocabulary"].append("foreign-atom")
    else:
        cp["feature_space"]["columns"] = cp["feature_space"]["columns"][:-1]
    # Preserve report/checkpoint hash consistency so validation actually reaches
    # the changed producer/profile/codec rather than only a stale outer digest.
    changed["report"]["checkpoint_sha256"] = exchange._digest(cp)
    with pytest.raises(ValueError):
        exchange.stage_formula_update(parent, changed, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("key", ["qualified", "admitted", "formalized", "semantic_correctness_verified"])
def test_no_transport_authority_from_checkpoints_or_reports(trained, tmp_path, key):
    _, parent, _, _ = trained
    altered = copy.deepcopy(parent)
    altered["checkpoint"][key] = True
    with pytest.raises(ValueError):
        exchange.stage_formula_anchor(altered, tmp_path / "bad-checkpoint")
    altered = copy.deepcopy(parent)
    altered["report"][key] = True
    with pytest.raises(ValueError):
        exchange.stage_formula_anchor(altered, tmp_path / "bad-report")


@pytest.mark.parametrize("claimed", [False, None, 1])
def test_missing_false_or_nonboolean_training_claim_cannot_exchange(trained, tmp_path, claimed):
    _, parent, child, _ = trained
    altered_parent, altered_child = copy.deepcopy(parent), copy.deepcopy(child)
    for result in (altered_parent, altered_child):
        if claimed is None:
            result["report"].pop("training_executed")
        else:
            result["report"]["training_executed"] = claimed
    # The numerical state still contains completed, valid optimizer steps.
    # False/missing execution claims cannot enter as either anchors or updates.
    assert exchange._steps(altered_parent) > 0
    assert exchange._steps(altered_child) > exchange._steps(parent)
    with pytest.raises(ValueError, match="explicitly completed training"):
        exchange.stage_formula_anchor(altered_parent, tmp_path / "anchor")
    with pytest.raises(ValueError, match="explicitly completed training"):
        exchange.stage_formula_update(parent, altered_child, tmp_path / "update")
    assert not (tmp_path / "anchor").exists() and not (tmp_path / "update").exists()


def test_tampering_receiver_binding_download_optin_and_wrong_parent(trained, tmp_path):
    _, parent, child, _ = trained
    stage = exchange.stage_formula_update(parent, child, tmp_path / "stage")
    binding = {**exchange.formula_binding(parent), "domain_id": "foreign"}
    with pytest.raises(ValueError, match="binding"):
        exchange.load_formula_bundle(stage["manifest_path"], parent_result=parent, expected_binding=binding)
    wrong = copy.deepcopy(parent)
    wrong["report"]["elapsed_seconds"] = 100
    with pytest.raises(ValueError, match="parent differs"):
        exchange.load_formula_bundle(stage["manifest_path"], parent_result=wrong)
    with pytest.raises(ValueError, match="exact parent"):
        exchange.load_formula_bundle(stage["manifest_path"])
    hub = FakeHub()
    ref = exchange.publish_formula_bundle(stage["manifest_path"], parent_result=parent, upload=True, api=hub)["formula_reference"]
    client = FakeClient(hub.files)
    with pytest.raises(ValueError, match="explicit opt-in"):
        exchange.receive_formula_bundle(ref, tmp_path / "disabled", client=client)
    assert not client.calls
    with pytest.raises(ValueError, match="before download"):
        exchange.receive_formula_bundle(ref, tmp_path / "wrong-binding", expected_binding=binding,
            allow_weight_download=True, client=client)
    assert not client.calls
    with pytest.raises(ValueError, match="exact local parent"):
        exchange.receive_formula_bundle(ref, tmp_path / "missing-parent", allow_weight_download=True, client=client)
    assert len(client.calls) == 1 and "/manifests/" in client.calls[0][1]
    manifest = json.loads(Path(stage["manifest_path"]).read_bytes())
    payload = Path(stage["manifest_path"]).parent / manifest["payload_filename"]
    payload.write_bytes(payload.read_bytes() + b" ")
    with pytest.raises(ValueError, match="identity changed"):
        exchange.load_formula_bundle(stage["manifest_path"], parent_result=parent)


def test_postimage_rejects_duplicate_overlap_bad_preimage_and_caps(monkeypatch):
    parent = {"checkpoint": {"a": [1., 2., 3.]}, "report": {}}
    op = {"path": ["checkpoint", "a", 1], "before_sha256": exchange._digest(2.), "value": 4.}
    assert exchange._replay(parent, {"schema": exchange.PATCH_SCHEMA, "operations": [op]})["checkpoint"]["a"] == [1., 4., 3.]
    for ops in ([op, op], [{**op, "before_sha256": "f" * 64}],
                [op, {"path": ["checkpoint"], "before_sha256": exchange._digest(parent["checkpoint"]), "value": {}}]):
        with pytest.raises(ValueError):
            exchange._replay(parent, {"schema": exchange.PATCH_SCHEMA, "operations": ops})
    with pytest.raises(ValueError, match="duplicate"):
        exchange._decode(b'{"x":1,"x":2}', 100)
    with pytest.raises(ValueError, match="canonical"):
        exchange._decode(b'{"x": 1}', 100)
    with pytest.raises(ValueError, match="cap"):
        exchange._raw(parent, 5)
    monkeypatch.setattr(exchange, "MAX_OPERATIONS", 0)
    with pytest.raises(ValueError, match="cap"):
        exchange._replay(parent, {"schema": exchange.PATCH_SCHEMA, "operations": [op]})


def test_legacy_state_cannot_enter_formula_transport(tmp_path):
    with pytest.raises(ValueError, match="unsupported formula lineage"):
        exchange.stage_formula_anchor({"checkpoint": {"schema": "modal-autoencoder/v1"},
                                       "report": {"training_executed": True}}, tmp_path)
