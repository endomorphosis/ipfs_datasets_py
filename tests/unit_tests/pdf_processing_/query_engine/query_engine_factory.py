from unittest.mock import Mock, MagicMock, patch
from typing import Generator, Any, Dict, Set, Type, Union
import logging

import faker
import pytest

from ipfs_datasets_py.ipld.storage import IPLDStorage
from ipfs_datasets_py.pdf_processing import GraphRAGIntegrator, KnowledgeGraph
from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine, QueryResult, Relationship

RANDOM_SEED = 420

def faker_instance() -> faker.Faker:
    """Create a Faker instance with a fixed seed for reproducibility."""
    fake = faker.Faker()
    fake.seed(RANDOM_SEED)
    return fake

class QueryEngineFactory:
    """Factory class for creating test objects and mock instances for QueryEngine testing."""


    def make_mock_knowledge_graph(self):
        """Create a sample knowledge graph."""

        # Create sample knowledge graphs with proper structure
        mock_kg1 = MagicMock()
        mock_kg1.document_id = "document_001"
        mock_kg1.document_chunks = {
            "document_001": ["doc1_chunk1", "doc1_chunk2", "doc1_chunk3", "doc1_chunk5", "doc1_chunk7"]
        }
        
        # Create second knowledge graph
        mock_kg2 = MagicMock()
        mock_kg2.document_id = "document_002"
        mock_kg2.document_chunks = {
            "document_002": ["doc2_chunk1", "doc2_chunk2", "doc2_chunk3", "doc2_chunk8"]
        }
        
        # Create additional knowledge graphs for tests that expect more documents
        mock_kg3 = MagicMock()
        mock_kg3.document_id = "document_003"
        mock_kg3.document_chunks = {
            "document_003": ["doc3_chunk1", "doc3_chunk2", "doc3_chunk3"]
        }
        
        mock_kg4 = MagicMock()
        mock_kg4.document_id = "document_004"
        mock_kg4.document_chunks = {
            "document_004": ["doc4_chunk1", "doc4_chunk2", "doc4_chunk3"]
        }
        
        mock_kg5 = MagicMock()
        mock_kg5.document_id = "document_005"
        mock_kg5.document_chunks = {
            "document_005": ["doc5_chunk1", "doc5_chunk2", "doc5_chunk3"]
        }
        
        # Set up the knowledge_graphs collection
        return {
            "document_001": mock_kg1,
            "document_002": mock_kg2,
            "document_003": mock_kg3,
            "document_004": mock_kg4,
            "document_005": mock_kg5
        }


    def make_mock_graphrag_integrator(self, **kwargs) -> MagicMock:
        """
        Factory function to create a mock GraphRAGIntegrator with configurable return values.
        
        Args:
            **kwargs: Override values for the mock instance attributes/methods
        
        Returns:
            MagicMock: Configured mock GraphRAGIntegrator instance
        """
        mock = MagicMock(spec=GraphRAGIntegrator)
        mock.global_entities = MagicMock
        mock.knowledge_graphs = self.make_mock_knowledge_graph()

        if kwargs:
            # Configure mock with any provided kwargs
            for attr_name, attr_value in kwargs.items():
                setattr(mock, attr_name, attr_value)

        return mock

    def make_mock_ipld_storage(self) -> MagicMock:
        """
        Create a mock IPLDStorage for testing.
        
        Returns:
            MagicMock: Mock IPLDStorage instance
        """
        mock = MagicMock(spec=IPLDStorage)
        return mock

    def _validate_override_keys(self, overrides: Dict[str, Any], valid_keys: Set[str]) -> None:
        """
        Validate that all override keys are valid.
        
        Args:
            overrides: Dictionary of override values
            valid_keys: Set of valid keys
            
        Raises:
            KeyError: If any override key is invalid
        """
        if not overrides:
            return
            
        invalid_keys = set(overrides.keys()) - valid_keys
        if invalid_keys:
            raise KeyError(f"Invalid keys in overrides: {invalid_keys}. Valid keys are: {valid_keys}")

    def make_sample_relationship(self, **overrides) -> Relationship:
        """
        Create a sample Relationship for testing.
        
        Args:
            **overrides: Override values for relationship attributes
            
        Returns:
            Relationship: Sample relationship instance
            
        Raises:
            KeyError: If any override key is invalid
        """
        defaults = {
            "id": "rel_001",
            "source_entity_id": "entity_001", 
            "target_entity_id": "entity_002",
            "relationship_type": "founded",
            "description": "Bill Gates founded Microsoft",
            "properties": {"year": "1975"},
            "source_chunks": ["doc_001_chunk_003"]
        }
        
        self._validate_override_keys(overrides, set(defaults.keys()))
        defaults.update(overrides)
        
        return Relationship(**defaults)

    def make_sample_query_result(self, **overrides) -> QueryResult:
        """
        Create a sample QueryResult for testing.
        
        Args:
            **overrides: Override values for query result attributes
            
        Returns:
            QueryResult: Sample query result instance
            
        Raises:
            KeyError: If any override key is invalid
        """
        defaults = {
            "id": "result_001",
            "type": "entity", 
            "content": "Bill Gates (Person): Co-founder of Microsoft",
            "relevance_score": 0.85,
            "source_document": "doc_001",
            "source_chunks": ["doc_001_chunk_003"],
            "metadata": {"entity_type": "Person", "confidence": 0.9}
        }
        
        self._validate_override_keys(overrides, set(defaults.keys()))
        defaults.update(overrides)
        
        return QueryResult(**defaults)

    def make_mock_logger(self) -> MagicMock:
        """
        Create a mock logger for testing.
        
        Returns:
            MagicMock: Mock logger instance
        """
        mock_logger = MagicMock(spec=logging.Logger)
        return mock_logger

    def make_query_engine(self, mock_graphrag_integrator=None, mock_storage=None, mock_logger=None) -> QueryEngine:
        """
        Create a QueryEngine instance for testing.
        
        Args:
            mock_graphrag_integrator: Optional mock GraphRAG integrator
            mock_storage: Optional mock storage
            mock_logger: Optional mock logger
            
        Returns:
            QueryEngine: Configured QueryEngine instance for testing
        """
        embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
        embedding_return = [[0.1, 0.2, 0.3]]
        
        if mock_graphrag_integrator is None:
            mock_graphrag_integrator = self.make_mock_graphrag_integrator()
        if mock_storage is None:
            mock_storage = self.make_mock_ipld_storage()
        if mock_logger is None:
            mock_logger = self.make_mock_logger()

        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'):
            engine = QueryEngine(
                graphrag_integrator=mock_graphrag_integrator,
                storage=mock_storage,
                embedding_model=embedding_model
            )
            # Mock the embedding model
            engine.embedding_model = Mock()
            engine.embedding_model.encode = Mock(return_value=embedding_return)
            return engine

    @staticmethod
    def make_fake_names(n: int = 30) -> list[str]:
        """
        Generate a list of fake names using Faker library.
        
        Args:
            n: Number of names to generate (default: 30)
        
        Returns:
            list[str]: List of fake names
        """
        fake = faker_instance()
        return [fake.name() for _ in range(n)]

    def make_fake_name_questions(self, n: int = 30) -> Generator[tuple[str, str], None, None]:
        """
        Generate a list of fake name-related questions using Faker library.
        
        Args:
            n: Number of questions to generate (default: 30)
        
        Yields:
            tuple[str, str]: Tuple of (name, question) where question is "Who is {name}?"
        """
        fake_names = self.make_fake_names(n)
        for name in fake_names:
            yield name, f"Who is {name}?"

    @staticmethod
    def make_fake_companies(n: int = 30) -> list[str]:
        """
        Generate a list of fake company names using Faker library.
        
        Args:
            n: Number of company names to generate (default: 30)
        
        Returns:
            list[str]: List of fake company names
        """
        fake = faker_instance()
        return [fake.company() for _ in range(n)]

    def make_fake_company_questions(self, n: int = 30) -> Generator[tuple[str, str, str], None, None]:
        """
        Generate a list of fake company-related questions using Faker library.
        
        Args:
            n: Number of questions to generate (default: 30)
        
        Yields:
            tuple[str, str, str]: Tuple of (company1, company2, statement) where 
                                 statement is "{company1} and {company2} are competitors."
        """
        fake_companies_1 = self.make_fake_companies(n)
        fake_companies_2 = self.make_fake_companies(n)
        for company1, company2 in zip(fake_companies_1, fake_companies_2):
            yield company1, company2, f"{company1} and {company2} are competitors."


# Global factory instance for convenience
query_engine_factory = QueryEngineFactory()