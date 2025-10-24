#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Gemini CLI MCP Server Tools

This module provides MCP server tool functions for Google Gemini CLI integration.
These functions are designed to be registered with the MCP server for AI assistant access.
"""

from typing import Dict, Any, List, Optional
import logging
from ipfs_datasets_py.utils.gemini_cli import GeminiCLI

logger = logging.getLogger(__name__)


def gemini_cli_status(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Get Google Gemini CLI installation status and information.
    
    Returns information about the Gemini CLI installation including version
    and API key configuration status.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing status information
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        status = cli.get_status()
        
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        logger.error(f"Failed to get Gemini CLI status: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_install(
    install_dir: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Install Google Gemini CLI via pip.
    
    Args:
        install_dir: Optional custom installation directory path
        force: Force reinstallation even if already installed
    
    Returns:
        Dictionary with installation result
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        success = cli.install(force=force)
        
        if success:
            status = cli.get_status()
            return {
                "success": True,
                "message": "Gemini CLI installed successfully",
                "status": status
            }
        else:
            return {
                "success": False,
                "error": "Installation failed"
            }
    except Exception as e:
        logger.error(f"Failed to install Gemini CLI: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_config_set_api_key(
    api_key: str,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Configure API key for Google Gemini.
    
    Args:
        api_key: Google Gemini API key
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with configuration result
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        success = cli.configure_api_key(api_key)
        
        return {
            "success": success,
            "message": "API key configured successfully" if success else "Failed to configure API key"
        }
    except Exception as e:
        logger.error(f"Failed to configure Gemini API key: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_execute(
    command: List[str],
    install_dir: Optional[str] = None,
    timeout: int = 60,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a Gemini CLI command.
    
    Args:
        command: List of command arguments (e.g., ['chat', 'Hello world'])
        install_dir: Optional custom installation directory path
        timeout: Command timeout in seconds (default: 60)
        api_key: Optional API key to use (overrides configured key)
    
    Returns:
        Dictionary with command execution results
    """
    try:
        if not isinstance(command, list):
            return {
                "success": False,
                "error": "command must be a list of strings"
            }
        
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        result = cli.execute(command, timeout=timeout, api_key=api_key)
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command
        }
    except Exception as e:
        logger.error(f"Failed to execute Gemini CLI command: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_test_connection(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Test connection to Google Gemini API.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with test results
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        result = cli.test_connection()
        
        return result
    except Exception as e:
        logger.error(f"Failed to test Gemini connection: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_list_models(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    List available Google Gemini models.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with model list
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        models = cli.list_models()
        
        return {
            "success": True,
            "models": models,
            "count": len(models)
        }
    except Exception as e:
        logger.error(f"Failed to list Gemini models: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_generate_text(
    prompt: str,
    model: str = "gemini-pro",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate text using Google Gemini.
    
    Generate text responses for various use cases: summaries, analysis,
    creative writing, data transformation, etc. Output can be stored in IPFS
    or used in RAG pipelines.
    
    Args:
        prompt: Text prompt for generation
        model: Model to use (default: "gemini-pro")
        max_tokens: Maximum tokens to generate (optional)
        temperature: Sampling temperature 0.0-1.0 (optional)
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with generated text
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        # Build command
        cmd = ['chat', prompt]
        
        result = cli.execute(cmd, timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "generated_text": result.stdout,
                "model": model,
                "prompt": prompt
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to generate text with Gemini: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_summarize_text(
    text: str,
    max_length: Optional[int] = None,
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Summarize text using Google Gemini.
    
    Generate concise summaries of documents, articles, or datasets.
    Useful for creating metadata for IPFS storage or building knowledge graphs.
    
    Args:
        text: Text to summarize
        max_length: Maximum summary length in words (optional)
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with summary
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        # Build prompt
        if max_length:
            prompt = f"Please provide a concise summary of the following text in no more than {max_length} words:\n\n{text}"
        else:
            prompt = f"Please provide a concise summary of the following text:\n\n{text}"
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "summary": result.stdout,
                "original_length": len(text),
                "summary_length": len(result.stdout)
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to summarize text with Gemini: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_analyze_code(
    code: str,
    language: Optional[str] = None,
    analysis_type: str = "general",
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze code using Google Gemini.
    
    Analyze code for quality, security, performance, or generate explanations.
    Useful for code review automation and documentation generation.
    
    Args:
        code: Code to analyze
        language: Programming language (optional, will be inferred if not provided)
        analysis_type: Type of analysis - "general", "security", "performance", "explain" (default: "general")
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with code analysis
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        # Build prompt based on analysis type
        lang_info = f" ({language})" if language else ""
        
        if analysis_type == "security":
            prompt = f"Analyze the following{lang_info} code for security vulnerabilities:\n\n{code}"
        elif analysis_type == "performance":
            prompt = f"Analyze the following{lang_info} code for performance issues and suggest optimizations:\n\n{code}"
        elif analysis_type == "explain":
            prompt = f"Explain what the following{lang_info} code does:\n\n{code}"
        else:  # general
            prompt = f"Analyze the following{lang_info} code for quality, potential issues, and improvements:\n\n{code}"
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "analysis": result.stdout,
                "analysis_type": analysis_type,
                "language": language,
                "code_length": len(code)
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to analyze code with Gemini: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_extract_structured_data(
    text: str,
    schema: str,
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract structured data from text using Google Gemini.
    
    Parse unstructured text into structured JSON format based on a schema.
    Useful for data extraction, entity recognition, and knowledge graph building.
    
    Args:
        text: Unstructured text to parse
        schema: Description of the desired output structure (e.g., "Extract person names, dates, and locations as JSON")
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with extracted structured data
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        prompt = f"{schema}\n\nText:\n{text}\n\nProvide the output as valid JSON only, without any additional explanation."
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            # Try to parse as JSON
            import json
            try:
                structured_data = json.loads(result.stdout.strip())
                return {
                    "success": True,
                    "data": structured_data,
                    "schema": schema
                }
            except json.JSONDecodeError:
                # Return raw output if not valid JSON
                return {
                    "success": True,
                    "data": result.stdout,
                    "schema": schema,
                    "warning": "Output was not valid JSON"
                }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to extract structured data with Gemini: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_translate_text(
    text: str,
    target_language: str,
    source_language: Optional[str] = None,
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Translate text using Google Gemini.
    
    Translate text between languages. Useful for internationalizing datasets
    or making content accessible in multiple languages.
    
    Args:
        text: Text to translate
        target_language: Target language (e.g., "Spanish", "French", "Japanese")
        source_language: Source language (optional, will be auto-detected)
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with translated text
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        if source_language:
            prompt = f"Translate the following text from {source_language} to {target_language}:\n\n{text}"
        else:
            prompt = f"Translate the following text to {target_language}:\n\n{text}"
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "translated_text": result.stdout,
                "source_language": source_language or "auto-detected",
                "target_language": target_language
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to translate text with Gemini: {e}")
        return {
            "success": False,
            "error": str(e)
        }
