import pytest

# These tests exercise the full GraphRAG stack and require heavy optional deps.
pytest.importorskip("tiktoken")
pytest.importorskip("networkx")
pytest.importorskip("numpy")
pytest.importorskip("faker")

# This checks if the imports of the module we're testing are accessible:
import logging
import hashlib
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import uuid
import re
from tiktoken import get_encoding

import networkx as nx
import numpy as np

from ipfs_datasets_py.ipld import IPLDStorage

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk, LLMChunkMetadata

from enum import StrEnum
import anyio
import os
import random
from typing import Callable, Optional
from unittest.mock import MagicMock, AsyncMock, Mock


import faker
from faker.providers import DynamicProvider

from ipfs_datasets_py.pdf_processing.graphrag_integrator import (
    GraphRAGIntegrator,
    Entity,
    KnowledgeGraph,
    Relationship,
)

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as MetadataFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk.llm_chunk_factory import (
    LLMChunkTestDataFactory as ChunkFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_document.llm_document_factory import (
    LLMDocumentTestDataFactory as DocumentFactory
)

# Common file path setup
home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."


# Check if each classes methods are accessible and callable:
assert callable(GraphRAGIntegrator.integrate_document)
assert callable(GraphRAGIntegrator._extract_entities_from_chunks)
assert callable(GraphRAGIntegrator._extract_entities_from_text)
assert callable(GraphRAGIntegrator._extract_relationships)
assert callable(GraphRAGIntegrator._extract_chunk_relationships)
assert callable(GraphRAGIntegrator._infer_relationship_type)
assert callable(GraphRAGIntegrator._extract_cross_chunk_relationships)
assert callable(GraphRAGIntegrator._find_chunk_sequences)
assert callable(GraphRAGIntegrator._create_networkx_graph)
assert callable(GraphRAGIntegrator._merge_into_global_graph)
assert callable(GraphRAGIntegrator._discover_cross_document_relationships)
assert callable(GraphRAGIntegrator._find_similar_entities)
assert callable(GraphRAGIntegrator._calculate_text_similarity)
assert callable(GraphRAGIntegrator._store_knowledge_graph_ipld)
assert callable(GraphRAGIntegrator.query_graph)
assert callable(GraphRAGIntegrator.get_entity_neighborhood)

### CONSTANTS AND ENUMS ###

SEED = 420
random.seed(SEED)

class ValidEntities(StrEnum):
    """
    Valid entity types for testing.
    NOTE: More may be added in the future as the need arises.
    """
    PERSON = "person" # Ex: "John Madden, Jane Smith"
    ORGANIZATION = "organization" # Ex: "Google, United Nations"
    LOCATION = "location" # Ex: "New York, Paris"
    DATE = "date" # Ex: "January 1, 2020, 2020-01-01"
    EVENT = "event" # Ex: "WWII, The Olympics"
    OBJECT = "object" # Ex: "Eiffel Tower, Statue of Liberty"
    CONCEPT = "concept" # Ex: "Quantum Mechanics, Relativity, The Renaissance"

class ValidRelationships(StrEnum):
    """
    Valid relationship types for testing.
    NOTE: More may be added in the future as the need arises.
    """
    WORKS_FOR = "works_for" # Ex: "John works for Google"
    LOCATED_IN = "located_in" # Ex: "Google is located in Mountain View"
    BORN_IN = "born_in" # Ex: "John was born in New York"
    FOUNDED = "founded" # Ex: "Google was founded by Larry Page"
    PART_OF = "part_of" # Ex: "The Eiffel Tower is part of Paris"
    RELATED_TO = "related_to" # Ex: "Quantum Mechanics is related to Relativity"
    COLLABORATES_WITH = "collaborates_with" # Ex: "John collaborates with Jane"

ENTITIES_PER_TEXT: int = 3

# GraphRAG integrator non-callable parameters
SIMILARITY_THRESHOLD: float = 0.8
ENTITY_CONFIDENCE_EXTRACTION_THRESHOLD: float = 0.6

# For Faker, so we don't get non-English names
DEFAULT_LOCALES: list[str] = ['en_US']

TECH_JOB_SET = {
    "Software Engineer",
    "Data Scientist",
    "Data Analyst",
    "Product Manager",
    "DevOps Engineer",
    "Site Reliability Engineer",
    "Machine Learning Engineer",
    "AI Engineer",
    "Cloud Engineer",
    "Cybersecurity Analyst",
    "Network Engineer",
    "Systems Administrator",
    "Database Administrator",
    "Full-Stack Developer",
    "Front-End Developer",
    "Back-End Developer",
    "Mobile Developer",
    "QA Engineer",
    "Software Tester",
    "UI/UX Designer",
    "Solutions Architect",
    "Technical Writer",
    "Scrum Master",
    "IT Support Specialist",
    "Business Analyst",
    "Security Engineer",
    "Blockchain Developer",
    "Game Developer",
    "Embedded Systems Engineer",
    "Firmware Engineer",
    "Hardware Engineer",
    "Research Scientist",
    "Quantitative Analyst",
    "Robotics Engineer",
    "Computer Vision Engineer",
    "Natural Language Processing Engineer",
    "Data Engineer",
    "Platform Engineer",
    "Release Engineer",
    "Technical Program Manager",
    "Sales Engineer",
    "Developer Advocate",
}

BUSINESS_WORDS = {
    "Report", "Analysis", "Summary", "Findings", "Overview", "Insights",
    "Data", "Trends", "Metrics", "Performance", "Evaluation", "Assessment",
    "Review", "Survey", "Study", "Research", "Statistics", "Figures",
    "Results", "Conclusions", "Recommendations", "Forecast", "Projections",
    "Highlights", "Key Points", "Takeaways", "Implications", "Opportunities",
    "Challenges", "Risks", "Benefits", "Costs", "Budget", "Resources",
    "Timeline", "Milestones", "Objectives", "Goals", "Strategies", "Tactics",
    "Action Plan", "Implementation", "Execution", "Monitoring", "Reporting",
    "Evaluation", "Feedback", "Improvement", "Optimization", "Innovation",
    "Technology", "Digital", "Transformation", "Change", "Leadership",
    "Management", "Operations", "Logistics", "Supply Chain", "Marketing",
    "Sales", "Customer", "Client", "Stakeholder", "Partnership", "Collaboration",
    "Team", "Workforce", "Talent", "Skills", "Training", "Development",
    "Culture", "Diversity", "Inclusion", "Sustainability", "Environment",
    "Social", "Governance", "Ethics", "Compliance", "Regulation", "Policy",
    "Legislation", "Standards", "Best Practices", "Benchmarking", "Case Studies",
    "Examples", "Use Cases", "Applications", "Solutions", "Platforms", "Systems",
    "Infrastructure", "Architecture", "Design", "Engineering",
}

BUSINESS_WORDS_PROVIDER = DynamicProvider(
    provider_name="business_words",
    elements=list(BUSINESS_WORDS)
)

TECH_JOBS_PROVIDER = DynamicProvider(
    provider_name="tech_jobs",
    elements=list(TECH_JOB_SET)
)

US_STATE_ABBREVIATIONS = {
    "AL", "AK", "AR", "GA", "IN", "KS", "OK", "TN", "AZ", "CA", "AS", "DE",
    "FL", "CO", "CT", "DC", "IL", "ID", "HI", "KY", "LA", "MD", "ME", "MA",
    "IA", "MN", "MI", "MS", "MO", "NE", "MT", "NV", "NJ", "NH", "NY", "NC",
    "ND", "NM", "OH", "PA", "SC", "PR", "MP", "TX", "SD", "OR", "RI", "UT",
    "VA", "WA", "WI", "WV", "WY", "VT", "VI"
}

US_STATES_PROVIDER = DynamicProvider(
    provider_name="us_states",
    elements=list(US_STATE_ABBREVIATIONS)
)

### HELPER CLASSES AND FUNCTIONS ###

def _tokenize_with_tiktoken(text: str, encoding: str = "cl100k_base") -> List[int]:
    """Tokenizes text using tiktoken's cl100k_base encoding."""
    encoding = get_encoding(encoding)
    return encoding.encode(text)


def count_tokens(text: str, encoding: str = "cl100k_base") -> int:
    """Count the number of tokens in a given text using tiktoken's cl100k_base encoding."""
    tokens = _tokenize_with_tiktoken(text, encoding)
    return len(tokens)

class _GraphRAGIntegratorFixtureFactory:
    """
    Factory class to programmatically create test data for GraphRAGIntegrator fixtures.
    
    This allows us to dynamically generate entities, chunks, and documents
    with realistic but random data for more robust testing.
    Also reduces LLM cheating.
    """

    def __init__(self, 
                 locales: Optional[list[str]] = DEFAULT_LOCALES,
                 entity_extraction_confidence: float = ENTITY_CONFIDENCE_EXTRACTION_THRESHOLD,
                 tech_jobs_provider: DynamicProvider = TECH_JOBS_PROVIDER,
                 us_states_provider: DynamicProvider = US_STATES_PROVIDER, 
                 business_words: DynamicProvider = BUSINESS_WORDS_PROVIDER,
                 ):

        self.fake = faker.Faker(locales)
        faker.Faker.seed(SEED)
        for provider in [tech_jobs_provider, us_states_provider, business_words]:
            self.fake.add_provider(provider)

        self.entity_extraction_confidence: float = entity_extraction_confidence

        # Start at 1
        self.entity_counter = 1
        self.chunk_counter = 1

    def _get_dict_values(self, type_: str) -> tuple[str, str, str]:
        """ Get realistic name, description, and chunk_id based on entity type."""
        match type_:
            case "person":
                return self.fake.name(), self.fake.tech_jobs(), "person_chunk"
            case "organization":
                return self.fake.company(), "Technology Company", "organization_chunk"
            case "location":
                return f"{self.fake.city()}, {self.fake.us_states()}", "City", "location_chunk"
            case "date":
                faker_date_patterns = {
                    '%m/%d/%Y', '%B %d, %Y', '%Y-%m-%d', '%d %b %Y', '%A, %B %d, %Y',
                }  
                pattern = random.choice(faker_date_patterns)
                return self.fake.date(pattern=pattern), "Calendar Date", "date_chunk"
            case _:
                # NOTE Should never happen due to prior validation, but just in case.
                raise ValueError(f"Unknown entity type: {type_}")

    def make_entity(self, type_: str, name: str, description: str, chunk_id: int ) -> Entity:
        entity_dict = {
            "id": f"entity_{self.entity_counter}",
            "name":  name,
            "type": type_,
            "description": description,
            "confidence": np.random.uniform(self.entity_extraction_confidence, 1.0),
            "source_chunks": [f"chunk_{self.chunk_counter}"],
            "properties": {"source_chunk": {"chunk_id": chunk_id}},
        }
        return Entity(**entity_dict)


    def make_entity_list(self, type_list: list[str]) -> list[Entity]:

        if not isinstance(type_list, list):
            raise TypeError(f"Expected type_list to be type list, got {type(type_list).__name__}")

        output = []
        for type_ in type_list:
            name, description, chunk_id = self._get_dict_values(type_)
            entity = self.make_entity(type_, name, description, chunk_id)
            output.append(entity)
            self.entity_counter += 1
        self.chunk_counter += 1
        return output

    def make_llm_chunk_metadata(self) -> LLMChunkMetadata:
        """
        Create sample metadata for LLMChunk objects.
        
        Note that this data is arbitrary and is not tied to any specific chunk or its content.
        """
        return LLMChunkMetadata(**MetadataFactory.create_valid_baseline_data())

    def make_llm_chunk(self, sentences: list[str]) -> LLMChunk:
        assert isinstance(sentences, list), f"Expected sentences to be list, got {type(sentences).__name__} instead."
        for idx, elem in enumerate(sentences):
            assert isinstance(elem, str), f"Expected each sentence {idx} in list to be str, got {type(elem).__name__} instead."

        paragraph = ' '.join(sentences)
        arbitrary_page_number = 1
        return LLMChunk(
            chunk_id=f"chunk_{self.chunk_counter}",
            content=paragraph,
            source_page=arbitrary_page_number,
            source_elements=["paragraph"],
            token_count=count_tokens(paragraph),
            semantic_types="text",
            relationships=[],
            metadata=self.make_llm_chunk_metadata(),
            embedding=None
        )

    def make_relationship(self, 
                          entities: list[Entity], 
                          *, 
                          relationship_type: str, 
                          ) -> Relationship:
        """
        Create a Relationship between two entities.
        """
        assert isinstance(entities, list), f"Expected entities to be list, got {type(entities).__name__} instead."
        for entity in entities:
            assert isinstance(entity, Entity), f"Expected each entity in list to be Entity, got {type(entity).__name__} instead."
        assert isinstance(relationship_type, str), f"Expected relationship_type to be str, got {type(relationship_type).__name__} instead."
        assert relationship_type in ValidRelationships.__members__.values(), f"Invalid relationship_type: {relationship_type}. Must be one of {list(ValidRelationships)}."
        assert len(entities) == 2, f"Expected exactly two entities, got {len(entities)} instead."

        entity1 = entities[0]
        entity2 = entities[1]
        description = f"{entity1.name} {relationship_type.replace("_", " ")} {entity2.name}"

        relationship = Relationship(
            id=f"rel_{self.entity_counter}",
            source_entity_id=entity1.id,
            target_entity_id=entity2.id,
            relationship_type=relationship_type,
            description=description,
            confidence=np.random.uniform(self.entity_extraction_confidence, 1.0),
            source_chunks=[f"chunk_{self.chunk_counter}"],
            properties={}
        )
        return relationship

    def make_llm_document(
            self, 
            entity_list: list[Entity], 
            chunks: list[LLMChunk],
        ) -> LLMDocument:
        key_entities = []
        assert isinstance(entity_list, list), f"Expected entity_list to be list, got {type(entity_list).__name__} instead."
        assert isinstance(chunks, list), f"Expected chunks to be list, got {type(chunks).__name__} instead."
        for idx, chunk in enumerate(chunks):
            assert isinstance(chunk, LLMChunk), f"Expected each chunk {idx} in list to be LLMChunk, got {type(chunk).__name__} instead."
        for idx, entity in enumerate(entity_list):
            assert isinstance(entity, Entity), f"Expected entity {idx} in list to be Entity, got {type(entity).__name__} instead."
            entity_dict = {"text": entity.name, "type": entity.type, "confidence": entity.confidence}
            key_entities.append(entity_dict)

        random_job = self.fake.tech_jobs()
        random_business_word = self.fake.business_words()
        title = random_job + " " + random_business_word
        bs = self.fake.bs()

        arbitrary_random_int = random.randint(1000, 9999)
        document_id = title.replace(" ", "_").lower() + f"_{arbitrary_random_int}"
        summary = f"{random_business_word.capitalize()} on {random_job.lower()}s to help them {bs}."
        created_at = self.fake.iso8601()

        return LLMDocument(
            document_id=document_id,
            title=title,
            chunks=chunks,
            summary=summary,
            key_entities=key_entities,
            processing_metadata={
                "created_at": created_at,
            }
        )

    def make_sentence_fragment(
        self,
        entities: list[Entity],
        conjunction: str = " and ",
        final_clause: str = " and {final_entity}."
    ) -> str:
        """Joins entity names into a sentence fragment."""
        assert isinstance(entities, list), f"Expected entities to be list, got {type(entities).__name__} instead."
        assert isinstance(conjunction, str), f"Expected conjunction to be str, got {type(conjunction).__name__} instead."
        assert isinstance(final_clause, str), f"Expected final_clause to be str, got {type(final_clause).__name__} instead."
        assert len(entities) == 3, f"Expected exactly three entities, got {len(entities)} instead."

        # Remove the final entity.
        # NOTE We modify the original list to prevent duplication of entities in the final sentence.
        final_clause = final_clause.format(final_entity=entities.pop().name)

        output_string = f"{conjunction.join([e.name for e in entities])}" + final_clause

        return output_string.strip(conjunction).strip()


def _get_entity_chunk_id(entity_list):
    # Evaluate entity_list fixture to get access to its value.
    @pytest.fixture
    def chunk_id_fixture(entity_list) -> str:
        entity = entity_list[0]
        return entity['properties']['source_chunk']['chunk_id']
    return chunk_id_fixture


def _create_entity_fixture(entity_type: str):
    @pytest.fixture
    def entity_fixture(num_entities, fixture_factory) -> list[Entity]:
        return fixture_factory.make_entity_list([entity_type for _ in range(num_entities)])
    return entity_fixture


### FIXTURES ###

@pytest.fixture()
def fixture_factory() -> _GraphRAGIntegratorFixtureFactory:
    """A test-scoped fixture factory instance for generating test data."""
    return _GraphRAGIntegratorFixtureFactory()


@pytest.fixture
def similarity_threshold() -> float:
    return SIMILARITY_THRESHOLD


@pytest.fixture
def entity_extraction_confidence() -> float:
    return ENTITY_CONFIDENCE_EXTRACTION_THRESHOLD


@pytest.fixture
def num_entities() -> int:
    return ENTITIES_PER_TEXT


@pytest.fixture
def mock_ipld_storage():
    return AsyncMock(spec=IPLDStorage)


@pytest.fixture
def mock_logger():
    return MagicMock(spec_set=logging.Logger)


@pytest.fixture
def integrator(
    mock_ipld_storage, mock_logger, similarity_threshold, entity_extraction_confidence
    ) -> GraphRAGIntegrator:
    """Create a GraphRAGIntegrator instance for testing."""
    return GraphRAGIntegrator(
        similarity_threshold=similarity_threshold,
        entity_extraction_confidence=entity_extraction_confidence,
        logger=mock_logger,
        storage=mock_ipld_storage
    )


def real_integrator():
    """Create a GraphRAGIntegrator instance with default parameters for testing."""
    return GraphRAGIntegrator()





# Dynamically create fixtures
only_location_entities = _create_entity_fixture("location")
only_person_entities = _create_entity_fixture("person")
only_date_entities = _create_entity_fixture("date")
only_organization_entities = _create_entity_fixture("organization")

try:
    person_entity_chunk_id = _get_entity_chunk_id(only_person_entities)
    location_entity_chunk_id = _get_entity_chunk_id(only_location_entities)
    date_entity_chunk_id = _get_entity_chunk_id(only_date_entities)
    organization_entity_chunk_id = _get_entity_chunk_id(only_organization_entities)
except Exception as e:
    raise RuntimeError(f"Error creating chunk_id fixtures: {e}") from e

@pytest.fixture
def person_entity_text(only_person_entities, fixture_factory) -> str:
    """An entity text containing only people

    Example output:
    >>> "John Madden and Mathew Mercer met with John Cena for lunch yesterday."
    """
    final_clause = "met with {final_entity} for lunch yesterday."
    return fixture_factory.make_sentence_fragment(only_person_entities, final_clause=final_clause)


@pytest.fixture
def location_entity_text(only_location_entities, fixture_factory) -> str:
    """An entity text containing only locations
    
    Example output:
    >>> "Our offices in San Francisco, CA and New York, NY are closed. Please try the one in Miami, FL instead."
    """
    final_clause = " are closed. Please try the one in {final_entity} instead."
    sentence_fragment = fixture_factory.make_sentence_fragment(
        only_location_entities, final_clause=final_clause
    )
    return "Our offices in " + sentence_fragment

@pytest.fixture
def date_entity_text(only_date_entities, fixture_factory) -> str:
    """An entity text containing only dates
    
    Example output:
    >>> "The event was originally scheduled for January 1, 2020 and February 15, 2020 but was postponed to March 10, 2020."
    """
    final_clause = "but was postponed to {final_entity}."
    sentence_fragment = fixture_factory.make_sentence_fragment(
        only_date_entities, final_clause=final_clause
    )
    return "The event was originally scheduled for " + sentence_fragment


@pytest.fixture
def sample_entities(fixture_factory) -> list[Entity]:
    """Create sample Entity classes for testing."""
    type_list = ["person", "organization", "person"]
    return fixture_factory.make_entity_list(type_list)


@pytest.fixture
def sample_relationships(
    sample_entities, 
    fixture_factory: _GraphRAGIntegratorFixtureFactory
    ) -> list[Relationship]:
    """Create a dynamic list of sample relationships for testing."""
    entities = sample_entities

    assert len(entities) == 3, f"Expected exactly three entities, got {len(entities)} instead."

    entity_list_1 = [entities[0], entities[1]]
    entity_list_2 = [entities[0], entities[2]]

    relationships = [
        fixture_factory.make_relationship(entity_list_1, relationship_type="works_for"),
        fixture_factory.make_relationship(entity_list_2, relationship_type="collaborates_with"),
    ]
    return relationships


@pytest.fixture
def sample_chunks(
        fixture_factory: _GraphRAGIntegratorFixtureFactory,
        person_entity_text,
        location_entity_text,
        ) -> list[LLMChunk]:
    """Create a dynamic sample chunk list for testing."""
    sentences_list = [person_entity_text, location_entity_text]

    chunk_list = []
    for sentence in sentences_list:
        llm_chunk = fixture_factory.make_llm_chunk([sentence])
        chunk_list.append(llm_chunk)
    return chunk_list


@pytest.fixture
def sample_llm_document(
    fixture_factory: _GraphRAGIntegratorFixtureFactory, 
    sample_chunks,
    only_person_entities: list[Entity],
    only_organization_entities: list[Entity],
    ) -> LLMDocument:
    """Create a dynamic sample LLMDocument for testing."""

    key_entities = []
    all_entities = only_person_entities + only_organization_entities
    for entity in all_entities:
        entity: Entity
        entity_dict = {"text": entity.name, "type": entity.type, "confidence": entity.confidence}
        key_entities.append(entity_dict)

    llm_document = fixture_factory.make_llm_document(
        entity_list=all_entities,
        chunks=sample_chunks
    )
    return llm_document


@pytest.fixture
def test_graph_entities(fixture_factory) -> dict[str, Entity]:
    """Create a set of entities for testing graph operations."""
    entity1 = Entity(
        id="entity_1", name="John Smith", type="person",
        description="CEO", confidence=0.9, source_chunks=["chunk_1"], properties={}
    )
    entity2 = Entity(
        id="entity_2", name="ACME Corp", type="organization", 
        description="Company", confidence=0.8, source_chunks=["chunk_1"], properties={}
    )
    entity3 = Entity(
        id="entity_3", name="Jane Doe", type="person",
        description="CTO", confidence=0.85, source_chunks=["chunk_2"], properties={}
    )
    entity4 = Entity(
        id="entity_4", name="TechCorp", type="organization",
        description="Partner company", confidence=0.7, source_chunks=["chunk_3"], properties={}
    )
    entity5 = Entity(
        id="entity_5", name="San Francisco", type="location",
        description="City", confidence=0.9, source_chunks=["chunk_1"], properties={}
    )
    
    return {
        "entity_1": entity1,
        "entity_2": entity2, 
        "entity_3": entity3,
        "entity_4": entity4,
        "entity_5": entity5
    }


@pytest.fixture
def test_graph_relationships() -> list[tuple]:
    """Create relationships for the test graph."""
    return [
        ("entity_1", "entity_2", {"relationship_type": "leads", "confidence": 0.9, "source_chunks": ["chunk_1"]}),
        ("entity_1", "entity_3", {"relationship_type": "manages", "confidence": 0.8, "source_chunks": ["chunk_1"]}),
        ("entity_3", "entity_2", {"relationship_type": "works_for", "confidence": 0.85, "source_chunks": ["chunk_2"]}),
        ("entity_2", "entity_4", {"relationship_type": "partners_with", "confidence": 0.7, "source_chunks": ["chunk_1"]}),
        ("entity_2", "entity_5", {"relationship_type": "located_in", "confidence": 0.9, "source_chunks": ["chunk_1"]})
    ]


@pytest.fixture
def integrator_with_test_graph(
    integrator, test_graph_entities, test_graph_relationships
) -> GraphRAGIntegrator:
    """Create a GraphRAGIntegrator instance with a populated test graph."""
    # Add entities to global registry
    integrator.global_entities = test_graph_entities
    
    # Create graph structure
    integrator.global_graph = nx.DiGraph()
    
    # Add nodes with attributes
    for entity_id, entity in test_graph_entities.items():
        integrator.global_graph.add_node(entity_id, **{
            "name": entity.name, "type": entity.type, 
            "confidence": entity.confidence, "source_chunks": entity.source_chunks
        })
    
    # Add edges with attributes
    for source, target, attrs in test_graph_relationships:
        integrator.global_graph.add_edge(source, target, **attrs)
    
    return integrator


@pytest.fixture
def isolated_entity() -> Entity:
    """Create an isolated entity for testing."""
    return Entity(
        id="isolated_1", name="Isolated Entity", type="concept",
        description="No connections", confidence=0.5, source_chunks=["chunk_5"], properties={}
    )


@pytest.fixture
def integrator_with_isolated_entity(integrator, isolated_entity) -> GraphRAGIntegrator:
    """Create a GraphRAGIntegrator instance with only an isolated entity."""
    integrator.global_entities = {"isolated_1": isolated_entity}
    integrator.global_graph = nx.DiGraph()
    integrator.global_graph.add_node("isolated_1", **{
        "name": isolated_entity.name, "type": isolated_entity.type,
        "confidence": isolated_entity.confidence, "source_chunks": isolated_entity.source_chunks
    })
    return integrator


@pytest.fixture
def empty_integrator(integrator) -> GraphRAGIntegrator:
    """Create a GraphRAGIntegrator instance with empty graph and entities."""
    integrator.global_graph = nx.DiGraph()
    integrator.global_entities = {}
    return integrator


# Test constants to replace magic numbers/strings
@pytest.fixture
def test_constants() -> dict[str, Any]:
    """Provide common test constants to eliminate magic numbers and strings."""
    return {
        'EMPTY_DOC_ID': "empty_doc",
        'EMPTY_DOC_TITLE': "Empty Document",
        'EMPTY_DOC_SUMMARY': "Empty document for testing",
        'SINGLE_DOC_ID': "single_doc", 
        'SINGLE_DOC_TITLE': "Single Chunk",
        'SINGLE_CHUNK_ID': "only_chunk",
        'SINGLE_CHUNK_CONTENT': "Microsoft was founded by Bill Gates.",
        'MICROSOFT_ENTITY_ID': "ms",
        'MICROSOFT_ENTITY_NAME': "Microsoft",
        'MICROSOFT_ENTITY_TYPE': "organization",
        'MICROSOFT_ENTITY_DESCRIPTION': "Tech company",
        'MICROSOFT_ENTITY_CONFIDENCE': 0.9,
        'GATES_RELATIONSHIP_ID': "rel_1",
        'GATES_ENTITY_ID': "gates",
        'FOUNDED_RELATIONSHIP_TYPE': "founded",
        'FOUNDED_RELATIONSHIP_DESCRIPTION': "Founded relationship",
        'FOUNDED_RELATIONSHIP_CONFIDENCE': 0.8,
        'MULTI_PAGE_DOC_ID': "multi_page",
        'MULTI_PAGE_DOC_TITLE': "Multi Page Document",
        'SOURCE_PAGE_ONE': 1,
        'SOURCE_PAGE_TWO': 2,
        'TOKEN_COUNT_SIX': 6,
        'TOKEN_COUNT_THREE': 3,
        'TOKEN_COUNT_FOUR': 4,
        'TOKEN_COUNT_FIVE': 5,
        'TOKEN_COUNT_TEN': 10,
        'TOKEN_COUNT_TWELVE': 12,
        'PARAGRAPH_ELEMENT': "paragraph",
        'TEXT_SEMANTIC_TYPE': "text",
        'EXPECTED_RESULT_COUNT_ONE': 1,
        'EXPECTED_RESULT_COUNT_TWO': 2,
        'EXPECTED_RESULT_COUNT_THREE': 3,
        'EXPECTED_RESULT_COUNT_FIVE': 5,
        'EXPECTED_RESULT_COUNT_FIFTEEN': 15,
        'EXPECTED_RESULT_COUNT_ONE_FIFTY': 150,
        'PERFORMANCE_TIMEOUT_SECONDS': 30,
        'PROCESSING_TIMESTAMP': "2024-01-01T00:00:00Z",
        'ISO_TIMESTAMP_MIN_LENGTH': 19,
        'TIMESTAMP_Z_SUFFIX': 'Z',
        'TEST_CID_PREFIX': "test_cid",
        'CONCURRENT_TASK_COUNT': 3,
        'LARGE_CHUNK_COUNT': 150,
        'CHUNKS_PER_PAGE': 10,
        'LOW_CONFIDENCE_THRESHOLD': 0.5,
        'HIGH_CONFIDENCE_THRESHOLD': 0.9,
        'NONE_INPUT_ERROR_MSG': "llm_document cannot be None",
        'MISSING_DOC_ID_ERROR_MSG': "document_id is required",
        'MISSING_TITLE_ERROR_MSG': "title is required", 
        'INVALID_CHUNKS_ERROR_MSG': "All chunks must be LLMChunk instances",
        'ENTITY_EXTRACTION_FAILED_MSG': "Entity extraction failed",
        'RELATIONSHIP_EXTRACTION_FAILED_MSG': "Relationship extraction failed",
        'STORAGE_FAILED_MSG': "Storage failed",
    }


@pytest.fixture
def sample_metadata(fixture_factory) -> LLMChunkMetadata:
    """Create sample metadata for LLMChunk objects."""
    return fixture_factory.make_llm_chunk_metadata()


# Specific document fixtures for test_IntegrateDocument.py
@pytest.fixture
def empty_document(fixture_factory, test_constants) -> LLMDocument:
    """Create an LLMDocument with empty chunks list using fixture factory."""
    # Use factory to create document with empty chunks
    return fixture_factory.make_llm_document(entity_list=[], chunks=[])


@pytest.fixture
def single_chunk_document(fixture_factory, sample_metadata, test_constants) -> LLMDocument:
    """Create an LLMDocument with a single chunk containing entities using fixture factory."""
    # Create entities using factory
    entities = fixture_factory.make_entity_list([test_constants['MICROSOFT_ENTITY_TYPE']])
    
    # Create chunk using factory 
    chunk = fixture_factory.make_llm_chunk([test_constants['SINGLE_CHUNK_CONTENT']])
    
    # Create document using factory
    return fixture_factory.make_llm_document(entity_list=entities, chunks=[chunk])


@pytest.fixture
def multi_page_document(fixture_factory, test_constants) -> LLMDocument:
    """Create an LLMDocument with chunks from different pages using fixture factory."""
    # Create multiple chunks using factory
    chunk_contents = ["Content page 1", "Content page 2", "More content page 2"]
    chunks = []
    for content in chunk_contents:
        chunk = fixture_factory.make_llm_chunk([content])
        chunks.append(chunk)
    
    # Create entities using factory
    entities = fixture_factory.make_entity_list(["person", "organization"])
    
    # Create document using factory
    return fixture_factory.make_llm_document(entity_list=entities, chunks=chunks)


@pytest.fixture
def concurrent_test_documents(fixture_factory, sample_metadata, test_constants) -> list[LLMDocument]:
    """Create multiple documents for concurrent testing using fixture factory."""
    documents = []
    for i in range(test_constants['CONCURRENT_TASK_COUNT']):
        # Create single chunk using factory
        chunk = fixture_factory.make_llm_chunk([f"Content {i}"])
        # Create entities using factory
        entities = fixture_factory.make_entity_list(["person"])
        # Create document using factory  
        doc = fixture_factory.make_llm_document(entity_list=entities, chunks=[chunk])
        documents.append(doc)
    return documents


@pytest.fixture
def large_document(fixture_factory, test_constants) -> LLMDocument:
    """Create an LLMDocument with a large number of chunks using fixture factory."""
    # Create multiple chunks using factory
    chunk_contents = [f"Content for chunk {i} with some entity data" for i in range(test_constants['LARGE_CHUNK_COUNT'])]
    chunks = []
    for content in chunk_contents:
        chunk = fixture_factory.make_llm_chunk([content])
        chunks.append(chunk)
    
    # Create entities using factory
    entities = fixture_factory.make_entity_list(["person", "organization", "location"])
    
    # Create document using factory
    return fixture_factory.make_llm_document(entity_list=entities, chunks=chunks)


@pytest.fixture
def no_entities_document(fixture_factory, test_constants) -> LLMDocument:
    """Create an LLMDocument with chunks that contain no extractable entities using fixture factory."""
    # Create chunk using factory
    chunk = fixture_factory.make_llm_chunk(["This is just plain text with no named entities."])
    
    # Create document with no entities using factory
    return fixture_factory.make_llm_document(entity_list=[], chunks=[chunk])


@pytest.fixture
def low_confidence_document(fixture_factory, test_constants) -> LLMDocument:
    """Create an LLMDocument with chunks containing low-confidence entities using fixture factory."""
    # Create chunk using factory
    chunk = fixture_factory.make_llm_chunk(["Maybe John Smith works somewhere."])
    
    # Create entities using factory
    entities = fixture_factory.make_entity_list(["person"])
    
    # Create document using factory
    return fixture_factory.make_llm_document(entity_list=entities, chunks=[chunk])


@pytest.fixture
def real_integrator() -> GraphRAGIntegrator:
    """Create a GraphRAGIntegrator instance with default parameters for testing exceptions."""
    return GraphRAGIntegrator()


@pytest.fixture
def large_graph_entities() -> dict[str, Entity]:
    """Create entities for large graph testing."""
    entities = {}
    for i in range(100):
        entity_id = f"large_entity_{i}"
        entity = Entity(
            id=entity_id, name=f"Entity {i}", type="concept",
            description=f"Entity number {i}", confidence=0.5,
            source_chunks=[f"chunk_{i}"], properties={}
        )
        entities[entity_id] = entity
    return entities


@pytest.fixture
def performance_graph_entities() -> dict[str, Entity]:
    """Create entities for performance testing."""
    entities = {}
    for i in range(50):
        entity_id = f"perf_entity_{i}"
        entity = Entity(
            id=entity_id, name=f"Performance Entity {i}", type="concept",
            description=f"Performance test entity {i}", confidence=0.5,
            source_chunks=[f"perf_chunk_{i}"], properties={}
        )
        entities[entity_id] = entity
    return entities


@pytest.fixture
def integrator_with_large_graph(
    integrator_with_test_graph, large_graph_entities, entity_id
) -> GraphRAGIntegrator:
    """Create a GraphRAGIntegrator instance with large graph for testing."""
    # Add large entities to the existing test graph
    integrator_with_test_graph.global_entities.update(large_graph_entities)
    
    # Add nodes and edges for large entities
    for entity_id_new, entity in large_graph_entities.items():
        integrator_with_test_graph.global_graph.add_node(entity_id_new, **{
            "name": entity.name, "type": entity.type,
            "confidence": entity.confidence, "source_chunks": entity.source_chunks
        })
        integrator_with_test_graph.global_graph.add_edge(
            entity_id, entity_id_new,
            relationship_type="related_to", confidence=0.5
        )
    
    return integrator_with_test_graph


@pytest.fixture
def integrator_with_performance_graph(
    integrator_with_test_graph, performance_graph_entities, entity_id
) -> GraphRAGIntegrator:
    """Create a GraphRAGIntegrator instance with performance graph for testing."""
    # Add performance entities to the existing test graph
    integrator_with_test_graph.global_entities.update(performance_graph_entities)
    
    # Add nodes and edges for performance entities
    for entity_id_new, entity in performance_graph_entities.items():
        integrator_with_test_graph.global_graph.add_node(entity_id_new, **{
            "name": entity.name, "type": entity.type,
            "confidence": entity.confidence, "source_chunks": entity.source_chunks
        })
        integrator_with_test_graph.global_graph.add_edge(
            entity_id, entity_id_new,
            relationship_type="performance_test", confidence=0.5
        )
    
    return integrator_with_test_graph


@pytest.fixture
def cyclic_graph_integrator(integrator_with_test_graph) -> GraphRAGIntegrator:
    """Create a GraphRAGIntegrator instance with test graph containing a cycle."""
    # Add a cycle: entity_4 -> entity_1 (completing a cycle)
    integrator_with_test_graph.global_graph.add_edge(
        "entity_4", "entity_1", 
        relationship_type="related_to", 
        confidence=0.6
    )
    return integrator_with_test_graph


@pytest.fixture
def self_loop_integrator(integrator_with_test_graph) -> GraphRAGIntegrator:
    """Create a GraphRAGIntegrator instance with test graph containing self-loops."""
    # Add self-loop: entity_1 -> entity_1
    integrator_with_test_graph.global_graph.add_edge(
        "entity_1", "entity_1", 
        relationship_type="self_reference", 
        confidence=0.5
    )
    return integrator_with_test_graph


@pytest.fixture
def get_entity_neighborhood_concurrent_tasks(integrator_with_test_graph):
    """Create 10 concurrent tasks for testing concurrent access to get_entity_neighborhood."""
    async def _create_tasks(entity_id, depth=1):
        return [
            integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
            for _ in range(10)
        ]
    return _create_tasks


@pytest.fixture
def invalid_document_for_missing_id(fixture_factory, test_constants) -> LLMDocument:
    """Create a document that can be modified for missing document_id tests."""
    return fixture_factory.make_llm_document(
        entity_list=[],
        chunks=[]
    )


@pytest.fixture  
def invalid_document_for_missing_title(fixture_factory, test_constants) -> LLMDocument:
    """Create a document that can be modified for missing title tests."""
    return fixture_factory.make_llm_document(
        entity_list=[],
        chunks=[]
    )


@pytest.fixture
def invalid_document_for_chunks_type(fixture_factory, test_constants) -> LLMDocument:
    """Create a document that can be modified for invalid chunks type tests.""" 
    return fixture_factory.make_llm_document(
        entity_list=[],
        chunks=[]
    )
