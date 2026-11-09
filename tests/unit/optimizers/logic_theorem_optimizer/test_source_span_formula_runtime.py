"""Source-span registry compatibility with small, untrained engineering states.

No archived weights, optimizer updates, legal accuracy claims or registry
services are used. Controlled heads exercise exact copied-span report custody.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import importlib
import json

import pytest

torch = pytest.importorskip("torch")
PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
registry = importlib.import_module(PREFIX + ".autoencoder_runtime_registry")
span = importlib.import_module(PREFIX + ".legal_span_formula")
VERSION = "source_span_formula_v1"
SOURCE = "The Łódź committee shall disclose résumé Ω-17."


@pytest.fixture(scope="module", autouse=True)
def cpu_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def checkpoint_factory():
    @lru_cache(maxsize=3)
    def make(dimension=0, enabled=True):
        row = {"id": "fictional-untrained-fixture", "source_text": "The agency shall disclose records.",
               "canonical_ir": {"rules": [{"modality": "O", "actor": "agency", "action": "disclose",
                   "object": "records", "conditions": [], "exceptions": [], "temporal": []}]}}
        if dimension:
            row["latent"] = [0.] * dimension
        checkpoint = span.build_checkpoint([row], latent_dimension=dimension, latent_enabled=enabled,
            hidden_size=8, embedding_dim=4, projection_width=4, batch_size=1, seed=19)
        assert checkpoint["progress"]["optimizer_steps"] == 0
        return checkpoint
    return make


def write_checkpoint(tmp_path, checkpoint, name="span.json"):
    # Deliberately noncanonical wire bytes distinguish file custody from the
    # unchanged direct owner's canonical checkpoint identity.
    path = tmp_path / name
    raw = json.dumps(checkpoint, ensure_ascii=False, indent=2, allow_nan=False).encode()
    path.write_bytes(raw)
    return {"checkpoint_path": path, "checkpoint_sha256": hashlib.sha256(raw).hexdigest()}


def forbidden(*args, **kwargs):
    pytest.fail("Unsupported operation or target supervision was accessed")


def test_discovery_is_explicit_inference_only_and_does_not_restore(monkeypatch):
    monkeypatch.setattr(span, "load_checkpoint", forbidden)
    monkeypatch.setattr(span, "SpanLegalFormulaDecoder", forbidden)
    description = registry.describe_runtime("legal_ir", VERSION)
    catalog = registry.list_runtimes()
    assert registry.SPAN_FORMULA_VERSION == VERSION
    assert [d["runtime_id"] for d in catalog].count("legal_ir:" + VERSION) == 1
    assert not any(d["runtime_version"] == VERSION and d["domain"] != "legal_ir" for d in catalog)
    assert description["lineage_id"] == span.LINEAGE_ID
    assert description["dimension"] is None
    assert description["supported_latent_dimensions"] == [0, 384]
    assert description["latent_ablation_modes"] == ["none", "zero", "rotate", "disabled"]
    assert description["state_schema"] == span.SCHEMA
    assert description["output_schema"] == "span-legal-formula-inference/v1"
    assert description["capabilities"] == ["load_checkpoint", "infer", "decode_formal_logic"]
    assert description["formal_decoder"]["head_required"] is True
    assert description["source_identity"]["scope"] == "listed_runtime_files_only_not_transitive_dependency_provenance"
    assert "legal_span_formula.py" in description["source_identity"]["files"]
    assert description["all_family_requirements_satisfied"] is False
    assert len(description["qualification_requirements"]["logic_floor"]) == 8
    assert all(description[k] is False for k in registry.features.FALSE)
    assert registry.describe_runtime("legal_ir", registry.LEARNED_FORMULA_VERSION)["state_schema"] == "learned-legal-formula-checkpoint/v1"
    assert registry.describe_runtime("legal_ir", registry.GROUPED_FORMULA_VERSION)["numeric_vector_conditioning"] is False


@pytest.mark.parametrize("domain,version", [("intent_ir", VERSION), ("security_ir", VERSION),
    ("ui_ux_ir", VERSION), ("codebase_ir", VERSION), ("legal_ir", "source_span_formula_v2"),
    ("legal_ir", "warm_start_source_span_formula_v1"), ("legal_ir", "384")])
def test_wrong_domain_and_lineage_never_dispatch_to_span_loader(domain, version, monkeypatch):
    monkeypatch.setattr(span, "load_checkpoint", forbidden)
    with pytest.raises(registry.RuntimeVersionError, match="unknown"):
        registry.open_runtime(domain, version)


def test_checkpoint_binding_is_required_and_preflighted_before_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(span, "load_checkpoint", forbidden)
    with pytest.raises(TypeError):
        registry.open_runtime("legal_ir", VERSION)
    for path in (None, {}, b"checkpoint.json", 384):
        with pytest.raises(registry.RuntimeVersionError, match="local path"):
            registry.open_runtime("legal_ir", VERSION, checkpoint_path=path, checkpoint_sha256="0" * 64)
    for digest in (None, True, "", "a" * 63, "A" * 64, "z" * 64):
        with pytest.raises(registry.RuntimeVersionError, match="exact SHA"):
            registry.open_runtime("legal_ir", VERSION, checkpoint_path=tmp_path / "unused", checkpoint_sha256=digest)


def test_actual_strict_owner_load_and_both_factories_preserve_complete_report(tmp_path, checkpoint_factory, monkeypatch):
    checkpoint = checkpoint_factory()
    binding = write_checkpoint(tmp_path, checkpoint)
    expected = span.SpanLegalFormulaDecoder(checkpoint).decode_formal_logic([SOURCE])
    original_load = span.load_checkpoint
    calls = []
    def retained_load(path, *, expected_sha256):
        calls.append((path, expected_sha256))
        return original_load(path, expected_sha256=expected_sha256)
    monkeypatch.setattr(span, "load_checkpoint", retained_load)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    monkeypatch.setattr(span, "_labels", forbidden)
    runtime = registry.open_runtime("legal_ir", VERSION, **binding)
    formal = registry.open_formal_decoder("legal_ir", VERSION, **binding)
    assert calls == [(binding["checkpoint_path"], binding["checkpoint_sha256"])] * 2
    assert runtime.infer([SOURCE]) == formal.decode_formal_logic([SOURCE]) == expected
    description = runtime.describe()
    assert description["checkpoint_file_sha256"] == binding["checkpoint_sha256"]
    assert description["checkpoint_sha256"] == span.checkpoint_digest(checkpoint)
    assert description["checkpoint_file_sha256"] != description["checkpoint_sha256"]
    assert description["latent_dimension"] == 0 and description["latent_conditioned"] is False
    assert description["optimizer_steps"] == 0 and description["trained_checkpoint_present"] is False
    assert not hasattr(runtime, "train") and not hasattr(runtime, "register_candidate")
    with pytest.raises(registry.RuntimeVersionError, match="lacks registry"):
        registry.load_version(None, "unused", domain="legal_ir", version=VERSION)
    with pytest.raises(registry.RuntimeVersionError, match="lacks prepare_targets"):
        registry.prepare_targets("legal_ir", VERSION, document={})


@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_checkpoint_bound_latent_controls_match_direct_owner(tmp_path, checkpoint_factory, ablation):
    checkpoint = checkpoint_factory(384)
    runtime = registry.open_runtime("legal_ir", VERSION, **write_checkpoint(tmp_path, checkpoint))
    texts = [SOURCE, "The board may retain notice."]
    latents = [[1.] * 384, [-.5] * 384]
    before = deepcopy(latents)
    expected = span.SpanLegalFormulaDecoder(checkpoint).decode_formal_logic(texts, latents, latent_ablation=ablation)
    assert runtime.infer(texts, latents, latent_ablation=ablation) == expected
    assert latents == before
    assert runtime.describe()["latent_dimension"] == 384 and runtime.describe()["latent_conditioned"] is True
    assert all(expected[k] is False for k in span.FALSE)
    assert expected["target_access"] is expected["teacher_forcing"] is expected["training_executed"] is False


def test_direct_checkpoint_save_and_registry_reload_preserve_outputs(tmp_path, checkpoint_factory):
    checkpoint = checkpoint_factory()
    before = deepcopy(checkpoint)
    saved = span.save_checkpoint(checkpoint, tmp_path / "saved.json")
    loaded = span.load_checkpoint(saved["path"], expected_sha256=saved["sha256"])
    expected = span.SpanLegalFormulaDecoder(loaded).decode_formal_logic([SOURCE])
    for factory in (registry.open_runtime, registry.open_formal_decoder):
        runtime = factory("legal_ir", VERSION, checkpoint_path=saved["path"],
                          checkpoint_sha256=saved["sha256"])
        assert runtime.infer([SOURCE]) == expected
        assert runtime.describe()["checkpoint_file_sha256"] == saved["sha256"]
        assert runtime.describe()["checkpoint_sha256"] == span.checkpoint_digest(checkpoint)
    assert loaded == checkpoint == before
    assert checkpoint["progress"]["optimizer_steps"] == 0


def test_disabled_latent_checkpoint_remains_disabled(tmp_path, checkpoint_factory):
    checkpoint = checkpoint_factory(384, False)
    runtime = registry.open_runtime("legal_ir", VERSION, **write_checkpoint(tmp_path, checkpoint))
    expected = span.SpanLegalFormulaDecoder(checkpoint).decode_formal_logic([SOURCE], [[1.] * 384])
    actual = runtime.decode_formal_logic([SOURCE], [[1.] * 384])
    assert actual == expected and actual["rows"][0]["latent_input_enabled"] is False
    assert runtime.describe()["latent_enabled"] is runtime.describe()["latent_conditioned"] is False


def controlled_heads(decoder):
    def forward(byte_ids, byte_lengths, lengths, latent, *, enabled=True):
        length = int(lengths[0])
        starts, ends = torch.full((1, 6, length), -9.), torch.full((1, 6, length), -9.)
        for field, left, right in ((0, 1, 2), (1, 4, 4), (2, 5, 8)):
            starts[0, field, left] = 9.
            ends[0, field, right] = 9.
        return {"modality": torch.tensor([[8., -8., -8.]]),
                "presence": torch.tensor([[[-9., 9.], [9., -9.], [9., -9.], [9., -9.]]]),
                "start": starts, "end": ends}
    decoder.model.forward = forward


def test_decoded_unicode_spans_and_refusals_are_unchanged(tmp_path, checkpoint_factory, monkeypatch):
    checkpoint = checkpoint_factory()
    runtime = registry.open_runtime("legal_ir", VERSION, **write_checkpoint(tmp_path, checkpoint))
    direct = span.SpanLegalFormulaDecoder(checkpoint)
    runtime._decoder = span.SpanLegalFormulaDecoder(checkpoint)
    controlled_heads(direct)
    controlled_heads(runtime._decoder)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    monkeypatch.setattr(span, "_labels", forbidden)
    texts = [SOURCE, "x " * 257, "x" * 16385]
    result = runtime.infer(texts)
    assert result == direct.decode_formal_logic(texts)
    row = result["rows"][0]
    assert row["status"] == "decoded" and row["canonical_ir"]["rules"][0]["object"] == "résumé Ω-17"
    for field in ("actor", "action", "object"):
        d = row["span_diagnostics"]["facets"][field]
        assert SOURCE[d["char_start"]:d["char_end"]] == d["text"]
    assert all(r["status"] == "abstained" and r["reason"] == "source_too_long" for r in result["rows"][1:])
    assert all(result[k] is False for k in span.FALSE)


def test_wrong_hash_and_noncanonical_path_refuse_before_restore(tmp_path, checkpoint_factory, monkeypatch):
    binding = write_checkpoint(tmp_path, checkpoint_factory())
    monkeypatch.setattr(span, "validate_checkpoint", forbidden)
    with pytest.raises(ValueError, match="hash differs"):
        registry.open_runtime("legal_ir", VERSION, **{**binding, "checkpoint_sha256": "0" * 64})
    link = tmp_path / "linked.json"
    link.symlink_to(binding["checkpoint_path"])
    with pytest.raises(ValueError, match="canonical checkpoint path"):
        registry.open_runtime("legal_ir", VERSION, **{**binding, "checkpoint_path": link})


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":2}', b'{"value":NaN}', b'{"value":Infinity}'])
def test_bad_json_cannot_reach_numerical_restore(tmp_path, raw, monkeypatch):
    path = tmp_path / "malformed.json"
    path.write_bytes(raw)
    monkeypatch.setattr(span, "validate_checkpoint", forbidden)
    with pytest.raises(ValueError):
        registry.open_runtime("legal_ir", VERSION, checkpoint_path=path, checkpoint_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("damage", ["schema", "lineage", "latent_width", "architecture", "tokenizer", "implementation", "authority"])
def test_incompatible_checkpoint_cannot_reach_model_restore(tmp_path, checkpoint_factory, monkeypatch, damage):
    checkpoint = deepcopy(checkpoint_factory())
    if damage == "schema":
        checkpoint["schema"] = "learned-legal-formula-checkpoint/v1"
    elif damage == "lineage":
        checkpoint["lineage_id"] = "warm_start_source_span_formula_v1"
    elif damage == "latent_width":
        checkpoint["config"]["latent_dimension"] = 8
    elif damage == "architecture":
        checkpoint["config"]["architecture"] = "different-gru/v1"
    elif damage == "tokenizer":
        checkpoint["config"]["tokenizer"] = "normalized_words/v1"
    elif damage == "implementation":
        checkpoint["implementation"]["span"] = "0" * 64
    else:
        checkpoint["qualified"] = True
    binding = write_checkpoint(tmp_path, checkpoint)
    monkeypatch.setattr(span, "_model", forbidden)
    with pytest.raises(ValueError):
        registry.open_runtime("legal_ir", VERSION, **binding)


@pytest.mark.parametrize("latents", [None, [[0.] * 383], [[0.] * 385], [[True] * 384], [[float("nan")] * 384]])
def test_incompatible_latents_are_not_reshaped_or_defaulted(tmp_path, checkpoint_factory, latents):
    runtime = registry.open_runtime("legal_ir", VERSION, **write_checkpoint(tmp_path, checkpoint_factory(384)))
    with pytest.raises(ValueError):
        runtime.infer([SOURCE], latents)


def test_source_only_input_and_options_are_not_reinterpreted(tmp_path, checkpoint_factory):
    runtime = registry.open_runtime("legal_ir", VERSION, **write_checkpoint(tmp_path, checkpoint_factory()))
    for sources in (SOURCE, [], [{"source_text": SOURCE, "canonical_ir": {}}]):
        with pytest.raises(ValueError):
            runtime.infer(sources)
    with pytest.raises(ValueError, match="does not accept latent"):
        runtime.infer([SOURCE], [[]])
    with pytest.raises(ValueError, match="unsupported latent ablation"):
        runtime.infer([SOURCE], latent_ablation="normalize")
    with pytest.raises(ValueError, match="at least two rows"):
        runtime.infer([SOURCE], latent_ablation="rotate")
    with pytest.raises(TypeError):
        runtime.infer([SOURCE], modal_scope="inferred")
    with pytest.raises(TypeError):
        runtime.decode_formal_logic([SOURCE], mode="learned")
