"""Deterministic, source-withheld realization of canonical legal IR.

This module is the packaged implementation of the realizer selected by the
SRT-026 replacement matrix and authorized by the SRT-027 design gate.  It
reproduces ``SourceWithheldCanonicalParaphraser@1`` without importing the
benchmark package.  The implementation is deliberately stateless: its only
semantic input is :class:`CanonicalRoundTripIR`, and it never resolves,
recovers, or infers originating source text.

The selected profile uses no model.  A successful result therefore contains
one deterministic component trace with no model receipt.  Any future learned
realizer must use a new reviewed interface/configuration and expose its model
receipt rather than silently replacing this path.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_PARITY_POLICY_CID,
    CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE,
    SELECTED_REALIZER_ADAPTER_RAW_CID,
    SELECTED_REALIZER_INTERFACE,
    SOURCE_WITHHELD_DECOMPILER_CONFIG,
    SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
    SOURCE_WITHHELD_RENDERING_SPEC_CID,
    CanonicalContractError,
    CanonicalError,
    CanonicalErrorCode,
    CanonicalRoundTripIR,
    CanonicalRule,
    CanonicalStructuredTextDecompiler,
    ComponentTrace,
    DecompilerRequest,
    DecompilerResult,
    OperationStatus,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_dag_json


CANONICAL_DECOMPILER_COMPONENT_ID: Final = "source_withheld_paraphrase"
CANONICAL_DECOMPILER_ATTRIBUTION_INTERFACE: Final = (
    "CanonicalDecompilerAttribution@1"
)
CANONICAL_DECOMPILER_ATTRIBUTION_SCHEMA: Final = (
    "ipfs-datasets.canonical-decompiler-attribution.v1"
)

_PUBLIC_ADAPTER_INPUT_FIELDS: Final = (
    "canonical_ir",
    "allowed_atom_vocabulary",
    "config",
)
_EXCLUDED_ADAPTER_INPUT_CHANNELS: Final = (
    "t0",
    "gold_ir",
    "native_records",
    "source_bearing_caches",
    "hidden_case_fields",
)
_MODAL_PHRASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "O": SOURCE_WITHHELD_DECOMPILER_CONFIG["obligation_surface"],
        "P": SOURCE_WITHHELD_DECOMPILER_CONFIG["permission_surface"],
        "F": SOURCE_WITHHELD_DECOMPILER_CONFIG["prohibition_surface"],
    }
)


def _rendering_spec_payload() -> dict[str, object]:
    """Return the exact selected adapter rendering specification."""

    return {
        "interface": SELECTED_REALIZER_INTERFACE,
        "replacement_config_cid": SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
        "accepted_input_fields": list(_PUBLIC_ADAPTER_INPUT_FIELDS),
        "excluded_input_channels": list(_EXCLUDED_ADAPTER_INPUT_CHANNELS),
        "stateless": True,
        "deterministic": True,
    }


if (
    cid_for_dag_json(dict(SOURCE_WITHHELD_DECOMPILER_CONFIG))
    != SOURCE_WITHHELD_DECOMPILER_CONFIG_CID
):
    raise RuntimeError("canonical decompiler frozen configuration CID drifted")
if cid_for_dag_json(_rendering_spec_payload()) != SOURCE_WITHHELD_RENDERING_SPEC_CID:
    raise RuntimeError("canonical decompiler rendering specification CID drifted")


_INVALID_REQUEST_CID: Final = cid_for_dag_json(
    {
        "interface": CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE,
        "request_state": "invalid_before_contract_boundary",
    }
)


def frozen_decompiler_config() -> dict[str, str]:
    """Return a detached copy of the only accepted v1 configuration."""

    return dict(SOURCE_WITHHELD_DECOMPILER_CONFIG)


def _readable_atom(atom: str) -> str:
    """Apply the frozen ``underscore_to_space_v1`` atom surface."""

    return " ".join(atom.replace("_", " ").split())


def _join_atoms(atoms: tuple[str, ...], conjunction: str) -> str:
    return f" {conjunction} ".join(_readable_atom(atom) for atom in atoms)


def decompile_rule(rule: CanonicalRule) -> str:
    """Render every v1 rule facet using the frozen polarity-safe grammar."""

    if not isinstance(rule, CanonicalRule):
        raise CanonicalContractError("rule must be CanonicalRule")

    parts = [
        _readable_atom(rule.actor),
        _MODAL_PHRASES[rule.modality],
        _readable_atom(rule.action),
    ]
    if rule.object:
        parts.append(_readable_atom(rule.object))

    sentence = " ".join(parts)
    if rule.temporal:
        sentence += " " + _join_atoms(rule.temporal, "and")
    if rule.conditions:
        sentence += (
            f" {SOURCE_WITHHELD_DECOMPILER_CONFIG['condition_connector']} "
            + _join_atoms(rule.conditions, "and")
        )
    if rule.exceptions:
        sentence += (
            f" {SOURCE_WITHHELD_DECOMPILER_CONFIG['exception_connector']} "
            + _join_atoms(rule.exceptions, "or")
        )
    if not sentence.strip():
        raise CanonicalContractError("rule cannot produce a nonblank sentence")
    return sentence[0].upper() + sentence[1:] + "."


def _failure(
    request_cid: str,
    code: CanonicalErrorCode,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> DecompilerResult:
    return DecompilerResult(
        status=OperationStatus.FAILED,
        request_cid=request_cid,
        error=CanonicalError(
            code=code,
            message=message,
            retryable=False,
            details={} if details is None else details,
        ),
    )


def _request_drift(request: DecompilerRequest) -> tuple[str, str] | None:
    """Return a safe reason for post-construction request drift, if any."""

    if request.policy_cid != CANONICAL_PARITY_POLICY_CID:
        return (
            "policy_cid",
            "decompiler request policy CID does not match the frozen policy",
        )
    if (
        dict(request.config) != dict(SOURCE_WITHHELD_DECOMPILER_CONFIG)
        or cid_for_dag_json(dict(request.config))
        != SOURCE_WITHHELD_DECOMPILER_CONFIG_CID
    ):
        return (
            "config_cid",
            "decompiler request configuration does not match the frozen profile",
        )
    if cid_for_dag_json(_rendering_spec_payload()) != (
        SOURCE_WITHHELD_RENDERING_SPEC_CID
    ):
        return (
            "rendering_spec_cid",
            "decompiler rendering specification does not match the frozen profile",
        )
    return None


def _attribution_receipt(
    request: DecompilerRequest,
    result: DecompilerResult,
) -> dict[str, object]:
    """Bind the public request, selected implementation, trace, and output."""

    if (
        result.status is not OperationStatus.SUCCESS
        or result.text is None
        or result.text_cid is None
    ):
        raise CanonicalContractError(
            "attribution requires a successful decompiler result"
        )
    body: dict[str, object] = {
        "interface": CANONICAL_DECOMPILER_ATTRIBUTION_INTERFACE,
        "schema_version": CANONICAL_DECOMPILER_ATTRIBUTION_SCHEMA,
        "realizer_identity": SELECTED_REALIZER_INTERFACE,
        "selected_adapter_raw_cid": SELECTED_REALIZER_ADAPTER_RAW_CID,
        "rendering_spec_cid": SOURCE_WITHHELD_RENDERING_SPEC_CID,
        "deterministic": True,
        "source_withheld": True,
        "input_attribution": {
            "public_request_cid": request.request_cid,
            "canonical_ir_cid": request.canonical_ir.ir_cid,
            "policy_cid": request.policy_cid,
            "frozen_config_cid": SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
        },
        "output_attribution": {
            "text_cid": result.text_cid,
            "character_count": len(result.text),
        },
        "component_trace": [
            trace.to_dict() for trace in result.component_trace
        ],
    }
    return {**body, "receipt_cid": cid_for_dag_json(body)}


class SourceWithheldCanonicalDecompiler:
    """Stateless implementation of the selected canonical decompiler."""

    __slots__ = ()

    @property
    def identity(self) -> str:
        """Return the exact selected realizer interface."""

        return SELECTED_REALIZER_INTERFACE

    @property
    def deterministic(self) -> bool:
        """The selected implementation contains no learned component."""

        return True

    @property
    def uses_model(self) -> bool:
        """Make the absence of optional model use explicit."""

        return False

    def decompile(self, request: DecompilerRequest) -> DecompilerResult:
        """Realize canonical IR without consulting originating source data."""

        if not isinstance(request, DecompilerRequest):
            return _failure(
                _INVALID_REQUEST_CID,
                CanonicalErrorCode.INVALID_REQUEST,
                "request must be DecompilerRequest",
                details={
                    "expected_interface": (
                        CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE
                    )
                },
            )

        try:
            request_cid = request.request_cid
        except Exception:
            return _failure(
                _INVALID_REQUEST_CID,
                CanonicalErrorCode.INVALID_REQUEST,
                "decompiler request is not a valid canonical request",
            )

        try:
            drift = _request_drift(request)
        except Exception:
            drift = (
                "config_cid",
                "decompiler request configuration is invalid",
            )
        if drift is not None:
            field, message = drift
            return _failure(
                request_cid,
                CanonicalErrorCode.POLICY_MISMATCH,
                message,
                details={"drifted_field": field},
            )

        if not isinstance(request.canonical_ir, CanonicalRoundTripIR):
            return _failure(
                request_cid,
                CanonicalErrorCode.INVALID_IR,
                "decompiler request canonical IR is invalid",
            )

        try:
            text = " ".join(
                decompile_rule(rule) for rule in request.canonical_ir.rules
            )
        except CanonicalContractError as exc:
            return _failure(
                request_cid,
                CanonicalErrorCode.INVALID_IR,
                str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive component fence
            return _failure(
                request_cid,
                CanonicalErrorCode.COMPONENT_FAILED,
                "canonical decompiler component failed",
                details={"exception_type": type(exc).__name__},
            )

        if not text.strip():
            return _failure(
                request_cid,
                CanonicalErrorCode.EMPTY_OUTPUT,
                "canonical decompiler produced blank text",
            )

        text_cid = cid_for_bytes(text.encode("utf-8"))
        trace = ComponentTrace(
            component_id=CANONICAL_DECOMPILER_COMPONENT_ID,
            component_interface=SELECTED_REALIZER_INTERFACE,
            input_cid=request.canonical_ir.ir_cid,
            input_codec="dag-json",
            output_cid=text_cid,
            output_codec="raw",
            config_cid=SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
            deterministic=True,
            model_receipt_cid=None,
        )
        return DecompilerResult(
            status=OperationStatus.SUCCESS,
            request_cid=request_cid,
            text=text,
            text_cid=text_cid,
            component_trace=(trace,),
        )

    def decompile_with_attribution(
        self,
        request: DecompilerRequest,
    ) -> tuple[DecompilerResult, dict[str, object] | None]:
        """Return the result and a deterministic CID-bound attribution."""

        result = self.decompile(request)
        if result.status is not OperationStatus.SUCCESS:
            return result, None
        assert isinstance(request, DecompilerRequest)
        return result, _attribution_receipt(request, result)

    decompile_with_receipt = decompile_with_attribution


assert isinstance(
    SourceWithheldCanonicalDecompiler(), CanonicalStructuredTextDecompiler
)


CanonicalDecompiler = SourceWithheldCanonicalDecompiler
SourceWithheldCanonicalParaphraser = SourceWithheldCanonicalDecompiler


__all__ = [
    "CANONICAL_DECOMPILER_ATTRIBUTION_INTERFACE",
    "CANONICAL_DECOMPILER_ATTRIBUTION_SCHEMA",
    "CANONICAL_DECOMPILER_COMPONENT_ID",
    "CanonicalDecompiler",
    "SourceWithheldCanonicalDecompiler",
    "SourceWithheldCanonicalParaphraser",
    "decompile_rule",
    "frozen_decompiler_config",
]
