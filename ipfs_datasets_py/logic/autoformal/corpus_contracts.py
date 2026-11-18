"""Bounded content-addressed envelopes for additive legal corpus records.

Seals establish data identity, not source authenticity, legal meaning or proof.
Existing caches, semantic payloads and historical identifiers are unchanged.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from ipfs_datasets_py.utils.cid_utils import (
    canonical_dag_json_bytes,
    cid_for_dag_json,
    validate_cid,
)

MAX_RECORD_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 20
MAX_JSON_NODES = 25_000
MAX_INTEGER = (1 << 63) - 1
RECORD_CID_SCOPE = "payload_without_record_cid/v1"


class CorpusContractError(ValueError):
    """A record is malformed, unbound, oversized or unsupported."""


def require_text(value, field, *, allow_empty=False, max_bytes=4096):
    if type(value) is not str or "\x00" in value:
        raise CorpusContractError(f"{field} must be ordinary text without NUL")
    if not allow_empty and not value.strip():
        raise CorpusContractError(f"{field} must be nonblank")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise CorpusContractError(f"{field} must be valid UTF8") from error
    if size > max_bytes:
        raise CorpusContractError(f"{field} exceeds its byte bound")
    return value


def require_int(value, field, *, minimum=0, maximum=MAX_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        raise CorpusContractError(f"{field} must be an integer in [{minimum}, {maximum}]")
    return value


def require_keys(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise CorpusContractError(f"closed {label} fields required")
    return value


def require_sha256(value, field):
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise CorpusContractError(f"{field} must be lowercase SHA256")
    return value


def require_cid(value, field, *, codecs=("raw", "dag-json")):
    if type(value) is not str:
        raise CorpusContractError(f"{field} must be a canonical CIDv1")
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as error:
        raise CorpusContractError(f"{field} must be a canonical CIDv1") from error


def require_cid_sha256(value, digest, field, *, codecs=("raw",)):
    """Check an artifact CID against an independently supplied SHA256."""
    from multiformats import CID

    checked = require_cid(value, field, codecs=codecs)
    require_sha256(digest, field + " SHA256")
    if bytes(CID.decode(checked).raw_digest).hex() != digest:
        raise CorpusContractError(f"{field} CID digest differs from SHA256")
    return checked


def clone_json(value, *, max_depth=MAX_JSON_DEPTH):
    """Validate bounded ordinary JSON before returning a detached copy."""
    require_int(max_depth, "JSON maximum depth", minimum=0, maximum=96)
    remaining = MAX_JSON_NODES
    remaining_bytes = MAX_RECORD_BYTES

    def visit(node, depth):
        nonlocal remaining, remaining_bytes
        remaining -= 1
        if remaining < 0 or depth > max_depth:
            raise CorpusContractError("record exceeds JSON node/depth bounds")
        if type(node) is dict:
            for key, item in node.items():
                require_text(key, "JSON key", max_bytes=4096)
                remaining_bytes -= len(key.encode("utf-8"))
                visit(item, depth + 1)
        elif type(node) is list:
            for item in node:
                visit(item, depth + 1)
        elif type(node) is str:
            require_text(node, "JSON string", allow_empty=True, max_bytes=MAX_RECORD_BYTES)
            remaining_bytes -= len(node.encode("utf-8"))
        elif type(node) is int:
            require_int(node, "JSON integer", minimum=-MAX_INTEGER, maximum=MAX_INTEGER)
        elif node is None or type(node) in (bool, float):
            pass  # The existing canonical owner rejects non-finite floats.
        else:
            raise CorpusContractError("record requires ordinary JSON values")
        if remaining_bytes < 0:
            raise CorpusContractError("record exceeds byte bound")

    try:
        visit(value, 0)
        raw = canonical_dag_json_bytes(value)
        if len(raw) > MAX_RECORD_BYTES:
            raise CorpusContractError("record exceeds byte bound")
        return json.loads(raw)
    except (TypeError, ValueError, RecursionError, OverflowError) as error:
        if isinstance(error, CorpusContractError):
            raise
        raise CorpusContractError("record requires bounded finite JSON") from error


def seal_record(payload):
    """Seal a new payload; the CID excludes only its own record_cid field."""
    body = clone_json(payload)
    if type(body) is not dict:
        raise CorpusContractError("record payload must be an object")
    require_text(body.get("schema"), "schema", max_bytes=256)
    if {"record_cid", "cid_scope"} & set(body):
        raise CorpusContractError("record_cid and cid_scope are reserved envelope fields")
    body["cid_scope"] = RECORD_CID_SCOPE
    body["record_cid"] = cid_for_dag_json(body)
    return clone_json(body)


def validate_record(record, *, schema, fields: Sequence[str]):
    """Verify exact envelope shape, scope and canonical content identity."""
    checked = clone_json(record)
    require_keys(checked, {*fields, "schema", "record_cid", "cid_scope"}, schema)
    if checked["schema"] != schema or checked["cid_scope"] != RECORD_CID_SCOPE:
        raise CorpusContractError("record schema or CID scope differs")
    require_cid(checked["record_cid"], "record_cid", codecs=("dag-json",))
    body = {key: item for key, item in checked.items() if key != "record_cid"}
    if cid_for_dag_json(body) != checked["record_cid"]:
        raise CorpusContractError("record CID differs from payload")
    return checked


def load_json_bytes(raw, *, expected_sha256, max_depth=MAX_JSON_DEPTH):
    """Read exact digest-bound JSON, including opaque array/string AST payloads."""
    require_int(max_depth, "JSON maximum depth", minimum=0, maximum=96)
    require_sha256(expected_sha256, "expected_sha256")
    if type(raw) is not bytes or len(raw) > MAX_RECORD_BYTES:
        raise CorpusContractError("bounded record bytes required")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise CorpusContractError("record bytes differ from expected SHA256")

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise CorpusContractError("duplicate JSON key")
            result[key] = item
        return result

    def constant(value):
        raise CorpusContractError(f"non-finite JSON constant {value}")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, CorpusContractError):
            raise
        raise CorpusContractError("invalid record JSON bytes") from error
    return clone_json(result, max_depth=max_depth)


def load_record_bytes(raw, *, expected_sha256):
    """Read an exact digest-bound JSON object; duplicate keys and oversize refuse."""
    result = load_json_bytes(raw, expected_sha256=expected_sha256)
    if type(result) is not dict:
        raise CorpusContractError("record JSON must be an object")
    return result


# Private loaded-code bindings for the explicit original-parent release join.
# These checks establish implementation identity only; they confer no admission.
from dataclasses import (
    Field as _LOADED_OWNER_FIELD_V1,
    _DataclassParams as _LOADED_OWNER_PARAMS_V1,
    MISSING as _LOADED_OWNER_MISSING_V1,
    _EMPTY_METADATA as _LOADED_OWNER_EMPTY_METADATA_V1,
    _HAS_DEFAULT_FACTORY as _LOADED_OWNER_FACTORY_V1,
    _FIELD as _LOADED_OWNER_FIELD_KIND_V1,
    _FIELD_CLASSVAR as _LOADED_OWNER_CLASSVAR_V1,
    _FIELD_INITVAR as _LOADED_OWNER_INITVAR_V1,
)
from re import Pattern as _LOADED_OWNER_PATTERN_V1
from sys import _getframe as _LOADED_OWNER_GETFRAME_V1
from importlib.machinery import ModuleSpec as _LOADED_OWNER_SPEC_V1
from types import (
    FunctionType as _LOADED_OWNER_FUNCTION_V1,
    MappingProxyType as _LOADED_OWNER_MAPPING_V1,
    ModuleType as _LOADED_OWNER_MODULE_V1,
    BuiltinFunctionType as _LOADED_OWNER_BUILTIN_V1,
    MethodDescriptorType as _LOADED_OWNER_METHOD_V1,
    WrapperDescriptorType as _LOADED_OWNER_WRAPPER_V1,
    GetSetDescriptorType as _LOADED_OWNER_GETSET_V1,
    MemberDescriptorType as _LOADED_OWNER_MEMBER_V1,
)
_LOADED_OWNER_FIELD_SLOTS_V1 = tuple(
    (name, type.__getattribute__(_LOADED_OWNER_FIELD_V1, "__dict__")[name])
    for name in type.__getattribute__(_LOADED_OWNER_FIELD_V1, "__dict__")["__slots__"]
    if name != "__weakref__")
_LOADED_OWNER_PARAM_SLOTS_V1 = tuple(
    (name, type.__getattribute__(_LOADED_OWNER_PARAMS_V1, "__dict__")[name])
    for name in type.__getattribute__(_LOADED_OWNER_PARAMS_V1, "__dict__")["__slots__"])
if any(type(descriptor) is not _LOADED_OWNER_MEMBER_V1
       for _name, descriptor in _LOADED_OWNER_FIELD_SLOTS_V1 + _LOADED_OWNER_PARAM_SLOTS_V1):
    raise CorpusContractError("native dataclass slot descriptors required")

_LOADED_OWNER_MAX_REGISTRATIONS_V1 = 128
_LOADED_OWNER_MAX_DEPTH_V1 = 48
_LOADED_OWNER_MAX_NODES_V1 = 16384
_LOADED_OWNER_MAX_LITERAL_BYTES_V1 = 1024 * 1024
_LOADED_OWNER_REGISTRATION_NAME_V1 = "_JOIN_LOADED_OWNER_GUARD_V1"


def _loaded_owner_shape_v1(bindings):
    """Snapshot a bounded, explicit binding surface without running properties."""
    seen, references = set(), []
    remaining = [_LOADED_OWNER_MAX_NODES_V1, _LOADED_OWNER_MAX_LITERAL_BYTES_V1]

    def pin(item):
        references.append(item)
        return id(item)

    def walk(item, depth, *, expand_class=False):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > _LOADED_OWNER_MAX_DEPTH_V1:
            raise CorpusContractError("loaded-owner snapshot node/depth bound exceeded")
        kind = type(item)
        if item is None:
            return ("none",)
        if any(kind is allowed for allowed in (bool, int)):
            if kind is int and item.bit_length() > 4096:
                raise CorpusContractError("loaded-owner integer bound exceeded")
            return (kind.__name__, item)
        if kind is float:
            return ("float", item.hex())
        if any(kind is allowed for allowed in (str, bytes)):
            if len(item) > remaining[1]:
                raise CorpusContractError("loaded-owner snapshot literal byte bound exceeded")
            remaining[1] -= len(item.encode("utf-8")) if kind is str else len(item)
            if remaining[1] < 0:
                raise CorpusContractError("loaded-owner snapshot literal byte bound exceeded")
            return (kind.__name__, item)
        if kind is _LOADED_OWNER_MAPPING_V1:
            # Only the stdlib's captured immutable empty metadata singleton is
            # trusted here. Other proxies can delegate to arbitrary Mapping
            # callbacks, even when type(proxy) is exactly MappingProxyType.
            if item is _LOADED_OWNER_EMPTY_METADATA_V1:
                return ("empty_dataclass_metadata", pin(item))
            raise CorpusContractError("untrusted loaded-owner mapping proxy")
        identity = pin(item)
        if identity in seen:
            return ("reference", identity)
        if any(kind is allowed for allowed in (tuple, list, dict, set, frozenset)):
            seen.add(identity)
            if len(item) > remaining[0]:
                raise CorpusContractError("loaded-owner container node bound exceeded")
            if kind is dict:
                pairs = tuple((walk(key, depth + 1), walk(child, depth + 1))
                              for key, child in item.items())
                return ("mapping", identity, pairs)
            children = tuple(walk(child, depth + 1) for child in item)
            if any(kind is allowed for allowed in (set, frozenset)):
                children = tuple(sorted(children))
            return (kind.__name__, identity, children)
        if kind is _LOADED_OWNER_FUNCTION_V1:
            seen.add(identity)
            closure = []
            for cell_name, cell in zip(item.__code__.co_freevars, item.__closure__ or ()):
                try:
                    child = cell.cell_contents
                except ValueError:
                    closure.append(("empty", pin(cell)))
                else:
                    private_registry_owner = any(
                        item is globals().get(name) for name in (
                            "_capture_loaded_owner_guard_v1",
                            "_loaded_owner_guard_binding_v1",
                            "_loaded_owner_registry_binding_v1"))
                    if (private_registry_owner and cell_name == "registrations"
                            and type(child) is dict):
                        # Its original entries are checked through the separately
                        # authenticated registry binding, never a namespace walk.
                        closure.append(("private_registry_cell", pin(cell), pin(child)))
                    else:
                        closure.append(("cell", pin(cell), walk(child, depth + 1)))
            return ("function", identity, pin(item.__code__),
                    pin(item.__globals__), walk(item.__defaults__, depth + 1),
                    walk(item.__kwdefaults__, depth + 1),
                    walk(item.__dict__, depth + 1), tuple(closure))
        if any(kind is allowed for allowed in (classmethod, staticmethod)):
            seen.add(identity)
            return ("method_descriptor", identity, kind.__name__,
                    walk(item.__func__, depth + 1), walk(item.__dict__, depth + 1))
        if kind is property:
            seen.add(identity)
            return ("property_descriptor", identity,
                    walk(item.fget, depth + 1), walk(item.fset, depth + 1),
                    walk(item.fdel, depth + 1), walk(item.__doc__, depth + 1))
        if kind is type:
            if not expand_class:
                return ("type_binding", identity)
            seen.add(identity)
            namespace = type.__getattribute__(item, "__dict__")
            if len(namespace) > 512:
                raise CorpusContractError("loaded-owner class namespace bound exceeded")
            return ("class", identity, tuple(pin(base) for base in item.__bases__),
                    tuple((name, walk(namespace[name], depth + 1))
                          for name in sorted(namespace)))
        if kind is _LOADED_OWNER_FIELD_V1:
            seen.add(identity)
            return ("dataclass_field", identity,
                    tuple((name, walk(descriptor.__get__(item, kind), depth + 1))
                          for name, descriptor in _LOADED_OWNER_FIELD_SLOTS_V1))
        if kind is _LOADED_OWNER_PARAMS_V1:
            seen.add(identity)
            return ("dataclass_parameters", identity,
                    tuple((name, walk(descriptor.__get__(item, kind), depth + 1))
                          for name, descriptor in _LOADED_OWNER_PARAM_SLOTS_V1))
        if kind is _LOADED_OWNER_PATTERN_V1:
            return ("regular_expression", identity, item.pattern, item.flags)
        opaque_types = (_LOADED_OWNER_MODULE_V1,
                        _LOADED_OWNER_BUILTIN_V1,
                        _LOADED_OWNER_METHOD_V1,
                        _LOADED_OWNER_WRAPPER_V1,
                        _LOADED_OWNER_GETSET_V1,
                        _LOADED_OWNER_MEMBER_V1)
        if any(kind is allowed for allowed in opaque_types):
            return ("opaque_binding", pin(kind), identity)
        sentinels = (_LOADED_OWNER_MISSING_V1,
                     _LOADED_OWNER_FACTORY_V1,
                     _LOADED_OWNER_FIELD_KIND_V1,
                     _LOADED_OWNER_CLASSVAR_V1,
                     _LOADED_OWNER_INITVAR_V1)
        if any(item is sentinel for sentinel in sentinels):
            return ("dataclass_sentinel", identity)
        raise CorpusContractError("unsupported loaded-owner snapshot value")

    if (type(bindings) is not tuple or len(bindings) > 512
            or any(type(entry) is not tuple or len(entry) != 3
                   or type(entry[0]) is not str or type(entry[1]) is not str
                   for entry in bindings)):
        raise CorpusContractError("bounded loaded-owner binding population required")
    result = tuple((category, name,
                    ("import_binding", pin(type(value)), pin(value))
                    if category == "alias" else
                    walk(value, 0, expand_class=category == "class"))
                   for category, name, value in bindings)
    return result, tuple(references)


def _loaded_owner_state_v1(namespace, selection):
    """Capture only owner functions and the explicitly selected data/bindings."""
    if (type(namespace) is not dict or len(namespace) > 4096
            or type(selection) is not tuple or len(selection) != 4
            or any(type(name) is not str or len(name) > 256 for name in namespace)):
        raise CorpusContractError("exact loaded-owner namespace/selection required")
    value_names, class_names, imported_function_names, alias_names = selection
    names = tuple(sorted(name for name, value in namespace.items()
                         if type(value) is _LOADED_OWNER_FUNCTION_V1
                         and (value.__globals__ is namespace
                              or (type(value.__module__) is str
                                  and type(namespace.get("__name__")) is str
                                  and value.__module__ == namespace["__name__"]))
                         and name != _LOADED_OWNER_REGISTRATION_NAME_V1))
    bindings = [("value", "__name__", namespace.get("__name__")),
                ("value", "__file__", namespace.get("__file__")),
                ("value", "__package__", namespace.get("__package__"))]
    for category, selected in (("function", names), ("value", value_names),
                               ("class", class_names), ("imported", imported_function_names),
                               ("alias", alias_names)):
        if (type(selected) is not tuple or len(selected) > 512
                or any(type(name) is not str or not name or len(name) > 256 for name in selected)
                or len(set(selected)) != len(selected)):
            raise CorpusContractError("bounded distinct loaded-owner selection required")
        for name in selected:
            if name not in namespace:
                raise CorpusContractError("selected loaded-owner binding is missing")
            value = namespace[name]
            if category == "class" and type(value) is not type:
                raise CorpusContractError("ordinary selected class required")
            if category == "imported" and type(value) is not _LOADED_OWNER_FUNCTION_V1:
                raise CorpusContractError("ordinary imported function required")
            bindings.append((category, name, value))
            if len(bindings) > 512:
                raise CorpusContractError("loaded-owner binding population bound exceeded")
    state, references = _loaded_owner_shape_v1(tuple(bindings))
    return (tuple(sorted(name for name in namespace
                         if name != _LOADED_OWNER_REGISTRATION_NAME_V1)), names, state), references


def _loaded_owner_guard_identity_v1(verifier):
    """Cold identity material; the issuing owner pins and checks this helper too."""
    if (type(verifier) is not _LOADED_OWNER_FUNCTION_V1
            or verifier.__globals__ is not globals()
            or verifier.__name__ != "verifier"):
        raise CorpusContractError("exact private loaded-owner verifier required")
    cells = []
    for cell in verifier.__closure__ or ():
        try:
            value = cell.cell_contents
        except ValueError:
            cells.append((id(cell), None))
        else:
            cells.append((id(cell), id(value)))
    return (id(verifier), id(verifier.__code__), id(verifier.__defaults__),
            id(verifier.__kwdefaults__), tuple(cells))


if True:
    def _new_loaded_owner_registry_v1():
        # The dictionary is never returned. Import establishes each namespace once.
        registrations = {}

        def _capture_loaded_owner_guard_v1(namespace, *, value_names=(), class_names=(),
                                          imported_function_names=(), alias_names=()):
            """Make a cold private checker; an untrusted caller cannot supply its baseline.

        The issuing owner separately authenticates this primitive and the exact
        checker/closure identities in its fixed private registration tuple. Calling
        a replacement predicate, or presenting a serialized snapshot, is not enough.
        No module globals, object properties or unrelated dependency graphs are
        discovered beyond the explicit selection and each owned function binding.
        """
            if (type(namespace) is not dict
                    or _LOADED_OWNER_REGISTRATION_NAME_V1 in namespace):
                raise CorpusContractError("fresh exact loaded-owner registration required")
            frame = _LOADED_OWNER_GETFRAME_V1(1)
            origin_code = frame.f_code
            source_path = namespace.get("__file__")
            spec = namespace.get("__spec__")
            if (frame.f_globals is not namespace or frame.f_locals is not namespace
                    or origin_code.co_name != "<module>"
                    or type(source_path) is not str or origin_code.co_filename != source_path
                    or type(spec) is not _LOADED_OWNER_SPEC_V1):
                raise CorpusContractError("loaded-owner capture requires its genuine module import")
            spec_fields = object.__getattribute__(spec, "__dict__")
            if (type(spec_fields.get("origin")) is not str
                    or type(spec_fields.get("name")) is not str
                    or type(namespace.get("__name__")) is not str
                    or spec_fields["origin"] != source_path
                    or spec_fields["name"] != namespace["__name__"]):
                raise CorpusContractError("loaded-owner import origin differs")
            if id(namespace) in registrations:
                raise CorpusContractError("original loaded-owner namespace already registered")
            if len(registrations) >= _LOADED_OWNER_MAX_REGISTRATIONS_V1:
                raise CorpusContractError("loaded-owner original registration count bound exceeded")
            selection = (value_names, class_names, imported_function_names, alias_names)
            expected, references = _loaded_owner_state_v1(namespace, selection)

            def verifier():
                # Keep the original code/objects alive; snapshots compare IDs without
                # invoking arbitrary equality, repr, descriptors or property getters.
                _original_references = references
                if (namespace.get(_LOADED_OWNER_REGISTRATION_NAME_V1) is not verifier
                        or type(namespace.get("__file__")) is not str
                        or namespace["__file__"] != origin_code.co_filename):
                    raise CorpusContractError("loaded-owner checker binding differs")
                current, _current_references = _loaded_owner_state_v1(namespace, selection)
                if current != expected:
                    raise CorpusContractError("loaded-owner implementation binding differs")
                return None

            original_objects = (verifier.__code__, verifier.__defaults__,
                                verifier.__kwdefaults__, *verifier.__closure__,
                                *(cell.cell_contents for cell in verifier.__closure__))
            registrations[id(namespace)] = (namespace, verifier,
                _loaded_owner_guard_identity_v1(verifier), original_objects)
            return verifier

        def _loaded_owner_guard_binding_v1(namespace, verifier):
            """Return scalar comparison material and original strong references only."""
            if (type(namespace) is not dict or type(namespace.get("__file__")) is not str):
                raise CorpusContractError("exact loaded-owner namespace required")
            entry = registrations.get(id(namespace))
            if (entry is None or entry[0] is not namespace or entry[1] is not verifier
                    or namespace.get(_LOADED_OWNER_REGISTRATION_NAME_V1) is not verifier):
                raise CorpusContractError("original loaded-owner registration differs")
            identity = _loaded_owner_guard_identity_v1(verifier)
            if identity != entry[2]:
                raise CorpusContractError("original loaded-owner verifier binding differs")
            return (id(namespace), identity), entry


        def _loaded_owner_registry_binding_v1():
            """Pin the original private registry, independently of unrelated owners.

        The issuer also binds each owner in its fixed selected module tuple via
        _loaded_owner_guard_binding_v1. No dictionary or reset API is returned.
        """
            return (id(registrations),), (
                _capture_loaded_owner_guard_v1, _loaded_owner_guard_binding_v1)


        return (_capture_loaded_owner_guard_v1, _loaded_owner_guard_binding_v1,
                _loaded_owner_registry_binding_v1)


(_capture_loaded_owner_guard_v1, _loaded_owner_guard_binding_v1,
 _loaded_owner_registry_binding_v1) = _new_loaded_owner_registry_v1()
del _new_loaded_owner_registry_v1

_JOIN_LOADED_OWNER_GUARD_V1 = _capture_loaded_owner_guard_v1(
    globals(), value_names=('MAX_INTEGER', 'MAX_JSON_DEPTH', 'MAX_JSON_NODES', 'MAX_RECORD_BYTES', 'RECORD_CID_SCOPE', '_LOADED_OWNER_FIELD_SLOTS_V1', '_LOADED_OWNER_MAX_DEPTH_V1', '_LOADED_OWNER_MAX_LITERAL_BYTES_V1', '_LOADED_OWNER_MAX_NODES_V1', '_LOADED_OWNER_MAX_REGISTRATIONS_V1', '_LOADED_OWNER_PARAM_SLOTS_V1', '_LOADED_OWNER_REGISTRATION_NAME_V1'),
    class_names=('CorpusContractError',),
    imported_function_names=('canonical_dag_json_bytes', 'cid_for_dag_json', 'validate_cid'),
    alias_names=('Sequence', '_LOADED_OWNER_BUILTIN_V1', '_LOADED_OWNER_CLASSVAR_V1', '_LOADED_OWNER_EMPTY_METADATA_V1', '_LOADED_OWNER_FACTORY_V1', '_LOADED_OWNER_FIELD_KIND_V1', '_LOADED_OWNER_FIELD_V1', '_LOADED_OWNER_FUNCTION_V1', '_LOADED_OWNER_GETFRAME_V1', '_LOADED_OWNER_GETSET_V1', '_LOADED_OWNER_INITVAR_V1', '_LOADED_OWNER_MAPPING_V1', '_LOADED_OWNER_MEMBER_V1', '_LOADED_OWNER_METHOD_V1', '_LOADED_OWNER_MISSING_V1', '_LOADED_OWNER_MODULE_V1', '_LOADED_OWNER_PARAMS_V1', '_LOADED_OWNER_PATTERN_V1', '_LOADED_OWNER_SPEC_V1', '_LOADED_OWNER_WRAPPER_V1', '__builtins__', '__loader__', '__spec__', 'canonical_dag_json_bytes', 'cid_for_dag_json', 'hashlib', 'json', 'validate_cid'))
