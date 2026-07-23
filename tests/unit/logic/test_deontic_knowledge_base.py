from datetime import datetime

from ipfs_datasets_py.logic.deontic import (
    Action,
    Conjunction,
    DeonticKnowledgeBase,
    DeonticStatement,
    KnowledgeDeonticModality,
    Party,
    Predicate,
    TimeInterval,
)


def test_deontic_knowledge_base_infers_and_checks_compliance():
    kb = DeonticKnowledgeBase()
    authority = Party(name="Housing Authority", role="agency", entity_id="agency:hacc")
    tenant = Party(name="Tenant", role="resident", entity_id="resident:1")
    action = Action(verb="provide", object_noun="informal review", action_id="action:review")
    statement = DeonticStatement(
        modality=KnowledgeDeonticModality.OBLIGATORY,
        actor=authority,
        action=action,
        recipient=tenant,
        time_interval=TimeInterval(start=datetime(2026, 2, 13), duration_days=30),
    )
    kb.add_rule(Predicate("notice_served", (authority, tenant)), statement)
    kb.add_fact(f"notice_served({authority}, {tenant})")

    inferred = kb.infer_statements()
    compliant, reason = kb.check_compliance(authority, action, datetime(2026, 2, 20))

    assert statement in inferred
    assert compliant is True
    assert "complies with obligation" in reason


def test_predicate_conjunction_evaluates_against_model():
    condition = Conjunction(
        Predicate("requested_review", ("tenant_1",)),
        Predicate("notice_sent", ("tenant_1",)),
    )

    assert condition.evaluate({"requested_review(tenant_1)": True, "notice_sent(tenant_1)": True}) is True
