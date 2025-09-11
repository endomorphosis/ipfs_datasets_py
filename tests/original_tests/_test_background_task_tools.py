#!/usr/bin/env python3
"""
Test suite for background task tools functionality.
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestBackgroundTaskTools:
    """Test background task tools functionality."""

    @pytest.mark.asyncio
    async def test_create_background_task(self):
        """Test background task creation."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import create_background_task
        
        task_config = {
            "name": "embedding_generation",
            "function": "generate_embeddings",
            "parameters": {
                "dataset_id": "test_dataset",
                "model": "sentence-transformers/all-MiniLM-L6-v2"
            },
            "schedule": "immediate"
        }
        
        result = await create_background_task(
            task_configuration=task_config,
            priority="normal",
            max_retries=3
        )
        
        assert result is not None
        assert "status" in result
        assert "task_id" in result or "job_id" in result
    
    @pytest.mark.asyncio
    async def test_get_task_status(self):
        """Test getting background task status."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import get_task_status
        
        result = await get_task_status(
            task_id="task_123",
            include_logs=True
        )
        
        assert result is not None
        assert "status" in result
        assert "task_status" in result or "state" in result
    
    @pytest.mark.asyncio
    async def test_cancel_background_task(self):
        """Test canceling background task."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import cancel_background_task
        
        result = await cancel_background_task(
            task_id="task_123",
            reason="user_request"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_list_background_tasks(self):
        """Test listing background tasks."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import list_background_tasks
        
        result = await list_background_tasks(
            status_filter="running",
            limit=10,
            include_completed=False
        )
        
        assert result is not None
        assert "status" in result
        assert "tasks" in result or "task_list" in result
    
    @pytest.mark.asyncio
    async def test_schedule_recurring_task(self):
        """Test scheduling recurring background task."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import schedule_recurring_task
        
        task_config = {
            "name": "periodic_cleanup",
            "function": "cleanup_temporary_files",
            "parameters": {"max_age_days": 7}
        }
        
        result = await schedule_recurring_task(
            task_configuration=task_config,
            schedule_expression="0 2 * * *",  # Daily at 2 AM
            enabled=True
        )
        
        assert result is not None
        assert "status" in result
        assert "schedule_id" in result or "job_id" in result
    
    @pytest.mark.asyncio
    async def test_task_queue_management(self):
        """Test task queue management."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import manage_task_queue
        
        result = await manage_task_queue(
            action="status",
            queue_name="default",
            max_size=100
        )
        
        assert result is not None
        assert "status" in result
        assert "queue_status" in result or "queue_info" in result


class TestTaskMonitoring:
    """Test background task monitoring functionality."""

    @pytest.mark.asyncio
    async def test_get_task_logs(self):
        """Test retrieving task logs."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import get_task_logs
        
        result = await get_task_logs(
            task_id="task_123",
            log_level="INFO",
            max_lines=100
        )
        
        assert result is not None
        assert "status" in result
        assert "logs" in result or "log_entries" in result
    
    @pytest.mark.asyncio
    async def test_get_task_metrics(self):
        """Test retrieving task performance metrics."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import get_task_metrics
        
        result = await get_task_metrics(
            task_id="task_123",
            metric_types=["execution_time", "memory_usage", "cpu_usage"]
        )
        
        assert result is not None
        assert "status" in result
        assert "metrics" in result or "performance_data" in result
    
    @pytest.mark.asyncio
    async def test_monitor_task_progress(self):
        """Test monitoring task progress."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import monitor_task_progress
        
        result = await monitor_task_progress(
            task_id="task_123",
            real_time=True
        )
        
        assert result is not None
        assert "status" in result
        assert "progress" in result or "progress_info" in result


class TestTaskRetryAndRecovery:
    """Test task retry and recovery functionality."""

    @pytest.mark.asyncio
    async def test_retry_failed_task(self):
        """Test retrying failed task."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import retry_failed_task
        
        result = await retry_failed_task(
            task_id="failed_task_123",
            modified_parameters={"timeout": 300},
            max_retries=3
        )
        
        assert result is not None
        assert "status" in result
        assert "retry_task_id" in result or "new_task_id" in result
    
    @pytest.mark.asyncio
    async def test_task_error_handling(self):
        """Test task error handling and recovery."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import handle_task_error
        
        error_info = {
            "error_type": "TimeoutError",
            "error_message": "Task execution timed out",
            "error_code": "TIMEOUT"
        }
        
        result = await handle_task_error(
            task_id="task_123",
            error_info=error_info,
            recovery_action="retry_with_increased_timeout"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_bulk_task_operations(self):
        """Test bulk operations on tasks."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import bulk_task_operations
        
        task_ids = ["task_1", "task_2", "task_3"]
        
        result = await bulk_task_operations(
            operation="cancel",
            task_ids=task_ids,
            reason="maintenance_window"
        )
        
        assert result is not None
        assert "status" in result
        assert "operation_results" in result or "results" in result


class TestTaskIntegration:
    """Test background task tools integration."""

    @pytest.mark.asyncio
    async def test_embedding_generation_task(self):
        """Test embedding generation as background task."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import create_background_task
        
        embedding_task = {
            "name": "batch_embedding_generation",
            "function": "generate_embeddings_batch",
            "parameters": {
                "texts": ["Sample text 1", "Sample text 2"],
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "batch_size": 10
            },
            "schedule": "immediate"
        }
        
        result = await create_background_task(
            task_configuration=embedding_task,
            priority="high"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_dataset_processing_task(self):
        """Test dataset processing as background task."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import create_background_task
        
        processing_task = {
            "name": "dataset_processing",
            "function": "process_dataset",
            "parameters": {
                "dataset_id": "large_dataset",
                "operations": [
                    {"type": "filter", "params": {"condition": "length > 100"}},
                    {"type": "chunk", "params": {"chunk_size": 512}}
                ]
            },
            "schedule": "immediate"
        }
        
        result = await create_background_task(
            task_configuration=processing_task,
            priority="normal"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_vector_indexing_task(self):
        """Test vector indexing as background task."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import create_background_task
        
        indexing_task = {
            "name": "vector_indexing",
            "function": "create_vector_index",
            "parameters": {
                "vectors": "embeddings_batch_001",
                "index_name": "document_embeddings",
                "index_type": "qdrant"
            },
            "schedule": "immediate"
        }
        
        result = await create_background_task(
            task_configuration=indexing_task,
            priority="normal"
        )
        
        assert result is not None
        assert "status" in result


class TestBackgroundTaskToolsIntegration:
    """Test background task tools integration with other components."""

    @pytest.mark.asyncio
    async def test_background_task_tools_mcp_registration(self):
        """Test that background task tools are properly registered with MCP."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import get_registered_tools
        
        tools = get_registered_tools()
        background_tools = [tool for tool in tools if 'background' in tool.get('name', '').lower() or 'task' in tool.get('name', '').lower()]
        
        assert len(background_tools) > 0, "Background task tools should be registered"
    
    @pytest.mark.asyncio
    async def test_task_status_persistence(self):
        """Test that task status is properly persisted."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import create_background_task, get_task_status
        
        # Create a task
        task_config = {
            "name": "test_persistence",
            "function": "simple_task",
            "parameters": {"test": True}
        }
        
        create_result = await create_background_task(task_configuration=task_config)
        
        if create_result.get("status") == "success" and "task_id" in create_result:
            # Check status
            status_result = await get_task_status(task_id=create_result["task_id"])
            
            assert status_result is not None
            assert "status" in status_result
    
    @pytest.mark.asyncio
    async def test_task_error_handling(self):
        """Test background task error handling."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import create_background_task
        
        # Test with invalid task configuration
        invalid_task = {
            "name": "",  # Empty name
            "function": "nonexistent_function"
        }
        
        result = await create_background_task(task_configuration=invalid_task)
        
        assert result is not None
        assert "status" in result
        # Should handle error gracefully
        assert result["status"] in ["error", "success"]


class TestTaskScheduling:
    """Test task scheduling functionality."""

    @pytest.mark.asyncio
    async def test_cron_scheduling(self):
        """Test CRON-based task scheduling."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import schedule_recurring_task
        
        cron_task = {
            "name": "daily_cleanup",
            "function": "cleanup_expired_data",
            "parameters": {"retention_days": 30}
        }
        
        result = await schedule_recurring_task(
            task_configuration=cron_task,
            schedule_expression="0 3 * * *",  # Daily at 3 AM
            timezone="UTC"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_interval_scheduling(self):
        """Test interval-based task scheduling."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import schedule_recurring_task
        
        interval_task = {
            "name": "health_check",
            "function": "check_system_health",
            "parameters": {"components": ["cpu", "memory", "disk"]}
        }
        
        result = await schedule_recurring_task(
            task_configuration=interval_task,
            schedule_expression="every 5 minutes",
            enabled=True
        )
        
        assert result is not None
        assert "status" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
