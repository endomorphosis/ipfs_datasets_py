"""Invocation-local, explicitly bound Arrow feature weights for the daemon.

Only the initial feature map changes representation. Native transactions,
capacity pruning, rollback and full checkpoint persistence retain their rules.
An owner supplies immutable artifacts and closes this session after all users
have detached their snapshots; this context confers no admission authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import threading

from .autoencoder_daemon_invocation_contracts import (
    MAX_ARROW_FEATURE_WEIGHT_BYTES, MAX_CHECKPOINT_BYTES, canonical, reference, verify,
)
from .modal_autoencoder_arrow_weights import (
    MappedFeatureEmbeddingWeights, load_feature_embedding_weights_ipc,
)

_CURRENT = ContextVar("autoencoder_daemon_weight_session", default=None)
_COMPONENT = "feature_embedding_weights"
_MAX_BOUNDARIES = 128


class DaemonWeightSessionError(ValueError):
    """A bound weight session cannot safely continue."""


def _detached(value):
    return json.loads(canonical(value))


def current_weight_session():
    return _CURRENT.get()


@contextmanager
def weight_session(session):
    """Install an owner session without transferring its close ownership."""
    if type(session) is not VerifiedDaemonWeightSession:
        raise DaemonWeightSessionError("expected an exact verified weight session")
    session._require_open()
    if _CURRENT.get() is not None:
        raise DaemonWeightSessionError("a daemon weight session is already installed")
    token = _CURRENT.set(session)
    try:
        yield session
    finally:
        _CURRENT.reset(token)


class VerifiedDaemonWeightSession:
    """An immutable mapped base and one native state's private update overlay.

Attachment is restricted to the constructing thread and an idle native state.
It does not normalize/rebuild that state or advance its operational revision.
Later native component/state replacements are observed, never reattached.
"""

    def __init__(self, arrow_ref, *, base_artifact, base_identity):
        self._thread = threading.get_ident()
        self._closed = self._poisoned = self._base_verified = self._attached = False
        self._storage = "not_attached"
        self._first_detachment = None
        self._boundaries = []
        self._boundary_checks = 0
        self._bound = self._state = self._mapped = None
        self._last_bound_statistics = None
        self._provenance = None
        try:
            self._arrow_ref = reference(arrow_ref, MAX_ARROW_FEATURE_WEIGHT_BYTES, with_path=True)
            self._base_artifact = reference(base_artifact, MAX_CHECKPOINT_BYTES, with_path=True)
            if type(base_identity) is not dict:
                raise DaemonWeightSessionError("base identity must be a detached native identity record")
            self._base_identity = _detached(base_identity)
            verify(self._base_artifact, MAX_CHECKPOINT_BYTES)
            self._mapped = load_feature_embedding_weights_ipc(
                self._arrow_ref["path"], expected_sha256=self._arrow_ref["sha256"],
                expected_size_bytes=self._arrow_ref["bytes"],
                expected_base_checkpoint_sha256=self._base_artifact["sha256"],
            )
        except BaseException:
            self._poisoned = True
            self.close()
            raise

    def _require_open(self):
        if threading.get_ident() != self._thread:
            raise DaemonWeightSessionError("weight session requires its creating thread")
        if self._closed or self._poisoned:
            raise DaemonWeightSessionError("weight session is closed or poisoned")

    @staticmethod
    def _require_state(state):
        from .modal_autoencoder import ModalAutoencoderTrainingState
        if type(state) is not ModalAutoencoderTrainingState:
            raise DaemonWeightSessionError("expected an exact native training state")
        if state._active_state_transaction is not None:
            raise DaemonWeightSessionError("weight attachment requires no active state transaction")

    def verify_base_state(self, state):
        """Reconcile the exact full base identity, row order and float bits."""
        try:
            self._require_open()
            self._require_state(state)
            with state._state_transaction_guard:
                self._require_state(state)
                if canonical(state.state_identity_record().to_dict()) != canonical(self._base_identity):
                    raise DaemonWeightSessionError("loaded state differs from the bound base identity/revision")
                rows = state.feature_embedding_weights
                if any(type(key) is not str or any(type(value) is not float for value in row)
                       for key, row in rows.items()):
                    raise DaemonWeightSessionError("base feature rows must already contain string keys and float scalars")
                self._mapped.verify_source_rows(rows)
                self._mapped.verify_unchanged()
                stats = self._mapped.statistics
                self._provenance = {
                    "schema": "autoencoder-daemon-feature-weights-v1",
                    "component": _COMPONENT, "storage": "arrow_cow_float64",
                    "artifact": {key: self._arrow_ref[key] for key in ("sha256", "bytes")},
                    "base_artifact": {key: self._base_artifact[key] for key in ("sha256", "bytes")},
                    "base_identity": self._base_identity,
                    "row_count": stats["base_rows"], "scalar_count": stats["scalar_count"],
                    "normalization": "legacy-str-key-float64-v1",
                    "whole_training_zero_copy": False, "full_checkpoint_authoritative": True,
                }
                self._base_verified = True
        except BaseException:
            self._poisoned = True
            raise

    def attach(self, state):
        """Bind only feature weights in place, retaining all other fields."""
        original = None
        try:
            self._require_open()
            if self._attached:
                raise DaemonWeightSessionError("weight session has already attached a state")
            self._require_state(state)
            with state._state_transaction_guard:
                self.verify_base_state(state)
                original = state.feature_embedding_weights
                tracker = state._state_identity_tracker
                bound = tracker.track_component(_COMPONENT, self._mapped, mutation=False)
                object.__setattr__(state, _COMPONENT, bound)
                try:
                    bound.verify_source_rows(original)
                    if canonical(state.state_identity_record().to_dict()) != canonical(self._base_identity):
                        raise DaemonWeightSessionError("weight attachment changed state identity or revision")
                    self._mapped.verify_unchanged()
                except BaseException:
                    # Restore the tracker and field without recording a mutation.
                    restored = tracker.track_component(_COMPONENT, original, mutation=False)
                    object.__setattr__(state, _COMPONENT, restored)
                    raise
                self._bound, self._state = bound, state
                self._attached = True
                self._storage = "mapped_overlay"
            return state
        except BaseException:
            self._poisoned = True
            raise

    def verify_boundary(self, phase, state=None):
        """Verify immutable bytes and report native representation changes."""
        try:
            self._require_open()
            if type(phase) is not str or not 0 < len(phase) <= 128:
                raise DaemonWeightSessionError("weight boundary requires a bounded phase name")
            self._mapped.verify_unchanged()
            if self._attached:
                state = self._state if state is None else state
                from .modal_autoencoder import ModalAutoencoderTrainingState
                if type(state) is not ModalAutoencoderTrainingState:
                    raise DaemonWeightSessionError("weight boundary requires an exact native state")
                self._state = state
                current = state.feature_embedding_weights
                mapped = (type(current) is MappedFeatureEmbeddingWeights
                          and current._base is self._mapped._base)
                from .modal_autoencoder_state_version import _TrackedDict
                if not mapped and type(current) not in (dict, _TrackedDict):
                    raise DaemonWeightSessionError("feature weights detached to an unbound representation")
                self._storage = "mapped_overlay" if mapped else "detached_native"
                if not mapped and self._first_detachment is None:
                    self._first_detachment = phase
                if mapped:
                    self._bound = current
                elif self._bound is not None:
                    # Tracked callbacks retain their former state. Keep only
                    # detached counters after native whole-state replacement.
                    self._last_bound_statistics = dict(self._bound.statistics)
                    self._bound = None
            self._boundary_checks += 1
            self._boundaries.append({"phase": phase, "storage": self._storage})
            del self._boundaries[:-_MAX_BOUNDARIES]
        except BaseException:
            self._poisoned = True
            raise

    def provenance(self):
        if not self._base_verified:
            raise DaemonWeightSessionError("base state has not been verified")
        return _detached(self._provenance)

    def summary(self):
        mapped = self._bound if self._bound is not None else self._mapped
        stats = (dict(self._last_bound_statistics) if self._bound is None and self._last_bound_statistics is not None
                 else None if mapped is None else dict(mapped.statistics))
        if stats is not None and self._closed:
            stats["closed"] = True
        return _detached({
            "schema": "autoencoder-daemon-weight-session-v1",
            "base_verified": self._base_verified, "attached": self._attached,
            "closed": self._closed, "poisoned": self._poisoned,
            "current_storage": self._storage, "first_detachment_phase": self._first_detachment,
            "boundary_checks": self._boundary_checks, "boundaries": self._boundaries,
            "mapping_statistics": stats,
            "provenance": self._provenance, "admitted": False,
        })

    def close(self):
        if not self._closed:
            if threading.get_ident() != self._thread:
                raise DaemonWeightSessionError("weight session close requires its creating thread")
            self._closed = True
            try:
                if self._bound is not None:
                    self._last_bound_statistics = dict(self._bound.statistics)
                if self._mapped is not None:
                    self._mapped.close()
            finally:
                self._state = self._bound = None
