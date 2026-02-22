"""
Tests for CEC cognitive logic inference rules (cognitive.py).

Validates that all 13 cognitive rules fire correctly after the session-30 bug fix:
- cognitive.py: B/K/I/P/D rules (was broken: ProofResult.SUCCESS/FAILURE, .content attr,
  .operator vs .connective, .left/.right vs .formulas[0/1])

Test structure follows GIVEN-WHEN-THEN pattern matching session-29 temporal/deontic tests.
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    Atom,
    ConnectiveFormula,
    CognitiveFormula,
    LogicalConnective,
    CognitiveOperator,
    Sort,
    Variable,
    VariableTerm,
    AtomicFormula,
    Predicate,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.cognitive import (
    BeliefDistribution,
    KnowledgeImpliesBelief,
    BeliefMonotonicity,
    IntentionCommitment,
    BeliefConjunction,
    KnowledgeDistribution,
    IntentionMeansEnd,
    PerceptionImpliesKnowledge,
    BeliefNegation,
    KnowledgeConjunction,
    IntentionPersistence,
    BeliefRevision,
    KnowledgeMonotonicity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(name: str = "alice") -> VariableTerm:
    agent_sort = Sort("agent")
    return VariableTerm(Variable(name, agent_sort))


def atom(name: str) -> Atom:
    return Atom(name)


def conj(a, b) -> ConnectiveFormula:
    return ConnectiveFormula(LogicalConnective.AND, [a, b])


def impl(a, b) -> ConnectiveFormula:
    return ConnectiveFormula(LogicalConnective.IMPLIES, [a, b])


def neg(a) -> ConnectiveFormula:
    return ConnectiveFormula(LogicalConnective.NOT, [a])


def belief(agent, f) -> CognitiveFormula:
    return CognitiveFormula(CognitiveOperator.BELIEF, agent, f)


def knowledge(agent, f) -> CognitiveFormula:
    return CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent, f)


def intention(agent, f) -> CognitiveFormula:
    return CognitiveFormula(CognitiveOperator.INTENTION, agent, f)


def perception(agent, f) -> CognitiveFormula:
    return CognitiveFormula(CognitiveOperator.PERCEPTION, agent, f)


# ---------------------------------------------------------------------------
# BeliefDistribution: B(a, P∧Q) ⊢ B(a, P) ∧ B(a, Q)
# ---------------------------------------------------------------------------

class TestBeliefDistribution:
    def setup_method(self):
        self.rule = BeliefDistribution()
        self.agent = _make_agent()
        self.p = atom("raining")
        self.q = atom("wet")

    def test_name_is_nonempty(self):
        assert self.rule.name() == "BeliefDistribution"

    def test_can_apply_true_when_belief_with_conjunction(self):
        # GIVEN a belief with a conjunction as content
        b_pq = belief(self.agent, conj(self.p, self.q))
        # WHEN we check can_apply
        # THEN it returns True
        assert self.rule.can_apply([b_pq])

    def test_can_apply_false_for_simple_belief(self):
        # GIVEN a belief with a simple atom (no conjunction)
        b_p = belief(self.agent, self.p)
        # WHEN we check can_apply
        # THEN it returns False
        assert not self.rule.can_apply([b_p])

    def test_can_apply_false_for_empty_list(self):
        assert not self.rule.can_apply([])

    def test_can_apply_false_for_knowledge_with_conjunction(self):
        # Knowledge, not belief
        k_pq = knowledge(self.agent, conj(self.p, self.q))
        assert not self.rule.can_apply([k_pq])

    def test_apply_produces_two_beliefs(self):
        # GIVEN B(alice, P∧Q)
        b_pq = belief(self.agent, conj(self.p, self.q))
        # WHEN we apply the rule
        result = self.rule.apply([b_pq])
        # THEN we get [B(alice, P), B(alice, Q)]
        assert len(result) == 2
        assert all(isinstance(r, CognitiveFormula) for r in result)
        assert all(r.operator == CognitiveOperator.BELIEF for r in result)
        assert result[0].formula == self.p
        assert result[1].formula == self.q

    def test_apply_returns_empty_for_non_applicable(self):
        b_p = belief(self.agent, self.p)
        assert self.rule.apply([b_p]) == []


# ---------------------------------------------------------------------------
# KnowledgeImpliesBelief: K(a, P) ⊢ B(a, P)
# ---------------------------------------------------------------------------

class TestKnowledgeImpliesBelief:
    def setup_method(self):
        self.rule = KnowledgeImpliesBelief()
        self.agent = _make_agent()
        self.p = atom("fact")

    def test_name(self):
        assert self.rule.name() == "KnowledgeImpliesBelief"

    def test_can_apply_true_for_knowledge(self):
        assert self.rule.can_apply([knowledge(self.agent, self.p)])

    def test_can_apply_false_for_belief(self):
        assert not self.rule.can_apply([belief(self.agent, self.p)])

    def test_can_apply_false_for_empty(self):
        assert not self.rule.can_apply([])

    def test_apply_converts_knowledge_to_belief(self):
        # GIVEN K(alice, fact)
        k_p = knowledge(self.agent, self.p)
        # WHEN applied
        result = self.rule.apply([k_p])
        # THEN B(alice, fact)
        assert len(result) == 1
        assert isinstance(result[0], CognitiveFormula)
        assert result[0].operator == CognitiveOperator.BELIEF
        assert result[0].formula == self.p

    def test_apply_returns_empty_when_not_applicable(self):
        assert self.rule.apply([belief(self.agent, self.p)]) == []


# ---------------------------------------------------------------------------
# BeliefMonotonicity: B(a, P) ∧ (P→Q) ⊢ B(a, Q)
# ---------------------------------------------------------------------------

class TestBeliefMonotonicity:
    def setup_method(self):
        self.rule = BeliefMonotonicity()
        self.agent = _make_agent()
        self.p = atom("raining")
        self.q = atom("ground_wet")

    def test_name(self):
        assert self.rule.name() == "BeliefMonotonicity"

    def test_can_apply_true_with_belief_and_implication(self):
        b_p = belief(self.agent, self.p)
        p_impl_q = impl(self.p, self.q)
        assert self.rule.can_apply([b_p, p_impl_q])

    def test_can_apply_false_without_implication(self):
        b_p = belief(self.agent, self.p)
        assert not self.rule.can_apply([b_p])

    def test_can_apply_false_without_belief(self):
        p_impl_q = impl(self.p, self.q)
        assert not self.rule.can_apply([p_impl_q])

    def test_apply_derives_belief_in_consequent(self):
        # GIVEN B(alice, P) and P→Q
        b_p = belief(self.agent, self.p)
        p_impl_q = impl(self.p, self.q)
        # WHEN applied
        result = self.rule.apply([b_p, p_impl_q])
        # THEN B(alice, Q)
        assert len(result) == 1
        assert result[0].operator == CognitiveOperator.BELIEF
        assert result[0].formula == self.q

    def test_apply_returns_empty_when_antecedent_mismatch(self):
        # Belief is about Q but implication starts from P
        b_q = belief(self.agent, self.q)
        p_impl_q = impl(self.p, self.q)
        # P→Q but belief is B(Q), not B(P), so no match
        assert self.rule.apply([b_q, p_impl_q]) == []


# ---------------------------------------------------------------------------
# IntentionCommitment: I(a, P) ∧ B(a, P→Q) ⊢ I(a, Q)
# ---------------------------------------------------------------------------

class TestIntentionCommitment:
    def setup_method(self):
        self.rule = IntentionCommitment()
        self.agent = _make_agent()
        self.p = atom("go_to_store")
        self.q = atom("buy_milk")

    def test_name(self):
        assert self.rule.name() == "IntentionCommitment"

    def test_can_apply_true_with_intention_and_belief_impl(self):
        i_p = intention(self.agent, self.p)
        b_pq = belief(self.agent, impl(self.p, self.q))
        assert self.rule.can_apply([i_p, b_pq])

    def test_can_apply_false_without_intention(self):
        b_pq = belief(self.agent, impl(self.p, self.q))
        assert not self.rule.can_apply([b_pq])

    def test_can_apply_false_without_belief_implication(self):
        i_p = intention(self.agent, self.p)
        b_p = belief(self.agent, self.p)
        assert not self.rule.can_apply([i_p, b_p])

    def test_apply_derives_intention_in_consequent(self):
        # GIVEN I(alice, go_to_store) and B(alice, go_to_store→buy_milk)
        i_p = intention(self.agent, self.p)
        b_pq = belief(self.agent, impl(self.p, self.q))
        # WHEN applied
        result = self.rule.apply([i_p, b_pq])
        # THEN I(alice, buy_milk)
        assert len(result) == 1
        assert result[0].operator == CognitiveOperator.INTENTION
        assert result[0].formula == self.q

    def test_apply_returns_empty_when_antecedent_mismatch(self):
        i_p = intention(self.agent, self.p)
        # belief has Q→P (not P→Q), so antecedent Q doesn't match intention P
        b_qp = belief(self.agent, impl(self.q, self.p))
        assert self.rule.apply([i_p, b_qp]) == []


# ---------------------------------------------------------------------------
# BeliefConjunction: B(a, P) ∧ B(a, Q) ⊢ B(a, P∧Q)
# ---------------------------------------------------------------------------

class TestBeliefConjunction:
    def setup_method(self):
        self.rule = BeliefConjunction()
        self.agent = _make_agent()
        self.p = atom("raining")
        self.q = atom("cold")

    def test_name(self):
        assert self.rule.name() == "BeliefConjunction"

    def test_can_apply_true_with_two_beliefs(self):
        assert self.rule.can_apply([belief(self.agent, self.p), belief(self.agent, self.q)])

    def test_can_apply_false_with_one_belief(self):
        assert not self.rule.can_apply([belief(self.agent, self.p)])

    def test_can_apply_false_with_empty(self):
        assert not self.rule.can_apply([])

    def test_apply_produces_conjunction_belief(self):
        # GIVEN B(alice, raining) and B(alice, cold)
        b_p = belief(self.agent, self.p)
        b_q = belief(self.agent, self.q)
        # WHEN applied
        result = self.rule.apply([b_p, b_q])
        # THEN B(alice, raining∧cold)
        assert len(result) == 1
        assert result[0].operator == CognitiveOperator.BELIEF
        assert isinstance(result[0].formula, ConnectiveFormula)
        assert result[0].formula.connective == LogicalConnective.AND

    def test_apply_empty_when_no_beliefs(self):
        assert self.rule.apply([atom("x")]) == []


# ---------------------------------------------------------------------------
# KnowledgeDistribution: K(a, P∧Q) ⊢ K(a, P) ∧ K(a, Q)
# ---------------------------------------------------------------------------

class TestKnowledgeDistribution:
    def setup_method(self):
        self.rule = KnowledgeDistribution()
        self.agent = _make_agent()
        self.p = atom("fact_a")
        self.q = atom("fact_b")

    def test_name(self):
        assert self.rule.name() == "KnowledgeDistribution"

    def test_can_apply_true_for_knowledge_with_conjunction(self):
        k_pq = knowledge(self.agent, conj(self.p, self.q))
        assert self.rule.can_apply([k_pq])

    def test_can_apply_false_for_simple_knowledge(self):
        assert not self.rule.can_apply([knowledge(self.agent, self.p)])

    def test_apply_produces_two_knowledge_formulas(self):
        # GIVEN K(alice, P∧Q)
        k_pq = knowledge(self.agent, conj(self.p, self.q))
        # WHEN applied
        result = self.rule.apply([k_pq])
        # THEN [K(alice, P), K(alice, Q)]
        assert len(result) == 2
        assert all(r.operator == CognitiveOperator.KNOWLEDGE for r in result)
        assert result[0].formula == self.p
        assert result[1].formula == self.q

    def test_apply_empty_when_not_applicable(self):
        assert self.rule.apply([knowledge(self.agent, self.p)]) == []


# ---------------------------------------------------------------------------
# IntentionMeansEnd: I(a, goal) ∧ B(a, action→goal) ⊢ I(a, action)
# ---------------------------------------------------------------------------

class TestIntentionMeansEnd:
    def setup_method(self):
        self.rule = IntentionMeansEnd()
        self.agent = _make_agent()
        self.action = atom("take_bus")
        self.goal = atom("arrive_work")

    def test_name(self):
        assert self.rule.name() == "IntentionMeansEnd"

    def test_can_apply_true(self):
        i_goal = intention(self.agent, self.goal)
        b_means = belief(self.agent, impl(self.action, self.goal))
        assert self.rule.can_apply([i_goal, b_means])

    def test_can_apply_false_without_intention(self):
        b_means = belief(self.agent, impl(self.action, self.goal))
        assert not self.rule.can_apply([b_means])

    def test_apply_derives_intention_for_action(self):
        # GIVEN I(alice, arrive_work) and B(alice, take_bus→arrive_work)
        i_goal = intention(self.agent, self.goal)
        b_means = belief(self.agent, impl(self.action, self.goal))
        # WHEN applied
        result = self.rule.apply([i_goal, b_means])
        # THEN I(alice, take_bus)
        assert len(result) == 1
        assert result[0].operator == CognitiveOperator.INTENTION
        assert result[0].formula == self.action

    def test_apply_empty_when_goal_does_not_match(self):
        # Belief leads to different goal
        other = atom("other_goal")
        i_goal = intention(self.agent, self.goal)
        b_means = belief(self.agent, impl(self.action, other))
        assert self.rule.apply([i_goal, b_means]) == []


# ---------------------------------------------------------------------------
# PerceptionImpliesKnowledge: P(a, φ) ⊢ K(a, φ)
# ---------------------------------------------------------------------------

class TestPerceptionImpliesKnowledge:
    def setup_method(self):
        self.rule = PerceptionImpliesKnowledge()
        self.agent = _make_agent()
        self.p = atom("light_is_on")

    def test_name(self):
        assert self.rule.name() == "PerceptionImpliesKnowledge"

    def test_can_apply_true_for_perception(self):
        assert self.rule.can_apply([perception(self.agent, self.p)])

    def test_can_apply_false_for_belief(self):
        assert not self.rule.can_apply([belief(self.agent, self.p)])

    def test_can_apply_false_for_empty(self):
        assert not self.rule.can_apply([])

    def test_apply_converts_perception_to_knowledge(self):
        # GIVEN P(alice, light_is_on)
        per_p = perception(self.agent, self.p)
        # WHEN applied
        result = self.rule.apply([per_p])
        # THEN K(alice, light_is_on)
        assert len(result) == 1
        assert isinstance(result[0], CognitiveFormula)
        assert result[0].operator == CognitiveOperator.KNOWLEDGE
        assert result[0].formula == self.p

    def test_apply_empty_when_not_applicable(self):
        assert self.rule.apply([belief(self.agent, self.p)]) == []


# ---------------------------------------------------------------------------
# BeliefNegation: B(a, ¬P) ⊢ ¬B(a, P)
# ---------------------------------------------------------------------------

class TestBeliefNegation:
    def setup_method(self):
        self.rule = BeliefNegation()
        self.agent = _make_agent()
        self.p = atom("raining")

    def test_name(self):
        assert self.rule.name() == "BeliefNegation"

    def test_can_apply_true_for_belief_in_negation(self):
        b_not_p = belief(self.agent, neg(self.p))
        assert self.rule.can_apply([b_not_p])

    def test_can_apply_false_for_belief_without_negation(self):
        b_p = belief(self.agent, self.p)
        assert not self.rule.can_apply([b_p])

    def test_can_apply_false_for_empty(self):
        assert not self.rule.can_apply([])

    def test_apply_produces_negated_belief(self):
        # GIVEN B(alice, ¬raining)
        b_not_p = belief(self.agent, neg(self.p))
        # WHEN applied
        result = self.rule.apply([b_not_p])
        # THEN ¬B(alice, raining) = ConnectiveFormula(NOT, [B(alice, raining)])
        assert len(result) == 1
        assert isinstance(result[0], ConnectiveFormula)
        assert result[0].connective == LogicalConnective.NOT
        assert len(result[0].formulas) == 1
        inner = result[0].formulas[0]
        assert isinstance(inner, CognitiveFormula)
        assert inner.operator == CognitiveOperator.BELIEF
        assert inner.formula == self.p

    def test_apply_empty_when_not_applicable(self):
        b_p = belief(self.agent, self.p)
        assert self.rule.apply([b_p]) == []


# ---------------------------------------------------------------------------
# KnowledgeConjunction: K(a, P) ∧ K(a, Q) ⊢ K(a, P∧Q)
# ---------------------------------------------------------------------------

class TestKnowledgeConjunction:
    def setup_method(self):
        self.rule = KnowledgeConjunction()
        self.agent = _make_agent()
        self.p = atom("fact_x")
        self.q = atom("fact_y")

    def test_name(self):
        assert self.rule.name() == "KnowledgeConjunction"

    def test_can_apply_true_with_two_knowledge_formulas(self):
        assert self.rule.can_apply([knowledge(self.agent, self.p), knowledge(self.agent, self.q)])

    def test_can_apply_false_with_one_knowledge(self):
        assert not self.rule.can_apply([knowledge(self.agent, self.p)])

    def test_apply_produces_conjunction_knowledge(self):
        # GIVEN K(alice, X) and K(alice, Y)
        k_p = knowledge(self.agent, self.p)
        k_q = knowledge(self.agent, self.q)
        # WHEN applied
        result = self.rule.apply([k_p, k_q])
        # THEN K(alice, X∧Y)
        assert len(result) == 1
        assert result[0].operator == CognitiveOperator.KNOWLEDGE
        assert isinstance(result[0].formula, ConnectiveFormula)
        assert result[0].formula.connective == LogicalConnective.AND

    def test_apply_empty_when_not_applicable(self):
        assert self.rule.apply([knowledge(self.agent, self.p)]) == []


# ---------------------------------------------------------------------------
# IntentionPersistence: I(a, P) ∧ ¬B(a, P) ⊢ I(a, P)
# ---------------------------------------------------------------------------

class TestIntentionPersistence:
    def setup_method(self):
        self.rule = IntentionPersistence()
        self.agent = _make_agent()
        self.p = atom("go_to_store")

    def test_name(self):
        assert self.rule.name() == "IntentionPersistence"

    def test_can_apply_true_with_intention_and_negated_belief(self):
        i_p = intention(self.agent, self.p)
        b_p = belief(self.agent, self.p)
        not_belief = neg(b_p)
        assert self.rule.can_apply([i_p, not_belief])

    def test_can_apply_false_without_intention(self):
        b_p = belief(self.agent, self.p)
        not_belief = neg(b_p)
        assert not self.rule.can_apply([not_belief])

    def test_can_apply_false_without_negated_belief(self):
        i_p = intention(self.agent, self.p)
        assert not self.rule.can_apply([i_p])

    def test_apply_persists_intention(self):
        # GIVEN I(alice, go_to_store) and ¬B(alice, go_to_store)
        i_p = intention(self.agent, self.p)
        b_p = belief(self.agent, self.p)
        not_belief = neg(b_p)
        # WHEN applied
        result = self.rule.apply([i_p, not_belief])
        # THEN I(alice, go_to_store) persists
        assert len(result) == 1
        assert result[0].operator == CognitiveOperator.INTENTION
        assert result[0].formula == self.p

    def test_apply_empty_when_not_applicable(self):
        i_p = intention(self.agent, self.p)
        assert self.rule.apply([i_p]) == []


# ---------------------------------------------------------------------------
# BeliefRevision: B(a, P) ∧ P(a, ¬P) ⊢ B(a, ¬P)
# ---------------------------------------------------------------------------

class TestBeliefRevision:
    def setup_method(self):
        self.rule = BeliefRevision()
        self.agent = _make_agent()
        self.p = atom("light_off")

    def test_name(self):
        assert self.rule.name() == "BeliefRevision"

    def test_can_apply_true_with_belief_and_perception(self):
        b_p = belief(self.agent, self.p)
        per_not_p = perception(self.agent, neg(self.p))
        assert self.rule.can_apply([b_p, per_not_p])

    def test_can_apply_false_without_belief(self):
        per_not_p = perception(self.agent, neg(self.p))
        assert not self.rule.can_apply([per_not_p])

    def test_can_apply_false_without_perception(self):
        b_p = belief(self.agent, self.p)
        assert not self.rule.can_apply([b_p])

    def test_apply_revises_belief_to_negation(self):
        # GIVEN B(alice, light_off) and P(alice, ¬light_off)
        b_p = belief(self.agent, self.p)
        per_not_p = perception(self.agent, neg(self.p))
        # WHEN applied
        result = self.rule.apply([b_p, per_not_p])
        # THEN B(alice, ¬light_off) — belief revised to negation
        assert len(result) == 1
        assert result[0].operator == CognitiveOperator.BELIEF
        assert isinstance(result[0].formula, ConnectiveFormula)
        assert result[0].formula.connective == LogicalConnective.NOT

    def test_apply_empty_when_perception_doesnt_negate_belief(self):
        # Belief is about P, perception is about Q (not ¬P)
        b_p = belief(self.agent, self.p)
        other = atom("other")
        per_other = perception(self.agent, neg(other))
        assert self.rule.apply([b_p, per_other]) == []


# ---------------------------------------------------------------------------
# KnowledgeMonotonicity: K(a, P) ∧ (P→Q) ⊢ K(a, Q)
# ---------------------------------------------------------------------------

class TestKnowledgeMonotonicity:
    def setup_method(self):
        self.rule = KnowledgeMonotonicity()
        self.agent = _make_agent()
        self.p = atom("socrates_is_human")
        self.q = atom("socrates_is_mortal")

    def test_name(self):
        assert self.rule.name() == "KnowledgeMonotonicity"

    def test_can_apply_true_with_knowledge_and_implication(self):
        k_p = knowledge(self.agent, self.p)
        p_impl_q = impl(self.p, self.q)
        assert self.rule.can_apply([k_p, p_impl_q])

    def test_can_apply_false_without_knowledge(self):
        p_impl_q = impl(self.p, self.q)
        assert not self.rule.can_apply([p_impl_q])

    def test_can_apply_false_without_implication(self):
        k_p = knowledge(self.agent, self.p)
        assert not self.rule.can_apply([k_p])

    def test_apply_derives_knowledge_in_consequent(self):
        # GIVEN K(alice, socrates_is_human) and socrates_is_human→socrates_is_mortal
        k_p = knowledge(self.agent, self.p)
        p_impl_q = impl(self.p, self.q)
        # WHEN applied
        result = self.rule.apply([k_p, p_impl_q])
        # THEN K(alice, socrates_is_mortal)
        assert len(result) == 1
        assert result[0].operator == CognitiveOperator.KNOWLEDGE
        assert result[0].formula == self.q

    def test_apply_empty_when_antecedent_mismatch(self):
        # Implication starts from Q but knowledge is about P (reversed)
        k_p = knowledge(self.agent, self.p)
        q_impl_p = impl(self.q, self.p)  # wrong direction
        assert self.rule.apply([k_p, q_impl_p]) == []


# ---------------------------------------------------------------------------
# Chain tests: composing multiple rules
# ---------------------------------------------------------------------------

class TestCognitiveRuleChains:
    def setup_method(self):
        self.agent = _make_agent()

    def test_perception_to_knowledge_to_belief_chain(self):
        """P(a, φ) → K(a, φ) → B(a, φ) via two rules."""
        p = atom("light_on")
        per = perception(self.agent, p)

        pik = PerceptionImpliesKnowledge()
        kib = KnowledgeImpliesBelief()

        # Step 1: Perception → Knowledge
        step1 = pik.apply([per])
        assert len(step1) == 1
        assert step1[0].operator == CognitiveOperator.KNOWLEDGE

        # Step 2: Knowledge → Belief
        step2 = kib.apply(step1)
        assert len(step2) == 1
        assert step2[0].operator == CognitiveOperator.BELIEF
        assert step2[0].formula == p

    def test_belief_monotonicity_chain(self):
        """B(a, P) + P→Q + Q→R → B(a, R) via two applications."""
        p = atom("it_rains")
        q = atom("ground_wet")
        r = atom("road_slippery")

        b_p = belief(self.agent, p)
        p_impl_q = impl(p, q)
        q_impl_r = impl(q, r)

        bm = BeliefMonotonicity()

        # Step 1: B(a, P) + P→Q → B(a, Q)
        step1 = bm.apply([b_p, p_impl_q])
        assert step1[0].formula == q

        # Step 2: B(a, Q) + Q→R → B(a, R)
        step2 = bm.apply([step1[0], q_impl_r])
        assert step2[0].formula == r

    def test_knowledge_distribution_then_implication(self):
        """K(a, P∧Q) → [K(a,P), K(a,Q)] → K(a,R) via monotonicity."""
        p = atom("x")
        q = atom("y")
        r = atom("z")

        k_pq = knowledge(self.agent, conj(p, q))
        p_impl_r = impl(p, r)

        kd = KnowledgeDistribution()
        km = KnowledgeMonotonicity()

        step1 = kd.apply([k_pq])
        assert len(step1) == 2

        # Use K(a, P) with P→R to get K(a, R)
        step2 = km.apply([step1[0], p_impl_r])
        assert len(step2) == 1
        assert step2[0].formula == r

    def test_intention_commitment_then_means_end(self):
        """I(a, P) + B(a, P→Q) → I(a, Q) then I(a, Q) + B(a, R→Q) → I(a, R)."""
        p = atom("goal_a")
        q = atom("goal_b")
        r = atom("action")

        i_p = intention(self.agent, p)
        b_pq = belief(self.agent, impl(p, q))
        b_rq = belief(self.agent, impl(r, q))

        ic = IntentionCommitment()
        ime = IntentionMeansEnd()

        # Step 1: I(a, P) + B(a, P→Q) → I(a, Q)
        step1 = ic.apply([i_p, b_pq])
        assert step1[0].formula == q

        # Step 2: I(a, Q) + B(a, R→Q) → I(a, R) (means-end)
        step2 = ime.apply([step1[0], b_rq])
        assert len(step2) == 1
        assert step2[0].formula == r


# ---------------------------------------------------------------------------
# Export / name uniqueness tests
# ---------------------------------------------------------------------------

class TestCognitiveRulesExports:
    def test_all_thirteen_rules_importable(self):
        rules = [
            BeliefDistribution, KnowledgeImpliesBelief, BeliefMonotonicity,
            IntentionCommitment, BeliefConjunction, KnowledgeDistribution,
            IntentionMeansEnd, PerceptionImpliesKnowledge, BeliefNegation,
            KnowledgeConjunction, IntentionPersistence, BeliefRevision,
            KnowledgeMonotonicity,
        ]
        assert len(rules) == 13

    def test_all_rule_names_are_unique(self):
        agent = _make_agent()
        rules = [
            BeliefDistribution(), KnowledgeImpliesBelief(), BeliefMonotonicity(),
            IntentionCommitment(), BeliefConjunction(), KnowledgeDistribution(),
            IntentionMeansEnd(), PerceptionImpliesKnowledge(), BeliefNegation(),
            KnowledgeConjunction(), IntentionPersistence(), BeliefRevision(),
            KnowledgeMonotonicity(),
        ]
        names = [r.name() for r in rules]
        assert len(set(names)) == 13

    def test_all_rules_in_module_all(self):
        import ipfs_datasets_py.logic.CEC.native.inference_rules.cognitive as cog_mod
        all_names = cog_mod.__all__
        assert "BeliefDistribution" in all_names
        assert "KnowledgeImpliesBelief" in all_names
        assert "BeliefMonotonicity" in all_names
        assert "IntentionCommitment" in all_names
        assert "BeliefConjunction" in all_names
        assert "KnowledgeDistribution" in all_names
        assert "IntentionMeansEnd" in all_names
        assert "PerceptionImpliesKnowledge" in all_names
        assert "BeliefNegation" in all_names
        assert "KnowledgeConjunction" in all_names
        assert "IntentionPersistence" in all_names
        assert "BeliefRevision" in all_names
        assert "KnowledgeMonotonicity" in all_names
        assert len(all_names) == 13

    def test_perception_operator_is_in_enum(self):
        from ipfs_datasets_py.logic.CEC.native.dcec_types import CognitiveOperator
        assert CognitiveOperator.PERCEPTION is not None
        assert CognitiveOperator.PERCEPTION.value == "P"

    def test_all_rules_can_apply_returns_bool(self):
        agent = _make_agent()
        p = atom("p")
        rules = [
            BeliefDistribution(), KnowledgeImpliesBelief(), BeliefMonotonicity(),
            IntentionCommitment(), BeliefConjunction(), KnowledgeDistribution(),
            IntentionMeansEnd(), PerceptionImpliesKnowledge(), BeliefNegation(),
            KnowledgeConjunction(), IntentionPersistence(), BeliefRevision(),
            KnowledgeMonotonicity(),
        ]
        for rule in rules:
            result = rule.can_apply([p])
            assert isinstance(result, bool), f"{rule.name()}.can_apply must return bool"

    def test_all_rules_apply_returns_list(self):
        agent = _make_agent()
        p = atom("p")
        rules = [
            BeliefDistribution(), KnowledgeImpliesBelief(), BeliefMonotonicity(),
            IntentionCommitment(), BeliefConjunction(), KnowledgeDistribution(),
            IntentionMeansEnd(), PerceptionImpliesKnowledge(), BeliefNegation(),
            KnowledgeConjunction(), IntentionPersistence(), BeliefRevision(),
            KnowledgeMonotonicity(),
        ]
        for rule in rules:
            result = rule.apply([p])
            assert isinstance(result, list), f"{rule.name()}.apply must return List[Formula]"
