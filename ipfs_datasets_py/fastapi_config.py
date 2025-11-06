"""
Configuration settings for IPFS Datasets FastAPI service.

This module provides configuration management for the FastAPI service,
including environment variables, security settings, and service parameters.
"""

import os
from typing import List, Optional, Dict, Any
from functools import lru_cache

try:
    # Pydantic v2
    from pydantic_settings import BaseSettings
    from pydantic import Field
except ImportError:
    # Pydantic v1 fallback
    from pydantic import BaseSettings, Field

class FastAPISettings(BaseSettings):
    """FastAPI service configuration settings."""
    
    # Application settings
    app_name: str = "IPFS Datasets API"
    app_version: str = "1.0.0"
    debug: bool = Field(default=False, env="DEBUG")
    environment: str = Field(default="development", env="ENVIRONMENT")
    
    # Server settings
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")
    reload: bool = Field(default=True, env="RELOAD")
    
    # Security settings
    secret_key: str = Field(default="your-secret-key-change-in-production", env="SECRET_KEY")
    algorithm: str = Field(default="HS256", env="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # CORS settings
    allowed_origins: List[str] = Field(default=["*"], env="ALLOWED_ORIGINS")
    allowed_methods: List[str] = Field(default=["*"], env="ALLOWED_METHODS")
    allowed_headers: List[str] = Field(default=["*"], env="ALLOWED_HEADERS")
    allow_credentials: bool = Field(default=True, env="ALLOW_CREDENTIALS")
    
    # Rate limiting settings
    rate_limit_enabled: bool = Field(default=True, env="RATE_LIMIT_ENABLED")
    rate_limit_storage: str = Field(default="memory", env="RATE_LIMIT_STORAGE")  # memory, redis
    redis_url: Optional[str] = Field(default=None, env="REDIS_URL")
    
    # Database settings (for user management)
    database_url: Optional[str] = Field(default=None, env="DATABASE_URL")
    
    # Embedding settings
    default_embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        env="DEFAULT_EMBEDDING_MODEL"
    )
    max_batch_size: int = Field(default=32, env="MAX_BATCH_SIZE")
    max_text_length: int = Field(default=10000, env="MAX_TEXT_LENGTH")
    
    # Vector store settings
    default_vector_store: str = Field(default="faiss", env="DEFAULT_VECTOR_STORE")
    qdrant_url: Optional[str] = Field(default="http://localhost:6333", env="QDRANT_URL")
    elasticsearch_url: Optional[str] = Field(default="http://localhost:9200", env="ELASTICSEARCH_URL")
    
    # IPFS settings
    ipfs_gateway_url: str = Field(default="http://localhost:8080", env="IPFS_GATEWAY_URL")
    ipfs_api_url: str = Field(default="http://localhost:5001", env="IPFS_API_URL")
    
    # Monitoring settings
    enable_metrics: bool = Field(default=True, env="ENABLE_METRICS")
    metrics_endpoint: str = Field(default="/metrics", env="METRICS_ENDPOINT")
    enable_health_checks: bool = Field(default=True, env="ENABLE_HEALTH_CHECKS")
    
    # Logging settings
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        env="LOG_FORMAT"
    )
    
    # Background task settings
    enable_background_tasks: bool = Field(default=True, env="ENABLE_BACKGROUND_TASKS")
    task_queue_size: int = Field(default=1000, env="TASK_QUEUE_SIZE")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

@lru_cache()
def get_settings() -> FastAPISettings:
    """Get cached settings instance."""
    return FastAPISettings()

# Rate limiting configuration
DEFAULT_RATE_LIMITS = {
    "/embeddings/generate": {"requests": 100, "window": 3600},
    "/embeddings/batch": {"requests": 50, "window": 3600},
    "/search/semantic": {"requests": 1000, "window": 3600},
    "/search/hybrid": {"requests": 500, "window": 3600},
    "/analysis/*": {"requests": 200, "window": 3600},
    "/admin/*": {"requests": 50, "window": 3600},
    "/tools/execute/*": {"requests": 100, "window": 3600},
}

# API documentation configuration
API_DOCS_CONFIG = {
    "title": "IPFS Datasets API",
    "description": """
    REST API for IPFS Datasets with advanced embedding and vector search capabilities.
    
    ## Features
    
    * **Embedding Generation**: Generate embeddings for text using various models
    * **Vector Search**: Semantic and hybrid search capabilities
    * **Analysis Tools**: Clustering, quality assessment, similarity analysis
    * **MCP Tools**: Access to 100+ Model Context Protocol tools
    * **Authentication**: JWT-based secure authentication
    * **Rate Limiting**: Configurable rate limiting for API endpoints
    * **Monitoring**: Comprehensive health checks and metrics
    
    ## Authentication
    
    This API uses JWT (JSON Web Tokens) for authentication. To get started:
    
    1. Login using `/auth/login` with your credentials
    2. Use the returned token in the `Authorization` header: `Bearer <token>`
    3. Refresh tokens using `/auth/refresh` when needed
    
    ## Rate Limits
    
    API endpoints have rate limits to ensure fair usage:
    
    * Embedding generation: 100 requests/hour
    * Search operations: 1000 requests/hour
    * Analysis operations: 200 requests/hour
    * Admin operations: 50 requests/hour
    
    ## Support
    
    For support and documentation, visit the project repository.
    """,
    "version": "1.0.0",
    "contact": {
        "name": "IPFS Datasets API Support",
        "url": "https://github.com/your-org/ipfs-datasets-py",
    },
    "license_info": {
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
}

# Model configuration
SUPPORTED_EMBEDDING_MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-mpnet-base-v2",
    "sentence-transformers/paraphrase-MiniLM-L6-v2",
    "text-embedding-ada-002",  # OpenAI
    "text-embedding-3-small",  # OpenAI
    "text-embedding-3-large",  # OpenAI
]

# Vector store configuration
VECTOR_STORE_CONFIGS = {
    "faiss": {
        "index_type": "IndexFlatIP",
        "dimension": 384,
        "metric": "cosine"
    },
    "qdrant": {
        "collection_config": {
            "vectors": {
                "size": 384,
                "distance": "Cosine"
            }
        }
    },
    "elasticsearch": {
        "index_settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0
        },
        "mapping": {
            "properties": {
                "vector": {
                    "type": "dense_vector",
                    "dims": 384
                }
            }
        }
    }
}

# Health check configuration
HEALTH_CHECK_CONFIG = {
    "checks": [
        {"name": "database", "enabled": True},
        {"name": "vector_store", "enabled": True},
        {"name": "embedding_service", "enabled": True},
        {"name": "ipfs", "enabled": True},
        {"name": "redis", "enabled": False},
    ],
    "timeout": 5.0,
    "retries": 3
}

# Monitoring configuration
MONITORING_CONFIG = {
    "enable_prometheus": True,
    "enable_jaeger": False,
    "custom_metrics": [
        "api_requests_total",
        "embedding_generation_duration",
        "search_requests_total",
        "vector_store_operations",
        "error_rate"
    ]
}
