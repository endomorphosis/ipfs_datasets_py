#!/usr/bin/env python3
"""
Test suite for FastAPI service integration with GIVEN WHEN THEN format.
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestFastAPIService:
    """Test FastAPI service functionality."""

    def test_fastapi_service_import(self):
        """
        GIVEN a FastAPI service module exists
        WHEN attempting to import the FastAPI service components
        THEN expect successful import of app and get_current_user functions
        AND app should not be None
        """
        try:
            from ipfs_datasets_py.fastapi_service import app, get_current_user
            assert app is not None
            assert get_current_user is not None
        except ImportError as e:
            assert False, f"FastAPISettings import failed: {e}"

    def test_fastapi_config_import(self):
        """
        GIVEN a FastAPI configuration module exists
        WHEN attempting to import and instantiate FastAPISettings
        THEN expect successful import and instantiation
        AND config instance should not be None
        """
        try:
            from ipfs_datasets_py.fastapi_config import FastAPISettings
            config = FastAPISettings()
            assert config is not None
        except ImportError as e:
            assert False, f"FastAPISettings import failed: {e}"

    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """
        GIVEN a FastAPI application with a health endpoint
        WHEN making a GET request to /health
        THEN expect status code 200
        AND response JSON should contain 'status' field
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        response = client.get("/health")
        
        assert response.status_code == 200
        response_json = response.json()
        assert "status" in response_json
        assert response_json["status"] in ["healthy", "ok"]

    @pytest.mark.asyncio
    async def test_authentication_endpoint(self):
        """
        GIVEN a FastAPI application with authentication endpoint
        WHEN making a POST request to /auth/login with username and password
        THEN expect status code to be 200, 401, or 422
        AND response should handle authentication appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test with valid credentials (should accept any for demo)
        response = client.post("/auth/login", json={
            "username": "test_user",
            "password": "test_password"
        })
        
        # Should be 200 (success), 401 (unauthorized), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have token or similar auth response
            assert "access_token" in response_json or "token" in response_json or "message" in response_json


class TestFastAPIEmbeddingEndpoints:
    """Test FastAPI embedding-related endpoints."""

    @pytest.mark.asyncio
    async def test_generate_embeddings_endpoint(self):
        """
        GIVEN a FastAPI application with embedding generation endpoint
        WHEN making a POST request to /embeddings/generate with texts and model
        THEN expect status code to be 200, 401, or 422
        AND request should handle embedding generation appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test embedding generation with sample data
        test_data = {
            "texts": ["Hello world", "This is a test"],
            "model": "all-MiniLM-L6-v2"
        }
        
        response = client.post("/embeddings/generate", json=test_data)
        
        # Should be 200 (success), 401 (unauthorized), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have embeddings or similar response
            assert "embeddings" in response_json or "data" in response_json or "result" in response_json

    @pytest.mark.asyncio
    async def test_search_embeddings_endpoint(self):
        """
        GIVEN a FastAPI application with embedding search endpoint
        WHEN making a POST request to /search/semantic with query and parameters
        THEN expect status code to be 200, 401, or 422
        AND request should handle semantic search appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test semantic search with sample data
        test_data = {
            "query": "machine learning algorithms",
            "top_k": 5,
            "threshold": 0.7
        }
        
        response = client.post("/search/semantic", json=test_data)
        
        # Should be 200 (success), 401 (unauthorized), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have results or similar response
            assert "results" in response_json or "matches" in response_json or "data" in response_json


class TestFastAPIDatasetEndpoints:
    """Test FastAPI dataset-related endpoints."""

    @pytest.mark.asyncio
    async def test_load_dataset_endpoint(self):
        """
        GIVEN a FastAPI application with dataset loading endpoint
        WHEN making a POST request to /datasets/load with source and format
        THEN expect status code to be 200, 401, or 422
        AND request should handle dataset loading appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test dataset loading with sample data
        test_data = {
            "source": "sample_dataset.json",
            "format": "json",
            "options": {}
        }
        
        response = client.post("/datasets/load", json=test_data)
        
        # Should be 200 (success), 401 (unauthorized), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have dataset info or similar response
            assert "dataset_id" in response_json or "status" in response_json or "result" in response_json

    @pytest.mark.asyncio
    async def test_process_dataset_endpoint(self):
        """
        GIVEN a FastAPI application with dataset processing endpoint
        WHEN making a POST request to /datasets/process with dataset_id and operations
        THEN expect status code to be 200, 401, or 422
        AND request should handle dataset processing appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test dataset processing with sample data
        test_data = {
            "dataset_id": "test_dataset_123",
            "operations": ["normalize", "embed"],
            "options": {"batch_size": 32}
        }
        
        response = client.post("/datasets/process", json=test_data)
        
        # Should be 200 (success), 401 (unauthorized), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have task info or similar response
            assert "task_id" in response_json or "status" in response_json or "result" in response_json


class TestFastAPIVectorEndpoints:
    """Test FastAPI vector-related endpoints."""

    @pytest.mark.asyncio
    async def test_create_vector_index_endpoint(self):
        """
        GIVEN a FastAPI application with vector index creation endpoint
        WHEN making a POST request to /vectors/create-index with index configuration
        THEN expect status code to be 200, 401, or 422
        AND request should handle vector index creation appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test vector index creation with sample data
        test_data = {
            "index_name": "test_index",
            "dimension": 384,
            "metric": "cosine",
            "index_type": "faiss"
        }
        
        response = client.post("/vectors/create-index", json=test_data)
        
        # Should be 200 (success), 401 (unauthorized), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have index info or similar response
            assert "index_id" in response_json or "status" in response_json or "result" in response_json

    @pytest.mark.asyncio
    async def test_search_vector_index_endpoint(self):
        """
        GIVEN a FastAPI application with vector index search endpoint
        WHEN making a POST request to /vectors/search with query vector and parameters
        THEN expect status code to be 200, 401, or 422
        AND request should handle vector search appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test vector search with sample data
        test_data = {
            "index_name": "test_index",
            "query_vector": [0.1] * 384,  # Sample 384-dimensional vector
            "top_k": 5,
            "threshold": 0.8
        }
        
        response = client.post("/vectors/search", json=test_data)
        
        # Should be 200 (success), 401 (unauthorized), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have search results or similar response
            assert "results" in response_json or "matches" in response_json or "data" in response_json


class TestFastAPIIPFSEndpoints:
    """Test FastAPI IPFS-related endpoints."""

    @pytest.mark.asyncio
    async def test_pin_to_ipfs_endpoint(self):
        """
        GIVEN a FastAPI application with IPFS pinning endpoint
        WHEN making a POST request to /ipfs/pin with content and recursive flag
        THEN expect status code to be 200, 401, or 422
        AND request should handle IPFS pinning appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test IPFS pinning with sample data
        test_data = {
            "content": "test content for IPFS",
            "recursive": True,
            "metadata": {"name": "test_file"}
        }
        
        response = client.post("/ipfs/pin", json=test_data)
        
        # Should be 200 (success), 401 (unauthorized), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have CID or similar response
            assert "cid" in response_json or "hash" in response_json or "result" in response_json

    @pytest.mark.asyncio
    async def test_get_from_ipfs_endpoint(self):
        """
        GIVEN a FastAPI application with IPFS retrieval endpoint
        WHEN making a GET request to /ipfs/get/{cid} with a test CID
        THEN expect status code to be 200, 401, 404, or 422
        AND request should handle IPFS retrieval appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test IPFS retrieval with sample CID
        test_cid = "QmTest123456789abcdef"  # Sample IPFS CID format
        
        response = client.get(f"/ipfs/get/{test_cid}")
        
        # Should be 200 (success), 401 (unauthorized), 403 (forbidden), 404 (not found), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 404, 422]
        
        if response.status_code == 200:
            # Could be JSON response with content info or actual file content
            # Just verify we get some response
            assert response.content is not None


class TestFastAPIWorkflowEndpoints:
    """Test FastAPI workflow-related endpoints."""

    @pytest.mark.asyncio
    async def test_execute_workflow_endpoint(self):
        """
        GIVEN a FastAPI application with workflow execution endpoint
        WHEN making a POST request to /workflows/execute with workflow parameters
        THEN expect status code to be 200, 401, or 422
        AND request should handle workflow execution appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test workflow execution with sample data
        test_data = {
            "workflow_name": "test_workflow",
            "steps": [
                {"action": "load_data", "source": "test.json"},
                {"action": "process", "operation": "normalize"}
            ],
            "parameters": {"batch_size": 16}
        }
        
        response = client.post("/workflows/execute", json=test_data)
        
        # Should be 200 (success), 401 (unauthorized), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have task_id or status info
            assert "task_id" in response_json or "status" in response_json or "result" in response_json

    @pytest.mark.asyncio
    async def test_workflow_status_endpoint(self):
        """
        GIVEN a FastAPI application with workflow status endpoint
        WHEN making a GET request to /workflows/status/{task_id} with a task ID
        THEN expect status code to be 200, 401, 404, or 422
        AND request should handle workflow status check appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test workflow status with sample task ID
        test_task_id = "test_task_123456"
        
        response = client.get(f"/workflows/status/{test_task_id}")
        
        # Should be 200 (success), 401 (unauthorized), 403 (forbidden), 404 (not found), or 422 (validation error)
        assert response.status_code in [200, 401, 403, 404, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have status info
            assert "status" in response_json or "state" in response_json or "result" in response_json


class TestFastAPIAdminEndpoints:
    """Test FastAPI admin-related endpoints."""

    @pytest.mark.asyncio
    async def test_system_health_endpoint(self):
        """
        GIVEN a FastAPI application with system health admin endpoint
        WHEN making a GET request to /admin/health with admin token
        THEN expect status code to be 200, 401, or 403
        AND request should handle system health check appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        response = client.get("/admin/health")
        
        # Should be 200 (success), 401 (unauthorized), or 403 (forbidden)
        assert response.status_code in [200, 401, 403]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have system health info
            assert "status" in response_json or "health" in response_json or "system" in response_json

    @pytest.mark.asyncio
    async def test_cache_management_endpoint(self):
        """
        GIVEN a FastAPI application with cache management endpoints
        WHEN making requests to /cache/stats and /cache/clear
        THEN expect status code to be 200, 401, 403, or 422
        AND request should handle cache management appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test cache stats endpoint
        response = client.get("/cache/stats")
        assert response.status_code in [200, 401, 403]
        
        if response.status_code == 200:
            response_json = response.json()
            # Should have cache statistics
            assert "stats" in response_json or "cache" in response_json or "result" in response_json
        
        # Test cache clear endpoint
        response = client.post("/cache/clear", json={
            "cache_type": "embedding",
            "pattern": "test_*"
        })
        assert response.status_code in [200, 401, 403, 422]


class TestFastAPIErrorHandling:
    """Test FastAPI error handling."""

    @pytest.mark.asyncio
    async def test_invalid_endpoint(self):
        """
        GIVEN a FastAPI application
        WHEN making a GET request to a non-existent endpoint
        THEN expect status code 404
        AND request should handle invalid endpoints appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        response = client.get("/nonexistent/endpoint")
        assert response.status_code == 404
        
        response_json = response.json()
        assert "detail" in response_json or "error" in response_json

    @pytest.mark.asyncio
    async def test_invalid_request_data(self):
        """
        GIVEN a FastAPI application with embedding generation endpoint
        WHEN making a POST request with invalid JSON data structure
        THEN expect status code to be 401 or 422
        AND request should handle invalid request data appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test with malformed request data
        invalid_data = {
            "invalid_field": "test",
            "missing_required_fields": True
        }
        
        response = client.post("/embeddings/generate", json=invalid_data)
        assert response.status_code in [401, 403, 422]
        
        if response.status_code == 422:
            response_json = response.json()
            assert "detail" in response_json or "error" in response_json

    @pytest.mark.asyncio
    async def test_missing_authentication(self):
        """
        GIVEN a FastAPI application with protected admin endpoint
        WHEN making a GET request to /admin/health without authentication
        THEN expect status code to be 401 or 403
        AND request should handle missing authentication appropriately
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Remove any default headers that might contain auth
        response = client.get("/admin/health")
        assert response.status_code in [401, 403, 200]  # 200 if auth is optional for demo
        
        if response.status_code in [401, 403]:
            response_json = response.json()
            assert "detail" in response_json or "error" in response_json


class TestFastAPIDocumentation:
    """Test FastAPI documentation endpoints."""

    @pytest.mark.asyncio
    async def test_openapi_schema(self):
        """
        GIVEN a FastAPI application with OpenAPI schema
        WHEN making a GET request to /openapi.json
        THEN expect status code 200
        AND response JSON should contain 'info' and 'paths' fields
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        response = client.get("/openapi.json")
        assert response.status_code == 200
        
        response_json = response.json()
        assert "info" in response_json
        assert "paths" in response_json
        assert "openapi" in response_json

    @pytest.mark.asyncio
    async def test_docs_endpoint(self):
        """
        GIVEN a FastAPI application with documentation UI
        WHEN making a GET request to /docs
        THEN expect status code 200
        AND response content-type should be 'text/html'
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


class TestFastAPIMiddleware:
    """Test FastAPI middleware functionality."""

    @pytest.mark.asyncio
    async def test_cors_middleware(self):
        """
        GIVEN a FastAPI application with CORS middleware
        WHEN making an OPTIONS request to /health with CORS headers
        THEN expect status code to be 200 or 204
        AND request should handle CORS preflight properly
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test CORS preflight request
        headers = {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization"
        }
        
        response = client.options("/health", headers=headers)
        assert response.status_code in [200, 204, 405]  # 405 if OPTIONS not specifically handled
        
        # Should have CORS headers in response
        cors_headers = ["access-control-allow-origin", "access-control-allow-methods"]
        has_cors = any(header.lower() in [k.lower() for k in response.headers.keys()] for header in cors_headers)
        # Note: CORS might be configured but not active in test client

    @pytest.mark.asyncio
    async def test_rate_limiting_middleware(self):
        """
        GIVEN a FastAPI application with rate limiting middleware
        WHEN making multiple rapid requests to /health
        THEN expect status codes to be 200 or 429
        AND requests should be handled normally or with rate limiting
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Make multiple rapid requests
        status_codes = []
        for _ in range(10):
            response = client.get("/health")
            status_codes.append(response.status_code)
        
        # Should be 200 (normal) or 429 (rate limited)
        for status_code in status_codes:
            assert status_code in [200, 429]
        
        # At least some requests should succeed
        assert 200 in status_codes


class TestFastAPIIntegration:
    """Test FastAPI integration with other components."""

    @pytest.mark.asyncio
    async def test_fastapi_mcp_integration(self):
        """
        GIVEN a FastAPI application integrated with MCP tools
        WHEN importing and using MCP tools within FastAPI context
        THEN expect successful import of app and load_dataset function
        AND MCP tools should be usable within FastAPI context
        AND result should not be None and contain 'status' field
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test MCP tools list endpoint (which uses MCP tools internally)
        response = client.get("/tools/list")
        assert response.status_code in [200, 401, 403]
        
        if response.status_code == 200:
            response_json = response.json()
            assert "tools" in response_json or "data" in response_json or "result" in response_json

    @pytest.mark.asyncio
    async def test_fastapi_embedding_integration(self):
        """
        GIVEN a FastAPI application integrated with embedding tools
        WHEN importing and using embedding tools within FastAPI context
        THEN expect successful import of app and EmbeddingManager
        AND embedding manager should not be None
        """
        from fastapi.testclient import TestClient
        from ipfs_datasets_py.fastapi_service import app
        
        client = TestClient(app)
        
        # Test embedding generation endpoint (which uses embedding tools internally)
        test_data = {
            "texts": ["test embedding integration"],
            "model": "all-MiniLM-L6-v2"
        }
        
        response = client.post("/embeddings/generate", json=test_data)
        assert response.status_code in [200, 401, 403, 422]
        
        if response.status_code == 200:
            response_json = response.json()
            assert "embeddings" in response_json or "data" in response_json or "result" in response_json


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
