"""
MCP Tools Registration System

This module provides a comprehensive registration system for all migrated MCP tools
from the ipfs_embeddings_py project integration.
"""

import logging
import importlib
from typing import Dict, List, Any, Optional
from pathlib import Path

from .tool_wrapper import wrap_function_as_tool, BaseMCPTool

logger = logging.getLogger(__name__)


class MCPToolRegistry:
    """
    Registry for managing and registering MCP tools from the migration.
    """
    
    def __init__(self):
        self.tools: Dict[str, BaseMCPTool] = {}
        self.categories: Dict[str, List[str]] = {}
        self.registration_errors: List[str] = []
        
    def register_tool(self, tool: BaseMCPTool) -> bool:
        """
        Register a single MCP tool.
        
        Args:
            tool: The MCP tool to register
            
        Returns:
            True if registration successful, False otherwise
        """
        try:
            if not isinstance(tool, BaseMCPTool):
                raise ValueError(f"Tool must inherit from BaseMCPTool, got {type(tool)}")
            
            if tool.name in self.tools:
                logger.warning(f"Tool '{tool.name}' already registered, overwriting")
            
            self.tools[tool.name] = tool
            
            # Update categories
            if tool.category not in self.categories:
                self.categories[tool.category] = []
            if tool.name not in self.categories[tool.category]:
                self.categories[tool.category].append(tool.name)
            
            logger.info(f"Registered tool: {tool.name} (category: {tool.category})")
            return True
            
        except Exception as e:
            error_msg = f"Failed to register tool {getattr(tool, 'name', 'unknown')}: {e}"
            self.registration_errors.append(error_msg)
            logger.error(error_msg)
            return False
    
    def get_tool(self, tool_name: str) -> Optional[BaseMCPTool]:
        """Get a tool by name."""
        return self.tools.get(tool_name)
    
    def get_tools_by_category(self, category: str) -> List[BaseMCPTool]:
        """Get all tools in a category."""
        tool_names = self.categories.get(category, [])
        return [self.tools[name] for name in tool_names if name in self.tools]
    
    def list_all_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools with metadata."""
        return [tool.get_schema() for tool in self.tools.values()]
    
    def get_registration_summary(self) -> Dict[str, Any]:
        """Get a summary of tool registration."""
        return {
            "total_tools": len(self.tools),
            "categories": {cat: len(tools) for cat, tools in self.categories.items()},
            "errors": len(self.registration_errors),
            "error_details": self.registration_errors
        }


# Tool mapping definitions for automated registration
TOOL_MAPPINGS = {
    # Auth Tools
    "auth_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools",
        "functions": {
            "authenticate_user": {
                "name": "authenticate_user",
                "category": "auth",
                "description": "Authenticate a user with username and password",
                "tags": ["authentication", "security", "user"]
            },
            "validate_token": {
                "name": "validate_token", 
                "category": "auth",
                "description": "Validate JWT authentication token",
                "tags": ["authentication", "validation", "jwt"]
            },
            "get_user_info": {
                "name": "get_user_info",
                "category": "auth", 
                "description": "Get user information from authentication context",
                "tags": ["user", "info", "profile"]
            }
        }
    },
    
    # Session Management Tools
    "session_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.session_tools.session_tools",
        "functions": {
            "create_session": {
                "name": "create_session",
                "category": "session",
                "description": "Create a new user session",
                "tags": ["session", "create", "management"]
            },
            "get_session_state": {
                "name": "get_session_state",
                "category": "session",
                "description": "Get current session state and metadata",
                "tags": ["session", "state", "info"]
            },
            "cleanup_session": {
                "name": "cleanup_session",
                "category": "session",
                "description": "Clean up and terminate a session",
                "tags": ["session", "cleanup", "terminate"]
            }
        }
    },
    
    # Background Task Tools
    "background_task_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools",
        "functions": {
            "create_task": {
                "name": "create_background_task",
                "category": "tasks",
                "description": "Create a new background task",
                "tags": ["background", "task", "async"]
            },
            "get_task_status": {
                "name": "get_task_status",
                "category": "tasks",
                "description": "Get status of a background task",
                "tags": ["task", "status", "monitoring"]
            },
            "cancel_task": {
                "name": "cancel_background_task",
                "category": "tasks",
                "description": "Cancel a running background task",
                "tags": ["task", "cancel", "management"]
            },
            "list_tasks": {
                "name": "list_background_tasks",
                "category": "tasks",
                "description": "List all background tasks",
                "tags": ["task", "list", "overview"]
            }
        }
    },
    
    # Data Processing Tools
    "data_processing_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools", 
        "functions": {
            "chunk_text": {
                "name": "chunk_text_data",
                "category": "processing",
                "description": "Chunk text data into smaller segments",
                "tags": ["text", "chunking", "preprocessing"]
            },
            "transform_data": {
                "name": "transform_data_format",
                "category": "processing", 
                "description": "Transform data between different formats",
                "tags": ["transform", "format", "conversion"]
            },
            "validate_data": {
                "name": "validate_data_integrity",
                "category": "processing",
                "description": "Validate data integrity and structure",
                "tags": ["validation", "integrity", "quality"]
            },
            "convert_format": {
                "name": "convert_data_format",
                "category": "processing",
                "description": "Convert data to different format",
                "tags": ["conversion", "format", "export"]
            }
        }
    },
    
    # Embedding Tools
    "embedding_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_embedding_generation",
        "functions": {
            "generate_embedding": {
                "name": "generate_embedding",
                "category": "embeddings",
                "description": "Generate embeddings for text using various models",
                "tags": ["embeddings", "generation", "ai"]
            },
            "generate_batch_embeddings": {
                "name": "generate_batch_embeddings", 
                "category": "embeddings",
                "description": "Generate embeddings for multiple texts in batch",
                "tags": ["embeddings", "batch", "generation"]
            },
            "generate_embeddings_from_file": {
                "name": "generate_embeddings_from_file",
                "category": "embeddings", 
                "description": "Generate embeddings from file content",
                "tags": ["embeddings", "file", "processing"]
            }
        }
    },
    
    # Search Tools
    "search_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_search",
        "functions": {
            "semantic_search": {
                "name": "semantic_search",
                "category": "search",
                "description": "Perform semantic similarity search",
                "tags": ["search", "semantic", "similarity"]
            },
            "multi_modal_search": {
                "name": "multi_modal_search",
                "category": "search",
                "description": "Search across multiple modalities",
                "tags": ["search", "multimodal", "cross-modal"]
            },
            "hybrid_search": {
                "name": "hybrid_search", 
                "category": "search",
                "description": "Combine dense and sparse search methods",
                "tags": ["search", "hybrid", "dense", "sparse"]
            },
            "search_with_filters": {
                "name": "search_with_filters",
                "category": "search",
                "description": "Search with metadata filtering",
                "tags": ["search", "filter", "metadata"]
            }
        }
    },
    
    # Sharding Tools
    "shard_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.embedding_tools.shard_embeddings",
        "functions": {
            "shard_embeddings_by_dimension": {
                "name": "shard_embeddings_by_dimension",
                "category": "sharding",
                "description": "Shard embeddings by dimension",
                "tags": ["sharding", "dimension", "distribution"]
            },
            "shard_embeddings_by_cluster": {
                "name": "shard_embeddings_by_cluster",
                "category": "sharding", 
                "description": "Shard embeddings by clustering",
                "tags": ["sharding", "clustering", "optimization"]
            },
            "merge_embedding_shards": {
                "name": "merge_embedding_shards",
                "category": "sharding",
                "description": "Merge embedding shards back together",
                "tags": ["sharding", "merge", "reconstruction"]
            }
        }
    },
    
    # Rate Limiting Tools  
    "rate_limiting_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools",
        "functions": {
            "check_rate_limit": {
                "name": "check_rate_limit",
                "category": "rate_limiting",
                "description": "Check if request is within rate limits",
                "tags": ["rate_limiting", "throttling", "control"]
            },
            "configure_rate_limit": {
                "name": "configure_rate_limit",
                "category": "rate_limiting",
                "description": "Configure rate limiting parameters",
                "tags": ["rate_limiting", "configuration", "setup"]
            },
            "get_rate_limit_stats": {
                "name": "get_rate_limit_stats",
                "category": "rate_limiting",
                "description": "Get rate limiting statistics",
                "tags": ["rate_limiting", "statistics", "monitoring"]
            }
        }
    }
    
    # Sparse Embedding Tools
    "sparse_embedding_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools",
        "functions": {
            "generate_sparse_embeddings": {
                "name": "generate_sparse_embeddings",
                "category": "embedding",
                "description": "Generate sparse vector embeddings",
                "tags": ["embedding", "sparse", "vectors"]
            },
            "index_sparse_collection": {
                "name": "index_sparse_collection",
                "category": "embedding",
                "description": "Index a collection of sparse embeddings",
                "tags": ["indexing", "sparse", "collection"]
            },
            "search_sparse_vectors": {
                "name": "search_sparse_vectors",
                "category": "search",
                "description": "Search using sparse vector embeddings",
                "tags": ["search", "sparse", "similarity"]
            },
            "configure_sparse_model": {
                "name": "configure_sparse_model",
                "category": "embedding",
                "description": "Configure sparse embedding model",
                "tags": ["configuration", "sparse", "model"]
            }
        }
    },
    
    # Storage Tools
    "storage_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools",
        "functions": {
            "store_data": {
                "name": "store_data",
                "category": "storage",
                "description": "Store data using configured storage backend",
                "tags": ["storage", "save", "persist"]
            },
            "retrieve_data": {
                "name": "retrieve_data",
                "category": "storage",
                "description": "Retrieve data from storage backend",
                "tags": ["storage", "retrieve", "load"]
            },
            "manage_collection": {
                "name": "manage_storage_collection",
                "category": "storage",
                "description": "Manage storage collections",
                "tags": ["storage", "collection", "management"]
            },
            "query_storage": {
                "name": "query_storage_backend",
                "category": "storage",
                "description": "Query storage backend for data",
                "tags": ["storage", "query", "search"]
            }
        }
    },
    
    # Analysis Tools
    "analysis_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools",
        "functions": {
            "perform_clustering": {
                "name": "perform_data_clustering",
                "category": "analysis",
                "description": "Perform clustering analysis on data",
                "tags": ["analysis", "clustering", "ml"]
            },
            "assess_quality": {
                "name": "assess_data_quality",
                "category": "analysis",
                "description": "Assess quality of data or embeddings",
                "tags": ["analysis", "quality", "metrics"]
            },
            "reduce_dimensionality": {
                "name": "reduce_dimensionality",
                "category": "analysis",
                "description": "Reduce dimensionality of high-dimensional data",
                "tags": ["analysis", "dimensionality", "reduction"]
            },
            "analyze_distribution": {
                "name": "analyze_data_distribution",
                "category": "analysis", 
                "description": "Analyze statistical distribution of data",
                "tags": ["analysis", "statistics", "distribution"]
            }
        }
    },
    
    # Index Management Tools
    "index_management_tools": {
        "module_path": "ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools",
        "functions": {
            "load_index": {
                "name": "load_vector_index",
                "category": "index",
                "description": "Load or create vector index",
                "tags": ["index", "vector", "load"]
            },
            "manage_shards": {
                "name": "manage_index_shards",
                "category": "index", 
                "description": "Manage index sharding operations",
                "tags": ["index", "sharding", "distribution"]
            },
            "monitor_index_status": {
                "name": "monitor_index_status",
                "category": "index",
                "description": "Monitor index health and performance",
                "tags": ["index", "monitoring", "health"]
            },
            "manage_index_configuration": {
                "name": "configure_index_settings",
                "category": "index",
                "description": "Configure index settings and optimization",
                "tags": ["index", "configuration", "optimization"]
            }
        }
    }
}


def register_all_migrated_tools(registry: MCPToolRegistry) -> Dict[str, Any]:
    """
    Register all migrated tools from the ipfs_embeddings_py integration.
    
    Args:
        registry: The tool registry to register tools with
        
    Returns:
        Registration summary with success/failure details
    """
    registration_results = {
        "successful": [],
        "failed": [],
        "total_attempted": 0,
        "categories_registered": set()
    }
    
    for category_name, category_config in TOOL_MAPPINGS.items():
        module_path = category_config["module_path"]
        functions = category_config["functions"]
        
        logger.info(f"Registering tools from category: {category_name}")
        
        try:
            # Import the module
            module = importlib.import_module(module_path)
            
            for func_name, tool_config in functions.items():
                registration_results["total_attempted"] += 1
                
                try:
                    # Get the function from the module
                    if hasattr(module, func_name):
                        function = getattr(module, func_name)
                        
                        # Wrap the function as an MCP tool
                        tool = wrap_function_as_tool(
                            function=function,
                            tool_name=tool_config["name"],
                            category=tool_config["category"],
                            description=tool_config["description"],
                            tags=tool_config["tags"]
                        )
                        
                        # Register the tool
                        if registry.register_tool(tool):
                            registration_results["successful"].append(tool_config["name"])
                            registration_results["categories_registered"].add(tool_config["category"])
                        else:
                            registration_results["failed"].append(f"{tool_config['name']} (registration failed)")
                            
                    else:
                        error_msg = f"Function {func_name} not found in module {module_path}"
                        registration_results["failed"].append(f"{tool_config['name']} ({error_msg})")
                        logger.warning(error_msg)
                        
                except Exception as e:
                    error_msg = f"Error wrapping function {func_name}: {e}"
                    registration_results["failed"].append(f"{tool_config['name']} ({error_msg})")
                    logger.error(error_msg)
                    
        except ImportError as e:
            error_msg = f"Could not import module {module_path}: {e}"
            logger.error(error_msg)
            # Mark all functions in this category as failed
            for tool_config in functions.values():
                registration_results["failed"].append(f"{tool_config['name']} (module import failed)")
                registration_results["total_attempted"] += 1
        
        except Exception as e:
            error_msg = f"Unexpected error processing category {category_name}: {e}"
            logger.error(error_msg)
    
    # Convert set to list for JSON serialization
    registration_results["categories_registered"] = list(registration_results["categories_registered"])
    
    # Log summary
    success_count = len(registration_results["successful"])
    total_count = registration_results["total_attempted"]
    success_rate = (success_count / total_count * 100) if total_count > 0 else 0
    
    logger.info(f"Tool registration completed:")
    logger.info(f"  ✅ Successful: {success_count}/{total_count} ({success_rate:.1f}%)")
    logger.info(f"  ❌ Failed: {len(registration_results['failed'])}")
    logger.info(f"  📂 Categories: {len(registration_results['categories_registered'])}")
    
    return registration_results


def create_and_register_all_tools() -> MCPToolRegistry:
    """
    Create a new registry and register all migrated tools.
    
    Returns:
        Configured MCPToolRegistry with all tools registered
    """
    registry = MCPToolRegistry()
    results = register_all_migrated_tools(registry)
    
    logger.info(f"Created tool registry with {len(registry.tools)} tools")
    return registry
