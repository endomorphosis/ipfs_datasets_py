"""
Grammar Loader for DCEC.

This module provides utilities to load grammar rules from YAML configuration files,
enabling external configuration of grammar rules for better maintainability and
multi-language support.
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GrammarConfig:
    """Configuration for grammar rules loaded from YAML."""
    
    version: str
    language: str
    case_sensitive: bool
    allow_contractions: bool
    default_tense: str


class GrammarLoader:
    """
    Loads and manages grammar rules from YAML configuration files.
    
    This allows grammar rules to be externalized from Python code for:
    - Better maintainability
    - Easier rule modifications
    - Multi-language support
    - Version control of grammar rules
    
    Example:
        loader = GrammarLoader("grammar_rules.yaml")
        connectives = loader.get_connectives()
        deontic_rules = loader.get_deontic_rules()
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the grammar loader.
        
        Args:
            config_path: Path to YAML config file. If None, uses default.
        """
        if config_path is None:
            # Default to grammar_rules.yaml in same directory
            config_path = Path(__file__).parent / "grammar_rules.yaml"
        
        self.config_path = Path(config_path)
        self._grammar_data: Optional[Dict[str, Any]] = None
        self._config: Optional[GrammarConfig] = None
        
        self.load()
    
    def load(self) -> None:
        """Load grammar rules from YAML file."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._grammar_data = yaml.safe_load(f)
            
            # Load configuration
            config_data = self._grammar_data.get('config', {})
            self._config = GrammarConfig(
                version=config_data.get('version', '1.0'),
                language=config_data.get('language', 'en'),
                case_sensitive=config_data.get('case_sensitive', False),
                allow_contractions=config_data.get('allow_contractions', True),
                default_tense=config_data.get('default_tense', 'present')
            )
            
            logger.info(f"Loaded grammar rules from {self.config_path}")
            logger.info(f"Grammar version: {self._config.version}, language: {self._config.language}")
            
        except FileNotFoundError:
            logger.error(f"Grammar file not found: {self.config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Error parsing grammar YAML: {e}")
            raise
    
    def get_config(self) -> GrammarConfig:
        """Get grammar configuration."""
        if self._config is None:
            raise RuntimeError("Grammar not loaded")
        return self._config
    
    def get_connectives(self) -> Dict[str, Any]:
        """
        Get logical connectives (and, or, not, implies).
        
        Returns:
            Dictionary of connectives with their properties.
        """
        if self._grammar_data is None:
            raise RuntimeError("Grammar not loaded")
        return self._grammar_data.get('connectives', {})
    
    def get_deontic_rules(self) -> Dict[str, Any]:
        """
        Get deontic modal rules (obligation, permission, prohibition).
        
        Returns:
            Dictionary of deontic rules with their properties.
        """
        if self._grammar_data is None:
            raise RuntimeError("Grammar not loaded")
        return self._grammar_data.get('deontic', {})
    
    def get_cognitive_rules(self) -> Dict[str, Any]:
        """
        Get cognitive operator rules (belief, knowledge, intention, desire).
        
        Returns:
            Dictionary of cognitive rules with their properties.
        """
        if self._grammar_data is None:
            raise RuntimeError("Grammar not loaded")
        return self._grammar_data.get('cognitive', {})
    
    def get_temporal_rules(self) -> Dict[str, Any]:
        """
        Get temporal operator rules (always, eventually, next, until).
        
        Returns:
            Dictionary of temporal rules with their properties.
        """
        if self._grammar_data is None:
            raise RuntimeError("Grammar not loaded")
        return self._grammar_data.get('temporal', {})
    
    def get_quantifiers(self) -> Dict[str, Any]:
        """
        Get quantifier rules (universal, existential).
        
        Returns:
            Dictionary of quantifier rules with their properties.
        """
        if self._grammar_data is None:
            raise RuntimeError("Grammar not loaded")
        return self._grammar_data.get('quantifiers', {})
    
    def get_production_rules(self) -> Dict[str, Any]:
        """
        Get production rules for sentence structures.
        
        Returns:
            Dictionary of production rules with patterns and examples.
        """
        if self._grammar_data is None:
            raise RuntimeError("Grammar not loaded")
        return self._grammar_data.get('production_rules', {})
    
    def get_words_for_operator(self, operator_type: str, operator_name: str) -> List[str]:
        """
        Get list of words that map to a specific operator.
        
        Args:
            operator_type: Type of operator ('deontic', 'cognitive', 'temporal', 'quantifiers')
            operator_name: Name of specific operator ('obligation', 'belief', etc.)
        
        Returns:
            List of words that map to this operator.
            
        Example:
            >>> loader.get_words_for_operator('deontic', 'obligation')
            ['must', 'obligated', 'should', 'required']
        """
        if self._grammar_data is None:
            raise RuntimeError("Grammar not loaded")
        
        operator_section = self._grammar_data.get(operator_type, {})
        operator_data = operator_section.get(operator_name, {})
        
        # Handle both 'words' (list) and 'word' (single) keys
        if 'words' in operator_data:
            return operator_data['words']
        elif 'word' in operator_data:
            return [operator_data['word']]
        else:
            return []
    
    def get_semantics(self, operator_type: str, operator_name: str) -> Dict[str, Any]:
        """
        Get semantic information for an operator.
        
        Args:
            operator_type: Type of operator ('deontic', 'cognitive', 'temporal')
            operator_name: Name of specific operator
        
        Returns:
            Dictionary containing semantic information.
        """
        if self._grammar_data is None:
            raise RuntimeError("Grammar not loaded")
        
        operator_section = self._grammar_data.get(operator_type, {})
        operator_data = operator_section.get(operator_name, {})
        return operator_data.get('semantics', {})
    
    def get_examples(self, operator_type: str, operator_name: str) -> List[str]:
        """
        Get usage examples for an operator.
        
        Args:
            operator_type: Type of operator
            operator_name: Name of specific operator
        
        Returns:
            List of example sentences.
        """
        if self._grammar_data is None:
            raise RuntimeError("Grammar not loaded")
        
        operator_section = self._grammar_data.get(operator_type, {})
        operator_data = operator_section.get(operator_name, {})
        return operator_data.get('examples', [])
    
    def reload(self) -> None:
        """Reload grammar rules from file (useful for hot-reloading)."""
        self.load()
    
    def validate(self) -> bool:
        """
        Validate grammar structure and completeness.
        
        Returns:
            True if grammar is valid, False otherwise.
        """
        if self._grammar_data is None:
            logger.error("No grammar data loaded")
            return False
        
        required_sections = ['connectives', 'deontic', 'cognitive', 'temporal', 'quantifiers']
        missing_sections = [s for s in required_sections if s not in self._grammar_data]
        
        if missing_sections:
            logger.warning(f"Missing grammar sections: {missing_sections}")
            return False
        
        logger.info("Grammar validation passed")
        return True
    
    def get_all_words(self) -> List[str]:
        """
        Get all words defined in the grammar.
        
        Returns:
            List of all lexical items.
        """
        words = []
        
        if self._grammar_data is None:
            return words
        
        # Extract from connectives
        for conn_data in self._grammar_data.get('connectives', {}).values():
            if 'word' in conn_data:
                words.append(conn_data['word'])
        
        # Extract from operators
        for section in ['deontic', 'cognitive', 'temporal', 'quantifiers']:
            for op_data in self._grammar_data.get(section, {}).values():
                if 'words' in op_data:
                    words.extend(op_data['words'])
                elif 'word' in op_data:
                    words.append(op_data['word'])
        
        return words


# Singleton instance for easy access
_default_loader: Optional[GrammarLoader] = None


def get_grammar_loader(config_path: Optional[str] = None) -> GrammarLoader:
    """
    Get the default grammar loader instance.
    
    This provides a singleton pattern for easy access to grammar rules
    throughout the application.
    
    Args:
        config_path: Optional path to config file. Only used on first call.
    
    Returns:
        GrammarLoader instance.
        
    Example:
        >>> loader = get_grammar_loader()
        >>> deontic = loader.get_deontic_rules()
    """
    global _default_loader
    
    if _default_loader is None:
        _default_loader = GrammarLoader(config_path)
    
    return _default_loader
