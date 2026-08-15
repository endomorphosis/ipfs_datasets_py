"""Packaging parity for the exact-target supervisor dependency contract."""

from __future__ import annotations

import ast
import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SCHEMA = "ipfs_accelerate_py/agent-supervisor/scoped-project-dependency-preflight@2"
BOARD_NAMESPACE = "verified-gui-optimizer-v1"
PYTEST_REQUIREMENTS = ["pytest>=9.0.3,<10.0.0"]
TARGETS = {
    "tests/unit/logic/gui_optimizer/test_models.py": {
        "canonical-task-cid": (
            "baguqeeraldxfnc3xz23jqkibkzvni5oqjlnvxne6mcyfcappp3ankxgh4xna"
        ),
        "baseline": {
            "state": "present",
            "sha256": (
                "cbcbc9c30e82ce722a89f30360a973b6e25ce3e6dfd99feaf77a14d9ababb923"
            ),
        },
    },
    "tests/unit/logic/gui_optimizer/test_identity.py": {
        "canonical-task-cid": (
            "baguqeera6eevydfnkuv6uaqvkgvxyt2hhw7wjt2qywk422ifqi4r4wgas7oa"
        ),
        "baseline": {"state": "declared-output-absent"},
    },
    "tests/unit/logic/gui_optimizer/test_formal_adapter.py": {
        "canonical-task-cid": (
            "baguqeera42pzuy6xhjg72xhs3zqzaanxpsio76d7ula3svtd5yvggkcsujvq"
        ),
        "baseline": {"state": "declared-output-absent"},
    },
    "tests/unit/logic/gui_optimizer/test_invariants.py": {
        "canonical-task-cid": (
            "baguqeerascaj2hy5byhsutgth5h5unwwxm5kmqfsf3ap64km4vvvalg4zsbq"
        ),
        "baseline": {"state": "declared-output-absent"},
    },
    "tests/unit/logic/gui_optimizer/test_receipts.py": {
        "canonical-task-cid": (
            "baguqeera3dycj3rf4fkbzcwzhngfpv7l6xy6lwrym7bpdf4pyaou5wsl2psa"
        ),
        "baseline": {"state": "declared-output-absent"},
    },
    "tests/unit/logic/gui_optimizer/test_identity_vectors.py": {
        "canonical-task-cid": (
            "baguqeerasxrw46uw2ocr76pxl4hyrkj4lau62fdvdw5uew3nhqydmwkky75q"
        ),
        "baseline": {"state": "declared-output-absent"},
    },
}


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
        "authority",
        "targets",
    }
    assert contract["schema"] == CONTRACT_SCHEMA
    assert contract["requires-python"] == metadata["project"]["requires-python"]

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

    targets = contract["targets"]
    assert isinstance(targets, list)
    assert len(targets) == len(TARGETS)
    assert len({entry["target"] for entry in targets}) == len(targets)
    assert len(
        {entry["validation-command-sha256"] for entry in targets}
    ) == len(targets)

    observed = {entry["target"]: entry for entry in targets}
    assert set(observed) == set(TARGETS)
    for target, expected in TARGETS.items():
        entry = observed[target]
        assert set(entry) == {
            "target",
            "validation-command-sha256",
            "requirements",
            "task",
            "baseline",
        }
        command = (
            "cd external/ipfs_datasets && python3 -m pytest "
            f"{target} -q"
        )
        assert entry["validation-command-sha256"] == hashlib.sha256(
            command.encode("utf-8")
        ).hexdigest()
        assert entry["requirements"] == PYTEST_REQUIREMENTS
        assert all(requirement in positions for requirement in entry["requirements"])
        assert [positions[item] for item in entry["requirements"]] == sorted(
            positions[item] for item in entry["requirements"]
        )

        task = entry["task"]
        assert set(task) == {
            "board-namespace",
            "canonical-task-cid",
            "declared-output",
        }
        assert task == {
            "board-namespace": BOARD_NAMESPACE,
            "canonical-task-cid": expected["canonical-task-cid"],
            "declared-output": f"external/ipfs_datasets/{target}",
        }

        baseline = entry["baseline"]
        assert baseline == expected["baseline"]
        target_path = ROOT / target
        if baseline["state"] == "present":
            assert target_path.is_file()
            assert baseline["sha256"] == hashlib.sha256(
                target_path.read_bytes()
            ).hexdigest()
        else:
            assert baseline == {"state": "declared-output-absent"}
            assert not target_path.exists()
