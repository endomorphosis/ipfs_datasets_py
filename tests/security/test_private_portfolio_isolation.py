"""Security tests: private portfolio isolation and anti-oracle (PATLAW-152).

Proves that authorization and tenant isolation expose **no** record, count,
timing, or search oracle to an unauthorized caller. Wrong-tenant and
ungranted principals receive uniform denials regardless of whether a matter
exists.
"""

from __future__ import annotations

import time

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.matter_events import (
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
    AccessOutcome,
    FactPresence,
    PatentPortfolioService,
    PortfolioAccessGrant,
    PortfolioAccessResult,
    PortfolioAuthorizationError,
    PortfolioCapabilityError,
    PortfolioPrincipal,
)

CLOCK = "2026-08-04T15:00:00Z"
TENANT_A = "tenant-iso-a"
TENANT_B = "tenant-iso-b"
MATTER_SECRET = "matter:syn:private-secret-99"
APP_SECRET = "16999999"
PRIVATE_CANARY = "CONFIDENTIAL-PORTFOLIO-CANARY-text-7c2e"


def _svc() -> PatentPortfolioService:
    return PatentPortfolioService(wall_clock=lambda: CLOCK)


def _setup_tenant_with_secret(
    svc: PatentPortfolioService,
) -> tuple[PortfolioPrincipal, PortfolioPrincipal]:
    """Create tenant A operator + authorized reviewer with one private matter."""
    op_a = PortfolioPrincipal(subject_id="op-a", tenant_id=TENANT_A, roles=("operator",))
    svc.register_operator(op_a)
    reviewer_a = PortfolioPrincipal(subject_id="reviewer-a", tenant_id=TENANT_A)
    svc.grant_access(
        op_a,
        PortfolioAccessGrant(
            grant_id="g-a-all",
            tenant_id=TENANT_A,
            subject_id="reviewer-a",
            matter_id="*",
            capabilities=(
                CAP_READ_REVIEW,
                CAP_LIST_PORTFOLIO,
                CAP_SEARCH,
                CAP_INGEST_PUBLIC,
                CAP_INGEST_PRIVATE,
            ),
            issued_utc=CLOCK,
        ),
    )
    # Seed a private matter with a canary that must never leak.
    seeded = svc.ingest_private_export_status(
        reviewer_a,
        matter_id=MATTER_SECRET,
        application_number=APP_SECRET,
        status_code="40",
        status_text=f"Non Final Action Mailed {PRIVATE_CANARY}",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        raw_fields={"canary": PRIVATE_CANARY},
        notes=(PRIVATE_CANARY,),
    )
    assert seeded.authorized is True
    assert seeded.projection is not None
    assert PRIVATE_CANARY in canonical_blob(seeded.projection.to_dict())
    return op_a, reviewer_a


def canonical_blob(obj: object) -> str:
    import json

    return json.dumps(obj, sort_keys=True, default=str)


def _unauthorized_principals() -> list[PortfolioPrincipal]:
    return [
        PortfolioPrincipal(subject_id="stranger", tenant_id=TENANT_A),
        PortfolioPrincipal(subject_id="reviewer-a", tenant_id=TENANT_B),
        PortfolioPrincipal(subject_id="eve", tenant_id=TENANT_B),
        PortfolioPrincipal(subject_id="nobody", tenant_id="tenant-other"),
    ]


# ---------------------------------------------------------------------------
# Uniform denial — no record / count / timing / search oracle
# ---------------------------------------------------------------------------


def test_unauthorized_get_review_is_uniform_whether_matter_exists() -> None:
    svc = _svc()
    _setup_tenant_with_secret(svc)

    # Existing secret matter vs never-created matter — same denial shape.
    existing_id = MATTER_SECRET
    missing_id = "matter:syn:does-not-exist-000"

    for principal in _unauthorized_principals():
        den_exist = svc.get_review(principal, matter_id=existing_id)
        den_miss = svc.get_review(principal, matter_id=missing_id)
        assert den_exist.authorized is False
        assert den_miss.authorized is False
        assert den_exist.outcome is AccessOutcome.DENIED
        assert den_miss.outcome is AccessOutcome.DENIED
        assert den_exist.code == ACCESS_DENIED_CODE
        assert den_miss.code == ACCESS_DENIED_CODE
        # Structural equality of oracle-sensitive fields.
        assert den_exist.projection is None and den_miss.projection is None
        assert den_exist.total_count is None and den_miss.total_count is None
        assert den_exist.matter_ids is None and den_miss.matter_ids is None
        assert den_exist.search_hits is None and den_miss.search_hits is None
        assert den_exist.duration_ms == den_miss.duration_ms == 0
        # Canary must not appear in denial serialization.
        blob = canonical_blob(den_exist.to_dict()) + canonical_blob(den_miss.to_dict())
        assert PRIVATE_CANARY not in blob
        assert APP_SECRET not in blob
        assert MATTER_SECRET not in blob or "matter_id" not in den_exist.audit


def test_unauthorized_list_exposes_no_count_or_records() -> None:
    svc = _svc()
    _, reviewer_a = _setup_tenant_with_secret(svc)

    # Authorized baseline sees the secret matter.
    allowed = svc.list_portfolio(reviewer_a)
    assert allowed.authorized is True
    assert allowed.total_count == 1
    assert MATTER_SECRET in (allowed.matter_ids or ())

    for principal in _unauthorized_principals():
        denied = svc.list_portfolio(principal)
        assert denied.authorized is False
        assert denied.code == ACCESS_DENIED_CODE
        assert denied.total_count is None  # no count oracle
        assert denied.matter_ids is None  # no record oracle
        blob = canonical_blob(denied.to_dict())
        assert PRIVATE_CANARY not in blob
        assert MATTER_SECRET not in blob
        assert APP_SECRET not in blob


def test_unauthorized_search_exposes_no_search_oracle() -> None:
    svc = _svc()
    _, reviewer_a = _setup_tenant_with_secret(svc)

    # Authorized search finds the matter by application number.
    hit = svc.search_portfolio(reviewer_a, query=APP_SECRET)
    assert hit.authorized is True
    assert MATTER_SECRET in (hit.search_hits or ())

    for principal in _unauthorized_principals():
        # Searching for the known secret app number still yields uniform denial.
        denied_known = svc.search_portfolio(principal, query=APP_SECRET)
        denied_noise = svc.search_portfolio(principal, query="zzzz-nonexistent")
        assert denied_known.authorized is False
        assert denied_noise.authorized is False
        assert denied_known.search_hits is None
        assert denied_noise.search_hits is None
        assert denied_known.total_count is None
        assert denied_noise.total_count is None
        assert denied_known.to_dict()["code"] == denied_noise.to_dict()["code"]
        assert denied_known.duration_ms == denied_noise.duration_ms
        blob = canonical_blob(denied_known.to_dict())
        assert PRIVATE_CANARY not in blob
        assert APP_SECRET not in blob


def test_unauthorized_count_exposes_no_count_oracle() -> None:
    svc = _svc()
    _, reviewer_a = _setup_tenant_with_secret(svc)

    assert svc.count_portfolio(reviewer_a).total_count == 1

    # Empty tenant vs populated tenant — unauthorized still identical.
    for principal in _unauthorized_principals():
        denied = svc.count_portfolio(principal)
        assert denied.authorized is False
        assert denied.total_count is None
        assert denied.code == ACCESS_DENIED_CODE


def test_timing_oracle_not_exposed_on_denial() -> None:
    """Denial duration_ms is fixed; measured wall time must not appear in result."""
    svc = _svc()
    _setup_tenant_with_secret(svc)
    eve = PortfolioPrincipal(subject_id="eve", tenant_id=TENANT_B)

    samples_exist: list[int] = []
    samples_miss: list[int] = []
    for _ in range(5):
        t0 = time.perf_counter()
        r1 = svc.get_review(eve, matter_id=MATTER_SECRET)
        _ = time.perf_counter() - t0
        t1 = time.perf_counter()
        r2 = svc.get_review(eve, matter_id="matter:syn:missing-xyz")
        _ = time.perf_counter() - t1
        assert r1.duration_ms == r2.duration_ms == 0
        samples_exist.append(r1.duration_ms)
        samples_miss.append(r2.duration_ms)

    assert samples_exist == samples_miss == [0, 0, 0, 0, 0]


def test_denial_constructor_rejects_oracle_fields() -> None:
    with pytest.raises(Exception):
        PortfolioAccessResult(
            outcome=AccessOutcome.DENIED,
            code=ACCESS_DENIED_CODE,
            authorized=False,
            duration_ms=0,
            total_count=3,  # count oracle
        )
    with pytest.raises(Exception):
        PortfolioAccessResult(
            outcome=AccessOutcome.DENIED,
            code=ACCESS_DENIED_CODE,
            authorized=False,
            duration_ms=5,  # timing oracle
        )
    with pytest.raises(Exception):
        PortfolioAccessResult(
            outcome=AccessOutcome.DENIED,
            code="not_found",  # non-uniform code
            authorized=False,
            duration_ms=0,
        )


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_cross_tenant_operator_cannot_grant_or_read() -> None:
    svc = _svc()
    op_a, reviewer_a = _setup_tenant_with_secret(svc)

    op_b = PortfolioPrincipal(subject_id="op-b", tenant_id=TENANT_B, roles=("operator",))
    svc.register_operator(op_b)

    # Operator B cannot issue grants for tenant A.
    with pytest.raises(PortfolioAuthorizationError) as exc:
        svc.grant_access(
            op_b,
            PortfolioAccessGrant(
                grant_id="evil-grant",
                tenant_id=TENANT_A,
                subject_id="mole",
                matter_id="*",
                capabilities=(CAP_READ_REVIEW, CAP_LIST_PORTFOLIO, CAP_SEARCH),
            ),
        )
    assert exc.value.code == "tenant_mismatch"

    # Even a same-subject_id in tenant B cannot read tenant A substance.
    # A tenant-B wildcard grant only sees tenant-B storage (empty for this id).
    twin = PortfolioPrincipal(subject_id="reviewer-a", tenant_id=TENANT_B)
    svc.grant_access(
        op_b,
        PortfolioAccessGrant(
            grant_id="g-b",
            tenant_id=TENANT_B,
            subject_id="reviewer-a",
            matter_id="*",
            capabilities=(CAP_READ_REVIEW, CAP_LIST_PORTFOLIO, CAP_SEARCH),
        ),
    )
    twin_view = svc.get_review(twin, matter_id=MATTER_SECRET)
    assert twin_view.authorized is True
    assert twin_view.projection is not None
    assert twin_view.projection.tenant_id == TENANT_B
    # No private canary / substance from tenant A.
    twin_blob = canonical_blob(twin_view.projection.to_dict())
    assert PRIVATE_CANARY not in twin_blob
    assert twin_view.projection.lifecycle.phase.value == "unknown"
    assert twin_view.projection.rejections == ()
    assert twin_view.projection.submissions == ()

    # Tenant A reviewer still works and still sees private substance.
    ok = svc.get_review(reviewer_a, matter_id=MATTER_SECRET)
    assert ok.authorized is True
    assert ok.projection is not None
    assert ok.projection.tenant_id == TENANT_A
    assert PRIVATE_CANARY in canonical_blob(ok.projection.to_dict())


def test_matter_scoped_grant_does_not_leak_sibling_matters() -> None:
    svc = _svc()
    op = PortfolioPrincipal(subject_id="op-a", tenant_id=TENANT_A)
    svc.register_operator(op)
    full = PortfolioPrincipal(subject_id="full", tenant_id=TENANT_A)
    limited = PortfolioPrincipal(subject_id="limited", tenant_id=TENANT_A)

    svc.grant_access(
        op,
        PortfolioAccessGrant(
            grant_id="g-full",
            tenant_id=TENANT_A,
            subject_id="full",
            matter_id="*",
            capabilities=(
                CAP_READ_REVIEW,
                CAP_LIST_PORTFOLIO,
                CAP_SEARCH,
                CAP_INGEST_PRIVATE,
            ),
        ),
    )
    svc.grant_access(
        op,
        PortfolioAccessGrant(
            grant_id="g-lim",
            tenant_id=TENANT_A,
            subject_id="limited",
            matter_id="matter:syn:allowed-only",
            capabilities=(CAP_READ_REVIEW, CAP_LIST_PORTFOLIO, CAP_SEARCH),
        ),
    )

    svc.ingest_private_export_status(
        full,
        matter_id="matter:syn:allowed-only",
        status_code="30",
        status_text="Docketed",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    svc.ingest_private_export_status(
        full,
        matter_id="matter:syn:secret-sibling",
        status_code="40",
        status_text=f"Non Final {PRIVATE_CANARY}",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )

    ok = svc.get_review(limited, matter_id="matter:syn:allowed-only")
    assert ok.authorized is True

    blocked = svc.get_review(limited, matter_id="matter:syn:secret-sibling")
    assert blocked.authorized is False
    assert blocked.projection is None
    assert PRIVATE_CANARY not in canonical_blob(blocked.to_dict())

    listed = svc.list_portfolio(limited)
    assert listed.authorized is True
    assert listed.matter_ids == ("matter:syn:allowed-only",)
    assert "matter:syn:secret-sibling" not in (listed.matter_ids or ())

    search = svc.search_portfolio(limited, query="secret")
    assert search.authorized is True
    assert "matter:syn:secret-sibling" not in (search.search_hits or ())


def test_unauthorized_ingest_does_not_create_or_leak() -> None:
    svc = _svc()
    _setup_tenant_with_secret(svc)
    eve = PortfolioPrincipal(subject_id="eve", tenant_id=TENANT_B)

    denied = svc.ingest_private_export_status(
        eve,
        matter_id=MATTER_SECRET,
        status_code="50",
        status_text="Final Rejection Mailed",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    assert denied.authorized is False
    assert denied.projection is None

    # Tenant B still has empty portfolio.
    op_b = PortfolioPrincipal(subject_id="op-b", tenant_id=TENANT_B)
    svc.register_operator(op_b)
    reader_b = PortfolioPrincipal(subject_id="reader-b", tenant_id=TENANT_B)
    svc.grant_access(
        op_b,
        PortfolioAccessGrant(
            grant_id="g-b-read",
            tenant_id=TENANT_B,
            subject_id="reader-b",
            matter_id="*",
            capabilities=(CAP_READ_REVIEW, CAP_LIST_PORTFOLIO, CAP_SEARCH),
        ),
    )
    listed_b = svc.list_portfolio(reader_b)
    assert listed_b.authorized is True
    assert listed_b.total_count == 0
    assert listed_b.matter_ids == ()


def test_forbidden_capabilities_blocked() -> None:
    svc = _svc()
    for cap in (
        "scrape_authenticated_patent_center",
        "enumerate_patent_center_account",
        "existence_oracle",
        "count_oracle",
        "timing_oracle",
        "search_oracle",
        "cross_tenant_portfolio_search",
    ):
        assert cap in FORBIDDEN_PORTFOLIO_CAPABILITIES
        with pytest.raises(PortfolioCapabilityError):
            svc.assert_capability_allowed(cap)


def test_private_classification_not_downgraded_across_tenants() -> None:
    """Even when comparing denials, private substance never appears."""
    svc = _svc()
    _, reviewer_a = _setup_tenant_with_secret(svc)
    authorized = svc.get_review(reviewer_a, matter_id=MATTER_SECRET)
    assert authorized.projection is not None
    assert (
        authorized.projection.classification
        is DisclosureClassification.CONFIDENTIAL_APPLICATION
    )

    eve = PortfolioPrincipal(subject_id="eve", tenant_id=TENANT_B)
    denied = svc.get_review(eve, matter_id=MATTER_SECRET)
    # Denial carries neither classification nor private text.
    d = denied.to_dict()
    assert d["projection"] is None
    assert PRIVATE_CANARY not in canonical_blob(d)


def test_rejection_ingest_by_unauthorized_is_denied() -> None:
    svc = _svc()
    _setup_tenant_with_secret(svc)
    eve = PortfolioPrincipal(subject_id="eve", tenant_id=TENANT_B)
    denied = svc.ingest_rejection_event(
        eve,
        matter_id=MATTER_SECRET,
        event_id="rej-evil",
        disposition=RejectionDisposition.FINAL,
        claim_numbers=("1",),
        private=True,
    )
    assert denied.authorized is False
    assert denied.code == ACCESS_DENIED_CODE


def test_delayed_gap_does_not_leak_via_unauthorized_read() -> None:
    svc = _svc()
    _, reviewer_a = _setup_tenant_with_secret(svc)
    svc.record_delayed_or_absent(
        reviewer_a,
        matter_id=MATTER_SECRET,
        gap_id="gap-secret-delayed",
        code="delayed_publication",
        presence=FactPresence.DELAYED,
        message=f"delayed secret gap {PRIVATE_CANARY}",
    )
    eve = PortfolioPrincipal(subject_id="eve", tenant_id=TENANT_B)
    denied = svc.get_review(eve, matter_id=MATTER_SECRET)
    assert denied.authorized is False
    assert PRIVATE_CANARY not in canonical_blob(denied.to_dict())
