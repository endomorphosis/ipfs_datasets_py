"""Separate exact binding-inventory deduplication for held 768D/4096D heads.

Repeated inherited method records for exactly the same owner object and attribute
are checked once, preserving the first record. The immutable original inventory,
expected keys/counts and unchanged wrapped-method inventory remain bound. Every
fresh verifier invocation, input snapshot and numerical branch remains intact.

Only the outer request ``inputs_guard`` changes. Three source-pinned decode
methods retain their exact numerical branches, row caches, receipt and result
digests, checkpoints, byte anchors, tensor checks, polls and cleanup. Private
source-bound compilation avoids mutating any held module alias. The per-call
guard and its immutable root are retained independently in function locals.

This candidate does not select an existing route, qualify performance or
authenticate native Leanstral output. CPU opt-out and 4096D admission gates
remain inherited. No Torch or model is imported eagerly by this module.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import inspect
from pathlib import Path
from functools import wraps

from . import input_content_guard as input_guard
from . import legal_span_device_bitwise_inference as native768
from . import legal_span_4096_bitwise_device_inference_v2 as native4096

PROFILE_768 = "native-768-owned-bitwise-deduplicated-whole-call-input/v1"
PROFILE_4096 = "native-4096-owned-bitwise-deduplicated-whole-call-input/v1"
SCHEMA = "native-span-deduplicated-whole-call-input-implementation/v1"
_BASE_768 = native768.DeviceBitwiseDimensionalSpanSession
_BASE_4096 = native4096.BitwiseDeviceLeanstral4096SpanSession
_RESIDENT = native768.resident
_BATCHED = native768.batched
_COMBINED = native4096.inherited
_PURE_768, _PURE_4096 = _BASE_768._pure_check, _BASE_4096._pure_check
_DESCRIPTION_768, _DESCRIPTION_4096 = _BASE_768._description, _BASE_4096._description
_INPUT_GUARD = input_guard.InputContentGuard
_INPUT_IMPLEMENTATION = input_guard.inference_implementation
_INPUT_VERIFY = input_guard._verify_bindings
_HASH, _READ = hashlib.sha256, Path.read_bytes
_SOURCE_PATH = Path(__file__)
_SOURCE_AT_IMPORT = _HASH(_READ(_SOURCE_PATH)).hexdigest()
_SOURCE_PINS = (
    (input_guard, "aa3fefbe8a1ab4d81bf61ae9edf395a9070b3c0f94b728ee6fa5ddca0c81c325"),
    (native768, "d1c12eb54ca8c17c9815ed20db9237c86876361ac3d72fa30ce2d470b0fccf91"),
    (native4096, "14678654b927d0b6910fda6a8c82961978a9e7ebc29334aaae6cb2320abc5dc3"),
    (_RESIDENT, "4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5"),
    (_BATCHED, "5c916e7ab3b52f908731a6bab5dce83a31a7b6ad269445281c89ecd5cee07133"),
    (_COMBINED, "658382fb5b7bb30eb5e82a444b9ac9168b7557f5452a87a8ff59a5f883de55a8"),
)
_OWN_FUNCTIONS = _OWN_ALIASES = _OWN_CLASSES = _OWN_METHODS = _RESOLVED_METHODS = _COMPILED_BINDINGS = ()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _fingerprint(value):
    function = value.fget if isinstance(value, property) else getattr(value, "__func__", value)
    keywords = getattr(function, "__kwdefaults__", None)
    closure = getattr(function, "__closure__", None)
    return (value, function, getattr(function, "__code__", None), getattr(function, "__defaults__", None),
            keywords, tuple(keywords.items()) if keywords else (), closure,
            tuple(cell.cell_contents for cell in closure) if closure else (),
            getattr(function, "__wrapped__", None))


def _same(value, expected):
    actual = _fingerprint(value)
    return (all(left is right for left, right in zip(actual[:5], expected[:5]))
            and len(actual[5]) == len(expected[5]) and all(
                type(left_key) is type(right_key) and left_key == right_key
                and left_value is right_value
                for (left_key, left_value), (right_key, right_value) in zip(actual[5], expected[5]))
            and actual[6] is expected[6] and len(actual[7]) == len(expected[7])
            and all(left is right for left, right in zip(actual[7], expected[7]))
            and actual[8] is expected[8])


_BASE_MODULES = (native768, native4096, _RESIDENT, _BATCHED, _COMBINED)
_BASE_FUNCTIONS = tuple((module, name, _fingerprint(value)) for module in _BASE_MODULES
    for name, value in vars(module).items() if inspect.isfunction(value))
_BASE_CLASSES = tuple((module, name, value) for module in _BASE_MODULES for name, value in vars(module).items()
    if isinstance(value, type) and value.__module__ == module.__name__)
_BASE_METHODS_BEFORE_DEDUP = tuple((owner, name, _fingerprint(value)) for _, _, owner in _BASE_CLASSES
    for name, value in vars(owner).items() if isinstance(value, property) or inspect.isfunction(value)) + tuple(
    (owner, name, _fingerprint(getattr(owner, name))) for owner in (_BASE_768, _BASE_4096)
    for name in ("__init__", "_pure_check", "_description", "decode_formal_logic", "infer", "_poll", "_operation", "close"))
def _deduplicate_method_records(records):
    """Keep the first exact owner-identity/attribute record, retaining aliases."""
    seen, result = {}, []
    for record in records:
        _require(type(record) is tuple and len(record) == 3 and type(record[1]) is str,
                 "closed inherited method inventory record required")
        owner, name, expected = record
        key = (id(owner), name)
        if key not in seen:
            seen[key] = record
            result.append(record)
        else:
            _require(_same(expected[0], seen[key][2]), "duplicate inherited method fingerprints differ")
    return tuple(result)


_BASE_METHODS = _deduplicate_method_records(_BASE_METHODS_BEFORE_DEDUP)
_BASE_METHOD_KEYS_BEFORE_DEDUP = tuple((id(owner), name) for owner, name, _ in _BASE_METHODS_BEFORE_DEDUP)
_BASE_METHOD_KEYS = tuple((id(owner), name) for owner, name, _ in _BASE_METHODS)
_BASE_METHOD_KEYSET = frozenset(_BASE_METHOD_KEYS_BEFORE_DEDUP)
_BASE_METHOD_COUNTS = (len(_BASE_METHODS_BEFORE_DEDUP), len(_BASE_METHODS), len(_BASE_METHOD_KEYSET))
_require(_BASE_METHOD_KEYS == tuple(dict.fromkeys(_BASE_METHOD_KEYS_BEFORE_DEDUP))
         and len(_BASE_METHOD_KEYS) == len(set(_BASE_METHOD_KEYS))
         and frozenset(_BASE_METHOD_KEYS) == _BASE_METHOD_KEYSET,
         "deduplicated inherited method initial keys or first-record order differ")


_BASE_WRAPPED_METHODS = tuple((owner, name, value.__wrapped__, _fingerprint(value.__wrapped__))
    for owner, name, _ in _BASE_METHODS_BEFORE_DEDUP for value in (getattr(owner, name),)
    if getattr(value, "__wrapped__", None) is not None)
_BASE_METADATA = tuple((module, name, getattr(module, name)) for module in _BASE_MODULES
    for name in ("SCHEMA", "PROFILE", "CUDA_GRU_PROFILE", "DIMENSION") if hasattr(module, name))
_INPUT_FUNCTIONS = tuple((name, _fingerprint(value)) for name, value in vars(input_guard).items()
    if inspect.isfunction(value) and value.__module__ == input_guard.__name__)
_INPUT_CLASSES = tuple((name, value) for name, value in vars(input_guard).items()
    if isinstance(value, type) and value.__module__ == input_guard.__name__)
_INPUT_METHODS = tuple((owner, name, _fingerprint(value)) for _, owner in _INPUT_CLASSES
    for name, value in vars(owner).items() if isinstance(value, property) or inspect.isfunction(value))


def _check_method_inventory(*, _before=_BASE_METHODS_BEFORE_DEDUP, _after=_BASE_METHODS,
                            _before_keys=_BASE_METHOD_KEYS_BEFORE_DEDUP, _after_keys=_BASE_METHOD_KEYS,
                            _keyset=_BASE_METHOD_KEYSET, _counts=_BASE_METHOD_COUNTS):
    """Fresh custody of immutable inventories whose exact keys were admitted once.

    Tuple/frozenset membership cannot mutate. Captured identities therefore
    preserve the independently admitted keys and order without rehashing them.
    Every distinct live owner attribute is freshly fingerprinted afterwards.
    """
    _require(_BASE_METHODS_BEFORE_DEDUP is _before and _BASE_METHODS is _after
             and _BASE_METHOD_KEYS_BEFORE_DEDUP is _before_keys and _BASE_METHOD_KEYS is _after_keys
             and _BASE_METHOD_KEYSET is _keyset and _BASE_METHOD_COUNTS is _counts,
             "deduplicated inherited method inventory identity changed")
    _require((len(_before), len(_after), len(_keyset)) == _counts
             and len(_before_keys) == _counts[0] and len(_after_keys) == _counts[1] == _counts[2],
             "deduplicated inherited method inventory count or keyset changed")


def _check_bindings():
    _check_method_inventory()
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_FUNCTIONS)
             and all(_same(globals().get(name), expected) for name, expected in _OWN_ALIASES),
             "whole-input owner helper or alias changed")
    _require(_HASH(_READ(_SOURCE_PATH)).hexdigest() == _SOURCE_AT_IMPORT
             and all(_HASH(_READ(Path(module.__file__))).hexdigest() == digest for module, digest in _SOURCE_PINS),
             "whole-input owner or pinned source changed")
    _require(all(_same(getattr(module, name), expected) for module, name, expected in _BASE_FUNCTIONS)
             and all(getattr(module, name) is expected for module, name, expected in _BASE_CLASSES)
             and all(_same(getattr(owner, name), expected) for owner, name, expected in _BASE_METHODS)
             and all(getattr(getattr(owner, name), "__wrapped__", None) is function and _same(function, expected)
                     for owner, name, function, expected in _BASE_WRAPPED_METHODS)
             and all(type(getattr(module, name)) is type(value) and getattr(module, name) == value
                     for module, name, value in _BASE_METADATA),
             "whole-input inherited class, method, function or profile changed")
    _require(all(_same(getattr(input_guard, name), expected) for name, expected in _INPUT_FUNCTIONS)
             and all(getattr(input_guard, name) is expected for name, expected in _INPUT_CLASSES)
             and all(_same(getattr(owner, name), expected) for owner, name, expected in _INPUT_METHODS),
             "whole-input guard class, function or method changed")
    _require(all(globals().get(name) is owner for name, owner in _OWN_CLASSES)
             and all(_same(getattr(owner, name), expected) for owner, name, expected in _OWN_METHODS)
             and all(getattr(getattr(owner, name), "__wrapped__", None) is function and _same(function, expected)
                     for owner, name, function, expected in _OWN_WRAPPED_METHODS),
             "whole-input owner class or method changed")
    for function, expected, namespace, bindings, originals in _COMPILED_BINDINGS:
        _require(_same(function, expected) and function.__globals__ is namespace
                 and set(namespace) == {name for name, _ in bindings}
                 and all(_same(namespace[name], value) for name, value in bindings)
                 and all(_same(getattr(module, name), value) for module, name, value in originals),
                 "whole-input source-bound decode code or namespace changed")
    # This verifies all helper callable/default identities without formatting
    # a discarded public implementation receipt. Its fixed source was freshly
    # compared above; actual guard construction/comparison repeats its verifier.
    _INPUT_VERIFY()


def _check_owner(owner, expected=None, *, _verify=_check_bindings):
    # Retain the source verifier in this private callable's default. A live
    # module alias replacement cannot bypass the very identity check that
    # refuses it. Public method closures retain this owner verifier likewise.
    _verify()
    record = next((methods for cls, methods in _RESOLVED_METHODS if type(owner) is cls), None)
    _require(record is not None and (expected is None or type(owner) is expected),
             "exact whole-input span owner required")
    for name, fingerprint in record:
        actual = getattr(type(owner), name) if isinstance(fingerprint[0], property) else getattr(owner, name)
        actual = getattr(actual, "__func__", actual)
        _require(_same(actual, fingerprint), "whole-input private owner method resolution changed")


def _snapshot(guard):
    _require(type(guard) is _INPUT_GUARD, "exact whole-input guard required")
    pending, seen, wrappers = [guard._reference], set(), []
    while pending:
        item = pending.pop()
        kind = type(item)
        if kind not in (input_guard._Object, input_guard._Array):
            continue
        _require(id(item) not in seen, "whole-input reference wrapper alias or cycle changed")
        seen.add(id(item))
        if kind is input_guard._Object:
            _require(type(item.fields) is tuple and type(item.keys) is frozenset
                     and all(type(pair) is tuple and len(pair) == 2 for pair in item.fields),
                     "closed whole-input object reference wrapper required")
            wrappers.append((item, kind, item.fields, item.keys))
            pending.extend(value for _, value in item.fields)
        else:
            _require(type(item.items) is tuple and type(item.atoms) is bool,
                     "closed whole-input array reference wrapper required")
            wrappers.append((item, kind, item.items, item.atoms))
            if not item.atoms:
                pending.extend(item.items)
    return guard, guard._reference, guard._canonical_bytes, guard._use_fast_comparison, tuple(wrappers)


def _check_snapshot(guard, snapshot):
    _require(type(snapshot) is tuple and len(snapshot) == 5 and guard is snapshot[0]
             and type(guard) is _INPUT_GUARD and guard._reference is snapshot[1]
             and guard._canonical_bytes is snapshot[2] and guard._use_fast_comparison is snapshot[3]
             and type(snapshot[4]) is tuple and all(
                 type(item) is kind and (item.fields is first and item.keys is second
                    if kind is input_guard._Object else item.items is first and item.atoms is second)
                 for item, kind, first, second in snapshot[4]),
             "whole-input independent local guard or immutable snapshot changed")


def _whole_inputs_check(owner, guard, snapshot, current):
    _check_owner(owner)
    _check_snapshot(guard, snapshot)
    guard.check(current, message="checkpoint content changed")
    _check_owner(owner)
    _check_snapshot(guard, snapshot)


def _public_input_profile(owner, profile, guard, snapshot):
    _check_owner(owner)
    _check_snapshot(guard, snapshot)
    _require(type(guard._use_fast_comparison) is bool, "plain whole-input comparison mode required")
    profile["whole_input_guard_currentness"] = {
        "schema": "span-whole-call-input-currentness/v1",
        "guard_object_and_immutable_snapshot_identities_checked": True,
        "nested_reference_wrapper_field_identities_checked": True,
        "atom_array_scalar_reference_nodes_traversed": False,
        "comparison": "immutable-input-structural-content-with-canonical-json-fallback/v1",
        "scope": "independent_function_local_guard_and_snapshot_checked_before_and_after_full_call",
        "fast_comparison": guard._use_fast_comparison,
        "standard_finite_input_snapshot_canonical_json_serialized": False,
        "proof_authority": False, "execution_attestation": False,
    }
    return profile


def _compile_decode(module, owner_name, function_name, *, resident_opt_out=None):
    """Compile one fixed method with a closed, narrowly checked AST delta."""
    source = _READ(Path(module.__file__))
    expected = next(digest for candidate, digest in _SOURCE_PINS if candidate is module)
    _require(_HASH(source).hexdigest() == expected, "whole-input decode source differs before compilation")
    tree = ast.parse(source, filename=module.__file__)
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner_name)
    original = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "decode_formal_logic")
    changed = deepcopy(original)
    delta = {"outer_input_constructor": 0, "final_input_comparison": 0, "public_input_profile": 0, "resident_opt_out": 0}

    class Substitute(ast.NodeTransformer):
        def visit_Assign(self, node):
            if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "inputs_guard"):
                _require(isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                         and node.value.func.id == "CheckpointContentGuard" and len(node.value.args) == 1
                         and isinstance(node.value.args[0], ast.Name) and node.value.args[0].id == "authored"
                         and not node.value.keywords, "exact outer input constructor seam required")
                node.value.func = ast.Name(id="_INPUT_GUARD", ctx=ast.Load())
                delta["outer_input_constructor"] += 1
                snapshot = ast.parse("_input_snapshot = _snapshot(inputs_guard)\n_check_snapshot(inputs_guard, _input_snapshot)").body
                return [node, *snapshot]
            return self.generic_visit(node)

        def visit_Call(self, node):
            if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "inputs_guard" and node.func.attr == "check"):
                _require(len(node.args) == 1 and not node.keywords, "exact final input comparison seam required")
                delta["final_input_comparison"] += 1
                return ast.Call(func=ast.Name(id="_whole_inputs_check", ctx=ast.Load()),
                    args=[ast.Name(id="self", ctx=ast.Load()), ast.Name(id="inputs_guard", ctx=ast.Load()),
                          ast.Name(id="_input_snapshot", ctx=ast.Load()), node.args[0]], keywords=[])
            if (resident_opt_out is not None and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "decode_formal_logic" and isinstance(node.func.value, ast.Call)
                    and isinstance(node.func.value.func, ast.Name) and node.func.value.func.id == "super"):
                _require(not node.func.value.args and not node.func.value.keywords, "exact resident opt-out seam required")
                delta["resident_opt_out"] += 1
                return ast.Call(func=ast.Name(id="_RESIDENT_WHOLE_INPUT", ctx=ast.Load()),
                    args=[ast.Name(id="self", ctx=ast.Load()), *node.args], keywords=node.keywords)
            return self.generic_visit(node)

        def visit_Dict(self, node):
            for index, key in enumerate(node.keys):
                if isinstance(key, ast.Constant) and key.value == "execution_profile":
                    value = node.values[index]
                    _require(isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                             and isinstance(value.func.value, ast.Name) and value.func.value.id == "self"
                             and value.func.attr == "_description" and not value.args and not value.keywords,
                             "exact public profile seam required")
                    node.values[index] = ast.Call(func=ast.Name(id="_public_input_profile", ctx=ast.Load()),
                        args=[ast.Name(id="self", ctx=ast.Load()), value, ast.Name(id="inputs_guard", ctx=ast.Load()),
                              ast.Name(id="_input_snapshot", ctx=ast.Load())], keywords=[])
                    delta["public_input_profile"] += 1
            return self.generic_visit(node)

    changed = Substitute().visit(changed)
    _require(delta == {"outer_input_constructor": 1, "final_input_comparison": 1,
                      "public_input_profile": 1, "resident_opt_out": int(resident_opt_out is not None)},
             "whole-input decode AST delta differs from closed substitution")
    changed.name = function_name
    _require(not changed.decorator_list, "undecorated held decode method required")
    ast.fix_missing_locations(changed)
    names = {node.id for node in ast.walk(changed) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    originals = tuple((module, name, _fingerprint(vars(module)[name])) for name in sorted(names & vars(module).keys()))
    namespace = {name: vars(module)[name] for _, name, _ in originals}
    namespace.update(__name__=__name__, __builtins__=__builtins__, _INPUT_GUARD=_INPUT_GUARD,
        _snapshot=_snapshot, _check_snapshot=_check_snapshot, _whole_inputs_check=_whole_inputs_check,
        _public_input_profile=_public_input_profile)
    if resident_opt_out is not None:
        namespace["_RESIDENT_WHOLE_INPUT"] = resident_opt_out
    executable = ast.Module(body=[changed], type_ignores=[])
    exec(compile(executable, str(_SOURCE_PATH), "exec"), namespace)
    function = namespace[function_name]
    bindings = tuple((name, _fingerprint(value)) for name, value in namespace.items())
    record = (function, _fingerprint(function), namespace, bindings, originals)
    receipt = (module.__name__.rsplit(".", 1)[-1], owner_name, "decode_formal_logic", expected,
               tuple(sorted(delta.items())), _HASH(ast.dump(original, include_attributes=False).encode()).hexdigest(),
               _HASH(ast.dump(changed, include_attributes=False).encode()).hexdigest())
    return function, record, receipt


_RESIDENT_WHOLE_INPUT, _RESIDENT_BINDING, _RESIDENT_ADAPTATION = _compile_decode(
    _RESIDENT, "DeviceDimensionalSpanSession", "_decode_768_resident")
_DECODE_768, _BATCHED_BINDING, _BATCHED_ADAPTATION = _compile_decode(
    _BATCHED, "DeviceBatchedDimensionalSpanSession", "_decode_768_batched", resident_opt_out=_RESIDENT_WHOLE_INPUT)
_DECODE_4096, _COMBINED_BINDING, _COMBINED_ADAPTATION = _compile_decode(
    _COMBINED, "DeviceLeanstral4096SpanSession", "_decode_4096")
_COMPILED_BINDINGS = _RESIDENT_BINDING, _BATCHED_BINDING, _COMBINED_BINDING
_ADAPTATIONS = _RESIDENT_ADAPTATION, _BATCHED_ADAPTATION, _COMBINED_ADAPTATION


def inference_implementation():
    _check_bindings()
    return {"schema": SCHEMA, "source_sha256": _SOURCE_AT_IMPORT,
        "binding_inventory_deduplication": {"schema": "exact-owner-attribute-binding-inventory/v1",
            "key_policy": "exact_owner_object_identity_and_attribute_name",
            "original_record_count": _BASE_METHOD_COUNTS[0], "checked_record_count": _BASE_METHOD_COUNTS[1],
            "removed_duplicate_record_count": _BASE_METHOD_COUNTS[0] - _BASE_METHOD_COUNTS[1],
            "original_distinct_key_count": _BASE_METHOD_COUNTS[2],
            "checked_distinct_key_count": len(_BASE_METHOD_KEYS),
            "first_record_preserved": True, "original_inventory_identity_checked": True,
            "expected_counts_keys_and_order_checked": True,
            "wrapped_binding_inventory_deduplicated": False, "freshness_success_cached": False},
        "profiles": {"768": PROFILE_768, "4096": PROFILE_4096},
        "input_guard_implementation": _INPUT_IMPLEMENTATION(),
        "inherited_owner_source_sha256": {"768": _SOURCE_PINS[1][1], "4096": _SOURCE_PINS[2][1]},
        "source_bound_decode_adaptations": [{"source_role": role, "class": owner, "method": method,
            "source_sha256": digest, "closed_ast_substitution_counts": dict(delta),
            "original_method_ast_sha256": original, "adapted_method_ast_sha256": changed}
            for role, owner, method, digest, delta, original, changed in _ADAPTATIONS],
        "change_scope": "outer_whole_call_input_guard_only_independent_local_immutable_snapshot",
        "checkpoint_receipt_policy_lease_and_result_guards_retained": True,
        "row_cache_and_numerical_paths_retained": True, "all_existing_boundary_and_per_row_polls_retained": True,
        "nested_reference_wrapper_field_identities_bound": True,
        "atom_array_scalar_snapshot_traversal_performed": False,
        "copied_decode_globals_are_private_and_source_bound": True,
        "source_verification_success_cached": False, "boundary_consolidation_performed": False,
        "cached_row_input_substitution_performed": False, "lease_cadence_substitution_performed": False,
        "existing_selected_route_changed": False, "performance_qualified": False,
        "native_leanstral_outputs_qualified": False, "trained4096_qualification_established": False,
        "production_qualified": False, "proof_authority": False, "execution_attestation": False}


def _description(owner, inherited, profile):
    _check_owner(owner)
    result = inherited(owner)
    result["whole_input_guard_inherited_profile_id"] = result["profile_id"]
    result["whole_input_guard_profile_id"] = result["session_profile_id"] = profile
    if owner._optimized:
        result["profile_id"] = profile
    result["whole_input_guard_implementation"] = inference_implementation()
    return result


def _bound_owner_method(method):
    """Retain the verifier across live module helper-alias replacement."""
    verify = _check_owner
    @wraps(method)
    def guarded(owner, *args, **kwargs):
        verify(owner)
        return method(owner, *args, **kwargs)
    return guarded


class DeduplicatedWholeInputDeviceDimensionalSpanSession(_BASE_768):
    @_bound_owner_method
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, optimized=True,
                 scheduler=None, parent_lease=None, cancel_event=None,
                 admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=0):
        _check_owner(self, DeduplicatedWholeInputDeviceDimensionalSpanSession)
        super().__init__(checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256, optimized=optimized,
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, max_seconds=max_seconds,
            memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb, unified_memory_mb=unified_memory_mb)

    @_bound_owner_method
    def _pure_check(self):
        _check_owner(self, DeduplicatedWholeInputDeviceDimensionalSpanSession)
        return _PURE_768(self)

    @_bound_owner_method
    def _description(self):
        return _description(self, _DESCRIPTION_768, PROFILE_768)

    @_bound_owner_method
    def decode_formal_logic(self, texts, latents, *, latent_ablation="none",
                            embedding_receipts=None, expected_receipt_sha256s=None):
        _check_owner(self, DeduplicatedWholeInputDeviceDimensionalSpanSession)
        result = _DECODE_768(self, texts, latents, latent_ablation=latent_ablation,
            embedding_receipts=embedding_receipts, expected_receipt_sha256s=expected_receipt_sha256s)
        _check_owner(self, DeduplicatedWholeInputDeviceDimensionalSpanSession)
        return result

    infer = decode_formal_logic


class DeduplicatedWholeInputDeviceLeanstral4096SpanSession(_BASE_4096):
    @_bound_owner_method
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, optimized=True,
                 synthetic_unreceipted=False, scheduler=None, parent_lease=None,
                 cancel_event=None, admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=0):
        _check_owner(self, DeduplicatedWholeInputDeviceLeanstral4096SpanSession)
        super().__init__(checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256, optimized=optimized,
            synthetic_unreceipted=synthetic_unreceipted, scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds, max_seconds=max_seconds,
            memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb, unified_memory_mb=unified_memory_mb)

    @_bound_owner_method
    def _pure_check(self):
        _check_owner(self, DeduplicatedWholeInputDeviceLeanstral4096SpanSession)
        return _PURE_4096(self)

    @_bound_owner_method
    def _description(self):
        return _description(self, _DESCRIPTION_4096, PROFILE_4096)

    @_bound_owner_method
    def decode_formal_logic(self, texts, latents, *, latent_ablation="none",
                            embedding_receipts=None, expected_receipt_sha256s=None):
        _check_owner(self, DeduplicatedWholeInputDeviceLeanstral4096SpanSession)
        result = _DECODE_4096(self, texts, latents, latent_ablation=latent_ablation,
            embedding_receipts=embedding_receipts, expected_receipt_sha256s=expected_receipt_sha256s)
        _check_owner(self, DeduplicatedWholeInputDeviceLeanstral4096SpanSession)
        return result

    infer = decode_formal_logic


_METHOD_NAMES = ("__init__", "_check", "_pure_check", "_poll", "_operation", "_description", "_decision",
    "decode_formal_logic", "infer", "_synchronize", "_admit_batch_memory", "_lease_binding", "close",
    "_reference_byte_plan", "_reference_state_bytes", "_check_reference_anchor", "checkpoint")
_OWN_CLASSES = (("DeduplicatedWholeInputDeviceDimensionalSpanSession", DeduplicatedWholeInputDeviceDimensionalSpanSession),
                ("DeduplicatedWholeInputDeviceLeanstral4096SpanSession", DeduplicatedWholeInputDeviceLeanstral4096SpanSession))
_OWN_METHODS = tuple((owner, name, _fingerprint(value)) for _, owner in _OWN_CLASSES
    for name, value in vars(owner).items() if isinstance(value, property) or inspect.isfunction(value))
_OWN_WRAPPED_METHODS = tuple((owner, name, value.__wrapped__, _fingerprint(value.__wrapped__))
    for _, owner in _OWN_CLASSES for name, value in vars(owner).items() if getattr(value, "__wrapped__", None) is not None)
_RESOLVED_METHODS = tuple((owner, tuple((name, _fingerprint(getattr(owner, name))) for name in _METHOD_NAMES))
                         for _, owner in _OWN_CLASSES)
_OWN_FUNCTIONS = tuple((name, _fingerprint(value)) for name, value in list(globals().items())
    if inspect.isfunction(value) and value.__module__ == __name__)
_OWN_ALIASES = tuple((name, _fingerprint(globals()[name])) for name in ("input_guard", "native768", "native4096",
    "_BASE_768", "_BASE_4096", "_RESIDENT", "_BATCHED", "_COMBINED", "_PURE_768", "_PURE_4096",
    "_DESCRIPTION_768", "_DESCRIPTION_4096", "_INPUT_GUARD", "_INPUT_IMPLEMENTATION", "_INPUT_VERIFY",
    "_HASH", "_READ", "_SOURCE_PATH", "_SOURCE_PINS", "_SOURCE_AT_IMPORT", "_BASE_MODULES",
    "_COMPILED_BINDINGS", "_ADAPTATIONS", "_OWN_CLASSES", "_RESOLVED_METHODS", "_METHOD_NAMES",
    "_OWN_WRAPPED_METHODS", "_BASE_WRAPPED_METHODS",
    "_BASE_FUNCTIONS", "_BASE_CLASSES", "_BASE_METHODS", "_BASE_METHODS_BEFORE_DEDUP",
    "_BASE_METHOD_KEYS_BEFORE_DEDUP", "_BASE_METHOD_KEYS", "_BASE_METHOD_KEYSET", "_BASE_METHOD_COUNTS",
    "_RESIDENT_WHOLE_INPUT", "_DECODE_768", "_DECODE_4096", "PROFILE_768", "PROFILE_4096", "SCHEMA",
    "ast", "deepcopy", "inspect", "Path", "wraps"))

__all__ = ["DeduplicatedWholeInputDeviceDimensionalSpanSession", "DeduplicatedWholeInputDeviceLeanstral4096SpanSession",
           "PROFILE_768", "PROFILE_4096", "SCHEMA", "inference_implementation"]
