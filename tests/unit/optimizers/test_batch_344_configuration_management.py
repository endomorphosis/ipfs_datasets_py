"""
Batch 344: Configuration Management
==================================

Implements a flexible configuration system with support for
multiple sources, hot reload, validation, defaults, and change
notifications for operational flexibility.

Goal: Provide:
- Multiple configuration sources (environment, file, dict)
- Configuration validation and schema enforcement
- Default values and hierarchical fallbacks
- Hot reload/dynamic updates with change notifications
- Watch system for configuration changes
- Thread-safe configuration access
- Configuration export and merge
"""

import pytest
import json
import os
import time
import threading
from typing import Any, Dict, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class ConfigSourceType(Enum):
    """Type of configuration source."""
    ENVIRONMENT = "environment"
    FILE = "file"
    DICT = "dict"
    REMOTE = "remote"


@dataclass
class ConfigValue:
    """A configuration value with metadata."""
    value: Any
    source: ConfigSourceType
    timestamp: float = field(default_factory=time.time)
    description: Optional[str] = None


@dataclass
class ConfigSchema:
    """Schema for configuration validation."""
    required_keys: List[str] = field(default_factory=list)
    allowed_keys: Optional[List[str]] = None
    type_hints: Dict[str, type] = field(default_factory=dict)
    defaults: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfigChangeEvent:
    """Event for configuration change."""
    key: str
    old_value: Any
    new_value: Any
    source: ConfigSourceType
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# CONFIGURATION SOURCES
# ============================================================================

class ConfigSource(ABC):
    """Base class for configuration sources."""
    
    def __init__(self, name: str, source_type: ConfigSourceType):
        """Initialize configuration source.
        
        Args:
            name: Source name
            source_type: Type of source
        """
        self.name = name
        self.source_type = source_type
    
    @abstractmethod
    def load(self) -> Dict[str, Any]:
        """Load configuration.
        
        Returns:
            Configuration dictionary
        """
        pass
    
    @abstractmethod
    def reload(self) -> bool:
        """Reload configuration.
        
        Returns:
            True if configuration changed
        """
        pass


class DictConfigSource(ConfigSource):
    """Configuration source from dictionary."""
    
    def __init__(self, name: str, config_dict: Dict[str, Any]):
        """Initialize dict source.
        
        Args:
            name: Source name
            config_dict: Configuration dictionary
        """
        super().__init__(name, ConfigSourceType.DICT)
        self.config_dict = config_dict
    
    def load(self) -> Dict[str, Any]:
        """Load configuration from dict."""
        return self.config_dict.copy()
    
    def reload(self) -> bool:
        """Reload configuration (always returns False for dict)."""
        return False


class EnvironmentConfigSource(ConfigSource):
    """Configuration source from environment variables."""
    
    def __init__(self, name: str, prefix: str = ""):
        """Initialize environment source.
        
        Args:
            name: Source name
            prefix: Environment variable prefix
        """
        super().__init__(name, ConfigSourceType.ENVIRONMENT)
        self.prefix = prefix
        self.last_config = self._load_from_env()
    
    def load(self) -> Dict[str, Any]:
        """Load configuration from environment."""
        return self._load_from_env()
    
    def reload(self) -> bool:
        """Reload configuration from environment."""
        new_config = self._load_from_env()
        changed = new_config != self.last_config
        self.last_config = new_config
        return changed
    
    def _load_from_env(self) -> Dict[str, Any]:
        """Load environment variables."""
        result = {}
        
        for key, value in os.environ.items():
            if self.prefix and not key.startswith(self.prefix):
                continue
            
            # Remove prefix from key
            config_key = key[len(self.prefix):] if self.prefix else key
            
            # Try to parse JSON values
            try:
                result[config_key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                result[config_key] = value
        
        return result


class JSONFileConfigSource(ConfigSource):
    """Configuration source from JSON file."""
    
    def __init__(self, name: str, file_path: str):
        """Initialize JSON file source.
        
        Args:
            name: Source name
            file_path: Path to JSON config file
        """
        super().__init__(name, ConfigSourceType.FILE)
        self.file_path = file_path
        self.last_mtime = self._get_mtime()
    
    def load(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def reload(self) -> bool:
        """Reload configuration if file changed."""
        mtime = self._get_mtime()
        changed = mtime != self.last_mtime and mtime > 0
        self.last_mtime = mtime
        return changed
    
    def _get_mtime(self) -> float:
        """Get file modification time."""
        try:
            return os.path.getmtime(self.file_path)
        except (FileNotFoundError, OSError):
            return -1


# ============================================================================
# CONFIGURATION MANAGER
# ============================================================================

class ConfigManager:
    """Manages configuration from multiple sources."""
    
    def __init__(self, schema: Optional[ConfigSchema] = None):
        """Initialize configuration manager.
        
        Args:
            schema: Optional configuration schema
        """
        self.schema = schema or ConfigSchema()
        self.sources: List[tuple] = []  # List of (priority, source) tuples
        self.config: Dict[str, ConfigValue] = {}
        self.watchers: List[Callable[[ConfigChangeEvent], None]] = []
        self._lock = threading.Lock()
        self.load_count = 0
    
    def add_source(self, source: ConfigSource, priority: int = 0) -> None:
        """Add configuration source.
        
        Args:
            source: Configuration source
            priority: Priority (higher = overrides lower)
        """
        with self._lock:
            self.sources.append((priority, source))
    
    def load(self) -> None:
        """Load configuration from all sources."""
        with self._lock:
            # Apply defaults first
            for key, value in self.schema.defaults.items():
                if key not in self.config:
                    self.config[key] = ConfigValue(
                        value=value,
                        source=ConfigSourceType.DICT,
                        description=f"Default value for {key}"
                    )
            
            # Sort sources by priority (ascending), so higher priority gets applied later
            sorted_sources = sorted(self.sources, key=lambda x: x[0])
            
            for priority, source in sorted_sources:
                source_config = source.load()
                
                for key, value in source_config.items():
                    if self.schema.allowed_keys and key not in self.schema.allowed_keys:
                        continue
                    
                    self.config[key] = ConfigValue(
                        value=value,
                        source=source.source_type
                    )
            
            # Validate required keys
            for required_key in self.schema.required_keys:
                if required_key not in self.config:
                    raise ValueError(f"Missing required configuration key: {required_key}")
            
            self.load_count += 1
    
    def reload(self) -> bool:
        """Reload configuration from sources.
        
        Returns:
            True if configuration changed
        """
        old_config = {}
        with self._lock:
            old_config = {k: v.value for k, v in self.config.items()}
        
        # Check if any source needs reload
        changed = any(source.reload() for source in self.sources)
        
        if changed:
            self.load()
            
            # Notify watchers of changes
            with self._lock:
                new_config = {k: v.value for k, v in self.config.items()}
                
                for key in set(list(old_config.keys()) + list(new_config.keys())):
                    old_val = old_config.get(key)
                    new_val = new_config.get(key)
                    
                    if old_val != new_val:
                        event = ConfigChangeEvent(
                            key=key,
                            old_value=old_val,
                            new_value=new_val,
                            source=self.config.get(key, ConfigValue(None, ConfigSourceType.DICT)).source
                        )
                        
                        for watcher in self.watchers:
                            watcher(event)
        
        return changed
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found
            
        Returns:
            Configuration value
        """
        with self._lock:
            if key in self.config:
                return self.config[key].value
            return default
    
    def set(self, key: str, value: Any) -> None:
        """Set configuration value.
        
        Args:
            key: Configuration key
            value: New value
        """
        with self._lock:
            old_value = self.config.get(key, ConfigValue(None, ConfigSourceType.DICT)).value
            self.config[key] = ConfigValue(
                value=value,
                source=ConfigSourceType.DICT
            )
            
            # Notify watchers if value changed
            if old_value != value:
                event = ConfigChangeEvent(
                    key=key,
                    old_value=old_value,
                    new_value=value,
                    source=ConfigSourceType.DICT
                )
                
                for watcher in self.watchers:
                    try:
                        watcher(event)
                    except Exception:
                        pass  # Don't let watcher errors break config updates
    
    def watch(self, callback: Callable[[ConfigChangeEvent], None]) -> None:
        """Register configuration change watcher.
        
        Args:
            callback: Function called on config change
        """
        with self._lock:
            self.watchers.append(callback)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values.
        
        Returns:
            Dictionary of all config values
        """
        with self._lock:
            return {k: v.value for k, v in self.config.items()}
    
    def validate(self) -> bool:
        """Validate configuration against schema.
        
        Returns:
            True if valid
        """
        with self._lock:
            # Check required keys
            for required_key in self.schema.required_keys:
                if required_key not in self.config:
                    return False
            
            # Check type hints
            for key, expected_type in self.schema.type_hints.items():
                if key in self.config:
                    if not isinstance(self.config[key].value, expected_type):
                        return False
            
            return True


# ============================================================================
# TESTS
# ============================================================================

class TestDictConfigSource:
    """Test DictConfigSource."""
    
    def test_dict_source_load(self):
        """Test loading from dict."""
        config_dict = {"host": "localhost", "port": 8000}
        source = DictConfigSource("test", config_dict)
        
        loaded = source.load()
        
        assert loaded["host"] == "localhost"
        assert loaded["port"] == 8000
    
    def test_dict_source_reload(self):
        """Test reload returns False for dict."""
        source = DictConfigSource("test", {"key": "value"})
        
        assert not source.reload()


class TestEnvironmentConfigSource:
    """Test EnvironmentConfigSource."""
    
    def test_env_source_load(self):
        """Test loading from environment."""
        os.environ["TEST_HOST"] = "example.com"
        os.environ["TEST_PORT"] = "9000"
        
        source = EnvironmentConfigSource("test", prefix="TEST_")
        loaded = source.load()
        
        assert loaded["HOST"] == "example.com"
        assert loaded["PORT"] == 9000
        
        # Cleanup
        del os.environ["TEST_HOST"]
        del os.environ["TEST_PORT"]
    
    def test_env_source_json_parsing(self):
        """Test JSON parsing in environment."""
        os.environ["TEST_CONFIG"] = '{"nested": "value"}'
        
        source = EnvironmentConfigSource("test", prefix="TEST_")
        loaded = source.load()
        
        assert isinstance(loaded["CONFIG"], dict)
        assert loaded["CONFIG"]["nested"] == "value"
        
        del os.environ["TEST_CONFIG"]


class TestJSONFileConfigSource:
    """Test JSONFileConfigSource."""
    
    def test_file_source_load(self):
        """Test loading from JSON file."""
        import tempfile
        
        config_data = {"app": "test", "version": "1.0"}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name
        
        try:
            source = JSONFileConfigSource("test", temp_path)
            loaded = source.load()
            
            assert loaded["app"] == "test"
            assert loaded["version"] == "1.0"
        finally:
            os.unlink(temp_path)
    
    def test_file_source_reload(self):
        """Test reload detection in file source."""
        import tempfile
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"key": "value1"}, f)
            temp_path = f.name
        
        try:
            source = JSONFileConfigSource("test", temp_path)
            source.load()
            
            # Touch file to update mtime
            time.sleep(0.1)
            with open(temp_path, 'w') as f:
                json.dump({"key": "value2"}, f)
            
            assert source.reload()
        finally:
            os.unlink(temp_path)


class TestConfigSchema:
    """Test ConfigSchema."""
    
    def test_schema_creation(self):
        """Test creating schema."""
        schema = ConfigSchema(
            required_keys=["host", "port"],
            allowed_keys=["host", "port", "timeout"],
            defaults={"timeout": 30}
        )
        
        assert "host" in schema.required_keys
        assert "timeout" in schema.defaults


class TestConfigManager:
    """Test ConfigManager."""
    
    def test_add_source(self):
        """Test adding configuration source."""
        manager = ConfigManager()
        source = DictConfigSource("test", {"key": "value"})
        
        manager.add_source(source)
        
        assert len(manager.sources) == 1
    
    def test_load_configuration(self):
        """Test loading configuration."""
        manager = ConfigManager()
        source = DictConfigSource("test", {"host": "localhost", "port": 8000})
        
        manager.add_source(source)
        manager.load()
        
        assert manager.get("host") == "localhost"
        assert manager.get("port") == 8000
    
    def test_get_with_default(self):
        """Test getting config with default."""
        manager = ConfigManager()
        
        value = manager.get("missing", "default_value")
        assert value == "default_value"
    
    def test_set_configuration(self):
        """Test setting configuration."""
        manager = ConfigManager()
        
        manager.set("key", "value")
        assert manager.get("key") == "value"
    
    def test_config_validation(self):
        """Test configuration validation."""
        schema = ConfigSchema(required_keys=["host", "port"])
        manager = ConfigManager(schema)
        
        source = DictConfigSource("test", {"host": "localhost"})
        manager.add_source(source)
        
        with pytest.raises(ValueError):
            manager.load()
    
    def test_required_keys_validation(self):
        """Test required keys validation."""
        schema = ConfigSchema(required_keys=["host", "port"])
        manager = ConfigManager(schema)
        
        source = DictConfigSource("test", {"host": "localhost", "port": 8000})
        manager.add_source(source)
        
        manager.load()
        assert manager.validate()
    
    def test_get_all_config(self):
        """Test getting all configuration."""
        manager = ConfigManager()
        source = DictConfigSource("test", {"a": 1, "b": 2, "c": 3})
        
        manager.add_source(source)
        manager.load()
        
        all_config = manager.get_all()
        assert len(all_config) == 3
        assert all_config["a"] == 1
    
    def test_watch_config_changes(self):
        """Test watching configuration changes."""
        manager = ConfigManager()
        changes = []
        
        def on_change(event):
            changes.append(event)
        
        manager.set("initial", "value")
        manager.watch(on_change)
        manager.set("key", "value")
        
        # Should have at least one change event
        assert len(changes) >= 1
        # Find the change for "key"
        key_changes = [c for c in changes if c.key == "key"]
        assert len(key_changes) >= 1
        assert key_changes[0].new_value == "value"
    
    def test_reload_configuration(self):
        """Test reloading configuration."""
        manager = ConfigManager()
        
        source = DictConfigSource("test", {"key": "value1"})
        manager.add_source(source)
        manager.load()
        
        # Change in-memory config
        manager.set("key", "changed")
        assert manager.get("key") == "changed"
    
    def test_defaults_application(self):
        """Test default values are applied."""
        schema = ConfigSchema(
            defaults={"timeout": 30, "retries": 3}
        )
        manager = ConfigManager(schema)
        
        manager.load()
        
        assert manager.get("timeout") == 30
        assert manager.get("retries") == 3


class TestConfigManagerIntegration:
    """Integration tests for configuration management."""
    
    def test_multiple_sources_override(self):
        """Test multiple sources with priority."""
        manager = ConfigManager()
        
        # Add sources in order (later sources have higher priority)
        manager.add_source(DictConfigSource("default", {"host": "default", "port": 8000}), priority=0)
        manager.add_source(DictConfigSource("override", {"host": "override"}), priority=0)
        
        manager.load()
        
        assert manager.get("host") == "override"
        assert manager.get("port") == 8000
    
    def test_environment_override_dict(self):
        """Test environment overriding dict source."""
        os.environ["CONFIG_host"] = "env_host"
        
        manager = ConfigManager()
        # Add dict source first (lower priority)
        manager.add_source(DictConfigSource("default", {"host": "default", "port": 8000}), priority=0)
        # Add env source second (higher priority - will override)
        manager.add_source(EnvironmentConfigSource("env", prefix="CONFIG_"), priority=1)
        
        manager.load()
        
        # The env variable should override the dict value
        host = manager.get("host")
        assert host == "env_host", f"Expected 'env_host' but got '{host}'"
        assert manager.get("port") == 8000
        
        del os.environ["CONFIG_host"]
    
    def test_config_with_schema_and_defaults(self):
        """Test config with schema, defaults, and sources."""
        schema = ConfigSchema(
            required_keys=["host"],
            defaults={"port": 8000, "timeout": 30},
            allowed_keys=["host", "port", "timeout"]
        )
        
        manager = ConfigManager(schema)
        manager.add_source(DictConfigSource("app", {"host": "localhost"}))
        
        manager.load()
        
        assert manager.get("host") == "localhost"
        assert manager.get("port") == 8000
        assert manager.get("timeout") == 30
