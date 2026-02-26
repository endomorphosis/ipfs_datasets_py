"""
Batch 332: Integration Tests with Agentic Module
==================================================

Tests integration between ontology/extraction systems and
agentic reasoning components.

Goal: Provide:
- Agent-controlled ontology extraction
- Multi-agent consensus mechanisms
- Workflow coordination tests
- State management across agents
"""

import pytest
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import json


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class AgentRole(Enum):
    """Different agent role types."""
    EXTRACTOR = "extractor"
    VALIDATOR = "validator"
    REASONER = "reasoner"
    CRITIC = "critic"
    ORCHESTRATOR = "orchestrator"


class MessageType(Enum):
    """Types of inter-agent messages."""
    TASK = "task"
    RESULT = "result"
    QUERY = "query"
    RESPONSE = "response"
    CONSENSUS = "consensus"
    ERROR = "error"


@dataclass
class Message:
    """Inter-agent communication message."""
    from_agent: str
    to_agent: str
    message_type: MessageType
    content: Dict[str, Any]
    timestamp: float = 0.0
    
    def to_json(self) -> str:
        """Convert to JSON."""
        return json.dumps({
            "from": self.from_agent,
            "to": self.to_agent,
            "type": self.message_type.value,
            "content": self.content,
        })


@dataclass
class AgentState:
    """State of an agent."""
    agent_id: str
    role: AgentRole
    is_active: bool = True
    messages_received: int = 0
    messages_sent: int = 0
    tasks_completed: int = 0
    errors: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.agent_id,
            "role": self.role.value,
            "active": self.is_active,
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
            "tasks_completed": self.tasks_completed,
            "errors": self.errors,
        }


@dataclass
class WorkflowTask:
    """Task for agents to process."""
    task_id: str
    task_type: str
    input_data: Dict[str, Any]
    required_role: AgentRole
    priority: int = 0
    timeout_seconds: float = 30.0
    completed: bool = False
    result: Optional[Dict[str, Any]] = None


# ============================================================================
# AGENT IMPLEMENTATIONS
# ============================================================================

class Agent:
    """Base agent for ontology processing."""
    
    def __init__(self, agent_id: str, role: AgentRole):
        """Initialize agent.
        
        Args:
            agent_id: Unique agent identifier
            role: Agent's role in the system
        """
        self.agent_id = agent_id
        self.role = role
        self.state = AgentState(agent_id=agent_id, role=role)
        self.inbox = []
        self.outbox = []
        self.knowledge_base = {}
    
    def receive_message(self, message: Message) -> None:
        """Receive an incoming message.
        
        Args:
            message: Message to receive
        """
        self.inbox.append(message)
        self.state.messages_received += 1
    
    def send_message(self, to_agent: str, message_type: MessageType,
                    content: Dict[str, Any]) -> Message:
        """Send a message to another agent.
        
        Args:
            to_agent: Recipient agent ID
            message_type: Type of message
            content: Message content
            
        Returns:
            Message object
        """
        message = Message(
            from_agent=self.agent_id,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
        )
        self.outbox.append(message)
        self.state.messages_sent += 1
        return message
    
    def process_task(self, task: WorkflowTask) -> Dict[str, Any]:
        """Process a task (to be overridden by subclasses).
        
        Args:
            task: Task to process
            
        Returns:
            Task result
        """
        if task.required_role != self.role:
            raise ValueError(f"Task requires {task.required_role}, I am {self.role}")
        
        return {"status": "unknown", "agent": self.agent_id}


class ExtractionAgent(Agent):
    """Agent responsible for entity/relationship extraction."""
    
    def __init__(self, agent_id: str):
        """Initialize extraction agent."""
        super().__init__(agent_id, AgentRole.EXTRACTOR)
    
    def process_task(self, task: WorkflowTask) -> Dict[str, Any]:
        """Extract entities and relationships from text."""
        super().process_task(task)  # Validate role
        
        text = task.input_data.get("text", "")
        
        # Simulate extraction
        words = text.split()
        entities = [f"entity_{i}" for i in range(len(words) // 10 + 1)]
        relationships = [(entities[i], entities[(i+1) % len(entities)]) 
                        for i in range(len(entities) - 1)]
        
        self.state.tasks_completed += 1
        
        return {
            "entities": entities,
            "relationships": relationships,
            "confidence": 0.8,
            "agent": self.agent_id,
        }


class ValidationAgent(Agent):
    """Agent responsible for validating extracted ontologies."""
    
    def __init__(self, agent_id: str):
        """Initialize validation agent."""
        super().__init__(agent_id, AgentRole.VALIDATOR)
    
    def process_task(self, task: WorkflowTask) -> Dict[str, Any]:
        """Validate ontology structure."""
        super().process_task(task)  # Validate role
        
        entities = task.input_data.get("entities", [])
        relationships = task.input_data.get("relationships", [])
        
        # Validate
        is_valid = True
        issues = []
        
        if not entities:
            is_valid = False
            issues.append("No entities found")
        
        # Check for dangling references
        entity_names = set(entities)
        for src, dst in relationships:
            if src not in entity_names or dst not in entity_names:
                is_valid = False
                issues.append(f"Dangling reference: {src} -> {dst}")
        
        self.state.tasks_completed += 1
        
        return {
            "valid": is_valid,
            "issues": issues,
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "agent": self.agent_id,
        }


class ReasoningAgent(Agent):
    """Agent that performs logical reasoning."""
    
    def __init__(self, agent_id: str):
        """Initialize reasoning agent."""
        super().__init__(agent_id, AgentRole.REASONER)
    
    def process_task(self, task: WorkflowTask) -> Dict[str, Any]:
        """Perform reasoning over ontology."""
        super().process_task(task)  # Validate role
        
        entities = task.input_data.get("entities", [])
        relationships = task.input_data.get("relationships", [])
        
        # Simple reasoning: transitive closure
        inferences = []
        for src, dst in relationships:
            # If A -> B, infer properties
            inferences.append(f"{src} is related to {dst}")
        
        self.state.tasks_completed += 1
        
        return {
            "inferences": inferences,
            "reasoning_steps": len(inferences),
            "agent": self.agent_id,
        }


class CriticAgent(Agent):
    """Agent that critiques ontology quality."""
    
    def __init__(self, agent_id: str):
        """Initialize critic agent."""
        super().__init__(agent_id, AgentRole.CRITIC)
    
    def process_task(self, task: WorkflowTask) -> Dict[str, Any]:
        """Critique ontology quality."""
        super().process_task(task)  # Validate role
        
        entities = task.input_data.get("entities", [])
        relationships = task.input_data.get("relationships", [])
        entity_count = len(entities)
        relationship_count = len(relationships)
        
        # Scoring
        completeness = min(1.0, entity_count / 10.0)
        coherence = 0.5 if relationship_count > 0 else 0.0
        
        overall_score = (completeness + coherence) / 2.0
        
        self.state.tasks_completed += 1
        
        return {
            "completeness_score": completeness,
            "coherence_score": coherence,
            "overall_score": overall_score,
            "quality_assessment": "good" if overall_score > 0.6 else "poor",
            "agent": self.agent_id,
        }


class OrchestratorAgent(Agent):
    """Agent that coordinates workflow execution."""
    
    def __init__(self, agent_id: str):
        """Initialize orchestrator agent."""
        super().__init__(agent_id, AgentRole.ORCHESTRATOR)
        self.managed_agents = {}
        self.active_tasks = {}
    
    def register_agent(self, agent: Agent) -> None:
        """Register an agent for management.
        
        Args:
            agent: Agent to register
        """
        self.managed_agents[agent.agent_id] = agent
    
    def assign_task(self, task: WorkflowTask) -> Dict[str, Any]:
        """Assign task to appropriate agent.
        
        Args:
            task: Task to assign
            
        Returns:
            Task assignment result
        """
        # Find agent with matching role
        for agent in self.managed_agents.values():
            if agent.role == task.required_role:
                result = agent.process_task(task)
                self.active_tasks[task.task_id] = result
                return result
        
        return {"error": f"No agent found for role {task.required_role}"}
    
    def collect_results(self) -> Dict[str, Any]:
        """Collect results from all agents.
        
        Returns:
            Aggregated results
        """
        all_results = {}
        for agent_id, agent in self.managed_agents.items():
            all_results[agent_id] = agent.state.to_dict()
        
        return all_results
    
    def get_consensus(self, attribute: str) -> Optional[Any]:
        """Get consensus answer from agents.
        
        Args:
            attribute: Attribute to get consensus on
            
        Returns:
            Consensus value or None if no agreement
        """
        # Not implemented - placeholder for future multi-agent consensus
        return None


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestAgentBasics:
    """Test basic agent functionality."""
    
    def test_agent_creation(self):
        """Test creating an agent."""
        agent = Agent("agent1", AgentRole.EXTRACTOR)
        
        assert agent.agent_id == "agent1"
        assert agent.role == AgentRole.EXTRACTOR
        assert agent.state.is_active
    
    def test_message_sending(self):
        """Test sending messages between agents."""
        agent1 = Agent("agent1", AgentRole.EXTRACTOR)
        agent2 = Agent("agent2", AgentRole.VALIDATOR)
        
        msg = agent1.send_message("agent2", MessageType.TASK, {"data": "test"})
        agent2.receive_message(msg)
        
        assert len(agent1.outbox) == 1
        assert len(agent2.inbox) == 1
        assert agent2.state.messages_received == 1
    
    def test_agent_state_tracking(self):
        """Test agent state tracking."""
        agent = Agent("agent1", AgentRole.EXTRACTOR)
        
        # Send and receive messages
        msg = Message("agent1", "agent2", MessageType.TASK, {})
        agent.send_message("agent2", MessageType.TASK, {})
        agent.receive_message(msg)
        
        state = agent.state
        assert state.messages_sent == 1
        assert state.messages_received == 1


class TestExtractionAgent:
    """Test extraction agent."""
    
    def test_extract_entities(self):
        """Test entity extraction."""
        agent = ExtractionAgent("extractor1")
        
        task = WorkflowTask(
            task_id="extract1",
            task_type="extract",
            input_data={"text": "The patient presented with symptoms"},
            required_role=AgentRole.EXTRACTOR,
        )
        
        result = agent.process_task(task)
        
        assert "entities" in result
        assert len(result["entities"]) > 0
        assert result["confidence"] > 0


class TestValidationAgent:
    """Test validation agent."""
    
    def test_validate_valid_ontology(self):
        """Test validation of valid ontology."""
        agent = ValidationAgent("validator1")
        
        task = WorkflowTask(
            task_id="val1",
            task_type="validate",
            input_data={
                "entities": ["entity1", "entity2", "entity3"],
                "relationships": [("entity1", "entity2"), ("entity2", "entity3")],
            },
            required_role=AgentRole.VALIDATOR,
        )
        
        result = agent.process_task(task)
        
        assert result["valid"] is True
        assert len(result["issues"]) == 0
    
    def test_validate_invalid_ontology(self):
        """Test validation of invalid ontology."""
        agent = ValidationAgent("validator1")
        
        task = WorkflowTask(
            task_id="val2",
            task_type="validate",
            input_data={
                "entities": ["entity1"],
                "relationships": [("entity1", "entity_unknown")],
            },
            required_role=AgentRole.VALIDATOR,
        )
        
        result = agent.process_task(task)
        
        assert result["valid"] is False
        assert len(result["issues"]) > 0


class TestReasoningAgent:
    """Test reasoning agent."""
    
    def test_logical_reasoning(self):
        """Test logical reasoning over ontology."""
        agent = ReasoningAgent("reasoner1")
        
        task = WorkflowTask(
            task_id="reason1",
            task_type="reason",
            input_data={
                "entities": ["A", "B", "C"],
                "relationships": [("A", "B"), ("B", "C")],
            },
            required_role=AgentRole.REASONER,
        )
        
        result = agent.process_task(task)
        
        assert "inferences" in result
        assert len(result["inferences"]) >= 2


class TestCriticAgent:
    """Test critic agent."""
    
    def test_critique_quality(self):
        """Test quality critique."""
        agent = CriticAgent("critic1")
        
        task = WorkflowTask(
            task_id="crit1",
            task_type="critique",
            input_data={
                "entities": ["e1", "e2", "e3", "e4", "e5"],
                "relationships": [("e1", "e2"), ("e2", "e3")],
            },
            required_role=AgentRole.CRITIC,
        )
        
        result = agent.process_task(task)
        
        assert "overall_score" in result
        assert 0.0 <= result["overall_score"] <= 1.0
        assert result["quality_assessment"] in ["good", "poor"]


class TestOrchestratorAgent:
    """Test orchestrator agent."""
    
    def test_agent_registration(self):
        """Test registering agents."""
        orchestrator = OrchestratorAgent("orchestrator1")
        extractor = ExtractionAgent("extractor1")
        validator = ValidationAgent("validator1")
        
        orchestrator.register_agent(extractor)
        orchestrator.register_agent(validator)
        
        assert len(orchestrator.managed_agents) == 2
    
    def test_task_assignment(self):
        """Test task assignment."""
        orchestrator = OrchestratorAgent("orchestrator1")
        extractor = ExtractionAgent("extractor1")
        
        orchestrator.register_agent(extractor)
        
        task = WorkflowTask(
            task_id="task1",
            task_type="extract",
            input_data={"text": "test text"},
            required_role=AgentRole.EXTRACTOR,
        )
        
        result = orchestrator.assign_task(task)
        
        assert "entities" in result
        assert task.task_id in orchestrator.active_tasks
    
    def test_collect_results(self):
        """Test collecting results from agents."""
        orchestrator = OrchestratorAgent("orchestrator1")
        extractor = ExtractionAgent("extractor1")
        validator = ValidationAgent("validator1")
        
        orchestrator.register_agent(extractor)
        orchestrator.register_agent(validator)
        
        # Run some tasks
        ext_task = WorkflowTask(
            task_id="e1",
            task_type="extract",
            input_data={"text": "test"},
            required_role=AgentRole.EXTRACTOR,
        )
        orchestrator.assign_task(ext_task)
        
        results = orchestrator.collect_results()
        
        assert len(results) == 2
        assert "extractor1" in results
        assert "validator1" in results


class TestMultiAgentWorkflow:
    """Test multi-agent workflow coordination."""
    
    def test_extraction_validation_workflow(self):
        """Test extract -> validate workflow."""
        orchestrator = OrchestratorAgent("orchestrator1")
        extractor = ExtractionAgent("extractor1")
        validator = ValidationAgent("validator1")
        
        orchestrator.register_agent(extractor)
        orchestrator.register_agent(validator)
        
        # Extract
        extract_task = WorkflowTask(
            task_id="extract1",
            task_type="extract",
            input_data={"text": "The patient has diabetes. Doctor prescribed medication."},
            required_role=AgentRole.EXTRACTOR,
        )
        
        extract_result = orchestrator.assign_task(extract_task)
        
        # Validate
        validate_task = WorkflowTask(
            task_id="validate1",
            task_type="validate",
            input_data={
                "entities": extract_result["entities"],
                "relationships": extract_result["relationships"],
            },
            required_role=AgentRole.VALIDATOR,
        )
        
        validate_result = orchestrator.assign_task(validate_task)
        
        assert validate_result["entity_count"] > 0
    
    def test_full_pipeline_workflow(self):
        """Test complete extraction -> validation -> reasoning -> critique pipeline."""
        orchestrator = OrchestratorAgent("orchestrator1")
        
        # Register all agents
        orchestrator.register_agent(ExtractionAgent("extractor1"))
        orchestrator.register_agent(ValidationAgent("validator1"))
        orchestrator.register_agent(ReasoningAgent("reasoner1"))
        orchestrator.register_agent(CriticAgent("critic1"))
        
        # Step 1: Extract
        text = "Patient presented with symptoms. Doctor examined. Diagnosis confirmed."
        extract_task = WorkflowTask(
            task_id="step1",
            task_type="extract",
            input_data={"text": text},
            required_role=AgentRole.EXTRACTOR,
        )
        extract_result = orchestrator.assign_task(extract_task)
        
        # Step 2: Validate
        validate_task = WorkflowTask(
            task_id="step2",
            task_type="validate",
            input_data={
                "entities": extract_result["entities"],
                "relationships": extract_result["relationships"],
            },
            required_role=AgentRole.VALIDATOR,
        )
        validate_result = orchestrator.assign_task(validate_task)
        
        assert validate_result["valid"] or len(validate_result["issues"]) > 0
        
        # Step 3: Reason
        reason_task = WorkflowTask(
            task_id="step3",
            task_type="reason",
            input_data={
                "entities": extract_result["entities"],
                "relationships": extract_result["relationships"],
            },
            required_role=AgentRole.REASONER,
        )
        reason_result = orchestrator.assign_task(reason_task)
        
        # Step 4: Critique
        critique_task = WorkflowTask(
            task_id="step4",
            task_type="critique",
            input_data={
                "entities": extract_result["entities"],
                "relationships": extract_result["relationships"],
            },
            required_role=AgentRole.CRITIC,
        )
        critique_result = orchestrator.assign_task(critique_task)
        
        assert 0.0 <= critique_result["overall_score"] <= 1.0
    
    def test_agent_communication_flow(self):
        """Test communication between agents."""
        agent1 = ExtractionAgent("ext1")
        agent2 = ValidationAgent("val1")
        
        # Agent 1 sends task to Agent 2
        msg1 = agent1.send_message(
            "val1",
            MessageType.TASK,
            {"entities": ["e1", "e2"], "relationships": []}
        )
        
        # Agent 2 receives and processes
        agent2.receive_message(msg1)
        
        # Agent 2 sends result back
        msg2 = agent2.send_message(
            "ext1",
            MessageType.RESPONSE,
            {"valid": True, "issues": []}
        )
        
        agent1.receive_message(msg2)
        
        assert len(agent1.outbox) == 1
        assert len(agent2.outbox) == 1
        assert len(agent1.inbox) == 1
        assert len(agent2.inbox) == 1
