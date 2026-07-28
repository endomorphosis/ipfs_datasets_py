"""Authorization portfolio execution and deterministic result selection (LIG-033).

Interface: ``AuthorizationPortfolio@1``

Portfolio behavior follows Security result-policy practice:

* backend capability and logic support are explicit;
* attempts, timeouts, translations, assumptions, and reconstruction are
  recorded;
* result selection is deterministic and order independent;
* contradictory authoritative backend results fail closed and page review;
* unavailable backends never become successful attempts; and
* policy decisions retain links to typed proof results without adopting their
  authority kind.

Backends are **probed without installation**: availability checks use PATH
lookups and optional injected callables only.  Discovery never installs a
package, starts a long-lived solver service, or mutates the environment.

Authority paths that cannot allow (plan §9 / LIG-G110):

unsupported, unknown, contradictory, unavailable, SAT-only, model, monitor,
evidence, policy, and simulation.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from ..ir_core.claims import FrozenMap, stable_digest
from ..ir_core.protocols import (
    AttemptStatus,
    AuthorityKind,
    BackendCapabilities,
    QueryKind,
    ResultStatus,
)
from .compose import (
    NON_ALLOWING_AUTHORITY_PATHS,
    AuthorizationDecision,
    AuthorizationDecisionPolicy,
    AuthorizationQueryBundle,
    ComposeError,
    JobVerdict,
    ProofJob,
    ProofJobKind,
    ProofJobResult,
    evaluate_authorization_decision,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

AUTHORIZATION_PORTFOLIO_INTERFACE: Final = "AuthorizationPortfolio@1"
AUTHORIZATION_PORTFOLIO_SCHEMA_VERSION: Final = "authorization-portfolio/v1"
BACKEND_PROBE_SCHEMA_VERSION: Final = "authorization-backend-probe/v1"
PORTFOLIO_ATTEMPT_SCHEMA_VERSION: Final = "authorization-portfolio-attempt/v1"
PORTFOLIO_RUN_SCHEMA_VERSION: Final = "authorization-portfolio-run/v1"
TRANSLATION_RECORD_SCHEMA_VERSION: Final = "authorization-translation-record/v1"
RECONSTRUCTION_RECORD_SCHEMA_VERSION: Final = (
    "authorization-reconstruction-record/v1"
)

# Well-known backend executables that may be PATH-probed without install.
DEFAULT_BACKEND_EXECUTABLES: Final[Mapping[str, str]] = {
    "z3": "z3",
    "cvc5": "cvc5",
    "vampire": "vampire",
    "eprover": "eprover",
    "lean": "lean",
}

# Verdicts that never authorize an allow under portfolio selection.
_NON_ALLOWING_VERDICTS: Final[frozenset[JobVerdict]] = frozenset(
    {
        JobVerdict.UNSUPPORTED,
        JobVerdict.UNKNOWN,
        JobVerdict.CONTRADICTORY,
        JobVerdict.UNAVAILABLE,
        JobVerdict.SAT_ONLY,
        JobVerdict.MODEL,
        JobVerdict.MONITOR,
        JobVerdict.EVIDENCE,
        JobVerdict.POLICY,
        JobVerdict.SIMULATION,
        JobVerdict.TIMEOUT,
        JobVerdict.ERROR,
    }
)


class PortfolioError(ComposeError):
    """Raised when portfolio configuration or selection fails closed."""


class BackendAvailability(str, Enum):
    """Result of a side-effect-free backend probe."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PortfolioError(f"{name} must be a non-empty trimmed string")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise PortfolioError(f"{name} must be one of: {allowed}") from exc


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioError(f"{name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PortfolioError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _unique_sorted(values: Any, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise PortfolioError(f"{name} must be a sequence of strings")
    items = tuple(_text(item, f"{name} item") for item in values)
    if len(items) != len(set(items)):
        raise PortfolioError(f"{name} must be unique")
    return tuple(sorted(items))


# ---------------------------------------------------------------------------
# Capability probe (no installation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BackendProbeResult:
    """Record of one PATH/capability probe without installation.

    Probing never installs packages, writes files, or starts a solver
    subprocess for a full problem.  Optional version probes may run a
    short ``--version`` command only when an injectable runner is supplied.
    """

    backend_id: str
    availability: BackendAvailability
    executable_path: str = ""
    version: str = ""
    capabilities: BackendCapabilities | None = None
    logic_families: tuple[str, ...] = ()
    query_kinds: tuple[str, ...] = ()
    probed_without_install: bool = True
    diagnostics: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = BACKEND_PROBE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "backend_id", _text(self.backend_id, "backend_id")
        )
        object.__setattr__(
            self,
            "availability",
            _enum(self.availability, BackendAvailability, "availability"),
        )
        object.__setattr__(
            self,
            "executable_path",
            _optional_text(self.executable_path, "executable_path"),
        )
        if not isinstance(self.version, str):
            raise PortfolioError("version must be a string")
        if self.capabilities is not None and not isinstance(
            self.capabilities, BackendCapabilities
        ):
            raise PortfolioError(
                "capabilities must be BackendCapabilities or None"
            )
        object.__setattr__(
            self,
            "logic_families",
            _unique_sorted(self.logic_families, "logic_families"),
        )
        object.__setattr__(
            self,
            "query_kinds",
            _unique_sorted(self.query_kinds, "query_kinds"),
        )
        if not isinstance(self.probed_without_install, bool):
            raise PortfolioError("probed_without_install must be a bool")
        if not self.probed_without_install:
            raise PortfolioError(
                "portfolio probes must record probed_without_install=True; "
                "installation during probe is forbidden"
            )
        object.__setattr__(
            self,
            "diagnostics",
            _unique_sorted(self.diagnostics, "diagnostics"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != BACKEND_PROBE_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported backend probe schema: {self.schema_version!r}"
            )

    @property
    def available(self) -> bool:
        return self.availability is BackendAvailability.AVAILABLE

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "availability": self.availability.value,
            "backend_id": self.backend_id,
            "capabilities": (
                None
                if self.capabilities is None
                else self.capabilities.to_dict()
            ),
            "diagnostics": list(self.diagnostics),
            "executable_path": self.executable_path,
            "logic_families": list(self.logic_families),
            "metadata": self.metadata.to_dict(),
            "probed_without_install": self.probed_without_install,
            "query_kinds": list(self.query_kinds),
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BackendProbeResult":
        value = _mapping(value, "backend probe")
        _reject_unknown(
            value,
            frozenset(
                {
                    "availability",
                    "backend_id",
                    "capabilities",
                    "diagnostics",
                    "executable_path",
                    "logic_families",
                    "metadata",
                    "probed_without_install",
                    "query_kinds",
                    "schema_version",
                    "version",
                }
            ),
            "backend probe",
        )
        caps_raw = value.get("capabilities")
        capabilities = None
        if caps_raw is not None:
            capabilities = (
                caps_raw
                if isinstance(caps_raw, BackendCapabilities)
                else BackendCapabilities.from_dict(caps_raw)
            )
        return cls(
            backend_id=value.get("backend_id", ""),
            availability=value.get("availability", ""),
            executable_path=value.get("executable_path", ""),
            version=value.get("version", ""),
            capabilities=capabilities,
            logic_families=tuple(value.get("logic_families", ())),
            query_kinds=tuple(value.get("query_kinds", ())),
            probed_without_install=bool(
                value.get("probed_without_install", True)
            ),
            diagnostics=tuple(value.get("diagnostics", ())),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get(
                "schema_version", BACKEND_PROBE_SCHEMA_VERSION
            ),
        )


def probe_backend(
    backend_id: str,
    *,
    executable_name: str | None = None,
    capabilities: BackendCapabilities | None = None,
    which: Callable[[str], str | None] | None = None,
    version_probe: Callable[[str], str] | None = None,
) -> BackendProbeResult:
    """Probe a backend executable on PATH without installing anything.

    ``which`` defaults to :func:`shutil.which`.  No package manager, pip, or
    network fetch is invoked.  A missing executable yields ``UNAVAILABLE``,
    never a fabricated success.
    """

    backend_id = _text(backend_id, "backend_id")
    exe_name = executable_name or DEFAULT_BACKEND_EXECUTABLES.get(
        backend_id, backend_id
    )
    which_fn = which or shutil.which
    diagnostics: list[str] = ["auth.portfolio.probe_without_install"]
    path = which_fn(exe_name)
    if not path:
        diagnostics.append(f"auth.portfolio.executable_missing:{exe_name}")
        return BackendProbeResult(
            backend_id=backend_id,
            availability=BackendAvailability.UNAVAILABLE,
            executable_path="",
            version="",
            capabilities=capabilities,
            logic_families=(
                tuple(capabilities.logic_families) if capabilities else ()
            ),
            query_kinds=(
                tuple(item.value for item in capabilities.query_kinds)
                if capabilities
                else ()
            ),
            probed_without_install=True,
            diagnostics=tuple(diagnostics),
        )

    version = ""
    if version_probe is not None:
        try:
            version = str(version_probe(path) or "")
        except Exception as exc:  # noqa: BLE001 — probe must not raise out
            diagnostics.append(
                f"auth.portfolio.version_probe_failed:{type(exc).__name__}"
            )
            version = ""

    return BackendProbeResult(
        backend_id=backend_id,
        availability=BackendAvailability.AVAILABLE,
        executable_path=path,
        version=version,
        capabilities=capabilities,
        logic_families=(
            tuple(capabilities.logic_families) if capabilities else ()
        ),
        query_kinds=(
            tuple(item.value for item in capabilities.query_kinds)
            if capabilities
            else ()
        ),
        probed_without_install=True,
        diagnostics=tuple(diagnostics),
    )


def probe_backends(
    backend_ids: Sequence[str],
    *,
    capabilities_by_backend: Mapping[str, BackendCapabilities] | None = None,
    which: Callable[[str], str | None] | None = None,
    version_probe: Callable[[str], str] | None = None,
) -> tuple[BackendProbeResult, ...]:
    """Probe many backends without installation; order-independent result."""

    caps = capabilities_by_backend or {}
    results = [
        probe_backend(
            backend_id,
            capabilities=caps.get(backend_id),
            which=which,
            version_probe=version_probe,
        )
        for backend_id in backend_ids
    ]
    return tuple(sorted(results, key=lambda item: item.backend_id))


# ---------------------------------------------------------------------------
# Translation / reconstruction / attempt records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PortfolioTranslationRecord:
    """Recorded translation step for one portfolio attempt."""

    translation_id: str
    source_logic_family: str
    target_logic_family: str
    lossy: bool = False
    translator_id: str = ""
    schema_version: str = TRANSLATION_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "translation_id",
            _text(self.translation_id, "translation_id"),
        )
        object.__setattr__(
            self,
            "source_logic_family",
            _text(self.source_logic_family, "source_logic_family"),
        )
        object.__setattr__(
            self,
            "target_logic_family",
            _text(self.target_logic_family, "target_logic_family"),
        )
        if self.source_logic_family == self.target_logic_family:
            raise PortfolioError(
                "translation must change logic family"
            )
        if not isinstance(self.lossy, bool):
            raise PortfolioError("lossy must be a bool")
        object.__setattr__(
            self,
            "translator_id",
            _optional_text(self.translator_id, "translator_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lossy": self.lossy,
            "schema_version": self.schema_version,
            "source_logic_family": self.source_logic_family,
            "target_logic_family": self.target_logic_family,
            "translation_id": self.translation_id,
            "translator_id": self.translator_id,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "PortfolioTranslationRecord":
        value = _mapping(value, "translation record")
        return cls(
            translation_id=value.get("translation_id", ""),
            source_logic_family=value.get("source_logic_family", ""),
            target_logic_family=value.get("target_logic_family", ""),
            lossy=bool(value.get("lossy", False)),
            translator_id=value.get("translator_id", ""),
            schema_version=value.get(
                "schema_version", TRANSLATION_RECORD_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioReconstructionRecord:
    """Recorded reconstruction step for one portfolio attempt."""

    reconstruction_id: str
    logic_family: str
    faithful: bool = True
    reconstructor_id: str = ""
    schema_version: str = RECONSTRUCTION_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconstruction_id",
            _text(self.reconstruction_id, "reconstruction_id"),
        )
        object.__setattr__(
            self, "logic_family", _text(self.logic_family, "logic_family")
        )
        if not isinstance(self.faithful, bool):
            raise PortfolioError("faithful must be a bool")
        object.__setattr__(
            self,
            "reconstructor_id",
            _optional_text(self.reconstructor_id, "reconstructor_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "faithful": self.faithful,
            "logic_family": self.logic_family,
            "reconstruction_id": self.reconstruction_id,
            "reconstructor_id": self.reconstructor_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "PortfolioReconstructionRecord":
        value = _mapping(value, "reconstruction record")
        return cls(
            reconstruction_id=value.get("reconstruction_id", ""),
            logic_family=value.get("logic_family", ""),
            faithful=bool(value.get("faithful", True)),
            reconstructor_id=value.get("reconstructor_id", ""),
            schema_version=value.get(
                "schema_version", RECONSTRUCTION_RECORD_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioAttemptRecord:
    """One backend attempt against one proof job (immutable receipt)."""

    attempt_id: str
    job_id: str
    backend_id: str
    status: AttemptStatus
    verdict: JobVerdict
    authority_path: str = "theorem_proof"
    timed_out: bool = False
    elapsed_ms: int = 0
    assumption_ids: tuple[str, ...] = ()
    translations: tuple[PortfolioTranslationRecord, ...] = ()
    reconstructions: tuple[PortfolioReconstructionRecord, ...] = ()
    probe: BackendProbeResult | None = None
    diagnostics: tuple[str, ...] = ()
    reason: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = PORTFOLIO_ATTEMPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "attempt_id", _text(self.attempt_id, "attempt_id")
        )
        object.__setattr__(self, "job_id", _text(self.job_id, "job_id"))
        object.__setattr__(
            self, "backend_id", _text(self.backend_id, "backend_id")
        )
        object.__setattr__(
            self, "status", _enum(self.status, AttemptStatus, "status")
        )
        object.__setattr__(
            self, "verdict", _enum(self.verdict, JobVerdict, "verdict")
        )
        object.__setattr__(
            self,
            "authority_path",
            _text(self.authority_path, "authority_path"),
        )
        if not isinstance(self.timed_out, bool):
            raise PortfolioError("timed_out must be a bool")
        if (
            isinstance(self.elapsed_ms, bool)
            or not isinstance(self.elapsed_ms, int)
            or self.elapsed_ms < 0
        ):
            raise PortfolioError("elapsed_ms must be a non-negative integer")
        object.__setattr__(
            self,
            "assumption_ids",
            _unique_sorted(self.assumption_ids, "assumption_ids"),
        )
        translations = tuple(
            item
            if isinstance(item, PortfolioTranslationRecord)
            else PortfolioTranslationRecord.from_dict(
                _mapping(item, "translation")
            )
            for item in (self.translations or ())
        )
        object.__setattr__(
            self,
            "translations",
            tuple(sorted(translations, key=lambda item: item.translation_id)),
        )
        reconstructions = tuple(
            item
            if isinstance(item, PortfolioReconstructionRecord)
            else PortfolioReconstructionRecord.from_dict(
                _mapping(item, "reconstruction")
            )
            for item in (self.reconstructions or ())
        )
        object.__setattr__(
            self,
            "reconstructions",
            tuple(
                sorted(
                    reconstructions, key=lambda item: item.reconstruction_id
                )
            ),
        )
        if self.probe is not None and not isinstance(
            self.probe, BackendProbeResult
        ):
            raise PortfolioError("probe must be BackendProbeResult or None")
        # Unavailable backends cannot claim success.
        if (
            self.status is AttemptStatus.UNAVAILABLE
            and self.verdict is JobVerdict.PROVED
        ):
            raise PortfolioError(
                "unavailable backends never become successful attempts"
            )
        if self.status is AttemptStatus.TIMED_OUT and not self.timed_out:
            object.__setattr__(self, "timed_out", True)
        if self.timed_out and self.verdict is JobVerdict.PROVED:
            raise PortfolioError("timed-out attempts cannot claim proved")
        object.__setattr__(
            self,
            "diagnostics",
            _unique_sorted(self.diagnostics, "diagnostics"),
        )
        if not isinstance(self.reason, str):
            raise PortfolioError("reason must be a string")
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PORTFOLIO_ATTEMPT_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported portfolio attempt schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attempt_id": self.attempt_id,
            "authority_path": self.authority_path,
            "backend_id": self.backend_id,
            "diagnostics": list(self.diagnostics),
            "elapsed_ms": self.elapsed_ms,
            "job_id": self.job_id,
            "metadata": self.metadata.to_dict(),
            "probe": None if self.probe is None else self.probe.to_dict(),
            "reason": self.reason,
            "reconstructions": [
                item.to_dict() for item in self.reconstructions
            ],
            "schema_version": self.schema_version,
            "status": self.status.value,
            "timed_out": self.timed_out,
            "translations": [item.to_dict() for item in self.translations],
            "verdict": self.verdict.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioAttemptRecord":
        value = _mapping(value, "portfolio attempt")
        probe_raw = value.get("probe")
        probe = None
        if probe_raw is not None:
            probe = (
                probe_raw
                if isinstance(probe_raw, BackendProbeResult)
                else BackendProbeResult.from_dict(probe_raw)
            )
        return cls(
            attempt_id=value.get("attempt_id", ""),
            job_id=value.get("job_id", ""),
            backend_id=value.get("backend_id", ""),
            status=value.get("status", ""),
            verdict=value.get("verdict", ""),
            authority_path=value.get("authority_path", "theorem_proof"),
            timed_out=bool(value.get("timed_out", False)),
            elapsed_ms=int(value.get("elapsed_ms", 0) or 0),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            translations=tuple(value.get("translations", ())),
            reconstructions=tuple(value.get("reconstructions", ())),
            probe=probe,
            diagnostics=tuple(value.get("diagnostics", ())),
            reason=value.get("reason", ""),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get(
                "schema_version", PORTFOLIO_ATTEMPT_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


#: Rank for deny-overrides selection (higher wins).
_VERDICT_RANK: Final[dict[JobVerdict, int]] = {
    JobVerdict.DENIED: 100,
    JobVerdict.DISPROVED: 100,
    JobVerdict.CONTRADICTORY: 90,
    JobVerdict.ERROR: 80,
    JobVerdict.REVIEW: 70,
    JobVerdict.UNSUPPORTED: 60,
    JobVerdict.UNAVAILABLE: 55,
    JobVerdict.TIMEOUT: 50,
    JobVerdict.SAT_ONLY: 45,
    JobVerdict.MODEL: 45,
    JobVerdict.MONITOR: 45,
    JobVerdict.EVIDENCE: 45,
    JobVerdict.POLICY: 45,
    JobVerdict.SIMULATION: 45,
    JobVerdict.UNKNOWN: 40,
    JobVerdict.PROVED: 10,
}


def result_status_to_job_verdict(
    status: ResultStatus | str,
    *,
    authority_kind: AuthorityKind | str = AuthorityKind.THEOREM_PROOF,
    simulated: bool = False,
) -> JobVerdict:
    """Map a solver-neutral result status into a portfolio job verdict.

    SAT-only, monitor, evidence, policy, and simulation paths never map to
    :attr:`JobVerdict.PROVED` for theorem-authorization jobs.
    """

    status = _enum(status, ResultStatus, "status")
    authority = _enum(authority_kind, AuthorityKind, "authority_kind")
    if simulated:
        return JobVerdict.SIMULATION
    if authority is AuthorityKind.SATISFIABILITY:
        return JobVerdict.SAT_ONLY
    if authority is AuthorityKind.RUNTIME_MONITOR:
        return JobVerdict.MONITOR
    if authority is AuthorityKind.EVIDENCE_READINESS:
        return JobVerdict.EVIDENCE
    if authority is AuthorityKind.POLICY_APPROVAL:
        return JobVerdict.POLICY
    if status is ResultStatus.PROVED:
        return JobVerdict.PROVED
    if status is ResultStatus.DISPROVED:
        return JobVerdict.DISPROVED
    if status is ResultStatus.ERROR:
        return JobVerdict.ERROR
    if status is ResultStatus.UNKNOWN:
        return JobVerdict.UNKNOWN
    if status in {ResultStatus.SATISFIABLE, ResultStatus.UNSATISFIABLE}:
        return JobVerdict.SAT_ONLY
    if status in {
        ResultStatus.MONITOR_SATISFIED,
        ResultStatus.MONITOR_VIOLATED,
    }:
        return JobVerdict.MONITOR
    if status in {ResultStatus.READY, ResultStatus.NOT_READY}:
        return JobVerdict.EVIDENCE
    if status in {ResultStatus.APPROVED, ResultStatus.REJECTED}:
        if status is ResultStatus.REJECTED:
            return JobVerdict.DENIED
        return JobVerdict.POLICY
    return JobVerdict.UNKNOWN


def select_job_result(
    attempts: Sequence[PortfolioAttemptRecord] | Iterable[PortfolioAttemptRecord],
    job: ProofJob,
    *,
    required_backends: Sequence[str] = (),
) -> ProofJobResult:
    """Select one job result by deny-overrides consensus (order independent).

    * Deny / disproof from any attempt wins.
    * Contradictory authoritative proved/denied pairs fail closed as
      ``CONTRADICTORY`` (review).
    * Missing required backends and pure non-allowing paths never yield
      ``PROVED``.
    * When multiple agreeing proved attempts exist, the lexicographically
      smallest attempt digest is the representative (tie-break only).
    """

    if not isinstance(job, ProofJob):
        raise TypeError("job must be a ProofJob")
    ordered = tuple(
        sorted(
            (
                item
                if isinstance(item, PortfolioAttemptRecord)
                else PortfolioAttemptRecord.from_dict(
                    _mapping(item, "attempt")
                )
                for item in attempts
            ),
            key=lambda item: (item.backend_id, item.attempt_id, item.digest),
        )
    )
    job_attempts = [item for item in ordered if item.job_id == job.job_id]
    diagnostics: list[str] = []
    attempt_ids = tuple(sorted({item.attempt_id for item in job_attempts}))

    if not job_attempts:
        diagnostics.append(f"auth.portfolio.no_attempts:{job.job_id}")
        return ProofJobResult(
            job_id=job.job_id,
            kind=job.kind,
            verdict=JobVerdict.UNAVAILABLE,
            authority_path="unavailable",
            attempt_ids=(),
            diagnostics=tuple(diagnostics),
            reason="no portfolio attempts recorded for job",
        )

    required = tuple(sorted(set(required_backends)))
    present = {item.backend_id for item in job_attempts}
    missing = sorted(set(required) - present)
    if missing:
        diagnostics.extend(
            f"auth.portfolio.required_backend_missing:{backend_id}"
            for backend_id in missing
        )

    # Group by backend — duplicates fail closed.
    by_backend: dict[str, list[PortfolioAttemptRecord]] = {}
    for attempt in job_attempts:
        by_backend.setdefault(attempt.backend_id, []).append(attempt)
    for backend_id, values in sorted(by_backend.items()):
        if len(values) > 1:
            digests = {item.digest for item in values}
            if len(digests) > 1:
                diagnostics.append(
                    f"auth.portfolio.ambiguous_backend_output:{backend_id}"
                )

    # Deny overrides: any deny/disproof wins regardless of order.
    deny_attempts = [
        item
        for item in job_attempts
        if item.verdict in {JobVerdict.DENIED, JobVerdict.DISPROVED}
    ]
    if deny_attempts:
        chosen = min(deny_attempts, key=lambda item: item.digest)
        diagnostics.append("auth.portfolio.deny_overrides")
        return ProofJobResult(
            job_id=job.job_id,
            kind=job.kind,
            verdict=chosen.verdict,
            authority_path=chosen.authority_path,
            backend_id=chosen.backend_id,
            attempt_ids=attempt_ids,
            diagnostics=tuple(sorted(set(diagnostics))),
            reason=chosen.reason or f"deny from backend {chosen.backend_id}",
        )

    # Contradictory: mixed proved with non-proved authoritative outcomes.
    proved = [
        item for item in job_attempts if item.verdict is JobVerdict.PROVED
    ]
    blocking = [
        item
        for item in job_attempts
        if item.verdict
        in {
            JobVerdict.CONTRADICTORY,
            JobVerdict.ERROR,
            JobVerdict.UNSUPPORTED,
        }
        or item.authority_path in NON_ALLOWING_AUTHORITY_PATHS
        and item.verdict is not JobVerdict.PROVED
    ]
    if proved and any(
        item.verdict
        in {
            JobVerdict.UNKNOWN,
            JobVerdict.UNAVAILABLE,
            JobVerdict.TIMEOUT,
            JobVerdict.SAT_ONLY,
            JobVerdict.MODEL,
            JobVerdict.MONITOR,
            JobVerdict.EVIDENCE,
            JobVerdict.POLICY,
            JobVerdict.SIMULATION,
            JobVerdict.ERROR,
            JobVerdict.UNSUPPORTED,
            JobVerdict.CONTRADICTORY,
            JobVerdict.REVIEW,
        }
        for item in job_attempts
        if item.backend_id
        in (required if required else {a.backend_id for a in job_attempts})
        and item not in proved
    ):
        # Required backends disagree on success.
        if required:
            required_verdicts = {
                item.verdict
                for item in job_attempts
                if item.backend_id in required
            }
            if len(required_verdicts) > 1 and JobVerdict.PROVED in required_verdicts:
                diagnostics.append("auth.portfolio.solver_disagreement")
                return ProofJobResult(
                    job_id=job.job_id,
                    kind=job.kind,
                    verdict=JobVerdict.CONTRADICTORY,
                    authority_path="contradictory",
                    attempt_ids=attempt_ids,
                    diagnostics=tuple(sorted(set(diagnostics))),
                    reason="contradictory authoritative backend results",
                )

    if any(item.verdict is JobVerdict.CONTRADICTORY for item in job_attempts):
        diagnostics.append("auth.portfolio.contradictory")
        return ProofJobResult(
            job_id=job.job_id,
            kind=job.kind,
            verdict=JobVerdict.CONTRADICTORY,
            authority_path="contradictory",
            attempt_ids=attempt_ids,
            diagnostics=tuple(sorted(set(diagnostics))),
            reason="contradictory portfolio attempts",
        )

    if missing:
        diagnostics.append("auth.portfolio.incomplete_required_backends")
        return ProofJobResult(
            job_id=job.job_id,
            kind=job.kind,
            verdict=JobVerdict.UNAVAILABLE,
            authority_path="unavailable",
            attempt_ids=attempt_ids,
            diagnostics=tuple(sorted(set(diagnostics))),
            reason="required backend missing; cannot allow",
        )

    # Highest non-proved rank wins when no proved consensus.
    if not proved:
        # Pick the "worst" non-allowing verdict deterministically.
        ranked = sorted(
            job_attempts,
            key=lambda item: (
                -_VERDICT_RANK.get(item.verdict, 0),
                item.digest,
            ),
        )
        chosen = ranked[0]
        verdict = chosen.verdict
        if verdict is JobVerdict.PROVED:
            verdict = JobVerdict.UNKNOWN
        if verdict not in _NON_ALLOWING_VERDICTS and verdict not in {
            JobVerdict.DENIED,
            JobVerdict.DISPROVED,
            JobVerdict.REVIEW,
        }:
            verdict = JobVerdict.UNKNOWN
        diagnostics.append(
            f"auth.portfolio.non_proved_selection:{verdict.value}"
        )
        return ProofJobResult(
            job_id=job.job_id,
            kind=job.kind,
            verdict=verdict,
            authority_path=chosen.authority_path
            if chosen.authority_path in NON_ALLOWING_AUTHORITY_PATHS
            or chosen.authority_path == "theorem_proof"
            else chosen.authority_path,
            backend_id=chosen.backend_id,
            attempt_ids=attempt_ids,
            diagnostics=tuple(sorted(set(diagnostics))),
            reason=chosen.reason or f"non-proved portfolio outcome {verdict.value}",
        )

    # Filter proved attempts that used non-allowing authority paths.
    theorem_proved = [
        item
        for item in proved
        if item.authority_path not in NON_ALLOWING_AUTHORITY_PATHS
        and item.authority_path == "theorem_proof"
        and item.status is AttemptStatus.SUCCEEDED
        and not item.timed_out
    ]
    if not theorem_proved:
        diagnostics.append("auth.portfolio.proved_without_theorem_authority")
        chosen = min(proved, key=lambda item: item.digest)
        # Map to the non-allowing path of the attempt.
        verdict = result_status_to_job_verdict(
            ResultStatus.UNKNOWN,
            authority_kind=(
                AuthorityKind.SATISFIABILITY
                if chosen.authority_path
                in {"sat_only", "satisfiability"}
                else AuthorityKind.THEOREM_PROOF
            ),
            simulated=chosen.authority_path
            in {"simulation", "simulated"},
        )
        if chosen.authority_path in NON_ALLOWING_AUTHORITY_PATHS:
            path_to_verdict = {
                "sat_only": JobVerdict.SAT_ONLY,
                "satisfiability": JobVerdict.SAT_ONLY,
                "model": JobVerdict.MODEL,
                "monitor": JobVerdict.MONITOR,
                "runtime_monitor": JobVerdict.MONITOR,
                "evidence": JobVerdict.EVIDENCE,
                "evidence_readiness": JobVerdict.EVIDENCE,
                "policy": JobVerdict.POLICY,
                "policy_approval": JobVerdict.POLICY,
                "simulation": JobVerdict.SIMULATION,
                "simulated": JobVerdict.SIMULATION,
                "unsupported": JobVerdict.UNSUPPORTED,
                "unknown": JobVerdict.UNKNOWN,
                "unavailable": JobVerdict.UNAVAILABLE,
                "contradictory": JobVerdict.CONTRADICTORY,
            }
            verdict = path_to_verdict.get(
                chosen.authority_path, JobVerdict.UNKNOWN
            )
        return ProofJobResult(
            job_id=job.job_id,
            kind=job.kind,
            verdict=verdict,
            authority_path=chosen.authority_path,
            backend_id=chosen.backend_id,
            attempt_ids=attempt_ids,
            diagnostics=tuple(sorted(set(diagnostics))),
            reason="non-theorem authority cannot allow",
        )

    if required:
        required_proved = {
            item.backend_id
            for item in theorem_proved
            if item.backend_id in required
        }
        if required_proved != set(required):
            diagnostics.append("auth.portfolio.required_backends_not_all_proved")
            return ProofJobResult(
                job_id=job.job_id,
                kind=job.kind,
                verdict=JobVerdict.UNKNOWN,
                authority_path="unknown",
                attempt_ids=attempt_ids,
                diagnostics=tuple(sorted(set(diagnostics))),
                reason="not all required backends proved the job",
            )

    chosen = min(theorem_proved, key=lambda item: item.digest)
    diagnostics.append("auth.portfolio.consensus_proved")
    return ProofJobResult(
        job_id=job.job_id,
        kind=job.kind,
        verdict=JobVerdict.PROVED,
        authority_path="theorem_proof",
        backend_id=chosen.backend_id,
        attempt_ids=attempt_ids,
        evidence_cids=(),
        diagnostics=tuple(sorted(set(diagnostics))),
        reason=chosen.reason or "portfolio consensus proved",
    )


def select_portfolio_results(
    bundle: AuthorizationQueryBundle,
    attempts: Sequence[PortfolioAttemptRecord] | Iterable[PortfolioAttemptRecord],
    *,
    required_backends: Sequence[str] = (),
) -> tuple[ProofJobResult, ...]:
    """Select one result per job; order of *attempts* is irrelevant."""

    ordered_attempts = tuple(attempts)
    results = [
        select_job_result(
            ordered_attempts, job, required_backends=required_backends
        )
        for job in bundle.jobs
    ]
    return tuple(sorted(results, key=lambda item: item.job_id))


# ---------------------------------------------------------------------------
# Portfolio runner
# ---------------------------------------------------------------------------


@runtime_checkable
class JobSolver(Protocol):
    """Callable that solves one proof job on one backend (for tests/fakes)."""

    def __call__(
        self, job: ProofJob, backend_id: str, probe: BackendProbeResult
    ) -> PortfolioAttemptRecord: ...


@dataclass(frozen=True, slots=True)
class PortfolioRunResult:
    """Complete portfolio run: probes, attempts, selected results, decision."""

    run_id: str
    bundle_digest: str
    probes: tuple[BackendProbeResult, ...]
    attempts: tuple[PortfolioAttemptRecord, ...]
    job_results: tuple[ProofJobResult, ...]
    decision: AuthorizationDecision | None = None
    assumptions: tuple[str, ...] = ()
    translations: tuple[PortfolioTranslationRecord, ...] = ()
    reconstructions: tuple[PortfolioReconstructionRecord, ...] = ()
    timeouts: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    schema_version: str = PORTFOLIO_RUN_SCHEMA_VERSION
    interface: str = AUTHORIZATION_PORTFOLIO_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _text(self.run_id, "run_id"))
        object.__setattr__(
            self, "bundle_digest", _text(self.bundle_digest, "bundle_digest")
        )
        object.__setattr__(
            self,
            "probes",
            tuple(sorted(self.probes, key=lambda item: item.backend_id)),
        )
        object.__setattr__(
            self,
            "attempts",
            tuple(
                sorted(
                    self.attempts,
                    key=lambda item: (item.job_id, item.backend_id, item.attempt_id),
                )
            ),
        )
        object.__setattr__(
            self,
            "job_results",
            tuple(sorted(self.job_results, key=lambda item: item.job_id)),
        )
        object.__setattr__(
            self, "assumptions", _unique_sorted(self.assumptions, "assumptions")
        )
        object.__setattr__(
            self,
            "timeouts",
            _unique_sorted(self.timeouts, "timeouts"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _unique_sorted(self.diagnostics, "diagnostics"),
        )
        if self.interface != AUTHORIZATION_PORTFOLIO_INTERFACE:
            raise PortfolioError(
                f"unsupported portfolio interface: {self.interface!r}"
            )
        if self.schema_version != PORTFOLIO_RUN_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported portfolio run schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "attempts": [item.to_dict() for item in self.attempts],
            "bundle_digest": self.bundle_digest,
            "decision": (
                None if self.decision is None else self.decision.to_dict()
            ),
            "diagnostics": list(self.diagnostics),
            "interface": self.interface,
            "job_results": [item.to_dict() for item in self.job_results],
            "probes": [item.to_dict() for item in self.probes],
            "reconstructions": [
                item.to_dict() for item in self.reconstructions
            ],
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "timeouts": list(self.timeouts),
            "translations": [item.to_dict() for item in self.translations],
        }


@dataclass(frozen=True, slots=True)
class AuthorizationPortfolio:
    """``AuthorizationPortfolio@1`` — probe, attempt, select, decide.

    Evaluation has no side effect on the corpus or environment beyond optional
    read-only PATH probes and injected solvers.  Installation is never
    performed.
    """

    backend_ids: tuple[str, ...] = ("z3", "cvc5")
    required_backends: tuple[str, ...] = ()
    capabilities_by_backend: Mapping[str, BackendCapabilities] = field(
        default_factory=dict
    )
    decision_policy: AuthorizationDecisionPolicy | None = None
    interface: str = AUTHORIZATION_PORTFOLIO_INTERFACE
    schema_version: str = AUTHORIZATION_PORTFOLIO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "backend_ids",
            _unique_sorted(self.backend_ids, "backend_ids"),
        )
        if not self.backend_ids:
            raise PortfolioError("backend_ids must not be empty")
        object.__setattr__(
            self,
            "required_backends",
            _unique_sorted(self.required_backends, "required_backends"),
        )
        if set(self.required_backends) - set(self.backend_ids):
            raise PortfolioError(
                "required_backends must be a subset of backend_ids"
            )
        caps = self.capabilities_by_backend or {}
        if not isinstance(caps, Mapping):
            raise PortfolioError("capabilities_by_backend must be a mapping")
        object.__setattr__(
            self,
            "capabilities_by_backend",
            dict(caps),
        )
        if self.decision_policy is not None and not isinstance(
            self.decision_policy, AuthorizationDecisionPolicy
        ):
            raise PortfolioError(
                "decision_policy must be AuthorizationDecisionPolicy or None"
            )
        if self.interface != AUTHORIZATION_PORTFOLIO_INTERFACE:
            raise PortfolioError(
                f"unsupported portfolio interface: {self.interface!r}"
            )
        if self.schema_version != AUTHORIZATION_PORTFOLIO_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported portfolio schema: {self.schema_version!r}"
            )

    def probe(
        self,
        *,
        which: Callable[[str], str | None] | None = None,
        version_probe: Callable[[str], str] | None = None,
    ) -> tuple[BackendProbeResult, ...]:
        """Probe configured backends without installation."""

        return probe_backends(
            self.backend_ids,
            capabilities_by_backend=self.capabilities_by_backend,
            which=which,
            version_probe=version_probe,
        )

    def run(
        self,
        bundle: AuthorizationQueryBundle,
        *,
        solver: JobSolver | None = None,
        precomputed_attempts: Sequence[PortfolioAttemptRecord] | None = None,
        which: Callable[[str], str | None] | None = None,
        version_probe: Callable[[str], str] | None = None,
        decide: bool = True,
        run_id: str = "",
    ) -> PortfolioRunResult:
        """Probe backends, collect attempts, select results, optionally decide.

        When ``precomputed_attempts`` is provided (unit tests / offline
        fixtures), no solver is invoked.  When ``solver`` is provided, it is
        called only for backends that probe as available.  Unavailable
        backends record an ``UNAVAILABLE`` attempt and never a success.
        """

        if not isinstance(bundle, AuthorizationQueryBundle):
            raise TypeError("bundle must be an AuthorizationQueryBundle")

        probes = self.probe(which=which, version_probe=version_probe)
        probe_by_id = {item.backend_id: item for item in probes}
        diagnostics: list[str] = ["auth.portfolio.run"]
        attempts: list[PortfolioAttemptRecord] = []
        translations: list[PortfolioTranslationRecord] = []
        reconstructions: list[PortfolioReconstructionRecord] = []
        timeouts: list[str] = []
        assumptions = list(bundle.assumptions)

        if precomputed_attempts is not None:
            attempts.extend(
                item
                if isinstance(item, PortfolioAttemptRecord)
                else PortfolioAttemptRecord.from_dict(
                    _mapping(item, "attempt")
                )
                for item in precomputed_attempts
            )
        elif solver is not None:
            for job in bundle.jobs:
                for backend_id in self.backend_ids:
                    probe = probe_by_id[backend_id]
                    if not probe.available:
                        attempts.append(
                            PortfolioAttemptRecord(
                                attempt_id=(
                                    f"attempt:{job.job_id}:{backend_id}:unavailable"
                                ),
                                job_id=job.job_id,
                                backend_id=backend_id,
                                status=AttemptStatus.UNAVAILABLE,
                                verdict=JobVerdict.UNAVAILABLE,
                                authority_path="unavailable",
                                probe=probe,
                                diagnostics=(
                                    "auth.portfolio.backend_unavailable",
                                ),
                                reason=f"backend {backend_id} unavailable",
                            )
                        )
                        continue
                    # Capability filter without install.
                    if probe.capabilities is not None and not probe.capabilities.supports(
                        job.logic_family, job.query_kind
                    ):
                        attempts.append(
                            PortfolioAttemptRecord(
                                attempt_id=(
                                    f"attempt:{job.job_id}:{backend_id}:unsupported"
                                ),
                                job_id=job.job_id,
                                backend_id=backend_id,
                                status=AttemptStatus.FAILED,
                                verdict=JobVerdict.UNSUPPORTED,
                                authority_path="unsupported",
                                probe=probe,
                                diagnostics=(
                                    "auth.portfolio.capability_mismatch",
                                ),
                                reason=(
                                    f"backend {backend_id} does not support "
                                    f"{job.logic_family}/{job.query_kind.value}"
                                ),
                            )
                        )
                        continue
                    started = time.monotonic()
                    try:
                        attempt = solver(job, backend_id, probe)
                    except Exception as exc:  # noqa: BLE001 — fail closed
                        attempts.append(
                            PortfolioAttemptRecord(
                                attempt_id=(
                                    f"attempt:{job.job_id}:{backend_id}:error"
                                ),
                                job_id=job.job_id,
                                backend_id=backend_id,
                                status=AttemptStatus.FAILED,
                                verdict=JobVerdict.ERROR,
                                authority_path="unknown",
                                probe=probe,
                                elapsed_ms=int(
                                    (time.monotonic() - started) * 1000
                                ),
                                diagnostics=(
                                    f"auth.portfolio.solver_error:"
                                    f"{type(exc).__name__}",
                                ),
                                reason=str(exc) or type(exc).__name__,
                            )
                        )
                        continue
                    if not isinstance(attempt, PortfolioAttemptRecord):
                        raise PortfolioError(
                            "solver must return PortfolioAttemptRecord"
                        )
                    attempts.append(attempt)
        else:
            # No solver and no precomputed attempts: record unavailable.
            diagnostics.append("auth.portfolio.no_solver_no_attempts")
            for job in bundle.jobs:
                for backend_id in self.backend_ids:
                    probe = probe_by_id[backend_id]
                    attempts.append(
                        PortfolioAttemptRecord(
                            attempt_id=(
                                f"attempt:{job.job_id}:{backend_id}:noop"
                            ),
                            job_id=job.job_id,
                            backend_id=backend_id,
                            status=AttemptStatus.UNAVAILABLE,
                            verdict=JobVerdict.UNAVAILABLE,
                            authority_path="unavailable",
                            probe=probe,
                            diagnostics=("auth.portfolio.no_execution",),
                            reason="portfolio run without solver or attempts",
                        )
                    )

        for attempt in attempts:
            translations.extend(attempt.translations)
            reconstructions.extend(attempt.reconstructions)
            assumptions.extend(attempt.assumption_ids)
            if attempt.timed_out or attempt.status is AttemptStatus.TIMED_OUT:
                timeouts.append(attempt.attempt_id)

        job_results = select_portfolio_results(
            bundle,
            attempts,
            required_backends=self.required_backends,
        )

        decision: AuthorizationDecision | None = None
        if decide:
            policy = self.decision_policy or AuthorizationDecisionPolicy.for_profile(
                bundle.profile_id
            )
            decision = evaluate_authorization_decision(
                bundle, job_results, policy=policy
            )

        resolved_run_id = run_id or (
            "run:" + stable_digest(
                {
                    "bundle": bundle.digest,
                    "attempts": sorted(item.digest for item in attempts),
                }
            )[:24]
        )
        return PortfolioRunResult(
            run_id=resolved_run_id,
            bundle_digest=bundle.digest,
            probes=probes,
            attempts=tuple(attempts),
            job_results=job_results,
            decision=decision,
            assumptions=tuple(sorted(set(assumptions))),
            translations=tuple(
                sorted(translations, key=lambda item: item.translation_id)
            ),
            reconstructions=tuple(
                sorted(
                    reconstructions, key=lambda item: item.reconstruction_id
                )
            ),
            timeouts=tuple(sorted(set(timeouts))),
            diagnostics=tuple(sorted(set(diagnostics))),
        )


def run_authorization_portfolio(
    bundle: AuthorizationQueryBundle,
    **kwargs: Any,
) -> PortfolioRunResult:
    """Module-level helper: run the default authorization portfolio."""

    portfolio = AuthorizationPortfolio(
        backend_ids=tuple(kwargs.pop("backend_ids", ("z3", "cvc5"))),
        required_backends=tuple(kwargs.pop("required_backends", ())),
        decision_policy=kwargs.pop("decision_policy", None),
    )
    return portfolio.run(bundle, **kwargs)


__all__ = [
    "AUTHORIZATION_PORTFOLIO_INTERFACE",
    "AUTHORIZATION_PORTFOLIO_SCHEMA_VERSION",
    "BACKEND_PROBE_SCHEMA_VERSION",
    "AuthorizationPortfolio",
    "BackendAvailability",
    "BackendProbeResult",
    "DEFAULT_BACKEND_EXECUTABLES",
    "PORTFOLIO_ATTEMPT_SCHEMA_VERSION",
    "PORTFOLIO_RUN_SCHEMA_VERSION",
    "PortfolioAttemptRecord",
    "PortfolioError",
    "PortfolioReconstructionRecord",
    "PortfolioRunResult",
    "PortfolioTranslationRecord",
    "probe_backend",
    "probe_backends",
    "result_status_to_job_verdict",
    "run_authorization_portfolio",
    "select_job_result",
    "select_portfolio_results",
]
