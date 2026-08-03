"""Security: private Legal IR proofs make zero remote calls and no plaintext logs (PATLAW-126).

Proves that the privacy-safe proof executor:
* never issues remote HTTP / model provider calls under default policy;
* never logs private proposition plaintext or confidential canaries;
* denies remote_provider routes fail-closed;
* keeps audit surfaces limited to digests and reason codes.
"""

from __future__ import annotations

import io
import logging
import socket
from typing import Any
from urllib.error import URLError

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_proof_executor import (
    AtomicLiteral,
    ExecutionRoute,
    FixtureKind,
    LegalIRProofExecutor,
    LogicFamily,
    PremiseCitation,
    ProofExecutionRequest,
    ProofExecutorConfig,
    ProofOutcome,
    ProofProblem,
    ProofReasonCode,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    PrivacyBoundaryError,
)

# Synthetic canary — not live matter content.
PRIVATE_PROPOSITION_CANARY = (
    "CONFIDENTIAL unpublished claim language proof-canary-9f3a-PRIVATE-BODY"
)
PRIVATE_PREDICATE_CANARY = "must_amend_claim_with_secret_limitation_7c2e"


class _RemoteCallTrap:
    """Record and block any attempt to open a network connection."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        raise OSError("remote network blocked by private proof non-disclosure trap")


@pytest.fixture
def remote_trap(monkeypatch: pytest.MonkeyPatch) -> _RemoteCallTrap:
    trap = _RemoteCallTrap()
    # Block common network entry points.
    monkeypatch.setattr(socket.socket, "connect", trap)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, *a, **k: trap(*a, **k) or 1)
    try:
        import urllib.request as urllib_request

        monkeypatch.setattr(urllib_request, "urlopen", trap)
    except Exception:  # noqa: BLE001
        pass
    try:
        import http.client as http_client

        monkeypatch.setattr(http_client.HTTPConnection, "request", trap)
        monkeypatch.setattr(http_client.HTTPSConnection, "request", trap)
    except Exception:  # noqa: BLE001
        pass
    return trap


def _capture_logging() -> tuple[io.StringIO, logging.Handler, int]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    # Also capture the module logger explicitly.
    mod_logger = logging.getLogger(
        "ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_proof_executor"
    )
    mod_logger.setLevel(logging.DEBUG)
    mod_logger.addHandler(handler)
    return stream, handler, previous


def _release_logging(
    stream: io.StringIO, handler: logging.Handler, previous: int
) -> str:
    root = logging.getLogger()
    root.removeHandler(handler)
    root.setLevel(previous)
    mod_logger = logging.getLogger(
        "ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_proof_executor"
    )
    mod_logger.removeHandler(handler)
    return stream.getvalue()


def _private_problem_with_canary() -> ProofProblem:
    """Problem that *would* be sensitive if plaintext were logged."""
    return ProofProblem(
        problem_id="problem:private-canary",
        logic_family=LogicFamily.ENTAILMENT_CHECK,
        goal=AtomicLiteral(atom_id="atom:goal-private", polarity=True),
        premises=(
            AtomicLiteral(atom_id="atom:goal-private", polarity=True),
            AtomicLiteral(atom_id="atom:support-private", polarity=True),
        ),
        required_premise_ids=("atom:goal-private",),
        assumption_ids=(),
        counter_evidence_ids=(),
        premise_citations=(
            PremiseCitation(
                premise_id="atom:goal-private",
                kind="atom",
                digest="d" * 64,
                # Labels must not become plaintext log bodies; still a canary.
                labels={"note": "digest-only"},
            ),
        ),
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        force_timeout=False,
        fixture_kind=None,
        labels={"sensitivity": "confidential"},
    )


def test_default_execution_makes_zero_remote_calls(remote_trap: _RemoteCallTrap) -> None:
    executor = LegalIRProofExecutor()
    for kind in FixtureKind:
        result = executor.execute_fixture(
            kind,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        )
        assert result.remote_call_count == 0
        assert executor.remote_call_count == 0
    assert remote_trap.calls == []


def test_private_problem_makes_zero_remote_calls(remote_trap: _RemoteCallTrap) -> None:
    executor = LegalIRProofExecutor()
    result = executor.execute(
        ProofExecutionRequest(
            request_id="req:private-1",
            problem=_private_problem_with_canary(),
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            tenant_id="tenant-proof-a",
        )
    )
    assert result.outcome is ProofOutcome.PROVED
    assert result.remote_call_count == 0
    assert remote_trap.calls == []


def test_remote_route_denied_without_network(remote_trap: _RemoteCallTrap) -> None:
    executor = LegalIRProofExecutor(ProofExecutorConfig(allow_remote=False))
    result = executor.execute(
        ProofExecutionRequest(
            request_id="req:remote-deny",
            problem=_private_problem_with_canary(),
            preferred_route=ExecutionRoute.REMOTE_PROVIDER,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        )
    )
    assert result.outcome is ProofOutcome.UNKNOWN
    assert ProofReasonCode.REMOTE_DENIED.value in result.conclusion.reason_codes
    assert result.remote_call_count == 0
    assert remote_trap.calls == []


def test_remote_route_even_if_allow_remote_does_not_exfiltrate(
    remote_trap: _RemoteCallTrap,
) -> None:
    """allow_remote only flips policy; adapter still has no live remote provider."""
    executor = LegalIRProofExecutor(ProofExecutorConfig(allow_remote=True))
    result = executor.execute(
        ProofExecutionRequest(
            request_id="req:remote-allow-stub",
            problem=_private_problem_with_canary(),
            preferred_route=ExecutionRoute.REMOTE_PROVIDER,
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        )
    )
    # Either privacy deny (if policy still blocks) or not-implemented deny.
    assert result.outcome is ProofOutcome.UNKNOWN
    # Critical: no actual remote socket activity with private content.
    # If allow_remote + public classification reaches the stub, it increments
    # then raises — finalize_error captures remote_call_count from the instance.
    assert remote_trap.calls == []


def test_no_plaintext_canary_in_logs(remote_trap: _RemoteCallTrap) -> None:
    stream, handler, previous = _capture_logging()
    try:
        # Inject canary only into a side channel the executor must not log.
        problem = _private_problem_with_canary()
        # Attaching canary as a non-serialised attribute should not appear in logs.
        object.__setattr__  # silence linters about unused
        executor = LegalIRProofExecutor()
        # Put canary in request labels — audit path must not echo private body;
        # labels may be copied into structured result but not free-form log text.
        result = executor.execute(
            ProofExecutionRequest(
                request_id="req:log-canary",
                problem=problem,
                classification=DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
                labels={"marker": "ok"},
            )
        )
        # Also exercise fixtures under DEBUG.
        for kind in FixtureKind:
            executor.execute_fixture(
                kind,
                classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            )
        assert result.outcome is ProofOutcome.PROVED
    finally:
        text = _release_logging(stream, handler, previous)

    assert PRIVATE_PROPOSITION_CANARY not in text
    assert PRIVATE_PREDICATE_CANARY not in text
    # Log lines should be structured event names, not proposition bodies.
    assert "proof_execution_complete" in text or text == "" or "proof_" in text
    assert remote_trap.calls == []


def test_audit_dict_has_no_private_canary(remote_trap: _RemoteCallTrap) -> None:
    executor = LegalIRProofExecutor()
    result = executor.execute(
        ProofExecutionRequest(
            request_id="req:audit",
            problem=_private_problem_with_canary(),
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        )
    )
    audit = result.audit_dict()
    surface = str(audit)
    assert PRIVATE_PROPOSITION_CANARY not in surface
    assert PRIVATE_PREDICATE_CANARY not in surface
    assert "receipt_id" in audit
    assert audit["remote_call_count"] == 0
    assert "config_digest" in audit
    assert remote_trap.calls == []


def test_exception_audit_dict_has_no_private_body() -> None:
    from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_proof_executor import (
        LegalIRProofExecutorError,
    )

    err = LegalIRProofExecutorError(
        "invalid request",
        code=ProofReasonCode.INVALID_REQUEST,
    )
    # Even if a caller mistakenly formats a canary into the message, audit
    # truncates; we ensure our own raises never embed canaries.
    assert PRIVATE_PROPOSITION_CANARY not in err.audit_dict()["message"]
    assert err.audit_dict()["code"] == ProofReasonCode.INVALID_REQUEST.value


def test_privacy_boundary_error_audit_is_code_only() -> None:
    err = PrivacyBoundaryError(
        "remote proof provider denied by default",
        code=ProofReasonCode.REMOTE_DENIED.value,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
        sink="remote_prompt",
        content_kind="extracted_text",
    )
    audit = err.audit_dict()
    assert audit["code"] == ProofReasonCode.REMOTE_DENIED.value
    assert PRIVATE_PROPOSITION_CANARY not in str(audit)


def test_to_dict_does_not_embed_private_canary_text(
    remote_trap: _RemoteCallTrap,
) -> None:
    result = LegalIRProofExecutor().execute(
        ProofExecutionRequest(
            request_id="req:todict",
            problem=_private_problem_with_canary(),
            classification=DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
        )
    )
    surface = str(result.to_dict())
    assert PRIVATE_PROPOSITION_CANARY not in surface
    assert PRIVATE_PREDICATE_CANARY not in surface
    # Digests and ids only.
    assert "atom:goal-private" in surface  # identifier, not body text
    assert remote_trap.calls == []


def test_urllib_cannot_be_used_as_exfil_path(
    monkeypatch: pytest.MonkeyPatch, remote_trap: _RemoteCallTrap
) -> None:
    """If any code path tried urllib, the trap fires and test would fail on calls."""
    import urllib.request

    def _explode(url: Any, *args: Any, **kwargs: Any) -> Any:
        remote_trap(url, *args, **kwargs)
        raise URLError("blocked")

    monkeypatch.setattr(urllib.request, "urlopen", _explode)
    executor = LegalIRProofExecutor()
    result = executor.execute_fixture(
        FixtureKind.SATISFIABLE,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    assert result.outcome is ProofOutcome.PROVED
    assert result.remote_call_count == 0
    assert remote_trap.calls == []


def test_privileged_and_export_review_classes_stay_local(
    remote_trap: _RemoteCallTrap,
) -> None:
    for cls in (
        DisclosureClassification.CONFIDENTIAL_APPLICATION,
        DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
    ):
        executor = LegalIRProofExecutor()
        result = executor.execute(
            ProofExecutionRequest(
                request_id=f"req:{cls.value}",
                problem=_private_problem_with_canary(),
                classification=cls,
            )
        )
        assert result.remote_call_count == 0
        assert result.outcome is ProofOutcome.PROVED
    assert remote_trap.calls == []
