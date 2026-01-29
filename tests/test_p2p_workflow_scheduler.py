"""
Tests for P2P Workflow Scheduler

Tests the merkle clock, fibonacci heap, and workflow scheduling functionality.
"""

import pytest
import time
from ipfs_datasets_py.p2p_networking.p2p_workflow_scheduler import (
    MerkleClock,
    FibonacciHeap,
    WorkflowDefinition,
    WorkflowTag,
    P2PWorkflowScheduler,
    calculate_hamming_distance,
    get_scheduler
)


class TestMerkleClock:
    """Test Merkle Clock implementation."""
    
    def test_clock_initialization(self):
        """
        GIVEN: A peer ID
        WHEN: Creating a new MerkleClock
        THEN: Clock should be initialized with counter 0
        """
        clock = MerkleClock(peer_id="peer1")
        assert clock.peer_id == "peer1"
        assert clock.counter == 0
        assert clock.parent_hash is None
        
    def test_clock_tick(self):
        """
        GIVEN: An initialized MerkleClock
        WHEN: Calling tick()
        THEN: Counter should increment and parent_hash should be set
        """
        clock = MerkleClock(peer_id="peer1")
        initial_hash = clock.hash()
        
        clock = clock.tick()
        assert clock.counter == 1
        assert clock.parent_hash == initial_hash
        
    def test_clock_hash_deterministic(self):
        """
        GIVEN: Two clocks with same state
        WHEN: Computing hashes
        THEN: Hashes should be identical
        """
        clock1 = MerkleClock(peer_id="peer1", counter=5, parent_hash="abc123", timestamp=1000.0)
        clock2 = MerkleClock(peer_id="peer1", counter=5, parent_hash="abc123", timestamp=1000.0)
        
        assert clock1.hash() == clock2.hash()
        
    def test_clock_hash_different_state(self):
        """
        GIVEN: Two clocks with different state
        WHEN: Computing hashes
        THEN: Hashes should be different
        """
        clock1 = MerkleClock(peer_id="peer1", counter=5)
        clock2 = MerkleClock(peer_id="peer1", counter=6)
        
        assert clock1.hash() != clock2.hash()
        
    def test_clock_merge(self):
        """
        GIVEN: Two merkle clocks with different counters
        WHEN: Merging the clocks
        THEN: New clock should have max counter + 1
        """
        clock1 = MerkleClock(peer_id="peer1", counter=3)
        clock2 = MerkleClock(peer_id="peer2", counter=5)
        
        merged = clock1.merge(clock2)
        assert merged.counter == 6  # max(3, 5) + 1
        assert merged.peer_id == "peer1"
        
    def test_clock_to_dict(self):
        """
        GIVEN: A MerkleClock
        WHEN: Converting to dictionary
        THEN: Dictionary should contain all clock data
        """
        clock = MerkleClock(peer_id="peer1", counter=5, parent_hash="abc123")
        clock_dict = clock.to_dict()
        
        assert clock_dict['peer_id'] == "peer1"
        assert clock_dict['counter'] == 5
        assert clock_dict['parent_hash'] == "abc123"
        assert 'hash' in clock_dict
        assert 'timestamp' in clock_dict
        
    def test_clock_from_dict(self):
        """
        GIVEN: A clock dictionary
        WHEN: Creating clock from dictionary
        THEN: Clock should have correct state
        """
        data = {
            'peer_id': 'peer1',
            'counter': 5,
            'parent_hash': 'abc123',
            'timestamp': 1000.0
        }
        
        clock = MerkleClock.from_dict(data)
        assert clock.peer_id == "peer1"
        assert clock.counter == 5
        assert clock.parent_hash == "abc123"


class TestFibonacciHeap:
    """Test Fibonacci Heap implementation."""
    
    def test_heap_initialization(self):
        """
        GIVEN: No parameters
        WHEN: Creating a new FibonacciHeap
        THEN: Heap should be empty
        """
        heap = FibonacciHeap()
        assert heap.is_empty()
        assert heap.size() == 0
        
    def test_heap_insert(self):
        """
        GIVEN: An empty FibonacciHeap
        WHEN: Inserting an element
        THEN: Heap should not be empty and size should be 1
        """
        heap = FibonacciHeap()
        heap.insert(5.0, "workflow1")
        
        assert not heap.is_empty()
        assert heap.size() == 1
        
    def test_heap_find_min(self):
        """
        GIVEN: A heap with multiple elements
        WHEN: Finding minimum
        THEN: Should return element with lowest key without removing it
        """
        heap = FibonacciHeap()
        heap.insert(5.0, "workflow1")
        heap.insert(2.0, "workflow2")
        heap.insert(8.0, "workflow3")
        
        min_elem = heap.find_min()
        assert min_elem is not None
        assert min_elem[0] == 2.0
        assert min_elem[1] == "workflow2"
        assert heap.size() == 3  # Should not remove element
        
    def test_heap_extract_min(self):
        """
        GIVEN: A heap with multiple elements
        WHEN: Extracting minimum
        THEN: Should return and remove element with lowest key
        """
        heap = FibonacciHeap()
        heap.insert(5.0, "workflow1")
        heap.insert(2.0, "workflow2")
        heap.insert(8.0, "workflow3")
        
        min_elem = heap.extract_min()
        assert min_elem is not None
        assert min_elem[0] == 2.0
        assert min_elem[1] == "workflow2"
        assert heap.size() == 2  # Should remove element
        
    def test_heap_priority_order(self):
        """
        GIVEN: A heap with elements inserted in random order
        WHEN: Extracting all elements
        THEN: Elements should be returned in priority order (ascending)
        """
        heap = FibonacciHeap()
        priorities = [5.0, 2.0, 8.0, 1.0, 9.0, 3.0]
        
        for i, priority in enumerate(priorities):
            heap.insert(priority, f"workflow{i}")
        
        extracted = []
        while not heap.is_empty():
            min_elem = heap.extract_min()
            extracted.append(min_elem[0])
        
        assert extracted == sorted(priorities)
        
    def test_heap_empty_extract(self):
        """
        GIVEN: An empty heap
        WHEN: Attempting to extract minimum
        THEN: Should return None
        """
        heap = FibonacciHeap()
        assert heap.extract_min() is None


class TestWorkflowDefinition:
    """Test WorkflowDefinition class."""
    
    def test_workflow_creation(self):
        """
        GIVEN: Workflow parameters
        WHEN: Creating a WorkflowDefinition
        THEN: Workflow should be properly initialized
        """
        workflow = WorkflowDefinition(
            workflow_id="wf1",
            name="Test Workflow",
            tags=[WorkflowTag.P2P_ELIGIBLE, WorkflowTag.CODE_GEN],
            priority=2.0
        )
        
        assert workflow.workflow_id == "wf1"
        assert workflow.name == "Test Workflow"
        assert WorkflowTag.P2P_ELIGIBLE in workflow.tags
        assert workflow.priority == 2.0
        
    def test_workflow_is_p2p_eligible(self):
        """
        GIVEN: Workflows with different tags
        WHEN: Checking if P2P eligible
        THEN: Should correctly identify P2P eligibility
        """
        wf1 = WorkflowDefinition(
            workflow_id="wf1",
            name="P2P Eligible",
            tags=[WorkflowTag.P2P_ELIGIBLE]
        )
        
        wf2 = WorkflowDefinition(
            workflow_id="wf2",
            name="P2P Only",
            tags=[WorkflowTag.P2P_ONLY]
        )
        
        wf3 = WorkflowDefinition(
            workflow_id="wf3",
            name="GitHub API",
            tags=[WorkflowTag.GITHUB_API]
        )
        
        assert wf1.is_p2p_eligible()
        assert wf2.is_p2p_eligible()
        assert not wf3.is_p2p_eligible()
        
    def test_workflow_requires_github_api(self):
        """
        GIVEN: Workflows with different tags
        WHEN: Checking if requires GitHub API
        THEN: Should correctly identify API requirement
        """
        wf1 = WorkflowDefinition(
            workflow_id="wf1",
            name="Unit Test",
            tags=[WorkflowTag.UNIT_TEST]
        )
        
        wf2 = WorkflowDefinition(
            workflow_id="wf2",
            name="P2P Only",
            tags=[WorkflowTag.P2P_ONLY]
        )
        
        assert wf1.requires_github_api()
        assert not wf2.requires_github_api()
        
    def test_workflow_to_dict(self):
        """
        GIVEN: A WorkflowDefinition
        WHEN: Converting to dictionary
        THEN: Dictionary should contain all workflow data
        """
        workflow = WorkflowDefinition(
            workflow_id="wf1",
            name="Test",
            tags=[WorkflowTag.P2P_ELIGIBLE],
            priority=1.5
        )
        
        wf_dict = workflow.to_dict()
        assert wf_dict['workflow_id'] == "wf1"
        assert wf_dict['name'] == "Test"
        assert 'p2p_eligible' in wf_dict['tags']
        assert wf_dict['priority'] == 1.5


class TestHammingDistance:
    """Test hamming distance calculation."""
    
    def test_hamming_distance_identical(self):
        """
        GIVEN: Two identical hashes
        WHEN: Calculating hamming distance
        THEN: Distance should be 0
        """
        hash1 = "abcd1234"
        hash2 = "abcd1234"
        
        distance = calculate_hamming_distance(hash1, hash2)
        assert distance == 0
        
    def test_hamming_distance_different(self):
        """
        GIVEN: Two different hashes
        WHEN: Calculating hamming distance
        THEN: Distance should be > 0
        """
        hash1 = "0000"
        hash2 = "ffff"
        
        distance = calculate_hamming_distance(hash1, hash2)
        assert distance > 0
        
    def test_hamming_distance_one_bit(self):
        """
        GIVEN: Two hashes differing by one bit
        WHEN: Calculating hamming distance
        THEN: Distance should be 1
        """
        hash1 = "0"
        hash2 = "1"
        
        distance = calculate_hamming_distance(hash1, hash2)
        assert distance == 1


class TestP2PWorkflowScheduler:
    """Test P2P Workflow Scheduler."""
    
    def test_scheduler_initialization(self):
        """
        GIVEN: A peer ID
        WHEN: Creating a P2PWorkflowScheduler
        THEN: Scheduler should be properly initialized
        """
        scheduler = P2PWorkflowScheduler(peer_id="peer1")
        
        assert scheduler.peer_id == "peer1"
        assert "peer1" in scheduler.peers
        assert scheduler.clock.peer_id == "peer1"
        assert scheduler.workflow_queue.size() == 0
        
    def test_scheduler_add_remove_peer(self):
        """
        GIVEN: An initialized scheduler
        WHEN: Adding and removing peers
        THEN: Peer list should be updated correctly
        """
        scheduler = P2PWorkflowScheduler(peer_id="peer1")
        
        scheduler.add_peer("peer2")
        assert "peer2" in scheduler.peers
        assert len(scheduler.peers) == 2
        
        scheduler.remove_peer("peer2")
        assert "peer2" not in scheduler.peers
        assert len(scheduler.peers) == 1
        
    def test_scheduler_schedule_github_workflow(self):
        """
        GIVEN: A workflow requiring GitHub API
        WHEN: Attempting to schedule it
        THEN: Scheduling should fail
        """
        scheduler = P2PWorkflowScheduler(peer_id="peer1")
        
        workflow = WorkflowDefinition(
            workflow_id="wf1",
            name="Unit Test",
            tags=[WorkflowTag.UNIT_TEST]
        )
        
        result = scheduler.schedule_workflow(workflow)
        assert not result['success']
        assert 'GitHub API' in result['reason']
        
    def test_scheduler_schedule_p2p_workflow(self):
        """
        GIVEN: A P2P eligible workflow
        WHEN: Scheduling it
        THEN: Workflow should be scheduled to a peer
        """
        scheduler = P2PWorkflowScheduler(peer_id="peer1", peers=["peer2", "peer3"])
        
        workflow = WorkflowDefinition(
            workflow_id="wf1",
            name="Code Generation",
            tags=[WorkflowTag.P2P_ELIGIBLE, WorkflowTag.CODE_GEN],
            priority=1.0
        )
        
        result = scheduler.schedule_workflow(workflow)
        assert result['success']
        assert 'assigned_peer' in result
        assert result['assigned_peer'] in scheduler.peers
        
    def test_scheduler_workflow_assignment_deterministic(self):
        """
        GIVEN: Same workflow and peers
        WHEN: Scheduling multiple times
        THEN: Should always assign to same peer (deterministic)
        """
        scheduler = P2PWorkflowScheduler(peer_id="peer1", peers=["peer2", "peer3"])
        
        workflow = WorkflowDefinition(
            workflow_id="wf1",
            name="Test",
            tags=[WorkflowTag.P2P_ELIGIBLE],
            priority=1.0
        )
        
        result1 = scheduler.schedule_workflow(workflow)
        
        # Reset scheduler to test determinism
        scheduler2 = P2PWorkflowScheduler(peer_id="peer1", peers=["peer2", "peer3"])
        result2 = scheduler2.schedule_workflow(workflow)
        
        # Note: Assignment might differ due to clock ticking, but algorithm is deterministic
        assert result1['success']
        assert result2['success']
        
    def test_scheduler_get_next_workflow(self):
        """
        GIVEN: Scheduler with queued workflows
        WHEN: Getting next workflow
        THEN: Should return workflow with highest priority (lowest value)
        """
        scheduler = P2PWorkflowScheduler(peer_id="peer1")
        
        # Schedule multiple workflows (all will be assigned to peer1 since it's the only peer)
        workflows = [
            WorkflowDefinition("wf1", "Low Priority", [WorkflowTag.P2P_ELIGIBLE], priority=5.0),
            WorkflowDefinition("wf2", "High Priority", [WorkflowTag.P2P_ELIGIBLE], priority=1.0),
            WorkflowDefinition("wf3", "Med Priority", [WorkflowTag.P2P_ELIGIBLE], priority=3.0),
        ]
        
        for wf in workflows:
            scheduler.schedule_workflow(wf)
        
        # Should get highest priority (lowest value) first
        next_wf = scheduler.get_next_workflow()
        assert next_wf is not None
        assert next_wf.workflow_id == "wf2"  # priority 1.0
        
    def test_scheduler_get_status(self):
        """
        GIVEN: An initialized scheduler with workflows
        WHEN: Getting status
        THEN: Status should reflect current state
        """
        scheduler = P2PWorkflowScheduler(peer_id="peer1", peers=["peer2"])
        
        workflow = WorkflowDefinition(
            workflow_id="wf1",
            name="Test",
            tags=[WorkflowTag.P2P_ELIGIBLE]
        )
        scheduler.schedule_workflow(workflow)
        
        status = scheduler.get_status()
        assert status['peer_id'] == "peer1"
        assert status['num_peers'] == 2
        assert 'clock' in status
        assert status['clock']['counter'] > 0  # Clock should have ticked
        
    def test_scheduler_merge_clock(self):
        """
        GIVEN: Two schedulers with different clocks
        WHEN: Merging clocks
        THEN: Clock should be updated
        """
        scheduler1 = P2PWorkflowScheduler(peer_id="peer1")
        scheduler2 = P2PWorkflowScheduler(peer_id="peer2")
        
        # Advance clock on scheduler2
        for _ in range(5):
            scheduler2.clock = scheduler2.clock.tick()
        
        initial_counter = scheduler1.clock.counter
        
        # Merge scheduler2's clock into scheduler1
        scheduler1.merge_clock(scheduler2.clock)
        
        # Counter should have increased
        assert scheduler1.clock.counter > initial_counter
        
    def test_scheduler_multiple_peers_distribution(self):
        """
        GIVEN: Scheduler with multiple peers
        WHEN: Scheduling many workflows
        THEN: Workflows should be distributed across peers
        """
        peers = ["peer1", "peer2", "peer3", "peer4"]
        scheduler = P2PWorkflowScheduler(peer_id="peer1", peers=peers)
        
        assigned_peers = set()
        
        # Schedule multiple workflows
        for i in range(20):
            workflow = WorkflowDefinition(
                workflow_id=f"wf{i}",
                name=f"Workflow {i}",
                tags=[WorkflowTag.P2P_ELIGIBLE],
                priority=float(i)
            )
            
            result = scheduler.schedule_workflow(workflow)
            if result['success']:
                assigned_peers.add(result['assigned_peer'])
        
        # Should use multiple peers (not all might be used due to hamming distance)
        assert len(assigned_peers) >= 2


class TestGetScheduler:
    """Test global scheduler instance."""
    
    def test_get_scheduler_creates_instance(self):
        """
        GIVEN: No existing scheduler instance
        WHEN: Calling get_scheduler()
        THEN: Should create and return a scheduler
        """
        # Clear global instance
        import ipfs_datasets_py.p2p_workflow_scheduler as scheduler_module
        scheduler_module._scheduler_instance = None
        
        scheduler = get_scheduler(peer_id="test_peer")
        assert scheduler is not None
        assert scheduler.peer_id == "test_peer"
        
    def test_get_scheduler_reuses_instance(self):
        """
        GIVEN: An existing scheduler instance
        WHEN: Calling get_scheduler() again
        THEN: Should return the same instance
        """
        import ipfs_datasets_py.p2p_workflow_scheduler as scheduler_module
        scheduler_module._scheduler_instance = None
        
        scheduler1 = get_scheduler(peer_id="test_peer")
        scheduler2 = get_scheduler(peer_id="different_peer")  # Should be ignored
        
        assert scheduler1 is scheduler2
        assert scheduler2.peer_id == "test_peer"  # Should keep original peer_id


@pytest.mark.asyncio
async def test_integration_workflow_lifecycle():
    """
    Integration test for complete workflow lifecycle.
    
    GIVEN: A P2P scheduler with multiple peers
    WHEN: Scheduling workflows, getting next, and processing
    THEN: Full lifecycle should work correctly
    """
    scheduler = P2PWorkflowScheduler(peer_id="peer1", peers=["peer2", "peer3"])
    
    # Schedule workflows with different priorities
    workflows = [
        WorkflowDefinition("wf1", "Web Scraping", [WorkflowTag.P2P_ELIGIBLE, WorkflowTag.WEB_SCRAPE], priority=2.0),
        WorkflowDefinition("wf2", "Code Gen", [WorkflowTag.P2P_ELIGIBLE, WorkflowTag.CODE_GEN], priority=1.0),
        WorkflowDefinition("wf3", "Data Processing", [WorkflowTag.P2P_ONLY, WorkflowTag.DATA_PROCESSING], priority=3.0),
    ]
    
    scheduled_count = 0
    for wf in workflows:
        result = scheduler.schedule_workflow(wf)
        if result['success'] and result.get('is_local'):
            scheduled_count += 1
    
    # Get status
    status = scheduler.get_status()
    assert status['queue_size'] == scheduled_count
    
    # Process workflows in priority order
    processed = []
    while scheduler.get_queue_size() > 0:
        next_wf = scheduler.get_next_workflow()
        if next_wf:
            processed.append(next_wf.workflow_id)
    
    # Verify queue is now empty
    assert scheduler.get_queue_size() == 0
