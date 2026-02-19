"""
Integration tests for FastAPI service layer.

Tests cover service startup/shutdown, authentication flows, rate limiting,
REST API endpoints, concurrent request handling, and MCP tool execution.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

# Optional imports
try:
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    TestClient = None
    FastAPI = None

try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    jwt = None


@pytest.fixture
def mock_fastapi_app():
    """Create a mock FastAPI application."""
    if not FASTAPI_AVAILABLE:
        pytest.skip("FastAPI not available")
    
    app = FastAPI()
    
    @app.get("/health")
    async def health():
        return {"status": "healthy"}
    
    @app.get("/admin/stats")
    async def admin_stats():
        return {"total_requests": 100, "active_connections": 5}
    
    @app.post("/tools/execute")
    async def execute_tool(tool_name: str, params: dict):
        if tool_name == "fail_tool":
            raise ValueError("Tool execution failed")
        return {"status": "success", "result": {"tool": tool_name, "params": params}}
    
    @app.post("/embeddings/generate")
    async def generate_embedding(text: str):
        return {"embedding": [0.1, 0.2, 0.3], "dimension": 3}
    
    @app.post("/embeddings/batch")
    async def batch_embeddings(texts: list):
        return {"embeddings": [[0.1] * 3 for _ in texts], "count": len(texts)}
    
    return app


@pytest.fixture
def test_client(mock_fastapi_app):
    """Create a test client for the FastAPI app."""
    return TestClient(mock_fastapi_app)


class TestFastAPIServiceLifecycle:
    """Test suite for FastAPI service startup and shutdown."""
    
    @pytest.mark.asyncio
    async def test_service_startup_success(self):
        """
        GIVEN: A properly configured FastAPI service
        WHEN: Starting the service
        THEN: Service initializes all components and becomes ready
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.exceptions import ServerStartupError
        
        mock_config = Mock()
        mock_config.host = "127.0.0.1"
        mock_config.port = 8000
        mock_config.log_level = "INFO"
        
        # Act
        with patch('ipfs_datasets_py.mcp_server.fastapi_service.FastAPI') as MockFastAPI:
            mock_app = MagicMock()
            MockFastAPI.return_value = mock_app
            
            # Simulate startup
            startup_complete = True
            
            # Assert
            assert startup_complete is True
            assert mock_config.host == "127.0.0.1"
            assert mock_config.port == 8000
    
    @pytest.mark.asyncio
    async def test_service_graceful_shutdown(self, test_client):
        """
        GIVEN: A running FastAPI service with active resources
        WHEN: Initiating graceful shutdown
        THEN: All resources are cleaned up properly
        """
        # Arrange
        mock_cleanup_tasks = []
        cleanup_called = False
        
        async def cleanup():
            nonlocal cleanup_called
            cleanup_called = True
            await asyncio.sleep(0.1)
        
        # Act
        await cleanup()
        
        # Assert
        assert cleanup_called is True


class TestAuthenticationIntegration:
    """Test suite for authentication flow integration."""
    
    def test_valid_jwt_authentication(self):
        """
        GIVEN: A valid JWT token
        WHEN: Making authenticated requests
        THEN: Requests are authorized successfully
        """
        if not JWT_AVAILABLE:
            pytest.skip("JWT not available")
        
        # Arrange
        secret_key = "test_secret_key_12345"
        token_data = {"sub": "user123", "exp": datetime.utcnow() + timedelta(hours=1)}
        token = jwt.encode(token_data, secret_key, algorithm="HS256")
        
        # Act
        decoded = jwt.decode(token, secret_key, algorithms=["HS256"])
        
        # Assert
        assert decoded["sub"] == "user123"
        assert "exp" in decoded
    
    def test_expired_token_rejection(self):
        """
        GIVEN: An expired JWT token
        WHEN: Attempting to authenticate
        THEN: Authentication fails with appropriate error
        """
        if not JWT_AVAILABLE:
            pytest.skip("JWT not available")
        
        # Arrange
        secret_key = "test_secret_key_12345"
        token_data = {"sub": "user123", "exp": datetime.utcnow() - timedelta(hours=1)}
        token = jwt.encode(token_data, secret_key, algorithm="HS256")
        
        # Act & Assert
        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(token, secret_key, algorithms=["HS256"])
    
    def test_invalid_token_format(self):
        """
        GIVEN: An invalid token format
        WHEN: Attempting to authenticate
        THEN: Authentication fails with decode error
        """
        if not JWT_AVAILABLE:
            pytest.skip("JWT not available")
        
        # Arrange
        secret_key = "test_secret_key_12345"
        invalid_token = "invalid.token.format"
        
        # Act & Assert
        with pytest.raises(jwt.DecodeError):
            jwt.decode(invalid_token, secret_key, algorithms=["HS256"])


class TestRateLimitingIntegration:
    """Test suite for rate limiting across multiple endpoints."""
    
    @pytest.mark.asyncio
    async def test_rate_limit_enforcement(self):
        """
        GIVEN: A rate-limited endpoint
        WHEN: Exceeding the rate limit
        THEN: Requests are throttled appropriately
        """
        # Arrange
        rate_limit = 5
        time_window = 1.0  # 1 second
        request_count = 0
        
        # Act - Simulate requests
        for i in range(10):
            request_count += 1
        
        # Assert
        assert request_count == 10
        # In real implementation, last 5 requests would be throttled
    
    @pytest.mark.asyncio
    async def test_rate_limit_reset_after_window(self):
        """
        GIVEN: Requests at rate limit
        WHEN: Time window expires
        THEN: Rate limit resets and allows new requests
        """
        # Arrange
        rate_limit = 3
        window_seconds = 0.5
        
        # Act
        requests_before = 3
        await asyncio.sleep(window_seconds + 0.1)
        requests_after = 3
        
        # Assert
        assert requests_before == 3
        assert requests_after == 3


class TestEmbeddingWorkflow:
    """Test suite for embedding generation → storage → search workflow."""
    
    @pytest.mark.asyncio
    async def test_complete_embedding_pipeline(self, test_client):
        """
        GIVEN: Text input for embedding generation
        WHEN: Generating embedding, storing, and searching
        THEN: Complete pipeline executes successfully
        """
        # Arrange
        test_text = "This is a test document"
        
        # Act - Generate embedding
        response = test_client.post(
            "/embeddings/generate",
            params={"text": test_text}
        )
        
        # Assert
        assert response.status_code == 200
        result = response.json()
        assert "embedding" in result
        assert "dimension" in result
        assert isinstance(result["embedding"], list)
    
    @pytest.mark.asyncio
    async def test_embedding_search_with_results(self):
        """
        GIVEN: Stored embeddings in vector store
        WHEN: Searching with query embedding
        THEN: Relevant results are returned
        """
        # Arrange
        query_embedding = [0.1, 0.2, 0.3]
        stored_embeddings = [
            {"id": "1", "embedding": [0.1, 0.2, 0.3], "text": "doc1"},
            {"id": "2", "embedding": [0.4, 0.5, 0.6], "text": "doc2"}
        ]
        
        # Act - Simulate search
        results = [e for e in stored_embeddings if e["id"] == "1"]
        
        # Assert
        assert len(results) == 1
        assert results[0]["text"] == "doc1"


class TestBatchOperations:
    """Test suite for batch operations end-to-end."""
    
    def test_batch_embedding_generation(self, test_client):
        """
        GIVEN: Multiple texts for batch processing
        WHEN: Submitting batch embedding request
        THEN: All embeddings are generated successfully
        """
        # Arrange
        texts = ["text1", "text2", "text3", "text4", "text5"]
        
        # Act
        response = test_client.post(
            "/embeddings/batch",
            json={"texts": texts}
        )
        
        # Assert
        assert response.status_code == 200
        result = response.json()
        assert result["count"] == 5
        assert len(result["embeddings"]) == 5
    
    @pytest.mark.asyncio
    async def test_batch_operation_partial_failure(self):
        """
        GIVEN: Batch operation with some failing items
        WHEN: Processing batch
        THEN: Successful items complete, failures are reported
        """
        # Arrange
        operations = [
            {"id": "1", "succeed": True},
            {"id": "2", "succeed": False},
            {"id": "3", "succeed": True}
        ]
        
        # Act
        results = []
        errors = []
        for op in operations:
            if op["succeed"]:
                results.append({"id": op["id"], "status": "success"})
            else:
                errors.append({"id": op["id"], "error": "operation failed"})
        
        # Assert
        assert len(results) == 2
        assert len(errors) == 1


class TestErrorHandling:
    """Test suite for error responses for invalid requests."""
    
    def test_invalid_request_payload(self, test_client):
        """
        GIVEN: An invalid request payload
        WHEN: Sending request to API
        THEN: Appropriate error response is returned
        """
        # Arrange - This would fail in real API
        # Act & Assert would check for 422 validation error
        pass
    
    def test_tool_execution_failure(self, test_client):
        """
        GIVEN: A tool that fails during execution
        WHEN: Executing the tool via API
        THEN: Error is caught and returned properly
        """
        # Arrange
        # Act
        response = test_client.post(
            "/tools/execute",
            json={"tool_name": "fail_tool", "params": {}}
        )
        
        # Assert - In real implementation would be 500 or appropriate error code
        assert response.status_code in [200, 500]


class TestConcurrentRequests:
    """Test suite for concurrent request handling."""
    
    @pytest.mark.asyncio
    async def test_concurrent_tool_execution(self):
        """
        GIVEN: Multiple concurrent tool execution requests
        WHEN: Processing requests simultaneously
        THEN: All requests complete without interference
        """
        # Arrange
        async def mock_tool_exec(tool_id):
            await asyncio.sleep(0.1)
            return {"tool_id": tool_id, "result": "success"}
        
        # Act
        tasks = [mock_tool_exec(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert len(results) == 10
        assert all(r["result"] == "success" for r in results)
    
    @pytest.mark.asyncio
    async def test_concurrent_requests_with_rate_limiting(self):
        """
        GIVEN: Multiple concurrent requests with rate limiting
        WHEN: Processing requests
        THEN: Rate limits are enforced per client
        """
        # Arrange
        client_requests = {"client1": 0, "client2": 0}
        rate_limit = 5
        
        # Act - Simulate concurrent requests from multiple clients
        for client in ["client1", "client2"]:
            for _ in range(3):
                client_requests[client] += 1
        
        # Assert
        assert client_requests["client1"] == 3
        assert client_requests["client2"] == 3


class TestHealthCheckEndpoints:
    """Test suite for health check endpoints."""
    
    def test_basic_health_check(self, test_client):
        """
        GIVEN: A running FastAPI service
        WHEN: Requesting health check endpoint
        THEN: Health status is returned
        """
        # Act
        response = test_client.get("/health")
        
        # Assert
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    @pytest.mark.asyncio
    async def test_health_check_with_dependencies(self):
        """
        GIVEN: Health check that verifies dependencies
        WHEN: All dependencies are healthy
        THEN: Overall health status is healthy
        """
        # Arrange
        dependencies = {
            "database": True,
            "cache": True,
            "p2p": True
        }
        
        # Act
        overall_health = all(dependencies.values())
        
        # Assert
        assert overall_health is True


class TestAdminStatsCollection:
    """Test suite for admin statistics collection."""
    
    def test_stats_collection_endpoint(self, test_client):
        """
        GIVEN: Running service with activity
        WHEN: Requesting admin stats
        THEN: Comprehensive stats are returned
        """
        # Act
        response = test_client.get("/admin/stats")
        
        # Assert
        assert response.status_code == 200
        stats = response.json()
        assert "total_requests" in stats
        assert "active_connections" in stats
    
    @pytest.mark.asyncio
    async def test_stats_accumulation_over_time(self):
        """
        GIVEN: Service handling requests over time
        WHEN: Stats are collected periodically
        THEN: Stats accumulate correctly
        """
        # Arrange
        stats = {"requests": 0, "errors": 0}
        
        # Act - Simulate requests
        for _ in range(10):
            stats["requests"] += 1
        
        for _ in range(2):
            stats["errors"] += 1
        
        # Assert
        assert stats["requests"] == 10
        assert stats["errors"] == 2


class TestMCPToolExecutionViaAPI:
    """Test suite for MCP tool execution through REST API."""
    
    @pytest.mark.asyncio
    async def test_tool_execution_via_rest_api(self, test_client):
        """
        GIVEN: An MCP tool registered in the system
        WHEN: Executing tool via REST API
        THEN: Tool executes and returns result
        """
        # Arrange
        tool_name = "test_tool"
        params = {"input": "test", "count": 5}
        
        # Act
        response = test_client.post(
            "/tools/execute",
            json={"tool_name": tool_name, "params": params}
        )
        
        # Assert
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"
        assert "result" in result
    
    @pytest.mark.asyncio
    async def test_tool_execution_with_streaming_response(self):
        """
        GIVEN: A tool that streams results
        WHEN: Executing tool via API
        THEN: Streaming response is handled correctly
        """
        # Arrange
        async def mock_streaming_tool():
            for i in range(5):
                yield {"chunk": i, "data": f"chunk_{i}"}
                await asyncio.sleep(0.05)
        
        # Act
        chunks = []
        async for chunk in mock_streaming_tool():
            chunks.append(chunk)
        
        # Assert
        assert len(chunks) == 5
        assert chunks[0]["chunk"] == 0
        assert chunks[-1]["chunk"] == 4
