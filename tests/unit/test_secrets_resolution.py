import json


def test_resolve_secret_reads_config_secrets_file(monkeypatch, tmp_path):
    from ipfs_datasets_py.utils.secrets import resolve_secret

    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(json.dumps({"BRAVE_API_KEY": "brave-test-key"}), encoding="utf-8")
    monkeypatch.setenv("IPFS_DATASETS_PY_SECRETS_FILE", str(secrets_path))
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    assert resolve_secret("BRAVE_SEARCH_API_KEY", "BRAVE_API_KEY") == "brave-test-key"


def test_resolve_secret_prefers_env_over_config(monkeypatch, tmp_path):
    from ipfs_datasets_py.utils.secrets import resolve_secret

    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(json.dumps({"BRAVE_API_KEY": "config-key"}), encoding="utf-8")
    monkeypatch.setenv("IPFS_DATASETS_PY_SECRETS_FILE", str(secrets_path))
    monkeypatch.setenv("BRAVE_API_KEY", "env-key")

    assert resolve_secret("BRAVE_API_KEY") == "env-key"


def test_brave_client_uses_config_secret(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.web_archiving.brave_search_client import BraveSearchClient

    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(json.dumps({"BRAVE_API_KEY": "brave-client-key"}), encoding="utf-8")
    monkeypatch.setenv("IPFS_DATASETS_PY_SECRETS_FILE", str(secrets_path))
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    client = BraveSearchClient()

    assert client.api_key == "brave-client-key"

