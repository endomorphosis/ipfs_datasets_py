"""
Native Python 3 namespace and container management for DCEC.

This module provides symbol namespace management and statement containers
for the native DCEC implementation.
"""

from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
import logging

from .dcec_core import (
    Sort, Variable, Function, Predicate, Formula, DCECStatement,
    DeonticOperator, CognitiveOperator, TemporalOperator
)

try:
    from beartype import beartype
except ImportError:
    def beartype(func):
        return func

logger = logging.getLogger(__name__)


class DCECNamespace:
    """
    Manages the namespace of sorts, variables, functions, and predicates in DCEC.
    
    The namespace maintains all declared symbols and ensures type consistency.
    """
    
    def __init__(self):
        """Initialize an empty namespace."""
        self.sorts: Dict[str, Sort] = {}
        self.variables: Dict[str, Variable] = {}
        self.functions: Dict[str, Function] = {}
        self.predicates: Dict[str, Predicate] = {}
        
        # Initialize built-in sorts
        self._init_builtin_sorts()
    
    def _init_builtin_sorts(self):
        """Initialize built-in DCEC sorts."""
        # Base sorts
        self.add_sort("Entity")
        self.add_sort("Boolean")
        self.add_sort("Moment")  # Time points
        self.add_sort("Event")
        self.add_sort("Action")
        self.add_sort("Agent", parent="Entity")
        self.add_sort("ActionType")
        
        # Deontic and cognitive sorts
        self.add_sort("Obligation", parent="Boolean")
        self.add_sort("Permission", parent="Boolean")
        
    @beartype
    def add_sort(self, name: str, parent: Optional[str] = None) -> Sort:
        """
        Add a sort to the namespace.
        
        Args:
            name: Name of the sort
            parent: Optional parent sort name
            
        Returns:
            The created Sort object
            
        Raises:
            ValueError: If sort already exists or parent doesn't exist
        """
        if name in self.sorts:
            raise ValueError(f"Sort '{name}' already exists")
        
        parent_sort = None
        if parent:
            if parent not in self.sorts:
                raise ValueError(f"Parent sort '{parent}' does not exist")
            parent_sort = self.sorts[parent]
        
        sort = Sort(name, parent_sort)
        self.sorts[name] = sort
        logger.debug(f"Added sort: {name}")
        return sort
    
    @beartype
    def get_sort(self, name: str) -> Optional[Sort]:
        """Get a sort by name."""
        return self.sorts.get(name)
    
    @beartype
    def add_variable(self, name: str, sort_name: str) -> Variable:
        """
        Add a variable to the namespace.
        
        Args:
            name: Name of the variable
            sort_name: Name of the variable's sort
            
        Returns:
            The created Variable object
            
        Raises:
            ValueError: If variable already exists or sort doesn't exist
        """
        if name in self.variables:
            raise ValueError(f"Variable '{name}' already exists")
        
        if sort_name not in self.sorts:
            raise ValueError(f"Sort '{sort_name}' does not exist")
        
        variable = Variable(name, self.sorts[sort_name])
        self.variables[name] = variable
        logger.debug(f"Added variable: {variable}")
        return variable
    
    @beartype
    def get_variable(self, name: str) -> Optional[Variable]:
        """Get a variable by name."""
        return self.variables.get(name)
    
    @beartype
    def add_function(
        self, 
        name: str, 
        argument_sort_names: List[str], 
        return_sort_name: str
    ) -> Function:
        """
        Add a function to the namespace.
        
        Args:
            name: Name of the function
            argument_sort_names: List of argument sort names
            return_sort_name: Name of the return sort
            
        Returns:
            The created Function object
            
        Raises:
            ValueError: If function already exists or sorts don't exist
        """
        if name in self.functions:
            raise ValueError(f"Function '{name}' already exists")
        
        # Validate sorts
        argument_sorts = []
        for sort_name in argument_sort_names:
            if sort_name not in self.sorts:
                raise ValueError(f"Sort '{sort_name}' does not exist")
            argument_sorts.append(self.sorts[sort_name])
        
        if return_sort_name not in self.sorts:
            raise ValueError(f"Return sort '{return_sort_name}' does not exist")
        
        function = Function(name, argument_sorts, self.sorts[return_sort_name])
        self.functions[name] = function
        logger.debug(f"Added function: {function}")
        return function
    
    @beartype
    def get_function(self, name: str) -> Optional[Function]:
        """Get a function by name."""
        return self.functions.get(name)
    
    @beartype
    def add_predicate(self, name: str, argument_sort_names: List[str]) -> Predicate:
        """
        Add a predicate to the namespace.
        
        Args:
            name: Name of the predicate
            argument_sort_names: List of argument sort names
            
        Returns:
            The created Predicate object
            
        Raises:
            ValueError: If predicate already exists or sorts don't exist
        """
        if name in self.predicates:
            raise ValueError(f"Predicate '{name}' already exists")
        
        # Validate sorts
        argument_sorts = []
        for sort_name in argument_sort_names:
            if sort_name not in self.sorts:
                raise ValueError(f"Sort '{sort_name}' does not exist")
            argument_sorts.append(self.sorts[sort_name])
        
        predicate = Predicate(name, argument_sorts)
        self.predicates[name] = predicate
        logger.debug(f"Added predicate: {predicate}")
        return predicate
    
    @beartype
    def get_predicate(self, name: str) -> Optional[Predicate]:
        """Get a predicate by name."""
        return self.predicates.get(name)
    
    def get_statistics(self) -> Dict[str, int]:
        """Get statistics about the namespace."""
        return {
            "sorts": len(self.sorts),
            "variables": len(self.variables),
            "functions": len(self.functions),
            "predicates": len(self.predicates)
        }
    
    def __repr__(self) -> str:
        stats = self.get_statistics()
        return f"DCECNamespace(sorts={stats['sorts']}, vars={stats['variables']}, funcs={stats['functions']}, preds={stats['predicates']})"


class DCECContainer:
    """
    Container for managing DCEC statements and knowledge base.
    
    This provides the main API for working with DCEC formulas,
    similar to the original DCEC_Library DCECContainer.
    """
    
    def __init__(self):
        """Initialize an empty DCEC container."""
        self.namespace = DCECNamespace()
        self.statements: List[DCECStatement] = []
        self.statement_labels: Dict[str, DCECStatement] = {}
        self.axioms: List[DCECStatement] = []
        self.theorems: List[DCECStatement] = []
    
    @beartype
    def add_statement(
        self, 
        formula: Formula, 
        label: Optional[str] = None,
        is_axiom: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> DCECStatement:
        """
        Add a statement to the container.
        
        Args:
            formula: The formula to add
            label: Optional label for the statement
            is_axiom: Whether this is an axiom (assumed true)
            metadata: Optional metadata dictionary
            
        Returns:
            The created DCECStatement
            
        Raises:
            ValueError: If label already exists
        """
        if label and label in self.statement_labels:
            raise ValueError(f"Statement with label '{label}' already exists")
        
        statement = DCECStatement(
            formula=formula,
            label=label,
            metadata=metadata or {}
        )
        
        self.statements.append(statement)
        
        if label:
            self.statement_labels[label] = statement
        
        if is_axiom:
            self.axioms.append(statement)
        
        logger.debug(f"Added statement: {statement}")
        return statement
    
    @beartype
    def get_statement(self, label: str) -> Optional[DCECStatement]:
        """Get a statement by its label."""
        return self.statement_labels.get(label)
    
    @beartype
    def add_theorem(self, formula: Formula, label: Optional[str] = None) -> DCECStatement:
        """
        Add a theorem to prove.
        
        Args:
            formula: The theorem formula
            label: Optional label
            
        Returns:
            The created DCECStatement
        """
        statement = self.add_statement(formula, label, is_axiom=False)
        self.theorems.append(statement)
        return statement
    
    def get_all_statements(self) -> List[DCECStatement]:
        """Get all statements in the container."""
        return self.statements.copy()
    
    def get_axioms(self) -> List[DCECStatement]:
        """Get all axioms."""
        return self.axioms.copy()
    
    def get_theorems(self) -> List[DCECStatement]:
        """Get all theorems."""
        return self.theorems.copy()
    
    def clear(self):
        """Clear all statements (but keep the namespace)."""
        self.statements.clear()
        self.statement_labels.clear()
        self.axioms.clear()
        self.theorems.clear()
        logger.debug("Cleared all statements")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the container."""
        return {
            "total_statements": len(self.statements),
            "axioms": len(self.axioms),
            "theorems": len(self.theorems),
            "labeled_statements": len(self.statement_labels),
            "namespace": self.namespace.get_statistics()
        }
    
    def __repr__(self) -> str:
        stats = self.get_statistics()
        return f"DCECContainer(statements={stats['total_statements']}, axioms={stats['axioms']}, theorems={stats['theorems']})"
