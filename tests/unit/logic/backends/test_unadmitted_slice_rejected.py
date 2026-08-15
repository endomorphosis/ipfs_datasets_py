"""LPC-044: reject unadmitted DomainLogicSlice@2 at executable request construction.

Acceptance:

* Executable requests without an admitted DomainLogicSlice@2 are rejected.
* rejected / unsupported slices cannot seed LogicObligation@2 or BackendRequest@2.
* Only admitted slices bind source + expression identity into BackendRequest@2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.protocol_v2 import (
    EXECUTABLE_OPERATIONS,
    ProveCheckMode,
    ProtocolV2AdmissionError,
    ProveCheckRequestV2,
    is_executable_operation,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BACKEND_REQUEST_V2_INTERFACE,
    LOGIC_OBLIGATION_V2_INTERFACE,
    BackendRequestV2,
    LogicObligationV2,
    MissingBoundsError,
    RequestAuthorityCeiling,
    RequestBounds,
    RequestV2Error,
)
from ipfs_datasets_py.logic.families.namespaces import (
    encoding_id,
    evidence_id,
    notation_id,
    property_id,
    view_id,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DOMAIN_LOGIC_SLICE_V2_INTERFACE,
    DomainLogicSliceV2,
    DomainSliceAdmissionError,
    DomainSliceStatus,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_predicate
from ipfs_datasets_py.logic.syntax_core.contracts import SourceDocument
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _document(text: str = "P", document_id: str = "doc:lpc-044") -> SourceDocument:
    return SourceDocument.from_text(document_id, text, encoding="utf-8")


def _expression(expression_id: str = "expr:lpc-044-p") -> TypedExpression:
    return TypedExpression(
        expression_id=expression_id,
        root=mk_predicate("n:p", "P"),
        signature=propositional_signature("sig:lpc-044-p", ("P",)),
    )


def _bounds() -> RequestBounds:
    return RequestBounds.default()


def _slice(
    *,
    document: SourceDocument | None = None,
    expression: TypedExpression | None = None,
    status: DomainSliceStatus | str = DomainSliceStatus.ADMITTED,
    domain: str = "security_ir",
    slice_id: str = "slice:lpc-044",
    unsupported_extensions: tuple[str, ...] = (),
    **kwargs: Any,
) -> DomainLogicSliceV2:
    document = document or _document()
    expression = expression or _expression()
    return DomainLogicSliceV2(
        slice_id=slice_id,
        domain=domain,
        document_id=document.document_id,
        source_digest=document.content_digest,
        expression_id=expression.expression_id,
        expression_digest=expression.content_digest,
        family=expression.family,
        profile=expression.profile,
        property=property_id("validity"),
        view=view_id("source"),
        notation=notation_id("canonical_text"),
        status=status,
        features=("propositional",),
        unsupported_extensions=unsupported_extensions,
        **kwargs,
    )


def _from_slice_kwargs(*, request_id: str = "req:lpc-044", obligation_id: str = "obl:lpc-044") -> dict[str, Any]:
    return {
        "request_id": request_id,
        "obligation_id": obligation_id,
        "statement": "prove P",
        "encoding": encoding_id("smtlib2"),
        "evidence_kind": evidence_id("model"),
        "bounds": _bounds(),
        "authority_ceiling": RequestAuthorityCeiling.SATISFIABILITY,
    }


def _note_path() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "slice_admission.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / note_relative


# ---------------------------------------------------------------------------
# Interface / note anchors
# ---------------------------------------------------------------------------


def test_domain_logic_slice_interface_is_v2() -> None:
    assert DOMAIN_LOGIC_SLICE_V2_INTERFACE == "DomainLogicSlice@2"
    assert LOGIC_OBLIGATION_V2_INTERFACE == "LogicObligation@2"
    assert BACKEND_REQUEST_V2_INTERFACE == "BackendRequest@2"


def test_slice_admission_note_documents_fail_closed_gate() -> None:
    note = _note_path()
    assert note.is_file(), f"missing LPC-044 note at {note}"
    text = note.read_text(encoding="utf-8")
    assert "LPC-044" in text
    assert "DomainLogicSlice@2" in text
    assert "require_admitted" in text
    assert "BackendRequest@2" in text
    assert "rejected" in text.lower()
    assert "unsupported" in text.lower()
    assert "test_unadmitted_slice_rejected.py" in text


# ---------------------------------------------------------------------------
# require_admitted gate
# ---------------------------------------------------------------------------


def test_require_admitted_accepts_only_admitted_status() -> None:
    admitted = _slice(status=DomainSliceStatus.ADMITTED)
    assert admitted.is_admitted is True
    assert admitted.require_admitted() is admitted

    rejected = _slice(
        status=DomainSliceStatus.REJECTED,
        slice_id="slice:lpc-044-rejected",
    )
    assert rejected.is_admitted is False
    with pytest.raises(DomainSliceAdmissionError, match="not admitted"):
        rejected.require_admitted()

    unsupported = _slice(
        status=DomainSliceStatus.UNSUPPORTED,
        slice_id="slice:lpc-044-unsupported",
        unsupported_extensions=("hyper.trace/v1",),
    )
    assert unsupported.is_admitted is False
    with pytest.raises(DomainSliceAdmissionError, match="not admitted"):
        unsupported.require_admitted()


def test_admitted_slice_cannot_carry_unsupported_extensions() -> None:
    with pytest.raises(DomainSliceAdmissionError, match="unsupported"):
        _slice(
            status=DomainSliceStatus.ADMITTED,
            unsupported_extensions=("modal.kripke/v1",),
        )


# ---------------------------------------------------------------------------
# LogicObligation@2.from_slice
# ---------------------------------------------------------------------------


def test_obligation_from_slice_rejects_rejected_status() -> None:
    rejected = _slice(
        status=DomainSliceStatus.REJECTED,
        slice_id="slice:lpc-044-obl-rej",
    )
    with pytest.raises(DomainSliceAdmissionError, match="not admitted"):
        LogicObligationV2.from_slice(
            rejected,
            obligation_id="obl:lpc-044-rej",
            statement="prove P",
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
        )


def test_obligation_from_slice_rejects_unsupported_status() -> None:
    unsupported = _slice(
        status=DomainSliceStatus.UNSUPPORTED,
        slice_id="slice:lpc-044-obl-unsup",
        unsupported_extensions=("resource.linear/v1",),
    )
    with pytest.raises(DomainSliceAdmissionError, match="not admitted"):
        LogicObligationV2.from_slice(
            unsupported,
            obligation_id="obl:lpc-044-unsup",
            statement="prove P",
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
        )


def test_obligation_from_slice_rejects_non_domain_logic_slice() -> None:
    with pytest.raises(RequestV2Error, match="DomainLogicSliceV2"):
        LogicObligationV2.from_slice(
            {"slice_id": "slice:fake", "status": "admitted"},  # type: ignore[arg-type]
            obligation_id="obl:lpc-044-fake",
            statement="prove P",
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
        )


def test_obligation_from_slice_requires_bounds_even_when_admitted() -> None:
    admitted = _slice()
    with pytest.raises(MissingBoundsError, match="bounds"):
        LogicObligationV2.from_slice(
            admitted,
            obligation_id="obl:lpc-044-nobounds",
            statement="prove P",
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=None,
        )


def test_obligation_from_admitted_slice_binds_lineage() -> None:
    document = _document("P ∧ Q")
    expression = _expression("expr:lpc-044-bound")
    admitted = _slice(
        document=document,
        expression=expression,
        slice_id="slice:lpc-044-bound",
        domain="legal_ir",
    )
    obligation = LogicObligationV2.from_slice(
        admitted,
        obligation_id="obl:lpc-044-bound",
        statement="prove P and Q",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    assert obligation.interface == LOGIC_OBLIGATION_V2_INTERFACE
    assert obligation.document_id == document.document_id
    assert obligation.source_digest == document.content_digest
    assert obligation.expression_id == expression.expression_id
    assert obligation.expression_digest == expression.content_digest
    assert obligation.slice_id == admitted.slice_id
    assert obligation.slice_digest == admitted.content_digest


# ---------------------------------------------------------------------------
# BackendRequest@2.from_slice (executable request construction)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,unsupported_extensions",
    [
        (DomainSliceStatus.REJECTED, ()),
        (DomainSliceStatus.UNSUPPORTED, ("hyper.trace/v1",)),
        ("rejected", ()),
        ("unsupported", ("intent.opaque/v1",)),
    ],
)
def test_backend_request_from_slice_rejects_unadmitted(
    status: DomainSliceStatus | str,
    unsupported_extensions: tuple[str, ...],
) -> None:
    unadmitted = _slice(
        status=status,
        slice_id=f"slice:lpc-044-{status}",
        unsupported_extensions=unsupported_extensions,
    )
    assert unadmitted.is_admitted is False
    with pytest.raises(DomainSliceAdmissionError, match="not admitted"):
        BackendRequestV2.from_slice(unadmitted, **_from_slice_kwargs())


def test_backend_request_from_slice_rejects_non_domain_logic_slice() -> None:
    with pytest.raises(RequestV2Error, match="DomainLogicSliceV2"):
        BackendRequestV2.from_slice(
            object(),  # type: ignore[arg-type]
            **_from_slice_kwargs(request_id="req:lpc-044-obj"),
        )


@pytest.mark.parametrize(
    "domain",
    (
        "legal_ir",
        "security_ir",
        "software_verification",
        "crypto_ir",
        "intent_ir",
        "ui_ux_ir",
    ),
)
def test_backend_request_from_admitted_slice_succeeds_across_domains(
    domain: str,
) -> None:
    document = _document(f"claim for {domain}", document_id=f"doc:{domain}")
    expression = _expression(f"expr:{domain}")
    admitted = _slice(
        document=document,
        expression=expression,
        domain=domain,
        slice_id=f"slice:lpc-044:{domain}",
    )
    request = BackendRequestV2.from_slice(
        admitted,
        **_from_slice_kwargs(
            request_id=f"req:lpc-044:{domain}",
            obligation_id=f"obl:lpc-044:{domain}",
        ),
    )
    assert request.interface == BACKEND_REQUEST_V2_INTERFACE
    assert request.slice_id == admitted.slice_id
    assert request.slice_digest == admitted.content_digest
    assert request.document_id == document.document_id
    assert request.source_digest == document.content_digest
    assert request.expression_id == expression.expression_id
    assert request.expression_digest == expression.content_digest
    # Executable construction never drops lineage.
    assert request.slice_id
    assert request.slice_digest
    assert len(request.slice_digest) == 64


def test_backend_request_from_slice_is_only_admitted_path_for_slice_seed() -> None:
    """Rejected slices never produce a request object that could reach providers."""

    rejected = _slice(
        status=DomainSliceStatus.REJECTED,
        slice_id="slice:lpc-044-no-leak",
    )
    caught: DomainSliceAdmissionError | None = None
    try:
        BackendRequestV2.from_slice(
            rejected,
            **_from_slice_kwargs(request_id="req:lpc-044-no-leak"),
        )
    except DomainSliceAdmissionError as error:
        caught = error
    assert caught is not None
    assert "not admitted" in str(caught)
    # No partial request: construction either fully succeeds or raises.


def test_executable_protocol_ops_require_backend_request_built_from_admitted_slice() -> None:
    """Executable protocol ops bind an admitted BackendRequest@2 only."""

    for operation in sorted(EXECUTABLE_OPERATIONS):
        assert is_executable_operation(operation) is True

    admitted = _slice(slice_id="slice:lpc-044-exec")
    request = BackendRequestV2.from_slice(
        admitted,
        **_from_slice_kwargs(request_id="req:lpc-044-exec", obligation_id="obl:lpc-044-exec"),
    )
    prove = ProveCheckRequestV2(
        mode=ProveCheckMode.PROVE,
        backend_request=request,
        bounds=request.bounds,
    )
    assert prove.backend_request.slice_id == admitted.slice_id
    assert prove.backend_request.slice_digest == admitted.content_digest

    with pytest.raises(ProtocolV2AdmissionError, match="BackendRequest@2"):
        ProveCheckRequestV2(
            mode=ProveCheckMode.PROVE,
            backend_request=None,  # type: ignore[arg-type]
            bounds=_bounds(),
        )


def test_unadmitted_slice_never_reaches_executable_protocol_request() -> None:
    """End-to-end: unadmitted slice cannot produce prove/check work."""

    unsupported = _slice(
        status=DomainSliceStatus.UNSUPPORTED,
        slice_id="slice:lpc-044-e2e-unsup",
        unsupported_extensions=("uiux.layout/v1",),
    )
    with pytest.raises(DomainSliceAdmissionError, match="not admitted"):
        request = BackendRequestV2.from_slice(
            unsupported,
            **_from_slice_kwargs(request_id="req:lpc-044-e2e"),
        )
        # Unreachable: if from_slice ever leaked a request, the next line
        # would incorrectly elevate unadmitted work.
        ProveCheckRequestV2(
            mode=ProveCheckMode.CHECK,
            backend_request=request,
            bounds=request.bounds,
        )


def test_rejected_and_unsupported_do_not_equal_admitted_for_request_seed() -> None:
    document = _document()
    expression = _expression()
    admitted = _slice(document=document, expression=expression, slice_id="slice:ok")
    rejected = _slice(
        document=document,
        expression=expression,
        status=DomainSliceStatus.REJECTED,
        slice_id="slice:rej",
    )
    unsupported = _slice(
        document=document,
        expression=expression,
        status=DomainSliceStatus.UNSUPPORTED,
        slice_id="slice:unsup",
        unsupported_extensions=("session.pi/v1",),
    )
    assert admitted.status is DomainSliceStatus.ADMITTED
    assert rejected.status is DomainSliceStatus.REJECTED
    assert unsupported.status is DomainSliceStatus.UNSUPPORTED
    assert admitted.is_admitted and not rejected.is_admitted and not unsupported.is_admitted

    ok = BackendRequestV2.from_slice(admitted, **_from_slice_kwargs())
    assert ok.slice_id == "slice:ok"
    for bad in (rejected, unsupported):
        with pytest.raises(DomainSliceAdmissionError):
            BackendRequestV2.from_slice(
                bad,
                **_from_slice_kwargs(request_id=f"req:{bad.slice_id}"),
            )
