"""
DCEC Library Wrapper

This module provides a Python wrapper for the DCEC_Library submodule,
which implements the Deontic Cognitive Event Calculus (DCEC) logic system.

DCEC extends Event Calculus with deontic operators for reasoning about
obligations, permissions, beliefs, knowledge, and intentions of agents.

This wrapper now supports both:
1. Native Python 3 implementation (preferred, from ipfs_datasets_py.logic.native)
2. Python 2 submodule fallback (DCEC_Library)
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
    
    Supports both native Python 3 implementation and Python 2 submodule fallback.
    
    Attributes:
        container: The underlying DCECContainer instance (native or submodule)
        namespace: The DCEC namespace for managing symbols
        statements: List of parsed DCEC statements
        use_native: Whether to prefer native Python 3 implementation
        is_native: Whether currently using native implementation
    """
    
    def __init__(self, use_native: bool = True):
        """
        Initialize the DCEC Library wrapper.
        
        Args:
            use_native: If True (default), prefer native Python 3 implementation
                       with fallback to submodule. If False, use submodule only.
        """
        self.container = None
        self.namespace = None
        self.statements: List[DCECStatement] = []
        self._initialized = False
        self.use_native = use_native
        self.is_native = False
        
    @beartype
    def initialize(self) -> bool:
        """
        Initialize the DCEC library and create a container.
        
        Attempts to use native Python 3 implementation first (if use_native=True),
        then falls back to Python 2 submodule if native is unavailable.
        
        Returns:
            bool: True if initialization succeeded, False otherwise
        """
        # Try native implementation first if requested
        if self.use_native:
            try:
                from ipfs_datasets_py.logic.native import DCECContainer as NativeDCECContainer
                
                self.container = NativeDCECContainer()
                self.namespace = self.container.namespace
                self._initialized = True
                self.is_native = True
                logger.info("DCEC Library initialized successfully (using native Python 3)")
                return True
                
            except ImportError as e:
                logger.debug(f"Native DCEC not available: {e}")
                logger.info("Falling back to DCEC_Library submodule")
            except Exception as e:
                logger.warning(f"Failed to initialize native DCEC: {e}")
                logger.info("Falling back to DCEC_Library submodule")
        
        # Fall back to Python 2 submodule
        try:
            # Import DCEC modules
            from DCECContainer import DCECContainer
            
            self.container = DCECContainer()
            self.namespace = self.container.namespace
            self._initialized = True
            self.is_native = False
            logger.info("DCEC Library initialized successfully (using Python 2 submodule)")
            return True
            
        except ImportError as e:
            logger.error(f"Failed to import DCEC_Library: {e}")
            logger.warning("DCEC_Library not available. No DCEC backend available.")
            self._initialized = False
            self.is_native = False
            return False
        except Exception as e:
            logger.error(f"Failed to initialize DCEC Library: {e}")
            self._initialized = False
            self.is_native = False
            return False
    
    @beartype
    def add_statement(self, statement: str, label: Optional[str] = None, is_axiom: bool = False) -> DCECStatement:
        """
        Add a DCEC statement to the container.
        
        Args:
            statement: Natural language or DCEC formula string (or formula object if native)
            label: Optional label for the statement (native only)
            is_axiom: Whether this is an axiom (native only)
            
        Returns:
            DCECStatement object with parsing results
        """
        if not self._initialized:
            logger.error("DCEC Library not initialized. Call initialize() first.")
            return DCECStatement(
                raw_text=str(statement),
                is_valid=False,
                error_message="Library not initialized"
            )
        
        try:
            if self.is_native:
                # Native implementation supports formula objects directly
                result = self.container.add_statement(statement, label=label, is_axiom=is_axiom)
                dcec_stmt = DCECStatement(
                    raw_text=str(statement),
                    is_valid=True,
                    parsed_formula=result
                )
                self.statements.append(dcec_stmt)
                logger.info(f"Successfully added statement (native): {str(statement)[:50]}...")
                return dcec_stmt
            else:
                # Submodule implementation
                result = self.container.addStatement(statement)
                dcec_stmt = DCECStatement(
                    raw_text=statement,
                    is_valid=bool(result),
                    parsed_formula=result if result else None
                )
                
                if dcec_stmt.is_valid:
                    self.statements.append(dcec_stmt)
                    logger.info(f"Successfully added statement (submodule): {statement[:50]}...")
                else:
                    logger.warning(f"Failed to parse statement: {statement[:50]}...")
                    dcec_stmt.error_message = "Statement parsing failed"
                    
                return dcec_stmt
            
        except Exception as e:
            logger.error(f"Error adding statement: {e}")
            return DCECStatement(
                raw_text=str(statement),
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
    
    @beartype
    def get_backend_info(self) -> Dict[str, Any]:
        """
        Get information about the currently active backend.
        
        Returns:
            Dictionary with backend information
        """
        return {
            "initialized": self._initialized,
            "is_native": self.is_native,
            "backend": "native_python3" if self.is_native else "python2_submodule",
            "use_native_preference": self.use_native,
            "statements_count": len(self.statements)
        }
    
    def __repr__(self) -> str:
        """String representation of the wrapper."""
        status = "initialized" if self._initialized else "not initialized"
        backend = " (native)" if self.is_native else " (submodule)"
        return f"DCECLibraryWrapper(status={status}{backend if self._initialized else ''}, statements={len(self.statements)})"
