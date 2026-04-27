import json
import sys
from types import SimpleNamespace


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


def test_brave_client_prefers_paid_secret_over_legacy_key(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.web_archiving.brave_search_client import BraveSearchClient

    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(
        json.dumps(
            {
                "BRAVE_API_KEY": "legacy-free-key",
                "BRAVE_SEARCH_PAID_API_KEY": "paid-key",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IPFS_DATASETS_PY_SECRETS_FILE", str(secrets_path))
    for name in (
        "BRAVE_SEARCH_PAID_API_KEY",
        "BRAVE_SEARCH_PRO_API_KEY",
        "BRAVE_SEARCH_API_KEY_PAID",
        "BRAVE_SEARCH_API_KEY_PRO",
        "BRAVE_SEARCH_API_KEY",
        "BRAVE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    client = BraveSearchClient()

    assert client.api_key == "paid-key"


def test_legacy_brave_api_uses_shared_paid_secret_resolver(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.web_archiving.brave_search_engine import BraveSearchAPI

    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(
        json.dumps(
            {
                "BRAVE_API_KEY": "legacy-free-key",
                "BRAVE_SEARCH_PRO_API_KEY": "pro-key",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IPFS_DATASETS_PY_SECRETS_FILE", str(secrets_path))
    monkeypatch.delenv("BRAVE_SEARCH_PRO_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    api = BraveSearchAPI()

    assert api.api_key == "pro-key"


def test_brave_client_prefers_paid_keyring_secret_over_legacy_config(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.web_archiving.brave_search_client import BraveSearchClient

    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(json.dumps({"BRAVE_API_KEY": "legacy-free-key"}), encoding="utf-8")
    monkeypatch.setenv("IPFS_DATASETS_PY_SECRETS_FILE", str(secrets_path))
    monkeypatch.setenv("IPFS_DATASETS_KEYRING_TIMEOUT_SECONDS", "0")
    for name in (
        "BRAVE_SEARCH_PAID_API_KEY",
        "BRAVE_SEARCH_PRO_API_KEY",
        "BRAVE_SEARCH_API_KEY_PAID",
        "BRAVE_SEARCH_API_KEY_PRO",
        "BRAVE_SEARCH_API_KEY",
        "BRAVE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    def get_password(service_name, name):
        if service_name == "ipfs_datasets_py" and name == "BRAVE_SEARCH_PAID_API_KEY":
            return "paid-keyring-key"
        return None

    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=get_password))

    client = BraveSearchClient()

    assert client.api_key == "paid-keyring-key"
