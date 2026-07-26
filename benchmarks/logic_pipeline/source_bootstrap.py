"""Minimal two-stage bootstrap for the production HSSL-G240 executor.

This file is launched directly as a tracked repository script.  That is
deliberate: ``python -m benchmarks.logic_pipeline...`` would execute the
package's broad convenience initializer before this boundary could apply
Landlock.

Before confinement, the bootstrap loads only a small standard-library prefix
of the package initializer plus the CID, Landlock, and bootstrap-contract
modules.  It authenticates Git/source observations, reconstructs the exact
parent-held private policy from canonical stdin, applies Landlock, emits one
atomic canonical ``G240LandlockReceiptV1`` frame on the dedicated pipe, closes
that pipe, and only then imports the source executor.
"""

from __future__ import annotations

import ast
import importlib
from importlib.abc import MetaPathFinder
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import ModuleType
from importlib.machinery import ModuleSpec
from typing import Final


_MAX_PRIVATE_POLICY_BYTES: Final = 16 * 1024 * 1024
_MAX_RECEIPT_BYTES: Final = 64 * 1024
_GIT_OBJECT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SUBMODULE_PATH: Final = Path("ipfs_accelerate_py")
_CANONICAL_PACKAGE: Final = "ipfs_accelerate_py"


class G240SourceBootstrapError(RuntimeError):
    """Raised before stage two when launch confinement cannot be proved."""


class _ExactTrackedSourceFinder(MetaPathFinder):
    """Resolve reviewed worktree modules without enumerating source dirs."""

    def __init__(
        self,
        modules: dict[str, tuple[Path, bool]],
    ) -> None:
        self._modules = dict(modules)

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> object:
        del path, target
        source = self._modules.get(fullname)
        if source is None:
            return None
        source_path, is_package = source
        return importlib.util.spec_from_file_location(
            fullname,
            source_path,
            submodule_search_locations=(
                [source_path.parent.as_posix()]
                if is_package
                else None
            ),
        )


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, member in pairs:
        if key in value:
            raise G240SourceBootstrapError(
                f"duplicate bootstrap JSON key: {key}"
            )
        value[key] = member
    return value


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value or "\0" in value:
        raise G240SourceBootstrapError(
            f"required bootstrap environment is absent: {name}"
        )
    return value


def _new_package(name: str, directory: Path) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = (directory / "__init__.py").as_posix()
    module.__package__ = name
    module.__path__ = [directory.as_posix()]  # type: ignore[attr-defined]
    spec = ModuleSpec(name, loader=None, is_package=True)
    spec.submodule_search_locations = [directory.as_posix()]
    module.__spec__ = spec
    sys.modules[name] = module
    return module


def _install_minimal_package(repository_root: Path) -> None:
    """Execute only the side-effect-free package core before confinement."""

    benchmarks_root = repository_root / "benchmarks"
    package_root = benchmarks_root / "logic_pipeline"
    if any(
        name in sys.modules for name in ("benchmarks", "benchmarks.logic_pipeline")
    ):
        raise G240SourceBootstrapError(
            "benchmark package was imported before the minimal bootstrap"
        )
    benchmarks = _new_package("benchmarks", benchmarks_root)
    logic_pipeline = _new_package(
        "benchmarks.logic_pipeline", package_root
    )
    setattr(benchmarks, "logic_pipeline", logic_pipeline)
    initializer = package_root / "__init__.py"
    try:
        source = initializer.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=initializer.as_posix())
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise G240SourceBootstrapError(
            "cannot parse the tracked lightweight package initializer"
        ) from exc
    prefix: list[ast.stmt] = []
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.level:
            break
        prefix.append(statement)
    if not prefix or not any(
        isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        )
        for statement in prefix
    ):
        raise G240SourceBootstrapError(
            "lightweight package initializer boundary changed"
        )
    minimal_tree = ast.Module(
        body=prefix,
        type_ignores=tree.type_ignores,
    )
    ast.fix_missing_locations(minimal_tree)
    exec(
        compile(
            minimal_tree,
            initializer.as_posix(),
            "exec",
            dont_inherit=True,
        ),
        logic_pipeline.__dict__,
    )


def _load_tracked_module(name: str, path: Path) -> ModuleType:
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError("tracked module has no loader")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _load_bootstrap_dependencies(
    repository_root: Path,
) -> tuple[ModuleType, ModuleType, ModuleType]:
    package_root = repository_root / "benchmarks" / "logic_pipeline"
    content = _load_tracked_module(
        "benchmarks.logic_pipeline.content_addressing",
        package_root / "content_addressing.py",
    )
    confinement = _load_tracked_module(
        "benchmarks.logic_pipeline.runtime_confinement",
        package_root / "runtime_confinement.py",
    )
    contract = _load_tracked_module(
        "benchmarks.logic_pipeline.source_bootstrap_contract",
        package_root / "source_bootstrap_contract.py",
    )
    return content, confinement, contract


def _install_exact_source_finder(
    repository_root: Path,
    read_only_paths: tuple[Path, ...],
) -> None:
    """Map each explicitly granted tracked Python file to one module name."""

    modules: dict[str, tuple[Path, bool]] = {}
    for source_path in read_only_paths:
        if source_path.suffix != ".py":
            continue
        try:
            relative = source_path.relative_to(repository_root)
        except ValueError:
            continue
        parts = relative.parts
        if (
            len(parts) >= 3
            and parts[0] == "ipfs_accelerate_py"
            and parts[1] == "ipfs_accelerate_py"
        ):
            parts = parts[1:]
        if not parts:
            continue
        is_package = parts[-1] == "__init__.py"
        module_parts = (
            parts[:-1]
            if is_package
            else (*parts[:-1], Path(parts[-1]).stem)
        )
        if not module_parts or any(
            not part.isidentifier() for part in module_parts
        ):
            continue
        module_name = ".".join(module_parts)
        previous = modules.get(module_name)
        candidate = (source_path, is_package)
        if previous is not None and previous != candidate:
            raise G240SourceBootstrapError(
                "reviewed source map contains a duplicate module"
            )
        modules[module_name] = candidate
    if "benchmarks.logic_pipeline.source_executor" not in modules:
        raise G240SourceBootstrapError(
            "reviewed source map lacks the stage-two executor"
        )
    sys.meta_path.insert(0, _ExactTrackedSourceFinder(modules))


def _receipt_descriptor() -> int:
    raw = _required_environment("HSSL_G240_LANDLOCK_RECEIPT_FD")
    try:
        descriptor = int(raw, 10)
        metadata = os.fstat(descriptor)
    except (OSError, ValueError) as exc:
        raise G240SourceBootstrapError(
            "Landlock receipt descriptor is invalid"
        ) from exc
    if descriptor <= 2 or not stat.S_ISFIFO(metadata.st_mode):
        raise G240SourceBootstrapError(
            "Landlock receipt channel must be one dedicated pipe"
        )
    return descriptor


def _observe_inherited_descriptors(
    receipt_descriptor: int | None,
) -> tuple[int, int, int]:
    """Reject every live inherited descriptor except stdio and the pipe."""

    try:
        if len(os.listdir("/proc/self/task")) != 1:
            raise G240SourceBootstrapError(
                "bootstrap must remain single-threaded before Landlock"
            )
        listed = tuple(
            int(name)
            for name in os.listdir("/proc/self/fd")
            if name.isdigit()
        )
    except OSError as exc:
        raise G240SourceBootstrapError(
            "cannot inspect bootstrap threads/descriptors"
        ) from exc
    live: set[int] = set()
    sockets = 0
    for descriptor in listed:
        try:
            metadata = os.fstat(descriptor)
        except OSError:
            # ``/proc/self/fd`` may transiently list its own already-closed
            # directory descriptor.  Only descriptors that remain live count.
            continue
        live.add(descriptor)
        sockets += int(stat.S_ISSOCK(metadata.st_mode))
    expected = {0, 1, 2}
    if receipt_descriptor is not None:
        expected.add(receipt_descriptor)
    unexpected = sorted(live - expected)
    if unexpected:
        for descriptor in unexpected:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise G240SourceBootstrapError(
            "unexpected inherited bootstrap descriptors were closed"
        )
    if live != expected or sockets:
        raise G240SourceBootstrapError(
            "bootstrap descriptor set differs from stdio plus its receipt pipe"
        )
    return len(live), len(unexpected), sockets


def _authenticated_git(
    content: ModuleType,
) -> Path:
    raw_path = _required_environment(
        "HSSL_G240_GIT_EXECUTABLE_PATH"
    )
    raw_cid = _required_environment(
        "HSSL_G240_GIT_EXECUTABLE_CID"
    )
    try:
        requested = Path(raw_path)
        if not requested.is_absolute():
            raise OSError("Git executable is not absolute")
        executable = requested.resolve(strict=True)
        metadata = executable.lstat()
        payload = executable.read_bytes()
        expected_cid = content.validate_cid(raw_cid, codecs=("raw",))
    except (OSError, TypeError, ValueError) as exc:
        raise G240SourceBootstrapError(
            "cannot authenticate the pinned Git executable"
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not payload
        or content.cid_for_bytes(payload) != expected_cid
    ):
        raise G240SourceBootstrapError(
            "pinned Git executable differs from its raw CID"
        )
    return executable


def _git(
    executable: Path,
    repository: Path,
    *arguments: str,
    input_text: str | None = None,
    preserve_output: bool = False,
) -> str:
    try:
        result = subprocess.run(
            (
                executable.as_posix(),
                "--no-replace-objects",
                "--no-pager",
                "--no-optional-locks",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.excludesFile=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.untrackedCache=false",
                "-c",
                "protocol.allow=never",
                "-C",
                repository.as_posix(),
                *arguments,
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            close_fds=True,
            shell=False,
            input=input_text,
            stdin=(
                subprocess.DEVNULL
                if input_text is None
                else None
            ),
            env={
                "PATH": os.defpath,
                "GIT_ALLOW_PROTOCOL": "file",
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_CONFIG_COUNT": "0",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_PROTOCOL_FROM_USER": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise G240SourceBootstrapError(
            "bootstrap Git observation failed"
        ) from exc
    return result.stdout if preserve_output else result.stdout.strip()


def _reject_effective_checkout_filters(
    executable: Path,
    repository: Path,
    commit: str,
) -> None:
    """Reject pinned or info/worktree filter selection before Git status."""

    if not _GIT_OBJECT.fullmatch(commit):
        raise G240SourceBootstrapError(
            "bootstrap filter preflight commit is invalid"
        )
    for source_bound in (True, False):
        raw_paths = _git(
            executable,
            repository,
            *(
                (
                    "ls-tree",
                    "-r",
                    "-z",
                    "--name-only",
                    "--full-tree",
                    commit,
                )
                if source_bound
                else ("ls-files", "-z")
            ),
            preserve_output=True,
        )
        paths = raw_paths.split("\0")
        if paths[-1] != "" or any(not path for path in paths[:-1]):
            raise G240SourceBootstrapError(
                "bootstrap filter path inventory is malformed"
            )
        attribute_arguments = (
            (
                "check-attr",
                f"--source={commit}",
                "-z",
                "--stdin",
                "filter",
            )
            if source_bound
            else ("check-attr", "-z", "--stdin", "filter")
        )
        raw_attributes = _git(
            executable,
            repository,
            *attribute_arguments,
            input_text=raw_paths,
            preserve_output=True,
        )
        attributes = raw_attributes.split("\0")
        if attributes[-1:] != [""]:
            raise G240SourceBootstrapError(
                "bootstrap filter evidence is malformed"
            )
        attributes = attributes[:-1]
        expected_paths = paths[:-1]
        if len(attributes) != len(expected_paths) * 3:
            raise G240SourceBootstrapError(
                "bootstrap filter evidence is incomplete"
            )
        for index, expected_path in enumerate(expected_paths):
            path, attribute, value = attributes[
                index * 3 : index * 3 + 3
            ]
            if (
                path != expected_path
                or attribute != "filter"
                or value not in {"unspecified", "unset"}
            ):
                raise G240SourceBootstrapError(
                    "effective bootstrap Git filters are forbidden"
                )


def _observe_source(
    repository_root: Path,
    executable: Path,
) -> tuple[str, str | None, Path | None]:
    expected = _required_environment(
        "HSSL_G240_EXPECTED_SOURCE_COMMIT"
    )
    head = _git(executable, repository_root, "rev-parse", "--verify", "HEAD")
    if (
        not _GIT_OBJECT.fullmatch(expected)
        or head != expected
    ):
        raise G240SourceBootstrapError(
            "bootstrap source checkout differs from the frozen clean commit"
        )
    _reject_effective_checkout_filters(
        executable,
        repository_root,
        head,
    )
    if _git(
        executable,
        repository_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=all",
    ):
        raise G240SourceBootstrapError(
            "bootstrap source checkout differs from the frozen clean commit"
        )
    tree_line = _git(
        executable,
        repository_root,
        "ls-tree",
        "HEAD",
        "--",
        _SUBMODULE_PATH.as_posix(),
    )
    if not tree_line:
        return head, None, None
    metadata, separator, recorded_path = tree_line.partition("\t")
    fields = metadata.split()
    if (
        separator != "\t"
        or recorded_path != _SUBMODULE_PATH.as_posix()
        or len(fields) != 3
        or fields[0] != "160000"
        or fields[1] != "commit"
        or not _GIT_OBJECT.fullmatch(fields[2])
    ):
        raise G240SourceBootstrapError(
            "bootstrap source has an invalid ipfs_accelerate_py gitlink"
        )
    submodule = repository_root / _SUBMODULE_PATH
    package = submodule / _CANONICAL_PACKAGE
    try:
        if (
            submodule.resolve(strict=True) != submodule
            or package.resolve(strict=True) != package
            or not (package / "__init__.py").is_file()
        ):
            raise OSError("source-bound package path changed")
    except OSError as exc:
        raise G240SourceBootstrapError(
            "source-bound ipfs_accelerate_py package is unavailable"
        ) from exc
    local_commit = _git(
        executable,
        submodule,
        "rev-parse",
        "--verify",
        "HEAD^{commit}",
    )
    if local_commit != fields[2]:
        raise G240SourceBootstrapError(
            "source-bound package differs from its pinned gitlink"
        )
    _reject_effective_checkout_filters(
        executable,
        submodule,
        local_commit,
    )
    if _git(
        executable,
        submodule,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=all",
        "--",
        _CANONICAL_PACKAGE,
    ):
        raise G240SourceBootstrapError(
            "source-bound package differs from its pinned gitlink"
        )
    return head, local_commit, package


def _read_private_policy() -> object:
    raw = sys.stdin.buffer.read(_MAX_PRIVATE_POLICY_BYTES + 1)
    if (
        not raw
        or len(raw) > _MAX_PRIVATE_POLICY_BYTES
        or not raw.endswith(b"\n")
        or raw.endswith(b"\n\n")
    ):
        raise G240SourceBootstrapError(
            "bootstrap private policy framing is invalid"
        )
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise G240SourceBootstrapError(
            "bootstrap private policy is not strict JSON"
        ) from exc
    return value


def _write_landlock_receipt(
    descriptor: int,
    receipt: object,
    content: ModuleType,
) -> bytes:
    payload = content.canonical_dag_json_bytes(receipt.to_dict()) + b"\n"
    try:
        pipe_bound = int(os.fpathconf(descriptor, "PC_PIPE_BUF"))
    except (OSError, ValueError) as exc:
        raise G240SourceBootstrapError(
            "cannot authenticate receipt-pipe atomicity"
        ) from exc
    if not payload or len(payload) > min(pipe_bound, _MAX_RECEIPT_BYTES):
        raise G240SourceBootstrapError(
            "Landlock receipt exceeds the one-shot atomic frame"
        )
    try:
        written = os.write(descriptor, payload)
    except OSError as exc:
        raise G240SourceBootstrapError(
            "cannot write the one-shot Landlock receipt"
        ) from exc
    if written != len(payload):
        raise G240SourceBootstrapError(
            "one-shot Landlock receipt write was incomplete"
        )
    return payload


def _stage_two() -> int:
    executor = importlib.import_module(
        "benchmarks.logic_pipeline.source_executor"
    )
    return int(
        executor.main(
            _bootstrap_capability=(
                executor._G240_BOOTSTRAP_STAGE2_CAPABILITY_V2
            )
        )
    )


def main() -> int:
    if len(sys.argv) != 1:
        raise G240SourceBootstrapError(
            "G240 source bootstrap accepts no command-line arguments"
        )
    repository_root = Path(__file__).resolve(strict=True).parents[2]
    if Path.cwd().resolve(strict=True) != repository_root:
        raise G240SourceBootstrapError(
            "G240 source bootstrap must run at its authenticated worktree root"
        )
    _install_minimal_package(repository_root)
    content, confinement, contract = _load_bootstrap_dependencies(
        repository_root
    )
    expected_profile = _required_environment(
        "HSSL_G240_CONFINEMENT_PROFILE_CID"
    )
    if (
        content.validate_cid(expected_profile, codecs=("dag-json",))
        != contract.G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
    ):
        raise G240SourceBootstrapError(
            "bootstrap confinement profile differs from the contract"
        )
    synthetic = (
        "HSSL_G240_TEST_ONLY_SYNTHETIC_REQUEST_CID" in os.environ
    )
    receipt_descriptor = None if synthetic else _receipt_descriptor()
    (
        inherited_descriptor_count,
        unexpected_inherited_descriptor_count,
        inherited_socket_count,
    ) = _observe_inherited_descriptors(receipt_descriptor)
    executable = _authenticated_git(content)
    source_commit, gitlink_commit, package = _observe_source(
        repository_root,
        executable,
    )
    policy = None
    landlock_receipt = None
    if synthetic:
        if sys.stdin.buffer.read(1):
            raise G240SourceBootstrapError(
                "synthetic bootstrap may not receive production policy bytes"
            )
    else:
        private_value = _read_private_policy()
        private_sources = (
            contract.g240_private_landlock_sources_from_payload_v2(
                private_value
            )
        )
        rebuilt_sources = confinement.build_g240_landlock_policy_v1(
            read_only_paths=private_sources.read_only_paths,
            state_path=private_sources.state_path,
            output_path=private_sources.output_path,
            cache_paths=private_sources.cache_paths,
            approved_tcp_ports=private_sources.approved_tcp_ports,
        )
        if (
            rebuilt_sources.policy.to_dict()
            != private_sources.policy.to_dict()
        ):
            raise G240SourceBootstrapError(
                "bootstrap-rebuilt Landlock policy differs from its parent"
            )
        _install_exact_source_finder(
            repository_root,
            rebuilt_sources.read_only_paths,
        )
        policy = rebuilt_sources.policy
        landlock_receipt = confinement.apply_g240_landlock_confinement(
            rebuilt_sources
        )
        try:
            _write_landlock_receipt(
                receipt_descriptor,
                landlock_receipt,
                content,
            )
        finally:
            assert receipt_descriptor is not None
            os.close(receipt_descriptor)
    source_observation_cid = contract.g240_bootstrap_git_observation_cid(
        source_commit,
        role="source",
    )
    gitlink_observation_cid = (
        None
        if gitlink_commit is None
        else contract.g240_bootstrap_git_observation_cid(
            gitlink_commit,
            role="ipfs-accelerate-gitlink",
        )
    )
    bootstrap_receipt = contract.G240BootstrapConfinementReceiptV2(
        confinement_profile_cid=expected_profile,
        landlock_policy=(
            None if policy is None else policy.to_dict()
        ),
        landlock_receipt=(
            None
            if landlock_receipt is None
            else landlock_receipt.to_dict()
        ),
        source_commit_observation_cid=source_observation_cid,
        source_bound_gitlink_observation_cid=(
            gitlink_observation_cid
        ),
        inherited_descriptor_count=inherited_descriptor_count,
        unexpected_inherited_descriptor_count=(
            unexpected_inherited_descriptor_count
        ),
        inherited_socket_count=inherited_socket_count,
        close_fds_observed=True,
        receipt_channel_one_shot=not synthetic,
        git_observed_before_confinement=True,
        execution_request_opened_before_confinement=False,
        confinement_applied=not synthetic,
        stage2_authorized=True,
        synthetic_test_only=synthetic,
    )
    os.environ["HSSL_G240_BOOTSTRAP_RECEIPT_JSON"] = (
        content.canonical_dag_json_bytes(
            bootstrap_receipt.to_dict()
        ).decode("utf-8")
    )
    os.environ["HSSL_G240_BOOTSTRAP_SOURCE_COMMIT"] = source_commit
    if package is not None and gitlink_commit is not None:
        os.environ[
            "HSSL_G240_SOURCE_BOUND_IPFS_ACCELERATE_PACKAGE_PATH"
        ] = package.as_posix()
        os.environ[
            "HSSL_G240_SOURCE_BOUND_IPFS_ACCELERATE_GITLINK_COMMIT"
        ] = gitlink_commit
    os.environ.pop("HSSL_G240_LANDLOCK_RECEIPT_FD", None)
    os.environ.pop("HSSL_G240_EXPECTED_SOURCE_COMMIT", None)
    return _stage_two()


if __name__ == "__main__":
    raise SystemExit(main())
