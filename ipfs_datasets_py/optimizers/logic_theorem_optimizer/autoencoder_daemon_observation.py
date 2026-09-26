"""Bounded, invocation-local daemon facts; no lease or acceptance authority."""

from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
import threading


SCHEMA = "autoencoder-daemon-observation-v1"
_CURRENT = ContextVar("autoencoder_daemon_observation", default=None)
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MAX_EVENTS = 128
_MAX_EVENT_BYTES = 65536


def _detached(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > _MAX_EVENT_BYTES:
        raise ValueError("daemon observation event exceeds size bound")
    return json.loads(encoded)


def current_observer():
    """Return the observer for this execution context, normally None."""
    return _CURRENT.get()


class DaemonObservation:
    """Capture identities without retaining samples, model weights or graphs.

    Only the creating thread can append. Async evaluator/writer threads neither
    inherit this context nor inspect the mutable trainer through this observer.
    Detached snapshots may be read concurrently under the collector lock.
    """

    def __init__(self, binding):
        if type(binding) is not dict or set(binding) != {"request_sha256", "launch_sha256"}:
            raise ValueError("daemon observation requires exact request/launch binding")
        if any(type(value) is not str or not _HASH.fullmatch(value) for value in binding.values()):
            raise ValueError("daemon observation binding must contain lowercase SHA-256 values")
        self._binding = dict(binding)
        self._thread = threading.get_ident()
        self._lock = threading.RLock()
        self._events = []
        self._closed = False
        self._error = None
        self._exit_code = None

    def checkpoint_metadata(self):
        return {"daemon_invocation": dict(self._binding)}

    def _check_writer(self):
        if self._closed:
            raise RuntimeError("daemon observation is closed")
        if threading.get_ident() != self._thread:
            raise RuntimeError("daemon state observations require the creating thread")
        if len(self._events) >= _MAX_EVENTS:
            raise ValueError("daemon observation event count exceeds bound")

    def record_state(self, phase, state, *, cycle, metric_lineage, metadata=None):
        with self._lock:
            self._check_writer()
            revision = state.state_revision
            default = state.state_identity_record().to_dict()
            metric = state.state_identity_record(metric_lineage=metric_lineage).to_dict()
            if state.state_revision != revision or default["revision"] != revision or metric["revision"] != revision:
                raise RuntimeError("state mutated during daemon identity observation")
            metadata = metadata or {}
            versions = (None if "compiler_version" not in metadata or "holdout_version" not in metadata else {
                "state_version": metric["digest"], "schema_version": metric_lineage,
                "compiler_version": metadata["compiler_version"], "holdout_version": metadata["holdout_version"],
            })
            self._events.append(_detached({
                "kind": "state", "phase": phase, "cycle": cycle,
                "state_identity": default, "metric_state_identity": metric,
                "metric_lineage": metric_lineage, "versions": versions, "metadata": metadata,
            }))

    def record_selection(self, *, cycle, train_indices, train_samples,
                         validation_indices, validation_samples, corpus_inputs=None):
        with self._lock:
            self._check_writer()
            roles = {}
            for role, indices, samples in (
                ("train", train_indices, train_samples),
                ("validation", validation_indices, validation_samples),
            ):
                indices, samples = list(indices), list(samples)
                if len(indices) != len(samples) or len(indices) > 256:
                    raise ValueError("daemon selection length is invalid")
                if any(type(index) is not int or index < 0 for index in indices):
                    raise ValueError("daemon selection indices must be nonnegative integers")
                sample_ids = [sample.sample_id for sample in samples]
                if any(type(value) is not str for value in sample_ids):
                    raise ValueError("daemon sample IDs must be strings")
                roles[role] = {
                    "indices": indices, "sample_ids": sample_ids,
                    "record_ids": (None if corpus_inputs is None else
                                   [corpus_inputs.record_id(index) for index in indices]),
                }
            self._events.append(_detached({"kind": "selection", "cycle": cycle, **roles}))

    def record_return(self, exit_code):
        with self._lock:
            self._check_writer()
            if type(exit_code) is not int or self._exit_code is not None:
                raise ValueError("daemon return must be recorded once as an integer")
            self._exit_code = exit_code

    def _close(self, error):
        with self._lock:
            if error is not None:
                try:
                    message = str(error)[:2048]
                except BaseException:
                    message = "exception string unavailable"
                self._error = {"error_type": f"{type(error).__module__}.{type(error).__qualname__}",
                               "error": message}
            self._closed = True

    def to_dict(self):
        with self._lock:
            final_observed = any(event.get("phase") == "final_shutdown" for event in self._events)
            return {
                "schema": SCHEMA, "binding": dict(self._binding),
                "observations_only": True, "lease_authority_verified": False,
                "admitted": False, "promoted": False,
                "closed": self._closed, "exit_code": self._exit_code,
                "success": self._closed and self._error is None and self._exit_code == 0 and final_observed,
                "error": None if self._error is None else dict(self._error),
                "events": json.loads(json.dumps(self._events)),
            }


@contextmanager
def observation_session(*, binding):
    """Install facts collection around real main; always restore the context.

    An exception retains its original identity/traceback. A successful context
    exit alone is insufficient: main must return zero and final durable state
    must have been observed. Owner verification and completion remain separate.
    """
    observer = DaemonObservation(binding)
    token = _CURRENT.set(observer)
    error = None
    try:
        yield observer
    except BaseException as exc:
        error = exc
        raise
    finally:
        try:
            observer._close(error)
        except BaseException:
            if error is None:
                raise
        finally:
            _CURRENT.reset(token)
