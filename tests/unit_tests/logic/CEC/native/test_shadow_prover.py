"""
Tests for ShadowProver modal logic theorem prover.

Following GIVEN-WHEN-THEN format for clear test structure.
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.shadow_prover import (
    KProver, S4Prover, S5Prover, CognitiveCalculusProver,
    ModalLogic, ProofStatus, ProofStep, ProofTree, ProblemFile,
    ModalOperator, ProblemReader, create_prover, create_cognitive_prover
)


class TestModalLogicEnum:
    """Test suite for ModalLogic enum."""
    
    def test_modal_logic_values(self):
        """
        GIVEN: ModalLogic enum
        WHEN: Accessing enum values
        THEN: Should have all expected modal logics
        """
        # GIVEN / WHEN / THEN
        assert ModalLogic.K.value == "K"
        assert ModalLogic.T.value == "T"
        assert ModalLogic.S4.value == "S4"
        assert ModalLogic.S5.value == "S5"
        assert ModalLogic.D.value == "D"
        assert ModalLogic.LP.value == "LP"


class TestProofStep:
    """Test suite for ProofStep class."""
    
    def test_proof_step_creation(self):
        """
        GIVEN: ProofStep parameters
        WHEN: Creating a proof step
        THEN: All fields should be correctly set
        """
        # GIVEN / WHEN
        step = ProofStep(
            rule_name="Modus Ponens",
            premises=["P", "P→Q"],
            conclusion="Q",
            justification="From P and P→Q, derive Q"
        )
        
        # THEN
        assert step.rule_name == "Modus Ponens"
        assert len(step.premises) == 2
        assert step.conclusion == "Q"
        assert "derive Q" in step.justification
    
    def test_proof_step_str(self):
        """
        GIVEN: A proof step
        WHEN: Converting to string
        THEN: Should produce readable format
        """
        # GIVEN
        step = ProofStep(
            rule_name="MP",
            premises=["A", "A→B"],
            conclusion="B"
        )
        
        # WHEN
        str_repr = str(step)
        
        # THEN
        assert "MP" in str_repr
        assert "⊢" in str_repr


class TestProofTree:
    """Test suite for ProofTree class."""
    
    def test_proof_tree_creation(self):
        """
        GIVEN: ProofTree parameters
        WHEN: Creating a proof tree
        THEN: Should initialize correctly
        """
        # GIVEN / WHEN
        tree = ProofTree(
            goal="P→P",
            steps=[],
            status=ProofStatus.SUCCESS,
            logic=ModalLogic.K
        )
        
        # THEN
        assert tree.goal == "P→P"
        assert len(tree.steps) == 0
        assert tree.status == ProofStatus.SUCCESS
        assert tree.logic == ModalLogic.K
    
    def test_proof_tree_is_successful(self):
        """
        GIVEN: Proof trees with different statuses
        WHEN: Checking if successful
        THEN: Should return correct boolean
        """
        # GIVEN
        success_tree = ProofTree("P", [], ProofStatus.SUCCESS, ModalLogic.K)
        failure_tree = ProofTree("P", [], ProofStatus.FAILURE, ModalLogic.K)
        
        # WHEN / THEN
        assert success_tree.is_successful() is True
        assert failure_tree.is_successful() is False
    
    def test_proof_tree_get_depth(self):
        """
        GIVEN: A proof tree with steps
        WHEN: Getting the depth
        THEN: Should return number of steps
        """
        # GIVEN
        steps = [
            ProofStep("Rule1", [], "A"),
            ProofStep("Rule2", ["A"], "B"),
            ProofStep("Rule3", ["B"], "C"),
        ]
        tree = ProofTree("C", steps, ProofStatus.SUCCESS, ModalLogic.K)
        
        # WHEN
        depth = tree.get_depth()
        
        # THEN
        assert depth == 3


class TestProblemFile:
    """Test suite for ProblemFile class."""
    
    def test_problem_file_creation(self):
        """
        GIVEN: Problem file parameters
        WHEN: Creating a problem file
        THEN: Should initialize correctly
        """
        # GIVEN / WHEN
        problem = ProblemFile(
            name="test_problem",
            logic=ModalLogic.S4,
            assumptions=["A", "A→B"],
            goals=["B"]
        )
        
        # THEN
        assert problem.name == "test_problem"
        assert problem.logic == ModalLogic.S4
        assert len(problem.assumptions) == 2
        assert len(problem.goals) == 1


class TestKProver:
    """Test suite for K modal logic prover."""
    
    def test_k_prover_initialization(self):
        """
        GIVEN: KProver class
        WHEN: Initializing a K prover
        THEN: Should set up for K logic
        """
        # GIVEN / WHEN
        prover = KProver()
        
        # THEN
        assert prover.logic == ModalLogic.K
        assert len(prover.proof_cache) == 0
        assert prover.statistics["proofs_attempted"] == 0
    
    def test_k_prover_prove_basic(self):
        """
        GIVEN: A K prover and a simple goal
        WHEN: Attempting to prove the goal
        THEN: Should return a proof tree
        """
        # GIVEN
        prover = KProver()
        goal = "P→P"  # Tautology
        
        # WHEN
        proof = prover.prove(goal)
        
        # THEN
        assert proof is not None
        assert proof.goal == goal
        assert proof.logic == ModalLogic.K
        assert prover.statistics["proofs_attempted"] == 1
    
    def test_k_prover_prove_with_assumptions(self):
        """
        GIVEN: A K prover with assumptions
        WHEN: Proving a goal from assumptions
        THEN: Should attempt proof with assumptions
        """
        # GIVEN
        prover = KProver()
        goal = "Q"
        assumptions = ["P", "P→Q"]
        
        # WHEN
        proof = prover.prove(goal, assumptions)
        
        # THEN
        assert proof.goal == goal
    
    def test_k_prover_prove_problem(self):
        """
        GIVEN: A K prover and a problem file
        WHEN: Proving all goals in the problem
        THEN: Should return list of proof trees
        """
        # GIVEN
        prover = KProver()
        problem = ProblemFile(
            name="test",
            logic=ModalLogic.K,
            assumptions=["P"],
            goals=["P", "P∨Q"]
        )
        
        # WHEN
        proofs = prover.prove_problem(problem)
        
        # THEN
        assert len(proofs) == 2
        assert all(isinstance(p, ProofTree) for p in proofs)


class TestS4Prover:
    """Test suite for S4 modal logic prover."""
    
    def test_s4_prover_initialization(self):
        """
        GIVEN: S4Prover class
        WHEN: Initializing an S4 prover
        THEN: Should set up for S4 logic
        """
        # GIVEN / WHEN
        prover = S4Prover()
        
        # THEN
        assert prover.logic == ModalLogic.S4
    
    def test_s4_prover_prove(self):
        """
        GIVEN: An S4 prover
        WHEN: Attempting to prove a goal
        THEN: Should return a proof tree
        """
        # GIVEN
        prover = S4Prover()
        goal = "□P→P"  # T axiom (reflexivity)
        
        # WHEN
        proof = prover.prove(goal)
        
        # THEN
        assert proof is not None
        assert proof.logic == ModalLogic.S4


class TestS5Prover:
    """Test suite for S5 modal logic prover."""
    
    def test_s5_prover_initialization(self):
        """
        GIVEN: S5Prover class
        WHEN: Initializing an S5 prover
        THEN: Should set up for S5 logic
        """
        # GIVEN / WHEN
        prover = S5Prover()
        
        # THEN
        assert prover.logic == ModalLogic.S5
    
    def test_s5_prover_prove(self):
        """
        GIVEN: An S5 prover
        WHEN: Attempting to prove a goal
        THEN: Should return a proof tree
        """
        # GIVEN
        prover = S5Prover()
        goal = "◇P→□◇P"  # 5 axiom (symmetry)
        
        # WHEN
        proof = prover.prove(goal)
        
        # THEN
        assert proof is not None
        assert proof.logic == ModalLogic.S5


class TestCognitiveCalculusProver:
    """Test suite for cognitive calculus prover."""
    
    def test_cognitive_prover_initialization(self):
        """
        GIVEN: CognitiveCalculusProver class
        WHEN: Initializing a cognitive calculus prover
        THEN: Should set up with cognitive axioms
        """
        # GIVEN / WHEN
        prover = CognitiveCalculusProver()
        
        # THEN
        assert prover.logic == ModalLogic.S5  # Based on S5
        assert len(prover.cognitive_axioms) > 0
        assert "K_distribution" in prover.cognitive_axioms
        assert "B_distribution" in prover.cognitive_axioms
    
    def test_cognitive_prover_has_knowledge_axioms(self):
        """
        GIVEN: A cognitive calculus prover
        WHEN: Checking for knowledge axioms
        THEN: Should have standard knowledge axioms
        """
        # GIVEN
        prover = CognitiveCalculusProver()
        
        # WHEN / THEN
        assert "K_truth" in prover.cognitive_axioms  # KP → P
        assert "K_positive_introspection" in prover.cognitive_axioms  # KP → KKP
        assert "K_negative_introspection" in prover.cognitive_axioms
    
    def test_cognitive_prover_has_belief_axioms(self):
        """
        GIVEN: A cognitive calculus prover
        WHEN: Checking for belief axioms
        THEN: Should have belief-related axioms
        """
        # GIVEN
        prover = CognitiveCalculusProver()
        
        # WHEN / THEN
        assert "B_distribution" in prover.cognitive_axioms
        assert "belief_revision" in prover.cognitive_axioms
    
    def test_cognitive_prover_prove(self):
        """
        GIVEN: A cognitive calculus prover
        WHEN: Proving a cognitive formula
        THEN: Should return proof tree with cognitive metadata
        """
        # GIVEN
        prover = CognitiveCalculusProver()
        goal = "K(P→Q) → (KP→KQ)"  # K distribution
        
        # WHEN
        proof = prover.prove(goal)
        
        # THEN
        assert proof is not None
        assert "axioms" in proof.metadata


class TestProverStatistics:
    """Test suite for prover statistics."""
    
    def test_prover_tracks_attempts(self):
        """
        GIVEN: A prover
        WHEN: Making multiple proof attempts
        THEN: Should track the number of attempts
        """
        # GIVEN
        prover = KProver()
        
        # WHEN
        prover.prove("P")
        prover.prove("Q")
        prover.prove("R")
        
        # THEN
        stats = prover.get_statistics()
        assert stats["proofs_attempted"] == 3
    
    def test_prover_clear_cache(self):
        """
        GIVEN: A prover with cached proofs
        WHEN: Clearing the cache
        THEN: Cache should be empty
        """
        # GIVEN
        prover = KProver()
        prover.proof_cache["test"] = ProofTree("P", [], ProofStatus.SUCCESS, ModalLogic.K)
        
        # WHEN
        prover.clear_cache()
        
        # THEN
        assert len(prover.proof_cache) == 0


class TestFactoryFunctions:
    """Test suite for factory functions."""
    
    def test_create_prover_k(self):
        """
        GIVEN: ModalLogic.K
        WHEN: Creating a prover
        THEN: Should return KProver instance
        """
        # GIVEN / WHEN
        prover = create_prover(ModalLogic.K)
        
        # THEN
        assert isinstance(prover, KProver)
        assert prover.logic == ModalLogic.K
    
    def test_create_prover_s4(self):
        """
        GIVEN: ModalLogic.S4
        WHEN: Creating a prover
        THEN: Should return S4Prover instance
        """
        # GIVEN / WHEN
        prover = create_prover(ModalLogic.S4)
        
        # THEN
        assert isinstance(prover, S4Prover)
        assert prover.logic == ModalLogic.S4
    
    def test_create_prover_s5(self):
        """
        GIVEN: ModalLogic.S5
        WHEN: Creating a prover
        THEN: Should return S5Prover instance
        """
        # GIVEN / WHEN
        prover = create_prover(ModalLogic.S5)
        
        # THEN
        assert isinstance(prover, S5Prover)
        assert prover.logic == ModalLogic.S5
    
    def test_create_prover_unsupported(self):
        """
        GIVEN: Unsupported modal logic
        WHEN: Creating a prover
        THEN: Should raise ValueError
        """
        # GIVEN / WHEN / THEN
        with pytest.raises(ValueError):
            create_prover(ModalLogic.T)
    
    def test_create_cognitive_prover(self):
        """
        GIVEN: Factory function
        WHEN: Creating cognitive prover
        THEN: Should return CognitiveCalculusProver instance
        """
        # GIVEN / WHEN
        prover = create_cognitive_prover()
        
        # THEN
        assert isinstance(prover, CognitiveCalculusProver)
        assert len(prover.cognitive_axioms) > 0


class TestProblemReader:
    """Test suite for problem file reader."""
    
    def test_problem_reader_placeholder(self):
        """
        GIVEN: A file path
        WHEN: Reading problem file (placeholder)
        THEN: Should return placeholder problem
        """
        # GIVEN
        filepath = "test_problem.p"
        
        # WHEN
        problem = ProblemReader.read_problem_file(filepath)
        
        # THEN
        assert problem is not None
        assert problem.name == "placeholder"
        assert filepath in problem.metadata.get("filepath", "")


class TestModalOperator:
    """Test suite for ModalOperator enum."""
    
    def test_modal_operator_values(self):
        """
        GIVEN: ModalOperator enum
        WHEN: Accessing values
        THEN: Should have correct symbols
        """
        # GIVEN / WHEN / THEN
        assert ModalOperator.NECESSARY.value == "□"
        assert ModalOperator.POSSIBLE.value == "◇"
        assert ModalOperator.BELIEF.value == "B"
        assert ModalOperator.KNOWLEDGE.value == "K"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
