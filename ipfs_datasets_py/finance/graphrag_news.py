"""Finance-specific GraphRAG news analysis.

This is **core package functionality**. MCP tools and CLIs should wrap these
functions/classes rather than hosting the implementation themselves.

It is intentionally dependency-tolerant: if optional GraphRAG deps are missing,
APIs still return structured "unavailable" responses instead of failing at
import time.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from ipfs_datasets_py.graphrag import (
        GRAPHRAG_AVAILABLE,
        Entity,
        KnowledgeGraph,
        Relationship,
    )
except Exception:  # pragma: no cover
    # Fallback for unusual module-resolution environments.
    from ..graphrag import (  # type: ignore
        GRAPHRAG_AVAILABLE,
        Entity,
        KnowledgeGraph,
        Relationship,
    )

logger = logging.getLogger(__name__)


@dataclass
class ExecutiveProfile:
    person_id: str
    name: str
    gender: str = "unknown"
    personality_traits: List[str] = field(default_factory=list)
    education: Dict[str, str] = field(default_factory=dict)
    companies: List[str] = field(default_factory=list)
    positions: List[str] = field(default_factory=list)
    tenure_start: Optional[datetime] = None
    tenure_end: Optional[datetime] = None
    news_mentions: int = 0
    sentiment_score: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_entity(self) -> Entity:
        return Entity(
            entity_id=self.person_id,
            entity_type="executive",
            name=self.name,
            properties={
                "gender": self.gender,
                "personality_traits": self.personality_traits,
                "education": self.education,
                "companies": self.companies,
                "positions": self.positions,
                "tenure_start": self.tenure_start.isoformat() if self.tenure_start else None,
                "tenure_end": self.tenure_end.isoformat() if self.tenure_end else None,
                "news_mentions": self.news_mentions,
                "sentiment_score": self.sentiment_score,
                **self.attributes,
            },
        )


@dataclass
class CompanyPerformance:
    company_id: str
    symbol: str
    name: str
    return_percentage: float = 0.0
    volatility: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_entity(self) -> Entity:
        return Entity(
            entity_id=self.company_id,
            entity_type="company",
            name=self.name,
            properties={
                "symbol": self.symbol,
                "return_percentage": self.return_percentage,
                "volatility": self.volatility,
                **self.metadata,
            },
        )


@dataclass
class HypothesisTest:
    hypothesis: str
    attribute_name: str
    group_a_value: str
    group_b_value: str
    group_a_count: int
    group_b_count: int
    group_a_avg_performance: float
    group_b_avg_performance: float
    effect_size: float
    confidence: float
    conclusion: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis": self.hypothesis,
            "attribute": self.attribute_name,
            "group_a": {
                "value": self.group_a_value,
                "count": self.group_a_count,
                "avg_performance": self.group_a_avg_performance,
            },
            "group_b": {
                "value": self.group_b_value,
                "count": self.group_b_count,
                "avg_performance": self.group_b_avg_performance,
            },
            "effect_size": self.effect_size,
            "confidence": self.confidence,
            "conclusion": self.conclusion,
        }


class GraphRAGNewsAnalyzer:
    """Finance-specific analysis built on top of core GraphRAG primitives."""

    def __init__(self):
        self.executives: Dict[str, ExecutiveProfile] = {}
        self.companies: Dict[str, CompanyPerformance] = {}
        self.knowledge_graph: KnowledgeGraph = KnowledgeGraph()

    @staticmethod
    def _hash_id(*parts: str) -> str:
        blob = "|".join(parts).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]

    def extract_executive_profiles(self, news_articles: List[Dict[str, Any]]) -> List[ExecutiveProfile]:
        """Extract basic executive profiles from article metadata.

        This is intentionally lightweight and deterministic; the "derivative" GraphRAG
        capability (entity linking / reasoning) is expected to be added by consumers
        when `GRAPHRAG_AVAILABLE` is true.
        """

        profiles: Dict[str, ExecutiveProfile] = {}

        for article in news_articles or []:
            # Heuristic: accept an explicit executives list if present
            execs = article.get("executives") or []
            for item in execs:
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                person_id = item.get("person_id") or self._hash_id(name.lower())
                profile = profiles.get(person_id)
                if profile is None:
                    profile = ExecutiveProfile(person_id=person_id, name=name)
                    profiles[person_id] = profile

                profile.news_mentions += 1
                gender = item.get("gender")
                if gender:
                    profile.gender = str(gender).lower()

                companies = item.get("companies")
                if isinstance(companies, list):
                    for c in companies:
                        if c and c not in profile.companies:
                            profile.companies.append(c)

        self.executives = profiles
        return list(profiles.values())

    def link_executives_to_performance(
        self,
        executives: List[ExecutiveProfile],
        companies: List[CompanyPerformance],
    ) -> List[Relationship]:
        relationships: List[Relationship] = []
        company_by_symbol = {c.symbol: c for c in companies}

        for exec_profile in executives:
            for company_symbol in exec_profile.companies:
                company = company_by_symbol.get(company_symbol)
                if company is None:
                    continue

                rel = Relationship(
                    relationship_id=self._hash_id(exec_profile.person_id, company.company_id, "exec_of"),
                    relationship_type="executive_of",
                    source_entity=exec_profile.to_entity(),
                    target_entity=company.to_entity(),
                    properties={"role": "executive"},
                )
                self.knowledge_graph.add_relationship(rel)
                relationships.append(rel)

        self.companies = {c.company_id: c for c in companies}
        return relationships

    def test_hypothesis(
        self,
        hypothesis: str,
        attribute_name: str,
        group_a_value: str,
        group_b_value: str,
    ) -> HypothesisTest:
        # Map exec -> avg performance across linked companies
        performance_by_exec: Dict[str, float] = {}
        for exec_profile in self.executives.values():
            if not exec_profile.companies:
                continue
            perf_values: List[float] = []
            for symbol in exec_profile.companies:
                # companies keyed by id; try by symbol
                company = next((c for c in self.companies.values() if c.symbol == symbol), None)
                if company:
                    perf_values.append(company.return_percentage)
            if perf_values:
                performance_by_exec[exec_profile.person_id] = sum(perf_values) / len(perf_values)

        def get_attr(exec_profile: ExecutiveProfile) -> str:
            if attribute_name == "gender":
                return exec_profile.gender
            return str(exec_profile.attributes.get(attribute_name, "unknown")).lower()

        group_a: List[float] = []
        group_b: List[float] = []

        for exec_profile in self.executives.values():
            perf = performance_by_exec.get(exec_profile.person_id)
            if perf is None:
                continue
            attr = get_attr(exec_profile)
            if attr == str(group_a_value).lower():
                group_a.append(perf)
            elif attr == str(group_b_value).lower():
                group_b.append(perf)

        group_a_avg = sum(group_a) / len(group_a) if group_a else 0.0
        group_b_avg = sum(group_b) / len(group_b) if group_b else 0.0
        effect = group_a_avg - group_b_avg

        # Heuristic confidence: more samples => higher confidence
        sample_count = len(group_a) + len(group_b)
        confidence = min(1.0, sample_count / 20.0) if sample_count else 0.0

        if confidence == 0.0:
            conclusion = "insufficient_data"
        elif effect > 0:
            conclusion = "supports_hypothesis"
        elif effect < 0:
            conclusion = "contradicts_hypothesis"
        else:
            conclusion = "no_effect_detected"

        return HypothesisTest(
            hypothesis=hypothesis,
            attribute_name=attribute_name,
            group_a_value=str(group_a_value).lower(),
            group_b_value=str(group_b_value).lower(),
            group_a_count=len(group_a),
            group_b_count=len(group_b),
            group_a_avg_performance=group_a_avg,
            group_b_avg_performance=group_b_avg,
            effect_size=effect,
            confidence=confidence,
            conclusion=conclusion,
        )

    def build_knowledge_graph(self) -> KnowledgeGraph:
        for exec_prof in self.executives.values():
            self.knowledge_graph.add_entity(exec_prof.to_entity())
        for company in self.companies.values():
            self.knowledge_graph.add_entity(company.to_entity())
        return self.knowledge_graph


def analyze_news_with_graphrag(
    *,
    news_articles: List[Dict[str, Any]],
    stock_data: List[Dict[str, Any]],
    analysis_type: str = "executive_performance",
    hypothesis: Optional[str] = None,
    attribute: Optional[str] = None,
    groups: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """High-level finance analysis entrypoint used by the CLI.

    This is a finance-layer derivative that *can* be enhanced by GraphRAG when
    optional deps exist, but still operates in stub mode otherwise.
    """

    if analysis_type != "executive_performance":
        return {
            "success": False,
            "error": f"Unsupported analysis_type: {analysis_type}",
            "supported": ["executive_performance"],
        }

    analyzer = GraphRAGNewsAnalyzer()

    executives = analyzer.extract_executive_profiles(news_articles)

    companies = [
        CompanyPerformance(
            company_id=item.get("company_id", item.get("symbol", "")) or GraphRAGNewsAnalyzer._hash_id(item.get("symbol", "")),
            symbol=item.get("symbol", ""),
            name=item.get("name", item.get("symbol", "")),
            return_percentage=float(item.get("return_percentage", 0.0) or 0.0),
            volatility=float(item.get("volatility", 0.0) or 0.0),
        )
        for item in (stock_data or [])
        if item.get("symbol")
    ]

    analyzer.companies = {c.company_id: c for c in companies}
    relationships = analyzer.link_executives_to_performance(executives, companies)

    if not hypothesis or not attribute or not groups:
        return {
            "success": True,
            "note": "No hypothesis parameters provided; returning extracted entities only.",
            "graphrag_available": GRAPHRAG_AVAILABLE,
            "executives_analyzed": len(executives),
            "companies_analyzed": len(companies),
            "relationships_found": len(relationships),
        }

    group_a = groups.get("A") if groups else None
    group_b = groups.get("B") if groups else None
    if group_a is None or group_b is None:
        return {"success": False, "error": "groups must include keys 'A' and 'B'"}

    test_result = analyzer.test_hypothesis(
        hypothesis=hypothesis,
        attribute_name=attribute,
        group_a_value=group_a,
        group_b_value=group_b,
    )

    kg = analyzer.build_knowledge_graph()

    return {
        "success": True,
        "graphrag_available": GRAPHRAG_AVAILABLE,
        "hypothesis_test": test_result.to_dict(),
        "executives_analyzed": len(executives),
        "companies_analyzed": len(companies),
        "relationships_found": len(relationships),
        "knowledge_graph": {"entities": len(getattr(kg, "entities", [])), "relationships": len(getattr(kg, "relationships", []))},
    }


def create_financial_knowledge_graph(
    *,
    news_articles: List[Dict[str, Any]],
    stock_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a simple knowledge graph from provided finance inputs."""

    analyzer = GraphRAGNewsAnalyzer()
    executives = analyzer.extract_executive_profiles(news_articles)
    companies = [
        CompanyPerformance(
            company_id=item.get("company_id", item.get("symbol", "")) or GraphRAGNewsAnalyzer._hash_id(item.get("symbol", "")),
            symbol=item.get("symbol", ""),
            name=item.get("name", item.get("symbol", "")),
            return_percentage=float(item.get("return_percentage", 0.0) or 0.0),
            volatility=float(item.get("volatility", 0.0) or 0.0),
        )
        for item in (stock_data or [])
        if item.get("symbol")
    ]
    analyzer.companies = {c.company_id: c for c in companies}
    analyzer.link_executives_to_performance(executives, companies)
    kg = analyzer.build_knowledge_graph()

    # For now return counts + minimal serialization (avoids huge payloads)
    return {
        "success": True,
        "graphrag_available": GRAPHRAG_AVAILABLE,
        "entities": len(getattr(kg, "entities", [])),
        "relationships": len(getattr(kg, "relationships", [])),
    }


# Backwards-compatible JSON-in/JSON-out wrappers (used by MCP tools)

def analyze_executive_performance(
    news_articles_json: str,
    stock_data_json: str,
    hypothesis: str,
    attribute: str,
    group_a: str,
    group_b: str,
) -> str:
    try:
        articles = json.loads(news_articles_json)
        stock_data = json.loads(stock_data_json)

        result = analyze_news_with_graphrag(
            news_articles=articles,
            stock_data=stock_data,
            analysis_type="executive_performance",
            hypothesis=hypothesis,
            attribute=attribute,
            groups={"A": group_a, "B": group_b},
        )

        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error("Executive performance analysis failed: %s", e, exc_info=True)
        return json.dumps({"success": False, "error": str(e)})


def extract_executive_profiles_from_archives(
    sources: str = "ap,reuters,bloomberg",
    start_date: str = "2020-01-01",
    end_date: str = "2024-01-01",
    min_mentions: int = 5,
) -> str:
    # Core implementation intentionally does not scrape by default.
    # Keep the placeholder contract for the MCP tool.
    return json.dumps(
        {
            "success": True,
            "note": "Placeholder: integrate with finance.news scraping for production.",
            "graphrag_available": GRAPHRAG_AVAILABLE,
            "sources": [s.strip() for s in sources.split(",") if s.strip()],
            "date_range": {"start": start_date, "end": end_date},
            "min_mentions": min_mentions,
            "profiles_found": 0,
        },
        indent=2,
    )


__all__ = [
    "ExecutiveProfile",
    "CompanyPerformance",
    "HypothesisTest",
    "GraphRAGNewsAnalyzer",
    "analyze_news_with_graphrag",
    "create_financial_knowledge_graph",
    "analyze_executive_performance",
    "extract_executive_profiles_from_archives",
]
