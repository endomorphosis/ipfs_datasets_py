"""Unit tests for versioned baseline filing-obligation packs (PATLAW-137).

Acceptance:
  - Rules identify jurisdiction, application type, scenario,
    applicability/effective interval, required evidence, exceptions,
    citations, reviewer/version, and tests
  - Provisional, PCT national-stage, reissue, continuation, divisional, and
    CIP cases have an explicit reviewed profile or return out-of-scope/unknown
  - Unsupported scenarios return coverage gaps
  - A pack cannot become active until source digests and human approval are
    recorded
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.filing_rule_packs import (
    BASELINE_PACK_ID,
    BASELINE_PACK_VERSION,
    SPECIAL_APPLICATION_TYPES,
    SUPPORTED_BASELINE_APPLICATION_TYPES,
    ActivationBlockReason,
    ApplicationType,
    ApplicationTypeProfile,
    EffectiveInterval,
    EntityStatus,
    EvidenceKind,
    FILING_RULE_PACKS_SCHEMA_VERSION,
    FilingObligationPack,
    FilingObligationRule,
    FilingScenario,
    HumanApprovalRecord,
    Jurisdiction,
    LegalRegime,
    PackActivationError,
    PackStatus,
    ProfileCoverage,
    ProsecutionStage,
    RequiredEvidence,
    RuleCitation,
    RuleException,
    RuleTestCase,
    SourceDigestRecord,
    activate_pack,
    load_baseline_rules,
    resolve_baseline_fixture_path,
    rules_for_application_type,
    with_human_approval,
    with_source_digests,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.filing_obligation_processor import (
    FILING_OBLIGATION_SCHEMA_VERSION,
    CoverageGapKind,
    FilingObligationProcessor,
    FilingObligationRequest,
    FilingObligationResult,
    ObligationResolutionStatus,
    match_rules,
    resolve_filing_obligations,
)

# ---------------------------------------------------------------------------
# Paths / helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[6]
_FIXTURE_PATH = (
    _REPO_ROOT / "tests/fixtures/uspto/filing_rules/baseline_rules.json"
)

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64


def _id_factory():
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"fob:test:{counter['n']:04d}"

    return _ids


def _minimal_rule(
    *,
    rule_id: str = "rule:test:1",
    application_type: str = "utility",
    scenario: str = "new_application",
    version: str = "1.0.0",
) -> FilingObligationRule:
    return FilingObligationRule(
        rule_id=rule_id,
        version=version,
        jurisdiction=Jurisdiction.US_USPTO,
        application_type=application_type,
        scenario=scenario,
        title="Test rule",
        description="Minimal rule for unit tests",
        effective_interval=EffectiveInterval.open_ended("2013-03-16"),
        required_evidence=(
            RequiredEvidence(
                evidence_kind=EvidenceKind.SPECIFICATION,
                description="Spec present",
                mandatory=True,
            ),
        ),
        exceptions=(
            RuleException(
                exception_id="exc:test:1",
                description="Test exception",
                condition="never",
                authority_citation="37 C.F.R. 1.51",
            ),
        ),
        citations=(
            RuleCitation(citation="37 C.F.R. 1.51", citation_kind="regulation"),
        ),
        reviewer_id="reviewer:test",
        reviewed_at="2026-01-01T00:00:00Z",
        tests=(
            RuleTestCase(
                test_id="test:rule:test:1",
                description="minimal rule applies",
                expect_applicable=True,
                expect_coverage="matched",
            ),
        ),
        legal_regime=LegalRegime.ANY,
        entity_status=EntityStatus.ANY,
        prosecution_stage=ProsecutionStage.ANY,
    )


def _special_profiles(version: str = "1.0.0") -> tuple[ApplicationTypeProfile, ...]:
    """Explicit profiles for all special application types + utility."""
    profiles = [
        ApplicationTypeProfile(
            application_type=ApplicationType.UTILITY,
            coverage=ProfileCoverage.SUPPORTED,
            pack_version=version,
            reviewer_id="reviewer:test",
            reviewed_at="2026-01-01T00:00:00Z",
            scenarios_in_scope=("new_application", "office_action_response"),
        ),
        ApplicationTypeProfile(
            application_type=ApplicationType.DESIGN,
            coverage=ProfileCoverage.SUPPORTED,
            pack_version=version,
            reviewer_id="reviewer:test",
            reviewed_at="2026-01-01T00:00:00Z",
            scenarios_in_scope=("new_application",),
        ),
        ApplicationTypeProfile(
            application_type=ApplicationType.PLANT,
            coverage=ProfileCoverage.SUPPORTED,
            pack_version=version,
            reviewer_id="reviewer:test",
            reviewed_at="2026-01-01T00:00:00Z",
            scenarios_in_scope=("new_application",),
        ),
    ]
    for special in sorted(SPECIAL_APPLICATION_TYPES):
        coverage = (
            ProfileCoverage.OUT_OF_SCOPE
            if special in ("provisional", "pct_national_stage", "reissue")
            else ProfileCoverage.UNKNOWN
        )
        profiles.append(
            ApplicationTypeProfile(
                application_type=special,
                coverage=coverage,
                pack_version=version,
                reviewer_id="reviewer:test",
                reviewed_at="2026-01-01T00:00:00Z",
                notes=f"Explicit {coverage.value} profile for {special}",
            )
        )
    return tuple(profiles)


def _draft_pack(
    *,
    with_digests: bool = False,
    with_approval: bool = False,
    rules: tuple[FilingObligationRule, ...] | None = None,
    status: PackStatus = PackStatus.DRAFT,
) -> FilingObligationPack:
    digests: tuple[SourceDigestRecord, ...] = ()
    if with_digests:
        digests = (
            SourceDigestRecord(
                source_id="src:test",
                source_digest=_DIGEST_A,
                authority_citation="37 C.F.R. 1.51",
            ),
        )
    approval = None
    if with_approval:
        approval = HumanApprovalRecord(
            reviewer_id="reviewer:test",
            approved_at="2026-01-02T00:00:00Z",
            pack_version="1.0.0",
            approval_digest=_DIGEST_B,
            review_state=ReviewState.COMPLETE,
        )
    return FilingObligationPack(
        pack_id="uspto.test-pack",
        version="1.0.0",
        status=status,
        jurisdiction=Jurisdiction.US_USPTO,
        title="Test pack",
        rules=rules if rules is not None else (_minimal_rule(),),
        profiles=_special_profiles(),
        source_digests=digests,
        human_approval=approval,
        effective_interval=EffectiveInterval.open_ended(),
    )


def _activatable_pack() -> FilingObligationPack:
    draft = _draft_pack(with_digests=True, with_approval=True, status=PackStatus.REVIEWED)
    return activate_pack(draft)


# ---------------------------------------------------------------------------
# Rule field completeness (acceptance field list)
# ---------------------------------------------------------------------------


def test_rule_identifies_all_acceptance_fields() -> None:
    rule = _minimal_rule()
    d = rule.to_dict()
    # Required acceptance fields
    assert d["jurisdiction"] == "us_uspto"
    assert d["application_type"] == "utility"
    assert d["scenario"] == "new_application"
    assert "effective_interval" in d
    assert d["effective_interval"]["effective_from"] == "2013-03-16"
    assert d["required_evidence"]
    assert d["exceptions"]
    assert d["citations"]
    assert d["reviewer_id"]
    assert d["version"]
    assert d["tests"]
    # Round-trip
    restored = FilingObligationRule.from_dict(d)
    assert restored.to_dict() == d


def test_rule_rejects_missing_citations_or_tests() -> None:
    with pytest.raises(ValueError, match="citation"):
        FilingObligationRule(
            rule_id="rule:bad:cite",
            version="1.0.0",
            jurisdiction=Jurisdiction.US_USPTO,
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.NEW_APPLICATION,
            title="Bad",
            description="Missing citations",
            effective_interval=EffectiveInterval.open_ended(),
            required_evidence=(),
            exceptions=(),
            citations=(),
            reviewer_id="reviewer:x",
            reviewed_at="2026-01-01T00:00:00Z",
            tests=(
                RuleTestCase(
                    test_id="test:bad",
                    description="x",
                ),
            ),
        )
    with pytest.raises(ValueError, match="test"):
        FilingObligationRule(
            rule_id="rule:bad:test",
            version="1.0.0",
            jurisdiction=Jurisdiction.US_USPTO,
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.NEW_APPLICATION,
            title="Bad",
            description="Missing tests",
            effective_interval=EffectiveInterval.open_ended(),
            required_evidence=(),
            exceptions=(),
            citations=(RuleCitation(citation="37 C.F.R. 1.51"),),
            reviewer_id="reviewer:x",
            reviewed_at="2026-01-01T00:00:00Z",
            tests=(),
        )


def test_effective_interval_contains() -> None:
    interval = EffectiveInterval(
        effective_from="2022-07-01", effective_to="2025-12-31"
    )
    assert interval.contains("2022-07-01") is True
    assert interval.contains("2023-01-01") is True
    assert interval.contains("2025-12-31") is True
    assert interval.contains("2022-06-30") is False
    assert interval.contains("2026-01-01") is False


# ---------------------------------------------------------------------------
# Pack activation gates
# ---------------------------------------------------------------------------


def test_pack_cannot_activate_without_source_digests() -> None:
    pack = _draft_pack(with_digests=False, with_approval=True)
    blocks = pack.activation_block_reasons()
    assert ActivationBlockReason.MISSING_SOURCE_DIGESTS.value in blocks
    assert pack.can_activate() is False
    with pytest.raises(PackActivationError) as excinfo:
        activate_pack(pack)
    assert ActivationBlockReason.MISSING_SOURCE_DIGESTS.value in excinfo.value.block_reasons


def test_pack_cannot_activate_without_human_approval() -> None:
    pack = _draft_pack(with_digests=True, with_approval=False)
    blocks = pack.activation_block_reasons()
    assert ActivationBlockReason.MISSING_HUMAN_APPROVAL.value in blocks
    with pytest.raises(PackActivationError) as excinfo:
        activate_pack(pack)
    assert ActivationBlockReason.MISSING_HUMAN_APPROVAL.value in excinfo.value.block_reasons


def test_pack_cannot_activate_without_rules() -> None:
    pack = _draft_pack(
        with_digests=True, with_approval=True, rules=()
    )
    assert ActivationBlockReason.EMPTY_RULES.value in pack.activation_block_reasons()
    with pytest.raises(PackActivationError):
        activate_pack(pack)


def test_pack_cannot_activate_without_special_profiles() -> None:
    pack = FilingObligationPack(
        pack_id="uspto.missing-profiles",
        version="1.0.0",
        status=PackStatus.REVIEWED,
        jurisdiction=Jurisdiction.US_USPTO,
        title="Missing specials",
        rules=(_minimal_rule(),),
        profiles=(
            ApplicationTypeProfile(
                application_type=ApplicationType.UTILITY,
                coverage=ProfileCoverage.SUPPORTED,
                pack_version="1.0.0",
            ),
        ),
        source_digests=(
            SourceDigestRecord(source_id="src:x", source_digest=_DIGEST_A),
        ),
        human_approval=HumanApprovalRecord(
            reviewer_id="reviewer:x",
            approved_at="2026-01-01T00:00:00Z",
            pack_version="1.0.0",
        ),
        effective_interval=EffectiveInterval.open_ended(),
    )
    assert ActivationBlockReason.MISSING_SPECIAL_PROFILES.value in (
        pack.activation_block_reasons()
    )
    gaps = pack.special_profile_gaps()
    assert set(gaps) == set(SPECIAL_APPLICATION_TYPES)


def test_activate_pack_succeeds_when_gates_pass() -> None:
    pack = _draft_pack(
        with_digests=True, with_approval=True, status=PackStatus.REVIEWED
    )
    assert pack.can_activate() is True
    active = activate_pack(pack)
    assert active.status is PackStatus.ACTIVE
    assert active.has_source_digests() is True
    assert active.has_human_approval() is True


def test_constructing_active_pack_without_gates_raises() -> None:
    with pytest.raises(PackActivationError):
        FilingObligationPack(
            pack_id="uspto.bad-active",
            version="1.0.0",
            status=PackStatus.ACTIVE,
            jurisdiction=Jurisdiction.US_USPTO,
            title="Bad active",
            rules=(_minimal_rule(),),
            profiles=_special_profiles(),
            source_digests=(),
            human_approval=None,
            effective_interval=EffectiveInterval.open_ended(),
        )


def test_with_source_digests_and_approval_helpers() -> None:
    pack = _draft_pack()
    pack = with_source_digests(
        pack,
        [
            {
                "source_id": "src:helper",
                "source_digest": _DIGEST_A,
            }
        ],
    )
    assert pack.has_source_digests() is True
    pack = with_human_approval(
        pack,
        {
            "reviewer_id": "reviewer:helper",
            "approved_at": "2026-02-01T00:00:00Z",
            "pack_version": "1.0.0",
            "review_state": "complete",
        },
    )
    assert pack.has_human_approval() is True
    assert pack.status is PackStatus.REVIEWED
    active = activate_pack(pack)
    assert active.status is PackStatus.ACTIVE


# ---------------------------------------------------------------------------
# Baseline fixture
# ---------------------------------------------------------------------------


def test_baseline_fixture_exists_and_loads() -> None:
    path = resolve_baseline_fixture_path(_FIXTURE_PATH)
    assert path.is_file()
    pack = load_baseline_rules(path)
    assert pack.pack_id == BASELINE_PACK_ID
    assert pack.version == BASELINE_PACK_VERSION
    assert pack.schema_version == FILING_RULE_PACKS_SCHEMA_VERSION
    assert pack.status is PackStatus.ACTIVE
    assert pack.has_source_digests() is True
    assert pack.has_human_approval() is True
    assert pack.can_activate() is True  # already active; no blocks
    assert not pack.activation_block_reasons()


def test_baseline_rules_have_acceptance_fields() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    assert pack.rules
    for rule in pack.rules:
        d = rule.to_dict()
        assert d["jurisdiction"]
        assert d["application_type"]
        assert d["scenario"]
        assert d["effective_interval"] is not None
        assert d["required_evidence"] is not None
        assert d["exceptions"] is not None
        assert d["citations"]
        assert d["reviewer_id"]
        assert d["version"]
        assert d["tests"]


def test_baseline_covers_utility_design_plant() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    apps = {
        r.application_type.value
        if isinstance(r.application_type, ApplicationType)
        else str(r.application_type)
        for r in pack.rules
    }
    assert SUPPORTED_BASELINE_APPLICATION_TYPES <= apps
    for app in ("utility", "design", "plant"):
        assert rules_for_application_type(pack, app)
    # Design cites 1.151-1.155 family
    design_rules = rules_for_application_type(pack, ApplicationType.DESIGN)
    design_cites = {
        c.citation for r in design_rules for c in r.citations
    }
    assert any("1.151" in c for c in design_cites)
    plant_rules = rules_for_application_type(pack, ApplicationType.PLANT)
    plant_cites = {c.citation for r in plant_rules for c in r.citations}
    assert any("1.161" in c for c in plant_cites)


def test_baseline_special_profiles_explicit() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    assert not pack.special_profile_gaps()
    for special in SPECIAL_APPLICATION_TYPES:
        profile = pack.profile_for(special)
        assert profile is not None, f"missing profile for {special}"
        assert profile.coverage in (
            ProfileCoverage.SUPPORTED,
            ProfileCoverage.OUT_OF_SCOPE,
            ProfileCoverage.UNKNOWN,
        )


def test_baseline_pack_round_trip() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    data = pack.to_dict()
    restored = FilingObligationPack.from_dict(data)
    assert restored.content_digest() == pack.content_digest()
    assert canonical_json(restored.to_dict()) == canonical_json(data)


# ---------------------------------------------------------------------------
# Special application types → out_of_scope / unknown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "app_type,expected_status",
    [
        (ApplicationType.PROVISIONAL, ObligationResolutionStatus.OUT_OF_SCOPE),
        (ApplicationType.PCT_NATIONAL_STAGE, ObligationResolutionStatus.OUT_OF_SCOPE),
        (ApplicationType.REISSUE, ObligationResolutionStatus.OUT_OF_SCOPE),
        (ApplicationType.CONTINUATION, ObligationResolutionStatus.UNKNOWN),
        (ApplicationType.DIVISIONAL, ObligationResolutionStatus.UNKNOWN),
        (ApplicationType.CIP, ObligationResolutionStatus.UNKNOWN),
    ],
)
def test_special_application_types_explicit_disposition(
    app_type: ApplicationType,
    expected_status: ObligationResolutionStatus,
) -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id=f"req:{app_type.value}",
            application_type=app_type,
            scenario=FilingScenario.NEW_APPLICATION,
            filing_date="2024-06-01",
            pack=pack,
        ),
        id_factory=_id_factory(),
    )
    assert result.status is expected_status
    assert result.matched_obligations == ()
    assert result.has_coverage_gaps is True
    # Never silently match utility rules for special types.
    assert not any(
        m.rule.application_type is ApplicationType.UTILITY
        for m in result.matched_obligations
    )
    assert "no_silent_utility_reuse" in result.reason_codes or (
        result.profile is not None
    )


def test_special_type_without_profile_is_unknown_not_utility() -> None:
    """If a special type profile is stripped, return unknown — never utility."""
    base = _activatable_pack()
    # Drop provisional profile only.
    profiles = tuple(
        p
        for p in base.profiles
        if p.application_type is not ApplicationType.PROVISIONAL
    )
    # Re-build as reviewed then activate is blocked by missing special profile.
    incomplete = FilingObligationPack(
        pack_id=base.pack_id,
        version=base.version,
        status=PackStatus.REVIEWED,
        jurisdiction=base.jurisdiction,
        title=base.title,
        rules=base.rules,
        profiles=profiles,
        source_digests=base.source_digests,
        human_approval=base.human_approval,
        effective_interval=base.effective_interval,
    )
    assert incomplete.can_activate() is False
    # Force-match path: craft active-like processing by requiring_active_pack=False
    # still returns unknown for missing special profile (not utility match).
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:prov-missing",
            application_type=ApplicationType.PROVISIONAL,
            scenario=FilingScenario.NEW_APPLICATION,
            filing_date="2024-01-01",
            pack=incomplete,
        ),
        require_active_pack=False,
        id_factory=_id_factory(),
    )
    assert result.status is ObligationResolutionStatus.UNKNOWN
    assert any(
        g.kind is CoverageGapKind.MISSING_SPECIAL_PROFILE for g in result.coverage_gaps
    )
    assert result.matched_rule_ids == ()


# ---------------------------------------------------------------------------
# Supported scenarios + coverage gaps
# ---------------------------------------------------------------------------


def test_utility_new_application_matches_baseline() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:utility-new",
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.NEW_APPLICATION,
            filing_date="2024-06-01",
            as_of="2024-06-01",
            legal_regime=LegalRegime.AIA,
            entity_status=EntityStatus.UNDISCOUNTED,
            prosecution_stage=ProsecutionStage.FILING,
            pack=pack,
        ),
        id_factory=_id_factory(),
    )
    assert result.status is ObligationResolutionStatus.MATCHED
    assert result.is_review_only is True
    assert result.is_legal_advice is False
    assert result.is_exhaustive is False
    assert len(result.matched_obligations) >= 5
    ids = set(result.matched_rule_ids)
    assert "rule:utility:new:specification" in ids
    assert "rule:utility:new:claims" in ids
    assert "rule:utility:new:fees" in ids
    assert result.schema_version == FILING_OBLIGATION_SCHEMA_VERSION


def test_utility_oa_response_matches() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:utility-oa",
            application_type="utility",
            scenario="office_action_response",
            filing_date="2023-01-01",
            as_of="2024-08-01",
            prosecution_stage=ProsecutionStage.EXAMINATION,
            pack=pack,
        ),
        id_factory=_id_factory(),
    )
    assert result.status is ObligationResolutionStatus.MATCHED
    assert "rule:utility:oa-response:claim-amendment" in result.matched_rule_ids
    assert "rule:utility:oa-response:signature" in result.matched_rule_ids


def test_design_and_plant_new_application() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    for app, rule_prefix in (
        (ApplicationType.DESIGN, "rule:design:"),
        (ApplicationType.PLANT, "rule:plant:"),
    ):
        result = resolve_filing_obligations(
            FilingObligationRequest(
                request_id=f"req:{app.value}",
                application_type=app,
                scenario=FilingScenario.NEW_APPLICATION,
                filing_date="2024-01-15",
                pack=pack,
            ),
            id_factory=_id_factory(),
        )
        assert result.status is ObligationResolutionStatus.MATCHED, app
        assert any(rid.startswith(rule_prefix) for rid in result.matched_rule_ids)


def test_unsupported_scenario_returns_coverage_gap() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    # issue_fee is not in utility scenarios_in_scope
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:utility-issue-fee",
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.ISSUE_FEE,
            filing_date="2024-01-01",
            pack=pack,
        ),
        id_factory=_id_factory(),
    )
    assert result.status is ObligationResolutionStatus.COVERAGE_GAP
    assert result.has_coverage_gaps is True
    assert any(
        g.kind is CoverageGapKind.UNSUPPORTED_SCENARIO for g in result.coverage_gaps
    )
    assert result.matched_obligations == ()


def test_no_matching_rules_coverage_gap() -> None:
    """Supported profile but no rule for the key combination → coverage gap."""
    pack = _activatable_pack()  # only new_application utility rule
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:utility-oa-empty",
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.OFFICE_ACTION_RESPONSE,
            filing_date="2024-01-01",
            prosecution_stage=ProsecutionStage.EXAMINATION,
            pack=pack,
        ),
        id_factory=_id_factory(),
    )
    # office_action_response is in scenarios_in_scope but no rule matches
    assert result.status is ObligationResolutionStatus.COVERAGE_GAP
    assert any(
        g.kind is CoverageGapKind.NO_MATCHING_RULES for g in result.coverage_gaps
    )


def test_inactive_pack_blocks_matching() -> None:
    pack = _draft_pack(with_digests=True, with_approval=True, status=PackStatus.REVIEWED)
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:inactive",
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.NEW_APPLICATION,
            filing_date="2024-01-01",
            pack=pack,
        ),
        id_factory=_id_factory(),
        require_active_pack=True,
    )
    assert result.status is ObligationResolutionStatus.PACK_NOT_ACTIVE
    assert result.matched_obligations == ()
    assert any(g.kind is CoverageGapKind.PACK_NOT_ACTIVE for g in result.coverage_gaps)


def test_sequence_listing_interval_miss_for_early_filing() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    # Sequence rule effective_from 2022-07-01 — earlier as_of should not match it
    # but other utility rules still match.
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:pre-st26",
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.NEW_APPLICATION,
            filing_date="2020-01-01",
            as_of="2020-01-01",
            pack=pack,
        ),
        id_factory=_id_factory(),
    )
    assert result.status is ObligationResolutionStatus.MATCHED
    assert "rule:utility:new:sequence-listing" not in result.matched_rule_ids
    assert "rule:utility:new:specification" in result.matched_rule_ids


# ---------------------------------------------------------------------------
# Processor class + determinism
# ---------------------------------------------------------------------------


def test_processor_loads_baseline_and_resolves() -> None:
    proc = FilingObligationProcessor(
        baseline_path=_FIXTURE_PATH, id_factory=_id_factory()
    )
    assert proc.pack is not None
    assert proc.pack.status is PackStatus.ACTIVE
    result = proc.resolve(
        request_id="req:proc",
        application_type="utility",
        scenario="new_application",
        filing_date="2024-03-01",
    )
    assert result.status is ObligationResolutionStatus.MATCHED
    assert result.is_review_only is True


def test_result_round_trip_and_public_projection() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:rt",
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.NEW_APPLICATION,
            filing_date="2024-01-01",
            pack=pack,
        ),
        id_factory=_id_factory(),
    )
    data = result.to_dict()
    restored = FilingObligationResult.from_dict(data)
    assert restored.to_dict() == data
    public = result.public_projection()
    assert public["is_review_only"] is True
    assert public["is_legal_advice"] is False
    assert public["is_exhaustive"] is False
    assert "matched_obligations" not in public
    assert public["matched_count"] == len(result.matched_obligations)


def test_match_rules_deterministic_order() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    req = FilingObligationRequest(
        request_id="req:det",
        application_type=ApplicationType.UTILITY,
        scenario=FilingScenario.NEW_APPLICATION,
        filing_date="2024-01-01",
        pack=pack,
    )
    a = match_rules(pack, req)
    b = match_rules(pack, req)
    assert [r.rule_id for r in a] == [r.rule_id for r in b]
    # Sorted by rule_id in pack; matches preserve pack order.
    assert [r.rule_id for r in a] == sorted(r.rule_id for r in a)


def test_result_rejects_legal_advice_or_exhaustive_flags() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    base = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:flags",
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.NEW_APPLICATION,
            filing_date="2024-01-01",
            pack=pack,
        ),
        id_factory=_id_factory(),
    )
    d = base.to_dict()
    d["is_legal_advice"] = True
    with pytest.raises(ValueError, match="legal_advice"):
        FilingObligationResult.from_dict(d)
    d = base.to_dict()
    d["is_exhaustive"] = True
    with pytest.raises(ValueError, match="exhaustive"):
        FilingObligationResult.from_dict(d)


def test_fixture_json_is_valid_and_compact() -> None:
    raw = _FIXTURE_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "pack" in data
    # Compact recipe style — single pack object, not bulk golden dumps.
    assert isinstance(data["pack"]["rules"], list)
    assert len(data["pack"]["rules"]) >= 10
    assert len(data["pack"]["profiles"]) >= 9
    # Clone and strip approval → cannot load as active
    stripped = copy.deepcopy(data)
    stripped["pack"]["human_approval"] = None
    stripped["pack"]["status"] = "draft"
    pack = FilingObligationPack.from_dict(stripped["pack"])
    assert pack.can_activate() is False


def test_reason_codes_include_safety_markers() -> None:
    pack = load_baseline_rules(_FIXTURE_PATH)
    result = resolve_filing_obligations(
        FilingObligationRequest(
            request_id="req:safety",
            application_type=ApplicationType.UTILITY,
            scenario=FilingScenario.NEW_APPLICATION,
            filing_date="2024-01-01",
            pack=pack,
        ),
        id_factory=_id_factory(),
    )
    for code in (
        "review_only",
        "not_legal_advice",
        "not_exhaustive",
        "form_instructions_not_controlling",
    ):
        assert code in result.reason_codes
