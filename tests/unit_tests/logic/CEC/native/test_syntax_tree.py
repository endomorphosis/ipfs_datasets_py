"""
Tests for Syntax Tree Module.

Tests cover:
- Tree construction
- Tree traversal methods
- Tree transformations
- Pretty printing
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.syntax_tree import (
    NodeType,
    SyntaxNode,
    SyntaxTree,
)


class TestSyntaxNode:
    """Test syntax node operations."""
    
    def test_node_creation(self):
        """Test creating syntax nodes."""
        # GIVEN node type and value
        node_type = NodeType.SENTENCE
        value = "test"
        
        # WHEN creating a node
        node = SyntaxNode(node_type, value)
        
        # THEN it should have correct attributes
        assert node.node_type == node_type
        assert node.value == value
        assert len(node.children) == 0
    
    def test_add_child(self):
        """Test adding child nodes."""
        # GIVEN a parent and child node
        parent = SyntaxNode(NodeType.SENTENCE)
        child = SyntaxNode(NodeType.WORD, "hello")
        
        # WHEN adding child
        parent.add_child(child)
        
        # THEN parent should contain child
        assert len(parent.children) == 1
        assert child in parent.children
        assert child.parent == parent
    
    def test_add_multiple_children(self):
        """Test adding multiple children."""
        # GIVEN a parent and multiple children
        parent = SyntaxNode(NodeType.SENTENCE)
        children = [
            SyntaxNode(NodeType.WORD, "hello"),
            SyntaxNode(NodeType.WORD, "world"),
        ]
        
        # WHEN adding children
        parent.add_children(children)
        
        # THEN all should be added
        assert len(parent.children) == 2
        for child in children:
            assert child.parent == parent
    
    def test_remove_child(self):
        """Test removing child nodes."""
        # GIVEN a parent with a child
        parent = SyntaxNode(NodeType.SENTENCE)
        child = SyntaxNode(NodeType.WORD, "test")
        parent.add_child(child)
        
        # WHEN removing the child
        result = parent.remove_child(child)
        
        # THEN child should be removed
        assert result is True
        assert len(parent.children) == 0
        assert child.parent is None
    
    def test_is_leaf(self):
        """Test leaf node detection."""
        # GIVEN a leaf and non-leaf node
        leaf = SyntaxNode(NodeType.WORD, "test")
        parent = SyntaxNode(NodeType.SENTENCE)
        parent.add_child(leaf)
        
        # WHEN checking leaf status
        # THEN leaf should be detected correctly
        assert leaf.is_leaf()
        assert not parent.is_leaf()
    
    def test_is_root(self):
        """Test root node detection."""
        # GIVEN a root and non-root node
        root = SyntaxNode(NodeType.ROOT)
        child = SyntaxNode(NodeType.SENTENCE)
        root.add_child(child)
        
        # WHEN checking root status
        # THEN root should be detected correctly
        assert root.is_root()
        assert not child.is_root()
    
    def test_height(self):
        """Test calculating node height."""
        # GIVEN a tree: root -> sentence -> word
        root = SyntaxNode(NodeType.ROOT)
        sentence = SyntaxNode(NodeType.SENTENCE)
        word = SyntaxNode(NodeType.WORD, "test")
        root.add_child(sentence)
        sentence.add_child(word)
        
        # WHEN calculating heights
        # THEN should get correct heights
        assert word.height() == 0  # Leaf
        assert sentence.height() == 1
        assert root.height() == 2
    
    def test_size(self):
        """Test counting nodes in subtree."""
        # GIVEN a tree with 3 nodes
        root = SyntaxNode(NodeType.ROOT)
        child1 = SyntaxNode(NodeType.WORD, "a")
        child2 = SyntaxNode(NodeType.WORD, "b")
        root.add_child(child1)
        root.add_child(child2)
        
        # WHEN calculating size
        size = root.size()
        
        # THEN should count all nodes
        assert size == 3


class TestTreeTraversal:
    """Test tree traversal methods."""
    
    @pytest.fixture
    def sample_tree(self):
        """Create a sample tree for testing."""
        #     root
        #    /    \
        #   A      B
        #  / \      \
        # C   D      E
        root = SyntaxNode(NodeType.ROOT, "root")
        a = SyntaxNode(NodeType.PHRASE, "A")
        b = SyntaxNode(NodeType.PHRASE, "B")
        c = SyntaxNode(NodeType.WORD, "C")
        d = SyntaxNode(NodeType.WORD, "D")
        e = SyntaxNode(NodeType.WORD, "E")
        
        root.add_child(a)
        root.add_child(b)
        a.add_child(c)
        a.add_child(d)
        b.add_child(e)
        
        return SyntaxTree(root)
    
    def test_preorder_traversal(self, sample_tree):
        """Test pre-order traversal."""
        # GIVEN a sample tree
        # WHEN doing pre-order traversal
        values = [node.value for node in sample_tree.preorder()]
        
        # THEN should get: root, A, C, D, B, E
        assert values == ["root", "A", "C", "D", "B", "E"]
    
    def test_postorder_traversal(self, sample_tree):
        """Test post-order traversal."""
        # GIVEN a sample tree
        # WHEN doing post-order traversal
        values = [node.value for node in sample_tree.postorder()]
        
        # THEN should get: C, D, A, E, B, root
        assert values == ["C", "D", "A", "E", "B", "root"]
    
    def test_levelorder_traversal(self, sample_tree):
        """Test level-order traversal."""
        # GIVEN a sample tree
        # WHEN doing level-order traversal
        values = [node.value for node in sample_tree.levelorder()]
        
        # THEN should get: root, A, B, C, D, E
        assert values == ["root", "A", "B", "C", "D", "E"]


class TestTreeOperations:
    """Test tree operations."""
    
    def test_find_node(self):
        """Test finding nodes."""
        # GIVEN a tree with specific nodes
        tree = SyntaxTree()
        tree.root.add_child(SyntaxNode(NodeType.WORD, "target"))
        tree.root.add_child(SyntaxNode(NodeType.WORD, "other"))
        
        # WHEN finding a node
        found = tree.find(lambda n: n.value == "target")
        
        # THEN should find the correct node
        assert found is not None
        assert found.value == "target"
    
    def test_find_all_nodes(self):
        """Test finding all matching nodes."""
        # GIVEN a tree with multiple matching nodes
        tree = SyntaxTree()
        tree.root.add_child(SyntaxNode(NodeType.WORD, "a"))
        tree.root.add_child(SyntaxNode(NodeType.WORD, "b"))
        tree.root.add_child(SyntaxNode(NodeType.WORD, "a"))
        
        # WHEN finding all nodes with value "a"
        found = tree.find_all(lambda n: n.value == "a")
        
        # THEN should find both
        assert len(found) == 2
    
    def test_transform_tree(self):
        """Test tree transformation."""
        # GIVEN a tree
        tree = SyntaxTree()
        tree.root.add_child(SyntaxNode(NodeType.WORD, "hello"))
        
        # WHEN transforming (uppercase values)
        transformed = tree.transform(
            lambda n: SyntaxNode(n.node_type, 
                               n.value.upper() if n.value else None)
        )
        
        # THEN values should be transformed
        word_node = transformed.find(lambda n: n.node_type == NodeType.WORD)
        assert word_node.value == "HELLO"
    
    def test_map_values(self):
        """Test mapping over values."""
        # GIVEN a tree with numeric values
        tree = SyntaxTree()
        tree.root.value = 1
        tree.root.add_child(SyntaxNode(NodeType.WORD, 2))
        tree.root.add_child(SyntaxNode(NodeType.WORD, 3))
        
        # WHEN mapping (multiply by 2)
        mapped = tree.map(lambda v: v * 2 if v else None)
        
        # THEN values should be doubled
        assert mapped.root.value == 2
        assert mapped.root.children[0].value == 4
        assert mapped.root.children[1].value == 6


class TestTreeSerialization:
    """Test tree serialization."""
    
    def test_to_dict(self):
        """Test converting tree to dictionary."""
        # GIVEN a simple tree
        root = SyntaxNode(NodeType.ROOT, "root")
        root.add_child(SyntaxNode(NodeType.WORD, "child"))
        tree = SyntaxTree(root)
        
        # WHEN converting to dict
        data = tree.to_dict()
        
        # THEN should have correct structure
        assert data["type"] == "Root"
        assert data["value"] == "root"
        assert "children" in data
        assert len(data["children"]) == 1
    
    def test_from_dict(self):
        """Test creating tree from dictionary."""
        # GIVEN dictionary data
        data = {
            "type": "Root",
            "value": "root",
            "children": [
                {"type": "Word", "value": "child"}
            ]
        }
        
        # WHEN creating tree from dict
        tree = SyntaxTree.from_dict(data)
        
        # THEN should reconstruct correctly
        assert tree.root.node_type == NodeType.ROOT
        assert tree.root.value == "root"
        assert len(tree.root.children) == 1
    
    def test_pretty_print(self):
        """Test pretty printing."""
        # GIVEN a tree
        tree = SyntaxTree()
        tree.root.add_child(SyntaxNode(NodeType.WORD, "hello"))
        
        # WHEN pretty printing
        output = tree.pretty_print()
        
        # THEN should produce readable output
        assert "Root" in output
        assert "hello" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
