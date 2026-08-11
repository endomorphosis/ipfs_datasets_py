"""Unit tests for the patent temporal authority graph and as-of resolver.

Acceptance (PATLAW-016):

* Historical replay is deterministic.
* Proposed / future / withdrawn text is excluded unless explicitly requested.
* Conflicts and missing intervals return unknown with competing sources.
* Official and derived views remain separate.
"""

from __future__ import annotations

from datetime import date

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    ArtifactIdentity,
    IdentityRole,
    VerificationState,
    build_fixture_record,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_registry import (
    SCHEMA_VERSION,
    AsOfQuery,
    AsOfViewRole,
    AuthoritySpan,
    AuthorityTemporalEdge,
    AuthorityTextNode,
    AuthorityViewKind,
    DiagnosticCode,
    DuplicateNodeError,
    ExclusionReason,
    PatentAuthorityRegistry,
    PatentAuthorityRegistryError,
    PatentTemporalAuthorityGraph,
    PatentTemporalAuthorityGraphBuilder,
    ResolutionStatus,
    TemporalRelation,
    UnknownNodeError,
    resolve_as_of,
    resolve_mailing_and_response,
    validate_temporal_authority_graph,
)


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64


def _official(sha: str = _SHA_A, source_id: str = "official-1", url: str | None = None):
    return ArtifactIdentity(
        provider="govinfo",
        source_id=source_id,
        artifact_sha256=sha,
        source_url=url or f"https://www.govinfo.gov/{source_id}",
        role=IdentityRole.OFFICIAL_ARTIFACT,
    )


def _derived(sha: str = _SHA_B, source_id: str = "derived-1", url: str | None = None):
    return ArtifactIdentity(
        provider="ecfr",
        source_id=source_id,
        artifact_sha256=sha,
        source_url=url or f"https://www.ecfr.gov/{source_id}",
        role=IdentityRole.DERIVED_PRESENTATION,
    )


def _node(**overrides) -> AuthorityTextNode:
    base = dict(
        node_id="n-base",
        citation_key="37-cfr-1.56",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection="CFR",
        citation="37 C.F.R. § 1.56",
        edition="2020",
        version="2020-base",
        text_excerpt="Base text",
        effective_start=date(2020, 1, 1),
        is_binding=True,
        official_artifact=_official(),
        verification_state=VerificationState.VERIFIED,
    )
    base.update(overrides)
    return AuthorityTextNode(**base)


def _simple_graph() -> PatentTemporalAuthorityGraph:
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="unit-simple")
    base = _node(
        node_id="base-2020",
        text_excerpt="Base 2020",
        effective_start=date(2020, 1, 1),
        official_artifact=_official(_SHA_A, "base-2020"),
    )
    amend = _node(
        node_id="amend-2022",
        authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        collection="FR",
        edition="2022",
        version="2022-amend",
        text_excerpt="Amended 2022",
        effective_start=date(2022, 6, 1),
        official_artifact=_official(_SHA_C, "amend-2022"),
        derived_presentation=_derived(_SHA_D, "amend-2022-ecfr"),
    )
    proposed = _node(
        node_id="proposed-2023",
        authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
        collection="FR",
        edition=None,
        version="2023-proposed",
        document_type="proposed_rule",
        text_excerpt="Proposed 2023",
        effective_start=date(2023, 3, 1),
        is_binding=False,
        is_proposed=True,
        official_artifact=None,
        derived_presentation=_derived(_SHA_B, "proposed-2023"),
    )
    future = _node(
        node_id="future-2024",
        authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        collection="FR",
        edition="2024",
        version="2024-future",
        text_excerpt="Future 2024",
        effective_start=date(2024, 1, 1),
        official_artifact=_official("e" * 64, "future-2024"),
    )
    withdrawn = _node(
        node_id="withdrawn-rule",
        authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        collection="FR",
        edition=None,
        version="withdrawn-1",
        text_excerpt="Withdrawn text",
        effective_start=date(2021, 1, 1),
        is_binding=False,
        is_withdrawn=True,
        official_artifact=_official("f" * 64, "withdrawn-1"),
    )
    for n in (base, amend, proposed, future, withdrawn):
        builder.add_node(n)
    builder.add_edge(
        AuthorityTemporalEdge(
            edge_id="e-amends",
            relation=TemporalRelation.AMENDS,
            source_node_id="amend-2022",
            target_node_id="base-2020",
            effective_date=date(2022, 6, 1),
        )
    )
    return builder.build()


# ---------------------------------------------------------------------------
# Construction / serialization
# ---------------------------------------------------------------------------


def test_schema_version_stable():
    assert SCHEMA_VERSION == "patent-authority-registry-v1"


def test_node_rejects_hard_coded_latest_edition():
    with pytest.raises(Exception):
        _node(edition="latest")


def test_official_tier_rejects_derived_only_identity():
    with pytest.raises(PatentAuthorityRegistryError):
        _node(official_artifact=None, derived_presentation=_derived())


def test_proposed_cannot_be_binding():
    node = _node(
        node_id="p1",
        is_proposed=True,
        is_binding=True,
        official_artifact=_official(),
    )
    assert node.is_binding is False
    assert node.is_proposed is True


def test_node_round_trip_dict():
    node = _node(
        span=AuthoritySpan(section="1.56", quote="Base text", start_offset=0, end_offset=9)
    )
    rebuilt = AuthorityTextNode.from_dict(node.to_dict())
    assert rebuilt.to_dict() == node.to_dict()


def test_edge_round_trip_and_relation_coerce():
    edge = AuthorityTemporalEdge(
        edge_id="e1",
        relation="supersedes",
        source_node_id="a",
        target_node_id="b",
        effective_date="2022-01-01",
    )
    assert edge.relation is TemporalRelation.SUPERSEDES
    assert edge.effective_date == date(2022, 1, 1)
    assert AuthorityTemporalEdge.from_dict(edge.to_dict()).to_dict() == edge.to_dict()


def test_graph_nodes_and_edges_sorted_deterministically():
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="sort-test")
    builder.add_node(_node(node_id="z-node"))
    builder.add_node(_node(node_id="a-node", official_artifact=_official(_SHA_C, "a")))
    builder.add_edge(
        {
            "edge_id": "z-edge",
            "relation": "related",
            "source_node_id": "z-node",
            "target_node_id": "a-node",
        }
    )
    builder.add_edge(
        {
            "edge_id": "a-edge",
            "relation": "related",
            "source_node_id": "a-node",
            "target_node_id": "z-node",
        }
    )
    graph = builder.build()
    assert [n.node_id for n in graph.nodes] == ["a-node", "z-node"]
    assert [e.edge_id for e in graph.edges] == ["a-edge", "z-edge"]
    assert graph.to_canonical_json() == PatentTemporalAuthorityGraph.from_dict(
        graph.to_dict()
    ).to_canonical_json()


def test_duplicate_node_rejected():
    builder = PatentTemporalAuthorityGraphBuilder()
    builder.add_node(_node(node_id="dup"))
    with pytest.raises(DuplicateNodeError):
        builder.add_node(_node(node_id="dup"))


def test_edge_requires_nodes():
    builder = PatentTemporalAuthorityGraphBuilder()
    builder.add_node(_node(node_id="only"))
    with pytest.raises(UnknownNodeError):
        builder.add_edge(
            AuthorityTemporalEdge(
                edge_id="e",
                relation=TemporalRelation.AMENDS,
                source_node_id="only",
                target_node_id="missing",
            )
        )


def test_from_source_record_projection():
    record = build_fixture_record(
        source_key="us-cfr-37-2024",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection="CFR",
        edition="2024",
        official_sha256=_SHA_A,
        official_url="https://www.govinfo.gov/cfr",
        provider="govinfo",
        citation="37 C.F.R.",
        effective_start=date(2024, 7, 1),
    )
    node = AuthorityTextNode.from_source_record(
        record, citation_key="37-cfr", is_binding=True
    )
    assert node.source_key == "us-cfr-37-2024"
    assert node.authority_tier is AuthorityTier.OFFICIAL_BASE
    assert node.is_binding is True


# ---------------------------------------------------------------------------
# As-of resolution: selection, exclusions, dual views
# ---------------------------------------------------------------------------


def test_resolve_selects_base_before_amendment():
    graph = _simple_graph()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2021, 6, 1), citation_key="37-cfr-1.56"),
    )
    assert result.status is ResolutionStatus.RESOLVED
    assert result.selected_node_id == "base-2020"
    assert result.authority_tier is AuthorityTier.OFFICIAL_BASE


def test_resolve_selects_amendment_after_effective_date():
    graph = _simple_graph()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2022, 7, 1), citation_key="37-cfr-1.56"),
    )
    assert result.status is ResolutionStatus.RESOLVED
    assert result.selected_node_id == "amend-2022"
    assert "e-amends" in result.applied_edge_ids


def test_proposed_excluded_by_default():
    graph = _simple_graph()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2023, 4, 1), citation_key="37-cfr-1.56"),
    )
    assert result.status is ResolutionStatus.RESOLVED
    assert result.selected_node_id == "amend-2022"
    reasons = {e.node_id: e.reason for e in result.excluded}
    assert reasons.get("proposed-2023") is ExclusionReason.PROPOSED
    assert any(d.code is DiagnosticCode.PROPOSED_EXCLUDED for d in result.diagnostics)


def test_proposed_included_when_requested():
    graph = _simple_graph()
    result = resolve_as_of(
        graph,
        AsOfQuery(
            as_of=date(2023, 4, 1),
            citation_key="37-cfr-1.56",
            include_proposed=True,
            include_nonbinding=True,
            view_kind=AuthorityViewKind.DERIVED,
        ),
    )
    # Proposed is unofficial derived; may rank below official amendment.
    # Explicit request means it is not excluded for PROPOSED reason.
    proposed_exclusions = [
        e for e in result.excluded if e.node_id == "proposed-2023"
    ]
    assert all(e.reason is not ExclusionReason.PROPOSED for e in proposed_exclusions)


def test_future_excluded_by_default():
    graph = _simple_graph()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2023, 12, 15), citation_key="37-cfr-1.56"),
    )
    assert result.selected_node_id == "amend-2022"
    reasons = {e.node_id: e.reason for e in result.excluded}
    assert reasons.get("future-2024") is ExclusionReason.FUTURE


def test_future_selected_after_effective_date():
    graph = _simple_graph()
    # Add supersession edge so future replaces amendment.
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="with-future-edge")
    for n in _simple_graph().nodes:
        builder.add_node(n)
    for e in _simple_graph().edges:
        builder.add_edge(e)
    builder.add_edge(
        AuthorityTemporalEdge(
            edge_id="e-super",
            relation=TemporalRelation.SUPERSEDES,
            source_node_id="future-2024",
            target_node_id="amend-2022",
            effective_date=date(2024, 1, 1),
        )
    )
    graph = builder.build()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2024, 2, 1), citation_key="37-cfr-1.56"),
    )
    assert result.status is ResolutionStatus.RESOLVED
    assert result.selected_node_id == "future-2024"


def test_withdrawn_excluded_by_default():
    graph = _simple_graph()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2021, 6, 1), citation_key="37-cfr-1.56"),
    )
    reasons = {e.node_id: e.reason for e in result.excluded}
    assert reasons.get("withdrawn-rule") is ExclusionReason.WITHDRAWN


def test_withdrawn_included_when_requested():
    graph = _simple_graph()
    result = resolve_as_of(
        graph,
        AsOfQuery(
            as_of=date(2021, 6, 1),
            citation_key="37-cfr-1.56",
            include_withdrawn=True,
            include_nonbinding=True,
        ),
    )
    withdrawn_exclusions = [
        e for e in result.excluded if e.node_id == "withdrawn-rule"
    ]
    assert all(e.reason is not ExclusionReason.WITHDRAWN for e in withdrawn_exclusions)


def test_conflict_returns_unknown_with_competing_sources():
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="conflict")
    builder.add_node(
        _node(
            node_id="left",
            citation_key="35-usc-102",
            text_excerpt="Left",
            effective_start=date(2020, 1, 1),
            official_artifact=_official(_SHA_A, "left"),
        )
    )
    builder.add_node(
        _node(
            node_id="right",
            citation_key="35-usc-102",
            text_excerpt="Right",
            effective_start=date(2020, 1, 1),
            official_artifact=_official(_SHA_C, "right"),
        )
    )
    graph = builder.build()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2021, 1, 1), citation_key="35-usc-102"),
    )
    assert result.status is ResolutionStatus.UNKNOWN
    assert result.is_unknown
    assert result.selected_node_id is None
    assert len(result.competing_sources) == 2
    assert {c.node_id for c in result.competing_sources} == {"left", "right"}
    assert any(d.code is DiagnosticCode.CONFLICTING_SOURCES for d in result.diagnostics)
    # Competing sources ordered deterministically.
    assert [c.node_id for c in result.competing_sources] == ["left", "right"]


def test_missing_interval_returns_unknown_with_competing_sources():
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="gap")
    builder.add_node(
        _node(
            node_id="expired",
            citation_key="gap-key",
            effective_start=date(2018, 1, 1),
            effective_end=date(2019, 12, 31),
            official_artifact=_official(_SHA_A, "expired"),
        )
    )
    graph = builder.build()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2021, 6, 1), citation_key="gap-key"),
    )
    assert result.status is ResolutionStatus.UNKNOWN
    assert result.selected_node_id is None
    assert any(c.node_id == "expired" for c in result.competing_sources)
    assert any(d.code is DiagnosticCode.MISSING_INTERVAL for d in result.diagnostics)


def test_official_and_derived_views_remain_separate():
    graph = _simple_graph()
    official = resolve_as_of(
        graph,
        AsOfQuery(
            as_of=date(2022, 7, 1),
            citation_key="37-cfr-1.56",
            view_kind=AuthorityViewKind.OFFICIAL,
        ),
    )
    derived = resolve_as_of(
        graph,
        AsOfQuery(
            as_of=date(2022, 7, 1),
            citation_key="37-cfr-1.56",
            view_kind=AuthorityViewKind.DERIVED,
        ),
    )
    both = resolve_as_of(
        graph,
        AsOfQuery(
            as_of=date(2022, 7, 1),
            citation_key="37-cfr-1.56",
            view_kind=AuthorityViewKind.BOTH_SEPARATE,
        ),
    )
    assert official.status is ResolutionStatus.RESOLVED
    assert official.selected_node_id == "amend-2022"
    assert official.official_node_id == "amend-2022"
    # Derived view selects the same node when it carries derived identity.
    assert derived.status is ResolutionStatus.RESOLVED
    assert derived.selected_node_id == "amend-2022"
    assert both.status is ResolutionStatus.RESOLVED
    assert both.official_node_id == "amend-2022"
    assert both.derived_node_id == "amend-2022"
    assert any(
        d.code is DiagnosticCode.OFFICIAL_DERIVED_SEPARATE for d in both.diagnostics
    )


def test_guidance_never_outranks_official_regulation():
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="tier")
    builder.add_node(
        _node(
            node_id="reg",
            citation_key="same-key",
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            text_excerpt="Reg",
            effective_start=date(2020, 1, 1),
            official_artifact=_official(_SHA_A, "reg"),
        )
    )
    builder.add_node(
        _node(
            node_id="mpep",
            citation_key="same-key",
            authority_tier=AuthorityTier.GUIDANCE,
            collection="MPEP",
            text_excerpt="Guidance",
            effective_start=date(2023, 1, 1),
            is_binding=False,
            official_artifact=_official(_SHA_C, "mpep"),
        )
    )
    graph = builder.build()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2023, 6, 1), citation_key="same-key"),
    )
    assert result.selected_node_id == "reg"


def test_mailing_and_response_views_are_separate_and_reproducible():
    graph = _simple_graph()
    dual = resolve_mailing_and_response(
        graph,
        mailing_date=date(2021, 6, 1),
        response_date=date(2022, 7, 1),
        citation_key="37-cfr-1.56",
    )
    assert dual.mailing.query.view_role is AsOfViewRole.MAILING_DATE
    assert dual.response.query.view_role is AsOfViewRole.RESPONSE_DATE
    assert dual.mailing.selected_node_id == "base-2020"
    assert dual.response.selected_node_id == "amend-2022"
    # Deterministic dual serialization.
    assert dual.to_canonical_json() == dual.to_canonical_json()
    again = resolve_mailing_and_response(
        graph,
        mailing_date="2021-06-01",
        response_date="2022-07-01",
        citation_key="37-cfr-1.56",
    )
    assert dual.to_dict() == again.to_dict()


def test_resolution_payload_is_deterministic():
    graph = _simple_graph()
    q = AsOfQuery(as_of=date(2022, 7, 1), citation_key="37-cfr-1.56")
    a = resolve_as_of(graph, q).to_canonical_json()
    b = resolve_as_of(graph, q).to_canonical_json()
    assert a == b


def test_stayed_node_excluded_by_default():
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="stay")
    builder.add_node(
        _node(
            node_id="rule",
            citation_key="stay-key",
            effective_start=date(2020, 1, 1),
            official_artifact=_official(_SHA_A, "rule"),
        )
    )
    builder.add_node(
        _node(
            node_id="stay-order",
            citation_key="stay-key",
            authority_tier=AuthorityTier.OFFICIAL_CHANGE,
            collection="FR",
            edition="2021",
            version="stay-1",
            effective_start=date(2021, 1, 1),
            is_binding=True,
            official_artifact=_official(_SHA_C, "stay"),
        )
    )
    builder.add_edge(
        AuthorityTemporalEdge(
            edge_id="e-stay",
            relation=TemporalRelation.STAYS,
            source_node_id="stay-order",
            target_node_id="rule",
            effective_date=date(2021, 1, 1),
        )
    )
    graph = builder.build()
    result = resolve_as_of(
        graph,
        AsOfQuery(as_of=date(2021, 6, 1), citation_key="stay-key"),
    )
    # Rule is stayed; stay-order may itself not be the text of the rule.
    # Stayed rule must not be selected as binding authority silently.
    assert all(
        not (e.node_id == "rule" and e.reason is ExclusionReason.STAYED) or True
        for e in result.excluded
    )
    reasons = {e.node_id: e.reason for e in result.excluded}
    assert reasons.get("rule") is ExclusionReason.STAYED


def test_registry_register_source_and_resolve():
    registry = PatentAuthorityRegistry(graph_id="reg-test")
    record = build_fixture_record(
        source_key="cfr-base",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection="CFR",
        edition="2020",
        official_sha256=_SHA_A,
        official_url="https://www.govinfo.gov/base",
        provider="govinfo",
        citation="37 C.F.R. § 1.56",
        effective_start=date(2020, 1, 1),
    )
    registry.register_source(
        record,
        citation_key="37-cfr-1.56",
        is_binding=True,
        text_excerpt="From source",
    )
    registry.add_node(
        _node(
            node_id="amend",
            authority_tier=AuthorityTier.OFFICIAL_CHANGE,
            collection="FR",
            edition="2022",
            version="amend",
            text_excerpt="Amend",
            effective_start=date(2022, 1, 1),
            official_artifact=_official(_SHA_C, "amend"),
        )
    )
    registry.add_edge(
        {
            "edge_id": "e1",
            "relation": "amends",
            "source_node_id": "amend",
            "target_node_id": "cfr-base",
            "effective_date": "2022-01-01",
        }
    )
    early = registry.resolve(date(2021, 1, 1), citation_key="37-cfr-1.56")
    late = registry.resolve(
        AsOfQuery(as_of=date(2022, 6, 1), citation_key="37-cfr-1.56")
    )
    assert early.selected_node_id == "cfr-base"
    assert late.selected_node_id == "amend"
    assert len(registry) == 2
    assert "amend" in registry


def test_registry_fixture_round_trip():
    registry = PatentAuthorityRegistry(graph_id="round")
    registry.add_node(_node(node_id="n1"))
    payload = registry.to_fixture_dict()
    rebuilt = PatentAuthorityRegistry.from_fixture_dict(payload)
    assert rebuilt.to_canonical_json() == registry.to_canonical_json()


def test_validate_detects_missing_edge_target():
    graph = PatentTemporalAuthorityGraph(
        graph_id="bad",
        nodes=(_node(node_id="only"),),
        edges=(
            AuthorityTemporalEdge(
                edge_id="e",
                relation=TemporalRelation.AMENDS,
                source_node_id="only",
                target_node_id="ghost",
            ),
        ),
    )
    # Construction of graph doesn't require endpoints; validation does.
    diags = validate_temporal_authority_graph(graph)
    assert any(d.code is DiagnosticCode.EDGE_TARGET_MISSING for d in diags)


def test_query_from_dict_and_date_shortcut():
    graph = _simple_graph()
    r1 = resolve_as_of(graph, date(2021, 1, 1), citation_key="37-cfr-1.56")
    r2 = resolve_as_of(
        graph,
        {"as_of": "2021-01-01", "citation_key": "37-cfr-1.56"},
    )
    assert r1.selected_node_id == r2.selected_node_id == "base-2020"


def test_resolution_exposes_selected_span():
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="span")
    builder.add_node(
        _node(
            node_id="with-span",
            span=AuthoritySpan(
                section="1.56",
                quote="Base text",
                artifact_sha256=_SHA_A,
                start_offset=10,
                end_offset=20,
            ),
        )
    )
    result = resolve_as_of(
        builder.build(),
        AsOfQuery(as_of=date(2021, 1, 1), citation_key="37-cfr-1.56"),
    )
    assert result.selected_span is not None
    assert result.selected_span.section == "1.56"
    assert result.selected_span.start_offset == 10
