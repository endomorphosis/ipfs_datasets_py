"""
Syntax Tree Module for DCEC Natural Language Processing.

This module provides Abstract Syntax Tree (AST) representations with:
- Tree construction and manipulation
- Multiple traversal methods (pre-order, in-order, post-order, level-order)
- Tree transformations
- Pretty printing and visualization
- Semantic annotation support
"""

from typing import List, Optional, Any, Callable, Iterator, Dict
from dataclasses import dataclass, field
from enum import Enum
import logging

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable as CallableType
    F = TypeVar('F', bound=CallableType[..., Any])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class NodeType(Enum):
    """Types of syntax tree nodes."""
    # Structural
    ROOT = "Root"
    SENTENCE = "Sentence"
    PHRASE = "Phrase"
    
    # DCEC specific
    DEONTIC_EXPR = "DeonticExpr"
    COGNITIVE_EXPR = "CognitiveExpr"
    TEMPORAL_EXPR = "TemporalExpr"
    
    # Logical
    CONJUNCTION = "Conjunction"
    DISJUNCTION = "Disjunction"
    NEGATION = "Negation"
    IMPLICATION = "Implication"
    
    # Atomic
    PREDICATE = "Predicate"
    TERM = "Term"
    VARIABLE = "Variable"
    CONSTANT = "Constant"
    
    # Lexical
    WORD = "Word"
    OPERATOR = "Operator"


@dataclass
class SyntaxNode:
    """A node in the syntax tree.
    
    Attributes:
        node_type: Type of the node
        value: Node value (word, operator, etc.)
        children: Child nodes
        parent: Parent node (optional)
        semantics: Semantic representation (optional)
        metadata: Additional metadata
    """
    node_type: NodeType
    value: Any = None
    children: List['SyntaxNode'] = field(default_factory=list)
    parent: Optional['SyntaxNode'] = None
    semantics: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_child(self, child: 'SyntaxNode') -> 'SyntaxNode':
        """Add a child node.
        
        Args:
            child: Child node to add
            
        Returns:
            The child node (for chaining)
        """
        self.children.append(child)
        child.parent = self
        return child
    
    def add_children(self, children: List['SyntaxNode']) -> 'SyntaxNode':
        """Add multiple child nodes.
        
        Args:
            children: List of child nodes
            
        Returns:
            Self (for chaining)
        """
        for child in children:
            self.add_child(child)
        return self
    
    def remove_child(self, child: 'SyntaxNode') -> bool:
        """Remove a child node.
        
        Args:
            child: Child to remove
            
        Returns:
            True if removed, False if not found
        """
        if child in self.children:
            self.children.remove(child)
            child.parent = None
            return True
        return False
    
    def is_leaf(self) -> bool:
        """Check if this is a leaf node."""
        return len(self.children) == 0
    
    def is_root(self) -> bool:
        """Check if this is a root node."""
        return self.parent is None
    
    def height(self) -> int:
        """Calculate height of subtree rooted at this node."""
        if self.is_leaf():
            return 0
        return 1 + max(child.height() for child in self.children)
    
    def size(self) -> int:
        """Count total nodes in subtree."""
        return 1 + sum(child.size() for child in self.children)
    
    def depth(self) -> int:
        """Calculate depth of this node in the tree."""
        if self.is_root():
            return 0
        return 1 + self.parent.depth()
    
    def __str__(self) -> str:
        """String representation."""
        if self.value is not None:
            return f"{self.node_type.value}({self.value})"
        return self.node_type.value
    
    def __repr__(self) -> str:
        """Detailed representation."""
        return f"SyntaxNode({self.node_type.value}, value={self.value}, children={len(self.children)})"


class SyntaxTree:
    """Abstract Syntax Tree with traversal and transformation operations."""
    
    def __init__(self, root: Optional[SyntaxNode] = None):
        """Initialize syntax tree.
        
        Args:
            root: Root node (if None, creates empty root)
        """
        self.root = root if root is not None else SyntaxNode(NodeType.ROOT)
    
    def preorder(self, node: Optional[SyntaxNode] = None) -> Iterator[SyntaxNode]:
        """Pre-order traversal: root, left, right.
        
        Args:
            node: Starting node (defaults to root)
            
        Yields:
            Nodes in pre-order
        """
        if node is None:
            node = self.root
        
        yield node
        for child in node.children:
            yield from self.preorder(child)
    
    def inorder(self, node: Optional[SyntaxNode] = None) -> Iterator[SyntaxNode]:
        """In-order traversal (for binary trees): left, root, right.
        
        Args:
            node: Starting node (defaults to root)
            
        Yields:
            Nodes in in-order
        """
        if node is None:
            node = self.root
        
        if len(node.children) >= 1:
            yield from self.inorder(node.children[0])
        
        yield node
        
        if len(node.children) >= 2:
            for child in node.children[1:]:
                yield from self.inorder(child)
    
    def postorder(self, node: Optional[SyntaxNode] = None) -> Iterator[SyntaxNode]:
        """Post-order traversal: left, right, root.
        
        Args:
            node: Starting node (defaults to root)
            
        Yields:
            Nodes in post-order
        """
        if node is None:
            node = self.root
        
        for child in node.children:
            yield from self.postorder(child)
        
        yield node
    
    def levelorder(self, node: Optional[SyntaxNode] = None) -> Iterator[SyntaxNode]:
        """Level-order traversal (breadth-first).
        
        Args:
            node: Starting node (defaults to root)
            
        Yields:
            Nodes in level-order
        """
        if node is None:
            node = self.root
        
        queue = [node]
        while queue:
            current = queue.pop(0)
            yield current
            queue.extend(current.children)
    
    def find(self, predicate: Callable[[SyntaxNode], bool]) -> Optional[SyntaxNode]:
        """Find first node matching predicate.
        
        Args:
            predicate: Function to test nodes
            
        Returns:
            First matching node or None
        """
        for node in self.preorder():
            if predicate(node):
                return node
        return None
    
    def find_all(self, predicate: Callable[[SyntaxNode], bool]) -> List[SyntaxNode]:
        """Find all nodes matching predicate.
        
        Args:
            predicate: Function to test nodes
            
        Returns:
            List of matching nodes
        """
        return [node for node in self.preorder() if predicate(node)]
    
    def transform(self, transformer: Callable[[SyntaxNode], Optional[SyntaxNode]]) -> 'SyntaxTree':
        """Apply transformation function to all nodes.
        
        Args:
            transformer: Function that takes a node and returns a transformed node
                        (or None to remove the node)
            
        Returns:
            New transformed tree
        """
        def transform_node(node: SyntaxNode) -> Optional[SyntaxNode]:
            # Transform this node
            transformed = transformer(node)
            if transformed is None:
                return None
            
            # Transform children
            new_children = []
            for child in node.children:
                transformed_child = transform_node(child)
                if transformed_child is not None:
                    new_children.append(transformed_child)
            
            transformed.children = new_children
            return transformed
        
        new_root = transform_node(self.root)
        return SyntaxTree(new_root)
    
    def map(self, mapper: Callable[[Any], Any]) -> 'SyntaxTree':
        """Map a function over node values.
        
        Args:
            mapper: Function to apply to each node's value
            
        Returns:
            New tree with mapped values
        """
        def map_transformer(node: SyntaxNode) -> SyntaxNode:
            new_node = SyntaxNode(node.node_type)
            if node.value is not None:
                new_node.value = mapper(node.value)
            return new_node
        
        return self.transform(map_transformer)
    
    def filter(self, predicate: Callable[[SyntaxNode], bool]) -> 'SyntaxTree':
        """Filter nodes based on predicate.
        
        Args:
            predicate: Function to test nodes
            
        Returns:
            New tree with only matching nodes
        """
        def filter_transformer(node: SyntaxNode) -> Optional[SyntaxNode]:
            if predicate(node):
                return SyntaxNode(node.node_type, node.value)
            return None
        
        return self.transform(filter_transformer)
    
    def pretty_print(self, node: Optional[SyntaxNode] = None, indent: int = 0, 
                     prefix: str = "") -> str:
        """Generate pretty-printed tree representation.
        
        Args:
            node: Starting node (defaults to root)
            indent: Current indentation level
            prefix: Prefix for current line
            
        Returns:
            Pretty-printed tree string
        """
        if node is None:
            node = self.root
        
        result = prefix + str(node) + "\n"
        
        for i, child in enumerate(node.children):
            is_last = i == len(node.children) - 1
            child_prefix = "  " * indent + ("└─ " if is_last else "├─ ")
            result += self.pretty_print(child, indent + 1, child_prefix)
        
        return result
    
    def to_dict(self, node: Optional[SyntaxNode] = None) -> Dict[str, Any]:
        """Convert tree to dictionary representation.
        
        Args:
            node: Starting node (defaults to root)
            
        Returns:
            Dictionary representation
        """
        if node is None:
            node = self.root
        
        result = {
            "type": node.node_type.value,
            "value": node.value,
        }
        
        if node.semantics:
            result["semantics"] = str(node.semantics)
        
        if node.metadata:
            result["metadata"] = node.metadata
        
        if node.children:
            result["children"] = [self.to_dict(child) for child in node.children]
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SyntaxTree':
        """Create tree from dictionary representation.
        
        Args:
            data: Dictionary representation
            
        Returns:
            Syntax tree
        """
        def build_node(node_data: Dict[str, Any]) -> SyntaxNode:
            node_type = NodeType(node_data["type"])
            node = SyntaxNode(node_type, node_data.get("value"))
            
            if "metadata" in node_data:
                node.metadata = node_data["metadata"]
            
            if "children" in node_data:
                for child_data in node_data["children"]:
                    child = build_node(child_data)
                    node.add_child(child)
            
            return node
        
        root = build_node(data)
        return cls(root)
    
    def leaves(self) -> List[SyntaxNode]:
        """Get all leaf nodes.
        
        Returns:
            List of leaf nodes
        """
        return [node for node in self.preorder() if node.is_leaf()]
    
    def height(self) -> int:
        """Get tree height."""
        return self.root.height()
    
    def size(self) -> int:
        """Get total number of nodes."""
        return self.root.size()
    
    def __str__(self) -> str:
        """String representation."""
        return self.pretty_print()
