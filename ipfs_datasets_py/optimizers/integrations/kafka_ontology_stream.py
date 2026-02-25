"""Kafka streaming integration for ontology extraction.

This module provides Kafka-based streaming pipeline integration for distributed
ontology extraction. Features:

- KafkaOntologyProducer: Send documents to Kafka topics for processing
- KafkaOntologyConsumer: Process documents from Kafka and extract ontologies
- Batch processing with configurable commit strategies
- Error handling and dead-letter queue support
- Backpressure and rate limiting
- Integration with StreamingEntityExtractor for incremental processing

Architecture:
    Documents → Kafka Topic → Consumer → OntologyExtractor → Results Topic
    
Example:
    >>> from ipfs_datasets_py.optimizers.integrations.kafka_ontology_stream import (
    ...     KafkaOntologyProducer, KafkaOntologyConsumer, KafkaConfig
    ... )
    >>> 
    >>> # Producer: Send documents for processing
    >>> config = KafkaConfig(bootstrap_servers="localhost:9092")
    >>> producer = KafkaOntologyProducer(config)
    >>> producer.send_document({"text": "Contract between Alice and Bob", "id": "doc1"})
    >>> producer.flush()
    >>> 
    >>> # Consumer: Process documents and extract ontologies
    >>> consumer = KafkaOntologyConsumer(config, generator=my_generator)
    >>> for result in consumer.consume_and_extract(topics=["documents"]):
    ...     print(f"Extracted {len(result['ontology']['entities'])} entities")

Optional dependency: kafka-python (or use MockKafka for testing)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Iterator, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

# Optional Kafka import
try:
    from kafka import KafkaProducer as _KafkaProducer
    from kafka import KafkaConsumer as _KafkaConsumer
    from kafka.errors import KafkaError
    HAS_KAFKA = True
except ImportError:
    HAS_KAFKA = False
    logger.warning("kafka-python not installed. Using mock implementation for testing.")


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class KafkaConfig:
    """Kafka connection and processing configuration."""
    
    bootstrap_servers: str = "localhost:9092"
    input_topic: str = "ontology-input"
    output_topic: str = "ontology-output"
    error_topic: str = "ontology-errors"
    consumer_group: str = "ontology-extractors"
    
    # Processing settings
    batch_size: int = 10  # Documents per batch
    max_poll_interval_ms: int = 300000  # 5 minutes
    enable_auto_commit: bool = False  # Manual commit after processing
    auto_offset_reset: str = "earliest"  # Start from beginning if no offset
    
    # Producer settings
    producer_acks: str = "all"  # Wait for all replicas
    producer_retries: int = 3
    compression_type: Optional[str] = "gzip"
    
    # Performance tuning
    max_poll_records: int = 100
    fetch_min_bytes: int = 1024
    fetch_max_wait_ms: int = 500


# =============================================================================
# Mock Kafka Implementation (for testing without kafka-python)
# =============================================================================


class MockKafkaMessage:
    """Mock Kafka message for testing."""
    
    def __init__(self, topic: str, partition: int, offset: int, key: Optional[bytes], value: bytes):
        self.topic = topic
        self.partition = partition
        self.offset = offset
        self._key = key
        self._value = value
        self.timestamp = int(time.time() * 1000)
    
    def key(self) -> Optional[bytes]:
        """Get message key."""
        return self._key
    
    def value(self) -> bytes:
        """Get message value."""
        return self._value


class MockKafkaProducer:
    """Mock Kafka producer for testing."""
    
    def __init__(self, **kwargs):
        self.config = kwargs
        self.sent_messages = []
        self.closed = False
        logger.info(f"MockKafkaProducer initialized with config: {list(kwargs.keys())}")
    
    def send(self, topic: str, value: bytes, key: Optional[bytes] = None):
        """Send message (mock)."""
        if self.closed:
            raise RuntimeError("Producer is closed")
        
        # Handle key as either bytes or str
        if key is not None:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
        else:
            key_str = None
        
        msg = {
            "topic": topic,
            "key": key_str,
            "value": value.decode('utf-8') if isinstance(value, bytes) else value,
            "timestamp": datetime.now().isoformat(),
        }
        self.sent_messages.append(msg)
        logger.debug(f"MockKafkaProducer sent message to {topic}")
        
        # Return mock future
        class MockFuture:
            def get(self, timeout=None):
                return None
        
        return MockFuture()
    
    def flush(self):
        """Flush pending messages (mock)."""
        logger.debug(f"MockKafkaProducer flushed {len(self.sent_messages)} messages")
    
    def close(self):
        """Close producer."""
        self.closed = True


class MockKafkaConsumer:
    """Mock Kafka consumer for testing."""
    
    def __init__(self, *topics, **kwargs):
        self.topics = topics
        self.config = kwargs
        self._messages = []
        self._position = 0
        self.closed = False
        logger.info(f"MockKafkaConsumer initialized for topics: {topics}")
    
    def poll(self, timeout_ms: int = 1000, max_records: int = 100):
        """Poll for messages (mock)."""
        if self.closed:
            return {}
        
        if not self._messages:
            return {}
        
        # Return available messages
        batch_size = min(max_records, len(self._messages) - self._position)
        if batch_size == 0:
            return {}
        
        messages = []
        for i in range(batch_size):
            msg_data = self._messages[self._position + i]
            msg = MockKafkaMessage(
                topic=msg_data["topic"],
                partition=0,
                offset=self._position + i,
                key=msg_data.get("key", "").encode('utf-8') if msg_data.get("key") else None,
                value=msg_data["value"].encode('utf-8') if isinstance(msg_data["value"], str) else msg_data["value"],
            )
            messages.append(msg)
        
        self._position += batch_size
        
        # Return dict of topic partitions → messages
        result = {}
        for msg in messages:
            key = (msg.topic, msg.partition)
            if key not in result:
                result[key] = []
            result[key].append(msg)
        
        return result
    
    def commit(self):
        """Commit offsets (mock)."""
        logger.debug(f"MockKafkaConsumer committed offset {self._position}")
    
    def close(self):
        """Close consumer."""
        self.closed = True
    
    def _add_mock_message(self, topic: str, value: str, key: Optional[str] = None):
        """Add mock message for testing."""
        self._messages.append({"topic": topic, "value": value, "key": key})


# =============================================================================
# Kafka Ontology Producer
# =============================================================================


class KafkaOntologyProducer:
    """Kafka producer for sending documents to ontology extraction pipeline."""
    
    def __init__(self, config: KafkaConfig, use_mock: bool = False):
        """
        Initialize Kafka producer.
        
        Args:
            config: Kafka configuration.
            use_mock: Use mock producer (for testing without Kafka).
        """
        self.config = config
        self._use_mock = use_mock or not HAS_KAFKA
        
        if self._use_mock:
            self.producer = MockKafkaProducer(
                bootstrap_servers=config.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            )
        else:
            if not HAS_KAFKA:
                raise ImportError("kafka-python not installed. Install with: pip install kafka-python")
            
            self.producer = _KafkaProducer(
                bootstrap_servers=config.bootstrap_servers.split(','),
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                key_serializer=lambda k: k.encode('utf-8') if k else None,
                acks=config.producer_acks,
                retries=config.producer_retries,
                compression_type=config.compression_type,
            )
        
        logger.info(f"KafkaOntologyProducer initialized ({'mock' if self._use_mock else 'real'})")
    
    def send_document(
        self,
        document: Dict[str, Any],
        topic: Optional[str] = None,
        key: Optional[str] = None,
    ) -> None:
        """
        Send document to Kafka topic for processing.
        
        Args:
            document: Document dict with at least 'text' field.
                Must be JSON-serializable.
            topic: Kafka topic (defaults to config.input_topic).
            key: Optional message key for partitioning.
        
        Example:
            >>> producer.send_document({"text": "Sample contract", "id": "doc1"}, key="doc1")
        """
        topic = topic or self.config.input_topic
        
        # Validate document
        if "text" not in document:
            raise ValueError("Document must contain 'text' field")
        
        # Send to Kafka
        future = self.producer.send(topic, value=document, key=key)
        logger.debug(f"Sent document (key={key}) to topic {topic}")
    
    def send_batch(
        self,
        documents: List[Dict[str, Any]],
        topic: Optional[str] = None,
    ) -> None:
        """
        Send batch of documents.
        
        Args:
            documents: List of document dicts.
            topic: Kafka topic (defaults to config.input_topic).
        """
        for doc in documents:
            doc_id = doc.get("id") or doc.get("document_id")
            self.send_document(doc, topic=topic, key=doc_id)
        
        logger.info(f"Sent batch of {len(documents)} documents")
    
    def flush(self, timeout: Optional[float] = None) -> None:
        """
        Flush pending messages.
        
        Args:
            timeout: Max time to wait for flush (seconds).
        """
        self.producer.flush()
        logger.debug("Producer flushed")
    
    def close(self) -> None:
        """Close producer and release resources."""
        self.producer.close()
        logger.info("Producer closed")


# =============================================================================
# Kafka Ontology Consumer
# =============================================================================


class KafkaOntologyConsumer:
    """Kafka consumer for processing documents and extracting ontologies."""
    
    def __init__(
        self,
        config: KafkaConfig,
        generator: Any,  # OntologyGenerator
        context_builder: Optional[Callable[[Dict[str, Any]], Any]] = None,
        use_mock: bool = False,
    ):
        """
        Initialize Kafka consumer.
        
        Args:
            config: Kafka configuration.
            generator: OntologyGenerator instance for extraction.
            context_builder: Optional callable to build OntologyGenerationContext from document.
            use_mock: Use mock consumer (for testing without Kafka).
        """
        self.config = config
        self.generator = generator
        self.context_builder = context_builder
        self._use_mock = use_mock or not HAS_KAFKA
        self._stats = {
            "messages_processed": 0,
            "documents_extracted": 0,
            "errors": 0,
        }
        
        if self._use_mock:
            self.consumer = MockKafkaConsumer(
                bootstrap_servers=config.bootstrap_servers,
                group_id=config.consumer_group,
            )
            self.producer = MockKafkaProducer(
                bootstrap_servers=config.bootstrap_servers,
            )
        else:
            if not HAS_KAFKA:
                raise ImportError("kafka-python not installed. Install with: pip install kafka-python")
            
            self.consumer = _KafkaConsumer(
                bootstrap_servers=config.bootstrap_servers.split(','),
                group_id=config.consumer_group,
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                key_deserializer=lambda k: k.decode('utf-8') if k else None,
                enable_auto_commit=config.enable_auto_commit,
                auto_offset_reset=config.auto_offset_reset,
                max_poll_interval_ms=config.max_poll_interval_ms,
                max_poll_records=config.max_poll_records,
            )
            
            self.producer = _KafkaProducer(
                bootstrap_servers=config.bootstrap_servers.split(','),
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            )
        
        logger.info(f"KafkaOntologyConsumer initialized ({'mock' if self._use_mock else 'real'})")
    
    def consume_and_extract(
        self,
        topics: Optional[List[str]] = None,
        max_messages: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Consume documents from Kafka and extract ontologies.
        
        Args:
            topics: List of topics to subscribe to (defaults to config.input_topic).
            max_messages: Max messagesp to process before stopping (None = infinite).
        
        Yields:
            Dict with:
                - 'document_id': Original document ID
                - 'ontology': Extracted ontology dict
                - 'context': Generation context
                - 'processing_time_ms': Processing time
        
        Example:
            >>> for result in consumer.consume_and_extract(topics=["documents"]):
            ...     ontology = result['ontology']
            ...     print(f"Extracted {len(ontology['entities'])} entities")
        """
        topics = topics or [self.config.input_topic]
        
        if not self._use_mock:
            self.consumer.subscribe(topics)
        
        logger.info(f"Consuming from topics: {topics}")
        
        processed = 0
        while True:
            if max_messages and processed >= max_messages:
                break
            
            # Poll for messages
            msg_batch = self.consumer.poll(timeout_ms=1000, max_records=self.config.batch_size)
            
            if not msg_batch:
                logger.debug("No messages in poll")
                if max_messages:  # Stop if finite consumption mode
                    break
                continue
            
            # Process messages
            for topic_partition, messages in msg_batch.items():
                for message in messages:
                    try:
                        result = self._process_message(message)
                        yield result
                        processed += 1
                        self._stats["messages_processed"] += 1
                        self._stats["documents_extracted"] += 1
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        self._handle_error(message, str(e))
                        self._stats["errors"] += 1
            
            # Commit offsets after processing batch
            if not self.config.enable_auto_commit:
                self.consumer.commit()
    
    def _process_message(self, message: Any) -> Dict[str, Any]:
        """Process single message and extract ontology."""
        start_time = time.time()
        
        # Parse document
        if self._use_mock:
            document = json.loads(message.value())
        else:
            document = message.value()
        
        # Build context
        if self.context_builder:
            context = self.context_builder(document)
        else:
            from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerationContext
            context = OntologyGenerationContext(
                data_source="kafka",
                data_type="text",
                domain=document.get("domain", "general"),
            )
        
        # Extract ontology
        text = document["text"]
        result = self.generator.extract_entities(text, context)
        
        # Build ontology dict
        ontology = {
            "entities": result.entities,
            "relationships": result.relationships,
        }
        
        # Send result to output topic
        output = {
            "document_id": document.get("id") or document.get("document_id"),
            "ontology": ontology,
            "context": {
                "domain": context.domain,
                "data_source": context.data_source,
            },
            "processing_time_ms": (time.time() - start_time) * 1000,
            "timestamp": datetime.now().isoformat(),
        }
        
        self.producer.send(self.config.output_topic, value=output)
        
        logger.debug(f"Processed document: {len(ontology['entities'])} entities, {len(ontology['relationships'])} relationships")
        
        return output
    
    def _handle_error(self, message: Any, error: str) -> None:
        """Send error to dead-letter queue."""
        error_msg = {
            "original_message": str(message),
            "error": error,
            "timestamp": datetime.now().isoformat(),
        }
        
        self.producer.send(self.config.error_topic, value=error_msg)
        logger.error(f"Sent error to DLQ: {error}")
    
    def get_stats(self) -> Dict[str, int]:
        """Get consumer statistics."""
        return self._stats.copy()
    
    def close(self) -> None:
        """Close consumer and producer."""
        self.consumer.close()
        self.producer.close()
        logger.info(f"Consumer closed. Stats: {self._stats}")
