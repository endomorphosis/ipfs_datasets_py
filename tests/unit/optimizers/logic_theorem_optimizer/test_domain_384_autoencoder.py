"""Portable numerical transfer/inference tests; synthetic vectors are not GTE evidence."""
from copy import deepcopy
import hashlib
import json

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as legal


@pytest.fixture(scope="module")
def parent():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        binding = dict(domain="legal_ir", lineage_id="current_legal_v2", dimension=384,
                       runtime_profile="unit-test-authored/v1", core_sha256="a" * 64)
        rows = [dict(id="legal-training", source_text="The agency must save the report.",
            latent=[.5] + [0.] * 383, embedding=[.3] + [0.] * 383,
            canonical_ir={"rules": [dict(modality="O", actor="agency", action="save", object="report",
                conditions=[], exceptions=[], temporal=[])]})]
        checkpoint = legal.build_checkpoint(binding, rows, [], hidden_size=16, token_embedding_dim=8,
                                             projection_width=4, batch_size=1)
        return legal.train(checkpoint, rows, [], epochs=1, max_seconds=30)["checkpoint"]
    finally:
        torch.set_num_threads(previous)


def target(domain):
    if domain == "intent_ir":
        return dict(kind="intent_rich_ast", document=dict(kind="atom", actor="operator", action="save",
            object="report", modality="required"))
    if domain == "ui_ux_ir":
        return dict(kind="ui_component", document=dict(component_id="submit", role="button"))
    from ipfs_datasets_py.logic.software_verification.program import ProgramExpression
    return dict(kind="program_expression", document=ProgramExpression("expr:one", "literal", "integer",
        source_ref_ids=("authored-source",), attributes={"value": 1}).to_dict())


def row(domain, split):
    return dict(id=split, source_text=split + " authored source", embedding=[.5 if split == "train" else .6] + [0.] * 383,
                target=target(domain))


@pytest.fixture(scope="module", params=subject.DOMAINS)
def trained(request, parent):
    domain = request.param
    before = deepcopy(parent)
    result = subject.train(domain, [row(domain, "train")], [row(domain, "validation")],
        parent_projection=parent, config=dict(epochs=3, batch_size=1, max_seconds=30))
    assert parent == before
    return result["checkpoint"]


def inference_row(checkpoint):
    return {key: value for key, value in row(checkpoint["domain_id"], "validation").items() if key != "target"}


def test_runtime_consumes_weights_and_restores_threads(trained):
    runtime = subject.Runtime(trained)
    row = inference_row(trained)
    previous = torch.get_num_threads()
    baseline = runtime.infer([row])
    assert torch.get_num_threads() == previous
    changed = deepcopy(trained)
    changed["model_state"]["projection_up.bias"][0] += .125
    changed["weights_sha256"] = subject.digest(changed["model_state"])
    observed = subject.Runtime(changed).infer([row])["rows"][0]
    original = baseline["rows"][0]
    assert observed["reconstructed_embedding"][0] == pytest.approx(original["reconstructed_embedding"][0] + .125, abs=1e-5)
    assert observed["reconstructed_embedding"][1:] == pytest.approx(original["reconstructed_embedding"][1:], abs=1e-6)
    zero = runtime.infer([row], weight_ablation="zero_decoder")["rows"][0]
    assert zero["candidate_ir"] is None and zero["status"] == "fail_open_invalid_output"
    assert runtime.infer([row]) == baseline
    assert torch.get_num_threads() == previous


def test_inference_rejects_targets_and_uses_embedding_not_source_text(trained):
    runtime = subject.Runtime(trained)
    row = inference_row(trained)
    with pytest.raises(ValueError, match="closed domain row"):
        runtime.infer([{**row, "target": {}}])
    before = runtime.infer([row])["rows"][0]
    after = runtime.infer([{**row, "source_text": "Different text, same supplied numerical embedding."}])["rows"][0]
    for key in ("candidate_ir", "generated_tokens", "reconstructed_embedding", "status"):
        assert before[key] == after[key]
    assert before["source_sha256"] != after["source_sha256"]


def test_digest_domain_and_dimension_mismatches_rejected(trained, tmp_path):
    raw = json.dumps(trained, sort_keys=True, separators=(",", ":")).encode()
    path = tmp_path / "checkpoint.json"
    path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    runtime = subject.load_checkpoint(path, expected_sha256=sha, expected_domain=trained["domain_id"])
    assert runtime.describe()["dimension"] == 384
    with pytest.raises(ValueError, match="another domain"):
        subject.load_checkpoint(path, expected_sha256=sha, expected_domain="legal_ir")
    with pytest.raises(ValueError, match="bytes differ"):
        subject.load_checkpoint(path, expected_sha256="0" * 64, expected_domain=trained["domain_id"])
    with pytest.raises(ValueError, match="384"):
        runtime.infer([{**inference_row(trained), "embedding": [0.] * 48}])
    changed = deepcopy(trained)
    changed["model_state"]["projection_up.bias"][0] += .5
    with pytest.raises(ValueError, match="weight digest"):
        subject.Runtime(changed)


def test_train_validation_overlap_is_rejected(parent):
    data = [row("intent_ir", "train")]
    with pytest.raises(ValueError, match="overlap"):
        subject.train("intent_ir", data, data, parent_projection=parent)
