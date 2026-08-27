"""Base scraper class and normalized schema for state law scrapers.

This module provides:
1. A normalized schema for state laws across all states
2. A base scraper class that all state-specific scrapers inherit from
3. Common utilities for parsing and normalizing state law data
"""

from ipfs_datasets_py.utils import anyio_compat as asyncio
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from datetime import datetime, timezone
from abc import ABC, abstractmethod
from pathlib import Path
import contextvars
import dis
import hashlib
import inspect
from io import BytesIO
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import types
from urllib.parse import parse_qs, unquote, urljoin, urlparse, urlunparse

from .citation_history import extract_trailing_history_citations
from ...playwright_limiter import acquire_playwright_slot

logger = logging.getLogger(__name__)
_FETCH_PROVIDER: contextvars.ContextVar[str] = contextvars.ContextVar(
    "state_scraper_fetch_provider",
    default="",
)

# Same-process retry workers use separate scraper and acquisition-ledger
# instances.  These keyed reservations serialize only exact requests that
# target the same immutable jurisdiction evidence store; unrelated states and
# URLs remain concurrent.  A polling claim keeps the synchronization safe
# across asyncio and trio event loops without binding a lock to either loop.
_MULTIFETCH_REQUEST_RESERVATION_LOCK = threading.Lock()
_MULTIFETCH_REQUEST_RESERVATIONS: Dict[tuple[str, str, str, str], object] = {}

# A timeout deliberately returns without joining its daemon worker.  Each new
# supervised attempt claims a monotonically newer generation for the exact
# checkpoint path.  The registry stays process-local and does not mutate the
# shared scraper environment.
_PARTIAL_CHECKPOINT_GENERATION_LOCK = threading.Lock()
_PARTIAL_CHECKPOINT_GENERATIONS: Dict[str, int] = {}
_PARTIAL_CHECKPOINT_RUN_BINDING = threading.local()
_STATE_LAW_RUN_ENVIRONMENT_BINDING = threading.local()
_SOURCE_CORRESPONDENCE_CACHE_LOCK = threading.Lock()
_SOURCE_CORRESPONDENCE_CACHE: set[tuple[str, str, str]] = set()


def _loaded_reference(value: Any) -> str:
    """Return a stable qualified reference without process-specific addresses."""

    return ".".join(
        part
        for part in (
            str(getattr(value, "__module__", "") or ""),
            str(
                getattr(value, "__qualname__", "")
                or getattr(value, "__name__", "")
                or ""
            ),
        )
        if part
    )


def _loaded_object_is_source_owned(value: Any) -> bool:
    """Limit deep module/class traversal to executable sources in this repo."""

    module_name = str(
        getattr(value, "__name__" if inspect.ismodule(value) else "__module__", "")
        or ""
    )
    if module_name == "ipfs_datasets_py" or module_name.startswith(
        ("ipfs_datasets_py.", "scripts.")
    ):
        return True
    code_paths: List[str] = []
    if inspect.isfunction(value):
        code_paths.append(str(value.__code__.co_filename or ""))
    elif inspect.isclass(value):
        code_paths.extend(
            str(function.__code__.co_filename or "")
            for function in _class_defined_functions(value)
        )
    for code_path in code_paths:
        if not code_path or code_path.startswith("<"):
            continue
        try:
            if Path(code_path).resolve().is_relative_to(
                Path(__file__).resolve().parents[4]
            ):
                return True
        except Exception:
            continue
    module = value if inspect.ismodule(value) else sys.modules.get(module_name)
    source_file = str(getattr(module, "__file__", "") or "")
    if not source_file:
        return False
    try:
        return Path(source_file).resolve().is_relative_to(
            Path(__file__).resolve().parents[4]
        )
    except Exception:
        return False


def _loaded_code_constant_projection(
    value: Any,
    *,
    _seen: set[int] | None = None,
) -> Any:
    """Project loaded values, including nested callable behavior, deterministically."""

    seen = _seen if _seen is not None else set()

    if isinstance(value, types.CodeType):
        return {"code": _loaded_code_projection(value)}
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"float": value.hex()}
    if isinstance(value, complex):
        return {"complex": [value.real.hex(), value.imag.hex()]}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, re.Pattern):
        return {
            "regular_expression": {
                "flags": int(value.flags),
                "pattern": _loaded_code_constant_projection(
                    value.pattern,
                    _seen=seen,
                ),
            }
        }
    if isinstance(value, (tuple, list, Mapping, frozenset, set)):
        object_id = id(value)
        if object_id in seen:
            return {
                "recursive_reference": (
                    f"{type(value).__module__}.{type(value).__qualname__}"
                )
            }
        seen.add(object_id)
        try:
            if isinstance(value, tuple):
                return {
                    "tuple": [
                        _loaded_code_constant_projection(item, _seen=seen)
                        for item in value
                    ]
                }
            if isinstance(value, list):
                return {
                    "list": [
                        _loaded_code_constant_projection(item, _seen=seen)
                        for item in value
                    ]
                }
            if isinstance(value, Mapping):
                projected_pairs = [
                    {
                        "key": _loaded_code_constant_projection(key, _seen=seen),
                        "value": _loaded_code_constant_projection(item, _seen=seen),
                    }
                    for key, item in value.items()
                ]
                return {
                    "mapping": sorted(
                        projected_pairs,
                        key=lambda pair: json.dumps(
                            pair["key"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                }
            projected = [
                _loaded_code_constant_projection(item, _seen=seen)
                for item in value
            ]
            return {
                "frozenset" if isinstance(value, frozenset) else "set": sorted(
                    projected,
                    key=lambda item: json.dumps(
                        item,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            }
        finally:
            seen.remove(object_id)
    if value is Ellipsis:
        return {"singleton": "Ellipsis"}
    if inspect.ismodule(value):
        return {"module": str(getattr(value, "__name__", "") or "")}
    if inspect.isclass(value):
        return {"reference": _loaded_reference(value)}
    if inspect.isfunction(value) or inspect.ismethod(value):
        return {
            "callable": _loaded_callable_projection(value, _seen=seen),
        }
    if callable(value) and (
        hasattr(value, "__wrapped__") or inspect.isfunction(getattr(type(value), "__call__", None))
    ):
        return {
            "callable": _loaded_callable_projection(value, _seen=seen),
        }
    return {
        "type": f"{type(value).__module__}.{type(value).__qualname__}"
    }


def _loaded_code_projection(
    code: types.CodeType,
    *,
    _seen: set[int] | None = None,
) -> Dict[str, Any]:
    """Return a deterministic projection of one actually loaded code object."""

    return {
        "argcount": int(code.co_argcount),
        "cellvars": list(code.co_cellvars),
        "code": code.co_code.hex(),
        "consts": [
            _loaded_code_constant_projection(item, _seen=_seen)
            for item in code.co_consts
        ],
        "exceptiontable": bytes(
            getattr(code, "co_exceptiontable", b"") or b""
        ).hex(),
        "flags": int(code.co_flags),
        "freevars": list(code.co_freevars),
        "kwonlyargcount": int(code.co_kwonlyargcount),
        "name": str(code.co_name),
        "names": list(code.co_names),
        "posonlyargcount": int(getattr(code, "co_posonlyargcount", 0)),
        "qualname": str(getattr(code, "co_qualname", code.co_name)),
        "varnames": list(code.co_varnames),
    }


def _loaded_function_projection(
    function: Any,
    *,
    _seen: set[int] | None = None,
    _include_global_bindings: bool = True,
) -> Dict[str, Any]:
    seen = _seen if _seen is not None else set()
    object_id = id(function)
    if object_id in seen:
        return {"recursive_reference": _loaded_reference(function)}
    seen.add(object_id)
    try:
        closure_values: list[Any] = []
        for cell in function.__closure__ or ():
            try:
                closure_values.append(
                    _loaded_code_constant_projection(
                        cell.cell_contents,
                        _seen=seen,
                    )
                )
            except ValueError:
                closure_values.append({"empty_cell": True})
        projection = {
            "annotations": _loaded_code_constant_projection(
                function.__annotations__,
                _seen=seen,
            ),
            "attributes": _loaded_code_constant_projection(
                function.__dict__,
                _seen=seen,
            ),
            "code": _loaded_code_projection(function.__code__, _seen=seen),
            "closure": closure_values,
            "defaults": _loaded_code_constant_projection(
                function.__defaults__,
                _seen=seen,
            ),
            "kwdefaults": _loaded_code_constant_projection(
                function.__kwdefaults__,
                _seen=seen,
            ),
        }
        if _include_global_bindings:
            projection["global_bindings"] = _loaded_global_bindings_projection(
                (function,),
                _seen=seen,
            )
        return projection
    finally:
        seen.remove(object_id)


def _loaded_callable_projection(
    value: Any,
    *,
    _seen: set[int] | None = None,
) -> Dict[str, Any]:
    """Project Python callables and decorator wrappers without cache state."""

    seen = _seen if _seen is not None else set()
    if inspect.isfunction(value):
        return {
            "function": _loaded_function_projection(value, _seen=seen),
            "reference": _loaded_reference(value),
        }
    if inspect.ismethod(value):
        return {
            "method": _loaded_function_projection(value.__func__, _seen=seen),
            "reference": _loaded_reference(value),
        }

    object_id = id(value)
    if object_id in seen:
        return {
            "recursive_reference": _loaded_reference(value)
            or f"{type(value).__module__}.{type(value).__qualname__}"
        }
    seen.add(object_id)
    try:
        projection: Dict[str, Any] = {
            "reference": _loaded_reference(value),
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
        }
        wrapped = getattr(value, "__wrapped__", None)
        if wrapped is not None:
            projection["wrapped"] = _loaded_code_constant_projection(
                wrapped,
                _seen=seen,
            )
        try:
            attributes = vars(value)
        except TypeError:
            attributes = {}
        if attributes:
            projection["attributes"] = _loaded_code_constant_projection(
                attributes,
                _seen=seen,
            )
        call_implementation = getattr(type(value), "__call__", None)
        if inspect.isfunction(call_implementation):
            projection["call"] = _loaded_function_projection(
                call_implementation,
                _seen=seen,
            )
        return projection
    finally:
        seen.remove(object_id)


def _loaded_code_global_names(code: types.CodeType) -> set[str]:
    names = set(str(name) for name in code.co_names)
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            names.update(_loaded_code_global_names(constant))
    return names


def _class_defined_functions(target: Any) -> list[Any]:
    functions: list[Any] = []
    for raw_value in vars(target).values():
        if isinstance(raw_value, (staticmethod, classmethod)):
            if inspect.isfunction(raw_value.__func__):
                functions.append(raw_value.__func__)
        elif isinstance(raw_value, property):
            functions.extend(
                function
                for function in (raw_value.fget, raw_value.fset, raw_value.fdel)
                if function is not None
            )
        elif inspect.isfunction(raw_value):
            functions.append(raw_value)
    return functions


def _loaded_global_binding_projection(
    value: Any,
    *,
    _seen: set[int] | None = None,
) -> Any | None:
    """Project deterministic callable/immutable behavior loaded from globals."""

    reference = _loaded_reference(value)
    if inspect.isfunction(value):
        return {
            "function": _loaded_function_projection(value, _seen=_seen),
            "reference": reference,
        }
    if callable(value) and hasattr(value, "__wrapped__"):
        return {
            "callable": _loaded_callable_projection(value, _seen=_seen),
            "reference": reference,
        }
    if inspect.isclass(value):
        projection: Dict[str, Any] = {"reference": reference}
        if _loaded_object_is_source_owned(value):
            projection["class"] = _loaded_executable_projection(
                value,
                include_global_bindings=True,
                _seen=_seen,
            )
        return projection
    if inspect.ismodule(value):
        projection = {
            "module": str(getattr(value, "__name__", "") or "")
        }
        if _loaded_object_is_source_owned(value):
            projection["executable"] = _loaded_executable_projection(
                value,
                include_global_bindings=True,
                _seen=_seen,
            )
        return projection
    if isinstance(
        value,
        (
            type(None),
            bool,
            int,
            float,
            complex,
            str,
            bytes,
            tuple,
            frozenset,
            re.Pattern,
        ),
    ):
        return {"constant": _loaded_code_constant_projection(value)}
    return None


def _loaded_global_bindings_projection(
    functions: Sequence[Any],
    *,
    _seen: set[int] | None = None,
) -> list[Any]:
    bindings: list[Any] = []
    seen: set[tuple[str, str, str]] = set()
    for function in functions:
        global_namespace = str(function.__globals__.get("__name__") or "")
        for name in sorted(_loaded_code_global_names(function.__code__)):
            if name not in function.__globals__:
                continue
            projection = _loaded_global_binding_projection(
                function.__globals__[name],
                _seen=_seen,
            )
            if projection is None:
                continue
            serialized = json.dumps(
                projection,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            key = (global_namespace, name, serialized)
            if key in seen:
                continue
            seen.add(key)
            bindings.append(
                {
                    "global_namespace": global_namespace,
                    "name": name,
                    "projection": projection,
                }
            )
    return sorted(
        bindings,
        key=lambda item: (
            item["global_namespace"],
            item["name"],
            json.dumps(
                item["projection"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )


class _LoadedExecutableGraphProjector:
    """Project each loaded executable once and connect it with stable refs."""

    def __init__(self) -> None:
        self._nodes_by_object: Dict[int, Dict[str, Any]] = {}
        self._nodes: List[Dict[str, Any]] = []
        self._key_counts: Dict[str, int] = {}
        self._active_containers: set[int] = set()

    def project(self, target: Any) -> Dict[str, Any]:
        if inspect.ismodule(target):
            root = self._module_reference(target, root=True)
        elif inspect.isclass(target):
            root = self._class_reference(target, force=True)
        else:
            raise RuntimeError("frontier source target must be a module or class")
        return {
            "format": "loaded-executable-graph-v1",
            "root": root,
            "nodes": sorted(self._nodes, key=lambda item: item["key"]),
        }

    def _new_node(self, value: Any, kind: str) -> tuple[Dict[str, Any], bool]:
        prior = self._nodes_by_object.get(id(value))
        if prior is not None:
            return prior, False
        reference = _loaded_reference(value) or (
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        base_key = f"{kind}:{reference}"
        count = self._key_counts.get(base_key, 0) + 1
        self._key_counts[base_key] = count
        key = base_key if count == 1 else f"{base_key}#{count}"
        node = {
            "key": key,
            "kind": kind,
            "reference": reference,
            "projection": {},
        }
        self._nodes_by_object[id(value)] = node
        self._nodes.append(node)
        return node, True

    @staticmethod
    def _node_ref(node: Mapping[str, Any]) -> Dict[str, str]:
        return {"loaded_node": str(node["key"])}

    def _function_reference(self, function: Any, *, force: bool) -> Any:
        prior = self._nodes_by_object.get(id(function))
        if prior is not None:
            return self._node_ref(prior)
        if not force and not _loaded_object_is_source_owned(function):
            return {"external_callable": _loaded_reference(function)}
        node, created = self._new_node(function, "function")
        if created:
            node["projection"] = self._function_projection(function)
        return self._node_ref(node)

    def _function_projection(self, function: Any) -> Dict[str, Any]:
        closure_values: List[Any] = []
        for cell in function.__closure__ or ():
            try:
                closure_values.append(
                    self._value_projection(
                        cell.cell_contents,
                        force_callable=True,
                    )
                )
            except ValueError:
                closure_values.append({"empty_cell": True})
        global_bindings: List[Dict[str, Any]] = []
        global_namespace = str(function.__globals__.get("__name__") or "")
        for name in sorted(_loaded_code_global_names(function.__code__)):
            if name not in function.__globals__:
                continue
            value = function.__globals__[name]
            # These containers are synchronization/runtime state, not producer
            # constants.  Their manipulating bytecode is identity-bound, but
            # projecting their live contents would make the identity mutate as
            # a normal acquisition reserves a request, advances a checkpoint
            # generation, or memoizes an already-proven correspondence result.
            if name in {
                "_MULTIFETCH_REQUEST_RESERVATIONS",
                "_PARTIAL_CHECKPOINT_GENERATIONS",
                "_SOURCE_CORRESPONDENCE_CACHE",
            } or (
                global_namespace
                == (
                    "ipfs_datasets_py.processors.legal_scrapers.state_scrapers."
                    "retained_replay_network_guard"
                )
                and name
                in {
                    "_ACTIVE_GUARDS",
                }
            ):
                projection = {
                    "runtime_state": (
                        f"{type(value).__module__}.{type(value).__qualname__}"
                    )
                }
            elif inspect.ismodule(value) and _loaded_object_is_source_owned(value):
                projection = self._module_reference(
                    value,
                    attributes=self._module_attributes_for_global(
                        function.__code__,
                        name,
                    ),
                )
            else:
                projection = self._value_projection(value)
            global_bindings.append(
                {
                    "global_namespace": global_namespace,
                    "name": name,
                    "projection": projection,
                }
            )
        return {
            "annotations": self._value_projection(function.__annotations__),
            "attributes": self._value_projection(
                function.__dict__,
                force_callable=True,
            ),
            "closure": closure_values,
            "code": self._code_projection(function.__code__),
            "defaults": self._value_projection(
                function.__defaults__,
                force_callable=True,
            ),
            "global_bindings": global_bindings,
            "kwdefaults": self._value_projection(
                function.__kwdefaults__,
                force_callable=True,
            ),
        }

    def _wrapper_reference(self, value: Any, *, force: bool) -> Any:
        prior = self._nodes_by_object.get(id(value))
        if prior is not None:
            return self._node_ref(prior)
        if not force and not _loaded_object_is_source_owned(value):
            return {"external_callable": _loaded_reference(value)}
        node, created = self._new_node(value, "callable_wrapper")
        if created:
            projection: Dict[str, Any] = {
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
            }
            wrapped = getattr(value, "__wrapped__", None)
            if wrapped is not None:
                projection["wrapped"] = self._value_projection(
                    wrapped,
                    force_callable=True,
                )
            try:
                attributes = vars(value)
            except TypeError:
                attributes = {}
            if attributes:
                projection["attributes"] = self._value_projection(
                    attributes,
                    force_callable=True,
                )
            call_implementation = getattr(type(value), "__call__", None)
            if inspect.isfunction(call_implementation):
                projection["call"] = self._function_reference(
                    call_implementation,
                    force=True,
                )
            node["projection"] = projection
        return self._node_ref(node)

    def _class_reference(self, value: Any, *, force: bool) -> Any:
        prior = self._nodes_by_object.get(id(value))
        if prior is not None:
            return self._node_ref(prior)
        if not force and not _loaded_object_is_source_owned(value):
            return {"external_class": _loaded_reference(value)}
        node, created = self._new_node(value, "class")
        if created:
            members: List[Dict[str, Any]] = []
            for name, raw_value in sorted(vars(value).items()):
                functions: List[Any] = []
                if isinstance(raw_value, (staticmethod, classmethod)):
                    if inspect.isfunction(raw_value.__func__):
                        functions.append(raw_value.__func__)
                elif isinstance(raw_value, property):
                    functions.extend(
                        function
                        for function in (
                            raw_value.fget,
                            raw_value.fset,
                            raw_value.fdel,
                        )
                        if inspect.isfunction(function)
                    )
                elif inspect.isfunction(raw_value):
                    functions.append(raw_value)
                if functions:
                    members.append(
                        {
                            "name": name,
                            "functions": [
                                self._function_reference(function, force=True)
                                for function in functions
                            ],
                        }
                    )
                elif (
                    not name.startswith("__")
                    and (
                        isinstance(
                            raw_value,
                            (
                                type(None),
                                bool,
                                int,
                                float,
                                complex,
                                str,
                                bytes,
                                tuple,
                                frozenset,
                                re.Pattern,
                            ),
                        )
                        or (
                            not name.startswith("_")
                            and name.isupper()
                            and isinstance(raw_value, (list, set, Mapping))
                        )
                    )
                ):
                    members.append(
                        {
                            "name": name,
                            "constant": self._value_projection(raw_value),
                        }
                    )
            node["projection"] = {
                "annotations": self._value_projection(
                    getattr(value, "__annotations__", {})
                ),
                "bases": [
                    f"{base.__module__}.{base.__qualname__}"
                    for base in value.__bases__
                ],
                "members": members,
                "metaclass": f"{type(value).__module__}.{type(value).__qualname__}",
            }
        return self._node_ref(node)

    def _module_reference(
        self,
        value: Any,
        *,
        attributes: Optional[set[str]] = None,
        root: bool = False,
    ) -> Any:
        prior = self._nodes_by_object.get(id(value))
        if prior is not None and not (root or attributes):
            return self._node_ref(prior)
        if not root and not _loaded_object_is_source_owned(value):
            return {"external_module": str(getattr(value, "__name__", "") or "")}
        node, created = self._new_node(value, "module")
        if created:
            node["projection"] = {"attributes": []}
        projection = node["projection"]
        existing = {
            str(item["name"])
            for item in projection.get("attributes", [])
        }
        module_name = str(getattr(value, "__name__", "") or "")
        if root:
            selected = {
                name
                for name, item in vars(value).items()
                if (
                    (inspect.isfunction(item) and item.__module__ == module_name)
                    or (
                        callable(item)
                        and hasattr(item, "__wrapped__")
                        and str(getattr(item, "__module__", "") or "") == module_name
                    )
                    or (inspect.isclass(item) and item.__module__ == module_name)
                    or (
                        not name.startswith("__")
                        and (
                            isinstance(
                                item,
                                (
                                    type(None),
                                    bool,
                                    int,
                                    float,
                                    complex,
                                    str,
                                    bytes,
                                    tuple,
                                    frozenset,
                                    re.Pattern,
                                ),
                            )
                            or (
                                not name.startswith("_")
                                and name.isupper()
                                and isinstance(item, (list, set, Mapping))
                            )
                        )
                    )
                )
            }
        else:
            selected = set(attributes or ())
            if not selected:
                selected = {
                    name
                    for name, item in vars(value).items()
                    if (
                        (inspect.isfunction(item) and item.__module__ == module_name)
                        or (inspect.isclass(item) and item.__module__ == module_name)
                    )
                }
        for name in sorted(selected - existing):
            if not hasattr(value, name):
                continue
            projection.setdefault("attributes", []).append(
                {
                    "name": name,
                    "projection": self._value_projection(
                        getattr(value, name),
                        force_callable=True,
                    ),
                }
            )
        projection.setdefault("attributes", []).sort(key=lambda item: item["name"])
        return self._node_ref(node)

    @staticmethod
    def _module_attributes_for_global(
        code: types.CodeType,
        global_name: str,
    ) -> set[str]:
        attributes: set[str] = set()
        instructions = list(dis.get_instructions(code))
        for index, instruction in enumerate(instructions):
            if instruction.opname not in {"LOAD_GLOBAL", "LOAD_NAME"}:
                continue
            if str(instruction.argval) != str(global_name):
                continue
            for following in instructions[index + 1 : index + 7]:
                if following.opname in {"CACHE", "PUSH_NULL", "PRECALL"}:
                    continue
                if following.opname in {"LOAD_ATTR", "LOAD_METHOD"}:
                    attributes.add(str(following.argval))
                break
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType):
                attributes.update(
                    _LoadedExecutableGraphProjector._module_attributes_for_global(
                        constant,
                        global_name,
                    )
                )
        return attributes

    def _code_projection(self, code: types.CodeType) -> Dict[str, Any]:
        return {
            "argcount": int(code.co_argcount),
            "cellvars": list(code.co_cellvars),
            "code": code.co_code.hex(),
            "consts": [self._value_projection(item) for item in code.co_consts],
            "exceptiontable": bytes(
                getattr(code, "co_exceptiontable", b"") or b""
            ).hex(),
            "flags": int(code.co_flags),
            "freevars": list(code.co_freevars),
            "kwonlyargcount": int(code.co_kwonlyargcount),
            "name": str(code.co_name),
            "names": list(code.co_names),
            "posonlyargcount": int(getattr(code, "co_posonlyargcount", 0)),
            "qualname": str(getattr(code, "co_qualname", code.co_name)),
            "varnames": list(code.co_varnames),
        }

    def _value_projection(
        self,
        value: Any,
        *,
        force_callable: bool = False,
    ) -> Any:
        if isinstance(value, types.CodeType):
            return {"code": self._code_projection(value)}
        if value is None or isinstance(value, (bool, int, str)):
            return value
        if isinstance(value, float):
            return {"float": value.hex()}
        if isinstance(value, complex):
            return {"complex": [value.real.hex(), value.imag.hex()]}
        if isinstance(value, bytes):
            return {"bytes": value.hex()}
        if isinstance(value, re.Pattern):
            return {
                "regular_expression": {
                    "flags": int(value.flags),
                    "pattern": self._value_projection(value.pattern),
                }
            }
        if inspect.ismodule(value):
            return self._module_reference(value)
        if inspect.isclass(value):
            return self._class_reference(value, force=force_callable)
        if inspect.isfunction(value):
            return self._function_reference(value, force=force_callable)
        if inspect.ismethod(value):
            return self._function_reference(value.__func__, force=force_callable)
        if callable(value) and hasattr(value, "__wrapped__"):
            return self._wrapper_reference(value, force=force_callable)
        if isinstance(value, (tuple, list, Mapping, frozenset, set)):
            object_id = id(value)
            if object_id in self._active_containers:
                return {
                    "recursive_container": (
                        f"{type(value).__module__}.{type(value).__qualname__}"
                    )
                }
            self._active_containers.add(object_id)
            try:
                if isinstance(value, tuple):
                    return {"tuple": [self._value_projection(item, force_callable=force_callable) for item in value]}
                if isinstance(value, list):
                    return {"list": [self._value_projection(item, force_callable=force_callable) for item in value]}
                if isinstance(value, Mapping):
                    pairs = [
                        {
                            "key": self._value_projection(key, force_callable=force_callable),
                            "value": self._value_projection(item, force_callable=force_callable),
                        }
                        for key, item in value.items()
                    ]
                    return {
                        "mapping": sorted(
                            pairs,
                            key=lambda pair: json.dumps(
                                pair["key"],
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        )
                    }
                items = [
                    self._value_projection(item, force_callable=force_callable)
                    for item in value
                ]
                return {
                    "frozenset" if isinstance(value, frozenset) else "set": sorted(
                        items,
                        key=lambda item: json.dumps(
                            item,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                }
            finally:
                self._active_containers.discard(object_id)
        if value is Ellipsis:
            return {"singleton": "Ellipsis"}
        return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _loaded_executable_graph_projection(target: Any) -> Dict[str, Any]:
    return _LoadedExecutableGraphProjector().project(target)


def _loaded_executable_projection(
    target: Any,
    *,
    include_global_bindings: bool = True,
    _seen: set[int] | None = None,
) -> Dict[str, Any]:
    """Bind executable objects already resident in this Python process."""

    seen = _seen if _seen is not None else set()
    object_id = id(target)
    if object_id in seen:
        return {
            "recursive_reference": _loaded_reference(target)
            or f"{type(target).__module__}.{type(target).__qualname__}"
        }
    seen.add(object_id)
    try:
        return _loaded_executable_projection_members(
            target,
            include_global_bindings=include_global_bindings,
            seen=seen,
        )
    finally:
        seen.discard(object_id)


def _loaded_executable_projection_members(
    target: Any,
    *,
    include_global_bindings: bool,
    seen: set[int],
) -> Dict[str, Any]:
    """Project one target while its cycle guard is owned by the caller."""

    members: Dict[str, Any] = {}
    defined_functions: list[Any] = []
    if inspect.ismodule(target):
        module_name = str(getattr(target, "__name__", "") or "")
        for name, value in sorted(vars(target).items()):
            if inspect.isfunction(value) and value.__module__ == module_name:
                defined_functions.append(value)
                members[name] = {
                    "function": _loaded_function_projection(
                        value,
                        _seen=seen,
                    )
                }
            elif (
                callable(value)
                and hasattr(value, "__wrapped__")
                and str(getattr(value, "__module__", "") or "") == module_name
            ):
                wrapped = getattr(value, "__wrapped__", None)
                if inspect.isfunction(wrapped):
                    defined_functions.append(wrapped)
                members[name] = {
                    "callable": _loaded_callable_projection(
                        value,
                        _seen=seen,
                    )
                }
            elif inspect.isclass(value) and value.__module__ == module_name:
                defined_functions.extend(_class_defined_functions(value))
                members[name] = {
                    "class": _loaded_executable_projection(
                        value,
                        include_global_bindings=True,
                        _seen=seen,
                    )
                }
            elif (
                not name.startswith("__")
                and (
                    isinstance(
                        value,
                        (
                            type(None),
                            bool,
                            int,
                            float,
                            complex,
                            str,
                            bytes,
                            tuple,
                            frozenset,
                            re.Pattern,
                        ),
                    )
                    or (
                        not name.startswith("_") and name.isupper()
                        and isinstance(value, (list, set, Mapping))
                    )
                )
            ):
                members[name] = {
                    "constant": _loaded_code_constant_projection(value)
                }
    elif inspect.isclass(target):
        defined_functions.extend(_class_defined_functions(target))
        members["__class_identity__"] = {
            "annotations": _loaded_code_constant_projection(
                getattr(target, "__annotations__", {})
            ),
            "bases": [
                f"{base.__module__}.{base.__qualname__}"
                for base in target.__bases__
            ],
            "metaclass": (
                f"{type(target).__module__}.{type(target).__qualname__}"
            ),
        }
        for name, raw_value in sorted(vars(target).items()):
            functions: List[Any] = []
            if isinstance(raw_value, (staticmethod, classmethod)):
                if inspect.isfunction(raw_value.__func__):
                    functions.append(raw_value.__func__)
            elif isinstance(raw_value, property):
                functions.extend(
                    function
                    for function in (
                        raw_value.fget,
                        raw_value.fset,
                        raw_value.fdel,
                    )
                    if function is not None
                )
            elif inspect.isfunction(raw_value):
                functions.append(raw_value)
            if functions:
                members[name] = {
                    "functions": [
                        _loaded_function_projection(
                            function,
                            _seen=seen,
                            _include_global_bindings=True,
                        )
                        for function in functions
                    ]
                }
            elif (
                not name.startswith("__")
                and (
                    isinstance(
                        raw_value,
                        (
                            type(None),
                            bool,
                            int,
                            float,
                            complex,
                            str,
                            bytes,
                            tuple,
                            frozenset,
                            re.Pattern,
                        ),
                    )
                    or (
                        not name.startswith("_") and name.isupper()
                        and isinstance(raw_value, (list, set, Mapping))
                    )
                )
            ):
                members[name] = {
                    "constant": _loaded_code_constant_projection(raw_value)
                }
    else:
        raise RuntimeError("frontier source target must be a module or class")
    if include_global_bindings:
        members["__global_bindings__"] = _loaded_global_bindings_projection(
            defined_functions,
            _seen=seen,
        )
    return {"members": members}


def _canonicalize_loaded_module_references(
    value: Any,
    *,
    actual_module_name: str,
    canonical_module_name: str,
) -> Any:
    """Normalize only self-module references across safe file-import aliases."""

    if isinstance(value, str):
        if value == actual_module_name:
            return canonical_module_name
        if value.startswith(f"{actual_module_name}."):
            return f"{canonical_module_name}{value[len(actual_module_name):]}"
        for kind in ("module", "class", "function", "callable_wrapper"):
            actual_prefix = f"{kind}:{actual_module_name}"
            if value == actual_prefix or value.startswith(f"{actual_prefix}."):
                return (
                    f"{kind}:{canonical_module_name}"
                    f"{value[len(actual_prefix):]}"
                )
        return value
    if isinstance(value, list):
        return [
            _canonicalize_loaded_module_references(
                item,
                actual_module_name=actual_module_name,
                canonical_module_name=canonical_module_name,
            )
            for item in value
        ]
    if isinstance(value, Mapping):
        return {
            key: _canonicalize_loaded_module_references(
                item,
                actual_module_name=actual_module_name,
                canonical_module_name=canonical_module_name,
            )
            for key, item in value.items()
        }
    return value


def _loaded_executable_sha256(
    target: Any,
    *,
    canonical_module_name: str = "",
) -> str:
    projection = _loaded_executable_graph_projection(target)
    actual_module_name = str(
        getattr(
            target,
            "__name__" if inspect.ismodule(target) else "__module__",
            "",
        )
        or ""
    )
    if canonical_module_name and actual_module_name != canonical_module_name:
        projection = _canonicalize_loaded_module_references(
            projection,
            actual_module_name=actual_module_name,
            canonical_module_name=canonical_module_name,
        )
        global_bindings = projection.get("members", {}).get(
            "__global_bindings__"
        )
        if isinstance(global_bindings, list):
            global_bindings.sort(
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        nodes = projection.get("nodes")
        if isinstance(nodes, list):
            nodes.sort(
                key=lambda item: str(
                    item.get("key") if isinstance(item, Mapping) else ""
                )
            )
    return hashlib.sha256(
        json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _import_source_sha256_for_target(
    target: Any,
    *,
    source_path: Path,
) -> str:
    """Return the exact source digest captured before/while ``target`` loaded."""

    resolved = str(source_path.resolve())
    for package_name in (
        "ipfs_datasets_py.processors.legal_scrapers",
        "ipfs_datasets_py.processors.legal_data",
    ):
        package = sys.modules.get(package_name)
        snapshots = getattr(
            package,
            "STATE_LAWS_PRODUCER_IMPORT_SOURCE_SHA256",
            {},
        )
        digest = str(snapshots.get(resolved) or "")
        if digest:
            return digest

    module = target if inspect.ismodule(target) else sys.modules.get(
        str(getattr(target, "__module__", "") or "")
    )
    digest = str(getattr(module, "MODULE_IMPORT_SOURCE_SHA256", "") or "")
    if digest:
        return digest

    if inspect.isclass(target) and issubclass(target, BaseStateScraper):
        try:
            from .registry import StateScraperRegistry

            for state_code in StateScraperRegistry.get_all_registered_states():
                if StateScraperRegistry.get_scraper_class(state_code) is not target:
                    continue
                attestation = (
                    StateScraperRegistry.get_source_registration_attestation(
                        state_code
                    )
                    or {}
                )
                if str(attestation.get("source_path") or "") == resolved:
                    return str(
                        attestation.get("import_source_sha256") or ""
                    )
        except Exception:
            return ""
    return ""


def _assert_loaded_executables_match_current_source(
    records: Mapping[str, Mapping[str, Any]],
) -> None:
    """Fail unless loaded objects equal a fresh import of the attested bytes."""

    pending: list[dict[str, str]] = []
    cache_keys: dict[str, tuple[str, str, str]] = {}
    with _SOURCE_CORRESPONDENCE_CACHE_LOCK:
        cached = set(_SOURCE_CORRESPONDENCE_CACHE)
    for label, record in records.items():
        target = record["target"]
        loaded_sha256 = str(record["loaded_executable_sha256"])
        source_sha256 = str(record["source_file_sha256"])
        cache_key = (label, loaded_sha256, source_sha256)
        cache_keys[label] = cache_key
        if cache_key in cached:
            continue
        if inspect.ismodule(target):
            module_name = str(
                record.get("fresh_import_module")
                or getattr(target, "__name__", "")
                or ""
            )
            qualname = ""
        else:
            module_name = str(getattr(target, "__module__", "") or "")
            qualname = str(getattr(target, "__qualname__", "") or "")
        if not module_name or "<locals>" in qualname:
            raise RuntimeError(
                f"frontier source dependency {label!r} cannot be freshly imported"
            )
        pending.append(
            {
                "label": label,
                "module": module_name,
                "qualname": qualname,
                "fresh_import_file": str(
                    record.get("fresh_import_file") or ""
                ),
                "source_path": str(record["source_path"]),
                "source_file_sha256": source_sha256,
                "canonical_module_name": str(
                    record.get("canonical_module_name") or ""
                ),
            }
        )
    if not pending:
        return

    child_program = r'''
import hashlib
import importlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    _loaded_executable_sha256,
)

descriptors = json.load(sys.stdin)
result = {}
for descriptor in descriptors:
    if descriptor.get("fresh_import_file"):
        spec = importlib.util.spec_from_file_location(
            descriptor["module"],
            descriptor["fresh_import_file"],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"fresh target {descriptor['label']!r} has no file loader"
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[descriptor["module"]] = module
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(descriptor["module"])
    target = module
    for part in descriptor["qualname"].split(".") if descriptor["qualname"] else ():
        target = getattr(target, part)
    source_file = inspect.getsourcefile(target)
    if not source_file:
        raise RuntimeError(f"fresh target {descriptor['label']!r} is uninspectable")
    source_path = Path(source_file).resolve()
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    loaded = _loaded_executable_sha256(
        target,
        canonical_module_name=descriptor.get("canonical_module_name", ""),
    )
    after = hashlib.sha256(source_path.read_bytes()).hexdigest()
    result[descriptor["label"]] = {
        "source_path": str(source_path),
        "source_before_sha256": before,
        "source_after_sha256": after,
        "loaded_executable_sha256": loaded,
    }
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
'''
    child_env = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(
            prefix="state-laws-source-correspondence-"
        ) as pycache_root:
            child_env["PYTHONPYCACHEPREFIX"] = pycache_root
            completed = subprocess.run(
                [sys.executable, "-c", child_program],
                input=json.dumps(pending, sort_keys=True),
                text=True,
                capture_output=True,
                env=child_env,
                check=False,
                timeout=180,
            )
    except Exception as exc:
        raise RuntimeError(
            "fresh frontier-source correspondence process failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            "fresh frontier-source correspondence process failed: "
            f"exit={completed.returncode}, detail={detail[-2000:]}"
        )
    try:
        output_line = next(
            line
            for line in reversed(completed.stdout.splitlines())
            if line.strip()
        )
        fresh = json.loads(output_line)
    except Exception as exc:
        raise RuntimeError(
            "fresh frontier-source correspondence output was invalid"
        ) from exc

    verified_keys: list[tuple[str, str, str]] = []
    for descriptor in pending:
        label = descriptor["label"]
        observation = fresh.get(label)
        if not isinstance(observation, Mapping):
            raise RuntimeError(
                f"fresh frontier-source correspondence is missing {label!r}"
            )
        expected_source = descriptor["source_file_sha256"]
        expected_path = str(Path(descriptor["source_path"]).resolve())
        if str(observation.get("source_path") or "") != expected_path:
            raise RuntimeError(
                f"fresh frontier-source path mismatch for {label!r}"
            )
        if not (
            observation.get("source_before_sha256") == expected_source
            and observation.get("source_after_sha256") == expected_source
        ):
            raise RuntimeError(
                f"frontier source changed during fresh import for {label!r}"
            )
        record = records[label]
        if observation.get("loaded_executable_sha256") != record.get(
            "loaded_executable_sha256"
        ):
            raise RuntimeError(
                "loaded frontier executable does not correspond to current "
                f"source bytes for {label!r}"
            )
        source_path = Path(str(record["source_path"]))
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != expected_source:
            raise RuntimeError(
                f"frontier source changed during correspondence check for {label!r}"
            )
        verified_keys.append(cache_keys[label])
    with _SOURCE_CORRESPONDENCE_CACHE_LOCK:
        _SOURCE_CORRESPONDENCE_CACHE.update(verified_keys)


def claim_partial_checkpoint_generation(
    *,
    state_code: str,
    checkpoint_dir: str | Path | None,
) -> tuple[str, int]:
    """Claim the next same-process writer generation for one checkpoint."""

    raw_dir = str(checkpoint_dir or "").strip()
    if not raw_dir:
        return "", 0
    checkpoint_path = (
        Path(raw_dir).expanduser().resolve()
        / f"STATE-{str(state_code or '').strip().upper()}-partial.json"
    )
    key = str(checkpoint_path)
    with _PARTIAL_CHECKPOINT_GENERATION_LOCK:
        generation = _PARTIAL_CHECKPOINT_GENERATIONS.get(key, 0) + 1
        _PARTIAL_CHECKPOINT_GENERATIONS[key] = generation
    return key, generation


def _partial_checkpoint_generation_is_current(key: str, generation: int) -> bool:
    if not key or generation <= 0:
        return True
    with _PARTIAL_CHECKPOINT_GENERATION_LOCK:
        return _PARTIAL_CHECKPOINT_GENERATIONS.get(key) == generation


def bind_partial_checkpoint_run_directory(
    checkpoint_dir: str | Path | None,
) -> tuple[bool, str]:
    """Bind this worker thread to one immutable checkpoint directory."""

    prior = (
        hasattr(_PARTIAL_CHECKPOINT_RUN_BINDING, "directory"),
        str(getattr(_PARTIAL_CHECKPOINT_RUN_BINDING, "directory", "") or ""),
    )
    raw_dir = str(checkpoint_dir or "").strip()
    resolved = str(Path(raw_dir).expanduser().resolve()) if raw_dir else ""
    _PARTIAL_CHECKPOINT_RUN_BINDING.directory = resolved
    return prior


def restore_partial_checkpoint_run_directory(prior: tuple[bool, str]) -> None:
    """Restore a worker thread's prior checkpoint-directory binding."""

    had_prior, prior_directory = prior
    if had_prior:
        _PARTIAL_CHECKPOINT_RUN_BINDING.directory = prior_directory
    elif hasattr(_PARTIAL_CHECKPOINT_RUN_BINDING, "directory"):
        delattr(_PARTIAL_CHECKPOINT_RUN_BINDING, "directory")


def current_partial_checkpoint_run_directory() -> str:
    """Return the immutable worker binding, or the legacy ambient setting."""

    if hasattr(_PARTIAL_CHECKPOINT_RUN_BINDING, "directory"):
        return str(_PARTIAL_CHECKPOINT_RUN_BINDING.directory or "")
    return str(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or "").strip()


def bind_state_law_worker_environment(
    values: Mapping[str, Optional[str]],
) -> tuple[bool, Mapping[str, str]]:
    """Bind typed run selectors to the current worker thread."""

    prior = (
        hasattr(_STATE_LAW_RUN_ENVIRONMENT_BINDING, "values"),
        getattr(_STATE_LAW_RUN_ENVIRONMENT_BINDING, "values", {}),
    )
    normalized = {
        str(name): (
            str(value if value is not None else "")
            if str(name) == "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY"
            else str(value or "").strip()
        )
        for name, value in values.items()
    }
    _STATE_LAW_RUN_ENVIRONMENT_BINDING.values = types.MappingProxyType(
        normalized
    )
    return prior


def restore_state_law_worker_environment(
    prior: tuple[bool, Mapping[str, str]],
) -> None:
    """Restore the current thread's previous immutable selector binding."""

    had_prior, prior_values = prior
    if had_prior:
        _STATE_LAW_RUN_ENVIRONMENT_BINDING.values = prior_values
    elif hasattr(_STATE_LAW_RUN_ENVIRONMENT_BINDING, "values"):
        delattr(_STATE_LAW_RUN_ENVIRONMENT_BINDING, "values")


def current_state_law_run_environment_value(
    name: str,
    default: str = "",
) -> str:
    """Read a selector from the worker binding, falling back only off-run."""

    key = str(name)
    values = getattr(_STATE_LAW_RUN_ENVIRONMENT_BINDING, "values", None)
    if values is not None:
        return str(values.get(key, default) or "")
    return str(os.environ.get(key, default) or "")


def _multifetch_request_reservation_keys(
    ledger: Any,
    urls: Sequence[str],
    *,
    sanitized_headers: Optional[Mapping[str, str]] = None,
) -> tuple[tuple[str, str, str, str], ...]:
    root = str(Path(ledger.jurisdiction_root).resolve())
    parser_name = str(getattr(ledger, "parser_name", "") or "")
    keys = []
    for url in dict.fromkeys(urls):
        request = {"method": "GET", "url": url}
        if sanitized_headers:
            request["headers"] = dict(sanitized_headers)
        request_sha = hashlib.sha256(
            json.dumps(
                request,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        keys.append((root, parser_name, url, request_sha))
    return tuple(sorted(keys))


def _sanitized_multifetch_headers(
    headers: Optional[Mapping[str, str]],
) -> Dict[str, str]:
    """Project plural GET headers onto the existing safe request identity."""

    return {
        str(key): str(value)
        for key, value in dict(headers or {}).items()
        if str(key).strip().lower() in {"accept", "content-type"}
    }


def _sanitized_multifetch_request(
    url: str,
    *,
    sanitized_headers: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    request: Dict[str, Any] = {"method": "GET", "url": url}
    if sanitized_headers:
        request["headers"] = dict(sanitized_headers)
    return request


async def _claim_multifetch_request_reservations(
    keys: Sequence[tuple[str, str, str, str]],
) -> object | None:
    if not keys:
        return None
    token = object()
    while True:
        with _MULTIFETCH_REQUEST_RESERVATION_LOCK:
            if all(key not in _MULTIFETCH_REQUEST_RESERVATIONS for key in keys):
                for key in keys:
                    _MULTIFETCH_REQUEST_RESERVATIONS[key] = token
                return token
        await asyncio.sleep(0.025)


def _release_multifetch_request_reservations(
    keys: Sequence[tuple[str, str, str, str]],
    token: object | None,
) -> None:
    if token is None:
        return
    with _MULTIFETCH_REQUEST_RESERVATION_LOCK:
        for key in keys:
            if _MULTIFETCH_REQUEST_RESERVATIONS.get(key) is token:
                _MULTIFETCH_REQUEST_RESERVATIONS.pop(key, None)


@dataclass(frozen=True)
class _StateLawHttpResponse:
    status_code: int
    final_url: str
    body: bytes
    media_type: str
    error_type: str = ""
    error_message: str = ""


@dataclass
class StateLawPageMultiFetchResult:
    """Aligned parser inputs and receipts for one requested URL frontier.

    ``payloads``, ``errors``, ``transport_receipts``, and
    ``parser_input_envelopes`` always have the same length and order as
    ``urls``.  Keeping these values together avoids relying on the legacy
    ``_last_page_*`` compatibility slots after a multi-page acquisition.
    """

    urls: List[str]
    payloads: List[bytes]
    errors: List[Optional[str]]
    transport_receipts: List[Optional[Dict[str, Any]]]
    parser_input_envelopes: List[Any]
    stats: Dict[str, Any]


class _StateLawStatefulHttpSession:
    """Small shared cookie-preserving HTTP session for official form flows."""

    def __init__(self, *, verify_tls: bool = True) -> None:
        import requests

        self.verify_tls = bool(verify_tls)
        self._session = requests.Session()
        self._closed = False

    def request(
        self,
        *,
        url: str,
        method: str,
        headers: Mapping[str, str],
        request_body: Optional[bytes],
        timeout_seconds: int,
    ) -> _StateLawHttpResponse:
        if self._closed:
            raise RuntimeError("state-law HTTP session is closed")
        try:
            response = self._session.request(
                method=str(method),
                url=str(url),
                headers=dict(headers),
                data=request_body,
                timeout=max(1, int(timeout_seconds)),
                verify=self.verify_tls,
                allow_redirects=True,
            )
            content_type = str(response.headers.get("Content-Type", "") or "")
            return _StateLawHttpResponse(
                status_code=int(response.status_code or 0),
                final_url=str(response.url or url),
                body=bytes(response.content or b""),
                media_type=content_type.split(";", 1)[0].strip(),
            )
        except Exception as exc:
            response = getattr(exc, "response", None)
            response_body = bytes(getattr(response, "content", b"") or b"")
            response_headers = getattr(response, "headers", {}) or {}
            content_type = str(response_headers.get("Content-Type", "") or "")
            return _StateLawHttpResponse(
                status_code=int(getattr(response, "status_code", 0) or 0),
                final_url=str(getattr(response, "url", "") or url),
                body=response_body,
                media_type=content_type.split(";", 1)[0].strip(),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def close(self) -> None:
        if not self._closed:
            self._session.close()
            self._closed = True


def _state_law_http_request(
    *,
    url: str,
    method: str,
    headers: Mapping[str, str],
    request_body: Optional[bytes],
    timeout_seconds: int,
    verify_tls: bool,
) -> _StateLawHttpResponse:
    """Execute the one shared raw HTTP request used by state transports."""

    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    request = Request(
        str(url),
        data=request_body,
        headers=dict(headers),
        method=str(method),
    )
    context = None if verify_tls else ssl._create_unverified_context()
    kwargs: Dict[str, Any] = {"timeout": max(1, int(timeout_seconds))}
    if context is not None:
        kwargs["context"] = context

    def _media_type(response_headers: Any) -> str:
        if response_headers is None:
            return ""
        try:
            return str(response_headers.get_content_type() or "").strip()
        except Exception:
            return str(response_headers.get("Content-Type", "") or "").split(
                ";", 1
            )[0].strip()

    try:
        with urlopen(request, **kwargs) as response:
            status = int(
                getattr(response, "status", None)
                or getattr(response, "getcode", lambda: 200)()
                or 200
            )
            return _StateLawHttpResponse(
                status_code=status,
                final_url=str(
                    getattr(response, "geturl", lambda: str(url))() or str(url)
                ),
                body=bytes(response.read() or b""),
                media_type=_media_type(getattr(response, "headers", None)),
            )
    except HTTPError as exc:
        try:
            body = bytes(exc.read() or b"")
        except Exception:
            body = b""
        return _StateLawHttpResponse(
            status_code=int(getattr(exc, "code", 0) or 0),
            final_url=str(getattr(exc, "url", "") or str(url)),
            body=body,
            media_type=_media_type(getattr(exc, "headers", None)),
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    except Exception as exc:
        return _StateLawHttpResponse(
            status_code=int(getattr(exc, "code", 0) or 0),
            final_url=str(getattr(exc, "url", "") or str(url)),
            body=b"",
            media_type="",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

SUBSEC_TOKEN_RE = re.compile(r"\(([0-9]+|[A-Za-z]{1,6})\)")
ROMAN_LOWER_RE = re.compile(r"^[ivxlcdm]+$")
ROMAN_UPPER_RE = re.compile(r"^[IVXLCDM]+$")
COMMON_ROMAN_LOWER = {
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "xi",
    "xii",
    "xiii",
    "xiv",
    "xv",
}
COMMON_ROMAN_UPPER = {token.upper() for token in COMMON_ROMAN_LOWER}

USC_CITATION_RE = re.compile(
    r"\b\d+\s+U\.?\s*S\.?\s*C\.?\s*(?:§+\s*|sec(?:tion)?\.?\s*)?\d[\w\-\.()]*", re.IGNORECASE
)
PUBLIC_LAW_CITATION_RE = re.compile(
    r"Pub\.?\s*L\.?\s*(?:No\.?\s*)?\d+\s*[–—−‑-]\s*\d+", re.IGNORECASE
)
STAT_CITATION_RE = re.compile(r"\b\d+\s+Stat\.?\s+\d+\b", re.IGNORECASE)
SECTION_REF_RE = re.compile(r"\b(?:section|sec\.?|§{1,2})\s+[\w\-.(),\sand]+\b", re.IGNORECASE)

# Generic quality filters to reduce navigation/event link pollution.
_NAV_LABEL_HINTS = (
    "home",
    "about",
    "contact",
    "staff",
    "members",
    "member roster",
    "committee",
    "committees",
    "senate",
    "house",
    "legislature",
    "legislative council",
    "agencies",
    "agency",
    "session",
    "calendar",
    "schedule",
    "events",
    "live proceedings",
    "archived meetings",
    "search",
    "login",
    "portal",
    "news",
    "media",
    "press",
    "privacy",
    "accessibility",
    "skip to",
    "footer",
)

_STATUTE_URL_HINTS = (
    "/statute",
    "/statutes",
    "/code",
    "/codes",
    "/laws",
    "/law",
    "/chapter",
    "/title",
    "/article",
    "docname=",
    "section=",
)

_NON_HTML_DOC_RE = re.compile(r"\.(?:pdf|rtf|docx?|xlsx?|pptx?)(?:$|[?#])", re.IGNORECASE)
_PDF_HEADER_RE = re.compile(rb"^\s*%PDF-", re.IGNORECASE)
_RTF_HEADER_RE = re.compile(rb"^\s*\{\\rtf", re.IGNORECASE)
_HTML_DOC_HEADER_RE = re.compile(
    rb"^\s*(?:<!doctype\s+html\b|<html\b|<head\b|<body\b|<!--\s*wayback)",
    re.IGNORECASE,
)
_SCAFFOLD_SECTION_TEXT_RE = re.compile(r"^\s*section\s+section-\d+\s*:", re.IGNORECASE)
_OBJECT_MOVED_HTML_RE = re.compile(
    r"<title>\s*document moved\s*</title>|<h1>\s*object moved\s*</h1>",
    re.IGNORECASE,
)
_NAV_URL_HINTS = (
    "/calendar",
    "/meeting",
    "/roster",
    "/blog",
    "/news",
    "/jobs",
    "/photos",
    "/contact",
    "/bulletin",
    "/live",
)


def _env_float(name: str, default: float = 0.0) -> float:
    try:
        return float(str(os.getenv(name, "") or default))
    except Exception:
        return float(default)


def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(str(os.getenv(name, "") or default))
    except Exception:
        return int(default)


@dataclass
class StatuteMetadata:
    """Metadata for a statute."""

    effective_date: Optional[str] = None
    last_amended: Optional[str] = None
    enacted_year: Optional[str] = None
    repealed: bool = False
    superseded_by: Optional[str] = None
    legislative_session: Optional[str] = None
    bill_number: Optional[str] = None
    history: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class NormalizedStatute:
    """Normalized representation of a state statute.

    This schema is consistent across all states, allowing for easy
    comparison and analysis of laws from different jurisdictions.
    """

    # Identification
    state_code: str  # e.g., "CA", "NY"
    state_name: str  # e.g., "California", "New York"
    statute_id: str  # Unique identifier within the state (e.g., "Penal Code § 187")

    # Hierarchy (for organizing statutes)
    code_name: Optional[str] = None  # e.g., "Penal Code", "Vehicle Code"
    title_number: Optional[str] = None  # Title or Part number
    title_name: Optional[str] = None  # Title or Part name
    chapter_number: Optional[str] = None
    chapter_name: Optional[str] = None
    section_number: Optional[str] = None
    section_name: Optional[str] = None

    # Content
    short_title: Optional[str] = None
    full_text: Optional[str] = None  # The actual text of the statute
    summary: Optional[str] = None

    # Classification
    legal_area: Optional[str] = None  # e.g., "criminal", "civil", "family"
    topics: List[str] = field(default_factory=list)  # e.g., ["murder", "homicide"]
    keywords: List[str] = field(default_factory=list)

    # Source information
    source_url: str = ""  # URL to official source
    official_cite: Optional[str] = None  # Official citation format

    # Metadata
    metadata: Optional[StatuteMetadata] = None
    structured_data: Dict[str, Any] = field(default_factory=dict)

    # Scraping metadata
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())
    scraper_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.metadata:
            data["metadata"] = self.metadata.to_dict()
        return data

    def __getitem__(self, key: str) -> Any:
        """Provide dict-like access for backward compatibility.

        Some legacy tests/scripts treat scraper results as dictionaries.
        """
        if hasattr(self, key):
            return getattr(self, key)

        legacy_key_map = {
            "id": "statute_id",
            "title": "short_title",
            "name": "short_title",
            "url": "source_url",
            "text": "full_text",
            "summary": "summary",
            "jsonld": "structured_data",
        }
        mapped = legacy_key_map.get(key)
        if mapped and hasattr(self, mapped):
            value = getattr(self, mapped)
            if value is not None:
                return value

        # Fallbacks for common legacy keys
        if key == "title":
            return self.short_title or self.section_name or self.statute_id
        if key == "url":
            return self.source_url
        if key in {
            "subsections",
            "preamble",
            "citations",
            "legislative_history",
            "parser_warnings",
        }:
            return (self.structured_data or {}).get(key)

        raise KeyError(key)

    def get_citation(self) -> str:
        """Get a standardized citation for this statute."""
        parts = []
        if self.state_code:
            parts.append(self.state_code)
        if self.code_name:
            parts.append(self.code_name)
        if self.section_number:
            parts.append(f"§ {self.section_number}")
        return " ".join(parts) if parts else self.statute_id


class BaseStateScraper(ABC):
    """Base class for state-specific law scrapers.

    Each state scraper inherits from this class and implements
    state-specific parsing logic while outputting normalized data.
    """

    def __init__(self, state_code: str, state_name: str):
        """Initialize the scraper.

        Args:
            state_code: Two-letter state code (e.g., "CA")
            state_name: Full state name (e.g., "California")
        """
        self.state_code = state_code
        self.state_name = state_name
        self.logger = logging.getLogger(f"{__name__}.{state_code}")
        self._fetch_analytics: Dict[str, Any] = {
            "attempted": 0,
            "success": 0,
            "providers": {},
            "fallback_count": 0,
            "cache_hits": 0,
            "cache_writes": 0,
            "fetch_cache_hits": 0,
            "fetch_cache_writes": 0,
            "last_error": None,
        }

        fetch_cache_enabled_raw = self.state_law_run_environment_value(
            "LEGAL_SCRAPER_FETCH_CACHE_ENABLED"
        ).lower()
        self._fetch_cache_enabled = (
            fetch_cache_enabled_raw in {"1", "true", "yes", "on"}
            if fetch_cache_enabled_raw
            else False
        )
        self._fetch_cache_ttl_seconds = self._env_int(
            "LEGAL_SCRAPER_FETCH_CACHE_TTL_SECONDS",
            default=60 * 60 * 24 * 30,
        )
        self._fetch_cache_dir = Path(
            self.state_law_run_environment_value("LEGAL_SCRAPER_FETCH_CACHE_DIR")
            or self.state_law_run_environment_value(
                "IPFS_DATASETS_LEGAL_FETCH_CACHE_DIR"
            )
            or (Path.home() / ".ipfs_datasets" / "legal_fetch_cache")
        )
        if self._fetch_cache_enabled:
            self._fetch_cache_dir.mkdir(parents=True, exist_ok=True)
            (self._fetch_cache_dir / "objects").mkdir(parents=True, exist_ok=True)
        ipfs_page_cache_enabled_raw = self.state_law_run_environment_value(
            "LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED"
        ).lower()
        self._ipfs_page_cache_enabled = (
            ipfs_page_cache_enabled_raw not in {"0", "false", "no", "off"}
        )
        ipfs_page_cache_pin_raw = self.state_law_run_environment_value(
            "LEGAL_SCRAPER_IPFS_PAGE_CACHE_PIN"
        ).lower()
        self._ipfs_page_cache_pin = ipfs_page_cache_pin_raw in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._ipfs_page_cache_ttl_seconds = self._env_int(
            "LEGAL_SCRAPER_IPFS_PAGE_CACHE_TTL_SECONDS",
            default=60 * 60 * 24 * 30,
        )
        self._ipfs_page_cache_timeout_seconds = self._env_int(
            "LEGAL_SCRAPER_IPFS_PAGE_CACHE_TIMEOUT_SECONDS",
            default=5,
        )
        self._ipfs_page_cache_metadata_dir = Path(
            self.state_law_run_environment_value(
                "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR"
            )
            or (Path.home() / ".ipfs_datasets" / "legal_page_cache")
        )
        if self._ipfs_page_cache_enabled:
            self._ipfs_page_cache_metadata_dir.mkdir(parents=True, exist_ok=True)
        self._ipfs_page_cache_index_path = self._ipfs_page_cache_metadata_dir / "index.json"
        self._ipfs_page_cache_index = self._load_ipfs_page_cache_index()
        self._partial_checkpoint_last_write_at = 0.0
        self._partial_checkpoint_last_count = 0
        self._partial_checkpoint_generation_key = ""
        self._partial_checkpoint_generation = 0
        self._partial_checkpoint_bound_path: Optional[Path] = None
        # Opt-in prospective evidence seam.  The default remains detached so
        # existing probes/tests keep their public byte-returning API.  A
        # production caller attaches the shared multi-fetch ledger before a
        # crawl; every response returned by the shared fetch path is then
        # retained and admitted through ParserInputEnvelope first.
        self._state_law_acquisition_ledger: Any = None
        self._last_page_parser_input_envelope: Any = None
        self._last_common_crawl_batch_stats: Dict[str, Any] = {}
        self._last_page_multifetch_stats: Dict[str, Any] = {}
        # In-run inventory memoization is deliberately scoped to this scraper
        # instance.  Raw domain inventories may be reused only for the same
        # source options and when the prior max_matches is a proven superset.
        # Failure backoff is likewise ephemeral: it prevents a crawl from
        # hammering a rate-limited endpoint without turning a transient miss
        # into a durable empty inventory.
        self._state_common_crawl_domain_inventory_cache: Dict[
            tuple[Any, ...], Dict[str, Any]
        ] = {}
        self._state_common_crawl_domain_inventory_backoff: Dict[
            tuple[Any, ...], Dict[str, Any]
        ] = {}
        self._state_common_crawl_legacy_query_cache: Dict[
            tuple[Any, ...], Dict[str, Any]
        ] = {}
        self._state_common_crawl_legacy_backoff_until = 0.0
        self._state_common_crawl_legacy_backoff_reason = ""
        self._last_state_common_crawl_inventory_stats: Dict[str, Any] = {}
        self._state_law_archive_discovery_receipts: List[Dict[str, Any]] = []
        self._state_law_fresh_discovery_receipts: List[Dict[str, Any]] = []
        self._state_law_first_official_frontier_observation: Optional[
            Dict[str, Any]
        ] = None
        self._state_law_official_frontier_observation_error = ""

    def bind_state_law_run_environment(
        self,
        values: Mapping[str, Optional[str]],
    ) -> None:
        """Bind launch-time path selectors so a late worker cannot cross runs."""

        normalized = {
            str(key): (
                str(value if value is not None else "")
                if str(key) == "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY"
                else str(value or "").strip()
            )
            for key, value in values.items()
        }
        prior = getattr(self, "_state_law_run_environment_binding", None)
        if prior is not None:
            if dict(prior) != normalized:
                raise RuntimeError("state-law run environment is already bound")
            return
        self._state_law_run_environment_binding = types.MappingProxyType(
            normalized
        )

    def state_law_run_environment_value(self, name: str) -> str:
        """Read a selector from the immutable run binding when one is present."""

        key = str(name)
        binding = getattr(self, "_state_law_run_environment_binding", None)
        if binding is not None:
            value = str(binding.get(key, "") or "")
        else:
            value = current_state_law_run_environment_value(key)
        if key == "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY":
            return value
        return value.strip()

    @staticmethod
    def _env_bool(name: str, *, default: bool) -> bool:
        raw = str(os.environ.get(name) or "").strip().lower()
        if not raw:
            return bool(default)
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _env_int(name: str, *, default: int) -> int:
        raw = str(os.environ.get(name) or "").strip()
        if not raw:
            return int(default)
        try:
            return int(raw)
        except Exception:
            return int(default)

    def _bounded_return_threshold(self, default: int) -> int:
        """Return the success threshold for candidate-loop scrapers.

        Legacy state scrapers often try several candidate URLs and only return
        early after finding a large number of section links. Bounded daemon
        probes set STATE_SCRAPER_MAX_STATUTES, so those scrapers should return
        as soon as they have the requested number of real records.
        """
        bounded = _env_int("STATE_SCRAPER_MAX_STATUTES", 0)
        if bounded > 0:
            return max(1, min(int(default), bounded))
        if self.state_law_run_environment_value(
            "STATE_SCRAPER_FULL_CORPUS"
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return 1000000
        return int(default)

    def _full_corpus_enabled(self) -> bool:
        return self.state_law_run_environment_value(
            "STATE_SCRAPER_FULL_CORPUS"
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _effective_scrape_limit(
        self,
        max_statutes: Optional[int],
        *,
        default: Optional[int],
    ) -> Optional[int]:
        """Resolve a scraper limit without confusing sampling with full corpus.

        Historically many state scrapers treated ``max_statutes=None`` as a
        small sample default. That is useful for unit tests and probes, but it
        silently truncates daemon full-corpus runs. Full-corpus mode makes an
        omitted max genuinely unbounded while bounded runs keep their caps.
        """
        if max_statutes is not None:
            try:
                value = int(max_statutes)
            except Exception:
                value = 0
            if value > 0:
                return max(1, value)
        if self._full_corpus_enabled():
            return None
        if default is None:
            return None
        return max(1, int(default))

    def _partial_checkpoint_path(self) -> Optional[Path]:
        if self._partial_checkpoint_bound_path is not None:
            bound_path = self._partial_checkpoint_bound_path
            try:
                if bound_path.is_symlink():
                    return None
                if str(bound_path.resolve()) != str(
                    self._partial_checkpoint_generation_key or ""
                ):
                    return None
            except OSError:
                return None
            return bound_path
        raw_dir = current_partial_checkpoint_run_directory()
        if not raw_dir:
            return None
        try:
            base_dir = Path(raw_dir).expanduser().resolve()
            base_dir.mkdir(parents=True, exist_ok=True)
            return base_dir / f"STATE-{self.state_code.upper()}-partial.json"
        except Exception:
            return None

    def bind_partial_checkpoint_generation(
        self,
        *,
        key: str,
        generation: int,
    ) -> None:
        """Bind this scraper to its supervised checkpoint-writer generation."""

        resolved_key = str(key or "").strip()
        resolved_generation = int(generation or 0)
        checkpoint_path = self._partial_checkpoint_path()
        if not resolved_key and resolved_generation == 0:
            self._partial_checkpoint_generation_key = ""
            self._partial_checkpoint_generation = 0
            self._partial_checkpoint_bound_path = None
            return
        if checkpoint_path is None or str(checkpoint_path.resolve()) != resolved_key:
            raise ValueError(
                "checkpoint generation key does not match this scraper checkpoint"
            )
        if resolved_generation <= 0:
            raise ValueError("checkpoint generation must be positive")
        self._partial_checkpoint_generation_key = resolved_key
        self._partial_checkpoint_generation = resolved_generation
        self._partial_checkpoint_bound_path = Path(resolved_key)

    def _coerce_checkpoint_row_to_statute(
        self,
        row: Dict[str, Any],
        *,
        code_name: str,
    ) -> Optional[NormalizedStatute]:
        if not isinstance(row, dict):
            return None
        field_names = set(getattr(NormalizedStatute, "__dataclass_fields__", {}).keys())
        kwargs: Dict[str, Any] = {key: row.get(key) for key in field_names if key in row}
        kwargs["state_code"] = str(kwargs.get("state_code") or self.state_code).upper()
        kwargs["state_name"] = (
            str(kwargs.get("state_name") or self.state_name).strip() or self.state_name
        )
        kwargs["code_name"] = str(kwargs.get("code_name") or code_name).strip() or code_name
        kwargs["statute_id"] = str(kwargs.get("statute_id") or "").strip()
        kwargs["source_url"] = str(kwargs.get("source_url") or "").strip()
        kwargs["scraped_at"] = str(kwargs.get("scraped_at") or datetime.now().isoformat())
        kwargs["scraper_version"] = str(kwargs.get("scraper_version") or "1.0")
        if not kwargs["statute_id"]:
            return None

        topics = kwargs.get("topics")
        if topics is None:
            kwargs["topics"] = []
        elif not isinstance(topics, list):
            kwargs["topics"] = [str(topics)]

        keywords = kwargs.get("keywords")
        if keywords is None:
            kwargs["keywords"] = []
        elif not isinstance(keywords, list):
            kwargs["keywords"] = [str(keywords)]

        structured = kwargs.get("structured_data")
        if not isinstance(structured, dict):
            kwargs["structured_data"] = {}

        metadata_payload = kwargs.get("metadata")
        if isinstance(metadata_payload, dict):
            metadata_fields = set(getattr(StatuteMetadata, "__dataclass_fields__", {}).keys())
            metadata_kwargs = {
                key: metadata_payload.get(key) for key in metadata_fields if key in metadata_payload
            }
            history = metadata_kwargs.get("history")
            if history is None:
                metadata_kwargs["history"] = []
            elif not isinstance(history, list):
                metadata_kwargs["history"] = [str(history)]
            kwargs["metadata"] = StatuteMetadata(**metadata_kwargs)
        elif not isinstance(metadata_payload, StatuteMetadata):
            kwargs["metadata"] = None

        try:
            return NormalizedStatute(**kwargs)
        except Exception:
            return None

    def _checkpoint_statute_key(self, statute: NormalizedStatute) -> str:
        statute_id = str(getattr(statute, "statute_id", "") or "").strip().lower()
        if statute_id:
            return statute_id
        source_url = str(getattr(statute, "source_url", "") or "").strip().lower()
        if source_url:
            return source_url
        return ""

    @staticmethod
    def _checkpoint_payload_row_key(row: Any) -> str:
        if not isinstance(row, dict):
            return ""
        statute_id = str(row.get("statute_id") or "").strip().lower()
        if statute_id:
            return statute_id
        source_url = str(row.get("source_url") or "").strip().lower()
        if source_url:
            return source_url
        return ""

    def _load_partial_checkpoint_statutes(
        self,
        *,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        checkpoint_path = self._partial_checkpoint_path()
        if checkpoint_path is None or not checkpoint_path.exists():
            return []
        try:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        rows = payload.get("statutes") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []

        loaded: List[NormalizedStatute] = []
        seen_keys = set()
        for row in rows:
            statute = self._coerce_checkpoint_row_to_statute(row, code_name=code_name)
            if statute is None:
                continue
            key = self._checkpoint_statute_key(statute)
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            loaded.append(statute)
            if max_statutes is not None and len(loaded) >= int(max_statutes):
                break

        if loaded:
            self._partial_checkpoint_last_count = len(loaded)
            self._partial_checkpoint_last_write_at = datetime.now().timestamp()
            self.logger.info(
                "%s resumed %s statutes from partial checkpoint (%s)",
                self.state_code,
                len(loaded),
                checkpoint_path,
            )
        return loaded

    def _load_partial_checkpoint_payload(self) -> Dict[str, Any]:
        """Load the raw partial-checkpoint payload for resume metadata.

        State-specific scrapers can use this to recover progress cursors
        (for example, titles/chapters already scanned) so retries do not
        restart from the first page after long-running partial progress.
        """
        checkpoint_path = self._partial_checkpoint_path()
        if checkpoint_path is None or not checkpoint_path.exists():
            return {}
        try:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def _load_partial_checkpoint_progress(self) -> Dict[str, Any]:
        """Return checkpoint progress metadata if available."""
        payload = self._load_partial_checkpoint_payload()
        progress = payload.get("progress")
        if isinstance(progress, dict):
            return dict(progress)
        return {}

    def _write_partial_checkpoint(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        stage_label: str,
        force: bool = False,
        extra: Optional[Dict[str, Any]] = None,
        replace_existing_rows: bool = False,
    ) -> bool:
        checkpoint_path = self._partial_checkpoint_path()
        if checkpoint_path is None:
            return False
        checkpoint_generation_key = str(
            self._partial_checkpoint_generation_key or ""
        )
        checkpoint_generation = int(self._partial_checkpoint_generation or 0)
        if checkpoint_generation_key and str(checkpoint_path.resolve()) != (
            checkpoint_generation_key
        ):
            return False
        if not _partial_checkpoint_generation_is_current(
            checkpoint_generation_key,
            checkpoint_generation,
        ):
            self.logger.info(
                "%s skipped stale generation %s partial-checkpoint write",
                self.state_code,
                checkpoint_generation,
            )
            return False
        if not isinstance(statutes, list):
            return False
        progress_payload = dict(extra) if isinstance(extra, dict) and extra else {}
        if not statutes and not progress_payload:
            return False

        count = len(statutes)
        now_ts = datetime.now().timestamp()
        write_every = max(
            1,
            self._env_int("STATE_SCRAPER_PARTIAL_CHECKPOINT_INTERVAL", default=250),
        )
        min_seconds = max(
            0,
            self._env_int("STATE_SCRAPER_PARTIAL_CHECKPOINT_MIN_SECONDS", default=20),
        )
        if not force:
            delta_count = count - int(self._partial_checkpoint_last_count or 0)
            delta_seconds = now_ts - float(self._partial_checkpoint_last_write_at or 0.0)
            if delta_count < write_every and delta_seconds < float(min_seconds):
                return False

        serialized_rows: List[Dict[str, Any]] = []
        for statute in statutes:
            if not isinstance(statute, NormalizedStatute):
                continue
            try:
                serialized_rows.append(statute.to_dict())
            except Exception:
                continue

        existing_rows: List[Dict[str, Any]] = []
        existing_progress: Dict[str, Any] = {}
        if checkpoint_path.exists():
            try:
                existing_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except Exception:
                existing_payload = {}
            if isinstance(existing_payload, dict):
                raw_existing_rows = existing_payload.get("statutes")
                if isinstance(raw_existing_rows, list):
                    existing_rows = [row for row in raw_existing_rows if isinstance(row, dict)]
                raw_existing_progress = existing_payload.get("progress")
                if isinstance(raw_existing_progress, dict):
                    existing_progress = dict(raw_existing_progress)

        if existing_progress:
            merged_progress = dict(existing_progress)
            merged_progress.update(progress_payload)
            progress_payload = merged_progress

        # Preserve prior statutes when a progress-only write would otherwise
        # clear the checkpoint corpus, and prevent regressions where a smaller
        # intermediate scrape path overwrites a larger recovered corpus. A
        # state-specific authoritative retry may opt into exact replacement to
        # purge previously checkpointed recovery rows.
        if not replace_existing_rows:
            if not serialized_rows and existing_rows:
                serialized_rows = list(existing_rows)
            elif serialized_rows and existing_rows and len(serialized_rows) < len(existing_rows):
                merged_rows = list(existing_rows)
                merged_keys = {
                    self._checkpoint_payload_row_key(row)
                    for row in merged_rows
                    if self._checkpoint_payload_row_key(row)
                }
                for row in serialized_rows:
                    row_key = self._checkpoint_payload_row_key(row)
                    if row_key and row_key in merged_keys:
                        continue
                    if row_key:
                        merged_keys.add(row_key)
                    merged_rows.append(row)
                serialized_rows = merged_rows

        if not serialized_rows and not progress_payload:
            return False

        payload: Dict[str, Any] = {
            "state_code": self.state_code,
            "state_name": self.state_name,
            "code_name": str(code_name or ""),
            "stage_label": str(stage_label or ""),
            "updated_at": datetime.now().isoformat(),
            "statutes_count": int(len(serialized_rows)),
            "statutes": serialized_rows,
        }
        if progress_payload:
            payload["progress"] = progress_payload

        tmp_path = checkpoint_path.with_name(
            f"{checkpoint_path.name}.g{checkpoint_generation}."
            f"t{threading.get_ident()}.tmp"
        )
        try:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
            with _PARTIAL_CHECKPOINT_GENERATION_LOCK:
                if (
                    checkpoint_generation_key
                    and checkpoint_generation > 0
                    and _PARTIAL_CHECKPOINT_GENERATIONS.get(
                        checkpoint_generation_key
                    )
                    != checkpoint_generation
                ):
                    tmp_path.unlink(missing_ok=True)
                    self.logger.info(
                        "%s discarded stale generation %s partial checkpoint",
                        self.state_code,
                        checkpoint_generation,
                    )
                    return False
                tmp_path.replace(checkpoint_path)
        except Exception as exc:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            self.logger.debug("Failed writing partial checkpoint for %s: %s", self.state_code, exc)
            return False

        self._partial_checkpoint_last_count = count
        self._partial_checkpoint_last_write_at = now_ts
        return True

    def _load_ipfs_page_cache_index(self) -> Dict[str, Dict[str, Any]]:
        if not self._ipfs_page_cache_index_path.exists():
            return {}
        try:
            raw = self._ipfs_page_cache_index_path.read_text(encoding="utf-8").strip()
            payload = json.loads(raw) if raw else {}
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_ipfs_page_cache_index(self) -> None:
        try:
            self._ipfs_page_cache_index_path.parent.mkdir(parents=True, exist_ok=True)
            self._ipfs_page_cache_index_path.write_text(
                json.dumps(self._ipfs_page_cache_index, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            self.logger.debug("Failed to save IPFS page cache index: %s", exc)

    @staticmethod
    def _ipfs_page_cache_key(url: str) -> str:
        normalized = BaseStateScraper._canonical_fetch_url(url)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_fetch_url(url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        try:
            parsed = urlparse(value)
            # URL fragments are client-side anchors and do not change the
            # HTTP resource. Remove them so per-section statute URLs reuse the
            # same page fetch/cache entry.
            if parsed.fragment:
                parsed = parsed._replace(fragment="")
                value = urlunparse(parsed)
        except Exception:
            pass
        return value

    def attach_state_law_acquisition_ledger(self, ledger: Any) -> None:
        """Attach/detach the prospective parser-input acquisition ledger.

        ``None`` detaches it.  Attachment is explicit so ordinary bounded
        probes do not unexpectedly write evidence.  With a ledger attached,
        the shared fetch path fails closed before parser admission when a
        direct/archive/cache response lacks exact origin evidence.
        """

        if ledger is None:
            self._state_law_acquisition_ledger = None
            self._last_page_parser_input_envelope = None
            return
        from ...legal_data.state_laws_multifetch_acquisition import (
            StateLawMultiFetchAcquisitionLedger,
        )

        if not isinstance(ledger, StateLawMultiFetchAcquisitionLedger):
            raise TypeError(
                "ledger must be StateLawMultiFetchAcquisitionLedger or None"
            )
        if str(ledger.jurisdiction).upper() != self.state_code.upper():
            raise ValueError(
                "acquisition ledger jurisdiction must match the state scraper"
            )
        self._state_law_acquisition_ledger = ledger
        self._last_page_parser_input_envelope = None

    def _retained_replay_only_enabled(self) -> bool:
        """Return whether the attached evidence ledger forbids all new I/O."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        return bool(
            ledger is not None
            and getattr(ledger, "retained_replay_only", False) is True
        )

    def _raise_if_retained_replay_only_network(
        self,
        *,
        operation: str,
        url: str = "",
    ) -> None:
        """Fail before a direct, archive, inventory, or remote-pointer call."""

        if not self._retained_replay_only_enabled():
            return
        from ...legal_data.state_laws_multifetch_acquisition import (
            StateLawRetainedReplayOnlyError,
        )

        locator = self._canonical_fetch_url(url)
        suffix = f": {locator}" if locator else ""
        raise StateLawRetainedReplayOnlyError(
            f"retained-replay-only mode forbids {operation}{suffix}"
        )

    def retain_state_law_frontier_closure_projection(
        self,
        completion_receipt: Mapping[str, Any],
        *,
        replayed_frontier: Mapping[str, Any],
        canonical_output_projection: Mapping[str, Any] | None = None,
        release_point: str,
        official_source_url: str,
        acquisition_path_ids: Sequence[str],
        observation_time: str,
        source_software_version: str,
        relative_path: str | None = None,
        legacy_singleton: bool = False,
    ) -> Path:
        """Submit an existing enumerator receipt and independent replay.

        Production state enumerators call this only after a separately executed
        second traversal yields ``replayed_frontier``.  The method never creates
        a replay from the first traversal and refuses to run without the
        prospective ledger attached before ``scrape_all``.
        """

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "state-law frontier closure requires an attached acquisition ledger"
            )
        return ledger.retain_frontier_closure_projection(
            completion_receipt,
            replayed_frontier=replayed_frontier,
            canonical_output_projection=canonical_output_projection,
            release_point=release_point,
            official_source_url=official_source_url,
            acquisition_path_ids=acquisition_path_ids,
            observation_time=observation_time,
            source_software_version=source_software_version,
            relative_path=relative_path,
            legacy_singleton=legacy_singleton,
        )

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Return extra source objects whose bytes define frontier parsing.

        State adapters whose canonical rows depend on a sibling parser module
        can opt in here.  The shared identity builder binds those files without
        making environment-specific paths part of the retained receipt.
        """

        return ()

    def _state_law_frontier_source_software_version(
        self,
        *,
        require_loaded_source_correspondence: bool = False,
    ) -> str:
        """Bind loaded producer code and every shared state-law dependency.

        ``require_loaded_source_correspondence`` is reserved for acquisition
        authorization.  It requires exact import/registration-time bytes to
        equal current disk and independently compares each loaded executable
        projection with a fresh source import.  Ordinary diagnostic callers
        still receive the same bundle identity without spawning a child.
        """

        from . import registry as registry_module
        from . import retained_replay_network_guard
        from . import strict_frontier_closure
        from .. import state_laws_scraper
        from ...legal_data import (
            open_us_law_acquisition_coordinator,
            state_laws_completeness,
            state_laws_current_source_software,
            state_laws_legacy_v2_adapter,
            state_laws_multifetch_acquisition,
            state_laws_run_seal,
            state_laws_source_policy,
            state_laws_source_provenance,
        )
        from ...web_archiving import (
            common_crawl_integration,
            wayback_machine_engine,
        )
        from ...web_archiving.common_crawl_search_engine.ccindex import (
            api as common_crawl_ccindex_api,
        )
        from . import state_archival_fetch

        scraper_type = type(self)
        qualified_name = f"{scraper_type.__module__}.{scraper_type.__qualname__}"
        dependencies = tuple(self.state_law_frontier_source_dependencies())
        targets = (
            scraper_type,
            BaseStateScraper,
            registry_module,
            state_laws_scraper,
            state_laws_multifetch_acquisition,
            state_laws_run_seal,
            state_laws_source_provenance,
            state_laws_completeness,
            state_laws_current_source_software,
            state_laws_source_policy,
            state_laws_legacy_v2_adapter,
            open_us_law_acquisition_coordinator,
            retained_replay_network_guard,
            strict_frontier_closure,
            state_archival_fetch,
            wayback_machine_engine,
            common_crawl_integration,
            common_crawl_ccindex_api,
            *dependencies,
        )
        digests: dict[str, dict[str, str]] = {}
        correspondence_records: dict[str, dict[str, Any]] = {}
        target_by_label: dict[str, Any] = {}
        for index, target in enumerate(targets):
            if inspect.ismodule(target):
                label = str(getattr(target, "__name__", "") or "").strip()
            else:
                module_name = str(getattr(target, "__module__", "") or "").strip()
                object_name = str(
                    getattr(target, "__qualname__", "")
                    or getattr(target, "__name__", "")
                    or ""
                ).strip()
                label = ".".join(part for part in (module_name, object_name) if part)
            if not label:
                raise RuntimeError(
                    f"frontier source dependency {index!r} has no qualified name"
                )
            prior_target = target_by_label.get(label)
            if prior_target is target:
                continue
            if prior_target is not None:
                raise RuntimeError(
                    "frontier source dependencies must have unique qualified names"
                )
            target_by_label[label] = target
            try:
                source_file = inspect.getsourcefile(target)
            except TypeError as exc:
                raise RuntimeError(
                    f"frontier source dependency {label or index!r} is not inspectable"
                ) from exc
            source_path = Path(source_file) if source_file else None
            if (
                source_path is None
                or source_path.is_symlink()
                or not source_path.is_file()
            ):
                raise RuntimeError(
                    f"frontier source dependency {label or index!r} is not a regular file"
                )
            source_path = source_path.resolve()
            loaded_executable_sha256 = _loaded_executable_sha256(target)
            source_file_sha256 = hashlib.sha256(
                source_path.read_bytes()
            ).hexdigest()
            import_source_sha256 = _import_source_sha256_for_target(
                target,
                source_path=source_path,
            )
            if require_loaded_source_correspondence:
                if not import_source_sha256:
                    raise RuntimeError(
                        "frontier source dependency has no import-time source "
                        f"attestation: {label!r}"
                    )
                if import_source_sha256 != source_file_sha256:
                    raise RuntimeError(
                        "loaded frontier source bytes differ from current disk "
                        f"for {label!r}: import={import_source_sha256}, "
                        f"current={source_file_sha256}"
                    )
                assertor = getattr(target, "assert_module_source_unchanged", None)
                if callable(assertor):
                    asserted_sha256 = str(assertor() or "")
                    if asserted_sha256 != source_file_sha256:
                        raise RuntimeError(
                            "module source assertion disagrees with current disk "
                            f"for {label!r}"
                        )
            digests[label] = {
                "import_source_sha256": import_source_sha256 or source_file_sha256,
                "loaded_executable_sha256": loaded_executable_sha256,
                "source_file_sha256": source_file_sha256,
            }
            correspondence_records[label] = {
                "target": target,
                "source_path": str(source_path),
                **digests[label],
            }

        if require_loaded_source_correspondence:
            _assert_loaded_executables_match_current_source(
                correspondence_records
            )
            for label, record in correspondence_records.items():
                source_path = Path(str(record["source_path"]))
                current_sha256 = hashlib.sha256(
                    source_path.read_bytes()
                ).hexdigest()
                if current_sha256 != record["source_file_sha256"]:
                    raise RuntimeError(
                        "frontier source changed while building the source "
                        f"bundle for {label!r}"
                    )

        digest = hashlib.sha256(
            json.dumps(
                {
                    "schema_version": "state-laws-frontier-source-bundle-v3",
                    "sources": digests,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return f"{qualified_name}@sha256:{digest}"

    def _supports_shared_official_frontier_bridge(self) -> bool:
        """Whether this state owns the prior exact ``OfficialFetch`` enumerator."""

        fetcher = getattr(self, "fetch_official", None)
        producer = getattr(type(self), "produce_state_law_frontier_closure", None)
        return bool(
            callable(fetcher)
            and producer is BaseStateScraper.produce_state_law_frontier_closure
        )

    def _catalog_acquisition_path_ids_for_source(
        self,
        official_source_url: str,
    ) -> List[str]:
        """Resolve an observed official URL to its sealed source-catalog path.

        Acquisition path identifiers are catalog identities, not labels for
        internal crawler stages.  The shared frontier bridge therefore binds
        its retained catalog observation and parser-input ledger to the one
        authoritative path whose domain admits the observed URL.  Ambiguous
        or stale catalog bindings fail closed instead of inventing path IDs.
        """

        from ...legal_data.state_laws_source_policy import (
            get_official_source_catalog,
        )

        parsed = urlparse(str(official_source_url or "").strip())
        source_host = str(parsed.hostname or "").strip().lower().strip(".")
        if parsed.scheme.lower() not in {"http", "https"} or not source_host:
            raise RuntimeError(
                "official frontier observation cannot bind an invalid source URL"
            )

        record = get_official_source_catalog().get(self.state_code.upper())
        matches = []
        for path in record.authoritative_paths():
            allowed_domains = {
                str(domain or "").strip().lower().strip(".")
                for domain in path.allowed_domains
                if str(domain or "").strip()
            }
            if not allowed_domains or any(
                source_host == domain or source_host.endswith("." + domain)
                for domain in allowed_domains
            ):
                matches.append(path)
        if len(matches) != 1:
            raise RuntimeError(
                "official frontier observation must resolve to exactly one "
                "authoritative source-catalog path; "
                f"state={self.state_code.upper()} host={source_host!r} "
                f"matches={[path.path_id for path in matches]!r}"
            )
        return [str(matches[0].path_id)]

    def _replay_exact_shared_official_frontier_input(
        self,
        official_url: str,
        *,
        frontier_name: str,
        replay_cache: Dict[str, Any],
    ) -> Any:
        """Select one exact retained request identity and reverify its bytes.

        The historical ``fetch_official`` bridge owns current source-specific
        parsing but not a retained-request descriptor.  In replay-only mode we
        therefore select the sole complete sanitized request already retained
        for the exact URL, then pass that exact identity through the shared
        strict replay seam.  Multiple request variants are ambiguous even when
        their bodies happen to agree; silently choosing one would detach the
        newly produced observation from its acquisition request.
        """

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None or getattr(ledger, "retained_replay_only", False) is not True:
            raise RuntimeError(
                f"{frontier_name} retained catalog replay requires a replay-only ledger"
            )
        locator = self._canonical_fetch_url(official_url)
        if not locator:
            raise RuntimeError(f"{frontier_name} requested an empty official URL")
        cached = replay_cache.get(locator)
        if cached is not None:
            return cached

        refresh_entries = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh_entries):
            refresh_entries()
        candidates = [
            retained
            for retained in ledger.entries
            if self._canonical_fetch_url(retained.receipt.endpoint) == locator
        ]
        if not candidates:
            from ...legal_data.state_laws_multifetch_acquisition import (
                StateLawRetainedReplayOnlyError,
            )

            raise StateLawRetainedReplayOnlyError(
                f"{frontier_name} retained parser input is missing: {locator}"
            )

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from .strict_frontier_closure import replay_exact_retained_state_record

        request_identities = {
            canonical_json_bytes(dict(retained.receipt.sanitized_request))
            for retained in candidates
        }
        if len(request_identities) != 1:
            raise RuntimeError(
                f"{frontier_name} retained parser request is ambiguous: {locator}"
            )
        sanitized_request = dict(candidates[0].receipt.sanitized_request)
        retained = replay_exact_retained_state_record(
            self,
            official_url=locator,
            sanitized_request=sanitized_request,
            frontier_name=frontier_name,
            refresh=False,
        )
        replay_cache[locator] = retained
        return retained

    def _reparse_shared_official_frontier_from_retained_inputs(
        self,
        *,
        phase: str,
    ) -> tuple[Any, List[Dict[str, Any]]]:
        """Run the current state enumerator against verified retained bytes.

        ``fetch_official`` remains the single source-specific parser.  Its
        private HTTP helper is replaced on this scraper instance for the
        duration of the call, so the parser receives only ledger-replayed
        bytes.  A process-wide audit-hook lease independently denies raw
        sockets, DNS, browsers, and non-local subprocesses if an enumerator
        attempts to bypass that helper.
        """

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None or getattr(ledger, "retained_replay_only", False) is not True:
            raise RuntimeError("retained official frontier replay requires its ledger")
        fetcher = getattr(self, "fetch_official", None)
        original_http_get = getattr(self, "_official_http_get", None)
        if not callable(fetcher) or not callable(original_http_get):
            raise RuntimeError(
                "shared official frontier parser has no injectable HTTP helper"
            )

        annotation = str(
            inspect.signature(original_http_get).return_annotation
        ).lower()
        returns_raw_triplet = "tuple" in annotation and annotation.count("bytes") >= 3
        replay_cache: Dict[str, Any] = {}
        frontier_name = (
            f"{self.state_code.upper()} shared official catalog {phase}"
        )

        def _retained_http_get(url: str, *_args: Any, **_kwargs: Any) -> Any:
            retained = self._replay_exact_shared_official_frontier_input(
                url,
                frontier_name=frontier_name,
                replay_cache=replay_cache,
            )
            body = bytes(retained.envelope.body or b"")
            if returns_raw_triplet:
                from ...legal_data.open_us_law_acquisition_coordinator import (
                    canonical_json_bytes,
                )

                request = canonical_json_bytes(
                    dict(retained.receipt.sanitized_request)
                )
                return request, body, body
            return body

        had_instance_helper = "_official_http_get" in vars(self)
        previous_instance_helper = vars(self).get("_official_http_get")
        setattr(self, "_official_http_get", _retained_http_get)
        try:
            from .retained_replay_network_guard import (
                retained_replay_network_guard,
            )

            with retained_replay_network_guard(
                ledger=ledger,
                state_code=self.state_code,
            ):
                parsed_fetch = fetcher(self.state_code)
        finally:
            if had_instance_helper:
                setattr(self, "_official_http_get", previous_instance_helper)
            else:
                delattr(self, "_official_http_get")

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.open_us_law_live_evidence import OfficialFetch

        if not isinstance(parsed_fetch, OfficialFetch):
            raise RuntimeError("retained official frontier parser returned the wrong contract")
        if not replay_cache:
            raise RuntimeError(
                "retained official frontier parser consumed no verified input bytes"
            )

        retained_inputs: List[Dict[str, Any]] = []
        response_bundle = bytearray(b"state-laws-retained-frontier-inputs-v1\n")
        observed_at_values: List[str] = []
        origin_transports: set[str] = set()
        for locator, retained in replay_cache.items():
            body = bytes(retained.envelope.body or b"")
            body_sha256 = hashlib.sha256(body).hexdigest()
            expected_sha256 = str(retained.receipt.content.sha256)
            if not body or body_sha256 != expected_sha256:
                raise RuntimeError(
                    f"retained official frontier input changed after replay: {locator}"
                )
            try:
                body_relative_path = retained.body_path.resolve().relative_to(
                    Path(ledger.jurisdiction_root).resolve()
                ).as_posix()
                evidence_relative_path = retained.evidence_path.resolve().relative_to(
                    Path(ledger.jurisdiction_root).resolve()
                ).as_posix()
            except ValueError as exc:
                raise RuntimeError(
                    "retained official frontier input escaped its ledger"
                ) from exc
            retrieved_at = retained.receipt.retrieved_at.isoformat()
            observed_at_values.append(retrieved_at)
            origin_transports.add(str(retained.transport.leaf_transport))
            input_record = {
                "body_relative_path": body_relative_path,
                "body_sha256": body_sha256,
                "evidence_relative_path": evidence_relative_path,
                "official_url": locator,
                "receipt_sha256": str(retained.receipt.receipt_sha256),
                "retrieved_at": retrieved_at,
                "sanitized_request": dict(retained.receipt.sanitized_request),
                "transport": retained.transport.to_dict(),
            }
            retained_inputs.append(input_record)
            record_bytes = canonical_json_bytes(input_record)
            response_bundle.extend(len(record_bytes).to_bytes(8, "big"))
            response_bundle.extend(record_bytes)
            response_bundle.extend(len(body).to_bytes(8, "big"))
            response_bundle.extend(body)

        request_projection = {
            "inputs": retained_inputs,
            "jurisdiction": self.state_code.upper(),
            "mode": "retained_parser_input_replay",
            "phase": str(phase or "observation"),
            "schema": "state-laws-retained-frontier-request-v1",
        }
        transport_kind = "retained_parser_input_replay:"
        transport_kind += "+".join(sorted(origin_transports))
        replayed_fetch = OfficialFetch(
            jurisdiction_code=str(parsed_fetch.jurisdiction_code),
            request_bytes=canonical_json_bytes(request_projection),
            response_bytes=bytes(response_bundle),
            body_bytes=bytes(parsed_fetch.body_bytes),
            source_domain=str(parsed_fetch.source_domain),
            source_path=str(parsed_fetch.source_path),
            frontier=dict(parsed_fetch.frontier),
            rows=tuple(dict(row) for row in parsed_fetch.rows),
            transport_kind=transport_kind,
            fixture=False,
            observed_at=max(observed_at_values),
            edition=str(parsed_fetch.edition),
            legal_as_of=str(parsed_fetch.legal_as_of),
            first_hierarchy_unit=str(parsed_fetch.first_hierarchy_unit),
            last_hierarchy_unit=str(parsed_fetch.last_hierarchy_unit),
        )
        return replayed_fetch, retained_inputs

    async def _capture_shared_official_frontier_observation(
        self,
        *,
        phase: str,
    ) -> Dict[str, Any]:
        """Run and retain one state-owned official catalog traversal."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("official frontier observation requires an attached ledger")
        fetcher = getattr(self, "fetch_official", None)
        if not callable(fetcher):
            raise RuntimeError("state scraper has no official frontier enumerator")

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
            write_retained_artifacts,
        )

        retained_inputs: List[Dict[str, Any]] = []
        if self._retained_replay_only_enabled():
            fetch, retained_inputs = await asyncio.to_thread(
                self._reparse_shared_official_frontier_from_retained_inputs,
                phase=phase,
            )
        else:
            fetch = await asyncio.to_thread(fetcher, self.state_code)
        if not isinstance(fetch, OfficialFetch):
            raise RuntimeError("official frontier enumerator returned the wrong contract")
        if str(fetch.jurisdiction_code or "").strip().upper() != self.state_code.upper():
            raise RuntimeError("official frontier observation changed jurisdiction")
        if fetch.fixture is not False:
            raise RuntimeError("fixture frontier observations cannot authorize a crawl")
        if not fetch.request_bytes or not fetch.response_bytes or not fetch.body_bytes:
            raise RuntimeError("official frontier observation omitted retained raw bytes")
        if not fetch.rows:
            raise RuntimeError("official frontier observation contains no catalog units")
        if str(fetch.transport_kind or "").strip().lower() in {
            "",
            "fixture",
            "mock",
            "synthetic",
        }:
            raise RuntimeError("official frontier observation uses an invalid transport")

        source_domain = str(fetch.source_domain or "").strip().lower().strip(".")
        parsed_domain = urlparse(f"https://{source_domain}")
        if (
            not source_domain
            or parsed_domain.hostname != source_domain
            or parsed_domain.username is not None
            or parsed_domain.password is not None
        ):
            raise RuntimeError("official frontier observation has an invalid source domain")
        source_path = str(fetch.source_path or "").strip()
        if not source_path:
            raise RuntimeError("official frontier observation has no source path")

        frontier = dict(fetch.frontier)
        if (
            frontier.get("closed") is not True
            or frontier.get("enumerator_closed") is not True
            or list(frontier.get("unvisited_continuation_links") or [])
        ):
            raise RuntimeError("official frontier enumerator did not close its catalog")
        expected = frontier.get("expected_index_units")
        visited = frontier.get("visited_index_units")
        if (
            isinstance(expected, int)
            and not isinstance(expected, bool)
            and isinstance(visited, int)
            and not isinstance(visited, bool)
            and visited < expected
        ):
            raise RuntimeError("official frontier catalog traversal is incomplete")
        computed_frontier_digest = compute_frontier_digest(frontier)
        declared_frontier_digest = str(
            frontier.get("frontier_digest_sha256") or ""
        ).strip().lower()
        if (
            declared_frontier_digest
            and declared_frontier_digest != computed_frontier_digest
        ):
            raise RuntimeError("official frontier observation digest does not replay")

        identity_material = {
            "body_sha256": hashlib.sha256(fetch.body_bytes).hexdigest(),
            "frontier_sha256": computed_frontier_digest,
            "jurisdiction": self.state_code.upper(),
            "request_sha256": hashlib.sha256(fetch.request_bytes).hexdigest(),
            "response_sha256": hashlib.sha256(fetch.response_bytes).hexdigest(),
            "source_domain": source_domain,
            "source_path": source_path,
            "transport_kind": str(fetch.transport_kind).strip().lower(),
        }
        observation_digest = hashlib.sha256(
            canonical_json_bytes(identity_material)
        ).hexdigest()
        observation_root = (
            Path(ledger.frontiers_dir)
            / "official-catalog-observations"
            / str(phase or "observation").strip().lower()
            / observation_digest
        )
        checkpoint = await asyncio.to_thread(
            write_retained_artifacts,
            observation_root,
            fetch,
            uncapped=True,
        )
        try:
            relative_root = observation_root.resolve().relative_to(
                Path(ledger.jurisdiction_root).resolve()
            ).as_posix()
        except ValueError as exc:
            raise RuntimeError("official frontier evidence escaped its ledger") from exc
        return {
            "checkpoint": checkpoint,
            "fetch": fetch,
            "frontier_digest": computed_frontier_digest,
            "observation_digest": observation_digest,
            "observed_at": (
                str(fetch.observed_at)
                if retained_inputs
                else datetime.now(timezone.utc).isoformat()
            ),
            "relative_root": relative_root,
            "retained_inputs": retained_inputs,
            "retained_replay": bool(retained_inputs),
        }

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Retain the prior state-owned catalog observation and true replay.

        The runner calls this hook only for an attached-ledger, uncapped,
        unfiltered jurisdiction run and only after the final normalized rows
        have passed hydration, quality, and strict-text filtering.  A state
        override must use an observation retained during the first source
        traversal, execute an independent second traversal, and hand both to
        :meth:`retain_state_law_frontier_closure_projection` with the exact
        ``canonical_output_projection`` supplied here.

        The shared implementation is active only when the state class owns the
        earlier ``fetch_official`` enumerator.  Its first traversal is retained
        before parser traversal by :meth:`scrape_all`; this hook performs and
        retains a second traversal.  Catalog closure and final section identity
        remain separate proofs: catalog counts are never promoted into the
        canonical section count.
        """

        if not self._supports_shared_official_frontier_bridge():
            return None
        first = self._state_law_first_official_frontier_observation
        if not isinstance(first, Mapping):
            detail = self._state_law_official_frontier_observation_error or (
                "first official catalog observation was not retained before parsing"
            )
            raise RuntimeError(detail)
        second = await self._capture_shared_official_frontier_observation(
            phase="replay"
        )
        first_fetch = first.get("fetch")
        second_fetch = second.get("fetch")
        if first_fetch is None or second_fetch is None:
            raise RuntimeError("official catalog replay observations are incomplete")
        stable_fields = (
            "edition",
            "legal_as_of",
            "source_domain",
            "source_path",
            "transport_kind",
        )
        if any(
            str(getattr(first_fetch, name, "") or "").strip()
            != str(getattr(second_fetch, name, "") or "").strip()
            for name in stable_fields
        ):
            raise RuntimeError("official catalog source identity changed during replay")
        if first.get("frontier_digest") != second.get("frontier_digest"):
            raise RuntimeError("official catalog frontier changed during replay")

        raw_keys = canonical_output_projection.get("canonical_keys")
        if not isinstance(raw_keys, Sequence) or isinstance(
            raw_keys, (str, bytes, bytearray)
        ):
            raise RuntimeError("canonical output projection lacks section identities")
        canonical_keys = [str(value).strip() for value in raw_keys]
        if not canonical_keys or any(not value for value in canonical_keys):
            raise RuntimeError("canonical output projection is empty")

        from ...legal_data.open_us_law_live_evidence import (
            canonical_keys_from_rows,
        )
        from ...legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )

        catalog_keys = canonical_keys_from_rows(self.state_code, first_fetch.rows)
        first_frontier = dict(first_fetch.frontier)
        first_frontier["frontier_digest_sha256"] = str(first["frontier_digest"])
        replayed_frontier = dict(second_fetch.frontier)
        replayed_frontier["frontier_digest_sha256"] = str(
            second["frontier_digest"]
        )
        first_hierarchy = str(first_fetch.first_hierarchy_unit or "").strip()
        last_hierarchy = str(first_fetch.last_hierarchy_unit or "").strip()
        if not first_hierarchy and catalog_keys:
            first_hierarchy = catalog_keys[0]
        if not last_hierarchy and catalog_keys:
            last_hierarchy = catalog_keys[-1]
        if not first_hierarchy or not last_hierarchy:
            raise RuntimeError("official catalog observation lacks boundary probes")

        row_count = len(canonical_keys)
        completion = closed_jurisdiction_receipt(
            self.state_code,
            discovered=row_count,
            fetched=row_count,
            excluded=0,
            quarantined=0,
            failed_final=0,
            duplicates=0,
            source_domain=str(first_fetch.source_domain),
            canonical_keys=canonical_keys,
            derived_keys=canonical_keys,
        )
        completion.update(
            {
                "canonical_row_count": row_count,
                "edition": str(first_fetch.edition),
                "frontier": first_frontier,
                "legal_as_of": str(first_fetch.legal_as_of),
                "observed_at": str(first["observed_at"]),
                "rights": {
                    "basis": "public_law_no_state_copyright",
                    "decision": "admit",
                    "scope": "statutory_text",
                },
                "source_catalog_evidence": {
                    "catalog_key_count": len(catalog_keys),
                    "first_observation": {
                        "artifact_root": str(first["relative_root"]),
                        "body_sha256": str(first["checkpoint"].admitted_body_sha256),
                        "observation_digest": str(first["observation_digest"]),
                        "retained_parser_inputs": list(
                            first.get("retained_inputs") or []
                        ),
                        "retained_replay": bool(first.get("retained_replay")),
                        "request_sha256": str(first["checkpoint"].request_sha256),
                        "response_sha256": str(first["checkpoint"].response_sha256),
                    },
                    "replay_observation": {
                        "artifact_root": str(second["relative_root"]),
                        "body_sha256": str(second["checkpoint"].admitted_body_sha256),
                        "observation_digest": str(second["observation_digest"]),
                        "retained_parser_inputs": list(
                            second.get("retained_inputs") or []
                        ),
                        "retained_replay": bool(second.get("retained_replay")),
                        "request_sha256": str(second["checkpoint"].request_sha256),
                        "response_sha256": str(second["checkpoint"].response_sha256),
                    },
                },
                "transport": {
                    "fixture": False,
                    "kind": str(first_fetch.transport_kind),
                    "retained_replay": bool(first.get("retained_replay")),
                    "synthetic": False,
                    **(
                        {"network_requests": 0}
                        if first.get("retained_replay")
                        else {}
                    ),
                },
            }
        )
        completion["boundary_probes"] = {
            "bundle_total": int(
                bool(first_frontier.get("bundle_closed"))
            ),
            "first_hierarchy_unit": first_hierarchy,
            "last_hierarchy_unit": last_hierarchy,
            "pagination_total": int(
                first_frontier.get("visited_index_units") or len(catalog_keys)
            ),
        }
        completion["replay"] = {
            "closed": True,
            "first_frontier_digest": str(first["frontier_digest"]),
            "second_frontier_digest": str(second["frontier_digest"]),
            "source": (
                "retained_parser_inputs"
                if first.get("retained_replay")
                else "independent_live_traversal"
            ),
            **(
                {"network_requests": 0}
                if first.get("retained_replay")
                else {}
            ),
        }

        source_path = str(first_fetch.source_path or "").strip()
        if source_path.startswith(("http://", "https://")):
            official_source_url = source_path
        else:
            official_source_url = (
                f"https://{str(first_fetch.source_domain).strip()}"
                f"/{source_path.lstrip('/')}"
            )
        acquisition_path_ids = self._catalog_acquisition_path_ids_for_source(
            official_source_url
        )
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=replayed_frontier,
            canonical_output_projection=canonical_output_projection,
            release_point=(
                f"sha256:{str(first['checkpoint'].admitted_body_sha256)}"
            ),
            official_source_url=official_source_url,
            acquisition_path_ids=acquisition_path_ids,
            observation_time=str(first["observed_at"]),
            source_software_version=(
                self._state_law_frontier_source_software_version()
            ),
        )

    def _retain_page_bytes_before_parser(
        self,
        *,
        url: str,
        payload: bytes,
        response_status: int = 200,
        media_type: Optional[str] = None,
        sanitized_request: Optional[Mapping[str, Any]] = None,
        pagination: Optional[Mapping[str, Any]] = None,
        network_used: Optional[bool] = None,
    ) -> bytes:
        """Retain one shared-fetch response before exposing it to a parser."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            return bytes(payload)
        evidence = getattr(self, "_last_page_fetch_transport_evidence", None)
        if not isinstance(evidence, dict) or not evidence:
            from ...legal_data.state_laws_multifetch_acquisition import (
                StateLawMultiFetchAcquisitionError,
            )

            raise StateLawMultiFetchAcquisitionError(
                "shared state-law fetch lacks a retained transport receipt"
            )
        provider = self._current_fetch_provider().strip().lower()
        retrieved_at = str(evidence.get("fetched_at") or "").strip() or None
        retained = ledger.retain_parser_input(
            official_url=self._canonical_fetch_url(url),
            body=bytes(payload),
            transport_receipt=evidence,
            retrieved_at=retrieved_at,
            response_status=int(response_status),
            media_type=media_type,
            sanitized_request=sanitized_request,
            pagination=pagination,
            network_used=(
                provider
                not in {
                    "fetch_cache",
                    "ipfs_page_cache",
                    "durable_cache",
                }
                if network_used is None
                else bool(network_used)
            ),
        )
        self._last_page_parser_input_envelope = retained.envelope
        body = retained.envelope.body
        if body is None:
            raise RuntimeError("parser-admitted acquisition unexpectedly lacks body bytes")
        return bytes(body)

    def _last_parser_input_row_provenance(self) -> Dict[str, Any]:
        """Return the exact byte binding for rows derived from the last input.

        Bulk XML/PDF/API endpoints commonly yield many statute rows whose
        human-facing section locators differ from the endpoint that supplied
        the bytes.  Those rows must repeat the retained response digest so the
        prospective multi-fetch ledger can reconcile every parser output.  A
        canonical transport receipt is retained alongside it for downstream
        legacy-v2 admission and archive/cache replay verification.
        """

        evidence = getattr(self, "_last_page_fetch_transport_evidence", None)
        if not isinstance(evidence, Mapping) or not evidence:
            return {}
        digest = str(evidence.get("content_sha256") or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            return {}
        try:
            from ...legal_data.state_laws_source_provenance import (
                canonicalize_state_law_transport_receipt,
            )

            receipt = canonicalize_state_law_transport_receipt(
                evidence,
                content_sha256=digest,
            )
        except Exception:
            return {}
        return {
            "content_sha256": digest,
            "transport_receipt": receipt,
        }

    def _retain_archival_fetch_result_before_parser(
        self,
        *,
        official_url: str,
        fetched: Any,
        media_type: Optional[str] = None,
        pagination: Optional[Mapping[str, Any]] = None,
        sanitized_request: Optional[Mapping[str, Any]] = None,
    ) -> bytes:
        """Admit one shared ``ArchivalFetchClient`` result without reprojecting it.

        The archive bridge remains the sole owner of Common Crawl range/WARC
        extraction and Wayback/archive.is retrieval.  This method only maps
        its exact result fields into the prospective parser-input ledger.
        """

        canonical_url = self._canonical_fetch_url(official_url)
        content = bytes(getattr(fetched, "content", b"") or b"")
        if not canonical_url or not content:
            return b""
        result_url = self._canonical_fetch_url(
            str(getattr(fetched, "url", "") or canonical_url)
        )
        if result_url.rstrip("/") != canonical_url.rstrip("/"):
            raise RuntimeError(
                "archival fetch result changed the cataloged official locator"
            )
        digest = hashlib.sha256(content).hexdigest()
        declared_digest = str(
            getattr(fetched, "content_sha256", "") or ""
        ).strip().lower()
        if declared_digest and declared_digest != digest:
            raise RuntimeError("archival fetch result content digest mismatch")
        evidence: Dict[str, Any] = {
            "content_sha256": digest,
            "official_url": canonical_url,
            "source_transport": str(
                getattr(fetched, "source", "") or ""
            ).strip(),
        }
        for key in ("archive_url", "archive_timestamp", "fetched_at"):
            value = getattr(fetched, key, None)
            if value not in (None, ""):
                evidence[key] = value
        for key in (
            "common_crawl_collection",
            "common_crawl_indexed_url",
            "common_crawl_warc_filename",
            "common_crawl_warc_length",
            "common_crawl_warc_offset",
            "wayback_cdx_query_url",
            "wayback_cdx_response_sha256",
            "wayback_cdx_fetched_at",
        ):
            value = getattr(fetched, key, None)
            if value not in (None, ""):
                evidence[key] = value
        self._last_page_fetch_transport_evidence = evidence
        return self._retain_page_bytes_before_parser(
            url=canonical_url,
            payload=content,
            response_status=int(getattr(fetched, "status_code", 200) or 200),
            media_type=media_type,
            sanitized_request=sanitized_request,
            pagination=pagination,
            network_used=True,
        )

    async def _fetch_wayback_replay_parser_input(
        self,
        archive_url: str,
        *,
        timeout_seconds: int = 45,
        content_validator: Optional[Callable[[bytes], bool]] = None,
        media_type: Optional[str] = None,
    ) -> bytes:
        """Retrieve and admit an explicit Wayback replay via one shared seam."""

        self._raise_if_retained_replay_only_network(
            operation="Wayback replay network access",
            url=archive_url,
        )

        try:
            from .state_archival_fetch import ArchivalFetchClient

            client = ArchivalFetchClient(
                request_timeout_seconds=max(1, int(timeout_seconds or 45)),
                delay_seconds=0.0,
                content_validator=content_validator or (lambda payload: bool(payload)),
                enable_common_crawl=False,
                enable_direct=False,
                enable_archive_is=False,
            )
            fetched = await client.fetch_wayback_replay(str(archive_url or "").strip())
            if fetched is None:
                return b""
            return self._retain_archival_fetch_result_before_parser(
                official_url=str(getattr(fetched, "url", "") or ""),
                fetched=fetched,
                media_type=media_type,
            )
        except Exception as exc:
            self._record_fetch_event(
                provider="wayback_replay",
                success=False,
                error=str(exc),
            )
            return b""

    async def _fetch_non_authoritative_reference_result(
        self,
        url: str,
        *,
        timeout_seconds: int = 30,
        content_validator: Optional[Callable[[bytes], bool]] = None,
        enable_common_crawl: bool = True,
    ) -> Any:
        """Fetch a recovery reference without making it release evidence.

        Public law text is not being treated as copyrighted here.  The gate is
        solely evidentiary: a commercial mirror, reader proxy, or delegated
        inventory-only endpoint cannot prove an official section frontier.
        Production crawls have an acquisition ledger attached and therefore
        quarantine these bytes; bounded diagnostics may still inspect them via
        the shared read-only direct/Common Crawl/Wayback stack.
        """

        if getattr(self, "_state_law_acquisition_ledger", None) is not None:
            self._record_fetch_event(
                provider="non_authoritative_reference_quarantined",
                success=False,
                error="reference bytes cannot authorize publication",
            )
            return None
        try:
            from .state_archival_fetch import ArchivalFetchClient

            client = ArchivalFetchClient(
                request_timeout_seconds=max(1, int(timeout_seconds or 30)),
                delay_seconds=0.0,
                content_validator=content_validator or (lambda payload: bool(payload)),
                enable_common_crawl=bool(enable_common_crawl),
                enable_direct=True,
                # Do not submit recovery references to archive.is.  Existing
                # Common Crawl/Wayback captures remain read-only fallbacks.
                enable_archive_is=False,
            )
            return await client.fetch_with_fallback(
                str(url or "").strip(),
                enable_common_crawl=bool(enable_common_crawl),
                enable_archive_is=False,
            )
        except Exception as exc:
            self._record_fetch_event(
                provider="non_authoritative_reference",
                success=False,
                error=str(exc),
            )
            return None

    async def _fetch_non_authoritative_reference_bytes(
        self,
        url: str,
        *,
        timeout_seconds: int = 30,
        content_validator: Optional[Callable[[bytes], bool]] = None,
        enable_common_crawl: bool = True,
    ) -> bytes:
        """Return quarantined reference bytes for bounded diagnostics only."""

        fetched = await self._fetch_non_authoritative_reference_result(
            url,
            timeout_seconds=timeout_seconds,
            content_validator=content_validator,
            enable_common_crawl=enable_common_crawl,
        )
        return bytes(getattr(fetched, "content", b"") or b"") if fetched else b""

    async def _fetch_fresh_official_response_receipt(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        timeout_seconds: int = 30,
        verify_tls: bool = True,
        admit_success_body: bool = False,
        media_type: Optional[str] = None,
        provider: str = "fresh_official_direct",
    ) -> Dict[str, Any]:
        """Fetch once without cache/fallback and retain redirect/status proof."""

        requested_url = self._canonical_fetch_url(url)
        observed_at = datetime.now(timezone.utc).isoformat()
        if not requested_url:
            return {
                "requested_url": str(url or ""),
                "final_url": "",
                "status_code": 0,
                "observed_at": observed_at,
                "body": b"",
                "content_sha256": hashlib.sha256(b"").hexdigest(),
                "error_type": "InvalidUrl",
                "error_message": "fresh official fetch requires an HTTP(S) URL",
            }
        self._raise_if_retained_replay_only_network(
            operation="fresh official network access",
            url=requested_url,
        )
        timeout = max(1, int(timeout_seconds or 30))
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    _state_law_http_request,
                    url=requested_url,
                    method="GET",
                    headers={str(k): str(v) for k, v in dict(headers or {}).items()},
                    request_body=None,
                    timeout_seconds=timeout,
                    verify_tls=bool(verify_tls),
                ),
                timeout=timeout + 2,
            )
        except Exception as exc:
            response = _StateLawHttpResponse(
                status_code=0,
                final_url=requested_url,
                body=b"",
                media_type="",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        body = bytes(response.body)
        digest = hashlib.sha256(body).hexdigest()
        error_text = str(response.error_message or "")
        receipt: Dict[str, Any] = {
            "requested_url": requested_url,
            "final_url": str(response.final_url or requested_url),
            "status_code": int(response.status_code),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "body": body,
            "content_sha256": digest,
            "media_type": str(response.media_type or media_type or ""),
            "error_type": str(response.error_type or ""),
            "error_message": error_text,
        }
        if error_text:
            receipt["error"] = error_text

        if admit_success_body and response.status_code == 200 and body:
            from ...legal_data.state_laws_source_provenance import (
                canonicalize_state_law_transport_receipt,
            )

            self._last_page_fetch_transport_evidence = (
                canonicalize_state_law_transport_receipt(
                    {
                        "content_sha256": digest,
                        "official_url": requested_url,
                        "source_transport": "direct",
                    },
                    official_url=requested_url,
                    content_sha256=digest,
                )
            )
            admitted = self._retain_page_bytes_before_parser(
                url=requested_url,
                payload=body,
                response_status=200,
                media_type=media_type or response.media_type or None,
                sanitized_request={"method": "GET", "url": requested_url},
                network_used=True,
            )
            receipt["body"] = admitted
            receipt["content_sha256"] = hashlib.sha256(admitted).hexdigest()
        else:
            discovery_receipt = {
                key: value for key, value in receipt.items() if key != "body"
            }
            self._state_law_fresh_discovery_receipts.append(discovery_receipt)

        self._record_fetch_event(
            provider=provider,
            success=bool(response.status_code == 200 and body),
            error=error_text or None,
        )
        return receipt

    def _new_stateful_parser_input_session(
        self,
        *,
        verify_tls: bool = True,
    ) -> _StateLawStatefulHttpSession:
        """Open a shared cookie jar for a bounded official form workflow."""

        return _StateLawStatefulHttpSession(verify_tls=verify_tls)

    async def _close_stateful_parser_input_session(
        self,
        session: _StateLawStatefulHttpSession,
    ) -> None:
        """Close a stateful parser-input session without blocking the loop."""

        await asyncio.to_thread(session.close)

    async def _fetch_parser_input_with_transport(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[Mapping[str, str]] = None,
        request_body: Optional[bytes] = None,
        timeout_seconds: int = 25,
        cache_url: Optional[str] = None,
        content_validator: Optional[Callable[[bytes], bool]] = None,
        allow_archival_fallback: bool = True,
        verify_tls: bool = True,
        media_type: Optional[str] = None,
        provider: str = "custom_direct_adapter",
        pagination: Optional[Mapping[str, Any]] = None,
        stateful_session: Optional[_StateLawStatefulHttpSession] = None,
    ) -> bytes:
        """Fetch custom GET/POST input through one prospective evidence seam.

        State implementations use this adapter when their official endpoint
        needs request headers, a POST body, relaxed legacy TLS, or a binary
        validator that the ordinary HTML fetch call cannot express directly.
        The adapter owns the network call and admits the exact response bytes
        through ``StateLawMultiFetchAcquisitionLedger`` *before* returning
        them to state parser code.  GET failures may reuse the existing shared
        web-archive fallback; POST bodies are never silently replayed as GETs.

        ``cache_url`` is only a local lookup namespace (for example, a digest
        of a GraphQL request).  Every receipt remains bound to ``url``, the
        official endpoint.  A legacy cache entry without a byte-bound origin
        receipt is not parser-admissible while a ledger is attached.
        """

        official_url = self._canonical_fetch_url(url)
        if not official_url:
            return b""
        resolved_method = str(method or "GET").strip().upper()
        if resolved_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("custom parser-input method must be GET, POST, PUT, PATCH, or DELETE")
        if request_body is not None and not isinstance(request_body, bytes):
            raise TypeError("request_body must be bytes or None")
        if resolved_method == "GET" and request_body is not None:
            raise ValueError("GET parser-input requests cannot declare a request body")
        if not isinstance(allow_archival_fallback, bool):
            raise TypeError("allow_archival_fallback must be a boolean")
        if not isinstance(verify_tls, bool):
            raise TypeError("verify_tls must be a boolean")
        if stateful_session is not None:
            if not isinstance(stateful_session, _StateLawStatefulHttpSession):
                raise TypeError("stateful_session must come from the shared session factory")
            if allow_archival_fallback:
                raise ValueError("stateful parser-input flows cannot use archival fallback")
            if stateful_session.verify_tls != verify_tls:
                raise ValueError("stateful session TLS policy must match the request")

        request_headers = {
            str(key): str(value)
            for key, value in dict(headers or {}).items()
            if str(key).strip()
        }
        timeout = max(1, int(timeout_seconds or 25))
        local_cache_url = str(cache_url or official_url).strip() or official_url
        raw_request_body = bytes(request_body) if request_body is not None else None
        safe_request: Dict[str, Any] = {
            "method": resolved_method,
            "url": official_url,
        }
        if raw_request_body is not None:
            safe_request.update(
                {
                    "request_body_length": len(raw_request_body),
                    "request_body_sha256": hashlib.sha256(raw_request_body).hexdigest(),
                }
            )
        safe_headers = {
            key: value
            for key, value in request_headers.items()
            if key.strip().lower() in {"accept", "content-type"}
        }
        if safe_headers:
            safe_request["headers"] = safe_headers

        def _content_is_valid(payload: bytes) -> bool:
            if not payload:
                return False
            if content_validator is None:
                return True
            try:
                return bool(content_validator(payload))
            except Exception:
                return False

        def _cache_receipt_for_official_url(
            evidence: Mapping[str, Any], payload: bytes
        ) -> Dict[str, Any]:
            normalized = dict(evidence)
            kind = str(normalized.get("source_transport") or "").strip().lower()
            if kind in {"fetch_cache", "ipfs_page_cache", "durable_cache"}:
                normalized["official_url"] = official_url
                normalized["content_sha256"] = hashlib.sha256(payload).hexdigest()
                origin = normalized.get("origin_transport_receipt")
                if isinstance(origin, Mapping):
                    normalized["origin_transport_receipt"] = (
                        _cache_receipt_for_official_url(origin, payload)
                    )
            return normalized

        self._last_page_fetch_transport_evidence = {}
        self._last_page_parser_input_envelope = None
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is not None:
            retained = ledger.replay_retained_parser_input(
                official_url=official_url,
                sanitized_request=safe_request,
            )
            if retained is not None:
                retained_body = bytes(retained.envelope.body or b"")
                if not _content_is_valid(retained_body):
                    from ...legal_data.state_laws_multifetch_acquisition import (
                        StateLawMultiFetchAcquisitionError,
                    )

                    raise StateLawMultiFetchAcquisitionError(
                        "retained parser-input replay failed the current content validator"
                    )
                self._last_page_fetch_transport_evidence = dict(
                    retained.transport_receipt
                )
                self._last_page_parser_input_envelope = retained.envelope
                self._record_fetch_event(
                    provider="retained_acquisition_replay",
                    success=True,
                )
                return retained_body
        self._raise_if_retained_replay_only_network(
            operation="direct/cache/archive parser-input acquisition",
            url=official_url,
        )
        cached = (
            b""
            if stateful_session is not None
            else await self._load_page_bytes_from_any_cache(local_cache_url)
        )
        if _content_is_valid(cached):
            evidence = getattr(self, "_last_page_fetch_transport_evidence", None)
            if isinstance(evidence, Mapping) and evidence:
                self._last_page_fetch_transport_evidence = _cache_receipt_for_official_url(
                    evidence, cached
                )
            try:
                return self._retain_page_bytes_before_parser(
                    url=official_url,
                    payload=cached,
                    response_status=200,
                    media_type=media_type,
                    sanitized_request=safe_request,
                    pagination=pagination,
                    network_used=False,
                )
            except Exception as exc:
                if getattr(self, "_state_law_acquisition_ledger", None) is None:
                    raise
                self._record_fetch_event(
                    provider="cache_provenance_rejected",
                    success=False,
                    error=str(exc),
                )
                self._last_page_fetch_transport_evidence = {}

        try:
            request_callable = (
                stateful_session.request
                if stateful_session is not None
                else _state_law_http_request
            )
            request_kwargs: Dict[str, Any] = {
                "url": official_url,
                "method": resolved_method,
                "headers": request_headers,
                "request_body": raw_request_body,
                "timeout_seconds": timeout,
            }
            if stateful_session is None:
                request_kwargs["verify_tls"] = verify_tls
            raw_response = await asyncio.wait_for(
                asyncio.to_thread(request_callable, **request_kwargs),
                timeout=timeout + 2,
            )
            status = int(raw_response.status_code)
            payload = bytes(raw_response.body)
            response_media_type = str(raw_response.media_type or "")
        except Exception as exc:
            self._record_fetch_event(provider=provider, success=False, error=str(exc))
            status, payload, response_media_type = 0, b"", ""

        if status == 200 and _content_is_valid(payload):
            from ...legal_data.state_laws_source_provenance import (
                canonicalize_state_law_transport_receipt,
            )

            evidence = canonicalize_state_law_transport_receipt(
                {
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "official_url": official_url,
                    "source_transport": "direct",
                },
                official_url=official_url,
                content_sha256=hashlib.sha256(payload).hexdigest(),
            )
            self._last_page_fetch_transport_evidence = evidence
            self._record_fetch_event(provider=provider, success=True)
            admitted = self._retain_page_bytes_before_parser(
                url=official_url,
                payload=payload,
                response_status=status,
                media_type=media_type or response_media_type or None,
                sanitized_request=safe_request,
                pagination=pagination,
                network_used=True,
            )
            if stateful_session is None:
                await self._cache_successful_page_fetch(
                    url=local_cache_url,
                    payload=admitted,
                    provider=provider,
                )
            return admitted

        if allow_archival_fallback and resolved_method == "GET":
            return await self._fetch_page_content_with_archival_fallback(
                official_url,
                timeout_seconds=timeout,
                content_validator=content_validator,
            )
        return b""

    def _fetch_cache_paths(self, url: str) -> tuple[Path, Path]:
        cache_key = self._ipfs_page_cache_key(url)
        object_path = self._fetch_cache_dir / "objects" / f"{cache_key}.bin"
        meta_path = self._fetch_cache_dir / "objects" / f"{cache_key}.json"
        return object_path, meta_path

    async def _load_page_bytes_from_fetch_cache(self, url: str) -> bytes:
        if not self._fetch_cache_enabled:
            return b""
        object_path, meta_path = self._fetch_cache_paths(url)
        if not object_path.exists() or not meta_path.exists():
            return b""
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return b""
        cached_at = float(meta.get("cached_at", 0.0) or 0.0)
        ttl_seconds = max(0, int(self._fetch_cache_ttl_seconds or 0))
        if ttl_seconds > 0 and cached_at > 0:
            age_seconds = max(0.0, datetime.now().timestamp() - cached_at)
            if age_seconds > float(ttl_seconds):
                return b""
        try:
            data = object_path.read_bytes()
        except Exception as exc:
            self.logger.debug("Fetch cache read failed for %s: %s", url, exc)
            return b""
        if data:
            digest = hashlib.sha256(data).hexdigest()
            stored_receipt = meta.get("transport_evidence")
            if isinstance(stored_receipt, dict):
                self._last_page_fetch_transport_evidence = {
                    "content_sha256": digest,
                    "official_url": str(url),
                    "origin_transport_receipt": dict(stored_receipt),
                    "source_transport": "fetch_cache",
                }
            elif (
                getattr(self, "_state_law_acquisition_ledger", None) is None
                and str(meta.get("provider") or "").strip().lower() in {
                "direct",
                "requests_direct",
                }
            ):
                # Legacy diagnostic mode may retain the historical provider
                # projection.  A prospective publication crawl never upgrades
                # that cache label into missing origin evidence.
                self._last_page_fetch_transport_evidence = {
                    "content_sha256": digest,
                    "official_url": str(url),
                    "origin_transport_receipt": {
                        "content_sha256": digest,
                        "official_url": str(url),
                        "source_transport": "direct",
                    },
                    "source_transport": "fetch_cache",
                }
            self._fetch_analytics["fetch_cache_hits"] = (
                int(self._fetch_analytics.get("fetch_cache_hits", 0) or 0) + 1
            )
            self._fetch_analytics["cache_hits"] = (
                int(self._fetch_analytics.get("cache_hits", 0) or 0) + 1
            )
            return data
        return b""

    async def _store_page_bytes_in_fetch_cache(
        self, *, url: str, payload: bytes, provider: str
    ) -> None:
        if not self._fetch_cache_enabled or not payload:
            return
        object_path, meta_path = self._fetch_cache_paths(url)
        try:
            object_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = object_path.with_suffix(".bin.tmp")
            tmp_path.write_bytes(payload)
            tmp_path.replace(object_path)
            meta_path.write_text(
                json.dumps(
                    {
                        "url": str(url),
                        "provider": str(provider or ""),
                        "size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "cached_at": datetime.now().timestamp(),
                        "state_code": self.state_code,
                        "transport_evidence": dict(
                            getattr(self, "_last_page_fetch_transport_evidence", {}) or {}
                        ),
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            self._fetch_analytics["fetch_cache_writes"] = (
                int(self._fetch_analytics.get("fetch_cache_writes", 0) or 0) + 1
            )
            self._fetch_analytics["cache_writes"] = (
                int(self._fetch_analytics.get("cache_writes", 0) or 0) + 1
            )
        except Exception as exc:
            self.logger.debug("Fetch cache write failed for %s: %s", url, exc)

    async def _cache_successful_page_fetch(
        self, *, url: str, payload: bytes, provider: str
    ) -> None:
        await self._store_page_bytes_in_fetch_cache(url=url, payload=payload, provider=provider)
        await self._store_page_bytes_in_ipfs_cache(url=url, payload=payload, provider=provider)

    async def _load_page_bytes_from_any_cache(self, url: str) -> bytes:
        cached_bytes = await self._load_page_bytes_from_fetch_cache(url)
        if cached_bytes:
            self._record_fetch_event(provider="fetch_cache", success=True)
            return cached_bytes
        cached_bytes = await self._load_page_bytes_from_ipfs_cache(url)
        if cached_bytes:
            self._record_fetch_event(provider="ipfs_page_cache", success=True)
            await self._store_page_bytes_in_fetch_cache(
                url=url, payload=cached_bytes, provider="ipfs_page_cache"
            )
            return cached_bytes
        return b""

    async def _load_page_bytes_from_ipfs_cache(self, url: str) -> bytes:
        if not self._ipfs_page_cache_enabled:
            return b""

        cache_key = self._ipfs_page_cache_key(url)
        entry = self._ipfs_page_cache_index.get(cache_key) or {}
        cid = str(entry.get("cid") or "").strip()
        if not cid:
            return b""

        cached_at = float(entry.get("cached_at", 0.0) or 0.0)
        ttl_seconds = max(0, int(self._ipfs_page_cache_ttl_seconds or 0))
        if ttl_seconds > 0 and cached_at > 0:
            age_seconds = max(0.0, datetime.now().timestamp() - cached_at)
            if age_seconds > float(ttl_seconds):
                return b""

        try:
            from ipfs_datasets_py import ipfs_backend_router as ipfs_router
        except Exception:
            return b""

        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(ipfs_router.cat, cid),
                timeout=max(1, int(self._ipfs_page_cache_timeout_seconds or 5)),
            )
        except asyncio.TimeoutError:
            self.logger.debug("IPFS page cache read timed out for %s", url)
            return b""
        except Exception as exc:
            self.logger.debug("IPFS page cache read failed for %s: %s", url, exc)
            return b""

        if isinstance(data, bytes) and data:
            digest = hashlib.sha256(data).hexdigest()
            stored_receipt = entry.get("transport_evidence")
            if isinstance(stored_receipt, dict):
                self._last_page_fetch_transport_evidence = {
                    "content_sha256": digest,
                    "official_url": str(url),
                    "origin_transport_receipt": dict(stored_receipt),
                    "source_transport": "ipfs_page_cache",
                }
            self._fetch_analytics["cache_hits"] = (
                int(self._fetch_analytics.get("cache_hits", 0) or 0) + 1
            )
            return data
        return b""

    async def _store_page_bytes_in_ipfs_cache(
        self,
        *,
        url: str,
        payload: bytes,
        provider: str,
    ) -> Optional[str]:
        if not self._ipfs_page_cache_enabled or not payload:
            return None

        try:
            from ipfs_datasets_py import ipfs_backend_router as ipfs_router
        except Exception:
            return None

        try:
            cid = await asyncio.wait_for(
                asyncio.to_thread(ipfs_router.add_bytes, payload, pin=self._ipfs_page_cache_pin),
                timeout=max(1, int(self._ipfs_page_cache_timeout_seconds or 5)),
            )
        except asyncio.TimeoutError:
            self.logger.debug("IPFS page cache write timed out for %s", url)
            return None
        except Exception as exc:
            self.logger.debug("IPFS page cache write failed for %s: %s", url, exc)
            return None

        if not cid:
            return None

        cache_key = self._ipfs_page_cache_key(url)
        self._ipfs_page_cache_index[cache_key] = {
            "cid": str(cid),
            "url": str(url),
            "provider": str(provider or ""),
            "size": len(payload),
            "cached_at": datetime.now().timestamp(),
            "state_code": self.state_code,
            "transport_evidence": dict(
                getattr(self, "_last_page_fetch_transport_evidence", {}) or {}
            ),
        }
        self._save_ipfs_page_cache_index()
        self._fetch_analytics["cache_writes"] = (
            int(self._fetch_analytics.get("cache_writes", 0) or 0) + 1
        )
        return str(cid)

    @abstractmethod
    def get_base_url(self) -> str:
        """Get the base URL for the state's legislative website.

        Returns:
            Base URL string
        """
        pass

    @abstractmethod
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of available codes/titles for this state.

        Returns:
            List of dicts with 'name', 'url', and optionally 'code_type' keys
        """
        pass

    @abstractmethod
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code (e.g., Penal Code, Vehicle Code).

        Args:
            code_name: Name of the code to scrape
            code_url: URL to the code

        Returns:
            List of NormalizedStatute objects
        """
        pass

    def _closed_zero_result_code_exclusion(
        self,
        code_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Return verified evidence that a declared code has no current units.

        The default is deliberately fail-closed.  A state scraper may override
        this only after it has fetched the exact official locator and retained
        a byte-bound, timestamped frontier receipt.  This keeps a repealed or
        otherwise inactive hierarchy unit in coverage accounting without
        manufacturing a statute row merely to make a non-empty assertion pass.
        """

        return None

    def _validate_closed_zero_result_code_exclusion(
        self,
        code_info: Dict[str, Any],
        exclusion: object,
    ) -> Optional[Dict[str, Any]]:
        """Validate the common contract for an official zero-unit exclusion."""

        if not isinstance(exclusion, dict):
            return None
        expected_name = str(code_info.get("name") or "").strip()
        expected_url = str(code_info.get("url") or "").strip().rstrip("/")
        source_url = str(exclusion.get("source_url") or "").strip().rstrip("/")
        disposition = str(exclusion.get("disposition") or "").strip().lower()
        digest = str(exclusion.get("content_sha256") or "").strip().lower()
        observed_at = str(exclusion.get("observed_at") or "").strip()
        try:
            observed = datetime.fromisoformat(observed_at)
            expected_statute_count = int(
                exclusion.get("expected_statute_count", -1)
            )
        except (TypeError, ValueError):
            return None
        valid = bool(
            str(exclusion.get("jurisdiction_code") or "").strip().upper()
            == self.state_code.upper()
            and str(exclusion.get("code_name") or "").strip() == expected_name
            and source_url
            and source_url == expected_url
            and exclusion.get("official_source") is True
            and exclusion.get("frontier_closed") is True
            and disposition in {"inactive", "repealed"}
            and expected_statute_count == 0
            and re.fullmatch(r"[a-f0-9]{64}", digest) is not None
            and observed.tzinfo is not None
            and observed.utcoffset() is not None
        )
        return dict(exclusion) if valid else None

    async def scrape_all(
        self,
        legal_areas: Optional[List[str]] = None,
        max_statutes: Optional[int] = None,
        rate_limit_delay: float = 2.0,
        hydrate_statute_text: bool = True,
    ) -> List[NormalizedStatute]:
        """Scrape all available codes for this state.

        Args:
            legal_areas: Filter by legal areas
            max_statutes: Maximum number of statutes to scrape
            rate_limit_delay: Delay between requests in seconds

        Returns:
            List of NormalizedStatute objects
        """
        import time

        all_statutes = []
        code_errors: List[str] = []
        closed_code_exclusions: List[Dict[str, Any]] = []
        codes = self.get_code_list()
        successful_codes = 0
        full_corpus_requested = max_statutes is None and not legal_areas
        if full_corpus_requested and not codes:
            code_errors.append("no declared codes")

        self._state_law_first_official_frontier_observation = None
        self._state_law_official_frontier_observation_error = ""
        if (
            full_corpus_requested
            and self._state_law_acquisition_ledger is not None
            and self._supports_shared_official_frontier_bridge()
        ):
            try:
                self._state_law_first_official_frontier_observation = (
                    await self._capture_shared_official_frontier_observation(
                        phase="first"
                    )
                )
            except Exception as exc:
                self._state_law_official_frontier_observation_error = (
                    f"first official catalog observation failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                self.logger.warning(
                    "%s",
                    self._state_law_official_frontier_observation_error,
                )
                if self._retained_replay_only_enabled():
                    # Replay-only is a zero-acquisition certification path.
                    # Missing or ambiguous catalog input must stop before the
                    # ordinary parser gets an opportunity to try any fallback.
                    raise

        self.logger.info(f"Scraping {len(codes)} codes for {self.state_name}")
        self._write_partial_checkpoint(
            all_statutes,
            code_name="scrape_all",
            stage_label="scrape_all:start",
            force=True,
            extra={"codes_total": len(codes), "codes_completed": 0},
        )

        for code_index, code_info in enumerate(codes, start=1):
            if max_statutes and len(all_statutes) >= max_statutes:
                break

            code_name = code_info["name"]
            code_url = code_info["url"]

            # Filter by legal area if specified
            if legal_areas:
                code_area = self._identify_legal_area(code_name)
                if code_area not in legal_areas:
                    continue

            try:
                self.logger.info(f"Scraping {code_name}...")
                if max_statutes:
                    remaining = max_statutes - len(all_statutes)
                    if remaining <= 0:
                        break
                else:
                    remaining = None
                scrape_code_params = inspect.signature(self.scrape_code).parameters
                if remaining is not None and "max_statutes" in scrape_code_params:
                    scrape_task = self.scrape_code(code_name, code_url, max_statutes=remaining)
                else:
                    scrape_task = self.scrape_code(code_name, code_url)
                code_timeout = _env_float("STATE_SCRAPER_CODE_TIMEOUT_SECONDS", 0.0)
                if code_timeout > 0:
                    try:
                        statutes = await asyncio.wait_for(scrape_task, timeout=code_timeout)
                    except TimeoutError:
                        failure = (
                            f"{code_name}: timed out after {code_timeout:.1f} seconds"
                        )
                        self.logger.error("%s", failure)
                        code_errors.append(failure)
                        self._write_partial_checkpoint(
                            all_statutes,
                            code_name=code_name,
                            stage_label=f"scrape_all:timeout:{code_index}",
                            force=True,
                            extra={
                                "codes_total": len(codes),
                                "codes_completed": successful_codes,
                                "latest_code_name": code_name,
                                "latest_code_statutes": 0,
                                "code_timeout_seconds": float(code_timeout),
                            },
                        )
                        continue
                else:
                    statutes = await scrape_task
                if max_statutes:
                    statutes = statutes[:remaining]
                enriched_statutes: List[NormalizedStatute] = []
                for statute in statutes:
                    if isinstance(statute, NormalizedStatute):
                        if hydrate_statute_text:
                            await self._hydrate_statute_text_if_needed(statute)
                        if self._is_low_quality_statute_record(statute):
                            continue
                        enriched_statutes.append(self._enrich_statute_structure(statute))
                statutes = enriched_statutes

                if full_corpus_requested and not statutes:
                    raw_exclusion = self._closed_zero_result_code_exclusion(code_info)
                    exclusion = self._validate_closed_zero_result_code_exclusion(
                        code_info,
                        raw_exclusion,
                    )
                    if exclusion is None:
                        raise RuntimeError(
                            f"{code_name} returned zero admissible statutes in "
                            "full-corpus mode"
                        )
                    closed_code_exclusions.append(exclusion)
                    successful_codes += 1
                    self.logger.info(
                        "Closed empty %s frontier as %s using official evidence",
                        code_name,
                        exclusion["disposition"],
                    )
                    self._write_partial_checkpoint(
                        all_statutes,
                        code_name=code_name,
                        stage_label=f"scrape_all:excluded:{code_index}",
                        force=True,
                        extra={
                            "codes_total": len(codes),
                            "codes_completed": successful_codes,
                            "latest_code_name": code_name,
                            "latest_code_statutes": 0,
                            "closed_code_exclusions": list(closed_code_exclusions),
                        },
                    )
                    continue

                all_statutes.extend(statutes)
                successful_codes += 1
                self.logger.info(f"Scraped {len(statutes)} statutes from {code_name}")
                self._write_partial_checkpoint(
                    all_statutes,
                    code_name=code_name,
                    stage_label=f"scrape_all:{code_index}",
                    extra={
                        "codes_total": len(codes),
                        "codes_completed": successful_codes,
                        "latest_code_name": code_name,
                        "latest_code_statutes": len(statutes),
                    },
                )

            except Exception as e:
                self.logger.error(f"Failed to scrape {code_name}: {e}")
                code_errors.append(f"{code_name}: {e}")
                self._write_partial_checkpoint(
                    all_statutes,
                    code_name=code_name,
                    stage_label=f"scrape_all:error:{code_index}",
                    force=True,
                    extra={
                        "codes_total": len(codes),
                        "codes_completed": successful_codes,
                        "latest_code_name": code_name,
                        "latest_code_statutes": 0,
                        "latest_error": str(e),
                    },
                )

            # Rate limiting
            time.sleep(rate_limit_delay)

        # A full-corpus frontier is closed only when every declared code
        # succeeds with at least one admissible statute.  Never overwrite an
        # error/timeout checkpoint with a misleading ``scrape_all:complete``.
        if full_corpus_requested and code_errors:
            self._write_partial_checkpoint(
                all_statutes,
                code_name="scrape_all",
                stage_label="scrape_all:incomplete",
                force=True,
                extra={
                    "codes_total": len(codes),
                    "codes_completed": successful_codes,
                    "code_failures": list(code_errors),
                    "closed_code_exclusions": list(closed_code_exclusions),
                },
            )
            error_summary = "; ".join(code_errors[:3])
            if len(code_errors) > 3:
                error_summary = f"{error_summary}; +{len(code_errors) - 3} more"
            raise RuntimeError(
                f"{self.state_code} full-corpus frontier is incomplete: {error_summary}"
            )

        self._write_partial_checkpoint(
            all_statutes,
            code_name="scrape_all",
            stage_label="scrape_all:complete",
            force=True,
            extra={
                "codes_total": len(codes),
                "codes_completed": successful_codes,
                "closed_code_exclusions": list(closed_code_exclusions),
            },
        )
        return all_statutes

    def _identify_legal_area(self, text: str) -> str:
        """Identify legal area from text.

        Args:
            text: Text to analyze

        Returns:
            Legal area string
        """
        text_lower = text.lower()

        area_keywords = {
            "administrative": [
                "administrative",
                "regulation",
                "regulatory",
                "code of regulations",
                "admin code",
                "agency rule",
                "oar",
                "aac",
                "arc",
                "nmac",
            ],
            "criminal": ["criminal", "penal", "crime", "felony", "misdemeanor"],
            "civil": ["civil", "tort", "liability", "damages"],
            "family": ["family", "marriage", "divorce", "custody", "child"],
            "employment": ["employment", "labor", "worker", "wage"],
            "environmental": ["environmental", "pollution", "conservation"],
            "business": ["business", "corporation", "commercial", "contract"],
            "property": ["property", "real estate", "land"],
            "tax": ["tax", "revenue", "assessment"],
            "health": ["health", "medical", "healthcare"],
            "education": ["education", "school"],
            "traffic": ["traffic", "vehicle", "motor", "driving"],
            "probate": ["probate", "estate", "will", "trust"],
        }

        for area, keywords in area_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                return area

        return "general"

    def _extract_section_number(self, text: str) -> Optional[str]:
        """Extract section number from text.

        Args:
            text: Text containing section reference

        Returns:
            Section number or None
        """
        import re

        # Common patterns: "Section 123", "§ 123", "§123", "Sec. 123"
        # Also support chapter/title labels and dot-prefixed identifiers (e.g., ".010").
        patterns = [
            r"§\s*(\d+[\.\-\w]*)",
            r"Section\s+(\d+[\.\-\w]*)",
            r"Sec\.\s*(\d+[\.\-\w]*)",
            r"^\s*\.(\d+[\.\-\w]*)\b",
            r"\b(\d+\-\d+[A-Za-z]?(?:\.\d+)*)\b",
            r"Title\s+(\d+[A-Za-z]?(?:\.\d+)?)\b",
            r"Chapter\s+(\d+[A-Za-z]?(?:\.\d+)?)\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return str(match.group(1)).strip().rstrip(".")

        return None

    def _extract_legislative_history(self, text: str) -> Dict[str, Any]:
        """Extract trailing legislative history citations from statute text.

        Returns a dictionary containing cleaned text and structured citation data.
        """
        cleaned_text, raw_blocks, citations = extract_trailing_history_citations(text)
        return {
            "cleaned_text": cleaned_text,
            "history_citation_blocks": raw_blocks,
            "history_citations": citations,
        }

    def _looks_like_shallow_stub_text(self, text: str) -> bool:
        normalized = self._normalize_legal_text(text)
        if not normalized:
            return True

        if len(normalized) < 220:
            return True

        # Many state scrapers currently seed text as "Section X: <link text>".
        if re.match(
            r"^(section|sec\.?|title|chapter)\s+[\w\-.]+\s*:\s*", normalized, flags=re.IGNORECASE
        ):
            return True

        return False

    def _contains_statute_signals(self, text: str) -> bool:
        value = self._normalize_legal_text(text).lower()
        if not value:
            return False

        patterns = [
            r"\b§\s*\d",
            r"\bsec(?:tion)?\.?\s+\d",
            r"\btitle\s+\d",
            r"\bchapter\s+\d",
            r"\barticle\s+\d",
            r"\b\d+[\-\.]\d+[a-z]?\b",
        ]
        return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)

    def _looks_like_navigation_text(self, text: str) -> bool:
        value = self._normalize_legal_text(text).lower()
        if not value:
            return True

        return any(hint in value for hint in _NAV_LABEL_HINTS)

    def _is_probable_statute_link(self, link_text: str, link_url: str, code_url: str = "") -> bool:
        text = self._normalize_legal_text(link_text)
        if len(text) < 3:
            return False

        url_value = str(link_url or "").strip().lower()
        parsed = urlparse(url_value) if url_value else None
        path = (parsed.path if parsed else "") or ""

        if url_value.startswith(("mailto:", "tel:", "javascript:")):
            return False

        # Skip obvious binary/document links that cannot hydrate into statute text.
        if _NON_HTML_DOC_RE.search(url_value):
            return False

        if self._looks_like_navigation_text(text) and not self._contains_statute_signals(text):
            return False

        if parsed and path in {"", "/"} and not parsed.query:
            return False

        if code_url:
            base = urlparse(str(code_url).strip())
            same_target = (
                parsed is not None
                and parsed.scheme == base.scheme
                and parsed.netloc == base.netloc
                and parsed.path == base.path
                and parsed.query == base.query
            )
            if same_target and not self._contains_statute_signals(text):
                return False

        if self._contains_statute_signals(text):
            return True

        if any(hint in url_value for hint in _STATUTE_URL_HINTS):
            # Avoid broad index/category links (e.g., /laws, /statutes, /code)
            # unless they contain section-like signals in URL structure.
            tail = path.rstrip("/").split("/")[-1] if path else ""
            generic_tails = {
                "law",
                "laws",
                "statute",
                "statutes",
                "code",
                "codes",
                "constitution",
                "rules",
                "home",
                "index",
                "default.aspx",
            }
            has_structured_query = any(
                token in url_value
                for token in ("section=", "sec=", "cite=", "docname=", "law.aspx?d=")
            )
            has_numeric_path = bool(re.search(r"\d", path or ""))
            path_depth = len([part for part in (path or "").split("/") if part])

            if (tail in generic_tails) and not (
                has_structured_query or has_numeric_path or path_depth >= 4
            ):
                return False
            return True

        return False

    def _is_source_bound_operative_statute_record(
        self,
        statute: NormalizedStatute,
    ) -> bool:
        """Return whether a state-owned parser proved an operative row.

        The default is deliberately fail-closed.  A state override may use
        this seam only when its source hierarchy, row identity, and complete
        frontier are independently bound.  Generic scaffold rejection still
        runs before this hook.
        """

        del statute
        return False

    def _is_low_quality_statute_record(self, statute: NormalizedStatute) -> bool:
        if not isinstance(statute, NormalizedStatute):
            return False

        section_name = self._normalize_legal_text(str(statute.section_name or ""))
        full_text = self._normalize_legal_text(str(statute.full_text or ""))
        source_url = str(statute.source_url or "").strip()
        section_number = str(statute.section_number or "").strip()

        fallback_section = bool(re.match(r"^Section-\d+$", section_number, flags=re.IGNORECASE))
        has_statute_signal = (
            self._contains_statute_signals(section_name)
            or self._contains_statute_signals(full_text)
            or any(hint in source_url.lower() for hint in _STATUTE_URL_HINTS)
        )
        nav_like = self._looks_like_navigation_text(
            section_name
        ) or self._looks_like_navigation_text(full_text)
        nav_url_like = any(hint in source_url.lower() for hint in _NAV_URL_HINTS)

        if _SCAFFOLD_SECTION_TEXT_RE.match(full_text):
            return True

        if self._is_source_bound_operative_statute_record(statute):
            return False

        if fallback_section and nav_like and not has_statute_signal:
            return True

        if nav_url_like and not has_statute_signal:
            return True

        if nav_like and not has_statute_signal and len(full_text) < 400:
            return True

        return False

    def _canonicalize_statute_url(self, link_url: str) -> str:
        """Normalize wrapped document links to direct statute URLs when possible."""
        raw = str(link_url or "").strip()
        if not raw:
            return raw

        try:
            parsed = urlparse(raw)
            query = parse_qs(parsed.query or "")
            doc_name_values = query.get("docName") or query.get("docname")
            if doc_name_values:
                candidate = unquote(str(doc_name_values[0] or "")).strip()
                if candidate.startswith(("http://", "https://")):
                    return candidate
        except Exception:
            return raw

        return raw

    def _derive_section_number_from_url(self, link_url: str) -> Optional[str]:
        """Best-effort section number extraction from statute URL patterns."""
        url_value = str(link_url or "").strip()
        if not url_value:
            return None

        lowered = url_value.lower()
        az_match = re.search(r"/ars/(\d+)/(\d{5})(?:-(\d{2}))?\.htm", lowered)
        if az_match:
            title_num = str(int(az_match.group(1)))
            base_num = str(int(az_match.group(2)))
            suffix = az_match.group(3)
            if suffix:
                return f"{title_num}-{base_num}.{suffix}"
            return f"{title_num}-{base_num}"

        parsed = urlparse(url_value)
        query = parse_qs(parsed.query or "")
        section_values = query.get("section") or query.get("sec")
        if section_values:
            candidate = self._normalize_legal_text(str(section_values[0]))
            if candidate:
                return candidate

        cite_values = query.get("cite")
        if cite_values:
            candidate = self._normalize_legal_text(str(cite_values[0]))
            if re.match(r"^\d+[A-Za-z]?\.\d+\.\d+[A-Za-z]?$", candidate):
                return candidate

        wi_match = re.search(
            r"/document/statutes/([0-9]+(?:\.[0-9A-Za-z]+)+)$", parsed.path, flags=re.IGNORECASE
        )
        if wi_match:
            return wi_match.group(1)

        mn_match = re.search(
            r"/statutes/cite/([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)+)$", parsed.path, flags=re.IGNORECASE
        )
        if mn_match:
            return mn_match.group(1)

        wv_match = re.search(r"/(\d+[A-Za-z]?(?:-\d+[A-Za-z]?){2,})/?$", parsed.path)
        if wv_match:
            return wv_match.group(1)

        mt_match = re.search(r"/(\d{4}-\d{4}-\d{4}-\d{4})\.html$", parsed.path, flags=re.IGNORECASE)
        if mt_match:
            return mt_match.group(1)

        return None

    def _extract_best_content_text(self, html_text: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except Exception:
            return self._normalize_legal_text(html_text)

        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe"]):
            tag.decompose()

        candidates = []
        selectors = [
            "main",
            "article",
            "section",
            "div#content",
            "div.content",
            "div#main-content",
            "div.main-content",
            "div.statute",
            "div.law-content",
        ]

        for selector in selectors:
            for node in soup.select(selector):
                text = self._normalize_legal_text(node.get_text(" ", strip=True))
                if len(text) >= 200:
                    candidates.append(text)

        if not candidates:
            body = soup.find("body")
            if body is not None:
                text = self._normalize_legal_text(body.get_text(" ", strip=True))
                if text:
                    candidates.append(text)

        if not candidates:
            fallback = self._normalize_legal_text(soup.get_text(" ", strip=True))
            return fallback

        # Prefer the longest candidate as a simple heuristic for statute body text.
        return max(candidates, key=len)

    def _trim_to_section_context(self, text: str, statute: NormalizedStatute) -> str:
        value = self._normalize_legal_text(text)
        if not value:
            return value

        section_number = self._normalize_legal_text(str(statute.section_number or ""))
        section_name = self._normalize_legal_text(str(statute.section_name or ""))

        anchors: List[str] = []
        if section_number:
            anchors.extend(
                [
                    f"section {section_number}",
                    f"§ {section_number}",
                    section_number,
                ]
            )
        if section_name and section_name != section_number and len(section_name) >= 6:
            anchors.append(section_name)

        lower_value = value.lower()
        best_idx: Optional[int] = None
        for anchor in anchors:
            idx = lower_value.find(anchor.lower())
            if idx >= 0:
                best_idx = idx if best_idx is None else min(best_idx, idx)

        if best_idx is None:
            trimmed = value
        else:
            # Keep a little left context for headings, but drop bulky site navigation.
            start = max(0, best_idx - 24)
            trimmed = self._normalize_legal_text(value[start:]) or value

        # Drop trailing site chrome/footer content that often follows statutes.
        footer_markers = [
            "Legislative questions or comments",
            "Call the Legislative Hotline",
            "TTY for deaf/hard of hearing",
            "Back to top",
            "Privacy notice",
        ]
        lowered = trimmed.lower()
        cut_index: Optional[int] = None
        for marker in footer_markers:
            idx = lowered.find(marker.lower())
            if idx >= 0:
                cut_index = idx if cut_index is None else min(cut_index, idx)

        if cut_index is not None and cut_index > 80:
            trimmed = self._normalize_legal_text(trimmed[:cut_index])

        return trimmed or value

    async def _fetch_page_contents_with_archival_fallback(
        self,
        urls: Sequence[str],
        timeout_seconds: int = 25,
        *,
        headers: Optional[Mapping[str, str]] = None,
        content_validator: Optional[Callable[[bytes], bool]] = None,
        media_type: Optional[str] = None,
        max_concurrency: int = 8,
        prefer_direct: bool = False,
        common_crawl_domain_terms: Optional[Sequence[str]] = None,
        common_crawl_url_terms: Optional[Sequence[str]] = None,
        common_crawl_mime_terms: Optional[Sequence[str]] = None,
        wayback_prefix_inventory: bool = False,
        archive_recovery_enabled: bool = True,
    ) -> StateLawPageMultiFetchResult:
        """Fetch a whole page frontier through one archive-aware batch.

        Common Crawl pointer discovery is performed once for the requested
        frontier.  The existing archival multi-fetch bridge then groups exact
        pointers by immutable WARC filename and coalesces nearby byte ranges.
        With ``prefer_direct``, concurrent official requests run once before
        the grouped archive recovery; otherwise the historical archive-first
        order is preserved.

        The returned payloads and receipts remain aligned with ``urls``.  This
        is the multi-page counterpart to
        :meth:`_fetch_page_content_with_archival_fallback`; the single-page API
        remains unchanged for compatibility and state-specific traversals that
        discover their next locator only after parsing the current response.
        ``wayback_prefix_inventory`` adds one bounded prefix-discovery stage
        for the plural frontier; exact captures are replayed without repeating
        CDX discovery for every residual page.  A prospective acquisition
        ledger always enables that grouped inventory and disables legacy
        per-page archive discovery, even when an older state adapter omitted
        the explicit opt-in.
        """

        request_headers = {
            str(key): str(value)
            for key, value in dict(headers or {}).items()
            if str(key).strip()
        }
        sanitized_headers = _sanitized_multifetch_headers(request_headers)
        requested_urls = [self._canonical_fetch_url(url) for url in urls]
        if any(not url for url in requested_urls):
            raise ValueError("urls must contain only non-empty values")
        if isinstance(max_concurrency, bool) or int(max_concurrency) <= 0:
            raise ValueError("max_concurrency must be positive")
        if not isinstance(prefer_direct, bool):
            raise TypeError("prefer_direct must be a boolean")
        if not isinstance(wayback_prefix_inventory, bool):
            raise TypeError("wayback_prefix_inventory must be a boolean")
        if not isinstance(archive_recovery_enabled, bool):
            raise TypeError("archive_recovery_enabled must be a boolean")
        if not requested_urls:
            empty_stats = {
                "common_crawl_inventory_queries": 0,
                "common_crawl_inventory_records": 0,
                "common_crawl_matched_pointers": 0,
                "requested_pages": 0,
                "unique_pages": 0,
            }
            self._last_page_multifetch_stats = dict(empty_stats)
            self._last_common_crawl_batch_stats = {}
            return StateLawPageMultiFetchResult(
                urls=[],
                payloads=[],
                errors=[],
                transport_receipts=[],
                parser_input_envelopes=[],
                stats=empty_stats,
            )

        parsed_urls = [urlparse(url) for url in requested_urls]
        if any(
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            for parsed in parsed_urls
        ):
            raise ValueError("urls must be absolute HTTP(S) locators")

        unique_urls = list(dict.fromkeys(requested_urls))

        def _content_is_valid(payload: bytes) -> bool:
            if not payload:
                return False
            if content_validator is None:
                return True
            try:
                return bool(content_validator(payload))
            except Exception:
                return False

        # A restarted exact crawl must not repeat requests whose immutable
        # parser inputs already exist.  Replay those first, then submit only
        # genuine misses to the live/archive batch.  This is intentionally the
        # same ledger contract used by the single-page and stateful adapters.
        retained_by_url: Dict[str, tuple[bytes, Dict[str, Any], Any]] = {}
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        effective_wayback_prefix_inventory = bool(
            wayback_prefix_inventory or ledger is not None
        )
        if ledger is not None:
            for official_url in unique_urls:
                retained = ledger.replay_retained_parser_input(
                    official_url=official_url,
                    sanitized_request=_sanitized_multifetch_request(
                        official_url,
                        sanitized_headers=sanitized_headers,
                    ),
                )
                if retained is None:
                    continue
                retained_body = bytes(retained.envelope.body or b"")
                if not _content_is_valid(retained_body):
                    self._raise_if_retained_replay_only_network(
                        operation=(
                            "network fallback after retained parser input failed "
                            "the current validator"
                        ),
                        url=official_url,
                    )
                    continue
                retained_by_url[official_url] = (
                    retained_body,
                    dict(retained.transport_receipt),
                    retained.envelope,
                )
                self._record_fetch_event(
                    provider="retained_acquisition_replay",
                    success=True,
                )

        network_requested_urls = [
            url for url in requested_urls if url not in retained_by_url
        ]
        network_unique_urls = list(dict.fromkeys(network_requested_urls))
        if not network_requested_urls:
            payloads = [retained_by_url[url][0] for url in requested_urls]
            receipts = [retained_by_url[url][1] for url in requested_urls]
            envelopes = [retained_by_url[url][2] for url in requested_urls]
            stats = {
                "common_crawl_inventory_queries": 0,
                "common_crawl_inventory_records": 0,
                "common_crawl_matched_pointers": 0,
                "network_requested_pages": 0,
                "requested_pages": len(requested_urls),
                "retained_replay_pages": len(requested_urls),
                "retained_replay_unique_pages": len(unique_urls),
                "cross_instance_retained_replay_pages": 0,
                "cross_instance_retained_replay_unique_pages": 0,
                "successful_pages": len(requested_urls),
                "unique_pages": len(unique_urls),
            }
            self._last_page_multifetch_stats = dict(stats)
            self._last_common_crawl_batch_stats = {}
            return StateLawPageMultiFetchResult(
                urls=list(requested_urls),
                payloads=payloads,
                errors=[None] * len(requested_urls),
                transport_receipts=receipts,
                parser_input_envelopes=envelopes,
                stats=stats,
            )

        self._raise_if_retained_replay_only_network(
            operation="direct/Common Crawl/Wayback/archive multi-fetch",
            url=network_unique_urls[0] if network_unique_urls else "",
        )

        from .state_archival_fetch import (
            ArchivalFetchClient,
            _archived_resource_identity,
        )

        inventory_query_count = 0
        inventory_records: List[Dict[str, Any]] = []
        pointer_requests: List[tuple[str, Dict[str, Any]]] = []

        async def _discover_common_crawl_pointers(
            target_urls: Sequence[str],
        ) -> List[tuple[str, Dict[str, Any]]]:
            nonlocal inventory_query_count, inventory_records, pointer_requests
            targets = list(
                dict.fromkeys(
                    self._canonical_fetch_url(url)
                    for url in target_urls
                    if self._canonical_fetch_url(url)
                )
            )
            if not targets:
                return []
            target_parsed_urls = [urlparse(url) for url in targets]
            derived_domains = sorted(
                {
                    str(parsed.hostname or "").lower().strip(".")
                    for parsed in target_parsed_urls
                    if parsed.hostname
                }
            )
            domain_terms = list(
                dict.fromkeys(
                    str(value or "").strip()
                    for value in (
                        common_crawl_domain_terms
                        if common_crawl_domain_terms is not None
                        else derived_domains
                    )
                    if str(value or "").strip()
                )
            )
            if common_crawl_url_terms is None:
                derived_url_terms: List[str] = []
                compact_threshold = max(
                    2,
                    _env_int(
                        "STATE_SCRAPER_COMMON_CRAWL_PREFIX_COMPACT_THRESHOLD",
                        64,
                    ),
                )
                parsed_by_origin: Dict[tuple[str, Optional[int]], List[Any]] = {}
                for parsed in target_parsed_urls:
                    parsed_by_origin.setdefault(
                        (
                            str(parsed.hostname or "").lower().strip("."),
                            parsed.port,
                        ),
                        [],
                    ).append(parsed)
                for origin in sorted(
                    parsed_by_origin,
                    key=lambda item: (
                        item[0],
                        -1 if item[1] is None else int(item[1]),
                    ),
                ):
                    origin_urls = parsed_by_origin[origin]
                    if len(origin_urls) >= compact_threshold:
                        paths = [str(parsed.path or "/") for parsed in origin_urls]
                        common_path = os.path.commonprefix(paths)
                        if len(set(paths)) == 1:
                            prefix_term = paths[0]
                        else:
                            prefix_term = (
                                common_path
                                if common_path.endswith("/")
                                else common_path.rsplit("/", 1)[0] + "/"
                            )
                        if prefix_term not in {"", "/"}:
                            derived_url_terms.append(prefix_term)
                            continue
                    for parsed in origin_urls:
                        path_query = str(parsed.path or "/")
                        if parsed.params:
                            path_query += ";" + str(parsed.params)
                        if parsed.query:
                            path_query += "?" + str(parsed.query)
                        derived_url_terms.append(
                            path_query if path_query != "/" else parsed.geturl()
                        )
                url_terms = list(dict.fromkeys(derived_url_terms))
            else:
                url_terms = list(
                    dict.fromkeys(
                        str(value or "").strip()
                        for value in common_crawl_url_terms
                        if str(value or "").strip()
                    )
                )
            mime_terms = list(
                dict.fromkeys(
                    str(value or "").strip()
                    for value in (common_crawl_mime_terms or ["html"])
                    if str(value or "").strip()
                )
            )
            inventory_limit = max(
                1,
                _env_int(
                    "STATE_SCRAPER_COMMON_CRAWL_FRONTIER_MAX_RESULTS",
                    max(100, len(targets) * 8),
                ),
            )
            inventory_query_count += 1
            try:
                discovered_records = (
                    await self._search_state_common_crawl_records(
                        domain_terms=domain_terms,
                        url_terms=url_terms,
                        mime_terms=mime_terms,
                        max_results=inventory_limit,
                    )
                )
            except Exception as exc:
                self.logger.warning(
                    "Common Crawl frontier inventory failed for %s: %s",
                    self.state_code,
                    exc,
                )
                discovered_records = []

            target_by_identity: Dict[
                tuple[str, Optional[int], str, str, str],
                str,
            ] = {}
            for official_url in targets:
                identity = _archived_resource_identity(official_url)
                if identity is not None:
                    target_by_identity.setdefault(identity, official_url)

            matched: List[tuple[str, Dict[str, Any]]] = []
            for raw_record in discovered_records:
                if not isinstance(raw_record, dict):
                    continue
                indexed_url = self._canonical_fetch_url(
                    str(raw_record.get("url") or "")
                )
                if not indexed_url:
                    continue
                official_url = target_by_identity.get(
                    _archived_resource_identity(indexed_url)
                )
                if official_url is not None:
                    matched.append((official_url, dict(raw_record)))
            inventory_records = [
                dict(record)
                for record in discovered_records
                if isinstance(record, dict)
            ]
            pointer_requests = list(matched)
            return matched

        common_crawl_record_loader = None
        initial_pointer_requests: List[tuple[str, Dict[str, Any]]] = []
        if prefer_direct and archive_recovery_enabled:
            common_crawl_record_loader = _discover_common_crawl_pointers

        wayback_inventory_loader = None
        if effective_wayback_prefix_inventory and archive_recovery_enabled:

            async def _discover_wayback_capture_inventory(
                target_urls: Sequence[str],
            ) -> Dict[str, Any]:
                from ...web_archiving.wayback_machine_engine import (
                    fetch_wayback_capture_inventory,
                )

                configured_max_queries = max(
                    1,
                    min(
                        512,
                        _env_int(
                            "STATE_SCRAPER_WAYBACK_PREFIX_MAX_QUERIES",
                            128,
                        ),
                    ),
                )
                max_results = max(
                    100,
                    min(
                        50_000,
                        _env_int(
                            "STATE_SCRAPER_WAYBACK_PREFIX_MAX_RESULTS_PER_QUERY",
                            5_000,
                        ),
                    ),
                )
                result_multiplier = max(
                    1,
                    min(
                        64,
                        _env_int(
                            "STATE_SCRAPER_WAYBACK_PREFIX_RESULT_MULTIPLIER",
                            8,
                        ),
                    ),
                )
                configured_query_attempts = max(
                    1,
                    min(
                        3,
                        _env_int(
                            "STATE_SCRAPER_WAYBACK_PREFIX_QUERY_ATTEMPTS",
                            2,
                        ),
                    ),
                )
                retry_delay_seconds = max(
                    0.0,
                    min(
                        5.0,
                        _env_float(
                            "STATE_SCRAPER_WAYBACK_PREFIX_RETRY_DELAY_SECONDS",
                            1.0,
                        ),
                    ),
                )
                inventory_targets = tuple(
                    dict.fromkeys(
                        self._canonical_fetch_url(url)
                        for url in target_urls
                        if self._canonical_fetch_url(url)
                    )
                )
                origin_counts: Dict[tuple[str, str], int] = {}
                for target_url in inventory_targets:
                    parsed_target = urlparse(target_url)
                    origin = (
                        str(parsed_target.scheme or "").lower(),
                        str(parsed_target.netloc or "").lower(),
                    )
                    origin_counts[origin] = origin_counts.get(origin, 0) + 1
                has_plural_same_origin_group = any(
                    count > 1 for count in origin_counts.values()
                )
                max_queries_per_origin: Optional[int] = None
                if has_plural_same_origin_group:
                    # Preserve tight title/chapter prefixes within one bounded
                    # logical inventory.  A small per-origin budget prevents
                    # both the former host-wide scan and a per-page CDX loop.
                    max_queries_per_origin = max(
                        1,
                        min(
                            8,
                            _env_int(
                                "STATE_SCRAPER_WAYBACK_PREFIX_MAX_QUERIES_PER_ORIGIN",
                                8,
                            ),
                        ),
                    )
                max_queries = min(
                    configured_max_queries,
                    max(
                        1,
                        len(origin_counts)
                        * int(max_queries_per_origin or configured_max_queries),
                    ),
                )
                outcome = await fetch_wayback_capture_inventory(
                    inventory_targets,
                    timeout_seconds=max(1, int(timeout_seconds or 25)),
                    max_queries=max_queries,
                    max_queries_per_origin=max_queries_per_origin,
                    max_results_per_query=max_results,
                    result_multiplier=result_multiplier,
                    # The engine retries only the exact transiently failed
                    # query plan.  Successful same-origin chunks are never
                    # submitted again, so a bounded plural retry cannot turn
                    # back into a whole-frontier or per-page archive loop.
                    query_attempts=configured_query_attempts,
                    retry_delay_seconds=retry_delay_seconds,
                )
                if not isinstance(outcome, dict):
                    raise TypeError(
                        "shared Wayback capture inventory returned a non-mapping"
                    )
                receipts = outcome.get("receipts")
                if isinstance(receipts, list):
                    for receipt in receipts:
                        if isinstance(receipt, Mapping) and receipt:
                            self._state_law_archive_discovery_receipts.append(
                                dict(receipt)
                            )
                return outcome

            wayback_inventory_loader = _discover_wayback_capture_inventory

        # Production crawls attach a prospective acquisition ledger.  Admit a
        # completed transport result immediately, before the rest of a large
        # frontier (or another WARC object) can fail or be interrupted.  The
        # callback deliberately reuses the same URL/digest/receipt checks as the
        # ordinary post-batch path; the aligned return vectors are still built
        # and verified below.
        eager_retained_by_url: Dict[
            str,
            tuple[bytes, Dict[str, Any], Any, Dict[str, Any]],
        ] = {}
        eager_retention_errors: Dict[str, str] = {}
        cross_instance_retained_replay_pages = 0
        cross_instance_retained_replay_unique_pages = 0

        def _retain_completed_result(official_url: str, fetched: Any) -> None:
            canonical_url = self._canonical_fetch_url(official_url)
            if canonical_url in eager_retained_by_url:
                return
            try:
                self._last_page_fetch_transport_evidence = {}
                self._last_page_parser_input_envelope = None
                payload = self._retain_archival_fetch_result_before_parser(
                    official_url=canonical_url,
                    fetched=fetched,
                    media_type=media_type,
                    sanitized_request=_sanitized_multifetch_request(
                        canonical_url,
                        sanitized_headers=sanitized_headers,
                    ),
                )
                if not _content_is_valid(payload):
                    raise RuntimeError(
                        "archival multi-fetch returned an invalid eager parser input"
                    )
                provenance = self._last_parser_input_row_provenance()
                receipt = provenance.get("transport_receipt")
                if not isinstance(receipt, dict) or not receipt:
                    receipt = dict(
                        getattr(self, "_last_page_fetch_transport_evidence", {})
                        or {}
                    )
                envelope = getattr(self, "_last_page_parser_input_envelope", None)
                evidence = dict(
                    getattr(self, "_last_page_fetch_transport_evidence", {})
                    or {}
                )
                eager_retained_by_url[canonical_url] = (
                    bytes(payload),
                    dict(receipt),
                    envelope,
                    evidence,
                )
                eager_retention_errors.pop(canonical_url, None)
            except Exception as exc:
                eager_retention_errors[canonical_url] = (
                    f"{type(exc).__name__}: {exc}"
                )

        # Two timeout/retry workers can reach this point with ledger instances
        # that were both constructed before either worker retained a response.
        # Serialize only their exact outstanding request identities, then
        # refresh and replay once more immediately before network/WARC I/O.
        # The successful-result callback publishes immutable receipts before
        # the reservation is released, including partial batch success.
        reservation_keys: tuple[tuple[str, str, str, str], ...] = ()
        reservation_token: object | None = None
        if ledger is not None:
            reservation_keys = _multifetch_request_reservation_keys(
                ledger,
                network_unique_urls,
                sanitized_headers=sanitized_headers,
            )
            reservation_token = await _claim_multifetch_request_reservations(
                reservation_keys
            )
            try:
                ledger.refresh_existing_entries()
                previous_network_page_count = len(network_requested_urls)
                previous_retained_urls = set(retained_by_url)
                for official_url in network_unique_urls:
                    retained = ledger.replay_retained_parser_input(
                        official_url=official_url,
                        sanitized_request=_sanitized_multifetch_request(
                            official_url,
                            sanitized_headers=sanitized_headers,
                        ),
                    )
                    if retained is None:
                        continue
                    retained_body = bytes(retained.envelope.body or b"")
                    if not _content_is_valid(retained_body):
                        continue
                    retained_by_url[official_url] = (
                        retained_body,
                        dict(retained.transport_receipt),
                        retained.envelope,
                    )
                    self._record_fetch_event(
                        provider="retained_acquisition_replay",
                        success=True,
                    )
                network_requested_urls = [
                    url for url in requested_urls if url not in retained_by_url
                ]
                network_unique_urls = list(dict.fromkeys(network_requested_urls))
                cross_instance_retained_replay_pages = (
                    previous_network_page_count - len(network_requested_urls)
                )
                cross_instance_retained_replay_unique_pages = len(
                    set(retained_by_url) - previous_retained_urls
                )
                remaining_network_urls = set(network_unique_urls)
                initial_pointer_requests = [
                    (official_url, record)
                    for official_url, record in initial_pointer_requests
                    if official_url in remaining_network_urls
                ]
                pointer_requests = [
                    (official_url, record)
                    for official_url, record in pointer_requests
                    if official_url in remaining_network_urls
                ]
            except BaseException:
                _release_multifetch_request_reservations(
                    reservation_keys,
                    reservation_token,
                )
                raise

        if not network_requested_urls:
            _release_multifetch_request_reservations(
                reservation_keys,
                reservation_token,
            )
            payloads = [retained_by_url[url][0] for url in requested_urls]
            receipts = [retained_by_url[url][1] for url in requested_urls]
            envelopes = [retained_by_url[url][2] for url in requested_urls]
            stats = {
                "common_crawl_inventory_queries": inventory_query_count,
                "common_crawl_inventory_records": len(inventory_records),
                "common_crawl_matched_pointers": len(pointer_requests),
                "common_crawl_inventory_memo": (
                    dict(self._last_state_common_crawl_inventory_stats)
                    if inventory_query_count
                    else {}
                ),
                "network_requested_pages": 0,
                "eager_parser_inputs_admitted": 0,
                "eager_parser_input_retention_failures": 0,
                "parser_inputs_admitted": len(requested_urls),
                "parser_input_retention_failures": 0,
                "requested_pages": len(requested_urls),
                "retained_replay_pages": len(requested_urls),
                "retained_replay_unique_pages": len(retained_by_url),
                "cross_instance_retained_replay_pages": (
                    cross_instance_retained_replay_pages
                ),
                "cross_instance_retained_replay_unique_pages": (
                    cross_instance_retained_replay_unique_pages
                ),
                "successful_pages": len(requested_urls),
                "unique_pages": len(unique_urls),
            }
            self._last_page_multifetch_stats = dict(stats)
            self._last_common_crawl_batch_stats = {}
            return StateLawPageMultiFetchResult(
                urls=list(requested_urls),
                payloads=payloads,
                errors=[None] * len(requested_urls),
                transport_receipts=receipts,
                parser_input_envelopes=envelopes,
                stats=stats,
            )

        try:
            if not prefer_direct and archive_recovery_enabled:
                # Archive inventory is network I/O too.  Keep it behind the
                # exact-request reservation and the JIT replay so an
                # overlapping attempt that is now fully retained performs no
                # duplicate index query or WARC planning.
                initial_pointer_requests = (
                    await _discover_common_crawl_pointers(network_unique_urls)
                )
            archival_client = ArchivalFetchClient(
                request_timeout_seconds=max(1, int(timeout_seconds or 25)),
                delay_seconds=0.0,
                content_validator=content_validator or (lambda payload: bool(payload)),
                enable_common_crawl=archive_recovery_enabled,
                enable_direct=True,
                enable_insecure_direct=ledger is None,
                enable_wayback=archive_recovery_enabled,
                enable_archive_is=archive_recovery_enabled,
            )
            fetch_many_kwargs: Dict[str, Any] = {
                "common_crawl_records": initial_pointer_requests,
                "common_crawl_record_loader": common_crawl_record_loader,
                "wayback_inventory_loader": wayback_inventory_loader,
                "result_callback": (
                    _retain_completed_result if ledger is not None else None
                ),
                "enable_common_crawl": archive_recovery_enabled,
                "enable_archive_is": archive_recovery_enabled,
                "enable_per_page_fallback": (
                    archive_recovery_enabled
                    and not effective_wayback_prefix_inventory
                ),
                "wayback_capture_replay_attempts": max(
                    1,
                    min(
                        2,
                        _env_int(
                            "STATE_SCRAPER_WAYBACK_CAPTURE_REPLAY_ATTEMPTS",
                            2,
                        ),
                    ),
                ),
                "wayback_capture_retry_concurrency": max(
                    1,
                    min(
                        4,
                        int(max_concurrency),
                        _env_int(
                            "STATE_SCRAPER_WAYBACK_CAPTURE_RETRY_CONCURRENCY",
                            4,
                        ),
                    ),
                ),
                "max_concurrency": int(max_concurrency),
                "prefer_direct": prefer_direct,
            }
            if request_headers:
                fetch_many_kwargs["request_headers"] = dict(request_headers)
            batch = await archival_client.fetch_many_with_fallback(
                network_requested_urls,
                **fetch_many_kwargs,
            )
        finally:
            _release_multifetch_request_reservations(
                reservation_keys,
                reservation_token,
            )
        fetched_results = list(getattr(batch, "results", []) or [])
        batch_errors = list(getattr(batch, "errors", []) or [])
        if (
            len(fetched_results) != len(network_requested_urls)
            or len(batch_errors) != len(network_requested_urls)
        ):
            raise RuntimeError(
                "archival multi-fetch result did not align with its URL frontier"
            )

        payloads: List[bytes] = []
        errors: List[Optional[str]] = []
        transport_receipts: List[Optional[Dict[str, Any]]] = []
        parser_input_envelopes: List[Any] = []
        retention_failures = 0
        for official_url, fetched, batch_error in zip(
            network_requested_urls,
            fetched_results,
            batch_errors,
        ):
            eager_retained = eager_retained_by_url.get(official_url)
            if eager_retained is not None:
                payload, receipt, envelope, evidence = eager_retained
                aligned_payload = bytes(getattr(fetched, "content", b"") or b"")
                aligned_url = self._canonical_fetch_url(
                    str(getattr(fetched, "url", "") or "")
                )
                declared_digest = str(
                    getattr(fetched, "content_sha256", "") or ""
                ).strip().lower()
                payload_digest = hashlib.sha256(payload).hexdigest()
                if (
                    fetched is None
                    or aligned_payload != payload
                    or aligned_url.rstrip("/") != official_url.rstrip("/")
                    or (declared_digest and declared_digest != payload_digest)
                ):
                    raise RuntimeError(
                        "eagerly retained result did not match its aligned batch row"
                    )
                self._last_page_fetch_transport_evidence = dict(evidence)
                self._last_page_parser_input_envelope = envelope
                payloads.append(bytes(payload))
                errors.append(None)
                transport_receipts.append(dict(receipt))
                parser_input_envelopes.append(envelope)
                provider = str(
                    getattr(fetched, "source", "archival_multifetch")
                    or "archival_multifetch"
                )
                self._record_fetch_event(provider=provider, success=True)
                await self._cache_successful_page_fetch(
                    url=official_url,
                    payload=bytes(payload),
                    provider=provider,
                )
                continue
            self._last_page_fetch_transport_evidence = {}
            self._last_page_parser_input_envelope = None
            if fetched is None:
                payloads.append(b"")
                errors.append(str(batch_error or "all archival transports missed"))
                transport_receipts.append(None)
                parser_input_envelopes.append(None)
                self._record_fetch_event(
                    provider="archival_multifetch",
                    success=False,
                    error=errors[-1],
                )
                continue
            provider = str(
                getattr(fetched, "source", "archival_multifetch")
                or "archival_multifetch"
            )
            try:
                payload = self._retain_archival_fetch_result_before_parser(
                    official_url=official_url,
                    fetched=fetched,
                    media_type=media_type,
                    sanitized_request=_sanitized_multifetch_request(
                        official_url,
                        sanitized_headers=sanitized_headers,
                    ),
                )
                if not payload:
                    raise RuntimeError("archival multi-fetch returned an empty parser input")
                provenance = self._last_parser_input_row_provenance()
                receipt = provenance.get("transport_receipt")
                if not isinstance(receipt, dict) or not receipt:
                    receipt = dict(
                        getattr(self, "_last_page_fetch_transport_evidence", {})
                        or {}
                    )
                envelope = getattr(self, "_last_page_parser_input_envelope", None)
                payloads.append(bytes(payload))
                errors.append(None)
                transport_receipts.append(dict(receipt))
                parser_input_envelopes.append(envelope)
                eager_retention_errors.pop(official_url, None)
                self._record_fetch_event(provider=provider, success=True)
                await self._cache_successful_page_fetch(
                    url=official_url,
                    payload=bytes(payload),
                    provider=provider,
                )
            except Exception as exc:
                retention_failures += 1
                payloads.append(b"")
                errors.append(f"{type(exc).__name__}: {exc}")
                transport_receipts.append(None)
                parser_input_envelopes.append(None)
                self._record_fetch_event(
                    provider=provider,
                    success=False,
                    error=str(exc),
                )

        if retained_by_url:
            network_rows = iter(
                zip(
                    payloads,
                    errors,
                    transport_receipts,
                    parser_input_envelopes,
                )
            )
            merged_payloads: List[bytes] = []
            merged_errors: List[Optional[str]] = []
            merged_receipts: List[Optional[Dict[str, Any]]] = []
            merged_envelopes: List[Any] = []
            for official_url in requested_urls:
                replayed = retained_by_url.get(official_url)
                if replayed is not None:
                    payload, receipt, envelope = replayed
                    merged_payloads.append(payload)
                    merged_errors.append(None)
                    merged_receipts.append(receipt)
                    merged_envelopes.append(envelope)
                    continue
                payload, error, receipt, envelope = next(network_rows)
                merged_payloads.append(payload)
                merged_errors.append(error)
                merged_receipts.append(receipt)
                merged_envelopes.append(envelope)
            payloads = merged_payloads
            errors = merged_errors
            transport_receipts = merged_receipts
            parser_input_envelopes = merged_envelopes

        stats = dict(getattr(batch, "stats", {}) or {})
        stats.update(
            {
                "common_crawl_inventory_queries": inventory_query_count,
                "common_crawl_inventory_records": len(inventory_records),
                "common_crawl_matched_pointers": len(pointer_requests),
                "common_crawl_inventory_memo": (
                    dict(self._last_state_common_crawl_inventory_stats)
                    if inventory_query_count
                    else {}
                ),
                "network_requested_pages": len(network_requested_urls),
                "eager_parser_inputs_admitted": len(eager_retained_by_url),
                "eager_parser_input_retention_failures": len(
                    eager_retention_errors
                ),
                "parser_inputs_admitted": sum(bool(payload) for payload in payloads),
                "parser_input_retention_failures": retention_failures,
                "requested_pages": len(requested_urls),
                "retained_replay_pages": len(requested_urls)
                - len(network_requested_urls),
                "retained_replay_unique_pages": len(retained_by_url),
                "cross_instance_retained_replay_pages": (
                    cross_instance_retained_replay_pages
                ),
                "cross_instance_retained_replay_unique_pages": (
                    cross_instance_retained_replay_unique_pages
                ),
                "successful_pages": sum(bool(payload) for payload in payloads),
                "unique_pages": len(unique_urls),
            }
        )
        self._last_page_multifetch_stats = dict(stats)
        self._last_common_crawl_batch_stats = dict(
            stats.get("common_crawl", {}) or {}
        )
        return StateLawPageMultiFetchResult(
            urls=list(requested_urls),
            payloads=payloads,
            errors=errors,
            transport_receipts=transport_receipts,
            parser_input_envelopes=parser_input_envelopes,
            stats=stats,
        )

    async def _fetch_page_contents_with_archival_fallback_retrying_residuals(
        self,
        urls: Sequence[str],
        *,
        residual_retry_attempts: int,
        repeat_grouped_archive_inventory_on_residual: bool = False,
        **fetch_kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        """Retry only unresolved rows through the existing plural fetch path.

        Each attempt remains one aligned multi-page request.  Successful rows
        are carried forward with their exact payload, transport receipt, and
        parser-input envelope, so they are never submitted to a later retry.
        The ordinary plural fetcher continues to own direct/archive selection,
        Common Crawl inventory discovery, WARC grouping, and durable eager
        retention; this helper only merges its aligned partial results.

        ``residual_retry_attempts`` counts retries after the initial request.
        Callers must keep it between zero and three so a configuration error
        cannot turn a strict corpus crawl into an unbounded retry loop.
        """

        if isinstance(residual_retry_attempts, bool):
            raise TypeError("residual_retry_attempts must be an integer")
        if not isinstance(repeat_grouped_archive_inventory_on_residual, bool):
            raise TypeError(
                "repeat_grouped_archive_inventory_on_residual must be a boolean"
            )
        retry_attempts = int(residual_retry_attempts)
        if retry_attempts < 0 or retry_attempts > 3:
            raise ValueError(
                "residual_retry_attempts must be between zero and three"
            )

        requested_urls = list(urls)
        unique_requested_urls = list(dict.fromkeys(requested_urls))
        attempt_urls = list(requested_urls)
        successful_rows: Dict[str, tuple[bytes, Optional[str], Any, Any]] = {}
        failed_rows: Dict[str, tuple[bytes, Optional[str], Any, Any]] = {}
        attempt_records: List[Dict[str, Any]] = []
        attempt_stats: List[Dict[str, Any]] = []
        initial_unresolved_urls: List[str] = []
        initial_stats: Dict[str, Any] = {}

        grouped_archive_inventory_enabled = bool(
            fetch_kwargs.get("wayback_prefix_inventory")
            or getattr(self, "_state_law_acquisition_ledger", None) is not None
        )
        for attempt_index in range(retry_attempts + 1):
            attempt_fetch_kwargs = dict(fetch_kwargs)
            if (
                attempt_index > 0
                and grouped_archive_inventory_enabled
                and not repeat_grouped_archive_inventory_on_residual
            ):
                # The initial grouped inventory is authoritative for this
                # retry cycle.  Retained rows are replayed by the plural fetcher
                # first; only unresolved rows receive another bounded direct
                # attempt, with no repeated CC/CDX/archive.is discovery.
                attempt_fetch_kwargs["archive_recovery_enabled"] = False
            batch = await self._fetch_page_contents_with_archival_fallback(
                attempt_urls,
                **attempt_fetch_kwargs,
            )
            aligned_vectors = (
                batch.urls,
                batch.payloads,
                batch.errors,
                batch.transport_receipts,
                batch.parser_input_envelopes,
            )
            if any(len(vector) != len(attempt_urls) for vector in aligned_vectors):
                raise RuntimeError(
                    "residual archival multi-fetch returned unaligned acquisition rows"
                )
            if list(batch.urls) != attempt_urls:
                raise RuntimeError(
                    "residual archival multi-fetch changed URL order or identity"
                )
            batch_stats = dict(batch.stats or {})
            attempt_stats.append(batch_stats)
            if attempt_index == 0:
                initial_stats = dict(batch_stats)

            unresolved_urls: List[str] = []
            status_by_url: Dict[str, bool] = {}
            payload_by_url: Dict[str, bytes] = {}
            for official_url, payload, error, receipt, envelope in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                batch.transport_receipts,
                batch.parser_input_envelopes,
                strict=True,
            ):
                aligned_payload = bytes(payload or b"")
                succeeded = error is None and bool(aligned_payload)
                prior_status = status_by_url.get(official_url)
                if prior_status is not None and prior_status != succeeded:
                    raise RuntimeError(
                        "residual archival multi-fetch returned inconsistent "
                        f"duplicate rows for exact URL: {official_url}"
                    )
                if succeeded and official_url in payload_by_url:
                    if payload_by_url[official_url] != aligned_payload:
                        raise RuntimeError(
                            "residual archival multi-fetch returned conflicting "
                            f"payloads for exact URL: {official_url}"
                        )
                status_by_url[official_url] = succeeded
                payload_by_url[official_url] = aligned_payload
                if succeeded:
                    successful_rows[official_url] = (
                        aligned_payload,
                        None,
                        receipt,
                        envelope,
                    )
                    failed_rows.pop(official_url, None)
                    continue
                failed_rows[official_url] = (
                    aligned_payload,
                    str(error or "empty parser input"),
                    receipt,
                    envelope,
                )
                if official_url not in unresolved_urls:
                    unresolved_urls.append(official_url)

            if attempt_index == 0:
                initial_unresolved_urls = list(unresolved_urls)
            attempt_records.append(
                {
                    "attempt": attempt_index,
                    "requested_urls": list(attempt_urls),
                    "requested_pages": len(attempt_urls),
                    "unresolved_urls": list(unresolved_urls),
                    "unresolved_pages": len(unresolved_urls),
                    "network_requested_pages": int(
                        batch_stats.get("network_requested_pages", 0) or 0
                    ),
                    "archive_recovery_enabled": bool(
                        attempt_fetch_kwargs.get("archive_recovery_enabled", True)
                    ),
                    "common_crawl_inventory_queries": int(
                        batch_stats.get("common_crawl_inventory_queries", 0) or 0
                    ),
                    "common_crawl_inventory_memo": dict(
                        batch_stats.get("common_crawl_inventory_memo", {}) or {}
                    ),
                    "common_crawl": dict(
                        batch_stats.get("common_crawl", {}) or {}
                    ),
                }
            )
            if not unresolved_urls or attempt_index >= retry_attempts:
                break
            # The residual list is de-duplicated in first-seen order.  Even a
            # one-page residual still travels through the plural API; there is
            # deliberately no per-URL singleton retry loop here.
            attempt_urls = list(unresolved_urls)

        unresolved_urls = [
            url for url in unique_requested_urls if url not in successful_rows
        ]
        payloads: List[bytes] = []
        errors: List[Optional[str]] = []
        transport_receipts: List[Optional[Dict[str, Any]]] = []
        parser_input_envelopes: List[Any] = []
        for official_url in requested_urls:
            row = successful_rows.get(official_url) or failed_rows.get(official_url)
            if row is None:
                raise RuntimeError(
                    "residual archival multi-fetch lost an aligned URL row: "
                    f"{official_url}"
                )
            payload, error, receipt, envelope = row
            payloads.append(payload)
            errors.append(error)
            transport_receipts.append(receipt)
            parser_input_envelopes.append(envelope)

        def _aggregate_attempt_counters(
            values: Sequence[Mapping[str, Any]],
            *,
            counter_keys: Sequence[str],
        ) -> Dict[str, Any]:
            """Sum counters while retaining metadata once, from first sight."""

            counters = set(counter_keys)
            aggregate: Dict[str, Any] = {}
            observed_counter_keys: set[str] = set()
            for value in values:
                for key, item in value.items():
                    if key not in counters:
                        # Configuration and transport descriptors such as
                        # max_slice_bytes or batch_transport_available are not
                        # additive.  Keep their first value; exact per-attempt
                        # values remain available in attempt_records below.
                        aggregate.setdefault(key, item)
                        continue
                    if isinstance(item, bool):
                        continue
                    try:
                        amount = int(item or 0)
                    except (TypeError, ValueError):
                        continue
                    aggregate[key] = int(aggregate.get(key, 0) or 0) + amount
                    observed_counter_keys.add(key)
            for key in counters - observed_counter_keys:
                aggregate.pop(key, None)
            return aggregate

        common_crawl_counter_keys = (
            "requested_pages",
            "valid_pointers",
            "invalid_pointers",
            "warc_objects",
            "requested_ranges",
            "unique_ranges",
            "duplicate_ranges",
            "range_fetch_calls",
            "naive_range_fetches",
            "range_fetches_avoided",
            "effective_range_fetches_avoided",
            "planned_range_fetches",
            "planned_range_fetches_avoided",
            "retry_range_fetches",
            "coalesced_gap_bytes",
            "requested_member_bytes",
            "successful_pages",
            "failed_pages",
        )
        common_crawl_attempt_stats = [
            dict(value.get("common_crawl", {}) or {}) for value in attempt_stats
        ]
        aggregate_common_crawl_stats = _aggregate_attempt_counters(
            common_crawl_attempt_stats,
            counter_keys=common_crawl_counter_keys,
        )

        inventory_memo_counter_keys = (
            "shared_domain_cache_hits",
            "shared_domain_cache_misses",
            "shared_domain_queries",
            "shared_domain_query_failures",
            "shared_domain_query_timeouts",
            "shared_domain_backoff_skips",
            "legacy_cache_hits",
            "legacy_queries",
            "legacy_query_failures",
            "legacy_backoff_skips",
        )
        inventory_attempt_memos = [
            dict(value.get("common_crawl_inventory_memo", {}) or {})
            for value in attempt_stats
        ]
        aggregate_inventory_memo = _aggregate_attempt_counters(
            inventory_attempt_memos,
            counter_keys=inventory_memo_counter_keys,
        )

        top_level_attempt_counter_keys = (
            "common_crawl_inventory_queries",
            "common_crawl_inventory_records",
            "common_crawl_matched_pointers",
            "common_crawl_pointer_candidates",
            "common_crawl_selected_pages",
            "network_requested_pages",
            "duplicate_page_requests_avoided",
            "direct_initial_requests",
            "direct_initial_successes",
            "result_callbacks_emitted",
            "fallback_requests",
            "eager_parser_inputs_admitted",
            "eager_parser_input_retention_failures",
            "parser_input_retention_failures",
            "retained_replay_pages",
            "retained_replay_unique_pages",
            "cross_instance_retained_replay_pages",
            "cross_instance_retained_replay_unique_pages",
        )
        aggregate_top_level_counters = _aggregate_attempt_counters(
            attempt_stats,
            counter_keys=top_level_attempt_counter_keys,
        )
        retry_records = attempt_records[1:]
        stats = dict(initial_stats)
        for key in top_level_attempt_counter_keys:
            if key in aggregate_top_level_counters:
                stats[key] = aggregate_top_level_counters[key]
        stats["common_crawl"] = aggregate_common_crawl_stats
        stats["common_crawl_inventory_memo"] = aggregate_inventory_memo
        logical_successful_pages = sum(
            error is None and bool(payload)
            for payload, error in zip(payloads, errors, strict=True)
        )
        logical_failed_pages = len(requested_urls) - logical_successful_pages
        stats.update(
            {
                "requested_pages": len(requested_urls),
                "unique_pages": len(unique_requested_urls),
                "successful_pages": logical_successful_pages,
                "failed_pages": logical_failed_pages,
                "parser_inputs_admitted": logical_successful_pages,
                "residual_retry_attempts_configured": retry_attempts,
                "residual_retry_rounds_executed": len(retry_records),
                "residual_retry_requested_pages": sum(
                    int(record["requested_pages"]) for record in retry_records
                ),
                "residual_retry_network_requested_pages": sum(
                    int(record["network_requested_pages"])
                    for record in retry_records
                ),
                "residual_retry_recovered_pages": len(
                    set(initial_unresolved_urls) - set(unresolved_urls)
                ),
                "residual_retry_unresolved_pages": len(unresolved_urls),
                "residual_retry_unresolved_urls": list(unresolved_urls),
                "residual_retry_attempt_batches": attempt_records,
            }
        )
        self._last_page_multifetch_stats = dict(stats)
        self._last_common_crawl_batch_stats = dict(aggregate_common_crawl_stats)
        return StateLawPageMultiFetchResult(
            urls=list(requested_urls),
            payloads=payloads,
            errors=errors,
            transport_receipts=transport_receipts,
            parser_input_envelopes=parser_input_envelopes,
            stats=stats,
        )

    async def _fetch_page_content_with_archival_fallback(
        self,
        url: str,
        timeout_seconds: int = 25,
        *,
        content_validator: Optional[Callable[[bytes], bool]] = None,
        enable_unified: bool = True,
    ) -> bytes:
        """Fetch bytes using the shared cache, direct, and archival chain.

        This keeps Common Crawl/Wayback/Archive.is logic inside state scrapers,
        mirroring Oregon archival workflow for all states.  A caller-supplied
        validator is applied to cached and newly fetched bytes before they are
        returned or cached, allowing the same path to safely retrieve PDFs and
        other non-HTML official documents.
        """
        fetch_url = self._canonical_fetch_url(url)
        if not fetch_url:
            return b""
        if not isinstance(enable_unified, bool):
            raise TypeError("enable_unified must be a boolean")
        self._last_page_fetch_transport_evidence = {}
        self._last_page_parser_input_envelope = None

        def _content_is_valid(payload: bytes) -> bool:
            if not payload:
                return False
            if content_validator is None:
                return True
            try:
                return bool(content_validator(payload))
            except Exception:
                return False

        # The singleton compatibility path historically checked only page
        # caches before touching the network.  Production acquisition uses a
        # stronger prospective ledger whose exact request/body/origin receipt
        # must win first, just as it does for the plural frontier path.  This
        # prevents restart discovery pages (for example part/chapter indexes)
        # from being requested again merely because their content-addressed
        # object is already retained outside the legacy cache.
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is not None:
            ledger.refresh_existing_entries()
            retained = ledger.replay_retained_parser_input(
                official_url=fetch_url,
                sanitized_request={"method": "GET", "url": fetch_url},
            )
            if retained is not None:
                retained_body = bytes(retained.envelope.body or b"")
                if _content_is_valid(retained_body):
                    self._last_page_fetch_transport_evidence = dict(
                        retained.transport_receipt
                    )
                    self._last_page_parser_input_envelope = retained.envelope
                    self._record_fetch_event(
                        provider="retained_acquisition_replay",
                        success=True,
                    )
                    return retained_body

                self._raise_if_retained_replay_only_network(
                    operation=(
                        "network fallback after retained parser input failed "
                        "the current validator"
                    ),
                    url=fetch_url,
                )

        self._raise_if_retained_replay_only_network(
            operation="direct/Common Crawl/Wayback/archive singleton fetch",
            url=fetch_url,
        )

        def _remember_transport(
            *,
            payload: bytes,
            source_transport: str,
            archive_url: str = "",
            archive_timestamp: str = "",
            fetched_at: str = "",
            extra: Optional[Dict[str, Any]] = None,
        ) -> None:
            evidence: Dict[str, Any] = {
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "official_url": fetch_url,
                "source_transport": str(source_transport or ""),
            }
            if archive_url:
                evidence["archive_url"] = str(archive_url)
            if archive_timestamp:
                evidence["archive_timestamp"] = str(archive_timestamp)
            if fetched_at:
                evidence["fetched_at"] = str(fetched_at)
            if isinstance(extra, dict):
                evidence.update(extra)
            self._last_page_fetch_transport_evidence = evidence

        original_timeout_seconds = timeout_seconds
        bounded_fetch_timeout = _env_float("STATE_SCRAPER_FETCH_TIMEOUT_SECONDS", 0.0)
        if bounded_fetch_timeout > 0:
            timeout_seconds = max(1, int(min(float(timeout_seconds), bounded_fetch_timeout)))

        async def _try_requests_direct() -> bytes:
            try:
                from urllib.request import Request, urlopen

                headers = {
                    "User-Agent": "ipfs-datasets-state-scraper/2.0",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                }

                def _blocking_fetch(candidate_url: str) -> tuple[int, bytes]:
                    request = Request(candidate_url, headers=headers)
                    with urlopen(request, timeout=max(1, int(timeout_seconds or 25))) as response:
                        status_code = int(getattr(response, "status", 200) or 200)
                        content = bytes(response.read() or b"")
                    return status_code, content

                for candidate_url in self._wayback_replay_candidates(fetch_url):
                    try:
                        status_code, content = await asyncio.wait_for(
                            asyncio.to_thread(_blocking_fetch, candidate_url),
                            timeout=max(2, int(timeout_seconds or 25) + 2),
                        )
                        if status_code != 200 or not _content_is_valid(content):
                            continue
                        _remember_transport(
                            payload=content,
                            source_transport="direct",
                        )
                        self._record_fetch_event(provider="requests_direct", success=True)
                        await self._cache_successful_page_fetch(
                            url=fetch_url,
                            payload=content,
                            provider="requests_direct",
                        )
                        return self._retain_page_bytes_before_parser(
                            url=fetch_url,
                            payload=content,
                        )
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        continue

                self._record_fetch_event(provider="requests_direct", success=False)
                return b""
            except Exception as exc:
                self._record_fetch_event(provider="requests_direct", success=False, error=str(exc))
                return b""

        cached_bytes = await self._load_page_bytes_from_any_cache(fetch_url)
        if cached_bytes and _content_is_valid(cached_bytes):
            try:
                return self._retain_page_bytes_before_parser(
                    url=fetch_url,
                    payload=cached_bytes,
                )
            except Exception as exc:
                if getattr(self, "_state_law_acquisition_ledger", None) is None:
                    raise
                # An old body without an origin receipt is not parser input.
                # Continue to a fresh official/archive acquisition instead of
                # upgrading a cache provider label into evidence.
                self._record_fetch_event(
                    provider="cache_provenance_rejected",
                    success=False,
                    error=str(exc),
                )
                self._last_page_fetch_transport_evidence = {}

        # Prefer the live official page before expensive rescue paths. The
        # archival/search chain is a recovery mechanism; letting it run before
        # a healthy official fetch makes full-corpus daemon sweeps look stalled
        # and can multiply RAM/network work across thousands of statute pages.
        direct_first = str(os.getenv("STATE_SCRAPER_DIRECT_FIRST", "1")).strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        if direct_first or bounded_fetch_timeout > 0:
            direct_bytes = await _try_requests_direct()
            if direct_bytes:
                return direct_bytes
            direct_only = str(os.getenv("STATE_SCRAPER_BOUNDED_DIRECT_ONLY", "")).strip().lower()
            if direct_only in {"1", "true", "yes", "on"}:
                return b""

        unified_enabled = str(
            os.getenv("STATE_SCRAPER_UNIFIED_FETCH_ENABLED", "1")
        ).strip().lower() not in {"0", "false", "no", "off"}
        # Very small hydration timeouts are usually smoke-test budgets. Avoid
        # non-cancellable background fetch workers in that mode.
        if original_timeout_seconds <= 5 and bounded_fetch_timeout <= 0:
            unified_enabled = False
        if unified_enabled and enable_unified:
            for candidate_url in self._wayback_replay_candidates(fetch_url):
                unified_bytes = await self._fetch_page_content_with_unified_api(
                    url=candidate_url,
                    timeout_seconds=timeout_seconds,
                )
                if self._is_object_moved_placeholder(unified_bytes):
                    unified_bytes = b""
                if _content_is_valid(unified_bytes):
                    _remember_transport(
                        payload=unified_bytes,
                        source_transport="unified_api",
                    )
                    await self._cache_successful_page_fetch(
                        url=fetch_url,
                        payload=unified_bytes,
                        provider="unified_api",
                    )
                    try:
                        return self._retain_page_bytes_before_parser(
                            url=fetch_url,
                            payload=unified_bytes,
                        )
                    except Exception as exc:
                        if getattr(self, "_state_law_acquisition_ledger", None) is None:
                            raise
                        # A provider-neutral label is observability, not an
                        # immutable archive/direct transport receipt.  Let the
                        # exact archival fallback attempt supply one.
                        self._record_fetch_event(
                            provider="unified_provenance_rejected",
                            success=False,
                            error=str(exc),
                        )
                        self._last_page_fetch_transport_evidence = {}

        archival_enabled = str(
            os.getenv("STATE_SCRAPER_ARCHIVAL_FETCH_ENABLED", "1")
        ).strip().lower() not in {"0", "false", "no", "off"}
        if original_timeout_seconds <= 5 and bounded_fetch_timeout <= 0:
            archival_enabled = False
        if archival_enabled:
            try:
                from .state_archival_fetch import ArchivalFetchClient

                client = ArchivalFetchClient(
                    request_timeout_seconds=timeout_seconds,
                    delay_seconds=0.0,
                    content_validator=_content_is_valid,
                    # The shared direct/cache stage above already attempted the
                    # exact locator.  Keep the archival client focused on the
                    # fallback transports and avoid a duplicate live request.
                    enable_direct=False,
                )
                fetched = await client.fetch_with_fallback(fetch_url)
                self._record_fetch_event(
                    provider=str(
                        getattr(fetched, "source", "archival_fallback") or "archival_fallback"
                    ),
                    success=bool(getattr(fetched, "content", b"")),
                )
                content = bytes(fetched.content or b"")
                if _content_is_valid(content):
                    await self._cache_successful_page_fetch(
                        url=fetch_url,
                        payload=content,
                        provider=str(
                            getattr(fetched, "source", "archival_fallback") or "archival_fallback"
                        ),
                    )
                    return self._retain_archival_fetch_result_before_parser(
                        official_url=fetch_url,
                        fetched=fetched,
                    )
            except Exception as exc:
                self._record_fetch_event(
                    provider="archival_fallback", success=False, error=str(exc)
                )
                pass

        return await _try_requests_direct()

    @staticmethod
    def _is_object_moved_placeholder(payload: bytes) -> bool:
        if not payload or len(payload) > 2048:
            return False
        try:
            text = payload.decode("utf-8", errors="replace")
        except Exception:
            return False
        return bool(_OBJECT_MOVED_HTML_RE.search(text))

    def _wayback_replay_candidates(self, url: str) -> List[str]:
        value = str(url or "").strip()
        if not value:
            return []

        out: List[str] = []

        def _add(candidate: str) -> None:
            c = str(candidate or "").strip()
            if c and c not in out:
                out.append(c)

        _add(value)

        if "web.archive.org/web/" in value:
            # Always include the canonical replay path first, even when the input
            # already contains `if_`/`id_` markers.
            canonical = re.sub(
                r"(web\.archive\.org/web/\d+)(?:if_|id_)/(https?://)",
                r"\1/\2",
                value,
                count=1,
                flags=re.IGNORECASE,
            )
            _add(canonical)
            _add(
                re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1if_/\2", canonical, count=1)
            )
            _add(
                re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1id_/\2", canonical, count=1)
            )

        # Try scheme-alternate variants last for flaky mirrors.
        seed = list(out)
        for candidate in seed:
            if candidate.startswith("https://"):
                _add("http://" + candidate[8:])
            elif candidate.startswith("http://"):
                _add("https://" + candidate[7:])

        return out

    async def _fetch_page_content_with_unified_api(
        self, url: str, timeout_seconds: int = 25
    ) -> bytes:
        self._raise_if_retained_replay_only_network(
            operation="unified web-archive network access",
            url=url,
        )
        try:
            from ....web_archiving.contracts import OperationMode, UnifiedFetchRequest
            from ....web_archiving.unified_api import UnifiedWebArchivingAPI
        except Exception:
            try:
                from ipfs_datasets_py.processors.web_archiving.contracts import (
                    OperationMode,
                    UnifiedFetchRequest,
                )
                from ipfs_datasets_py.processors.web_archiving.unified_api import (
                    UnifiedWebArchivingAPI,
                )
            except Exception:
                return b""

        try:
            api = UnifiedWebArchivingAPI()
            request = UnifiedFetchRequest(
                url=url,
                mode=OperationMode.MAX_QUALITY,
                timeout_seconds=max(1, int(timeout_seconds or 25)),
                domain="legal",
                metadata={"pipeline": "state_laws"},
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(api.fetch, request),
                timeout=max(1, int(timeout_seconds or 25)),
            )
        except asyncio.TimeoutError:
            self._record_fetch_event(
                provider="unified_api", success=False, error="unified_api_fetch_timeout"
            )
            return b""
        except Exception as exc:
            self._record_fetch_event(provider="unified_api", success=False, error=str(exc))
            return b""

        trace = getattr(response, "trace", None)
        provider = str(getattr(trace, "provider_selected", None) or "unified_api")
        if trace is not None:
            try:
                self._fetch_analytics["fallback_count"] = int(
                    self._fetch_analytics.get("fallback_count", 0) or 0
                ) + int(getattr(trace, "fallback_count", 0) or 0)
            except Exception:
                pass

        if not bool(getattr(response, "success", False)):
            message = None
            errors = getattr(response, "errors", []) or []
            if errors:
                message = str(getattr(errors[0], "message", "")) or "unified_api_fetch_failed"
            self._record_fetch_event(provider=provider, success=False, error=message)
            return b""

        document = getattr(response, "document", None)
        if document is None:
            self._record_fetch_event(provider=provider, success=False)
            return b""

        metadata = getattr(document, "metadata", {}) or {}
        raw_bytes = metadata.get("raw_bytes") if isinstance(metadata, dict) else None
        if isinstance(raw_bytes, bytes) and raw_bytes:
            self._record_fetch_event(provider=provider, success=True)
            return raw_bytes

        html = str(getattr(document, "html", "") or "")
        if html.strip():
            self._record_fetch_event(provider=provider, success=True)
            return html.encode("utf-8", errors="replace")

        text = str(getattr(document, "text", "") or "")
        if text.strip():
            self._record_fetch_event(provider=provider, success=True)
            return text.encode("utf-8", errors="replace")

        self._record_fetch_event(provider=provider, success=False)
        return b""

    def _record_fetch_event(
        self, *, provider: str, success: bool, error: Optional[str] = None
    ) -> None:
        self._last_fetch_provider = str(provider or "")
        try:
            _FETCH_PROVIDER.set(self._last_fetch_provider)
        except Exception:
            pass
        self._fetch_analytics["attempted"] = int(self._fetch_analytics.get("attempted", 0) or 0) + 1
        self._fetch_analytics["last_provider"] = self._last_fetch_provider
        if success:
            self._fetch_analytics["success"] = int(self._fetch_analytics.get("success", 0) or 0) + 1

        providers = self._fetch_analytics.get("providers")
        if not isinstance(providers, dict):
            providers = {}
            self._fetch_analytics["providers"] = providers
        providers[provider] = int(providers.get(provider, 0) or 0) + 1

        if error:
            self._fetch_analytics["last_error"] = str(error)

    def _current_fetch_provider(self) -> str:
        """Return the fetch provider for the current task, not a raced sibling."""

        try:
            value = str(_FETCH_PROVIDER.get() or "").strip()
        except Exception:
            value = ""
        return value or str(getattr(self, "_last_fetch_provider", "") or "")

    def get_fetch_analytics_snapshot(self) -> Dict[str, Any]:
        providers = self._fetch_analytics.get("providers")
        attempted = int(self._fetch_analytics.get("attempted", 0) or 0)
        success = int(self._fetch_analytics.get("success", 0) or 0)
        fallback_count = int(self._fetch_analytics.get("fallback_count", 0) or 0)
        cache_hits = int(self._fetch_analytics.get("cache_hits", 0) or 0)
        cache_writes = int(self._fetch_analytics.get("cache_writes", 0) or 0)
        fetch_cache_hits = int(self._fetch_analytics.get("fetch_cache_hits", 0) or 0)
        fetch_cache_writes = int(self._fetch_analytics.get("fetch_cache_writes", 0) or 0)
        return {
            "attempted": attempted,
            "success": success,
            "success_ratio": round((success / attempted), 3) if attempted > 0 else 0.0,
            "providers": dict(providers) if isinstance(providers, dict) else {},
            "fallback_count": fallback_count,
            "cache_hits": cache_hits,
            "cache_writes": cache_writes,
            "fetch_cache_hits": fetch_cache_hits,
            "fetch_cache_writes": fetch_cache_writes,
            "last_error": self._fetch_analytics.get("last_error"),
        }

    async def _hydrate_statute_text_if_needed(self, statute: NormalizedStatute) -> None:
        structured = statute.structured_data if isinstance(statute.structured_data, dict) else {}
        if bool(structured.get("skip_hydrate")):
            return

        source_url = self._canonicalize_statute_url(str(statute.source_url or "").strip())
        if source_url and source_url != str(statute.source_url or "").strip():
            statute.source_url = source_url
        if not source_url:
            return

        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"}:
            return

        base_text = str(statute.full_text or statute.summary or "")
        if not self._looks_like_shallow_stub_text(base_text):
            return

        hydrate_timeout = max(
            1, int(float(os.getenv("STATE_SCRAPER_HYDRATE_TIMEOUT_SECONDS", "25") or 25))
        )
        raw_bytes = await self._fetch_page_content_with_archival_fallback(
            source_url, timeout_seconds=hydrate_timeout
        )
        if not raw_bytes:
            return

        # For PDF/RTF statute URLs, route bytes through document processors first.
        document_extraction = await self._extract_text_from_document_bytes(
            source_url=source_url,
            raw_bytes=raw_bytes,
        )
        if isinstance(document_extraction, dict):
            fetched_text = self._normalize_legal_text(str(document_extraction.get("text") or ""))
            fetched_text = self._trim_to_section_context(fetched_text, statute)
            if len(fetched_text) >= 160:
                statute.full_text = fetched_text
                if not statute.section_name:
                    statute.section_name = fetched_text[:200]
                structured_update = (
                    statute.structured_data if isinstance(statute.structured_data, dict) else {}
                )
                structured_update = dict(structured_update)
                structured_update["method_used"] = str(
                    document_extraction.get("method") or "document_processor"
                )
                structured_update["source_content_type"] = str(
                    document_extraction.get("content_type") or ""
                )
                statute.structured_data = structured_update
                return

        try:
            html_text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            return

        fetched_text = self._extract_best_content_text(html_text)
        fetched_text = self._normalize_legal_text(fetched_text)
        fetched_text = self._trim_to_section_context(fetched_text, statute)
        if len(fetched_text) < 160:
            return

        # Avoid replacing stub text with navigation/event boilerplate content.
        if self._looks_like_navigation_text(fetched_text) and not self._contains_statute_signals(
            fetched_text
        ):
            return

        statute.full_text = fetched_text
        if not statute.section_name:
            statute.section_name = fetched_text[:200]

    async def _extract_text_from_document_bytes(
        self,
        *,
        source_url: str,
        raw_bytes: bytes,
    ) -> Optional[Dict[str, str]]:
        if not raw_bytes:
            return None

        lowered_url = str(source_url or "").strip().lower()
        byte_prefix = raw_bytes[:512]
        is_html_payload = bool(_HTML_DOC_HEADER_RE.search(byte_prefix))
        is_pdf_payload = bool(_PDF_HEADER_RE.search(byte_prefix))
        is_rtf_payload = bool(_RTF_HEADER_RE.search(byte_prefix))
        pdf_url_candidate = lowered_url.endswith(".pdf") or ".pdf?" in lowered_url
        rtf_url_candidate = lowered_url.endswith(".rtf") or ".rtf?" in lowered_url
        pdf_candidate = (
            (pdf_url_candidate or is_pdf_payload) and is_pdf_payload and not is_html_payload
        )
        rtf_candidate = (
            (rtf_url_candidate or is_rtf_payload) and is_rtf_payload and not is_html_payload
        )
        if not (pdf_candidate or rtf_candidate):
            if (pdf_url_candidate or rtf_url_candidate) and is_html_payload:
                self.logger.debug(
                    "Skipping document extraction for HTML payload served from document-looking URL: %s",
                    source_url,
                )
            return None

        if pdf_candidate:
            # Fast path for text-native PDFs so we can avoid expensive OCR/model bootstrap.
            try:
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(BytesIO(raw_bytes))
                pages = [str(page.extract_text() or "") for page in reader.pages]
                extracted = self._normalize_legal_text("\n".join(pages))
            except Exception:
                extracted = ""
            if extracted:
                return {
                    "text": extracted,
                    "method": "pypdf_fast_path",
                    "content_type": "application/pdf",
                }

            try:
                from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
                    UnifiedWebScraper,
                )
            except Exception:
                return None

            try:
                extracted = await UnifiedWebScraper._extract_pdf_text(raw_bytes)
            except Exception:
                extracted = ""
            extracted = str(extracted or "").strip()
            if extracted:
                return {
                    "text": extracted,
                    "method": "pdf_processor",
                    "content_type": "application/pdf",
                }

        if rtf_candidate:
            try:
                from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
                    UnifiedWebScraper,
                )
            except Exception:
                return None

            try:
                extracted = await UnifiedWebScraper._extract_rtf_text(raw_bytes)
            except Exception:
                extracted = ""
            extracted = str(extracted or "").strip()
            if extracted:
                return {
                    "text": extracted,
                    "method": "rtf_processor",
                    "content_type": "application/rtf",
                }

        return None

    def _normalize_legal_text(self, text: str) -> str:
        """Normalize whitespace and punctuation for legal-text parsing."""
        value = str(text or "")
        value = value.replace("\u00a0", " ")
        value = value.replace("\ufeff", "")
        value = value.replace("\u2019", "'")
        value = value.replace("\u201c", '"').replace("\u201d", '"')
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _dedupe_keep_order(self, items: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for item in items:
            value = self._normalize_legal_text(item)
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(value)
        return out

    def _classify_subsec_kind(self, token: str, prev_kind: Optional[str]) -> str:
        if token.isdigit():
            return "numeric"

        if token.islower():
            if token in COMMON_ROMAN_LOWER and prev_kind in {
                "alpha_upper",
                "roman_lower",
                "roman_upper",
            }:
                return "roman_lower"
            if len(token) > 1 and ROMAN_LOWER_RE.match(token):
                return "roman_lower"
            return "alpha_lower"

        if token.isupper():
            if token in COMMON_ROMAN_UPPER and prev_kind in {"roman_lower", "roman_upper"}:
                return "roman_upper"
            if len(token) > 1 and ROMAN_UPPER_RE.match(token):
                return "roman_upper"
            return "alpha_upper"

        return "other"

    def _subsec_level(self, kind: str) -> int:
        order = {
            "numeric": 1,
            "alpha_lower": 2,
            "alpha_upper": 3,
            "roman_lower": 4,
            "roman_upper": 5,
            "other": 6,
        }
        return int(order.get(kind, 6))

    def _find_subsec_markers(self, text: str) -> List[tuple[int, int, str]]:
        markers: List[tuple[int, int, str]] = []
        for match in SUBSEC_TOKEN_RE.finditer(text):
            start = int(match.start())
            end = int(match.end())
            token = str(match.group(1))

            if len(token) > 6:
                continue
            if token.isdigit() and len(token) > 3:
                continue
            if token.isalpha():
                if not (token.islower() or token.isupper()):
                    continue
                if len(token) > 1:
                    if token.islower() and not ROMAN_LOWER_RE.match(token):
                        continue
                    if token.isupper() and not ROMAN_UPPER_RE.match(token):
                        continue

            prev_ch = text[start - 1] if start > 0 else ""
            next_ch = text[end] if end < len(text) else ""

            valid_left = (start == 0) or prev_ch.isspace() or prev_ch in ";:.(["
            valid_right = (end == len(text)) or next_ch.isspace() or next_ch in "(),;:.]"
            if not (valid_left and valid_right):
                continue

            markers.append((start, end, token))
        return markers

    def _parse_subsections(self, text: str) -> List[Dict[str, Any]]:
        normalized = self._normalize_legal_text(text)
        markers = self._find_subsec_markers(normalized)
        if not markers:
            return []

        items: List[Dict[str, Any]] = []
        prev_kind: Optional[str] = None
        for idx, (start, end, token) in enumerate(markers):
            next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(normalized)
            body = self._normalize_legal_text(normalized[end:next_start])
            kind = self._classify_subsec_kind(token, prev_kind)
            prev_kind = kind
            items.append(
                {
                    "label": f"({token})",
                    "token": token,
                    "kind": kind,
                    "level": self._subsec_level(kind),
                    "text": body,
                    "subsections": [],
                }
            )

        roots: List[Dict[str, Any]] = []
        stack: List[Dict[str, Any]] = []

        for item in items:
            level = int(item["level"])
            while stack and int(stack[-1]["level"]) >= level:
                stack.pop()

            parent_subsections = roots if not stack else stack[-1]["subsections"]

            existing_node: Optional[Dict[str, Any]] = None
            for sibling in reversed(parent_subsections):
                if sibling.get("label") == item["label"]:
                    existing_node = sibling
                    break

            if existing_node is None:
                node = {
                    "label": item["label"],
                    "token": item["token"],
                    "kind": item["kind"],
                    "text": item["text"],
                    "subsections": [],
                }
                parent_subsections.append(node)
            else:
                node = existing_node
                new_text = self._normalize_legal_text(str(item.get("text") or ""))
                old_text = self._normalize_legal_text(str(node.get("text") or ""))
                if new_text:
                    if not old_text:
                        node["text"] = new_text
                    elif new_text not in old_text:
                        node["text"] = f"{old_text} {new_text}".strip()

            stack.append({"level": level, "subsections": node["subsections"]})

        return roots

    def _fallback_subsections_from_text(
        self, text: str, *, max_nodes: int = 8
    ) -> List[Dict[str, Any]]:
        """Build coarse subsection nodes when marker parsing yields nothing.

        Some state sources flatten formatting and omit explicit `(a)`/`(1)` labels.
        This fallback preserves useful structure by chunking long clause-like text.
        """
        normalized = self._normalize_legal_text(text)
        if len(normalized) < 120:
            return []

        # Prefer semicolon-delimited legal clauses.
        clauses = [self._normalize_legal_text(part) for part in re.split(r";\s+", normalized)]
        clauses = [part for part in clauses if len(part) >= 40]

        # If semicolon clauses are sparse, split on sentence boundaries.
        if len(clauses) < 2:
            clauses = [
                self._normalize_legal_text(part)
                for part in re.split(r"(?<=[\.!?])\s+(?=[A-Z0-9])", normalized)
            ]
            clauses = [part for part in clauses if len(part) >= 60]

        if not clauses:
            # Last resort: represent long narrative text as a single subsection.
            return [
                {
                    "label": "(1)",
                    "token": "1",
                    "kind": "numeric",
                    "text": normalized,
                    "subsections": [],
                }
            ]

        nodes: List[Dict[str, Any]] = []
        for index, clause in enumerate(clauses[:max_nodes], start=1):
            nodes.append(
                {
                    "label": f"({index})",
                    "token": str(index),
                    "kind": "numeric",
                    "text": clause,
                    "subsections": [],
                }
            )
        return nodes

    def _extract_preamble(self, text: str, max_chars: int = 500) -> str:
        source = self._normalize_legal_text(text)
        if not source:
            return ""

        markers = self._find_subsec_markers(source)
        if markers and markers[0][0] > 0:
            return self._normalize_legal_text(source[: markers[0][0]])[:max_chars]

        sentence_match = re.match(rf"(.{{1,{int(max_chars)}}}?[\.;:])(\s|$)", source)
        if sentence_match:
            return self._normalize_legal_text(sentence_match.group(1))

        return self._normalize_legal_text(source[:max_chars])

    def _extract_citations_from_text(
        self,
        full_text: str,
        core_text: str = "",
        extra_patterns: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, List[str]]:
        base = str(full_text or "")
        core = str(core_text or "") or base

        citations: Dict[str, List[str]] = {
            "usc_citations": self._dedupe_keep_order(USC_CITATION_RE.findall(core)),
            "public_laws": self._dedupe_keep_order(PUBLIC_LAW_CITATION_RE.findall(base)),
            "statutes_at_large": self._dedupe_keep_order(STAT_CITATION_RE.findall(base)),
            "section_references": self._dedupe_keep_order(SECTION_REF_RE.findall(core)),
        }

        for key, pattern in (extra_patterns or {}).items():
            try:
                if hasattr(pattern, "findall"):
                    matches = pattern.findall(core)
                else:
                    matches = re.findall(str(pattern), core, flags=re.IGNORECASE)
            except Exception:
                matches = []
            citations[str(key)] = self._dedupe_keep_order([str(item) for item in matches])

        return citations

    def _validate_subsection_tree(
        self, nodes: List[Dict[str, Any]], *, max_depth: int = 6
    ) -> List[str]:
        issues: List[str] = []

        def walk(siblings: List[Dict[str, Any]], depth: int, path: str) -> None:
            if depth > max_depth:
                issues.append(f"depth>{max_depth} at {path or 'root'}")

            seen_labels: Dict[str, int] = {}
            for index, node in enumerate(siblings, start=1):
                label = str(node.get("label", ""))
                kind = str(node.get("kind", ""))
                text = self._normalize_legal_text(str(node.get("text", "")))
                children = node.get("subsections", [])

                if label:
                    seen_labels[label] = seen_labels.get(label, 0) + 1
                    if seen_labels[label] > 1:
                        issues.append(f"duplicate sibling label {label} at {path or 'root'}")

                if not text and not children:
                    issues.append(
                        f"empty leaf node {label or '#' + str(index)} at {path or 'root'}"
                    )

                if kind not in {
                    "numeric",
                    "alpha_lower",
                    "alpha_upper",
                    "roman_lower",
                    "roman_upper",
                    "other",
                }:
                    issues.append(f"unknown kind {kind} for {label or '#' + str(index)}")

                child_path = f"{path}/{label}" if path else label
                if isinstance(children, list) and children:
                    walk(children, depth + 1, child_path)

        walk(nodes, depth=1, path="")
        return sorted(set(issues))

    def _build_state_jsonld(
        self,
        statute: NormalizedStatute,
        *,
        text: str,
        preamble: str,
        citations: Dict[str, Any],
        legislative_history: Dict[str, Any],
        subsections: List[Dict[str, Any]],
        parser_warnings: List[str],
    ) -> Dict[str, Any]:
        title_number = str(statute.title_number or "")
        chapter_number = str(statute.chapter_number or "")
        section_number = str(statute.section_number or "")
        year_value = getattr(statute.metadata, "enacted_year", None) if statute.metadata else None
        chapter_obj = {
            "chapter_label": statute.chapter_number
            or statute.title_number
            or statute.code_name
            or "",
            "chapter_name": statute.chapter_name or statute.title_name or statute.code_name or "",
            "chapter_inferred": True,
        }

        return {
            "@context": {
                "@vocab": "https://schema.org/",
                "state": f"https://www.usa.gov/states/{self.state_code.lower()}",
                "stateCode": "state:code",
                "sectionNumber": "state:sectionNumber",
                "sourceUrl": "state:sourceUrl",
            },
            "@type": "Legislation",
            "@id": f"urn:state:{self.state_code.lower()}:statute:{statute.statute_id}",
            "name": statute.section_name or statute.short_title or statute.statute_id,
            "isPartOf": {
                "@type": "CreativeWork",
                "name": statute.code_name or f"{self.state_name} Statutes",
                "identifier": f"{self.state_code}-{title_number or chapter_number or 'code'}",
            },
            "legislationType": "statute",
            "stateCode": self.state_code,
            "stateName": self.state_name,
            "titleNumber": title_number or None,
            "titleName": statute.title_name,
            "chapterNumber": chapter_number or None,
            "chapterName": statute.chapter_name,
            "sectionNumber": section_number or None,
            "sectionName": statute.section_name,
            "dateModified": str(year_value) if year_value is not None else None,
            "sourceUrl": statute.source_url,
            "chapter": chapter_obj,
            "preamble": preamble,
            "citations": citations,
            "legislativeHistory": legislative_history,
            "text": text,
            "subsections": subsections,
            "parser_warnings": parser_warnings,
        }

    def _enrich_statute_structure(self, statute: NormalizedStatute) -> NormalizedStatute:
        """Attach US Code-style structured parsing and JSON-LD to a statute."""
        if not isinstance(statute, NormalizedStatute):
            return statute

        source_text = str(statute.full_text or statute.summary or statute.short_title or "")
        existing = dict(statute.structured_data or {})
        if not source_text and existing:
            return statute

        legislative_history = existing.get("legislative_history")
        if not isinstance(legislative_history, dict):
            legislative_history = self._extract_legislative_history(source_text)

        cleaned_text = self._normalize_legal_text(
            str(legislative_history.get("cleaned_text") or source_text)
        )
        preamble = existing.get("preamble")
        if not isinstance(preamble, str):
            preamble = self._extract_preamble(cleaned_text)

        subsections = existing.get("subsections")
        if not isinstance(subsections, list):
            subsections = self._parse_subsections(cleaned_text)
        if isinstance(subsections, list) and not subsections:
            subsections = self._fallback_subsections_from_text(cleaned_text)

        parser_warnings = existing.get("parser_warnings")
        if not isinstance(parser_warnings, list):
            parser_warnings = self._validate_subsection_tree(subsections)

        citations = existing.get("citations")
        if not isinstance(citations, dict):
            citations = self._extract_citations_from_text(source_text, cleaned_text)

        jsonld_payload = existing.get("jsonld")
        if not isinstance(jsonld_payload, dict):
            jsonld_payload = self._build_state_jsonld(
                statute,
                text=cleaned_text,
                preamble=str(preamble or ""),
                citations=citations,
                legislative_history=legislative_history,
                subsections=subsections,
                parser_warnings=parser_warnings,
            )

        statute.structured_data = {
            **existing,
            "preamble": preamble,
            "citations": citations,
            "legislative_history": legislative_history,
            "subsections": subsections,
            "parser_warnings": parser_warnings,
            "jsonld": jsonld_payload,
        }
        return statute

    async def _generic_scrape(
        self, code_name: str, code_url: str, citation_format: str, max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Generic scraper implementation that can be used by most states.

        This method provides a common scraping pattern that works for many
        state legislative websites. Individual scrapers can override scrape_code()
        for more sophisticated parsing.

        Args:
            code_name: Name of the code (e.g., "Penal Code")
            code_url: URL to scrape
            citation_format: Citation format (e.g., "Cal. Penal Code")
            max_sections: Maximum number of sections to scrape

        Returns:
            List of NormalizedStatute objects
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        bounded_max_sections = _env_int("STATE_SCRAPER_MAX_STATUTES", 0)
        if bounded_max_sections > 0:
            scan_limit = max(
                bounded_max_sections,
                min(int(max_sections or bounded_max_sections), bounded_max_sections * 10),
            )
            max_sections = max(1, scan_limit)
        elif self._full_corpus_enabled():
            max_sections = None
        full_corpus_mode = self._full_corpus_enabled() and max_sections is None
        progress_log_every = max(10, _env_int("STATE_SCRAPER_PROGRESS_LOG_EVERY", 25))
        statutes: List[NormalizedStatute] = []
        seen_source_urls = set()
        legal_area = self._identify_legal_area(code_name)

        if full_corpus_mode:
            resumed_statutes = self._load_partial_checkpoint_statutes(
                code_name=code_name,
                max_statutes=None,
            )
            for resumed in resumed_statutes:
                if max_sections is not None and len(statutes) >= max_sections:
                    break
                resumed_url = self._canonicalize_statute_url(str(resumed.source_url or "").strip())
                if resumed_url and resumed_url in seen_source_urls:
                    continue
                if resumed_url:
                    resumed.source_url = resumed_url
                    seen_source_urls.add(resumed_url)
                statutes.append(resumed)
            if statutes:
                self.logger.info(
                    "%s generic scrape resume: statutes_so_far=%s",
                    self.state_code,
                    len(statutes),
                )

        def _extract_statutes_from_soup(soup, page_url: str, *, pages_scanned: int) -> int:
            """Extract probable statute anchors from one page soup into `statutes`."""
            section_links = soup.find_all("a", href=True)
            section_count = 0

            for link in section_links:
                if max_sections is not None and len(statutes) >= max_sections:
                    break

                link_text = link.get_text(strip=True)
                link_url = link.get("href", "")

                if not link_text or len(link_text) < 3:
                    continue

                if not link_url.startswith("http"):
                    from urllib.parse import urljoin

                    link_url = urljoin(page_url, link_url)
                if not link_url.startswith("http"):
                    continue

                link_url = self._canonicalize_statute_url(link_url)

                if not self._is_probable_statute_link(link_text, link_url, page_url):
                    continue

                if link_url in seen_source_urls:
                    continue

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = self._derive_section_number_from_url(link_url)
                if not section_number:
                    section_number = f"Section-{len(statutes) + 1}"

                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=link_text[:200],
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=link_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                )

                statutes.append(statute)
                seen_source_urls.add(link_url)
                section_count += 1
                if len(statutes) == 1 or len(statutes) % progress_log_every == 0:
                    self.logger.info(
                        "Generic scrape progress: state=%s code=%s statutes_so_far=%s pages_scanned=%s source_url=%s",
                        self.state_code,
                        code_name,
                        len(statutes),
                        pages_scanned,
                        page_url,
                    )

            return section_count

        def _collect_discovery_urls_from_soup(
            soup: Any,
            page_url: str,
            *,
            max_urls: int,
        ) -> List[str]:
            discovery_urls: List[str] = []
            discovery_keywords = (
                "statute",
                "statutes",
                "code",
                "codes",
                "law",
                "laws",
                "title",
                "chapter",
                "article",
                "revised",
                "consolidated",
                "constitution",
            )
            page_parsed = urlparse(str(page_url or ""))
            page_host = str(page_parsed.netloc or "").lower()
            discovery_seen = set()
            for link in soup.find_all("a", href=True):
                if len(discovery_urls) >= max(1, int(max_urls)):
                    break
                link_text = (link.get_text(" ", strip=True) or "").lower()
                href = str(link.get("href", "") or "")
                href_l = href.lower()
                if not any(k in link_text or k in href_l for k in discovery_keywords):
                    continue
                abs_url = self._canonicalize_statute_url(urljoin(page_url, href))
                if not abs_url.startswith("http"):
                    continue
                parsed = urlparse(abs_url)
                host = str(parsed.netloc or "").lower()
                same_host = bool(host and page_host and host == page_host)
                wayback_pair = "web.archive.org" in {host, page_host}
                if not same_host and not wayback_pair:
                    continue
                if abs_url in discovery_seen:
                    continue
                discovery_seen.add(abs_url)
                discovery_urls.append(abs_url)
            return discovery_urls

        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url, timeout_seconds=45
            )
            if not page_bytes:
                raise RuntimeError(f"Failed to retrieve code page: {code_url}")

            soup = BeautifulSoup(page_bytes, "html.parser")
            pages_scanned = 1
            visited_pages = {self._canonicalize_statute_url(code_url)}
            section_count = _extract_statutes_from_soup(
                soup,
                code_url,
                pages_scanned=pages_scanned,
            )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="generic:landing",
                extra={
                    "pages_scanned": pages_scanned,
                    "sections_extracted": int(section_count),
                    "source_url": code_url,
                },
            )

            enable_discovery = full_corpus_mode or len(statutes) < min(10, max_sections or 10)
            if enable_discovery:
                discovery_depth = max(
                    1,
                    _env_int(
                        "STATE_SCRAPER_GENERIC_DISCOVERY_DEPTH",
                        2 if full_corpus_mode else 1,
                    ),
                )
                fanout_limit = max(
                    4,
                    _env_int(
                        "STATE_SCRAPER_GENERIC_DISCOVERY_FANOUT",
                        24 if full_corpus_mode else 8,
                    ),
                )
                page_budget = max(
                    1,
                    _env_int(
                        "STATE_SCRAPER_GENERIC_MAX_PAGES",
                        240 if full_corpus_mode else 12,
                    ),
                )
                discovery_queue: List[tuple[str, int]] = [
                    (url, 1)
                    for url in _collect_discovery_urls_from_soup(
                        soup,
                        code_url,
                        max_urls=fanout_limit,
                    )
                ]
                queued_urls = {url for url, _ in discovery_queue}
                queue_index = 0
                frontier_batch_size = max(
                    2,
                    _env_int(
                        "STATE_SCRAPER_GENERIC_FRONTIER_BATCH_SIZE",
                        min(8, fanout_limit),
                    ),
                )
                while queue_index < len(discovery_queue):
                    if max_sections is not None and len(statutes) >= max_sections:
                        break
                    if pages_scanned >= page_budget:
                        break

                    frontier: List[tuple[str, int]] = []
                    remaining_page_budget = max(0, page_budget - pages_scanned)
                    frontier_limit = min(
                        frontier_batch_size,
                        remaining_page_budget,
                    )
                    while (
                        queue_index < len(discovery_queue)
                        and len(frontier) < frontier_limit
                    ):
                        discovery_url, depth = discovery_queue[queue_index]
                        queue_index += 1
                        canonical_discovery_url = self._canonicalize_statute_url(
                            discovery_url
                        )
                        if canonical_discovery_url in visited_pages:
                            continue
                        visited_pages.add(canonical_discovery_url)
                        frontier.append((canonical_discovery_url, depth))
                    if not frontier:
                        continue

                    if len(frontier) == 1:
                        try:
                            frontier_payloads = [
                                await self._fetch_page_content_with_archival_fallback(
                                    frontier[0][0],
                                    timeout_seconds=35,
                                )
                            ]
                        except Exception:
                            frontier_payloads = [b""]
                    else:
                        try:
                            frontier_result = (
                                await self._fetch_page_contents_with_archival_fallback(
                                    [url for url, _depth in frontier],
                                    timeout_seconds=35,
                                    media_type="text/html",
                                    max_concurrency=min(8, len(frontier)),
                                )
                            )
                            frontier_payloads = list(frontier_result.payloads)
                        except Exception as exc:
                            self.logger.warning(
                                "Generic discovery frontier batch failed for %s: %s",
                                self.state_code,
                                exc,
                            )
                            frontier_payloads = []
                            for discovery_url, _depth in frontier:
                                try:
                                    frontier_payloads.append(
                                        await self._fetch_page_content_with_archival_fallback(
                                            discovery_url,
                                            timeout_seconds=35,
                                        )
                                    )
                                except Exception:
                                    frontier_payloads.append(b"")

                    for (
                        canonical_discovery_url,
                        depth,
                    ), discovery_bytes in zip(frontier, frontier_payloads):
                        if max_sections is not None and len(statutes) >= max_sections:
                            break
                        if not discovery_bytes:
                            continue
                        try:
                            discovery_soup = BeautifulSoup(
                                discovery_bytes,
                                "html.parser",
                            )
                            pages_scanned += 1
                            extracted = _extract_statutes_from_soup(
                                discovery_soup,
                                canonical_discovery_url,
                                pages_scanned=pages_scanned,
                            )
                            section_count += extracted
                            self._write_partial_checkpoint(
                                statutes,
                                code_name=code_name,
                                stage_label=f"generic:depth{depth}",
                                extra={
                                    "pages_scanned": pages_scanned,
                                    "sections_extracted": int(section_count),
                                    "source_url": canonical_discovery_url,
                                    "discovery_depth": depth,
                                    "queue_size": len(discovery_queue),
                                },
                            )
                            if depth >= discovery_depth:
                                continue
                            for child_url in _collect_discovery_urls_from_soup(
                                discovery_soup,
                                canonical_discovery_url,
                                max_urls=fanout_limit,
                            ):
                                if (
                                    child_url in visited_pages
                                    or child_url in queued_urls
                                ):
                                    continue
                                discovery_queue.append((child_url, depth + 1))
                                queued_urls.add(child_url)
                        except Exception:
                            continue

            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="generic:complete",
                force=True,
                extra={
                    "pages_scanned": pages_scanned,
                    "sections_extracted": int(section_count),
                    "source_url": code_url,
                },
            )
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")

        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")

        return statutes

    def has_playwright(self) -> bool:
        """Check if Playwright is available."""
        try:
            from playwright.async_api import async_playwright as _async_playwright

            return callable(_async_playwright)
        except ImportError:
            return False

    async def _fetch_browser_parser_input_with_transport(
        self,
        url: str,
        *,
        wait_for_selector: str = "a",
        timeout_ms: int = 60000,
        wait_until: str = "networkidle",
        allowed_final_hosts: Optional[Sequence[str]] = None,
        provider: str = "browser_rendered_direct",
        pagination: Optional[Mapping[str, Any]] = None,
    ) -> bytes:
        """Render one official page and admit the serialized DOM before parsing."""

        self._raise_if_retained_replay_only_network(
            operation="browser network access",
            url=url,
        )

        official_url = self._canonical_fetch_url(url)
        parsed_official = urlparse(official_url)
        if (
            parsed_official.scheme.lower() not in {"http", "https"}
            or not parsed_official.hostname
            or parsed_official.username is not None
            or parsed_official.password is not None
        ):
            return b""
        allowed_hosts = {
            str(host or "").strip().lower().rstrip(".")
            for host in (allowed_final_hosts or [parsed_official.hostname])
            if str(host or "").strip()
        }
        if not allowed_hosts:
            return b""

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return b""

        bounded_timeout = max(1000, int(timeout_ms or 60000))
        browser = None
        page = None
        try:
            async with acquire_playwright_slot():
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(headless=True)
                    page = await browser.new_page()
                    navigation = await page.goto(
                        official_url,
                        wait_until=str(wait_until or "networkidle"),
                        timeout=bounded_timeout,
                    )
                    try:
                        await page.wait_for_selector(
                            str(wait_for_selector or "a"),
                            timeout=bounded_timeout,
                        )
                    except Exception:
                        self.logger.warning(
                            "Timeout waiting for selector %r on %s",
                            wait_for_selector,
                            official_url,
                        )

                    final_url = self._canonical_fetch_url(str(page.url or official_url))
                    parsed_final = urlparse(final_url)
                    try:
                        final_port = parsed_final.port
                    except ValueError:
                        final_port = -1
                    if (
                        parsed_final.scheme.lower() not in {"http", "https"}
                        or (parsed_final.hostname or "").lower().rstrip(".")
                        not in allowed_hosts
                        or parsed_final.username is not None
                        or parsed_final.password is not None
                        or final_port not in {None, 80, 443}
                    ):
                        raise RuntimeError(
                            "browser navigation left the cataloged official host"
                        )
                    status = int(getattr(navigation, "status", 0) or 0)
                    if status != 200:
                        raise RuntimeError(
                            f"browser navigation returned HTTP {status or 'unknown'}"
                        )
                    payload = str(await page.content() or "").encode("utf-8")
                    if not payload:
                        return b""

                    from ...legal_data.state_laws_source_provenance import (
                        canonicalize_state_law_transport_receipt,
                    )

                    digest = hashlib.sha256(payload).hexdigest()
                    self._last_page_fetch_transport_evidence = (
                        canonicalize_state_law_transport_receipt(
                            {
                                "content_sha256": digest,
                                "official_url": official_url,
                                "source_transport": "browser_rendered",
                            },
                            official_url=official_url,
                            content_sha256=digest,
                        )
                    )
                    admitted = self._retain_page_bytes_before_parser(
                        url=official_url,
                        payload=payload,
                        response_status=status,
                        media_type="text/html",
                        sanitized_request={
                            "method": "GET",
                            "url": official_url,
                            "browser_final_url": final_url,
                            "rendered_by": "playwright",
                            "wait_until": str(wait_until or "networkidle"),
                        },
                        pagination=pagination,
                        network_used=True,
                    )
                    self._record_fetch_event(provider=provider, success=True)
                    return admitted
        except Exception as exc:
            self._record_fetch_event(provider=provider, success=False, error=str(exc))
            self.logger.debug("Browser parser-input fetch failed for %s: %s", official_url, exc)
            return b""
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _playwright_scrape(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100,
        wait_for_selector: str = "a",
        timeout: int = 30000,
        wait_until: str = "networkidle",
    ) -> List[NormalizedStatute]:
        """Scrape using Playwright for JavaScript-rendered content.

        This method uses Playwright to render JavaScript content before scraping.
        It's useful for states with dynamic/modern web interfaces.

        Args:
            code_name: Name of the code being scraped
            code_url: URL of the code index page
            citation_format: Format string for citations
            max_sections: Maximum number of sections to scrape
            wait_for_selector: CSS selector to wait for before scraping
            timeout: Timeout in milliseconds (default: 30000)
            wait_until: Playwright navigation completion mode (e.g.,
                "networkidle", "domcontentloaded", "load")

        Returns:
            List of NormalizedStatute objects
        """
        self._raise_if_retained_replay_only_network(
            operation="Playwright network access",
            url=code_url,
        )
        from urllib.parse import urljoin

        bounded_max_sections = _env_int("STATE_SCRAPER_MAX_STATUTES", 0)
        if bounded_max_sections > 0:
            scan_limit = max(
                bounded_max_sections,
                min(int(max_sections or bounded_max_sections), bounded_max_sections * 10),
            )
            max_sections = max(1, scan_limit)
        elif self._full_corpus_enabled():
            max_sections = None

        if not self.has_playwright():
            self.logger.warning(
                f"Playwright not available, falling back to generic scrape for {code_name}"
            )
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)

        try:
            from playwright.async_api import async_playwright
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)

        full_corpus_mode = self._full_corpus_enabled() and max_sections is None
        progress_log_every = max(10, _env_int("STATE_SCRAPER_PROGRESS_LOG_EVERY", 25))
        statutes: List[NormalizedStatute] = []
        seen_source_urls = set()
        if full_corpus_mode:
            resumed_statutes = self._load_partial_checkpoint_statutes(
                code_name=code_name,
                max_statutes=None,
            )
            for resumed in resumed_statutes:
                if max_sections is not None and len(statutes) >= max_sections:
                    break
                resumed_url = self._canonicalize_statute_url(str(resumed.source_url or "").strip())
                if resumed_url and resumed_url in seen_source_urls:
                    continue
                if resumed_url:
                    resumed.source_url = resumed_url
                    seen_source_urls.add(resumed_url)
                statutes.append(resumed)
            if statutes:
                self.logger.info(
                    "%s playwright scrape resume: statutes_so_far=%s",
                    self.state_code,
                    len(statutes),
                )

        try:
            async with acquire_playwright_slot():
                async with async_playwright() as p:
                    # Launch browser
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()

                    try:
                        # Navigate to page
                        await page.goto(code_url, wait_until=wait_until, timeout=timeout)

                        # Wait for specific content
                        try:
                            await page.wait_for_selector(wait_for_selector, timeout=timeout)
                        except Exception:
                            self.logger.warning(
                                f"Timeout waiting for selector '{wait_for_selector}' on {code_url}"
                            )

                        # Get page content after JavaScript execution
                        content = await page.content()

                        # Parse with BeautifulSoup
                        soup = BeautifulSoup(content, "html.parser")

                        # Extract legal area
                        legal_area = self._identify_legal_area(code_name)

                        # Scan all anchors, then stop once enough probable statute links are collected.
                        section_links = soup.find_all("a", href=True)

                        section_count = 0
                        for link in section_links:
                            if max_sections is not None and section_count >= max_sections:
                                break

                            link_text = link.get_text(strip=True)
                            link_url = link.get("href", "")

                            # Skip if link doesn't look useful
                            if not link_text or len(link_text) < 3:
                                continue

                            # Make URL absolute (handles '/x' and 'x/y').
                            if not link_url.startswith("http"):
                                link_url = urljoin(code_url, link_url)
                            if not link_url.startswith("http"):
                                continue

                            link_url = self._canonicalize_statute_url(link_url)
                            if link_url in seen_source_urls:
                                continue

                            if not self._is_probable_statute_link(link_text, link_url, code_url):
                                continue

                            # Extract section number
                            section_number = self._extract_section_number(link_text)
                            if not section_number:
                                section_number = self._derive_section_number_from_url(link_url)
                            if not section_number:
                                section_number = f"Section-{section_count + 1}"

                            # Create normalized statute
                            statute = NormalizedStatute(
                                state_code=self.state_code,
                                state_name=self.state_name,
                                statute_id=f"{code_name} § {section_number}",
                                code_name=code_name,
                                section_number=section_number,
                                section_name=link_text[:200],
                                full_text=f"Section {section_number}: {link_text}",
                                legal_area=legal_area,
                                source_url=link_url,
                                official_cite=f"{citation_format} § {section_number}",
                                metadata=StatuteMetadata(),
                            )

                            statutes.append(statute)
                            seen_source_urls.add(link_url)
                            section_count += 1
                            if len(statutes) == 1 or len(statutes) % progress_log_every == 0:
                                self.logger.info(
                                    "Playwright scrape progress: state=%s code=%s statutes_so_far=%s source_url=%s",
                                    self.state_code,
                                    code_name,
                                    len(statutes),
                                    code_url,
                                )
                                self._write_partial_checkpoint(
                                    statutes,
                                    code_name=code_name,
                                    stage_label="playwright:progress",
                                    extra={
                                        "source_url": code_url,
                                        "sections_extracted": section_count,
                                    },
                                )

                        self._write_partial_checkpoint(
                            statutes,
                            code_name=code_name,
                            stage_label="playwright:complete",
                            force=True,
                            extra={"source_url": code_url, "sections_extracted": section_count},
                        )

                        self.logger.info(
                            f"Scraped {len(statutes)} sections using Playwright from {code_name}"
                        )

                    finally:
                        try:
                            await page.close()
                        finally:
                            await browser.close()

        except Exception as e:
            self.logger.error(f"Error in Playwright scrape for {code_name}: {str(e)}")
            # Try fallback to generic scrape
            self.logger.info(f"Falling back to generic scrape for {code_name}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)

        return statutes

    # ========================================================================
    # Common Crawl Integration Methods (Phase 11 Task 11.3)
    # ========================================================================

    async def scrape_from_common_crawl(
        self, url: str, dataset_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Scrape content from Common Crawl archives via HuggingFace datasets.

        This method queries Common Crawl indexes to find archived versions
        of legal websites, then fetches the content from WARC files.

        Args:
            url: URL to scrape from Common Crawl
            dataset_name: HuggingFace dataset name (e.g., "endomorphosis/common_crawl_state_index")

        Returns:
            Scraped content or None if not found

        Example:
            content = await scraper.scrape_from_common_crawl(
                "https://legislature.example.gov/code.html",
                dataset_name="endomorphosis/common_crawl_state_index"
            )
        """
        self._raise_if_retained_replay_only_network(
            operation="Common Crawl remote content access",
            url=url,
        )
        try:
            # Import Common Crawl scraper
            from ..common_crawl_scraper import CommonCrawlLegalScraper

            # Create scraper instance
            cc_scraper = CommonCrawlLegalScraper()

            # Scrape the URL using Common Crawl
            result = await cc_scraper.scrape_url(
                url,
                extract_rules=False,  # Just get content
                feed_to_logic=False,
            )

            if result.success and result.content:
                self.logger.info(f"Retrieved content from Common Crawl for: {url}")
                return result.content
            else:
                self.logger.warning(f"No Common Crawl content found for: {url}")
                return None

        except Exception as e:
            self.logger.error(f"Error scraping from Common Crawl: {e}")
            return None

    async def _search_state_common_crawl_records(
        self,
        *,
        domain_terms: Optional[List[str]] = None,
        url_terms: Optional[List[str]] = None,
        mime_terms: Optional[List[str]] = None,
        max_results: int = 20,
    ) -> List[Dict[str, Any]]:
        """Query the state Common Crawl HF index for this scraper's state."""
        self._raise_if_retained_replay_only_network(
            operation="Common Crawl inventory access"
        )
        inventory_stats: Dict[str, Any] = {
            "source": "none",
            "shared_domain_cache_hits": 0,
            "shared_domain_cache_misses": 0,
            "shared_domain_queries": 0,
            "shared_domain_query_failures": 0,
            "shared_domain_query_timeouts": 0,
            "shared_domain_backoff_skips": 0,
            "legacy_cache_hits": 0,
            "legacy_queries": 0,
            "legacy_query_failures": 0,
            "legacy_backoff_skips": 0,
        }
        self._last_state_common_crawl_inventory_stats = inventory_stats
        state_index_enabled = str(
            os.getenv("STATE_SCRAPER_COMMON_CRAWL_STATE_INDEX_ENABLED", "1")
        ).strip().lower() not in {"0", "false", "no", "off"}
        if not state_index_enabled:
            self.logger.info(
                "State Common Crawl index lookup disabled by env for %s",
                self.state_code,
            )
            return []

        try:
            from ..common_crawl_index_loader import CommonCrawlIndexLoader
        except Exception as e:
            self.logger.warning("State Common Crawl index loader unavailable: %s", e)
            return []

        local_index_root = str(
            os.getenv("IPFS_DATASETS_PY_COMMON_CRAWL_INDEX_ROOT", "")
            or (Path.cwd() / "data" / "common_crawl_indexes")
        ).strip()
        hf_fallback_enabled = str(
            os.getenv("STATE_SCRAPER_COMMON_CRAWL_HF_FALLBACK_ENABLED", "1")
        ).strip().lower() not in {"0", "false", "no", "off"}
        # Prefer an already-materialized jurisdiction sidecar/full state index,
        # but do not make the legacy monolithic HF state parquet the first
        # remote request.  The shared web_archiving engine has a domain-sharded
        # local/HF meta-index path and its own inventory cache; it also returns
        # the exact immutable WARC filename/offset/length pointers required by
        # the grouped range-fetch layer.
        loader = CommonCrawlIndexLoader(
            local_base_dir=local_index_root,
            use_hf_fallback=False,
        )
        try:
            materialize_local = str(
                os.getenv("IPFS_DATASETS_PY_COMMON_CRAWL_MATERIALIZE_LOCAL", "")
            ).strip().lower() in {"1", "true", "yes", "on"}
            if materialize_local and hf_fallback_enabled:
                loader.use_hf_fallback = True
                await asyncio.to_thread(loader.materialize_state_index_locally, False)
                loader.use_hf_fallback = False
            local_records = await asyncio.to_thread(
                loader.query_state_index,
                state_code=self.state_code,
                domain_terms=list(domain_terms or []),
                url_terms=list(url_terms or []),
                mime_terms=list(mime_terms or ["html"]),
                max_results=max_results,
            )
        except Exception as e:
            self.logger.warning(
                "Local state Common Crawl index query failed for %s: %s",
                self.state_code,
                e,
            )
            local_records = []

        if local_records or not hf_fallback_enabled:
            inventory_stats["source"] = "local" if local_records else "disabled"
            return list(local_records or [])

        normalized_domains: List[str] = []
        for value in list(domain_terms or []):
            raw = str(value or "").strip()
            if not raw:
                continue
            parsed = urlparse(raw if "://" in raw else f"https://{raw}")
            domain = str(parsed.hostname or "").lower().strip(".")
            if domain and domain not in normalized_domains:
                normalized_domains.append(domain)

        normalized_url_terms = [
            str(value or "").strip().lower()
            for value in list(url_terms or [])
            if str(value or "").strip()
        ]
        raw_url_terms = list(
            dict.fromkeys(
                str(value or "").strip()
                for value in list(url_terms or [])
                if str(value or "").strip()
            )
        )
        normalized_mime_terms = [
            str(value or "").strip().lower()
            for value in list(mime_terms or ["html"])
            if str(value or "").strip()
        ]

        result_limit = max(1, int(max_results or 100))
        failure_backoff_seconds = max(
            0.0,
            _env_float(
                "STATE_SCRAPER_COMMON_CRAWL_FAILURE_BACKOFF_SECONDS",
                300.0,
            ),
        )
        shared_source_options = tuple(
            (name, str(os.getenv(name) or ""))
            for name in (
                "CCINDEX_PARQUET_ROOT",
                "CCINDEX_MASTER_DB",
                "COMMON_CRAWL_HF_REMOTE_META",
                "IPFS_DATASETS_PY_COMMON_CRAWL_HF_REMOTE_META",
                "COMMON_CRAWL_HF_META_INDEX_DATASET",
                "IPFS_DATASETS_PY_COMMON_CRAWL_HF_META_INDEX_DATASET",
                "COMMON_CRAWL_HF_POINTER_DATASET",
                "IPFS_DATASETS_PY_COMMON_CRAWL_HF_POINTER_DATASET",
                "COMMON_CRAWL_HF_REVISION",
                "STATE_SCRAPER_COMMON_CRAWL_COLLECTION",
                "STATE_SCRAPER_COMMON_CRAWL_YEAR",
            )
        )
        shared_collection = str(
            os.getenv("STATE_SCRAPER_COMMON_CRAWL_COLLECTION") or ""
        ).strip() or None
        shared_year = str(
            os.getenv("STATE_SCRAPER_COMMON_CRAWL_YEAR") or ""
        ).strip() or None

        def _domain_url_prefixes(domain: str) -> tuple[str, ...]:
            """Build a bounded set of full prefixes for CC SQL pushdown."""

            candidates: List[str] = []
            for raw_term in raw_url_terms:
                # Preserve the reusable whole-domain inventory for small exact
                # frontiers.  Prefix pushdown is reserved for an explicitly
                # broad term (normally the common directory prefix compacted
                # from 64+ same-origin targets by the multi-fetch caller).
                if not raw_term.endswith(("/", "*", "%")):
                    continue
                if raw_term.startswith(("http://", "https://")):
                    try:
                        parsed_term = urlparse(raw_term)
                    except (TypeError, ValueError):
                        continue
                    if str(parsed_term.hostname or "").lower().strip(".") != domain:
                        continue
                    candidates.append(raw_term.rstrip("%*"))
                    continue
                if raw_term.startswith("/"):
                    candidates.append(f"https://{domain}{raw_term}".rstrip("%*"))

            # Each prefix is queried under both ordinary schemes because an
            # official HTTPS locator may have been archived before its upgrade
            # from HTTP.  Exact host/path/query identity is still enforced on
            # the returned records before any WARC byte request is admitted.
            expanded: List[str] = []
            for candidate in candidates:
                expanded.append(candidate)
                if candidate.startswith("https://"):
                    expanded.append("http://" + candidate[len("https://") :])
                elif candidate.startswith("http://"):
                    expanded.append("https://" + candidate[len("http://") :])
            return tuple(dict.fromkeys(expanded))

        now_monotonic = time.monotonic()
        domain_inventory: Dict[str, List[Dict[str, Any]]] = {}
        domains_to_query: List[str] = []
        shared_errors: List[str] = []
        for domain in normalized_domains:
            domain_url_prefixes = _domain_url_prefixes(domain)
            cache_key = (domain, domain_url_prefixes, shared_source_options)
            cached = self._state_common_crawl_domain_inventory_cache.get(cache_key)
            if cached is not None and int(cached.get("max_matches") or 0) >= result_limit:
                inventory_stats["shared_domain_cache_hits"] += 1
                domain_inventory[domain] = [
                    dict(record)
                    for record in list(cached.get("records") or [])
                    if isinstance(record, dict)
                ]
                continue
            backoff = self._state_common_crawl_domain_inventory_backoff.get(cache_key)
            if backoff is not None and float(backoff.get("until") or 0.0) > now_monotonic:
                inventory_stats["shared_domain_backoff_skips"] += 1
                reason = str(backoff.get("reason") or "transient shared inventory failure")
                shared_errors.append(f"{domain}: backoff active ({reason})")
                continue
            inventory_stats["shared_domain_cache_misses"] += 1
            domains_to_query.append(domain)

        if domains_to_query:
            try:
                from ...web_archiving.common_crawl_integration import (
                    CommonCrawlSearchEngine,
                )

                engine = CommonCrawlSearchEngine(mode="local")
                if not engine.is_available():
                    raise RuntimeError("shared Common Crawl search engine is unavailable")
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                for domain in domains_to_query:
                    domain_url_prefixes = _domain_url_prefixes(domain)
                    cache_key = (domain, domain_url_prefixes, shared_source_options)
                    if failure_backoff_seconds > 0:
                        self._state_common_crawl_domain_inventory_backoff[cache_key] = {
                            "until": now_monotonic + failure_backoff_seconds,
                            "reason": detail,
                        }
                    inventory_stats["shared_domain_query_failures"] += 1
                    shared_errors.append(f"{domain}: {detail}")
            else:
                for domain in domains_to_query:
                    # One domain inventory lookup serves every requested URL
                    # term on that host.  The engine chooses local meta-indexes
                    # when present and otherwise uses its cached HF remote-meta
                    # fallback rather than the legacy state-wide parquet.
                    inventory_stats["shared_domain_queries"] += 1
                    try:
                        search_options: Dict[str, Any] = {}
                        domain_url_prefixes = _domain_url_prefixes(domain)
                        if domain_url_prefixes:
                            search_options["url_prefixes"] = domain_url_prefixes
                        if shared_collection is not None:
                            search_options["collection"] = shared_collection
                        if shared_year is not None:
                            search_options["year"] = shared_year
                        inventory_timeout_seconds = max(
                            1.0,
                            _env_float(
                                "STATE_SCRAPER_COMMON_CRAWL_INVENTORY_TIMEOUT_SECONDS",
                                45.0,
                            ),
                        )
                        domain_records = await asyncio.wait_for(
                            asyncio.to_thread(
                                engine.search_domain,
                                domain,
                                max_matches=result_limit,
                                **search_options,
                            ),
                            timeout=inventory_timeout_seconds,
                        )
                    except asyncio.TimeoutError:
                        detail = (
                            "TimeoutError: shared Common Crawl domain inventory "
                            f"exceeded {inventory_timeout_seconds:g}s"
                        )
                        cache_key = (
                            domain,
                            _domain_url_prefixes(domain),
                            shared_source_options,
                        )
                        if failure_backoff_seconds > 0:
                            self._state_common_crawl_domain_inventory_backoff[cache_key] = {
                                "until": time.monotonic() + failure_backoff_seconds,
                                "reason": detail,
                            }
                        inventory_stats["shared_domain_query_failures"] += 1
                        inventory_stats["shared_domain_query_timeouts"] += 1
                        shared_errors.append(f"{domain}: {detail}")
                        continue
                    except Exception as exc:
                        detail = f"{type(exc).__name__}: {exc}"
                        cache_key = (
                            domain,
                            _domain_url_prefixes(domain),
                            shared_source_options,
                        )
                        if failure_backoff_seconds > 0:
                            self._state_common_crawl_domain_inventory_backoff[cache_key] = {
                                "until": time.monotonic() + failure_backoff_seconds,
                                "reason": detail,
                            }
                        inventory_stats["shared_domain_query_failures"] += 1
                        shared_errors.append(f"{domain}: {detail}")
                        continue
                    raw_inventory = [
                        dict(record)
                        for record in list(domain_records or [])
                        if isinstance(record, dict)
                    ]
                    cache_key = (
                        domain,
                        _domain_url_prefixes(domain),
                        shared_source_options,
                    )
                    prior = self._state_common_crawl_domain_inventory_cache.get(cache_key)
                    if prior is None or int(prior.get("max_matches") or 0) <= result_limit:
                        self._state_common_crawl_domain_inventory_cache[cache_key] = {
                            "max_matches": result_limit,
                            "records": raw_inventory,
                        }
                    self._state_common_crawl_domain_inventory_backoff.pop(cache_key, None)
                    domain_inventory[domain] = raw_inventory

        shared_records: List[Dict[str, Any]] = []
        seen_pointers: set[tuple[str, str, int, int, str]] = set()
        for domain in normalized_domains:
            for raw_record in domain_inventory.get(domain, []):
                if not isinstance(raw_record, dict):
                    continue
                record = dict(raw_record)
                indexed_url = str(record.get("url") or "").strip()
                indexed_url_lower = indexed_url.lower()
                if normalized_url_terms and not any(
                    term in indexed_url_lower for term in normalized_url_terms
                ):
                    continue
                mime = str(record.get("mime") or "").strip().lower()
                if normalized_mime_terms and not any(
                    term in mime for term in normalized_mime_terms
                ):
                    continue
                status = record.get("status")
                if status is None:
                    status = record.get("status_code")
                try:
                    if status is not None and int(status) != 200:
                        continue
                except (TypeError, ValueError):
                    continue

                warc_filename = str(
                    record.get("warc_filename")
                    or record.get("filename")
                    or ""
                ).strip()
                warc_offset = record.get("warc_offset")
                if warc_offset is None:
                    warc_offset = record.get("offset")
                warc_length = record.get("warc_length")
                if warc_length is None:
                    warc_length = record.get("length")
                try:
                    offset = int(warc_offset)
                    length = int(warc_length)
                except (TypeError, ValueError):
                    continue
                if not warc_filename or offset < 0 or length <= 0:
                    continue

                timestamp = str(record.get("timestamp") or "").strip()
                pointer_key = (
                    indexed_url,
                    warc_filename,
                    offset,
                    length,
                    timestamp,
                )
                if pointer_key in seen_pointers:
                    continue
                seen_pointers.add(pointer_key)
                record.update(
                    {
                        "state_code": str(
                            record.get("state_code") or self.state_code
                        ),
                        "warc_filename": warc_filename,
                        "warc_offset": offset,
                        "warc_length": length,
                    }
                )
                shared_records.append(record)
                if len(shared_records) >= result_limit:
                    break
            if len(shared_records) >= result_limit:
                break

        shared_error = "; ".join(shared_errors)
        if shared_error:
            self.logger.warning(
                "Shared Common Crawl domain inventory failed/backed off for %s: %s",
                self.state_code,
                shared_error,
            )

        if shared_records:
            inventory_stats["source"] = (
                "shared_cache"
                if int(inventory_stats["shared_domain_queries"]) == 0
                else "shared"
            )
            return shared_records

        # Preserve the legacy hosted state index as a final compatibility
        # fallback.  This path may be slower or rate-limited, but a transient
        # failure there no longer prevents the domain-sharded shared lookup.
        legacy_cache_key = (
            self.state_code.upper(),
            tuple(normalized_domains),
            tuple(normalized_url_terms),
            tuple(normalized_mime_terms),
            local_index_root,
        )
        cached_legacy = self._state_common_crawl_legacy_query_cache.get(
            legacy_cache_key
        )
        if (
            cached_legacy is not None
            and int(cached_legacy.get("max_results") or 0) >= result_limit
        ):
            inventory_stats["legacy_cache_hits"] += 1
            inventory_stats["source"] = "legacy_cache"
            return [
                dict(record)
                for record in list(cached_legacy.get("records") or [])[:result_limit]
                if isinstance(record, dict)
            ]

        if self._state_common_crawl_legacy_backoff_until > time.monotonic():
            inventory_stats["legacy_backoff_skips"] += 1
            inventory_stats["source"] = "failure_backoff"
            return []

        loader.use_hf_fallback = True
        inventory_stats["legacy_queries"] += 1
        try:
            legacy_records = await asyncio.to_thread(
                loader.query_state_index,
                state_code=self.state_code,
                domain_terms=list(domain_terms or []),
                url_terms=list(url_terms or []),
                mime_terms=list(mime_terms or ["html"]),
                max_results=max_results,
            )
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if shared_error:
                detail = f"shared={shared_error}; legacy={detail}"
            self.logger.warning(
                "State Common Crawl remote fallbacks failed for %s: %s",
                self.state_code,
                detail,
            )
            inventory_stats["legacy_query_failures"] += 1
            inventory_stats["source"] = "failure_backoff"
            if failure_backoff_seconds > 0:
                self._state_common_crawl_legacy_backoff_until = (
                    time.monotonic() + failure_backoff_seconds
                )
                self._state_common_crawl_legacy_backoff_reason = detail
            return []

        normalized_legacy_records = [
            dict(record)
            for record in list(legacy_records or [])
            if isinstance(record, dict)
        ]
        legacy_error = str(getattr(loader, "last_query_error", "") or "").strip()
        if not normalized_legacy_records and legacy_error:
            inventory_stats["legacy_query_failures"] += 1
            inventory_stats["source"] = "failure_backoff"
            if failure_backoff_seconds > 0:
                self._state_common_crawl_legacy_backoff_until = (
                    time.monotonic() + failure_backoff_seconds
                )
                self._state_common_crawl_legacy_backoff_reason = legacy_error
            self.logger.warning(
                "State Common Crawl legacy inventory failed for %s: %s",
                self.state_code,
                legacy_error,
            )
            return []

        self._state_common_crawl_legacy_backoff_until = 0.0
        self._state_common_crawl_legacy_backoff_reason = ""
        self._state_common_crawl_legacy_query_cache[legacy_cache_key] = {
            "max_results": result_limit,
            "records": normalized_legacy_records,
        }
        inventory_stats["source"] = "legacy"
        return normalized_legacy_records[:result_limit]

    async def _fetch_wayback_cdx_rows(
        self,
        cdx_url: str,
        *,
        timeout_seconds: int = 45,
    ) -> List[List[Any]]:
        """Run one CDX discovery query through the shared archive module.

        CDX responses enumerate potential parser inputs but are not themselves
        statutory text.  Their digest-bearing receipts are therefore retained
        separately for later frontier evidence instead of being mislabeled as
        official parser-input bytes.
        """

        self._raise_if_retained_replay_only_network(
            operation="Wayback CDX inventory access",
            url=cdx_url,
        )
        try:
            from ...web_archiving.wayback_machine_engine import (
                fetch_wayback_cdx_rows,
            )

            outcome = await fetch_wayback_cdx_rows(
                str(cdx_url or "").strip(),
                timeout_seconds=max(1, int(timeout_seconds or 45)),
            )
        except Exception as exc:
            self.logger.debug("Shared Wayback CDX query failed: %s", exc)
            return []

        if not isinstance(outcome, dict) or outcome.get("status") != "success":
            return []
        receipt = outcome.get("receipt")
        if isinstance(receipt, dict) and receipt:
            self._state_law_archive_discovery_receipts.append(dict(receipt))
        rows = outcome.get("rows")
        if not isinstance(rows, list):
            return []
        return [list(row) for row in rows if isinstance(row, list)]

    async def _scrape_state_common_crawl_candidates(
        self,
        *,
        domain_terms: Optional[List[str]] = None,
        url_terms: Optional[List[str]] = None,
        mime_terms: Optional[List[str]] = None,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch candidate archived pages from the state Common Crawl index."""
        records = await self._search_state_common_crawl_records(
            domain_terms=domain_terms,
            url_terms=url_terms,
            mime_terms=mime_terms,
            max_results=max_results,
        )
        if not records:
            return []

        try:
            from ...web_archiving.common_crawl_integration import CommonCrawlSearchEngine
            from .state_archival_fetch import ArchivalFetchClient
        except Exception as e:
            self.logger.warning("Common Crawl WARC fetch helpers unavailable: %s", e)
            return []

        try:
            engine = CommonCrawlSearchEngine(mode="local")
        except Exception as e:
            self.logger.warning("Common Crawl search engine unavailable: %s", e)
            return []
        archival_client = ArchivalFetchClient(
            request_timeout_seconds=max(
                1,
                _env_int("STATE_SCRAPER_FETCH_TIMEOUT_SECONDS", 45) or 45,
            ),
            delay_seconds=0.0,
            content_validator=lambda payload: bool(payload),
            enable_common_crawl=True,
            enable_direct=False,
            enable_archive_is=False,
        )

        batch_requests: List[tuple[str, Dict[str, Any]]] = []
        for record in records:
            source_url = self._canonical_fetch_url(str(record.get("url") or ""))
            if not source_url:
                continue
            batch_requests.append((source_url, dict(record)))
        if not batch_requests:
            return []

        try:
            batch = await asyncio.to_thread(
                archival_client.fetch_common_crawl_records,
                batch_requests,
                engine=engine,
            )
        except Exception as e:
            self.logger.warning(
                "Common Crawl state batch failed for %s: %s",
                self.state_code,
                e,
            )
            return []

        self._last_common_crawl_batch_stats = dict(
            getattr(batch, "stats", {}) or {}
        )
        fetched_results = list(getattr(batch, "results", []) or [])
        if len(fetched_results) != len(batch_requests):
            self.logger.warning(
                "Common Crawl state batch returned %s results for %s requests",
                len(fetched_results),
                len(batch_requests),
            )
            return []

        out: List[Dict[str, Any]] = []
        for (source_url, record), fetched in zip(
            batch_requests,
            fetched_results,
        ):
            try:
                if fetched is None:
                    continue
                payload = self._retain_archival_fetch_result_before_parser(
                    official_url=source_url,
                    fetched=fetched,
                    media_type=str(record.get("mime") or "") or None,
                )
                if not payload:
                    continue
                try:
                    from bs4 import BeautifulSoup

                    decoded = payload.decode("utf-8", errors="replace")
                    text = BeautifulSoup(decoded, "html.parser").get_text(
                        " ",
                        strip=True,
                    )
                except Exception:
                    text = payload.decode("utf-8", errors="replace")
                text = self._normalize_legal_text(text)
                if len(text) < 80:
                    continue
                out.append(
                    {
                        "url": source_url,
                        "domain": str(record.get("domain") or ""),
                        "timestamp": str(record.get("timestamp") or ""),
                        "text": text,
                        "mime": str(record.get("mime") or ""),
                        "collection": str(record.get("collection") or ""),
                        "archive_url": str(getattr(fetched, "archive_url", "") or ""),
                        "content_sha256": hashlib.sha256(payload).hexdigest(),
                        "warc_filename": str(
                            getattr(fetched, "common_crawl_warc_filename", "") or ""
                        ),
                        "warc_offset": int(
                            getattr(fetched, "common_crawl_warc_offset", 0) or 0
                        ),
                        "warc_length": int(
                            getattr(fetched, "common_crawl_warc_length", 0) or 0
                        ),
                    }
                )
            except Exception as e:
                self.logger.debug(
                    "Common Crawl state candidate fetch failed for %s: %s", record.get("url"), e
                )
                continue
        return out

    async def query_warc_file(self, warc_url: str, offset: int, length: int) -> Optional[str]:
        """
        Query a WARC file directly using offset and range.

        This method retrieves content from a Common Crawl WARC file
        using byte offset and length for efficient partial file access.

        Args:
            warc_url: S3 URL to WARC file
            offset: Byte offset in file
            length: Number of bytes to read

        Returns:
            WARC record content or None

        Example:
            content = await scraper.query_warc_file(
                "s3://commoncrawl/crawl-data/CC-MAIN-2024-10/segments/.../warc.gz",
                offset=123456,
                length=5000
            )
        """
        self._raise_if_retained_replay_only_network(
            operation="Common Crawl remote-pointer access",
            url=warc_url,
        )
        try:
            from ...web_archiving.common_crawl_integration import CommonCrawlSearchEngine
            from urllib.parse import urlparse

            # Create engine instance
            engine = CommonCrawlSearchEngine()

            parsed = urlparse(str(warc_url or ""))
            warc_filename = parsed.path.lstrip("/") if parsed.scheme else str(warc_url or "")

            # Support the current fetch_warc_record API and older fetch_warc_segment variants.
            if hasattr(engine, "fetch_warc_record"):
                raw_content = engine.fetch_warc_record(
                    warc_filename=warc_filename,
                    warc_offset=offset,
                    warc_length=length,
                )
                if isinstance(raw_content, (bytes, bytearray)):
                    content = bytes(raw_content).decode("utf-8", errors="replace")
                else:
                    content = str(raw_content or "")
            else:
                fetch_warc_segment = getattr(engine, "fetch_warc_segment")
                content = await fetch_warc_segment(warc_url=warc_url, offset=offset, length=length)

            if content:
                self.logger.info(f"Retrieved WARC content (offset={offset}, length={length})")
                return content
            else:
                self.logger.warning("Empty WARC content retrieved")
                return None

        except Exception as e:
            self.logger.error(f"Error querying WARC file: {e}")
            return None

    async def extract_with_graphrag(
        self, content: str, extract_rules: bool = True
    ) -> Dict[str, Any]:
        """
        Extract structured data from legal content using GraphRAG.

        This method uses GraphRAG to extract entities, relationships,
        and legal rules from raw legal text content.

        Args:
            content: Raw HTML or text content
            extract_rules: Whether to extract legal rules

        Returns:
            Dictionary with extracted data (entities, relationships, rules)

        Example:
            results = await scraper.extract_with_graphrag(
                html_content,
                extract_rules=True
            )
            rules = results.get('rules', [])
        """
        try:
            from ...specialized.graphrag import UnifiedGraphRAGProcessor

            # Create GraphRAG processor
            graphrag = UnifiedGraphRAGProcessor()

            # Use process_website which is the primary API
            # We pass the content as if it's from a URL
            extraction_result = await graphrag.process_website(
                url="inline://content",  # Dummy URL for inline content
                content_override=content,  # Pass content directly
            )

            result = {
                "entities": extraction_result.entities
                if hasattr(extraction_result, "entities")
                else [],
                "relationships": extraction_result.relationships
                if hasattr(extraction_result, "relationships")
                else [],
                "rules": [],
            }

            # Extract legal rules from knowledge graph if available
            if extract_rules and hasattr(extraction_result, "knowledge_graph"):
                # Simple rule extraction: look for entities that represent rules/statutes
                kg = extraction_result.knowledge_graph
                if kg and hasattr(kg, "entities"):
                    for entity in kg.entities.values():
                        if entity.type.lower() in ["rule", "statute", "law", "regulation"]:
                            result["rules"].append(
                                {
                                    "text": entity.name,
                                    "type": entity.type,
                                    "attributes": entity.attributes
                                    if hasattr(entity, "attributes")
                                    else {},
                                }
                            )

            self.logger.info(
                f"Extracted {len(result['entities'])} entities, "
                f"{len(result['relationships'])} relationships, "
                f"{len(result['rules'])} rules"
            )

            return result

        except Exception as e:
            self.logger.error(f"Error extracting with GraphRAG: {e}")
            return {"entities": [], "relationships": [], "rules": []}

    async def scrape_with_fallbacks(
        self, url: str, use_common_crawl: bool = True, use_graphrag: bool = False
    ) -> Optional[NormalizedStatute]:
        """
        Scrape a statute with graceful fallbacks through multiple methods.

        This method attempts to scrape using the following fallback chain:
        1. Common Crawl (if enabled)
        2. Direct HTTP request
        3. Playwright (if available)

        Args:
            url: URL to scrape
            use_common_crawl: Whether to try Common Crawl first
            use_graphrag: Whether to use GraphRAG for extraction

        Returns:
            NormalizedStatute or None

        Example:
            statute = await scraper.scrape_with_fallbacks(
                "https://legislature.example.gov/statute.html",
                use_common_crawl=True,
                use_graphrag=True
            )
        """
        self._raise_if_retained_replay_only_network(
            operation="direct/Common Crawl/browser fallback access",
            url=url,
        )
        content = None
        method_used = None

        # Try 1: Common Crawl
        if use_common_crawl:
            try:
                content = await self.scrape_from_common_crawl(url)
                if content:
                    method_used = "common_crawl"
            except Exception as e:
                self.logger.warning(f"Common Crawl failed: {e}")

        # Try 2: Direct HTTP
        if not content:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url)
                    if response.status_code == 200:
                        content = response.text
                        method_used = "http"
            except Exception as e:
                self.logger.warning(f"HTTP request failed: {e}")

        # Try 3: Playwright (if available)
        if not content:
            try:
                from playwright.async_api import async_playwright

                async with acquire_playwright_slot():
                    async with async_playwright() as p:
                        browser = await p.chromium.launch()
                        page = await browser.new_page()
                        try:
                            await page.goto(url, wait_until="networkidle")
                            content = await page.content()
                            method_used = "playwright"
                        finally:
                            try:
                                await page.close()
                            finally:
                                await browser.close()
            except Exception as e:
                self.logger.warning(f"Playwright failed: {e}")

        if not content:
            self.logger.error(f"All fallback methods failed for: {url}")
            return None

        # Extract with GraphRAG if requested
        if use_graphrag:
            await self.extract_with_graphrag(content)

        # Parse content to create NormalizedStatute
        # This is a simplified parser - real implementation would be more sophisticated
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "html.parser")

        # Extract basic information
        title = soup.find("title")
        title_text = title.get_text().strip() if title else "Unknown"

        # Try to extract section number from URL or title
        section_number = self._extract_section_number(url) or self._extract_section_number(
            title_text
        )

        # Create normalized statute
        statute = NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=section_number or url.split("/")[-1],
            section_number=section_number,
            short_title=title_text,
            full_text=soup.get_text(),
            source_url=url,
            legal_area=self._identify_legal_area(title_text),
            metadata=StatuteMetadata(),
        )

        self.logger.info(f"Scraped statute using {method_used}: {statute.statute_id}")

        return self._enrich_statute_structure(statute)
