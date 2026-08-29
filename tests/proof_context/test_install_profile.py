"""Install-profile checks for the immutable datasets proof-context artifact."""

from __future__ import annotations

import base64
import csv
import email
import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATE_EPOCH = "0"
CANONICAL_EXTRAS = {
    "all",
    "api",
    "file-conversion",
    "groth16",
    "ipld",
    "knowledge-graphs",
    "lazy",
    "legal-netherlands",
    "logic",
    "multimedia",
    "ocr",
    "profile-f-zk",
    "provekit",
    "scraping",
    "symai-router",
    "test",
    "theorem-provers",
    "vectors",
    "wallets",
    "wallets-all",
    "wallets-bitcoin",
    "wallets-ethereum",
    "wallets-solana",
    "wallets-worldcoin",
    "wallets-xaman",
    "wallets-xrpl",
}
_EXTRA_MARKER_COMPARISON = re.compile(r'(\bextra\s*(?:==|!=)\s*")([^"]+)(")')
CURRENT_HEAD_RECEIPT_SCHEMA = (
    "lift_coding.proof-carrying-semantic-minification."
    "datasets-package-current-head@1"
)


@dataclass(frozen=True)
class ArtifactEvidence:
    path: Path
    sha256: str
    contents_manifest_sha256: str
    member_count: int
    record_sha256: str | None = None


@dataclass(frozen=True)
class ArtifactPair:
    wheel: ArtifactEvidence
    sdist: ArtifactEvidence


def _run(
    args: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"command failed ({completed.returncode}): {args!r}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return completed


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_safe_archive_path(name: str) -> None:
    path = PurePosixPath(name)
    assert not path.is_absolute()
    assert ".." not in path.parts
    assert "\\" not in name


def _archive_manifest(path: Path) -> tuple[str, int]:
    records: list[dict[str, object]] = []
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for member in sorted(archive.infolist(), key=lambda item: item.filename):
                _assert_safe_archive_path(member.filename)
                if member.is_dir():
                    continue
                payload = archive.read(member)
                records.append(
                    {
                        "path": member.filename,
                        "size": member.file_size,
                        "sha256": _sha256_bytes(payload),
                    }
                )
    else:
        with tarfile.open(path) as archive:
            for member in sorted(archive.getmembers(), key=lambda item: item.name):
                _assert_safe_archive_path(member.name)
                record: dict[str, object] = {
                    "path": member.name,
                    "type": member.type.decode("ascii"),
                    "mode": member.mode,
                    "size": member.size,
                }
                if member.isfile():
                    extracted = archive.extractfile(member)
                    assert extracted is not None
                    record["sha256"] = _sha256_bytes(extracted.read())
                elif member.issym() or member.islnk():
                    record["linkname"] = member.linkname
                records.append(record)
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_bytes(canonical), len(records)


def _wheel_record_sha256(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        file_members = {member.filename for member in archive.infolist() if not member.is_dir()}
        (record_name,) = (name for name in file_members if name.endswith(".dist-info/RECORD"))
        record_payload = archive.read(record_name)
        rows = {
            name: (encoded_digest, size)
            for name, encoded_digest, size in csv.reader(
                io.StringIO(record_payload.decode("utf-8"))
            )
        }
        assert set(rows) == file_members
        for name, (encoded_digest, size) in rows.items():
            if name == record_name:
                assert encoded_digest == ""
                assert size == ""
                continue
            payload = archive.read(name)
            algorithm, expected = encoded_digest.split("=", maxsplit=1)
            assert algorithm == "sha256"
            actual = base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            assert actual.rstrip(b"=").decode("ascii") == expected
            assert int(size) == len(payload)
    return _sha256_bytes(record_payload)


def _evidence(path: Path) -> ArtifactEvidence:
    manifest_sha256, member_count = _archive_manifest(path)
    return ArtifactEvidence(
        path=path,
        sha256=_sha256_file(path),
        contents_manifest_sha256=manifest_sha256,
        member_count=member_count,
        record_sha256=_wheel_record_sha256(path) if path.suffix == ".whl" else None,
    )


def _build_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "LC_ALL": "C.UTF-8",
            "PATH": os.defpath,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONHASHSEED": "0",
            "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH,
            "TZ": "UTC",
        }
    )
    return environment


def _isolated_environment(home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": str(home),
        "IPFS_DATASETS_AUTO_INSTALL": "0",
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
        "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
        "LC_ALL": "C.UTF-8",
        "PATH": os.defpath,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_NO_INDEX": "1",
        "PYTHONNOUSERSITE": "1",
        "TZ": "UTC",
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
    }


def _build_artifacts(output: Path, *, source_root: Path = PROJECT_ROOT) -> ArtifactPair:
    output.mkdir(parents=True)
    _run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--sdist",
            "--outdir",
            str(output),
            str(source_root),
        ],
        cwd=output.parent,
        env=_build_environment(),
    )
    wheels = list(output.glob("*.whl"))
    sdists = list(output.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    return ArtifactPair(wheel=_evidence(wheels[0]), sdist=_evidence(sdists[0]))


def _linked_source_copy(destination: Path) -> Path:
    """Create a disposable build source without duplicating large key assets."""

    def link_or_copy(source: str, target: str) -> str:
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        return target

    shutil.copytree(
        PROJECT_ROOT,
        destination,
        copy_function=link_or_copy,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "build",
            "dist",
        ),
    )
    return destination


def _restrict_build_tree_modes(root: Path) -> None:
    """Model a warm build tree created beneath a supervisor umask of 077."""

    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            source_mode = stat.S_IMODE(path.stat().st_mode)
            path.chmod(0o700 if source_mode & 0o111 else 0o600)


def _source_egg_info_snapshot(
    source_root: Path = PROJECT_ROOT,
) -> dict[str, tuple[int, int, int, str]]:
    root = source_root / "ipfs_datasets_py.egg-info"
    snapshot: dict[str, tuple[int, int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            metadata = path.stat()
            snapshot[str(path.relative_to(root))] = (
                stat.S_IMODE(metadata.st_mode),
                metadata.st_mtime_ns,
                metadata.st_size,
                _sha256_file(path),
            )
    return snapshot


def _outer_receipt() -> Path | None:
    # A standalone datasets checkout has no outer package receipt. In a
    # composed workspace, prefer the exact-current-tree PCSM qualification
    # receipt. The historical PCCE-050 receipt remains immutable release
    # evidence and is only the compatibility fallback for its original tree.
    if PROJECT_ROOT.parent.name != "external":
        return None
    workspace_root = PROJECT_ROOT.parents[1]
    current = (
        workspace_root
        / "artifacts"
        / "proof_carrying_semantic_minification"
        / "handoff"
        / "datasets-proof-context-current-head.json"
    )
    if current.is_file():
        return current
    historical = (
        workspace_root
        / "artifacts"
        / "proof_carrying_context_engine"
        / "receipts"
        / "PCCE-050.json"
    )
    return historical if historical.is_file() else None


def _source_git_identity() -> tuple[str, str]:
    completed = _run(
        ["git", "rev-parse", "HEAD", "HEAD^{tree}"],
        cwd=PROJECT_ROOT,
    )
    lines = completed.stdout.splitlines()
    assert len(lines) == 2
    assert all(re.fullmatch(r"[0-9a-f]{40}", value) for value in lines)
    return lines[0], lines[1]


def _digest_value(value: object) -> str:
    assert isinstance(value, str)
    return value.removeprefix("sha256:")


def _canonical_requirement(value: str) -> tuple[str, tuple[str, ...], str, str, str | None]:
    requirement = Requirement(value)
    marker = str(requirement.marker or "")
    # packaging<26 preserves legacy underscores in ``extra`` marker values,
    # while newer releases normalize them according to PEP 685.  Both spellings
    # identify the same extra, so compare their canonical names instead of
    # making artifact validation depend on the host packaging release.
    marker = _EXTRA_MARKER_COMPARISON.sub(
        lambda match: f"{match.group(1)}{canonicalize_name(match.group(2))}{match.group(3)}",
        marker,
    )
    return (
        canonicalize_name(requirement.name),
        tuple(sorted(canonicalize_name(extra) for extra in requirement.extras)),
        str(requirement.specifier),
        marker,
        requirement.url,
    )


def test_requirement_comparison_canonicalizes_legacy_extra_markers() -> None:
    underscored = 'faiss-cpu>=1.7.0; platform_system == "Windows" and extra == "legal_netherlands"'
    hyphenated = 'faiss-cpu>=1.7.0; platform_system == "Windows" and extra == "legal-netherlands"'

    assert _canonical_requirement(underscored) == _canonical_requirement(hyphenated)


def _assert_receipt_binding(pair: ArtifactPair) -> None:
    receipt_path = _outer_receipt()
    if receipt_path is None:
        return
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") == CURRENT_HEAD_RECEIPT_SCHEMA:
        assert receipt["status"] == "qualified_current_head"
        source_binding = receipt["source_binding"]
        commit, tree = _source_git_identity()
        assert source_binding["repository"] == "ipfs_datasets_py"
        assert source_binding["commit"] == commit
        assert source_binding["tree"] == tree
    else:
        assert receipt["task_id"] == "PCCE-050"
        assert receipt["status"] == "completed"
    artifacts = receipt.get("artifacts") or receipt["evidence"]["artifacts"]
    reproducibility = receipt["evidence"]["reproducibility"]
    assert str(reproducibility["source_date_epoch"]) == SOURCE_DATE_EPOCH
    assert reproducibility["build_count"] >= 2
    assert reproducibility["byte_identical"] is True
    for name, actual in (("wheel", pair.wheel), ("sdist", pair.sdist)):
        expected = artifacts[name]
        assert expected["filename"] == actual.path.name
        assert _digest_value(expected["sha256"]) == actual.sha256
        assert (
            _digest_value(expected["contents_manifest_sha256"]) == actual.contents_manifest_sha256
        )
        assert expected["member_count"] == actual.member_count
        if name == "wheel":
            assert actual.record_sha256 is not None
            assert _digest_value(expected["record_sha256"]) == actual.record_sha256


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> ArtifactPair:
    temporary_root = tmp_path_factory.mktemp("package-artifacts")
    source_root = _linked_source_copy(temporary_root / "source")
    egg_info_before = _source_egg_info_snapshot(source_root)
    first = _build_artifacts(temporary_root / "first", source_root=source_root)
    assert _source_egg_info_snapshot(source_root) == egg_info_before
    build_root = source_root / "build"
    assert (build_root / "egg-info" / "ipfs_datasets_py.egg-info").is_dir()

    # A supervisor creates its worktree and build outputs under umask 077.
    # Deliberately make the second build warm *and* permission-restricted;
    # wheel bytes must not inherit either piece of ambient build state.
    _restrict_build_tree_modes(build_root)
    second = _build_artifacts(temporary_root / "second", source_root=source_root)
    assert _source_egg_info_snapshot(source_root) == egg_info_before

    assert first.wheel.path.name == second.wheel.path.name
    assert first.sdist.path.name == second.sdist.path.name
    assert first.wheel.sha256 == second.wheel.sha256
    assert first.sdist.sha256 == second.sdist.sha256
    assert first.wheel.contents_manifest_sha256 == second.wheel.contents_manifest_sha256
    assert first.sdist.contents_manifest_sha256 == second.sdist.contents_manifest_sha256
    assert first.wheel.record_sha256 == second.wheel.record_sha256
    _assert_receipt_binding(first)
    return first


def test_wheel_and_sdist_preserve_provider_and_packaging_contract(
    artifacts: ArtifactPair,
) -> None:
    wheel = artifacts.wheel.path
    sdist = artifacts.sdist.path

    assert not wheel.name.endswith("-none-any.whl")
    _distribution, _version, _build, filename_tags = parse_wheel_filename(wheel.name)
    assert filename_tags & set(sys_tags())
    assert any(tag.platform == "linux_aarch64" for tag in filename_tags)
    vendor_files = (
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "src/index.ts",
        "src/cli.ts",
    )
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        member_modes = {
            member.filename: (member.external_attr >> 16) & 0o777
            for member in archive.infolist()
            if not member.is_dir()
        }
        (record_name,) = (name for name in members if name.endswith(".dist-info/RECORD"))
        # wheel 0.42 materializes RECORD directly in the archive with its
        # fixed 0664 mode; every staging-tree member uses our canonical mode.
        assert member_modes.pop(record_name) == 0o664
        assert set(member_modes.values()) <= {0o644, 0o755}
        (metadata_name,) = (name for name in members if name.endswith(".dist-info/METADATA"))
        (wheel_metadata_name,) = (name for name in members if name.endswith(".dist-info/WHEEL"))
        (entry_points_name,) = (
            name for name in members if name.endswith(".dist-info/entry_points.txt")
        )
        metadata = email.message_from_bytes(archive.read(metadata_name))
        wheel_metadata = archive.read(wheel_metadata_name).decode("utf-8")
        entry_points = archive.read(entry_points_name).decode("utf-8")
        vendor_payloads = {}
        for relative in vendor_files:
            (vendor_name,) = (
                name
                for name in members
                if name.endswith(f"/ipfs_datasets_py/_vendor/logic-runtime-mtl/{relative}")
            )
            vendor_payloads[relative] = archive.read(vendor_name)

        native_binaries = {
            name
            for name in members
            if "/processors/groth16_backend/bin/" in f"/{name}" and name.endswith("/groth16")
        }
        assert native_binaries
        for name in native_binaries:
            payload = archive.read(name)
            mode = archive.getinfo(name).external_attr >> 16
            assert mode & 0o111
            assert "/linux-aarch64/" in name
            assert payload.startswith(b"\x7fELF")
            byteorder = "little" if payload[5] == 1 else "big"
            assert int.from_bytes(payload[18:20], byteorder) == 183

    assert "Root-Is-Purelib: false" in wheel_metadata
    wheel_tags = [
        line.removeprefix("Tag: ")
        for line in wheel_metadata.splitlines()
        if line.startswith("Tag: ")
    ]
    assert wheel_tags and all(not tag.endswith("-any") for tag in wheel_tags)
    assert any(name.endswith("/ipfs_datasets_py/proof_context/__init__.py") for name in members)
    assert any(name.endswith("/ipfs_datasets_py/proof_context/provider.py") for name in members)
    assert any(name.endswith("/ipfs_datasets_cli.py") for name in members)
    assert platform.machine().lower() in {"aarch64", "arm64"}
    assert not any(
        "/_vendor/logic-runtime-mtl/node_modules/" in f"/{name}"
        or "/_vendor/logic-runtime-mtl/dist/" in f"/{name}"
        for name in members
    )
    assert not any(".egg-info/" in name for name in members)
    for command in (
        "ipfs-datasets-install-provers = ipfs_datasets_py.logic.integration.bridges.prover_installer:main",
        "ipfs-datasets-sms-bridge = ipfs_datasets_py.messaging.sms_bridge:main",
        "ipfs-netherlands-laws = ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli:main",
        "netherlands-laws = ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli:main",
        "semantic-index = ipfs_datasets_py.cli.semantic_index_cli:main",
    ):
        assert command in entry_points

    assert metadata["Name"] == "ipfs_datasets_py"
    assert metadata["Version"] == "0.2.0"
    core_requirements = [
        value for value in metadata.get_all("Requires-Dist", []) if "extra ==" not in value
    ]
    assert core_requirements == []
    all_requirements = metadata.get_all("Requires-Dist", [])
    parsed_requirements = [Requirement(value) for value in all_requirements]
    assert all(requirement.url is None for requirement in parsed_requirements)
    assert not any(
        "git+" in value or "file:" in value or "@main" in value for value in all_requirements
    )
    normalized_extras = {
        extra.lower().replace("_", "-") for extra in metadata.get_all("Provides-Extra", [])
    }
    assert normalized_extras == CANONICAL_EXTRAS

    with tarfile.open(sdist) as archive:
        names = set(archive.getnames())
        source_prefix = sdist.name.removesuffix(".tar.gz")
        sdist_metadata = email.message_from_bytes(
            archive.extractfile(f"{source_prefix}/PKG-INFO").read()
        )
        for relative, wheel_payload in vendor_payloads.items():
            source_name = f"{source_prefix}/typescript/logic-runtime-mtl/{relative}"
            extracted = archive.extractfile(source_name)
            assert extracted is not None
            assert extracted.read() == wheel_payload
    assert f"{source_prefix}/PKG-INFO" in names
    assert f"{source_prefix}/ipfs_datasets_py/proof_context/provider.py" in names
    assert f"{source_prefix}/ipfs_datasets_cli.py" in names
    assert metadata["Name"] == sdist_metadata["Name"]
    assert metadata["Version"] == sdist_metadata["Version"]
    assert sorted(
        _canonical_requirement(value) for value in metadata.get_all("Requires-Dist", [])
    ) == sorted(
        _canonical_requirement(value) for value in sdist_metadata.get_all("Requires-Dist", [])
    )
    assert not any(
        "/typescript/logic-runtime-mtl/node_modules/" in f"/{name}"
        or "/typescript/logic-runtime-mtl/dist/" in f"/{name}"
        for name in names
    )
    assert not any(any(part.endswith(".egg-info") for part in Path(name).parts) for name in names)


def test_installed_wheel_exports_provider_without_source_tree_or_dependencies(
    artifacts: ArtifactPair, tmp_path: Path
) -> None:
    wheel = artifacts.wheel.path
    venv = tmp_path / "venv"
    home = tmp_path / "home"
    environment = _isolated_environment(home)
    assert "PYTHONHOME" not in environment
    assert "PYTHONPATH" not in environment

    contaminated = tmp_path / "contaminated"
    fake_metadata = contaminated / "ipfs_datasets_py-0.2.0.dist-info" / "METADATA"
    fake_metadata.parent.mkdir(parents=True)
    fake_metadata.write_text(
        "Metadata-Version: 2.1\nName: ipfs_datasets_py\nVersion: 0.2.0\n",
        encoding="utf-8",
    )
    polluted_environment = environment | {"PYTHONPATH": str(contaminated)}
    contaminated_probe = _run(
        [
            sys.executable,
            "-c",
            "import importlib.metadata as m; print(m.distribution('ipfs_datasets_py')._path)",
        ],
        cwd=tmp_path,
        env=polluted_environment,
    )
    assert str(contaminated) in contaminated_probe.stdout

    _run(
        [sys.executable, "-I", "-m", "venv", str(venv)],
        cwd=tmp_path,
        env=environment,
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run(
        [
            str(python),
            "-I",
            "-c",
            (
                "import importlib.metadata as m; "
                "assert not list(m.distributions(name='ipfs_datasets_py'))"
            ),
        ],
        cwd=tmp_path,
        env=environment,
    )
    _run(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-index",
            str(wheel),
        ],
        cwd=tmp_path,
        env=environment,
    )

    environment["PCCE_PROJECT_ROOT"] = str(PROJECT_ROOT)
    probe = """
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import sysconfig

def reject_network(event, _args):
    if event.startswith('socket.'):
        raise AssertionError(f'network audit event during import: {event}')

sys.addaudithook(reject_network)
import ipfs_datasets_py.proof_context as port
assert 'ipfs_datasets_py.proof_context.provider' not in sys.modules
provider = port.get_provider()
installed_root = Path(sysconfig.get_paths()['platlib']).resolve()
module_path = Path(port.__file__).resolve()
assert module_path.is_relative_to(installed_root)
distribution = importlib.metadata.distribution('ipfs_datasets_py')
assert distribution.version == '0.2.0'
assert Path(distribution.locate_file('')).resolve().is_relative_to(installed_root)
direct_url = distribution.read_text('direct_url.json') or ''
assert os.environ['PCCE_PROJECT_ROOT'] not in direct_url
for pth in installed_root.glob('*.pth'):
    assert os.environ['PCCE_PROJECT_ROOT'] not in pth.read_text(encoding='utf-8')
assert port.SCHEMA == provider.schema
assert port.INTERFACE == provider.interface
assert port.PRODUCER == provider.producer
assert 'ipfs_kit_py' not in sys.modules
assert 'ipfs_accelerate_py' not in sys.modules
from ipfs_datasets_py.logic.backends.installers.runtime_mtl import resolve_vendor_package_root
vendor = resolve_vendor_package_root()
assert vendor.is_relative_to(installed_root)
assert (vendor / 'package-lock.json').is_file()
assert (vendor / 'src' / 'index.ts').is_file()
print(json.dumps({'module': str(module_path), 'network_audit': 'passed', 'vendor': str(vendor)}, sort_keys=True))
"""
    result = _run(
        [str(python), "-I", "-c", probe],
        cwd=tmp_path,
        env=environment,
    )
    evidence = json.loads(result.stdout)
    assert evidence["network_audit"] == "passed"
    assert str(PROJECT_ROOT) not in evidence["module"]
    assert str(PROJECT_ROOT) not in evidence["vendor"]
    assert "site-packages/ipfs_datasets_py/proof_context/__init__.py" in evidence["module"]
