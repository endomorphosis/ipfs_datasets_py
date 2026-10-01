"""Opt-in bounded reuse of the preserved 8D linguistic feature encoding.

This is a runtime optimization, not a new representation or training objective.
All vectors, features, modal IR and numerical updates come from the frozen
implementations. Cache settings are deliberately absent from the semantic
checkpoint: a saved bundle also resumes with the original uncached profile.
The cache contains plain feature dataclasses, never resident spaCy ``Doc``s.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import fields, is_dataclass
import hashlib
import json
from pathlib import Path
import sys
from threading import RLock

from . import linguistic as _baseline
from .. import legacy_v1_optimized as _streamed_norms
from .._contract import load_local_checkpoint
from ._linguistic_snapshot.spacy_modal_codec import SpaCyModalCodec

RUNTIME_PROFILE = "legacy-linguistic-bounded-cache/v1"
STREAMED_RUNTIME_PROFILE = "legacy-linguistic-bounded-cache-streamed-norms/v1"
DEFAULT_CACHE_ENTRIES = 128
DEFAULT_CACHE_BYTES = 8 * 1024 * 1024


def _retained_bytes(value, seen=None):
    """Count the retained Python graph, including dataclass instance mappings."""
    seen = set() if seen is None else seen
    marker = id(value)
    if marker in seen:
        return 0
    seen.add(marker)
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        return size + sum(_retained_bytes(k, seen) + _retained_bytes(v, seen)
                          for k, v in value.items())
    if isinstance(value, (tuple, list, set, frozenset)):
        return size + sum(_retained_bytes(v, seen) for v in value)
    if is_dataclass(value):
        if hasattr(value, "__dict__"):
            return size + _retained_bytes(vars(value), seen)
        return size + sum(_retained_bytes(getattr(value, f.name), seen) for f in fields(value))
    return size


def _registry_configuration(registry):
    # Modal profiles/operators are frozen dataclasses whose children are tuples.
    # Copy the two mutable registry indexes so replacement cannot stale a hit.
    return (id(registry), tuple(sorted(registry._profiles.items())),
            tuple(sorted(registry._by_family.items(), key=lambda item: str(item[0]))))


class CachedSpaCyModalCodec(SpaCyModalCodec):
    """One bounded shared encoding for vector/family/features/IR requests.

    A lock prevents duplicate work and concurrent use of one spaCy pipeline.
    Different worker processes should own separate model/cache instances.
    Configuration drift fails closed; construct a new codec for another model.
    This does not cache bridge targets, proof results, weights or qualification.
    """

    def __init__(self, *, encoder=None, compiler=None, decoder=None,
                 max_entries=DEFAULT_CACHE_ENTRIES, max_bytes=DEFAULT_CACHE_BYTES):
        if type(max_entries) is not int or not 0 <= max_entries <= 4096:
            raise ValueError("cache max_entries must be an integer from 0 to 4096")
        if type(max_bytes) is not int or not 0 <= max_bytes <= 64 * 1024 * 1024:
            raise ValueError("cache max_bytes must be an integer from 0 to 64 MiB")
        super().__init__(encoder=encoder, compiler=compiler, decoder=decoder)
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._entries = OrderedDict()
        self._lock = RLock()
        self._bytes = 0
        self._hits = self._misses = self._evictions = self._oversized = 0
        self._encodes = self._compiles = 0
        self._initial_configuration = self._configuration()

    def _configuration(self):
        encoder = self.encoder
        return (id(encoder), id(self.compiler), id(self.decoder), id(encoder.nlp),
                encoder.model_name, encoder.used_fallback_model,
                encoder.nlp.config.to_str(),
                tuple((name, id(component)) for name, component in encoder.nlp.pipeline),
                _registry_configuration(encoder.registry),
                _registry_configuration(encoder._fallback_parser.registry),
                _registry_configuration(self.compiler._fallback_parser.registry),
                self.max_entries, self.max_bytes)

    def _require_configuration(self):
        if self._configuration() != self._initial_configuration:
            self._entries.clear()
            self._bytes = 0
            raise ValueError("cached linguistic codec configuration changed; construct a new codec")

    def clear_cache(self):
        """Discard retained features; cumulative telemetry remains available."""
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    def cache_info(self):
        with self._lock:
            return {"runtime_profile": RUNTIME_PROFILE, "entries": len(self._entries),
                    "retained_bytes": self._bytes, "max_entries": self.max_entries,
                    "max_bytes": self.max_bytes, "hits": self._hits, "misses": self._misses,
                    "encodes": self._encodes, "compiles": self._compiles,
                    "evictions": self._evictions, "oversized_skips": self._oversized,
                    "byte_accounting": "recursive_python_object_size_plus_entry_overhead"}

    @staticmethod
    def _key(sample):
        # Include unnormalized text as original text is part of the encoding.
        raw = json.dumps([sample.text, sample.sample_id, sample.citation, sample.source],
                         ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(raw).digest()

    def _retain(self, key, entry):
        if key in self._entries:
            self._bytes -= self._entries.pop(key)[1]
        # Include key and conservative OrderedDict bookkeeping, not just payload.
        size = _retained_bytes((key, entry)) + 256
        if not self.max_entries or size > self.max_bytes:
            self._oversized += 1
            return
        while self._entries and (len(self._entries) >= self.max_entries
                                 or self._bytes + size > self.max_bytes):
            _, (_, removed_size) = self._entries.popitem(last=False)
            self._bytes -= removed_size
            self._evictions += 1
        self._entries[key] = (entry, size)
        self._bytes += size

    def _entry(self, sample):
        self._require_configuration()
        key = self._key(sample)
        cached = self._entries.get(key)
        if cached is not None:
            self._hits += 1
            self._entries.move_to_end(key)
            return key, cached[0]
        self._misses += 1
        self._encodes += 1
        entry = {"encoding": super().encode_sample(sample)}
        self._retain(key, entry)
        return key, entry

    def encode_sample(self, sample):
        with self._lock:
            _, entry = self._entry(sample)
            # Frozen dataclasses still contain mutable lists: never expose them.
            return deepcopy(entry["encoding"])

    def compile_sample_ir(self, sample):
        with self._lock:
            key, entry = self._entry(sample)
            if "ir" not in entry:
                self._compiles += 1
                entry["ir"] = self.compiler.compile(entry["encoding"])
                self._retain(key, entry)
            return deepcopy(entry["ir"])

    def decode_sample_embedding(self, sample, *, dimensions):
        with self._lock:
            _, entry = self._entry(sample)
            return self.decoder.decode_embedding(entry["encoding"], dimensions=dimensions)

    def family_logits_for_sample(self, sample, *, modal_families):
        with self._lock:
            _, entry = self._entry(sample)
            return self.decoder.family_logits(entry["encoding"], modal_families=modal_families)

    def feature_keys_for_sample(self, sample):
        with self._lock:
            _, entry = self._entry(sample)
            # Preserve first occurrence/order exactly, including all features.
            return list(dict.fromkeys(self.decoder._feature_stream(entry["encoding"])))


class CachedLinguisticAutoencoder(_baseline.LinguisticAutoencoder):
    """Original 8D training with bounded parsing and complete sample cache keys.

    The frozen runtime omits citation/title/section and most IR metadata from
    its feature-cache key even though feature extraction reads those fields.
    Bind the complete sample here so two equal sentences in different source
    contexts have the same predictions and updates as separate fresh models.
    """

    def __init__(self, *, cache_max_entries=DEFAULT_CACHE_ENTRIES,
                 cache_max_bytes=DEFAULT_CACHE_BYTES, **legacy_options):
        super().__init__(**legacy_options)
        original = self._linguistic_codec
        cached = CachedSpaCyModalCodec(encoder=original.encoder, compiler=original.compiler,
                                      decoder=original.decoder, max_entries=cache_max_entries,
                                      max_bytes=cache_max_bytes)
        self._linguistic_codec = self.feature_codec = cached
        self._sample_feature_cache = OrderedDict()
        self._numerical_cache_max_entries = cache_max_entries

    def _sample_cache_for(self, sample):
        # LegalSample.to_json covers text, identity, citation, source, title,
        # section, embedding/model, complete modal IR, frame candidates, parser
        # trace and losses. Recompute to detect mutable nested sample fields;
        # object identity alone is insufficient for this frozen dataclass.
        digest = hashlib.sha256(sample.to_json().encode()).hexdigest()
        if not self._numerical_cache_max_entries:
            return {}
        # Historical ablation clones replace this field with a plain dict.
        if not isinstance(self._sample_feature_cache, OrderedDict):
            self._sample_feature_cache = OrderedDict(self._sample_feature_cache)
        key = ("complete-source/v1:" + digest, len(sample.embedding_vector))
        if key in self._sample_feature_cache:
            self._sample_feature_cache.move_to_end(key)
            return self._sample_feature_cache[key]
        while len(self._sample_feature_cache) >= self._numerical_cache_max_entries:
            self._sample_feature_cache.popitem(last=False)
        value = {}
        self._sample_feature_cache[key] = value
        return value

    def describe(self):
        result = super().describe()
        result.update({"runtime_profile": RUNTIME_PROFILE,
                       "cache_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "feature_cache_identity_policy": "complete-legal-sample-json/v1",
                       "numerical_feature_cache": {"entries": len(self._sample_feature_cache),
                                                   "max_entries": self._numerical_cache_max_entries,
                                                   "byte_bound": None},
                       "linguistic_cache": self._linguistic_codec.cache_info()})
        return result

    def linguistic_observation(self, sample):
        self._require_profile()
        self._samples([sample])
        codec = self._linguistic_codec
        encoding = codec.encode_sample(sample)
        ir = codec.compile_sample_ir(sample)
        return {"profile_id": _baseline.PROFILE_ID, "backend": self.backend,
                "linguistic_identity_sha256": self._linguistic_identity_sha256,
                "source_sha256": _baseline._sha(sample.text.encode()),
                "encoding": encoding.to_dict(), "modal_ir": ir.to_dict(),
                "decoded_feature_vector": codec.decoder.decode_embedding(encoding, dimensions=8),
                "feature_keys": list(codec.decoder._feature_stream(encoding)),
                "vector_origin": "deterministic_linguistic_feature_hash",
                "formula_origin": "frozen_linguistic_ir_compiler", **_baseline._FALSE}


class StreamedCachedLinguisticAutoencoder(CachedLinguisticAutoencoder):
    """Explicitly compose bounded parsing reuse with the existing norm port.

    Only transaction delta-norm bookkeeping changes. Update order, candidate
    acceptance, reconstruction objective and deadlines remain the old trainer's.
    This profile is never chosen automatically based on hardware or timings.
    """

    _apply_projection_update_batch_in_transaction = (
        _streamed_norms.Autoencoder._apply_projection_update_batch_in_transaction)

    def describe(self):
        result = super().describe()
        result.update({"runtime_profile": STREAMED_RUNTIME_PROFILE,
                       "speed_port_revision": _streamed_norms.PORT_REVISION,
                       "frozen_batch_method_sha256": _streamed_norms.FROZEN_BATCH_METHOD_SHA256})
        return result


def load_cached_checkpoint(path, *, expected_sha256, **model_options):
    """Read verified local legacy weights with the preserved cached codec.

    This binds the chosen linguistic backend, not the unknown original codec
    configuration of an older raw checkpoint. It never downloads weights.
    """
    return load_local_checkpoint(CachedLinguisticAutoencoder, path,
                                 expected_sha256=expected_sha256, **model_options)


def load_streamed_cached_checkpoint(path, *, expected_sha256, **model_options):
    """Read verified local weights with explicit streamed norm bookkeeping."""
    return load_local_checkpoint(StreamedCachedLinguisticAutoencoder, path,
                                 expected_sha256=expected_sha256, **model_options)


def load_cached_training_checkpoint(directory, *, cache_max_entries=DEFAULT_CACHE_ENTRIES,
                                    cache_max_bytes=DEFAULT_CACHE_BYTES):
    """Validate an ordinary preserved bundle, then opt into bounded reuse.

    Full source/model/configuration/core validation is delegated to the existing
    strict loader. Runtime caches are empty after load and never serialized.
    """
    return _load_training_checkpoint(directory, model_class=CachedLinguisticAutoencoder,
                                     cache_max_entries=cache_max_entries, cache_max_bytes=cache_max_bytes)


def load_streamed_cached_training_checkpoint(directory, *, cache_max_entries=DEFAULT_CACHE_ENTRIES,
                                             cache_max_bytes=DEFAULT_CACHE_BYTES):
    """Resume a strict linguistic bundle with the explicitly chosen norm port."""
    return _load_training_checkpoint(directory, model_class=StreamedCachedLinguisticAutoencoder,
                                     cache_max_entries=cache_max_entries, cache_max_bytes=cache_max_bytes)


def _load_training_checkpoint(directory, *, model_class, cache_max_entries, cache_max_bytes):
    original = _baseline.load_training_checkpoint(directory)
    model = model_class(state=original.state, cache_max_entries=cache_max_entries,
                        cache_max_bytes=cache_max_bytes, **original._linguistic_options)
    if (model._linguistic_identity != original._linguistic_identity
            or model._linguistic_effective_configuration != original._linguistic_effective_configuration):
        raise ValueError("cached linguistic checkpoint identity changed during construction")
    # Construction receives the already verified state object; preserve the
    # strict loader's file digest/provenance instead of describing it as fresh.
    model._checkpoint_identity = deepcopy(original._checkpoint_identity)
    return model


__all__ = ["CachedSpaCyModalCodec", "CachedLinguisticAutoencoder",
           "StreamedCachedLinguisticAutoencoder", "load_cached_checkpoint",
           "load_streamed_cached_checkpoint", "load_cached_training_checkpoint",
           "load_streamed_cached_training_checkpoint", "RUNTIME_PROFILE", "STREAMED_RUNTIME_PROFILE"]
