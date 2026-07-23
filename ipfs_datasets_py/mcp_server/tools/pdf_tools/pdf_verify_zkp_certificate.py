"""MCP tool: verify a ZKP certificate for a completed PDF form.

Wraps :func:`~ipfs_datasets_py.logic.zkp.form_circuit.verify_form_certificate`
as an MCP-compatible async function.

The verifier checks the proof inside a :class:`FormCompletionCertificate`
without needing access to the private field values.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


async def pdf_verify_zkp_certificate(
    certificate: Union[str, dict],
    pdf_source: Optional[Union[str, dict]] = None,
    jurisdiction: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify a ZKP certificate for a completed PDF form.

    Confirms that the proof inside the certificate is valid.  Optionally
    re-derives the ``DeonticRuleSet`` from *pdf_source* and checks that the
    certificate's public inputs are consistent with the current form template.

    ⚠️  For simulated certificates (``is_simulated=True``) this provides only
    logical consistency verification, not cryptographic security.

    Args:
        certificate: The serialised :class:`FormCompletionCertificate` as a
            dict (e.g. from ``pdf_generate_zkp_certificate``) or a JSON string.
        pdf_source: Optional path to the blank form PDF used to re-derive the
            rule set for consistency checking.
        jurisdiction: Optional jurisdiction string (used when re-deriving the
            rule set from *pdf_source*).

    Returns:
        Dict containing:

        * ``status``: ``"success"`` or ``"error"``
        * ``valid``: ``True`` if the certificate is valid
        * ``is_simulated``: whether a simulated proof was checked
        * ``message``: human-readable result
    """
    try:
        # Parse certificate
        if isinstance(certificate, str):
            try:
                cert_dict = json.loads(certificate)
            except json.JSONDecodeError as exc:
                return {"status": "error", "message": f"Invalid certificate JSON: {exc}"}
        elif isinstance(certificate, dict):
            cert_dict = certificate
        else:
            return {"status": "error", "message": "certificate must be a dict or JSON string"}

        # Reconstruct the ZKPProof
        proof_dict = cert_dict.get("proof")
        if not proof_dict:
            return {"status": "error", "message": "Certificate does not contain a 'proof' field"}

        from ipfs_datasets_py.logic.zkp import ZKPProof
        from ipfs_datasets_py.logic.zkp.form_circuit import (
            FormCompletionCertificate,
            verify_form_certificate,
        )

        try:
            proof = ZKPProof.from_dict(proof_dict)
        except Exception as exc:
            return {"status": "error", "message": f"Could not deserialise proof: {exc}"}

        cert_obj = FormCompletionCertificate(
            proof=proof,
            form_id=cert_dict.get("form_id", ""),
            source_pdf=cert_dict.get("source_pdf", ""),
            ipfs_cid=cert_dict.get("ipfs_cid", ""),
            verification_summary=cert_dict.get("verification_summary", {}),
            public_inputs=cert_dict.get("public_inputs", {}),
            timestamp=float(cert_dict.get("timestamp", 0)),
            is_simulated=bool(cert_dict.get("is_simulated", True)),
        )

        # Optionally re-derive rule_set for consistency checking
        rule_set = None
        if pdf_source is not None:
            try:
                if isinstance(pdf_source, dict):
                    pdf_path = str(pdf_source.get("path", pdf_source.get("pdf_source", "")))
                else:
                    pdf_path = str(pdf_source)
                from ipfs_datasets_py.processors.pdf_form_ir import pdf_to_legal_ir
                _, rule_set = pdf_to_legal_ir(pdf_path, jurisdiction=jurisdiction)
            except Exception as exc:
                logger.warning("Could not re-derive rule_set from pdf_source: %s", exc)

        valid = verify_form_certificate(cert_obj, rule_set=rule_set)

        return {
            "status": "success",
            "valid": valid,
            "is_simulated": cert_obj.is_simulated,
            "form_id": cert_obj.form_id,
            "message": (
                "Certificate is valid. "
                + ("⚠️  SIMULATED proof." if cert_obj.is_simulated else "✅ Groth16 proof.")
                if valid
                else "Certificate verification FAILED."
            ),
        }

    except Exception as exc:
        logger.exception("pdf_verify_zkp_certificate failed: %s", exc)
        return {"status": "error", "message": f"pdf_verify_zkp_certificate error: {exc}"}


__all__ = ["pdf_verify_zkp_certificate"]
