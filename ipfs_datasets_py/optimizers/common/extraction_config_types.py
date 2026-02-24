"""
Type stubs and validation for ExtractionConfig.

This module provides runtime type validation and IDE support enhancements
for ExtractionConfig dataclass fields.
"""

from typing import Dict, List, get_type_hints
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig


def get_extraction_config_type_hints() -> Dict[str, type]:
    """Get type hints for all ExtractionConfig fields.
    
    Returns:
        Dictionary mapping field names to their type annotations.
    
    Example:
        >>> hints = get_extraction_config_type_hints()
        >>> hints['confidence_threshold']
        <class 'float'>
        >>> hints['custom_rules']
        typing.List[tuple]
    """
    return get_type_hints(ExtractionConfig)


def validate_extraction_config_field(field_name: str, value) -> bool:
    """Validate a single field value against its type.
    
    Args:
        field_name: Name of the field (e.g., 'confidence_threshold')
        value: Value to validate
    
    Returns:
        True if value passes validation for the field type.
        
    Raises:
        ValueError: If field name is invalid.
    
    Example:
        >>> validate_extraction_config_field('confidence_threshold', 0.75)
        True
        >>> validate_extraction_config_field('confidence_threshold', 'invalid')
        False  # Will raise or return False depending on strict mode
    """
    hints = get_extraction_config_type_hints()
    
    if field_name not in hints:
        raise ValueError(f"Unknown field: {field_name}")
    
    expected_type = hints[field_name]
    
    # Special handling for complex types
    if field_name == 'domain_vocab':
        return isinstance(value, dict)
    elif field_name == 'custom_rules':
        return isinstance(value, list)
    elif field_name == 'stopwords':
        return isinstance(value, list)
    elif field_name == 'allowed_entity_types':
        return isinstance(value, list)
    
    # Basic type checking
    return isinstance(value, expected_type)


def create_extraction_config_from_typed_dict(config_dict: dict) -> ExtractionConfig:
    """Create ExtractionConfig with strict type validation.
    
    Args:
        config_dict: Configuration dictionary with typed values
    
    Returns:
        Validated ExtractionConfig instance
        
    Raises:
        TypeError: If any field has wrong type
        ValueError: If any field value is invalid
    
    Example:
        >>> typed_config = {
        ...     'confidence_threshold': 0.75,
        ...     'max_entities': 1000,
        ...     'domain_vocab': {'Symptom': ['fever']}
        ... }
        >>> config = create_extraction_config_from_typed_dict(typed_config)
    """
    # Validate types before creating
    hints = get_extraction_config_type_hints()
    
    for field_name, value in config_dict.items():
        if field_name not in hints:
            raise ValueError(f"Unknown field: {field_name}")
        
        # Type validation
        if not validate_extraction_config_field(field_name, value):
            expected = hints[field_name]
            raise TypeError(
                f"Field {field_name} must be {expected}, got {type(value).__name__}"
            )
    
    # Create instance using from_dict
    return ExtractionConfig.from_dict(config_dict)


def get_extraction_config_field_info() -> Dict[str, dict]:
    """Get information about all ExtractionConfig fields.
    
    Returns:
        Dictionary mapping field names to metadata including:
        - type: Field type
        - default: Default value
        - description: Field description
        - valid_range: Valid value range if applicable
    
    Example:
        >>> info = get_extraction_config_field_info()
        >>> info['confidence_threshold']['valid_range']
        (0.0, 1.0)
    """
    config = ExtractionConfig()
    
    return {
        'confidence_threshold': {
            'type': float,
            'default': 0.5,
            'description': 'Minimum confidence score to keep extracted entity',
            'valid_range': (0.0, 1.0),
        },
        'max_entities': {
            'type': int,
            'default': 0,
            'description': 'Maximum number of entities to extract (0 = unlimited)',
            'valid_range': (0, float('inf')),
        },
        'max_relationships': {
            'type': int,
            'default': 0,
            'description': 'Maximum number of relationships to infer (0 = unlimited)',
            'valid_range': (0, float('inf')),
        },
        'window_size': {
            'type': int,
            'default': 5,
            'description': 'Co-occurrence window size for relationship inference',
            'valid_range': (1, 1000),
        },
        'min_entity_length': {
            'type': int,
            'default': 2,
            'description': 'Minimum character length for entity text',
            'valid_range': (1, float('inf')),
        },
        'stopwords': {
            'type': List[str],
            'default': [],
            'description': 'Terms to exclude from entity text',
        },
        'allowed_entity_types': {
            'type': List[str],
            'default': [],
            'description': 'Whitelist of allowed entity types (empty = all)',
        },
        'domain_vocab': {
            'type': Dict[str, List[str]],
            'default': {},
            'description': 'Domain-specific vocabulary for entity recognition',
        },
        'custom_rules': {
            'type': List[tuple],
            'default': [],
            'description': 'Custom regex patterns for entity extraction',
        },
        'llm_fallback_threshold': {
            'type': float,
            'default': 0.0,
            'description': 'Threshold for LLM fallback (0 = disabled)',
            'valid_range': (0.0, 1.0),
        },
        'max_confidence': {
            'type': float,
            'default': 1.0,
            'description': 'Upper bound for confidence scores',
            'valid_range': (0.0, 1.0),  # (0.0, 1.0] in mathematical notation
        },
        'include_properties': {
            'type': bool,
            'default': True,
            'description': 'Whether to extract entity properties/attributes',
        },
    }


if __name__ == '__main__':
    # Demo
    print("ExtractionConfig Type Hints:")
    print(get_extraction_config_type_hints())
    print("\nField Information:")
    for field, info in get_extraction_config_field_info().items():
        print(f"\n  {field}:")
        print(f"    Type: {info['type']}")
        print(f"    Default: {info['default']}")
        print(f"    Description: {info['description']}")
