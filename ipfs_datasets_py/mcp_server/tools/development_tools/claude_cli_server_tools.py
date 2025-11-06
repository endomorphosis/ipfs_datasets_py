#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anthropic Claude CLI MCP Server Tools

This module provides MCP server tool functions for Anthropic Claude CLI integration.
These functions are designed to be registered with the MCP server for AI assistant access.
"""

from typing import Dict, Any, List, Optional
import logging
from ipfs_datasets_py.utils.claude_cli import ClaudeCLI

logger = logging.getLogger(__name__)


def claude_cli_status(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Get Anthropic Claude CLI installation status and information.
    
    Returns information about the Claude CLI installation including version
    and API key configuration status.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing status information
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        status = cli.get_status()
        
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        logger.error(f"Failed to get Claude CLI status: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_install(
    install_dir: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Install Anthropic Claude CLI via pip.
    
    Args:
        install_dir: Optional custom installation directory path
        force: Force reinstallation even if already installed
    
    Returns:
        Dictionary with installation result
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        success = cli.install(force=force)
        
        if success:
            status = cli.get_status()
            return {
                "success": True,
                "message": "Claude CLI installed successfully",
                "status": status
            }
        else:
            return {
                "success": False,
                "error": "Installation failed"
            }
    except Exception as e:
        logger.error(f"Failed to install Claude CLI: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_config_set_api_key(
    api_key: str,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Configure API key for Anthropic Claude.
    
    Args:
        api_key: Anthropic Claude API key
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with configuration result
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        success = cli.configure_api_key(api_key)
        
        return {
            "success": success,
            "message": "API key configured successfully" if success else "Failed to configure API key"
        }
    except Exception as e:
        logger.error(f"Failed to configure Claude API key: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_execute(
    command: List[str],
    install_dir: Optional[str] = None,
    timeout: int = 60,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a Claude CLI command.
    
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
        
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
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
        logger.error(f"Failed to execute Claude CLI command: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_test_connection(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Test connection to Anthropic Claude API.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with test results
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        result = cli.test_connection()
        
        return result
    except Exception as e:
        logger.error(f"Failed to test Claude connection: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_list_models(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    List available Anthropic Claude models.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with model list
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        models = cli.list_models()
        
        return {
            "success": True,
            "models": models,
            "count": len(models)
        }
    except Exception as e:
        logger.error(f"Failed to list Claude models: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_analyze_code_quality(
    code: str,
    language: Optional[str] = None,
    focus_areas: Optional[List[str]] = None,
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze code quality using Claude.
    
    Perform in-depth code analysis focusing on readability, maintainability,
    best practices, and potential issues. Useful for code review automation.
    
    Args:
        code: Code to analyze
        language: Programming language (optional)
        focus_areas: Specific areas to focus on (e.g., ["security", "performance", "style"])
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with detailed code quality analysis
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        lang_info = f" ({language})" if language else ""
        focus_info = f" Focus particularly on: {', '.join(focus_areas)}." if focus_areas else ""
        
        prompt = f"""Analyze the following{lang_info} code for quality, identifying:
1. Potential bugs or errors
2. Code smells and anti-patterns
3. Security vulnerabilities
4. Performance issues
5. Readability and maintainability concerns
6. Best practice violations
{focus_info}

Code:
{code}

Provide a detailed analysis with specific recommendations."""
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "analysis": result.stdout,
                "language": language,
                "focus_areas": focus_areas,
                "code_length": len(code)
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to analyze code quality with Claude: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_generate_documentation(
    code: str,
    language: Optional[str] = None,
    doc_type: str = "comprehensive",
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate documentation for code using Claude.
    
    Create comprehensive documentation including function descriptions,
    parameter explanations, usage examples, and more.
    
    Args:
        code: Code to document
        language: Programming language (optional)
        doc_type: Documentation type - "comprehensive", "docstrings", "readme", "api" (default: "comprehensive")
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with generated documentation
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        lang_info = f" ({language})" if language else ""
        
        if doc_type == "docstrings":
            prompt = f"Generate comprehensive docstrings for the following{lang_info} code:\n\n{code}"
        elif doc_type == "readme":
            prompt = f"Generate a README.md file for the following{lang_info} code:\n\n{code}"
        elif doc_type == "api":
            prompt = f"Generate API documentation for the following{lang_info} code:\n\n{code}"
        else:  # comprehensive
            prompt = f"Generate comprehensive documentation for the following{lang_info} code, including:\n1. Overview\n2. Function/class descriptions\n3. Parameters and return values\n4. Usage examples\n5. Notes and warnings\n\nCode:\n{code}"
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "documentation": result.stdout,
                "doc_type": doc_type,
                "language": language
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to generate documentation with Claude: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_explain_code(
    code: str,
    language: Optional[str] = None,
    detail_level: str = "medium",
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a detailed explanation of code using Claude.
    
    Explain complex code in natural language, useful for understanding
    unfamiliar codebases or generating training materials.
    
    Args:
        code: Code to explain
        language: Programming language (optional)
        detail_level: Explanation detail - "basic", "medium", "detailed" (default: "medium")
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with code explanation
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        lang_info = f" ({language})" if language else ""
        
        if detail_level == "basic":
            prompt = f"Provide a simple, high-level explanation of what this{lang_info} code does:\n\n{code}"
        elif detail_level == "detailed":
            prompt = f"Provide a detailed, line-by-line explanation of this{lang_info} code:\n\n{code}"
        else:  # medium
            prompt = f"Explain what this{lang_info} code does, including the main logic and key operations:\n\n{code}"
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "explanation": result.stdout,
                "detail_level": detail_level,
                "language": language
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to explain code with Claude: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_review_pull_request(
    diff: str,
    context: Optional[str] = None,
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Review a pull request using Claude.
    
    Analyze code changes in a PR for quality, potential issues, and improvements.
    Useful for automated code review in CI/CD pipelines.
    
    Args:
        diff: Git diff or code changes to review
        context: Optional context about the PR (description, related issues, etc.)
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with PR review
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        context_info = f"\n\nContext: {context}" if context else ""
        
        prompt = f"""Review the following code changes and provide:
1. Overall assessment (approve, request changes, comment)
2. Specific issues or concerns
3. Suggestions for improvements
4. Security considerations
5. Testing recommendations
{context_info}

Changes:
{diff}"""
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "review": result.stdout,
                "diff_size": len(diff)
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to review PR with Claude: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_generate_tests(
    code: str,
    language: Optional[str] = None,
    test_framework: Optional[str] = None,
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate unit tests for code using Claude.
    
    Create comprehensive test cases including edge cases and error conditions.
    Useful for improving test coverage automatically.
    
    Args:
        code: Code to generate tests for
        language: Programming language (optional)
        test_framework: Test framework to use (e.g., "pytest", "jest", "junit")
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with generated test code
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        lang_info = f" ({language})" if language else ""
        framework_info = f" using {test_framework}" if test_framework else ""
        
        prompt = f"""Generate comprehensive unit tests{framework_info} for the following{lang_info} code.
Include:
1. Tests for normal operation
2. Edge case tests
3. Error condition tests
4. Tests for boundary values

Code to test:
{code}"""
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "test_code": result.stdout,
                "language": language,
                "test_framework": test_framework
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to generate tests with Claude: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_refactor_suggestions(
    code: str,
    language: Optional[str] = None,
    goals: Optional[List[str]] = None,
    install_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get refactoring suggestions for code using Claude.
    
    Suggest improvements to code structure, design patterns, and implementation.
    Useful for code modernization and technical debt reduction.
    
    Args:
        code: Code to refactor
        language: Programming language (optional)
        goals: Refactoring goals (e.g., ["improve performance", "reduce complexity", "enhance readability"])
        install_dir: Optional custom installation directory path
        api_key: Optional API key to use
    
    Returns:
        Dictionary with refactoring suggestions
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        lang_info = f" ({language})" if language else ""
        goals_info = f"\n\nRefactoring goals: {', '.join(goals)}" if goals else ""
        
        prompt = f"""Analyze the following{lang_info} code and suggest refactoring improvements.
For each suggestion, explain:
1. What to change
2. Why to change it
3. How to implement the change
4. Expected benefits
{goals_info}

Code:
{code}"""
        
        result = cli.execute(['chat', prompt], timeout=120, api_key=api_key)
        
        if result.returncode == 0:
            return {
                "success": True,
                "suggestions": result.stdout,
                "language": language,
                "goals": goals
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to get refactoring suggestions from Claude: {e}")
        return {
            "success": False,
            "error": str(e)
        }
