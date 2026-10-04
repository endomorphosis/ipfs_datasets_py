"""Read-only Hyper dependency planning and explicit provenance-archive setup.

Plans describe filesystem candidates, never version validation or installation
success. Importing this module performs no discovery. Compiler provisioning,
source extraction, native probes and builds remain separate installer work.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat


def _inputs(tool_id, install_root, dependency_roots, archive_cache_root):
    from . import hyperproperty as hp
    if not isinstance(tool_id, str) or tool_id not in hp.EXTERNAL_TOOLS:
        raise ValueError("tool_id must be hyperltl, autohyper or mchyper")
    if install_root is None:
        from ...external_provers.lazy_installer import configured_user_install_root
        root = configured_user_install_root()
    else:
        root = _absolute_path(install_root)
    roots = hp._validated_dependency_roots(dependency_roots)
    allowed = set()
    for spec in hp._dependency_specs(tool_id):
        allowed.update((spec["name"], *spec["candidates"],
                        *hp._DEPENDENCY_ROOT_GROUPS.get(spec["name"], ())))
    if tool_id == hp.TOOL_MCHYPER:
        allowed.update(("ghc-package-db", "haskell-package-db"))
        for name, _, _, _ in _archive_specs(hp):
            allowed.update((name + "-source", name + "-source-root",
                            name + "-archive", name + "-source-archive"))
    if any(key not in allowed for key in roots):
        raise ValueError("unknown dependency root for this Hyper tool")
    roots = {key: str(_absolute_path(value)) for key, value in roots.items()}
    cache = root / "downloads" if archive_cache_root is None else _absolute_path(archive_cache_root)
    return hp, root, roots, cache


def _absolute_path(value):
    if not isinstance(value, (str, Path)):
        raise ValueError("setup paths must be strings or Paths")
    text = str(value)
    try:
        valid = bool(text) and text == text.strip() and "\x00" not in text and len(text.encode("utf-8")) <= 4096
    except UnicodeError:
        valid = False
    path = Path(text).expanduser() if valid else Path()
    if not valid or not path.is_absolute():
        raise ValueError("setup paths must be bounded absolute paths")
    # Preserve symlinks lexically: the downloader must see and refuse a poisoned
    # cache ancestor rather than receiving an already-resolved mutation target.
    return Path(os.path.abspath(path))


def _archive_specs(hp):
    return (
        ("aiger", hp.MCHYPER_AIGER_VERSION, hp.MCHYPER_AIGER_SOURCE_ARCHIVE_URL, hp.MCHYPER_AIGER_SOURCE_ARCHIVE_SHA256),
        ("abc", hp.MCHYPER_ABC_GIT_COMMIT, hp.MCHYPER_ABC_SOURCE_ARCHIVE_URL, hp.MCHYPER_ABC_SOURCE_ARCHIVE_SHA256),
        ("python", hp.MCHYPER_PYTHON_VERSION, hp.MCHYPER_PYTHON_SOURCE_ARCHIVE_URL, hp.MCHYPER_PYTHON_SOURCE_ARCHIVE_SHA256),
    )


def _archive_filename(name, version):
    return f"Python-{version}.tar.xz" if name == "python" else f"{name}-{version}.tar.gz"


def _archive_observation(hp, path, *, required=False):
    """Observe a real cache path without opening files or following links."""
    from .install_control import installation_checkpoint
    installation_checkpoint("before Hyper archive path observation")
    try:
        for parent in path.parents:
            try:
                details = parent.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(details.st_mode):
                raise hp.HyperpropertyInstallBlocked(
                    "source archive parent must be a real directory", "source_archive_fetch_failed")
        try:
            details = path.lstat()
        except FileNotFoundError:
            if not required:
                return None
            raise hp.HyperpropertyInstallBlocked(
                "prepared source archive is missing", "source_archive_fetch_failed")
        if not stat.S_ISREG(details.st_mode):
            raise hp.HyperpropertyInstallBlocked(
                "source archive must be a regular file", "source_archive_fetch_failed")
        return tuple(getattr(details, key) for key in
                     ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))
    except OSError as error:
        raise hp.HyperpropertyInstallBlocked(
            "source archive path inspection failed", "source_archive_fetch_failed") from error


def _archive_targets(hp, roots, cache):
    """Preflight every effective choice before the first archive mutation."""
    selected = []
    for name, version, url, digest in _archive_specs(hp):
        target = next((Path(roots[key]) for key in (name + "-archive", name + "-source-archive")
                       if key in roots), cache / _archive_filename(name, version))
        observed = _archive_observation(hp, target)
        for _, previous, previous_digest, _, previous_observed in selected:
            same_file = (observed is not None and previous_observed is not None
                         and observed[:2] == previous_observed[:2])
            if ((target == previous or same_file) and digest != previous_digest
                    or target in previous.parents or previous in target.parents):
                raise hp.HyperpropertyInstallBlocked(
                    "source archives have conflicting destinations", "source_archive_destination_conflict")
        selected.append((name, target, digest, url, observed))
    return selected


def _verify_prepared_archives(hp, verified):
    """Recheck the final files under the same bounded, cancellable operation.

    Observations detect replacement during this check; they do not lock the
    cache against other writers or attest to bytes after this function returns.
    """
    from .install_control import current_install_limits, installation_checkpoint
    maximum = current_install_limits().max_download_bytes
    observations = []
    for row in verified:
        path = Path(row["path"])
        before = _archive_observation(hp, path, required=True)
        try:
            digest = hp._sha256_file(path, max_bytes=maximum)
        except OSError as error:
            raise hp.HyperpropertyInstallBlocked(
                "prepared source archive could not be read", "source_archive_fetch_failed") from error
        after = _archive_observation(hp, path, required=True)
        if before != after:
            raise hp.HyperpropertyInstallBlocked(
                "prepared source archive changed during verification", "source_archive_changed")
        if digest != row["sha256"]:
            raise hp.HyperpropertyInstallBlocked(
                "prepared source archive digest mismatch", "source_archive_digest_mismatch")
        observations.append((path, after))
    for path, expected in observations:
        if _archive_observation(hp, path, required=True) != expected:
            raise hp.HyperpropertyInstallBlocked(
                "prepared source archive changed during verification", "source_archive_changed")
    installation_checkpoint("after Hyper prepared archive verification")


def _regular(path):
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _coherent_switch(hp, root, roots, blockers):
    names = ("ocamlc", "ocamlbuild", "ocamlfind", "menhir", "dune")
    if any(key in roots for key in (*names, "opam", "opam-switch", "ocaml")):
        return
    candidates = [root / "opam" / name for name in ("ipfs-datasets-coq", "ipfs-datasets-proverif")]
    complete = [path for path in candidates if all(_regular(path / "bin" / name) for name in names)]
    if len(complete) == 1:
        roots["opam-switch"] = str(complete[0].resolve())
    elif len(complete) > 1:
        blockers.append("ambiguous_managed_dependency:opam-switch")


def plan_hyperproperty_setup(tool_id, *, install_root=None, dependency_roots=None,
                            archive_cache_root=None):
    """Return detached candidate roots without probes, hashes, writes or locks.

    ``install_root`` is the existing managed dependency base, which may differ
    from a later fresh engine installation destination. ``archive_cache_root``
    selects an optional separate provenance-archive cache. Explicit dependency
    paths override discovered groups. Executable presence does not establish
    version compatibility; the normal vendor installer performs that validation.
    """
    hp, root, roots, cache = _inputs(tool_id, install_root, dependency_roots, archive_cache_root)
    blockers = []
    platform = hp._detect_platform()
    if platform not in hp.SUPPORTED_HOSTS:
        blockers.append("unsupported_platform:" + platform)
    if tool_id == hp.TOOL_HYPERLTL:
        _coherent_switch(hp, root, roots, blockers)
    elif tool_id == hp.TOOL_AUTOHYPER:
        arch = {hp.LINUX_AARCH64: "arm64", hp.LINUX_X86_64: "x64"}.get(platform)
        if arch:
            sdk = root / f"dotnet-sdk-{hp.AUTOHYPER_DOTNET_SDK}-linux-{arch}"
            if sdk.is_dir() and not any(key in roots for key in ("dotnet", "dotnet-sdk")):
                roots["dotnet-sdk"] = str(sdk.resolve())
        spot = root / f"spot-{hp.AUTOHYPER_SPOT_VERSION.removeprefix('>=')}-{platform}"
        if spot.is_dir() and not any(key in roots for key in ("spot", "autfilt", "ltl2tgba")):
            roots["spot"] = str(spot.resolve())
    else:
        base = root / "build-dependencies" / "mchyper"
        candidates = {
            "ghcup": base / ".ghcup", "python-root": base / f"python-{hp.MCHYPER_PYTHON_VERSION}",
            "abc-root": base / f"abc-{hp.MCHYPER_ABC_GIT_COMMIT}", "aiger-root": base / f"aiger-{hp.MCHYPER_AIGER_VERSION}",
        }
        group_aliases = {"ghcup": ("ghcup", "ghcup-bin"),
                         "python-root": ("python", "python-root"),
                         "abc-root": ("abc-root",), "aiger-root": ("aiger", "aiger-root")}
        for key, path in candidates.items():
            if path.is_dir() and not any(alias in roots for alias in group_aliases[key]):
                roots.setdefault(key, str(path.resolve()))
    dependencies = []
    for spec in hp._dependency_specs(tool_id):
        invalid_explicit = False
        try:
            selected = hp._executable_from_dependency_roots(spec["name"], spec["candidates"], roots)
        except hp.HyperpropertyInstallBlocked as error:
            blockers.extend(error.block_reasons)
            selected, invalid_explicit = None, True
        source = "dependency_roots"
        if selected is None and not invalid_explicit:
            selected = next((found for name in spec["candidates"] if (found := shutil.which(name))), None)
            source = "PATH"
        if selected is not None and not _regular(Path(selected)):
            selected = None
        if selected is None:
            blockers.append("missing_dependency:" + spec["name"])
        dependencies.append({"name": spec["name"], "constraint": spec["constraint"],
            "phase": spec.get("phase", "build"), "candidate_path": str(Path(selected).resolve()) if selected else None,
            "candidate_found": selected is not None, "source": source if selected else None,
            "version_validated": False})
    archives = []
    if tool_id == hp.TOOL_MCHYPER:
        ghc = next(item["candidate_path"] for item in dependencies if item["name"] == "ghc")
        if ghc and not any(key in roots for key in ("ghc-package-db", "haskell-package-db")):
            try:
                version = Path(ghc).relative_to(root / "build-dependencies/mchyper/.ghcup/ghc").parts[0]
            except ValueError:
                version = ""
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
                db = root / f"build-dependencies/mchyper/cabal/store/ghc-{version}/package.db"
                if db.is_dir():
                    roots["ghc-package-db"] = str(db.resolve())
        db = hp._dependency_root_path(roots, "ghc-package-db", "haskell-package-db")
        if db is None or not db.is_dir():
            blockers.append("missing_dependency:ghc-package-db")
        for name, version, url, digest in _archive_specs(hp):
            source = root / "sources" / (f"Python-{version}" if name == "python" else f"{name}-{version}")
            if source.is_dir() and not any(key in roots for key in (name + "-source", name + "-source-root")):
                roots[name + "-source"] = str(source.resolve())
            source = hp._dependency_root_path(roots, name + "-source", name + "-source-root")
            if source is None or not source.is_dir():
                blockers.append("missing_dependency_evidence:" + name + "-source")
            archive = hp._dependency_root_path(roots, name + "-archive", name + "-source-archive")
            if archive is None:
                archive = cache / _archive_filename(name, version)
                if archive.is_file() and not archive.is_symlink():
                    roots[name + "-archive"] = str(archive)
            present = archive.is_file() and not archive.is_symlink()
            if not present:
                blockers.append("missing_dependency_archive:" + name)
            archives.append({"name": name, "path": str(archive), "candidate_found": present,
                "expected_sha256": digest, "url": url, "digest_verified": False})
    return {"tool_id": tool_id, "managed_dependency_root": str(root), "archive_cache_root": str(cache),
        "status": "candidates_require_validation" if not blockers else "missing_or_ambiguous_dependencies",
        "dependency_roots": dict(roots), "dependencies": dependencies, "provenance_archives": archives,
        "blockers": list(dict.fromkeys(blockers)), "validation_required": True,
        "installed": False, "native_probes_run": False, "bootstrap_performed": False,
        "verified_archives": [], "notes": [
            "Candidates are filesystem observations; versions, package coherence and provenance require installer validation.",
            "Missing compilers/runtime packages require separate provisioning; this API does not install them.",
            "MCHyper requires exact pinned source archives in addition to binaries and source trees."]}


def prepare_hyperproperty_dependencies(tool_id, *, yes=False, install_root=None,
        dependency_roots=None, archive_cache_root=None, limits=None,
        operation_timeout_ms=None, cancellation=None, scheduler=None, parent_lease=None):
    """Explicitly verify/fetch only MCHyper's three reviewed source archives.

    The default returns an inert plan. ``yes=True`` writes only explicit archive
    destinations, or the selected cache when none is supplied, using the
    existing bounded digest-checking downloader. It
    never extracts sources, provisions compilers, probes tools or installs an
    engine. An existing verified archive may be reused; corrupt cache contents
    are replaced only after a verified transfer. Conflicting destinations are
    refused before any download, and all prepared files are rehashed before
    reporting verification. This is a bounded observation, not protection from
    changes after return. No resource lease is acquired.
    """
    if type(yes) is not bool:
        raise ValueError("yes must be a bool")
    if not yes:
        return plan_hyperproperty_setup(tool_id, install_root=install_root,
            dependency_roots=dependency_roots, archive_cache_root=archive_cache_root)
    from .install_control import installation_scope, installation_checkpoint
    with installation_scope(limits=limits, operation_timeout_ms=operation_timeout_ms,
            cancellation=cancellation, scheduler=scheduler, parent_lease=parent_lease):
        hp, root, roots, cache = _inputs(tool_id, install_root, dependency_roots, archive_cache_root)
        verified = []
        if tool_id == hp.TOOL_MCHYPER:
            selected = _archive_targets(hp, roots, cache)
            for name, target, digest, url, _ in selected:
                installation_checkpoint("before Hyper dependency archive")
                path = hp._download_verified_archive(url, target, digest)
                if Path(path) != target:
                    raise hp.HyperpropertyInstallBlocked(
                        "prepared archive destination changed", "source_archive_destination_conflict")
                roots[name + "-archive"] = str(path)
                verified.append({"name": name, "path": str(path), "sha256": digest,
                                 "url": url, "verification": "bounded_download_or_verified_cache"})
        result = plan_hyperproperty_setup(tool_id, install_root=root, dependency_roots=roots,
                                         archive_cache_root=cache)
        _verify_prepared_archives(hp, verified)
        result["verified_archives"] = verified
        for row in result["provenance_archives"]:
            row["digest_verified"] = any(item["name"] == row["name"] and item["path"] == row["path"] for item in verified)
        installation_checkpoint("before Hyper dependency preparation result")
        return result


__all__ = ["plan_hyperproperty_setup", "prepare_hyperproperty_dependencies"]
