import os

import pytest


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _require_integration_enabled() -> None:
    if not _truthy(os.getenv("IPFS_DATASETS_PY_RUN_HF_INTEGRATION_TESTS")):
        pytest.skip("Set IPFS_DATASETS_PY_RUN_HF_INTEGRATION_TESTS=1 to run HF integration tests")


def _model_is_cached_locally(model_id: str) -> bool:
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception:
        return False

    try:
        AutoTokenizer.from_pretrained(model_id, local_files_only=True)
        AutoModelForCausalLM.from_pretrained(model_id, local_files_only=True)
        return True
    except Exception:
        return False


def test_llm_router_accelerate_gpt2_generation(monkeypatch):
    """End-to-end: ipfs_datasets_py.llm_router -> accelerate -> ipfs_accelerate_py (HF) -> gpt2."""

    _require_integration_enabled()

    model_id = os.getenv("IPFS_DATASETS_PY_TEST_HF_MODEL", "gpt2")
    allow_network = _truthy(os.getenv("IPFS_DATASETS_PY_TEST_ALLOW_NETWORK"))

    try:
        import transformers  # noqa: F401
    except Exception:
        pytest.skip("transformers not installed")

    if not allow_network and not _model_is_cached_locally(model_id):
        pytest.skip(
            f"HF model '{model_id}' not cached locally. "
            "Set IPFS_DATASETS_PY_TEST_ALLOW_NETWORK=1 to allow downloads."
        )

    # Force accelerate codepath.
    monkeypatch.setenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "1")

    # Keep HF quieter + deterministic-ish.
    monkeypatch.setenv("HF_HUB_DISABLE_TELEMETRY", "1")
    if not allow_network:
        monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    from ipfs_datasets_py import llm_router
    from ipfs_datasets_py.router_deps import RouterDeps

    deps = RouterDeps()
    prompt = "Hello from ipfs_datasets_py"

    text = llm_router.generate_text(
        prompt,
        provider="accelerate",
        model_name=model_id,
        deps=deps,
        max_new_tokens=8,
    )

    assert isinstance(text, str)
    assert text.strip() != ""
    # HF text-generation pipelines typically echo the prompt.
    assert "Hello" in text
