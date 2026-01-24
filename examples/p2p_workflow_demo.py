#!/usr/bin/env python3
"""
P2P Workflow Scheduler Demonstration

This script demonstrates the peer-to-peer workflow scheduling system that
bypasses GitHub API using merkle clock consensus and fibonacci heap prioritization.
"""

import anyio
from ipfs_datasets_py.p2p_workflow_scheduler import (
    P2PWorkflowScheduler,
    WorkflowDefinition,
    WorkflowTag,
    MerkleClock
)


def demo_merkle_clock():
    """Demonstrate merkle clock functionality."""
    print("=" * 60)
    print("MERKLE CLOCK DEMONSTRATION")
    print("=" * 60)
    
    # Create clocks for two peers
    clock1 = MerkleClock(peer_id="peer1")
    clock2 = MerkleClock(peer_id="peer2")
    
    print(f"\nInitial clock states:")
    print(f"  Peer1: counter={clock1.counter}, hash={clock1.hash()[:16]}...")
    print(f"  Peer2: counter={clock2.counter}, hash={clock2.hash()[:16]}...")
    
    # Advance clocks independently
    clock1 = clock1.tick()
    clock1 = clock1.tick()
    clock2 = clock2.tick()
    
    print(f"\nAfter independent ticks:")
    print(f"  Peer1: counter={clock1.counter}")
    print(f"  Peer2: counter={clock2.counter}")
    
    # Merge clocks
    merged = clock1.merge(clock2)
    print(f"\nAfter merging:")
    print(f"  Merged counter: {merged.counter} (max of {clock1.counter} and {clock2.counter} + 1)")
    print(f"  Merged hash: {merged.hash()[:16]}...")


def demo_workflow_scheduling():
    """Demonstrate workflow scheduling with multiple peers."""
    print("\n" + "=" * 60)
    print("WORKFLOW SCHEDULING DEMONSTRATION")
    print("=" * 60)
    
    # Create scheduler with multiple peers
    peers = ["peer1", "peer2", "peer3"]
    scheduler = P2PWorkflowScheduler(peer_id="peer1", peers=peers)
    
    print(f"\nInitialized scheduler for {scheduler.peer_id}")
    print(f"Known peers: {list(scheduler.peers)}")
    
    # Create workflows with different tags and priorities
    workflows = [
        WorkflowDefinition(
            workflow_id="wf1",
            name="Web Scraping Task",
            tags=[WorkflowTag.P2P_ELIGIBLE, WorkflowTag.WEB_SCRAPE],
            priority=2.0
        ),
        WorkflowDefinition(
            workflow_id="wf2",
            name="Code Generation Task",
            tags=[WorkflowTag.P2P_ONLY, WorkflowTag.CODE_GEN],
            priority=1.0
        ),
        WorkflowDefinition(
            workflow_id="wf3",
            name="Data Processing Task",
            tags=[WorkflowTag.P2P_ELIGIBLE, WorkflowTag.DATA_PROCESSING],
            priority=3.0
        ),
        WorkflowDefinition(
            workflow_id="wf4",
            name="Unit Test (GitHub API)",
            tags=[WorkflowTag.UNIT_TEST],
            priority=1.0
        ),
    ]
    
    print("\nScheduling workflows:")
    for workflow in workflows:
        result = scheduler.schedule_workflow(workflow)
        
        if result['success']:
            print(f"  ✓ {workflow.workflow_id} ({workflow.name})")
            print(f"    - Tags: {[t.value for t in workflow.tags]}")
            print(f"    - Priority: {workflow.priority}")
            print(f"    - Assigned to: {result['assigned_peer']}")
            print(f"    - Is local: {result.get('is_local', False)}")
        else:
            print(f"  ✗ {workflow.workflow_id} ({workflow.name})")
            print(f"    - Reason: {result.get('reason', 'Unknown')}")
    
    # Show scheduler status
    status = scheduler.get_status()
    print(f"\nScheduler Status:")
    print(f"  Queue size: {status['queue_size']}")
    print(f"  Assigned workflows: {status['assigned_workflows']}")
    print(f"  Total workflows: {status['total_workflows']}")
    print(f"  Clock counter: {status['clock']['counter']}")
    
    # Process workflows in priority order
    print(f"\nProcessing workflows from queue (priority order):")
    while scheduler.get_queue_size() > 0:
        workflow = scheduler.get_next_workflow()
        if workflow:
            print(f"  → {workflow.workflow_id}: {workflow.name} (priority: {workflow.priority})")


def demo_peer_assignment():
    """Demonstrate how workflows are assigned to peers using hamming distance."""
    print("\n" + "=" * 60)
    print("PEER ASSIGNMENT ALGORITHM DEMONSTRATION")
    print("=" * 60)
    
    from ipfs_datasets_py.p2p_workflow_scheduler import calculate_hamming_distance
    import hashlib
    
    # Create scheduler with 5 peers
    peers = [f"peer{i}" for i in range(1, 6)]
    scheduler = P2PWorkflowScheduler(peer_id="peer1", peers=peers)
    
    print(f"\nNetwork has {len(scheduler.peers)} peers")
    
    # Create a single workflow and show assignment calculation
    workflow = WorkflowDefinition(
        workflow_id="demo_wf",
        name="Demo Workflow",
        tags=[WorkflowTag.P2P_ELIGIBLE],
        priority=1.0
    )
    
    print(f"\nScheduling workflow: {workflow.workflow_id}")
    
    # Show hamming distances for each peer
    print("\nHamming distances (lower = closer match):")
    
    # Generate task hash (similar to what scheduler does internally)
    task_content = f"{workflow.workflow_id}:{workflow.name}:{workflow.created_at}"
    task_hash = hashlib.sha256(task_content.encode()).hexdigest()
    clock_hash = scheduler.clock.hash()
    combined_hash = hashlib.sha256(f"{clock_hash}:{task_hash}".encode()).hexdigest()
    
    for peer_id in sorted(scheduler.peers):
        peer_hash = hashlib.sha256(peer_id.encode()).hexdigest()
        distance = calculate_hamming_distance(combined_hash, peer_hash)
        print(f"  {peer_id}: {distance} bits")
    
    # Schedule the workflow
    result = scheduler.schedule_workflow(workflow)
    print(f"\n✓ Workflow assigned to: {result['assigned_peer']}")
    print(f"  (Peer with minimum hamming distance wins)")


async def demo_mcp_tools():
    """Demonstrate MCP server tools (async)."""
    print("\n" + "=" * 60)
    print("MCP TOOLS DEMONSTRATION")
    print("=" * 60)
    
    try:
        # Import directly to avoid mcp_server dependencies
        import importlib.util
        from pathlib import Path
        
        tools_path = Path(__file__).parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "p2p_workflow_tools" / "p2p_workflow_tools.py"
        spec = importlib.util.spec_from_file_location("p2p_workflow_tools", tools_path)
        p2p_tools_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(p2p_tools_module)
        
        p2p_workflow_tools = p2p_tools_module
    except Exception as e:
        print(f"\n⚠ MCP tools not available: {e}")
        print("  (This is optional - core functionality works without MCP server)")
        return
    
    # Initialize scheduler
    print("\n1. Initializing P2P scheduler...")
    result = await p2p_workflow_tools.initialize_p2p_scheduler(
        peer_id="mcp_peer",
        peers=["peer1", "peer2"]
    )
    print(f"   Status: {'✓' if result['success'] else '✗'}")
    if result['success']:
        status = result['status']
        print(f"   Peer ID: {status['peer_id']}")
        print(f"   Known peers: {status['num_peers']}")
    
    # Get available tags
    print("\n2. Getting workflow tags...")
    result = await p2p_workflow_tools.get_workflow_tags()
    if result['success']:
        print(f"   Available tags: {len(result['tags'])}")
        for tag in result['tags'][:3]:
            desc = result['descriptions'].get(tag, '')
            print(f"     - {tag}: {desc}")
    
    # Schedule a workflow
    print("\n3. Scheduling a workflow...")
    result = await p2p_workflow_tools.schedule_p2p_workflow(
        workflow_id="mcp_wf1",
        name="MCP Test Workflow",
        tags=["p2p_eligible", "code_gen"],
        priority=1.5
    )
    print(f"   Status: {'✓' if result['success'] else '✗'}")
    if result['success']:
        wf_result = result['result']
        print(f"   Assigned to: {wf_result['assigned_peer']}")
        print(f"   Is local: {wf_result.get('is_local', False)}")
    
    # Get scheduler status
    print("\n4. Getting scheduler status...")
    result = await p2p_workflow_tools.get_p2p_scheduler_status()
    if result['success']:
        status = result['status']
        print(f"   Queue size: {status['queue_size']}")
        print(f"   Total workflows: {status['total_workflows']}")


def main():
    """Run all demonstrations."""
    print("\n" + "=" * 60)
    print("P2P WORKFLOW SCHEDULER DEMONSTRATION")
    print("=" * 60)
    print("\nThis demonstrates the peer-to-peer workflow scheduling system")
    print("that bypasses GitHub API for non-critical workflows using:")
    print("  • Merkle clock for distributed consensus")
    print("  • Fibonacci heap for priority scheduling")
    print("  • Hamming distance for peer assignment")
    
    # Run demonstrations
    demo_merkle_clock()
    demo_workflow_scheduling()
    demo_peer_assignment()
    
    # Run async MCP tools demo
    print("\n" + "=" * 60)
    print("Running MCP Tools demonstration...")
    anyio.run(demo_mcp_tools())
    
    print("\n" + "=" * 60)
    print("DEMONSTRATION COMPLETE")
    print("=" * 60)
    print("\nFor more information:")
    print("  • CLI: ipfs-datasets p2p --help")
    print("  • Python: from ipfs_datasets_py.p2p_workflow_scheduler import *")
    print("  • MCP: Use MCP server tools in p2p_workflow_tools category")


if __name__ == "__main__":
    main()
