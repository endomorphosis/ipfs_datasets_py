"""Regression tests for llm_router provider alias canonicalization."""

from __future__ import annotations

import subprocess
import sys
import types

from ipfs_datasets_py import llm_router


class _DummyProvider:
    def generate(self, prompt: str, **kwargs):
        return "ok"


def test_resolve_provider_uncached_preferred_alias_canonicalized(monkeypatch) -> None:
    calls = []

    def fake_builtin(name: str):
        calls.append(name)
        if name == "openai":
            return _DummyProvider()
        return None

    monkeypatch.setattr(llm_router, "_builtin_provider_by_name", fake_builtin)
    monkeypatch.setattr(llm_router, "_get_accelerate_provider", lambda deps: None)

    provider = llm_router._resolve_provider_uncached(
        preferred="gpt4",
        deps=llm_router.get_default_router_deps(),
    )

    assert isinstance(provider, _DummyProvider)
    assert "openai" in calls


def test_resolve_provider_uncached_codex_alias_targets_codex_cli(monkeypatch) -> None:
    calls = []

    def fake_builtin(name: str):
        calls.append(name)
        if name == "codex_cli":
            return _DummyProvider()
        return None

    monkeypatch.setattr(llm_router, "_builtin_provider_by_name", fake_builtin)
    monkeypatch.setattr(llm_router, "_get_accelerate_provider", lambda deps: None)

    provider = llm_router._resolve_provider_uncached(
        preferred="codex",
        deps=llm_router.get_default_router_deps(),
    )

    assert isinstance(provider, _DummyProvider)
    assert "codex_cli" in calls


def test_resolve_provider_uncached_default_prefers_accelerate(monkeypatch) -> None:
    provider = _DummyProvider()
    monkeypatch.delenv("IPFS_DATASETS_PY_LLM_PROVIDER", raising=False)
    monkeypatch.setattr(llm_router, "_get_accelerate_provider", lambda deps: provider)

    resolved = llm_router._resolve_provider_uncached(
        preferred=None,
        deps=llm_router.get_default_router_deps(),
    )

    assert resolved is provider


def test_resolve_provider_uncached_forced_alias_canonicalized(monkeypatch) -> None:
    calls = []

    def fake_builtin(name: str):
        calls.append(name)
        if name == "anthropic":
            return _DummyProvider()
        return None

    monkeypatch.setattr(llm_router, "_builtin_provider_by_name", fake_builtin)
    monkeypatch.setattr(llm_router, "_get_accelerate_provider", lambda deps: None)
    monkeypatch.setenv("IPFS_DATASETS_PY_LLM_PROVIDER", "claude")

    provider = llm_router._resolve_provider_uncached(
        preferred=None,
        deps=llm_router.get_default_router_deps(),
    )

    assert isinstance(provider, _DummyProvider)
    assert "anthropic" in calls


def test_run_cli_command_preserves_prompt_with_quotes_in_template(monkeypatch) -> None:
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(llm_router.subprocess, "run", fake_run)

    result = llm_router._run_cli_command(
        "npx --yes @github/copilot -p {prompt}",
        'He said "notice denied" and then filed a grievance.',
        label="Copilot CLI",
    )

    assert result == "ok"
    assert captured["input"] is None
    assert captured["cmd"][-2] == "-p"
    assert captured["cmd"][-1] == 'He said "notice denied" and then filed a grievance.'


def test_mistral_vibe_provider_passes_prompt_argument_and_lets_lean_agent_select_model(monkeypatch) -> None:
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = kwargs["env"]
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(cmd, 0, stdout="<p>proved</p>", stderr="")

    monkeypatch.setattr(llm_router, "_cli_available", lambda command: True)
    monkeypatch.setattr(llm_router.subprocess, "run", fake_run)
    monkeypatch.delenv("IPFS_DATASETS_PY_MISTRAL_VIBE_CLI_CMD", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_MISTRAL_VIBE_MODEL", raising=False)
    monkeypatch.delenv("VIBE_ACTIVE_MODEL", raising=False)

    provider = llm_router._get_mistral_vibe_provider()

    assert provider is not None
    result = provider.generate(
        'Prove "notice".',
        model_name="Leanstral",
        mistral_api_key="test-key",
        mistral_vibe_agent="lean",
    )

    assert result == "proved"
    assert captured["cmd"][0] == "vibe"
    assert captured["cmd"][1:3] == ["--prompt", 'Prove "notice".']
    assert captured["cmd"][-2:] == ["--agent", "lean"]
    assert captured["input"] is None
    assert "VIBE_ACTIVE_MODEL" not in captured["env"]
    assert captured["env"]["MISTRAL_API_KEY"] == "test-key"


def test_explicit_mistral_vibe_provider_uses_accelerator_auto_installer(monkeypatch) -> None:
    install_calls = []
    fake_module = types.ModuleType("ipfs_accelerate_py.utils.mistral_vibe")

    class Result:
        available = True
        executable = "/home/test/.local/bin/vibe"
        reason = "installed"

    def fake_install(**kwargs):
        install_calls.append(kwargs)
        return Result()

    fake_module.ensure_mistral_vibe = fake_install
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", types.ModuleType("ipfs_accelerate_py"))
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.utils", types.ModuleType("ipfs_accelerate_py.utils"))
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.utils.mistral_vibe", fake_module)
    monkeypatch.delenv("IPFS_DATASETS_PY_MISTRAL_VIBE_CLI_CMD", raising=False)
    monkeypatch.setattr(llm_router, "_cli_available", lambda _command: False)

    provider = llm_router._builtin_provider_by_name("mistral_vibe", auto_install=True)

    assert provider is not None
    assert install_calls == [{"auto_install": True}]


def test_explicit_llama_cpp_provider_delegates_to_accelerate_router(monkeypatch) -> None:
    calls = []
    fake_package = types.ModuleType("ipfs_accelerate_py")
    fake_router = types.ModuleType("ipfs_accelerate_py.llm_router")

    def fake_builtin(name: str, *, auto_install: bool = False):
        calls.append((name, auto_install))
        if name == "llama_cpp":
            return _DummyProvider()
        return None

    fake_router._builtin_provider_by_name = fake_builtin
    fake_package.llm_router = fake_router
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", fake_package)
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.llm_router", fake_router)

    provider = llm_router._builtin_provider_by_name("leanstral_local", auto_install=True)

    assert provider is not None
    assert provider.generate("hello") == "ok"
    assert calls == [("llama_cpp", True)]


def test_explicit_llama_cpp_native_provider_delegates_to_native_accelerate_router(monkeypatch) -> None:
    calls = []
    fake_package = types.ModuleType("ipfs_accelerate_py")
    fake_router = types.ModuleType("ipfs_accelerate_py.llm_router")

    def fake_builtin(name: str, *, auto_install: bool = False):
        calls.append((name, auto_install))
        if name == "llama_cpp_native":
            return _DummyProvider()
        return None

    fake_router._builtin_provider_by_name = fake_builtin
    fake_package.llm_router = fake_router
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", fake_package)
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.llm_router", fake_router)

    provider = llm_router._builtin_provider_by_name("llama_cpp_native", auto_install=True)

    assert provider is not None
    assert provider.generate("hello") == "ok"
    assert calls == [("llama_cpp_native", True)]


def test_generate_text_batch_uses_native_batch_provider() -> None:
    calls = []

    class BatchProvider:
        def generate_text_batch(self, prompts, **kwargs):
            calls.append((list(prompts), kwargs))
            return [f"batch:{prompt}" for prompt in prompts]

        def generate(self, prompt: str, **kwargs):
            raise AssertionError("single generate should not be called")

    result = llm_router.generate_text_batch(
        ["one", "two"],
        provider="mock",
        model_name="model-a",
        provider_instance=BatchProvider(),
        temperature=0.0,
    )

    assert result == ["batch:one", "batch:two"]
    assert calls == [
        (
            ["one", "two"],
            {"model_name": "model-a", "temperature": 0.0},
        )
    ]


def test_generate_text_batch_delegates_leanstral_local_to_accelerate_router(monkeypatch) -> None:
    calls = []
    fake_package = types.ModuleType("ipfs_accelerate_py")
    fake_router = types.ModuleType("ipfs_accelerate_py.llm_router")

    def fake_batch(prompts, **kwargs):
        calls.append((list(prompts), kwargs))
        return [f"accelerated:{prompt}" for prompt in prompts]

    fake_router.generate_text_batch = fake_batch
    fake_package.llm_router = fake_router
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", fake_package)
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.llm_router", fake_router)

    result = llm_router.generate_text_batch(
        ["a", "b"],
        provider="leanstral_local",
        model_name="Leanstral",
        max_workers=2,
    )

    assert result == ["accelerated:a", "accelerated:b"]
    assert calls == [
        (
            ["a", "b"],
            {
                "deps": None,
                "max_workers": 2,
                "model_name": "Leanstral",
                "provider": "leanstral_local",
                "use_mesh": False,
            },
        )
    ]


def test_generate_text_batch_mesh_failure_falls_back_to_provider(monkeypatch) -> None:
    calls = []
    fake_package = types.ModuleType("ipfs_accelerate_py")
    fake_router = types.ModuleType("ipfs_accelerate_py.llm_router")

    def fail_batch(prompts, **kwargs):
        calls.append((list(prompts), kwargs))
        raise RuntimeError("mesh unavailable")

    fake_router.generate_text_batch = fail_batch
    fake_package.llm_router = fake_router
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", fake_package)
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.llm_router", fake_router)

    result = llm_router.generate_text_batch(
        ["a", "b"],
        provider="mock",
        model_name="Leanstral",
        use_mesh=True,
        max_workers=1,
    )

    assert result == ["OK", "OK"]
    assert calls and calls[0][1]["use_mesh"] is True


def test_resolve_llama_cpp_native_alias_reports_missing_native_binding(monkeypatch) -> None:
    fake_package = types.ModuleType("ipfs_accelerate_py")
    fake_router = types.ModuleType("ipfs_accelerate_py.llm_router")
    fake_router._builtin_provider_by_name = lambda _name, *, auto_install=False: None
    fake_package.llm_router = fake_router
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", fake_package)
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.llm_router", fake_router)

    try:
        llm_router._resolve_provider_uncached(
            preferred="llama_cpp_native",
            deps=llm_router.get_default_router_deps(),
        )
    except llm_router.LLMRouterError as exc:
        assert "llama-cpp-python not installed" in str(exc)
    else:
        raise AssertionError("missing native llama.cpp binding should be explicit")


def test_copilot_cli_provider_native_mode_supports_add_dir_and_allow_all_paths(monkeypatch) -> None:
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(llm_router, "_cli_available", lambda command: True)
    monkeypatch.setattr(llm_router, "_copilot_cli_supports_image_inputs", lambda command: False)
    monkeypatch.setattr(llm_router, "find_standalone_copilot_cli", lambda: "/usr/bin/copilot")
    monkeypatch.setattr(llm_router.subprocess, "run", fake_run)

    provider = llm_router._get_copilot_cli_provider()

    assert provider is not None
    result = provider.generate(
        "Summarize this repo",
        model_name="gpt-5.4",
        copilot_add_dirs=["/tmp/worktree", "/var/data"],
        copilot_allow_all_paths=True,
    )

    assert result == "ok"
    assert captured["cmd"][:6] == [
        "/usr/bin/copilot",
        "--silent",
        "--stream",
        "off",
        "--allow-all-tools",
        "--allow-all-paths",
    ]
    assert "--add-dir" in captured["cmd"]
    assert "--prompt" in captured["cmd"]
    assert "/tmp/worktree" in captured["cmd"]
    assert "/var/data" in captured["cmd"]


def test_copilot_cli_provider_multimodal_adds_parent_dirs_for_images(monkeypatch) -> None:
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="vision ok", stderr="")

    monkeypatch.setattr(llm_router, "_cli_available", lambda command: True)
    monkeypatch.setattr(llm_router, "_copilot_cli_supports_image_inputs", lambda command: True)
    monkeypatch.setattr(llm_router, "find_standalone_copilot_cli", lambda: "/usr/bin/copilot")
    monkeypatch.setattr(llm_router.subprocess, "run", fake_run)

    provider = llm_router._get_copilot_cli_provider()

    assert provider is not None
    result = provider.generate_multimodal(
        "Describe this image",
        image_paths=["/tmp/screenshots/a.png"],
    )

    assert result == "vision ok"
    assert "--image" in captured["cmd"]
    assert "/tmp/screenshots/a.png" in captured["cmd"]
    assert "--add-dir" in captured["cmd"]
    assert "/tmp/screenshots" in captured["cmd"]
    assert "--prompt" in captured["cmd"]
