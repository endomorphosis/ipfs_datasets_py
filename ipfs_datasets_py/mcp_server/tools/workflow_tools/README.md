# Workflow Tools

MCP tools for orchestrating multi-step pipelines and dataset processing workflows.
Business logic lives in `ipfs_datasets_py.workflow_automation`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `workflow_tools.py` | `execute_workflow()`, `batch_process_datasets()`, `schedule_workflow()`, `get_workflow_status()` | Core workflow execution, batch processing, scheduling, status polling |
| `enhanced_workflow_tools.py` | `create_pipeline()`, `run_pipeline()`, `list_pipelines()`, `pause_pipeline()`, `resume_pipeline()` | Enhanced pipeline management with pause/resume, step tracking |

## Usage

### Execute a workflow

```python
from ipfs_datasets_py.mcp_server.tools.workflow_tools import (
    execute_workflow, get_workflow_status
)

# Execute a named workflow
execution = await execute_workflow(
    workflow_name="ingest_and_embed",
    params={
        "source": "legal_corpus",
        "embedding_model": "all-MiniLM-L6-v2",
        "output_index": "legal_v3"
    },
    async_execution=True      # Return immediately, poll for status
)

# Poll status
status = await get_workflow_status(execution_id=execution["execution_id"])
# Returns: {"status": "running", "current_step": "embedding", "progress": 0.45}
```

### Batch process datasets

```python
from ipfs_datasets_py.mcp_server.tools.workflow_tools import batch_process_datasets

result = await batch_process_datasets(
    datasets=["legal_v1", "legal_v2", "patents_2024"],
    workflow="clean_and_embed",
    parallel_jobs=3,
    output_prefix="processed/"
)
```

### Enhanced pipeline management

```python
from ipfs_datasets_py.mcp_server.tools.workflow_tools import (
    create_pipeline, run_pipeline
)

# Define a pipeline
pipeline = await create_pipeline(
    name="full_legal_pipeline",
    steps=[
        {"name": "ingest", "tool": "load_dataset", "params": {"source": "courtlistener"}},
        {"name": "clean", "tool": "process_dataset", "params": {"ops": ["deduplicate"]}},
        {"name": "embed", "tool": "generate_embeddings", "params": {"model": "all-MiniLM-L6-v2"}},
        {"name": "index", "tool": "create_vector_index", "params": {"backend": "faiss"}},
    ]
)

# Run it
run = await run_pipeline(pipeline_name="full_legal_pipeline")
```

## Core Module

- `ipfs_datasets_py.workflow_automation` — workflow engine, step registry

## Status

| Tool | Status |
|------|--------|
| `workflow_tools` | ✅ Production ready |
| `enhanced_workflow_tools` | ✅ Production ready |
