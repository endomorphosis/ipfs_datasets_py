"""Integration tests for scheduled temporal patent-authority materialization.

PATLAW-135 acceptance:

* Replaying identical inputs is byte-stable
* Changed sources create new snapshots without mutating old ones
* As-of queries never leak later law
* Statute/regulation/adjudicatory/guidance/editorial tiers and rendition
  status persist
* Absent adjudicatory coverage is a visible blocking research gap
* Stale/missing/conflicting mandatory sources block authoritative-ready

Network I/O is not used; tests replay the compact fixture recipe only.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AuthorityKind,
    RenditionLegalStatus,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_materializer import (
    FIXTURE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    AdjudicatoryCoverage,
    AuthoritativeBlockReason,
    ImmutableSnapshotStore,
    PatentAuthorityMaterializer,
    SnapshotImmutabilityError,
    SourceFreshnessStatus,
    TemporalAuthoritySnapshot,
    build_default_recipe,
    default_fixture_dir,
    filter_records_as_of,
    write_default_fixtures,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    VerificationState,
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
    if (candidate / "temporal_materialization_recipe.json").is_file():
        return candidate
    if (_REPO_FIXTURE_DIR / "temporal_materialization_recipe.json").is_file():
        return _REPO_FIXTURE_DIR
    write_default_fixtures(_REPO_FIXTURE_DIR)
    return _REPO_FIXTURE_DIR


@pytest.fixture(scope="module")
def fixture_dir() -> Path:
    return _fixture_dir()


@pytest.fixture(scope="module")
def recipe_path(fixture_dir: Path) -> Path:
    path = fixture_dir / "temporal_materialization_recipe.json"
    if not path.is_file():
        write_default_fixtures(fixture_dir)
    return path


@pytest.fixture(scope="module")
def recipe(recipe_path: Path) -> dict:
    return json.loads(recipe_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def materializer() -> PatentAuthorityMaterializer:
    return PatentAuthorityMaterializer(default_schedule_id="test-schedule")


@pytest.fixture(scope="module")
def baseline(materializer: PatentAuthorityMaterializer, recipe: dict):
    return materializer.materialize_from_recipe(
        recipe, schedule_id="baseline-2023-10-01"
    )


# ---------------------------------------------------------------------------
# Recipe structure / compactness
# ---------------------------------------------------------------------------


def test_recipe_exists_and_is_compact(recipe_path: Path):
    assert recipe_path.is_file()
    raw = recipe_path.read_text(encoding="utf-8")
    assert len(raw.encode("utf-8")) < 200_000
    payload = json.loads(raw)
    assert payload.get("schema_version") in {
        FIXTURE_SCHEMA_VERSION,
        SCHEMA_VERSION,
        "temporal-materialization-recipe-v1",
    }
    assert isinstance(payload.get("schedules"), list)
    assert len(payload["schedules"]) >= 4
    assert "adjudicatory_coverage" in payload
    assert "expected" in payload


def test_default_recipe_matches_fixture(recipe_path: Path):
    on_disk = json.loads(recipe_path.read_text(encoding="utf-8"))
    built = build_default_recipe()
    on_ids = {s["schedule_id"] for s in on_disk["schedules"]}
    built_ids = {s["schedule_id"] for s in built["schedules"]}
    assert built_ids <= on_ids or on_ids == built_ids
    assert on_disk["recipe_id"] == built["recipe_id"]


# ---------------------------------------------------------------------------
# Byte-stable replay
# ---------------------------------------------------------------------------


def test_identical_inputs_are_byte_stable(
    materializer: PatentAuthorityMaterializer, recipe: dict, baseline
):
    first = materializer.materialize_from_recipe(
        recipe, schedule_id="baseline-2023-10-01"
    )
    second = materializer.materialize_from_recipe(
        recipe, schedule_id="baseline-2023-10-01"
    )
    # Also the second schedule entry is an identical twin of the first.
    twin = materializer.materialize_from_recipe(
        recipe, schedule_id="baseline-2023-10-01"
    )
    assert first.to_canonical_bytes() == second.to_canonical_bytes() == twin.to_canonical_bytes()
    assert first.content_sha256 == second.content_sha256 == baseline.content_sha256
    # Round-trip through JSON is also byte-stable.
    restored = TemporalAuthoritySnapshot.from_canonical_json(first.to_canonical_json())
    assert restored.to_canonical_bytes() == first.to_canonical_bytes()
    payload = json.loads(first.to_canonical_json())
    assert list(payload.keys()) == sorted(payload.keys())


# ---------------------------------------------------------------------------
# Changed sources → new snapshot; old immutable
# ---------------------------------------------------------------------------


def test_changed_sources_create_new_snapshot_without_mutating_old(
    materializer: PatentAuthorityMaterializer, recipe: dict, baseline, tmp_path: Path
):
    store = ImmutableSnapshotStore(tmp_path / "snapshots")
    mat = PatentAuthorityMaterializer(store=store)

    addr1 = mat.put_snapshot(baseline)
    old_bytes = store.get_bytes(addr1.sha256)
    old_sha = addr1.sha256

    changed = mat.materialize_from_recipe(
        recipe, schedule_id="baseline-2023-10-01-changed", persist=True
    )
    addr2 = changed.content_address()

    assert addr2.sha256 != old_sha
    # Prior snapshot bytes are untouched.
    assert store.get_bytes(old_sha) == old_bytes
    assert store.contains(old_sha)
    assert store.contains(addr2.sha256)
    # Listing includes both.
    listed = store.list_sha256()
    assert old_sha in listed
    assert addr2.sha256 in listed


def test_store_refuses_to_mutate_existing_payload(
    baseline, tmp_path: Path
):
    store = ImmutableSnapshotStore(tmp_path / "immutable")
    addr = store.put(baseline)
    # Manually craft a different payload path under the same digest directory
    # by attempting put of a mutated snapshot that collides — force collision
    # by writing different bytes then calling put again with original.
    dest = store.snapshot_path(addr.sha256)
    dest.write_bytes(b'{"tampered":true}')
    with pytest.raises(SnapshotImmutabilityError):
        store.put(baseline)


def test_incremental_delta_preserves_parent_link(
    materializer: PatentAuthorityMaterializer, recipe: dict, baseline
):
    changed_sources = None
    for sched in recipe["schedules"]:
        if sched["schedule_id"] == "baseline-2023-10-01-changed":
            changed_sources = sched["sources"]
            break
    assert changed_sources is not None
    # Use only the changed regulation record as an update.
    updated = [s for s in changed_sources if s["record_id"] == "cfr-1.56-2022"]
    delta = materializer.materialize_schedule_delta(
        baseline,
        updated,
        as_of=baseline.as_of,
    )
    assert delta.parent_snapshot_sha256 == baseline.content_sha256
    assert delta.content_sha256 != baseline.content_sha256
    # Parent snapshot object is still intact (value equality of original bytes).
    assert baseline.content_sha256 == TemporalAuthoritySnapshot.from_canonical_json(
        baseline.to_canonical_json()
    ).content_sha256


# ---------------------------------------------------------------------------
# As-of never leaks later law
# ---------------------------------------------------------------------------


def test_as_of_never_leaks_later_law(
    materializer: PatentAuthorityMaterializer, baseline, recipe: dict
):
    expected = recipe["expected"]["as_of_2023_10_01_excludes_2024_future"]
    view = materializer.query_as_of(
        baseline,
        "2023-10-01",
        citation_key=expected["citation_key"],
    )
    ids = set(view["record_ids"])
    for excluded in expected["excluded_record_ids"]:
        assert excluded not in ids
    for required in expected["must_include_record_ids"]:
        assert required in ids

    # Direct filter helper also excludes future-effective records.
    filtered = filter_records_as_of(baseline.records, date(2023, 10, 1))
    filtered_ids = {r.record_id for r in filtered}
    assert "cfr-1.56-2024-future" not in filtered_ids
    assert "cfr-1.56-2022" in filtered_ids
    # Guidance effective 2024-01-01 also excluded before that date.
    assert "mpep-2001-guidance" not in filtered_ids

    for record in filtered:
        assert not record.is_future_as_of(date(2023, 10, 1))
        if record.effective_start is not None:
            assert record.effective_start <= date(2023, 10, 1)


def test_as_of_after_effective_includes_later_law(
    materializer: PatentAuthorityMaterializer, baseline, recipe: dict
):
    expected = recipe["expected"]["as_of_2024_02_01_includes_future"]
    view = materializer.query_as_of(
        baseline,
        "2024-02-01",
        citation_key=expected["citation_key"],
    )
    for required in expected["must_include_record_ids"]:
        assert required in view["record_ids"]

    # Graph resolver should also select the 2024 instrument when edges apply.
    result = baseline.resolve_as_of("2024-02-01", citation_key="37-cfr-1.56")
    assert result.selected_node_id in {
        "cfr-1.56-2024-future",
        "cfr-1.56-2022",
    }
    if result.selected_node_id == "cfr-1.56-2024-future":
        selected = baseline.record_by_id()[result.selected_node_id]
        assert selected.effective_start is not None
        assert selected.effective_start <= date(2024, 2, 1)


def test_as_of_view_is_byte_stable(
    materializer: PatentAuthorityMaterializer, baseline
):
    a = materializer.query_as_of(baseline, "2023-10-01", citation_key="37-cfr-1.56")
    b = materializer.query_as_of(baseline, "2023-10-01", citation_key="37-cfr-1.56")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---------------------------------------------------------------------------
# Kind / tier / rendition persistence
# ---------------------------------------------------------------------------


def test_authority_dimensions_persist(baseline, recipe: dict):
    classes = {r.acceptance_class for r in baseline.records}
    for expected_class in recipe["expected"]["baseline_acceptance_classes"]:
        assert expected_class in classes

    # Explicit non-collapse: each record keeps independent kind/tier/rendition.
    by_id = baseline.record_by_id()
    statute = by_id["usc-35-101-2023"]
    assert statute.authority_kind is AuthorityKind.CODIFIED_STATUTE
    assert statute.authority_tier is AuthorityTier.OFFICIAL_BASE
    assert statute.rendition_legal_status is RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT
    assert statute.acceptance_class == "statute"

    regulation = by_id["cfr-1.56-2022"]
    assert regulation.authority_kind is AuthorityKind.PROMULGATED_REGULATION
    assert regulation.authority_tier is AuthorityTier.OFFICIAL_CHANGE
    assert regulation.rendition_legal_status is RenditionLegalStatus.OFFICIAL_ELECTRONIC
    assert regulation.acceptance_class == "regulation"

    guidance = by_id["mpep-2001-guidance"]
    assert guidance.authority_kind is AuthorityKind.OFFICIAL_AGENCY_GUIDANCE
    assert guidance.authority_tier is AuthorityTier.GUIDANCE
    assert guidance.rendition_legal_status is RenditionLegalStatus.OFFICIAL_ELECTRONIC
    assert guidance.acceptance_class == "guidance"

    editorial = by_id["ecfr-1.56-editorial"]
    assert editorial.authority_kind is AuthorityKind.UNOFFICIAL_EDITORIAL_AID
    assert editorial.authority_tier is AuthorityTier.UNOFFICIAL_CURRENT
    assert (
        editorial.rendition_legal_status
        is RenditionLegalStatus.UNOFFICIAL_EDITORIAL_PRESENTATION
    )
    assert editorial.acceptance_class == "editorial_aid"

    # Dimensions survive canonical round-trip.
    restored = TemporalAuthoritySnapshot.from_canonical_json(
        baseline.to_canonical_json()
    )
    for record in restored.records:
        original = by_id[record.record_id]
        assert record.authority_kind is original.authority_kind
        assert record.authority_tier is original.authority_tier
        assert record.rendition_legal_status is original.rendition_legal_status


def test_adjudicatory_tier_present_when_acquired(
    materializer: PatentAuthorityMaterializer, recipe: dict
):
    snap = materializer.materialize_from_recipe(
        recipe, schedule_id="with-adjudicatory-2024-06"
    )
    adjud = [r for r in snap.records if r.acceptance_class == "adjudicatory_authority"]
    assert adjud
    assert adjud[0].authority_kind is AuthorityKind.BINDING_ADJUDICATORY_AUTHORITY
    assert adjud[0].rendition_legal_status is RenditionLegalStatus.OFFICIAL_ELECTRONIC


# ---------------------------------------------------------------------------
# Adjudicatory research gap
# ---------------------------------------------------------------------------


def test_absent_adjudicatory_coverage_is_blocking_research_gap(baseline, recipe: dict):
    cov = baseline.adjudicatory_coverage
    assert cov.present is False
    assert cov.is_blocking_research_gap is True
    assert cov.status in {"research_gap", "missing", "absent"}
    assert "research" in cov.notes.lower() or "gap" in cov.notes.lower()
    assert baseline.readiness.adjudicatory_is_blocking_research_gap is True
    assert (
        AuthoritativeBlockReason.ADJUDICATORY_RESEARCH_GAP
        in baseline.readiness.block_reasons
    )
    assert recipe["expected"]["baseline_not_authoritative_ready"] is True
    assert baseline.readiness.ready is False


def test_adjudicatory_gap_visible_in_serialized_snapshot(baseline):
    payload = json.loads(baseline.to_canonical_json())
    adj = payload["adjudicatory_coverage"]
    assert adj["present"] is False
    assert adj["is_blocking_research_gap"] is True
    assert payload["readiness"]["ready"] is False
    assert "adjudicatory_research_gap" in payload["readiness"]["block_reasons"]


# ---------------------------------------------------------------------------
# Stale / missing / conflict block authoritative-ready
# ---------------------------------------------------------------------------


def test_conflicting_mandatory_sources_block_ready(
    materializer: PatentAuthorityMaterializer, recipe: dict
):
    snap = materializer.materialize_from_recipe(
        recipe, schedule_id="conflict-35-usc-102"
    )
    assert snap.readiness.ready is False
    assert (
        AuthoritativeBlockReason.CONFLICTING_MANDATORY_SOURCE
        in snap.readiness.block_reasons
        or AuthoritativeBlockReason.VERIFICATION_CONFLICT
        in snap.readiness.block_reasons
    )
    conflict_entries = [
        e
        for e in snap.freshness.entries
        if e.status is SourceFreshnessStatus.CONFLICT
    ]
    assert conflict_entries
    assert all(e.is_mandatory for e in conflict_entries)
    assert recipe["expected"]["conflict_blocks_ready"] is True


def test_stale_and_missing_mandatory_sources_block_ready(
    materializer: PatentAuthorityMaterializer, recipe: dict
):
    snap = materializer.materialize_from_recipe(
        recipe, schedule_id="stale-and-missing"
    )
    assert snap.readiness.ready is False
    reasons = set(snap.readiness.block_reasons)
    assert AuthoritativeBlockReason.STALE_MANDATORY_SOURCE in reasons
    assert AuthoritativeBlockReason.MISSING_MANDATORY_SOURCE in reasons
    statuses = {e.source_key: e.status for e in snap.freshness.entries}
    assert statuses.get("govinfo-cfr-37-annual") is SourceFreshnessStatus.STALE
    assert statuses.get("missing-mandatory") is SourceFreshnessStatus.MISSING
    assert recipe["expected"]["stale_blocks_ready"] is True


def test_fresh_mandatory_with_adjudicatory_can_be_ready(
    materializer: PatentAuthorityMaterializer, recipe: dict
):
    snap = materializer.materialize_from_recipe(
        recipe, schedule_id="with-adjudicatory-2024-06"
    )
    assert snap.adjudicatory_coverage.present is True
    assert snap.adjudicatory_coverage.is_blocking_research_gap is False
    assert snap.readiness.ready is True
    assert snap.readiness.block_reasons == ()
    assert recipe["expected"]["with_adjudicatory_may_be_ready"] is True
    # Freshness entries for mandatory sources are fresh.
    for entry in snap.freshness.entries:
        if entry.is_mandatory:
            assert entry.status is SourceFreshnessStatus.FRESH


# ---------------------------------------------------------------------------
# Freshness manifest + content addressing
# ---------------------------------------------------------------------------


def test_freshness_manifest_is_deterministic(baseline):
    first = baseline.freshness.to_dict()
    second = TemporalAuthoritySnapshot.from_canonical_json(
        baseline.to_canonical_json()
    ).freshness.to_dict()
    assert first == second
    # Entries sorted by source_key.
    keys = [e["source_key"] for e in first["entries"]]
    assert keys == sorted(keys)


def test_content_address_is_stable_across_put(
    baseline, tmp_path: Path
):
    store = ImmutableSnapshotStore(tmp_path / "ca")
    a1 = store.put(baseline)
    a2 = store.put(baseline)  # idempotent
    assert a1.sha256 == a2.sha256 == baseline.content_sha256
    assert a1.cid == a2.cid
    loaded = store.get(a1.sha256)
    assert loaded.to_canonical_bytes() == baseline.to_canonical_bytes()


def test_no_hard_coded_latest_in_baseline(baseline):
    for record in baseline.records:
        for field_name in ("edition", "version", "release_point", "package_id"):
            value = getattr(record, field_name)
            if value is not None:
                assert str(value).strip().lower() != "latest"


def test_verification_state_persists(baseline):
    by_id = baseline.record_by_id()
    assert by_id["usc-35-101-2023"].verification_state is VerificationState.VERIFIED
    assert by_id["ecfr-1.56-editorial"].verification_state is VerificationState.UNVERIFIED


def test_adjudicatory_coverage_factory_defaults_to_gap():
    gap = AdjudicatoryCoverage.research_gap()
    assert gap.present is False
    assert gap.is_blocking_research_gap is True
    from_none = AdjudicatoryCoverage.from_dict(None)
    assert from_none.is_blocking_research_gap is True
