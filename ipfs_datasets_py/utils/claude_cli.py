#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anthropic Claude CLI Utility Module

This module provides functionality to install and manage the Anthropic Claude CLI tool.
It enables programmatic access to Claude API features including text generation,
chat, and other AI capabilities through the command line.

Features:
- Install Anthropic Claude CLI (via pip)
- Execute Claude CLI commands
- Manage API key configuration
- Python interface for programmatic access
"""

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class ClaudeCLI:
    """
    Anthropic Claude CLI Manager
    
    Manages Anthropic Claude CLI installation, configuration, and execution.
    Provides a Python interface for interacting with the Claude CLI tool.
    
    Note: The Claude CLI is typically installed via pip as 'anthropic'
    and accessed through Python scripts or a custom CLI wrapper.
    
    Attributes:
        install_dir (Path): Directory for configuration
        api_key_file (Path): Path to API key configuration file
        cli_module (str): Python module name for Claude CLI
    
    Example:
        >>> cli = ClaudeCLI()
        >>> cli.install()
        >>> cli.configure_api_key('your-api-key')
        >>> result = cli.execute(['chat', 'Hello'])
    """
    
    # Claude is installed via pip
    CLAUDE_PACKAGE = "anthropic"
    
    def __init__(self, install_dir: Optional[str] = None):
        """
        Initialize Claude CLI manager.
        
        Args:
            install_dir: Directory for configuration (defaults to ~/.claude-cli)
        """
        if install_dir is None:
            install_dir = os.path.expanduser('~/.claude-cli')
        
        self.install_dir = Path(install_dir)
        self.api_key_file = self.install_dir / 'api_key'
        self.config_file = self.install_dir / 'config.json'
        self.cli_module = self.CLAUDE_PACKAGE
        
        # Ensure install directory exists
        self.install_dir.mkdir(parents=True, exist_ok=True)
    
    def is_installed(self) -> bool:
        """
        Check if Claude CLI (anthropic package) is installed.
        
        Returns:
            True if the package is installed
        """
        try:
            import importlib.util
            spec = importlib.util.find_spec('anthropic')
            return spec is not None
        except (ImportError, ModuleNotFoundError):
            return False
    
    def install(self, force: bool = False) -> bool:
        """
        Install Claude CLI via pip.
        
        Args:
            force: Force reinstallation even if already installed
        
        Returns:
            True if installation successful
        """
        if self.is_installed() and not force:
            logger.info(f"Anthropic Claude CLI already installed")
            return True
        
        try:
            logger.info(f"Installing {self.CLAUDE_PACKAGE} via pip...")
            
            cmd = [sys.executable, '-m', 'pip', 'install']
            if force:
                cmd.append('--force-reinstall')
            cmd.append(self.CLAUDE_PACKAGE)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                check=False
            )
            
            if result.returncode == 0:
                logger.info(f"Anthropic Claude CLI installed successfully")
                return True
            else:
                logger.error(f"Failed to install Anthropic Claude CLI: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to install Anthropic Claude CLI: {e}")
            return False
    
    def configure_api_key(self, api_key: str) -> bool:
        """
        Configure API key for Claude.
        
        Args:
            api_key: Anthropic API key
        
        Returns:
            True if configuration successful
        """
        try:
            # Save API key to file
            self.api_key_file.write_text(api_key)
            self.api_key_file.chmod(0o600)  # Secure the file
            logger.info(f"API key configured at {self.api_key_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to configure API key: {e}")
            return False
    
    def get_api_key(self) -> Optional[str]:
        """
        Get the configured API key.
        
        Returns:
            API key string or None if not configured
        """
        try:
            if self.api_key_file.exists():
                return self.api_key_file.read_text().strip()
            # Also check environment variable
            return os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('CLAUDE_API_KEY')
        except Exception as e:
            logger.error(f"Failed to get API key: {e}")
            return None
    
    def execute(self, args: List[str], capture_output: bool = True, 
                timeout: Optional[int] = None, api_key: Optional[str] = None) -> subprocess.CompletedProcess:
        """
        Execute a Claude CLI command via Python with sanitized inputs.
        
        This creates a Python script to interact with the Claude API.
        
        Args:
            args: Command arguments (e.g., ['chat', 'Hello'])
            capture_output: Whether to capture stdout/stderr
            timeout: Command timeout in seconds
            api_key: Optional API key to use (overrides configured key)
        
        Returns:
            CompletedProcess object with command results
        
        Raises:
            RuntimeError: If Claude CLI is not installed
            TypeError: If args is not a list or contains non-strings
        """
        if not self.is_installed():
            raise RuntimeError(
                "Anthropic Claude CLI is not installed. Call install() first."
            )
        
        # Input sanitization: ensure args is a list
        if not isinstance(args, list):
            raise TypeError(f"args must be a list, got {type(args).__name__}")
        
        # Input sanitization: ensure all args are strings
        for arg in args:
            if not isinstance(arg, str):
                raise TypeError(f"All args must be strings, got {type(arg).__name__}")
        
        # Get API key
        used_api_key = api_key or self.get_api_key()
        if not used_api_key:
            raise RuntimeError(
                "No API key configured. Call configure_api_key() first or set ANTHROPIC_API_KEY environment variable."
            )
        
        # Sanitize API key - ensure it's a string and not empty
        if not isinstance(used_api_key, str) or not used_api_key.strip():
            raise ValueError("Invalid API key format")
        
        # Create a temporary Python script to execute the command
        # Pass sensitive data via environment variables for security
        import tempfile
        import json
        
        script_content = """
import os
import sys
import json
from anthropic import Anthropic

# Get API key from environment (set by parent process)
api_key = os.environ.get('CLAUDE_TEMP_API_KEY')
if not api_key:
    print("Error: API key not provided", file=sys.stderr)
    sys.exit(1)

# Configure API key
client = Anthropic(api_key=api_key)

# Parse command from environment (set by parent process)
args_json = os.environ.get('CLAUDE_TEMP_ARGS', '[]')
try:
    args = json.loads(args_json)
except json.JSONDecodeError:
    print("Error: Invalid command arguments", file=sys.stderr)
    sys.exit(1)
if len(args) == 0:
    print("No command specified")
    sys.exit(1)

command = args[0]
rest_args = args[1:]

if command == 'chat' or command == 'message':
    # Text generation
    if len(rest_args) == 0:
        print("No prompt specified")
        sys.exit(1)
    
    prompt = ' '.join(rest_args)
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[
            {{"role": "user", "content": prompt}}
        ]
    )
    print(message.content[0].text)
    
elif command == 'models':
    # List available models (hardcoded as API doesn't provide list endpoint)
    models = [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307"
    ]
    for model in models:
        print(model)
        
elif command == 'version':
    import anthropic
    print(f"anthropic version {{anthropic.__version__}}")
    
else:
    print(f"Unknown command: {{command}}")
    print("Available commands: chat, message, models, version")
    sys.exit(1)
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script_content)
            script_path = f.name
        
        try:
            cmd = [sys.executable, script_path]
            logger.debug(f"Executing Claude CLI command via Python script")
            
            # Pass sensitive data via environment variables for security
            import json
            env = os.environ.copy()
            env['CLAUDE_TEMP_API_KEY'] = used_api_key
            env['CLAUDE_TEMP_ARGS'] = json.dumps(args)
            
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                check=False,
                env=env
            )
            return result
        except subprocess.TimeoutExpired as e:
            logger.error(f"Claude CLI command timed out after {timeout} seconds")
            raise
        except Exception as e:
            logger.error(f"Failed to execute Claude CLI command: {e}")
            raise
        finally:
            # Clean up temporary script
            try:
                os.unlink(script_path)
            except:
                pass
    
    def get_version(self) -> Optional[str]:
        """
        Get the installed Claude CLI version.
        
        Returns:
            Version string or None if not installed
        """
        if not self.is_installed():
            return None
        
        try:
            result = self.execute(['version'], timeout=10)
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception as e:
            logger.error(f"Failed to get Claude CLI version: {e}")
            return None
    
    def list_models(self) -> List[str]:
        """
        List available Claude models.
        
        Returns:
            List of model names
        """
        try:
            result = self.execute(['models'], timeout=30)
            if result.returncode == 0:
                return [line.strip() for line in result.stdout.split('\n') if line.strip()]
            return []
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get Claude CLI status information.
        
        Returns:
            Dictionary with status information
        """
        api_key_configured = self.api_key_file.exists() or bool(self.get_api_key())
        
        return {
            'installed': self.is_installed(),
            'version': self.get_version(),
            'install_dir': str(self.install_dir),
            'config_file': str(self.config_file),
            'api_key_configured': api_key_configured,
            'package': self.CLAUDE_PACKAGE
        }
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to Claude API.
        
        Returns:
            Dictionary with test results
        """
        try:
            result = self.execute(['chat', 'Hello'], timeout=30)
            return {
                'success': result.returncode == 0,
                'response': result.stdout if result.returncode == 0 else None,
                'error': result.stderr if result.returncode != 0 else None
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _install(self, force: bool = False, **kwargs) -> bool:
        """
        Standardized installation method (internal).
        
        This is a standardized method name for installation across all CLI tools.
        Delegates to install().
        
        Args:
            force: Force reinstallation even if already installed
            **kwargs: Additional installation arguments
        
        Returns:
            True if installation successful
        """
        return self.install(force=force)
    
    def _config(self, **kwargs) -> Dict[str, Any]:
        """
        Standardized configuration method (internal).
        
        This is a standardized method name for configuration across all CLI tools.
        Handles API key configuration.
        
        Args:
            **kwargs: Configuration arguments (api_key)
        
        Returns:
            Dictionary with configuration result
        """
        api_key = kwargs.get('api_key')
        if not api_key:
            return {
                'success': False,
                'error': 'API key is required for configuration',
                'message': 'Please provide api_key parameter'
            }
        
        try:
            success = self.configure_api_key(api_key)
            return {
                'success': success,
                'message': 'API key configured successfully' if success else 'Failed to configure API key'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f'Configuration error: {str(e)}'
            }


def create_claude_cli(install_dir: Optional[str] = None) -> ClaudeCLI:
    """
    Create and return a Claude CLI manager instance.
    
    Args:
        install_dir: Optional installation directory
    
    Returns:
        ClaudeCLI instance
    """
    return ClaudeCLI(install_dir=install_dir)
