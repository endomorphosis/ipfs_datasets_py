"""Operator-owned, local deployment seals for the native replay policy.

No task claims, imports of the validator, or dependency installs occur here.
The profile is generated for a private repository; shared pyproject files are
never rewritten. Its receipt lives outside the agent's repository.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import stat
import tomllib

from .supervisor_queue import EDIT_SCOPES, NAMESPACE, REGRESSION_TESTS, SCHEMA, canonical_bytes

PROFILE_SCHEMA = "ipfs_accelerate_py/agent-supervisor/sealed-python-validator@1"
SEAL_SCHEMA = "uscode-autoformal-validator-deployment/v1"
ENTRYPOINT = "scripts/ops/legal_ir/validate_autoformal_repair.py"
SEALED_FILES = (
    ENTRYPOINT,
    "ipfs_datasets_py/logic/autoformal/supervisor_queue.py",
    "ipfs_datasets_py/logic/autoformal/autoencoder_router.py",
    "ipfs_datasets_py/logic/autoformal/supervisor_todo.py",
    "ipfs_datasets_py/logic/autoformal/ontology_capture.py",
    "ipfs_datasets_py/logic/autoformal/__init__.py",
    "ipfs_datasets_py/logic/autoformal/extended_repair.py",
    "ipfs_datasets_py/logic/legal_ir/extended_contracts.py",
    *REGRESSION_TESTS,
    "tests/fixtures/semantic_roundtrip/pilot_cases.json",
    "pytest.ini",
)
DEPLOYMENT_PROTECTED = ("pyproject.toml", "setup.py", *SEALED_FILES)
MAX_FILE_BYTES = 2 * 1024 * 1024
RUNTIME_PROFILE_V1 = "autoformal-runtime-v1"
RUNTIME_EXTRA_V1 = "autoformal-validator-runtime-v1"
RUNTIME_REQUIREMENTS_V1 = (
    "pytest>=9.0.3,<10.0.0",
    "multiformats==0.3.1.post4",
    "bases==0.3.0",
    "multiformats-config==0.3.1",
    "typing-validation==1.2.12",
    "typing-extensions==4.16.0",
)
RUNTIME_PROFILE_V2 = "autoformal-runtime-v2"
RUNTIME_EXTRA_V2 = "autoformal-validator-runtime-v2"
RUNTIME_REQUIREMENTS_V2 = (*RUNTIME_REQUIREMENTS_V1, "spacy==3.8.14")
RUNTIME_PROFILES = {
    RUNTIME_PROFILE_V1: (RUNTIME_EXTRA_V1, RUNTIME_REQUIREMENTS_V1),
    RUNTIME_PROFILE_V2: (RUNTIME_EXTRA_V2, RUNTIME_REQUIREMENTS_V2),
}


def read_regular(root: Path, relative: str) -> bytes:
    """Bound operator reads and reject symlinks, including parent components."""
    path = root / relative
    if path.absolute() != path.resolve(strict=True) or not path.resolve().is_relative_to(root):
        raise ValueError("deployment path is not canonical: " + relative)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError("deployment file is not bounded regular data: " + relative)
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if len(raw) > MAX_FILE_BYTES or any(getattr(after, field) != getattr(before, field) for field in fields):
        raise ValueError("deployment file changed during read: " + relative)
    return raw


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def profile_in(project: dict):
    return project.get("tool", {}).get("ipfs-accelerate-agent-supervisor", {}).get("sealed-python-validator")


def build_profile(repository: Path, packet_root: Path, *, interpreter: str = "python3",
                  runtime_profile: str = "") -> dict:
    repository = repository.resolve(strict=True)
    if packet_root.absolute() != packet_root.resolve(strict=True) or not packet_root.is_dir():
        raise ValueError("packet root must be a canonical existing directory")
    if interpreter != "python3":
        raise ValueError("interpreter is outside the reviewed native policy")
    project = tomllib.loads(read_regular(repository, "pyproject.toml").decode())
    base = project["tool"]["ipfs-accelerate-agent-supervisor"]["project-dependency-preflight"]
    authority = dict(base["authority"])
    if runtime_profile and runtime_profile not in RUNTIME_PROFILES:
        raise ValueError("unsupported validator runtime profile")
    if runtime_profile:
        extra, reviewed_requirements = RUNTIME_PROFILES[runtime_profile]
        authority.update(extra=extra,
                         **{"extra-requirements-sha256": digest(canonical_bytes(list(reviewed_requirements)))})
    setup = read_regular(repository, "setup.py")
    if authority["file"] != "setup.py":
        raise ValueError("unsupported setup authority")
    # A new, explicitly operator-applied deployment anchors the actual current
    # setup file. The selected extra must still match its reviewed digest below.
    # Existing profiles/receipts are never silently refreshed or overwritten.
    authority["sha256"] = digest(setup)
    calls = [node for node in ast.walk(ast.parse(setup)) if isinstance(node, ast.Call)
             and ((isinstance(node.func, ast.Name) and node.func.id == "setup")
                  or (isinstance(node.func, ast.Attribute) and node.func.attr == "setup"))]
    if len(calls) != 1 or any(key.arg is None for key in calls[0].keywords):
        raise ValueError("setup authority must be one static call")
    extras = [key.value for key in calls[0].keywords if key.arg == "extras_require"]
    if len(extras) != 1 or not isinstance(extras[0], ast.Dict):
        raise ValueError("setup extras must be literal")
    keys = [ast.literal_eval(key) for key in extras[0].keys]
    if any(type(key) is not str for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("setup extra keys must be unique strings")
    requirements = ast.literal_eval(extras[0].values[keys.index(authority["extra"])])
    if type(requirements) is not list or any(type(item) is not str for item in requirements):
        raise ValueError("setup extra requirements must be literal strings")
    if digest(canonical_bytes(requirements)) != authority["extra-requirements-sha256"]:
        raise ValueError("setup extra authority changed")
    # The protected validator uses pytest's built-ins, disables third-party
    # plugin auto-loading and inherited addopts, and does not load conftests.
    selected = [item for item in requirements if item.startswith("pytest>=")]
    if len(selected) != 1 or ";" in selected[0]:
        raise ValueError("expected exactly one reviewed unconditional pytest requirement")
    if runtime_profile:
        if requirements != list(reviewed_requirements):
            raise ValueError("runtime requirements differ from reviewed version")
        selected = requirements
    seals, size = [], len(setup)
    for relative in SEALED_FILES:
        raw = read_regular(repository, relative)
        size += len(raw)
        seals.append({"path": relative, "sha256": digest(raw)})
    if len(seals) >= 16 or size > MAX_FILE_BYTES:
        raise ValueError("deployment exceeds native manifest bounds")
    return {"schema": PROFILE_SCHEMA, "requires-python": project["project"]["requires-python"],
            "authority": authority, "requirements": selected, "interpreter": interpreter,
            "entrypoint": ENTRYPOINT, "sealed-files": seals, "packet-root": str(packet_root),
            "packet-schema": SCHEMA, "board-namespace": NAMESPACE,
            "edit-scopes": {key: list(value) for key, value in EDIT_SCOPES.items()},
            "regression-tests": list(REGRESSION_TESTS),
            "regression-directory": "tests/unit/logic/autoformal_repairs"}


def toml_value(value) -> str:
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(key) + " = " + toml_value(item)
                                 for key, item in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def deployment_path(repository: Path) -> Path:
    return repository.parent / (repository.name + "-validator-profile.json")


def profile_patch(repository: Path, packet_root: Path, *, runtime_profile: str = "") -> str:
    """Generate an apply_patch payload; do not edit repository source here."""
    original = read_regular(repository, "pyproject.toml").decode()
    if profile_in(tomllib.loads(original)) is not None or deployment_path(repository).exists():
        raise ValueError("deployment already exists; prepare a new private snapshot")
    profile = build_profile(repository, packet_root, runtime_profile=runtime_profile)
    suffix = "\n[tool.ipfs-accelerate-agent-supervisor.sealed-python-validator]\n"
    suffix += "\n".join(key + " = " + toml_value(value) for key, value in profile.items()) + "\n"
    if profile_in(tomllib.loads(original + suffix)) != profile:
        raise ValueError("generated TOML failed roundtrip")
    context = original.splitlines()[-3:]
    return ("*** Begin Patch\n*** Update File: " + str(repository / "pyproject.toml")
            + "\n@@\n" + "\n".join(" " + line for line in context) + "\n"
            + "\n".join("+" + line for line in suffix.splitlines()) + "\n*** End Patch\n")


def seal_deployment(repository: Path, packet_root: Path, *, runtime_profile: str = "") -> dict:
    """Seal only the exact independently regenerated profile, without overwrite."""
    profile = build_profile(repository, packet_root, runtime_profile=runtime_profile)
    if profile_in(tomllib.loads(read_regular(repository, "pyproject.toml").decode())) != profile:
        raise ValueError("installed profile differs from generated policy")
    receipt = {"schema": SEAL_SCHEMA, "repository": str(repository),
               "files": {path: digest(read_regular(repository, path)) for path in DEPLOYMENT_PROTECTED},
               "published": False, "production_promotion": False}
    with deployment_path(repository).open("xb") as stream:
        stream.write(canonical_bytes(receipt))
    return receipt


def require_deployment(repository: Path) -> dict | None:
    """Fail closed on missing seals, file drift, or profile removal after seal."""
    repository = repository.resolve(strict=True)
    path = deployment_path(repository)
    pyproject = repository / "pyproject.toml"
    # Keep unconfigured repositories and synthetic read-only queue tests on
    # the existing native policy; this helper never authorizes a command.
    profile = (profile_in(tomllib.loads(read_regular(repository, "pyproject.toml").decode()))
               if pyproject.exists() else None)
    if profile is None and not path.exists() and not path.is_symlink():
        return None
    if profile is None or not path.exists() or path.is_symlink():
        raise ValueError("sealed validator deployment or operator receipt is missing")
    receipt = json.loads(read_regular(repository.parent, path.name))
    if (set(receipt) != {"schema", "repository", "files", "published", "production_promotion"}
            or receipt["schema"] != SEAL_SCHEMA or receipt["repository"] != str(repository)
            or receipt["published"] is not False or receipt["production_promotion"] is not False
            or set(receipt["files"]) != set(DEPLOYMENT_PROTECTED)):
        raise ValueError("invalid sealed validator deployment receipt")
    for relative, expected in receipt["files"].items():
        if digest(read_regular(repository, relative)) != expected:
            raise ValueError("sealed validator deployment drift: " + relative)
    return {"receipt": str(path), "sha256": digest(canonical_bytes(receipt)), "passed": True}
