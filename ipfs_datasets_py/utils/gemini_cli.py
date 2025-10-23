#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Gemini CLI Utility Module

This module provides functionality to install and manage the Google Gemini CLI tool.
It enables programmatic access to Google Gemini API features including text generation,
chat, and other AI capabilities through the command line.

Features:
- Install Google Gemini CLI (via pip)
- Execute Gemini CLI commands
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


class GeminiCLI:
    """
    Google Gemini CLI Manager
    
    Manages Google Gemini CLI installation, configuration, and execution.
    Provides a Python interface for interacting with the Gemini CLI tool.
    
    Note: The Gemini CLI is typically installed via pip as 'google-generativeai'
    and accessed through Python scripts or a custom CLI wrapper.
    
    Attributes:
        install_dir (Path): Directory for configuration
        api_key_file (Path): Path to API key configuration file
        cli_module (str): Python module name for Gemini CLI
    
    Example:
        >>> cli = GeminiCLI()
        >>> cli.install()
        >>> cli.configure_api_key('your-api-key')
        >>> result = cli.execute(['chat', 'Hello'])
    """
    
    # Gemini is installed via pip
    GEMINI_PACKAGE = "google-generativeai"
    
    def __init__(self, install_dir: Optional[str] = None):
        """
        Initialize Gemini CLI manager.
        
        Args:
            install_dir: Directory for configuration (defaults to ~/.gemini-cli)
        """
        if install_dir is None:
            install_dir = os.path.expanduser('~/.gemini-cli')
        
        self.install_dir = Path(install_dir)
        self.api_key_file = self.install_dir / 'api_key'
        self.config_file = self.install_dir / 'config.json'
        self.cli_module = self.GEMINI_PACKAGE
        
        # Ensure install directory exists
        self.install_dir.mkdir(parents=True, exist_ok=True)
    
    def is_installed(self) -> bool:
        """
        Check if Gemini CLI (google-generativeai package) is installed.
        
        Returns:
            True if the package is installed
        """
        try:
            import importlib.util
            spec = importlib.util.find_spec('google.generativeai')
            return spec is not None
        except (ImportError, ModuleNotFoundError):
            return False
    
    def install(self, force: bool = False) -> bool:
        """
        Install Gemini CLI via pip.
        
        Args:
            force: Force reinstallation even if already installed
        
        Returns:
            True if installation successful
        """
        if self.is_installed() and not force:
            logger.info(f"Google Gemini CLI already installed")
            return True
        
        try:
            logger.info(f"Installing {self.GEMINI_PACKAGE} via pip...")
            
            cmd = [sys.executable, '-m', 'pip', 'install']
            if force:
                cmd.append('--force-reinstall')
            cmd.append(self.GEMINI_PACKAGE)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                check=False
            )
            
            if result.returncode == 0:
                logger.info(f"Google Gemini CLI installed successfully")
                return True
            else:
                logger.error(f"Failed to install Google Gemini CLI: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to install Google Gemini CLI: {e}")
            return False
    
    def configure_api_key(self, api_key: str) -> bool:
        """
        Configure API key for Gemini.
        
        Args:
            api_key: Google Gemini API key
        
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
            return os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
        except Exception as e:
            logger.error(f"Failed to get API key: {e}")
            return None
    
    def execute(self, args: List[str], capture_output: bool = True, 
                timeout: Optional[int] = None, api_key: Optional[str] = None) -> subprocess.CompletedProcess:
        """
        Execute a Gemini CLI command via Python.
        
        This creates a Python script to interact with the Gemini API.
        
        Args:
            args: Command arguments (e.g., ['chat', 'Hello'])
            capture_output: Whether to capture stdout/stderr
            timeout: Command timeout in seconds
            api_key: Optional API key to use (overrides configured key)
        
        Returns:
            CompletedProcess object with command results
        
        Raises:
            RuntimeError: If Gemini CLI is not installed
        """
        if not self.is_installed():
            raise RuntimeError(
                "Google Gemini CLI is not installed. Call install() first."
            )
        
        # Get API key
        used_api_key = api_key or self.get_api_key()
        if not used_api_key:
            raise RuntimeError(
                "No API key configured. Call configure_api_key() first or set GEMINI_API_KEY environment variable."
            )
        
        # Create a temporary Python script to execute the command
        import tempfile
        import json
        
        script_content = f"""
import os
import sys
import google.generativeai as genai

# Configure API key
genai.configure(api_key='{used_api_key}')

# Parse command
args = {args}
if len(args) == 0:
    print("No command specified")
    sys.exit(1)

command = args[0]
rest_args = args[1:]

if command == 'chat' or command == 'generate':
    # Text generation
    if len(rest_args) == 0:
        print("No prompt specified")
        sys.exit(1)
    
    prompt = ' '.join(rest_args)
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(prompt)
    print(response.text)
    
elif command == 'models':
    # List available models
    for model in genai.list_models():
        print(f"{{model.name}}: {{model.description}}")
        
elif command == 'version':
    import google.generativeai
    print(f"google-generativeai version {{google.generativeai.__version__}}")
    
else:
    print(f"Unknown command: {{command}}")
    print("Available commands: chat, generate, models, version")
    sys.exit(1)
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script_content)
            script_path = f.name
        
        try:
            cmd = [sys.executable, script_path]
            logger.debug(f"Executing Gemini CLI command via Python script")
            
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                check=False
            )
            return result
        except subprocess.TimeoutExpired as e:
            logger.error(f"Gemini CLI command timed out after {timeout} seconds")
            raise
        except Exception as e:
            logger.error(f"Failed to execute Gemini CLI command: {e}")
            raise
        finally:
            # Clean up temporary script
            try:
                os.unlink(script_path)
            except:
                pass
    
    def get_version(self) -> Optional[str]:
        """
        Get the installed Gemini CLI version.
        
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
            logger.error(f"Failed to get Gemini CLI version: {e}")
            return None
    
    def list_models(self) -> List[str]:
        """
        List available Gemini models.
        
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
        Get Gemini CLI status information.
        
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
            'package': self.GEMINI_PACKAGE
        }
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to Gemini API.
        
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


def create_gemini_cli(install_dir: Optional[str] = None) -> GeminiCLI:
    """
    Create and return a Gemini CLI manager instance.
    
    Args:
        install_dir: Optional installation directory
    
    Returns:
        GeminiCLI instance
    """
    return GeminiCLI(install_dir=install_dir)
