"""
Comprehensive test suite for REST API endpoints.

Test coverage:
- Health check endpoint
- Entity CRUD operations
- Relationship CRUD operations
- Consensus endpoint
- Comparison endpoint
- Memory profiling endpoints
- Error handling
- Pagination
- Validation
- Response models
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from ipfs_datasets_py.optimizers.api.rest_api import (
    APIServer,
    EntityRequest,
    EntityResponse,
    RelationshipRequest,
    RelationshipResponse,
    ConsensusRequest,
    AgentVoteRequest,
    ComparisonRequest,
    EntityType,
    RelationshipType,
)
from ipfs_datasets_py.optimizers.common import metrics_prometheus


@pytest.fixture
def api_server():
    """Create API server instance for testing."""
    return APIServer(title="Test API", version="1.0.0-test")


@pytest.fixture
def client(api_server):
    """Create test client."""
    return TestClient(api_server.get_app())


@pytest.fixture
def sample_entity_request():
    """Sample entity request."""
    return EntityRequest(
        name="Test Entity",
        entity_type=EntityType.PERSON,
        description="A test entity",
        confidence=0.95
    )


@pytest.fixture
def sample_relationship_request():
    """Sample relationship request."""
    return RelationshipRequest(
        source_id="entity_1",
        target_id="entity_2",
        relationship_type=RelationshipType.WORKS_FOR,
        confidence=0.85
    )


class TestHealthEndpoint:
    """Tests for health check endpoint."""
    
    def test_health_check_status_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
    
    def test_health_check_response_format(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data
    
    def test_health_check_version(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["version"] == "1.0.0-test"


class TestMetricsEndpoint:
    """Tests for Prometheus metrics endpoint."""

    def test_metrics_endpoint_enabled(self, client, monkeypatch):
        monkeypatch.setenv("ENABLE_PROMETHEUS", "true")
        metrics_prometheus._GLOBAL_PROMETHEUS_METRICS = None

        response = client.get("/metrics")
        assert response.status_code == 200
        assert "optimizer_score" in response.text

    def test_metrics_endpoint_disabled(self, client, monkeypatch):
        monkeypatch.setenv("ENABLE_PROMETHEUS", "false")
        metrics_prometheus._GLOBAL_PROMETHEUS_METRICS = None

        response = client.get("/metrics")
        assert response.status_code == 200
        assert "disabled" in response.text.lower()


class TestEntityEndpoints:
    """Tests for entity CRUD endpoints."""
    
    def test_create_entity_success(self, client, sample_entity_request):
        response = client.post("/entities", json=sample_entity_request.dict())
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Entity"
        assert data["entity_type"] == "person"
        assert data["confidence"] == pytest.approx(0.95)
        assert "id" in data
        assert "created_at" in data
    
    def test_create_entity_invalid_confidence(self, client):
        invalid_entity = {
            "name": "Test",
            "entity_type": "person",
            "confidence": 1.5  # Invalid: > 1.0
        }
        response = client.post("/entities", json=invalid_entity)
        assert response.status_code == 422
    
    def test_create_entity_empty_name(self, client):
        invalid_entity = {
            "name": "",
            "entity_type": "person"
        }
        response = client.post("/entities", json=invalid_entity)
        assert response.status_code == 422
    
    def test_get_entity_success(self, client, sample_entity_request):
        # Create entity first
        create_response = client.post("/entities", json=sample_entity_request.dict())
        entity_id = create_response.json()["id"]
        
        # Get entity
        get_response = client.get(f"/entities/{entity_id}")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["id"] == entity_id
        assert data["name"] == "Test Entity"
    
    def test_get_entity_not_found(self, client):
        response = client.get("/entities/nonexistent_id")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_update_entity_success(self, client, sample_entity_request):
        # Create entity
        create_response = client.post("/entities", json=sample_entity_request.dict())
        entity_id = create_response.json()["id"]
        
        # Update entity
        updated_data = sample_entity_request.dict()
        updated_data["name"] = "Updated Entity"
        updated_data["confidence"] = 0.75
        
        update_response = client.put(f"/entities/{entity_id}", json=updated_data)
        assert update_response.status_code == 200
        data = update_response.json()
        assert data["name"] == "Updated Entity"
        assert data["confidence"] == pytest.approx(0.75)
    
    def test_update_entity_not_found(self, client, sample_entity_request):
        response = client.put("/entities/nonexistent_id", json=sample_entity_request.dict())
        assert response.status_code == 404
    
    def test_delete_entity_success(self, client, sample_entity_request):
        # Create entity
        create_response = client.post("/entities", json=sample_entity_request.dict())
        entity_id = create_response.json()["id"]
        
        # Delete entity
        delete_response = client.delete(f"/entities/{entity_id}")
        assert delete_response.status_code == 200
        assert "deleted" in delete_response.json()["message"].lower()
        
        # Verify deleted
        get_response = client.get(f"/entities/{entity_id}")
        assert get_response.status_code == 404
    
    def test_delete_entity_not_found(self, client):
        response = client.delete("/entities/nonexistent_id")
        assert response.status_code == 404
    
    def test_list_entities_empty(self, client):
        response = client.get("/entities")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_list_entities_with_data(self, client, sample_entity_request):
        # Create multiple entities
        for i in range(5):
            entity_data = sample_entity_request.dict()
            entity_data["name"] = f"Entity {i}"
            client.post("/entities", json=entity_data)
        
        # List entities
        response = client.get("/entities")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5
    
    def test_list_entities_pagination(self, client, sample_entity_request):
        # Create entities
        for i in range(15):
            entity_data = sample_entity_request.dict()
            entity_data["name"] = f"Entity {i}"
            client.post("/entities", json=entity_data)
        
        # Get first page
        response = client.get("/entities?skip=0&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5
        
        # Get second page
        response = client.get("/entities?skip=5&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5
    
    def test_list_entities_limit_boundary(self, client, sample_entity_request):
        # Try with limit > 100 (should be rejected)
        response = client.get("/entities?limit=101")
        assert response.status_code == 422


class TestRelationshipEndpoints:
    """Tests for relationship CRUD endpoints."""
    
    def test_create_relationship_success(self, client, sample_relationship_request):
        response = client.post("/relationships", json=sample_relationship_request.dict())
        assert response.status_code == 200
        data = response.json()
        assert data["source_id"] == "entity_1"
        assert data["target_id"] == "entity_2"
        assert data["relationship_type"] == "works_for"
        assert "id" in data
    
    def test_create_relationship_invalid_source(self, client):
        invalid_rel = {
            "source_id": "",
            "target_id": "entity_2",
            "relationship_type": "works_for"
        }
        response = client.post("/relationships", json=invalid_rel)
        assert response.status_code == 422
    
    def test_create_relationship_invalid_confidence(self, client):
        invalid_rel = {
            "source_id": "entity_1",
            "target_id": "entity_2",
            "relationship_type": "works_for",
            "confidence": -0.5  # Invalid
        }
        response = client.post("/relationships", json=invalid_rel)
        assert response.status_code == 422
    
    def test_get_relationship_success(self, client, sample_relationship_request):
        # Create relationship
        create_response = client.post("/relationships", json=sample_relationship_request.dict())
        rel_id = create_response.json()["id"]
        
        # Get relationship
        get_response = client.get(f"/relationships/{rel_id}")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["id"] == rel_id
    
    def test_get_relationship_not_found(self, client):
        response = client.get("/relationships/nonexistent_id")
        assert response.status_code == 404
    
    def test_delete_relationship_success(self, client, sample_relationship_request):
        # Create relationship
        create_response = client.post("/relationships", json=sample_relationship_request.dict())
        rel_id = create_response.json()["id"]
        
        # Delete relationship
        delete_response = client.delete(f"/relationships/{rel_id}")
        assert delete_response.status_code == 200
        
        # Verify deleted
        get_response = client.get(f"/relationships/{rel_id}")
        assert get_response.status_code == 404
    
    def test_list_relationships_empty(self, client):
        response = client.get("/relationships")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0
    
    def test_list_relationships_with_data(self, client, sample_relationship_request):
        # Create multiple relationships
        for i in range(3):
            rel_data = sample_relationship_request.dict()
            rel_data["source_id"] = f"entity_{i}"
            client.post("/relationships", json=rel_data)
        
        # List relationships
        response = client.get("/relationships")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3


class TestConsensusEndpoint:
    """Tests for consensus endpoint."""
    
    def test_consensus_single_vote(self, client):
        entity = {
            "name": "Test",
            "entity_type": "person",
            "confidence": 0.9
        }
        rel = {
            "source_id": "e1",
            "target_id": "e2",
            "relationship_type": "works_for",
            "confidence": 0.8
        }
        
        consensus_req = {
            "votes": [
                {
                    "agent_id": "agent_1",
                    "entities": [entity],
                    "relationships": [rel],
                    "confidence": 0.9
                }
            ],
            "strategy": "majority"
        }
        
        response = client.post("/consensus", json=consensus_req)
        assert response.status_code == 200
        data = response.json()
        assert "consensus_entities" in data
        assert "consensus_relationships" in data
        assert "agreement_rate" in data
        assert "entropy" in data
        assert "timestamp" in data
    
    def test_consensus_multiple_votes(self, client):
        entity = {
            "name": "Test",
            "entity_type": "person",
            "confidence": 0.9
        }
        rel = {
            "source_id": "e1",
            "target_id": "e2",
            "relationship_type": "works_for",
            "confidence": 0.8
        }
        
        consensus_req = {
            "votes": [
                {
                    "agent_id": "agent_1",
                    "entities": [entity],
                    "relationships": [rel],
                    "confidence": 0.9
                },
                {
                    "agent_id": "agent_2",
                    "entities": [entity],
                    "relationships": [rel],
                    "confidence": 0.85
                },
                {
                    "agent_id": "agent_3",
                    "entities": [entity],
                    "relationships": [rel],
                    "confidence": 0.8
                }
            ],
            "strategy": "majority"
        }
        
        response = client.post("/consensus", json=consensus_req)
        assert response.status_code == 200
        data = response.json()
        assert data["agreement_rate"] > 0
        assert data["agreement_rate"] <= 1.0
    
    def test_consensus_different_strategies(self, client):
        entity = {"name": "Test", "entity_type": "person"}
        rel = {"source_id": "e1", "target_id": "e2", "relationship_type": "works_for"}
        
        for strategy in ["majority", "unanimous", "weighted", "threshold", "qualified_majority"]:
            consensus_req = {
                "votes": [
                    {
                        "agent_id": "agent_1",
                        "entities": [entity],
                        "relationships": [rel],
                        "confidence": 0.9
                    }
                ],
                "strategy": strategy
            }
            
            response = client.post("/consensus", json=consensus_req)
            assert response.status_code == 200
            data = response.json()
            assert strategy in data["strategies_applied"]
    
    def test_consensus_invalid_strategy(self, client):
        consensus_req = {
            "votes": [],
            "strategy": "invalid_strategy"
        }
        
        response = client.post("/consensus", json=consensus_req)
        assert response.status_code == 422


class TestComparisonEndpoint:
    """Tests for comparison endpoint."""
    
    def test_comparison_basic(self, client):
        entity = {"name": "Test", "entity_type": "person"}
        rel = {"source_id": "e1", "target_id": "e2", "relationship_type": "works_for"}
        
        comparison_req = {
            "baseline_entities": [entity, entity, entity],
            "baseline_relationships": [rel, rel],
            "optimized_entities": [entity, entity],
            "optimized_relationships": [rel]
        }
        
        response = client.post("/compare", json=comparison_req)
        assert response.status_code == 200
        data = response.json()
        assert "memory_saved_mb" in data
        assert "memory_saved_percent" in data
        assert "improvement_ratio" in data
        assert "entity_reduction_percent" in data
        assert "relationship_reduction_percent" in data
        assert "recommendation" in data
        assert "timestamp" in data
    
    def test_comparison_no_reduction(self, client):
        entity = {"name": "Test", "entity_type": "person"}
        rel = {"source_id": "e1", "target_id": "e2", "relationship_type": "works_for"}
        
        comparison_req = {
            "baseline_entities": [entity],
            "baseline_relationships": [rel],
            "optimized_entities": [entity],
            "optimized_relationships": [rel]
        }
        
        response = client.post("/compare", json=comparison_req)
        assert response.status_code == 200
        data = response.json()
        assert data["entity_reduction_percent"] == 0.0
        assert data["relationship_reduction_percent"] == 0.0
    
    def test_comparison_full_reduction(self, client):
        entity = {"name": "Test", "entity_type": "person"}
        rel = {"source_id": "e1", "target_id": "e2", "relationship_type": "works_for"}
        
        comparison_req = {
            "baseline_entities": [entity, entity],
            "baseline_relationships": [rel, rel],
            "optimized_entities": [],
            "optimized_relationships": []
        }
        
        response = client.post("/compare", json=comparison_req)
        assert response.status_code == 200
        data = response.json()
        assert data["entity_reduction_percent"] == pytest.approx(100.0)
        assert data["relationship_reduction_percent"] == pytest.approx(100.0)


class TestMemoryEndpoints:
    """Tests for memory profiling endpoints."""
    
    def test_memory_snapshot_success(self, client):
        response = client.get("/memory/snapshot")
        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert "current_memory_mb" in data
        assert "peak_memory_mb" in data
        assert "total_allocated_mb" in data
        assert "object_count" in data
        assert "gc_collections" in data
    
    def test_memory_snapshot_values(self, client):
        response = client.get("/memory/snapshot")
        data = response.json()
        assert isinstance(data["current_memory_mb"], float)
        assert data["current_memory_mb"] >= 0
        assert data["object_count"] >= 0
    
    def test_memory_hotspots_success(self, client):
        response = client.get("/memory/hotspots")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_memory_hotspots_limit(self, client):
        # Test with different limits
        for limit in [1, 5, 10]:
            response = client.get(f"/memory/hotspots?limit={limit}")
            assert response.status_code == 200
            data = response.json()
            assert len(data) <= limit
    
    def test_memory_hotspots_invalid_limit(self, client):
        # Limit > 20 should be rejected
        response = client.get("/memory/hotspots?limit=21")
        assert response.status_code == 422


class TestStatisticsEndpoint:
    """Tests for statistics endpoint."""
    
    def test_statistics_endpoint(self, client):
        response = client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_entities" in data
        assert "total_relationships" in data
        assert "timestamp" in data
    
    def test_statistics_with_data(self, client, sample_entity_request, sample_relationship_request):
        # Create entities and relationships
        for i in range(3):
            entity_data = sample_entity_request.dict()
            entity_data["name"] = f"Entity {i}"
            client.post("/entities", json=entity_data)
        
        for i in range(2):
            rel_data = sample_relationship_request.dict()
            client.post("/relationships", json=rel_data)
        
        response = client.get("/stats")
        data = response.json()
        assert data["total_entities"] == 3
        assert data["total_relationships"] == 2


class TestOpenAPIDocumentation:
    """Tests for OpenAPI documentation."""
    
    def test_openapi_schema_exists(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data
        assert "components" in data
    
    def test_openapi_endpoints_documented(self, client):
        response = client.get("/openapi.json")
        data = response.json()
        paths = data["paths"]
        
        # Check key endpoints are documented
        assert "/entities" in paths
        assert "/relationships" in paths
        assert "/consensus" in paths
        assert "/compare" in paths
        assert "/health" in paths


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_invalid_json_request(self, client):
        response = client.post("/entities", content="invalid json", headers={"Content-Type": "application/json"})
        assert response.status_code == 422
    
    def test_missing_required_field(self, client):
        invalid_entity = {
            "entity_type": "person"
            # Missing 'name' which is required
        }
        response = client.post("/entities", json=invalid_entity)
        assert response.status_code == 422
    
    def test_invalid_enum_value(self, client):
        invalid_entity = {
            "name": "Test",
            "entity_type": "invalid_type"
        }
        response = client.post("/entities", json=invalid_entity)
        assert response.status_code == 422
    
    def test_path_parameter_validation(self, client):
        # Test that creating an entity with missing required field fails
        invalid_entity = {
            "entity_type": "person"
            # Missing 'name' which is required
        }
        response = client.post("/entities", json=invalid_entity)
        assert response.status_code == 422


class TestIntegration:
    """Integration tests for complete workflows."""
    
    def test_complete_entity_relationship_workflow(self, client, sample_entity_request, sample_relationship_request):
        # Create entity 1
        entity1_resp = client.post("/entities", json=sample_entity_request.dict())
        entity1_id = entity1_resp.json()["id"]
        
        # Create entity 2
        entity2_req = sample_entity_request.dict()
        entity2_req["name"] = "Entity 2"
        entity2_resp = client.post("/entities", json=entity2_req)
        entity2_id = entity2_resp.json()["id"]
        
        # Create relationship between them
        rel_req = sample_relationship_request.dict()
        rel_req["source_id"] = entity1_id
        rel_req["target_id"] = entity2_id
        rel_resp = client.post("/relationships", json=rel_req)
        assert rel_resp.status_code == 200
        
        # Get statistics
        stats_resp = client.get("/stats")
        stats = stats_resp.json()
        assert stats["total_entities"] == 2
        assert stats["total_relationships"] == 1
    
    def test_consensus_with_created_entities(self, client, sample_entity_request):
        # Create entities first
        entity_resp = client.post("/entities", json=sample_entity_request.dict())
        entity_id = entity_resp.json()["id"]
        
        # Use in consensus
        consensus_req = {
            "votes": [
                {
                    "agent_id": "agent_1",
                    "entities": [sample_entity_request.dict()],
                    "relationships": [],
                    "confidence": 0.9
                }
            ],
            "strategy": "majority"
        }
        
        response = client.post("/consensus", json=consensus_req)
        assert response.status_code == 200
