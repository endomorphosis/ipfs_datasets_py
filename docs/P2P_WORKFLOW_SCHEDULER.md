# P2P Workflow Scheduler

## Overview

The P2P Workflow Scheduler is a peer-to-peer system for distributing and executing GitHub Actions workflows without relying on the GitHub API. This system is designed to handle non-critical workflows like code generation, web scraping, and data processing tasks that don't need GitHub's infrastructure.

## Key Features

### 1. Merkle Clock Consensus
- **Distributed Timestamp**: Uses content-addressable hashing to create a causal ordering of events
- **Conflict Resolution**: Automatically merges concurrent operations from different peers
- **No Central Authority**: Each peer maintains its own clock and synchronizes with others

### 2. Fibonacci Heap Priority Queue
- **Efficient Operations**: O(1) insertion and O(log n) extraction
- **Priority-Based Scheduling**: Lower priority values execute first
- **Dynamic Reordering**: Priorities can be adjusted without full heap reconstruction

### 3. Hamming Distance Peer Assignment
- **Deterministic Assignment**: Uses hamming distance between hashes to determine workflow ownership
- **Load Distribution**: Workflows are distributed across peers based on:
  - `hash(merkle_clock_head) + hash(task)` vs `hash(peer_id)`
- **Automatic Failover**: If a peer fails, workflows are automatically reassigned

### 4. Workflow Tagging System
Workflows can be tagged to control execution mode:

| Tag | Description |
|-----|-------------|
| `github_api` | Use GitHub API (default for unit tests) |
| `p2p_eligible` | Can be executed via P2P or GitHub API |
| `p2p_only` | Must be executed via P2P (bypass GitHub completely) |
| `unit_test` | Unit test workflow (requires GitHub API) |
| `code_gen` | Code generation workflow (P2P eligible) |
| `web_scrape` | Web scraping workflow (P2P eligible) |
| `data_processing` | Data processing workflow (P2P eligible) |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    P2P Workflow Network                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Peer 1 (peer_id)          Peer 2                Peer 3      │
│  ┌──────────────┐         ┌──────────────┐     ┌──────────┐ │
│  │ Merkle Clock │◄────────┤ Merkle Clock │◄────┤ Merkle   │ │
│  │  counter: 5  │  sync   │  counter: 4  │sync │ Clock    │ │
│  │  hash: abc...│         │  hash: def...│     │ counter:3│ │
│  └──────────────┘         └──────────────┘     └──────────┘ │
│         │                         │                    │     │
│         ▼                         ▼                    ▼     │
│  ┌──────────────┐         ┌──────────────┐     ┌──────────┐ │
│  │ Fibonacci    │         │ Fibonacci    │     │Fibonacci │ │
│  │ Heap Queue   │         │ Heap Queue   │     │Heap Queue│ │
│  │ [wf1,wf3,wf5]│         │ [wf2,wf4]    │     │ [wf6]    │ │
│  └──────────────┘         └──────────────┘     └──────────┘ │
│         │                         │                    │     │
│         └─────────────────────────┴────────────────────┘     │
│                     Hamming Distance Assignment              │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Usage

### Python API

```python
from ipfs_datasets_py.p2p_workflow_scheduler import (
    P2PWorkflowScheduler,
    WorkflowDefinition,
    WorkflowTag,
    get_scheduler
)

# Initialize scheduler
scheduler = P2PWorkflowScheduler(
    peer_id="my-peer",
    peers=["peer2", "peer3"]
)

# Create a workflow
workflow = WorkflowDefinition(
    workflow_id="wf1",
    name="Web Scraping Task",
    tags=[WorkflowTag.P2P_ELIGIBLE, WorkflowTag.WEB_SCRAPE],
    priority=2.0
)

# Schedule the workflow
result = scheduler.schedule_workflow(workflow)
print(f"Assigned to: {result['assigned_peer']}")

# Get next workflow from queue (if assigned to this peer)
if result['is_local']:
    next_wf = scheduler.get_next_workflow()
    print(f"Processing: {next_wf.workflow_id}")
```

### CLI Commands

```bash
# Initialize P2P scheduler
ipfs-datasets p2p init --peer-id my-peer --peers peer2,peer3

# Schedule a workflow
ipfs-datasets p2p schedule \
  --id wf1 \
  --name "Code Generation" \
  --tags "p2p_eligible,code_gen" \
  --priority 1.0

# Get next workflow from queue
ipfs-datasets p2p next

# Check scheduler status
ipfs-datasets p2p status

# Add/remove peers
ipfs-datasets p2p add-peer peer4
ipfs-datasets p2p remove-peer peer2

# List available workflow tags
ipfs-datasets p2p tags

# Get workflows assigned to this peer
ipfs-datasets p2p assigned
```

### MCP Server Tools

The P2P workflow scheduler is exposed through MCP server tools:

```python
# Using MCP tools (async)
from ipfs_datasets_py.mcp_server.tools.p2p_workflow_tools import (
    initialize_p2p_scheduler,
    schedule_p2p_workflow,
    get_next_p2p_workflow,
    get_p2p_scheduler_status
)

# Initialize
result = await initialize_p2p_scheduler(peer_id="my-peer")

# Schedule
result = await schedule_p2p_workflow(
    workflow_id="wf1",
    name="Test",
    tags=["p2p_eligible"],
    priority=1.0
)

# Get status
result = await get_p2p_scheduler_status()
```

## Workflow Lifecycle

1. **Creation**: Workflow is defined with ID, name, tags, and priority
2. **Scheduling**: Scheduler calculates which peer should handle it using:
   - Merkle clock provides consistent ordering
   - Task hash combined with clock hash
   - Hamming distance to each peer's ID
   - Peer with minimum distance wins
3. **Queue**: If assigned to this peer, added to fibonacci heap priority queue
4. **Execution**: Workflows extracted from queue in priority order (lower value = higher priority)
5. **Synchronization**: Clock updates shared with other peers via P2P

## Performance Characteristics

- **Scheduling**: O(log n) where n is number of peers
- **Queue Insertion**: O(1) amortized
- **Queue Extraction**: O(log m) where m is queue size
- **Clock Merge**: O(1)
- **Hamming Distance**: O(k) where k is hash length (constant)

## Integration with Existing P2P Infrastructure

The P2P Workflow Scheduler integrates with existing components:

- **P2PPeerRegistry** (`p2p_peer_registry.py`): Peer discovery via GitHub Actions cache
- **UniversalConnectivity** (`p2p_connectivity.py`): libp2p connectivity (mDNS, DHT, relay)
- **DistributedGitHubCache** (`distributed_cache.py`): Content-addressable cache sharing

## Example Workflows

### Code Generation Workflow

```python
workflow = WorkflowDefinition(
    workflow_id="codegen-001",
    name="Generate API Documentation",
    tags=[WorkflowTag.P2P_ONLY, WorkflowTag.CODE_GEN],
    priority=1.5,
    metadata={
        "source": "src/",
        "output": "docs/api/",
        "format": "markdown"
    }
)
```

### Web Scraping Workflow

```python
workflow = WorkflowDefinition(
    workflow_id="scrape-001",
    name="Legal Document Scraping",
    tags=[WorkflowTag.P2P_ELIGIBLE, WorkflowTag.WEB_SCRAPE],
    priority=2.0,
    metadata={
        "url": "https://example.com/legal",
        "selector": ".document",
        "output": "data/legal/"
    }
)
```

### Data Processing Workflow

```python
workflow = WorkflowDefinition(
    workflow_id="process-001",
    name="Dataset Transformation",
    tags=[WorkflowTag.P2P_ELIGIBLE, WorkflowTag.DATA_PROCESSING],
    priority=3.0,
    metadata={
        "input": "data/raw/",
        "output": "data/processed/",
        "format": "parquet"
    }
)
```

## Testing

Run the comprehensive test suite:

```bash
pytest tests/test_p2p_workflow_scheduler.py -v
```

Test coverage includes:
- Merkle clock operations (tick, merge, hash)
- Fibonacci heap (insert, extract, priority ordering)
- Workflow definitions and tags
- Hamming distance calculations
- Scheduler initialization and peer management
- Workflow assignment algorithm
- Integration tests

## Demo

Run the demonstration script:

```bash
cd examples
python p2p_workflow_demo.py
```

This demonstrates:
- Merkle clock consensus
- Workflow scheduling with multiple peers
- Peer assignment algorithm
- Priority-based execution
- MCP tools integration

## Configuration

### Environment Variables

- `P2P_PEER_ID`: Override automatic peer ID detection
- `P2P_BOOTSTRAP_PEERS`: Comma-separated list of initial peers

### GitHub Actions Integration

To use P2P scheduling in GitHub Actions workflows, add this tag:

```yaml
name: Code Generation Workflow
on: workflow_dispatch

jobs:
  generate:
    runs-on: self-hosted
    # Tag this workflow as P2P eligible
    env:
      WORKFLOW_TAG: p2p_eligible
      WORKFLOW_TYPE: code_gen
    steps:
      - name: Schedule via P2P
        run: |
          ipfs-datasets p2p schedule \
            --id ${{ github.run_id }} \
            --name "${{ github.workflow }}" \
            --tags "p2p_eligible,code_gen"
```

## Troubleshooting

### Peer Not Receiving Workflows

1. Check peer is registered: `ipfs-datasets p2p status`
2. Verify clock synchronization: Look for clock counter updates
3. Check network connectivity between peers

### Workflows Not Being Assigned

1. Ensure workflow has correct tags (must include `p2p_eligible` or `p2p_only`)
2. Check scheduler status: `ipfs-datasets p2p status`
3. Verify peers are known: `ipfs-datasets p2p status`

### Priority Queue Issues

1. Verify priority values (lower = higher priority)
2. Check queue size: `ipfs-datasets p2p status`
3. Extract workflows: `ipfs-datasets p2p next`

## Future Enhancements

- **Persistence**: Save scheduler state to disk for restart recovery
- **Metrics**: Add Prometheus metrics for monitoring
- **Load Balancing**: Dynamic reassignment based on peer load
- **Failure Detection**: Heartbeat mechanism with automatic failover
- **Web Dashboard**: Visual interface for monitoring workflows
- **IPLD Integration**: Store workflow definitions in IPLD format

## References

- [Merkle Clocks Paper](https://arxiv.org/abs/1905.13064)
- [Fibonacci Heaps](https://en.wikipedia.org/wiki/Fibonacci_heap)
- [Hamming Distance](https://en.wikipedia.org/wiki/Hamming_distance)
- [libp2p Specifications](https://github.com/libp2p/specs)
- [IPFS Accelerate PR #61](https://github.com/endomorphosis/ipfs_accelerate_py/pull/61)
