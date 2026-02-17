"""
MCP++ Workflow DAG Engine (Phase 4.2)

Implements DAG-based workflow execution with:
- Dependency resolution
- Topological sorting
- Circular dependency detection
- Parallel execution of independent steps

This enables complex workflow orchestration with proper dependency management.
"""

import logging
from typing import Dict, List, Set, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    """Status of a workflow step."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    """Represents a single step in a workflow."""
    
    step_id: str
    action: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    
    def mark_ready(self) -> None:
        """Mark step as ready for execution."""
        self.status = StepStatus.READY
    
    def mark_running(self) -> None:
        """Mark step as running."""
        self.status = StepStatus.RUNNING
    
    def mark_completed(self, result: Any, execution_time_ms: float) -> None:
        """Mark step as completed."""
        self.status = StepStatus.COMPLETED
        self.result = result
        self.execution_time_ms = execution_time_ms
    
    def mark_failed(self, error: str) -> None:
        """Mark step as failed."""
        self.status = StepStatus.FAILED
        self.error = error
    
    def mark_skipped(self, reason: str) -> None:
        """Mark step as skipped."""
        self.status = StepStatus.SKIPPED
        self.error = reason


@dataclass
class WorkflowDAG:
    """
    Directed Acyclic Graph representation of a workflow.
    
    Provides dependency resolution, topological sorting, and cycle detection.
    """
    
    steps: Dict[str, WorkflowStep] = field(default_factory=dict)
    adjacency_list: Dict[str, List[str]] = field(default_factory=dict)
    reverse_adjacency_list: Dict[str, List[str]] = field(default_factory=dict)
    
    def add_step(self, step: WorkflowStep) -> None:
        """Add a step to the DAG."""
        self.steps[step.step_id] = step
        
        # Initialize adjacency lists
        if step.step_id not in self.adjacency_list:
            self.adjacency_list[step.step_id] = []
        if step.step_id not in self.reverse_adjacency_list:
            self.reverse_adjacency_list[step.step_id] = []
        
        # Build adjacency lists from dependencies
        for dep in step.depends_on:
            if dep not in self.adjacency_list:
                self.adjacency_list[dep] = []
            self.adjacency_list[dep].append(step.step_id)
            
            if dep not in self.reverse_adjacency_list:
                self.reverse_adjacency_list[dep] = []
            self.reverse_adjacency_list[step.step_id].append(dep)
    
    def get_root_steps(self) -> List[str]:
        """Get steps with no dependencies (roots of the DAG)."""
        return [
            step_id for step_id, step in self.steps.items()
            if not step.depends_on
        ]
    
    def get_ready_steps(self) -> List[str]:
        """Get steps that are ready to execute (all dependencies completed)."""
        ready = []
        
        for step_id, step in self.steps.items():
            if step.status != StepStatus.PENDING:
                continue
            
            # Check if all dependencies are completed
            all_deps_completed = all(
                self.steps[dep].status == StepStatus.COMPLETED
                for dep in step.depends_on
                if dep in self.steps
            )
            
            if all_deps_completed:
                ready.append(step_id)
        
        return ready
    
    def detect_cycles(self) -> Optional[List[str]]:
        """
        Detect cycles in the DAG using DFS.
        
        Returns:
            List of step IDs in the cycle, or None if no cycle found
        """
        visited = set()
        rec_stack = set()
        
        def dfs(node: str, path: List[str]) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.adjacency_list.get(node, []):
                if neighbor not in visited:
                    cycle = dfs(neighbor, path.copy())
                    if cycle:
                        return cycle
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]
            
            rec_stack.remove(node)
            return None
        
        for step_id in self.steps:
            if step_id not in visited:
                cycle = dfs(step_id, [])
                if cycle:
                    return cycle
        
        return None
    
    def topological_sort(self) -> List[List[str]]:
        """
        Perform topological sort on the DAG.
        
        Returns:
            List of levels, where each level contains steps that can be executed in parallel
        """
        # Calculate in-degrees
        in_degree = {step_id: 0 for step_id in self.steps}
        for step_id, step in self.steps.items():
            in_degree[step_id] = len([dep for dep in step.depends_on if dep in self.steps])
        
        # Find initial nodes with in-degree 0
        levels = []
        current_level = [step_id for step_id, degree in in_degree.items() if degree == 0]
        
        while current_level:
            levels.append(current_level)
            next_level = []
            
            for step_id in current_level:
                # Reduce in-degree of neighbors
                for neighbor in self.adjacency_list.get(step_id, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_level.append(neighbor)
            
            current_level = next_level
        
        # Verify all steps were processed (no cycles)
        if len([step for level in levels for step in level]) != len(self.steps):
            raise ValueError("Workflow contains cycles - cannot perform topological sort")
        
        return levels
    
    def get_execution_order(self) -> List[List[str]]:
        """
        Get the execution order as a list of levels.
        
        Each level contains steps that can be executed in parallel.
        """
        return self.topological_sort()
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """
        Validate the workflow DAG.
        
        Returns:
            (is_valid, error_message)
        """
        # Check for missing dependencies
        for step_id, step in self.steps.items():
            for dep in step.depends_on:
                if dep not in self.steps:
                    return False, f"Step '{step_id}' depends on non-existent step '{dep}'"
        
        # Check for cycles
        cycle = self.detect_cycles()
        if cycle:
            cycle_str = ' -> '.join(cycle)
            return False, f"Workflow contains cycle: {cycle_str}"
        
        return True, None


class WorkflowDAGExecutor:
    """
    Executor for DAG-based workflows.
    
    Executes workflow steps in dependency order, with parallel execution of
    independent steps.
    """
    
    def __init__(
        self,
        max_concurrent: int = 10,
        on_step_complete: Optional[callable] = None
    ):
        """
        Initialize the executor.
        
        Args:
            max_concurrent: Maximum number of concurrent step executions
            on_step_complete: Optional callback(step_id, result) for step completion
        """
        self.max_concurrent = max_concurrent
        self.on_step_complete = on_step_complete
        self.dag: Optional[WorkflowDAG] = None
    
    async def execute_workflow(
        self,
        steps: List[Dict[str, Any]],
        step_executor: callable
    ) -> Dict[str, Any]:
        """
        Execute a workflow defined by a list of steps.
        
        Args:
            steps: List of step definitions (dicts with step_id, action, inputs, depends_on)
            step_executor: Async function(step) that executes a step and returns result
            
        Returns:
            Dict with workflow execution results
        """
        # Build DAG
        self.dag = WorkflowDAG()
        
        for step_dict in steps:
            step = WorkflowStep(
                step_id=step_dict['step_id'],
                action=step_dict['action'],
                inputs=step_dict.get('inputs', {}),
                depends_on=step_dict.get('depends_on', [])
            )
            self.dag.add_step(step)
        
        # Validate DAG
        is_valid, error_msg = self.dag.validate()
        if not is_valid:
            logger.error(f"Invalid workflow: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'steps_completed': 0,
                'steps_failed': 0
            }
        
        # Get execution order
        try:
            execution_levels = self.dag.get_execution_order()
        except ValueError as e:
            logger.error(f"Failed to determine execution order: {e}")
            return {
                'success': False,
                'error': str(e),
                'steps_completed': 0,
                'steps_failed': 0
            }
        
        logger.info(f"Executing workflow with {len(execution_levels)} levels")
        
        # Execute levels in order
        steps_completed = 0
        steps_failed = 0
        
        for level_idx, level in enumerate(execution_levels):
            logger.info(f"Executing level {level_idx + 1}/{len(execution_levels)}: {len(level)} steps")
            
            # Execute all steps in this level concurrently
            tasks = []
            for step_id in level:
                step = self.dag.steps[step_id]
                step.mark_running()
                tasks.append(self._execute_step(step, step_executor))
            
            # Wait for all steps in this level to complete
            level_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for step_id, result in zip(level, level_results):
                step = self.dag.steps[step_id]
                
                if isinstance(result, Exception):
                    step.mark_failed(str(result))
                    steps_failed += 1
                    logger.error(f"Step '{step_id}' failed: {result}")
                else:
                    step.mark_completed(result['result'], result['execution_time_ms'])
                    steps_completed += 1
                    logger.info(f"Step '{step_id}' completed successfully")
                    
                    if self.on_step_complete:
                        self.on_step_complete(step_id, result)
            
            # If any step in this level failed, we might want to skip dependent steps
            # For now, we continue execution but mark dependent steps as skipped if their deps failed
            if steps_failed > 0:
                self._mark_skipped_steps()
        
        return {
            'success': steps_failed == 0,
            'steps_completed': steps_completed,
            'steps_failed': steps_failed,
            'steps_skipped': len([s for s in self.dag.steps.values() if s.status == StepStatus.SKIPPED]),
            'total_steps': len(self.dag.steps),
            'results': {
                step_id: {
                    'status': step.status.value,
                    'result': step.result,
                    'error': step.error,
                    'execution_time_ms': step.execution_time_ms
                }
                for step_id, step in self.dag.steps.items()
            }
        }
    
    async def _execute_step(
        self,
        step: WorkflowStep,
        step_executor: callable
    ) -> Dict[str, Any]:
        """Execute a single step."""
        import time
        
        start_time = time.perf_counter()
        
        try:
            result = await step_executor(step)
            end_time = time.perf_counter()
            
            return {
                'success': True,
                'result': result,
                'execution_time_ms': (end_time - start_time) * 1000
            }
        except Exception as e:
            end_time = time.perf_counter()
            raise RuntimeError(f"Step execution failed: {e}")
    
    def _mark_skipped_steps(self) -> None:
        """Mark steps that depend on failed steps as skipped."""
        if not self.dag:
            return
        
        # Find all steps that depend on failed steps
        for step_id, step in self.dag.steps.items():
            if step.status == StepStatus.PENDING:
                # Check if any dependency failed
                failed_deps = [
                    dep for dep in step.depends_on
                    if self.dag.steps[dep].status == StepStatus.FAILED
                ]
                
                if failed_deps:
                    step.mark_skipped(f"Depends on failed step(s): {', '.join(failed_deps)}")
    
    def get_workflow_graph(self) -> Dict[str, Any]:
        """
        Get a visualization-ready representation of the workflow graph.
        
        Returns:
            Dict with nodes and edges for graph visualization
        """
        if not self.dag:
            return {'nodes': [], 'edges': []}
        
        nodes = []
        for step_id, step in self.dag.steps.items():
            nodes.append({
                'id': step_id,
                'label': f"{step_id}\n{step.action}",
                'status': step.status.value
            })
        
        edges = []
        for step_id, step in self.dag.steps.items():
            for dep in step.depends_on:
                edges.append({
                    'from': dep,
                    'to': step_id
                })
        
        return {'nodes': nodes, 'edges': edges}


# Example usage
if __name__ == '__main__':
    import json
    
    async def example_step_executor(step: WorkflowStep) -> Any:
        """Example step executor for testing."""
        await asyncio.sleep(0.1)  # Simulate work
        return {'action': step.action, 'inputs': step.inputs}
    
    async def main():
        # Define a workflow with DAG structure
        steps = [
            # Layer 1: Root nodes
            {'step_id': 'fetch1', 'action': 'fetch_data', 'inputs': {'source': 'A'}},
            {'step_id': 'fetch2', 'action': 'fetch_data', 'inputs': {'source': 'B'}},
            
            # Layer 2: Process steps
            {'step_id': 'process1', 'action': 'transform', 'depends_on': ['fetch1']},
            {'step_id': 'process2', 'action': 'transform', 'depends_on': ['fetch2']},
            
            # Layer 3: Merge
            {'step_id': 'merge', 'action': 'merge_data', 'depends_on': ['process1', 'process2']},
            
            # Layer 4: Final
            {'step_id': 'store', 'action': 'store_result', 'depends_on': ['merge']}
        ]
        
        def on_complete(step_id, result):
            print(f"Step '{step_id}' completed in {result['execution_time_ms']:.2f}ms")
        
        executor = WorkflowDAGExecutor(on_step_complete=on_complete)
        result = await executor.execute_workflow(steps, example_step_executor)
        
        print("\nWorkflow execution result:")
        print(json.dumps(result, indent=2))
        
        print("\nWorkflow graph:")
        graph = executor.get_workflow_graph()
        print(json.dumps(graph, indent=2))
    
    asyncio.run(main())
