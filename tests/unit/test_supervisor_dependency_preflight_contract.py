"""Packaging parity for the exact-target supervisor dependency contract."""

from __future__ import annotations

import ast
import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SCHEMA = "ipfs_accelerate_py/agent-supervisor/scoped-project-dependency-preflight@3"
GUI_BOARD_NAMESPACE = "verified-gui-optimizer-v1"
LGCVF_BOARD_NAMESPACE = "logic-governed-compositional-verification-fabric-v1"
AUTHORITY_EXTRA = "lgcvf-validation"
PYTEST = "pytest>=9.0.3,<10.0.0"
Z3 = "z3-solver>=4.12.0,<5.0.0"
CVC5 = "cvc5==1.3.3"
PYTEST_REQUIREMENTS = [PYTEST]
SOLVER_REQUIREMENTS = [PYTEST, Z3, CVC5]
TARGETS = {
    "tests/unit/logic/gui_optimizer/test_models.py": {
        "repository-root": "external/ipfs_datasets",
        "command-style": "legacy",
        "board-namespace": GUI_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeeraldxfnc3xz23jqkibkzvni5oqjlnvxne6mcyfcappp3ankxgh4xna"
        ),
        "requirements": PYTEST_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "cbcbc9c30e82ce722a89f30360a973b6e25ce3e6dfd99feaf77a14d9ababb923"
            ),
        },
    },
    "tests/unit/logic/gui_optimizer/test_identity.py": {
        "repository-root": "external/ipfs_datasets",
        "command-style": "legacy",
        "board-namespace": GUI_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeera6eevydfnkuv6uaqvkgvxyt2hhw7wjt2qywk422ifqi4r4wgas7oa"
        ),
        "requirements": PYTEST_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "85faebe51c452a54c00d5b2150dd65757e6a24be607ab1ab2bd0c7a5a65d7efd"
            ),
        },
    },
    "tests/unit/logic/gui_optimizer/test_formal_adapter.py": {
        "repository-root": "external/ipfs_datasets",
        "command-style": "legacy",
        "board-namespace": GUI_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeera42pzuy6xhjg72xhs3zqzaanxpsio76d7ula3svtd5yvggkcsujvq"
        ),
        "requirements": PYTEST_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "572f666322243c639314a8222ff6c114626d81fd6924dab162159ec904c8b589"
            ),
        },
    },
    "tests/unit/logic/gui_optimizer/test_invariants.py": {
        "repository-root": "external/ipfs_datasets",
        "command-style": "legacy",
        "board-namespace": GUI_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeerascaj2hy5byhsutgth5h5unwwxm5kmqfsf3ap64km4vvvalg4zsbq"
        ),
        "requirements": PYTEST_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "fd6c146c396dead658e9de0efd331c5f2cf1e612ad29072cf5bcc18409b202ad"
            ),
        },
    },
    "tests/unit/logic/gui_optimizer/test_receipts.py": {
        "repository-root": "external/ipfs_datasets",
        "command-style": "legacy",
        "board-namespace": GUI_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeera3dycj3rf4fkbzcwzhngfpv7l6xy6lwrym7bpdf4pyaou5wsl2psa"
        ),
        "requirements": PYTEST_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "a4f88163908f5e66687bc73b27bc50db4b6ce388e490907cfc1d76bad286a800"
            ),
        },
    },
    "tests/unit/logic/gui_optimizer/test_identity_vectors.py": {
        "repository-root": "external/ipfs_datasets",
        "command-style": "legacy",
        "board-namespace": GUI_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeerasxrw46uw2ocr76pxl4hyrkj4lau62fdvdw5uew3nhqydmwkky75q"
        ),
        "requirements": PYTEST_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "3c8432febd07e627bbd7d535e875f82d97aab91e2d973be9c81d8be362f2c3d3"
            ),
        },
    },
    "tests/unit/logic/test_compositional_verification_public_api.py": {
        "repository-root": "ipfs_datasets_py",
        "command-style": "board",
        "board-namespace": LGCVF_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeera5akr2w56xcy6mus4td2ghwaita5k52lnqkh54tgooqq35fai72nq"
        ),
        "requirements": SOLVER_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "6c93b34d1b10b5c7e311a87a7aa901a2502858ed8d8601e910e1aec62417b86e"
            ),
        },
    },
    "tests/unit/logic/backends/test_interpolation.py": {
        "repository-root": "ipfs_datasets_py",
        "command-style": "board",
        "board-namespace": LGCVF_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeeratlqqozbenktvzhzzk36ewsti3mzegge2ynft24s3mznewzgswfoq"
        ),
        "requirements": SOLVER_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "8116954ee49c645ab1b7903521d02f4d3bfd0d659365c2ec66e5f18a3ce6d038"
            ),
        },
    },
    "tests/unit/logic/software_verification/test_cegar.py": {
        "repository-root": "ipfs_datasets_py",
        "command-style": "board",
        "board-namespace": LGCVF_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeeraqopotj43fgxcfptvziv3g3kna4wcwhtzarcobv2obvs32njoggjq"
        ),
        "requirements": SOLVER_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "e94e091d30e928219b090133f1f85bedad975028c767480982ec59ff58c4cfd9"
            ),
        },
    },
    "tests/unit/logic/formalization/test_translation_receipts.py": {
        "repository-root": "ipfs_datasets_py",
        "command-style": "board",
        "board-namespace": LGCVF_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeeraej2zz7zlrd2l5p6adjnzinnitzuqmxx4agfhfzekixdqm2mnqyda"
        ),
        "requirements": PYTEST_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "378b354559efa3fda676343313f1d9a6f14e5fcef4ced675aced58c6a5f6d885"
            ),
        },
    },
    "tests/unit/logic/software_verification/test_obligation_slicing.py": {
        "repository-root": "ipfs_datasets_py",
        "command-style": "board",
        "board-namespace": LGCVF_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeerar3vmbqw7f2qk6mjyhsx3hq7gpbnqcydt7cecm6og5xejbd2vz6cq"
        ),
        "requirements": PYTEST_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "487194ddf108167e647f5fe2cdce624854a7162f45d46b6a88f28395a608d65e"
            ),
        },
    },
    "tests/unit/logic/software_verification/test_proof_carrying_artifact.py": {
        "repository-root": "ipfs_datasets_py",
        "command-style": "board",
        "board-namespace": LGCVF_BOARD_NAMESPACE,
        "canonical-task-cid": (
            "baguqeeraompdkd4vtnb7z4sd5evmsx2jsucobyahrzqxyicwmwqdcwcvq3iq"
        ),
        "requirements": PYTEST_REQUIREMENTS,
        "baseline": {
            "state": "present",
            "sha256": (
                "d9b9c3d4391cbecc811059f81108989fa3b01dd5642469cc108bf9ed12fc6829"
            ),
        },
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


def _literal_setup_list(
    setup_payload: bytes,
    *,
    keyword_name: str,
    extra: str | None = None,
    allow_nonliteral_members: bool = False,
) -> list[str]:
    tree = ast.parse(setup_payload.decode("utf-8"), filename="setup.py")
    setup_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "setup"
    ]
    assert len(setup_calls) == 1
    values = [
        keyword.value
        for keyword in setup_calls[0].keywords
        if keyword.arg == keyword_name
    ]
    assert len(values) == 1
    if extra is None:
        assert isinstance(values[0], ast.List)
        selected = values
    else:
        assert isinstance(values[0], ast.Dict)
        selected = [
            values[0].values[index]
            for index, key in enumerate(values[0].keys)
            if isinstance(key, ast.Constant) and key.value == extra
        ]
        assert len(selected) == 1 and isinstance(selected[0], ast.List)
    literal_members = [
        element.value
        for element in selected[0].elts
        if isinstance(element, ast.Constant) and type(element.value) is str
    ]
    if not allow_nonliteral_members:
        assert len(literal_members) == len(selected[0].elts)
    return literal_members


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
    assert authority["extra"] == AUTHORITY_EXTRA
    setup_payload = (ROOT / authority["file"]).read_bytes()
    assert authority["sha256"] == hashlib.sha256(setup_payload).hexdigest()

    authority_requirements = _literal_setup_list(
        setup_payload,
        keyword_name="extras_require",
        extra=AUTHORITY_EXTRA,
    )
    assert authority_requirements == SOLVER_REQUIREMENTS
    assert authority["extra-requirements-sha256"] == _content_sha256(
        authority_requirements
    )
    positions = {value: index for index, value in enumerate(authority_requirements)}

    # The dedicated profile names no new distribution: it only selects exact
    # pins already present in base or ordinary test dependencies and does not
    # authorize installation.
    install_requires = _literal_setup_list(
        setup_payload,
        keyword_name="install_requires",
        allow_nonliteral_members=True,
    )
    test_requirements = _literal_setup_list(
        setup_payload,
        keyword_name="extras_require",
        extra="test",
    )
    assert set(authority_requirements) <= set(install_requires) | set(
        test_requirements
    )

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
        repository_root = expected["repository-root"]
        if expected["command-style"] == "legacy":
            command = f"cd {repository_root} && python3 -m pytest {target} -q"
        else:
            assert expected["command-style"] == "board"
            command = f"cd {repository_root} && python -m pytest -q {target}"
        assert entry["validation-command-sha256"] == hashlib.sha256(
            command.encode("utf-8")
        ).hexdigest()
        assert entry["requirements"] == expected["requirements"]
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
            "board-namespace": expected["board-namespace"],
            "canonical-task-cid": expected["canonical-task-cid"],
            "declared-output": f"{repository_root}/{target}",
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
