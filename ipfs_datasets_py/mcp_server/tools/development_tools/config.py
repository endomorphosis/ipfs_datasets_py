"""
Development Tools Configuration

Centralized configuration management for all development tools.
Provides default settings and environment-based overrides.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from pathlib import Path
import os
import yaml
import json


@dataclass
class TestGeneratorConfig:
    """Configuration for test generator tool."""
    output_dir: str = "tests"
    harness: str = "unittest"  # unittest, pytest
    default_fixtures: bool = False
    parametrized: bool = False
    docstring_style: str = "google"
    debug: bool = False


@dataclass
class DocumentationGeneratorConfig:
    """Configuration for documentation generator tool."""
    output_dir: str = "docs"
    docstring_style: str = "google"  # google, numpy, rest
    inheritance: bool = True
    format: str = "markdown"
    verbose: bool = False
    ignore_patterns: List[str] = field(default_factory=lambda: [
        "__pycache__", ".git", ".venv", "*.pyc", "*.pyo"
    ])


@dataclass
class LintingToolsConfig:
    """Configuration for linting tools."""
    patterns: List[str] = field(default_factory=lambda: ["**/*.py"])
    file_patterns: List[str] = field(default_factory=lambda: ["**/*.py"])
    exclude_dirs: List[str] = field(default_factory=lambda: [
        ".venv", ".git", "__pycache__", "node_modules"
    ])
    fix_blank_lines: bool = True
    fix_trailing_whitespace: bool = True
    ensure_newlines: bool = True
    dry_run: bool = False
    verbose: bool = False
    run_flake8: bool = True
    run_mypy: bool = False


@dataclass
class TestRunnerConfig:
    """Configuration for test runner tool."""
    check_all: bool = False
    run_mypy: bool = True
    run_flake8: bool = True
    run_coverage: bool = True
    lint_only: bool = False
    respect_gitignore: bool = True
    quiet: bool = False
    output_formats: List[str] = field(default_factory=lambda: ["json", "markdown"])


@dataclass
class CodebaseSearchConfig:
    """Configuration for codebase search tool."""
    case_insensitive: bool = False
    whole_word: bool = False
    regex: bool = False
    max_depth: Optional[int] = None
    context_lines: int = 0
    output_format: str = "text"  # text, json, xml
    compact: bool = False
    group_by_file: bool = False
    summary: bool = False
    extensions: List[str] = field(default_factory=lambda: [
        ".py", ".md", ".txt", ".yml", ".yaml", ".json"
    ])


@dataclass
class DevelopmentToolsConfig:
    """Main configuration for all development tools."""

    # Tool-specific configurations
    test_generator: TestGeneratorConfig = field(default_factory=TestGeneratorConfig)
    documentation_generator: DocumentationGeneratorConfig = field(default_factory=DocumentationGeneratorConfig)
    linting_tools: LintingToolsConfig = field(default_factory=LintingToolsConfig)
    test_runner: TestRunnerConfig = field(default_factory=TestRunnerConfig)
    codebase_search: CodebaseSearchConfig = field(default_factory=CodebaseSearchConfig)

    # Global settings
    enable_audit_logging: bool = True
    enable_ipfs_integration: bool = True
    enable_llm_features: bool = False
    working_directory: str = "."
    temp_directory: str = "/tmp/ipfs_datasets_dev_tools"

    # IPFS settings for development tools
    ipfs_pin_generated_content: bool = False
    ipfs_gateway_url: str = "http://localhost:8080"

    # LLM settings (if enabled)
    llm_provider: str = "anthropic"  # anthropic, openai
    llm_model: str = "claude-3-sonnet-20240229"
    llm_api_key_env: str = "ANTHROPIC_API_KEY"

    def __post_init__(self):
        """Post-initialization validation and setup."""
        # Create temp directory if it doesn't exist
        Path(self.temp_directory).mkdir(parents=True, exist_ok=True)

        # Check for LLM API keys if LLM features are enabled
        if self.enable_llm_features:
            if not os.getenv(self.llm_api_key_env):
                self.enable_llm_features = False
                print(f"Warning: LLM features disabled - {self.llm_api_key_env} not found")

    @classmethod
    def from_file(cls, config_path: str) -> 'DevelopmentToolsConfig':
        """
        Load configuration from a file.

        Args:
            config_path: Path to configuration file (JSON or YAML)

        Returns:
            DevelopmentToolsConfig instance
        """
        config_file = Path(config_path)
        if not config_file.exists():
            return cls()  # Return default config

        try:
            if config_file.suffix.lower() in ['.yml', '.yaml']:
                with open(config_file, 'r') as f:
                    config_data = yaml.safe_load(f)
            else:
                with open(config_file, 'r') as f:
                    config_data = json.load(f)

            return cls.from_dict(config_data)
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")
            return cls()  # Return default config on error

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'DevelopmentToolsConfig':
        """
        Create configuration from dictionary.

        Args:
            config_dict: Configuration dictionary

        Returns:
            DevelopmentToolsConfig instance
        """
        # Create tool-specific configs
        test_gen_config = TestGeneratorConfig(**config_dict.get('test_generator', {}))
        doc_gen_config = DocumentationGeneratorConfig(**config_dict.get('documentation_generator', {}))
        lint_config = LintingToolsConfig(**config_dict.get('linting_tools', {}))
        test_runner_config = TestRunnerConfig(**config_dict.get('test_runner', {}))
        search_config = CodebaseSearchConfig(**config_dict.get('codebase_search', {}))

        # Create main config
        main_config_data = {k: v for k, v in config_dict.items()
                           if k not in ['test_generator', 'documentation_generator',
                                       'linting_tools', 'test_runner', 'codebase_search']}

        return cls(
            test_generator=test_gen_config,
            documentation_generator=doc_gen_config,
            linting_tools=lint_config,
            test_runner=test_runner_config,
            codebase_search=search_config,
            **main_config_data
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.

        Returns:
            Configuration dictionary
        """
        return {
            'test_generator': self.test_generator.__dict__,
            'documentation_generator': self.documentation_generator.__dict__,
            'linting_tools': self.linting_tools.__dict__,
            'test_runner': self.test_runner.__dict__,
            'codebase_search': self.codebase_search.__dict__,
            'enable_audit_logging': self.enable_audit_logging,
            'enable_ipfs_integration': self.enable_ipfs_integration,
            'enable_llm_features': self.enable_llm_features,
            'working_directory': self.working_directory,
            'temp_directory': self.temp_directory,
            'ipfs_pin_generated_content': self.ipfs_pin_generated_content,
            'ipfs_gateway_url': self.ipfs_gateway_url,
            'llm_provider': self.llm_provider,
            'llm_model': self.llm_model,
            'llm_api_key_env': self.llm_api_key_env,
        }

    def save_to_file(self, config_path: str) -> None:
        """
        Save configuration to file.

        Args:
            config_path: Path to save configuration file
        """
        config_file = Path(config_path)
        config_file.parent.mkdir(parents=True, exist_ok=True)

        config_data = self.to_dict()

        if config_file.suffix.lower() in ['.yml', '.yaml']:
            with open(config_file, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False, indent=2)
        else:
            with open(config_file, 'w') as f:
                json.dump(config_data, f, indent=2)


# Global configuration instance
_global_config: Optional[DevelopmentToolsConfig] = None


def get_config() -> DevelopmentToolsConfig:
    """
    Get the global development tools configuration.

    Returns:
        DevelopmentToolsConfig instance
    """
    global _global_config

    if _global_config is None:
        # Try to load from standard locations
        config_paths = [
            "config/development_tools.yml",
            "config/development_tools.yaml",
            "config/development_tools.json",
            ".ipfs_datasets_dev_config.yml",
            ".ipfs_datasets_dev_config.yaml",
            ".ipfs_datasets_dev_config.json"
        ]

        for config_path in config_paths:
            if Path(config_path).exists():
                _global_config = DevelopmentToolsConfig.from_file(config_path)
                break

        if _global_config is None:
            _global_config = DevelopmentToolsConfig()

    return _global_config


def set_config(config: DevelopmentToolsConfig) -> None:
    """
    Set the global development tools configuration.

    Args:
        config: DevelopmentToolsConfig instance
    """
    global _global_config
    _global_config = config


def reset_config() -> None:
    """Reset the global configuration to None (forces reload)."""
    global _global_config
    _global_config = None
