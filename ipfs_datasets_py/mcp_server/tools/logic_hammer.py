"""Governed MCP and CLI hammer operations (HAMMER-013).

This module implements the ``## HAMMER-013`` entry of
``docs/logic/itp_hammer_taskboard.todo.md``: *"Provide inspect,
select-premises, translate, run-candidate, reconstruct, retrieve-receipt, and
capability-status operations. Govern execution with explicit policy,
confirmation for native process launch, correlation IDs, structured
unavailable states, and no claim that a candidate proof is verified before
kernel confirmation."*

It is a **thin governance layer** over the already-implemented HAMMER-001
through HAMMER-012 pipeline modules in
:mod:`ipfs_datasets_py.logic.hammers` — this module never re-implements
premise selection, translation, solver execution, reconstruction, or
receipt persistence; it only wires those modules together behind seven
named operations and enforces the interface-level policy the taskboard
requires:

- **Explicit policy** — every operation accepts an optional, versioned
  :class:`~ipfs_datasets_py.logic.hammers.models.HammerPolicy` (and, where
  relevant, a :class:`~ipfs_datasets_py.logic.hammers.policy.PortfolioPolicy`)
  payload; nothing here hard-codes a timeout, solver allow-list, or resource
  budget that bypasses those records' own validation.
- **Confirmation for native process launch** — :func:`hammer_inspect`,
  :func:`hammer_run_candidate`, and :func:`hammer_reconstruct` each spawn a
  real external process (a native ITP frontend/kernel invocation or an
  external ATP/SMT solver). None of them ever launches that process unless
  the caller passes ``confirm_native_execution=True``; otherwise they return
  a structured ``confirmation_required`` response and do nothing.
- **Correlation IDs** — every response carries a ``correlation_id`` (either
  the caller-supplied value or a freshly generated one), so a caller can
  thread one identifier through inspect -> select-premises -> translate ->
  run-candidate -> reconstruct -> retrieve-receipt and correlate the results
  in logs/traces.
- **Structured unavailable states** — a missing ITP toolchain, a missing
  solver executable, an unresolved receipt id, or a denied policy check
  always returns a machine-readable ``status`` (``"unavailable"``,
  ``"policy_denied"``, ``"confirmation_required"``, ``"not_found"``, or
  ``"error"``) plus a human-readable ``error`` — this module never raises an
  uncaught exception across its public operation boundary, and never
  silently substitutes a default value for a capability gap.
- **No premature "verified" claim** — :func:`hammer_run_candidate` only ever
  reports an untrusted solver-derived ``recommended_status`` of
  ``candidate``/``counterexample``/``unknown``/``timeout``/``unavailable``
  (see :func:`~ipfs_datasets_py.logic.hammers.provenance.
  aggregate_recommended_status`) — it can never report ``verified``.
  :func:`hammer_reconstruct` is the only operation whose response may report
  ``verified``, and only when the underlying
  :class:`~ipfs_datasets_py.logic.hammers.models.ReconstructionRecord.
  kernel_accepted` bit — set exclusively from a real kernel subprocess exit
  status/output, never assumed — is ``True``. This mirrors, rather than
  bypasses, the hard trust invariant already enforced by
  :meth:`~ipfs_datasets_py.logic.hammers.models.HammerResult.validate`.

Operations
----------
- :func:`hammer_inspect` — capture a genuine native goal snapshot for an
  incomplete theorem (HAMMER-006 frontends).
- :func:`hammer_select_premises` — deterministically rank premises from a
  content-addressed corpus manifest (HAMMER-003/HAMMER-004).
- :func:`hammer_translate` — lower a single goal/premise construct to
  TPTP/SMT-LIB (HAMMER-007).
- :func:`hammer_run_candidate` — execute a policy-controlled ATP/SMT
  portfolio and normalize its raw output into untrusted evidence
  (HAMMER-008/HAMMER-009).
- :func:`hammer_reconstruct` — reconstruct a native tactic/term from
  candidate evidence and kernel-check it (HAMMER-010).
- :func:`hammer_retrieve_receipt` — fetch a previously persisted, replayable
  receipt (HAMMER-012).
- :func:`hammer_capability_status` — report structured, no-side-effect
  capability evidence for every ITP frontend/reconstructor and allowlisted
  solver family (HAMMER-002/HAMMER-006/HAMMER-010).

:func:`hammer_persist_receipt` is also exposed as a supporting utility (not
one of the seven named operations) so a caller/tests can close the loop from
a hammer run's artifacts to a retrievable receipt id.

See ``docs/logic/itp_hammer_mcp_contract.md`` for the full narrative
contract, request/response schemas, and worked examples.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from typing import Any, Dict, List, Optional, Sequence, Union

from ipfs_datasets_py.logic.hammers import translation as _translation
from ipfs_datasets_py.logic.hammers.corpus import CorpusError, CorpusManifest
from ipfs_datasets_py.logic.hammers.frontends import (
    DEFAULT_TIMEOUT_SECONDS as _DEFAULT_FRONTEND_TIMEOUT_SECONDS,
    FrontendUnavailableError,
    GoalCaptureError,
    get_frontend,
)
from ipfs_datasets_py.logic.hammers.models import (
    EnvironmentLockRecord,
    HammerPolicy,
    HammerRequest,
    HammerResultStatus,
    ITPKind,
    ProofCandidateRecord,
    SolverVerdict,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.policy import (
    PolicyError,
    PortfolioPolicy,
    known_solver_names,
    solver_spec,
)
from ipfs_datasets_py.logic.hammers.portfolio import (
    PortfolioAttemptSpec,
    PortfolioRunResult,
    SolverPortfolio,
)
from ipfs_datasets_py.logic.hammers.premise_selection import (
    GoalFeatures,
    InvalidTopKError,
    PremiseSelectionError,
    select_premises,
)
from ipfs_datasets_py.logic.hammers.provenance import (
    MalformedEvidenceError,
    NormalizedEvidence,
    aggregate_recommended_status,
    build_proof_candidate_record,
    normalize_portfolio_run,
)
from ipfs_datasets_py.logic.hammers.receipts import (
    HammerReceipt,
    ReceiptError,
    ReceiptNotFoundError,
    ReceiptStore,
)
from ipfs_datasets_py.logic.hammers.reconstruction import (
    DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS,
    KernelUnavailableError,
    ReconstructionInputError,
    get_reconstructor,
    reconstruct_candidate,
)

logger = logging.getLogger(__name__)

__all__ = [
    "hammer_inspect",
    "hammer_select_premises",
    "hammer_translate",
    "hammer_run_candidate",
    "hammer_reconstruct",
    "hammer_retrieve_receipt",
    "hammer_persist_receipt",
    "hammer_capability_status",
    "HammerInspectTool",
    "HammerSelectPremisesTool",
    "HammerTranslateTool",
    "HammerRunCandidateTool",
    "HammerReconstructTool",
    "HammerRetrieveReceiptTool",
    "HammerPersistReceiptTool",
    "HammerCapabilityStatusTool",
]

#: Every operation that spawns a genuine native process (an ITP
#: frontend/kernel invocation or an external ATP/SMT solver) and therefore
#: requires ``confirm_native_execution=True`` before it will actually run.
_NATIVE_LAUNCH_OPERATIONS = frozenset({"inspect", "run-candidate", "reconstruct"})

#: Bounded wall-clock budget (seconds) for the lightweight ``--version``
#: metadata probe :func:`hammer_capability_status` performs against an
#: already-discovered solver executable. Mirrors
#: ``scripts/ops/logic/probe_itp_hammer_environment.py``'s own bounded
#: version probe -- never a proof-search invocation.
_VERSION_PROBE_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Governance helpers: correlation ids, response envelopes, confirmation gate
# ---------------------------------------------------------------------------


def _new_correlation_id() -> str:
    return f"hammer-{uuid.uuid4().hex}"


def _resolve_correlation_id(correlation_id: Optional[str]) -> str:
    if correlation_id is not None and str(correlation_id).strip():
        return str(correlation_id)
    return _new_correlation_id()


def _envelope(
    *,
    operation: str,
    correlation_id: str,
    status: str,
    success: bool,
    data: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    capability: Optional[Dict[str, Any]] = None,
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build the standard, structured response envelope shared by every
    hammer operation in this module.

    Every operation always returns this exact top-level shape (see
    ``docs/logic/itp_hammer_mcp_contract.md``) regardless of whether it
    succeeded, was denied by policy, requires confirmation, hit a
    capability gap, or failed outright -- callers never have to guess the
    response shape based on the outcome.
    """

    return {
        "success": bool(success),
        "operation": operation,
        "correlation_id": correlation_id,
        "status": status,
        "data": data,
        "error": error,
        "capability": capability,
        "notes": list(notes) if notes else [],
    }


def _require_native_confirmation(
    operation: str,
    *,
    confirm_native_execution: bool,
    correlation_id: str,
) -> Optional[Dict[str, Any]]:
    """Return a structured ``confirmation_required`` response if
    ``operation`` requires launching a native process and the caller has not
    passed ``confirm_native_execution=True``; otherwise return ``None`` (the
    caller may proceed).
    """

    if operation not in _NATIVE_LAUNCH_OPERATIONS:
        return None
    if confirm_native_execution:
        return None
    return _envelope(
        operation=operation,
        correlation_id=correlation_id,
        status="confirmation_required",
        success=False,
        error=(
            f"operation {operation!r} launches a native ITP/solver process; "
            "it was not executed because confirm_native_execution=True was "
            "not passed"
        ),
        notes=[
            "pass confirm_native_execution=True to explicitly authorize this "
            "native process launch"
        ],
    )


def _policy_from_payload(
    policy: Optional[Union[Dict[str, Any], HammerPolicy]],
) -> HammerPolicy:
    """Build a validated :class:`HammerPolicy` from a caller-supplied dict
    (or pass an already-built instance through), defaulting to the
    conservative :class:`HammerPolicy` baseline (no solvers allowlisted, no
    learned/LLM opt-ins) when ``policy`` is ``None``."""

    if policy is None:
        return HammerPolicy()
    if isinstance(policy, HammerPolicy):
        return policy
    return HammerPolicy.from_dict(policy)


def _portfolio_policy_from_payload(
    portfolio_policy: Optional[Union[Dict[str, Any], PortfolioPolicy]],
    *,
    fallback_hammer_policy: HammerPolicy,
) -> PortfolioPolicy:
    if portfolio_policy is None:
        return PortfolioPolicy(hammer_policy=fallback_hammer_policy)
    if isinstance(portfolio_policy, PortfolioPolicy):
        return portfolio_policy
    return PortfolioPolicy.from_dict(portfolio_policy)


def _load_corpus_manifest(
    *,
    corpus_manifest: Optional[Dict[str, Any]] = None,
    corpus_manifest_path: Optional[str] = None,
) -> CorpusManifest:
    if corpus_manifest is not None:
        return CorpusManifest.from_dict(corpus_manifest)
    if corpus_manifest_path is not None:
        return CorpusManifest.load(corpus_manifest_path)
    raise ValueError(
        "either corpus_manifest (a dict) or corpus_manifest_path (a file "
        "path) must be provided"
    )


# ---------------------------------------------------------------------------
# JSON <-> translation-term deserialization
#
# The HAMMER-007 translation pipeline operates on a typed term AST
# (ipfs_datasets_py.logic.hammers.translation.Term), not on raw goal-statement
# text -- that AST is what lets it distinguish a genuinely first-order
# construct from a dependent/higher-order/opaque one it must fail closed on.
# This module accepts that AST as plain, JSON-serializable dicts (one
# ``{"kind": ..., ...}`` node per Term/TypeRef variant) so MCP/CLI callers
# never need to import the translation module's dataclasses directly.
# ---------------------------------------------------------------------------


def _type_from_dict(data: Dict[str, Any]) -> Any:
    if not isinstance(data, dict) or "kind" not in data:
        raise ValueError(
            f"type payload must be a dict with a 'kind' key, got {data!r}"
        )
    kind = data["kind"]
    if kind == "sort":
        return _translation.SortRef(name=data["name"])
    if kind == "type_var":
        return _translation.TypeVarRef(name=data["name"])
    if kind == "function":
        params = tuple(_type_from_dict(p) for p in data.get("params", []))
        result = _type_from_dict(data["result"])
        return _translation.FunctionTypeRef(params=params, result=result)
    if kind == "dependent":
        return _translation.DependentTypeRef(description=data["description"])
    raise ValueError(
        f"unknown type kind {kind!r}; expected one of "
        "'sort', 'type_var', 'function', 'dependent'"
    )


def _term_from_dict(data: Dict[str, Any]) -> Any:
    if not isinstance(data, dict) or "kind" not in data:
        raise ValueError(
            f"term payload must be a dict with a 'kind' key, got {data!r}"
        )
    kind = data["kind"]
    if kind == "var":
        return _translation.Var(name=data["name"], type=_type_from_dict(data["type"]))
    if kind == "const":
        return _translation.Const(
            name=data["name"],
            type=_type_from_dict(data["type"]),
            opaque=bool(data.get("opaque", False)),
            opaque_reason=data.get("opaque_reason"),
        )
    if kind == "app":
        return _translation.App(
            fn=_term_from_dict(data["fn"]),
            args=tuple(_term_from_dict(a) for a in data.get("args", [])),
        )
    if kind == "lambda":
        params = tuple(
            _translation.LambdaParam(name=p["name"], type=_type_from_dict(p["type"]))
            for p in data.get("params", [])
        )
        return _translation.Lambda(params=params, body=_term_from_dict(data["body"]))
    if kind == "forall":
        return _translation.Forall(
            var=data["var"],
            var_type=_type_from_dict(data["var_type"]),
            body=_term_from_dict(data["body"]),
        )
    if kind == "exists":
        return _translation.Exists(
            var=data["var"],
            var_type=_type_from_dict(data["var_type"]),
            body=_term_from_dict(data["body"]),
        )
    if kind == "not":
        return _translation.Not(term=_term_from_dict(data["term"]))
    if kind == "and":
        return _translation.And(
            left=_term_from_dict(data["left"]), right=_term_from_dict(data["right"])
        )
    if kind == "or":
        return _translation.Or(
            left=_term_from_dict(data["left"]), right=_term_from_dict(data["right"])
        )
    if kind == "implies":
        return _translation.Implies(
            left=_term_from_dict(data["left"]), right=_term_from_dict(data["right"])
        )
    if kind == "iff":
        return _translation.Iff(
            left=_term_from_dict(data["left"]), right=_term_from_dict(data["right"])
        )
    if kind == "eq":
        return _translation.Eq(
            left=_term_from_dict(data["left"]), right=_term_from_dict(data["right"])
        )
    if kind == "bool":
        return _translation.BoolLit(value=bool(data["value"]))
    if kind == "opaque":
        type_payload = data.get("type")
        if type_payload is not None:
            return _translation.Opaque(
                reason=data["reason"], type=_type_from_dict(type_payload)
            )
        return _translation.Opaque(reason=data["reason"])
    raise ValueError(
        f"unknown term kind {kind!r}; expected one of 'var', 'const', 'app', "
        "'lambda', 'forall', 'exists', 'not', 'and', 'or', 'implies', 'iff', "
        "'eq', 'bool', 'opaque'"
    )


# ---------------------------------------------------------------------------
# Operation: inspect
# ---------------------------------------------------------------------------


async def hammer_inspect(
    *,
    itp: str,
    theorem_id: str,
    native_source: str,
    timeout: Optional[float] = None,
    confirm_native_execution: bool = False,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Capture a genuine native :class:`~ipfs_datasets_py.logic.hammers.
    frontends.base.GoalSnapshot` for one incomplete theorem (HAMMER-006).

    Governance: this operation launches a real ``lean``/``coqtop``/
    ``isabelle`` subprocess to elaborate ``native_source`` and therefore
    requires ``confirm_native_execution=True``; otherwise it returns a
    structured ``confirmation_required`` response without executing
    anything.

    Args:
        itp: One of ``"lean"``, ``"coq"``, ``"isabelle"``.
        theorem_id: Stable identifier for the declaration being snapshotted.
        native_source: The native source text (Lean/Coq/Isabelle) containing
            exactly one incomplete-proof marker whose goal state should be
            captured.
        timeout: Optional override of the bounded wall-clock budget for the
            underlying native invocation.
        confirm_native_execution: Must be ``True`` to actually invoke the
            native frontend; see "Governance" above.
        correlation_id: Optional caller-supplied correlation id; a fresh one
            is generated if omitted.
    """

    correlation_id = _resolve_correlation_id(correlation_id)
    operation = "inspect"

    try:
        itp_kind = ITPKind(itp)
    except ValueError:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"unknown itp {itp!r}; expected one of {[k.value for k in ITPKind]!r}",
        )

    frontend = get_frontend(
        itp_kind, timeout=timeout or _DEFAULT_FRONTEND_TIMEOUT_SECONDS
    )
    capability = frontend.capability()
    if not capability.available:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="unavailable",
            success=False,
            error=capability.unavailable_reason,
            capability=capability.to_dict(),
        )

    confirmation = _require_native_confirmation(
        operation,
        confirm_native_execution=confirm_native_execution,
        correlation_id=correlation_id,
    )
    if confirmation is not None:
        confirmation["capability"] = capability.to_dict()
        return confirmation

    try:
        snapshot = frontend.snapshot_goal(
            native_source, theorem_id=theorem_id, timeout=timeout
        )
    except FrontendUnavailableError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="unavailable",
            success=False,
            error=str(exc),
            capability=exc.capability.to_dict(),
        )
    except GoalCaptureError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=str(exc),
        )

    return _envelope(
        operation=operation,
        correlation_id=correlation_id,
        status="ok",
        success=True,
        data={
            "goal_snapshot": snapshot.to_dict(),
            "capability": capability.to_dict(),
        },
    )


# ---------------------------------------------------------------------------
# Operation: select-premises
# ---------------------------------------------------------------------------


async def hammer_select_premises(
    *,
    goal_statement: str,
    corpus_manifest: Optional[Dict[str, Any]] = None,
    corpus_manifest_path: Optional[str] = None,
    theorem_id: Optional[str] = None,
    imports: Optional[Sequence[str]] = None,
    top_k: int = 8,
    policy: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Deterministically rank premises for ``goal_statement`` from a
    content-addressed corpus manifest (HAMMER-003/HAMMER-004).

    Governance: this operation is pure, in-process computation (no native
    process is ever launched), so it never requires
    ``confirm_native_execution``.

    Args:
        goal_statement: The raw (diagnostic) goal statement text.
        corpus_manifest: An already-serialized
            :class:`~ipfs_datasets_py.logic.hammers.corpus.CorpusManifest`
            (``.to_dict()`` output). Mutually exclusive with
            ``corpus_manifest_path``.
        corpus_manifest_path: A file path to a manifest previously written
            by :meth:`~ipfs_datasets_py.logic.hammers.corpus.CorpusManifest.
            save`. Mutually exclusive with ``corpus_manifest``.
        theorem_id: If the goal is itself a corpus theorem, its identity
            (for self-exclusion).
        imports: The goal's module/theory/file dependencies.
        top_k: The enforced selection cutoff (bound on the number of
            premises returned); must not exceed ``policy.max_premises``.
        policy: An optional :class:`~ipfs_datasets_py.logic.hammers.models.
            HammerPolicy` payload; defaults to the conservative baseline.
        correlation_id: Optional caller-supplied correlation id.
    """

    correlation_id = _resolve_correlation_id(correlation_id)
    operation = "select-premises"

    try:
        manifest = _load_corpus_manifest(
            corpus_manifest=corpus_manifest, corpus_manifest_path=corpus_manifest_path
        )
    except (CorpusError, OSError, ValueError, KeyError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"invalid corpus manifest: {exc}",
        )

    try:
        hammer_policy = _policy_from_payload(policy)
    except (ValueError, TypeError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"invalid policy payload: {exc}",
        )

    goal = GoalFeatures.from_statement(
        goal_statement, theorem_id=theorem_id, imports=imports
    )

    try:
        result = select_premises(manifest, goal, top_k=top_k, policy=hammer_policy)
    except InvalidTopKError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="policy_denied",
            success=False,
            error=str(exc),
        )
    except PremiseSelectionError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=str(exc),
        )

    return _envelope(
        operation=operation,
        correlation_id=correlation_id,
        status="ok",
        success=True,
        data={
            "corpus_revision": manifest.revision,
            "selection": result.to_dict(),
        },
    )


# ---------------------------------------------------------------------------
# Operation: translate
# ---------------------------------------------------------------------------


async def hammer_translate(
    *,
    request_id: str,
    source_construct: str,
    term: Dict[str, Any],
    target: str,
    monomorphization: Optional[Dict[str, str]] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Lower one goal/premise construct to TPTP or SMT-LIB (HAMMER-007).

    Governance: pure, in-process computation; never requires
    ``confirm_native_execution``. An unsupported (dependent/higher-order/
    opaque) construct always fails closed: it is reported with
    ``status="unsupported_translation"`` and ``success=False``, never
    silently dropped or coerced into a supported-looking result.

    Args:
        request_id: The owning ``HammerRequest`` id every produced
            :class:`~ipfs_datasets_py.logic.hammers.models.
            TranslationRecord` is stamped with.
        source_construct: Identifier/description of the construct being
            translated (e.g. a goal id or premise id).
        term: A JSON-serializable term AST node -- see this module's
            docstring / ``docs/logic/itp_hammer_mcp_contract.md`` for the
            ``{"kind": ...}`` node schema mirroring
            :mod:`ipfs_datasets_py.logic.hammers.translation`'s ``Term``/
            ``TypeRef`` variants.
        target: ``"tptp"`` or ``"smtlib"``.
        monomorphization: Optional mapping of polymorphic type-variable name
            -> concrete sort name to explicitly monomorphize before
            translation.
        correlation_id: Optional caller-supplied correlation id.
    """

    correlation_id = _resolve_correlation_id(correlation_id)
    operation = "translate"

    try:
        target_enum = TranslationTarget(target)
    except ValueError:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=(
                f"unknown translation target {target!r}; expected one of "
                f"{[t.value for t in TranslationTarget]!r}"
            ),
        )

    try:
        term_obj = _term_from_dict(term)
        mono = {
            name: _translation.SortRef(sort_name)
            for name, sort_name in (monomorphization or {}).items()
        }
    except (KeyError, ValueError, TypeError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"invalid term/monomorphization payload: {exc}",
        )

    try:
        ctx = _translation.TranslationContext(request_id=request_id)
    except ValueError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=str(exc),
        )

    record = ctx.translate(
        source_construct=source_construct,
        term=term_obj,
        target=target_enum,
        monomorphization=mono,
    )

    if record.status is TranslationStatus.UNSUPPORTED:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="unsupported_translation",
            success=False,
            error=record.unsupported_reason,
            data={"translation": record.to_dict()},
            notes=[
                "the construct fails closed rather than silently dropping "
                "semantics; see HAMMER-007's translation contract"
            ],
        )

    return _envelope(
        operation=operation,
        correlation_id=correlation_id,
        status="ok",
        success=True,
        data={
            "translation": record.to_dict(),
            "translation_map": ctx.translation_map.to_dict(),
        },
        notes=(
            ["translation is PARTIAL: see obligations for what must still "
             "be discharged"]
            if record.status is TranslationStatus.PARTIAL
            else []
        ),
    )


# ---------------------------------------------------------------------------
# Operation: run-candidate
# ---------------------------------------------------------------------------


def _determine_recommended_status(
    run_result: PortfolioRunResult,
    normalized: Dict[str, NormalizedEvidence],
) -> HammerResultStatus:
    """Determine the single, untrusted, solver-derived recommended status
    for one portfolio run.

    Never returns :attr:`~ipfs_datasets_py.logic.hammers.models.
    HammerResultStatus.VERIFIED` -- that requires an independent kernel
    reconstruction (see :func:`hammer_reconstruct`), which this operation
    never performs.
    """

    if not run_result.attempts:
        if run_result.denied:
            return HammerResultStatus.UNAVAILABLE
        return HammerResultStatus.UNKNOWN

    if normalized:
        aggregate = aggregate_recommended_status(normalized.values())
        if aggregate is not HammerResultStatus.UNKNOWN:
            return aggregate

    if all(attempt.verdict is SolverVerdict.TIMEOUT for attempt in run_result.attempts):
        return HammerResultStatus.TIMEOUT

    return HammerResultStatus.UNKNOWN


async def hammer_run_candidate(
    *,
    request: Dict[str, Any],
    attempts: List[Dict[str, Any]],
    portfolio_policy: Optional[Dict[str, Any]] = None,
    premise_ids: Optional[Sequence[str]] = None,
    translation_map: Optional[Dict[str, Any]] = None,
    confirm_native_execution: bool = False,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a policy-controlled ATP/SMT solver portfolio and normalize its
    raw output into untrusted candidate/counterexample evidence
    (HAMMER-008/HAMMER-009).

    Governance: this operation launches real external solver subprocesses
    (Z3/CVC5/Vampire/E) and therefore requires
    ``confirm_native_execution=True``; otherwise it returns a structured
    ``confirmation_required`` response without executing anything. The
    response's ``recommended_status`` is always an *untrusted* solver-derived
    signal -- it is never ``verified``; only :func:`hammer_reconstruct` may
    ever report that.

    Args:
        request: A serialized :class:`~ipfs_datasets_py.logic.hammers.
            models.HammerRequest` (``.to_dict()`` output).
        attempts: A list of ``{"translation": <TranslationRecord dict>,
            "solver_name": <str>}`` entries -- each is one requested
            (translation, solver) pairing.
        portfolio_policy: An optional :class:`~ipfs_datasets_py.logic.
            hammers.policy.PortfolioPolicy` payload; defaults to a policy
            wrapping ``request.policy`` with no per-solver overrides.
        premise_ids: The :class:`~ipfs_datasets_py.logic.hammers.models.
            PremiseRecord` ids in scope, cross-referenced against any parsed
            unsat core.
        translation_map: An optional serialized :class:`~ipfs_datasets_py.
            logic.hammers.translation.TranslationMap` to cross-reference
            parsed identifiers against.
        confirm_native_execution: Must be ``True`` to actually run the
            solver portfolio; see "Governance" above.
        correlation_id: Optional caller-supplied correlation id.
    """

    correlation_id = _resolve_correlation_id(correlation_id)
    operation = "run-candidate"

    try:
        request_obj = HammerRequest.from_dict(request)
        request_obj.validate()
    except (KeyError, ValueError, TypeError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"invalid request payload: {exc}",
        )

    try:
        attempt_specs = [
            PortfolioAttemptSpec(
                translation=TranslationRecord.from_dict(entry["translation"]),
                solver_name=entry["solver_name"],
            )
            for entry in attempts
        ]
    except (KeyError, ValueError, TypeError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"invalid attempts payload: {exc}",
        )

    try:
        pf_policy = _portfolio_policy_from_payload(
            portfolio_policy, fallback_hammer_policy=request_obj.policy
        )
        pf_policy.validate()
    except (PolicyError, ValueError, TypeError, KeyError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="policy_denied",
            success=False,
            error=str(exc),
        )

    confirmation = _require_native_confirmation(
        operation,
        confirm_native_execution=confirm_native_execution,
        correlation_id=correlation_id,
    )
    if confirmation is not None:
        return confirmation

    portfolio = SolverPortfolio(pf_policy)
    run_result = portfolio.run(request_obj.request_id, attempt_specs)

    try:
        tmap = (
            _translation.TranslationMap.from_dict(translation_map)
            if translation_map is not None
            else None
        )
    except (KeyError, ValueError, TypeError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"invalid translation_map payload: {exc}",
        )

    normalized = normalize_portfolio_run(
        run_result,
        request_id=request_obj.request_id,
        premise_ids=list(premise_ids or []),
        translation_map=tmap,
    )

    recommended_status = _determine_recommended_status(run_result, normalized)

    proof_candidate = None
    if recommended_status is HammerResultStatus.CANDIDATE:
        for attempt in run_result.attempts:
            evidence = normalized.get(attempt.attempt_id)
            if evidence is not None and evidence.recommended_status is HammerResultStatus.CANDIDATE:
                try:
                    proof_candidate = build_proof_candidate_record(
                        evidence,
                        candidate_id=f"{request_obj.request_id}:{attempt.attempt_id}:candidate",
                        request_id=request_obj.request_id,
                        solver_attempt_id=attempt.attempt_id,
                    )
                except MalformedEvidenceError:  # pragma: no cover - defensive
                    continue
                break

    status = "unavailable" if recommended_status is HammerResultStatus.UNAVAILABLE else "ok"

    return _envelope(
        operation=operation,
        correlation_id=correlation_id,
        status=status,
        success=True,
        data={
            "run_result": run_result.to_dict(),
            "normalized_evidence": {k: v.to_dict() for k, v in normalized.items()},
            "proof_candidate": proof_candidate.to_dict() if proof_candidate else None,
            "recommended_status": recommended_status.value,
        },
        notes=[
            "recommended_status is an UNTRUSTED solver-derived signal; a "
            "candidate proof is never verified until an independent kernel "
            "reconstruction accepts it via the reconstruct operation"
        ],
    )


# ---------------------------------------------------------------------------
# Operation: reconstruct
# ---------------------------------------------------------------------------


async def hammer_reconstruct(
    *,
    request: Dict[str, Any],
    candidate: Dict[str, Any],
    itp: str,
    theorem_id: str,
    native_source: str,
    environment_lock: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    confirm_native_execution: bool = False,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Reconstruct a native tactic/proof term from candidate evidence and
    independently kernel-check it (HAMMER-010) -- the *only* operation in
    this module whose response may ever report a ``verified`` status.

    Governance: this operation launches a real ``lean``/``coqtop``/
    ``isabelle`` subprocess for both goal capture and the kernel check, and
    therefore requires ``confirm_native_execution=True``; otherwise it
    returns a structured ``confirmation_required`` response without
    executing anything. ``status`` in the response is derived *exclusively*
    from :attr:`~ipfs_datasets_py.logic.hammers.models.ReconstructionRecord.
    kernel_accepted` (itself set only from a real kernel subprocess exit
    status/output) -- this function never reports ``verified`` merely
    because a solver claimed success.

    Args:
        request: A serialized :class:`~ipfs_datasets_py.logic.hammers.
            models.HammerRequest`.
        candidate: A serialized :class:`~ipfs_datasets_py.logic.hammers.
            models.ProofCandidateRecord` -- the *untrusted* candidate to
            reconstruct.
        itp: One of ``"lean"``, ``"coq"``, ``"isabelle"``; must match
            ``request["itp"]``.
        theorem_id: Stable identifier for the declaration being
            reconstructed.
        native_source: The exact native source text containing exactly one
            incomplete-proof marker, used both to capture the goal snapshot
            and as the source the reconstruction is substituted into.
        environment_lock: An optional previously pinned
            :class:`~ipfs_datasets_py.logic.hammers.models.
            EnvironmentLockRecord` to reuse; a fresh one is captured from
            the current environment when omitted.
        timeout: Optional override of the bounded wall-clock budget for the
            kernel invocation.
        confirm_native_execution: Must be ``True`` to actually invoke the
            native frontend/kernel; see "Governance" above.
        correlation_id: Optional caller-supplied correlation id.
    """

    correlation_id = _resolve_correlation_id(correlation_id)
    operation = "reconstruct"

    try:
        itp_kind = ITPKind(itp)
    except ValueError:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"unknown itp {itp!r}; expected one of {[k.value for k in ITPKind]!r}",
        )

    try:
        request_obj = HammerRequest.from_dict(request)
        request_obj.validate()
    except (KeyError, ValueError, TypeError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"invalid request payload: {exc}",
        )

    try:
        candidate_obj = ProofCandidateRecord.from_dict(candidate)
        candidate_obj.validate()
    except (KeyError, ValueError, TypeError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"invalid candidate payload: {exc}",
        )

    env_lock_obj = None
    if environment_lock is not None:
        try:
            env_lock_obj = EnvironmentLockRecord.from_dict(environment_lock)
            env_lock_obj.validate()
        except (KeyError, ValueError, TypeError) as exc:
            return _envelope(
                operation=operation,
                correlation_id=correlation_id,
                status="error",
                success=False,
                error=f"invalid environment_lock payload: {exc}",
            )

    frontend = get_frontend(
        itp_kind, timeout=timeout or _DEFAULT_FRONTEND_TIMEOUT_SECONDS
    )
    capability = frontend.capability()
    if not capability.available:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="unavailable",
            success=False,
            error=capability.unavailable_reason,
            capability=capability.to_dict(),
        )

    confirmation = _require_native_confirmation(
        operation,
        confirm_native_execution=confirm_native_execution,
        correlation_id=correlation_id,
    )
    if confirmation is not None:
        confirmation["capability"] = capability.to_dict()
        return confirmation

    try:
        goal_snapshot = frontend.snapshot_goal(
            native_source, theorem_id=theorem_id, timeout=timeout
        )
    except FrontendUnavailableError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="unavailable",
            success=False,
            error=str(exc),
            capability=exc.capability.to_dict(),
        )
    except GoalCaptureError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=str(exc),
        )

    try:
        record, evidence, lock = reconstruct_candidate(
            request=request_obj,
            candidate=candidate_obj,
            goal_snapshot=goal_snapshot,
            native_source=native_source,
            environment_lock=env_lock_obj,
            timeout=timeout,
        )
    except ReconstructionInputError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=str(exc),
        )
    except KernelUnavailableError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="unavailable",
            success=False,
            error=str(exc),
            capability=exc.capability.to_dict(),
        )

    # The trust boundary: "verified" is reported here, and only here, and
    # only because record.kernel_accepted was independently set to True by a
    # real kernel subprocess -- never because a solver "said so".
    final_status = (
        HammerResultStatus.VERIFIED if record.kernel_accepted else HammerResultStatus.CANDIDATE
    )

    return _envelope(
        operation=operation,
        correlation_id=correlation_id,
        status="ok",
        success=True,
        data={
            "reconstruction": record.to_dict(),
            "reconstruction_evidence": evidence.to_dict(),
            "environment_lock": lock.to_dict(),
            "status": final_status.value,
        },
        notes=(
            [
                "status is VERIFIED only because reconstruction.kernel_accepted "
                "is True (an independent kernel check), per the HAMMER-001 "
                "trust contract"
            ]
            if record.kernel_accepted
            else [
                "the target ITP kernel did not accept the reconstruction; the "
                "candidate remains untrusted"
            ]
        ),
    )


# ---------------------------------------------------------------------------
# Operation: retrieve-receipt (and the persist-receipt utility)
# ---------------------------------------------------------------------------


async def hammer_retrieve_receipt(
    *,
    receipt_id: str,
    publishable: bool = False,
    store_root: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch a previously persisted, replayable
    :class:`~ipfs_datasets_py.logic.hammers.receipts.HammerReceipt`
    (HAMMER-012).

    Governance: pure I/O against the local-disk (and, if opted in, IPFS)
    receipt store; never requires ``confirm_native_execution``.

    Args:
        receipt_id: The receipt's content-addressed id.
        publishable: If ``True``, fetch the redacted, publishable view
            (:meth:`~ipfs_datasets_py.logic.hammers.receipts.HammerReceipt.
            to_publishable_dict`) instead of the full, unredacted receipt.
        store_root: Optional override of the :class:`~ipfs_datasets_py.
            logic.hammers.receipts.ReceiptStore` root directory; defaults to
            :func:`~ipfs_datasets_py.logic.hammers.receipts.
            default_receipt_store_root`.
        correlation_id: Optional caller-supplied correlation id.
    """

    correlation_id = _resolve_correlation_id(correlation_id)
    operation = "retrieve-receipt"

    store = ReceiptStore(root_dir=store_root) if store_root else ReceiptStore()

    try:
        if publishable:
            payload = store.get_publishable(receipt_id)
            return _envelope(
                operation=operation,
                correlation_id=correlation_id,
                status="ok",
                success=True,
                data={"receipt": payload, "publishable": True},
            )
        receipt = store.get(receipt_id)
    except ReceiptNotFoundError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="not_found",
            success=False,
            error=str(exc),
        )

    return _envelope(
        operation=operation,
        correlation_id=correlation_id,
        status="ok",
        success=True,
        data={
            "receipt": receipt.to_dict(),
            "publishable": False,
            "is_verified": receipt.is_verified(),
        },
    )


async def hammer_persist_receipt(
    *,
    receipt: Dict[str, Any],
    publish: bool = False,
    store_root: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a caller-assembled
    :class:`~ipfs_datasets_py.logic.hammers.receipts.HammerReceipt` payload
    (a supporting utility, not one of this module's seven named governed
    operations, but exposed here so a caller/test can close the loop from a
    hammer run's artifacts to a retrievable receipt id -- see
    :func:`hammer_retrieve_receipt`).

    Governance: pure I/O against the local-disk (and, if opted in, IPFS)
    receipt store; never requires ``confirm_native_execution``.
    """

    correlation_id = _resolve_correlation_id(correlation_id)
    operation = "persist-receipt"

    try:
        receipt_obj = HammerReceipt.from_dict(receipt)
    except (ReceiptError, KeyError, ValueError, TypeError) as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"invalid receipt payload: {exc}",
        )

    store = ReceiptStore(root_dir=store_root) if store_root else ReceiptStore()
    result = store.put(receipt_obj, publish=publish)

    return _envelope(
        operation=operation,
        correlation_id=correlation_id,
        status="ok",
        success=True,
        data={
            "receipt_id": receipt_obj.receipt_id,
            "persist_result": result.to_dict(),
        },
    )


# ---------------------------------------------------------------------------
# Operation: capability-status
# ---------------------------------------------------------------------------


def _probe_solver_version(executable_path: str, version_args: Sequence[str]) -> Dict[str, Any]:
    """Run a bounded ``--version``-style metadata probe against an
    already-discovered solver executable.

    This is a lightweight metadata query (mirroring
    ``scripts/ops/logic/probe_itp_hammer_environment.py``'s own probe), not
    a proof-search invocation, so it is not gated behind
    ``confirm_native_execution`` -- it never runs untrusted content through
    the solver and never launches a proof search.
    """

    try:
        proc = subprocess.run(
            [executable_path, *version_args],
            capture_output=True,
            text=True,
            timeout=_VERSION_PROBE_TIMEOUT_SECONDS,
        )
        raw = (proc.stdout or proc.stderr or "").strip()
        version = raw.splitlines()[0] if raw else None
        return {"version": version, "version_probe_error": None}
    except Exception as exc:  # pragma: no cover - defensive, environment-dependent
        return {"version": None, "version_probe_error": str(exc)}


async def hammer_capability_status(
    *,
    itps: Optional[Sequence[str]] = None,
    solvers: Optional[Sequence[str]] = None,
    probe_versions: bool = True,
    frontend_timeout: Optional[float] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Report structured, no-proof-search capability evidence for every ITP
    frontend/reconstructor and allowlisted solver family (HAMMER-002/
    HAMMER-006/HAMMER-010).

    Governance: this never invokes a native frontend goal capture, a solver
    proof search, or a kernel check -- only executable discovery
    (``shutil.which``) and, unless disabled via ``probe_versions=False``, a
    bounded ``--version`` metadata probe against an already-discovered
    executable. It therefore never requires ``confirm_native_execution``,
    mirroring ``scripts/ops/logic/probe_itp_hammer_environment.py``'s own
    "no solver invocation by default" design.

    Args:
        itps: Optional subset of ``["lean", "coq", "isabelle"]`` to report
            on; defaults to every :class:`~ipfs_datasets_py.logic.hammers.
            models.ITPKind`.
        solvers: Optional subset of solver family names to report on;
            defaults to every :func:`~ipfs_datasets_py.logic.hammers.
            policy.known_solver_names` entry.
        probe_versions: Whether to additionally run the bounded
            ``--version`` metadata probe for each discovered solver
            executable. When ``False``, this operation performs zero
            subprocess calls.
        frontend_timeout: Optional override of the bounded wall-clock
            budget used when constructing each ITP frontend/reconstructor
            (capability checks themselves never run a proof search
            regardless of this value).
        correlation_id: Optional caller-supplied correlation id.
    """

    correlation_id = _resolve_correlation_id(correlation_id)
    operation = "capability-status"

    try:
        itp_kinds = [ITPKind(value) for value in itps] if itps else list(ITPKind)
    except ValueError as exc:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=f"unknown itp in {itps!r}: {exc}",
        )

    solver_names = list(solvers) if solvers else list(known_solver_names())
    unknown_solvers = [name for name in solver_names if name not in known_solver_names()]
    if unknown_solvers:
        return _envelope(
            operation=operation,
            correlation_id=correlation_id,
            status="error",
            success=False,
            error=(
                f"unknown solver families {unknown_solvers!r}; known families "
                f"are {known_solver_names()!r}"
            ),
        )

    resolved_frontend_timeout = frontend_timeout or _DEFAULT_FRONTEND_TIMEOUT_SECONDS
    resolved_reconstruction_timeout = (
        frontend_timeout or DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS
    )

    itp_report: Dict[str, Any] = {}
    for kind in itp_kinds:
        frontend = get_frontend(kind, timeout=resolved_frontend_timeout)
        frontend_capability = frontend.capability()
        reconstructor = get_reconstructor(kind, timeout=resolved_reconstruction_timeout)
        reconstructor_capability = reconstructor.capability()
        itp_report[kind.value] = {
            "frontend": frontend_capability.to_dict(),
            "reconstruction": reconstructor_capability.to_dict(),
        }

    solver_report: Dict[str, Any] = {}
    for name in solver_names:
        spec = solver_spec(name)
        resolved_path: Optional[str] = None
        for candidate_executable in spec.candidate_executables:
            found = shutil.which(candidate_executable)
            if found:
                resolved_path = found
                break

        entry: Dict[str, Any] = {
            "display_name": spec.display_name,
            "target": spec.target.value,
            "candidate_executables": list(spec.candidate_executables),
            "available": resolved_path is not None,
            "path": resolved_path,
            "version": None,
            "version_probe_error": None,
        }
        if resolved_path is not None and probe_versions:
            entry.update(_probe_solver_version(resolved_path, spec.version_args))
        solver_report[name] = entry

    any_capability_available = any(
        entry["frontend"]["available"] for entry in itp_report.values()
    ) or any(entry["available"] for entry in solver_report.values())

    return _envelope(
        operation=operation,
        correlation_id=correlation_id,
        status="ok",
        success=True,
        data={
            "itps": itp_report,
            "solvers": solver_report,
            "any_capability_available": any_capability_available,
        },
    )


# ---------------------------------------------------------------------------
# OOP wrappers (matching the existing ipfs_datasets_py.mcp_server.tools.
# logic_tools convention of a thin class exposing name/category/tags/execute)
# ---------------------------------------------------------------------------


class _HammerToolBase:
    """Shared OOP wrapper base: routes ``execute(params=..., **kwargs)`` to
    the module-level async operation function, merging ``params`` (a dict,
    if given) with any additional keyword arguments."""

    name: str = ""
    category: str = "logic_hammer"
    tags: List[str] = []
    _func_name: str = ""

    async def execute(self, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        merged: Dict[str, Any] = dict(params or {})
        merged.update(kwargs)
        func = globals()[self._func_name]
        return await func(**merged)


class HammerInspectTool(_HammerToolBase):
    """OOP wrapper for the ``inspect`` hammer MCP tool."""

    name = "hammer_inspect"
    tags = ["logic", "hammer", "itp", "frontend", "governed"]
    _func_name = "hammer_inspect"


class HammerSelectPremisesTool(_HammerToolBase):
    """OOP wrapper for the ``select-premises`` hammer MCP tool."""

    name = "hammer_select_premises"
    tags = ["logic", "hammer", "premise-selection", "governed"]
    _func_name = "hammer_select_premises"


class HammerTranslateTool(_HammerToolBase):
    """OOP wrapper for the ``translate`` hammer MCP tool."""

    name = "hammer_translate"
    tags = ["logic", "hammer", "translation", "tptp", "smtlib", "governed"]
    _func_name = "hammer_translate"


class HammerRunCandidateTool(_HammerToolBase):
    """OOP wrapper for the ``run-candidate`` hammer MCP tool."""

    name = "hammer_run_candidate"
    tags = ["logic", "hammer", "portfolio", "solver", "governed"]
    _func_name = "hammer_run_candidate"


class HammerReconstructTool(_HammerToolBase):
    """OOP wrapper for the ``reconstruct`` hammer MCP tool."""

    name = "hammer_reconstruct"
    tags = ["logic", "hammer", "reconstruction", "kernel", "governed"]
    _func_name = "hammer_reconstruct"


class HammerRetrieveReceiptTool(_HammerToolBase):
    """OOP wrapper for the ``retrieve-receipt`` hammer MCP tool."""

    name = "hammer_retrieve_receipt"
    tags = ["logic", "hammer", "receipts", "governed"]
    _func_name = "hammer_retrieve_receipt"


class HammerPersistReceiptTool(_HammerToolBase):
    """OOP wrapper for the ``persist-receipt`` hammer MCP utility tool."""

    name = "hammer_persist_receipt"
    tags = ["logic", "hammer", "receipts", "governed"]
    _func_name = "hammer_persist_receipt"


class HammerCapabilityStatusTool(_HammerToolBase):
    """OOP wrapper for the ``capability-status`` hammer MCP tool."""

    name = "hammer_capability_status"
    tags = ["logic", "hammer", "capability", "governed"]
    _func_name = "hammer_capability_status"
