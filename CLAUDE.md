# CLAUDE.md

## Project Rules
- You will be assigned a designation number and the directory it is assigned to.
- Only work in your designated directory. Every directory and file outside it is to be considered a black box that you cannot modify or access.

## Jobs Available

### Priority Jobs - Workers 1 - 10
- [ ] 1: Implement robustness tests for file system operations.
- [ ] 2: Integrate claudes_toolbox dataset tools into library
- [ ] 3: Make claudes_toolbox dataset tools work with decentralized file system
- [ ] 4: Make claudes_toolbox dataset tools work in a docker container
- [ ] 5: Implement robustness tests for file system operations in `ipfs_datasets_py/pdf_processing/graphrag_integrator.py`

### Docstring Improvement - Workers 20 - 40
- [X] 1: Improve docstrings for python files in top-level directory for `ipfs_datasets_py`
- [X] 2: Improve docstrings for python files in `ipfs_datasets_py/audit`
- [X] 3: Improve docstrings for python files in `ipfs_datasets_py/pdf_processing`
- [X] 4: Improve docstrings for python files in `ipfs_datasets/config`
- [X] 5: Improve docstrings for python files in `ipfs_datasets/embeddings`

### Unit Test Writing - Workers 40 - 60

`class_diagram_to_python_files/`
- [X] 2: `entity_relationship_diagram_to_sql_schema/`
- [X] 3: `flowchart_to_directory_tree/`
- [ ] 4: Tests for `class_diagram_to_python_files`
- [ ] 5: Tests for `entity_relationship_diagram_to_sql_schema`
- [ ] 6: Tests for `flowchart_to_directory_tree`

### Identify Work That's Already Been Done - Workers 11 - 15
- [X] 11: Identify files in top-level directory for `ipfs_datasets_py` for which tests exist.

### Omni-Converted Integration - Workers 16 - 19

### IPFS Datasets Integration
- [ ] 16: Integrate dataset tools with  in 


`ipfs_datasets_py`




- Document all actions taken in your directory's CHANGELOG.md
- Document all actions that need to be do be done in your directory's TODO.md
- Document your software architecture decisions in your directory's ARCHITECTURE.md
- Read the CHANGELOG.md and TODO.md files in your directory before starting work. If you cannot find one, ask for it before looking for it.

## Code Writing Guidelines
- You will produce 1 function for export. The function has no arguments and constructs a single object.
- The object must have a series of pre-specified characteristics and meet pre-specified evaluation metrics. These characteristics and metrics will be specified in that directory's README.md file.
