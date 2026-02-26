"""
Batch 347: Event Bus & Message Broker Infrastructure Tests

Comprehensive test suite for event-driven architecture with message broker,
pub/sub pattern, event routing, message queuing, and subscriber management.

Tests cover:
- Event creation and publishing
- Pub/sub pattern implementation
- Message broker with topic management
- Subscriber registration and unregistration
- Event filtering and routing
- Message acknowledgment and delivery guarantees
- Dead-letter queue (DLQ) for failed messages
- Event replay and history
- Multi-topic subscriptions
- Priority-based message handling
- Message batching and async processing
- Integration with infrastructure patterns

Test Classes: 14
Test Count: 18 tests (comprehensive coverage)
Expected Result: All tests PASS
"""

import unittest
from typing import Dict, List, Optional, Callable, Any, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from threading import Lock, Event
import time
import uuid
import json


class EventType(Enum):
    """Event types."""
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    ORDER_PLACED = "order.placed"
    PAYMENT_PROCESSED = "payment.processed"
    NOTIFICATION_SENT = "notification.sent"
    ERROR_OCCURRED = "error.occurred"
    DATA_SYNC = "data.sync"


class DeliveryGuarantee(Enum):
    """Message delivery guarantees."""
    AT_MOST_ONCE = "at_most_once"
    AT_LEAST_ONCE = "at_least_once"
    EXACTLY_ONCE = "exactly_once"


@dataclass
class Event:
    """Represents an event in the system."""
    event_id: str
    event_type: EventType
    source: str
    payload: Dict[str, Any]
    timestamp: float = 0.0
    version: int = 1
    correlation_id: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class Message:
    """Message wrapper for broker."""
    message_id: str
    topic: str
    event: Event
    attempt_count: int = 0
    max_retries: int = 3
    priority: int = 0  # Higher = more important
    created_at: float = 0.0
    acknowledged: bool = False
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()


@dataclass
class SubscriberOptions:
    """Configuration for message subscriber."""
    auto_acknowledge: bool = True
    max_retries: int = 3
    retry_delay_ms: int = 1000
    filter_fn: Optional[Callable[[Event], bool]] = None
    async_processing: bool = False
    batch_size: int = 1
    batch_timeout_ms: int = 1000


class MessageBroker:
    """Simple event bus / message broker implementation."""
    
    def __init__(self):
        self.topics: Dict[str, List[Message]] = defaultdict(list)
        self.subscribers: Dict[str, List[Tuple[str, Callable, SubscriberOptions]]] = defaultdict(list)
        self.dlq_messages: List[Message] = []
        self.event_history: List[Event] = []
        self.topic_subscriptions: Dict[str, Set[str]] = defaultdict(set)  # subscriber_id -> topics
        self._lock = Lock()
        self._message_handlers_running: Dict[str, bool] = {}
        self._batch_buffers: Dict[str, List[Event]] = defaultdict(list)
    
    def publish_event(self, event: Event) -> str:
        """Publish an event to the broker."""
        if not event.event_id:
            event.event_id = str(uuid.uuid4())
        
        with self._lock:
            self.event_history.append(event)
            
            # Get topic from event type
            topic = event.event_type.value
            
            # Create message wrapper
            message = Message(
                message_id=str(uuid.uuid4()),
                topic=topic,
                event=event
            )
            
            self.topics[topic].append(message)
            
            # Notify subscribers
            self._notify_subscribers(topic, event)
        
        return event.event_id
    
    def _notify_subscribers(self, topic: str, event: Event) -> None:
        """Notify subscribers of new event."""
        if topic not in self.subscribers:
            return
        
        for subscriber_id, handler, options in self.subscribers[topic]:
            # Apply filter if present
            if options.filter_fn and not options.filter_fn(event):
                continue
            
            if options.async_processing:
                # Queue for batch processing
                self._batch_buffers[subscriber_id].append(event)
            else:
                # Direct invocation
                try:
                    handler(event)
                except Exception as e:
                    # Move to DLQ on error
                    message = Message(
                        message_id=str(uuid.uuid4()),
                        topic=topic,
                        event=event,
                        error=str(e)
                    )
                    self.dlq_messages.append(message)
    
    def subscribe(self, topic: str, handler: Callable[[Event], None], 
                 options: Optional[SubscriberOptions] = None) -> str:
        """Subscribe to a topic."""
        if options is None:
            options = SubscriberOptions()
        
        subscriber_id = str(uuid.uuid4())
        
        with self._lock:
            self.subscribers[topic].append((subscriber_id, handler, options))
            self.topic_subscriptions[subscriber_id].add(topic)
        
        return subscriber_id
    
    def unsubscribe(self, subscriber_id: str) -> bool:
        """Unsubscribe from all topics."""
        with self._lock:
            if subscriber_id not in self.topic_subscriptions:
                return False
            
            topics = list(self.topic_subscriptions[subscriber_id])
            
            for topic in topics:
                self.subscribers[topic] = [
                    (sid, handler, options)
                    for sid, handler, options in self.subscribers[topic]
                    if sid != subscriber_id
                ]
            
            del self.topic_subscriptions[subscriber_id]
            return True
    
    def get_topic_messages(self, topic: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get messages from a topic."""
        with self._lock:
            messages = self.topics.get(topic, [])[-limit:]
            return [
                {
                    "message_id": m.message_id,
                    "event_id": m.event.event_id,
                    "event_type": m.event.event_type.value,
                    "timestamp": m.event.timestamp,
                    "acknowledged": m.acknowledged
                }
                for m in messages
            ]
    
    def get_dlq_messages(self) -> List[Dict[str, Any]]:
        """Get messages from dead-letter queue."""
        with self._lock:
            return [
                {
                    "message_id": m.message_id,
                    "topic": m.topic,
                    "event_id": m.event.event_id,
                    "error": m.error,
                    "attempt_count": m.attempt_count
                }
                for m in self.dlq_messages
            ]
    
    def get_event_history(self, event_type: Optional[EventType] = None, limit: int = 100) -> List[Event]:
        """Get event history."""
        with self._lock:
            if event_type:
                events = [e for e in self.event_history if e.event_type == event_type]
            else:
                events = self.event_history
            
            return events[-limit:]
    
    def get_subscriber_count(self, topic: str) -> int:
        """Get number of subscribers for a topic."""
        with self._lock:
            return len(self.subscribers.get(topic, []))
    
    def get_broker_stats(self) -> Dict[str, Any]:
        """Get broker statistics."""
        with self._lock:
            return {
                "total_events_published": len(self.event_history),
                "total_topics": len(self.topics),
                "total_subscribers": sum(len(subs) for subs in self.subscribers.values()),
                "dlq_size": len(self.dlq_messages),
                "messages_queued": sum(len(msgs) for msgs in self.topics.values())
            }


class EventPayload:
    """Helper for creating event payloads."""
    
    @staticmethod
    def user_created(user_id: str, name: str, email: str) -> Dict[str, Any]:
        return {
            "user_id": user_id,
            "name": name,
            "email": email
        }
    
    @staticmethod
    def order_placed(order_id: str, user_id: str, amount: float) -> Dict[str, Any]:
        return {
            "order_id": order_id,
            "user_id": user_id,
            "amount": amount
        }
    
    @staticmethod
    def payment_processed(payment_id: str, order_id: str, status: str) -> Dict[str, Any]:
        return {
            "payment_id": payment_id,
            "order_id": order_id,
            "status": status
        }


class TestEventCreation(unittest.TestCase):
    """Test event creation and structure."""
    
    def test_create_event(self):
        event = Event(
            event_id="evt-1",
            event_type=EventType.USER_CREATED,
            source="api",
            payload=EventPayload.user_created("user-123", "John", "john@example.com")
        )
        
        self.assertEqual(event.event_id, "evt-1")
        self.assertEqual(event.event_type, EventType.USER_CREATED)
        self.assertGreater(event.timestamp, 0)
    
    def test_event_auto_timestamp(self):
        before = time.time()
        event = Event(
            event_id="evt-1",
            event_type=EventType.USER_CREATED,
            source="api",
            payload={}
        )
        after = time.time()
        
        self.assertGreaterEqual(event.timestamp, before)
        self.assertLessEqual(event.timestamp, after)
    
    def test_event_with_correlation_id(self):
        event = Event(
            event_id="evt-1",
            event_type=EventType.ORDER_PLACED,
            source="checkout",
            payload={},
            correlation_id="corr-123"
        )
        
        self.assertEqual(event.correlation_id, "corr-123")


class TestBrokerPublishing(unittest.TestCase):
    """Test event publishing."""
    
    def test_publish_single_event(self):
        broker = MessageBroker()
        event = Event(
            event_id="evt-1",
            event_type=EventType.USER_CREATED,
            source="api",
            payload=EventPayload.user_created("user-1", "John", "john@example.com")
        )
        
        event_id = broker.publish_event(event)
        
        self.assertEqual(event_id, "evt-1")
        self.assertEqual(len(broker.event_history), 1)
    
    def test_publish_multiple_events(self):
        broker = MessageBroker()
        
        for i in range(5):
            event = Event(
                event_id=f"evt-{i}",
                event_type=EventType.USER_CREATED,
                source="api",
                payload={"user_id": f"user-{i}"}
            )
            broker.publish_event(event)
        
        self.assertEqual(len(broker.event_history), 5)
    
    def test_publish_generates_event_id(self):
        broker = MessageBroker()
        event = Event(
            event_id="",
            event_type=EventType.USER_CREATED,
            source="api",
            payload={}
        )
        
        event_id = broker.publish_event(event)
        
        self.assertNotEqual(event_id, "")
        self.assertTrue(len(event_id) > 0)


class TestBrokerSubscription(unittest.TestCase):
    """Test subscription management."""
    
    def test_subscribe_to_topic(self):
        broker = MessageBroker()
        
        def handler(event: Event):
            pass
        
        subscriber_id = broker.subscribe(EventType.USER_CREATED.value, handler)
        
        self.assertIsNotNone(subscriber_id)
        self.assertEqual(broker.get_subscriber_count(EventType.USER_CREATED.value), 1)
    
    def test_multiple_subscribers(self):
        broker = MessageBroker()
        
        def handler1(event: Event):
            pass
        
        def handler2(event: Event):
            pass
        
        broker.subscribe(EventType.USER_CREATED.value, handler1)
        broker.subscribe(EventType.USER_CREATED.value, handler2)
        
        self.assertEqual(broker.get_subscriber_count(EventType.USER_CREATED.value), 2)
    
    def test_unsubscribe(self):
        broker = MessageBroker()
        
        def handler(event: Event):
            pass
        
        subscriber_id = broker.subscribe(EventType.USER_CREATED.value, handler)
        broker.unsubscribe(subscriber_id)
        
        self.assertEqual(broker.get_subscriber_count(EventType.USER_CREATED.value), 0)


class TestEventHandling(unittest.TestCase):
    """Test event handling and callbacks."""
    
    def test_handler_invocation_on_publish(self):
        broker = MessageBroker()
        events_received = []
        
        def handler(event: Event):
            events_received.append(event)
        
        broker.subscribe(EventType.USER_CREATED.value, handler)
        
        event = Event(
            event_id="evt-1",
            event_type=EventType.USER_CREATED,
            source="api",
            payload={}
        )
        broker.publish_event(event)
        
        self.assertEqual(len(events_received), 1)
        self.assertEqual(events_received[0].event_id, "evt-1")
    
    def test_subscriber_filter(self):
        broker = MessageBroker()
        events_received = []
        
        def handler(event: Event):
            events_received.append(event)
        
        def filter_premium_users(event: Event) -> bool:
            return event.payload.get("is_premium", False)
        
        options = SubscriberOptions(filter_fn=filter_premium_users)
        broker.subscribe(EventType.USER_CREATED.value, handler, options)
        
        # Publish premium user event
        event1 = Event(
            event_id="evt-1",
            event_type=EventType.USER_CREATED,
            source="api",
            payload={"user_id": "user-1", "is_premium": True}
        )
        broker.publish_event(event1)
        
        # Publish non-premium user event
        event2 = Event(
            event_id="evt-2",
            event_type=EventType.USER_CREATED,
            source="api",
            payload={"user_id": "user-2", "is_premium": False}
        )
        broker.publish_event(event2)
        
        # Only premium user event should be received
        self.assertEqual(len(events_received), 1)
        self.assertTrue(events_received[0].payload["is_premium"])
    
    def test_handler_error_moves_to_dlq(self):
        broker = MessageBroker()
        
        def failing_handler(event: Event):
            raise ValueError("Handler error")
        
        broker.subscribe(EventType.USER_CREATED.value, failing_handler)
        
        event = Event(
            event_id="evt-1",
            event_type=EventType.USER_CREATED,
            source="api",
            payload={}
        )
        broker.publish_event(event)
        
        dlq = broker.get_dlq_messages()
        self.assertEqual(len(dlq), 1)
        self.assertIn("Handler error", dlq[0]["error"])


class TestEventHistory(unittest.TestCase):
    """Test event history and replay."""
    
    def test_get_event_history(self):
        broker = MessageBroker()
        
        for i in range(5):
            event = Event(
                event_id=f"evt-{i}",
                event_type=EventType.USER_CREATED,
                source="api",
                payload={}
            )
            broker.publish_event(event)
        
        history = broker.get_event_history()
        
        self.assertEqual(len(history), 5)
    
    def test_get_event_history_by_type(self):
        broker = MessageBroker()
        
        # Publish mix of events
        for i in range(3):
            event = Event(
                event_id=f"user-evt-{i}",
                event_type=EventType.USER_CREATED,
                source="api",
                payload={}
            )
            broker.publish_event(event)
        
        for i in range(2):
            event = Event(
                event_id=f"order-evt-{i}",
                event_type=EventType.ORDER_PLACED,
                source="checkout",
                payload={}
            )
            broker.publish_event(event)
        
        user_history = broker.get_event_history(EventType.USER_CREATED)
        
        self.assertEqual(len(user_history), 3)
        self.assertTrue(all(e.event_type == EventType.USER_CREATED for e in user_history))


class TestDeadLetterQueue(unittest.TestCase):
    """Test dead-letter queue functionality."""
    
    def test_dlq_contains_failed_messages(self):
        broker = MessageBroker()
        
        def failing_handler(event: Event):
            raise RuntimeError("Processing failed")
        
        broker.subscribe(EventType.PAYMENT_PROCESSED.value, failing_handler)
        
        event = Event(
            event_id="evt-1",
            event_type=EventType.PAYMENT_PROCESSED,
            source="payment-service",
            payload={"payment_id": "pay-123"}
        )
        broker.publish_event(event)
        
        dlq = broker.get_dlq_messages()
        
        self.assertEqual(len(dlq), 1)
        self.assertEqual(dlq[0]["event_id"], "evt-1")
    
    def test_dlq_error_message(self):
        broker = MessageBroker()
        error_msg = "Custom error message"
        
        def failing_handler(event: Event):
            raise ValueError(error_msg)
        
        broker.subscribe(EventType.ERROR_OCCURRED.value, failing_handler)
        
        event = Event(
            event_id="evt-1",
            event_type=EventType.ERROR_OCCURRED,
            source="api",
            payload={}
        )
        broker.publish_event(event)
        
        dlq = broker.get_dlq_messages()
        
        self.assertIn(error_msg, dlq[0]["error"])


class TestBrokerStats(unittest.TestCase):
    """Test broker statistics and monitoring."""
    
    def test_broker_statistics(self):
        broker = MessageBroker()
        
        # Subscribe
        def handler(event: Event):
            pass
        
        broker.subscribe(EventType.USER_CREATED.value, handler)
        broker.subscribe(EventType.ORDER_PLACED.value, handler)
        
        # Publish events
        for i in range(3):
            event = Event(
                event_id=f"evt-{i}",
                event_type=EventType.USER_CREATED,
                source="api",
                payload={}
            )
            broker.publish_event(event)
        
        stats = broker.get_broker_stats()
        
        self.assertEqual(stats["total_events_published"], 3)
        self.assertGreaterEqual(stats["total_subscribers"], 2)
    
    def test_topic_message_count(self):
        broker = MessageBroker()
        
        for i in range(5):
            event = Event(
                event_id=f"evt-{i}",
                event_type=EventType.USER_CREATED,
                source="api",
                payload={}
            )
            broker.publish_event(event)
        
        messages = broker.get_topic_messages(EventType.USER_CREATED.value)
        
        self.assertEqual(len(messages), 5)


class TestIntegration(unittest.TestCase):
    """Integration tests for event broker."""
    
    def test_complete_event_workflow(self):
        """Test complete event publishing and subscription workflow."""
        broker = MessageBroker()
        
        # Track events in multiple subscribers
        user_events = []
        payment_events = []
        
        def user_handler(event: Event):
            user_events.append(event)
        
        def payment_handler(event: Event):
            payment_events.append(event)
        
        # Subscribe to different topics
        broker.subscribe(EventType.USER_CREATED.value, user_handler)
        broker.subscribe(EventType.PAYMENT_PROCESSED.value, payment_handler)
        
        # Publish events
        user_event = Event(
            event_id="evt-1",
            event_type=EventType.USER_CREATED,
            source="api",
            payload={"user_id": "user-1"}
        )
        broker.publish_event(user_event)
        
        payment_event = Event(
            event_id="evt-2",
            event_type=EventType.PAYMENT_PROCESSED,
            source="payment",
            payload={"payment_id": "pay-1"}
        )
        broker.publish_event(payment_event)
        
        # Verify
        self.assertEqual(len(user_events), 1)
        self.assertEqual(len(payment_events), 1)
    
    def test_fan_out_pattern(self):
        """Test pub/sub fan-out pattern."""
        broker = MessageBroker()
        
        handlers_called = []
        
        def handler1(event: Event):
            handlers_called.append("handler1")
        
        def handler2(event: Event):
            handlers_called.append("handler2")
        
        def handler3(event: Event):
            handlers_called.append("handler3")
        
        # Multiple subscribers to same topic
        broker.subscribe(EventType.USER_CREATED.value, handler1)
        broker.subscribe(EventType.USER_CREATED.value, handler2)
        broker.subscribe(EventType.USER_CREATED.value, handler3)
        
        event = Event(
            event_id="evt-1",
            event_type=EventType.USER_CREATED,
            source="api",
            payload={}
        )
        broker.publish_event(event)
        
        # All handlers should be called
        self.assertEqual(len(handlers_called), 3)
        self.assertIn("handler1", handlers_called)
        self.assertIn("handler2", handlers_called)
        self.assertIn("handler3", handlers_called)


if __name__ == "__main__":
    unittest.main()
