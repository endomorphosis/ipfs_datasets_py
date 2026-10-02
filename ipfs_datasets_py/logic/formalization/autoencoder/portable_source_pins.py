"""Direct producer identity for a relocated, complete Python source package.

The package containing this module is the anchor. No Git metadata, caller root,
environment override, or downloaded source is accepted as an identity selector.
This checks source bytes and owned function code, not the full Python process,
mutable globals, numerical model memory, or the semantics of those functions.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
import threading
import types

_PACKAGE_ROOT = Path(__file__).resolve().parents[3]
_SOURCES = {}
_LOCK = threading.RLock()


def _owned_code(module):
    """Loaded functions/methods, excluding generated dataclass functions.

    The historical schema-Lake checker has the same limited identity contract,
    but its import performs checkout-only verification. Keep this source-package
    checker independent of that tool's Git and Lake initialization.
    """
    path = Path(module.__file__).resolve()
    result = {}
    def add(name, value):
        if isinstance(value, (staticmethod, classmethod)):
            value = value.__func__
        try:
            value = inspect.unwrap(value)
        except ValueError:
            return
        code = getattr(value, "__code__", None)
        if isinstance(code, types.CodeType) and Path(code.co_filename).resolve() == path:
            result[name] = code
    for name, value in vars(module).items():
        add(name, value)
        if isinstance(value, type) and value.__module__ == module.__name__:
            for member, method in vars(value).items():
                add(name + "." + member, method.fget if isinstance(method, property) else method)
    return result


def pin_imported_module(module):
    """Reject imports outside this package and disk/loaded-code disagreement."""
    name = getattr(module, "__name__", "")
    if not isinstance(module, types.ModuleType) or not name.startswith("ipfs_datasets_py."):
        raise ValueError("named datasets producer module required")
    parts = name.split(".")
    if not all(part.isidentifier() for part in parts):
        raise ValueError("canonical producer module name required")
    path = Path(module.__file__).resolve(strict=True)
    expected = _PACKAGE_ROOT.joinpath(*parts[1:])
    if (path not in {expected.with_suffix(".py"), expected / "__init__.py"}
            or not path.is_file() or not (_PACKAGE_ROOT / "__init__.py").is_file()):
        raise ValueError("imported producer resolved outside canonical package path")
    raw = path.read_bytes()
    identity = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
        owned_code=_owned_code(module))
    with _LOCK:
        previous = _SOURCES.get(name)
        if previous is not None:
            if identity != previous:
                raise ValueError("imported producer source or executed code changed: " + name)
            return identity["sha256"]
        compiled = compile(raw, str(path), "exec", dont_inherit=True)
        candidates = set()
        def visit(code):
            candidates.add(code)
            for child in code.co_consts:
                if isinstance(child, types.CodeType):
                    visit(child)
        visit(compiled)
        if not all(code in candidates for code in identity["owned_code"].values()):
            raise ValueError("loaded producer code differs from current source: " + name)
        _SOURCES[name] = identity
    return identity["sha256"]


__all__ = ["pin_imported_module"]
