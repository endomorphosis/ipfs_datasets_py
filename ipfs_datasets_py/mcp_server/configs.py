# ipfs_datasets_py/mcp_server/configs.py
"""
Configuration settings for the IPFS Datasets MCP server.
"""
from dataclasses import dataclass, field
from functools import cached_property
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml

_ROOT_DIR = Path(__file__).parent


@dataclass
class Configs:
    """
    Configuration settings for the IPFS Datasets MCP server.

    Attributes:
        verbose: Enable verbose output
        log_level: The log level for the server and logger
        host: Host for the server
        port: Port for the server
        reload: Enable auto-reload
        tool_timeout: Timeout for tool execution in seconds
        enabled_tool_categories: List of enabled tool categories
        transport: Transport protocol for the MCP server
        ipfs_kit_integration: Integration method for ipfs_kit_py ('direct' or 'mcp')
        ipfs_kit_mcp_url: URL of the ipfs_kit_py MCP server (if using 'mcp' integration)
    
    Properties:
        ROOT_DIR: The root directory of the project
        PROJECT_NAME: The name of the project
        CONFIG_DIR: The directory containing configuration files
    """
    verbose: bool = field(default=True, metadata={"description": "Enable verbose output"})
    log_level: int = field(default=logging.INFO, metadata={"description": "The log level for the server and logger"})
    host: str = field(default="127.0.0.1", metadata={"description": "Host for the server"})
    port: int = field(default=5000, metadata={"description": "Port for the server"})
    reload: bool = field(default=True, metadata={"description": "Enable auto-reload"})
    tool_timeout: int = field(default=60, metadata={"description": "Timeout for tool execution in seconds"})
    enabled_tool_categories: List[str] = field(
        default_factory=lambda: [
            "dataset", "ipfs", "vector", "graph", "audit", "security", "provenance"
        ],
        metadata={"description": "List of enabled tool categories"}
    )
    transport: str = field(default="stdio", metadata={"description": "Transport protocol for the MCP server"})
    tool_configs: Dict[str, Any] = field(
        default_factory=dict,
        metadata={"description": "Configuration for specific tools"}
    )
    ipfs_kit_integration: str = field(default="direct", metadata={"description": "Integration method for ipfs_kit_py ('direct' or 'mcp')"})
    ipfs_kit_mcp_url: Optional[str] = field(default=None, metadata={"description": "URL of the ipfs_kit_py MCP server (if using 'mcp' integration)"})

    @property
    def ROOT_DIR(self) -> Path:
        """The root directory of the project."""
        return _ROOT_DIR

    @property
    def PROJECT_NAME(self) -> str:
        """The name of the project."""
        return "ipfs_datasets_mcp"
    
    @property
    def CONFIG_DIR(self) -> Path:
        """The directory containing configuration files."""
        return self.ROOT_DIR / "config"


def load_config_from_yaml(config_path: Optional[str] = None) -> Configs:
    """
    Load configuration from a YAML file.
    
    Args:
        config_path: Path to the YAML configuration file
        
    Returns:
        Configs: Configuration settings
    """
    default_config = Configs()
    
    if not config_path:
        return default_config
    
    config_file = Path(config_path)
    if not config_file.exists():
        return default_config
    
    try:
        with open(config_file, "r") as f:
            yaml_config = yaml.safe_load(f)
        
        # Convert YAML to Configs
        config_dict = {}
        
        # Server settings
        if "server" in yaml_config:
            server_config = yaml_config["server"]
            for key in ["verbose", "host", "port", "reload", "tool_timeout", "transport"]:
                if key in server_config:
                    config_dict[key] = server_config[key]
            
            if "log_level" in server_config:
                level_name = server_config["log_level"].upper()
                config_dict["log_level"] = getattr(logging, level_name, logging.INFO)
        
        # Tool categories
        if "tools" in yaml_config and "enabled_categories" in yaml_config["tools"]:
            config_dict["enabled_tool_categories"] = yaml_config["tools"]["enabled_categories"]
        
        # Tool-specific configurations
        if "tools" in yaml_config:
            tool_configs = {}
            for category in ["dataset", "ipfs", "vector", "graph", "audit", "security", "provenance"]:
                if category in yaml_config["tools"]:
                    tool_configs[category] = yaml_config["tools"][category]
            config_dict["tool_configs"] = tool_configs
        
        # IPFS Kit integration
        if "ipfs_kit" in yaml_config:
            ipfs_kit_config = yaml_config["ipfs_kit"]
            if "integration" in ipfs_kit_config:
                config_dict["ipfs_kit_integration"] = ipfs_kit_config["integration"]
            if "mcp_url" in ipfs_kit_config:
                config_dict["ipfs_kit_mcp_url"] = ipfs_kit_config["mcp_url"]
        
        return Configs(**config_dict)
    
    except (yaml.YAMLError, KeyError, AttributeError) as e:
        logging.error(f"Error loading configuration from {config_path}: {e}")
        return default_config


# Create a default configuration instance
configs = Configs()
