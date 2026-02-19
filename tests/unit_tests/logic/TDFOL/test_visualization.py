"""
Tests for TDFOL visualization components.

Tests basic visualization data structures and concepts.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate, create_implication
from ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer import ProofTreeNode, NodeType


class TestProofTreeNode:
    """Tests for ProofTreeNode dataclass"""
    
    def test_proof_node_creation(self):
        """Test creating a proof tree node"""
        # GIVEN a formula
        p = Predicate('P', [])
        
        # WHEN creating node with required parameters
        node = ProofTreeNode(
            formula=p,
            node_type=NodeType.AXIOM,
            rule_name="Assumption"
        )
        
        # THEN it should store properties
        assert node.formula == p
        assert node.node_type == NodeType.AXIOM
        assert node.rule_name == "Assumption"
    
    def test_proof_node_with_premises(self):
        """Test proof node with premises"""
        # GIVEN parent and child nodes
        p = Predicate('P', [])
        q = Predicate('Q', [])
        premise = ProofTreeNode(formula=p, node_type=NodeType.PREMISE)
        conclusion = ProofTreeNode(
            formula=q,
            node_type=NodeType.INFERRED,
            premises=[premise]
        )
        
        # WHEN checking premises
        premises = conclusion.premises
        
        # THEN premise should be present
        assert len(premises) == 1
        assert premises[0].formula == p
    
    def test_node_types(self):
        """Test different node types"""
        # GIVEN different node types
        p = Predicate('P', [])
        
        # WHEN creating nodes of different types
        axiom = ProofTreeNode(formula=p, node_type=NodeType.AXIOM)
        theorem = ProofTreeNode(formula=p, node_type=NodeType.THEOREM)
        lemma = ProofTreeNode(formula=p, node_type=NodeType.LEMMA)
        
        # THEN each should have correct type
        assert axiom.node_type == NodeType.AXIOM
        assert theorem.node_type == NodeType.THEOREM
        assert lemma.node_type == NodeType.LEMMA


class TestNodeTypeEnum:
    """Tests for NodeType enumeration"""
    
    def test_node_type_values(self):
        """Test NodeType enum values"""
        # GIVEN NodeType enum
        # WHEN checking values
        types = [NodeType.AXIOM, NodeType.PREMISE, NodeType.INFERRED,
                 NodeType.THEOREM, NodeType.GOAL, NodeType.LEMMA]
        
        # THEN all types should be defined
        assert len(types) == 6
        assert all(isinstance(t, NodeType) for t in types)
    
    def test_node_type_string_values(self):
        """Test NodeType string representations"""
        # GIVEN node types
        axiom = NodeType.AXIOM
        premise = NodeType.PREMISE
        
        # WHEN checking string values
        axiom_str = axiom.value
        premise_str = premise.value
        
        # THEN strings should match
        assert axiom_str == "axiom"
        assert premise_str == "premise"


class TestProofTreeStructure:
    """Tests for proof tree structure"""
    
    def test_single_node_tree(self):
        """Test tree with single node"""
        # GIVEN a single node
        p = Predicate('P', [])
        root = ProofTreeNode(formula=p, node_type=NodeType.AXIOM)
        
        # WHEN checking structure
        has_premises = len(root.premises) > 0
        
        # THEN it should be a leaf
        assert not has_premises
        assert root.premises == []
    
    def test_multi_level_tree(self):
        """Test tree with multiple levels"""
        # GIVEN multi-level structure
        p = Predicate('P', [])
        q = Predicate('Q', [])
        r = Predicate('R', [])
        
        leaf = ProofTreeNode(formula=p, node_type=NodeType.AXIOM)
        mid = ProofTreeNode(formula=q, node_type=NodeType.INFERRED, premises=[leaf])
        root = ProofTreeNode(formula=r, node_type=NodeType.THEOREM, premises=[mid])
        
        # WHEN checking structure
        root_has_premises = len(root.premises) > 0
        mid_has_premises = len(mid.premises) > 0
        
        # THEN structure should be preserved
        assert root_has_premises
        assert mid_has_premises
        assert root.premises[0].formula == q
        assert mid.premises[0].formula == p
    
    def test_tree_with_justification(self):
        """Test node with justification"""
        # GIVEN node with justification
        p = Predicate('P', [])
        node = ProofTreeNode(
            formula=p,
            node_type=NodeType.INFERRED,
            rule_name="ModusPonens",
            justification="Applied modus ponens to premises"
        )
        
        # WHEN checking justification
        just = node.justification
        
        # THEN it should be stored
        assert just == "Applied modus ponens to premises"
        assert node.rule_name == "ModusPonens"


class TestCountermodelConcepts:
    """Tests for countermodel concepts"""
    
    def test_countermodel_data_structure(self):
        """Test countermodel as dictionary"""
        # GIVEN countermodel data
        countermodel = {
            "world": "w1",
            "valuation": {"P": True, "Q": False},
            "relations": []
        }
        
        # WHEN accessing components
        world = countermodel["world"]
        valuation = countermodel["valuation"]
        
        # THEN structure should be valid
        assert world == "w1"
        assert valuation["P"] is True
        assert valuation["Q"] is False
    
    def test_modal_countermodel(self):
        """Test countermodel with accessibility relations"""
        # GIVEN modal countermodel
        countermodel = {
            "worlds": ["w1", "w2", "w3"],
            "accessibility": [("w1", "w2"), ("w2", "w3")],
            "valuations": {
                "w1": {"P": True},
                "w2": {"P": False},
                "w3": {"P": True}
            }
        }
        
        # WHEN checking structure
        worlds = countermodel["worlds"]
        accessibility = countermodel["accessibility"]
        
        # THEN it should have modal structure
        assert len(worlds) == 3
        assert len(accessibility) == 2
        assert ("w1", "w2") in accessibility


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
