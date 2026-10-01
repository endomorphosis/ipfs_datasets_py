"""Opt-in reuse of an identical LegalIR readout within one legacy encode call.

This does not cache predictions across calls, epochs, state changes or sources.
The first readout uses the unchanged frozen numerical implementation. Repeated
readouts receive fresh dictionaries, and the bounded memo is discarded even
when encoding raises. All old configuration and qualification guards remain.
"""
from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
import hashlib
from pathlib import Path

from .._contract import load_local_checkpoint
from . import linguistic
from . import daemon_teacher
from .linguistic_cached import CachedLinguisticAutoencoder, StreamedCachedLinguisticAutoencoder

_MEMO = ContextVar("legacy_linguistic_encode_view_memo", default=None)
_MAX_MEMO_ENTRIES = 8


def _source_identity(path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


class _EncodeViewReuse:
    """Compose the same readout optimization with either preserved codec."""

    def __init__(self, **options):
        self._view_reuse_path = Path(__file__).resolve()
        self._view_reuse_source_identity = _source_identity(self._view_reuse_path)
        self._view_reuse_source_sha256 = hashlib.sha256(self._view_reuse_path.read_bytes()).hexdigest()
        self._view_reuse_last = {"hits": 0, "misses": 0, "retained_after_encode": 0}
        super().__init__(**options)

    def _require_profile(self):
        super()._require_profile()
        if _source_identity(self._view_reuse_path) != self._view_reuse_source_identity:
            raise ValueError("legacy view reuse source changed; construct a new model in a fresh process")

    def encode(self, sample, **kwargs):
        scope = {"owner": self, "entries": {}, "hits": 0, "misses": 0}
        token = _MEMO.set(scope)
        try:
            return super().encode(sample, **kwargs)
        finally:
            scope["entries"].clear()
            self._view_reuse_last = {"hits": scope["hits"], "misses": scope["misses"],
                                     "retained_after_encode": 0}
            _MEMO.reset(token)

    def _legal_ir_view_distribution_for_embedding(self, sample, *, use_sample_memory):
        scope = _MEMO.get()
        if scope is None or scope["owner"] is not self:
            return super()._legal_ir_view_distribution_for_embedding(
                sample, use_sample_memory=use_sample_memory)
        # These checks remain active on a hit. The complete source includes
        # nested mutable parser/IR/frame fields; state revisions track sparse
        # writes, while explicit target values catch bridge-cache changes.
        self._require_profile()
        source_digest = hashlib.sha256(sample.to_json().encode()).digest()
        key = (id(self.state), self.state.state_revision, source_digest,
               bool(use_sample_memory),
               tuple(self._legal_ir_view_target_distribution_for_sample(sample).items()),
               tuple(self._legal_ir_view_family_candidates()))
        if key in scope["entries"]:
            scope["hits"] += 1
            return dict(scope["entries"][key])
        scope["misses"] += 1
        value = super()._legal_ir_view_distribution_for_embedding(
            sample, use_sample_memory=use_sample_memory)
        if len(scope["entries"]) < _MAX_MEMO_ENTRIES:
            scope["entries"][key] = dict(value)
        return value

    def describe(self):
        result = super().describe()
        result.update(runtime_profile=self._view_reuse_profile,
                      view_reuse_source_sha256=self._view_reuse_source_sha256,
                      view_reuse={"scope": "one encode call; no cross-call prediction retention",
                                  "max_entries": _MAX_MEMO_ENTRIES,
                                  "byte_bound": None,
                                  "memory_scope": "source JSON hashed transiently; retained readout sizes depend on IR family count",
                                  "last_encode": dict(self._view_reuse_last)})
        return result


class ViewReuseCachedLinguisticAutoencoder(_EncodeViewReuse, CachedLinguisticAutoencoder):
    _view_reuse_profile = "legacy-linguistic-bounded-cache-encode-view-reuse/v1"


class ViewReuseStreamedCachedLinguisticAutoencoder(_EncodeViewReuse, StreamedCachedLinguisticAutoencoder):
    _view_reuse_profile = "legacy-linguistic-bounded-cache-streamed-norms-encode-view-reuse/v1"


class ViewReuseHistoricalDaemonAutoencoder(_EncodeViewReuse, daemon_teacher.HistoricalDaemonAutoencoder):
    _view_reuse_profile = "legacy-daemon-linguistic-bm25-flogic-encode-view-reuse/v1"


_PROFILES = {"cached": ViewReuseCachedLinguisticAutoencoder,
             "streamed_cached": ViewReuseStreamedCachedLinguisticAutoencoder,
             "historical_daemon": ViewReuseHistoricalDaemonAutoencoder}


def _profile(name):
    if name not in _PROFILES:
        raise ValueError(f"view reuse profile must be one of {tuple(_PROFILES)}")
    return _PROFILES[name]


def load_checkpoint(path, *, expected_sha256, profile="historical_daemon", **model_options):
    """Load verified existing local weights under an explicitly chosen profile."""
    return load_local_checkpoint(_profile(profile), path, expected_sha256=expected_sha256,
                                 **model_options)


def load_training_checkpoint(directory, *, profile="historical_daemon", **cache_options):
    """Validate a preserved bundle, then opt into encode-local readout reuse.

    The weight/configuration bundle remains usable with its original runtime;
    this optimization makes no new representation or objective claim.
    """
    model_class = _profile(profile)
    if profile == "historical_daemon":
        if cache_options:
            raise ValueError("historical daemon profile uses its preserved cache configuration")
        original = daemon_teacher.load_training_checkpoint(directory)
        configuration = original._daemon_constructor_options
    else:
        if set(cache_options) - {"cache_max_entries", "cache_max_bytes"}:
            raise ValueError("only runtime cache bounds may override a preserved checkpoint")
        original = linguistic.load_training_checkpoint(directory)
        configuration = original._linguistic_options
    model = model_class(state=original.state, **configuration, **cache_options)
    if (model._linguistic_identity != original._linguistic_identity
            or model._linguistic_effective_configuration != original._linguistic_effective_configuration):
        raise ValueError("view reuse checkpoint identity changed during construction")
    model._checkpoint_identity = deepcopy(original._checkpoint_identity)
    return model


__all__ = ["ViewReuseCachedLinguisticAutoencoder", "ViewReuseStreamedCachedLinguisticAutoencoder",
           "ViewReuseHistoricalDaemonAutoencoder", "load_checkpoint", "load_training_checkpoint"]
