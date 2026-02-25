"""Tests for Kafka streaming ontology extraction.

Tests cover producer (sending documents), consumer (processing and extraction),
error handling, batching, and integration scenarios.
"""

import json
import pytest
from typing import Any, Dict, List

from ipfs_datasets_py.optimizers.integrations.kafka_ontology_stream import (
    KafkaConfig,
    KafkaOntologyProducer,
    KafkaOntologyConsumer,
    MockKafkaProducer,
    MockKafkaConsumer,
    MockKafkaMessage,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    EntityExtractionResult,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def kafka_config() -> KafkaConfig:
    """Create default Kafka configuration."""
    return KafkaConfig(
        bootstrap_servers="localhost:9092",
        input_topic="test-input",
        output_topic="test-output",
        error_topic="test-errors",
        consumer_group="test-group",
    )


@pytest.fixture
def mock_generator():
    """Create mock generator for testing."""
    class MockGenerator:
        def extract_entities(self, text: str, context: Any) -> EntityExtractionResult:
            # Simple extraction: words starting with capital letters
            words = text.split()
            entities = [
                {"id": f"e{i}", "text": word, "type": "Entity", "confidence": 0.9}
                for i, word in enumerate(words) if word[0].isupper()
            ]
            relationships = []
            
            return EntityExtractionResult(
                entities=entities,
                relationships=relationships,
                confidence=0.85,
            )
    
    return MockGenerator()


@pytest.fixture
def sample_document() -> Dict[str, Any]:
    """Create sample document."""
    return {
        "id": "doc1",
        "text": "Alice and Bob signed a contract with TechCorp.",
        "domain": "legal",
    }


# =============================================================================
# Test Cases: KafkaConfig
# =============================================================================


class TestKafkaConfig:
    """Test Kafka configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = KafkaConfig()
        assert config.bootstrap_servers == "localhost:9092"
        assert config.input_topic == "ontology-input"
        assert config.output_topic == "ontology-output"
        assert config.batch_size == 10
        assert config.enable_auto_commit is False
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = KafkaConfig(
            bootstrap_servers="kafka1:9092,kafka2:9092",
            input_topic="custom-input",
            batch_size=50,
            enable_auto_commit=True,
        )
        assert config.bootstrap_servers == "kafka1:9092,kafka2:9092"
        assert config.input_topic == "custom-input"
        assert config.batch_size == 50
        assert config.enable_auto_commit is True


# =============================================================================
# Test Cases: Mock Kafka Components
# =============================================================================


class TestMockKafkaComponents:
    """Test mock Kafka producer and consumer."""
    
    def test_mock_producer_send(self):
        """Test mock producer sends messages."""
        producer = MockKafkaProducer()
        msg = json.dumps({"text": "test"}).encode('utf-8')
        
        producer.send("test-topic", value=msg, key=b"key1")
        
        assert len(producer.sent_messages) == 1
        assert producer.sent_messages[0]["topic"] == "test-topic"
        assert producer.sent_messages[0]["key"] == "key1"
    
    def test_mock_producer_flush(self):
        """Test mock producer flush."""
        producer = MockKafkaProducer()
        producer.send("topic", value=b"test")
        producer.flush()
        # Should not raise
    
    def test_mock_producer_close(self):
        """Test mock producer close."""
        producer = MockKafkaProducer()
        producer.close()
        assert producer.closed
        
        # Should raise after close
        with pytest.raises(RuntimeError, match="closed"):
            producer.send("topic", value=b"test")
    
    def test_mock_consumer_poll(self):
        """Test mock consumer poll."""
        consumer = MockKafkaConsumer("test-topic")
        consumer._add_mock_message("test-topic", '{"text": "test1"}')
        consumer._add_mock_message("test-topic", '{"text": "test2"}')
        
        messages = consumer.poll(timeout_ms=1000)
        
        assert len(messages) > 0
        topic_partition = list(messages.keys())[0]
        assert len(messages[topic_partition]) == 2
    
    def test_mock_consumer_commit(self):
        """Test mock consumer commit."""
        consumer = MockKafkaConsumer("test-topic")
        consumer.commit()
        # Should not raise
    
    def test_mock_message_attributes(self):
        """Test mock message attributes."""
        msg = MockKafkaMessage(
            topic="test",
            partition=0,
            offset=42,
            key=b"key1",
            value=b"value1",
        )
        
        assert msg.topic == "test"
        assert msg.partition == 0
        assert msg.offset == 42
        assert msg.key() == b"key1"
        assert msg.value() == b"value1"
        assert msg.timestamp > 0


# =============================================================================
# Test Cases: KafkaOntologyProducer
# =============================================================================


class TestKafkaOntologyProducer:
    """Test Kafka ontology producer."""
    
    def test_producer_initialization(self, kafka_config: KafkaConfig):
        """Test producer initialization."""
        producer = KafkaOntologyProducer(kafka_config, use_mock=True)
        assert producer.config == kafka_config
        assert isinstance(producer.producer, MockKafkaProducer)
    
    def test_send_document(self, kafka_config: KafkaConfig, sample_document: Dict[str, Any]):
        """Test sending single document."""
        producer = KafkaOntologyProducer(kafka_config, use_mock=True)
        
        producer.send_document(sample_document, key="doc1")
        
        assert len(producer.producer.sent_messages) == 1
        msg = producer.producer.sent_messages[0]
        assert msg["key"] == "doc1"
        assert "Alice" in msg["value"]
    
    def test_send_document_without_text_raises(self, kafka_config: KafkaConfig):
        """Test sending document without 'text' field raises."""
        producer = KafkaOntologyProducer(kafka_config, use_mock=True)
        
        with pytest.raises(ValueError, match="must contain 'text' field"):
            producer.send_document({"id": "doc1", "title": "Test"})
    
    def test_send_batch(self, kafka_config: KafkaConfig):
        """Test sending batch of documents."""
        producer = KafkaOntologyProducer(kafka_config, use_mock=True)
        
        documents = [
            {"id": "doc1", "text": "Text 1"},
            {"id": "doc2", "text": "Text 2"},
            {"id": "doc3", "text": "Text 3"},
        ]
        
        producer.send_batch(documents)
        
        assert len(producer.producer.sent_messages) == 3
        assert producer.producer.sent_messages[0]["key"] == "doc1"
        assert producer.producer.sent_messages[2]["key"] == "doc3"
    
    def test_flush(self, kafka_config: KafkaConfig):
        """Test flushing producer."""
        producer = KafkaOntologyProducer(kafka_config, use_mock=True)
        producer.send_document({"text": "Test", "id": "doc1"})
        producer.flush()
        # Should not raise
    
    def test_close(self, kafka_config: KafkaConfig):
        """Test closing producer."""
        producer = KafkaOntologyProducer(kafka_config, use_mock=True)
        producer.close()
        assert producer.producer.closed
    
    def test_send_to_custom_topic(self, kafka_config: KafkaConfig, sample_document: Dict[str, Any]):
        """Test sending to custom topic."""
        producer = KafkaOntologyProducer(kafka_config, use_mock=True)
        
        producer.send_document(sample_document, topic="custom-topic")
        
        assert producer.producer.sent_messages[0]["topic"] == "custom-topic"
    
    def test_send_document_with_id_as_key(self, kafka_config: KafkaConfig):
        """Test document ID used as key when not explicitly provided."""
        producer = KafkaOntologyProducer(kafka_config, use_mock=True)
        documents = [{"id": "doc123", "text": "Test"}]
        
        producer.send_batch(documents)
        
        assert producer.producer.sent_messages[0]["key"] == "doc123"


# =============================================================================
# Test Cases: KafkaOntologyConsumer
# =============================================================================


class TestKafkaOntologyConsumer:
    """Test Kafka ontology consumer."""
    
    def test_consumer_initialization(self, kafka_config: KafkaConfig, mock_generator):
        """Test consumer initialization."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        assert consumer.config == kafka_config
        assert consumer.generator == mock_generator
        assert isinstance(consumer.consumer, MockKafkaConsumer)
    
    def test_consume_and_extract_single_message(self, kafka_config: KafkaConfig, mock_generator):
        """Test consuming and extracting from single message."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Add mock message
        doc = {"text": "Alice and Bob signed a contract.", "id": "doc1"}
        consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        # Consume
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        
        assert len(results) == 1
        result = results[0]
        assert result["document_id"] == "doc1"
        assert "ontology" in result
        assert len(result["ontology"]["entities"]) == 2  # Alice, Bob
        assert "processing_time_ms" in result
    
    def test_consume_batch(self, kafka_config: KafkaConfig, mock_generator):
        """Test consuming batch of messages."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Add multiple messages
        for i in range(5):
            doc = {"text": f"Entity{i} is a test.", "id": f"doc{i}"}
            consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        # Consume
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=5))
        
        assert len(results) == 5
        assert all("ontology" in r for r in results)
    
    def test_consumer_stats(self, kafka_config: KafkaConfig, mock_generator):
        """Test consumer statistics tracking."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Add message
        doc = {"text": "Test Entity", "id": "doc1"}
        consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        # Consume
        list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        
        stats = consumer.get_stats()
        assert stats["messages_processed"] == 1
        assert stats["documents_extracted"] == 1
        assert stats["errors"] == 0
    
    def test_output_message_format(self, kafka_config: KafkaConfig, mock_generator):
        """Test output message structure."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        doc = {"text": "Alice works at TechCorp.", "id": "doc1", "domain": "business"}
        consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        result = results[0]
        
        # Verify output structure
        assert "document_id" in result
        assert "ontology" in result
        assert "entities" in result["ontology"]
        assert "relationships" in result["ontology"]
        assert "context" in result
        assert "processing_time_ms" in result
        assert "timestamp" in result
    
    def test_close_consumer(self, kafka_config: KafkaConfig, mock_generator):
        """Test closing consumer."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        consumer.close()
        assert consumer.consumer.closed


# =============================================================================
# Test Cases: Integration
# =============================================================================


class TestKafkaIntegration:
    """Test end-to-end integration scenarios."""
    
    def test_producer_consumer_pipeline(self, kafka_config: KafkaConfig, mock_generator):
        """Test full producer → consumer pipeline."""
        # Producer sends documents
        producer = KafkaOntologyProducer(kafka_config, use_mock=True)
        documents = [
            {"id": "doc1", "text": "Alice and Bob founded StartupInc."},
            {"id": "doc2", "text": "TechCorp acquired StartupInc in 2023."},
        ]
        producer.send_batch(documents)
        producer.flush()
        
        # Consumer processes documents
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Simulate messages in consumer (in real scenario, Kafka would handle this)
        for doc in documents:
            consumer.consumer._add_mock_message(kafka_config.input_topic, json.dumps(doc))
        
        # Extract
        results = list(consumer.consume_and_extract(topics=[kafka_config.input_topic], max_messages=2))
        
        assert len(results) == 2
        assert results[0]["document_id"] == "doc1"
        assert results[1]["document_id"] == "doc2"
        
        # Verify output messages sent
        assert len(consumer.producer.sent_messages) == 2
    
    def test_batch_processing_performance(self, kafka_config: KafkaConfig, mock_generator):
        """Test batch processing with multiple documents."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Add large batch
        for i in range(100):
            doc = {"text": f"Entity{i} in Document{i}.", "id": f"doc{i}"}
            consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        # Process batch
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=100))
        
        assert len(results) == 100
        stats = consumer.get_stats()
        assert stats["messages_processed"] == 100
    
    def test_custom_context_builder(self, kafka_config: KafkaConfig, mock_generator):
        """Test custom context builder."""
        def custom_builder(document: Dict[str, Any]) -> OntologyGenerationContext:
            return OntologyGenerationContext(
                data_source=document.get("source", "kafka"),
                data_type="text",
                domain=document.get("domain", "custom"),
            )
        
        consumer = KafkaOntologyConsumer(
            kafka_config,
            generator=mock_generator,
            context_builder=custom_builder,
            use_mock=True,
        )
        
        doc = {"text": "Test", "id": "doc1", "domain": "medical", "source": "hospital"}
        consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        
        assert results[0]["context"]["domain"] == "medical"
        assert results[0]["context"]["data_source"] == "hospital"


# =============================================================================
# Test Cases: Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling and resilience."""
    
    def test_consumer_handles_malformed_message(self, kafka_config: KafkaConfig, mock_generator):
        """Test consumer handles messages without 'text' field."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Add invalid message (no 'text' field)
        invalid_doc = json.dumps({"id": "doc1", "title": "No text field"})
        consumer.consumer._add_mock_message("test-input", invalid_doc)
        
        # Should handle gracefully
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        
        assert len(results) == 0  # No results due to error
        stats = consumer.get_stats()
        assert stats["errors"] == 1
    
    def test_error_sent_to_dlq(self, kafka_config: KafkaConfig, mock_generator):
        """Test errors are sent to dead-letter queue."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Add invalid message
        invalid_doc = json.dumps({"id": "doc1", "invalid": "data"})
        consumer.consumer._add_mock_message("test-input", invalid_doc)
        
        # Process
        list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        
        # Check DLQ
        dlq_messages = [msg for msg in consumer.producer.sent_messages if msg["topic"] == kafka_config.error_topic]
        assert len(dlq_messages) == 1
        assert "error" in dlq_messages[0]["value"]


# =============================================================================
# Test Cases: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_text_document(self, kafka_config: KafkaConfig, mock_generator):
        """Test document with empty text."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        doc = {"text": "", "id": "doc1"}
        consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        
        assert len(results) == 1
        assert len(results[0]["ontology"]["entities"]) == 0
    
    def test_large_document(self, kafka_config: KafkaConfig, mock_generator):
        """Test processing large document."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Generate large text
        large_text = " ".join([f"Entity{i}" for i in range(1000)])
        doc = {"text": large_text, "id": "large_doc"}
        consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        
        assert len(results) == 1
        assert len(results[0]["ontology"]["entities"]) == 1000
    
    def test_unicode_text(self, kafka_config: KafkaConfig, mock_generator):
        """Test document with Unicode text."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        doc = {"text": "北京市 and Tokyo are cities.", "id": "doc1"}
        consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        
        assert len(results) == 1
    
    def test_no_messages_available(self, kafka_config: KafkaConfig, mock_generator):
        """Test when no messages are available."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Don't add any messages
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=1))
        
        assert len(results) == 0
    
    def test_max_messages_limit(self, kafka_config: KafkaConfig, mock_generator):
        """Test max_messages limit is respected."""
        consumer = KafkaOntologyConsumer(kafka_config, generator=mock_generator, use_mock=True)
        
        # Add 10 messages
        for i in range(10):
            doc = {"text": f"Test{i}", "id": f"doc{i}"}
            consumer.consumer._add_mock_message("test-input", json.dumps(doc))
        
        # Request only 5
        results = list(consumer.consume_and_extract(topics=["test-input"], max_messages=5))
        
        assert len(results) == 5
