"""Persist replayable hammer receipts through IPFS-aware storage (HAMMER-012).

This module implements the ``## HAMMER-012`` entry of
``docs/logic/itp_hammer_taskboard.todo.md``:

    Persist canonical request, selected premises, translation artifacts,
    solver candidates, reconstruction sources, environment lock, and
    verification outcome with content digests or CIDs. Support local-disk
    fallback and redact private theorem sources, credentials, and raw
    prompts from publishable receipts.

Where this sits in the pipeline
--------------------------------
Every earlier hammer stage already produces its own versioned,
content-addressed record:

- HAMMER-001/``.models`` — :class:`~.models.HammerRequest` (the canonical
  request), :class:`~.models.PremiseRecord`, :class:`~.models.
  TranslationRecord`, :class:`~.models.SolverAttemptRecord`,
  :class:`~.models.ProofCandidateRecord`, :class:`~.models.
  ReconstructionRecord`, :class:`~.models.EnvironmentLockRecord`, and the
  final :class:`~.models.HammerResult` (the verification outcome — the
  *only* record whose ``status`` may assert ``VERIFIED``, and only when it
  carries a kernel-accepted reconstruction; see HAMMER-001's trust
  invariant).
- HAMMER-003/``.corpus`` — the content-addressed premise corpus manifest
  every :class:`~.models.PremiseRecord` is drawn from.
- HAMMER-008/``.portfolio`` — :class:`~.portfolio.SolverAttemptEvidence`,
  the out-of-band raw solver stdout/stderr/trace behind each
  :class:`~.models.SolverAttemptRecord`.
- HAMMER-009/``.provenance`` — :class:`~.provenance.NormalizedEvidence`,
  the structural, content-addressed normalization of that raw solver
  evidence.
- HAMMER-010/``.reconstruction`` — :class:`~.reconstruction.
  ReconstructionEvidence`, the out-of-band checked source, kernel
  stdout/stderr, and exit status behind each :class:`~.models.
  ReconstructionRecord`.
- HAMMER-011/``.fallbacks`` — an optional :class:`~.fallbacks.
  DecompositionPlan`, carrying any redacted, human-reviewed LLM-suggested
  subgoal text from the recovery pipeline.

None of those records are individually enough to *replay* a hammer run: a
:class:`~.models.HammerResult` alone references digests
(``raw_output_digest``, ``kernel_output_digest``, ...) rather than the
out-of-band bytes those digests were computed from, and nothing upstream of
this module durably stores that bundle together, addresses it by content,
or persists it anywhere durable (IPFS or local disk). This module is the
final, dedicated persistence layer:

- :class:`HammerReceipt` bundles the canonical :class:`~.models.
  HammerResult` (request, premises, translations, solver attempts, proof
  candidate, reconstruction, environment lock, and status) together with
  the out-of-band evidence (:class:`~.reconstruction.ReconstructionEvidence`,
  :class:`~.portfolio.SolverAttemptEvidence`, :class:`~.provenance.
  NormalizedEvidence`, an optional :class:`~.fallbacks.DecompositionPlan`)
  into one coherent, content-addressed, versioned bundle. ``receipt_id`` is
  always a deterministic content digest (see :func:`~.corpus.
  compute_content_digest`) over that bundle — never a caller-supplied,
  mutable label — so two byte-identical receipts always resolve to the same
  id.
- :func:`build_publishable_view` / :meth:`HammerReceipt.to_publishable_dict`
  produce a redacted view safe to share publicly: private theorem sources
  (the request's own goal statement, translated formula text, checked
  reconstruction source, kernel/solver raw output, proof-step formula text,
  and decomposition subgoal statements) are replaced with a placeholder
  carrying only a length and a content digest, and every remaining string
  leaf is additionally scanned for common credential shapes (API keys,
  bearer/JWT tokens, private-key blocks, ...) and scrubbed. This is a
  *derived*, non-replayable view — only the full, unredacted receipt is
  meant to be replayed.
- :class:`ReceiptStore` is the IPFS-aware persistence layer: every
  ``put()`` always writes to a local, content-addressed disk cache (so the
  system works with zero external dependencies), and — only when opted in
  via ``use_ipfs``/an injected backend — additionally attempts to push the
  same bytes through :mod:`ipfs_datasets_py.ipfs_backend_router` and record
  the resulting CID. Any IPFS failure (no daemon, no ``ipfs`` binary, no
  network) is caught and silently falls back to the local-disk copy, which
  remains the source of truth either way — this is the "local-disk
  fallback" the taskboard entry requires.

Trust boundary
--------------
This module never re-derives or upgrades a verification outcome. It only
serializes/deserializes the :class:`~.models.HammerResult` produced
upstream — :meth:`HammerReceipt.validate` re-runs
:meth:`~.models.HammerResult.validate` (whose ``VERIFIED`` invariant cannot
be bypassed) and additionally requires every piece of out-of-band evidence
to reference the *same* ``request_id``/``attempt_id``/``candidate_id`` as
the result it is bundled with, so a receipt can never silently mix evidence
from two unrelated runs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .corpus import compute_content_digest
from .fallbacks import DecompositionPlan
from .models import (
    SCHEMA_VERSION,
    HammerResult,
    _isoformat,
    _parse_datetime,
    _require_schema_version,
    _utcnow,
)
from .portfolio import SolverAttemptEvidence
from .provenance import NormalizedEvidence
from .reconstruction import ReconstructionEvidence

__all__ = [
    "SCHEMA_VERSION",
    "ReceiptError",
    "ReceiptValidationError",
    "ReceiptStorageError",
    "ReceiptNotFoundError",
    "HammerReceipt",
    "StorageLocation",
    "PersistResult",
    "ReceiptStore",
    "build_publishable_view",
    "scrub_credential_text",
    "compute_receipt_digest",
    "default_receipt_store_root",
    "persist_hammer_receipt",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReceiptError(ValueError):
    """Base class for all receipt persistence/validation errors."""


class ReceiptValidationError(ReceiptError):
    """Raised when a :class:`HammerReceipt`'s nested records are internally
    inconsistent (e.g. out-of-band evidence referencing a ``request_id``,
    ``attempt_id``, or ``candidate_id`` not present in the bundled
    :class:`~.models.HammerResult`)."""


class ReceiptStorageError(RuntimeError):
    """Raised when a receipt could be neither read from nor written to any
    available backend (IPFS and local disk both failed). This is never
    raised merely because IPFS is unavailable — that case falls back to
    local disk silently."""


class ReceiptNotFoundError(ReceiptError):
    """Raised when a requested receipt id does not exist in the local-disk
    cache and either no IPFS backend is configured or the backend could not
    resolve it."""


# ---------------------------------------------------------------------------
# Credential / secret scrubbing
# ---------------------------------------------------------------------------

#: Dict/JSON key names that always cause a value to be fully redacted,
#: regardless of its shape (defense in depth for structured credential
#: fields that a free-text pattern below might miss).
_SENSITIVE_KEY_RE = re.compile(
    r"(pass(word|wd)?|secret|api[_-]?key|access[_-]?key|private[_-]?key"
    r"|auth(orization)?|token|credential|bearer)",
    re.IGNORECASE,
)

#: Free-text patterns matching common credential/secret shapes. Applied to
#: every remaining string leaf of a publishable receipt as a final,
#: defense-in-depth pass — independent of which field the text was found
#: in.
_CREDENTIAL_VALUE_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens (ghp_/gho_/ghu_/ghs_/ghr_)
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),  # GitHub fine-grained PAT
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style secret keys
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{10,}", re.IGNORECASE),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
]

_CREDENTIAL_PLACEHOLDER = "<redacted:credential>"


def scrub_credential_text(text: str) -> str:
    """Replace any credential-shaped substring of ``text`` with a fixed
    placeholder.

    This is a best-effort, pattern-based scan (AWS/GitHub/Slack/OpenAI-style
    keys, bearer tokens, JWTs, PEM private-key blocks) — it is not a
    substitute for never embedding a real secret in a diagnostic string in
    the first place, but it provides defense-in-depth for
    :func:`build_publishable_view`.
    """

    if not isinstance(text, str) or not text:
        return text
    scrubbed = text
    for pattern in _CREDENTIAL_VALUE_PATTERNS:
        scrubbed = pattern.sub(_CREDENTIAL_PLACEHOLDER, scrubbed)
    return scrubbed


def _scrub_tree(value: Any) -> Any:
    """Recursively scrub ``value`` (a JSON-like tree of dict/list/str/...).

    Any dict key matching :data:`_SENSITIVE_KEY_RE` has its entire value
    replaced regardless of shape; every remaining string leaf is passed
    through :func:`scrub_credential_text`.
    """

    if isinstance(value, dict):
        scrubbed: Dict[str, Any] = {}
        for key, sub_value in value.items():
            if isinstance(key, str) and _SENSITIVE_KEY_RE.search(key):
                scrubbed[key] = _CREDENTIAL_PLACEHOLDER
            else:
                scrubbed[key] = _scrub_tree(sub_value)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_tree(item) for item in value]
    if isinstance(value, str):
        return scrub_credential_text(value)
    return value


def _redact_text_field(
    container: Optional[Dict[str, Any]],
    key: str,
    label: str,
    notes: List[str],
) -> None:
    """Replace ``container[key]`` (if a non-empty string) with a
    length+digest placeholder, recording ``label`` in ``notes``."""

    if not container:
        return
    value = container.get(key)
    if not isinstance(value, str) or not value:
        return
    digest = compute_content_digest({label: value})
    container[key] = f"<redacted:{label} length={len(value)} digest={digest}>"
    notes.append(label)


# ---------------------------------------------------------------------------
# HammerReceipt
# ---------------------------------------------------------------------------


@dataclass
class HammerReceipt:
    """A single, content-addressed, replayable bundle of every artifact
    produced by one hammer run.

    Attributes:
        schema_version: Schema version of this record.
        receipt_id: Deterministic content digest of this receipt's payload
            (computed automatically at construction time if left blank;
            never accepted as an unverified caller-supplied label).
        result: The canonical :class:`~.models.HammerResult` — request,
            selected premises, translation artifacts, solver attempts,
            proof candidate, reconstruction, environment lock, and the
            final verification outcome.
        reconstruction_evidence: Out-of-band :class:`~.reconstruction.
            ReconstructionEvidence` (the checked native source, the
            reconstructed tactic/term text, and the kernel's raw
            stdout/stderr/exit status) behind ``result.reconstruction``, if
            any reconstruction was attempted.
        solver_evidence: Out-of-band :class:`~.portfolio.
            SolverAttemptEvidence` (exact argv, input digest, raw
            stdout/stderr, solver trace) for zero or more of
            ``result.solver_attempts``.
        normalized_evidence: Zero or more :class:`~.provenance.
            NormalizedEvidence` records normalizing that raw solver
            evidence into structural proof steps / unsat cores / models.
        decomposition_plan: The HAMMER-011 recovery :class:`~.fallbacks.
            DecompositionPlan`, if the run went through the failure-recovery
            pipeline.
        created_at: When this receipt was assembled.
        notes: Free-form, non-authoritative diagnostic notes.
        metadata: Free-form, non-authoritative caller metadata. Never
            trusted for correctness; still scrubbed on publication.
    """

    schema_version: str = SCHEMA_VERSION
    receipt_id: str = ""
    result: Optional[HammerResult] = None
    reconstruction_evidence: Optional[ReconstructionEvidence] = None
    solver_evidence: List[SolverAttemptEvidence] = field(default_factory=list)
    normalized_evidence: List[NormalizedEvidence] = field(default_factory=list)
    decomposition_plan: Optional[DecompositionPlan] = None
    created_at: datetime = field(default_factory=_utcnow)
    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()
        if not self.receipt_id:
            self.receipt_id = compute_content_digest(self._digest_payload())

    # -- validation ---------------------------------------------------

    def validate(self) -> None:  # noqa: C901 - inherently a coherence checklist
        """Validate every nested record and cross-record coherence.

        Raises:
            ReceiptValidationError: If ``result`` is missing/invalid, or if
                any piece of out-of-band evidence does not belong to
                ``result`` (mismatched ``request_id``/``attempt_id``/
                ``candidate_id``/``reconstruction_id``).
        """

        _require_schema_version(self.schema_version, owner="HammerReceipt")

        if self.result is None or not isinstance(self.result, HammerResult):
            raise ReceiptValidationError("HammerReceipt.result must be a HammerResult")
        self.result.validate()
        request_id = self.result.request.request_id

        if self.reconstruction_evidence is not None:
            if not isinstance(self.reconstruction_evidence, ReconstructionEvidence):
                raise ReceiptValidationError(
                    "HammerReceipt.reconstruction_evidence must be a "
                    "ReconstructionEvidence"
                )
            self.reconstruction_evidence.validate()
            if self.reconstruction_evidence.request_id != request_id:
                raise ReceiptValidationError(
                    "HammerReceipt.reconstruction_evidence.request_id "
                    f"{self.reconstruction_evidence.request_id!r} does not match "
                    f"result.request.request_id {request_id!r}"
                )
            if (
                self.result.reconstruction is not None
                and self.reconstruction_evidence.reconstruction_id
                and self.reconstruction_evidence.reconstruction_id
                != self.result.reconstruction.reconstruction_id
            ):
                raise ReceiptValidationError(
                    "HammerReceipt.reconstruction_evidence.reconstruction_id does "
                    "not match result.reconstruction.reconstruction_id"
                )
            if (
                self.result.proof_candidate is not None
                and self.reconstruction_evidence.candidate_id
                and self.reconstruction_evidence.candidate_id
                != self.result.proof_candidate.candidate_id
            ):
                raise ReceiptValidationError(
                    "HammerReceipt.reconstruction_evidence.candidate_id does not "
                    "match result.proof_candidate.candidate_id"
                )

        if not isinstance(self.solver_evidence, list):
            raise ReceiptValidationError("HammerReceipt.solver_evidence must be a list")
        known_attempt_ids = {a.attempt_id for a in self.result.solver_attempts}
        for evidence in self.solver_evidence:
            if not isinstance(evidence, SolverAttemptEvidence):
                raise ReceiptValidationError(
                    "HammerReceipt.solver_evidence must contain SolverAttemptEvidence"
                )
            if evidence.attempt_id not in known_attempt_ids:
                raise ReceiptValidationError(
                    f"HammerReceipt.solver_evidence references unknown "
                    f"attempt_id {evidence.attempt_id!r}"
                )

        if not isinstance(self.normalized_evidence, list):
            raise ReceiptValidationError(
                "HammerReceipt.normalized_evidence must be a list"
            )
        for evidence in self.normalized_evidence:
            if not isinstance(evidence, NormalizedEvidence):
                raise ReceiptValidationError(
                    "HammerReceipt.normalized_evidence must contain NormalizedEvidence"
                )
            evidence.validate()
            if evidence.request_id != request_id:
                raise ReceiptValidationError(
                    "HammerReceipt.normalized_evidence entry request_id "
                    f"{evidence.request_id!r} does not match "
                    f"result.request.request_id {request_id!r}"
                )
            if evidence.attempt_id not in known_attempt_ids:
                raise ReceiptValidationError(
                    "HammerReceipt.normalized_evidence entry references unknown "
                    f"attempt_id {evidence.attempt_id!r}"
                )

        if self.decomposition_plan is not None:
            if not isinstance(self.decomposition_plan, DecompositionPlan):
                raise ReceiptValidationError(
                    "HammerReceipt.decomposition_plan must be a DecompositionPlan"
                )
            self.decomposition_plan.validate()
            if self.decomposition_plan.request_id != request_id:
                raise ReceiptValidationError(
                    "HammerReceipt.decomposition_plan.request_id does not match "
                    "result.request.request_id"
                )

        if not isinstance(self.notes, list) or not all(
            isinstance(n, str) for n in self.notes
        ):
            raise ReceiptValidationError("HammerReceipt.notes must be a list of strings")
        if not isinstance(self.metadata, dict):
            raise ReceiptValidationError("HammerReceipt.metadata must be a dict")

    # -- serialization --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain, JSON-compatible dictionary (the full,
        unredacted, replayable form)."""

        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "result": self.result.to_dict(),
            "reconstruction_evidence": (
                self.reconstruction_evidence.to_dict()
                if self.reconstruction_evidence
                else None
            ),
            "solver_evidence": [e.to_dict() for e in self.solver_evidence],
            "normalized_evidence": [e.to_dict() for e in self.normalized_evidence],
            "decomposition_plan": (
                self.decomposition_plan.to_dict() if self.decomposition_plan else None
            ),
            "created_at": _isoformat(self.created_at),
            "notes": list(self.notes),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HammerReceipt":
        """Deserialize from a plain dictionary produced by :meth:`to_dict`."""

        data = dict(data)
        data["result"] = HammerResult.from_dict(data["result"])
        if data.get("reconstruction_evidence"):
            data["reconstruction_evidence"] = ReconstructionEvidence.from_dict(
                data["reconstruction_evidence"]
            )
        else:
            data["reconstruction_evidence"] = None
        data["solver_evidence"] = [
            SolverAttemptEvidence.from_dict(e) for e in data.get("solver_evidence", [])
        ]
        data["normalized_evidence"] = [
            NormalizedEvidence.from_dict(e) for e in data.get("normalized_evidence", [])
        ]
        if data.get("decomposition_plan"):
            data["decomposition_plan"] = DecompositionPlan.from_dict(
                data["decomposition_plan"]
            )
        else:
            data["decomposition_plan"] = None
        if "created_at" in data:
            data["created_at"] = _parse_datetime(data["created_at"])
        return cls(**data)

    def _digest_payload(self) -> Dict[str, Any]:
        """The subset of :meth:`to_dict` that determines ``receipt_id`` —
        excludes the id itself and non-authoritative bookkeeping
        (``created_at``, ``notes``, ``metadata``) so two runs that produced
        byte-identical trust-contract content always resolve to the same
        receipt id regardless of when they were persisted or what
        diagnostic notes were attached."""

        payload = self.to_dict()
        payload.pop("receipt_id", None)
        payload.pop("created_at", None)
        payload.pop("notes", None)
        payload.pop("metadata", None)
        return payload

    def is_verified(self) -> bool:
        """Return whether the bundled result asserts a kernel-checked
        theorem (delegates to :meth:`~.models.HammerResult.is_verified`)."""

        return self.result is not None and self.result.is_verified()

    def to_publishable_dict(self) -> Dict[str, Any]:
        """Return a redacted, safe-to-publish view of this receipt.

        See :func:`build_publishable_view` for exactly what is redacted.
        """

        return build_publishable_view(self)


def compute_receipt_digest(receipt: HammerReceipt) -> str:
    """Recompute the content digest a :class:`HammerReceipt` *should* carry
    as ``receipt_id`` from its current field values.

    Useful for verifying that a stored receipt has not been tampered with:
    ``compute_receipt_digest(receipt) == receipt.receipt_id`` should always
    hold for any receipt that was constructed normally (never with an
    explicit, mismatched ``receipt_id`` override).
    """

    return compute_content_digest(receipt._digest_payload())


# ---------------------------------------------------------------------------
# Publishable (redacted) view
# ---------------------------------------------------------------------------


def build_publishable_view(receipt: HammerReceipt) -> Dict[str, Any]:
    """Build a redacted, safe-to-publish view of ``receipt``.

    Redacted (replaced with a ``<redacted:label length=N digest=...>``
    placeholder that reveals only length and a content digest, never the
    raw text):

    - ``result.request.goal_statement`` — the private theorem/goal text.
    - Every ``result.translations[i].translated_text`` — the private goal
      lowered to TPTP/SMT-LIB.
    - ``result.proof_candidate.certificate`` — may embed private formula
      literals derived from the goal.
    - ``reconstruction_evidence.checked_source`` /
      ``reconstructed_proof_text`` / ``stdout`` / ``stderr`` — the full
      native source submitted to the kernel and its raw output.
    - Each ``solver_evidence[i].raw_stdout`` / ``raw_stderr`` /
      ``solver_trace`` — raw external-solver output.
    - Each ``normalized_evidence[i].proof_steps[j].formula`` — raw formula
      text embedded in a normalized proof step.
    - Each ``decomposition_plan.subgoals[i].statement`` — the raw subgoal
      text (native-structural subgoals are also derived from the private
      goal; LLM-suggested subgoals additionally already carry a
      ``redacted_suggestion`` placeholder from HAMMER-011's own redaction
      gate, which is left untouched and is the only subgoal text a
      publishable receipt ever surfaces).

    After those targeted redactions, every remaining string leaf in the
    payload is scanned by :func:`scrub_credential_text` (via
    :func:`_scrub_tree`), and any dict key that looks like a credential
    field name (``password``, ``token``, ``secret``, ``api_key``, ...) has
    its value fully replaced — this is what "redact ... credentials ...
    from publishable receipts" means operationally, applied independent of
    *where* a secret-shaped string happens to appear (caller metadata,
    diagnostic notes, environment lock executable paths, ...).

    Returns:
        A new dictionary (the input ``receipt`` and its nested records are
        never mutated); includes ``"visibility": "publishable"``,
        ``"redaction_notes"`` (sorted list of redacted field labels), and
        ``"publishable_digest"`` (a content digest of this redacted
        payload, computed before those two bookkeeping keys are added, for
        independent integrity verification of the published copy).
    """

    data = receipt.to_dict()
    redaction_notes: List[str] = []

    request = data["result"]["request"]
    _redact_text_field(request, "goal_statement", "private-theorem-goal", redaction_notes)

    for translation in data["result"].get("translations", []) or []:
        _redact_text_field(
            translation,
            "translated_text",
            "private-theorem-translation",
            redaction_notes,
        )

    candidate = data["result"].get("proof_candidate")
    if candidate is not None:
        _redact_text_field(
            candidate,
            "certificate",
            "private-theorem-candidate-certificate",
            redaction_notes,
        )

    reconstruction_evidence = data.get("reconstruction_evidence")
    if reconstruction_evidence is not None:
        _redact_text_field(
            reconstruction_evidence,
            "checked_source",
            "private-theorem-checked-source",
            redaction_notes,
        )
        _redact_text_field(
            reconstruction_evidence,
            "reconstructed_proof_text",
            "private-theorem-proof-text",
            redaction_notes,
        )
        _redact_text_field(
            reconstruction_evidence, "stdout", "kernel-stdout", redaction_notes
        )
        _redact_text_field(
            reconstruction_evidence, "stderr", "kernel-stderr", redaction_notes
        )

    for evidence in data.get("solver_evidence", []) or []:
        _redact_text_field(evidence, "raw_stdout", "solver-stdout", redaction_notes)
        _redact_text_field(evidence, "raw_stderr", "solver-stderr", redaction_notes)
        _redact_text_field(evidence, "solver_trace", "solver-trace", redaction_notes)

    for evidence in data.get("normalized_evidence", []) or []:
        for step in evidence.get("proof_steps", []) or []:
            _redact_text_field(step, "formula", "proof-step-formula", redaction_notes)

    plan = data.get("decomposition_plan")
    if plan is not None:
        for subgoal in plan.get("subgoals", []) or []:
            label = (
                "llm-suggested-subgoal"
                if subgoal.get("source") == "llm_suggested"
                else "private-theorem-subgoal"
            )
            _redact_text_field(subgoal, "statement", label, redaction_notes)

    # Final defense-in-depth credential scrub across every remaining string
    # leaf in the entire payload (caller metadata, diagnostic notes,
    # environment lock fields, request metadata, ...).
    data = _scrub_tree(data)

    publishable_digest = compute_content_digest(data)
    data["visibility"] = "publishable"
    data["redaction_notes"] = sorted(set(redaction_notes))
    data["publishable_digest"] = publishable_digest
    return data


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _truthy_env(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def default_receipt_store_root() -> Path:
    """Resolve the default local-disk root for :class:`ReceiptStore`.

    Honors ``IPFS_DATASETS_PY_HAMMER_RECEIPTS_DIR`` when set; otherwise
    defaults to ``~/.cache/ipfs_datasets_py/hammer_receipts``.
    """

    configured = os.environ.get("IPFS_DATASETS_PY_HAMMER_RECEIPTS_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "ipfs_datasets_py" / "hammer_receipts"


@dataclass
class StorageLocation:
    """Where one persisted receipt payload physically lives.

    Attributes:
        backend: ``"ipfs"`` if the payload was successfully pushed through
            an IPFS backend, ``"local-disk"`` otherwise (the fallback).
        digest: The content-addressed key this payload was stored under
            (the receipt's ``receipt_id``/``publishable_digest``).
        cid: The IPFS CID returned by the backend, if ``backend`` is
            ``"ipfs"``.
        path: The local-disk file path the payload was (also) written to;
            local disk is always written, even when ``backend`` is
            ``"ipfs"``, so the local cache can serve subsequent reads
            without any network/daemon dependency.
        pinned: Whether the IPFS backend reported the content as pinned.
    """

    backend: str = "local-disk"
    digest: str = ""
    cid: Optional[str] = None
    path: Optional[str] = None
    pinned: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StorageLocation":
        return cls(**dict(data))


@dataclass
class PersistResult:
    """The result of one :meth:`ReceiptStore.put` call."""

    full: StorageLocation
    publishable: Optional[StorageLocation] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "full": self.full.to_dict(),
            "publishable": self.publishable.to_dict() if self.publishable else None,
        }


class ReceiptStore:
    """IPFS-aware, content-addressed persistence for :class:`HammerReceipt`
    with a local-disk fallback.

    Every :meth:`put` call always writes the receipt's canonical JSON
    payload to a local, content-addressed disk cache under ``root_dir``
    (created on first use). Pushing the same bytes through an IPFS backend
    is opt-in (``use_ipfs=True`` or an explicitly injected ``ipfs_backend``)
    and best-effort: any failure — no ``ipfs`` binary, no daemon running,
    no network, an unexpected backend error — is caught and logged, and the
    local-disk copy is used instead. This means the store is always fully
    functional with zero external dependencies, and callers that *do* want
    IPFS-backed durability/sharing only need to opt in explicitly.

    A lightweight local index (``<root_dir>/index.json``) additionally
    records the CID (if any) each digest was last pushed to, so a read can
    still recover content from IPFS even if its local cache file was
    separately deleted, as long as the index survives.
    """

    def __init__(
        self,
        *,
        root_dir: Optional[Union[str, Path]] = None,
        ipfs_backend: Optional[Any] = None,
        use_ipfs: Optional[bool] = None,
        pin: bool = True,
    ) -> None:
        self.root_dir = Path(root_dir) if root_dir is not None else default_receipt_store_root()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._full_dir = self.root_dir / "full"
        self._publishable_dir = self.root_dir / "publishable"
        self._full_dir.mkdir(parents=True, exist_ok=True)
        self._publishable_dir.mkdir(parents=True, exist_ok=True)

        self._explicit_backend = ipfs_backend
        if use_ipfs is None:
            use_ipfs = _truthy_env("IPFS_DATASETS_PY_HAMMER_RECEIPTS_USE_IPFS")
        self._use_ipfs = bool(use_ipfs) or ipfs_backend is not None
        self._pin = pin
        self._index_path = self.root_dir / "index.json"

    # -- backend resolution ---------------------------------------------

    def _resolve_ipfs_backend(self) -> Optional[Any]:
        if self._explicit_backend is not None:
            return self._explicit_backend
        if not self._use_ipfs:
            return None
        try:
            from ipfs_datasets_py.ipfs_backend_router import get_ipfs_backend

            return get_ipfs_backend()
        except Exception as exc:  # pragma: no cover - defensive, optional dep
            logger.debug("No IPFS backend available for hammer receipts: %s", exc)
            return None

    # -- local index ------------------------------------------------------

    def _load_index(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        if not self._index_path.exists():
            return {"full": {}, "publishable": {}}
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except Exception:
            return {"full": {}, "publishable": {}}
        data.setdefault("full", {})
        data.setdefault("publishable", {})
        return data

    def _save_index(self, index: Dict[str, Dict[str, Dict[str, Any]]]) -> None:
        try:
            self._index_path.write_text(
                json.dumps(index, sort_keys=True, indent=2), encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover - best-effort bookkeeping
            logger.warning("Failed to persist hammer receipt index: %s", exc)

    def _record_index(
        self, digest: str, *, publishable: bool, location: StorageLocation
    ) -> None:
        index = self._load_index()
        bucket = "publishable" if publishable else "full"
        index[bucket][digest] = location.to_dict()
        self._save_index(index)

    def _indexed_location(
        self, digest: str, *, publishable: bool
    ) -> Optional[StorageLocation]:
        index = self._load_index()
        bucket = "publishable" if publishable else "full"
        raw = index.get(bucket, {}).get(digest)
        if raw is None:
            return None
        return StorageLocation.from_dict(raw)

    # -- path helpers -----------------------------------------------------

    @staticmethod
    def _safe_filename(digest: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.:-]", "_", digest) + ".json"

    def _dir_for(self, publishable: bool) -> Path:
        return self._publishable_dir if publishable else self._full_dir

    def _local_path(self, digest: str, *, publishable: bool) -> Path:
        return self._dir_for(publishable) / self._safe_filename(digest)

    # -- write ------------------------------------------------------------

    def _write_payload(
        self, payload: Dict[str, Any], *, digest: str, publishable: bool
    ) -> StorageLocation:
        data_bytes = json.dumps(
            payload, sort_keys=True, indent=2, ensure_ascii=True, default=str
        ).encode("utf-8")

        backend_name = "local-disk"
        cid: Optional[str] = None
        backend = self._resolve_ipfs_backend()
        if backend is not None:
            try:
                cid = backend.add_bytes(data_bytes, pin=self._pin)
                backend_name = "ipfs"
            except Exception as exc:
                logger.warning(
                    "IPFS store failed for hammer receipt digest=%s; falling back "
                    "to local disk: %s",
                    digest,
                    exc,
                )
                cid = None

        path = self._local_path(digest, publishable=publishable)
        try:
            path.write_bytes(data_bytes)
        except OSError as exc:
            if cid is None:
                raise ReceiptStorageError(
                    f"Failed to persist hammer receipt digest={digest!r} to both "
                    f"IPFS and local disk: {exc}"
                ) from exc
            logger.warning(
                "Local-disk write failed for hammer receipt digest=%s (IPFS copy "
                "still available at cid=%s): %s",
                digest,
                cid,
                exc,
            )
            path = None  # type: ignore[assignment]

        location = StorageLocation(
            backend=backend_name,
            digest=digest,
            cid=cid,
            path=str(path) if path is not None else None,
            pinned=cid is not None and self._pin,
        )
        self._record_index(digest, publishable=publishable, location=location)
        return location

    def put(self, receipt: HammerReceipt, *, publish: bool = False) -> PersistResult:
        """Persist ``receipt``.

        Always writes the full, unredacted receipt keyed by its
        ``receipt_id``. When ``publish`` is ``True``, additionally builds
        and persists :meth:`HammerReceipt.to_publishable_dict` under the
        same id in a separate ``publishable/`` namespace.
        """

        full_location = self._write_payload(
            receipt.to_dict(), digest=receipt.receipt_id, publishable=False
        )
        publishable_location = None
        if publish:
            publishable_payload = receipt.to_publishable_dict()
            publishable_location = self._write_payload(
                publishable_payload, digest=receipt.receipt_id, publishable=True
            )
        return PersistResult(full=full_location, publishable=publishable_location)

    # -- read ---------------------------------------------------------------

    def _read_payload(
        self, digest: str, *, publishable: bool
    ) -> Optional[Dict[str, Any]]:
        path = self._local_path(digest, publishable=publishable)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - corrupted cache file
                logger.warning(
                    "Corrupted local hammer receipt cache file at %s: %s", path, exc
                )

        location = self._indexed_location(digest, publishable=publishable)
        if location is None or location.cid is None:
            return None
        backend = self._resolve_ipfs_backend()
        if backend is None:
            return None
        try:
            raw = backend.cat(location.cid)
        except Exception as exc:
            logger.warning(
                "Failed to retrieve hammer receipt digest=%s from IPFS cid=%s: %s",
                digest,
                location.cid,
                exc,
            )
            return None
        data = json.loads(raw.decode("utf-8"))
        # Repopulate the local cache so future reads avoid the network.
        try:
            path.write_bytes(
                json.dumps(data, sort_keys=True, indent=2, ensure_ascii=True).encode(
                    "utf-8"
                )
            )
        except OSError:  # pragma: no cover - best-effort cache repopulation
            pass
        return data

    def get(self, receipt_id: str) -> HammerReceipt:
        """Retrieve and reconstruct the full, unredacted
        :class:`HammerReceipt` stored under ``receipt_id``.

        Raises:
            ReceiptNotFoundError: If ``receipt_id`` is not present in the
                local-disk cache and could not be resolved via IPFS either.
        """

        data = self._read_payload(receipt_id, publishable=False)
        if data is None:
            raise ReceiptNotFoundError(
                f"No stored hammer receipt found for id {receipt_id!r}"
            )
        return HammerReceipt.from_dict(data)

    def get_publishable(self, receipt_id: str) -> Dict[str, Any]:
        """Retrieve the redacted, publishable payload stored under
        ``receipt_id`` (a plain dict — a publishable payload is a lossy,
        redacted view and is never reconstructed back into a strict
        :class:`HammerReceipt`; only the full receipt is replayable).

        Raises:
            ReceiptNotFoundError: If no publishable payload was ever
                persisted for ``receipt_id``.
        """

        data = self._read_payload(receipt_id, publishable=True)
        if data is None:
            raise ReceiptNotFoundError(
                f"No publishable hammer receipt found for id {receipt_id!r}"
            )
        return data

    def exists(self, receipt_id: str, *, publishable: bool = False) -> bool:
        """Return whether a receipt (or its publishable view) is known to
        this store, either on local disk or in the CID index."""

        if self._local_path(receipt_id, publishable=publishable).exists():
            return True
        return self._indexed_location(receipt_id, publishable=publishable) is not None

    def list_ids(self, *, publishable: bool = False) -> List[str]:
        """List every receipt id with a payload cached on local disk."""

        directory = self._dir_for(publishable)
        return sorted(path.stem for path in directory.glob("*.json"))


def persist_hammer_receipt(
    receipt: HammerReceipt,
    *,
    store: Optional[ReceiptStore] = None,
    publish: bool = False,
) -> PersistResult:
    """Convenience wrapper: persist ``receipt`` into ``store`` (or a
    freshly constructed default :class:`ReceiptStore` if ``store`` is
    ``None``) and return the resulting :class:`PersistResult`."""

    store = store or ReceiptStore()
    return store.put(receipt, publish=publish)
