# TODO List Splitter Tool

## Overview

This tool is designed to split the massive `master_todo_list.md` file into separate `TODO.md` files for each subdirectory in the `ipfs_datasets_py` folder (excluding `mcp_server`). This organization makes it easier for individual workers to focus on specific directories and track their progress.

## Worker Assignment

**Worker 10**: Split master_todo_list.md into separate TODO.md files for each subdirectory in ipfs_datasets_py except mcp_server.

## Worker Assignment Tool

The TODO splitter includes a worker assignment system that randomly assigns workers to directories. This ensures fair distribution of work and prevents conflicts.

### Assignment Algorithm

```python
def assign_workers_to_directories(subdirs, start_worker_id=61):
    """
    Randomly assign workers to directories.
    
    Args:
        subdirs: List of subdirectories to assign workers to
        start_worker_id: Starting worker ID number
        
    Returns:
        dict: Mapping of directory to worker ID
    """
    import random
    
    # Create worker pool starting from start_worker_id
    workers = list(range(start_worker_id, start_worker_id + len(subdirs)))
    
    # Shuffle workers for random assignment
    random.shuffle(workers)
    
    # Assign workers to directories
    assignments = {}
    for i, subdir in enumerate(subdirs):
        assignments[subdir] = workers[i]
    
    return assignments
```

### Current Directory-Worker Assignments

The following workers have been assigned to directories:

- **Worker 61**: `audit/` directory
- **Worker 62**: `config/` directory  
- **Worker 63**: `embeddings/` directory
- **Worker 64**: `ipfs_embeddings_py/` directory
- **Worker 65**: `ipld/` directory
- **Worker 66**: `llm/` directory
- **Worker 67**: `logic_integration/` directory
- **Worker 68**: `mcp_tools/` directory
- **Worker 69**: `multimedia/` directory
- **Worker 70**: `optimizers/` directory
- **Worker 71**: `rag/` directory
- **Worker 72**: `search/` directory
- **Worker 73**: `utils/` directory
- **Worker 74**: `vector_stores/` directory
- **Worker 75**: `wikipedia_x/` directory

### Adding Worker Assignments to CLAUDE.md

The tool automatically updates the CLAUDE.md file with new worker assignments:

```markdown
### Directory-Specific Jobs - Workers 61-75
- [ ] 61: Complete TDD tasks for audit/ directory
- [ ] 62: Complete TDD tasks for config/ directory
- [ ] 63: Complete TDD tasks for embeddings/ directory
- [ ] 64: Complete TDD tasks for ipfs_embeddings_py/ directory
- [ ] 65: Complete TDD tasks for ipld/ directory
- [ ] 66: Complete TDD tasks for llm/ directory
- [ ] 67: Complete TDD tasks for logic_integration/ directory
- [ ] 68: Complete TDD tasks for mcp_tools/ directory
- [ ] 69: Complete TDD tasks for multimedia/ directory
- [ ] 70: Complete TDD tasks for optimizers/ directory
- [ ] 71: Complete TDD tasks for rag/ directory
- [ ] 72: Complete TDD tasks for search/ directory
- [ ] 73: Complete TDD tasks for utils/ directory
- [ ] 74: Complete TDD tasks for vector_stores/ directory
- [ ] 75: Complete TDD tasks for wikipedia_x/ directory
```

## Purpose

The original `master_todo_list.md` file was 2.4MB in size and contained comprehensive Test-Driven Development (TDD) tasks for the entire codebase. This made it unwieldy to work with. The splitter tool addresses this by:

1. **Organizing tasks by directory**: Each subdirectory gets its own `TODO.md` file
2. **Maintaining TDD methodology**: All tasks follow the Red-Green-Refactor cycle
3. **Improving workflow**: Workers can focus on specific directories without scrolling through massive files
4. **Preserving structure**: The original hierarchical task structure is maintained

## How It Works

### Script: `split_todo_script.py`

The script performs the following operations:

1. **Identifies target directories**: Scans all subdirectories in `ipfs_datasets_py` except `mcp_server`
2. **Parses master todo list**: Reads and analyzes the structure of `master_todo_list.md`
3. **Extracts relevant sections**: Identifies tasks belonging to each subdirectory
4. **Creates TODO.md files**: Generates individual TODO.md files for each subdirectory
5. **Preserves existing files**: Skips directories that already have TODO.md files

### Target Directories

The following subdirectories received TODO.md files:

- `audit/` - Security and audit functionality
- `config/` - Configuration management
- `embeddings/` - Embedding generation and processing
- `ipfs_embeddings_py/` - IPFS-specific embedding tools
- `ipld/` - IPLD (InterPlanetary Linked Data) functionality
- `llm/` - Large Language Model integration
- `logic_integration/` - Logic and reasoning components
- `mcp_tools/` - MCP (Model Context Protocol) tools
- `multimedia/` - Media processing tools
- `optimizers/` - Query and processing optimizers
- `rag/` - Retrieval-Augmented Generation tools
- `search/` - Search functionality
- `utils/` - Utility functions
- `vector_stores/` - Vector storage implementations
- `wikipedia_x/` - Wikipedia-specific tools

## Generated TODO.md Structure

Each generated `TODO.md` file contains:

### Header
- Directory name and purpose
- Explanation of TDD methodology

### TDD Cycle Description
1. Write function stub with type hints and comprehensive docstring
2. Write test that calls the actual (not-yet-implemented) callable
3. Write additional test cases for edge cases and error conditions
4. Run all tests to confirm they fail (red phase)
5. Implement the method to make tests pass (green phase)
6. Refactor implementation while keeping tests passing (refactor phase)

### Tasks Section
- Hierarchical task list extracted from master_todo_list.md
- File-specific tasks organized by Python modules
- Class and method-specific TDD tasks

## Usage

```bash
# Run the splitter script
python split_todo_script.py
```

The script will:
- Create TODO.md files in each target subdirectory
- Skip directories that already have TODO.md files
- Display progress messages for each created file

## Benefits

1. **Focused Work**: Workers can concentrate on specific directories
2. **Reduced Cognitive Load**: Smaller, manageable task lists
3. **Better Organization**: Clear separation of concerns
4. **Preserved Methodology**: TDD practices maintained across all directories
5. **Scalable Workflow**: Easy to add new directories or workers

## Integration with Project Workflow

This tool supports the project's worker-based development model where:
- Each worker has a designated number and directory
- Workers document actions in CHANGELOG.md
- Workers track tasks in TODO.md
- Workers document architecture decisions in ARCHITECTURE.md

## Files Created

- `split_todo_script.py` - The main splitter script
- `README_TODO_SPLITTER.md` - This documentation
- `TODO.md` files in each target subdirectory

## Dependencies

- Python 3.6+
- No external dependencies required
- Uses only standard library modules (os, re, pathlib)

## Notes

- The script preserves the original master_todo_list.md file
- Generated TODO.md files can be manually edited as needed
- The tool can be re-run safely (it skips existing TODO.md files)
- Each TODO.md file is self-contained and follows the same format

## Future Enhancements

Potential improvements could include:
- Better parsing of complex task hierarchies
- Integration with project management tools
- Automated progress tracking
- Cross-reference validation between directories