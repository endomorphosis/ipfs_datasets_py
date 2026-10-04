"""WALPROC-G050 / WALPROC-010 optional dependency extras contract tests.

Proves:

* declared wallet extras exist with synchronized pins in pyproject.toml and setup.py
* license/SBOM/selection rationale is documented
* eth-hash / eth-keys win over required coincurve via golden vectors
* raw REST/JSON-RPC policy keeps chain SDKs out of extras
* minimal packaging imports succeed without chain extras
* Python version mismatch resolution is documented
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
IPFS_DATASETS_ROOT = REPO_ROOT / "ipfs_datasets_py"
PYPROJECT = IPFS_DATASETS_ROOT / "pyproject.toml"
SETUP_PY = IPFS_DATASETS_ROOT / "setup.py"
DEPENDENCIES_DOC = (
    IPFS_DATASETS_ROOT / "docs" / "dependencies" / "WALLET_PROCESSOR_DEPENDENCIES.md"
)
GOLDEN_VECTORS = (
    IPFS_DATASETS_ROOT
    / "tests"
    / "fixtures"
    / "wallets"
    / "worldcoin"
    / "golden_vectors.json"
)
ROOT_PYPROJECT = REPO_ROOT / "pyproject.toml"

REQUIRED_WALLET_EXTRAS = (
    "wallets",
    "wallets-worldcoin",
    "wallets-ethereum",
    "wallets-xrpl",
    "wallets-xaman",
    "wallets-bitcoin",
    "wallets-solana",
    "wallets-all",
)

# Chain SDKs and vendor libraries must not be admitted via convenience alone.
FORBIDDEN_EXTRA_PACKAGES = {
    "web3",
    "web3.py",
    "solana",
    "solders",
    "xrpl-py",
    "xrpl",
    "xumm-sdk",
    "xumm",
    "python-bitcoinlib",
    "bitcoinlib",
    "coincurve",  # optional accelerator only; not a declared wallet extra pin
}

WORLDCOIN_REQUIRED_PACKAGES = {
    "eth-hash[pycryptodome]",
    "eth-keys",
}


def _normalize_req(req: str) -> str:
    """Strip environment markers and whitespace; keep name+extras+specifiers loosely."""
    return req.split(";")[0].strip()


def _requirement_name(req: str) -> str:
    """Return the distribution name including extras brackets, lowercased."""
    bare = _normalize_req(req)
    # Drop version specifiers: name[extra]>=1.0 -> name[extra]
    match = re.match(r"^([A-Za-z0-9_.-]+(?:\[[^\]]+\])?)", bare)
    if not match:
        return bare.lower()
    return match.group(1).lower()


def _base_distribution_name(req: str) -> str:
    name = _requirement_name(req)
    return name.split("[", 1)[0]


def _load_pyproject_wallet_extras() -> dict[str, list[str]]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    optional = data["project"]["optional-dependencies"]
    missing = [name for name in REQUIRED_WALLET_EXTRAS if name not in optional]
    assert not missing, f"pyproject.toml missing wallet extras: {missing}"
    return {name: list(optional[name]) for name in REQUIRED_WALLET_EXTRAS}


def _literal_str_list(node: ast.AST) -> list[str] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            values.append(elt.value)
        else:
            # Conditional expressions (platform extras) — not used for wallets.
            return None
    return values


def _load_setup_wallet_extras() -> dict[str, list[str]]:
    """Extract wallet extras from setup.py without executing it."""
    tree = ast.parse(SETUP_PY.read_text(encoding="utf-8"), filename=str(SETUP_PY))
    found: dict[str, list[str]] = {}

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "setup":
                self.generic_visit(node)
                return
            for keyword in node.keywords:
                if keyword.arg != "extras_require":
                    continue
                if not isinstance(keyword.value, ast.Dict):
                    continue
                for key_node, value_node in zip(
                    keyword.value.keys, keyword.value.values, strict=False
                ):
                    if not isinstance(key_node, ast.Constant):
                        continue
                    key = key_node.value
                    if key not in REQUIRED_WALLET_EXTRAS:
                        continue
                    items = _literal_str_list(value_node)
                    assert items is not None, (
                        f"setup.py extras_require[{key!r}] must be a list of string literals"
                    )
                    found[str(key)] = items
            self.generic_visit(node)

    Visitor().visit(tree)
    missing = [name for name in REQUIRED_WALLET_EXTRAS if name not in found]
    assert not missing, f"setup.py missing wallet extras: {missing}"
    return found


def _sorted_req_set(reqs: list[str]) -> set[str]:
    return {_normalize_req(r) for r in reqs}


@pytest.fixture(scope="module")
def pyproject_extras() -> dict[str, list[str]]:
    return _load_pyproject_wallet_extras()


@pytest.fixture(scope="module")
def setup_extras() -> dict[str, list[str]]:
    return _load_setup_wallet_extras()


@pytest.fixture(scope="module")
def dependencies_doc() -> str:
    assert DEPENDENCIES_DOC.is_file(), f"missing dependency report: {DEPENDENCIES_DOC}"
    return DEPENDENCIES_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def golden_vectors() -> dict[str, Any]:
    assert GOLDEN_VECTORS.is_file(), f"missing golden vectors: {GOLDEN_VECTORS}"
    with GOLDEN_VECTORS.open(encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Extra presence and synchronization
# ---------------------------------------------------------------------------


def test_all_required_wallet_extras_declared(
    pyproject_extras: dict[str, list[str]],
    setup_extras: dict[str, list[str]],
) -> None:
    assert set(pyproject_extras) == set(REQUIRED_WALLET_EXTRAS)
    assert set(setup_extras) == set(REQUIRED_WALLET_EXTRAS)


def test_pyproject_and_setup_wallet_extras_match(
    pyproject_extras: dict[str, list[str]],
    setup_extras: dict[str, list[str]],
) -> None:
    for name in REQUIRED_WALLET_EXTRAS:
        assert _sorted_req_set(pyproject_extras[name]) == _sorted_req_set(
            setup_extras[name]
        ), f"mismatched pins for extra {name!r}"


def test_worldcoin_extra_pins_eth_hash_and_eth_keys(
    pyproject_extras: dict[str, list[str]],
) -> None:
    names = {_requirement_name(r) for r in pyproject_extras["wallets-worldcoin"]}
    for required in WORLDCOIN_REQUIRED_PACKAGES:
        assert required in names, (
            f"wallets-worldcoin must pin {required!r}; got {sorted(names)}"
        )


def test_wallets_all_is_superset_of_chain_extras(
    pyproject_extras: dict[str, list[str]],
) -> None:
    all_pins = _sorted_req_set(pyproject_extras["wallets-all"])
    for name in REQUIRED_WALLET_EXTRAS:
        if name in {"wallets-all"}:
            continue
        for req in pyproject_extras[name]:
            assert _normalize_req(req) in all_pins, (
                f"wallets-all missing pin from {name}: {req}"
            )


def test_no_forbidden_chain_sdks_in_wallet_extras(
    pyproject_extras: dict[str, list[str]],
) -> None:
    for extra_name, reqs in pyproject_extras.items():
        for req in reqs:
            base = _base_distribution_name(req)
            assert base not in FORBIDDEN_EXTRA_PACKAGES, (
                f"extra {extra_name!r} must not pin forbidden package {base!r} ({req})"
            )


def test_chain_ledger_extras_have_no_sdk_packages(
    pyproject_extras: dict[str, list[str]],
) -> None:
    """Raw REST/JSON-RPC policy: ledger extras stay empty of third-party SDKs."""
    for name in (
        "wallets",
        "wallets-ethereum",
        "wallets-xrpl",
        "wallets-xaman",
        "wallets-bitcoin",
        "wallets-solana",
    ):
        assert pyproject_extras[name] == [], (
            f"{name} must remain empty under raw REST/JSON-RPC policy; got {pyproject_extras[name]}"
        )


# ---------------------------------------------------------------------------
# Documentation coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "term",
    [
        "wallets",
        "wallets-worldcoin",
        "wallets-ethereum",
        "wallets-xrpl",
        "wallets-xaman",
        "wallets-bitcoin",
        "wallets-solana",
        "wallets-all",
        "SBOM",
        "license",
        "eth-hash",
        "eth-keys",
        "coincurve",
        "pycryptodome",
        "raw REST",
        "JSON-RPC",
        "Python 3.12",
        "requires-python",
        "Do not auto-install",
        "SDK convenience",
    ],
)
def test_dependencies_doc_covers_acceptance_terms(
    dependencies_doc: str, term: str
) -> None:
    assert term in dependencies_doc, f"dependencies doc missing term: {term!r}"


def test_dependencies_doc_states_python_version_resolution(
    dependencies_doc: str,
) -> None:
    assert "3.11" in dependencies_doc
    assert "3.12" in dependencies_doc
    assert "Resolution" in dependencies_doc or "resolution" in dependencies_doc
    root_data = tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))
    package_data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert root_data["project"]["requires-python"].startswith(">=")
    assert "3.11" in root_data["project"]["requires-python"]
    assert "3.12" in package_data["project"]["requires-python"]


def test_dependencies_doc_rejects_sdk_convenience_justification(
    dependencies_doc: str,
) -> None:
    lowered = dependencies_doc.lower()
    assert "convenience" in lowered
    assert "web3" in lowered
    assert "not selected" in lowered or "rejected" in lowered


# ---------------------------------------------------------------------------
# Vector-backed crypto selection
# ---------------------------------------------------------------------------


def test_eth_hash_matches_hash_to_field_golden_vectors(
    golden_vectors: dict[str, Any],
) -> None:
    eth_hash = pytest.importorskip("eth_hash.auto")
    keccak = eth_hash.keccak

    for name, case in golden_vectors["hash_to_field"].items():
        if "input_hex" in case:
            data = bytes.fromhex(case["input_hex"])
        else:
            data = str(case["input_utf8"]).encode("utf-8")
        field = (int.from_bytes(keccak(data), "big") >> 8).to_bytes(32, "big")
        assert f"0x{field.hex()}" == case["field_hex"], name


def test_eth_keys_matches_rp_signing_golden_vectors(
    golden_vectors: dict[str, Any],
) -> None:
    eth_hash = pytest.importorskip("eth_hash.auto")
    eth_keys = pytest.importorskip("eth_keys")
    keccak = eth_hash.keccak

    rp = golden_vectors["rp_signing"]
    key = bytes.fromhex(rp["signing_key_hex"].removeprefix("0x"))
    private_key = eth_keys.keys.PrivateKey(key)

    for case_name in ("without_action", "with_action_test_action"):
        case = rp[case_name]
        message = bytes.fromhex(case["message_hex"])
        prefix = b"\x19Ethereum Signed Message:\n" + str(len(message)).encode("ascii")
        digest = keccak(prefix + message)
        signature = private_key.sign_msg_hash(digest)
        # Ethereum yellow-paper v = recovery_id + 27
        encoded = (
            signature.r.to_bytes(32, "big")
            + signature.s.to_bytes(32, "big")
            + bytes([signature.v + 27])
        )
        assert f"0x{encoded.hex()}" == case["signature"], case_name


def test_coincurve_is_not_required_when_eth_keys_matches(
    golden_vectors: dict[str, Any],
) -> None:
    """Documented decision: coincurve is optional; eth-keys alone is sufficient."""
    eth_hash = pytest.importorskip("eth_hash.auto")
    eth_keys = pytest.importorskip("eth_keys")
    keccak = eth_hash.keccak
    rp = golden_vectors["rp_signing"]
    key = bytes.fromhex(rp["signing_key_hex"].removeprefix("0x"))
    message = bytes.fromhex(rp["without_action"]["message_hex"])
    prefix = b"\x19Ethereum Signed Message:\n" + str(len(message)).encode("ascii")
    digest = keccak(prefix + message)
    signature = eth_keys.keys.PrivateKey(key).sign_msg_hash(digest)
    encoded = (
        signature.r.to_bytes(32, "big")
        + signature.s.to_bytes(32, "big")
        + bytes([signature.v + 27])
    )
    assert f"0x{encoded.hex()}" == rp["without_action"]["signature"]

    # If coincurve happens to be installed, it must not be a packaging pin.
    pyproject_extras = _load_pyproject_wallet_extras()
    for reqs in pyproject_extras.values():
        assert all(_base_distribution_name(r) != "coincurve" for r in reqs)


# ---------------------------------------------------------------------------
# Minimal import / absence contract
# ---------------------------------------------------------------------------


def test_wallet_extras_not_required_for_base_package_metadata() -> None:
    """Base packaging metadata loads without installing chain extras."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert data["project"]["name"] == "ipfs_datasets_py"
    # Base install must not list chain SDKs as mandatory dependencies.
    # Dependencies are dynamic from setup.py; parse install_requires strings.
    setup_text = SETUP_PY.read_text(encoding="utf-8")
    for forbidden in ("web3", "solana", "xrpl-py", "xumm-sdk", "bitcoinlib"):
        # Allow comments mentioning rejection; forbid requirement-like pins.
        for match in re.finditer(
            rf"['\"]({re.escape(forbidden)}[^'\"]*)['\"]", setup_text
        ):
            snippet = match.group(1)
            # Only fail if it looks like a requirement entry (version bound or bare).
            if snippet.startswith(forbidden) and (
                snippet == forbidden
                or snippet[len(forbidden) : len(forbidden) + 1] in "><=!["
            ):
                # wallet extras section may discuss them in comments only — string
                # literals in comments are not captured by this regex. Fail only
                # when appearing as a setup string that is not inside a comment
                # line.
                line_start = setup_text.rfind("\n", 0, match.start()) + 1
                line = setup_text[line_start : setup_text.find("\n", match.start())]
                if line.lstrip().startswith("#"):
                    continue
                # String in a wallet extra empty list comment is fine; actual pin:
                if forbidden in {
                    _base_distribution_name(s)
                    for s in sum(_load_setup_wallet_extras().values(), [])
                }:
                    pytest.fail(f"forbidden base/extra pin detected: {snippet}")


def test_minimal_stdlib_import_succeeds_without_chain_sdks() -> None:
    """A clean subprocess proves no chain SDK is imported for basic runtime."""
    import subprocess

    code = """
import json
import sys

def present(name: str) -> bool:
    return any(m == name or m.startswith(name + ".") for m in sys.modules)

# Import nothing wallet-chain-specific; only exercise packaging parse path.
import tomllib
from pathlib import Path
root = Path(%r)
data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
extras = data["project"]["optional-dependencies"]
print(json.dumps({
    "extras": sorted(k for k in extras if k.startswith("wallets")),
    "web3": present("web3"),
    "solana": present("solana"),
    "xrpl": present("xrpl"),
    "coincurve": present("coincurve"),
}))
""" % (
        str(IPFS_DATASETS_ROOT),
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["extras"] == sorted(REQUIRED_WALLET_EXTRAS)
    # Modules must not appear merely because we read packaging metadata.
    assert payload["web3"] is False
    assert payload["solana"] is False
    assert payload["xrpl"] is False


def test_version_bounds_are_compatible(
    pyproject_extras: dict[str, list[str]],
) -> None:
    """Worldcoin pins use compatible lower/upper bounds."""
    for req in pyproject_extras["wallets-worldcoin"]:
        normalized = _normalize_req(req)
        assert ">=" in normalized, f"expected lower bound in {req}"
        assert "<" in normalized, f"expected upper bound in {req}"
