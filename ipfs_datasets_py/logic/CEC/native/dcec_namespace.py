"""
Native Python 3 namespace and container management for DCEC.

This module provides symbol namespace management and statement containers
for the native DCEC implementation.
"""

from typing import Dict, List, Optional, Set, Any, TypeVar, Callable
from dataclasses import dataclass, field
import logging

from .dcec_core import (
    Sort, Variable, Function, Predicate, Formula, DCECStatement,
    DeonticOperator, CognitiveOperator, TemporalOperator
)
from .exceptions import NamespaceError

try:
    from beartype import beartype  # type: ignore[import-not-found]
except ImportError:
    F = TypeVar('F', bound=Callable[..., Any])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class DCECNamespace:
    """
    Manages the namespace of sorts, variables, functions, and predicates in DCEC.
    
    The namespace maintains all declared symbols and ensures type consistency.
    """
    
    def __init__(self) -> None:
        """Initialize an empty namespace."""
        self.sorts: Dict[str, Sort] = {}
        self.variables: Dict[str, Variable] = {}
        self.functions: Dict[str, Function] = {}
        self.predicates: Dict[str, Predicate] = {}
        
        # Initialize built-in sorts
        self._init_builtin_sorts()
    
    def _init_builtin_sorts(self) -> None:
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
        
    @beartype  # type: ignore[untyped-decorator]
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
            raise NamespaceError(
                f"Duplicate sort name '{name}'",
                symbol=name,
                operation="add_sort",
                suggestion=f"Use a different name or remove the existing sort '{name}' first"
            )
        
        parent_sort = None
        if parent:
            if parent not in self.sorts:
                raise NamespaceError(
                    f"Parent sort '{parent}' does not exist",
                    symbol=parent,
                    operation="lookup",
                    suggestion=f"Register sort '{parent}' first, or use an existing sort: {', '.join(self.sorts.keys())}"
                )
            parent_sort = self.sorts[parent]
        
        sort = Sort(name, parent_sort)
        self.sorts[name] = sort
        logger.debug(f"Added sort: {name}")
        return sort
    
    @beartype  # type: ignore[untyped-decorator]
    def get_sort(self, name: str) -> Optional[Sort]:
        """Get a sort by name."""
        return self.sorts.get(name)
    
    @beartype  # type: ignore[untyped-decorator]
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
            raise NamespaceError(
                f"Duplicate variable name '{name}'",
                symbol=name,
                operation="add_variable",
                suggestion=f"Use a different variable name or remove the existing variable '{name}' first"
            )
        
        if sort_name not in self.sorts:
            raise NamespaceError(
                f"Sort '{sort_name}' does not exist for variable",
                symbol=sort_name,
                operation="lookup",
                suggestion=f"Register sort '{sort_name}' first, or use an existing sort: {', '.join(self.sorts.keys())}"
            )
        
        variable = Variable(name, self.sorts[sort_name])
        self.variables[name] = variable
        logger.debug(f"Added variable: {variable}")
        return variable
    
    @beartype  # type: ignore[untyped-decorator]
    def get_variable(self, name: str) -> Optional[Variable]:
        """Get a variable by name."""
        return self.variables.get(name)
    
    @beartype  # type: ignore[untyped-decorator]
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
            raise NamespaceError(
                f"Duplicate function name '{name}'",
                symbol=name,
                operation="add_function",
                suggestion=f"Use a different function name or remove the existing function '{name}' first"
            )
        
        # Validate sorts
        argument_sorts = []
        for sort_name in argument_sort_names:
            if sort_name not in self.sorts:
                raise NamespaceError(
                    f"Sort '{sort_name}' does not exist for function argument",
                    symbol=sort_name,
                    operation="lookup",
                    suggestion=f"Register sort '{sort_name}' first, or use an existing sort: {', '.join(self.sorts.keys())}"
                )
            argument_sorts.append(self.sorts[sort_name])
        
        if return_sort_name not in self.sorts:
            raise NamespaceError(
                f"Return sort '{return_sort_name}' does not exist",
                symbol=return_sort_name,
                operation="lookup",
                suggestion=f"Register sort '{return_sort_name}' first, or use an existing sort: {', '.join(self.sorts.keys())}"
            )
        
        function = Function(name, argument_sorts, self.sorts[return_sort_name])
        self.functions[name] = function
        logger.debug(f"Added function: {function}")
        return function
    
    @beartype  # type: ignore[untyped-decorator]
    def get_function(self, name: str) -> Optional[Function]:
        """Get a function by name."""
        return self.functions.get(name)
    
    @beartype  # type: ignore[untyped-decorator]
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
            raise NamespaceError(
                f"Duplicate predicate name '{name}'",
                symbol=name,
                operation="add_predicate",
                suggestion=f"Use a different predicate name or remove the existing predicate '{name}' first"
            )
        
        # Validate sorts
        argument_sorts = []
        for sort_name in argument_sort_names:
            if sort_name not in self.sorts:
                raise NamespaceError(
                    f"Sort '{sort_name}' does not exist for predicate argument",
                    symbol=sort_name,
                    operation="lookup",
                    suggestion=f"Register sort '{sort_name}' first, or use an existing sort: {', '.join(self.sorts.keys())}"
                )
            argument_sorts.append(self.sorts[sort_name])
        
        predicate = Predicate(name, argument_sorts)
        self.predicates[name] = predicate
        logger.debug(f"Added predicate: {predicate}")
        return predicate
    
    @beartype  # type: ignore[untyped-decorator]
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
    
    def __init__(self) -> None:
        """Initialize an empty DCEC container."""
        self.namespace = DCECNamespace()
        self.statements: List[DCECStatement] = []
        self.statement_labels: Dict[str, DCECStatement] = {}
        self.axioms: List[DCECStatement] = []
        self.theorems: List[DCECStatement] = []
    
    @beartype  # type: ignore[untyped-decorator]
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
            raise NamespaceError(
                f"Duplicate statement label '{label}'",
                symbol=label,
                operation="add_statement",
                suggestion=f"Use a different label or remove the existing statement with label '{label}' first"
            )
        
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
    
    @beartype  # type: ignore[untyped-decorator]
    def get_statement(self, label: str) -> Optional[DCECStatement]:
        """Get a statement by its label."""
        return self.statement_labels.get(label)
    
    @beartype  # type: ignore[untyped-decorator]
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
    
    def clear(self) -> None:
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
