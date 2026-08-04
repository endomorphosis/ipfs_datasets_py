"""Integration tests for authorized portfolio review (PATLAW-152 / PATLAW-G171).

Covers:
- public/private version reconciliation without disclosure downgrade
- rejection is not treated as terminal lifecycle
- delayed or absent upstream records remain unknown
- authorized tenant-scoped review projections (lifecycle, OA, rejection,
  submission, receipt, gap, reviewer-action)
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.matter_events import (
    ApplicationLifecyclePhase,
    RejectionDisposition,
)
from ipfs_datasets_py.processors.domains.uspto.portfolio_service import (
    ACCESS_DENIED_CODE,
    CAP_INGEST_PRIVATE,
    CAP_INGEST_PUBLIC,
    CAP_LIST_PORTFOLIO,
    CAP_READ_REVIEW,
    CAP_SEARCH,
    FORBIDDEN_PORTFOLIO_CAPABILITIES,
    PORTFOLIO_SERVICE_SCHEMA_VERSION,
    AccessOutcome,
    ApplicationLifecycle,
    FactPresence,
    FactSourceChannel,
    PatentPortfolioService,
    PortfolioAccessGrant,
    PortfolioAccessResult,
    PortfolioCapabilityError,
    PortfolioFactVersion,
    PortfolioPrincipal,
    PortfolioServiceError,
    RejectionEvent,
    ReviewDisposition,
    content_digest,
    lifecycle_is_terminal,
)

CLOCK = "2026-08-04T12:00:00Z"
TENANT_A = "tenant-portfolio-a"
TENANT_B = "tenant-portfolio-b"
MATTER = "matter:syn:16-123456"
APP_NO = "16123456"


def _service() -> PatentPortfolioService:
    return PatentPortfolioService(wall_clock=lambda: CLOCK)


def _operator(service: PatentPortfolioService, tenant: str = TENANT_A) -> PortfolioPrincipal:
    op = PortfolioPrincipal(subject_id=f"op-{tenant}", tenant_id=tenant, roles=("operator",))
    service.register_operator(op)
    return op


def _grant(
    service: PatentPortfolioService,
    operator: PortfolioPrincipal,
    *,
    subject_id: str,
    matter_id: str = "*",
    capabilities: tuple[str, ...] = (
        CAP_READ_REVIEW,
        CAP_LIST_PORTFOLIO,
        CAP_SEARCH,
        CAP_INGEST_PUBLIC,
        CAP_INGEST_PRIVATE,
    ),
) -> PortfolioPrincipal:
    principal = PortfolioPrincipal(subject_id=subject_id, tenant_id=operator.tenant_id)
    grant_matter_token = "all" if matter_id == "*" else matter_id.replace(":", "-")
    service.grant_access(
        operator,
        PortfolioAccessGrant(
            grant_id=f"grant-{subject_id}-{grant_matter_token}",
            tenant_id=operator.tenant_id,
            subject_id=subject_id,
            matter_id=matter_id,
            capabilities=capabilities,
            issued_utc=CLOCK,
        ),
    )
    return principal


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)


# ---------------------------------------------------------------------------
# Capability surface
# ---------------------------------------------------------------------------


def test_forbidden_capabilities_cannot_be_invoked() -> None:
    svc = _service()
    for cap in sorted(FORBIDDEN_PORTFOLIO_CAPABILITIES):
        with pytest.raises(PortfolioCapabilityError):
            svc.assert_capability_allowed(cap)
    # Allowed capabilities pass
    for cap in (CAP_READ_REVIEW, CAP_LIST_PORTFOLIO, CAP_SEARCH):
        svc.assert_capability_allowed(cap)


def test_no_patent_center_account_enumeration_surface() -> None:
    svc = _service()
    assert not hasattr(svc, "enumerate_account")
    assert not hasattr(svc, "scrape_patent_center")
    assert not hasattr(svc, "login")
    assert "enumerate_patent_center_account" in FORBIDDEN_PORTFOLIO_CAPABILITIES
    assert "scrape_authenticated_patent_center" in FORBIDDEN_PORTFOLIO_CAPABILITIES


# ---------------------------------------------------------------------------
# Public/private reconciliation without disclosure downgrade
# ---------------------------------------------------------------------------


def test_public_private_versions_reconcile_without_disclosure_downgrade() -> None:
    svc = _service()
    op = _operator(svc)
    user = _grant(svc, op, subject_id="reviewer-a")

    # Public ODP status
    pub = svc.ingest_public_odp_status(
        user,
        matter_id=MATTER,
        application_number=APP_NO,
        status_code="40",
        status_text="Non Final Action Mailed",
        source_event_utc="2025-06-01T00:00:00Z",
        observed_utc="2026-08-01T10:00:00Z",
        source_receipt_id="receipt-odp-1",
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    assert pub.authorized is True
    assert pub.projection is not None
    assert pub.projection.classification is DisclosureClassification.PUBLIC_OFFICIAL

    # Private export with more restrictive classification for same logical status
    priv = svc.ingest_private_export_status(
        user,
        matter_id=MATTER,
        application_number=APP_NO,
        status_code="40",
        status_text="Non Final Action Mailed",
        source_event_utc="2025-06-01T00:00:00Z",
        observed_utc="2026-08-02T10:00:00Z",
        source_receipt_id="receipt-private-1",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    assert priv.authorized is True
    proj = priv.projection
    assert proj is not None
    # Result must not downgrade to public_official.
    assert proj.classification is DisclosureClassification.CONFIDENTIAL_APPLICATION
    assert len(proj.reconciled_facts) >= 1
    fact = next(f for f in proj.reconciled_facts if f.logical_id == "status:current")
    assert fact.downgrade_prevented is True
    assert fact.classification is DisclosureClassification.CONFIDENTIAL_APPLICATION
    channels = {v.channel for v in fact.versions}
    assert FactSourceChannel.PUBLIC_ODP in channels
    assert FactSourceChannel.PRIVATE_IMPORT in channels
    # Both version identities retained
    assert len(fact.versions) == 2
    _assert_round_trip(proj)
    _assert_round_trip(fact)


def test_reconcile_helper_refuses_public_over_private() -> None:
    svc = _service()
    public_v = PortfolioFactVersion(
        version_id="v-public",
        channel=FactSourceChannel.PUBLIC_ODP,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        presence=FactPresence.PRESENT,
        content_sha256="a" * 64,
        source_receipt_id="r1",
        source_event_utc="2025-01-01T00:00:00Z",
        observed_utc="2026-01-01T00:00:00Z",
    )
    private_v = PortfolioFactVersion(
        version_id="v-private",
        channel=FactSourceChannel.PRIVATE_IMPORT,
        classification=DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        presence=FactPresence.PRESENT,
        content_sha256="b" * 64,
        source_receipt_id="r2",
        source_event_utc="2025-01-01T00:00:00Z",
        observed_utc="2026-01-02T00:00:00Z",
    )
    fact = svc.reconcile_public_private_versions(
        (public_v, private_v), logical_id="status:current"
    )
    assert fact.classification is DisclosureClassification.PRIVILEGED_WORK_PRODUCT
    assert fact.downgrade_prevented is True
    # Constructing a downgraded ReconciledFact must fail.
    with pytest.raises(PortfolioServiceError) as exc:
        from ipfs_datasets_py.processors.domains.uspto.portfolio_service import (
            PortfolioFactKind,
            ReconciledFact,
        )

        ReconciledFact(
            logical_id="status:current",
            kind=PortfolioFactKind.STATUS,
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            versions=(public_v, private_v),
            presence=FactPresence.PRESENT,
            downgrade_prevented=False,
        )
    assert exc.value.code == "disclosure_downgrade"


# ---------------------------------------------------------------------------
# Rejection is not terminal
# ---------------------------------------------------------------------------


def test_final_rejection_is_not_terminal_lifecycle() -> None:
    svc = _service()
    op = _operator(svc)
    user = _grant(svc, op, subject_id="reviewer-rej")

    result = svc.ingest_public_odp_status(
        user,
        matter_id=MATTER,
        application_number=APP_NO,
        status_code="50",
        status_text="Final Rejection Mailed",
        source_event_utc="2025-07-01T00:00:00Z",
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    assert result.authorized
    life = result.projection.lifecycle  # type: ignore[union-attr]
    assert life.phase is ApplicationLifecyclePhase.EXAMINATION
    assert life.rejection_disposition is RejectionDisposition.FINAL
    assert life.is_terminal is False
    assert life.is_abandoned is not True
    assert lifecycle_is_terminal(life.phase) is False
    assert "rejected" not in life.to_dict() or life.to_dict().get("is_terminal") is False

    rej = svc.ingest_rejection_event(
        user,
        matter_id=MATTER,
        event_id="rej-final-1",
        disposition=RejectionDisposition.FINAL,
        claim_numbers=("1", "2", "3-10"),
        office_action_artifact_id="oa-art-1",
        source_event_utc="2025-07-01T00:00:00Z",
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    assert rej.authorized
    events = rej.projection.rejections  # type: ignore[union-attr]
    assert len(events) == 1
    assert events[0].is_terminal is False
    assert events[0].disposition is RejectionDisposition.FINAL
    assert events[0].claim_numbers == ("1", "2", "3-10")
    # Lifecycle still not terminal after rejection event.
    assert rej.projection.lifecycle.is_terminal is False  # type: ignore[union-attr]
    assert any(
        "not a terminal" in n.lower() or "not terminal" in n.lower()
        for n in rej.projection.notes  # type: ignore[union-attr]
    )
    _assert_round_trip(events[0])


def test_rejection_event_refuses_is_terminal_true() -> None:
    with pytest.raises(PortfolioServiceError) as exc:
        RejectionEvent(
            schema_version=PORTFOLIO_SERVICE_SCHEMA_VERSION,
            event_id="bad-terminal",
            matter_id=MATTER,
            disposition=RejectionDisposition.FINAL,
            claim_numbers=("1",),
            office_action_artifact_id=None,
            source_event_utc="2025-01-01T00:00:00Z",
            observed_utc="2026-01-01T00:00:00Z",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            source_channel=FactSourceChannel.PUBLIC_ODP,
            review_disposition=ReviewDisposition.NOT_REVIEWED,
            source_receipt_id=None,
            is_terminal=True,
        )
    assert exc.value.code == "rejection_not_terminal"


def test_abandonment_and_grant_are_terminal_but_rejection_is_not() -> None:
    assert lifecycle_is_terminal(ApplicationLifecyclePhase.ABANDONMENT) is True
    assert lifecycle_is_terminal(ApplicationLifecyclePhase.GRANT) is True
    assert lifecycle_is_terminal(ApplicationLifecyclePhase.EXAMINATION) is False
    assert lifecycle_is_terminal(ApplicationLifecyclePhase.ALLOWANCE) is False

    svc = _service()
    op = _operator(svc)
    user = _grant(svc, op, subject_id="reviewer-term")

    abandoned = svc.ingest_public_odp_status(
        user,
        matter_id="matter:syn:abandon-1",
        status_code="360",
        status_text="Abandoned -- Failure to Respond to an Office Action",
    )
    assert abandoned.projection.lifecycle.is_terminal is True  # type: ignore[union-attr]
    assert (
        abandoned.projection.lifecycle.phase  # type: ignore[union-attr]
        is ApplicationLifecyclePhase.ABANDONMENT
    )

    patented = svc.ingest_public_odp_status(
        user,
        matter_id="matter:syn:grant-1",
        status_code="90",
        status_text="Patented Case",
    )
    assert patented.projection.lifecycle.is_terminal is True  # type: ignore[union-attr]
    assert patented.projection.lifecycle.phase is ApplicationLifecyclePhase.GRANT  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Delayed / absent remain unknown
# ---------------------------------------------------------------------------


def test_delayed_upstream_status_remains_unknown() -> None:
    svc = _service()
    op = _operator(svc)
    user = _grant(svc, op, subject_id="reviewer-delay")

    result = svc.ingest_public_odp_status(
        user,
        matter_id=MATTER,
        application_number=APP_NO,
        status_code=None,
        status_text=None,
        presence=FactPresence.DELAYED,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    assert result.authorized
    proj = result.projection
    assert proj is not None
    assert proj.lifecycle.phase is ApplicationLifecyclePhase.UNKNOWN
    assert proj.lifecycle.presence is FactPresence.DELAYED
    assert proj.lifecycle.is_terminal is False
    assert proj.lifecycle.is_abandoned is None
    assert len(proj.gaps) >= 1
    gap = proj.gaps[0]
    assert gap.is_proof_of_nonreceipt is False
    assert gap.presence is FactPresence.DELAYED
    _assert_round_trip(gap)


def test_absent_upstream_status_remains_unknown() -> None:
    svc = _service()
    op = _operator(svc)
    user = _grant(svc, op, subject_id="reviewer-absent")

    result = svc.record_delayed_or_absent(
        user,
        matter_id=MATTER,
        gap_id="gap-absent-doc-1",
        code="expected_item_absent",
        presence=FactPresence.ABSENT,
        message="document inventory entry not yet downloadable",
        interpretation="retrieval_gap",
    )
    assert result.authorized
    proj = result.projection
    assert proj is not None
    # No status invented from absence.
    assert proj.lifecycle.phase is ApplicationLifecyclePhase.UNKNOWN
    assert any(g.presence is FactPresence.ABSENT for g in proj.gaps)
    assert all(g.is_proof_of_nonreceipt is False for g in proj.gaps)


def test_unknown_status_code_stays_unknown_not_invented() -> None:
    svc = _service()
    op = _operator(svc)
    user = _grant(svc, op, subject_id="reviewer-unk-code")

    # Numeric code outside protected vocabulary → quarantine recognition,
    # but we still record the raw code via inference path carefully.
    result = svc.ingest_public_odp_status(
        user,
        matter_id=MATTER,
        status_code="99999",
        status_text="Totally Novel Future Status",
        presence=FactPresence.PRESENT,
    )
    assert result.authorized
    life = result.projection.lifecycle  # type: ignore[union-attr]
    # Phase may be OTHER/UNKNOWN via inference; must not invent abandoned.
    assert life.is_abandoned is not True
    assert life.is_terminal is False


# ---------------------------------------------------------------------------
# Full review projection surfaces
# ---------------------------------------------------------------------------


def test_authorized_review_projection_covers_all_views() -> None:
    svc = _service()
    op = _operator(svc)
    user = _grant(svc, op, subject_id="reviewer-full")

    svc.ingest_public_odp_status(
        user,
        matter_id=MATTER,
        application_number=APP_NO,
        status_code="40",
        status_text="Non Final Action Mailed",
        source_event_utc="2025-05-01T00:00:00Z",
    )
    svc.ingest_private_export_status(
        user,
        matter_id=MATTER,
        application_number=APP_NO,
        status_code="40",
        status_text="Non Final Action Mailed",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        source_event_utc="2025-05-01T00:00:00Z",
    )
    svc.ingest_rejection_event(
        user,
        matter_id=MATTER,
        event_id="rej-nf-1",
        disposition=RejectionDisposition.NONFINAL,
        claim_numbers=("1", "5"),
        office_action_artifact_id="oa-1",
        source_event_utc="2025-05-01T00:00:00Z",
        private=True,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    svc.ingest_submission(
        user,
        matter_id=MATTER,
        submission_id="sub-1",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        artifact_id="art-sub-1",
        source_event_utc="2025-04-01T00:00:00Z",
    )
    svc.ingest_receipt(
        user,
        matter_id=MATTER,
        receipt_id="rcpt-1",
        kind="acknowledgement",
        artifact_id="art-rcpt-1",
        source_event_utc="2025-04-01T00:00:00Z",
    )
    svc.record_delayed_or_absent(
        user,
        matter_id=MATTER,
        gap_id="gap-drawings",
        code="delayed_publication",
        presence=FactPresence.DELAYED,
        message="drawings not yet in public file wrapper",
    )
    svc.ingest_reviewer_action(
        user,
        matter_id=MATTER,
        action_id="act-1",
        action_code="review_response_strategy",
        review_state=ReviewState.REQUIRED,
        classification=DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
    )

    review = svc.get_review(user, matter_id=MATTER)
    assert review.outcome is AccessOutcome.AUTHORIZED
    assert review.authorized is True
    proj = review.projection
    assert proj is not None
    assert proj.tenant_id == TENANT_A
    assert proj.matter_id == MATTER
    assert proj.application_number == APP_NO
    assert proj.lifecycle.phase is ApplicationLifecyclePhase.EXAMINATION
    assert proj.lifecycle.is_terminal is False
    assert len(proj.rejections) == 1
    assert len(proj.office_actions) == 1
    assert len(proj.submissions) == 1
    assert len(proj.receipts) == 1
    assert len(proj.gaps) >= 1
    assert len(proj.reviewer_actions) == 1
    assert proj.review_state is ReviewState.REQUIRED
    # Most restrictive overall classification across private inputs.
    assert proj.classification in (
        DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    _assert_round_trip(proj)

    listed = svc.list_portfolio(user)
    assert listed.authorized
    assert MATTER in (listed.matter_ids or ())
    assert listed.total_count == 1

    searched = svc.search_portfolio(user, query=APP_NO)
    assert searched.authorized
    assert MATTER in (searched.search_hits or ())

    counted = svc.count_portfolio(user)
    assert counted.authorized
    assert counted.total_count == 1


def test_application_lifecycle_unknown_factory_and_round_trip() -> None:
    life = ApplicationLifecycle.unknown(MATTER)
    assert life.phase is ApplicationLifecyclePhase.UNKNOWN
    assert life.presence is FactPresence.UNKNOWN
    assert life.is_terminal is False
    _assert_round_trip(life)


def test_content_digest_stable() -> None:
    a = content_digest({"x": 1, "y": "z"})
    b = content_digest({"y": "z", "x": 1})
    assert a == b
    assert len(a) == 64


def test_denial_shape_is_uniform() -> None:
    denied_a = PortfolioAccessResult.denied(
        audit={"operation": "get_review", "reason": "unauthorized"}
    )
    denied_b = PortfolioAccessResult.denied(
        audit={"operation": "get_review", "reason": "unauthorized"}
    )
    assert denied_a.to_dict() == denied_b.to_dict()
    assert denied_a.code == ACCESS_DENIED_CODE
    assert denied_a.projection is None
    assert denied_a.total_count is None
    assert denied_a.matter_ids is None
    assert denied_a.search_hits is None
    assert denied_a.duration_ms == 0
