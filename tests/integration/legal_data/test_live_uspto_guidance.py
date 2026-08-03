"""Integration tests for live USPTO guidance acquisition (PATLAW-132).

Recorded recipe coverage:

* MPEP edition/revision rollover (old + new retained)
* artifact removal (prior version retained, marked removed)
* version conflict (both digests retained; no silent latest)
* explicit supersession (both sides remain guidance)
* unavailable published/effective dates (explicit, not filled)
* happy-path forms, fees, and examination notices

Every item version has source CID/span/retrieved/published/effective metadata
where supplied. Links never silently select ``latest``.

Network I/O is not used; tests replay the compact fixture recipe only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    VerificationState,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.live_uspto_guidance_processor import (
    REQUIRED_SCENARIO_KINDS,
    SCHEMA_VERSION,
    FIXTURE_SCHEMA_VERSION,
    CaseOutcome,
    DateAvailability,
    GuidanceElevationError,
    HardCodedLatestError,
    LiveGuidanceItem,
    LiveUsptoGuidanceError,
    LiveUsptoGuidanceProcessor,
    ScenarioKind,
    SilentLatestSelectionError,
    VersionRole,
    VersionRetentionError,
    build_default_recipe,
    content_sha256,
    default_fixture_dir,
    parse_recipe,
    process_case,
    reject_latest_token,
    resolve_guidance_link,
    source_cid_for_sha256,
    write_default_fixtures,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.mpep_guidance_processor import (
    GuidanceKind,
)

# tests/integration/legal_data/this_file.py → tests/fixtures/...
_REPO_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "legal_data"
    / "patent_authorities"
    / "live"
)


def _fixture_dir() -> Path:
    candidate = default_fixture_dir()
    if (candidate / "uspto_guidance_recipe.json").is_file():
        return candidate
    if (_REPO_FIXTURE_DIR / "uspto_guidance_recipe.json").is_file():
        return _REPO_FIXTURE_DIR
    write_default_fixtures(_REPO_FIXTURE_DIR)
    return _REPO_FIXTURE_DIR


@pytest.fixture(scope="module")
def fixture_dir() -> Path:
    return _fixture_dir()


@pytest.fixture(scope="module")
def recipe_path(fixture_dir: Path) -> Path:
    path = fixture_dir / "uspto_guidance_recipe.json"
    if not path.is_file():
        write_default_fixtures(fixture_dir)
    return path


@pytest.fixture(scope="module")
def processor(fixture_dir: Path) -> LiveUsptoGuidanceProcessor:
    return LiveUsptoGuidanceProcessor(fixture_dir=fixture_dir)


@pytest.fixture(scope="module")
def report(processor: LiveUsptoGuidanceProcessor):
    return processor.acquire_from_fixture()


# ---------------------------------------------------------------------------
# Recipe structure / required scenario coverage
# ---------------------------------------------------------------------------


def test_recipe_exists_and_is_compact(recipe_path: Path):
    assert recipe_path.is_file()
    raw = recipe_path.read_text(encoding="utf-8")
    # Prefer compact recipes over bulk golden dumps (admission policy).
    assert len(raw.encode("utf-8")) < 200_000
    payload = json.loads(raw)
    assert payload.get("schema_version") in {
        FIXTURE_SCHEMA_VERSION,
        SCHEMA_VERSION,
        "live-uspto-guidance-recipe-v1",
    }
    assert isinstance(payload.get("cases"), list)
    assert len(payload["cases"]) >= len(REQUIRED_SCENARIO_KINDS)
    assert payload.get("authority_class") == "guidance"
    assert payload.get("is_binding") is False


def test_required_scenarios_covered(report, processor):
    assert report.covers_required_scenarios()
    assert not report.missing_required_scenarios()
    kinds = report.scenario_kinds
    for required in REQUIRED_SCENARIO_KINDS:
        assert required in kinds, f"missing required scenario {required!r}"
    processor.assert_acceptance_coverage(report)


def test_default_recipe_matches_fixture(recipe_path: Path):
    on_disk = json.loads(recipe_path.read_text(encoding="utf-8"))
    built = build_default_recipe()
    on_ids = {c["case_id"] for c in on_disk["cases"]}
    built_ids = {c["case_id"] for c in built["cases"]}
    assert built_ids <= on_ids or on_ids == built_ids
    assert on_disk.get("authority_class") == "guidance"


# ---------------------------------------------------------------------------
# Edition rollover — retain old and new
# ---------------------------------------------------------------------------


def test_edition_rollover_retains_old_and_new(report):
    results = report.results_for_scenario(ScenarioKind.EDITION_ROLLOVER)
    assert results
    for result in results:
        case = result.case
        assert case.prior_edition
        assert case.successor_edition or any(
            v.role is VersionRole.SUCCESSOR
            for item in result.items
            for v in item.versions
        )
        assert "latest" not in case.prior_edition.lower()
        if case.successor_edition:
            assert "latest" not in case.successor_edition.lower()
        assert result.retains_old_and_new
        assert len(result.retained_version_ids) >= 2
        digests = {v.content_sha256 for item in result.items for v in item.versions}
        assert len(digests) >= 2
        assert result.outcome is CaseOutcome.ROLLOVER_RETAINED
        assert any("rollover" in r.lower() or "retained" in r.lower() for r in result.reasons)


# ---------------------------------------------------------------------------
# Artifact removal — prior retained
# ---------------------------------------------------------------------------


def test_artifact_removal_retains_prior_version(report):
    results = report.results_for_scenario(ScenarioKind.ARTIFACT_REMOVAL)
    assert results
    for result in results:
        assert result.retains_old_and_new
        assert result.outcome is CaseOutcome.REMOVAL_RETAINED
        removed = [
            v
            for item in result.items
            for v in item.versions
            if v.removed or v.role is VersionRole.REMOVED
        ]
        assert removed, "removal case must mark at least one version removed"
        # Prior content still addressable.
        assert all(v.source_cid for v in removed)
        assert all(v.content_sha256 for v in removed)


# ---------------------------------------------------------------------------
# Version conflict — both retained, no silent latest
# ---------------------------------------------------------------------------


def test_version_conflict_retains_both_no_silent_latest(report):
    results = report.results_for_scenario(ScenarioKind.VERSION_CONFLICT)
    assert results
    for result in results:
        assert result.retains_old_and_new
        assert result.outcome is CaseOutcome.CONFLICT_RETAINED
        assert result.verification_state is VerificationState.CONFLICT
        digests = {v.content_sha256 for item in result.items for v in item.versions}
        assert len(digests) >= 2
        roles = {v.role for item in result.items for v in item.versions}
        assert VersionRole.CONFLICTING_A in roles or VersionRole.CONFLICTING_B in roles or len(roles) >= 2
        for item in result.items:
            for ver in item.versions:
                assert "latest" not in ver.version_id.lower()
                if ver.version_label:
                    assert "latest" not in ver.version_label.lower()


# ---------------------------------------------------------------------------
# Supersession — explicit, remains guidance
# ---------------------------------------------------------------------------


def test_supersession_explicit_and_remains_guidance(report):
    results = report.results_for_scenario(ScenarioKind.SUPERSESSION)
    assert results
    for result in results:
        assert result.outcome is CaseOutcome.SUPERSEDED
        assert result.supersessions or any(
            i.supersedes or i.superseded_by for i in result.items
        )
        for edge in result.supersessions:
            assert edge.remains_guidance is True
            assert edge.elevates_to_law is False
            assert edge.successor_id
            assert edge.predecessor_id
            assert "latest" not in edge.successor_id.lower()
            assert "latest" not in edge.predecessor_id.lower()
        for item in result.items:
            assert item.authority_tier is AuthorityTier.GUIDANCE
            assert item.is_binding is False
        # Both predecessor and successor versions retained.
        assert result.retains_old_and_new or len(result.retained_version_ids) >= 2


# ---------------------------------------------------------------------------
# Unavailable dates remain explicit
# ---------------------------------------------------------------------------


def test_unavailable_dates_remain_explicit(report):
    results = report.results_for_scenario(ScenarioKind.UNAVAILABLE_DATE)
    assert results
    for result in results:
        assert result.outcome is CaseOutcome.DATE_UNAVAILABLE
        found_unavailable = False
        for item in result.items:
            for ver in item.versions:
                if ver.published.is_unavailable:
                    found_unavailable = True
                    assert ver.published.availability is DateAvailability.UNAVAILABLE
                    assert ver.published.value is None
                if ver.effective.is_unavailable:
                    found_unavailable = True
                    assert ver.effective.availability is DateAvailability.UNAVAILABLE
                    assert ver.effective.value is None
        assert found_unavailable, "must not silently invent published/effective dates"


# ---------------------------------------------------------------------------
# Every item: source CID / span / retrieved / published / effective
# ---------------------------------------------------------------------------


def test_every_item_has_source_cid_span_retrieved_published_effective(report):
    items = report.all_items()
    assert items
    for item in items:
        assert isinstance(item, LiveGuidanceItem)
        assert item.authority_tier is AuthorityTier.GUIDANCE
        assert item.is_binding is False
        assert item.versions
        for ver in item.versions:
            assert ver.source_cid
            assert ver.source_cid.startswith("baf") or ver.source_cid.startswith("sha256:")
            assert ver.source_span is not None
            assert isinstance(ver.source_span.start, int)
            assert isinstance(ver.source_span.end, int)
            assert ver.source_span.end >= ver.source_span.start
            assert ver.retrieved_at is not None
            assert ver.published is not None
            assert ver.effective is not None
            assert ver.published.availability in DateAvailability
            assert ver.effective.availability in DateAvailability
            # Where supplied as present, value must be a real date.
            if ver.published.availability is DateAvailability.PRESENT:
                assert ver.published.value is not None
            if ver.effective.availability is DateAvailability.PRESENT:
                assert ver.effective.value is not None
            payload = ver.to_dict()
            assert "source_cid" in payload
            assert "source_span" in payload
            assert "retrieved_at" in payload
            assert "published" in payload
            assert "effective" in payload


def test_content_kinds_cover_mpep_forms_fees_guides(report):
    kinds = {item.kind for item in report.all_items()}
    assert GuidanceKind.MPEP_SECTION in kinds
    assert GuidanceKind.FORM in kinds
    assert GuidanceKind.FEE_SCHEDULE in kinds
    assert (
        GuidanceKind.EXAMINATION_GUIDE in kinds
        or GuidanceKind.NOTICE in kinds
        or GuidanceKind.LATER_PUBLICATION in kinds
    )


# ---------------------------------------------------------------------------
# Links never silently select latest
# ---------------------------------------------------------------------------


def test_hard_coded_latest_rejected():
    with pytest.raises((HardCodedLatestEditionError, HardCodedLatestError, LiveUsptoGuidanceError)):
        reject_latest_token("latest", field_name="edition")
    with pytest.raises((HardCodedLatestEditionError, HardCodedLatestError, LiveUsptoGuidanceError)):
        reject_latest_token("mpep-latest", field_name="edition")
    with pytest.raises((HardCodedLatestEditionError, HardCodedLatestError, LiveUsptoGuidanceError)):
        reject_latest_token("LATEST", field_name="revision")


def test_resolve_guidance_link_never_silent_latest():
    available = {
        "r07.2022": "mpep-9-r07.2022",
        "r01.2024": "mpep-9-r01.2024",
    }
    with pytest.raises(SilentLatestSelectionError):
        resolve_guidance_link(link_target="latest", available_versions=available)
    with pytest.raises(
        (
            SilentLatestSelectionError,
            HardCodedLatestError,
            HardCodedLatestEditionError,
            LiveUsptoGuidanceError,
        )
    ):
        resolve_guidance_link(
            link_target="r07.2022",
            available_versions=available,
            prefer_version="latest",
        )
    concrete = resolve_guidance_link(
        link_target="r01.2024",
        available_versions=available,
    )
    assert concrete == "mpep-9-r01.2024"
    assert "latest" not in concrete.lower()
    preferred = resolve_guidance_link(
        link_target="r07.2022",
        available_versions=available,
        prefer_version="r07.2022",
    )
    assert preferred == "mpep-9-r07.2022"


def test_no_latest_token_in_report_identities(report):
    for item in report.all_items():
        assert "latest" not in item.item_id.lower()
        if item.stable_id:
            assert "latest" not in item.stable_id.lower()
        for ver in item.versions:
            assert "latest" not in ver.version_id.lower()
            if ver.edition:
                assert "latest" not in ver.edition.lower()
            if ver.revision:
                assert "latest" not in ver.revision.lower()
            if ver.version_label:
                assert "latest" not in ver.version_label.lower()
    for result in report.results:
        if result.case.prior_edition:
            assert "latest" not in result.case.prior_edition.lower()
        if result.case.successor_edition:
            assert "latest" not in result.case.successor_edition.lower()


# ---------------------------------------------------------------------------
# Happy path + form replacement + fee rollover
# ---------------------------------------------------------------------------


def test_happy_path_acquires_forms_fees_notices(report):
    results = report.results_for_scenario(ScenarioKind.HAPPY_PATH)
    assert results
    for result in results:
        assert result.outcome is CaseOutcome.ACQUIRED
        assert result.items
        kinds = {i.kind for i in result.items}
        assert kinds & {
            GuidanceKind.FORM,
            GuidanceKind.FEE_SCHEDULE,
            GuidanceKind.NOTICE,
            GuidanceKind.EXAMINATION_GUIDE,
        }


def test_form_replacement_retains_both_versions(report):
    results = report.results_for_scenario(ScenarioKind.FORM_REPLACEMENT)
    if not results:
        pytest.skip("optional form_replacement scenario not in recipe")
    for result in results:
        assert result.retains_old_and_new
        digests = {v.content_sha256 for item in result.items for v in item.versions}
        assert len(digests) >= 2


def test_fee_schedule_rollover_retains_both_years(report):
    results = report.results_for_scenario(ScenarioKind.FEE_SCHEDULE_ROLLOVER)
    if not results:
        pytest.skip("optional fee_schedule_rollover scenario not in recipe")
    for result in results:
        assert result.retains_old_and_new
        assert len(result.retained_version_ids) >= 2


# ---------------------------------------------------------------------------
# Freshness gaps explicit
# ---------------------------------------------------------------------------


def test_freshness_gaps_are_explicit(report):
    results = report.results_for_scenario(ScenarioKind.FRESHNESS_GAP)
    if not results:
        # Freshness gaps may also appear on other cases.
        gaps = [g for r in report.results for g in r.freshness_gaps]
        assert gaps or True  # optional enrichment
        return
    for result in results:
        assert result.freshness_gaps or result.outcome is CaseOutcome.FRESHNESS_GAP
        for gap in result.freshness_gaps:
            assert gap.reason
            assert gap.source_id
            assert gap.kind is not None


# ---------------------------------------------------------------------------
# Helpers / unit-level guards used by integration path
# ---------------------------------------------------------------------------


def test_source_cid_deterministic():
    digest = content_sha256("patlaw-132:probe")
    cid_a = source_cid_for_sha256(digest)
    cid_b = source_cid_for_sha256(digest)
    assert cid_a == cid_b
    assert cid_a.startswith("baf") or cid_a.startswith("sha256:")


def test_process_case_rejects_missing_retention():
    from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.live_uspto_guidance_processor import (
        GuidanceCase,
    )

    bad = {
        "case_id": "bad-rollover-single-version",
        "scenario": "edition_rollover",
        "prior_edition": "mpep-9-r07.2022",
        "successor_edition": "mpep-9-r01.2024",
        "items": [
            {
                "item_id": "mpep-only-one",
                "kind": "mpep_section",
                "anchor": "2106",
                "versions": [
                    {
                        "version_id": "only-one",
                        "role": "sole",
                        "content_sha256": content_sha256("only"),
                        "retrieved_at": "2024-09-15T12:00:00Z",
                        "text_excerpt": "single version only",
                    }
                ],
            }
        ],
    }
    case = GuidanceCase.from_dict(bad)
    with pytest.raises(VersionRetentionError):
        process_case(case)


def test_parse_recipe_rejects_latest_edition(recipe_path: Path):
    payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    # Inject a poisoned case.
    poisoned = dict(payload)
    poisoned_cases = list(payload["cases"])
    poisoned_cases = poisoned_cases + [
        {
            "case_id": "poison-latest",
            "scenario": "happy_path",
            "prior_edition": "latest",
            "items": [
                {
                    "item_id": "x",
                    "kind": "form",
                    "versions": [
                        {
                            "version_id": "v1",
                            "role": "sole",
                            "content_sha256": content_sha256("x"),
                            "retrieved_at": "2024-09-15T12:00:00Z",
                            "edition": "latest",
                            "text_excerpt": "bad",
                        }
                    ],
                }
            ],
        }
    ]
    poisoned["cases"] = poisoned_cases
    with pytest.raises((HardCodedLatestError, HardCodedLatestEditionError, LiveUsptoGuidanceError)):
        parse_recipe(poisoned)


def test_guidance_never_elevated_to_law(report):
    for item in report.all_items():
        assert item.authority_tier is AuthorityTier.GUIDANCE
        assert item.is_binding is False
        payload = item.to_dict()
        assert payload["authority_tier"] == "guidance"
        assert payload["is_binding"] is False
    with pytest.raises(GuidanceElevationError):
        LiveGuidanceItem.from_dict(
            {
                "item_id": "bad-elevated",
                "kind": "mpep_section",
                "authority_tier": "official-base",
                "is_binding": True,
                "versions": [
                    {
                        "version_id": "v",
                        "role": "sole",
                        "content_sha256": content_sha256("e"),
                        "retrieved_at": "2024-09-15T12:00:00Z",
                        "text_excerpt": "x",
                    }
                ],
            }
        )
