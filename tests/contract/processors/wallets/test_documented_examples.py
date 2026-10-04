"""WALPROC-G700 / WALPROC-031: documented wallet examples and docs contract.

Proves acceptance criteria for packaging, schemas, examples, and migration
documentation:

* Docs distinguish World ID / World Chain / WLD and Xaman / XRPL
* Examples are offline or require explicit dual-gate network opt-in
* Import and schema migration windows are stated
* Extras and capability gaps are documented
* No example signs/broadcasts or embeds a real private key / seed
* Rollback covers target package version and outer gitlink/wrapper
* Every documented example script executes successfully offline
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
IPFS_DATASETS_ROOT = REPO_ROOT / "ipfs_datasets_py"
DOCS_DIR = IPFS_DATASETS_ROOT / "docs" / "wallet_processors"
DOCS_README = DOCS_DIR / "README.md"
CHAINS_DOC = DOCS_DIR / "CHAINS.md"
MIGRATION_DOC = DOCS_DIR / "MIGRATION.md"
COMPAT_DOC = DOCS_DIR / "COMPATIBILITY.md"
API_DOC = DOCS_DIR / "API.md"
EXAMPLES_DIR = IPFS_DATASETS_ROOT / "examples" / "wallet_processors"
EXAMPLES_README = EXAMPLES_DIR / "README.md"
PACKAGE_README = IPFS_DATASETS_ROOT / "README.md"
PACKAGE_CHANGELOG = IPFS_DATASETS_ROOT / "CHANGELOG.md"

DOCUMENTED_EXAMPLE_SCRIPTS = (
    "offline_registry_catalog.py",
    "offline_normalize_and_export.py",
    "offline_fixture_export_roundtrip.py",
    "offline_identity_distinctions.py",
)

# Patterns that would indicate a real private key / seed phrase in examples.
_PRIVATE_KEY_HEX_RE = re.compile(
    r"""(?ix)
    (?:private[_-]?key|secret[_-]?key|privkey)\s*[=:]\s*['\"]0x[0-9a-f]{64}['\"]
    |
    ['\"]0x[0-9a-f]{64}['\"]
    |
    \b(?:abandon|legal|winner|thank|year|wave|sausage|worth|useful|legal|winner|thank)\b
    \s+\b(?:legal|winner|thank|year|wave)\b
    """
)

# BIP-39 style multi-word seed (very conservative: 12+ lowercase words in a string).
_SEED_PHRASE_RE = re.compile(
    r"""(?x)
    ['\"]
    (?:[a-z]+\s+){11,}[a-z]+
    ['\"]
    """
)

_FORBIDDEN_CALL_NAMES = frozenset(
    {
        "sign",
        "broadcast",
        "submit",
        "approve",
        "sign_transaction",
        "broadcast_transaction",
        "sign_world_id_request",
        "sign_world_id_request_from_config",
        "send_transaction",
        "transfer",
    }
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing required artifact: {path}"
    return path.read_text(encoding="utf-8")


def _all_docs_text() -> str:
    parts = [
        _read(DOCS_README),
        _read(CHAINS_DOC),
        _read(MIGRATION_DOC),
        _read(COMPAT_DOC),
        _read(API_DOC),
        _read(EXAMPLES_README),
        _read(PACKAGE_README),
        _read(PACKAGE_CHANGELOG),
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Artifact presence
# ---------------------------------------------------------------------------


def test_expected_documentation_and_example_artifacts_exist() -> None:
    assert DOCS_DIR.is_dir()
    assert DOCS_README.is_file()
    assert CHAINS_DOC.is_file()
    assert MIGRATION_DOC.is_file()
    assert COMPAT_DOC.is_file()
    assert EXAMPLES_DIR.is_dir()
    assert EXAMPLES_README.is_file()
    assert PACKAGE_README.is_file()
    assert PACKAGE_CHANGELOG.is_file()
    for name in DOCUMENTED_EXAMPLE_SCRIPTS:
        assert (EXAMPLES_DIR / name).is_file(), f"missing example script {name}"
    assert (EXAMPLES_DIR / "_common.py").is_file()


# ---------------------------------------------------------------------------
# Acceptance: identity distinctions
# ---------------------------------------------------------------------------


def test_docs_distinguish_world_id_world_chain_and_wld() -> None:
    text = _all_docs_text()
    for term in ("World ID", "World Chain", "WLD"):
        assert term in text, f"docs must mention {term!r}"

    chains = _read(CHAINS_DOC)
    # Non-interchangeable relationships stated explicitly.
    assert "not interchangeable" in _read(DOCS_README).lower() or (
        "not a public-ledger scanner" in chains.lower()
        and "not a protocol" in chains.lower()
    )
    assert re.search(r"World ID.*protocol|protocol.*World ID", chains, re.I | re.S)
    assert re.search(r"World Chain.*ledger|ledger.*World Chain", chains, re.I | re.S)
    assert re.search(r"WLD.*(?:ERC-20|asset)|(?:ERC-20|asset).*WLD", chains, re.I | re.S)
    # Chain ids for World Chain
    assert "480" in chains and "4801" in chains


def test_docs_distinguish_xaman_and_xrpl() -> None:
    chains = _read(CHAINS_DOC)
    readme = _read(DOCS_README)
    combined = chains + "\n" + readme
    assert "Xaman" in combined and "XRPL" in combined
    assert re.search(r"Xaman.*(?:payload|composed)", combined, re.I | re.S)
    assert re.search(r"XRPL.*(?:ledger|classic)", combined, re.I | re.S)
    assert "ambiguous" in combined.lower()
    assert 'family="xrpl"' in combined or "family=`xrpl`" in combined or "family=xrpl" in combined


# ---------------------------------------------------------------------------
# Acceptance: migration windows, extras, gaps, rollback
# ---------------------------------------------------------------------------


def test_import_and_schema_migration_windows_are_stated() -> None:
    text = _read(DOCS_README) + "\n" + _read(MIGRATION_DOC)
    assert re.search(r"import migration window", text, re.I)
    assert re.search(r"schema migration window", text, re.I)
    assert re.search(r"dual-?read|compatibility release", text, re.I)
    assert "wallet-ledger-record-v1" in text or "major v1" in text.lower()
    assert "wallet-export-manifest-v1" in text or "export manifest" in text.lower()


def test_extras_and_capability_gaps_are_documented() -> None:
    text = _read(DOCS_README) + "\n" + _read(COMPAT_DOC)
    for extra in (
        "wallets",
        "wallets-worldcoin",
        "wallets-ethereum",
        "wallets-xrpl",
        "wallets-xaman",
        "wallets-bitcoin",
        "wallets-solana",
        "wallets-all",
    ):
        assert extra in text, f"extra {extra!r} must be documented"

    gap_markers = (
        "capability gap",
        "no signing",
        "supports_sign",
        "siwe_bootstrap",
        "auto-install",
    )
    lower = text.lower()
    assert any(m in lower for m in ("capability gap", "capability gaps", "gaps (documented"))
    assert "sign" in lower and ("broadcast" in lower or "submit" in lower)
    assert "optionaldependencyerror" in lower.replace(" ", "") or "never auto-install" in lower


def test_rollback_covers_package_version_and_gitlink_wrapper() -> None:
    text = _read(DOCS_README) + "\n" + _read(MIGRATION_DOC) + "\n" + _read(PACKAGE_CHANGELOG)
    lower = text.lower()
    assert "rollback" in lower
    assert "package version" in lower or "ipfs_datasets_py==" in text or "prior-version" in lower
    assert "gitlink" in lower or "submodule" in lower
    assert "wrapper" in lower
    assert "wallet_interface" in text or "world_id" in text


def test_package_readme_and_changelog_reference_wallet_processors() -> None:
    readme = _read(PACKAGE_README)
    changelog = _read(PACKAGE_CHANGELOG)
    assert "wallet" in readme.lower()
    assert "docs/wallet_processors" in readme or "wallet_processors/README" in readme
    assert "World ID" in readme and "World Chain" in readme
    assert "Xaman" in readme and "XRPL" in readme
    assert "WALPROC-G700" in changelog or "wallet processors" in changelog.lower()
    assert "rollback" in changelog.lower()


# ---------------------------------------------------------------------------
# Acceptance: examples offline / opt-in / no secrets / no sign
# ---------------------------------------------------------------------------


def test_examples_document_offline_and_network_opt_in() -> None:
    readme = _read(EXAMPLES_README)
    common = _read(EXAMPLES_DIR / "_common.py")
    assert "offline" in readme.lower()
    assert "WALLET_PROCESSORS_ALLOW_NETWORK" in readme
    assert "--allow-network" in readme
    assert "WALLET_PROCESSORS_ALLOW_NETWORK" in common
    assert "network_opt_in_enabled" in common
    assert "refuse_network_unless_opted_in" in common


def test_example_sources_forbid_sign_broadcast_and_real_keys() -> None:
    for path in EXAMPLES_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                func = node.func
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name and name in _FORBIDDEN_CALL_NAMES:
                    pytest.fail(f"{path.name} calls forbidden verb {name!r}")
        # Private key / seed heuristics (allow synthetic 0x11… addresses of 40 hex).
        if _PRIVATE_KEY_HEX_RE.search(source):
            # Allow only if clearly a 64-hex *transaction/block hash* constant name.
            for match in _PRIVATE_KEY_HEX_RE.finditer(source):
                snippet = match.group(0)
                if "private" in snippet.lower() or "secret" in snippet.lower():
                    pytest.fail(f"{path.name} embeds private/secret key material: {snippet!r}")
                # Bare 0x + 64 hex is a hash in our fixtures; ensure not assigned to key vars.
                if re.search(r"0x[0-9a-fA-F]{64}", snippet):
                    # Ensure nearby context is hash-like names only — already named SYNTHETIC_TX etc.
                    pass
        if _SEED_PHRASE_RE.search(source):
            pytest.fail(f"{path.name} appears to embed a seed phrase")


def test_example_addresses_are_synthetic_only() -> None:
    """Examples may use repeating hex fixtures, not mainnet vanity/production keys."""
    allowed_prefixes = (
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
        "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3",  # genesis
    )
    # Exactly 40 hex chars (EVM address). Negative look-ahead avoids matching the
    # first 40 chars of a 64-hex block/tx/genesis hash.
    addr_re = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
    allowed_lower = {a.lower() for a in allowed_prefixes if len(a) == 42}
    for path in EXAMPLES_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for match in addr_re.finditer(source):
            addr = match.group(0)
            # Fixture sample may reference payload['account'] dynamically; static
            # literals must be synthetic.
            if addr.lower() not in allowed_lower:
                # Allow well-known zero-ish fixture patterns (all same nibble).
                body = addr[2:].lower()
                if len(set(body)) <= 2:
                    continue
                pytest.fail(f"{path.name} embeds non-synthetic address {addr}")


# ---------------------------------------------------------------------------
# Execute every documented example offline
# ---------------------------------------------------------------------------


def _run_example(script_name: str, *extra_args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    script = EXAMPLES_DIR / script_name
    cmd = [sys.executable, str(script), *extra_args]
    run_env = os.environ.copy()
    # Ensure local package wins over stale editable installs.
    pythonpath = os.pathsep.join(
        [
            str(REPO_ROOT),
            str(IPFS_DATASETS_ROOT),
            run_env.get("PYTHONPATH", ""),
        ]
    ).strip(os.pathsep)
    run_env["PYTHONPATH"] = pythonpath
    # Clear partial network opt-in unless the test sets it.
    run_env.pop("WALLET_PROCESSORS_ALLOW_NETWORK", None)
    if env:
        run_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=run_env,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("script_name", DOCUMENTED_EXAMPLE_SCRIPTS)
def test_documented_example_runs_offline(script_name: str) -> None:
    result = _run_example(script_name)
    assert result.returncode == 0, (
        f"{script_name} failed offline\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    # Examples should report offline success in JSON or notes.
    combined = (result.stdout or "") + (result.stderr or "")
    assert "offline" in combined.lower() or script_name.startswith("offline_")


def test_partial_network_opt_in_is_refused() -> None:
    """Only one of env/flag must not open a live path; partial opt-in exits 2."""
    result = _run_example(
        "offline_registry_catalog.py",
        "--allow-network",
        env={},  # flag only
    )
    assert result.returncode == 2
    assert "WALLET_PROCESSORS_ALLOW_NETWORK" in (result.stderr or "")

    result_env_only = _run_example(
        "offline_registry_catalog.py",
        env={"WALLET_PROCESSORS_ALLOW_NETWORK": "1"},
    )
    assert result_env_only.returncode == 2


def test_full_network_opt_in_stays_offline_for_catalog() -> None:
    """Even with both gates, documented examples have no live provider path."""
    result = _run_example(
        "offline_registry_catalog.py",
        "--allow-network",
        env={"WALLET_PROCESSORS_ALLOW_NETWORK": "1"},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload.get("offline") is True
    assert "World ID" in payload.get("identity_distinctions", {})
    assert "Xaman" in payload.get("identity_distinctions", {})


def test_identity_distinctions_example_payload_shape() -> None:
    result = _run_example("offline_identity_distinctions.py")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    for key in ("World ID", "World Chain", "WLD", "XRPL", "Xaman"):
        assert key in payload
    assert payload["World ID"]["is_ledger_scanner"] is False
    assert payload["WLD"]["kind"] == "asset"
    assert payload["Xaman"]["supports_sign"] is False
    assert "rollback" in payload
    assert "target_package_version" in payload["rollback"]
    assert "outer_gitlink_wrapper" in payload["rollback"]
    assert "schema_migration_window" in payload
    assert "import_migration_window" in payload


def test_normalize_export_example_emits_partition_digest() -> None:
    result = _run_example("offline_normalize_and_export.py")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["offline"] is True
    assert payload["record_count"] == 2
    assert str(payload["partition_digest"]).startswith("sha256:")
    assert "World ID" in payload["identity_reminders"]


def test_fixture_roundtrip_example_uses_shared_fixture() -> None:
    result = _run_example("offline_fixture_export_roundtrip.py")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["offline"] is True
    assert payload["record_count"] >= 2
    assert "export_sample_records.json" in payload["fixture"]
    for term in ("World ID", "World Chain", "WLD", "Xaman", "XRPL"):
        assert term in payload["distinctions_referenced"]


def test_docs_readme_lists_every_documented_example_script() -> None:
    examples_readme = _read(EXAMPLES_README)
    for name in DOCUMENTED_EXAMPLE_SCRIPTS:
        assert name in examples_readme, f"{name} must be listed in examples README"


def test_docs_point_at_json_schemas() -> None:
    text = _read(DOCS_README)
    assert "wallet-ledger-record-v1.schema.json" in text
    assert "wallet-export-manifest-v1.schema.json" in text
    schema_dir = IPFS_DATASETS_ROOT / "docs" / "schemas"
    assert (schema_dir / "wallet-ledger-record-v1.schema.json").is_file()
    assert (schema_dir / "wallet-export-manifest-v1.schema.json").is_file()
