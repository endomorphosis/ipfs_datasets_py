"""Architecture guards for the production state-law indexing pipeline.

The state-law modules may project legal-domain fields and enforce stricter
release rules, but they must not fork the physical GraphRAG, embedding, sort,
resolver, or query implementations already used by the other legal datasets.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from types import ModuleType

import pytest

from ipfs_datasets_py.processors.legal_data import (
    legal_graph_core,
    open_us_law_acquisition_coordinator,
    open_us_law_embeddings,
    open_us_law_graph,
    state_laws_adjacency,
    state_laws_bm25,
    state_laws_bm25_physical,
    state_laws_chunk_physical,
    state_laws_corpus_physical,
    state_laws_embedding_store,
    state_laws_embeddings,
    state_laws_graph,
    state_laws_graph_physical,
    state_laws_graph_streaming_projection,
    state_laws_graphrag_adapter,
    state_laws_hf_release,
    state_laws_legacy_v2_adapter,
    state_laws_local_release,
    state_laws_query,
    state_laws_source_provenance,
    state_laws_source_receipt_reuse,
    state_laws_sparse_graphrag,
    state_laws_vector_physical,
    state_laws_vectors,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    base_scraper,
    georgia_archived_official,
    state_archival_fetch,
    state_archival_pointer_downloader,
)
from ipfs_datasets_py.processors.web_archiving import common_crawl_integration
from ipfs_datasets_py.processors.web_archiving.common_crawl_search_engine.ccindex import (
    api as common_crawl_api,
)
from ipfs_datasets_py.retrieval.hf_graphrag import (
    artifacts,
    external_sort,
    streaming_bm25,
    streaming_graph,
)
from ipfs_datasets_py.retrieval.hf_graphrag import bm25 as shared_bm25
from ipfs_datasets_py.retrieval.hf_graphrag import graph as shared_graph
from ipfs_datasets_py.retrieval.hf_graphrag import locators as shared_locators
from ipfs_datasets_py.retrieval.hf_graphrag import query as shared_query
from ipfs_datasets_py.retrieval.hf_graphrag import vectors as shared_vectors

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

# Exact shared implementation names that a state adapter must import.  A
# legal-domain wrapper can have its own name, but redefining one of these names
# is evidence that a second infrastructure implementation has appeared.
SHARED_IMPLEMENTATION_NAMES = frozenset(
    {
        "BoundedRemoteQueryEngine",
        "OpenUsLawEmbeddingGenerator",
        "atomic_staging",
        "atomic_write_canonical_json",
        "confine_path",
        "describe_file",
        "digest_sorted_bm25_term_statistics",
        "external_sort_to_file",
        "evaluate_prior_receipt",
        "file_digest",
        "manifest_descriptor",
        "validate_locator_ranges",
        "resolve_embedder",
        "resolve_release_root",
        "stream_bounded_partitions",
        "validate_graph_layout",
        "verify_descriptor",
        "write_centroid_routed_vectors",
        "write_graph_layout",
        "write_streaming_multifield_bm25_layout",
        "write_streaming_graph_layout",
        "write_zstd_parquet",
    }
)

PRODUCTION_STATE_ADAPTERS = (
    state_laws_corpus_physical,
    state_laws_chunk_physical,
    state_laws_embedding_store,
    state_laws_bm25_physical,
    state_laws_vector_physical,
    state_laws_graph_streaming_projection,
    state_laws_graph_physical,
    state_laws_legacy_v2_adapter,
    state_laws_source_receipt_reuse,
    state_laws_local_release,
)


def _top_level_definitions(module: ModuleType) -> set[str]:
    path = Path(module.__file__ or "")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _module_source(module: ModuleType) -> str:
    path = Path(module.__file__ or "")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("adapter", "name", "shared"),
    (
        (
            state_laws_embedding_store,
            "OpenUsLawEmbeddingGenerator",
            open_us_law_embeddings.OpenUsLawEmbeddingGenerator,
        ),
        (
            state_laws_embedding_store,
            "resolve_embedder",
            open_us_law_embeddings.resolve_embedder,
        ),
        (
            state_laws_bm25,
            "bm25_term_score",
            shared_bm25.bm25_term_score,
        ),
        (
            state_laws_bm25,
            "external_sort_to_file",
            external_sort.external_sort_to_file,
        ),
        (
            state_laws_corpus_physical,
            "atomic_staging",
            artifacts.atomic_staging,
        ),
        (
            state_laws_corpus_physical,
            "write_zstd_parquet",
            artifacts.write_zstd_parquet,
        ),
        (
            state_laws_corpus_physical,
            "_manifest_descriptor",
            artifacts.manifest_descriptor,
        ),
        (
            state_laws_chunk_physical,
            "external_sort_to_file",
            external_sort.external_sort_to_file,
        ),
        (
            state_laws_chunk_physical,
            "write_zstd_parquet",
            artifacts.write_zstd_parquet,
        ),
        (
            state_laws_chunk_physical,
            "_manifest_descriptor",
            artifacts.manifest_descriptor,
        ),
        (
            state_laws_bm25_physical,
            "write_zstd_parquet",
            artifacts.write_zstd_parquet,
        ),
        (
            state_laws_bm25_physical,
            "_manifest_descriptor",
            artifacts.manifest_descriptor,
        ),
        (
            state_laws_bm25_physical,
            "write_streaming_multifield_bm25_layout",
            streaming_bm25.write_streaming_multifield_bm25_layout,
        ),
        (
            state_laws_vector_physical,
            "external_sort_to_file",
            external_sort.external_sort_to_file,
        ),
        (
            state_laws_vector_physical,
            "write_centroid_routed_vectors",
            shared_vectors.write_centroid_routed_vectors,
        ),
        (
            state_laws_vector_physical,
            "_descriptor_dict",
            artifacts.manifest_descriptor,
        ),
        (
            state_laws_vector_physical,
            "LocatorRow",
            shared_locators.LocatorRow,
        ),
        (
            state_laws_vector_physical,
            "validate_locator_ranges",
            shared_locators.validate_locator_ranges,
        ),
        (
            state_laws_graph_streaming_projection,
            "StateLawsGraphProjector",
            state_laws_graph.StateLawsGraphProjector,
        ),
        (
            state_laws_graph_physical,
            "digest_sorted_bm25_term_statistics",
            streaming_bm25.digest_sorted_bm25_term_statistics,
        ),
        (
            state_laws_graph_physical,
            "write_streaming_graph_layout",
            streaming_graph.write_streaming_graph_layout,
        ),
        (
            state_laws_graph_physical,
            "write_graph_layout",
            shared_graph.write_graph_layout,
        ),
        (
            state_laws_graph_physical,
            "validate_graph_layout",
            shared_graph.validate_graph_layout,
        ),
        (
            state_laws_local_release,
            "external_sort_to_file",
            external_sort.external_sort_to_file,
        ),
        (
            state_laws_local_release,
            "verify_artifact_descriptor",
            artifacts.verify_descriptor,
        ),
        (
            state_laws_legacy_v2_adapter,
            "file_digest",
            artifacts.file_digest,
        ),
        (
            state_laws_legacy_v2_adapter,
            "verify_state_law_transport_receipt",
            state_laws_source_provenance.verify_state_law_transport_receipt,
        ),
        (
            state_laws_source_receipt_reuse,
            "evaluate_prior_receipt",
            open_us_law_acquisition_coordinator.evaluate_prior_receipt,
        ),
        (
            state_laws_source_receipt_reuse,
            "normalize_source_receipt",
            state_laws_legacy_v2_adapter.normalize_source_receipt,
        ),
        (
            georgia_archived_official,
            "canonicalize_state_law_transport_receipt",
            state_laws_source_provenance.canonicalize_state_law_transport_receipt,
        ),
        (
            state_laws_query,
            "BoundedRemoteQueryEngine",
            shared_query.BoundedRemoteQueryEngine,
        ),
    ),
)
def test_state_pipeline_binds_shared_implementations(
    adapter: ModuleType,
    name: str,
    shared: object,
) -> None:
    """Imported core symbols remain the same objects used by other datasets."""

    assert getattr(adapter, name) is shared


@pytest.mark.parametrize("module", PRODUCTION_STATE_ADAPTERS)
def test_state_adapters_do_not_redefine_shared_implementations(
    module: ModuleType,
) -> None:
    """Prevent a state-specific module from growing a duplicate core stack."""

    duplicated = _top_level_definitions(module) & SHARED_IMPLEMENTATION_NAMES
    assert duplicated == set()


def test_state_bm25_physical_layer_is_a_lossless_legal_projection() -> None:
    """The one specialized writer preserves fields absent from the generic API."""

    assert state_laws_bm25.FIELD_ORDER == (
        "citation",
        "title",
        "heading",
        "hierarchy",
        "jurisdiction",
        "body",
        "note",
    )
    assert state_laws_bm25_physical.QUERY_TITLE_FIELDS == ("title",)
    assert state_laws_bm25_physical.QUERY_BODY_FIELDS == (
        "citation",
        "heading",
        "hierarchy",
        "jurisdiction",
        "body",
        "note",
    )
    assert state_laws_bm25_physical.INDEX_TO_LAYOUT_PRODUCTION_READY is False
    assert state_laws_bm25_physical.ITERABLE_TO_LAYOUT_PRODUCTION_READY is True
    assert state_laws_graph_physical.LEGACY_OVERLAY_PRODUCTION_READY is False
    assert (
        state_laws_graph_physical.LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY
        is False
    )
    assert state_laws_graph_physical.STREAMING_GRAPH_WRITER_PRODUCTION_READY is True
    assert state_laws_graph_physical.PHYSICAL_BM25_EVIDENCE_PRODUCTION_READY is True


def test_canonical_chunk_store_is_the_only_production_rechunk_boundary() -> None:
    """Downstream physical stages must replay chunks, never recreate them."""

    assert state_laws_chunk_physical.STREAMING_CHUNK_STORE_PRODUCTION_READY is True
    assert state_laws_chunk_physical.CANONICAL_DOCUMENT_ORDER == (
        "jurisdiction_code",
        "chunk_cid",
    )
    assert state_laws_local_release.REQUIRED_INDEX_PATHS["corpus_documents"] == (
        "indexes/corpus_documents.parquet"
    )
    assert state_laws_local_release.REQUIRED_INDEX_PATHS["corpus_chunks"] == (
        "indexes/corpus_chunks.parquet"
    )
    assert "StateLawsChunker(" in _module_source(state_laws_chunk_physical)
    for downstream in (
        state_laws_bm25_physical,
        state_laws_embedding_store,
        state_laws_vector_physical,
        state_laws_graph_streaming_projection,
        state_laws_graph_physical,
        state_laws_local_release,
    ):
        source = _module_source(downstream)
        assert "StateLawsChunker(" not in source
        assert ".chunk_statute(" not in source


def test_streaming_state_graph_projection_reuses_ontology_and_shared_writer() -> None:
    """Fence the bounded input seam from becoming a second graph stack."""

    projection_source = _module_source(state_laws_graph_streaming_projection)
    projection_definitions = _top_level_definitions(
        state_laws_graph_streaming_projection
    )

    # The state-specific stage delegates every legal relation family to the
    # established ontology projector.  It may own disk-backed registries, but
    # not a second ontology implementation.
    for helper in (
        "_project_structure",
        "_project_citations",
        "_project_amendments",
    ):
        assert f"projector.{helper}(" in projection_source
    assert {
        "GraphOntology",
        "StateLawsGraphEdge",
        "StateLawsGraphNode",
        "StateLawsGraphProjector",
    }.isdisjoint(projection_definitions)

    # Physical graph writing remains one adapter call into the same shared
    # streaming writer used by the other GraphRAG datasets.
    assert "write_streaming_graph_layout" not in projection_definitions
    assert "write_state_laws_streaming_graph_layout" not in projection_definitions
    assert (
        state_laws_graph_physical.write_streaming_graph_layout
        is streaming_graph.write_streaming_graph_layout
    )
    assert state_laws_graph_streaming_projection.PRODUCTION_READY is True
    assert state_laws_graph_streaming_projection.PERFORMS_NETWORK_IO is False
    assert state_laws_graph_streaming_projection.AUTHORIZES_PUBLICATION is False
    assert state_laws_graph_streaming_projection.AUTHORIZES_HUB_UPLOAD is False


def test_public_query_wrapper_accepts_production_local_release_schema() -> None:
    assert (
        state_laws_sparse_graphrag.RELEASE_SCHEMA_VERSION
        in state_laws_sparse_graphrag.SUPPORTED_RELEASE_SCHEMAS
    )


@pytest.mark.parametrize(
    "module",
    (
        state_laws_adjacency,
        state_laws_bm25,
        state_laws_embeddings,
        state_laws_graphrag_adapter,
        state_laws_hf_release,
        state_laws_query,
        state_laws_vectors,
    ),
)
def test_parallel_legacy_contract_modules_cannot_authorize_production(
    module: ModuleType,
) -> None:
    """Keep cloned fixture-era stacks outside the production release gate."""

    assert module.PROVES_SOFTWARE_CONTRACT_ONLY is True
    assert module.AUTHORIZES_PUBLICATION is False
    assert module.AUTHORIZES_RELEASE is False
    assert module.AUTHORIZES_HUB_UPLOAD is False


@pytest.mark.parametrize(
    "relative_path",
    (
        "scripts/ops/legal_data/build_state_laws_sparse_graphrag.py",
        "scripts/ops/legal_data/build_state_laws_hf_release.py",
    ),
)
def test_legacy_compact_build_cannot_be_mistaken_for_production(
    relative_path: str,
) -> None:
    """Older fixture orchestrators remain explicit non-release paths."""

    path = REPOSITORY_ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constants: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            try:
                constants[node.target.id] = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                continue

    assert constants["PROVES_SOFTWARE_CONTRACT_ONLY"] is True
    assert constants["AUTHORIZES_PUBLICATION"] is False
    assert constants["AUTHORIZES_RELEASE"] is False
    assert constants["AUTHORIZES_HUB_UPLOAD"] is False


def test_state_scraper_fallback_reuses_web_archiving_engines() -> None:
    """Keep archive recovery on the shared transport modules."""

    base_source = _module_source(base_scraper)
    bridge_source = _module_source(state_archival_fetch)

    assert "from .state_archival_fetch import ArchivalFetchClient" in base_source
    assert "state_archival_pointer_downloader" not in base_source
    for shared_module in (
        "ipfs_datasets_py.processors.web_archiving.common_crawl_integration",
        "ipfs_datasets_py.processors.web_archiving.wayback_machine_engine",
    ):
        assert shared_module in bridge_source
    assert "ipfs_datasets_py.processors.web_archiving.archive_is_engine" not in bridge_source

    duplicated_engine_entrypoints = {
        "archive_to_archive_is",
        "extract_http_from_warc_gzip_member",
        "fetch_warc_record",
        "get_archive_is_content",
        "get_wayback_content",
        "search_wayback_machine",
    } & _top_level_definitions(state_archival_fetch)
    assert duplicated_engine_entrypoints == set()

    # The older Common-Crawl pointer utility must also be a client of the
    # shared bridge, not a second archive transport implementation.
    assert (
        state_archival_pointer_downloader.ArchivalFetchClient
        is state_archival_fetch.ArchivalFetchClient
    )
    assert (
        state_archival_pointer_downloader.FetchResult
        is state_archival_fetch.FetchResult
    )
    assert {
        "ArchivalFetchClient",
        "FetchResult",
        "_HttpResponse",
    }.isdisjoint(_top_level_definitions(state_archival_pointer_downloader))


def test_state_common_crawl_warc_transport_is_only_a_shared_api_adapter() -> None:
    """Ban a second HTTP Range downloader or WARC/HTTP parser in state code."""

    assert (
        state_archival_fetch.CommonCrawlSearchEngine
        is common_crawl_integration.CommonCrawlSearchEngine
    )
    assert (
        state_archival_fetch.extract_http_from_warc_gzip_member
        is common_crawl_api.extract_http_from_warc_gzip_member
    )
    assert state_archival_fetch.warc_download_url is common_crawl_api.warc_download_url

    path = Path(state_archival_fetch.__file__ or "")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    client = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ArchivalFetchClient"
    )
    methods = [
        node
        for node in client.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in {
            "_fetch_from_common_crawl_warc_record",
            "_common_crawl_result_from_warc_bytes",
            "fetch_common_crawl_records",
        }
    ]
    assert len(methods) == 3
    called_names = {
        node.func.id
        for method in methods
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
    }
    called_attributes = {
        node.func.attr
        for method in methods
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }
    string_literals = {
        node.value
        for method in methods
        for node in ast.walk(method)
        if isinstance(node, ast.Constant) and isinstance(node.value, (bytes, str))
    }
    imported_modules = {
        alias.name.split(".", 1)[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "extract_http_from_warc_gzip_member" in called_names
    assert "warc_download_url" in called_names
    assert "fetch_warc_record" in called_attributes
    assert "fetch_warc_record_ranges_sliced" in string_literals
    assert {
        "_extract_html_from_warc_bytes",
        "_request_with_retries",
        "decompress",
        "urlopen",
    }.isdisjoint(called_attributes)
    assert {"gzip", "zlib"}.isdisjoint(imported_modules)
    serialized_literals = {
        value.decode("latin-1") if isinstance(value, bytes) else value
        for value in string_literals
    }
    assert not any("Range" in value for value in serialized_literals)
    assert not any("data.commoncrawl.org" in value for value in serialized_literals)
    assert not any("WARC/" in value for value in serialized_literals)
    assert not any("HTTP/" in value for value in serialized_literals)

    # The inherited state-scraper recovery path must consume the same archive
    # bridge instead of fetching ranges or decoding WARC/HTTP payloads again.
    base_tree = ast.parse(
        _module_source(base_scraper),
        filename=str(base_scraper.__file__ or "base_scraper.py"),
    )
    base_class = next(
        node
        for node in base_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "BaseStateScraper"
    )
    recovery = next(
        node
        for node in base_class.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_scrape_state_common_crawl_candidates"
    )
    recovery_attributes = {
        node.attr
        for node in ast.walk(recovery)
        if isinstance(node, ast.Attribute)
    }
    assert "fetch_common_crawl_records" in recovery_attributes
    assert {
        "fetch_warc_record",
        "extract_http_from_warc_gzip_member",
    }.isdisjoint(recovery_attributes)
    recovery_source = ast.get_source_segment(_module_source(base_scraper), recovery) or ""
    assert "body_text_preview" not in recovery_source
    assert not any("\r\n\r\n" in value for value in serialized_literals)


def test_production_legal_graph_projection_reuses_shared_core() -> None:
    """Keep production graph mechanics shared while identity seams stay explicit."""

    projector_methods = (
        "_edge",
        "_ensure_node",
        "_normalize_public_law_id",
        "_project_amendments",
        "_project_citations",
        "_project_structure",
        "_synthetic_field_span",
    )
    for projector in (
        open_us_law_graph.OpenUsLawGraphProjector,
        state_laws_graph.StateLawsGraphProjector,
    ):
        assert issubclass(projector, legal_graph_core.LegalGraphProjectorCore)
        for method_name in projector_methods:
            assert getattr(projector, method_name) is getattr(
                legal_graph_core.LegalGraphProjectorCore,
                method_name,
            )

    for module, projector_name, node_name, edge_name in (
        (
            open_us_law_graph,
            "OpenUsLawGraphProjector",
            "OpenUsLawGraphNode",
            "OpenUsLawGraphEdge",
        ),
        (
            state_laws_graph,
            "StateLawsGraphProjector",
            "StateLawsGraphNode",
            "StateLawsGraphEdge",
        ),
    ):
        source_span = module.SourceSpan
        citation_mention = module.CitationMention
        node_type = getattr(module, node_name)
        edge_type = getattr(module, edge_name)

        assert source_span.__post_init__ is legal_graph_core.validate_source_span_record
        assert source_span.bind_to_source is legal_graph_core.bind_source_span
        assert source_span.to_dict is legal_graph_core.source_span_to_dict
        assert citation_mention.__post_init__ is (
            legal_graph_core.validate_citation_mention_record
        )
        assert citation_mention.to_dict is legal_graph_core.citation_mention_to_dict
        assert node_type.__post_init__ is legal_graph_core.validate_graph_node_record
        assert node_type.to_dict is legal_graph_core.graph_node_to_dict
        assert edge_type.__post_init__ is legal_graph_core.validate_graph_edge_record
        assert edge_type.to_dict is legal_graph_core.graph_edge_to_dict
        assert module.GraphOntology.validate_edge is (
            legal_graph_core.validate_graph_ontology_edge
        )
        assert module.lookup_citation_locator is legal_graph_core.lookup_citation_locator
        assert module.CITATION_CODE_ALIASES is legal_graph_core.CITATION_CODE_ALIASES

        path = Path(module.__file__ or "")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        projector_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == projector_name
        )
        locally_defined_projector_methods = {
            node.name
            for node in projector_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert set(projector_methods).isdisjoint(locally_defined_projector_methods)

        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        extractor = functions["extract_citation_mentions"]
        resolver = functions["resolve_citations"]
        assert not any(isinstance(node, ast.For) for node in ast.walk(extractor))
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "finditer"
            for node in ast.walk(extractor)
        )
        called_names = {
            node.func.id
            for root in (extractor, resolver)
            for node in ast.walk(root)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "extract_citation_mentions_core" in called_names
        assert "resolve_citations_core" in called_names

    # These vocabularies are intentionally not aliases: state adds ACT and
    # VERSION_OF while OUL retains PUBLIC_LAW and its federal-ID semantics.
    assert state_laws_graph.GraphNodeType is not open_us_law_graph.GraphNodeType
    assert state_laws_graph.GraphEdgeType is not open_us_law_graph.GraphEdgeType


def test_shared_legal_graph_core_preserves_sealed_fixture_bytes() -> None:
    expected = {
        "open": (
            "4e355f96b85954801584988809f653fac05822e20a2275cbf514aa6984641258",
            "9dc7ba233dd50bedc7cea606596b20c54c11562e8406ed754f74fdcc4bd0974b",
        ),
        "state": (
            "1fc5ae5dca24c09ba1f3bab6ea0caee14506efaace80c747c732ed76309446a1",
            "3cce1e39a81f35023eec0722b82fad5c1b6b91c8b95dacc4e0312ce76c2d6496",
        ),
    }
    for name, module in (
        ("open", open_us_law_graph),
        ("state", state_laws_graph),
    ):
        graph_bytes = json.dumps(
            module.bind_fixture_graph().to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        report_bytes = json.dumps(
            module.run_fixture_case(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        assert (
            hashlib.sha256(graph_bytes).hexdigest(),
            hashlib.sha256(report_bytes).hexdigest(),
        ) == expected[name]
