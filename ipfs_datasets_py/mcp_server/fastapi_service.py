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
import os
import threading
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
try:
    from hypercorn.config import Config as HypercornConfig
    from hypercorn.trio import serve as hypercorn_serve
    HAVE_HYPERCORN = True
except ImportError:  # pragma: no cover - optional dependency
    HAVE_HYPERCORN = False
try:
    import uvicorn
    HAVE_UVICORN = True
except ImportError:  # pragma: no cover - optional dependency
    uvicorn = None  # type: ignore[assignment]
    HAVE_UVICORN = False

logger = logging.getLogger(__name__)
wallet_router = None

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

try:
    from ..wallet.api import router as wallet_router
except ImportError:
    try:
        from wallet.api import router as wallet_router
    except ImportError:
        wallet_router = None

# Load configuration (SECRET_KEY may be absent in test environments)
try:
    settings = FastAPISettings()
    SECRET_KEY = settings.secret_key
    ALGORITHM = settings.algorithm
    ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
except ValueError as _cfg_err:
    import os as _os
    _env = _os.environ.get("ENVIRONMENT", "development")
    SECRET_KEY = _os.environ.get("SECRET_KEY", "")
    if not SECRET_KEY:
        if _env == "production":
            raise RuntimeError(
                "FATAL: SECRET_KEY environment variable is required in production. "
                "Set: export SECRET_KEY='<strong-random-value>'"
            ) from _cfg_err
        SECRET_KEY = "dev-fallback-key-NOT-for-production"
        logger.warning(
            "FastAPISettings could not be initialised: %s. "
            "Using INSECURE fallback SECRET_KEY — set SECRET_KEY env var for production.", _cfg_err
        )
    settings = None
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30

class _FallbackPasswordContext:
    """Fallback password hashing when passlib is unavailable."""

    def hash(self, password: str) -> str:
        """Generate a SHA-256 hash for the password."""
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plain password against a SHA-256 hash."""
        return self.hash(plain_password) == hashed_password


if CryptContext:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
else:
    logger.warning("passlib not available; falling back to SHA-256 password hashing.")
    pwd_context = _FallbackPasswordContext()
security = HTTPBearer(auto_error=False)

# Rate limiting configuration
RATE_LIMITS = {
    "/embeddings/generate": {"requests": 100, "window": 3600},  # 100 requests per hour
    "/search/semantic": {"requests": 1000, "window": 3600},     # 1000 searches per hour
    "/admin/*": {"requests": 50, "window": 3600},               # 50 admin requests per hour
}

# Global rate limiting storage (in production, use Redis)
rate_limit_storage: Dict[str, Dict[str, Any]] = {}
_rate_limit_last_cleanup: float = time.time()
_RATE_LIMIT_MAX_ENTRIES = 50000
_rate_limit_lock = None
_rate_limit_lock_init = threading.Lock()

def _get_rate_limit_lock():
    """Lazy init of rate limit lock (double-checked locking for thread safety)."""
    global _rate_limit_lock
    if _rate_limit_lock is None:
        with _rate_limit_lock_init:
            if _rate_limit_lock is None:
                _rate_limit_lock = anyio.Lock()
    return _rate_limit_lock

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
# Phase C2: track server start time for uptime reporting in health endpoints.
_SERVER_START_TIME: float = time.time()

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

    # Shutdown — persist state and clean up resources
    logger.info("🛑 Shutting down FastAPI service...")
    try:
        # Persist EventDAG state
        from .event_dag import get_event_dag
        dag = get_event_dag()
        dag_state = dag.to_dict(include_events=True)
        if dag_state.get("total_events", 0) > 0:
            import json as _json
            state_dir = os.path.join(
                os.environ.get("MCPPP_STORAGE_DIR", os.path.expanduser("~/.ipfs_datasets/state"))
            )
            os.makedirs(state_dir, exist_ok=True)
            dag_path = os.path.join(state_dir, "event_dag.json")
            with open(dag_path, "w") as f:
                _json.dump(dag_state, f)
            logger.info("EventDAG persisted: %d events", dag_state["total_events"])
    except Exception as e:
        logger.warning("EventDAG persistence failed on shutdown: %s", e)

    try:
        # Persist P2P peer state
        from .p2p_libp2p_transport import get_p2p_node
        node = get_p2p_node()
        if node._started:
            await node.stop()
    except Exception as e:
        logger.debug("P2P shutdown: %s", e)

app = FastAPI(
    title="IPFS Datasets API",
    description="REST API for IPFS Datasets with advanced embedding and vector search capabilities",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

if wallet_router is not None:
    app.include_router(wallet_router)

# Middleware configuration
_cors_origins = os.environ.get("MCP_CORS_ORIGINS", "").strip()
_allowed_origins = _cors_origins.split(",") if _cors_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=(_allowed_origins != ["*"]),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=os.environ.get("MCP_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")
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
    base = datetime.utcnow()
    if expires_delta:
        expire = base + expires_delta
    else:
        expire = base + timedelta(minutes=15)
    to_encode.update({"exp": int(expire.timestamp())})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """Get current authenticated user."""
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if credentials is None:
        raise credentials_exception

    payload: Optional[Dict[str, Any]] = None
    decode_keys = [SECRET_KEY]
    env_secret = os.environ.get("SECRET_KEY")
    if env_secret and env_secret not in decode_keys:
        decode_keys.append(env_secret)

    for key in decode_keys:
        try:
            payload = jwt.decode(credentials.credentials, key, algorithms=[ALGORITHM])
            break
        except jwt.PyJWTError:
            continue

    if payload is None:
        raise credentials_exception

    username: str = payload.get("sub")
    if username is None:
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
    
    # Periodic cleanup to prevent unbounded memory growth
    global _rate_limit_last_cleanup
    lock = _get_rate_limit_lock()
    if len(rate_limit_storage) > _RATE_LIMIT_MAX_ENTRIES or (current_time - _rate_limit_last_cleanup > 300):
        async with lock:
            stale = [k for k, v in rate_limit_storage.items()
                     if current_time - v.get("window_start", 0) > 7200]
            for k in stale:
                del rate_limit_storage[k]
            if len(rate_limit_storage) > _RATE_LIMIT_MAX_ENTRIES:
                rate_limit_storage.clear()
            _rate_limit_last_cleanup = current_time
    
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
    """Liveness probe — returns 200 as long as the process is running."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "uptime_seconds": round(time.time() - _SERVER_START_TIME, 1),
    }


@app.get("/health/ready")
async def readiness_check():
    """Readiness probe — verifies that key dependencies are operational.

    Returns HTTP 200 when all checks pass, HTTP 503 otherwise so that
    load-balancers can remove the instance from rotation.
    """
    checks: Dict[str, Any] = {}
    all_ok = True

    # Check 1: monitoring metrics collector is alive
    try:
        from .monitoring import get_metrics_collector
        collector = get_metrics_collector()
        checks["metrics_collector"] = {"status": "ok", "uptime_seconds": round(
            getattr(collector, "_uptime_seconds", time.time() - _SERVER_START_TIME), 1
        )}
    except Exception as exc:  # pragma: no cover
        checks["metrics_collector"] = {"status": "error", "error": str(exc)}
        all_ok = False

    # Check 2: tool manager has at least one category loaded
    try:
        from .hierarchical_tool_manager import get_tool_manager
        mgr = get_tool_manager()
        mgr.discover_categories()
        n_cats = len(mgr.categories)
        checks["tool_manager"] = {"status": "ok", "categories": n_cats}
        if n_cats == 0:
            checks["tool_manager"]["status"] = "warning"
    except Exception as exc:  # pragma: no cover
        checks["tool_manager"] = {"status": "error", "error": str(exc)}
        all_ok = False

    status_code = 200 if all_ok else 503
    body = {
        "status": "ready" if all_ok else "not_ready",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": round(time.time() - _SERVER_START_TIME, 1),
        "checks": checks,
    }
    from fastapi.responses import JSONResponse
    return JSONResponse(content=body, status_code=status_code)


@app.get("/metrics")
async def prometheus_metrics():
    """Expose server metrics in a simple text format compatible with Prometheus.

    Each metric is emitted on its own line:
    ``# HELP <name> <description>``
    ``<name>{<labels>} <value>``
    """
    try:
        from .monitoring import get_metrics_collector
        collector = get_metrics_collector()
        summary = collector.get_metrics_summary()
    except Exception:  # pragma: no cover
        summary = {}

    uptime = round(time.time() - _SERVER_START_TIME, 1)
    req = summary.get("request_metrics", {})
    sys_m = summary.get("system_metrics", {})

    lines = [
        "# HELP mcp_uptime_seconds Seconds since the server started",
        f"mcp_uptime_seconds {uptime}",
        "# HELP mcp_requests_total Total HTTP requests processed",
        f"mcp_requests_total {req.get('total_requests', 0)}",
        "# HELP mcp_errors_total Total errors encountered",
        f"mcp_errors_total {req.get('total_errors', 0)}",
        "# HELP mcp_active_requests Requests currently in flight",
        f"mcp_active_requests {req.get('active_requests', 0)}",
        "# HELP mcp_avg_response_time_ms Average response time in milliseconds",
        f"mcp_avg_response_time_ms {req.get('avg_response_time_ms', 0.0):.3f}",
        "# HELP process_cpu_percent CPU utilisation percent",
        f"process_cpu_percent {sys_m.get('cpu_percent', 0.0):.1f}",
        "# HELP process_memory_percent Memory utilisation percent",
        f"process_memory_percent {sys_m.get('memory_percent', 0.0):.1f}",
    ]

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

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
    """Run development server with Hypercorn+Trio (preferred) or uvicorn fallback."""
    import trio

    # Configure logging
    logging.basicConfig(
        level=logging.INFO if not settings.debug else logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")

    if HAVE_HYPERCORN:
        config = HypercornConfig()
        config.bind = [f"{settings.host}:{settings.port}"]
        config.worker_class = "trio"
        config.loglevel = "DEBUG" if settings.debug else "INFO"
        config.accesslog = "-"
        logger.info("Using Hypercorn+Trio runtime")
        trio.run(hypercorn_serve, app, config)
    elif HAVE_UVICORN:
        logger.warning("Hypercorn not available — falling back to uvicorn (non-Trio)")
        uvicorn.run(
            "ipfs_datasets_py.fastapi_service:app",
            host=settings.host,
            port=settings.port,
            reload=settings.reload and settings.debug,
            log_level="debug" if settings.debug else "info",
            access_log=True
        )
    else:
        raise RuntimeError("No ASGI server available. Install hypercorn[trio] or uvicorn.")

def run_production_server():
    """Run production server with Hypercorn+Trio."""
    import trio

    # Configure production logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version} (Production)")

    if HAVE_HYPERCORN:
        config = HypercornConfig()
        config.bind = [f"{settings.host}:{settings.port}"]
        config.worker_class = "trio"
        config.loglevel = "INFO"
        config.accesslog = "-"
        config.workers = int(os.environ.get("MCP_WORKERS", "4"))
        logger.info("Using Hypercorn+Trio runtime (%d workers)", config.workers)
        trio.run(hypercorn_serve, app, config)
    elif HAVE_UVICORN:
        logger.warning("Hypercorn not available — falling back to uvicorn")
        uvicorn.run(
            "ipfs_datasets_py.fastapi_service:app",
            host=settings.host,
            port=settings.port,
            workers=4,
            log_level="info",
            access_log=True,
        )
    else:
        raise RuntimeError("No ASGI server available. Install hypercorn[trio] or uvicorn.")

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


# =============================================================================
# MCP++ Protocol Endpoints (Profiles A-E)
# =============================================================================

# --- Profile A: MCP-IDL Interface Discovery ---

@app.get("/mcp/interfaces")
async def list_mcp_interfaces():
    """List all registered MCP++ interface descriptors (Profile A)."""
    try:
        from .interface_descriptor import get_interface_repository
        repo = get_interface_repository()
        descriptors = repo.list()
        return {
            "interfaces": [
                {
                    "name": d.name,
                    "namespace": d.namespace,
                    "version": d.version,
                    "interface_cid": str(d.interface_cid) if hasattr(d, 'interface_cid') else "",
                    "methods": [{"name": m.name, "input_schema_cid": str(getattr(m, 'input_schema_cid', '')), "output_schema_cid": str(getattr(m, 'output_schema_cid', ''))} for m in (d.methods if hasattr(d, 'methods') else [])],
                    "semantic_tags": list(d.semantic_tags) if hasattr(d, 'semantic_tags') else [],
                }
                for d in descriptors
            ],
            "count": len(descriptors),
        }
    except ImportError:
        return {"interfaces": [], "count": 0, "error": "interface_descriptor module not available"}
    except Exception as e:
        logger.error(f"Failed to list interfaces: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list interfaces: {e}")


@app.get("/mcp/interfaces/{interface_cid}")
async def get_mcp_interface(interface_cid: str):
    """Get a specific interface descriptor by CID (Profile A)."""
    try:
        from .interface_descriptor import get_interface_repository
        repo = get_interface_repository()
        descriptor = repo.get(interface_cid)
        if descriptor is None:
            raise HTTPException(status_code=404, detail=f"Interface not found: {interface_cid}")
        return {
            "name": descriptor.name,
            "namespace": descriptor.namespace,
            "version": descriptor.version,
            "interface_cid": str(descriptor.interface_cid) if hasattr(descriptor, 'interface_cid') else interface_cid,
            "methods": [{"name": m.name} for m in (descriptor.methods if hasattr(descriptor, 'methods') else [])],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get interface: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- Profile B: CID-Native Execution with Envelope ---

@app.post("/mcp/execute")
async def mcp_execute_with_envelope(request: Request):
    """Execute a tool call with CID-native envelope (Profile B)."""
    try:
        from .cid_artifacts import IntentObject, artifact_cid, EventNode
        body = await request.json()
        # Accept both naming conventions for frontend compatibility:
        # ipfs_accelerate style: {"method": "...", "params": {...}}
        # ipfs_datasets style: {"tool": "...", "arguments": {...}}
        tool_name = body.get("method") or body.get("tool", "")
        arguments = body.get("params") or body.get("arguments", {})
        proof_cid = body.get("proof_cid") or body.get("delegation_cid")
        policy_cid = body.get("policy_cid")

        # Create intent
        intent = IntentObject(
            interface_cid=body.get("interface_cid", ""),
            tool=tool_name,
            input_cid=str(artifact_cid(arguments)),
            correlation_id=str(uuid.uuid4()),
        )
        intent_cid = str(artifact_cid({"tool": tool_name, "input": arguments}))

        # Evaluate policy if available (fail-closed: deny on error)
        decision = "allow" if not policy_cid else "deny"
        if policy_cid:
            try:
                from .temporal_policy import get_policy_evaluator
                evaluator = get_policy_evaluator()
                decision_obj = evaluator.evaluate(intent, policy_cid)
                decision = decision_obj.decision if hasattr(decision_obj, 'decision') else decision_obj.get("decision", "deny")
            except ImportError as e:
                logger.warning(f"Policy module unavailable (fail-closed): {e}")
                decision = "deny"
            except Exception as e:
                logger.error(f"Policy evaluation error (fail-closed): {e}", exc_info=True)
                decision = "deny"

        if decision == "deny":
            return {
                "envelope_cid": str(artifact_cid({"intent": intent_cid, "decision": "deny"})),
                "decision": "deny",
                "justification": "Denied by temporal deontic policy",
            }

        # Execute the tool with timeout (anyio-compatible for Trio/asyncio)
        import time as _time
        start = _time.time()
        output = None
        error_msg = None
        exec_timeout = float(os.environ.get("MCPPP_EXEC_TIMEOUT_S", "30"))
        try:
            mcp_server = app.state.mcp_server if hasattr(app.state, 'mcp_server') else None
            if mcp_server and hasattr(mcp_server, 'tools') and tool_name in mcp_server.tools:
                tool_fn = mcp_server.tools[tool_name]
                if callable(tool_fn):
                    try:
                        import inspect
                        async with anyio.fail_after(exec_timeout):
                            if inspect.iscoroutinefunction(tool_fn):
                                output = await tool_fn(**arguments)
                            else:
                                # Run sync tools in a thread so timeout can cancel them
                                output = await anyio.to_thread.run_sync(
                                    lambda: tool_fn(**arguments), cancellable=True
                                )
                    except TimeoutError:
                        error_msg = f"Execution timeout after {exec_timeout}s"
                else:
                    output = None
            else:
                error_msg = f"Tool not found: {tool_name}"
        except TimeoutError:
            error_msg = f"Execution timeout after {exec_timeout}s"
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
        duration_ms = int((_time.time() - start) * 1000)

        # Build envelope
        output_cid = str(artifact_cid(output or {}))
        receipt_cid = str(artifact_cid({"intent": intent_cid, "output": output_cid, "duration": duration_ms}))
        event_cid = str(artifact_cid({"intent": intent_cid, "receipt": receipt_cid}))
        envelope_cid = str(artifact_cid({"intent": intent_cid, "receipt": receipt_cid, "event": event_cid}))

        # Append to Event DAG
        try:
            from .event_dag import EventDAG
            dag = getattr(app.state, '_event_dag', None)
            if dag is None:
                dag = EventDAG(strict=False)
                app.state._event_dag = dag
            node = EventNode(
                parents=[n.event_cid for n in dag.frontier()] if hasattr(dag, 'frontier') else [],
                intent_cid=intent_cid,
                decision_cid=str(artifact_cid({"decision": decision})),
                receipt_cid=receipt_cid,
            )
            dag.append(node)
        except (ImportError, Exception) as e:
            logger.debug(f"Event DAG append skipped: {e}")

        return {
            "envelope_cid": envelope_cid,
            "event_cid": event_cid,
            "decision": decision,
            "receipt": {
                "receipt_cid": receipt_cid,
                "duration_ms": duration_ms,
                "success": error_msg is None,
                "error": error_msg,
                "output_cid": output_cid,
            },
            "output": output,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP++ execute failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Execution failed: {e}")


# --- Event DAG Endpoints ---

@app.get("/mcp/dag/frontier")
async def get_dag_frontier():
    """Get the current Event DAG frontier (leaf nodes)."""
    try:
        from .event_dag import EventDAG
        dag = getattr(app.state, '_event_dag', None)
        if dag is None:
            return {"frontier": []}
        frontier_nodes = dag.frontier()
        return {"frontier": [str(n.event_cid) if hasattr(n, 'event_cid') else str(n) for n in frontier_nodes]}
    except Exception as e:
        logger.error(f"DAG frontier error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/mcp/dag/history")
async def get_dag_history(limit: int = 50):
    """Get Event DAG history (most recent events)."""
    try:
        from .event_dag import EventDAG
        dag = getattr(app.state, '_event_dag', None)
        if dag is None:
            return {"events": [], "count": 0}
        # Walk the DAG
        all_nodes = list(dag._nodes.values()) if hasattr(dag, '_nodes') else []
        recent = all_nodes[-limit:] if len(all_nodes) > limit else all_nodes
        return {
            "events": [
                {
                    "event_cid": str(n.event_cid),
                    "parents": [str(p) for p in (n.parents or [])],
                    "intent_cid": str(getattr(n, 'intent_cid', '')),
                    "receipt_cid": str(getattr(n, 'receipt_cid', '')),
                }
                for n in recent
            ],
            "count": len(all_nodes),
        }
    except Exception as e:
        logger.error(f"DAG history error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/mcp/dag/provenance/{event_cid}")
async def trace_dag_provenance(event_cid: str):
    """Trace provenance chain from an event CID back to roots."""
    try:
        from .event_dag import EventDAG
        dag = getattr(app.state, '_event_dag', None)
        if dag is None:
            return {"chain": []}
        chain = dag.walk(event_cid) if hasattr(dag, 'walk') else []
        return {
            "chain": [
                {"event_cid": str(n.event_cid), "parents": [str(p) for p in (n.parents or [])]}
                for n in chain
            ]
        }
    except Exception as e:
        logger.error(f"DAG provenance error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- Profile C: UCAN Delegation Endpoints ---

@app.post("/mcp/ucan/delegate")
async def create_ucan_delegation(request: Request):
    """Create a UCAN capability delegation (Profile C)."""
    try:
        from .ucan_delegation import Capability, Delegation, add_delegation
        body = await request.json()
        audience = body.get("audience", "")
        capabilities = body.get("capabilities", [])
        expiration_hours = body.get("expiration_hours", 24)

        if not audience:
            raise HTTPException(status_code=400, detail="audience DID required")

        caps = [
            Capability(resource=c.get("resource", "*"), ability=c.get("ability", "*"))
            for c in capabilities
        ]

        import time as _time
        from .cid_artifacts import artifact_cid
        now = int(_time.time())

        # Compute CID for the delegation first
        proof_cid = str(artifact_cid({
            "issuer": "did:key:z6MkIPFSDatasetsMCPServer",
            "audience": audience,
            "capabilities": [{"resource": c.resource, "ability": c.ability} for c in caps],
            "expiry": now + (expiration_hours * 3600),
        }))

        delegation = Delegation(
            cid=proof_cid,
            issuer="did:key:z6MkIPFSDatasetsMCPServer",
            audience=audience,
            capabilities=caps,
            expiry=now + (expiration_hours * 3600),
        )

        # Store delegation
        add_delegation(proof_cid, delegation)

        return {
            "proof_cid": proof_cid,
            "delegation": {
                "issuer": delegation.issuer,
                "audience": delegation.audience,
                "capabilities": [{"resource": c.resource, "ability": c.ability} for c in caps],
                "expiry": delegation.expiry,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"UCAN delegation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mcp/ucan/validate")
async def validate_ucan_delegation(request: Request):
    """Validate a UCAN proof chain (Profile C)."""
    try:
        from .ucan_delegation import get_delegation, DelegationEvaluator, get_delegation_evaluator
        body = await request.json()
        proof_cid = body.get("proof_cid", "")

        if not proof_cid:
            raise HTTPException(status_code=400, detail="proof_cid required")

        delegation = get_delegation(proof_cid)
        if delegation is None:
            return {"valid": False, "error": "Delegation not found", "chain": []}

        # Validate time bounds
        import time as _time
        now = int(_time.time())
        valid = True
        reasons = []

        if hasattr(delegation, 'expiry') and delegation.expiry < now:
            valid = False
            reasons.append("expired")
        if hasattr(delegation, 'not_before') and delegation.not_before > now:
            valid = False
            reasons.append("not yet valid")

        return {
            "valid": valid,
            "reasons": reasons,
            "chain": [{
                "issuer": getattr(delegation, 'issuer', ''),
                "audience": getattr(delegation, 'audience', ''),
                "expiry": getattr(delegation, 'expiry', 0),
            }],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"UCAN validation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- Profile D: Policy Evaluation ---

@app.post("/mcp/policy/evaluate")
async def evaluate_deontic_policy(request: Request):
    """Evaluate temporal deontic policy for an intent (Profile D)."""
    try:
        from .temporal_policy import TemporalPolicyEvaluator
        body = await request.json()
        intent_cid = body.get("intent_cid", "")
        proof_cid = body.get("proof_cid")

        evaluator = TemporalPolicyEvaluator()
        result = evaluator.evaluate(intent_cid=intent_cid, proof_cid=proof_cid)

        return {
            "decision": getattr(result, 'decision', 'allow') if result else "allow",
            "obligations": getattr(result, 'obligations', []) if result else [],
            "policy_cid": getattr(result, 'policy_cid', '') if result else "",
        }
    except ImportError:
        return {"decision": "allow", "obligations": [], "note": "Policy module not available"}
    except Exception as e:
        logger.error(f"Policy evaluation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- Profile E: P2P Peer Discovery ---

@app.get("/mcp/p2p/peers")
async def discover_p2p_peers():
    """Discover available P2P peers (Profile E) — filtered for security."""
    try:
        from .p2p_libp2p_transport import get_p2p_node, MCP_P2P_PROTOCOL
        node = get_p2p_node()
        full = node.to_dict()
        # Filter sensitive multiaddrs (contain internal IPs)
        safe_peers = []
        for peer in full.get("peers", []):
            safe_peers.append({
                "peer_id": peer.get("peer_id", ""),
                "protocols": peer.get("protocols", []),
                "last_seen": peer.get("last_seen", 0),
                "latency_ms": peer.get("latency_ms", 0),
            })
        full["peers"] = safe_peers
        return full
    except ImportError:
        return {"protocol": "/mcp+p2p/1.0.0", "peers": [], "count": 0, "started": False}
    except Exception as e:
        logger.error(f"P2P peer discovery failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mcp/p2p/call")
async def p2p_call_remote_tool(request: Request):
    """Call a tool on a remote peer via libp2p /mcp+p2p/1.0.0 (Profile E)."""
    try:
        from .p2p_libp2p_transport import get_p2p_node
        body = await request.json()
        node = get_p2p_node()
        if not node._started:
            raise HTTPException(status_code=503, detail="P2P node not started")
        peer_id = body.get("peer_id", "")
        # Validate peer is known (prevent SSRF relay to arbitrary hosts)
        if peer_id not in node._peers:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown peer: {peer_id[:16]}... Use /mcp/p2p/peers to discover available peers"
            )
        result = await node.call_tool(
            peer_id=peer_id,
            method=body.get("method", ""),
            params=body.get("params", {}),
            timeout=min(max(float(body.get("timeout", 30.0)), 1.0), 120.0),
        )
        return {"result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- MCP++ Capability Negotiation (JSON-RPC) ---

@app.get("/mcp/discover")
async def mcp_discover():
    """Discovery endpoint: returns server capabilities, version, available tools.

    Frontend (Electron/SwissKnife) connects here first to discover what's available.
    """
    import os as _os

    tools = []
    try:
        from .dispatch_pipeline import _TOOL_REGISTRY
        tools = list(_TOOL_REGISTRY.keys()) if _TOOL_REGISTRY else []
    except Exception:
        pass

    profiles = {
        "A": "MCP-IDL (Interface Descriptors)",
        "B": "CID-Native Execution (Intent/Decision/Receipt)",
        "C": "UCAN Authorization (Delegation Chains)",
        "D": "Temporal Deontic Policy (Permission/Prohibition/Obligation)",
        "E": "mcp+p2p (libp2p Transport)",
    }

    p2p_status = "disabled"
    peer_id = None
    try:
        from .p2p_libp2p_transport import get_p2p_node
        node = get_p2p_node()
        if node._started:
            p2p_status = "active"
            peer_id = node.peer_id
    except Exception:
        pass

    return {
        "server": "ipfs-datasets-mcp",
        "version": "0.1.0",
        "protocol": "mcp++",
        "profiles": profiles,
        "tools": tools,
        "interfaces": len(tools),
        "p2p": {"status": p2p_status, "peer_id": peer_id},
        "endpoints": {
            "jsonrpc": "/mcp",
            "execute": "/mcp/execute",
            "interfaces": "/mcp/interfaces",
            "ucan_delegate": "/mcp/ucan/delegate",
            "policy_evaluate": "/mcp/policy/evaluate",
            "p2p_call": "/mcp/p2p/call",
            "events": "/mcp/events/stream",
            "health": "/health",
            "tools_list": "/tools/list",
        },
        "auth": {
            "ucan_required": not bool(_os.environ.get("MCPPP_ALLOW_UNSIGNED_DELEGATIONS")),
        },
    }


@app.get("/mcp/events/stream")
async def mcp_event_stream(request: Request):
    """SSE endpoint: streams EventDAG changes and server events in real-time.

    Frontend connects here for live updates (tool executions, peer events, etc).
    Uses Server-Sent Events (SSE) for broad compatibility with Electron/browsers.
    """
    import json as _json
    from starlette.responses import StreamingResponse

    try:
        from .event_dag import get_event_dag
        dag = get_event_dag()
    except Exception:
        dag = None

    async def _generate_events():
        last_count = len(dag._events) if dag else 0
        yield f"event: connected\ndata: {{\"server\": \"ipfs-datasets-mcp\", \"events\": {last_count}}}\n\n"

        try:
            while True:
                await anyio.sleep(1.0)
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                if dag is None:
                    yield ": keepalive\n\n"
                    continue
                current_count = len(dag._events)
                if current_count > last_count:
                    new_events = list(dag._events.values())[last_count:current_count]
                    for event in new_events:
                        event_data = _json.dumps({
                            "cid": event.cid,
                            "type": event.event_type,
                            "timestamp": event.timestamp,
                            "parents": event.parent_cids,
                        })
                        yield f"event: dag_event\ndata: {event_data}\n\n"
                    last_count = current_count
                else:
                    yield ": keepalive\n\n"
        except (GeneratorExit, BaseException):
            pass

    return StreamingResponse(
        _generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/mcp")
async def mcp_jsonrpc_handler(request: Request):
    """Handle MCP JSON-RPC requests including MCP++ profile negotiation."""
    try:
        body = await request.json()
        method = body.get("method", "")
        params = body.get("params", {})
        req_id = body.get("id", 1)

        # JSON-RPC 2.0: id must be string, number, or null
        if req_id is not None and not isinstance(req_id, (str, int, float)):
            return JSONResponse(
                status_code=400,
                content={"jsonrpc": "2.0", "id": None,
                         "error": {"code": -32600, "message": "Invalid request: id must be string, number, or null"}}
            )

        if method == "initialize":
            # MCP++ capability negotiation
            client_caps = params.get("capabilities", {}).get("experimental", {})
            server_caps = {}
            if client_caps.get("mcp++/mcp-idl"):
                server_caps["mcp++/mcp-idl"] = True
            if client_caps.get("mcp++/cid-envelope"):
                server_caps["mcp++/cid-envelope"] = True
            if client_caps.get("mcp++/ucan"):
                server_caps["mcp++/ucan"] = True
            if client_caps.get("mcp++/deontic-policy"):
                server_caps["mcp++/deontic-policy"] = True
            if client_caps.get("mcp++/event-dag"):
                server_caps["mcp++/event-dag"] = True
            if client_caps.get("mcp++/p2p-transport"):
                server_caps["mcp++/p2p-transport"] = True

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": True},
                        "experimental": server_caps,
                    },
                    "serverInfo": {"name": "ipfs-datasets-mcppp", "version": "1.0.0"},
                },
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            mcp_server = getattr(app.state, 'mcp_server', None)
            if mcp_server and hasattr(mcp_server, 'tools') and tool_name in mcp_server.tools:
                tool_fn = mcp_server.tools[tool_name]
                import inspect
                if callable(tool_fn):
                    if inspect.iscoroutinefunction(tool_fn):
                        result = await tool_fn(**arguments)
                    else:
                        result = tool_fn(**arguments)
                else:
                    result = None
                return {"jsonrpc": "2.0", "id": req_id, "result": result}
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}}

        elif method == "tools/list":
            mcp_server = getattr(app.state, 'mcp_server', None)
            tools = list(mcp_server.tools.keys()) if mcp_server and hasattr(mcp_server, 'tools') else []
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

        elif method == "mcp++/execute":
            # Delegate to the envelope execution endpoint
            from starlette.testclient import TestClient
            # Inline call
            return await mcp_execute_with_envelope(request)

        elif method == "mcp++/ucan/validate":
            proof_cid = params.get("proof_cid", "")
            from .ucan_delegation import get_delegation
            delegation = get_delegation(proof_cid)
            import time as _time
            now = int(_time.time())
            valid = delegation is not None and (not hasattr(delegation, 'expiry') or delegation.expiry >= now)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"valid": valid, "chain": []}}

        elif method == "mcp++/policy/evaluate":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"decision": "allow", "obligations": []}}

        elif method == "mcp++/p2p/peers":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"peers": [], "protocol": "/mcp+p2p/1.0.0"}}

        elif method == "shutdown":
            return {"jsonrpc": "2.0", "id": req_id, "result": None}

        else:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    except Exception as e:
        logger.error(f"MCP JSON-RPC error: {e}", exc_info=True)
        return {"jsonrpc": "2.0", "id": body.get("id", 1) if 'body' in dir() else 1, "error": {"code": -32603, "message": str(e)}}
