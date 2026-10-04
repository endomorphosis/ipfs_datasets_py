"""Explicit integration boundary for future synchronized-gradient training.

Federated local training is the default. This module supplies no collective
implementation and opens no network connections. A synchronized backend must
be injected and independently qualified by its caller before it is advertised.
MCP++ can coordinate these sessions through the canonical accelerator
``mcp_server.tools.p2p.native_p2p_tools`` task route; tensor transport belongs to
the backend, rather than to JSON task payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
import time
from typing import Any, Callable, Protocol


class TrainingSyncError(ValueError):
    """A synchronization request violates the configured session contract."""


class GradientBackendUnavailable(TrainingSyncError):
    """No independently qualified synchronized-gradient backend is configured."""


class TrainingMode(str, Enum):
    FEDERATED = "federated"
    GRADIENT_SYNCHRONIZED = "gradient_synchronized"


class GradientReduction(str, Enum):
    SUM = "sum"
    MEAN = "mean"


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DTYPES = frozenset(("float16", "bfloat16", "float32", "float64"))
_MAX_PARTICIPANTS = 4096


def _text(value: Any, field: str, maximum: int = 128) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise TrainingSyncError(f"{field} must be bounded, nonempty text")


def _integer(value: Any, field: str) -> None:
    if type(value) is not int or value < 0:
        raise TrainingSyncError(f"{field} must be a nonnegative integer")


def _positive_number(value: Any, field: str) -> None:
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise TrainingSyncError(f"{field} must be finite and positive")


@dataclass(frozen=True)
class TrainingRoundBinding:
    """Immutable numerical and membership identity of one training round."""

    run_id: str
    round_id: str
    base_sha256: str
    layout_sha256: str
    optimizer_profile: str
    membership_epoch: int
    participant_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        _text(self.round_id, "round_id")
        _text(self.optimizer_profile, "optimizer_profile", 256)
        for field in ("base_sha256", "layout_sha256"):
            value = getattr(self, field)
            if type(value) is not str or not _SHA256.fullmatch(value):
                raise TrainingSyncError(f"{field} must be lowercase SHA-256 hex")
        _integer(self.membership_epoch, "membership_epoch")
        if (
            type(self.participant_ids) is not tuple
            or not 1 <= len(self.participant_ids) <= _MAX_PARTICIPANTS
        ):
            raise TrainingSyncError("participant_ids must be a bounded nonempty tuple")
        for participant_id in self.participant_ids:
            _text(participant_id, "participant_id")
        if len(set(self.participant_ids)) != len(self.participant_ids):
            raise TrainingSyncError("participant_ids must be unique")

    @property
    def world_size(self) -> int:
        return len(self.participant_ids)


@dataclass(frozen=True)
class GradientBucketSpec:
    """Tensor identity shared by every participant in a collective."""

    bucket_id: str
    shape: tuple[int, ...]
    dtype: str

    def __post_init__(self) -> None:
        _text(self.bucket_id, "bucket_id")
        if (
            type(self.shape) is not tuple
            or len(self.shape) > 32
            or any(type(dimension) is not int or dimension <= 0 for dimension in self.shape)
        ):
            raise TrainingSyncError("shape must contain positive integer dimensions")
        if type(self.dtype) is not str or self.dtype not in _DTYPES:
            raise TrainingSyncError("unsupported gradient dtype")


@dataclass(frozen=True)
class GradientReductionRequest:
    """Reduce all members' gradients, then multiply by ``scale``.

    The backend owns reduction arithmetic, complete-member participation,
    deadlines, and deduplication of ``operation_id``. Reusing an operation ID
    with different request or tensor content must fail, rather than reusing a
    prior result. This adapter never retries a collective or changes it into
    a federated update.
    """

    binding: TrainingRoundBinding
    participant_id: str
    step: int
    bucket: GradientBucketSpec
    reduction: GradientReduction
    scale: float
    deadline_unix_s: float
    operation_id: str

    def __post_init__(self) -> None:
        if type(self.binding) is not TrainingRoundBinding:
            raise TrainingSyncError("binding must be a TrainingRoundBinding")
        if type(self.bucket) is not GradientBucketSpec:
            raise TrainingSyncError("bucket must be a GradientBucketSpec")
        _text(self.participant_id, "participant_id")
        if self.participant_id not in self.binding.participant_ids:
            raise TrainingSyncError("participant_id is outside the bound membership")
        _integer(self.step, "step")
        if type(self.reduction) is not GradientReduction:
            raise TrainingSyncError("reduction must be a GradientReduction")
        _positive_number(self.scale, "scale")
        _positive_number(self.deadline_unix_s, "deadline_unix_s")
        _text(self.operation_id, "operation_id")


@dataclass(frozen=True)
class GradientBackendCapabilities:
    """Declared capabilities to be checked by an independent qualification hook."""

    backend_id: str
    reductions: tuple[GradientReduction, ...]
    dtypes: tuple[str, ...]
    complete_membership: bool
    idempotent_operations: bool

    def __post_init__(self) -> None:
        _text(self.backend_id, "backend_id")
        if (
            type(self.reductions) is not tuple
            or not self.reductions
            or any(type(value) is not GradientReduction for value in self.reductions)
            or len(set(self.reductions)) != len(self.reductions)
        ):
            raise TrainingSyncError("reductions must be a unique tuple of GradientReduction values")
        if (
            type(self.dtypes) is not tuple
            or not self.dtypes
            or any(type(value) is not str or value not in _DTYPES for value in self.dtypes)
            or len(set(self.dtypes)) != len(self.dtypes)
        ):
            raise TrainingSyncError("dtypes must be a unique supported tuple")
        if self.complete_membership is not True or self.idempotent_operations is not True:
            raise TrainingSyncError("backend must enforce complete membership and idempotency")


class GradientSynchronizer(Protocol):
    """Backend contract; implementations must actually synchronize gradients.

    Implementations resolve the layout identity to its exact bucket manifest,
    verify the submitted bucket, bind all peer requests to the same round and
    membership, reject stale steps, and make operation retries idempotent only
    for the same request and tensor content. One controller belongs to one
    participant and is used sequentially; concurrent buckets require a
    backend-owned scheduling layer.
    """

    def capabilities(self) -> GradientBackendCapabilities: ...

    def join(self, binding: TrainingRoundBinding, participant_id: str) -> None: ...

    def reduce_gradients(self, request: GradientReductionRequest, gradients: Any) -> Any: ...

    def barrier(
        self, binding: TrainingRoundBinding, participant_id: str,
        operation_id: str, deadline_unix_s: float,
    ) -> None: ...

    def abort(self, binding: TrainingRoundBinding, reason: str) -> None: ...

    def close(self, binding: TrainingRoundBinding) -> None: ...


BackendVerifier = Callable[[GradientSynchronizer, GradientBackendCapabilities], bool]


def _round_snapshot(value: Any) -> TrainingRoundBinding:
    if type(value) is not TrainingRoundBinding:
        raise TrainingSyncError("binding must be a TrainingRoundBinding")
    return TrainingRoundBinding(
        value.run_id, value.round_id, value.base_sha256, value.layout_sha256,
        value.optimizer_profile, value.membership_epoch, value.participant_ids,
    )


def _bucket_snapshot(value: Any) -> GradientBucketSpec:
    if type(value) is not GradientBucketSpec:
        raise TrainingSyncError("bucket must be a GradientBucketSpec")
    return GradientBucketSpec(value.bucket_id, value.shape, value.dtype)


def _request_snapshot(value: Any) -> GradientReductionRequest:
    if type(value) is not GradientReductionRequest:
        raise TrainingSyncError("request must be a GradientReductionRequest")
    return GradientReductionRequest(
        _round_snapshot(value.binding), value.participant_id, value.step,
        _bucket_snapshot(value.bucket), value.reduction, value.scale,
        value.deadline_unix_s, value.operation_id,
    )


def _capability_snapshot(value: Any) -> GradientBackendCapabilities:
    if type(value) is not GradientBackendCapabilities:
        raise GradientBackendUnavailable("backend returned invalid capabilities")
    return GradientBackendCapabilities(
        value.backend_id, value.reductions, value.dtypes,
        value.complete_membership, value.idempotent_operations,
    )


class TrainingSyncController:
    """Fail-closed, optional session adapter; federated mode needs no backend.

    ``verify_backend`` is supplied by the deployment and must establish that
    the specific backend fulfills its declared contract. Merely returning a
    capability object does not qualify a backend. Contract objects are
    reconstructed and validated at dispatch boundaries, and the session owns
    snapshots independent of caller and backend aliases. Tensors are forwarded
    directly. No optional ML, accelerator, database, or network dependency is
    imported by this module.
    """

    def __init__(
        self, *, mode: TrainingMode = TrainingMode.FEDERATED,
        backend: GradientSynchronizer | None = None,
        verify_backend: BackendVerifier | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(mode) is not TrainingMode:
            raise TrainingSyncError("mode must be a TrainingMode")
        if not callable(clock):
            raise TrainingSyncError("clock must be callable")
        self._mode = mode
        self._clock = clock
        self._backend: GradientSynchronizer | None = None
        self._capabilities: GradientBackendCapabilities | None = None
        self._binding: TrainingRoundBinding | None = None
        self._participant_id: str | None = None
        self._failed = False
        if mode is TrainingMode.FEDERATED:
            if backend is not None or verify_backend is not None:
                raise TrainingSyncError("configure a backend only in gradient_synchronized mode")
            return
        if backend is None or not callable(verify_backend):
            raise GradientBackendUnavailable("gradient synchronization requires a qualified injected backend")
        for method in ("capabilities", "join", "reduce_gradients", "barrier", "abort", "close"):
            if not callable(getattr(backend, method, None)):
                raise GradientBackendUnavailable(f"backend is missing {method}")
        try:
            declared = backend.capabilities()
            capabilities = _capability_snapshot(declared)
            qualification_input = _capability_snapshot(capabilities)
            if verify_backend(backend, qualification_input) is not True:
                raise GradientBackendUnavailable("backend qualification was rejected")
            if (
                _capability_snapshot(qualification_input) != capabilities
                or _capability_snapshot(declared) != capabilities
            ):
                raise GradientBackendUnavailable("backend capabilities changed during qualification")
        except GradientBackendUnavailable:
            raise
        except Exception as error:
            raise GradientBackendUnavailable("backend qualification failed") from error
        self._backend = backend
        self._capabilities = capabilities

    @property
    def mode(self) -> TrainingMode:
        return self._mode

    @property
    def supported_modes(self) -> tuple[TrainingMode, ...]:
        """Advertise only the configured and independently qualified mode."""
        return (self.mode,)

    @property
    def binding(self) -> TrainingRoundBinding | None:
        return _round_snapshot(self._binding) if self._binding is not None else None

    def _require_backend(self) -> GradientSynchronizer:
        if self._backend is None:
            raise GradientBackendUnavailable("gradient synchronization is unavailable in federated mode")
        if self._failed:
            raise TrainingSyncError("session failed; configure a new controller")
        try:
            if _capability_snapshot(self._backend.capabilities()) != self._capabilities:
                raise GradientBackendUnavailable("backend capabilities changed after qualification")
        except Exception as error:
            if self._binding is not None:
                self._backend_failed(self._backend, self._binding)
            else:
                self._failed = True
            raise GradientBackendUnavailable("backend capabilities are no longer qualified") from error
        return self._backend

    def _active(self, binding: TrainingRoundBinding) -> GradientSynchronizer:
        backend = self._require_backend()
        binding = _round_snapshot(binding)
        if self._binding is None or binding != self._binding:
            raise TrainingSyncError("request differs from the joined round binding")
        return backend

    def _deadline(self, deadline_unix_s: float) -> None:
        _positive_number(deadline_unix_s, "deadline_unix_s")
        now = self._clock()
        try:
            valid = type(now) in (int, float) and math.isfinite(now)
        except OverflowError:
            valid = False
        if not valid:
            raise TrainingSyncError("clock returned an invalid timestamp")
        if deadline_unix_s <= now:
            raise TrainingSyncError("operation deadline has expired")

    @staticmethod
    def _tensor(gradients: Any, bucket: GradientBucketSpec) -> None:
        try:
            shape = tuple(gradients.shape)
            dtype = str(gradients.dtype)
        except Exception as error:
            raise TrainingSyncError("gradient tensor must expose shape and dtype") from error
        if any(type(dimension) is not int for dimension in shape) or shape != bucket.shape:
            raise TrainingSyncError("gradient tensor shape differs from its bucket")
        # NumPy and PyTorch expose respectively 'float32' and 'torch.float32'.
        if dtype.removeprefix("torch.") != bucket.dtype:
            raise TrainingSyncError("gradient tensor dtype differs from its bucket")

    def _backend_failed(self, backend: GradientSynchronizer, binding: TrainingRoundBinding) -> None:
        self._failed = True
        self._binding = _round_snapshot(binding)
        try:
            backend.abort(_round_snapshot(binding), "backend_operation_failed")
        except Exception:
            pass  # Preserve the original failure; this session remains unusable.

    def join(self, binding: TrainingRoundBinding, participant_id: str) -> None:
        backend = self._require_backend()
        binding = _round_snapshot(binding)
        _text(participant_id, "participant_id")
        if participant_id not in binding.participant_ids:
            raise TrainingSyncError("participant_id is outside the bound membership")
        if self._binding is not None:
            raise TrainingSyncError("close the joined round before joining another")
        try:
            backend.join(_round_snapshot(binding), participant_id)
        except Exception:
            self._backend_failed(backend, binding)
            raise
        self._binding = binding
        self._participant_id = participant_id

    def reduce_gradients(self, request: GradientReductionRequest, gradients: Any) -> Any:
        request = _request_snapshot(request)
        backend = self._active(request.binding)
        if request.participant_id != self._participant_id:
            raise TrainingSyncError("request participant differs from this session")
        capabilities = self._capabilities
        assert capabilities is not None
        if request.reduction not in capabilities.reductions or request.bucket.dtype not in capabilities.dtypes:
            raise TrainingSyncError("backend does not support this reduction or dtype")
        self._deadline(request.deadline_unix_s)
        self._tensor(gradients, request.bucket)
        try:
            reduced = backend.reduce_gradients(_request_snapshot(request), gradients)
            self._tensor(reduced, request.bucket)
            self._deadline(request.deadline_unix_s)
        except Exception:
            self._backend_failed(backend, request.binding)
            raise
        return reduced

    def barrier(
        self, binding: TrainingRoundBinding, *, operation_id: str,
        deadline_unix_s: float,
    ) -> None:
        binding = _round_snapshot(binding)
        backend = self._active(binding)
        _text(operation_id, "operation_id")
        self._deadline(deadline_unix_s)
        assert self._participant_id is not None
        try:
            backend.barrier(_round_snapshot(binding), self._participant_id, operation_id, deadline_unix_s)
            self._deadline(deadline_unix_s)
        except Exception:
            self._backend_failed(backend, binding)
            raise

    def abort(self, *, reason: str) -> None:
        backend = self._require_backend()
        if self._binding is None:
            raise TrainingSyncError("no joined round to abort")
        _text(reason, "reason", 256)
        self._failed = True
        backend.abort(_round_snapshot(self._binding), reason)

    def close(self) -> None:
        # Cleanup remains available after a failed or explicitly aborted session.
        backend = self._backend
        if backend is None or self._binding is None:
            return
        binding = self._binding
        try:
            backend.close(_round_snapshot(binding))
        except Exception:
            self._failed = True
            raise
        finally:
            self._binding = None
            self._participant_id = None


__all__ = [
    "BackendVerifier", "GradientBackendCapabilities", "GradientBackendUnavailable",
    "GradientBucketSpec", "GradientReduction", "GradientReductionRequest",
    "GradientSynchronizer", "TrainingMode", "TrainingRoundBinding",
    "TrainingSyncController", "TrainingSyncError",
]
