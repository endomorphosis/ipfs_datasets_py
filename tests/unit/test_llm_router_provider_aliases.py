"""Regression tests for llm_router provider alias canonicalization."""

from __future__ import annotations

import subprocess

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


def test_mistral_vibe_provider_passes_model_and_auth_without_prompt_interpolation(monkeypatch) -> None:
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = kwargs["env"]
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(cmd, 0, stdout="<p>proved</p>", stderr="")

    monkeypatch.setattr(llm_router, "_cli_available", lambda command: True)
    monkeypatch.setattr(llm_router.subprocess, "run", fake_run)
    monkeypatch.setenv(
        "IPFS_DATASETS_PY_MISTRAL_VIBE_CLI_CMD",
        "vibe --prompt {prompt} --output text --max-turns 1",
    )

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
    assert captured["cmd"][2] == 'Prove "notice".'
    assert captured["cmd"][-2:] == ["--agent", "lean"]
    assert captured["input"] is None
    assert captured["env"]["VIBE_ACTIVE_MODEL"] == "Leanstral"
    assert captured["env"]["MISTRAL_API_KEY"] == "test-key"


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
