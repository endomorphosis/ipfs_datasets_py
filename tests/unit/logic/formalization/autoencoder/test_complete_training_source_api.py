"""Public source training dispatch and native semantic preflight contracts."""
from copy import deepcopy
import importlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import complete_training as api


BACKENDS = [("source_training_v2", "source_decoder_384_v2"),
            ("structured_source_384", "structured_source_decoder_384")]


def component(**fields):
    return {"kind": "ui_component", "document": {
        "component_id": "accept", "role": "button", "privacy_sensitivity": "restricted",
        "presentation_classification": "interactive", **fields}}


def test_public_import_is_lazy_and_offline():
    subprocess.run([sys.executable, "-c", """
import sys
from ipfs_datasets_py.logic.formalization.autoencoder import complete_training
assert 'torch' not in sys.modules
assert 'sentence_transformers' not in sys.modules
assert 'ipfs_datasets_py.logic.formalization.autoencoder.structured_source_384' not in sys.modules
"""], check=True, capture_output=True, text=True)


@pytest.mark.parametrize("backend,name", BACKENDS)
@pytest.mark.parametrize("domain", ["intent_ir", "security_ir", "ui_ux_ir", "legal_ir"])
def test_training_dispatch_preserves_parent_and_config(monkeypatch, backend, name, domain):
    module = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder." + backend)
    calls = []
    def train(*args, **kwargs):
        calls.append((args, kwargs))
        return {"checkpoint": "sentinel"}
    monkeypatch.setattr(module, "train", train)
    rows = [{"target": component() if domain == "ui_ux_ir" else {}}]
    options = {"parent_projection": {"path": "parent", "sha256": "a" * 64}, "config": {"example": True}}
    assert getattr(api, "train_" + name)(domain, rows, rows, **options) == {"checkpoint": "sentinel"}
    assert calls == [((domain, rows, rows), options)]


@pytest.mark.parametrize("backend,name", BACKENDS)
@pytest.mark.parametrize("invalid", [{"privacy_sensitivity": "sensitive"},
                                    {"presentation_classification": "informational"}])
def test_native_ui_preflight_rejects_labels_before_any_fit(monkeypatch, backend, name, invalid):
    module = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder." + backend)
    monkeypatch.setattr(module, "train", lambda *a, **k: pytest.fail("invalid target reached fitting"))
    good, bad = [{"target": component()}], [{"target": component(**invalid)}]
    for train, tune in ((good, bad), (bad, good)):
        with pytest.raises(ValueError, match="closed vocabulary"):
            getattr(api, "train_" + name)("ui_ux_ir", train, tune)


@pytest.mark.parametrize("backend,name", BACKENDS)
def test_load_and_inference_preserve_exact_identity_and_options(monkeypatch, backend, name):
    module = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder." + backend)
    calls = []
    raw = SimpleNamespace(describe=lambda: {"dimension": 384},
        infer=lambda rows, **options: calls.append((rows, options)) or {"domain_id": "legal_ir", "rows": [], "proof_authority": False})
    def load(path, **options):
        assert path == "checkpoint.json"
        assert options == {"expected_sha256": "a" * 64, "expected_domain": "legal_ir"}
        return raw
    monkeypatch.setattr(module, "load_checkpoint", load)
    runtime = getattr(api, "load_" + name)("checkpoint.json", expected_sha256="a" * 64, expected_domain="legal_ir")
    rows = [{"source_text": "x", "id": "x", "embedding": [0.] * 384}]
    assert runtime.infer(rows, weight_ablation="zero_head")["proof_authority"] is False
    assert calls == [(rows, {"weight_ablation": "zero_head"})]


def test_source_text_helper_uses_verified_embedding_producer_and_target_free_rows(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    vectors = [[.25] * 384]
    def embed(texts, **options):
        assert texts == ["The operator must check the report."]
        assert options == {"snapshot_path": "verified-snapshot"}
        return vectors
    monkeypatch.setattr(source_embeddings_384, "embed_texts", embed)
    def infer(rows, **options):
        assert rows == [{"id": "input-0", "source_text": "The operator must check the report.", "embedding": vectors[0]}]
        assert options == {"weight_ablation": "zero_head"}
        return {"domain_id": "intent_ir", "rows": [], "proof_authority": False}
    result = api.infer_source_texts_384(SimpleNamespace(infer=infer),
        ["The operator must check the report."], snapshot_path="verified-snapshot", weight_ablation="zero_head")
    assert result["proof_authority"] is False


def test_invalid_ui_inference_fails_open_preserving_evidence_without_mutation():
    report = {"domain_id": "ui_ux_ir", "proof_authority": False, "rows": [
        {"candidate_ir": component(privacy_sensitivity="sensitive"), "status": "unqualified_candidate", "proof_authority": False},
        {"candidate_ir": component(), "status": "unqualified_candidate", "proof_authority": False}]}
    before = deepcopy(report)
    result = api._NativeCheckedSourceRuntime(SimpleNamespace(infer=lambda rows: report)).infer([])
    assert report == before
    bad, good = result["rows"]
    assert bad["status"] == "fail_open_native_component_invalid"
    assert bad["continue_planning"] is True and bad["native_component_validated"] is False
    assert bad["candidate_ir"] == before["rows"][0]["candidate_ir"]
    assert good["native_component_validated"] is True
    assert good["status"] == "unqualified_candidate" and good["proof_authority"] is False


def test_rejected_source_input_does_not_invoke_decoder():
    def infer(*a, **k):
        pytest.fail("invalid source reached decoder")
    with pytest.raises(ValueError, match="source texts"):
        api.infer_source_texts_384(SimpleNamespace(infer=infer), [""])
