"""Separate cached-row input snapshots for retained 768D/4096D sessions.

Only the request-local output cache's unused digest is avoided. Checkpoint,
policy, lease, receipt, numerical output and tensor custody remain inherited.
These adapters are experimental; they do not change existing selected routes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
from pathlib import Path

from . import input_content_guard as input_guard
from . import legal_span_device_batch_inference as batched
from . import legal_span_device_bitwise_inference as native768
from . import legal_span_4096_bitwise_device_inference_v2 as native4096

PROFILE_768 = "native768-owned-bitwise-cached-input/v1"
PROFILE_4096 = "native4096-owned-bitwise-cached-input/v1"
_INPUT_GUARD = input_guard.InputContentGuard
_CACHE = batched._CachedOutput
_BATCH = batched._BATCH_AT_IMPORT
_DECODE = batched._DECODE_AT_IMPORT
_SPAN = batched.span
_NO_FORWARD = batched._NoForward
_OUTPUTS = batched._OUTPUTS
_BASE_768 = native768.DeviceBitwiseDimensionalSpanSession
_BASE_4096 = native4096.BitwiseDeviceLeanstral4096SpanSession
_PURE_768 = _BASE_768._pure_check
_PURE_4096 = _BASE_4096._pure_check
_DESCRIPTION_768 = _BASE_768._description
_DESCRIPTION_4096 = _BASE_4096._description
_CACHE_BIND = _CACHE.bind
_CACHE_CALL = _CACHE.__call__
_MODULES = (input_guard, batched, native768, native4096)
_HASH = hashlib.sha256
_READ = Path.read_bytes
_SOURCE_PATH = Path(__file__)
_SOURCE_AT_IMPORT = _HASH(_READ(_SOURCE_PATH)).hexdigest()
_SOURCE_PINS = tuple((Path(module.__file__), _HASH(_READ(Path(module.__file__))).hexdigest())
                     for module in _MODULES)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _fingerprint(value):
    prop = value if isinstance(value, property) else None
    value = prop.fget if prop is not None else getattr(value, "__func__", value)
    kwdefaults = getattr(value, "__kwdefaults__", None)
    return (prop, value, getattr(value, "__code__", None), getattr(value, "__defaults__", None),
            kwdefaults, tuple(kwdefaults.items()) if kwdefaults else ())


def _same(value, expected):
    observed = _fingerprint(value)
    return (all(left is right for left, right in zip(observed[:5], expected[:5]))
            and len(observed[5]) == len(expected[5]) and all(
                key is fixed_key and item is fixed_item
                for (key, item), (fixed_key, fixed_item) in zip(observed[5], expected[5])))


def _check_bindings():
    _require(_HASH(_READ(_SOURCE_PATH)).hexdigest() == _SOURCE_AT_IMPORT
             and all(_HASH(_READ(path)).hexdigest() == digest
                     for path, digest in _SOURCE_PINS), "cached-input adapter or dependency source changed")
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_FUNCTIONS)
             and all(_same(globals().get(name), expected) for name, expected in _OWN_ALIASES),
             "cached-input adapter helper or alias changed")
    _require(all(getattr(module, name) is expected for module, name, expected in _CLASS_BINDINGS)
             and all(_same(getattr(owner, name), expected) for owner, name, expected in _METHOD_BINDINGS),
             "cached-input adapter class or method changed")
    _require(all(_same(getattr(input_guard, name), expected) for name, expected in _INPUT_HELPERS)
             and all(globals().get(name) is expected for name, expected in _OWN_CLASSES),
             "cached-input guard helper or owner class changed")
    _require(type(PROFILE_768) is str and PROFILE_768 == _PROFILES[0]
             and type(PROFILE_4096) is str and PROFILE_4096 == _PROFILES[1],
             "cached-input profile changed")
    input_guard.inference_implementation()


def inference_implementation():
    _check_bindings()
    return {"schema": "native-span-cached-input-implementation/v1",
        "source_sha256": _SOURCE_AT_IMPORT,
        "input_guard_implementation": input_guard.inference_implementation(),
        "change_scope": "request_local_cached_row_binding_only_unused_digest",
        "checkpoint_and_receipt_digests_retained": True,
        "inherited_numerical_cache_checks_retained": True,
        "source_verification_success_cached": False,
        "existing_selected_route_changed": False, "performance_qualified": False,
        "native_leanstral_outputs_qualified": False, "production_qualified": False,
        "proof_authority": False, "execution_attestation": False}


class _InputCachedOutput(_CACHE):
    def __init__(self, torch, *, text, vector, tokens, output, enabled):
        _check_bindings()
        _require(type(self) is _InputCachedOutput, "exact cached-input output owner required")
        self._torch, self._enabled = torch, enabled
        self._binding = deepcopy({"text": text, "vector": vector, "tokens": tokens})
        self._binding_guard = _INPUT_GUARD(self._binding)
        guard = self._binding_guard
        self._guard_bindings = (guard, guard._reference, guard._canonical_bytes, guard._use_fast_comparison)
        self._guard_bindings_identity = self._guard_bindings
        self._expected = _BATCH(torch, [{"tokens": tokens, "latent": vector}])
        shapes = {"modality": (1, 3), "presence": (1, 4, 2),
                  "start": (1, 6, len(tokens)), "end": (1, 6, len(tokens))}
        _require(type(output) is dict and set(output) == set(_OUTPUTS) and all(
            isinstance(value, torch.Tensor) and str(value.device) == "cpu" and value.dtype == torch.float32
            and tuple(value.shape) == shapes[name] and bool(torch.isfinite(value).all())
            for name, value in output.items()), "closed finite CPU cached head tensors required")
        self._output = {name: value.detach().clone() for name, value in output.items()}
        self._reference = {name: value.detach().clone() for name, value in self._output.items()}
        self._used = False
        self.bind(text, vector)

    def _check_guard(self):
        _check_bindings()
        _require(type(self) is _InputCachedOutput and type(self._guard_bindings) is tuple
                 and self._guard_bindings is self._guard_bindings_identity and len(self._guard_bindings) == 4,
                 "cached-input guard binding snapshot changed")
        guard, reference, canonical, fast = self._guard_bindings
        _require(self._binding_guard is guard and type(guard) is _INPUT_GUARD
                 and guard._reference is reference and guard._canonical_bytes is canonical
                 and guard._use_fast_comparison is fast, "cached-input guard or immutable snapshot changed")

    def bind(self, text, vector):
        self._check_guard()
        return _CACHE_BIND(self, text, vector)

    def __call__(self, *inputs, enabled=True):
        self._check_guard()
        return _CACHE_CALL(self, *inputs, enabled=enabled)


def _decision(owner, text, vector, tokens, output, enabled):
    _check_bindings()
    torch = owner._torch
    surrogate = (_NO_FORWARD() if tokens is None else _InputCachedOutput(torch,
        text=text, vector=vector, tokens=tokens, output=output, enabled=enabled))
    # Keep an independent local anchor across decoding. Writable cache fields
    # cannot replace this tuple together with the guard to bless new inputs.
    guard = None if tokens is None else surrogate._binding_guard
    binding = None if guard is None else (
        guard, guard._reference, guard._canonical_bytes, guard._use_fast_comparison)
    if binding is not None:
        _check_cache_snapshot(surrogate, binding)
    decoder = _SPAN.SpanLegalFormulaDecoder.__new__(_SPAN.SpanLegalFormulaDecoder)
    decoder.torch, decoder.model = torch, surrogate
    decoder.checkpoint, decoder.checkpoint_sha256 = owner._checkpoint, owner.checkpoint_sha256
    result = _DECODE(decoder, text, vector, enabled=enabled)
    if binding is not None:
        _check_cache_snapshot(surrogate, binding)
    _require(tokens is None or surrogate._used, "valid source did not consume its bound numerical output")
    return result


def _check_cache_snapshot(cache, binding):
    _require(type(binding) is tuple and len(binding) == 4
             and type(cache) is _InputCachedOutput
             and cache._binding_guard is binding[0] and type(binding[0]) is _INPUT_GUARD
             and binding[0]._reference is binding[1]
             and binding[0]._canonical_bytes is binding[2]
             and binding[0]._use_fast_comparison is binding[3],
             "cached-input independent local guard snapshot changed")
    cache._check_guard()


def _check_owner(owner, expected):
    _check_bindings()
    bindings = next((methods for owner_class, methods in _RESOLVED_METHODS
                     if owner_class is expected), None)
    _require(bindings is not None and type(owner) is expected
             and all(_same(getattr(owner, name), fingerprint) for name, fingerprint in bindings),
             "cached-input session method resolution changed")


def _description(owner, inherited, profile):
    _check_owner(owner, type(owner))
    result = inherited(owner)
    result["inherited_cached_input_profile_id"] = result["profile_id"]
    if owner._optimized:
        result["profile_id"] = profile
    result["cached_input_profile_id"] = profile
    result["cached_input_implementation"] = inference_implementation()
    return result


class InputCachedDeviceDimensionalSpanSession(_BASE_768):
    def _pure_check(self):
        _check_owner(self, InputCachedDeviceDimensionalSpanSession)
        return _PURE_768(self)

    def _decision(self, text, vector, tokens, output, *, enabled):
        return _decision(self, text, vector, tokens, output, enabled)

    def _description(self):
        return _description(self, _DESCRIPTION_768, PROFILE_768)


class InputCachedDeviceLeanstral4096SpanSession(_BASE_4096):
    def _pure_check(self):
        _check_owner(self, InputCachedDeviceLeanstral4096SpanSession)
        return _PURE_4096(self)

    def _decision(self, text, vector, tokens, output, enabled):
        return _decision(self, text, vector, tokens, output, enabled)

    def _description(self):
        return _description(self, _DESCRIPTION_4096, PROFILE_4096)


_PROFILES = PROFILE_768, PROFILE_4096
_OWN_CLASSES = tuple((name, globals()[name]) for name in ("_InputCachedOutput",
    "InputCachedDeviceDimensionalSpanSession", "InputCachedDeviceLeanstral4096SpanSession"))
_OWN_FUNCTIONS = tuple((name, _fingerprint(value)) for name, value in list(globals().items())
                      if inspect.isfunction(value) and value.__module__ == __name__)
_OWN_ALIASES = tuple((name, _fingerprint(globals()[name])) for name in (
    "input_guard", "batched", "native768", "native4096", "_INPUT_GUARD", "_CACHE", "_BATCH", "_DECODE",
    "_SPAN", "_NO_FORWARD", "_OUTPUTS", "_BASE_768", "_BASE_4096", "_PURE_768", "_PURE_4096",
    "_DESCRIPTION_768", "_DESCRIPTION_4096", "_CACHE_BIND", "_CACHE_CALL", "deepcopy", "Path",
    "_HASH", "_READ", "_SOURCE_PATH"))
_INPUT_HELPERS = tuple((name, _fingerprint(value)) for name, value in vars(input_guard).items()
                      if inspect.isfunction(value) and value.__module__ == input_guard.__name__)
_CLASS_BINDINGS = ((input_guard, "InputContentGuard", _INPUT_GUARD), (batched, "_CachedOutput", _CACHE),
    (native768, "DeviceBitwiseDimensionalSpanSession", _BASE_768),
    (native4096, "BitwiseDeviceLeanstral4096SpanSession", _BASE_4096))
_METHOD_BINDINGS = tuple((owner, name, _fingerprint(getattr(owner, name)))
    for owner, names in ((_INPUT_GUARD, ("__init__", "matches", "check", "inference_implementation")),
        (_BASE_768, ("_pure_check", "_description")),
        (_BASE_4096, ("_pure_check", "_description")),
        (_CACHE, ("__init__", "bind", "__call__", "eval")),
        (_InputCachedOutput, ("__init__", "_check_guard", "bind", "__call__", "eval"))) for name in names)
_RESOLVED_METHODS = tuple((owner, tuple((name, _fingerprint(getattr(owner, name))) for name in (
    "__init__", "_check", "_pure_check", "_poll", "_operation", "_decision", "_description",
    "decode_formal_logic", "infer", "_synchronize", "_admit_batch_memory", "close"))
    ) for _, owner in _OWN_CLASSES[1:])

__all__ = ["InputCachedDeviceDimensionalSpanSession", "InputCachedDeviceLeanstral4096SpanSession",
           "PROFILE_768", "PROFILE_4096", "inference_implementation"]
