"""MCP tool: generate a ZKP certificate for a completed PDF form.

Wraps :func:`~ipfs_datasets_py.logic.zkp.form_circuit.generate_form_certificate`
as an MCP-compatible async function.

The tool:
1. Converts the form's ``DeonticRuleSet`` to deontic IR (if not already done).
2. Verifies the completed values against the rule set.
3. Generates a ZKP certificate proving the form is correctly filled, without
   revealing the private field values.

The certificate can later be checked with ``pdf_verify_zkp_certificate``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


async def pdf_generate_zkp_certificate(
    pdf_source: Union[str, dict],
    field_values: Dict[str, Any],
    jurisdiction: Optional[str] = None,
    prover: str = "z3",
    ipfs_cid: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a zero-knowledge proof certificate for a completed PDF form.

    The certificate proves that the form's requirements are satisfied without
    revealing the private field values (SSN, income, etc.).

    ⚠️  The proof uses a **simulated** ZKP backend by default (not
    cryptographically secure).  Set ``IPFS_DATASETS_ENABLE_GROTH16=1`` for a
    Groth16 proof.

    Args:
        pdf_source: Path to the blank form PDF or a dict with a ``"path"`` key.
        field_values: ``{field_name: value}`` dict of the completed form.
            These values serve as the **private witness** and are **not**
            included in the certificate.
        jurisdiction: Optional jurisdiction string for deontic IR.
        prover: Theorem prover used for requirement verification
            (``"z3"``, ``"cvc5"``, ``"lean"``, ``"coq"``).
        ipfs_cid: Optional IPFS CID of the stored filled PDF.
        metadata: Extra metadata attached to the proof.

    Returns:
        Dict containing:

        * ``status``: ``"success"`` or ``"error"``
        * ``certificate``: serialised :class:`FormCompletionCertificate` (no
          private values)
        * ``overall_pass``: whether the form passed verification
        * ``is_simulated``: whether a simulated (non-cryptographic) proof was used
        * ``message``: human-readable summary
    """
    try:
        if isinstance(pdf_source, dict):
            pdf_path = str(pdf_source.get("path", pdf_source.get("pdf_source", "")))
        else:
            pdf_path = str(pdf_source)

        if not pdf_path:
            return {"status": "error", "message": "pdf_source must be a file path or dict with 'path' key"}
        if not field_values:
            return {"status": "error", "message": "field_values must be a non-empty dict"}

        # 1. Parse form and build legal IR
        from ipfs_datasets_py.processors.pdf_form_ir import pdf_to_legal_ir

        kg, rule_set = pdf_to_legal_ir(pdf_path, jurisdiction=jurisdiction)

        # 2. Verify requirements
        from ipfs_datasets_py.processors.form_requirements_verifier import FormRequirementsVerifier

        verifier = FormRequirementsVerifier(prover=prover)
        report = verifier.verify(
            field_values,
            rule_set,
            form_id=kg.form_id,
            source_pdf=pdf_path,
        )

        if not report.overall_pass:
            violations = [
                {"formula_id": r.formula_id, "field": r.field_name, "errors": r.errors}
                for r in report.results
                if r.status == "violated"
            ]
            return {
                "status": "error",
                "overall_pass": False,
                "violations": violations,
                "message": (
                    f"Form verification failed with {len(violations)} violation(s). "
                    "Fix the issues before generating a certificate."
                ),
            }

        # 3. Generate ZKP certificate
        from ipfs_datasets_py.logic.zkp.form_circuit import generate_form_certificate

        certificate = generate_form_certificate(
            field_values,
            rule_set,
            report,
            form_id=kg.form_id,
            source_pdf=pdf_path,
            ipfs_cid=ipfs_cid,
            metadata=metadata,
        )

        return {
            "status": "success",
            "overall_pass": True,
            "is_simulated": certificate.is_simulated,
            "certificate": certificate.to_dict(),
            "public_inputs": certificate.public_inputs,
            "message": (
                f"ZKP certificate generated for form {kg.form_id}. "
                + ("⚠️  SIMULATED proof — not cryptographically secure." if certificate.is_simulated else "✅ Groth16 proof.")
            ),
        }

    except Exception as exc:
        logger.exception("pdf_generate_zkp_certificate failed: %s", exc)
        return {"status": "error", "message": f"pdf_generate_zkp_certificate error: {exc}"}


__all__ = ["pdf_generate_zkp_certificate"]
