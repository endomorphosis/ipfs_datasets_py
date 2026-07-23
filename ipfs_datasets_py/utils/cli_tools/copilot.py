"""GitHub Copilot CLI wrappers.

This module distinguishes between two different tools that were previously
treated as one surface in the codebase:

- ``gh copilot`` via the GitHub CLI extension.
- standalone ``copilot`` for local agentic prompt mode.
"""

import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseCLITool

logger = logging.getLogger(__name__)


def find_standalone_copilot_cli() -> Optional[str]:
    """Resolve the standalone ``copilot`` executable path."""

    env_path = str(os.environ.get("COPILOT_CLI_PATH") or "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return str(candidate)

    resolved = shutil.which("copilot")
    if resolved:
        return resolved
    return None


def build_standalone_copilot_command_template(cli_path: Optional[str] = None) -> str:
    """Return the default non-interactive prompt template for ``copilot``."""

    executable = cli_path or find_standalone_copilot_cli() or "copilot"
    return (
        f"{shlex.quote(executable)} --silent --stream off --allow-all-tools "
        f"--no-ask-user --model {{model}} --prompt {{prompt}}"
    )


class Copilot(BaseCLITool):
    """Wrapper for the ``gh copilot`` extension."""

    tool_name = "gh"

    def __init__(
        self,
        github_cli_path: Optional[str] = None,
        enable_cache: bool = True,
        cache_maxsize: int = 100,
        cache_ttl: int = 600,
    ):
        resolved_path = github_cli_path or self._find_gh_cli()
        super().__init__(
            cli_path=resolved_path,
            enable_cache=enable_cache,
            cache_maxsize=cache_maxsize,
            cache_ttl=cache_ttl,
        )
        self.copilot_installed = self._check_copilot_extension()

    @staticmethod
    def _find_gh_cli() -> Optional[str]:
        """Backward-compatible path resolver for tests and older callers."""

        resolved = shutil.which("gh")
        return resolved or None

    def _check_installed(self) -> bool:
        """Backward-compatible installation probe."""

        return self._verify_installation()

    def _verify_installation(self) -> bool:
        if not self.cli_path or not self.cli_path.exists():
            return False

        try:
            result = subprocess.run(
                [str(self.cli_path), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.debug("Failed to verify gh CLI: %s", exc)
            return False

    def _check_copilot_extension(self) -> bool:
        if not self.installed:
            return False

        try:
            result = subprocess.run(
                [str(self.cli_path), "extension", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "gh-copilot" in result.stdout or "copilot" in result.stdout
        except Exception as exc:
            logger.debug("Failed to check Copilot extension: %s", exc)
            return False

    def get_status(self) -> Dict[str, Any]:
        """Return status for the GitHub CLI and its Copilot extension."""

        version_info = ""
        if self.installed and self.cli_path:
            try:
                result = subprocess.run(
                    [str(self.cli_path), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    version_info = result.stdout.strip().splitlines()[0]
            except Exception:
                version_info = ""

        return {
            "installed": bool(self.installed and self.copilot_installed),
            "github_cli_available": bool(self.installed),
            "github_cli_path": str(self.cli_path) if self.cli_path else None,
            "copilot_extension_installed": bool(self.copilot_installed),
            "agent_task_available": self.has_agent_task_support(),
            "version_info": version_info,
        }

    def has_agent_task_support(self) -> bool:
        """Return whether the installed gh binary exposes ``agent-task``."""

        if not self.installed or not self.cli_path:
            return False
        try:
            result = subprocess.run(
                [str(self.cli_path), "agent-task", "--help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            logger.debug("Failed to probe gh agent-task support: %s", exc)
            return False

        combined_output = f"{result.stdout}\n{result.stderr}".lower()
        if "unknown command" in combined_output or "agent-task" not in combined_output:
            return False
        return result.returncode == 0

    def install(self, force: bool = False) -> Dict[str, Any]:
        """Install the ``gh-copilot`` extension."""

        if not self.installed:
            logger.error("GitHub CLI not installed, cannot install Copilot extension")
            return {
                "success": False,
                "message": "GitHub CLI is not installed",
                "error": "gh CLI not installed",
            }

        try:
            if self.copilot_installed and force:
                subprocess.run(
                    [str(self.cli_path), "extension", "remove", "gh-copilot"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )

            if self.copilot_installed and not force:
                return {
                    "success": True,
                    "message": "GitHub Copilot extension already installed",
                    "stdout": "",
                    "stderr": "",
                }

            result = subprocess.run(
                [str(self.cli_path), "extension", "install", "github/gh-copilot"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            success = result.returncode == 0
            if success:
                self.copilot_installed = True

            return {
                "success": success,
                "message": "GitHub Copilot extension installed successfully" if success else "Failed to install GitHub Copilot extension",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except Exception as exc:
            logger.error("Error installing Copilot: %s", exc)
            return {
                "success": False,
                "message": "Failed to install GitHub Copilot extension",
                "error": str(exc),
            }

    def suggest(self, query: str, cache_result: bool = True) -> str:
        if not self.copilot_installed:
            raise RuntimeError("GitHub Copilot extension not installed")

        cache_key = f"suggest:{query}" if cache_result else None
        result = self._run_command(["copilot", "suggest", query], cache_key=cache_key)
        if result["success"]:
            return result["stdout"].strip()
        raise RuntimeError(f"Copilot suggest failed: {result['stderr']}")

    def explain(self, code: str, cache_result: bool = True) -> str:
        if not self.copilot_installed:
            raise RuntimeError("GitHub Copilot extension not installed")

        cache_key = f"explain:{code[:100]}" if cache_result else None
        result = self._run_command(["copilot", "explain", code], cache_key=cache_key)
        if result["success"]:
            return result["stdout"].strip()
        raise RuntimeError(f"Copilot explain failed: {result['stderr']}")

    def explain_code(
        self,
        code: str,
        language: Optional[str] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Compatibility wrapper returning a structured explanation result."""

        prompt = code if not language else f"Language: {language}\n\n{code}"
        try:
            explanation = self.explain(prompt, cache_result=use_cache)
            return {
                "success": True,
                "explanation": explanation,
                "code": code,
                "language": language,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "code": code,
                "language": language,
            }

    def suggest_command(
        self,
        description: str,
        shell: Optional[str] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Compatibility wrapper returning a structured shell suggestion."""

        query = description if not shell else f"{description}\nShell: {shell}"
        try:
            suggestion = self.suggest(query, cache_result=use_cache)
            return {
                "success": True,
                "suggestion": suggestion,
                "suggestions": suggestion,
                "description": description,
                "shell": shell,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "description": description,
                "shell": shell,
            }

    def suggest_git_command(
        self,
        description: str,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Compatibility wrapper returning a Git-oriented suggestion."""

        return self.suggest_command(f"git: {description}", use_cache=use_cache)

    def create_agent_task(
        self,
        *,
        task_description: str,
        base_branch: Optional[str] = None,
        follow: bool = False,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """Create a GitHub-hosted Copilot agent task when supported by ``gh``.

        This is intentionally separate from ``gh copilot``. The wrapper keeps the
        method for backward compatibility because several repo scripts call it
        through ``CopilotCLI``.
        """

        if not self.installed or not self.cli_path:
            return {
                "success": False,
                "error": "gh CLI not installed",
                "message": "GitHub CLI is not installed",
            }
        if not self.has_agent_task_support():
            return {
                "success": False,
                "error": "gh agent-task is not available in the installed GitHub CLI",
                "message": "The installed gh binary does not support agent-task",
            }

        args = ["agent-task", "create", task_description]
        if base_branch:
            args.extend(["--base", base_branch])
        if follow:
            args.append("--follow")

        try:
            result = self._run_command(args, timeout=timeout)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "message": "Failed to create GitHub Copilot agent task",
            }

        response = {
            "success": result["success"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "returncode": result["returncode"],
            "task_description": task_description,
            "base_branch": base_branch,
            "follow": follow,
        }
        if not result["success"]:
            response["error"] = (result.get("stderr") or result.get("stdout") or "gh agent-task create failed").strip()
        return response


class StandaloneCopilot(BaseCLITool):
    """Wrapper around the standalone local ``copilot`` CLI."""

    tool_name = "copilot"

    def __init__(
        self,
        copilot_cli_path: Optional[str] = None,
        enable_cache: bool = True,
        cache_maxsize: int = 100,
        cache_ttl: int = 600,
    ):
        resolved_path = copilot_cli_path or find_standalone_copilot_cli()
        super().__init__(
            cli_path=resolved_path,
            enable_cache=enable_cache,
            cache_maxsize=cache_maxsize,
            cache_ttl=cache_ttl,
        )

    def _verify_installation(self) -> bool:
        if not self.cli_path or not self.cli_path.exists():
            return False

        try:
            result = subprocess.run(
                [str(self.cli_path), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.debug("Failed to verify standalone copilot CLI: %s", exc)
            return False

    def get_status(self) -> Dict[str, Any]:
        version_info = ""
        if self.installed and self.cli_path:
            try:
                result = subprocess.run(
                    [str(self.cli_path), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    version_info = result.stdout.strip()
            except Exception:
                version_info = ""

        return {
            "installed": bool(self.installed),
            "copilot_cli_path": str(self.cli_path) if self.cli_path else None,
            "version_info": version_info,
            "command_template": build_standalone_copilot_command_template(
                str(self.cli_path) if self.cli_path else None
            ),
        }

    def prompt(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        allow_all_paths: bool = False,
        autopilot: bool = False,
        timeout: int = 180,
        cache_result: bool = False,
    ) -> Dict[str, Any]:
        if not self.installed:
            return {"success": False, "error": "standalone copilot CLI not installed"}

        cache_key = None
        if cache_result:
            cache_key = f"prompt:{model or ''}:{allow_all_paths}:{autopilot}:{prompt}"

        args = [
            "--silent",
            "--stream",
            "off",
            "--allow-all-tools",
            "--no-ask-user",
        ]
        if allow_all_paths:
            args.append("--allow-all-paths")
        if autopilot:
            args.append("--autopilot")
        if model:
            args.extend(["--model", model])
        args.extend(["-p", prompt])
        args[-2:] = ["--prompt", prompt]

        try:
            result = self._run_command(args, timeout=timeout, cache_key=cache_key)
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

        return {
            "success": result["success"],
            "response": (result["stdout"] or "").strip(),
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "returncode": result["returncode"],
        }


CopilotCLI = Copilot
