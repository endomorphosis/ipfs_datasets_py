"""
Tests for MCP++ Workflow Templates System (Phase 4.5)

Tests template validation, instantiation, composition, and registry.
"""

import pytest
import tempfile
from pathlib import Path
import json

from ipfs_datasets_py.mcp_server.mcplusplus.workflow_templates import (
    TemplateParameter,
    WorkflowTemplate,
    TemplateRegistry
)


# Tests

class TestTemplateParameter:
    """Test TemplateParameter class."""
    
    def test_parameter_creation(self):
        """Test creating a template parameter."""
        param = TemplateParameter(
            name='test_param',
            type='string',
            description='Test parameter',
            default='default_value',
            required=False
        )
        
        assert param.name == 'test_param'
        assert param.type == 'string'
        assert param.default == 'default_value'
        assert param.required is False
    
    def test_validate_required_missing(self):
        """Test validation fails for missing required parameter."""
        param = TemplateParameter(name='test', type='string', required=True)
        
        is_valid, error = param.validate_value(None)
        
        assert is_valid is False
        assert 'required' in error.lower()
    
    def test_validate_type_mismatch(self):
        """Test validation fails for type mismatch."""
        param = TemplateParameter(name='test', type='number', required=True)
        
        is_valid, error = param.validate_value('not_a_number')
        
        assert is_valid is False
        assert 'type' in error.lower()
    
    def test_validate_regex_pattern(self):
        """Test validation with regex pattern."""
        param = TemplateParameter(
            name='format',
            type='string',
            required=True,
            validation=r'^(json|csv|xml)$'
        )
        
        # Valid value
        is_valid, error = param.validate_value('json')
        assert is_valid is True
        
        # Invalid value
        is_valid, error = param.validate_value('invalid')
        assert is_valid is False
    
    def test_validate_optional_with_default(self):
        """Test validation of optional parameter with default."""
        param = TemplateParameter(
            name='test',
            type='string',
            required=False,
            default='default'
        )
        
        is_valid, error = param.validate_value(None)
        assert is_valid is True


class TestWorkflowTemplate:
    """Test WorkflowTemplate class."""
    
    def test_template_creation(self):
        """Test creating a workflow template."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test Template',
            description='Test description',
            version='1.0.0',
            parameters=[
                TemplateParameter(name='param1', type='string', required=True)
            ],
            steps=[
                {'step_id': 'step1', 'action': 'test_action'}
            ]
        )
        
        assert template.template_id == 'test'
        assert template.name == 'Test Template'
        assert len(template.parameters) == 1
        assert len(template.steps) == 1
    
    def test_validate_success(self):
        """Test validation of valid template."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[
                {'step_id': 'step1', 'action': 'action1'}
            ]
        )
        
        is_valid, errors = template.validate()
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_validate_missing_required_fields(self):
        """Test validation catches missing required fields."""
        template = WorkflowTemplate(
            template_id='',
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[]
        )
        
        is_valid, errors = template.validate()
        
        assert is_valid is False
        assert any('Template ID' in e for e in errors)
        assert any('at least one step' in e for e in errors)
    
    def test_validate_duplicate_step_ids(self):
        """Test validation catches duplicate step IDs."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[
                {'step_id': 'step1', 'action': 'action1'},
                {'step_id': 'step1', 'action': 'action2'}  # Duplicate
            ]
        )
        
        is_valid, errors = template.validate()
        
        assert is_valid is False
        assert any('unique' in e.lower() for e in errors)
    
    def test_validate_invalid_dependencies(self):
        """Test validation catches invalid dependencies."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[
                {'step_id': 'step1', 'action': 'action1', 'depends_on': ['nonexistent']}
            ]
        )
        
        is_valid, errors = template.validate()
        
        assert is_valid is False
        assert any('non-existent' in e.lower() for e in errors)
    
    def test_get_parameter_placeholders(self):
        """Test extracting parameter placeholders."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[
                {
                    'step_id': 'step1',
                    'action': 'action1',
                    'inputs': {
                        'url': '${source_url}',
                        'format': '${output_format}'
                    }
                }
            ]
        )
        
        placeholders = template.get_parameter_placeholders()
        
        assert 'source_url' in placeholders
        assert 'output_format' in placeholders
    
    def test_instantiate_success(self):
        """Test successful template instantiation."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            parameters=[
                TemplateParameter(name='url', type='string', required=True),
                TemplateParameter(name='format', type='string', default='json', required=False)
            ],
            steps=[
                {
                    'step_id': 'fetch',
                    'action': 'fetch_data',
                    'inputs': {'url': '${url}', 'format': '${format}'}
                }
            ]
        )
        
        workflow = template.instantiate({
            'url': 'https://example.com/data'
        })
        
        assert workflow['template_id'] == 'test'
        assert workflow['parameters']['url'] == 'https://example.com/data'
        assert workflow['parameters']['format'] == 'json'  # Default value
        assert workflow['steps'][0]['inputs']['url'] == 'https://example.com/data'
        assert workflow['steps'][0]['inputs']['format'] == 'json'
    
    def test_instantiate_with_custom_workflow_id(self):
        """Test instantiation with custom workflow ID."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        workflow = template.instantiate({}, workflow_id='custom-id')
        
        assert workflow['workflow_id'] == 'custom-id'
    
    def test_instantiate_parameter_validation_failure(self):
        """Test instantiation fails with invalid parameters."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            parameters=[
                TemplateParameter(name='count', type='number', required=True)
            ],
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        with pytest.raises(ValueError, match="Parameter validation failed"):
            template.instantiate({'count': 'not_a_number'})
    
    def test_instantiate_substitutes_nested_values(self):
        """Test parameter substitution in nested structures."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            parameters=[
                TemplateParameter(name='value', type='number', required=True)
            ],
            steps=[
                {
                    'step_id': 'step1',
                    'action': 'action1',
                    'inputs': {
                        'nested': {
                            'value': '${value}',
                            'list': ['item1', '${value}', 'item3']
                        }
                    }
                }
            ]
        )
        
        workflow = template.instantiate({'value': 42})
        
        assert workflow['steps'][0]['inputs']['nested']['value'] == 42
        assert workflow['steps'][0]['inputs']['nested']['list'][1] == 42
    
    def test_to_dict_and_from_dict(self):
        """Test converting template to/from dictionary."""
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            parameters=[
                TemplateParameter(name='param1', type='string', required=True)
            ],
            steps=[
                {'step_id': 'step1', 'action': 'action1'}
            ]
        )
        
        # Convert to dict
        template_dict = template.to_dict()
        
        assert template_dict['template_id'] == 'test'
        assert len(template_dict['parameters']) == 1
        
        # Convert back from dict
        restored = WorkflowTemplate.from_dict(template_dict)
        
        assert restored.template_id == template.template_id
        assert restored.name == template.name
        assert len(restored.parameters) == len(template.parameters)


class TestTemplateRegistry:
    """Test TemplateRegistry class."""
    
    def test_registry_initialization(self):
        """Test registry initialization."""
        registry = TemplateRegistry()
        
        templates = registry.list_templates()
        assert len(templates) == 0
    
    def test_register_template(self):
        """Test registering a template."""
        registry = TemplateRegistry()
        
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        registry.register(template)
        
        retrieved = registry.get('test')
        assert retrieved is not None
        assert retrieved.template_id == 'test'
    
    def test_register_duplicate_without_overwrite(self):
        """Test registering duplicate template fails without overwrite."""
        registry = TemplateRegistry()
        
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        registry.register(template)
        
        with pytest.raises(ValueError, match="already exists"):
            registry.register(template, overwrite=False)
    
    def test_register_duplicate_with_overwrite(self):
        """Test registering duplicate template succeeds with overwrite."""
        registry = TemplateRegistry()
        
        template1 = WorkflowTemplate(
            template_id='test',
            name='Test 1',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        template2 = WorkflowTemplate(
            template_id='test',
            name='Test 2',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        registry.register(template1)
        registry.register(template2, overwrite=True)
        
        retrieved = registry.get('test')
        assert retrieved.name == 'Test 2'
    
    def test_register_invalid_template(self):
        """Test registering invalid template fails."""
        registry = TemplateRegistry()
        
        invalid_template = WorkflowTemplate(
            template_id='',  # Invalid: empty ID
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[]  # Invalid: no steps
        )
        
        with pytest.raises(ValueError, match="validation failed"):
            registry.register(invalid_template)
    
    def test_get_template_by_version(self):
        """Test getting template by specific version."""
        registry = TemplateRegistry()
        
        template_v1 = WorkflowTemplate(
            template_id='test',
            name='Test V1',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        template_v2 = WorkflowTemplate(
            template_id='test',
            name='Test V2',
            description='Test',
            version='2.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        registry.register(template_v1)
        registry.register(template_v2)
        
        retrieved_v1 = registry.get('test', version='1.0.0')
        retrieved_v2 = registry.get('test', version='2.0.0')
        
        assert retrieved_v1.name == 'Test V1'
        assert retrieved_v2.name == 'Test V2'
    
    def test_get_latest_version(self):
        """Test getting latest version when no version specified."""
        registry = TemplateRegistry()
        
        template_v1 = WorkflowTemplate(
            template_id='test',
            name='Test V1',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        template_v2 = WorkflowTemplate(
            template_id='test',
            name='Test V2',
            description='Test',
            version='2.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        registry.register(template_v1)
        registry.register(template_v2)
        
        latest = registry.get('test')
        assert latest.version == '2.0.0'
    
    def test_list_templates(self):
        """Test listing all templates."""
        registry = TemplateRegistry()
        
        template1 = WorkflowTemplate(
            template_id='test1',
            name='Test 1',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        template2 = WorkflowTemplate(
            template_id='test2',
            name='Test 2',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        registry.register(template1)
        registry.register(template2)
        
        templates = registry.list_templates()
        
        assert len(templates) == 2
        template_ids = [t['template_id'] for t in templates]
        assert 'test1' in template_ids
        assert 'test2' in template_ids
    
    def test_delete_template_version(self):
        """Test deleting specific template version."""
        registry = TemplateRegistry()
        
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        registry.register(template)
        deleted = registry.delete('test', version='1.0.0')
        
        assert deleted is True
        assert registry.get('test') is None
    
    def test_delete_all_versions(self):
        """Test deleting all versions of a template."""
        registry = TemplateRegistry()
        
        template_v1 = WorkflowTemplate(
            template_id='test',
            name='Test V1',
            description='Test',
            version='1.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        template_v2 = WorkflowTemplate(
            template_id='test',
            name='Test V2',
            description='Test',
            version='2.0.0',
            steps=[{'step_id': 'step1', 'action': 'action1'}]
        )
        
        registry.register(template_v1)
        registry.register(template_v2)
        
        deleted = registry.delete('test')
        
        assert deleted is True
        assert registry.get('test', version='1.0.0') is None
        assert registry.get('test', version='2.0.0') is None
    
    def test_compose_template(self):
        """Test template composition."""
        registry = TemplateRegistry()
        
        # Base template
        base = WorkflowTemplate(
            template_id='base',
            name='Base',
            description='Base template',
            version='1.0.0',
            parameters=[
                TemplateParameter(name='base_param', type='string', required=True)
            ],
            steps=[
                {'step_id': 'base_step', 'action': 'base_action'}
            ]
        )
        
        registry.register(base)
        
        # Template with include
        main = WorkflowTemplate(
            template_id='main',
            name='Main',
            description='Main template',
            version='1.0.0',
            includes=['base'],
            parameters=[
                TemplateParameter(name='main_param', type='string', required=True)
            ],
            steps=[
                {'step_id': 'main_step', 'action': 'main_action', 'depends_on': ['base_base_step']}
            ]
        )
        
        composed = registry.compose_template(main)
        
        # Should have steps from both templates
        assert len(composed.steps) > 1
        step_ids = [s['step_id'] for s in composed.steps]
        assert 'base_base_step' in step_ids
        assert 'main_step' in step_ids
        
        # Should have parameters from both templates
        param_names = [p.name for p in composed.parameters]
        assert 'base_param' in param_names
        assert 'main_param' in param_names
    
    def test_save_and_load_registry(self):
        """Test saving and loading registry."""
        registry = TemplateRegistry()
        
        template = WorkflowTemplate(
            template_id='test',
            name='Test',
            description='Test',
            version='1.0.0',
            parameters=[
                TemplateParameter(name='param1', type='string', required=True)
            ],
            steps=[
                {'step_id': 'step1', 'action': 'action1'}
            ]
        )
        
        registry.register(template)
        
        # Save to file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = Path(f.name)
        
        try:
            registry.save_to_file(temp_path)
            
            # Load into new registry
            new_registry = TemplateRegistry()
            new_registry.load_from_file(temp_path)
            
            retrieved = new_registry.get('test')
            assert retrieved is not None
            assert retrieved.name == 'Test'
            assert len(retrieved.parameters) == 1
        finally:
            temp_path.unlink()


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
