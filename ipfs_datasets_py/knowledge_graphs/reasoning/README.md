# Cross-Document Reasoning Subpackage

This subpackage contains the cross-document reasoning components extracted from the
root-level modules of `knowledge_graphs/`.

## Modules

| Module | Description |
|--------|-------------|
| `types.py` | Core data types (`InformationRelationType`, `DocumentNode`, `EntityMediatedConnection`, `CrossDocReasoning`) |
| `helpers.py` | `ReasoningHelpersMixin` — traversal and LLM answer-generation helpers |
| `cross_document.py` | `CrossDocumentReasoner` — main cross-document reasoning engine |

## Migration from old import paths

| Old import | New import |
|-----------|-----------|
| `from ipfs_datasets_py.knowledge_graphs.cross_document_types import ...` | `from ipfs_datasets_py.knowledge_graphs.reasoning.types import ...` |
| `from ipfs_datasets_py.knowledge_graphs._reasoning_helpers import ...` | `from ipfs_datasets_py.knowledge_graphs.reasoning.helpers import ...` |
| `from ipfs_datasets_py.knowledge_graphs.cross_document_reasoning import ...` | `from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import ...` |

The old root-level paths remain as deprecation shims for backward compatibility.
