"""
FastAPI Integration for Migrated MCP Tools

This module provides REST API endpoints for all migrated MCP tools from the
embeddings/tooling integration, enabling both MCP and HTTP access to functionality.
"""

from typing import Dict, List, Any, Optional
import logging
from datetime import datetime

try:
    from fastapi import FastAPI, HTTPException, Depends, Security
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    # Mock classes for when FastAPI is not available
    class BaseModel:
        pass
    class FastAPI:
        pass

from .tool_registration import create_and_register_all_tools, MCPToolRegistry

logger = logging.getLogger(__name__)


# Pydantic models for API requests/responses
class ToolExecutionRequest(BaseModel):
    """Request model for tool execution."""
    tool_name: str = Field(..., description="Name of the tool to execute")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameters for tool execution")
    

class ToolExecutionResponse(BaseModel):
    """Response model for tool execution."""
    success: bool = Field(..., description="Whether the tool execution was successful")
    result: Dict[str, Any] = Field(..., description="Tool execution result")
    tool_name: str = Field(..., description="Name of the executed tool")
    executed_at: str = Field(..., description="Timestamp of execution")
    execution_time_ms: Optional[float] = Field(None, description="Execution time in milliseconds")


class ToolInfo(BaseModel):
    """Model for tool information."""
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    category: str = Field(..., description="Tool category")
    tags: List[str] = Field(default_factory=list, description="Tool tags")
    input_schema: Dict[str, Any] = Field(..., description="Tool input schema")


class ApiStatus(BaseModel):
    """API status response."""
    status: str = Field(..., description="API status")
    version: str = Field(..., description="API version")
    total_tools: int = Field(..., description="Total number of registered tools")
    categories: Dict[str, int] = Field(..., description="Tool count by category")
    uptime: str = Field(..., description="API uptime")


class MCPToolsAPI:
    """
    FastAPI application for migrated MCP tools.
    
    Provides REST API endpoints for all migrated MCP tools.
    """
    
    def __init__(self):
        if not FASTAPI_AVAILABLE:
            raise ImportError("FastAPI is required for REST API functionality. Install with: pip install fastapi uvicorn")
        
        self.app = FastAPI(
            title="IPFS Datasets MCP Tools API",
            description="REST API for migrated MCP tools",
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc"
        )
        
        self.registry: Optional[MCPToolRegistry] = None
        self.startup_time = datetime.utcnow()
        self.security = HTTPBearer(auto_error=False)
        
        self._setup_middleware()
        self._setup_routes()
        
    def _setup_middleware(self):
        """Setup middleware for the FastAPI app."""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Configure appropriately for production
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
    def _setup_routes(self):
        """Setup API routes."""
        
        @self.app.on_event("startup")
        async def startup_event():
            """Initialize tools on startup."""
            logger.info("🚀 Starting MCP Tools API...")
            try:
                self.registry = create_and_register_all_tools()
                summary = self.registry.get_registration_summary()
                logger.info(f"✅ API started with {summary['total_tools']} tools")
            except Exception as e:
                logger.error(f"❌ Failed to initialize tools: {e}")
                raise
        
        @self.app.get("/", response_model=ApiStatus)
        async def root():
            """Get API status and information."""
            if not self.registry:
                raise HTTPException(status_code=503, detail="Tools not initialized")
            
            summary = self.registry.get_registration_summary()
            uptime = datetime.utcnow() - self.startup_time
            
            return ApiStatus(
                status="healthy",
                version="1.0.0",
                total_tools=summary["total_tools"],
                categories=summary["categories"],
                uptime=str(uptime)
            )
        
        @self.app.get("/tools", response_model=List[ToolInfo])
        async def list_tools(category: Optional[str] = None):
            """List all available tools, optionally filtered by category."""
            if not self.registry:
                raise HTTPException(status_code=503, detail="Tools not initialized")
            
            if category:
                tools = self.registry.get_tools_by_category(category)
            else:
                tools = list(self.registry.tools.values())
            
            return [
                ToolInfo(
                    name=tool.name,
                    description=tool.description,
                    category=tool.category,
                    tags=tool.tags,
                    input_schema=tool.input_schema
                )
                for tool in tools
            ]
        
        @self.app.get("/tools/{tool_name}", response_model=ToolInfo)
        async def get_tool_info(tool_name: str):
            """Get information about a specific tool."""
            if not self.registry:
                raise HTTPException(status_code=503, detail="Tools not initialized")
            
            tool = self.registry.get_tool(tool_name)
            if not tool:
                raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
            
            return ToolInfo(
                name=tool.name,
                description=tool.description,
                category=tool.category,
                tags=tool.tags,
                input_schema=tool.input_schema
            )
        
        @self.app.post("/tools/{tool_name}/execute", response_model=ToolExecutionResponse)
        async def execute_tool(
            tool_name: str,
            request: ToolExecutionRequest,
            credentials: Optional[HTTPAuthorizationCredentials] = Security(self.security)
        ):
            """Execute a specific tool."""
            if not self.registry:
                raise HTTPException(status_code=503, detail="Tools not initialized")
            
            # TODO: Add authentication validation using credentials
            
            tool = self.registry.get_tool(tool_name)
            if not tool:
                raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
            
            try:
                start_time = datetime.utcnow()
                result = await tool.execute(request.parameters)
                end_time = datetime.utcnow()
                
                execution_time = (end_time - start_time).total_seconds() * 1000
                
                return ToolExecutionResponse(
                    success=result.get("success", True),
                    result=result,
                    tool_name=tool_name,
                    executed_at=end_time.isoformat(),
                    execution_time_ms=execution_time
                )
                
            except Exception as e:
                logger.error(f"Tool execution failed for {tool_name}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Tool execution failed: {str(e)}"
                )
        
        @self.app.post("/tools/execute", response_model=ToolExecutionResponse)
        async def execute_tool_by_request(
            request: ToolExecutionRequest,
            credentials: Optional[HTTPAuthorizationCredentials] = Security(self.security)
        ):
            """Execute a tool specified in the request body."""
            return await execute_tool(request.tool_name, request, credentials)
        
        @self.app.get("/categories")
        async def list_categories():
            """List all tool categories."""
            if not self.registry:
                raise HTTPException(status_code=503, detail="Tools not initialized")
            
            summary = self.registry.get_registration_summary()
            return {
                "categories": summary["categories"],
                "total_categories": len(summary["categories"])
            }
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            if not self.registry:
                return {"status": "unhealthy", "message": "Tools not initialized"}
            
            return {
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "tools_count": len(self.registry.tools)
            }


def create_api_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI application
    """
    api = MCPToolsAPI()
    return api.app


# For running with uvicorn
app = create_api_app() if FASTAPI_AVAILABLE else None


def run_api_server(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """
    Run the API server using uvicorn.
    
    Args:
        host: Host to bind to
        port: Port to bind to
        reload: Enable auto-reload for development
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI and uvicorn are required to run the API server")
    
    try:
        import uvicorn
        logger.info(f"🌐 Starting API server at http://{host}:{port}")
        uvicorn.run(
            "ipfs_datasets_py.mcp_server.tools.fastapi_integration:app",
            host=host,
            port=port,
            reload=reload
        )
    except ImportError:
        raise ImportError("uvicorn is required to run the API server. Install with: pip install uvicorn")


if __name__ == "__main__":
    # Run the server if executed directly
    import argparse
    
    parser = argparse.ArgumentParser(description="Run MCP Tools API server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    
    args = parser.parse_args()
    run_api_server(args.host, args.port, args.reload)
