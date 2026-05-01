"""Zero-knowledge proof circuit and certificate for PDF form completion.

This module provides:

* :class:`FormCompletionCircuit` — encodes a ``DeonticRuleSet`` as a
  :class:`~ipfs_datasets_py.logic.zkp.circuits.ZKPCircuit` whose *statement*
  is:

      "I know a set of field values that:
       (a) hash to ``witness_hash``,
       (b) pass every required type-check constraint, and
       (c) satisfy the deontic rule set."

  Public inputs: ``form_template_hash``, ``rule_set_hash``, ``verdicts_hash``.
  Private inputs (witness): actual field values.

* :class:`FormCompletionCertificate` — wraps a
  :class:`~ipfs_datasets_py.logic.zkp.ZKPProof` together with the public
  :class:`~ipfs_datasets_py.processors.form_requirements_verifier.VerificationReport`
  summary, an IPFS CID for the filled PDF, and a timestamp.

* :func:`generate_form_certificate` — convenience one-shot function that:
  1. Builds a :class:`FormCompletionCircuit`.
  2. Calls :class:`~ipfs_datasets_py.logic.zkp.ZKPProver` to produce the proof.
  3. Returns a :class:`FormCompletionCertificate`.

* :func:`verify_form_certificate` — verifies the proof inside a
  :class:`FormCompletionCertificate` using
  :class:`~ipfs_datasets_py.logic.zkp.ZKPVerifier`.

⚠️  The ZKP proof produced here is **simulated** by default (not
cryptographically secure).  Enable the Groth16 backend by setting
``IPFS_DATASETS_ENABLE_GROTH16=1`` in the environment before importing this
module (see ``logic/zkp/backends/__init__.py``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FormCompletionCircuit
# ---------------------------------------------------------------------------


class FormCompletionCircuit:
    """Boolean circuit encoding the statement "this form is correctly filled".

    The circuit has three public inputs (committed as hashes) and a private
    witness (the raw field values).

    Public inputs
    -------------
    * ``form_template_hash`` — SHA-256 of the form's source PDF path / ID.
    * ``rule_set_hash`` — SHA-256 of the serialised ``DeonticRuleSet``.
    * ``verdicts_hash`` — SHA-256 of the per-formula pass/fail verdicts from
      the :class:`~ipfs_datasets_py.processors.form_requirements_verifier.VerificationReport`.

    Private witness
    ---------------
    * Serialised field values (never included in the proof or certificate).

    Circuit statement
    -----------------
    ``hash(field_values) = witness_hash  ∧  overall_pass = True``
    """

    def __init__(
        self,
        *,
        form_id: str = "",
        form_template_hash: str = "",
        rule_set_hash: str = "",
        verdicts_hash: str = "",
    ) -> None:
        self.form_id = form_id
        self.form_template_hash = form_template_hash
        self.rule_set_hash = rule_set_hash
        self.verdicts_hash = verdicts_hash
        self._circuit: Any = None

    # ------------------------------------------------------------------

    @classmethod
    def from_rule_set_and_report(
        cls,
        rule_set: Any,
        report: Any,  # VerificationReport
        *,
        form_id: str = "",
        source_pdf: str = "",
    ) -> "FormCompletionCircuit":
        """Build the circuit from a ``DeonticRuleSet`` and a
        :class:`~ipfs_datasets_py.processors.form_requirements_verifier.VerificationReport`.
        """
        # Compute public input hashes
        template_hash = hashlib.sha256(
            (source_pdf or form_id or "").encode()
        ).hexdigest()

        try:
            rule_set_json = json.dumps(rule_set.to_dict(), sort_keys=True)
        except Exception:
            rule_set_json = str(rule_set)
        rs_hash = hashlib.sha256(rule_set_json.encode()).hexdigest()

        verdicts_hash = report.verdicts_hash() if hasattr(report, "verdicts_hash") else ""

        return cls(
            form_id=form_id or getattr(report, "form_id", ""),
            form_template_hash=template_hash,
            rule_set_hash=rs_hash,
            verdicts_hash=verdicts_hash,
        )

    # ------------------------------------------------------------------

    def build(self) -> Any:
        """Construct and return the underlying :class:`ZKPCircuit`."""
        from ipfs_datasets_py.logic.zkp.circuits import ZKPCircuit

        circuit = ZKPCircuit()

        # Input wires for public hashes
        form_wire = circuit.add_input("form_template_hash_match")
        rs_wire = circuit.add_input("rule_set_hash_match")
        verdicts_wire = circuit.add_input("verdicts_hash_match")
        overall_pass_wire = circuit.add_input("overall_pass")

        # Combine: all three hashes match AND overall_pass = True
        all_hashes = circuit.add_and_gate(form_wire, rs_wire)
        all_hashes_and_verdicts = circuit.add_and_gate(all_hashes, verdicts_wire)
        output_wire = circuit.add_and_gate(all_hashes_and_verdicts, overall_pass_wire)
        circuit.set_output(output_wire)

        self._circuit = circuit
        return circuit

    def get_circuit(self) -> Any:
        """Return the cached circuit, building it if necessary."""
        if self._circuit is None:
            self.build()
        return self._circuit

    def public_inputs_dict(self) -> Dict[str, str]:
        return {
            "form_template_hash": self.form_template_hash,
            "rule_set_hash": self.rule_set_hash,
            "verdicts_hash": self.verdicts_hash,
        }

    def witness_from_values(self, values: Dict[str, Any]) -> str:
        """Compute a deterministic witness string from *values*.

        The witness is the SHA-256 hash of the JSON-encoded values; the raw
        values remain private.
        """
        canonical = json.dumps({k: str(v) for k, v in sorted(values.items())}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def statement(self, *, witness_hash: str = "") -> str:
        """Return a human-readable statement for the proof theorem."""
        return (
            f"form_template={self.form_template_hash[:12]}… "
            f"AND rule_set={self.rule_set_hash[:12]}… "
            f"AND verdicts={self.verdicts_hash[:12]}… "
            f"AND overall_pass=True "
            f"AND witness={witness_hash[:12] if witness_hash else '?'}…"
        )


# ---------------------------------------------------------------------------
# FormCompletionCertificate
# ---------------------------------------------------------------------------


@dataclass
class FormCompletionCertificate:
    """A ZKP-backed certificate that a form was correctly completed.

    Attributes
    ----------
    proof:
        The zero-knowledge proof (simulated by default).
    form_id:
        Identifier for the form template.
    source_pdf:
        Path / identifier of the blank form template.
    ipfs_cid:
        IPFS content identifier for the filled PDF, if it was stored.
    verification_summary:
        Public summary from the :class:`VerificationReport` (pass/fail per
        field, no private values).
    public_inputs:
        Public hashes committed by the proof.
    timestamp:
        Unix timestamp of certificate generation.
    is_simulated:
        ``True`` if a simulated (non-cryptographic) backend was used.
    """

    proof: Any  # ZKPProof
    form_id: str
    source_pdf: str
    ipfs_cid: str = ""
    verification_summary: Dict[str, Any] = field(default_factory=dict)
    public_inputs: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    is_simulated: bool = True

    def to_dict(self) -> Dict[str, Any]:
        proof_dict = self.proof.to_dict() if self.proof else {}
        return {
            "form_id": self.form_id,
            "source_pdf": self.source_pdf,
            "ipfs_cid": self.ipfs_cid,
            "verification_summary": self.verification_summary,
            "public_inputs": self.public_inputs,
            "timestamp": self.timestamp,
            "is_simulated": self.is_simulated,
            "proof": proof_dict,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# generate_form_certificate
# ---------------------------------------------------------------------------


def generate_form_certificate(
    values: Dict[str, Any],
    rule_set: Any,
    report: Any,  # VerificationReport
    *,
    form_id: str = "",
    source_pdf: str = "",
    ipfs_cid: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> "FormCompletionCertificate":
    """Generate a ZKP certificate for a completed form.

    Parameters
    ----------
    values:
        ``{field_name: filled_value}`` dict (the private witness).
    rule_set:
        ``DeonticRuleSet`` from :class:`FormToLegalIR`.
    report:
        :class:`VerificationReport` from :class:`FormRequirementsVerifier`.
    form_id, source_pdf:
        Identifiers forwarded into the certificate.
    ipfs_cid:
        Optional IPFS CID of the stored filled PDF.
    metadata:
        Extra metadata attached to the proof.

    Returns
    -------
    :class:`FormCompletionCertificate`

    Raises
    ------
    ValueError
        If ``report.overall_pass`` is ``False``; you should not certify a
        form that failed verification.
    """
    if not report.overall_pass:
        raise ValueError(
            "Cannot generate a ZKP certificate for a form that failed verification. "
            "Fix the reported violations first."
        )

    from ipfs_datasets_py.logic.zkp.zkp_prover import ZKPProver

    circuit = FormCompletionCircuit.from_rule_set_and_report(
        rule_set, report, form_id=form_id, source_pdf=source_pdf
    )
    witness_hash = circuit.witness_from_values(values)
    theorem = circuit.statement(witness_hash=witness_hash)

    # The private axioms are the hashed witness + overall_pass assertion.
    # Raw field values are NEVER passed to the prover.
    private_axioms = [
        f"witness_hash={witness_hash}",
        "overall_pass=True",
        f"form_template_hash={circuit.form_template_hash}",
        f"rule_set_hash={circuit.rule_set_hash}",
        f"verdicts_hash={circuit.verdicts_hash}",
    ]

    prover_meta = {
        **(metadata or {}),
        "form_id": form_id,
        "source_pdf": source_pdf,
        "circuit_inputs": circuit.public_inputs_dict(),
    }

    # Detect backend
    use_groth16 = os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "0").strip() in {"1", "true", "yes"}
    backend = "groth16" if use_groth16 else "simulated"

    try:
        prover = ZKPProver(backend=backend)
        proof = prover.generate_proof(
            theorem=theorem,
            private_axioms=private_axioms,
            metadata=prover_meta,
        )
        is_simulated = backend == "simulated"
    except Exception as exc:
        # Groth16 backend unavailable — fall back to simulation
        logger.warning("Groth16 backend failed (%s); falling back to simulated ZKP", exc)
        prover = ZKPProver(backend="simulated")
        proof = prover.generate_proof(
            theorem=theorem,
            private_axioms=private_axioms,
            metadata=prover_meta,
        )
        is_simulated = True

    # Build a privacy-safe verification summary (no field values)
    verification_summary = {
        "overall_pass": report.overall_pass,
        "form_id": report.form_id,
        "timestamp": report.timestamp,
        "verdicts": {r.formula_id: r.status for r in report.results},
        "conflict_count": len(report.conflicts),
        "metadata": report.metadata,
    }

    return FormCompletionCertificate(
        proof=proof,
        form_id=form_id or report.form_id,
        source_pdf=source_pdf or report.source_pdf,
        ipfs_cid=ipfs_cid,
        verification_summary=verification_summary,
        public_inputs=circuit.public_inputs_dict(),
        timestamp=time.time(),
        is_simulated=is_simulated,
    )


# ---------------------------------------------------------------------------
# verify_form_certificate
# ---------------------------------------------------------------------------


def verify_form_certificate(
    certificate: "FormCompletionCertificate",
    *,
    rule_set: Optional[Any] = None,
    report: Optional[Any] = None,
) -> bool:
    """Verify the ZKP proof inside *certificate*.

    Optionally re-checks the public-input hashes against *rule_set* and/or
    *report* to confirm the certificate is consistent with the expected form.

    Parameters
    ----------
    certificate:
        The :class:`FormCompletionCertificate` to verify.
    rule_set:
        If provided, recomputes the rule-set hash and checks it matches the
        certificate's ``rule_set_hash`` public input.
    report:
        If provided, recomputes the verdicts hash and checks it matches the
        certificate's ``verdicts_hash`` public input.

    Returns
    -------
    bool
        ``True`` if the proof is valid and all hash checks pass.
    """
    if certificate.proof is None:
        logger.warning("Certificate has no proof")
        return False

    # 1. ZKP proof verification
    from ipfs_datasets_py.logic.zkp.zkp_verifier import ZKPVerifier

    verifier = ZKPVerifier()
    try:
        proof_valid = verifier.verify_proof(certificate.proof)
    except Exception as exc:
        logger.warning("Proof verification raised an exception: %s", exc)
        return False

    if not proof_valid:
        return False

    # 2. Optional public-input consistency checks
    pub = certificate.public_inputs

    if rule_set is not None:
        try:
            rule_set_json = json.dumps(rule_set.to_dict(), sort_keys=True)
        except Exception:
            rule_set_json = str(rule_set)
        expected_rs_hash = hashlib.sha256(rule_set_json.encode()).hexdigest()
        if pub.get("rule_set_hash") != expected_rs_hash:
            logger.warning("rule_set_hash mismatch: certificate does not match provided rule_set")
            return False

    if report is not None:
        expected_verdicts_hash = report.verdicts_hash() if hasattr(report, "verdicts_hash") else ""
        if expected_verdicts_hash and pub.get("verdicts_hash") != expected_verdicts_hash:
            logger.warning("verdicts_hash mismatch: certificate does not match provided report")
            return False

    return True


__all__ = [
    "FormCompletionCertificate",
    "FormCompletionCircuit",
    "generate_form_certificate",
    "verify_form_certificate",
]
