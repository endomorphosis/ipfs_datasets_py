#!/usr/bin/env python3
"""
Test suite for FastAPI service integration.
"""

import pytest
import anyio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestFastAPIService:
    """Test FastAPI service functionality."""

    def test_fastapi_service_import(self):
        """Test that FastAPI service can be imported."""
        try:
            from ipfs_datasets_py.fastapi_service import app, get_current_user
            assert app is not None
        except ImportError as e:
            raise ImportError(f"FastAPI service not available: {e}")
    
    def test_fastapi_config_import(self):
        """Test that FastAPI configuration can be imported."""
        try:
            from ipfs_datasets_py.fastapi_config import FastAPIConfig
            config = FastAPIConfig()
            assert config is not None
        except ImportError as e:
            raise ImportError(f"FastAPI config not available: {e}")
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test health check endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_authentication_endpoint(self):
        """Test authentication endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            auth_data = {
                "username": "test_user",
                "password": "test_password"
            }
            
            response = client.post("/auth/login", json=auth_data)
            
            # Should return 200 or appropriate auth response
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIEmbeddingEndpoints:
    """Test FastAPI embedding-related endpoints."""

    @pytest.mark.asyncio
    async def test_generate_embeddings_endpoint(self):
        """Test embedding generation endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            embedding_request = {
                "texts": ["Test text for embedding"],
                "model": "sentence-transformers/all-MiniLM-L6-v2"
            }
            
            # Mock authentication if required
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/embeddings/generate", json=embedding_request, headers=headers)
            
            # Should return 200, 401 (auth), or 422 (validation)
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_search_embeddings_endpoint(self):
        """Test embedding search endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            search_request = {
                "query": "search query",
                "index_name": "test_index",
                "top_k": 5
            }
            
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/embeddings/search", json=search_request, headers=headers)
            
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIDatasetEndpoints:
    """Test FastAPI dataset-related endpoints."""

    @pytest.mark.asyncio
    async def test_load_dataset_endpoint(self):
        """Test dataset loading endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            dataset_request = {
                "source": "test_dataset",
                "format": "json"
            }
            
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/datasets/load", json=dataset_request, headers=headers)
            
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_process_dataset_endpoint(self):
        """Test dataset processing endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            process_request = {
                "dataset_id": "test_dataset",
                "operations": [
                    {"type": "filter", "params": {"condition": "length > 10"}}
                ]
            }
            
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/datasets/process", json=process_request, headers=headers)
            
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIVectorEndpoints:
    """Test FastAPI vector-related endpoints."""

    @pytest.mark.asyncio
    async def test_create_vector_index_endpoint(self):
        """Test vector index creation endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            index_request = {
                "vectors": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
                "index_name": "test_index",
                "metric": "cosine"
            }
            
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/vectors/create_index", json=index_request, headers=headers)
            
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_search_vector_index_endpoint(self):
        """Test vector index search endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            search_request = {
                "index_id": "test_index",
                "query_vector": [0.1, 0.2, 0.3],
                "top_k": 5
            }
            
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/vectors/search", json=search_request, headers=headers)
            
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIIPFSEndpoints:
    """Test FastAPI IPFS-related endpoints."""

    @pytest.mark.asyncio
    async def test_pin_to_ipfs_endpoint(self):
        """Test IPFS pinning endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            pin_request = {
                "content": {"test": "data"},
                "recursive": True
            }
            
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/ipfs/pin", json=pin_request, headers=headers)
            
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_get_from_ipfs_endpoint(self):
        """Test IPFS retrieval endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            headers = {"Authorization": "Bearer test_token"}
            response = client.get("/ipfs/get/QmTestCID123", headers=headers)
            
            assert response.status_code in [200, 401, 404, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIWorkflowEndpoints:
    """Test FastAPI workflow-related endpoints."""

    @pytest.mark.asyncio
    async def test_create_workflow_endpoint(self):
        """Test workflow creation endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            workflow_request = {
                "name": "test_workflow",
                "steps": [
                    {"type": "load_dataset", "params": {"source": "test"}},
                    {"type": "generate_embeddings", "params": {"model": "test"}}
                ]
            }
            
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/workflows/create", json=workflow_request, headers=headers)
            
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_execute_workflow_endpoint(self):
        """Test workflow execution endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            execute_request = {
                "workflow_id": "test_workflow_123",
                "parameters": {"batch_size": 10}
            }
            
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/workflows/execute", json=execute_request, headers=headers)
            
            assert response.status_code in [200, 401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIAdminEndpoints:
    """Test FastAPI admin-related endpoints."""

    @pytest.mark.asyncio
    async def test_system_health_endpoint(self):
        """Test system health admin endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            headers = {"Authorization": "Bearer admin_token"}
            response = client.get("/admin/health", headers=headers)
            
            assert response.status_code in [200, 401, 403]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_cache_management_endpoint(self):
        """Test cache management admin endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            cache_request = {
                "operation": "clear",
                "namespace": "test"
            }
            
            headers = {"Authorization": "Bearer admin_token"}
            response = client.post("/admin/cache", json=cache_request, headers=headers)
            
            assert response.status_code in [200, 401, 403, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIErrorHandling:
    """Test FastAPI error handling."""

    @pytest.mark.asyncio
    async def test_invalid_endpoint(self):
        """Test handling of invalid endpoints."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            response = client.get("/invalid/endpoint")
            
            assert response.status_code == 404
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_invalid_request_data(self):
        """Test handling of invalid request data."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            # Send invalid JSON data
            invalid_request = {"invalid": "data structure"}
            headers = {"Authorization": "Bearer test_token"}
            response = client.post("/embeddings/generate", json=invalid_request, headers=headers)
            
            # Should return validation error
            assert response.status_code in [401, 422]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_missing_authentication(self):
        """Test handling of missing authentication."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            # Try to access protected endpoint without auth
            response = client.get("/admin/health")
            
            # Should return authentication error
            assert response.status_code in [401, 403]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIDocumentation:
    """Test FastAPI documentation endpoints."""

    @pytest.mark.asyncio
    async def test_openapi_schema(self):
        """Test OpenAPI schema endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            response = client.get("/openapi.json")
            
            assert response.status_code == 200
            data = response.json()
            assert "info" in data
            assert "paths" in data
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_docs_endpoint(self):
        """Test documentation UI endpoint."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            response = client.get("/docs")
            
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIMiddleware:
    """Test FastAPI middleware functionality."""

    @pytest.mark.asyncio
    async def test_cors_middleware(self):
        """Test CORS middleware."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            # Test CORS preflight request
            response = client.options(
                "/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET"
                }
            )
            
            # Should handle CORS properly
            assert response.status_code in [200, 204]
            
        except ImportError:
            raise ImportError("FastAPI test client not available")
    
    @pytest.mark.asyncio
    async def test_rate_limiting_middleware(self):
        """Test rate limiting middleware."""
        try:
            from fastapi.testclient import TestClient
            from ipfs_datasets_py.fastapi_service import app
            
            client = TestClient(app)
            
            # Make multiple rapid requests
            responses = []
            for _ in range(10):
                response = client.get("/health")
                responses.append(response.status_code)
            
            # Should handle requests normally or with rate limiting
            assert all(status in [200, 429] for status in responses)
            
        except ImportError:
            raise ImportError("FastAPI test client not available")


class TestFastAPIIntegration:
    """Test FastAPI integration with other components."""

    @pytest.mark.asyncio
    async def test_fastapi_mcp_integration(self):
        """Test FastAPI integration with MCP tools."""
        try:
            # Test that FastAPI can import and use MCP tools
            from ipfs_datasets_py.fastapi_service import app
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
            
            # Test that MCP tools can be used within FastAPI context
            result = await load_dataset("test_source")
            
            assert result is not None
            assert "status" in result
            
        except ImportError:
            raise ImportError("FastAPI or MCP tools not available")
    
    @pytest.mark.asyncio
    async def test_fastapi_embedding_integration(self):
        """Test FastAPI integration with embedding tools."""
        try:
            from ipfs_datasets_py.fastapi_service import app
            from ipfs_datasets_py.embeddings.core import EmbeddingManager
            
            # Test that embedding tools can be used within FastAPI context
            manager = EmbeddingManager()
            assert manager is not None
            
        except ImportError:
            raise ImportError("FastAPI or embedding tools not available")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
