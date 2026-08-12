"""Packaging parity for the exact-target supervisor dependency contract."""

from __future__ import annotations

import ast
import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SCHEMA = "ipfs_accelerate_py/agent-supervisor/scoped-project-dependency-preflight@1"
TARGET = "tests/unit/logic/gui_optimizer/test_models.py"


def _content_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _literal_setup_test_extra(setup_payload: bytes) -> list[str]:
    tree = ast.parse(setup_payload.decode("utf-8"), filename="setup.py")
    setup_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "setup"
    ]
    assert len(setup_calls) == 1
    extras = [
        keyword.value for keyword in setup_calls[0].keywords if keyword.arg == "extras_require"
    ]
    assert len(extras) == 1 and isinstance(extras[0], ast.Dict)
    selected = [
        extras[0].values[index]
        for index, key in enumerate(extras[0].keys)
        if isinstance(key, ast.Constant) and key.value == "test"
    ]
    assert len(selected) == 1 and isinstance(selected[0], ast.List)
    assert all(
        isinstance(element, ast.Constant) and type(element.value) is str
        for element in selected[0].elts
    )
    return [element.value for element in selected[0].elts]


def test_scoped_supervisor_contract_is_exact_and_setup_authorized() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    inventory = metadata["tool"]["ipfs-datasets-py"]["dependency-inventory"]
    contract = metadata["tool"]["ipfs-accelerate-agent-supervisor"]["project-dependency-preflight"]

    assert inventory["runtime-authority"] == "setup.py:install_requires"
    assert inventory["requirements-txt-role"] == ("source-checkout-development-and-integration")
    assert set(contract) == {
        "schema",
        "requires-python",
        "covered-pytest-target",
        "covered-pytest-target-sha256",
        "requirements",
        "authority",
    }
    assert contract["schema"] == CONTRACT_SCHEMA
    assert contract["requires-python"] == metadata["project"]["requires-python"]
    assert contract["covered-pytest-target"] == TARGET

    target_payload = (ROOT / TARGET).read_bytes()
    assert contract["covered-pytest-target-sha256"] == hashlib.sha256(target_payload).hexdigest()

    authority = contract["authority"]
    assert set(authority) == {
        "file",
        "sha256",
        "extra",
        "extra-requirements-sha256",
    }
    assert authority["file"] == "setup.py"
    assert authority["extra"] == "test"
    setup_payload = (ROOT / authority["file"]).read_bytes()
    assert authority["sha256"] == hashlib.sha256(setup_payload).hexdigest()

    setup_test_extra = _literal_setup_test_extra(setup_payload)
    assert authority["extra-requirements-sha256"] == _content_sha256(setup_test_extra)
    positions = {value: index for index, value in enumerate(setup_test_extra)}
    assert contract["requirements"]
    assert all(requirement in positions for requirement in contract["requirements"])
    assert [positions[item] for item in contract["requirements"]] == sorted(
        positions[item] for item in contract["requirements"]
    )
    assert contract["requirements"] == ["pytest>=9.0.3,<10.0.0"]
