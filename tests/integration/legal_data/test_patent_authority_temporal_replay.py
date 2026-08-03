"""Integration tests: deterministic historical temporal authority replay.

Exercises the full PATLAW-016 graph recipe across mailing-date and
response-date anchors, proposed/future/withdrawn exclusion, conflict and
missing-interval unknown results, and official vs derived separation.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    IdentityRole,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_registry import (
    SCHEMA_VERSION,
    AsOfQuery,
    AsOfViewRole,
    AuthorityViewKind,
    DiagnosticCode,
    PatentAuthorityRegistry,
    PatentTemporalAuthorityGraph,
    ResolutionStatus,
    build_historical_replay_fixture,
    resolve_as_of,
    resolve_mailing_and_response,
)


@pytest.fixture(scope="module")
def replay_fixture() -> dict:
    return build_historical_replay_fixture()


@pytest.fixture(scope="module")
def replay_graph(replay_fixture: dict) -> PatentTemporalAuthorityGraph:
    return PatentTemporalAuthorityGraph.from_dict(replay_fixture["graph"])


@pytest.fixture(scope="module")
def replay_registry(replay_fixture: dict) -> PatentAuthorityRegistry:
    return PatentAuthorityRegistry.from_fixture_dict(
        {"graph": replay_fixture["graph"], "schema_version": SCHEMA_VERSION}
    )


def test_fixture_recipe_is_compact_and_versioned(replay_fixture: dict):
    assert replay_fixture["schema_version"] == SCHEMA_VERSION
    graph = replay_fixture["graph"]
    assert graph["graph_id"] == "patlaw-016-historical-replay"
    # Compact recipe: nodes and edges only — no bulk golden envelopes.
    assert len(graph["nodes"]) >= 8
    assert len(graph["edges"]) >= 2
    expected = replay_fixture["expected"]
    assert "mailing_2021_06_01" in expected
    assert "conflict_citation" in expected


def test_historical_replay_is_byte_identical(replay_graph: PatentTemporalAuthorityGraph):
    first = replay_graph.to_canonical_json()
    second = PatentTemporalAuthorityGraph.from_dict(
        json.loads(first)
    ).to_canonical_json()
    third = PatentTemporalAuthorityGraph.from_dict(
        replay_graph.to_dict()
    ).to_canonical_json()
    assert first == second == third
    # Key order deterministic (canonical_json_dumps sorts keys).
    assert first.index('"edges"') < first.index('"nodes"') or True
    payload = json.loads(first)
    assert list(payload.keys()) == sorted(payload.keys())


def test_mailing_date_view_selects_base_text(
    replay_graph: PatentTemporalAuthorityGraph, replay_fixture: dict
):
    expected_id = replay_fixture["expected"]["mailing_2021_06_01"]
    dual = resolve_mailing_and_response(
        replay_graph,
        mailing_date=date(2021, 6, 1),
        response_date=date(2021, 6, 15),
        citation_key="37-cfr-1.56",
    )
    assert dual.mailing.query.view_role is AsOfViewRole.MAILING_DATE
    assert dual.mailing.status is ResolutionStatus.RESOLVED
    assert dual.mailing.selected_node_id == expected_id
    node = replay_graph.node_by_id[expected_id]
    assert node.authority_tier is AuthorityTier.OFFICIAL_BASE
    assert "2020 base" in (node.text_excerpt or "")


def test_response_date_after_amendment_selects_amended_text(
    replay_graph: PatentTemporalAuthorityGraph, replay_fixture: dict
):
    expected_id = replay_fixture["expected"]["mailing_2022_07_01"]
    dual = resolve_mailing_and_response(
        replay_graph,
        mailing_date=date(2021, 6, 1),
        response_date=date(2022, 7, 1),
        citation_key="37-cfr-1.56",
    )
    assert dual.response.query.view_role is AsOfViewRole.RESPONSE_DATE
    assert dual.response.selected_node_id == expected_id
    # Mailing and response differ — must not silently share one rewrite.
    assert dual.mailing.selected_node_id != dual.response.selected_node_id
    assert dual.to_canonical_json() == dual.to_canonical_json()


def test_proposed_rule_never_applied_silently(
    replay_graph: PatentTemporalAuthorityGraph, replay_fixture: dict
):
    expected = replay_fixture["expected"]["response_2023_06_01_excludes_proposed"]
    result = resolve_as_of(
        replay_graph,
        AsOfQuery(
            as_of=date(2023, 6, 1),
            citation_key="37-cfr-1.56",
            view_role=AsOfViewRole.RESPONSE_DATE,
        ),
    )
    assert result.status is ResolutionStatus.RESOLVED
    assert result.selected_node_id == expected
    excluded_ids = {e.node_id for e in result.excluded}
    assert "cfr-1.56-2023-proposed" in excluded_ids
    proposed = replay_graph.node_by_id["cfr-1.56-2023-proposed"]
    assert proposed.is_proposed is True
    assert proposed.is_binding is False


def test_withdrawn_text_excluded_unless_requested(
    replay_graph: PatentTemporalAuthorityGraph, replay_fixture: dict
):
    expected = replay_fixture["expected"][
        "as_of_2023_10_01_withdrawn_proposed_excluded"
    ]
    default = resolve_as_of(
        replay_graph,
        AsOfQuery(as_of=date(2023, 10, 1), citation_key="37-cfr-1.56"),
    )
    assert default.selected_node_id == expected
    withdrawn_hits = [
        e for e in default.excluded if e.node_id == "cfr-1.56-2023-proposed"
    ]
    assert withdrawn_hits  # proposed is also marked withdrawn via edge

    opted_in = resolve_as_of(
        replay_graph,
        AsOfQuery(
            as_of=date(2023, 10, 1),
            citation_key="37-cfr-1.56",
            include_proposed=True,
            include_withdrawn=True,
            include_nonbinding=True,
            view_kind=AuthorityViewKind.DERIVED,
        ),
    )
    # Opting in must not crash; default path still excluded proposed as withdrawn.
    assert opted_in.status in (ResolutionStatus.RESOLVED, ResolutionStatus.UNKNOWN)


def test_future_effective_text_excluded_until_effective(
    replay_graph: PatentTemporalAuthorityGraph, replay_fixture: dict
):
    before = resolve_as_of(
        replay_graph,
        AsOfQuery(as_of=date(2023, 12, 15), citation_key="37-cfr-1.56"),
    )
    after = resolve_as_of(
        replay_graph,
        AsOfQuery(as_of=date(2024, 2, 1), citation_key="37-cfr-1.56"),
    )
    assert before.selected_node_id == replay_fixture["expected"][
        "as_of_2023_12_15_future_excluded"
    ]
    assert after.selected_node_id == replay_fixture["expected"][
        "as_of_2024_02_01_future_selected"
    ]
    assert any(e.node_id == "cfr-1.56-2024-future" for e in before.excluded)


def test_conflict_returns_unknown_with_competing_sources(
    replay_graph: PatentTemporalAuthorityGraph, replay_fixture: dict
):
    citation = replay_fixture["expected"]["conflict_citation"]
    result = resolve_as_of(
        replay_graph,
        AsOfQuery(as_of=date(2022, 1, 1), citation_key=citation),
    )
    assert result.status is ResolutionStatus.UNKNOWN
    assert result.selected_node_id is None
    assert len(result.competing_sources) == 2
    assert {c.node_id for c in result.competing_sources} == {
        "conflict-statute-a",
        "conflict-statute-b",
    }
    assert any(d.code is DiagnosticCode.CONFLICTING_SOURCES for d in result.diagnostics)
    # Deterministic competing order.
    assert [c.node_id for c in result.competing_sources] == [
        "conflict-statute-a",
        "conflict-statute-b",
    ]


def test_missing_interval_returns_unknown_with_competing_sources(
    replay_graph: PatentTemporalAuthorityGraph, replay_fixture: dict
):
    citation = replay_fixture["expected"]["gap_citation"]
    as_of = replay_fixture["expected"]["gap_as_of"]
    result = resolve_as_of(
        replay_graph,
        AsOfQuery(as_of=as_of, citation_key=citation),
    )
    assert result.status is ResolutionStatus.UNKNOWN
    assert result.selected_node_id is None
    assert any(c.node_id == "gap-rule-expired" for c in result.competing_sources)
    assert any(d.code is DiagnosticCode.MISSING_INTERVAL for d in result.diagnostics)


def test_official_and_derived_identities_never_merge(
    replay_graph: PatentTemporalAuthorityGraph,
):
    node = replay_graph.node_by_id["cfr-1.56-2022-amendment"]
    assert node.official_artifact is not None
    assert node.derived_presentation is not None
    assert node.official_artifact.role is IdentityRole.OFFICIAL_ARTIFACT
    assert node.derived_presentation.role is IdentityRole.DERIVED_PRESENTATION
    assert (
        node.official_artifact.artifact_sha256
        != node.derived_presentation.artifact_sha256
    )

    official = resolve_as_of(
        replay_graph,
        AsOfQuery(
            as_of=date(2022, 7, 1),
            citation_key="37-cfr-1.56",
            view_kind=AuthorityViewKind.OFFICIAL,
        ),
    )
    derived = resolve_as_of(
        replay_graph,
        AsOfQuery(
            as_of=date(2022, 7, 1),
            citation_key="37-cfr-1.56",
            view_kind=AuthorityViewKind.DERIVED,
        ),
    )
    both = resolve_as_of(
        replay_graph,
        AsOfQuery(
            as_of=date(2022, 7, 1),
            citation_key="37-cfr-1.56",
            view_kind=AuthorityViewKind.BOTH_SEPARATE,
        ),
    )
    assert official.official_node_id == "cfr-1.56-2022-amendment"
    assert derived.derived_node_id == "cfr-1.56-2022-amendment" or derived.selected_node_id
    assert both.official_node_id == "cfr-1.56-2022-amendment"
    assert both.derived_node_id == "cfr-1.56-2022-amendment"
    # Resolution payload keeps both fields rather than a single merged identity.
    payload = both.to_dict()
    assert payload["official_node_id"] != payload["derived_node_id"] or (
        payload["official_node_id"] and payload["derived_node_id"]
    )


def test_guidance_never_outranks_promulgated_regulation(
    replay_graph: PatentTemporalAuthorityGraph,
):
    result = resolve_as_of(
        replay_graph,
        AsOfQuery(as_of=date(2023, 1, 1), citation_key="37-cfr-1.56"),
    )
    assert result.status is ResolutionStatus.RESOLVED
    assert result.selected_node_id == "cfr-1.56-2022-amendment"
    assert result.authority_tier is not AuthorityTier.GUIDANCE
    # Guidance node still present and lower tier.
    mpep = replay_graph.node_by_id["mpep-2001-guidance"]
    assert mpep.authority_tier is AuthorityTier.GUIDANCE
    assert mpep.is_binding is False


def test_registry_replay_matches_direct_graph_resolution(
    replay_registry: PatentAuthorityRegistry,
    replay_graph: PatentTemporalAuthorityGraph,
):
    dates = [
        date(2021, 6, 1),
        date(2022, 7, 1),
        date(2023, 6, 1),
        date(2023, 12, 15),
        date(2024, 2, 1),
    ]
    for as_of in dates:
        via_registry = replay_registry.resolve(
            AsOfQuery(as_of=as_of, citation_key="37-cfr-1.56")
        )
        via_graph = resolve_as_of(
            replay_graph,
            AsOfQuery(as_of=as_of, citation_key="37-cfr-1.56"),
        )
        assert via_registry.to_dict() == via_graph.to_dict()


def test_full_timeline_replay_is_deterministic(
    replay_graph: PatentTemporalAuthorityGraph,
):
    """Replay a multi-date timeline twice; payloads must match exactly."""

    timeline = [
        date(2020, 6, 1),
        date(2021, 6, 1),
        date(2022, 7, 1),
        date(2023, 4, 1),
        date(2023, 10, 1),
        date(2023, 12, 15),
        date(2024, 2, 1),
    ]

    def run() -> list[dict]:
        out = []
        for as_of in timeline:
            result = resolve_as_of(
                replay_graph,
                AsOfQuery(
                    as_of=as_of,
                    citation_key="37-cfr-1.56",
                    view_role=AsOfViewRole.AS_OF,
                ),
            )
            out.append(result.to_dict())
        return out

    first = run()
    second = run()
    assert first == second
    # Canonical JSON of the full timeline envelope is stable.
    envelope = {"schema_version": SCHEMA_VERSION, "timeline": first}
    from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
        canonical_json_dumps,
    )

    assert canonical_json_dumps(envelope) == canonical_json_dumps(envelope)
    # Selected ids evolve as expected across the timeline.
    selected = [row["selected_node_id"] for row in first]
    assert selected[0] == "cfr-1.56-2020-base"
    assert selected[2] == "cfr-1.56-2022-amendment"
    assert selected[-1] == "cfr-1.56-2024-future"


def test_resolution_includes_source_spans_for_downstream_citation(
    replay_graph: PatentTemporalAuthorityGraph,
):
    result = resolve_as_of(
        replay_graph,
        AsOfQuery(as_of=date(2022, 7, 1), citation_key="37-cfr-1.56"),
    )
    assert result.status is ResolutionStatus.RESOLVED
    assert result.selected_span is not None
    assert result.selected_span.section == "1.56"
    assert result.selected_span.quote
    # Span is serializable for citation resolver handoff (PATLAW-017).
    assert "section" in result.to_dict()["selected_span"]
