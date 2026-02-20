"""
FastAPI service layer for IPFS Datasets Python with embedding capabilities.

This module provides REST API endpoints for all the migrated embedding and MCP tools,
with authentication, rate limiting, and comprehensive error handling.
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

import anyio
import logging
import time
import uuid
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import jwt
import hashlib

# Import custom exceptions
from .exceptions import (
    MCPServerError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ValidationError as MCPValidationError,
    ConfigurationError,
    ServerStartupError,
    ServerShutdownError
)
try:
    from passlib.context import CryptContext
except ImportError:  # pragma: no cover - optional dependency
    CryptContext = None
from pydantic import BaseModel, Field
import uvicorn

logger = logging.getLogger(__name__)

# Import our modules
try:
    from .embeddings.core import IPFSEmbeddings
    from .embeddings.schema import EmbeddingRequest, EmbeddingResponse
    from .vector_stores.base import BaseVectorStore
    from .vector_stores.qdrant_store import QdrantVectorStore
    from .vector_stores.faiss_store import FAISSVectorStore
    from .mcp_server.server import IPFSDatasetsMCPServer
    from .fastapi_config import FastAPISettings
except ImportError:
    # Fallback imports for development
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    try:
        from embeddings.core import IPFSEmbeddings
        from embeddings.schema import EmbeddingRequest, EmbeddingResponse
        from vector_stores.base import BaseVectorStore
        from vector_stores.qdrant_store import QdrantVectorStore 
        from vector_stores.faiss_store import FAISSVectorStore
        from mcp_server.server import IPFSDatasetsMCPServer
        from fastapi_config import FastAPISettings
    except ImportError as e:
        logger.warning(f"Some imports failed, using mock implementations: {e}")

        class IPFSEmbeddings:  # type: ignore[too-many-public-methods]
            """Fallback embeddings implementation when dependencies are missing."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                """No-op constructor; real implementation requires optional dependencies."""
                pass

        class BaseVectorStore:  # type: ignore[too-many-public-methods]
            """Fallback vector store base class."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                """No-op constructor; real implementation requires optional dependencies."""
                pass

        class QdrantVectorStore(BaseVectorStore):
            """Fallback Qdrant vector store."""

        class FAISSVectorStore(BaseVectorStore):
            """Fallback FAISS vector store."""

        class IPFSDatasetsMCPServer:
            """Fallback MCP server implementation."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                """No-op constructor; real implementation requires optional dependencies."""
                pass

        class FastAPISettings:
            """Fallback FastAPI settings with safe defaults."""

            def __init__(self) -> None:
                """Initialise settings with defaults; SECRET_KEY is required at runtime."""
                self.app_name = "IPFS Datasets API"
                self.app_version = "1.0.0"
                self.debug = False
                self.environment = "development"
                self.host = "0.0.0.0"
                self.port = 8000
                self.reload = False
                # CRITICAL: SECRET_KEY must be set via environment variable
                # Fail fast if not set rather than using insecure default
                import os
                if not os.environ.get("SECRET_KEY"):
                    raise ValueError(
                        "SECRET_KEY environment variable is required for security. "
                        "Set it to a strong random value: export SECRET_KEY='your-secret-key-here'"
                    )
                self.secret_key = os.environ["SECRET_KEY"]
                self.algorithm = "HS256"
                self.access_token_expire_minutes = 30

# Load configuration (SECRET_KEY may be absent in test environments)
try:
    settings = FastAPISettings()
    SECRET_KEY = settings.secret_key
    ALGORITHM = settings.algorithm
    ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
except ValueError as _cfg_err:
    import os as _os
    logger.warning(f"FastAPISettings could not be fully initialised: {_cfg_err}. "
                   "Using fallback values — set SECRET_KEY env var for production.")
    settings = None
    SECRET_KEY = _os.environ.get("SECRET_KEY", "dev-fallback-key-NOT-for-production")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30

if CryptContext:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
else:
    logger.warning("passlib not available; falling back to SHA-256 password hashing.")

    class _FallbackPasswordContext:
        """Fallback password hashing when passlib is unavailable."""

        def hash(self, password: str) -> str:
            """Generate a SHA-256 hash for the password."""
            return hashlib.sha256(password.encode("utf-8")).hexdigest()

        def verify(self, plain_password: str, hashed_password: str) -> bool:
            """Verify a plain password against a SHA-256 hash."""
            return self.hash(plain_password) == hashed_password

    pwd_context = _FallbackPasswordContext()
security = HTTPBearer()

# Rate limiting configuration
RATE_LIMITS = {
    "/embeddings/generate": {"requests": 100, "window": 3600},  # 100 requests per hour
    "/search/semantic": {"requests": 1000, "window": 3600},     # 1000 searches per hour
    "/admin/*": {"requests": 50, "window": 3600},               # 50 admin requests per hour
}

# Global rate limiting storage (in production, use Redis)
rate_limit_storage: Dict[str, Dict[str, Any]] = {}

# Pydantic models for API
class TokenResponse(BaseModel):
    """Response body returned by authentication endpoints."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class UserCredentials(BaseModel):
    """Credentials submitted by the client to obtain a JWT token."""
    username: str
    password: str

class EmbeddingGenerationRequest(BaseModel):
    """Request body for the /embeddings/generate endpoint."""
    text: Union[str, List[str]]
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    normalize: bool = True
    batch_size: Optional[int] = 32
    
class VectorSearchRequest(BaseModel):
    """Request body for the /search/vector endpoint."""
    query: Union[str, List[float]]
    top_k: int = Field(default=10, ge=1, le=100)
    collection_name: str
    filter_criteria: Optional[Dict[str, Any]] = None
    include_metadata: bool = True
    
class AnalysisRequest(BaseModel):
    """Request body for vector analysis endpoints (clustering, quality, etc.)."""
    vectors: List[List[float]]
    analysis_type: str = Field(..., pattern="^(clustering|quality|similarity|drift)$")
    parameters: Optional[Dict[str, Any]] = None

# Additional Pydantic models
class DatasetLoadRequest(BaseModel):
    """Request body for loading a dataset from a source."""
    source: str
    format: Optional[str] = None
    options: Optional[Dict[str, Any]] = None

class DatasetProcessRequest(BaseModel):
    """Request body for applying transformation operations to a dataset."""
    dataset_source: Union[str, Dict[str, Any]]
    operations: List[Dict[str, Any]]
    output_id: Optional[str] = None

class DatasetSaveRequest(BaseModel):
    """Request body for persisting a dataset to a destination."""
    dataset_data: Union[str, Dict[str, Any]]
    destination: str
    format: Optional[str] = "json"
    options: Optional[Dict[str, Any]] = None

class IPFSPinRequest(BaseModel):
    """Request body for pinning content to IPFS."""
    content_source: Union[str, Dict[str, Any]]
    recursive: bool = True
    wrap_with_directory: bool = False
    hash_algo: str = "sha2-256"

class WorkflowRequest(BaseModel):
    """Request body for submitting a multi-step workflow."""
    workflow_name: str
    steps: List[Dict[str, Any]]
    parameters: Optional[Dict[str, Any]] = None

class VectorIndexRequest(BaseModel):
    """Request body for creating or updating a vector index."""
    vectors: List[List[float]]
    dimension: Optional[int] = None
    metric: str = "cosine"
    metadata: Optional[List[Dict[str, Any]]] = None
    index_id: Optional[str] = None
    index_name: Optional[str] = None

# FastAPI app initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("🚀 Starting IPFS Datasets FastAPI Service...")
    
    # Initialize MCP server
    app.state.mcp_server = IPFSDatasetsMCPServer()
    
    # Initialize vector stores
    app.state.vector_stores = {}
    
    # Initialize embedding core
    app.state.embedding_core = IPFSEmbeddings()
    
    logger.info("✅ FastAPI service initialized successfully")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down FastAPI service...")

app = FastAPI(
    title="IPFS Datasets API",
    description="REST API for IPFS Datasets with advanced embedding and vector search capabilities",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Configure appropriately for production
)

# Authentication functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Generate password hash."""
    return pwd_context.hash(password)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Get current authenticated user."""
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    
    # In production, fetch user from database
    user = {"username": username, "user_id": payload.get("user_id")}
    return user

# Rate limiting
async def check_rate_limit(request: Request, endpoint: str) -> None:
    """Check if request exceeds rate limit."""
    client_ip = request.client.host
    current_time = int(time.time())
    
    # Get rate limit config for endpoint
    rate_config = None
    for pattern, config in RATE_LIMITS.items():
        if pattern.endswith("*"):
            if endpoint.startswith(pattern[:-1]):
                rate_config = config
                break
        elif pattern == endpoint:
            rate_config = config
            break
    
    if not rate_config:
        return  # No rate limit configured
    
    # Check rate limit
    key = f"{client_ip}:{endpoint}"
    if key not in rate_limit_storage:
        rate_limit_storage[key] = {"requests": 0, "window_start": current_time}
    
    rate_data = rate_limit_storage[key]
    
    # Reset window if expired
    if current_time - rate_data["window_start"] >= rate_config["window"]:
        rate_data["requests"] = 0
        rate_data["window_start"] = current_time
    
    # Check limit
    if rate_data["requests"] >= rate_config["requests"]:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {rate_config['requests']} requests per {rate_config['window']} seconds"
        )
    
    rate_data["requests"] += 1

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }

# Authentication endpoints
@app.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserCredentials):
    """Authenticate user and return JWT token."""
    # In production, validate against user database
    # For demo purposes, accept any credentials
    if not credentials.username or not credentials.password:
        raise HTTPException(status_code=400, detail="Username and password required")
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": credentials.username, "user_id": str(uuid.uuid4())},
        expires_delta=access_token_expires
    )
    
    return TokenResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

@app.post("/auth/refresh")
async def refresh_token(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Refresh JWT token."""
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": current_user["username"], "user_id": current_user["user_id"]},
        expires_delta=access_token_expires
    )
    
    return TokenResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

# Main API endpoints will be added in the next part...

# Embedding endpoints
@app.post("/embeddings/generate")
async def generate_embeddings_api(
    request: EmbeddingGenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(get_current_user),
    http_request: Request = None
):
    """Generate embeddings for text input."""
    await check_rate_limit(http_request, "/embeddings/generate")
    
    try:
        # Use our embedding generation tool
        embedding_request = EmbeddingRequest(
            text=request.text,
            model=request.model,
            normalize=request.normalize
        )
        
        # Generate embeddings using the migrated tools
        from .mcp_server.tools.embedding_tools.embedding_generation import generate_embeddings as mcp_generate
        
        result = await mcp_generate({
            "text": request.text,
            "model": request.model,
            "normalize": request.normalize,
            "batch_size": request.batch_size
        })
        
        # Log the request
        background_tasks.add_task(
            log_api_request,
            user_id=current_user["user_id"],
            endpoint="/embeddings/generate",
            input_size=len(request.text) if isinstance(request.text, str) else len(request.text),
            status="success"
        )
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Embedding tool not found: {e}")
        background_tasks.add_task(
            log_api_request,
            user_id=current_user["user_id"],
            endpoint="/embeddings/generate",
            status="error",
            error=str(e)
        )
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Embedding generation execution failed: {e}", exc_info=e.original_error)
        background_tasks.add_task(
            log_api_request,
            user_id=current_user["user_id"],
            endpoint="/embeddings/generate",
            status="error",
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid embedding request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in embedding generation: {e}", exc_info=True)
        background_tasks.add_task(
            log_api_request,
            user_id=current_user["user_id"],
            endpoint="/embeddings/generate",
            status="error",
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {str(e)}")

@app.post("/embeddings/batch")
async def batch_generate_embeddings(
    texts: List[str],
    model: str = "sentence-transformers/all-MiniLM-L6-v2",
    normalize: bool = True,
    current_user: Dict[str, Any] = Depends(get_current_user),
    http_request: Request = None
):
    """Generate embeddings for multiple texts in batch."""
    await check_rate_limit(http_request, "/embeddings/generate")
    
    try:
        from .mcp_server.tools.embedding_tools.advanced_embedding_generation import batch_generate_embeddings as mcp_batch
        
        result = await mcp_batch({
            "texts": texts,
            "model": model,
            "normalize": normalize,
            "batch_size": 32
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Batch embedding tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Batch embedding execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Batch embedding generation failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid batch embedding request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in batch embedding generation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch embedding generation failed: {str(e)}")

# Vector search endpoints
@app.post("/search/semantic")
async def semantic_search(
    request: VectorSearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    http_request: Request = None
):
    """Perform semantic vector search."""
    await check_rate_limit(http_request, "/search/semantic")
    
    try:
        from .mcp_server.tools.embedding_tools.advanced_search import semantic_search as mcp_search
        
        result = await mcp_search({
            "query": request.query,
            "top_k": request.top_k,
            "collection_name": request.collection_name,
            "filter_criteria": request.filter_criteria,
            "include_metadata": request.include_metadata
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Semantic search tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Semantic search execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Semantic search failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid search request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in semantic search: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Semantic search failed: {str(e)}")

@app.post("/search/hybrid")
async def hybrid_search(
    query: str,
    collection_name: str,
    top_k: int = 10,
    vector_weight: float = 0.7,
    text_weight: float = 0.3,
    current_user: Dict[str, Any] = Depends(get_current_user),
    http_request: Request = None
):
    """Perform hybrid vector + text search."""
    await check_rate_limit(http_request, "/search/semantic")
    
    try:
        from .mcp_server.tools.embedding_tools.advanced_search import hybrid_search as mcp_hybrid
        
        result = await mcp_hybrid({
            "query": query,
            "collection_name": collection_name,
            "top_k": top_k,
            "vector_weight": vector_weight,
            "text_weight": text_weight
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Hybrid search tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Hybrid search execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Hybrid search failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid hybrid search request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in hybrid search: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Hybrid search failed: {str(e)}")

# Analysis endpoints
@app.post("/analysis/clustering")
async def clustering_analysis(
    request: AnalysisRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Perform clustering analysis on vectors."""
    try:
        from .mcp_server.tools.analysis_tools.analysis_tools import clustering_analysis as mcp_clustering
        
        result = await mcp_clustering({
            "vectors": request.vectors,
            "algorithm": request.parameters.get("algorithm", "kmeans") if request.parameters else "kmeans",
            "n_clusters": request.parameters.get("n_clusters", 5) if request.parameters else 5
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Clustering tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Clustering analysis execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Clustering analysis failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid clustering request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in clustering analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Clustering analysis failed: {str(e)}")

@app.post("/analysis/quality")
async def quality_assessment(
    vectors: List[List[float]],
    metadata: Optional[Dict[str, Any]] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Assess embedding quality."""
    try:
        from .mcp_server.tools.analysis_tools.analysis_tools import quality_assessment as mcp_quality
        
        result = await mcp_quality({
            "vectors": vectors,
            "metadata": metadata
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Quality assessment tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Quality assessment execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Quality assessment failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid quality assessment request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in quality assessment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Quality assessment failed: {str(e)}")

# Admin endpoints
@app.get("/admin/stats")
async def get_system_stats(
    current_user: Dict[str, Any] = Depends(get_current_user),
    http_request: Request = None
):
    """Get system statistics."""
    await check_rate_limit(http_request, "/admin/stats")
    
    try:
        from .mcp_server.tools.monitoring_tools.monitoring_tools import get_system_stats as mcp_stats
        
        result = await mcp_stats({})
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"System stats tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"System stats execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Failed to get system stats: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error getting system stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get system stats: {str(e)}")

@app.get("/admin/health")
async def detailed_health_check(
    current_user: Dict[str, Any] = Depends(get_current_user),
    http_request: Request = None
):
    """Get detailed health information."""
    await check_rate_limit(http_request, "/admin/health")
    
    try:
        from .mcp_server.tools.monitoring_tools.monitoring_tools import health_check as mcp_health
        
        result = await mcp_health({})
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Health check tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Health check execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in health check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

# MCP Tools endpoint
@app.get("/tools/list")
async def list_available_tools(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """List all available MCP tools."""
    try:
        # Get tools from MCP server
        mcp_server = app.state.mcp_server
        tools = list(mcp_server.tools.keys()) if hasattr(mcp_server, 'tools') else []
        
        return {
            "tools": tools,
            "count": len(tools),
            "categories": [
                "embedding_tools", "analysis_tools", "workflow_tools",
                "admin_tools", "cache_tools", "monitoring_tools",
                "sparse_embedding_tools", "background_task_tools",
                "auth_tools", "session_tools", "rate_limiting_tools",
                "data_processing_tools", "index_management_tools",
                "vector_store_tools", "storage_tools"
            ]
        }
        
    except ConfigurationError as e:
        logger.error(f"MCP server configuration error: {e}")
        raise HTTPException(status_code=500, detail=f"Server configuration error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error listing tools: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list tools: {str(e)}")

@app.post("/tools/execute/{tool_name}")
async def execute_tool(
    tool_name: str,
    parameters: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Execute a specific MCP tool."""
    try:
        mcp_server = app.state.mcp_server
        
        if not hasattr(mcp_server, 'tools') or tool_name not in mcp_server.tools:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
        
        # Execute the tool
        tool_func = mcp_server.tools[tool_name]
        result = await tool_func(parameters)
        
        return {
            "tool": tool_name,
            "status": "success",
            "result": result
        }
        
    except ToolNotFoundError as e:
        logger.error(f"Tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Tool execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error executing tool: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {str(e)}")

# Background task functions
async def run_workflow_background(
    task_id: str,
    workflow_name: str,
    steps: List[Dict[str, Any]],
    parameters: Optional[Dict[str, Any]],
    user_id: str
):
    """Run workflow in background."""
    try:
        from .mcp_server.tools.workflow_tools.workflow_tools import execute_workflow as mcp_workflow
        
        result = await mcp_workflow({
            "workflow_name": workflow_name,
            "steps": steps,
            "parameters": parameters,
            "task_id": task_id
        })
        
        # Log completion
        await log_api_request(
            user_id=user_id,
            endpoint="/workflows/execute",
            status="completed"
        )
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Workflow tool not found: {e}")
        await log_api_request(
            user_id=user_id,
            endpoint="/workflows/execute",
            status="error",
            error=str(e)
        )
    except ToolExecutionError as e:
        logger.error(f"Background workflow execution failed: {e}", exc_info=e.original_error)
        await log_api_request(
            user_id=user_id,
            endpoint="/workflows/execute",
            status="error",
            error=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error in background workflow: {e}", exc_info=True)
        await log_api_request(
            user_id=user_id,
            endpoint="/workflows/execute",
            status="error",
            error=str(e)
        )

# Utility functions
async def log_api_request(user_id: str, endpoint: str, input_size: int = None, status: str = "success", error: str = None):
    """Log API request for analytics."""
    try:
        from .mcp_server.tools.audit_tools.audit_tools import record_audit_event
        
        await record_audit_event({
            "action": f"api.{endpoint.replace('/', '.')}",
            "user_id": user_id,
            "resource_type": "api_endpoint",
            "details": {
                "endpoint": endpoint,
                "input_size": input_size,
                "status": status,
                "error": error,
                "timestamp": datetime.utcnow().isoformat()
            }
        })
    except Exception as e:
        logger.warning(f"Failed to log API request: {e}")

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(MCPServerError)
async def mcp_server_error_handler(request: Request, exc: MCPServerError):
    """Handle MCP server custom exceptions."""
    status_code = 500
    if isinstance(exc, ToolNotFoundError):
        status_code = 404
    elif isinstance(exc, (MCPValidationError, ConfigurationError)):
        status_code = 400
    
    logger.error(f"MCP server error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": str(exc),
            "error_type": type(exc).__name__,
            "status_code": status_code,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# Custom OpenAPI schema
def custom_openapi():
    """Generate custom OpenAPI schema."""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="IPFS Datasets API",
        version="1.0.0",
        description="REST API for IPFS Datasets with advanced embedding and vector search capabilities",
        routes=app.routes,
    )
    
    # Add authentication to schema
    openapi_schema["components"]["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    
    # Add security requirement to all endpoints except auth
    for path, methods in openapi_schema["paths"].items():
        if not path.startswith("/auth/") and path != "/health":
            for method in methods:
                if method != "options":
                    methods[method]["security"] = [{"bearerAuth": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Development server with configuration
def run_development_server():
    """Run development server with configuration."""
    try:
        # Configure logging
        logging.basicConfig(
            level=logging.INFO if not settings.debug else logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        
        logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version}")
        logger.info(f"Environment: {settings.environment}")
        logger.info(f"Debug mode: {settings.debug}")
        
        uvicorn.run(
            "ipfs_datasets_py.fastapi_service:app",
            host=settings.host,
            port=settings.port,
            reload=settings.reload and settings.debug,
            log_level="debug" if settings.debug else "info",
            access_log=True
        )
    except ConfigurationError as e:
        logger.error(f"Server configuration error: {e}")
        raise
    except ServerStartupError as e:
        logger.error(f"Failed to start server: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error starting server: {e}", exc_info=True)
        raise

def run_production_server():
    """Run production server with optimized settings."""
    try:
        # Configure production logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        
        logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version} (Production)")
        
        uvicorn.run(
            "ipfs_datasets_py.fastapi_service:app",
            host=settings.host,
            port=settings.port,
            workers=4,  # Multiple workers for production
            log_level="info",
            access_log=True,
            loop="uvloop"  # Use uvloop for better performance
        )
    except ConfigurationError as e:
        logger.error(f"Production server configuration error: {e}")
        raise
    except ServerStartupError as e:
        logger.error(f"Failed to start production server: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error starting production server: {e}", exc_info=True)
        raise

# Dataset Management Endpoints
@app.post("/datasets/load")
async def load_dataset(
    request: DatasetLoadRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Load a dataset from various sources."""
    try:
        from .mcp_server.tools.dataset_tools.load_dataset import load_dataset as mcp_load
        
        result = await mcp_load({
            "source": request.source,
            "format": request.format,
            "options": request.options
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Dataset loading tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Dataset loading execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Dataset loading failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid dataset load request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in dataset loading: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Dataset loading failed: {str(e)}")

@app.post("/datasets/process")
async def process_dataset(
    request: DatasetProcessRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Process a dataset with a series of operations."""
    try:
        from .mcp_server.tools.dataset_tools.process_dataset import process_dataset as mcp_process
        
        result = await mcp_process({
            "dataset_source": request.dataset_source,
            "operations": request.operations,
            "output_id": request.output_id
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Dataset processing tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Dataset processing execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Dataset processing failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid dataset process request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in dataset processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Dataset processing failed: {str(e)}")

@app.post("/datasets/save")
async def save_dataset(
    request: DatasetSaveRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Save a dataset to a destination."""
    try:
        from .mcp_server.tools.dataset_tools.save_dataset import save_dataset as mcp_save
        
        result = await mcp_save({
            "dataset_data": request.dataset_data,
            "destination": request.destination,
            "format": request.format,
            "options": request.options
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Dataset saving tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Dataset saving execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Dataset saving failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid dataset save request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in dataset saving: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Dataset saving failed: {str(e)}")

@app.post("/datasets/convert")
async def convert_dataset_format(
    dataset_id: str,
    target_format: str,
    output_path: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Convert a dataset to a different format."""
    try:
        from .mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format as mcp_convert
        
        result = await mcp_convert({
            "dataset_id": dataset_id,
            "target_format": target_format,
            "output_path": output_path,
            "options": options
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Dataset conversion tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Dataset conversion execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Dataset conversion failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid dataset conversion request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in dataset conversion: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Dataset conversion failed: {str(e)}")

# IPFS Endpoints
@app.post("/ipfs/pin")
async def pin_to_ipfs(
    request: IPFSPinRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Pin content to IPFS."""
    try:
        from .mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs as mcp_pin
        
        result = await mcp_pin({
            "content_source": request.content_source,
            "recursive": request.recursive,
            "wrap_with_directory": request.wrap_with_directory,
            "hash_algo": request.hash_algo
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"IPFS pinning tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"IPFS pinning execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"IPFS pinning failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid IPFS pin request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in IPFS pinning: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"IPFS pinning failed: {str(e)}")

@app.get("/ipfs/get/{cid}")
async def get_from_ipfs(
    cid: str,
    output_path: Optional[str] = None,
    timeout_seconds: int = 60,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get content from IPFS by CID."""
    try:
        from .mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs as mcp_get
        
        result = await mcp_get({
            "cid": cid,
            "output_path": output_path,
            "timeout_seconds": timeout_seconds
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"IPFS retrieval tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"IPFS retrieval execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"IPFS retrieval failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid IPFS get request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in IPFS retrieval: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"IPFS retrieval failed: {str(e)}")

# Vector Store Endpoints
@app.post("/vectors/create-index")
async def create_vector_index(
    request: VectorIndexRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Create a vector index for similarity search."""
    try:
        from .mcp_server.tools.vector_tools.create_vector_index import create_vector_index as mcp_create_index
        
        result = await mcp_create_index({
            "vectors": request.vectors,
            "dimension": request.dimension,
            "metric": request.metric,
            "metadata": request.metadata,
            "index_id": request.index_id,
            "index_name": request.index_name
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Vector index creation tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Vector index creation execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Vector index creation failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid vector index creation request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in vector index creation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Vector index creation failed: {str(e)}")

@app.post("/vectors/search")
async def search_vector_index(
    index_id: str,
    query_vector: List[float],
    top_k: int = 5,
    include_metadata: bool = True,
    include_distances: bool = True,
    filter_metadata: Optional[Dict[str, Any]] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Search a vector index for similar vectors."""
    try:
        from .mcp_server.tools.vector_tools.search_vector_index import search_vector_index as mcp_search_index
        
        result = await mcp_search_index({
            "index_id": index_id,
            "query_vector": query_vector,
            "top_k": top_k,
            "include_metadata": include_metadata,
            "include_distances": include_distances,
            "filter_metadata": filter_metadata
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Vector index search tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Vector index search execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Vector index search failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid vector index search request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in vector index search: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Vector index search failed: {str(e)}")

# Workflow Endpoints
@app.post("/workflows/execute")
async def execute_workflow(
    request: WorkflowRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Execute a workflow with multiple steps."""
    try:
        from .mcp_server.tools.workflow_tools.workflow_tools import execute_workflow as mcp_workflow
        
        # Execute workflow in background if it's long-running
        task_id = str(uuid.uuid4())
        
        background_tasks.add_task(
            run_workflow_background,
            task_id,
            request.workflow_name,
            request.steps,
            request.parameters,
            current_user["user_id"]
        )
        
        return {
            "task_id": task_id,
            "status": "started",
            "workflow_name": request.workflow_name,
            "steps_count": len(request.steps)
        }
        
    except ToolNotFoundError as e:
        logger.error(f"Workflow execution tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Workflow execution failed: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid workflow execution request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in workflow execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")

@app.get("/workflows/status/{task_id}")
async def get_workflow_status(
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get the status of a running workflow."""
    try:
        from .mcp_server.tools.workflow_tools.workflow_tools import get_workflow_status as mcp_status
        
        result = await mcp_status({"task_id": task_id})
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Workflow status tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Failed to get workflow status: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Failed to get workflow status: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid workflow status request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error getting workflow status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get workflow status: {str(e)}")

# Audit and Monitoring Endpoints
@app.post("/audit/record")
async def record_audit_event(
    action: str,
    resource_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    severity: str = "info",
    tags: Optional[List[str]] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Record an audit event."""
    try:
        from .mcp_server.tools.audit_tools.audit_tools import record_audit_event as mcp_audit
        
        result = await mcp_audit({
            "action": action,
            "resource_id": resource_id,
            "resource_type": resource_type,
            "user_id": current_user["user_id"],
            "details": details,
            "severity": severity,
            "tags": tags
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Audit event tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Failed to record audit event: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Failed to record audit event: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid audit event request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error recording audit event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to record audit event: {str(e)}")

@app.get("/audit/report")
async def generate_audit_report(
    report_type: str = "comprehensive",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    output_format: str = "json",
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Generate an audit report."""
    try:
        from .mcp_server.tools.audit_tools.audit_tools import generate_audit_report as mcp_report
        
        result = await mcp_report({
            "report_type": report_type,
            "start_time": start_time,
            "end_time": end_time,
            "output_format": output_format
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Audit report tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Failed to generate audit report: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Failed to generate audit report: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid audit report request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error generating audit report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate audit report: {str(e)}")

# Cache Management Endpoints
@app.get("/cache/stats")
async def get_cache_stats(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get cache statistics."""
    try:
        from .mcp_server.tools.cache_tools.cache_tools import get_cache_stats as mcp_cache_stats
        
        result = await mcp_cache_stats({})
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Cache stats tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Failed to get cache stats: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Failed to get cache stats: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error getting cache stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get cache stats: {str(e)}")

@app.post("/cache/clear")
async def clear_cache(
    cache_type: Optional[str] = None,
    pattern: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Clear cache entries."""
    try:
        from .mcp_server.tools.cache_tools.cache_tools import clear_cache as mcp_clear_cache
        
        result = await mcp_clear_cache({
            "cache_type": cache_type,
            "pattern": pattern
        })
        
        return result
        
    except ToolNotFoundError as e:
        logger.error(f"Clear cache tool not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ToolExecutionError as e:
        logger.error(f"Failed to clear cache: {e}", exc_info=e.original_error)
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")
    except MCPValidationError as e:
        logger.warning(f"Invalid clear cache request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error clearing cache: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")
