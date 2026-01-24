#!/usr/bin/env python3
"""
Test suite for workflow tools functionality.
"""

import pytest
import anyio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestWorkflowTools:
    """Test workflow tools functionality."""

    @pytest.mark.asyncio
    async def test_create_workflow(self):
        """Test workflow creation."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import create_workflow
        
        workflow_definition = {
            "name": "test-workflow",
            "steps": [
                {"type": "load_dataset", "params": {"source": "test_data"}},
                {"type": "generate_embeddings", "params": {"model": "test-model"}},
                {"type": "store_vectors", "params": {"index": "test-index"}}
            ]
        }
        
        result = await create_workflow(
            workflow_definition=workflow_definition,
            workflow_id="test-workflow-001"
        )
        
        assert result is not None
        assert "status" in result
        assert "workflow_id" in result or "id" in result
    
    @pytest.mark.asyncio
    async def test_execute_workflow(self):
        """Test workflow execution."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import execute_workflow
        
        result = await execute_workflow(
            workflow_id="test-workflow-001",
            execution_params={"batch_size": 100},
            async_execution=True
        )
        
        assert result is not None
        assert "status" in result
        assert "execution_id" in result or "job_id" in result
    
    @pytest.mark.asyncio
    async def test_get_workflow_status(self):
        """Test workflow status monitoring."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import get_workflow_status
        
        result = await get_workflow_status(
            workflow_id="test-workflow-001",
            execution_id="exec-001"
        )
        
        assert result is not None
        assert "status" in result
        assert "workflow_status" in result or "state" in result
    
    @pytest.mark.asyncio
    async def test_list_workflows(self):
        """Test listing available workflows."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import list_workflows
        
        result = await list_workflows(
            filter_by_status="active",
            include_metadata=True
        )
        
        assert result is not None
        assert "status" in result
        assert "workflows" in result or "workflow_list" in result
    
    @pytest.mark.asyncio
    async def test_pause_resume_workflow(self):
        """Test workflow pause and resume functionality."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import pause_workflow, resume_workflow
        
        # Test pause
        pause_result = await pause_workflow(
            workflow_id="test-workflow-001",
            execution_id="exec-001"
        )
        
        assert pause_result is not None
        assert "status" in pause_result
        
        # Test resume
        resume_result = await resume_workflow(
            workflow_id="test-workflow-001",
            execution_id="exec-001"
        )
        
        assert resume_result is not None
        assert "status" in resume_result
    
    @pytest.mark.asyncio
    async def test_workflow_template_management(self):
        """Test workflow template management."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import manage_workflow_templates
        
        template = {
            "name": "embedding-pipeline",
            "description": "Standard embedding generation pipeline",
            "steps": [
                {"type": "load_dataset", "params": {}},
                {"type": "chunk_text", "params": {"chunk_size": 512}},
                {"type": "generate_embeddings", "params": {}},
                {"type": "store_vectors", "params": {}}
            ]
        }
        
        result = await manage_workflow_templates(
            action="create",
            template_id="embedding-pipeline-v1",
            template_data=template
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_workflow_scheduling(self):
        """Test workflow scheduling functionality."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import schedule_workflow
        
        result = await schedule_workflow(
            workflow_id="test-workflow-001",
            schedule_type="cron",
            schedule_expression="0 2 * * *",  # Daily at 2 AM
            enabled=True
        )
        
        assert result is not None
        assert "status" in result
        assert "schedule_id" in result or "scheduler_id" in result


class TestWorkflowOrchestration:
    """Test workflow orchestration and dependencies."""

    @pytest.mark.asyncio
    async def test_workflow_with_dependencies(self):
        """Test workflow execution with dependencies."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import create_workflow
        
        workflow_with_deps = {
            "name": "complex-workflow",
            "steps": [
                {
                    "id": "step1",
                    "type": "load_dataset",
                    "params": {"source": "dataset1"}
                },
                {
                    "id": "step2", 
                    "type": "generate_embeddings",
                    "params": {"model": "model1"},
                    "depends_on": ["step1"]
                },
                {
                    "id": "step3",
                    "type": "store_vectors",
                    "params": {"index": "index1"},
                    "depends_on": ["step2"]
                }
            ]
        }
        
        result = await create_workflow(
            workflow_definition=workflow_with_deps,
            workflow_id="complex-workflow-001"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_parallel_workflow_steps(self):
        """Test parallel execution of workflow steps."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import execute_workflow
        
        result = await execute_workflow(
            workflow_id="complex-workflow-001",
            execution_params={
                "parallel_execution": True,
                "max_parallel_steps": 3
            }
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_workflow_error_handling(self):
        """Test workflow error handling and recovery."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import handle_workflow_error
        
        result = await handle_workflow_error(
            workflow_id="test-workflow-001",
            execution_id="exec-001",
            error_info={"step": "step2", "error": "Model not found"},
            recovery_action="retry"
        )
        
        assert result is not None
        assert "status" in result


class TestWorkflowMonitoring:
    """Test workflow monitoring and logging."""

    @pytest.mark.asyncio
    async def test_get_workflow_logs(self):
        """Test retrieving workflow execution logs."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import get_workflow_logs
        
        result = await get_workflow_logs(
            workflow_id="test-workflow-001",
            execution_id="exec-001",
            log_level="INFO",
            max_lines=100
        )
        
        assert result is not None
        assert "status" in result
        assert "logs" in result or "log_entries" in result
    
    @pytest.mark.asyncio
    async def test_workflow_metrics(self):
        """Test workflow performance metrics."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import get_workflow_metrics
        
        result = await get_workflow_metrics(
            workflow_id="test-workflow-001",
            metric_types=["execution_time", "success_rate", "resource_usage"]
        )
        
        assert result is not None
        assert "status" in result
        assert "metrics" in result or "performance_data" in result
    
    @pytest.mark.asyncio
    async def test_workflow_alerts(self):
        """Test workflow alerting system."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import configure_workflow_alerts
        
        alert_config = {
            "failure_alert": True,
            "long_running_threshold": 3600,  # 1 hour
            "notification_channels": ["email", "slack"]
        }
        
        result = await configure_workflow_alerts(
            workflow_id="test-workflow-001",
            alert_configuration=alert_config
        )
        
        assert result is not None
        assert "status" in result


class TestWorkflowToolsIntegration:
    """Test workflow tools integration with other components."""

    @pytest.mark.asyncio
    async def test_workflow_tools_mcp_registration(self):
        """Test that workflow tools are properly registered with MCP."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import get_registered_tools
        
        tools = get_registered_tools()
        workflow_tools = [tool for tool in tools if 'workflow' in tool.get('name', '').lower()]
        
        assert len(workflow_tools) > 0, "Workflow tools should be registered"
    
    @pytest.mark.asyncio
    async def test_workflow_integration_with_datasets(self):
        """Test workflow integration with dataset tools."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import create_workflow
        
        # Create workflow that uses dataset tools
        dataset_workflow = {
            "name": "dataset-processing-workflow",
            "steps": [
                {"type": "load_dataset", "params": {"source": "test-dataset"}},
                {"type": "process_dataset", "params": {"operations": [{"type": "filter"}]}},
                {"type": "save_dataset", "params": {"destination": "processed-dataset"}}
            ]
        }
        
        result = await create_workflow(
            workflow_definition=dataset_workflow,
            workflow_id="dataset-workflow-001"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_workflow_integration_with_embeddings(self):
        """Test workflow integration with embedding tools."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import create_workflow
        
        # Create workflow that uses embedding tools
        embedding_workflow = {
            "name": "embedding-workflow",
            "steps": [
                {"type": "load_dataset", "params": {"source": "text-dataset"}},
                {"type": "generate_embeddings", "params": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
                {"type": "create_vector_index", "params": {"index_name": "text-embeddings"}}
            ]
        }
        
        result = await create_workflow(
            workflow_definition=embedding_workflow,
            workflow_id="embedding-workflow-001"
        )
        
        assert result is not None
        assert "status" in result


class TestWorkflowValidation:
    """Test workflow validation and schema checking."""

    @pytest.mark.asyncio
    async def test_validate_workflow_definition(self):
        """Test workflow definition validation."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import validate_workflow_definition
        
        valid_workflow = {
            "name": "valid-workflow",
            "steps": [
                {"type": "load_dataset", "params": {"source": "test"}}
            ]
        }
        
        result = await validate_workflow_definition(workflow_definition=valid_workflow)
        
        assert result is not None
        assert "status" in result
        assert "valid" in result or "validation_result" in result
    
    @pytest.mark.asyncio
    async def test_invalid_workflow_definition(self):
        """Test handling of invalid workflow definitions."""
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import validate_workflow_definition
        
        invalid_workflow = {
            "name": "",  # Empty name
            "steps": []  # No steps
        }
        
        result = await validate_workflow_definition(workflow_definition=invalid_workflow)
        
        assert result is not None
        assert "status" in result
        # Should indicate validation failure
        assert result.get("valid", True) == False or "error" in result.get("status", "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
