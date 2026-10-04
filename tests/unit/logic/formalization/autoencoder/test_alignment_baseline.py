"""Integrity, source-only generation and honest development baseline coverage."""
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_baseline.py"
spec = importlib.util.spec_from_file_location("alignment_baseline_subject", PATH)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def target(actor, action="retain", object_="certificate"):
    return {"rules": [{"modality": "O", "actor": actor, "action": action, "object": object_,
                       "conditions": [], "exceptions": [], "temporal": []}]}


def row(identity, group, split, actor, vector):
    text = "The " + actor + " must retain the certificate."
    return {"id": identity, "group_id": group, "split": split, "source_text": text,
            "source_sha256": subject._text_hash(text), "embedding": vector,
            "embedding_sha256": subject._digest(vector), "target": target(actor)}


def vector(first, second=0):
    return [first, second] + [0.0] * 382


def write_inputs(folder, training, development):
    folder.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, rows in (("train", training), ("development", development)):
        path = folder / ("train.json" if name == "train" else "validation.json")
        path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
        result[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


@pytest.fixture
def inputs(tmp_path):
    training = [row("train-a", "group-a", "train", "clerk", vector(1)),
                row("train-b", "group-b", "train", "officer", vector(0, 1))]
    development = [row("dev-a", "group-c", "validation", "executor", vector(.9, .1)),
                   row("dev-b", "group-d", "validation", "custodian", vector(.8, .2))]
    config = {"corpus": {**write_inputs(tmp_path, training, development), "dimension": 384,
                         "vector_space_id": subject.VECTOR_SPACE_ID, "max_rows": 5000,
                         "target_origin": "synthetic_authored_unreviewed", "evaluation_role": "exposed_development"},
              "retrieval": {"top_k": 2}}
    return tmp_path, training, development, config


def run(inputs):
    folder, _, _, config = inputs
    return subject.run_alignment_baseline(config, folder, folder)


def failed_compile(sources, vocabulary, deadline):
    return [{"status": "failed", "canonical_ir": None, "error": {"code": "component_unavailable"},
             "source_sha256_observed": subject._text_hash(source["source_text"])} for source in sources]


def test_source_only_compiler_train_only_retrieval_and_unavailable_authority(inputs, monkeypatch):
    folder, training, development, config = inputs
    snapshot = deepcopy(config)
    def compile_sources(sources, vocabulary, deadline):
        assert all(set(source) == {"id", "source_text"} for source in sources)
        assert vocabulary["actors"] == ["clerk", "officer"]
        assert "executor" not in vocabulary["actors"] and "custodian" not in vocabulary["actors"]
        return failed_compile(sources, vocabulary, deadline)
    monkeypatch.setattr(subject, "_compile_sources", compile_sources)
    result = run(inputs)
    assert result["status"] == "completed" and config == snapshot
    assert result["B0"]["status_counts"] == {"failed": 2}
    assert result["B0"]["exact_authored_targets"] == 0
    assert result["B1"]["rows"][0]["retrieved"][0]["train_id"] == "train-a"
    assert all(set(item["train_id"] for item in row_["retrieved"]) == {"train-a", "train-b"}
               for row_ in result["B1"]["rows"])
    assert result["B1"]["counterpart_recall"]["status"] == "not_applicable"
    assert result["B1"]["nearest_target_copy_exact_authored_targets"] == 0
    assert result["B1"]["mean_best_top_k_authored_core_facet_fraction"] == .75
    assert result["B1"]["mean_best_top_k_authored_facet_fraction"] == pytest.approx(6 / 7)
    assert result["B1"]["nearest_authored_facet_match_rates"]["actor"] == 0
    assert len(result["B1"]["diagnostic_limitations"]) == 3
    assert result["primary_metrics"]["independently_adjudicated_fidelity"]["status"] == "unavailable"
    assert result["primary_metrics"]["native_proof_coverage"]["status"] == "unavailable"
    assert result["model_calls"] == result["backend_calls"] == result["downloads"] == 0
    assert result["qualified"] is result["proof_authority"] is result["source_semantics_verified"] is False
    assert len(result["B0"]["compiler_source_sha256"]) == 64
    assert sorted(path.name for path in folder.iterdir()) == ["train.json", "validation.json"]


@pytest.mark.parametrize("field", ["id", "group_id", "source_sha256", "embedding_sha256", "target"])
def test_split_leakage_rejected_before_compilation(inputs, monkeypatch, field):
    folder, training, development, config = inputs
    if field == "source_sha256":
        development[0]["source_text"] = training[0]["source_text"]
    if field == "embedding_sha256":
        development[0]["embedding"] = training[0]["embedding"]
    development[0][field] = deepcopy(training[0][field])
    config["corpus"].update(write_inputs(folder, training, development))
    monkeypatch.setattr(subject, "_compile_sources", lambda *args: pytest.fail("compiler must not be called"))
    with pytest.raises(ValueError, match="leakage"):
        run(inputs)


def test_conservative_normalized_source_leakage(inputs):
    folder, training, development, config = inputs
    development[0]["source_text"] = "  " + training[0]["source_text"].upper() + "\n"
    development[0]["source_sha256"] = subject._text_hash(development[0]["source_text"])
    config["corpus"].update(write_inputs(folder, training, development))
    with pytest.raises(ValueError, match="normalized_source_sha256"):
        run(inputs)


@pytest.mark.parametrize("fault", ["file", "source", "embedding", "zero", "dimension", "nan", "split", "role", "path", "bound"])
def test_bad_hashes_vectors_and_protected_inputs_fail_closed(inputs, fault):
    folder, training, development, config = inputs
    if fault == "file":
        config["corpus"]["development"]["sha256"] = "0" * 64
    elif fault == "source":
        development[0]["source_text"] += " changed"
    elif fault == "embedding":
        development[0]["embedding"][0] = .7
    elif fault in ("zero", "dimension"):
        development[0]["embedding"] = [0.0] * (384 if fault == "zero" else 383)
        development[0]["embedding_sha256"] = subject._digest(development[0]["embedding"])
    elif fault == "nan":
        development[0]["embedding"][0] = float("nan")
    elif fault == "split":
        development[0]["split"] = "test"
    elif fault == "role":
        config["corpus"]["evaluation_role"] = "sealed"
    elif fault == "path":
        config["corpus"].update(write_inputs(folder / "sealed", training, development))
    elif fault == "bound":
        config["corpus"]["max_file_bytes"] = 1
    if fault in ("source", "embedding", "zero", "dimension", "nan", "split"):
        config["corpus"].update(write_inputs(folder, training, development))
    with pytest.raises(ValueError):
        run(inputs)


def test_source_file_changes_during_compile_are_rejected(inputs, monkeypatch):
    folder, training, development, config = inputs
    def compile_sources(*args):
        (folder / "validation.json").write_text('{"rows": []}')
        return failed_compile(*args)
    monkeypatch.setattr(subject, "_compile_sources", compile_sources)
    with pytest.raises(ValueError, match="corpus file SHA256 mismatch"):
        run(inputs)


def test_compiler_observed_source_binding_is_enforced(inputs, monkeypatch):
    def compile_sources(*args):
        results = failed_compile(*args)
        results[0]["source_sha256_observed"] = "0" * 64
        return results
    monkeypatch.setattr(subject, "_compile_sources", compile_sources)
    with pytest.raises(ValueError, match="compiler source binding changed"):
        run(inputs)


def test_deadline_returns_completed_cases_and_explicit_pending_ids(inputs, monkeypatch):
    state = {"now": 0.0}
    monkeypatch.setattr(subject.time, "perf_counter", lambda: state["now"])
    inputs[3]["resource_policy"] = {"max_baseline_seconds": 1}
    def compile_sources(sources, vocabulary, deadline):
        result = failed_compile(sources[:1], vocabulary, deadline)
        state["now"] = 2.0
        return result
    monkeypatch.setattr(subject, "_compile_sources", compile_sources)
    result = run(inputs)
    assert result["status"] == "partial_timeout"
    assert result["B0"]["completed_rows"] == 1 and result["B0"]["pending_ids"] == ["dev-b"]
    assert result["B1"]["completed_rows"] == 0 and result["B1"]["pending_ids"] == ["dev-a", "dev-b"]
    assert result["B1"]["mean_best_top_k_authored_facet_fraction"] is None


def test_runtime_configuration_cannot_enable_models_provers_or_training(inputs):
    for name in ("model_loads", "provider_calls", "prover_calls", "optimizer_steps"):
        inputs[3]["resource_policy"] = {name: 1}
        with pytest.raises(ValueError, match="forbidden resource policy"):
            run(inputs)


def test_cosine_keeps_large_finite_cached_vectors_without_overflow(inputs, monkeypatch):
    folder, training, development, config = inputs
    development[0]["embedding"] = vector(1e308, 1e307)
    development[0]["embedding_sha256"] = subject._digest(development[0]["embedding"])
    config["corpus"].update(write_inputs(folder, training, development))
    monkeypatch.setattr(subject, "_compile_sources", failed_compile)
    result = run(inputs)
    assert 0 < result["B1"]["rows"][0]["retrieved"][0]["cosine_similarity"] <= 1


def test_real_generation_boundary_receives_no_query_target_and_loads_no_model(inputs, monkeypatch):
    import builtins

    from ipfs_datasets_py.logic.legal_ir import canonical_compiler
    original_import = builtins.__import__
    forbidden = {"torch", "transformers", "sentence_transformers", "requests", "httpx"}
    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in forbidden, "unexpected model/provider import: " + name
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    seen = []
    def compile_source(self, request):
        # This is the actual CompilerRequest boundary, not a mock of the helper.
        assert request.atom_vocabulary.actors == ("clerk", "officer")
        assert not any(hasattr(request, name) for name in ("target", "reference_target", "embedding", "group_id"))
        seen.append(request.source_text)
        payload = {"status": "abstained", "canonical_ir": None, "error": {"code": "unsupported"},
                   "request_cid": request.request_cid}
        return SimpleNamespace(request_cid=request.request_cid, to_dict=lambda: payload)
    monkeypatch.setattr(canonical_compiler.TypedDeonticCanonicalCompiler, "compile", compile_source)
    result = run(inputs)
    assert seen == [row_["source_text"] for row_ in inputs[2]]
    assert result["B0"]["status_counts"] == {"abstained": 2}


def test_changed_compiler_request_source_is_integrity_failure(inputs, monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import canonical_compiler
    def compile_source(self, request):
        object.__setattr__(request, "source_text", "changed compiler source")
        return SimpleNamespace(request_cid=request.request_cid,
                               to_dict=lambda: {"status": "failed", "canonical_ir": None})
    monkeypatch.setattr(canonical_compiler.TypedDeonticCanonicalCompiler, "compile", compile_source)
    with pytest.raises(ValueError, match="compiler source binding changed"):
        run(inputs)


def test_integer_float_vector_alias_cannot_bypass_split_exclusion(inputs):
    folder, training, development, config = inputs
    development[0]["embedding"] = [float(value) for value in training[0]["embedding"]]
    development[0]["embedding_sha256"] = subject._digest(development[0]["embedding"])
    config["corpus"].update(write_inputs(folder, training, development))
    with pytest.raises(ValueError, match="numeric_embedding_sha256"):
        run(inputs)
