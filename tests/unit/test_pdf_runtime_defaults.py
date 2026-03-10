from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph
from ipfs_datasets_py.processors.specialized.pdf.pdf_processor import _instantiate_graphrag_integrator


@pytest.mark.asyncio
async def test_compat_graphrag_integrator_supports_pdf_processor_document_flow() -> None:
    integrator = GraphRAGIntegrator(storage=None)
    llm_document = SimpleNamespace(
        document_id="az-rule-1",
        title="Arizona Administrative Code",
        chunks=[
            {"chunk_id": "chunk-1", "text": "Arizona Department adopts Rule R1-1-101."},
            {"chunk_id": "chunk-2", "text": "Rule R1-1-101 defines filing requirements."},
        ],
    )

    graph = await integrator.integrate_document(llm_document)

    assert isinstance(graph, KnowledgeGraph)
    assert graph.document_id == "az-rule-1"
    assert graph.chunks == llm_document.chunks
    assert any(entity.text == "Arizona Department" for entity in graph.entities)
    assert any(relationship.relationship_type for relationship in graph.relationships)


def test_instantiate_graphrag_integrator_handles_common_constructor_shapes() -> None:
    class FullSignature:
        def __init__(self, *, storage=None, logger=None):
            self.storage = storage
            self.logger = logger

    class StorageOnly:
        def __init__(self, *, storage=None):
            self.storage = storage

    class NoArgs:
        def __init__(self):
            self.created = True

    instance = _instantiate_graphrag_integrator(FullSignature, storage="s", logger="l")
    assert instance.storage == "s"
    assert instance.logger == "l"

    instance = _instantiate_graphrag_integrator(StorageOnly, storage="s", logger="l")
    assert instance.storage == "s"

    instance = _instantiate_graphrag_integrator(NoArgs, storage="s", logger="l")
    assert instance.created is True


def test_default_dependency_manifests_include_pdf_and_rtf_runtime_libraries() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifests = [
        repo_root / "setup.py",
        repo_root / "pyproject.toml",
        repo_root / "requirements.txt",
    ]
    required_specs = [
        "nltk",
        "pdfplumber",
        "pymupdf",
        "pillow",
        "PyPDF2",
        "pypdf",
        "pytesseract",
        "striprtf",
        "tiktoken",
        "pysbd",
    ]

    for manifest in manifests:
        content = manifest.read_text(encoding="utf-8")
        for spec in required_specs:
            assert spec in content, f"{spec} missing from {manifest.name}"