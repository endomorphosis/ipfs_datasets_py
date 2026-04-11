from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
from ipfs_datasets_py.logic.types import (
    DeonticFormula,
    DeonticOperator,
    DeonticRuleSet,
    LegalAgent,
    LegalContext,
)


def test_query_engine_builds_graph_conflict_summary_and_support_map():
    agent = LegalAgent(identifier="agency:hacc", name="HACC", agent_type="agency")
    context = LegalContext(applicable_law="24 C.F.R. 982.555", precedents=["Goldberg v. Kelly"])
    rule_set = DeonticRuleSet(
        name="hearing-rights",
        formulas=[
            DeonticFormula(
                operator=DeonticOperator.OBLIGATION,
                proposition="grant informal review",
                agent=agent,
                conditions=["requested review", "notice sent"],
                legal_context=context,
                confidence=0.9,
                source_text="Agency must grant informal review when requested.",
            ),
            DeonticFormula(
                operator=DeonticOperator.PROHIBITION,
                proposition="grant informal review",
                agent=agent,
                conditions=["deadline missed", "notice sent"],
                legal_context=context,
                confidence=0.8,
                source_text="Agency may not grant review after deadline.",
            ),
        ],
    )
    engine = DeonticQueryEngine(rule_set=rule_set, enable_rate_limiting=False, enable_validation=False)

    graph = engine.build_deontic_graph()
    summary = engine.summarize_graph_conflicts()
    support_map = engine.build_support_map(
        fact_catalog={
            "fact:requested-review:1:1": {"predicate": "requested review", "status": "verified", "source_ids": ["email:1"]},
            "fact:notice-sent:1:2": {"predicate": "notice sent", "status": "verified", "source_ids": ["notice:1"]},
        },
        filing_map={
            rule_set.formulas[0].formula_id: [
                {"filing_id": "motion:show-cause", "filing_type": "motion", "proposition": "Agency had a duty to grant review."}
            ]
        },
    )

    assert graph.summary()["total_rules"] == 2
    assert summary["graph_conflict_count"] == 1
    assert summary["source_gap_summary"]["rule_count"] == 2
    assert support_map["entry_count"] == 2
