"""Canonical Hammer meta-backend (``HammerBackend@1``).

Hammer is a **registry-driven, staged** meta-backend for interactive theorem
prover reconstruction:

1. **Premise selection** — content-addressed corpus ranking (never proof);
2. **SMT/ATP search** — bounded portfolio of untrusted solvers;
3. **Proof candidates** — normalized solver evidence (still untrusted);
4. **Reconstruction** — independent native tactic/term construction;
5. **Kernel receipts** — target ITP kernel check (the only promotion path).

These stages are deliberately separate operations.  A successful solver
search yields **candidate authority only**.  Theorem / verified authority
requires an independent reconstruction whose kernel receipt is accepted.

Provider sets (solvers, reconstructors, kernel backends) are registry-driven:
callers inject provider ids at construction or via
:meth:`HammerBackend.register_*`.  Global public API and the main backend
registry are intentionally not mutated here (LFV-G050 conflict policy).

Interfaces
----------
* ``HammerBackend@1`` — this module.
* ``IsabelleKernelBackend@1`` — independent Isabelle kernel adapter used for
  kernel-receipt stage when the target ITP is Isabelle/HOL.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from ..backends.kernel.isabelle import (
    ISABELLE_KERNEL_BACKEND_VERSION,
    IsabelleKernelBackend,
    IsabelleKernelOutcome,
)
from ..backends.results import (
    CandidateResult,
    ResultAuthority,
    ResultStatus,
    TheoremResult,
    TypedBackendResult,
)
from ..families.models import EvidenceAuthority
from ..ir_core.claims import FrozenMap, stable_digest
from ..ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    ExecutionBounds,
    QueryKind,
    ResourceUsage,
)
from .corpus import CorpusManifest
from .models import (
    HammerPolicy,
    PremiseRecord,
    ReconstructionRecord,
)
from .premise_selection import (
    DETERMINISTIC_BASELINE_METHOD,
    GoalFeatures,
    PremiseSelectionResult,
    select_premises,
)

HAMMER_BACKEND_VERSION: Final = "HammerBackend@1"
HAMMER_STAGE_RECEIPT_VERSION: Final = "hammer-stage-receipt/v1"
HAMMER_PROVIDER_REGISTRY_VERSION: Final = "hammer-provider-registry/v1"

_DEFAULT_SOLVER_PROVIDERS: Final = ("z3", "cvc5", "vampire", "e")
_DEFAULT_RECONSTRUCTOR_PROVIDERS: Final = ("lean", "coq", "isabelle")
_STAGE_ORDER: Final = (
    "premise_selection",
    "smt_atp_search",
    "proof_candidates",
    "reconstruction",
    "kernel_receipts",
)


class HammerBackendError(ValueError):
    """Raised when a Hammer backend request or stage contract is violated."""


class HammerStage(StrEnum):
    """Named pipeline stages kept strictly separate for auditability."""

    PREMISE_SELECTION = "premise_selection"
    SMT_ATP_SEARCH = "smt_atp_search"
    PROOF_CANDIDATES = "proof_candidates"
    RECONSTRUCTION = "reconstruction"
    KERNEL_RECEIPTS = "kernel_receipts"


class HammerStageStatus(StrEnum):
    """Outcome of one isolated stage — never promotes authority alone."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    CANDIDATE_ONLY = "candidate_only"
    VERIFIED = "verified"


@runtime_checkable
class SolverProvider(Protocol):
    """Minimal protocol for a registry-driven SMT/ATP search provider."""

    provider_id: str

    def is_available(self) -> bool:
        ...

    def search(
        self,
        *,
        translation: Mapping[str, Any],
        premises: Sequence[PremiseRecord],
        bounds: ExecutionBounds,
    ) -> Mapping[str, Any]:
        """Return untrusted solver evidence.  Must never claim kernel acceptance."""

        ...


@runtime_checkable
class ReconstructorProvider(Protocol):
    """Minimal protocol for a registry-driven reconstruction provider."""

    provider_id: str
    itp: str

    def is_available(self) -> bool:
        ...

    def reconstruct(
        self,
        *,
        candidate: Mapping[str, Any],
        native_source: str,
        bounds: ExecutionBounds,
    ) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class HammerProviderSpec:
    """One registry entry for a solver or reconstructor provider."""

    provider_id: str
    kind: str
    available: bool = True
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise HammerBackendError("provider_id must be a non-empty string")
        if self.kind not in {"solver", "reconstructor", "kernel"}:
            raise HammerBackendError(
                "kind must be one of 'solver', 'reconstructor', 'kernel'"
            )
        if not isinstance(self.available, bool):
            raise HammerBackendError("available must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "kind": self.kind,
            "metadata": self.metadata.to_dict()
            if hasattr(self.metadata, "to_dict")
            else dict(self.metadata),
            "provider_id": self.provider_id,
        }


@dataclass(frozen=True, slots=True)
class HammerProviderRegistry:
    """Immutable snapshot of registry-driven provider sets."""

    solvers: tuple[HammerProviderSpec, ...]
    reconstructors: tuple[HammerProviderSpec, ...]
    kernels: tuple[HammerProviderSpec, ...]
    schema_version: str = HAMMER_PROVIDER_REGISTRY_VERSION

    def __post_init__(self) -> None:
        for group_name, group in (
            ("solvers", self.solvers),
            ("reconstructors", self.reconstructors),
            ("kernels", self.kernels),
        ):
            if not isinstance(group, tuple):
                raise HammerBackendError(f"{group_name} must be a tuple")
            ids = [item.provider_id for item in group]
            if len(ids) != len(set(ids)):
                raise HammerBackendError(f"{group_name} provider ids must be unique")

    def solver_ids(self) -> tuple[str, ...]:
        return tuple(item.provider_id for item in self.solvers)

    def reconstructor_ids(self) -> tuple[str, ...]:
        return tuple(item.provider_id for item in self.reconstructors)

    def kernel_ids(self) -> tuple[str, ...]:
        return tuple(item.provider_id for item in self.kernels)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kernels": [item.to_dict() for item in self.kernels],
            "reconstructors": [item.to_dict() for item in self.reconstructors],
            "schema_version": self.schema_version,
            "solvers": [item.to_dict() for item in self.solvers],
        }


@dataclass(frozen=True, slots=True)
class HammerStageReceipt:
    """Auditable receipt for exactly one pipeline stage."""

    stage: HammerStage
    status: HammerStageStatus
    provider_ids: tuple[str, ...] = ()
    authority: ResultAuthority = ResultAuthority.CANDIDATE
    payload: FrozenMap = field(default_factory=FrozenMap)
    diagnostics: tuple[str, ...] = ()
    schema_version: str = HAMMER_STAGE_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "stage",
            self.stage if isinstance(self.stage, HammerStage) else HammerStage(self.stage),
        )
        object.__setattr__(
            self,
            "status",
            self.status
            if isinstance(self.status, HammerStageStatus)
            else HammerStageStatus(self.status),
        )
        object.__setattr__(
            self,
            "provider_ids",
            tuple(str(item) for item in self.provider_ids),
        )
        object.__setattr__(
            self,
            "authority",
            self.authority
            if isinstance(self.authority, ResultAuthority)
            else ResultAuthority(self.authority),
        )
        # Fail-closed: no stage except kernel_receipts may claim theorem authority,
        # and kernel_receipts may only do so when status is VERIFIED.
        if self.authority is ResultAuthority.THEOREM:
            if self.stage is not HammerStage.KERNEL_RECEIPTS:
                raise HammerBackendError(
                    "only the kernel_receipts stage may claim theorem authority"
                )
            if self.status is not HammerStageStatus.VERIFIED:
                raise HammerBackendError(
                    "theorem authority requires kernel_receipts status=verified"
                )
        if (
            self.stage is HammerStage.SMT_ATP_SEARCH
            or self.stage is HammerStage.PROOF_CANDIDATES
        ) and self.authority is not ResultAuthority.CANDIDATE:
            raise HammerBackendError(
                "search and proof-candidate stages are candidate authority only"
            )

    @property
    def receipt_id(self) -> str:
        return f"hammer-stage:{self.stage.value}:{stable_digest(self.to_dict())}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "diagnostics": list(self.diagnostics),
            "payload": self.payload.to_dict()
            if hasattr(self.payload, "to_dict")
            else dict(self.payload),
            "provider_ids": list(self.provider_ids),
            "schema_version": self.schema_version,
            "stage": self.stage.value,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class HammerSearchCandidate:
    """Untrusted proof candidate produced by SMT/ATP search.

    Intentionally has **no** verified / kernel_accepted field.
    """

    candidate_id: str
    provider_id: str
    verdict: str
    premise_ids: tuple[str, ...] = ()
    evidence_digest: str = ""
    raw_excerpt: str = ""
    reconstructed: bool = False

    def __post_init__(self) -> None:
        if self.reconstructed:
            raise HammerBackendError(
                "HammerSearchCandidate cannot be marked reconstructed; "
                "use the reconstruction stage"
            )
        if not self.candidate_id or not str(self.candidate_id).strip():
            raise HammerBackendError("candidate_id must be non-empty")
        if not self.provider_id or not str(self.provider_id).strip():
            raise HammerBackendError("provider_id must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "evidence_digest": self.evidence_digest,
            "premise_ids": list(self.premise_ids),
            "provider_id": self.provider_id,
            "raw_excerpt": self.raw_excerpt,
            "reconstructed": False,
            "verdict": self.verdict,
        }


@dataclass(frozen=True, slots=True)
class HammerBackendOutcome:
    """Full staged outcome of one HammerBackend invocation."""

    request_digest: str
    stages: tuple[HammerStageReceipt, ...]
    result: TypedBackendResult
    premises: tuple[PremiseRecord, ...] = ()
    candidates: tuple[HammerSearchCandidate, ...] = ()
    reconstruction: ReconstructionRecord | None = None
    kernel_outcome: IsabelleKernelOutcome | None = None
    provider_registry: HammerProviderRegistry | None = None
    interface_version: str = HAMMER_BACKEND_VERSION

    def __post_init__(self) -> None:
        if self.interface_version != HAMMER_BACKEND_VERSION:
            raise HammerBackendError(
                f"unsupported Hammer backend interface: {self.interface_version!r}"
            )
        stage_names = [receipt.stage for receipt in self.stages]
        if len(stage_names) != len(set(stage_names)):
            raise HammerBackendError("stage receipts must be unique by stage")
        # Unreconstructed success is candidate only.
        if self.result.status is ResultStatus.PROVED:
            if self.reconstruction is None or not self.reconstruction.kernel_accepted:
                if self.kernel_outcome is None or not self.kernel_outcome.receipt.accepted:
                    raise HammerBackendError(
                        "proved results require accepted reconstruction or kernel receipt"
                    )
        if any(
            candidate.reconstructed for candidate in self.candidates
        ):  # pragma: no cover - frozen by candidate ctor
            raise HammerBackendError("candidates must remain unreconstructed")

    def stage(self, name: HammerStage | str) -> HammerStageReceipt | None:
        target = name if isinstance(name, HammerStage) else HammerStage(name)
        for receipt in self.stages:
            if receipt.stage is target:
                return receipt
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [item.to_dict() for item in self.candidates],
            "interface_version": self.interface_version,
            "kernel_outcome": (
                self.kernel_outcome.to_dict()
                if self.kernel_outcome is not None
                else None
            ),
            "premises": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)  # type: ignore[arg-type]
                for item in self.premises
            ],
            "provider_registry": (
                self.provider_registry.to_dict()
                if self.provider_registry is not None
                else None
            ),
            "reconstruction": (
                self.reconstruction.to_dict()
                if self.reconstruction is not None
                else None
            ),
            "request_digest": self.request_digest,
            "result": self.result.to_dict(),
            "stages": [item.to_dict() for item in self.stages],
        }


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise HammerBackendError(
            f"{field_name} must be a non-empty string without NUL bytes"
        )
    return value.strip()


def _frozen(value: Mapping[str, Any] | FrozenMap | None) -> FrozenMap:
    if value is None:
        return FrozenMap()
    if isinstance(value, FrozenMap):
        return value
    return FrozenMap(dict(value))


def _result_id(backend_id: str, digest: str) -> str:
    return f"result:{backend_id}:{digest[:24]}"


class _CallableSolverProvider:
    """Adapter wrapping a callable as a :class:`SolverProvider`."""

    def __init__(
        self,
        provider_id: str,
        runner: Callable[..., Mapping[str, Any]],
        *,
        available: bool = True,
    ) -> None:
        self.provider_id = _text(provider_id, "provider_id")
        self._runner = runner
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def search(
        self,
        *,
        translation: Mapping[str, Any],
        premises: Sequence[PremiseRecord],
        bounds: ExecutionBounds,
    ) -> Mapping[str, Any]:
        return self._runner(
            translation=translation, premises=premises, bounds=bounds
        )


class _CallableReconstructorProvider:
    """Adapter wrapping a callable as a :class:`ReconstructorProvider`."""

    def __init__(
        self,
        provider_id: str,
        itp: str,
        runner: Callable[..., Mapping[str, Any]],
        *,
        available: bool = True,
    ) -> None:
        self.provider_id = _text(provider_id, "provider_id")
        self.itp = _text(itp, "itp")
        self._runner = runner
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def reconstruct(
        self,
        *,
        candidate: Mapping[str, Any],
        native_source: str,
        bounds: ExecutionBounds,
    ) -> Mapping[str, Any]:
        return self._runner(
            candidate=candidate, native_source=native_source, bounds=bounds
        )


class HammerBackend:
    """Canonical Hammer meta-backend implementing ``HammerBackend@1``.

    Stages are exposed both as dedicated methods and as a single
    :meth:`run` orchestration that records a :class:`HammerStageReceipt`
    for each stage.  Unreconstructed solver success always remains
    candidate authority.
    """

    interface_version: Final = HAMMER_BACKEND_VERSION
    backend_id: Final = "hammer"
    aliases: Final = frozenset(
        {"hammer-backend", "itp-hammer", "sledgehammer-compat"}
    )
    stage_order: Final = _STAGE_ORDER

    def __init__(
        self,
        *,
        backend_version: str = "hammer",
        solver_providers: Sequence[SolverProvider | str] | None = None,
        reconstructor_providers: Sequence[ReconstructorProvider | str]
        | None = None,
        isabelle_kernel: IsabelleKernelBackend | None = None,
        corpus: CorpusManifest | None = None,
        policy: HammerPolicy | None = None,
        logic_families: Sequence[str] = (
            "hammer",
            "higher_order",
            "fol",
            "smt",
            "software_verification",
            "isabelle",
            "lean",
            "coq",
            "rocq",
        ),
    ) -> None:
        self.backend_version = _text(backend_version, "backend_version")
        self._solvers: dict[str, SolverProvider] = {}
        self._reconstructors: dict[str, ReconstructorProvider] = {}
        self._isabelle_kernel = isabelle_kernel
        self._corpus = corpus
        self._policy = policy or HammerPolicy()
        self.capabilities = BackendCapabilities(
            logic_families=tuple(logic_families),
            query_kinds=(QueryKind.THEOREM_PROOF,),
            deterministic=True,
        )

        if solver_providers is None:
            for name in _DEFAULT_SOLVER_PROVIDERS:
                self.register_solver_id(name, available=False)
        else:
            for provider in solver_providers:
                if isinstance(provider, str):
                    self.register_solver_id(provider, available=False)
                else:
                    self.register_solver(provider)

        if reconstructor_providers is None:
            for name in _DEFAULT_RECONSTRUCTOR_PROVIDERS:
                self.register_reconstructor_id(name, available=False)
        else:
            for provider in reconstructor_providers:
                if isinstance(provider, str):
                    self.register_reconstructor_id(provider, available=False)
                else:
                    self.register_reconstructor(provider)

    # -- registry ----------------------------------------------------------

    def register_solver(self, provider: SolverProvider) -> None:
        if not isinstance(provider, SolverProvider):
            raise HammerBackendError("provider must implement SolverProvider")
        self._solvers[_text(provider.provider_id, "provider_id")] = provider

    def register_solver_id(
        self,
        provider_id: str,
        *,
        available: bool = False,
        runner: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        if runner is None:

            def _unavailable(**_kwargs: Any) -> Mapping[str, Any]:
                return {
                    "verdict": "unavailable",
                    "provider_id": provider_id,
                    "available": False,
                }

            runner = _unavailable
        self.register_solver(
            _CallableSolverProvider(provider_id, runner, available=available)
        )

    def register_reconstructor(self, provider: ReconstructorProvider) -> None:
        if not isinstance(provider, ReconstructorProvider):
            raise HammerBackendError(
                "provider must implement ReconstructorProvider"
            )
        self._reconstructors[_text(provider.provider_id, "provider_id")] = provider

    def register_reconstructor_id(
        self,
        provider_id: str,
        *,
        itp: str | None = None,
        available: bool = False,
        runner: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        resolved_itp = itp or provider_id

        if runner is None:

            def _unavailable(**_kwargs: Any) -> Mapping[str, Any]:
                return {
                    "kernel_accepted": False,
                    "provider_id": provider_id,
                    "available": False,
                }

            runner = _unavailable
        self.register_reconstructor(
            _CallableReconstructorProvider(
                provider_id, resolved_itp, runner, available=available
            )
        )

    def provider_registry(self) -> HammerProviderRegistry:
        kernels: list[HammerProviderSpec] = []
        if self._isabelle_kernel is not None:
            kernels.append(
                HammerProviderSpec(
                    provider_id=self._isabelle_kernel.backend_id,
                    kind="kernel",
                    available=self._isabelle_kernel.is_available(),
                    metadata=FrozenMap(
                        {
                            "interface": ISABELLE_KERNEL_BACKEND_VERSION,
                        }
                    ),
                )
            )
        else:
            kernels.append(
                HammerProviderSpec(
                    provider_id="isabelle",
                    kind="kernel",
                    available=False,
                    metadata=FrozenMap({"interface": ISABELLE_KERNEL_BACKEND_VERSION}),
                )
            )
        return HammerProviderRegistry(
            solvers=tuple(
                HammerProviderSpec(
                    provider_id=provider_id,
                    kind="solver",
                    available=provider.is_available(),
                )
                for provider_id, provider in sorted(self._solvers.items())
            ),
            reconstructors=tuple(
                HammerProviderSpec(
                    provider_id=provider_id,
                    kind="reconstructor",
                    available=provider.is_available(),
                    metadata=FrozenMap({"itp": getattr(provider, "itp", provider_id)}),
                )
                for provider_id, provider in sorted(self._reconstructors.items())
            ),
            kernels=tuple(kernels),
        )

    def supports(self, logic_family: str, query_kind: QueryKind) -> bool:
        return self.capabilities.supports(logic_family, query_kind)

    def is_available(self) -> bool:
        """True when at least one solver or reconstructor/kernel is available."""

        if any(p.is_available() for p in self._solvers.values()):
            return True
        if any(p.is_available() for p in self._reconstructors.values()):
            return True
        if self._isabelle_kernel is not None and self._isabelle_kernel.is_available():
            return True
        return False

    # -- stages ------------------------------------------------------------

    def select_premises(
        self,
        *,
        goal_statement: str,
        goal_features: GoalFeatures | None = None,
        corpus: CorpusManifest | None = None,
        top_k: int = 8,
        policy: HammerPolicy | None = None,
    ) -> tuple[PremiseSelectionResult | None, HammerStageReceipt]:
        """Stage 1: premise selection (never proof authority)."""

        manifest = corpus if corpus is not None else self._corpus
        if manifest is None:
            receipt = HammerStageReceipt(
                stage=HammerStage.PREMISE_SELECTION,
                status=HammerStageStatus.SKIPPED,
                authority=ResultAuthority.CANDIDATE,
                diagnostics=("no corpus registered; premise selection skipped",),
                payload=FrozenMap({"method": DETERMINISTIC_BASELINE_METHOD}),
            )
            return None, receipt

        features = goal_features or GoalFeatures.from_statement(goal_statement)
        try:
            selection = select_premises(
                manifest,
                features,
                top_k=top_k,
                policy=policy or self._policy,
            )
        except Exception as error:  # noqa: BLE001 — stage isolation
            receipt = HammerStageReceipt(
                stage=HammerStage.PREMISE_SELECTION,
                status=HammerStageStatus.FAILED,
                authority=ResultAuthority.CANDIDATE,
                diagnostics=(str(error)[:512],),
            )
            return None, receipt

        premises = tuple(selection.selected)
        receipt = HammerStageReceipt(
            stage=HammerStage.PREMISE_SELECTION,
            status=HammerStageStatus.COMPLETED,
            authority=ResultAuthority.CANDIDATE,
            provider_ids=("deterministic_baseline",),
            payload=FrozenMap(
                {
                    "method": DETERMINISTIC_BASELINE_METHOD,
                    "selected_count": len(premises),
                    "top_k": top_k,
                    "corpus_revision": selection.corpus_revision,
                    "premise_ids": [item.premise_id for item in premises],
                }
            ),
        )
        return selection, receipt

    def search_candidates(
        self,
        *,
        translation: Mapping[str, Any] | None = None,
        premises: Sequence[PremiseRecord] = (),
        bounds: ExecutionBounds | None = None,
        provider_ids: Sequence[str] | None = None,
    ) -> tuple[
        tuple[HammerSearchCandidate, ...],
        HammerStageReceipt,
        HammerStageReceipt,
    ]:
        """Stage 2+3: SMT/ATP search producing **candidate-only** results.

        A solver ``proved``/``unsat`` verdict never becomes theorem authority
        here.  The stage receipt authority is always
        :attr:`ResultAuthority.CANDIDATE`.

        Returns ``(candidates, search_receipt, proof_candidate_receipt)``.
        """

        bounds = bounds or ExecutionBounds(timeout_ms=1000, max_steps=32)
        translation = dict(translation or {"target": "smtlib", "status": "supported"})
        requested = (
            tuple(provider_ids)
            if provider_ids is not None
            else tuple(self._solvers.keys())
        )
        candidates: list[HammerSearchCandidate] = []
        diagnostics: list[str] = []
        used: list[str] = []

        for provider_id in requested:
            provider = self._solvers.get(provider_id)
            if provider is None:
                diagnostics.append(f"unknown solver provider: {provider_id}")
                continue
            if not provider.is_available():
                diagnostics.append(f"solver provider unavailable: {provider_id}")
                continue
            used.append(provider_id)
            raw = provider.search(
                translation=translation, premises=premises, bounds=bounds
            )
            verdict = str(raw.get("verdict", "unknown")).lower()
            # Hard gate: never promote search success.
            if verdict in {"proved", "unsat", "theorem", "verified"}:
                verdict_label = (
                    "proved"
                    if verdict in {"proved", "theorem", "verified"}
                    else verdict
                )
            else:
                verdict_label = verdict
            candidate_id = str(
                raw.get("candidate_id")
                or (
                    f"candidate:{provider_id}:"
                    f"{stable_digest({'verdict': verdict_label, 'provider': provider_id})[:16]}"
                )
            )
            premise_ids = tuple(
                str(item)
                for item in (
                    raw.get("premise_ids") or [p.premise_id for p in premises]
                )
            )
            candidates.append(
                HammerSearchCandidate(
                    candidate_id=candidate_id,
                    provider_id=provider_id,
                    verdict=verdict_label,
                    premise_ids=premise_ids,
                    evidence_digest=str(
                        raw.get("evidence_digest")
                        or stable_digest(
                            {"raw": dict(raw), "provider": provider_id}
                        )
                    ),
                    raw_excerpt=str(
                        raw.get("raw_excerpt") or raw.get("stdout") or ""
                    )[:512],
                )
            )

        if not used and not candidates:
            status = HammerStageStatus.UNAVAILABLE
        elif any(c.verdict in {"proved", "unsat"} for c in candidates):
            status = HammerStageStatus.CANDIDATE_ONLY
        elif candidates:
            status = HammerStageStatus.COMPLETED
        else:
            status = HammerStageStatus.FAILED

        search_receipt = HammerStageReceipt(
            stage=HammerStage.SMT_ATP_SEARCH,
            status=status,
            provider_ids=tuple(used),
            authority=ResultAuthority.CANDIDATE,
            payload=FrozenMap(
                {
                    "attempted_providers": list(requested),
                    "candidate_count": len(candidates),
                    "conclusive_unreconstructed": any(
                        c.verdict in {"proved", "unsat"} for c in candidates
                    ),
                }
            ),
            diagnostics=tuple(diagnostics),
        )
        candidate_receipt = HammerStageReceipt(
            stage=HammerStage.PROOF_CANDIDATES,
            status=(
                HammerStageStatus.CANDIDATE_ONLY
                if candidates
                else HammerStageStatus.SKIPPED
            ),
            provider_ids=tuple(used),
            authority=ResultAuthority.CANDIDATE,
            payload=FrozenMap(
                {
                    "candidates": [c.to_dict() for c in candidates],
                    "unreconstructed": True,
                    "theorem_authority_forbidden": True,
                }
            ),
            diagnostics=tuple(diagnostics),
        )
        return tuple(candidates), search_receipt, candidate_receipt

    def reconstruct_candidate(
        self,
        *,
        candidate: HammerSearchCandidate | Mapping[str, Any],
        native_source: str,
        itp: str = "isabelle",
        bounds: ExecutionBounds | None = None,
        provider_id: str | None = None,
    ) -> tuple[Mapping[str, Any] | None, HammerStageReceipt]:
        """Stage 4: independent reconstruction (still not final authority)."""

        bounds = bounds or ExecutionBounds(timeout_ms=5000, max_steps=64)
        candidate_map = (
            candidate.to_dict()
            if isinstance(candidate, HammerSearchCandidate)
            else dict(candidate)
        )
        resolved_provider = provider_id or itp
        provider = self._reconstructors.get(resolved_provider)
        if provider is None:
            # Fall back to any reconstructor matching the ITP.
            for item in self._reconstructors.values():
                if getattr(item, "itp", "") == itp:
                    provider = item
                    resolved_provider = item.provider_id
                    break
        if provider is None:
            return None, HammerStageReceipt(
                stage=HammerStage.RECONSTRUCTION,
                status=HammerStageStatus.UNAVAILABLE,
                authority=ResultAuthority.RECONSTRUCTION,
                diagnostics=(f"no reconstructor registered for itp={itp!r}",),
            )
        if not provider.is_available():
            return None, HammerStageReceipt(
                stage=HammerStage.RECONSTRUCTION,
                status=HammerStageStatus.UNAVAILABLE,
                provider_ids=(resolved_provider,),
                authority=ResultAuthority.RECONSTRUCTION,
                diagnostics=(f"reconstructor unavailable: {resolved_provider}",),
            )

        raw = provider.reconstruct(
            candidate=candidate_map,
            native_source=native_source,
            bounds=bounds,
        )
        kernel_accepted = bool(raw.get("kernel_accepted", False))
        status = (
            HammerStageStatus.COMPLETED
            if kernel_accepted
            else HammerStageStatus.FAILED
        )
        # Reconstruction stage itself does not grant theorem authority —
        # that is reserved for the kernel_receipts stage.
        receipt = HammerStageReceipt(
            stage=HammerStage.RECONSTRUCTION,
            status=status,
            provider_ids=(resolved_provider,),
            authority=ResultAuthority.RECONSTRUCTION,
            payload=FrozenMap(
                {
                    "candidate_id": candidate_map.get("candidate_id", ""),
                    "kernel_accepted": kernel_accepted,
                    "itp": itp,
                    "checked_source_digest": str(
                        raw.get("checked_source_digest") or ""
                    ),
                }
            ),
            diagnostics=tuple(
                str(item) for item in (raw.get("diagnostics") or ()) if item
            ),
        )
        return dict(raw), receipt

    def check_kernel(
        self,
        request: BackendRequest,
        *,
        kernel: IsabelleKernelBackend | None = None,
    ) -> tuple[IsabelleKernelOutcome | None, HammerStageReceipt]:
        """Stage 5: independent kernel receipt (sole theorem-authority path)."""

        backend = kernel if kernel is not None else self._isabelle_kernel
        if backend is None:
            return None, HammerStageReceipt(
                stage=HammerStage.KERNEL_RECEIPTS,
                status=HammerStageStatus.UNAVAILABLE,
                authority=ResultAuthority.CANDIDATE,
                diagnostics=("no Isabelle kernel backend registered",),
            )
        if not backend.is_available():
            # Still run so unavailable receipts are produced for audit.
            pass

        outcome = backend.run(request)
        if outcome.receipt.accepted and outcome.result.status is ResultStatus.PROVED:
            status = HammerStageStatus.VERIFIED
            authority = ResultAuthority.THEOREM
        elif outcome.result.status is ResultStatus.CANDIDATE:
            status = HammerStageStatus.CANDIDATE_ONLY
            authority = ResultAuthority.CANDIDATE
        elif outcome.result.status is ResultStatus.UNAVAILABLE:
            status = HammerStageStatus.UNAVAILABLE
            authority = ResultAuthority.CANDIDATE
        else:
            status = HammerStageStatus.FAILED
            authority = ResultAuthority.CANDIDATE

        receipt = HammerStageReceipt(
            stage=HammerStage.KERNEL_RECEIPTS,
            status=status,
            provider_ids=(backend.backend_id,),
            authority=authority,
            payload=FrozenMap(
                {
                    "kernel_interface": ISABELLE_KERNEL_BACKEND_VERSION,
                    "receipt_id": outcome.receipt.receipt_id,
                    "accepted": outcome.receipt.accepted,
                    "path_metadata": outcome.receipt.path_metadata.to_dict(),
                    "result_status": outcome.result.status.value,
                }
            ),
            diagnostics=tuple(outcome.receipt.diagnostics),
        )
        return outcome, receipt

    # -- orchestration -----------------------------------------------------

    def _validate_request(self, request: BackendRequest) -> None:
        if not isinstance(request, BackendRequest):
            raise HammerBackendError("request must be a BackendRequest")
        if request.requested_backend_id and request.requested_backend_id not in {
            self.backend_id,
            *self.aliases,
        }:
            raise HammerBackendError(
                f"request targets {request.requested_backend_id!r}, not {self.backend_id!r}"
            )
        if not self.capabilities.supports(request.logic_family, request.query_kind):
            raise HammerBackendError(
                f"{self.backend_id} does not support {request.logic_family}/"
                f"{request.query_kind.value}"
            )

    def _payload(self, request: BackendRequest) -> dict[str, Any]:
        return request.payload.to_dict()

    def run(
        self,
        request: BackendRequest,
        *,
        stages: Sequence[HammerStage | str] | None = None,
    ) -> HammerBackendOutcome:
        """Run the requested stages (default: all five) and normalize results.

        Unreconstructed solver success is always returned as
        :class:`CandidateResult` with :attr:`ResultAuthority.CANDIDATE`.
        """

        self._validate_request(request)
        payload = self._payload(request)
        selected_stages = (
            tuple(
                s if isinstance(s, HammerStage) else HammerStage(s)
                for s in stages
            )
            if stages is not None
            else tuple(HammerStage(name) for name in self.stage_order)
        )

        stage_receipts: list[HammerStageReceipt] = []
        premises: tuple[PremiseRecord, ...] = ()
        candidates: tuple[HammerSearchCandidate, ...] = ()
        reconstruction_payload: Mapping[str, Any] | None = None
        kernel_outcome: IsabelleKernelOutcome | None = None
        usage = ResourceUsage()

        goal_statement = str(
            payload.get("goal_statement")
            or payload.get("goal")
            or payload.get("source")
            or "goal"
        )
        native_source = str(
            payload.get("native_source")
            or payload.get("source")
            or payload.get("isabelle")
            or ""
        )
        top_k = int(payload.get("top_k", 8))
        itp = str(payload.get("itp") or payload.get("target_itp") or "isabelle")

        if HammerStage.PREMISE_SELECTION in selected_stages:
            selection, receipt = self.select_premises(
                goal_statement=goal_statement,
                top_k=top_k,
            )
            stage_receipts.append(receipt)
            if selection is not None:
                premises = tuple(selection.selected)

        if (
            HammerStage.SMT_ATP_SEARCH in selected_stages
            or HammerStage.PROOF_CANDIDATES in selected_stages
        ):
            candidates, search_receipt, candidate_receipt = self.search_candidates(
                translation=payload.get("translation")
                if isinstance(payload.get("translation"), Mapping)
                else None,
                premises=premises,
                bounds=request.bounds,
                provider_ids=payload.get("solver_providers"),
            )
            if HammerStage.SMT_ATP_SEARCH in selected_stages:
                stage_receipts.append(search_receipt)
            if HammerStage.PROOF_CANDIDATES in selected_stages:
                stage_receipts.append(candidate_receipt)

        if HammerStage.RECONSTRUCTION in selected_stages:
            if candidates and native_source:
                reconstruction_payload, recon_receipt = self.reconstruct_candidate(
                    candidate=candidates[0],
                    native_source=native_source,
                    itp=itp,
                    bounds=request.bounds,
                    provider_id=payload.get("reconstructor_provider"),
                )
            else:
                reconstruction_payload = None
                recon_receipt = HammerStageReceipt(
                    stage=HammerStage.RECONSTRUCTION,
                    status=HammerStageStatus.SKIPPED,
                    authority=ResultAuthority.RECONSTRUCTION,
                    diagnostics=(
                        "reconstruction skipped: missing candidate or native_source",
                    ),
                )
            stage_receipts.append(recon_receipt)

        if HammerStage.KERNEL_RECEIPTS in selected_stages:
            # Prefer an embedded Isabelle kernel request when source is present.
            if native_source and (
                self._isabelle_kernel is not None
                or str(payload.get("encoding", "")).startswith("isabelle")
                or itp == "isabelle"
            ):
                # Always retarget to the Isabelle kernel backend id and a
                # corrected Isabelle payload — the hammer request id may be
                # "hammer" and must not fail the kernel's backend filter.
                kernel_payload = {
                    "encoding": "isabelle",
                    "source": native_source,
                    "path": str(
                        payload.get("path")
                        or payload.get("file_name")
                        or "Goal.thy"
                    ),
                }
                if isinstance(payload.get("translation"), Mapping):
                    kernel_payload["translation"] = dict(payload["translation"])
                kernel_request = BackendRequest(
                    request_id=request.request_id,
                    claim_id=request.claim_id,
                    declaration_id=request.declaration_id,
                    claim_digest=request.claim_digest,
                    obligation_id=request.obligation_id,
                    obligation_digest=request.obligation_digest,
                    assumption_ids=request.assumption_ids,
                    logic_family="isabelle",
                    query_kind=QueryKind.THEOREM_PROOF,
                    bounds=request.bounds,
                    payload=FrozenMap(kernel_payload),
                    requested_backend_id="isabelle",
                )
                kernel_outcome, kernel_receipt = self.check_kernel(kernel_request)
                stage_receipts.append(kernel_receipt)
            else:
                stage_receipts.append(
                    HammerStageReceipt(
                        stage=HammerStage.KERNEL_RECEIPTS,
                        status=HammerStageStatus.SKIPPED,
                        authority=ResultAuthority.CANDIDATE,
                        diagnostics=("kernel receipt stage skipped",),
                    )
                )

        # Normalize final typed result — fail closed on authority.
        registry = self.provider_registry()
        proved = (
            kernel_outcome is not None
            and kernel_outcome.receipt.accepted
            and kernel_outcome.result.status is ResultStatus.PROVED
        )
        recon_accepted = bool(
            reconstruction_payload and reconstruction_payload.get("kernel_accepted")
        )

        if proved:
            # Prefer the kernel's theorem result, re-tagged under hammer backend id.
            kernel_result = kernel_outcome.result
            result: TypedBackendResult = TheoremResult(
                result_id=_result_id(self.backend_id, request.digest),
                status=ResultStatus.PROVED,
                authority=ResultAuthority.THEOREM,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                bounds=request.bounds,
                assumptions=request.assumption_ids,
                usage=kernel_result.usage,
                translation_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
                witness={
                    "kernel_receipt_id": kernel_outcome.receipt.receipt_id,
                    "path_metadata": kernel_outcome.receipt.path_metadata.to_dict(),
                    "stages": [s.stage.value for s in stage_receipts],
                },
                metadata={
                    "adapter_interface": HAMMER_BACKEND_VERSION,
                    "provider_registry": registry.to_dict(),
                    "stages": [s.to_dict() for s in stage_receipts],
                },
                diagnostics=kernel_result.diagnostics,
                reason="",
            )
        elif recon_accepted and not proved:
            # Reconstruction without an accepted kernel receipt stays reconstruction
            # authority / candidate surface — never silent theorem promotion.
            result = CandidateResult(
                result_id=_result_id(self.backend_id, request.digest),
                status=ResultStatus.CANDIDATE,
                authority=ResultAuthority.CANDIDATE,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                bounds=request.bounds,
                assumptions=request.assumption_ids,
                usage=usage,
                translation_ceiling=EvidenceAuthority.ADVISORY,
                witness={
                    "candidate_kind": "reconstructed_awaiting_kernel_receipt",
                    "stages": [s.stage.value for s in stage_receipts],
                },
                metadata={
                    "adapter_interface": HAMMER_BACKEND_VERSION,
                    "provider_registry": registry.to_dict(),
                    "stages": [s.to_dict() for s in stage_receipts],
                },
                diagnostics=(
                    "reconstruction reported acceptance but kernel receipt was not verified",
                ),
                reason="unreconstructed_or_unverified_kernel",
            )
        elif any(c.verdict in {"proved", "unsat"} for c in candidates):
            # Unreconstructed solver success is candidate only.
            result = CandidateResult(
                result_id=_result_id(self.backend_id, request.digest),
                status=ResultStatus.CANDIDATE,
                authority=ResultAuthority.CANDIDATE,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                bounds=request.bounds,
                assumptions=request.assumption_ids,
                usage=usage,
                translation_ceiling=EvidenceAuthority.ADVISORY,
                witness={
                    "candidate_kind": "unreconstructed_solver_success",
                    "candidates": [c.to_dict() for c in candidates],
                    "stages": [s.stage.value for s in stage_receipts],
                    "theorem_authority_forbidden": True,
                },
                metadata={
                    "adapter_interface": HAMMER_BACKEND_VERSION,
                    "provider_registry": registry.to_dict(),
                    "stages": [s.to_dict() for s in stage_receipts],
                },
                diagnostics=(
                    "solver reported success; result remains candidate until "
                    "independent reconstruction and kernel receipt",
                ),
                reason="unreconstructed_solver_success",
            )
        elif kernel_outcome is not None:
            # Surface kernel non-success through hammer without authority upgrade.
            kr = kernel_outcome.result
            if isinstance(kr, CandidateResult):
                result = CandidateResult(
                    result_id=_result_id(self.backend_id, request.digest),
                    status=kr.status,
                    authority=ResultAuthority.CANDIDATE,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    bounds=request.bounds,
                    assumptions=request.assumption_ids,
                    usage=kr.usage,
                    translation_ceiling=EvidenceAuthority.ADVISORY,
                    witness={
                        **dict(kr.witness or {}),
                        "stages": [s.stage.value for s in stage_receipts],
                    },
                    metadata={
                        "adapter_interface": HAMMER_BACKEND_VERSION,
                        "provider_registry": registry.to_dict(),
                        "stages": [s.to_dict() for s in stage_receipts],
                        "kernel_receipt": kernel_outcome.receipt.to_dict(),
                    },
                    diagnostics=kr.diagnostics,
                    reason=kr.reason,
                )
            else:
                result = CandidateResult(
                    result_id=_result_id(self.backend_id, request.digest),
                    status=(
                        ResultStatus.UNAVAILABLE
                        if kr.status is ResultStatus.UNAVAILABLE
                        else ResultStatus.CANDIDATE
                    ),
                    authority=ResultAuthority.CANDIDATE,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    bounds=request.bounds,
                    assumptions=request.assumption_ids,
                    usage=kr.usage,
                    translation_ceiling=EvidenceAuthority.ADVISORY,
                    witness={
                        "kernel_status": kr.status.value,
                        "stages": [s.stage.value for s in stage_receipts],
                    },
                    metadata={
                        "adapter_interface": HAMMER_BACKEND_VERSION,
                        "provider_registry": registry.to_dict(),
                        "stages": [s.to_dict() for s in stage_receipts],
                    },
                    diagnostics=kr.diagnostics,
                    reason=kr.reason or kr.status.value,
                )
        else:
            result = CandidateResult(
                result_id=_result_id(self.backend_id, request.digest),
                status=ResultStatus.CANDIDATE,
                authority=ResultAuthority.CANDIDATE,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                bounds=request.bounds,
                assumptions=request.assumption_ids,
                usage=usage,
                translation_ceiling=EvidenceAuthority.ADVISORY,
                witness={
                    "candidate_kind": "no_conclusive_evidence",
                    "stages": [s.stage.value for s in stage_receipts],
                },
                metadata={
                    "adapter_interface": HAMMER_BACKEND_VERSION,
                    "provider_registry": registry.to_dict(),
                    "stages": [s.to_dict() for s in stage_receipts],
                },
                diagnostics=("no conclusive solver or kernel evidence",),
                reason="no_conclusive_evidence",
            )

        return HammerBackendOutcome(
            request_digest=request.digest,
            stages=tuple(stage_receipts),
            result=result,
            premises=premises,
            candidates=candidates,
            reconstruction=None,
            kernel_outcome=kernel_outcome,
            provider_registry=registry,
        )


__all__ = [
    "HAMMER_BACKEND_VERSION",
    "HAMMER_PROVIDER_REGISTRY_VERSION",
    "HAMMER_STAGE_RECEIPT_VERSION",
    "HammerBackend",
    "HammerBackendError",
    "HammerBackendOutcome",
    "HammerProviderRegistry",
    "HammerProviderSpec",
    "HammerSearchCandidate",
    "HammerStage",
    "HammerStageReceipt",
    "HammerStageStatus",
    "ReconstructorProvider",
    "SolverProvider",
]
