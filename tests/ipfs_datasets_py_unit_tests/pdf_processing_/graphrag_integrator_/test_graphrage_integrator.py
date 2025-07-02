import pytest
from unittest.mock import Mock, AsyncMock, patch


class TestGraphRAGIntegratorIntegrateDocument:
    """Test GraphRAGIntegrator integrate_document method."""


    async def test_integrate_document_success_with_valid_llm_document(self):
        """
        GIVEN a valid LLMDocument with document_id, title, and chunks
        AND mock methods for entity extraction, relationship extraction, and IPLD storage
        WHEN integrate_document is called
        THEN expect:
            - Entities are extracted from chunks
            - Relationships are extracted from entities and chunks
            - KnowledgeGraph is created with correct structure
            - Graph is stored in IPLD and CID is returned
            - Graph is merged into global graph
            - Cross-document relationships are discovered
            - NetworkX graph is created and stored
            - Returned KnowledgeGraph has all expected attributes
        """

    async def test_integrate_document_with_empty_chunks(self):
        """
        GIVEN an LLMDocument with empty chunks list
        WHEN integrate_document is called
        THEN expect:
            - KnowledgeGraph is created with empty entities and relationships
            - Graph is still stored in IPLD
            - Global graph operations complete successfully
        """

    async def test_integrate_document_with_invalid_llm_document_missing_id(self):
        """
        GIVEN an LLMDocument missing document_id attribute
        WHEN integrate_document is called
        THEN expect ValueError to be raised
        """

    async def test_integrate_document_with_invalid_llm_document_missing_chunks(self):
        """
        GIVEN an LLMDocument missing chunks attribute
        WHEN integrate_document is called
        THEN expect ValueError to be raised
        """

    async def test_integrate_document_entity_extraction_failure(self):
        """
        GIVEN a valid LLMDocument
        AND _extract_entities_from_chunks raises an exception
        WHEN integrate_document is called
        THEN expect the exception to be propagated
        """

    async def test_integrate_document_relationship_extraction_failure(self):
        """
        GIVEN a valid LLMDocument
        AND _extract_relationships raises an exception
        WHEN integrate_document is called
        THEN expect the exception to be propagated
        """

    async def test_integrate_document_ipld_storage_failure(self):
        """
        GIVEN a valid LLMDocument
        AND _store_knowledge_graph_ipld returns empty string (failure)
        WHEN integrate_document is called
        THEN expect:
            - KnowledgeGraph is created with ipld_cid as empty string
            - Global graph operations still complete
            - Method returns successfully
        """

    async def test_integrate_document_global_graph_merge_failure(self):
        """
        GIVEN a valid LLMDocument
        AND _merge_into_global_graph raises an exception
        WHEN integrate_document is called
        THEN expect the exception to be propagated
        """

    async def test_integrate_document_cross_document_discovery_failure(self):
        """
        GIVEN a valid LLMDocument
        AND _discover_cross_document_relationships raises an exception
        WHEN integrate_document is called
        THEN expect the exception to be propagated
        """

    async def test_integrate_document_updates_knowledge_graphs_collection(self):
        """
        GIVEN a valid LLMDocument with document_id "doc123"
        WHEN integrate_document is called
        THEN expect:
            - self.knowledge_graphs["doc123"] is set to the created KnowledgeGraph
            - Graph can be retrieved from the collection
        """

class TestGraphRAGIntegratorQueryGraph:
    """Test GraphRAGIntegrator query_graph method."""




    async def test_query_graph_global_search_with_matching_entities(self):
        """
        GIVEN global_entities containing entities with names matching query "John Smith"
        AND graph_id is None (global search)
        WHEN query_graph is called with query "John Smith"
        THEN expect:
            - Results dict contains 'query', 'entities', 'relationships', 'total_matches', 'timestamp'
            - Matching entities are returned in 'entities' list
            - Related relationships are returned in 'relationships' list
            - total_matches reflects actual number of matches found
            - Results are limited by max_results parameter
        """

    async def test_query_graph_specific_graph_search(self):
        """
        GIVEN knowledge_graphs contains graph with ID "graph123"
        AND graph contains entities matching query
        WHEN query_graph is called with graph_id="graph123"
        THEN expect:
            - Search is performed only on specified graph
            - Results contain entities from that graph only
            - Relationships are filtered to specified graph
        """

    async def test_query_graph_case_insensitive_matching(self):
        """
        GIVEN entities with names containing "COMPANY" and "company"
        WHEN query_graph is called with query "Company"
        THEN expect:
            - Both entities are matched regardless of case
            - Case-insensitive search is performed
        """

    async def test_query_graph_entity_type_matching(self):
        """
        GIVEN entities with types "person", "organization", "location"
        WHEN query_graph is called with query "person"
        THEN expect:
            - Entities with type "person" are matched
            - Type-based matching is performed alongside name matching
        """

    async def test_query_graph_entity_description_matching(self):
        """
        GIVEN entities with descriptions containing query terms
        WHEN query_graph is called with query matching description content
        THEN expect:
            - Entities are matched based on description content
            - Description-based search is performed
        """

    async def test_query_graph_with_max_results_limit(self):
        """
        GIVEN 15 entities matching query
        AND max_results set to 5
        WHEN query_graph is called
        THEN expect:
            - Only 5 entities returned in results
            - total_matches shows 15
            - Results are ranked by relevance
        """

    async def test_query_graph_no_matching_entities(self):
        """
        GIVEN no entities matching query "nonexistent"
        WHEN query_graph is called
        THEN expect:
            - Empty entities list in results
            - Empty relationships list in results
            - total_matches is 0
        """

    async def test_query_graph_empty_query_string(self):
        """
        GIVEN empty query string ""
        WHEN query_graph is called
        THEN expect:
            - No entities matched
            - Empty results returned
        """

    async def test_query_graph_nonexistent_graph_id(self):
        """
        GIVEN graph_id "nonexistent" that doesn't exist in knowledge_graphs
        WHEN query_graph is called with this graph_id
        THEN expect:
            - Empty results returned
            - No exception raised
        """

    async def test_query_graph_relationship_filtering(self):
        """
        GIVEN entities that match query
        AND relationships connected to those entities
        WHEN query_graph is called
        THEN expect:
            - Only relationships involving matched entities are returned
            - Relationships are properly filtered and serialized
        """

    async def test_query_graph_timestamp_generation(self):
        """
        GIVEN any valid query
        WHEN query_graph is called
        THEN expect:
            - timestamp field in results is ISO format datetime string
            - timestamp represents query execution time
        """


class TestGraphRAGIntegratorGetEntityNeighborhood:
    """Test GraphRAGIntegrator get_entity_neighborhood method."""




    async def test_get_entity_neighborhood_depth_one_success(self):
        """
        GIVEN global_graph containing entity "entity1" with direct neighbors
        AND depth parameter set to 1
        WHEN get_entity_neighborhood is called with entity_id="entity1"
        THEN expect:
            - Results dict contains center_entity_id, depth, nodes, edges, node_count, edge_count
            - nodes contains entity1 and its direct neighbors only
            - edges contains only edges connecting entity1 to direct neighbors
            - node_count and edge_count reflect actual subgraph size
        """

    async def test_get_entity_neighborhood_depth_two_success(self):
        """
        GIVEN global_graph with entity "entity1" having neighbors at depth 1 and 2
        AND depth parameter set to 2
        WHEN get_entity_neighborhood is called
        THEN expect:
            - Subgraph includes nodes within 2 hops of entity1
            - All edges between included nodes are present
            - Depth-2 traversal is performed correctly
        """

    async def test_get_entity_neighborhood_nonexistent_entity(self):
        """
        GIVEN entity_id "nonexistent" that doesn't exist in global_graph
        WHEN get_entity_neighborhood is called
        THEN expect:
            - Results dict contains 'error' key with appropriate error message
            - No nodes or edges in results
        """

    async def test_get_entity_neighborhood_isolated_entity(self):
        """
        GIVEN entity "isolated" with no connections in global_graph
        WHEN get_entity_neighborhood is called
        THEN expect:
            - Results contain only the center entity as a node
            - Empty edges list
            - node_count is 1, edge_count is 0
        """

    async def test_get_entity_neighborhood_depth_zero(self):
        """
        GIVEN valid entity_id and depth set to 0
        WHEN get_entity_neighborhood is called
        THEN expect:
            - Results contain only the center entity
            - No neighboring nodes included
            - Empty edges list
        """

    async def test_get_entity_neighborhood_large_depth(self):
        """
        GIVEN valid entity_id and depth set to 10 (larger than graph diameter)
        WHEN get_entity_neighborhood is called
        THEN expect:
            - All reachable nodes from the entity are included
            - Method handles large depth gracefully
            - No infinite loops or performance issues
        """

    async def test_get_entity_neighborhood_node_attribute_serialization(self):
        """
        GIVEN global_graph with nodes containing various attribute types
        WHEN get_entity_neighborhood is called
        THEN expect:
            - All node attributes are properly serialized to dict format
            - Each node dict contains 'id' field plus original attributes
            - No serialization errors for complex attribute types
        """

    async def test_get_entity_neighborhood_edge_attribute_serialization(self):
        """
        GIVEN global_graph with edges containing various attribute types
        WHEN get_entity_neighborhood is called
        THEN expect:
            - All edge attributes are properly serialized to dict format
            - Each edge dict contains 'source', 'target' fields plus original attributes
            - No serialization errors for complex attribute types
        """

    async def test_get_entity_neighborhood_directed_graph_traversal(self):
        """
        GIVEN directed global_graph with entity having incoming and outgoing edges
        WHEN get_entity_neighborhood is called
        THEN expect:
            - Both predecessors and successors are included in traversal
            - Direction of edges is properly handled
            - All connected nodes within depth are found regardless of edge direction
        """

    async def test_get_entity_neighborhood_cyclic_graph_handling(self):
        """
        GIVEN global_graph containing cycles involving the target entity
        WHEN get_entity_neighborhood is called
        THEN expect:
            - Cycles are handled without infinite loops
            - Each node is visited only once during traversal
            - All nodes within depth are correctly identified
        """

class TestGraphRAGIntegratorExtractEntitiesFromChunks:
    """Test GraphRAGIntegrator _extract_entities_from_chunks method."""




    async def test_extract_entities_from_chunks_single_chunk_success(self):
        """
        GIVEN a list containing one LLMChunk with extractable entities
        AND _extract_entities_from_text returns list of entity dicts
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - _extract_entities_from_text is called once with chunk content
            - Returned entities have confidence >= entity_extraction_confidence
            - Entity objects are created with proper attributes (id, name, type, etc.)
            - source_chunks list contains the chunk_id
        """

    async def test_extract_entities_from_chunks_multiple_chunks_success(self):
        """
        GIVEN a list of multiple LLMChunks with different entities
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - _extract_entities_from_text is called for each chunk
            - Entities from all chunks are consolidated
            - Each entity's source_chunks reflects all chunks where it appears
        """

    async def test_extract_entities_from_chunks_duplicate_entity_consolidation(self):
        """
        GIVEN multiple chunks containing the same entity (same name and type)
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - Duplicate entities are consolidated into single Entity object
            - Confidence score is maximized across all mentions
            - source_chunks contains all chunk IDs where entity appears
            - Properties are merged (first occurrence wins for conflicts)
        """

    async def test_extract_entities_from_chunks_confidence_filtering(self):
        """
        GIVEN chunks with entities having various confidence scores
        AND entity_extraction_confidence set to 0.7
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - Only entities with confidence >= 0.7 are returned
            - Low-confidence entities are filtered out
        """

    async def test_extract_entities_from_chunks_empty_chunks_list(self):
        """
        GIVEN empty chunks list
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - Empty list of entities is returned
            - No exceptions are raised
        """

    async def test_extract_entities_from_chunks_no_entities_found(self):
        """
        GIVEN chunks that contain no extractable entities
        AND _extract_entities_from_text returns empty lists
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - Empty list of entities is returned
            - Method completes successfully
        """

    async def test_extract_entities_from_chunks_entity_id_generation(self):
        """
        GIVEN chunks with extractable entities
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - Each entity has unique ID generated from name and type hash
            - Same entity across chunks gets same ID
            - ID generation is consistent and deterministic
        """

    async def test_extract_entities_from_chunks_case_insensitive_deduplication(self):
        """
        GIVEN chunks containing entities with same name but different cases
        (e.g., "John Smith" and "JOHN SMITH")
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - Entities are treated as duplicates
            - Case-insensitive matching is performed
            - Single consolidated entity is returned
        """

    async def test_extract_entities_from_chunks_extraction_service_exception(self):
        """
        GIVEN _extract_entities_from_text raises an exception
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - Exception is propagated to caller
            - No partial results are returned
        """

    async def test_extract_entities_from_chunks_property_merging(self):
        """
        GIVEN same entity found in multiple chunks with different properties
        WHEN _extract_entities_from_chunks is called
        THEN expect:
            - Properties from all mentions are merged
            - First occurrence wins for conflicting property values
            - All unique properties are preserved
        """


class TestGraphRAGIntegratorExtractEntitiesFromText:
    """Test GraphRAGIntegrator _extract_entities_from_text method."""




    async def test_extract_entities_from_text_person_extraction(self):
        """
        GIVEN text containing person names like "Dr. John Smith" and "Jane Doe"
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Person entities are extracted with type "person"
            - Names include titles when present
            - Confidence score is 0.7 for pattern matching
            - Properties include extraction method and source chunk
        """

    async def test_extract_entities_from_text_organization_extraction(self):
        """
        GIVEN text containing organizations like "Apple Inc.", "Harvard University", "Goldman Sachs LLC"
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Organization entities are extracted with type "organization"
            - Company suffixes (Inc., LLC, Corp., etc.) are recognized
            - University and institutional patterns are matched
        """

    async def test_extract_entities_from_text_location_extraction(self):
        """
        GIVEN text containing locations like "123 Main St, New York, NY" and "San Francisco, CA"
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Location entities are extracted with type "location"
            - Address patterns are recognized
            - City, state combinations are matched
        """

    async def test_extract_entities_from_text_date_extraction(self):
        """
        GIVEN text containing dates like "01/15/2023", "January 15, 2023", "2023-01-15"
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Date entities are extracted with type "date"
            - Multiple date formats are recognized
            - Dates are properly identified and extracted
        """

    async def test_extract_entities_from_text_currency_extraction(self):
        """
        GIVEN text containing currency amounts like "$1,000", "$1.5 million", "USD 500"
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Currency entities are extracted with type "currency"
            - Dollar signs and currency symbols are recognized
            - Large number formats (million, billion) are handled
        """

    async def test_extract_entities_from_text_empty_string(self):
        """
        GIVEN empty text string
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Empty list of entities is returned
            - No exceptions are raised
        """

    async def test_extract_entities_from_text_no_matching_patterns(self):
        """
        GIVEN text with no recognizable entity patterns
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Empty list of entities is returned
            - Method completes successfully
        """

    async def test_extract_entities_from_text_duplicate_removal(self):
        """
        GIVEN text containing duplicate entity mentions
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Duplicate entities are removed
            - Only unique entities are returned
            - Case-insensitive deduplication is performed
        """

    async def test_extract_entities_from_text_regex_pattern_validation(self):
        """
        GIVEN text designed to test regex pattern edge cases
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Regex patterns handle edge cases gracefully
            - No regex errors are thrown
            - Boundary conditions are handled correctly
        """

    async def test_extract_entities_from_text_entity_description_generation(self):
        """
        GIVEN text with extractable entities
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Each entity has appropriate human-readable description
            - Descriptions reflect entity type and context
            - Descriptions are informative and consistent
        """

    async def test_extract_entities_from_text_properties_structure(self):
        """
        GIVEN text with extractable entities
        WHEN _extract_entities_from_text is called
        THEN expect:
            - Each entity has properties dict with extraction_method and source_chunk
            - Properties structure is consistent across entity types
            - Additional metadata is properly included
        """


class TestGraphRAGIntegratorExtractRelationships:
    """Test GraphRAGIntegrator _extract_relationships method."""




    async def test_extract_relationships_intra_chunk_relationships(self):
        """
        GIVEN entities list and chunks list with entities co-occurring in same chunks
        AND _extract_chunk_relationships returns relationships for co-occurring entities
        WHEN _extract_relationships is called
        THEN expect:
            - _extract_chunk_relationships is called for each chunk with >= 2 entities
            - Intra-chunk relationships are extracted and included in results
            - Entity index is built for efficient lookups
        """

    async def test_extract_relationships_cross_chunk_relationships(self):
        """
        GIVEN entities appearing across multiple chunks
        AND _extract_cross_chunk_relationships returns narrative relationships
        WHEN _extract_relationships is called
        THEN expect:
            - _extract_cross_chunk_relationships is called with entities and chunks
            - Cross-chunk relationships are extracted and included in results
            - Both intra-chunk and cross-chunk relationships are combined
        """

    async def test_extract_relationships_entity_indexing(self):
        """
        GIVEN entities with source_chunks referencing specific chunk IDs
        WHEN _extract_relationships is called
        THEN expect:
            - Entity index maps chunk_id to list of entities in that chunk
            - Index is used for efficient chunk-level relationship extraction
            - Only chunks with entities are processed
        """

    async def test_extract_relationships_single_entity_chunks_skipped(self):
        """
        GIVEN chunks that contain only one entity each
        WHEN _extract_relationships is called
        THEN expect:
            - Chunks with < 2 entities are skipped for intra-chunk processing
            - _extract_chunk_relationships is not called for single-entity chunks
            - Cross-chunk relationships are still extracted
        """

    async def test_extract_relationships_empty_entities_list(self):
        """
        GIVEN empty entities list
        WHEN _extract_relationships is called
        THEN expect:
            - Empty relationships list is returned
            - No relationship extraction methods are called
            - Method completes successfully
        """

    async def test_extract_relationships_empty_chunks_list(self):
        """
        GIVEN entities list but empty chunks list
        WHEN _extract_relationships is called
        THEN expect:
            - Empty relationships list is returned
            - No chunk-based processing occurs
        """

    async def test_extract_relationships_relationship_deduplication(self):
        """
        GIVEN overlapping relationships from intra-chunk and cross-chunk extraction
        WHEN _extract_relationships is called
        THEN expect:
            - Duplicate relationships are handled appropriately
            - All unique relationships are preserved
            - No duplicate relationship objects in final results
        """

    async def test_extract_relationships_logging_total_count(self):
        """
        GIVEN successful relationship extraction
        WHEN _extract_relationships is called
        THEN expect:
            - Total count of extracted relationships is logged
            - Logging message includes actual count
        """

    async def test_extract_relationships_chunk_extraction_exception(self):
        """
        GIVEN _extract_chunk_relationships raises an exception
        WHEN _extract_relationships is called
        THEN expect:
            - Exception is propagated to caller
            - No partial results are returned
        """

    async def test_extract_relationships_cross_chunk_extraction_exception(self):
        """
        GIVEN _extract_cross_chunk_relationships raises an exception
        WHEN _extract_relationships is called
        THEN expect:
            - Exception is propagated to caller
            - No partial results are returned
        """


class TestGraphRAGIntegratorExtractChunkRelationships:
    """Test GraphRAGIntegrator _extract_chunk_relationships method."""




    async def test_extract_chunk_relationships_entity_co_occurrence_success(self):
        """
        GIVEN entities list with multiple entities having source_chunks containing chunk.chunk_id
        AND chunk with content containing all entity names
        AND _infer_relationship_type returns valid relationship type
        WHEN _extract_chunk_relationships is called
        THEN expect:
            - Relationships are created for all entity pairs that co-occur in chunk
            - Each relationship has unique MD5-based ID
            - Confidence score is set to 0.6 for co-occurrence
            - source_chunks contains the chunk ID
            - Properties include extraction_method and context snippet
        """

    async def test_extract_chunk_relationships_case_insensitive_entity_matching(self):
        """
        GIVEN entities with names "John Smith" and chunk content containing "JOHN SMITH"
        WHEN _extract_chunk_relationships is called
        THEN expect:
            - Case-insensitive matching identifies entity in chunk content
            - Relationships are created despite case differences
        """

    async def test_extract_chunk_relationships_no_valid_relationship_types(self):
        """
        GIVEN entities that co-occur in chunk
        AND _infer_relationship_type returns None for all entity pairs
        WHEN _extract_chunk_relationships is called
        THEN expect:
            - No relationships are created when type inference fails
            - Empty relationships list is returned
        """

    async def test_extract_chunk_relationships_single_entity_in_chunk(self):
        """
        GIVEN entities list with only one entity having source_chunks containing chunk.chunk_id
        WHEN _extract_chunk_relationships is called
        THEN expect:
            - No relationships are created (need at least 2 entities)
            - Empty relationships list is returned
        """

    async def test_extract_chunk_relationships_no_entities_in_chunk(self):
        """
        GIVEN entities list where no entities have source_chunks containing chunk.chunk_id
        WHEN _extract_chunk_relationships is called
        THEN expect:
            - No relationships are created
            - Empty relationships list is returned
        """

    async def test_extract_chunk_relationships_entity_not_found_in_content(self):
        """
        GIVEN entities with names not present in chunk content
        WHEN _extract_chunk_relationships is called
        THEN expect:
            - Entities not found in content are excluded from relationship creation
            - Only entities actually present in content participate in relationships
        """

    async def test_extract_chunk_relationships_unique_id_generation(self):
        """
        GIVEN same entity pair in same chunk
        WHEN _extract_chunk_relationships is called multiple times
        THEN expect:
            - Consistent MD5-based IDs are generated for same entity pairs
            - ID generation is deterministic and reproducible
        """

    async def test_extract_chunk_relationships_description_generation(self):
        """
        GIVEN entities that co-occur with inferred relationship type
        WHEN _extract_chunk_relationships is called
        THEN expect:
            - Relationship description follows format "{entity1.name} {relationship_type} {entity2.name}"
            - Description is human-readable and informative
        """

    async def test_extract_chunk_relationships_context_snippet_extraction(self):
        """
        GIVEN chunk content with entity co-occurrence
        WHEN _extract_chunk_relationships is called
        THEN expect:
            - Context snippet (first 100 chars) is included in relationship properties
            - Context provides evidence for the relationship
        """

    async def test_extract_chunk_relationships_metadata_properties(self):
        """
        GIVEN successful relationship extraction
        WHEN _extract_chunk_relationships is called
        THEN expect:
            - Properties dict includes extraction_method: "co_occurrence"
            - Properties include context snippet
            - All metadata is properly structured
        """




import unittest
from unittest.mock import Mock, AsyncMock, patch

class TestGraphRAGIntegratorExtractCrossChunkRelationships:
    """Test GraphRAGIntegrator _extract_cross_chunk_relationships method."""




    async def test_extract_cross_chunk_relationships_sequential_chunks_success(self):
        """
        GIVEN entities appearing in sequential chunk sequences
        AND _find_chunk_sequences returns sequences of related chunks
        WHEN _extract_cross_chunk_relationships is called
        THEN expect:
            - Narrative sequence relationships are created between entities in same sequence
            - Relationship type is "narrative_sequence"
            - Confidence score is 0.4 for narrative relationships
            - All entity combinations within sequence are connected
        """

    async def test_extract_cross_chunk_relationships_multiple_sequences(self):
        """
        GIVEN multiple chunk sequences with different entities
        WHEN _extract_cross_chunk_relationships is called
        THEN expect:
            - Relationships are created within each sequence separately
            - No relationships created between entities from different sequences
            - All sequences are processed independently
        """

    async def test_extract_cross_chunk_relationships_same_entity_excluded(self):
        """
        GIVEN entity appearing multiple times in same sequence
        WHEN _extract_cross_chunk_relationships is called
        THEN expect:
            - No self-relationships are created (entity1.id != entity2.id check)
            - Only relationships between different entities are created
        """

    async def test_extract_cross_chunk_relationships_no_chunk_sequences(self):
        """
        GIVEN _find_chunk_sequences returns empty list
        WHEN _extract_cross_chunk_relationships is called
        THEN expect:
            - No relationships are created
            - Empty relationships list is returned
            - Method completes successfully
        """

    async def test_extract_cross_chunk_relationships_single_entity_sequences(self):
        """
        GIVEN chunk sequences containing only one entity each
        WHEN _extract_cross_chunk_relationships is called
        THEN expect:
            - No relationships are created within single-entity sequences
            - Method handles single-entity sequences gracefully
        """

    async def test_extract_cross_chunk_relationships_entity_source_chunk_matching(self):
        """
        GIVEN entities with source_chunks and chunk sequences
        WHEN _extract_cross_chunk_relationships is called
        THEN expect:
            - Only entities whose source_chunks intersect with sequence chunk IDs are included
            - Entities not present in sequence chunks are excluded
        """

    async def test_extract_cross_chunk_relationships_unique_id_generation(self):
        """
        GIVEN same entity pair in narrative sequence
        WHEN _extract_cross_chunk_relationships is called multiple times
        THEN expect:
            - Consistent MD5-based IDs are generated for same entity pairs
            - ID generation uses both entity IDs for uniqueness
        """

    async def test_extract_cross_chunk_relationships_source_chunks_collection(self):
        """
        GIVEN entities appearing in multiple chunks within sequence
        WHEN _extract_cross_chunk_relationships is called
        THEN expect:
            - Relationship source_chunks contains all sequence chunk IDs
            - Both entities' source chunks are properly aggregated
        """

    async def test_extract_cross_chunk_relationships_metadata_properties(self):
        """
        GIVEN successful cross-chunk relationship extraction
        WHEN _extract_cross_chunk_relationships is called
        THEN expect:
            - Properties dict includes extraction_method: "narrative_sequence"
            - Properties include sequence information
            - All metadata is properly structured
        """

    async def test_extract_cross_chunk_relationships_all_combinations_created(self):
        """
        GIVEN sequence with 3 different entities (A, B, C)
        WHEN _extract_cross_chunk_relationships is called
        THEN expect:
            - 6 relationships are created: A->B, A->C, B->A, B->C, C->A, C->B
            - All possible entity pair combinations are connected
            - n*(n-1) relationships for n entities in sequence
        """



import unittest
from unittest.mock import Mock

class TestGraphRAGIntegratorInferRelationshipType:
    """Test GraphRAGIntegrator _infer_relationship_type method."""




    def test_infer_relationship_type_person_organization_leads(self):
        """
        GIVEN entity1 with type "person" and entity2 with type "organization"
        AND context containing keywords like "CEO", "director", "president"
        WHEN _infer_relationship_type is called
        THEN expect:
            - Relationship type "leads" is returned
            - Person-organization leadership relationship is inferred
        """

    def test_infer_relationship_type_person_organization_works_for(self):
        """
        GIVEN entity1 with type "person" and entity2 with type "organization"
        AND context containing keywords like "works", "employee", "staff"
        WHEN _infer_relationship_type is called
        THEN expect:
            - Relationship type "works_for" is returned
            - Employment relationship is inferred
        """

    def test_infer_relationship_type_person_organization_founded(self):
        """
        GIVEN entity1 with type "person" and entity2 with type "organization"
        AND context containing keywords like "founded", "established", "created"
        WHEN _infer_relationship_type is called
        THEN expect:
            - Relationship type "founded" is returned
            - Founder relationship is inferred
        """

    def test_infer_relationship_type_organization_organization_acquired(self):
        """
        GIVEN entity1 and entity2 both with type "organization"
        AND context containing keywords like "acquired", "bought", "purchased"
        WHEN _infer_relationship_type is called
        THEN expect:
            - Relationship type "acquired" is returned
            - Acquisition relationship is inferred
        """

    def test_infer_relationship_type_organization_organization_partners(self):
        """
        GIVEN entity1 and entity2 both with type "organization"
        AND context containing keywords like "partners", "partnership", "alliance"
        WHEN _infer_relationship_type is called
        THEN expect:
            - Relationship type "partners_with" is returned
            - Partnership relationship is inferred
        """

    def test_infer_relationship_type_organization_organization_competes(self):
        """
        GIVEN entity1 and entity2 both with type "organization"
        AND context containing keywords like "competes", "rival", "competitor"
        WHEN _infer_relationship_type is called
        THEN expect:
            - Relationship type "competes_with" is returned
            - Competition relationship is inferred
        """

    def test_infer_relationship_type_person_person_collaborates(self):
        """
        GIVEN entity1 and entity2 both with type "person"
        AND context containing keywords like "collaborates", "works together", "team"
        WHEN _infer_relationship_type is called
        THEN expect:
            - Relationship type "collaborates_with" is returned
            - Collaboration relationship is inferred
        """

    def test_infer_relationship_type_person_person_manages(self):
        """
        GIVEN entity1 and entity2 both with type "person"
        AND context containing keywords like "manages", "supervises", "reports to"
        WHEN _infer_relationship_type is called
        THEN expect:
            - Relationship type "manages" is returned
            - Management relationship is inferred
        """

    def test_infer_relationship_type_location_relationship(self):
        """
        GIVEN entity with any type and entity2 with type "location"
        AND context containing keywords like "located", "based", "headquarters"
        WHEN _infer_relationship_type is called
        THEN expect:
            - Relationship type "located_in" is returned
            - Location relationship is inferred
        """

    def test_infer_relationship_type_case_insensitive_matching(self):
        """
        GIVEN context containing keywords in various cases ("CEO", "ceo", "Ceo")
        WHEN _infer_relationship_type is called
        THEN expect:
            - Case-insensitive keyword matching is performed
            - Appropriate relationship type is returned regardless of case
        """

    def test_infer_relationship_type_no_matching_keywords(self):
        """
        GIVEN context with no recognizable relationship keywords
        WHEN _infer_relationship_type is called
        THEN expect:
            - Default relationship type "related_to" is returned
            - Fallback relationship is provided
        """

    def test_infer_relationship_type_empty_context(self):
        """
        GIVEN empty context string
        WHEN _infer_relationship_type is called
        THEN expect:
            - Default relationship type "related_to" is returned
            - Method handles empty context gracefully
        """

    def test_infer_relationship_type_prioritized_keyword_matching(self):
        """
        GIVEN context containing multiple relationship keywords with different specificity
        WHEN _infer_relationship_type is called
        THEN expect:
            - More specific relationships are prioritized over generic ones
            - Most appropriate relationship type is returned
        """


import unittest
from unittest.mock import Mock

class TestGraphRAGIntegratorFindChunkSequences:
    """Test GraphRAGIntegrator _find_chunk_sequences method."""




    def test_find_chunk_sequences_multiple_chunks_same_page(self):
        """
        GIVEN chunks list with multiple chunks having same source_page
        WHEN _find_chunk_sequences is called
        THEN expect:
            - Chunks from same page are grouped into sequence
            - Sequence contains chunk_ids of all chunks from that page
            - Only sequences with 2+ chunks are returned
        """

    def test_find_chunk_sequences_single_chunk_per_page_filtered(self):
        """
        GIVEN chunks list where each chunk has unique source_page
        WHEN _find_chunk_sequences is called
        THEN expect:
            - Single-chunk pages are filtered out
            - Empty sequences list is returned
            - No sequences with only 1 chunk are included
        """

    def test_find_chunk_sequences_mixed_page_sizes(self):
        """
        GIVEN chunks list with some pages having multiple chunks, others single chunks
        WHEN _find_chunk_sequences is called
        THEN expect:
            - Only pages with 2+ chunks are included in sequences
            - Single-chunk pages are excluded
            - Correct number of sequences returned
        """

    def test_find_chunk_sequences_empty_chunks_list(self):
        """
        GIVEN empty chunks list
        WHEN _find_chunk_sequences is called
        THEN expect:
            - Empty sequences list is returned
            - No exceptions are raised
            - Method handles empty input gracefully
        """

    def test_find_chunk_sequences_chunk_id_collection(self):
        """
        GIVEN chunks with specific chunk_id values grouped by source_page
        WHEN _find_chunk_sequences is called
        THEN expect:
            - Returned sequences contain correct chunk_id values
            - All chunk_ids from multi-chunk pages are included
            - chunk_id ordering is preserved within sequences
        """

    def test_find_chunk_sequences_page_grouping_logic(self):
        """
        GIVEN chunks with source_page values: [1, 1, 2, 2, 2, 3]
        WHEN _find_chunk_sequences is called
        THEN expect:
            - Two sequences returned: one for page 1 (2 chunks), one for page 2 (3 chunks)
            - Page 3 excluded (only 1 chunk)
            - Grouping by source_page works correctly
        """

    def test_find_chunk_sequences_chunk_attributes_access(self):
        """
        GIVEN chunks with source_page and chunk_id attributes
        WHEN _find_chunk_sequences is called
        THEN expect:
            - source_page attribute is accessed for grouping
            - chunk_id attribute is accessed for sequence building
            - No attribute errors are raised
        """

    def test_find_chunk_sequences_sequence_order_preservation(self):
        """
        GIVEN chunks in specific order within same page
        WHEN _find_chunk_sequences is called
        THEN expect:
            - Order of chunk_ids within sequence reflects original chunk order
            - Sequence maintains chunk ordering from input list
        """

    def test_find_chunk_sequences_multiple_pages_multiple_sequences(self):
        """
        GIVEN chunks from multiple pages, each page having 2+ chunks
        WHEN _find_chunk_sequences is called
        THEN expect:
            - One sequence per multi-chunk page
            - Each sequence contains chunk_ids from respective page
            - All qualifying pages produce sequences
        """

    def test_find_chunk_sequences_return_type_structure(self):
        """
        GIVEN any valid chunks input
        WHEN _find_chunk_sequences is called
        THEN expect:
            - Return type is List[List[str]]
            - Outer list contains sequences
            - Inner lists contain chunk_id strings
            - Structure matches expected type annotation
        """


class TestGraphRAGIntegratorCreateNetworkXGraph:
    """Test GraphRAGIntegrator _create_networkx_graph method."""




    async def test_create_networkx_graph_entities_as_nodes(self):
        """
        GIVEN KnowledgeGraph with entities having id, name, type, confidence, source_chunks, properties
        WHEN _create_networkx_graph is called
        THEN expect:
            - NetworkX DiGraph is created
            - Entities become nodes with entity.id as node identifier
            - Node attributes include name, type, confidence, source_chunks, and properties
            - All entity attributes are preserved in node data
        """

    async def test_create_networkx_graph_relationships_as_edges(self):
        """
        GIVEN KnowledgeGraph with relationships having source_entity_id, target_entity_id, relationship_type
        WHEN _create_networkx_graph is called
        THEN expect:
            - Relationships become directed edges in graph
            - Edge connects source_entity_id to target_entity_id
            - Edge attributes include relationship_type, confidence, source_chunks, properties
            - All relationship attributes are preserved in edge data
        """

    async def test_create_networkx_graph_empty_knowledge_graph(self):
        """
        GIVEN KnowledgeGraph with empty entities and relationships lists
        WHEN _create_networkx_graph is called
        THEN expect:
            - Empty NetworkX DiGraph is created
            - No nodes or edges in the graph
            - Graph structure is valid but empty
        """

    async def test_create_networkx_graph_entities_only_no_relationships(self):
        """
        GIVEN KnowledgeGraph with entities but no relationships
        WHEN _create_networkx_graph is called
        THEN expect:
            - DiGraph contains nodes for all entities
            - No edges in the graph
            - Isolated nodes with entity attributes are created
        """

    async def test_create_networkx_graph_relationships_only_no_entities(self):
        """
        GIVEN KnowledgeGraph with relationships but no entities
        WHEN _create_networkx_graph is called
        THEN expect:
            - DiGraph contains edges for all relationships
            - Nodes are automatically created for referenced entity IDs
            - Node attributes are minimal (just the entity ID)
        """

    async def test_create_networkx_graph_directed_graph_type(self):
        """
        GIVEN any KnowledgeGraph
        WHEN _create_networkx_graph is called
        THEN expect:
            - Returned graph is instance of nx.DiGraph
            - Graph supports directed edges
            - Graph type matches expected directed graph structure
        """

    async def test_create_networkx_graph_node_attribute_preservation(self):
        """
        GIVEN entities with complex properties including nested dicts and lists
        WHEN _create_networkx_graph is called
        THEN expect:
            - All entity properties are preserved as node attributes
            - Complex data structures are maintained in node data
            - No data loss during graph conversion
        """

    async def test_create_networkx_graph_edge_attribute_preservation(self):
        """
        GIVEN relationships with complex properties including nested dicts and lists
        WHEN _create_networkx_graph is called
        THEN expect:
            - All relationship properties are preserved as edge attributes
            - Complex data structures are maintained in edge data
            - No data loss during graph conversion
        """

    async def test_create_networkx_graph_self_loop_handling(self):
        """
        GIVEN relationships where source_entity_id equals target_entity_id
        WHEN _create_networkx_graph is called
        THEN expect:
            - Self-loops are created in the graph
            - Self-referential edges are handled correctly
            - No errors during self-loop creation
        """

    async def test_create_networkx_graph_multiple_edges_same_nodes(self):
        """
        GIVEN multiple relationships between same entity pair with different types
        WHEN _create_networkx_graph is called
        THEN expect:
            - Multiple edges are handled appropriately
            - NetworkX MultiDiGraph behavior or edge merging occurs
            - All relationship data is preserved
        """



import unittest
from unittest.mock import Mock, AsyncMock, patch
import networkx as nx

class TestGraphRAGIntegratorMergeIntoGlobalGraph:
    """Test GraphRAGIntegrator _merge_into_global_graph method."""




    async def test_merge_into_global_graph_new_entities_added(self):
        """
        GIVEN KnowledgeGraph with entities not in global_entities
        AND empty global_entities dict
        WHEN _merge_into_global_graph is called
        THEN expect:
            - All entities from KnowledgeGraph are added to global_entities
            - Entity IDs are used as keys in global_entities dict
            - Entity objects are stored as values
        """

    async def test_merge_into_global_graph_existing_entities_merged(self):
        """
        GIVEN KnowledgeGraph with entities that already exist in global_entities
        WHEN _merge_into_global_graph is called
        THEN expect:
            - Existing entities have their source_chunks extended
            - Confidence scores are updated to maximum value
            - No duplicate entities are created
            - Source chunks are deduplicated
        """

    async def test_merge_into_global_graph_confidence_maximization(self):
        """
        GIVEN existing entity in global_entities with confidence 0.7
        AND new entity in KnowledgeGraph with confidence 0.9
        WHEN _merge_into_global_graph is called
        THEN expect:
            - Entity confidence is updated to 0.9 (maximum)
            - Higher confidence score is preserved
        """

    async def test_merge_into_global_graph_source_chunks_deduplication(self):
        """
        GIVEN existing entity with source_chunks ["chunk1", "chunk2"]
        AND new entity with source_chunks ["chunk2", "chunk3"]
        WHEN _merge_into_global_graph is called
        THEN expect:
            - Combined source_chunks is ["chunk1", "chunk2", "chunk3"]
            - Duplicate chunks are removed
            - All unique chunks are preserved
        """

    async def test_merge_into_global_graph_networkx_composition(self):
        """
        GIVEN global_graph as existing NetworkX DiGraph
        AND KnowledgeGraph with entities and relationships
        WHEN _merge_into_global_graph is called
        THEN expect:
            - Document NetworkX graph is created from KnowledgeGraph
            - Document graph is composed with global_graph
            - global_graph contains nodes and edges from both graphs
        """

    async def test_merge_into_global_graph_document_graphs_storage(self):
        """
        GIVEN KnowledgeGraph with graph_id "doc123"
        WHEN _merge_into_global_graph is called
        THEN expect:
            - Document NetworkX graph is stored in document_graphs["doc123"]
            - Document-specific graph is preserved separately
            - Both global and document graphs are maintained
        """

    async def test_merge_into_global_graph_empty_knowledge_graph(self):
        """
        GIVEN KnowledgeGraph with empty entities and relationships
        WHEN _merge_into_global_graph is called
        THEN expect:
            - No changes to global_entities
            - Empty document graph is created and stored
            - global_graph composition handles empty graph gracefully
        """

    async def test_merge_into_global_graph_networkx_create_called(self):
        """
        GIVEN any KnowledgeGraph
        WHEN _merge_into_global_graph is called
        THEN expect:
            - _create_networkx_graph is called with the KnowledgeGraph
            - NetworkX graph creation is delegated to helper method
        """

    async def test_merge_into_global_graph_compose_preserves_attributes(self):
        """
        GIVEN global_graph with nodes having attributes
        AND document graph with nodes having different attributes
        WHEN _merge_into_global_graph is called
        THEN expect:
            - Node attributes from both graphs are preserved
            - NetworkX compose operation maintains all metadata
            - No attribute loss during graph composition
        """

    async def test_merge_into_global_graph_async_execution(self):
        """
        GIVEN valid KnowledgeGraph
        WHEN _merge_into_global_graph is called as async method
        THEN expect:
            - Method executes asynchronously
            - All operations complete successfully
            - Async context is properly handled
        """


class TestGraphRAGIntegratorDiscoverCrossDocumentRelationships:
    """Test GraphRAGIntegrator _discover_cross_document_relationships method."""




    async def test_discover_cross_document_relationships_empty_global_entities(self):
        """
        GIVEN empty global_entities dict
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - Method returns early without processing
            - No cross-document relationships are created
            - cross_document_relationships list remains unchanged
        """

    async def test_discover_cross_document_relationships_exact_name_matches(self):
        """
        GIVEN entities with identical names in global_entities from different documents
        AND _find_similar_entities returns entities with same names
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - CrossDocumentRelationship is created with type "same_entity"
            - Confidence is set to 0.8 for exact matches
            - Evidence chunks include source_chunks from both entities
        """

    async def test_discover_cross_document_relationships_similar_entities(self):
        """
        GIVEN entities with similar but not identical names from different documents
        AND _find_similar_entities returns similar entities
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - CrossDocumentRelationship is created with type "similar_entity"
            - Confidence is set to 0.6 for similar matches
            - Evidence chunks include source_chunks from both entities
        """

    async def test_discover_cross_document_relationships_same_document_filtering(self):
        """
        GIVEN similar entities that share source_chunks (same document)
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - No cross-document relationship is created for same-document entities
            - Only cross-document relationships are established
            - Same-document entity pairs are filtered out
        """

    async def test_discover_cross_document_relationships_unique_id_generation(self):
        """
        GIVEN entities that qualify for cross-document relationships
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - Unique relationship IDs are generated using entity IDs
            - IDs follow consistent format for cross-document relationships
            - No duplicate relationship IDs are created
        """

    async def test_discover_cross_document_relationships_evidence_chunks_aggregation(self):
        """
        GIVEN entities with multiple source_chunks each
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - Evidence chunks combine source_chunks from both entities
            - All relevant chunks are included as evidence
            - Evidence supports cross-document relationship discovery
        """

    async def test_discover_cross_document_relationships_document_id_extraction(self):
        """
        GIVEN entities with source_chunks containing document identifiers
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - Source and target document IDs are extracted from source_chunks
            - Document IDs are properly identified and set in relationships
            - Cross-document validation uses document ID information
        """

    async def test_discover_cross_document_relationships_no_similar_entities(self):
        """
        GIVEN entities with no similar counterparts in other documents
        AND _find_similar_entities returns empty lists
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - No cross-document relationships are created
            - Method completes successfully without relationships
        """

    async def test_discover_cross_document_relationships_logging_count(self):
        """
        GIVEN successful discovery of cross-document relationships
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - Number of discovered relationships is logged
            - Log message indicates successful relationship discovery
        """

    async def test_discover_cross_document_relationships_extends_list(self):
        """
        GIVEN existing cross_document_relationships list
        AND new relationships discovered
        WHEN _discover_cross_document_relationships is called
        THEN expect:
            - New relationships are appended to existing list
            - cross_document_relationships list is extended, not replaced
            - All relationships are preserved
        """


class TestGraphRAGIntegratorFindSimilarEntities:
    """Test GraphRAGIntegrator _find_similar_entities method."""




    async def test_find_similar_entities_same_type_matching(self):
        """
        GIVEN entity with type "person" and name "John Smith"
        AND global_entities containing other "person" type entities
        WHEN _find_similar_entities is called
        THEN expect:
            - Only entities with same type "person" are considered
            - Entities with different types are excluded from results
            - Type matching is performed before name similarity
        """

    async def test_find_similar_entities_similarity_threshold_filtering(self):
        """
        GIVEN entity with name "Apple Inc"
        AND global_entities with entities having various name similarities
        AND similarity_threshold set to 0.8
        WHEN _find_similar_entities is called
        THEN expect:
            - Only entities with name similarity >= 0.8 are returned
            - _calculate_text_similarity is called for name comparison
            - Entities below threshold are filtered out
        """

    async def test_find_similar_entities_excludes_self(self):
        """
        GIVEN entity with ID "entity123"
        AND global_entities containing entity with same ID
        WHEN _find_similar_entities is called
        THEN expect:
            - Entity with same ID is excluded from results
            - Self-matching is prevented
            - Only different entities are returned
        """

    async def test_find_similar_entities_empty_global_entities(self):
        """
        GIVEN empty global_entities dict
        WHEN _find_similar_entities is called
        THEN expect:
            - Empty list is returned
            - No exceptions are raised
            - Method handles empty global state gracefully
        """

    async def test_find_similar_entities_no_type_matches(self):
        """
        GIVEN entity with type "person"
        AND global_entities containing only "organization" type entities
        WHEN _find_similar_entities is called
        THEN expect:
            - Empty list is returned
            - No entities match the type filter
            - Type-based filtering works correctly
        """

    async def test_find_similar_entities_no_similarity_above_threshold(self):
        """
        GIVEN entity with name significantly different from all global entities
        AND all similarity scores below threshold
        WHEN _find_similar_entities is called
        THEN expect:
            - Empty list is returned
            - Threshold filtering works correctly
            - Low-similarity entities are excluded
        """

    async def test_find_similar_entities_multiple_matches_returned(self):
        """
        GIVEN entity that matches multiple entities in global_entities
        AND multiple entities exceed similarity threshold
        WHEN _find_similar_entities is called
        THEN expect:
            - All qualifying entities are returned in list
            - Multiple matches are handled correctly
            - All similar entities above threshold are included
        """

    async def test_find_similar_entities_text_similarity_calculation(self):
        """
        GIVEN entity with specific name
        AND global_entities with entities to compare
        WHEN _find_similar_entities is called
        THEN expect:
            - _calculate_text_similarity is called for each same-type entity
            - Text similarity comparison is performed correctly
            - Name-based matching uses text similarity method
        """

    async def test_find_similar_entities_case_sensitivity_handling(self):
        """
        GIVEN entity with name "APPLE INC"
        AND global_entities containing "Apple Inc"
        WHEN _find_similar_entities is called
        THEN expect:
            - Case differences are handled appropriately
            - Text similarity calculation accounts for case variations
            - Similar entities are found regardless of case
        """

    async def test_find_similar_entities_exact_name_match_high_similarity(self):
        """
        GIVEN entity with exact name match in global_entities
        WHEN _find_similar_entities is called
        THEN expect:
            - Exact match has similarity score of 1.0
            - Exact match exceeds any reasonable threshold
            - Identical names are properly identified as similar
        """


import unittest
from unittest.mock import Mock

class TestGraphRAGIntegratorCalculateTextSimilarity:
    """Test GraphRAGIntegrator _calculate_text_similarity method."""




    def test_calculate_text_similarity_identical_texts(self):
        """
        GIVEN two identical text strings "hello world"
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score of 1.0 is returned
            - Identical texts have perfect similarity
        """

    def test_calculate_text_similarity_completely_different_texts(self):
        """
        GIVEN two texts with no common words: "hello world" and "foo bar"
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score of 0.0 is returned
            - No intersection between word sets
        """

    def test_calculate_text_similarity_partial_overlap(self):
        """
        GIVEN texts "hello world" and "hello universe"
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score of 1/3 (0.333...) is returned
            - One common word ("hello") out of three unique words total
            - Jaccard coefficient calculation: |intersection| / |union|
        """

    def test_calculate_text_similarity_case_insensitive(self):
        """
        GIVEN texts "Hello World" and "hello world"
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score of 1.0 is returned
            - Case differences are normalized
            - Case-insensitive comparison is performed
        """

    def test_calculate_text_similarity_empty_strings(self):
        """
        GIVEN two empty strings ""
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score of 1.0 is returned (or handled gracefully)
            - Empty strings are considered identical
            - No division by zero errors
        """

    def test_calculate_text_similarity_one_empty_string(self):
        """
        GIVEN one empty string "" and one non-empty string "hello"
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score of 0.0 is returned
            - Empty string has no intersection with non-empty string
        """

    def test_calculate_text_similarity_whitespace_handling(self):
        """
        GIVEN texts with different whitespace: "hello  world" and "hello world"
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score of 1.0 is returned
            - Whitespace normalization through split() handles multiple spaces
        """

    def test_calculate_text_similarity_word_order_irrelevant(self):
        """
        GIVEN texts "hello world" and "world hello"
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score of 1.0 is returned
            - Word order doesn't affect set-based similarity
            - Same words in different order are identical sets
        """

    def test_calculate_text_similarity_punctuation_as_part_of_words(self):
        """
        GIVEN texts "hello, world!" and "hello world"
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score less than 1.0 is returned
            - Punctuation is treated as part of words
            - "hello," is different from "hello"
        """

    def test_calculate_text_similarity_jaccard_coefficient_formula(self):
        """
        GIVEN texts "apple banana cherry" and "banana cherry date"
        WHEN _calculate_text_similarity is called
        THEN expect:
            - Similarity score of 2/4 (0.5) is returned
            - Intersection: {"banana", "cherry"} = 2 words
            - Union: {"apple", "banana", "cherry", "date"} = 4 words
            - Jaccard coefficient: 2/4 = 0.5
        """


class TestGraphRAGIntegratorStoreKnowledgeGraphIpld:
    """Test GraphRAGIntegrator _store_knowledge_graph_ipld method."""




    async def test_store_knowledge_graph_ipld_successful_storage(self):
        """
        GIVEN valid KnowledgeGraph with entities, relationships, and metadata
        AND storage.store_data returns a valid CID string
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - KnowledgeGraph is serialized to JSON-compatible format
            - storage.store_data is called with serialized data
            - Valid CID string is returned
        """

    async def test_store_knowledge_graph_ipld_numpy_array_conversion(self):
        """
        GIVEN KnowledgeGraph with entities containing numpy array embeddings
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - Numpy arrays are converted to lists for JSON serialization
            - Entity embeddings are properly handled
            - No serialization errors occur
        """

    async def test_store_knowledge_graph_ipld_storage_exception(self):
        """
        GIVEN valid KnowledgeGraph
        AND storage.store_data raises an exception
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - Exception is caught and logged
            - Empty string is returned instead of propagating exception
            - Error handling prevents method failure
        """

    async def test_store_knowledge_graph_ipld_serialization_structure(self):
        """
        GIVEN KnowledgeGraph with all attributes populated
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - All KnowledgeGraph attributes are included in serialization
            - Entities, relationships, chunks, metadata are preserved
            - JSON-compatible format is created
        """

    async def test_store_knowledge_graph_ipld_empty_knowledge_graph(self):
        """
        GIVEN KnowledgeGraph with empty entities and relationships
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - Empty graph is serialized successfully
            - storage.store_data is called with empty collections
            - Valid CID or empty string is returned
        """

    async def test_store_knowledge_graph_ipld_complex_metadata_handling(self):
        """
        GIVEN KnowledgeGraph with complex metadata including nested objects
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - Complex metadata structures are serialized correctly
            - Nested dictionaries and lists are preserved
            - No serialization errors for complex data types
        """

    async def test_store_knowledge_graph_ipld_entity_properties_serialization(self):
        """
        GIVEN entities with complex properties including various data types
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - All entity properties are serialized correctly
            - Property data types are handled appropriately
            - No data loss during serialization
        """

    async def test_store_knowledge_graph_ipld_relationship_properties_serialization(self):
        """
        GIVEN relationships with complex properties including various data types
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - All relationship properties are serialized correctly
            - Property data types are handled appropriately
            - No data loss during serialization
        """

    async def test_store_knowledge_graph_ipld_logging_error_on_exception(self):
        """
        GIVEN storage operation that raises an exception
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - Exception is logged with appropriate error message
            - Logging includes context about storage failure
            - Error details are captured in logs
        """

    async def test_store_knowledge_graph_ipld_returns_empty_string_on_failure(self):
        """
        GIVEN any exception during storage process
        WHEN _store_knowledge_graph_ipld is called
        THEN expect:
            - Empty string is returned as failure indicator
            - Method doesn't raise exceptions to caller
            - Graceful failure handling
        """

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
