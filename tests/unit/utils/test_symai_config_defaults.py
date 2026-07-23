import json


def test_choose_symai_neurosymbolic_engine_defaults_to_codex_when_available(monkeypatch):
    from ipfs_datasets_py.utils import symai_config

    monkeypatch.delenv("NEUROSYMBOLIC_ENGINE_MODEL", raising=False)
    monkeypatch.delenv("NEUROSYMBOLIC_ENGINE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_DISABLE_CODEX_FOR_SYMAI", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_PY_CODEX_MODEL", "gpt-5.3-codex-spark")
    monkeypatch.setattr("shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)

    chosen = symai_config.choose_symai_neurosymbolic_engine()

    assert chosen == {
        "model": "codex:gpt-5.3-codex-spark",
        "api_key": "codex",
    }


def test_choose_symai_neurosymbolic_engine_respects_explicit_disable(monkeypatch):
    from ipfs_datasets_py.utils import symai_config

    monkeypatch.delenv("NEUROSYMBOLIC_ENGINE_MODEL", raising=False)
    monkeypatch.delenv("NEUROSYMBOLIC_ENGINE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_PY_DISABLE_CODEX_FOR_SYMAI", "1")
    monkeypatch.setattr("shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)

    assert symai_config.choose_symai_neurosymbolic_engine() is None


def test_ensure_symai_config_keeps_explicit_neurosymbolic_model_when_router_enabled(monkeypatch, tmp_path):
    from ipfs_datasets_py.utils import symai_config

    monkeypatch.setattr(symai_config.sys, "prefix", str(tmp_path))
    config_path = symai_config.ensure_symai_config(
        neurosymbolic_model="codex:gpt-5.3-codex-spark",
        neurosymbolic_api_key="codex",
        force=True,
        apply_engine_router=True,
    )

    assert config_path is not None

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["NEUROSYMBOLIC_ENGINE_MODEL"] == "codex:gpt-5.3-codex-spark"
    assert payload["NEUROSYMBOLIC_ENGINE_API_KEY"] == "codex"
    assert payload["SYMBOLIC_ENGINE"] == "ipfs"
    assert payload["EMBEDDING_ENGINE_MODEL"] == "ipfs:default"
    assert payload["SEARCH_ENGINE_MODEL"] == "ipfs:default"
    assert payload["INDEXING_ENGINE_ENVIRONMENT"] == "ipfs:default"