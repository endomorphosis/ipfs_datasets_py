"""Import the pinned local ``ipfs_accelerate_py`` submodule deterministically.

The repository contains ``ipfs_accelerate_py`` as a Git submodule whose Python
package is nested one level deeper.  With only the repository root on
``sys.path``, Python interprets the outer directory as a namespace package and
cannot find ``ipfs_accelerate_py.agent_supervisor``.  Adding a checkout-specific
path globally would make behavior depend on process import order.

This module instead binds the canonical package namespace to the exact nested
package in this source checkout.  Before the first load it also verifies that
the submodule HEAD is the gitlink pinned by the enclosing repository.  A benign
outer-directory namespace created by the detached layout is repaired; a real
package or namespace from any other location is rejected.  Importing this
module itself performs no Git commands and imports no optional runtime package.

The benchmark intentionally installs lightweight package namespaces instead
of executing the broad ``ipfs_accelerate_py`` and ``agent_supervisor`` package
initializers.  This resolver is for the dedicated, isolated benchmark process:
it exposes explicitly imported local modules, not every package convenience
export.
"""

from __future__ import annotations

from functools import lru_cache
import importlib
from importlib.machinery import ModuleSpec
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
from types import ModuleType
from typing import Final

from .content_addressing import cid_for_bytes, validate_cid


_CANONICAL_PACKAGE: Final = "ipfs_accelerate_py"
_SUBMODULE_PATH: Final = Path("ipfs_accelerate_py")
_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_GIT_OBJECT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_IMPORT_LOCK = threading.RLock()


class SourceBoundImportError(ImportError):
    """Raised when the local package cannot be bound to its pinned gitlink."""


def _git(repository: Path, *arguments: str) -> str:
    executable_value = os.environ.get("HSSL_G240_GIT_EXECUTABLE_PATH")
    executable_cid_value = os.environ.get("HSSL_G240_GIT_EXECUTABLE_CID")
    if (executable_value is None) != (executable_cid_value is None):
        raise SourceBoundImportError(
            "partial pinned Git authority is forbidden"
        )
    executable = "git"
    if executable_value is not None:
        try:
            requested = Path(executable_value)
            if not requested.is_absolute():
                raise OSError("Git path is not absolute")
            resolved = requested.resolve(strict=True)
            metadata = resolved.lstat()
            payload = resolved.read_bytes()
            expected_cid = validate_cid(
                executable_cid_value,
                codecs=("raw",),
            )
        except (OSError, TypeError, ValueError) as exc:
            raise SourceBoundImportError(
                "cannot authenticate the pinned Git executable"
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or not payload
            or cid_for_bytes(payload) != expected_cid
        ):
            raise SourceBoundImportError(
                "pinned Git executable differs from its raw CID"
            )
        executable = resolved.as_posix()
    try:
        completed = subprocess.run(
            (executable, "-C", str(repository), *arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env={
                "PATH": os.defpath,
                "GIT_CONFIG_COUNT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceBoundImportError(
            "cannot verify the local ipfs_accelerate_py git binding"
        ) from exc
    if completed.returncode != 0:
        raise SourceBoundImportError(
            "cannot verify the local ipfs_accelerate_py git binding"
        )
    return completed.stdout.strip()


def _strict_directory(path: Path, *, field_name: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SourceBoundImportError(f"{field_name} is unavailable") from exc
    if not resolved.is_dir() or path.absolute() != resolved:
        raise SourceBoundImportError(
            f"{field_name} must be a real, non-symlink directory"
        )
    return resolved


@lru_cache(maxsize=1)
def _pinned_package_directory() -> Path:
    """Return the exact nested package after checking the enclosing gitlink.

    Source reconciliation makes the benchmark checkout clean, detached, and
    immutable for one matrix process.  Cache that binding so a 560-coordinate
    run does not invoke Git at every stage boundary.
    """

    repository = _strict_directory(
        Path(__file__).resolve().parents[2],
        field_name="benchmark source root",
    )
    submodule = _strict_directory(
        repository / _SUBMODULE_PATH,
        field_name="ipfs_accelerate_py submodule",
    )
    package = _strict_directory(
        submodule / _CANONICAL_PACKAGE,
        field_name="ipfs_accelerate_py package",
    )
    package_initializer = package / "__init__.py"
    if (
        not package_initializer.is_file()
        or package_initializer.is_symlink()
    ):
        raise SourceBoundImportError(
            "local ipfs_accelerate_py package initializer is unavailable"
        )

    bootstrap_package = os.environ.get(
        "HSSL_G240_SOURCE_BOUND_IPFS_ACCELERATE_PACKAGE_PATH"
    )
    bootstrap_gitlink = os.environ.get(
        "HSSL_G240_SOURCE_BOUND_IPFS_ACCELERATE_GITLINK_COMMIT"
    )
    if (bootstrap_package is None) != (bootstrap_gitlink is None):
        raise SourceBoundImportError(
            "partial bootstrap source-bound authority is forbidden"
        )
    if bootstrap_package is not None:
        try:
            observed_package = Path(bootstrap_package).resolve(strict=True)
        except OSError as exc:
            raise SourceBoundImportError(
                "bootstrap source-bound package is unavailable"
            ) from exc
        if (
            "HSSL_G240_BOOTSTRAP_RECEIPT_JSON" not in os.environ
            or observed_package != package
            or not isinstance(bootstrap_gitlink, str)
            or not _GIT_OBJECT.fullmatch(bootstrap_gitlink)
        ):
            raise SourceBoundImportError(
                "bootstrap source-bound package authority changed"
            )
        # The tracked stage-one bootstrap performed the enclosing ls-tree,
        # submodule HEAD, and clean-package observations before Landlock.  The
        # stage-two process is the same process, so this branch deliberately
        # performs no post-confinement Git or .git access.
        return package

    tree_line = _git(
        repository,
        "ls-tree",
        "HEAD",
        "--",
        _SUBMODULE_PATH.as_posix(),
    )
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
        raise SourceBoundImportError(
            "enclosing source does not pin ipfs_accelerate_py as a gitlink"
        )
    pinned_commit = fields[2]
    local_commit = _git(submodule, "rev-parse", "--verify", "HEAD^{commit}")
    if local_commit != pinned_commit:
        raise SourceBoundImportError(
            "local ipfs_accelerate_py HEAD differs from the pinned gitlink"
        )
    local_root = Path(_git(submodule, "rev-parse", "--show-toplevel")).resolve(
        strict=True
    )
    if local_root != submodule:
        raise SourceBoundImportError(
            "local ipfs_accelerate_py package belongs to a different worktree"
        )
    if _git(
        submodule,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        _CANONICAL_PACKAGE,
    ):
        raise SourceBoundImportError(
            "local ipfs_accelerate_py package differs from its pinned commit"
        )
    return package


def _namespace(name: str, directory: Path) -> ModuleType:
    parent_name, separator, child_name = name.rpartition(".")
    parent = sys.modules.get(parent_name) if separator else None
    if separator and parent is None:
        raise SourceBoundImportError(
            "source-bound package namespace parent is unavailable"
        )

    def attach(module: ModuleType) -> ModuleType:
        if parent is None:
            return module
        sentinel = object()
        current = getattr(parent, child_name, sentinel)
        if current is not sentinel and current is not module:
            raise SourceBoundImportError(
                "source-bound package namespace attribute is inconsistent"
            )
        setattr(parent, child_name, module)
        return module

    existing = sys.modules.get(name)
    if existing is not None:
        actual_file = getattr(existing, "__file__", None)
        expected_file = directory / "__init__.py"
        try:
            resolved_file = (
                Path(actual_file).resolve(strict=True)
                if actual_file is not None
                else None
            )
            locations = tuple(
                Path(item).resolve(strict=True)
                for item in getattr(existing, "__path__", ())
            )
        except (OSError, TypeError) as exc:
            raise SourceBoundImportError(
                "source-bound package namespace has an invalid path"
            ) from exc
        if (
            locations != (directory,)
            or (
                resolved_file is not None
                and resolved_file != expected_file.resolve(strict=True)
            )
        ):
            raise SourceBoundImportError(
                "canonical ipfs_accelerate_py package is not source-bound"
            )
        return attach(existing)

    module = ModuleType(name)
    module.__package__ = name
    module.__path__ = [str(directory)]  # type: ignore[attr-defined]
    spec = ModuleSpec(name, loader=None, is_package=True)
    spec.submodule_search_locations = [str(directory)]
    module.__spec__ = spec
    sys.modules[name] = module
    try:
        return attach(module)
    except Exception:
        sys.modules.pop(name, None)
        raise


def _bind_canonical_root(package: Path) -> ModuleType:
    """Repair only the empty outer-directory namespace from this checkout."""

    existing = sys.modules.get(_CANONICAL_PACKAGE)
    if existing is None:
        return _namespace(_CANONICAL_PACKAGE, package)

    actual_file = getattr(existing, "__file__", None)
    if actual_file is not None:
        return _namespace(_CANONICAL_PACKAGE, package)
    try:
        locations = tuple(
            Path(item).resolve(strict=True)
            for item in getattr(existing, "__path__", ())
        )
    except (OSError, TypeError) as exc:
        raise SourceBoundImportError(
            "canonical ipfs_accelerate_py namespace has an invalid path"
        ) from exc
    if locations == (package,):
        return existing

    # With just the enclosing repository on sys.path, importing the canonical
    # name creates this empty namespace at the Git submodule root.  It has no
    # package code and is safe to replace with the exact nested package.
    if locations != (package.parent,):
        raise SourceBoundImportError(
            "canonical ipfs_accelerate_py namespace is not the local submodule"
        )
    descendants = tuple(
        name
        for name in sys.modules
        if name.startswith(_CANONICAL_PACKAGE + ".")
    )
    if descendants:
        raise SourceBoundImportError(
            "outer ipfs_accelerate_py namespace already has imported children"
        )
    del sys.modules[_CANONICAL_PACKAGE]
    return _namespace(_CANONICAL_PACKAGE, package)


def _validate_loaded_descendants(package: Path) -> None:
    """Reject preloaded canonical children that came from another package."""

    prefix = _CANONICAL_PACKAGE + "."
    for name, module in tuple(sys.modules.items()):
        if not name.startswith(prefix) or module is None:
            continue
        actual_file = getattr(module, "__file__", None)
        raw_locations = getattr(module, "__path__", ())
        try:
            locations = tuple(
                Path(item).resolve(strict=True) for item in raw_locations
            )
            resolved_file = (
                Path(actual_file).resolve(strict=True)
                if actual_file is not None
                else None
            )
        except (OSError, TypeError) as exc:
            raise SourceBoundImportError(
                f"preloaded canonical module {name!r} has an invalid path"
            ) from exc
        candidates = (*locations, *((resolved_file,) if resolved_file else ()))
        if not candidates:
            raise SourceBoundImportError(
                f"preloaded canonical module {name!r} has no source path"
            )
        for candidate in candidates:
            try:
                candidate.relative_to(package)
            except ValueError as exc:
                raise SourceBoundImportError(
                    f"preloaded canonical module {name!r} is not source-bound"
                ) from exc


def _relative_module_name(module_name: str) -> tuple[str, ...]:
    prefix = _CANONICAL_PACKAGE + "."
    if not isinstance(module_name, str) or not module_name.startswith(prefix):
        raise SourceBoundImportError(
            "source-bound module must be inside ipfs_accelerate_py"
        )
    components = tuple(module_name[len(prefix) :].split("."))
    if not components or any(
        not _MODULE_NAME.fullmatch(component) for component in components
    ):
        raise SourceBoundImportError("source-bound module name is invalid")
    return components


def _expected_module_path(package: Path, components: tuple[str, ...]) -> Path:
    base = package.joinpath(*components)
    module_file = base.with_suffix(".py")
    package_file = base / "__init__.py"
    if module_file.is_file() and not module_file.is_symlink():
        return module_file.resolve(strict=True)
    if package_file.is_file() and not package_file.is_symlink():
        return package_file.resolve(strict=True)
    raise SourceBoundImportError(
        "requested source-bound ipfs_accelerate_py module is unavailable"
    )


def import_source_bound_ipfs_accelerate(module_name: str) -> ModuleType:
    """Import one module from the exact locally pinned submodule checkout.

    An empty namespace rooted at the outer Git submodule directory is the
    expected detached-checkout ambiguity and is repaired.  Any unrelated
    canonical package is rejected instead of being used or silently replaced.
    The returned module's resolved file must exactly match the requested file
    beneath the gitlink-bound package.
    """

    components = _relative_module_name(module_name)
    package = _pinned_package_directory()
    expected = _expected_module_path(package, components)

    with _IMPORT_LOCK:
        _validate_loaded_descendants(package)
        _bind_canonical_root(package)
        for index in range(1, len(components)):
            directory = package.joinpath(*components[:index])
            initializer = directory / "__init__.py"
            if not initializer.is_file():
                break
            if initializer.is_symlink():
                raise SourceBoundImportError(
                    "source-bound package initializer must not be a symlink"
                )
            _namespace(
                ".".join((_CANONICAL_PACKAGE, *components[:index])),
                _strict_directory(
                    directory,
                    field_name="source-bound package directory",
                ),
            )
        try:
            module = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError) as exc:
            raise SourceBoundImportError(
                f"cannot import source-bound module {module_name!r}"
            ) from exc
        actual_file = getattr(module, "__file__", None)
        try:
            actual = Path(actual_file).resolve(strict=True)
        except (OSError, TypeError) as exc:
            raise SourceBoundImportError(
                f"source-bound module {module_name!r} has no real file"
            ) from exc
        if actual != expected:
            raise SourceBoundImportError(
                f"source-bound module {module_name!r} resolved outside its "
                "pinned local package"
            )
        return module


__all__ = [
    "SourceBoundImportError",
    "import_source_bound_ipfs_accelerate",
]
