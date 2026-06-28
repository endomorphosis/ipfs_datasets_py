"""TDFOL trace witness schema and Python pre-validation for ProveKit.

Before passing a derivation trace to ProveKit, this module:

1. Defines a bounded ``TDFOLTraceWitness`` schema compatible with the
   ``provekit_tdfol_v1_trace@v1`` Noir circuit family.
2. Derives and validates the trace using the existing TDFOL_v1 forward-chaining
   semantics in :mod:`~ipfs_datasets_py.logic.zkp.legal_theorem_semantics`.
3. Rejects non-derivable traces *before* any proving attempt (fail-closed).

The trace is bounded at ``MAX_TRACE_STEPS`` steps so the Noir circuit remains a
fixed-size constraint system.  Private axiom text must never appear in the
public schema fields, Noir inputs, log messages, or returned metadata.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from ..canonicalization import (
    P_BN254,
    axioms_commitment_hex,
    canonicalize_axioms,
    theorem_hash_hex,
)
from ..statement import format_circuit_ref

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum steps in a bounded derivation trace (circuit constraint).
MAX_TRACE_STEPS: int = 32

#: Circuit identifier for the TDFOL v1 trace circuit family.
TDFOL_TRACE_CIRCUIT_ID: str = "provekit_tdfol_v1_trace"

#: Pinned version for the first TDFOL trace circuit.
TDFOL_TRACE_CIRCUIT_VERSION: int = 1

#: Canonical circuit reference string, e.g. ``provekit_tdfol_v1_trace@v1``.
TDFOL_TRACE_CIRCUIT_REF: str = format_circuit_ref(
    TDFOL_TRACE_CIRCUIT_ID, TDFOL_TRACE_CIRCUIT_VERSION
)

#: Ruleset identifier reused from the existing TDFOL_v1 semantics.
TDFOL_TRACE_RULESET_ID: str = "TDFOL_v1"

#: Integer code for a fact step (atom known directly from axiom set).
STEP_KIND_FACT: int = 0

#: Integer code for a modus-ponens derivation step.
STEP_KIND_MODUS_PONENS: int = 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TDFOLTraceNotDerivableError(ValueError):
    """Raised when a theorem is not derivable from the supplied axioms.

    This is a fail-closed pre-validation error: ProveKit must not be called
    if the Python-side semantics cannot derive the theorem.
    """


class TDFOLTraceBoundExceededError(ValueError):
    """Raised when the derivation trace exceeds ``MAX_TRACE_STEPS``.

    The Noir circuit is bounded.  Traces longer than ``MAX_TRACE_STEPS`` cannot
    be encoded in the fixed-size circuit without modification.
    """


class TDFOLTraceSchemaError(ValueError):
    """Raised when a pre-built ``TDFOLTraceWitness`` fails internal consistency checks."""


# ---------------------------------------------------------------------------
# Schema datatypes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TDFOLTraceStep:
    """One step in a TDFOL_v1 forward-chaining derivation trace.

    Attributes:
        kind: ``"fact"`` for a direct axiom, ``"modus_ponens"`` for a derived atom.
        atom: The atom that becomes known at this step.
        antecedent: For ``"modus_ponens"`` steps, the triggering antecedent atom;
            ``None`` for ``"fact"`` steps.
        step_index: Zero-based position of this step in the full trace.
    """

    kind: str
    atom: str
    antecedent: Optional[str]
    step_index: int

    def __post_init__(self) -> None:
        if self.kind not in ("fact", "modus_ponens"):
            raise TDFOLTraceSchemaError(
                f"TDFOLTraceStep.kind must be 'fact' or 'modus_ponens', got {self.kind!r}"
            )
        if not isinstance(self.atom, str) or not self.atom:
            raise TDFOLTraceSchemaError("TDFOLTraceStep.atom must be a non-empty string")
        if self.kind == "fact" and self.antecedent is not None:
            raise TDFOLTraceSchemaError("fact step must have antecedent=None")
        if self.kind == "modus_ponens" and not self.antecedent:
            raise TDFOLTraceSchemaError("modus_ponens step must have a non-empty antecedent")
        if not isinstance(self.step_index, int) or self.step_index < 0:
            raise TDFOLTraceSchemaError("step_index must be a non-negative int")

    def kind_code(self) -> int:
        """Return the integer code for this step's kind (for Noir encoding)."""
        return STEP_KIND_FACT if self.kind == "fact" else STEP_KIND_MODUS_PONENS

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (no private axiom text)."""
        return {
            "kind": self.kind,
            "atom_hash": _sha256_field_hex(self.atom),
            "antecedent_hash": _sha256_field_hex(self.antecedent) if self.antecedent else None,
            "step_index": self.step_index,
        }


@dataclass(frozen=True)
class TDFOLTraceWitness:
    """Bounded TDFOL_v1 derivation trace witness for the ``provekit_tdfol_v1_trace@v1`` circuit.

    This is the Python-side schema for the private trace witness.  It is
    constructed and validated by :func:`build_tdfol_v1_trace_witness` before any
    ProveKit call.

    Public fields (safe to include in proof metadata):
        - ``theorem_hash``
        - ``axioms_commitment``
        - ``circuit_ref``
        - ``circuit_version``
        - ``ruleset_id``
        - ``trace_length``

    Private fields (must not be logged or serialized into public output):
        - ``theorem`` (raw text; use ``theorem_hash`` in public contexts)
        - ``trace_steps`` (exposes atom names, which may be policy-sensitive)

    Attributes:
        theorem: Canonical theorem atom string (private; hash is public).
        theorem_hash: SHA-256 hex of the canonicalized theorem.
        axioms_commitment: SHA-256 hex commitment over the canonical axiom set.
        trace_steps: Ordered derivation steps (length == trace_length).
        trace_length: Number of actual derivation steps (public).
        circuit_ref: Canonical circuit reference string.
        circuit_version: Numeric circuit version (matches ``circuit_ref``).
        ruleset_id: Ruleset identifier (``"TDFOL_v1"``).
    """

    theorem: str
    theorem_hash: str
    axioms_commitment: str
    trace_steps: tuple[TDFOLTraceStep, ...]
    trace_length: int
    circuit_ref: str
    circuit_version: int
    ruleset_id: str

    def __post_init__(self) -> None:
        if not self.theorem:
            raise TDFOLTraceSchemaError("theorem must be a non-empty string")
        _require_hex_32("theorem_hash", self.theorem_hash)
        _require_hex_32("axioms_commitment", self.axioms_commitment)
        if not isinstance(self.trace_length, int) or self.trace_length < 0:
            raise TDFOLTraceSchemaError("trace_length must be a non-negative int")
        if self.trace_length > MAX_TRACE_STEPS:
            raise TDFOLTraceBoundExceededError(
                f"trace_length {self.trace_length} exceeds MAX_TRACE_STEPS={MAX_TRACE_STEPS}"
            )
        if len(self.trace_steps) != self.trace_length:
            raise TDFOLTraceSchemaError(
                f"trace_steps length {len(self.trace_steps)} != trace_length {self.trace_length}"
            )
        if not isinstance(self.circuit_version, int) or self.circuit_version < 0:
            raise TDFOLTraceSchemaError("circuit_version must be a non-negative int")
        if not self.circuit_ref:
            raise TDFOLTraceSchemaError("circuit_ref must be a non-empty string")
        if not self.ruleset_id:
            raise TDFOLTraceSchemaError("ruleset_id must be a non-empty string")
        # Verify theorem_hash is consistent with theorem content.
        expected = theorem_hash_hex(self.theorem)
        if self.theorem_hash != expected:
            raise TDFOLTraceSchemaError(
                "theorem_hash does not match SHA-256 of the canonical theorem"
            )

    # ------------------------------------------------------------------
    # Noir field-input encoding
    # ------------------------------------------------------------------

    def to_noir_trace_field_inputs(self) -> dict[str, Any]:
        """Return deterministic BN254 scalar-field inputs for the Noir trace circuit.

        The trace is padded to ``MAX_TRACE_STEPS`` zero-valued steps.  Only the
        first ``trace_length`` steps carry actual derivation data.

        The public theorem hash and axioms commitment are also included so the
        circuit can bind the trace to the public statement.

        Returns:
            Dict with ``theorem_hash_field``, ``axioms_commitment_field``,
            ``trace_length``, and ``trace_steps`` (fixed-size padded list).
        """
        encoded: list[dict[str, int]] = []
        for step in self.trace_steps:
            encoded.append(
                {
                    "kind": step.kind_code(),
                    "atom_field": _sha256_field_int(step.atom),
                    "antecedent_field": (
                        _sha256_field_int(step.antecedent)
                        if step.antecedent
                        else 0
                    ),
                }
            )
        # Pad to MAX_TRACE_STEPS with zero-filled sentinel entries.
        while len(encoded) < MAX_TRACE_STEPS:
            encoded.append({"kind": 0, "atom_field": 0, "antecedent_field": 0})

        return {
            "theorem_hash_field": _hex_to_field(self.theorem_hash),
            "axioms_commitment_field": _hex_to_field(self.axioms_commitment),
            "trace_length": self.trace_length,
            "trace_steps": encoded,
        }

    # ------------------------------------------------------------------
    # Public metadata view (no private atom text)
    # ------------------------------------------------------------------

    def to_public_metadata(self) -> dict[str, Any]:
        """Return a public-safe dict (no private axiom or atom text).

        Suitable for inclusion in ``ZKPProof.metadata`` or proof attestation
        views.  Atom text is replaced with field hashes.
        """
        return {
            "circuit_ref": self.circuit_ref,
            "circuit_version": self.circuit_version,
            "ruleset_id": self.ruleset_id,
            "theorem_hash": self.theorem_hash,
            "axioms_commitment": self.axioms_commitment,
            "trace_length": self.trace_length,
            "trace_steps": [step.to_dict() for step in self.trace_steps],
        }


# ---------------------------------------------------------------------------
# Main construction and validation functions
# ---------------------------------------------------------------------------


def build_tdfol_v1_trace_witness(
    *,
    theorem: str,
    private_axioms: Sequence[str],
    circuit_version: int = TDFOL_TRACE_CIRCUIT_VERSION,
    ruleset_id: str = TDFOL_TRACE_RULESET_ID,
    precomputed_axioms_commitment: Optional[str] = None,
) -> TDFOLTraceWitness:
    """Derive and return a bounded TDFOL_v1 trace witness for ``theorem``.

    This is the primary entry point for constructing a trace witness before
    calling ProveKit.  It:

    1. Parses ``theorem`` and ``private_axioms`` with the existing TDFOL_v1
       semantics, raising :class:`~ipfs_datasets_py.logic.zkp.legal_theorem_semantics.LegalTheoremSyntaxError`
       on syntax errors.
    2. Runs forward-chaining derivation; raises :class:`TDFOLTraceNotDerivableError`
       if the theorem is not derivable (fail-closed).
    3. Builds and returns a :class:`TDFOLTraceWitness` with the bounded,
       canonicalized trace; raises :class:`TDFOLTraceBoundExceededError` if the
       trace exceeds ``MAX_TRACE_STEPS``.

    Private axiom text never appears in the returned schema's public fields.

    Args:
        theorem: Atom to prove (public).
        private_axioms: Axiom set (private; not stored in public fields).
        circuit_version: Circuit version; default is ``TDFOL_TRACE_CIRCUIT_VERSION``.
        ruleset_id: Ruleset identifier; default is ``"TDFOL_v1"``.
        precomputed_axioms_commitment: Optional pre-computed axioms commitment
            hex (must match the canonical commitment if supplied).

    Returns:
        A validated :class:`TDFOLTraceWitness` ready for ProveKit proving.

    Raises:
        LegalTheoremSyntaxError: Axiom or theorem text is outside the
            supported TDFOL_v1 fragment.
        TDFOLTraceNotDerivableError: Theorem is not derivable from axioms.
        TDFOLTraceBoundExceededError: Derived trace exceeds ``MAX_TRACE_STEPS``.
        TDFOLTraceSchemaError: Internal consistency check failed (should not
            occur for correctly built witnesses; indicates a bug).
    """
    from ..legal_theorem_semantics import (
        derive_tdfol_v1_trace,
        parse_tdfol_v1_axiom,
        parse_tdfol_v1_theorem,
    )

    # Parse to validate syntax (raises LegalTheoremSyntaxError on bad input).
    parsed_axioms = [parse_tdfol_v1_axiom(a) for a in private_axioms]
    canonical_theorem = parse_tdfol_v1_theorem(theorem)

    # Derive the trace using the existing forward-chaining semantics.
    atoms_in_trace = derive_tdfol_v1_trace(private_axioms, theorem)
    if atoms_in_trace is None:
        raise TDFOLTraceNotDerivableError(
            f"Theorem is not derivable from the supplied axioms under {ruleset_id}; "
            "ProveKit proving aborted (fail-closed)."
        )

    # Enforce the circuit bound before any further processing.
    if len(atoms_in_trace) > MAX_TRACE_STEPS:
        raise TDFOLTraceBoundExceededError(
            f"Derivation trace has {len(atoms_in_trace)} steps, exceeding "
            f"MAX_TRACE_STEPS={MAX_TRACE_STEPS}.  "
            "Increase the circuit bound or simplify the axiom set."
        )

    # Build richer step objects (kind + antecedent justification).
    trace_steps = tuple(
        _build_steps(parsed_axioms, atoms_in_trace)
    )

    # Compute public commitments.
    th_hash = theorem_hash_hex(theorem)
    canonical_commitment = axioms_commitment_hex(list(private_axioms))
    if precomputed_axioms_commitment is not None:
        if precomputed_axioms_commitment != canonical_commitment:
            raise TDFOLTraceSchemaError(
                "precomputed_axioms_commitment does not match the canonical commitment "
                "for the supplied private_axioms"
            )
    axioms_commitment = canonical_commitment

    circuit_ref = format_circuit_ref(TDFOL_TRACE_CIRCUIT_ID, circuit_version)

    return TDFOLTraceWitness(
        theorem=canonical_theorem,
        theorem_hash=th_hash,
        axioms_commitment=axioms_commitment,
        trace_steps=trace_steps,
        trace_length=len(trace_steps),
        circuit_ref=circuit_ref,
        circuit_version=circuit_version,
        ruleset_id=ruleset_id,
    )


def validate_tdfol_v1_trace_witness(
    witness: TDFOLTraceWitness,
    *,
    private_axioms: Optional[Sequence[str]] = None,
    rederive: bool = False,
) -> None:
    """Validate a pre-built :class:`TDFOLTraceWitness` for consistency.

    Always checks:
    - Bound: ``trace_length <= MAX_TRACE_STEPS``.
    - Schema: ``theorem_hash`` matches theorem content.
    - Step indices are contiguous and zero-based.
    - Modus-ponens steps reference a previously known atom.

    Optionally (when ``private_axioms`` is supplied):
    - Checks that ``witness.axioms_commitment`` matches the canonical commitment
      for ``private_axioms``.
    - When ``rederive=True``, re-runs the TDFOL_v1 semantics and verifies the
      trace matches the deterministic derivation.

    Args:
        witness: The witness to validate.
        private_axioms: Optional axiom set for cross-checking the commitment.
        rederive: When ``True`` (and ``private_axioms`` is supplied), re-derive
            the trace and check for agreement.

    Raises:
        TDFOLTraceSchemaError: Any consistency check fails.
        TDFOLTraceNotDerivableError: ``rederive=True`` and theorem is not
            derivable from the supplied axioms.
    """
    # The dataclass ``__post_init__`` already checks bound, types, and theorem_hash.
    # Here we run the richer sequential consistency checks.

    if not isinstance(witness, TDFOLTraceWitness):
        raise TDFOLTraceSchemaError("witness must be a TDFOLTraceWitness instance")

    # Check step indices are contiguous.
    for expected_idx, step in enumerate(witness.trace_steps):
        if step.step_index != expected_idx:
            raise TDFOLTraceSchemaError(
                f"trace_steps[{expected_idx}].step_index == {step.step_index}; "
                f"expected {expected_idx}"
            )

    # Check modus-ponens justification ordering: antecedent must appear before consequent.
    known_atoms: set[str] = set()
    for step in witness.trace_steps:
        if step.kind == "fact":
            known_atoms.add(step.atom)
        else:
            if step.antecedent not in known_atoms:
                raise TDFOLTraceSchemaError(
                    f"modus_ponens step {step.step_index}: antecedent {step.antecedent!r} "
                    "is not yet known at this point in the trace"
                )
            known_atoms.add(step.atom)

    # Check the theorem is the last known atom (must be in trace).
    if witness.theorem not in known_atoms:
        raise TDFOLTraceSchemaError(
            "theorem atom is not present in the trace; the trace does not prove the theorem"
        )

    # Optional cross-checks with private axioms.
    if private_axioms is not None:
        canonical_commitment = axioms_commitment_hex(list(private_axioms))
        if canonical_commitment != witness.axioms_commitment:
            raise TDFOLTraceSchemaError(
                "axioms_commitment in witness does not match the canonical commitment "
                "for the supplied private_axioms"
            )

        if rederive:
            from ..legal_theorem_semantics import derive_tdfol_v1_trace

            rederived = derive_tdfol_v1_trace(private_axioms, witness.theorem)
            if rederived is None:
                raise TDFOLTraceNotDerivableError(
                    "Re-derivation from private_axioms returned None; "
                    "the theorem is not derivable."
                )
            rederived_atoms = rederived
            witness_atoms = [s.atom for s in witness.trace_steps]
            if witness_atoms != rederived_atoms:
                raise TDFOLTraceSchemaError(
                    "Trace atoms do not match the deterministic re-derivation. "
                    "The trace witness may have been tampered with or built incorrectly."
                )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_steps(
    parsed_axioms: list[Any],
    atoms_in_trace: list[str],
) -> list[TDFOLTraceStep]:
    """Build enriched TDFOLTraceStep list from parsed axioms and ordered atoms.

    For each atom in the trace, determines whether it is a direct fact or a
    modus-ponens consequence, and records the triggering antecedent.  The
    antecedent is chosen deterministically as the first sorted antecedent that
    was already known at that point in the trace.

    Args:
        parsed_axioms: List of :class:`~ipfs_datasets_py.logic.zkp.legal_theorem_semantics.HornAxiom`.
        atoms_in_trace: Ordered list of atoms from ``derive_tdfol_v1_trace``.

    Returns:
        List of :class:`TDFOLTraceStep` (same length as ``atoms_in_trace``).
    """
    direct_facts: set[str] = {ax.consequent for ax in parsed_axioms if ax.antecedent is None}

    # For each consequent, record all possible antecedents sorted for determinism.
    impl_antecedents: dict[str, list[str]] = {}
    for ax in parsed_axioms:
        if ax.antecedent is not None:
            impl_antecedents.setdefault(ax.consequent, []).append(ax.antecedent)
    for key in impl_antecedents:
        impl_antecedents[key].sort()

    steps: list[TDFOLTraceStep] = []
    known_so_far: set[str] = set()

    for idx, atom in enumerate(atoms_in_trace):
        if atom in direct_facts:
            steps.append(
                TDFOLTraceStep(kind="fact", atom=atom, antecedent=None, step_index=idx)
            )
        else:
            # Pick the earliest antecedent already known in the trace.
            antecedent: Optional[str] = None
            for candidate in impl_antecedents.get(atom, []):
                if candidate in known_so_far:
                    antecedent = candidate
                    break
            steps.append(
                TDFOLTraceStep(
                    kind="modus_ponens",
                    atom=atom,
                    antecedent=antecedent,
                    step_index=idx,
                )
            )
        known_so_far.add(atom)

    return steps


def _sha256_field_int(text: str) -> int:
    """SHA-256 of UTF-8 text reduced modulo the BN254 scalar field."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % P_BN254


def _sha256_field_hex(text: str) -> str:
    """Return the BN254 field element for ``text`` as a 32-byte big-endian hex string."""
    value = _sha256_field_int(text)
    return value.to_bytes(32, "big").hex()


def _hex_to_field(hex_digest: str) -> int:
    """Map a 32-byte hex digest to the BN254 scalar field."""
    return int(hex_digest, 16) % P_BN254


def _require_hex_32(name: str, value: object) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise TDFOLTraceSchemaError(f"{name} must be a 64-char hex string")
    try:
        int(value, 16)
    except ValueError as exc:
        raise TDFOLTraceSchemaError(f"{name} is not valid hex") from exc
    if value.lower() != value:
        raise TDFOLTraceSchemaError(f"{name} must be lowercase hex")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "MAX_TRACE_STEPS",
    "STEP_KIND_FACT",
    "STEP_KIND_MODUS_PONENS",
    "TDFOL_TRACE_CIRCUIT_ID",
    "TDFOL_TRACE_CIRCUIT_REF",
    "TDFOL_TRACE_CIRCUIT_VERSION",
    "TDFOL_TRACE_RULESET_ID",
    "TDFOLTraceBoundExceededError",
    "TDFOLTraceNotDerivableError",
    "TDFOLTraceSchemaError",
    "TDFOLTraceStep",
    "TDFOLTraceWitness",
    "build_tdfol_v1_trace_witness",
    "validate_tdfol_v1_trace_witness",
]
