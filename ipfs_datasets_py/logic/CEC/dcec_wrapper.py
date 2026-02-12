"""
DCEC Library Wrapper

This module provides a Python wrapper for the DCEC_Library submodule,
which implements the Deontic Cognitive Event Calculus (DCEC) logic system.

DCEC extends Event Calculus with deontic operators for reasoning about
obligations, permissions, beliefs, knowledge, and intentions of agents.
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
import logging

# Add DCEC_Library to Python path
DCEC_PATH = Path(__file__).parent / "DCEC_Library"
if str(DCEC_PATH) not in sys.path:
    sys.path.insert(0, str(DCEC_PATH))

try:
    from beartype import beartype  # type: ignore
except ImportError:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func

logger = logging.getLogger(__name__)


@dataclass
class DCECStatement:
    """Represents a DCEC logical statement."""
    raw_text: str
    parsed_formula: Optional[Any] = None
    namespace_info: Optional[Dict[str, Any]] = None
    is_valid: bool = False
    error_message: Optional[str] = None


class DCECLibraryWrapper:
    """
    Wrapper for DCEC_Library providing a clean Python API.
    
    This wrapper manages DCEC containers, statements, and provides
    methods for parsing natural language into DCEC formulas.
    
    Attributes:
        container: The underlying DCECContainer instance
        namespace: The DCEC namespace for managing symbols
        statements: List of parsed DCEC statements
    """
    
    def __init__(self):
        """Initialize the DCEC Library wrapper."""
        self.container = None
        self.namespace = None
        self.statements: List[DCECStatement] = []
        self._initialized = False
        
    @beartype
    def initialize(self) -> bool:
        """
        Initialize the DCEC library and create a container.
        
        Returns:
            bool: True if initialization succeeded, False otherwise
        """
        try:
            # Import DCEC modules
            from DCECContainer import DCECContainer
            
            self.container = DCECContainer()
            self.namespace = self.container.namespace
            self._initialized = True
            logger.info("DCEC Library initialized successfully")
            return True
            
        except ImportError as e:
            logger.error(f"Failed to import DCEC_Library: {e}")
            logger.warning("DCEC_Library not available. Using fallback mode.")
            self._initialized = False
            return False
        except Exception as e:
            logger.error(f"Failed to initialize DCEC Library: {e}")
            self._initialized = False
            return False
    
    @beartype
    def add_statement(self, statement: str) -> DCECStatement:
        """
        Add a DCEC statement to the container.
        
        Args:
            statement: Natural language or DCEC formula string
            
        Returns:
            DCECStatement object with parsing results
        """
        if not self._initialized:
            logger.error("DCEC Library not initialized. Call initialize() first.")
            return DCECStatement(
                raw_text=statement,
                is_valid=False,
                error_message="Library not initialized"
            )
        
        try:
            result = self.container.addStatement(statement)
            dcec_stmt = DCECStatement(
                raw_text=statement,
                is_valid=bool(result),
                parsed_formula=result if result else None
            )
            
            if dcec_stmt.is_valid:
                self.statements.append(dcec_stmt)
                logger.info(f"Successfully added statement: {statement[:50]}...")
            else:
                logger.warning(f"Failed to parse statement: {statement[:50]}...")
                dcec_stmt.error_message = "Statement parsing failed"
                
            return dcec_stmt
            
        except Exception as e:
            logger.error(f"Error adding statement: {e}")
            return DCECStatement(
                raw_text=statement,
                is_valid=False,
                error_message=str(e)
            )
    
    @beartype
    def print_statement(
        self, 
        statement: Union[str, Any], 
        expression_type: str = "S"
    ) -> Optional[str]:
        """
        Print a DCEC statement in the specified notation.
        
        Args:
            statement: The statement to print (string or Token object)
            expression_type: "S" for S-expression or "F" for F-expression
            
        Returns:
            Formatted statement string or None if error
        """
        if not self._initialized:
            logger.error("DCEC Library not initialized")
            return None
            
        try:
            return self.container.printStatement(statement, expression_type)
        except Exception as e:
            logger.error(f"Error printing statement: {e}")
            return None
    
    @beartype
    def save_container(self, filename: str) -> bool:
        """
        Save the current DCEC container to disk.
        
        Args:
            filename: Base filename (extensions will be added automatically)
            
        Returns:
            bool: True if save succeeded, False otherwise
        """
        if not self._initialized:
            logger.error("DCEC Library not initialized")
            return False
            
        try:
            self.container.save(filename)
            logger.info(f"Container saved to {filename}")
            return True
        except Exception as e:
            logger.error(f"Error saving container: {e}")
            return False
    
    @beartype
    def load_container(self, filename: str) -> bool:
        """
        Load a DCEC container from disk.
        
        Args:
            filename: Base filename (without extensions)
            
        Returns:
            bool: True if load succeeded, False otherwise
        """
        if not self._initialized:
            logger.error("DCEC Library not initialized")
            return False
            
        try:
            self.container.load(filename)
            logger.info(f"Container loaded from {filename}")
            return True
        except Exception as e:
            logger.error(f"Error loading container: {e}")
            return False
    
    @beartype
    def get_namespace_info(self) -> Dict[str, Any]:
        """
        Get information about the current namespace.
        
        Returns:
            Dictionary with namespace information
        """
        if not self._initialized or not self.namespace:
            return {"error": "Library not initialized"}
            
        try:
            return {
                "atomics": getattr(self.namespace, 'atomics', {}),
                "functions": getattr(self.namespace, 'functions', {}),
                "quantifiers": getattr(self.namespace, 'quantMap', {}),
            }
        except Exception as e:
            logger.error(f"Error getting namespace info: {e}")
            return {"error": str(e)}
    
    @beartype
    def get_statements_count(self) -> int:
        """
        Get the number of valid statements in the container.
        
        Returns:
            Number of valid statements
        """
        return len(self.statements)
    
    def __repr__(self) -> str:
        """String representation of the wrapper."""
        status = "initialized" if self._initialized else "not initialized"
        return f"DCECLibraryWrapper(status={status}, statements={len(self.statements)})"
