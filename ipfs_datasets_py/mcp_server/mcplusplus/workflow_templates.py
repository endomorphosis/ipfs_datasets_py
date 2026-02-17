"""
MCP++ Workflow Templates System (Phase 4.5)

Implements workflow templates with:
- Template schema (JSON/YAML compatible)
- Template instantiation with parameter substitution
- Template validation
- Template composition (nested templates)
- Template library/registry

This enables reusable workflow definitions.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class TemplateFormat(Enum):
    """Template format types."""
    JSON = "json"
    YAML = "yaml"
    DICT = "dict"


@dataclass
class TemplateParameter:
    """Template parameter definition."""
    
    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str = ""
    default: Any = None
    required: bool = True
    validation: Optional[str] = None  # Regex for string validation
    
    def validate_value(self, value: Any) -> Tuple[bool, Optional[str]]:
        """
        Validate parameter value.
        
        Returns:
            (is_valid, error_message)
        """
        # Check required
        if self.required and value is None:
            return False, f"Parameter '{self.name}' is required"
        
        if value is None:
            return True, None
        
        # Check type
        type_checks = {
            "string": str,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict
        }
        
        expected_type = type_checks.get(self.type)
        if expected_type and not isinstance(value, expected_type):
            return False, f"Parameter '{self.name}' must be of type {self.type}"
        
        # Check regex validation for strings
        if self.type == "string" and self.validation:
            if not re.match(self.validation, value):
                return False, f"Parameter '{self.name}' does not match pattern '{self.validation}'"
        
        return True, None


@dataclass
class WorkflowTemplate:
    """
    Workflow template definition.
    
    A template defines a reusable workflow structure with parameters
    that can be instantiated multiple times with different values.
    """
    
    template_id: str
    name: str
    description: str
    version: str
    parameters: List[TemplateParameter] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Template composition
    includes: List[str] = field(default_factory=list)  # Other templates to include
    
    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate template definition.
        
        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        
        # Check required fields
        if not self.template_id:
            errors.append("Template ID is required")
        if not self.name:
            errors.append("Template name is required")
        if not self.steps:
            errors.append("Template must have at least one step")
        
        # Validate parameter names are unique
        param_names = [p.name for p in self.parameters]
        if len(param_names) != len(set(param_names)):
            errors.append("Parameter names must be unique")
        
        # Validate step structure
        for i, step in enumerate(self.steps):
            if 'step_id' not in step:
                errors.append(f"Step {i} missing 'step_id'")
            if 'action' not in step:
                errors.append(f"Step {i} missing 'action'")
        
        # Validate step IDs are unique
        step_ids = [s.get('step_id') for s in self.steps if 'step_id' in s]
        if len(step_ids) != len(set(step_ids)):
            errors.append("Step IDs must be unique")
        
        # Validate dependencies reference existing steps
        for step in self.steps:
            depends_on = step.get('depends_on', [])
            for dep in depends_on:
                if dep not in step_ids:
                    errors.append(f"Step '{step.get('step_id')}' depends on non-existent step '{dep}'")
        
        return len(errors) == 0, errors
    
    def get_parameter_placeholders(self) -> Set[str]:
        """Get all parameter placeholders used in the template."""
        placeholders = set()
        
        # Find all ${param_name} patterns
        def find_placeholders(obj):
            if isinstance(obj, str):
                matches = re.findall(r'\$\{(\w+)\}', obj)
                placeholders.update(matches)
            elif isinstance(obj, dict):
                for value in obj.values():
                    find_placeholders(value)
            elif isinstance(obj, list):
                for item in obj:
                    find_placeholders(item)
        
        find_placeholders(self.steps)
        return placeholders
    
    def instantiate(
        self,
        parameters: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Instantiate template with parameter values.
        
        Args:
            parameters: Parameter values
            workflow_id: Optional workflow ID (auto-generated if None)
            
        Returns:
            Instantiated workflow definition
        """
        # Validate parameters
        errors = []
        for param_def in self.parameters:
            value = parameters.get(param_def.name, param_def.default)
            is_valid, error = param_def.validate_value(value)
            if not is_valid:
                errors.append(error)
        
        if errors:
            raise ValueError(f"Parameter validation failed: {'; '.join(errors)}")
        
        # Check for undefined parameters
        used_placeholders = self.get_parameter_placeholders()
        defined_params = {p.name for p in self.parameters}
        undefined = used_placeholders - defined_params
        if undefined:
            logger.warning(f"Undefined parameter placeholders: {undefined}")
        
        # Fill in defaults
        final_params = {}
        for param_def in self.parameters:
            final_params[param_def.name] = parameters.get(param_def.name, param_def.default)
        
        # Substitute parameters in steps
        def substitute(obj, params):
            if isinstance(obj, str):
                # Replace ${param_name} with value
                for name, value in params.items():
                    placeholder = f"${{{name}}}"
                    if placeholder in obj:
                        # If the whole string is just the placeholder, replace with value directly
                        if obj == placeholder:
                            return value
                        # Otherwise, replace within string
                        obj = obj.replace(placeholder, str(value))
                return obj
            elif isinstance(obj, dict):
                return {k: substitute(v, params) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [substitute(item, params) for item in obj]
            return obj
        
        instantiated_steps = substitute(self.steps, final_params)
        
        # Generate workflow ID if not provided
        if workflow_id is None:
            import time
            workflow_id = f"{self.template_id}-{int(time.time() * 1000000)}"
        
        return {
            'workflow_id': workflow_id,
            'name': f"{self.name} ({workflow_id})",
            'template_id': self.template_id,
            'template_version': self.version,
            'parameters': final_params,
            'steps': instantiated_steps,
            'metadata': {
                **self.metadata,
                'instantiated_from_template': True
            }
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert template to dictionary."""
        return {
            'template_id': self.template_id,
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'parameters': [asdict(p) for p in self.parameters],
            'steps': self.steps,
            'metadata': self.metadata,
            'includes': self.includes
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkflowTemplate':
        """Create template from dictionary."""
        parameters = [
            TemplateParameter(**p) for p in data.get('parameters', [])
        ]
        
        return cls(
            template_id=data['template_id'],
            name=data['name'],
            description=data.get('description', ''),
            version=data.get('version', '1.0.0'),
            parameters=parameters,
            steps=data.get('steps', []),
            metadata=data.get('metadata', {}),
            includes=data.get('includes', [])
        )


class TemplateRegistry:
    """
    Template registry for storing and retrieving workflow templates.
    
    Supports:
    - Template registration and lookup
    - Template versioning
    - Template composition (includes)
    - Template validation
    """
    
    def __init__(self):
        """Initialize template registry."""
        self._templates: Dict[str, Dict[str, WorkflowTemplate]] = {}  # {template_id: {version: template}}
    
    def register(self, template: WorkflowTemplate, overwrite: bool = False) -> None:
        """
        Register a template.
        
        Args:
            template: Template to register
            overwrite: Whether to overwrite existing template
        """
        # Validate template
        is_valid, errors = template.validate()
        if not is_valid:
            raise ValueError(f"Template validation failed: {'; '.join(errors)}")
        
        # Check if template exists
        if template.template_id in self._templates:
            versions = self._templates[template.template_id]
            if template.version in versions and not overwrite:
                raise ValueError(
                    f"Template '{template.template_id}' version '{template.version}' already exists"
                )
        else:
            self._templates[template.template_id] = {}
        
        self._templates[template.template_id][template.version] = template
        logger.info(f"Registered template '{template.template_id}' version '{template.version}'")
    
    def get(
        self,
        template_id: str,
        version: Optional[str] = None
    ) -> Optional[WorkflowTemplate]:
        """
        Get a template by ID and optional version.
        
        Args:
            template_id: Template ID
            version: Optional version (gets latest if None)
            
        Returns:
            Template or None if not found
        """
        if template_id not in self._templates:
            return None
        
        versions = self._templates[template_id]
        
        if version:
            return versions.get(version)
        
        # Get latest version
        if not versions:
            return None
        
        latest_version = max(versions.keys())
        return versions[latest_version]
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """
        List all templates.
        
        Returns:
            List of template metadata
        """
        templates = []
        for template_id, versions in self._templates.items():
            for version, template in versions.items():
                templates.append({
                    'template_id': template_id,
                    'name': template.name,
                    'version': version,
                    'description': template.description,
                    'parameter_count': len(template.parameters),
                    'step_count': len(template.steps)
                })
        return templates
    
    def delete(
        self,
        template_id: str,
        version: Optional[str] = None
    ) -> bool:
        """
        Delete a template.
        
        Args:
            template_id: Template ID
            version: Optional version (deletes all versions if None)
            
        Returns:
            True if template was deleted
        """
        if template_id not in self._templates:
            return False
        
        if version:
            if version in self._templates[template_id]:
                del self._templates[template_id][version]
                if not self._templates[template_id]:
                    del self._templates[template_id]
                return True
            return False
        
        # Delete all versions
        del self._templates[template_id]
        return True
    
    def compose_template(
        self,
        template: WorkflowTemplate
    ) -> WorkflowTemplate:
        """
        Compose template by resolving includes.
        
        Args:
            template: Template with potential includes
            
        Returns:
            Composed template with all includes resolved
        """
        if not template.includes:
            return template
        
        # Resolve includes
        composed_steps = []
        composed_parameters = list(template.parameters)
        
        for include_id in template.includes:
            included = self.get(include_id)
            if not included:
                logger.warning(f"Included template '{include_id}' not found")
                continue
            
            # Add included steps (with prefix to avoid conflicts)
            for step in included.steps:
                prefixed_step = step.copy()
                prefixed_step['step_id'] = f"{include_id}_{step['step_id']}"
                
                # Update dependencies
                if 'depends_on' in prefixed_step:
                    prefixed_step['depends_on'] = [
                        f"{include_id}_{dep}" for dep in prefixed_step['depends_on']
                    ]
                
                composed_steps.append(prefixed_step)
            
            # Add included parameters (if not conflicting)
            param_names = {p.name for p in composed_parameters}
            for param in included.parameters:
                if param.name not in param_names:
                    composed_parameters.append(param)
        
        # Add template's own steps
        composed_steps.extend(template.steps)
        
        # Create composed template
        composed = WorkflowTemplate(
            template_id=template.template_id,
            name=template.name,
            description=template.description,
            version=template.version,
            parameters=composed_parameters,
            steps=composed_steps,
            metadata=template.metadata
        )
        
        return composed
    
    def save_to_file(self, path: Path) -> None:
        """Save registry to JSON file."""
        data = {
            'templates': {
                template_id: {
                    version: template.to_dict()
                    for version, template in versions.items()
                }
                for template_id, versions in self._templates.items()
            }
        }
        
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Saved template registry to {path}")
    
    def load_from_file(self, path: Path) -> None:
        """Load registry from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        
        for template_id, versions in data.get('templates', {}).items():
            for version, template_data in versions.items():
                template = WorkflowTemplate.from_dict(template_data)
                self.register(template, overwrite=True)
        
        logger.info(f"Loaded template registry from {path}")


# Example usage
if __name__ == '__main__':
    # Create a template
    template = WorkflowTemplate(
        template_id='data_processing',
        name='Data Processing Pipeline',
        description='Process data from source to destination',
        version='1.0.0',
        parameters=[
            TemplateParameter(
                name='source_url',
                type='string',
                description='Source data URL',
                required=True
            ),
            TemplateParameter(
                name='output_format',
                type='string',
                description='Output format (json, csv, parquet)',
                default='json',
                required=False,
                validation=r'^(json|csv|parquet)$'
            ),
            TemplateParameter(
                name='batch_size',
                type='number',
                description='Batch size for processing',
                default=100,
                required=False
            )
        ],
        steps=[
            {
                'step_id': 'fetch',
                'action': 'fetch_data',
                'inputs': {
                    'url': '${source_url}',
                    'batch_size': '${batch_size}'
                }
            },
            {
                'step_id': 'transform',
                'action': 'transform_data',
                'inputs': {
                    'format': '${output_format}'
                },
                'depends_on': ['fetch']
            },
            {
                'step_id': 'store',
                'action': 'store_data',
                'inputs': {},
                'depends_on': ['transform']
            }
        ]
    )
    
    # Validate template
    is_valid, errors = template.validate()
    print(f"Template valid: {is_valid}")
    if errors:
        print(f"Errors: {errors}")
    
    # Instantiate template
    workflow = template.instantiate({
        'source_url': 'https://example.com/data',
        'output_format': 'parquet',
        'batch_size': 500
    })
    
    print("\nInstantiated workflow:")
    print(json.dumps(workflow, indent=2))
    
    # Test template registry
    print("\n\nTesting Template Registry:")
    registry = TemplateRegistry()
    
    registry.register(template)
    
    # Get template
    retrieved = registry.get('data_processing')
    print(f"Retrieved template: {retrieved.name}")
    
    # List templates
    templates = registry.list_templates()
    print(f"\nTemplates in registry: {len(templates)}")
    for t in templates:
        print(f"  - {t['name']} v{t['version']}")
