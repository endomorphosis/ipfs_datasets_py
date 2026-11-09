"""Finite source-identity bridge for six retained experimental LegalIR kernels.

This is a declared compatibility policy, not proof of numerical equivalence or
authentication of historical physical paths. Legacy producer references remain
unchanged in caller checkpoints; new producer recipes bind this bridge's bytes.
Only exact retained producer identities or exact current package identities are
accepted. A mixed generation is refused. No checkpoint or artifact is opened.
"""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path, PurePosixPath
import stat

SCHEMA = "legal-ir-experimental-source-profile-bridge/v1"
_HERE = Path(__file__).absolute().parent
_SPECS = {
    "context_initialization": (
        "projected_context_decoder_v1.py", 22244,
        "de68e2ed3975c3ae27c6ed733fec7e1b162ffecc7d5a073280b40411eff3574d",
        "legal-ir-native-request-recovery-20261017-01/retained-legal-context-parity-20261018-v01/projected_context_decoder_v01.py"),
    "context_trained": (
        "trained_projected_context_decoder_v1.py", 22018,
        "508e77f75061d0a0567577f025d69a2a6680a286c82e8679e9ae972b1b2e0cf2",
        "legal-ir-native-request-recovery-20261017-01/retained-legal-context-training-20261018-v01/trained_projected_context_decoder_v01.py"),
    "gated_conditioning": (
        "gated_conditioning_v1.py", 21788,
        "dd91a47e8c116ea2cb6daa60716f0c452b82585df78d4c88756a1147eb55ba00",
        "legal-ir-step-conditioning-20261018-01/gated_conditioning.py"),
    "gated_training_state": (
        "gated_training_state_v1.py", 25068,
        "a1ad93184fbf417b704c801ce6c15b932f0d138974f4f020239c7cbb4e0493a3",
        "legal-ir-gated-training-state-20261018-01/training_state.py"),
    "journal_session": (
        "journal_training_session_v1.py", 39666,
        "527159a86b380e81c376d80e8464aa79420b71ab13e471faa33a3e72442beffc",
        "legal-ir-journal-training-session-20261018-01/candidate/session.py"),
    "journal_inference": (
        "journal_inference_v1.py", 34369,
        "95295682fe80c4ffc0010fded4235b38e6633ba82a39e17267e8e757f50bd6a9",
        "legal-ir-journal-inference-20261018-01/candidate/runtime.py"),
}
_BRIDGE_FIELD = "source_profile_bridge_sha256"


class SourceProfileBridgeError(ValueError):
    """An undeclared producer generation or source origin was offered."""


def _reference(path):
    path = Path(path).absolute()
    if path.resolve(strict=True) != path:
        raise SourceProfileBridgeError("plain package source required")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= 1024**2:
        raise SourceProfileBridgeError("bounded single-link package source required")
    raw = path.read_bytes()
    after = path.lstat()
    witness = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
                            item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if witness(before) != witness(after) or len(raw) != before.st_size:
        raise SourceProfileBridgeError("package source changed while reading")
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


_INITIAL_BRIDGE_SHA256 = _reference(__file__)["sha256"]


def implementation_sha256():
    """Actual loaded bridge source identity, rechecked at this boundary."""
    current = _reference(__file__)["sha256"]
    if current != _INITIAL_BRIDGE_SHA256:
        raise SourceProfileBridgeError("bridge source changed since import")
    return current


def source_reference(key):
    """Read only one fixed package source; never follow historical paths."""
    implementation_sha256()
    if type(key) is not str or key not in _SPECS:
        raise SourceProfileBridgeError("unknown experimental profile")
    return _reference(_HERE / _SPECS[key][0])


def require_source(key, imported_sha256):
    current = source_reference(key)
    if type(imported_sha256) is not str or current["sha256"] != imported_sha256:
        raise SourceProfileBridgeError("experimental source changed since import")
    return current


def require_module(key, module):
    """Require the fixed relative owner, rather than a caller validation hook."""
    if type(key) is not str or key not in _SPECS:
        raise SourceProfileBridgeError("unknown experimental profile")
    wanted = importlib.import_module(__package__ + "." + _SPECS[key][0][:-3])
    if module is not wanted or Path(module.__file__).absolute() != _HERE / _SPECS[key][0]:
        raise SourceProfileBridgeError("fixed packaged experimental owner required")
    return require_source(key, getattr(module, "_PORTED_SOURCE_SHA256", None))


def require_shared_source(module):
    wanted = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.source_training_v2")
    path = _HERE.parents[1] / "formalization/autoencoder/source_training_v2.py"
    if module is not wanted or Path(module.__file__).absolute() != path:
        raise SourceProfileBridgeError("fixed shared source-training owner required")
    return _reference(path)


def _bounded(value):
    # Producer metadata only. Complete checkpoint and tensor bounds stay with
    # their existing owners. Bound this graph before any source hashing.
    active, remaining = set(), [10000, 1024 * 1024]
    def visit(item, depth):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 32:
            raise SourceProfileBridgeError("producer metadata graph exceeds bounds")
        kind = type(item)
        if item is None or kind is bool:
            remaining[1] -= 5
        elif kind is int:
            if not -2**63 <= item < 2**63:
                raise SourceProfileBridgeError("bounded ordinary producer integer required")
            remaining[1] -= 24
        elif kind is str:
            if len(item) > 65536:
                raise SourceProfileBridgeError("producer string exceeds bounds")
            raw = item.encode("utf-8")
            if len(raw) > 65536:
                raise SourceProfileBridgeError("producer string exceeds UTF-8 bounds")
            remaining[1] -= len(raw)
        elif kind in (dict, list):
            if id(item) in active or len(item) > remaining[0]:
                raise SourceProfileBridgeError("cyclic or oversized producer metadata required")
            active.add(id(item))
            try:
                if kind is dict:
                    for key, child in item.items():
                        if type(key) is not str:
                            raise SourceProfileBridgeError("ordinary producer keys required")
                        visit(key, depth + 1); visit(child, depth + 1)
                else:
                    for child in item:
                        visit(child, depth + 1)
            finally:
                active.remove(id(item))
        else:
            raise SourceProfileBridgeError("ordinary producer metadata required")
        if remaining[1] < 0:
            raise SourceProfileBridgeError("producer metadata byte budget exceeded")
    visit(value, 0)


def _legacy_path(value, suffix):
    if type(value) is not str:
        return False
    path = PurePosixPath(value)
    return (path.is_absolute() and ".." not in path.parts
            and path.parts[-len(PurePosixPath(suffix).parts):] == PurePosixPath(suffix).parts)


def compatible_implementation(offered, expected):
    """Match one complete legacy or current producer recipe, never a mixture.

Legacy descriptor paths are declared producer locations only. Their fixed
SHA256/length/path suffix is checked without reading those paths. Shared-owner
recipes, including their path semantics, remain exact and are not generalized.
The expected recipe is constructed by a fixed package owner, not public input.
"""
    _bounded(offered); _bounded(expected)
    if type(offered) is not dict or type(expected) is not dict or _BRIDGE_FIELD not in expected:
        return False
    records = {key: source_reference(key) for key in _SPECS}
    expected = dict(expected)
    has_bridge = _BRIDGE_FIELD in offered
    if not has_bridge:
        del expected[_BRIDGE_FIELD]
    styles = set()
    def equal(actual, wanted):
        if type(actual) is not type(wanted):
            return False
        if type(wanted) is dict:
            if not has_bridge and _BRIDGE_FIELD in wanted:
                wanted = {key: child for key, child in wanted.items() if key != _BRIDGE_FIELD}
            if set(actual) != set(wanted):
                return False
            if set(wanted) == {"path", "bytes", "sha256"}:
                for key, current in records.items():
                    if wanted == current:
                        if actual == wanted:
                            styles.add("packaged"); return True
                        _, size, digest, suffix = _SPECS[key]
                        if (type(actual["bytes"]) is int and actual["bytes"] == size
                                and actual["sha256"] == digest and _legacy_path(actual["path"], suffix)):
                            styles.add("legacy"); return True
                        return False
            return all(equal(actual[key], child) for key, child in wanted.items())
        if type(wanted) is list:
            return len(actual) == len(wanted) and all(equal(a, b) for a, b in zip(actual, wanted))
        if type(wanted) is str:
            for key, current in records.items():
                if wanted == current["sha256"]:
                    if actual == wanted:
                        styles.add("packaged"); return True
                    if actual == _SPECS[key][2]:
                        styles.add("legacy"); return True
                    return False
        return actual == wanted
    return equal(offered, expected) and styles == {"packaged" if has_bridge else "legacy"}


def profile_bridge(key):
    """Detached discovery metadata; no checkpoint compatibility run is implied."""
    current = source_reference(key)
    _, size, digest, suffix = _SPECS[key]
    return {
        "schema": SCHEMA, "profile": key, "status": "experimental",
        "legacy_source": {"artifact_relative_path": suffix, "bytes": size, "sha256": digest},
        "packaged_source": current,
        "source_profile_bridge_sha256": implementation_sha256(),
        "historical_paths_freshly_authenticated": False,
        "numerical_equivalence_qualified": False, "checkpoint_replay_performed": False,
        "default_runtime_changed": False, "statutory_accuracy": False,
        "training_qualified": False, "Lean_admission": False,
    }


__all__ = ["SCHEMA", "SourceProfileBridgeError", "profile_bridge"]
