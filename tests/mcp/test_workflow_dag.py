"""
Tests for MCP++ Workflow DAG Engine (Phase 4.2)

Tests dependency resolution, topological sorting, cycle detection, and parallel execution.
"""

import pytest
import asyncio
from typing import Dict, Any

from ipfs_datasets_py.mcp_server.mcplusplus.workflow_dag import (
    WorkflowStep,
    WorkflowDAG,
    WorkflowDAGExecutor,
    StepStatus
)


# Test fixtures

async def simple_executor(step: WorkflowStep) -> Dict[str, Any]:
    """Simple step executor for testing."""
    await asyncio.sleep(0.01)
    return {
        'step_id': step.step_id,
        'action': step.action,
        'inputs': step.inputs
    }


async def failing_executor(step: WorkflowStep) -> Dict[str, Any]:
    """Executor that fails for specific steps."""
    if 'fail' in step.step_id:
        raise ValueError(f"Step {step.step_id} configured to fail")
    await asyncio.sleep(0.01)
    return {'step_id': step.step_id}


# Tests

class TestWorkflowStep:
    """Test WorkflowStep dataclass."""
    
    def test_step_creation(self):
        """Test creating a workflow step."""
        step = WorkflowStep(
            step_id='test_step',
            action='test_action',
            inputs={'key': 'value'},
            depends_on=['dep1', 'dep2']
        )
        
        assert step.step_id == 'test_step'
        assert step.action == 'test_action'
        assert step.inputs == {'key': 'value'}
        assert step.depends_on == ['dep1', 'dep2']
        assert step.status == StepStatus.PENDING
    
    def test_mark_ready(self):
        """Test marking step as ready."""
        step = WorkflowStep(step_id='test', action='test')
        step.mark_ready()
        assert step.status == StepStatus.READY
    
    def test_mark_completed(self):
        """Test marking step as completed."""
        step = WorkflowStep(step_id='test', action='test')
        result = {'data': 'test'}
        
        step.mark_completed(result, 50.0)
        
        assert step.status == StepStatus.COMPLETED
        assert step.result == result
        assert step.execution_time_ms == 50.0
    
    def test_mark_failed(self):
        """Test marking step as failed."""
        step = WorkflowStep(step_id='test', action='test')
        
        step.mark_failed('Test error')
        
        assert step.status == StepStatus.FAILED
        assert step.error == 'Test error'


class TestWorkflowDAG:
    """Test WorkflowDAG class."""
    
    def test_add_step(self):
        """Test adding steps to the DAG."""
        dag = WorkflowDAG()
        
        step1 = WorkflowStep(step_id='step1', action='action1')
        step2 = WorkflowStep(
            step_id='step2',
            action='action2',
            depends_on=['step1']
        )
        
        dag.add_step(step1)
        dag.add_step(step2)
        
        assert 'step1' in dag.steps
        assert 'step2' in dag.steps
        assert 'step2' in dag.adjacency_list['step1']
        assert 'step1' in dag.reverse_adjacency_list['step2']
    
    def test_get_root_steps(self):
        """Test getting root steps (no dependencies)."""
        dag = WorkflowDAG()
        
        dag.add_step(WorkflowStep(step_id='root1', action='action'))
        dag.add_step(WorkflowStep(step_id='root2', action='action'))
        dag.add_step(WorkflowStep(step_id='dep', action='action', depends_on=['root1']))
        
        roots = dag.get_root_steps()
        
        assert set(roots) == {'root1', 'root2'}
    
    def test_get_ready_steps(self):
        """Test getting steps ready for execution."""
        dag = WorkflowDAG()
        
        step1 = WorkflowStep(step_id='step1', action='action')
        step2 = WorkflowStep(step_id='step2', action='action', depends_on=['step1'])
        step3 = WorkflowStep(step_id='step3', action='action', depends_on=['step2'])
        
        dag.add_step(step1)
        dag.add_step(step2)
        dag.add_step(step3)
        
        # Initially, only step1 is ready
        ready = dag.get_ready_steps()
        assert ready == ['step1']
        
        # Mark step1 as completed
        step1.mark_completed({}, 0)
        
        # Now step2 should be ready
        ready = dag.get_ready_steps()
        assert ready == ['step2']
    
    def test_detect_no_cycle(self):
        """Test cycle detection with no cycle."""
        dag = WorkflowDAG()
        
        dag.add_step(WorkflowStep(step_id='a', action='action'))
        dag.add_step(WorkflowStep(step_id='b', action='action', depends_on=['a']))
        dag.add_step(WorkflowStep(step_id='c', action='action', depends_on=['b']))
        
        cycle = dag.detect_cycles()
        assert cycle is None
    
    def test_detect_simple_cycle(self):
        """Test cycle detection with a simple cycle."""
        dag = WorkflowDAG()
        
        # Create a cycle: a -> b -> c -> a
        dag.add_step(WorkflowStep(step_id='a', action='action', depends_on=['c']))
        dag.add_step(WorkflowStep(step_id='b', action='action', depends_on=['a']))
        dag.add_step(WorkflowStep(step_id='c', action='action', depends_on=['b']))
        
        cycle = dag.detect_cycles()
        assert cycle is not None
        assert len(cycle) >= 3
    
    def test_detect_self_cycle(self):
        """Test cycle detection with self-reference."""
        dag = WorkflowDAG()
        
        dag.add_step(WorkflowStep(step_id='a', action='action', depends_on=['a']))
        
        cycle = dag.detect_cycles()
        assert cycle is not None
        assert 'a' in cycle
    
    def test_topological_sort_linear(self):
        """Test topological sort with linear dependency chain."""
        dag = WorkflowDAG()
        
        dag.add_step(WorkflowStep(step_id='a', action='action'))
        dag.add_step(WorkflowStep(step_id='b', action='action', depends_on=['a']))
        dag.add_step(WorkflowStep(step_id='c', action='action', depends_on=['b']))
        
        levels = dag.topological_sort()
        
        assert len(levels) == 3
        assert levels[0] == ['a']
        assert levels[1] == ['b']
        assert levels[2] == ['c']
    
    def test_topological_sort_parallel(self):
        """Test topological sort with parallel branches."""
        dag = WorkflowDAG()
        
        # Root
        dag.add_step(WorkflowStep(step_id='root', action='action'))
        
        # Parallel branches
        dag.add_step(WorkflowStep(step_id='branch1', action='action', depends_on=['root']))
        dag.add_step(WorkflowStep(step_id='branch2', action='action', depends_on=['root']))
        
        # Merge
        dag.add_step(WorkflowStep(
            step_id='merge',
            action='action',
            depends_on=['branch1', 'branch2']
        ))
        
        levels = dag.topological_sort()
        
        assert len(levels) == 3
        assert levels[0] == ['root']
        assert set(levels[1]) == {'branch1', 'branch2'}
        assert levels[2] == ['merge']
    
    def test_topological_sort_with_cycle_raises(self):
        """Test that topological sort raises on cycles."""
        dag = WorkflowDAG()
        
        dag.add_step(WorkflowStep(step_id='a', action='action', depends_on=['b']))
        dag.add_step(WorkflowStep(step_id='b', action='action', depends_on=['a']))
        
        with pytest.raises(ValueError, match="contains cycles"):
            dag.topological_sort()
    
    def test_validate_success(self):
        """Test validation of valid DAG."""
        dag = WorkflowDAG()
        
        dag.add_step(WorkflowStep(step_id='a', action='action'))
        dag.add_step(WorkflowStep(step_id='b', action='action', depends_on=['a']))
        
        is_valid, error = dag.validate()
        
        assert is_valid is True
        assert error is None
    
    def test_validate_missing_dependency(self):
        """Test validation catches missing dependencies."""
        dag = WorkflowDAG()
        
        dag.add_step(WorkflowStep(
            step_id='a',
            action='action',
            depends_on=['nonexistent']
        ))
        
        is_valid, error = dag.validate()
        
        assert is_valid is False
        assert 'non-existent' in error.lower()
    
    def test_validate_cycle(self):
        """Test validation catches cycles."""
        dag = WorkflowDAG()
        
        dag.add_step(WorkflowStep(step_id='a', action='action', depends_on=['b']))
        dag.add_step(WorkflowStep(step_id='b', action='action', depends_on=['a']))
        
        is_valid, error = dag.validate()
        
        assert is_valid is False
        assert 'cycle' in error.lower()


@pytest.mark.asyncio
class TestWorkflowDAGExecutor:
    """Test WorkflowDAGExecutor class."""
    
    async def test_execute_linear_workflow(self):
        """Test executing a linear workflow."""
        steps = [
            {'step_id': 'step1', 'action': 'action1'},
            {'step_id': 'step2', 'action': 'action2', 'depends_on': ['step1']},
            {'step_id': 'step3', 'action': 'action3', 'depends_on': ['step2']},
        ]
        
        executor = WorkflowDAGExecutor()
        result = await executor.execute_workflow(steps, simple_executor)
        
        assert result['success'] is True
        assert result['steps_completed'] == 3
        assert result['steps_failed'] == 0
        assert len(result['results']) == 3
    
    async def test_execute_parallel_workflow(self):
        """Test executing a workflow with parallel steps."""
        steps = [
            {'step_id': 'root', 'action': 'root'},
            {'step_id': 'branch1', 'action': 'branch1', 'depends_on': ['root']},
            {'step_id': 'branch2', 'action': 'branch2', 'depends_on': ['root']},
            {'step_id': 'merge', 'action': 'merge', 'depends_on': ['branch1', 'branch2']},
        ]
        
        import time
        start = time.perf_counter()
        
        executor = WorkflowDAGExecutor()
        result = await executor.execute_workflow(steps, simple_executor)
        
        elapsed = time.perf_counter() - start
        
        assert result['success'] is True
        assert result['steps_completed'] == 4
        
        # Should be faster than sequential (rough check)
        # Sequential would be 4 * 0.01 = 0.04s
        # Parallel should be about 3 * 0.01 = 0.03s (3 levels)
        assert elapsed < 0.05
    
    async def test_execute_invalid_workflow(self):
        """Test executing an invalid workflow (cycle)."""
        steps = [
            {'step_id': 'a', 'action': 'action', 'depends_on': ['b']},
            {'step_id': 'b', 'action': 'action', 'depends_on': ['a']},
        ]
        
        executor = WorkflowDAGExecutor()
        result = await executor.execute_workflow(steps, simple_executor)
        
        assert result['success'] is False
        assert 'cycle' in result['error'].lower()
    
    async def test_execute_with_missing_dependency(self):
        """Test executing workflow with missing dependency."""
        steps = [
            {'step_id': 'a', 'action': 'action', 'depends_on': ['nonexistent']},
        ]
        
        executor = WorkflowDAGExecutor()
        result = await executor.execute_workflow(steps, simple_executor)
        
        assert result['success'] is False
        assert 'non-existent' in result['error'].lower()
    
    async def test_execute_with_failure(self):
        """Test workflow execution with step failure."""
        steps = [
            {'step_id': 'step1', 'action': 'action'},
            {'step_id': 'fail_step', 'action': 'action', 'depends_on': ['step1']},
            {'step_id': 'step3', 'action': 'action', 'depends_on': ['fail_step']},
        ]
        
        executor = WorkflowDAGExecutor()
        result = await executor.execute_workflow(steps, failing_executor)
        
        assert result['success'] is False
        assert result['steps_completed'] == 1  # Only step1
        assert result['steps_failed'] == 1  # fail_step
        assert result['steps_skipped'] == 1  # step3 should be skipped
    
    async def test_on_step_complete_callback(self):
        """Test step completion callback."""
        completed_steps = []
        
        def on_complete(step_id, result):
            completed_steps.append(step_id)
        
        steps = [
            {'step_id': 'step1', 'action': 'action'},
            {'step_id': 'step2', 'action': 'action', 'depends_on': ['step1']},
        ]
        
        executor = WorkflowDAGExecutor(on_step_complete=on_complete)
        result = await executor.execute_workflow(steps, simple_executor)
        
        assert result['success'] is True
        assert len(completed_steps) == 2
        assert 'step1' in completed_steps
        assert 'step2' in completed_steps
    
    async def test_get_workflow_graph(self):
        """Test getting workflow graph representation."""
        steps = [
            {'step_id': 'a', 'action': 'action1'},
            {'step_id': 'b', 'action': 'action2', 'depends_on': ['a']},
        ]
        
        executor = WorkflowDAGExecutor()
        await executor.execute_workflow(steps, simple_executor)
        
        graph = executor.get_workflow_graph()
        
        assert 'nodes' in graph
        assert 'edges' in graph
        assert len(graph['nodes']) == 2
        assert len(graph['edges']) == 1
        
        # Check edge connects a -> b
        edge = graph['edges'][0]
        assert edge['from'] == 'a'
        assert edge['to'] == 'b'
    
    async def test_complex_dag(self):
        """Test complex DAG with multiple levels."""
        steps = [
            # Level 1: Roots
            {'step_id': 'fetch1', 'action': 'fetch'},
            {'step_id': 'fetch2', 'action': 'fetch'},
            {'step_id': 'fetch3', 'action': 'fetch'},
            
            # Level 2: Process
            {'step_id': 'process1', 'action': 'process', 'depends_on': ['fetch1']},
            {'step_id': 'process2', 'action': 'process', 'depends_on': ['fetch2']},
            {'step_id': 'process3', 'action': 'process', 'depends_on': ['fetch3']},
            
            # Level 3: Merge
            {'step_id': 'merge', 'action': 'merge', 
             'depends_on': ['process1', 'process2', 'process3']},
            
            # Level 4: Final
            {'step_id': 'store', 'action': 'store', 'depends_on': ['merge']},
        ]
        
        executor = WorkflowDAGExecutor()
        result = await executor.execute_workflow(steps, simple_executor)
        
        assert result['success'] is True
        assert result['steps_completed'] == 8
        assert result['steps_failed'] == 0
        
        # Verify all steps completed
        for step_id in ['fetch1', 'fetch2', 'fetch3', 'process1', 
                       'process2', 'process3', 'merge', 'store']:
            assert result['results'][step_id]['status'] == 'completed'


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
