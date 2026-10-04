"""Real frozen inference, exact function provenance and honest capability gates."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from .test_security_autoencoder_checkpoint import teacher, fork, joint_inputs, trained, package
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formalization_evaluation as api


def inputs(tmp_path, source):
    repository = tmp_path / "permitted-source"
    repository.mkdir()
    raw = source.encode()
    (repository / "code.py").write_bytes(raw)
    return {"repository": repository, "paths": ["code.py"],
        "source_hashes": {"code.py": hashlib.sha256(raw).hexdigest()}, "polarity": "fixed"}


def evaluate(package, tmp_path, source):
    kwargs = inputs(tmp_path, source)
    result = api.run_security_formalization_evaluation(**kwargs, checkpoint=package[2], output=tmp_path / "evaluation")
    return kwargs, result


def test_real_model_is_executed_but_deterministic_model_cannot_pass_learned_gate(package, tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder.security import codebase_autoencoder as trainer
    from ipfs_datasets_py.logic.formalization.autoencoder.security import security_autoencoder_hub as hub
    monkeypatch.setattr(trainer, "train_codebase_autoencoder", lambda **kw: pytest.fail("runtime trained"))
    monkeypatch.setattr(hub, "download_security_checkpoint", lambda **kw: pytest.fail("runtime downloaded"))
    kwargs, report = evaluate(package, tmp_path, "def add_one(value):\n    return value + 1\n")
    assert report["inference"]["sample_count"] == report["summary"]["program_ir_count"] == 1
    assert report["inference"]["ranks"][0]["latent"]
    assert report["summary"]["learned_formula_count"] == 0
    assert report["summary"]["learned_formula_generation_passed"] is False
    assert report["model_capabilities"]["formal_decoder_implementation"] is None
    with pytest.raises(api.MissingFormalDecoderError): api.require_learned_formula_generation(report)
    baseline = api.derive_security_source_programs(**kwargs)
    assert baseline["function_results"] == report["function_results"]
    assert api.validate_security_formalization_evaluation(repository=kwargs["repository"], expected_report=report) == report
    assert report["provider_calls"] == report["training_steps"] == report["solver_calls"] == 0
    assert not report["proof_authority"] and not report["source_semantics_verified"]


@pytest.mark.parametrize("source,reason", [
    ("@wrapper\ndef f(x):\n    return x + 1\n", "function_signature_or_decorator_unsupported"),
    ("def f(x=side_effect()):\n    return x + 1\n", "function_signature_or_decorator_unsupported"),
    ("def f(x):\n    return external(x)\n", "expression_unsupported:Call"),
    ("def f(x):\n    y = x + 1\n    y = x + 2\n    return y\n", "assignment_target_or_reassignment_unsupported"),
])
def test_unsupported_source_semantics_are_not_erased_for_a_green_result(package, tmp_path, source, reason):
    kwargs, report = evaluate(package, tmp_path, source)
    result = report["function_results"][0]
    assert report["summary"]["sample_count"] == 1 and report["summary"]["program_ir_count"] == 0
    assert result["derivation"]["status"] == "unsupported"
    # Compare exact reason when part of the stable adapter contract.
    assert result["derivation"]["unsupported"]
    if "reassignment" not in reason:
        assert result["derivation"]["unsupported"][0]["reason"] == reason
    assert result["source_binding"]["start_byte"] == 0


def test_nested_decorators_and_indentation_have_explicit_original_byte_maps(package, tmp_path):
    source = "class Scope:\n    @staticmethod\n    def f(x):\n        return x + 1\n"
    kwargs, report = evaluate(package, tmp_path, source)
    row = report["function_results"][0]
    binding = row["source_binding"]
    assert row["symbol"] == "Scope.f" and binding["enclosing_scope"] == "Scope."
    raw = source.encode()
    normalized = b"".join(raw[x["source_start_byte"]:x["source_end_byte"]] for x in binding["line_byte_map"])
    assert normalized.startswith(b"@staticmethod\ndef f(x):")
    assert hashlib.sha256(normalized).hexdigest() == binding["normalized_body_sha256"]
    assert binding["source_sha256"] == kwargs["source_hashes"]["code.py"]
    assert row["derivation"]["status"] == "unsupported" and not binding["whole_file_semantics_verified"]


def test_source_is_never_executed_and_all_observed_functions_are_retained(package, tmp_path):
    sentinel = tmp_path / "executed-source"
    source = "from pathlib import Path\nPath(%r).write_text('ran')\ndef f(value):\n    return value + 1\ndef g(x=unknown()):\n    return x\n" % str(sentinel)
    kwargs, report = evaluate(package, tmp_path, source)
    assert not sentinel.exists()
    assert report["summary"]["sample_count"] == report["summary"]["visited_function_count"] == 2
    assert report["summary"]["all_functions_retained"]
    assert {r["row_id"] for r in report["function_results"]} == {r["row_id"] for r in report["inference"]["ranks"]}


@pytest.mark.parametrize("body", ["return (x +\n1)", 'return """first\nunindented literal\nlast"""'])
def test_unsupported_indentation_keeps_complete_function_coverage(package, tmp_path, body):
    source = "class Scope:\n    def awkward(x):\n        " + body + "\n\ndef fine(x):\n    return x + 1\n"
    kwargs, report = evaluate(package, tmp_path, source)
    assert report["summary"]["sample_count"] == report["summary"]["visited_function_count"] == 2
    awkward = next(x for x in report["function_results"] if x["symbol"] == "Scope.awkward")
    assert awkward["source_binding"]["normalization_frontier"] == "inconsistent_function_indentation"
    assert awkward["derivation"]["status"] == "unsupported"
    assert report["summary"]["program_ir_count"] == 1


@pytest.mark.parametrize("key", ["checkpoint", "source_hashes", "paths", "max_functions", "output"])
def test_report_cannot_join_inference_to_a_different_model_or_source(package, tmp_path, key):
    kwargs, report = evaluate(package, tmp_path, "def f(value):\n    return value + 1\n")
    altered = deepcopy(report["inference"])
    altered[key] = None
    with pytest.raises(ValueError, match="selection differ"):
        api._assemble(**kwargs, checkpoint=package[2], output=Path(report["output"]),
                      max_functions=1024, inference=altered)


@pytest.mark.parametrize("mutation", ["learned", "proof", "span", "missing_function"])
def test_consistently_rehashed_evaluation_cannot_change_attribution_or_coverage(package, tmp_path, mutation):
    kwargs, original = evaluate(package, tmp_path, "def f(value):\n    return value + 1\n")
    report = deepcopy(original)
    if mutation == "learned": report["summary"].update(learned_formula_count=1, learned_formula_generation_passed=True)
    elif mutation == "proof": report["proof_authority"] = True
    elif mutation == "span": report["function_results"][0]["source_binding"]["start_byte"] += 1
    else: report["function_results"] = []
    report["evaluation_cid"] = api._cid({k:v for k,v in report.items() if k != "evaluation_cid"}, "security-evaluation/report")
    path = Path(report["output"], "evaluation.json")
    path.chmod(0o644); path.write_bytes(api.checkpoint_api._json(report))
    with pytest.raises(ValueError, match="attribution|coverage|authority"):
        api.validate_security_formalization_evaluation(repository=kwargs["repository"], expected_report=report)


def test_stale_source_and_function_bounds_refuse_before_publication(package, tmp_path):
    kwargs = inputs(tmp_path, "def f(x):\n    return x\ndef g(x):\n    return x + 1\n")
    output = tmp_path / "bounded"
    with pytest.raises(ValueError, match="function bound"):
        api.run_security_formalization_evaluation(**kwargs, checkpoint=package[2], output=output, max_functions=1)
    assert not output.exists()
    (kwargs["repository"] / "code.py").write_text("def changed(x):\n    return x\n")
    with pytest.raises(ValueError, match="drift"):
        api.run_security_formalization_evaluation(**kwargs, checkpoint=package[2], output=output)
    assert not output.exists()
