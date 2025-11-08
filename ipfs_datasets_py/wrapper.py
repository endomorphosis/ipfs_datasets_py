"""
GitHub CLI Python Wrapper

This module provides Python wrappers for GitHub CLI (gh) commands,
enabling programmatic access to GitHub features with optional caching.
"""

import json
import logging
import os
import subprocess
import time
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from .cache import GitHubAPICache, get_global_cache

logger = logging.getLogger(__name__)


class GitHubCLI:
    """Python wrapper for GitHub CLI (gh) commands with optional caching."""
    
    def __init__(
        self,
        gh_path: str = "gh",
        enable_cache: bool = True,
        cache: Optional[GitHubAPICache] = None,
        cache_ttl: int = 300
    ):
        """
        Initialize GitHub CLI wrapper.
        
        Args:
            gh_path: Path to gh executable (default: "gh" from PATH)
            enable_cache: Whether to enable response caching
            cache: Custom cache instance (uses global cache if None)
            cache_ttl: Default cache TTL in seconds (default: 5 minutes)
        """
        self.gh_path = gh_path
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        
        # Set up cache
        if enable_cache:
            self.cache = cache if cache is not None else get_global_cache()
        else:
            self.cache = None
        
        self._verify_installation()
    
    def _verify_installation(self) -> None:
        """Verify that gh CLI is installed and authenticated."""
        try:
            logger.debug(f"Attempting to verify gh CLI at: {self.gh_path}")
            result = subprocess.run(
                [self.gh_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            logger.debug(f"gh CLI returncode: {result.returncode}, stdout: {result.stdout}, stderr: {result.stderr}")
            if result.returncode != 0:
                raise RuntimeError(f"gh CLI returned error (code {result.returncode}): stderr={result.stderr}, stdout={result.stdout}")
            logger.info(f"GitHub CLI version: {result.stdout.strip()}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            raise RuntimeError(f"Failed to verify gh CLI installation: {e}")
    
    def _run_command(
        self,
        args: List[str],
        stdin: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0
    ) -> Dict[str, Any]:
        """
        Run a gh CLI command with exponential backoff retry.
        
        Args:
            args: Command arguments
            stdin: Optional stdin input
            timeout: Command timeout in seconds
            max_retries: Maximum number of retry attempts
            base_delay: Base delay for exponential backoff (seconds)
            max_delay: Maximum delay between retries (seconds)
            
        Returns:
            Dict with stdout, stderr, and returncode
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                cmd = [self.gh_path] + args
                if attempt > 0:
                    logger.debug(f"Retry attempt {attempt}/{max_retries} for command: {' '.join(cmd)}")
                else:
                    logger.debug(f"Running command: {' '.join(cmd)}")
                
                result = subprocess.run(
                    cmd,
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                # Check for rate limiting in stderr
                stderr_lower = result.stderr.lower()
                if result.returncode != 0 and any(keyword in stderr_lower for keyword in ['rate limit', 'api rate limit', 'too many requests']):
                    if attempt < max_retries:
                        # Exponential backoff with jitter
                        delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                        logger.warning(f"Rate limit detected, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                        continue
                
                # Success or non-retryable error
                return {
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "returncode": result.returncode,
                    "success": result.returncode == 0,
                    "attempts": attempt + 1
                }
                
            except subprocess.TimeoutExpired:
                last_error = f"Command timed out after {timeout}s"
                if attempt < max_retries:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    logger.warning(f"Timeout, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                    
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    logger.warning(f"Error: {e}, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
        
        # All retries exhausted
        logger.error(f"Command failed after {max_retries + 1} attempts: {last_error}")
        return {
            "stdout": "",
            "stderr": last_error or "Unknown error",
            "returncode": -1,
            "success": False,
            "attempts": max_retries + 1
        }
    
    def get_auth_status(self) -> Dict[str, Any]:
        """Get GitHub authentication status."""
        # Check for GITHUB_TOKEN environment variable first
        import os
        if os.environ.get("GITHUB_TOKEN"):
            return {
                "authenticated": True,
                "output": "Authenticated via GITHUB_TOKEN environment variable",
                "error": ""
            }
        
        result = self._run_command(["auth", "status"])
        return {
            "authenticated": result["success"],
            "output": result["stdout"],
            "error": result["stderr"]
        }
    
    def get_auth_token(self) -> Optional[str]:
        """Get GitHub authentication token."""
        result = self._run_command(["auth", "token"])
        if result["success"]:
            return result["stdout"]
        return None
    
    def list_repos(
        self,
        owner: Optional[str] = None,
        limit: int = 30,
        visibility: str = "all",
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        List GitHub repositories.
        
        Args:
            owner: Repository owner (user or org)
            limit: Maximum number of repos to return
            visibility: Repository visibility (all, public, private)
            use_cache: Whether to use cached results
            
        Returns:
            List of repository dictionaries
        """
        # Check cache first
        if use_cache and self.cache:
            cached_result = self.cache.get("list_repos", owner=owner, limit=limit, visibility=visibility)
            if cached_result is not None:
                logger.debug(f"Using cached repo list for owner={owner}")
                return cached_result
        
        args = ["repo", "list", "--json", "name,owner,url,updatedAt", "--limit", str(limit)]
        if owner:
            args.append(owner)
        
        result = self._run_command(args)
        if result["success"] and result["stdout"]:
            try:
                repos = json.loads(result["stdout"])
                
                # Cache the result
                if use_cache and self.cache:
                    self.cache.put("list_repos", repos, ttl=self.cache_ttl, owner=owner, limit=limit, visibility=visibility)
                
                return repos
            except json.JSONDecodeError:
                logger.error(f"Failed to parse repo list: {result['stdout']}")
                return []
        return []
    
    def get_repo_info(self, repo: str, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific repository.
        
        Args:
            repo: Repository in format "owner/repo"
            use_cache: Whether to use cached results
            
        Returns:
            Repository information dictionary
        """
        # Check cache first
        if use_cache and self.cache:
            cached_result = self.cache.get("get_repo_info", repo=repo)
            if cached_result is not None:
                logger.debug(f"Using cached repo info for {repo}")
                return cached_result
        
        args = ["repo", "view", repo, "--json", 
                "name,owner,url,description,createdAt,updatedAt,pushedAt"]
        
        result = self._run_command(args)
        if result["success"] and result["stdout"]:
            try:
                repo_info = json.loads(result["stdout"])
                
                # Cache the result
                if use_cache and self.cache:
                    self.cache.put("get_repo_info", repo_info, ttl=self.cache_ttl, repo=repo)
                
                return repo_info
            except json.JSONDecodeError:
                logger.error(f"Failed to parse repo info: {result['stdout']}")
                return None
        return None


class WorkflowQueue:
    """Manage GitHub Actions workflow queues."""
    
    def __init__(self, gh_cli: Optional[GitHubCLI] = None):
        """
        Initialize workflow queue manager.
        
        Args:
            gh_cli: GitHubCLI instance (creates new one if None)
        """
        self.gh = gh_cli or GitHubCLI()
    
    def list_workflow_runs(
        self,
        repo: str,
        status: Optional[str] = None,
        limit: int = 20,
        branch: Optional[str] = None,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        List workflow runs for a repository.
        
        Args:
            repo: Repository in format "owner/repo"
            status: Filter by status (queued, in_progress, completed)
            limit: Maximum number of runs to return
            branch: Filter by branch
            use_cache: Whether to use cached results
            
        Returns:
            List of workflow run dictionaries
        """
        # Check cache first (shorter TTL for workflow runs - 60s)
        if use_cache and self.gh.cache:
            cached_result = self.gh.cache.get("list_workflow_runs", repo=repo, status=status, limit=limit, branch=branch)
            if cached_result is not None:
                logger.debug(f"Using cached workflow runs for {repo}")
                return cached_result
        
        args = ["run", "list", "--repo", repo, "--json",
                "databaseId,name,status,conclusion,createdAt,updatedAt,event,headBranch,workflowName",
                "--limit", str(limit)]
        
        if status:
            args.extend(["--status", status])
        if branch:
            args.extend(["--branch", branch])
        
        result = self.gh._run_command(args)
        if result["success"] and result["stdout"]:
            try:
                runs = json.loads(result["stdout"])
                
                # Cache with shorter TTL (60s) since workflow status changes frequently
                if use_cache and self.gh.cache:
                    self.gh.cache.put("list_workflow_runs", runs, ttl=60, repo=repo, status=status, limit=limit, branch=branch)
                
                return runs
            except json.JSONDecodeError:
                logger.error(f"Failed to parse workflow runs: {result['stdout']}")
                return []
        return []
    
    def get_workflow_run(self, repo: str, run_id: str, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get details of a specific workflow run.
        
        Args:
            repo: Repository in format "owner/repo"
            run_id: Workflow run ID
            use_cache: Whether to use cached results
            
        Returns:
            Workflow run details
        """
        # Check cache first (shorter TTL - 60s)
        if use_cache and self.gh.cache:
            cached_result = self.gh.cache.get("get_workflow_run", repo=repo, run_id=run_id)
            if cached_result is not None:
                logger.debug(f"Using cached workflow run {run_id} for {repo}")
                return cached_result
        
        args = ["run", "view", run_id, "--repo", repo, "--json",
                "databaseId,name,status,conclusion,createdAt,updatedAt,event,headBranch,workflowName,jobs"]
        
        result = self.gh._run_command(args)
        if result["success"] and result["stdout"]:
            try:
                run_details = json.loads(result["stdout"])
                
                # Cache with shorter TTL (60s)
                if use_cache and self.gh.cache:
                    self.gh.cache.put("get_workflow_run", run_details, ttl=60, repo=repo, run_id=run_id)
                
                return run_details
            except json.JSONDecodeError:
                logger.error(f"Failed to parse workflow run: {result['stdout']}")
                return None
        return None
    
    def list_failed_runs(
        self,
        repo: str,
        since_days: int = 1,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List failed workflow runs for a repository.
        
        Args:
            repo: Repository in format "owner/repo"
            since_days: Only include runs from the last N days
            limit: Maximum number of runs to return
            
        Returns:
            List of failed workflow run dictionaries
        """
        # Get all completed runs
        all_runs = self.list_workflow_runs(repo, status="completed", limit=limit)
        
        # Filter for failures within time window
        cutoff_date = datetime.now().replace(tzinfo=timezone.utc) - timedelta(days=since_days)
        failed_runs = []
        
        for run in all_runs:
            if run.get("conclusion") in ["failure", "timed_out", "cancelled"]:
                created_at = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))
                if created_at >= cutoff_date:
                    failed_runs.append(run)
        
        return failed_runs
    
    def get_repos_with_recent_activity(
        self,
        owner: Optional[str] = None,
        since_days: int = 1,
        limit: int = 100
    ) -> List[str]:
        """
        Get list of repositories with recent activity.
        
        Args:
            owner: Repository owner (user or org)
            since_days: Only include repos updated in the last N days
            limit: Maximum number of repos to check
            
        Returns:
            List of repository names in format "owner/repo"
        """
        repos = self.gh.list_repos(owner=owner, limit=limit)
        cutoff_date = datetime.now().replace(tzinfo=timezone.utc) - timedelta(days=since_days)
        
        recent_repos = []
        for repo in repos:
            updated_at = datetime.fromisoformat(repo["updatedAt"].replace("Z", "+00:00"))
            if updated_at >= cutoff_date:
                owner_name = repo["owner"]["login"]
                repo_name = repo["name"]
                recent_repos.append(f"{owner_name}/{repo_name}")
        
        return recent_repos
    
    def _check_workflow_runner_compatibility(
        self,
        workflow: Dict[str, Any],
        repo: str,
        system_arch: str
    ) -> bool:
        """
        Check if a workflow is compatible with the current system architecture.
        
        Args:
            workflow: Workflow run dictionary
            repo: Repository name
            system_arch: System architecture (e.g., 'x64', 'arm64')
            
        Returns:
            True if the workflow is compatible with this runner
        """
        workflow_name = workflow.get("workflowName", "").lower()
        
        # Architecture-specific workflow patterns
        if "arm64" in workflow_name or "aarch64" in workflow_name:
            # This workflow specifically requires ARM64
            return system_arch == "arm64"
        
        if "amd64" in workflow_name or "x86" in workflow_name or "x64" in workflow_name:
            # This workflow specifically requires x86_64
            return system_arch == "x64"
        
        # Try to get detailed job information to check runner labels
        try:
            run_id = workflow.get("databaseId")
            if run_id:
                detailed_run = self.get_workflow_run(repo, str(run_id))
                if detailed_run and "jobs" in detailed_run:
                    for job in detailed_run["jobs"]:
                        runner_labels = job.get("labels", [])
                        # Check if the job has specific architecture requirements
                        if "arm64" in runner_labels or "aarch64" in runner_labels:
                            return system_arch == "arm64"
                        if "x64" in runner_labels or "amd64" in runner_labels:
                            return system_arch == "x64"
        except Exception as e:
            logger.debug(f"Could not get detailed job info: {e}")
        
        # If no specific architecture is mentioned, assume it's compatible
        # (most workflows use ubuntu-latest which is x64)
        return True
    
    def create_workflow_queues(
        self,
        owner: Optional[str] = None,
        since_days: int = 1,
        system_arch: Optional[str] = None,
        filter_by_arch: bool = True
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Create workflow queues for repositories with recent activity.
        
        This method finds all repositories with recent updates and creates
        queues of running or failed workflows for each repository.
        
        Args:
            owner: Repository owner (user or org)
            since_days: Only include repos/workflows from the last N days
            system_arch: System architecture (e.g., 'x64', 'arm64') for filtering
            filter_by_arch: Whether to filter workflows by architecture compatibility
            
        Returns:
            Dict mapping repo names to lists of workflow runs
        """
        queues = {}
        
        # Get repositories with recent activity
        recent_repos = self.get_repos_with_recent_activity(owner=owner, since_days=since_days)
        logger.info(f"Found {len(recent_repos)} repositories with recent activity")
        
        # For each repo, get workflow runs
        for repo in recent_repos:
            logger.info(f"Processing repository: {repo}")
            
            # Get running workflows
            running = self.list_workflow_runs(repo, status="in_progress", limit=20)
            
            # Get failed workflows
            failed = self.list_failed_runs(repo, since_days=since_days, limit=20)
            
            # Combine workflows
            all_workflows = running + failed
            
            # Filter by architecture compatibility if requested
            if filter_by_arch and system_arch and all_workflows:
                compatible_workflows = [
                    w for w in all_workflows
                    if self._check_workflow_runner_compatibility(w, repo, system_arch)
                ]
                
                if len(compatible_workflows) < len(all_workflows):
                    logger.info(f"  Filtered {len(all_workflows) - len(compatible_workflows)} incompatible workflows for {system_arch}")
                
                all_workflows = compatible_workflows
            
            if all_workflows:
                queues[repo] = all_workflows
                logger.info(f"  Found {len(running)} running and {len(failed)} failed workflows (after filtering)")
        
        return queues


class RunnerManager:
    """Manage GitHub self-hosted runners."""
    
    def __init__(self, gh_cli: Optional[GitHubCLI] = None):
        """
        Initialize runner manager.
        
        Args:
            gh_cli: GitHubCLI instance (creates new one if None)
        """
        self.gh = gh_cli or GitHubCLI()
        self._system_arch = self._detect_system_architecture()
        self._runner_labels = self._generate_runner_labels()
    
    def _detect_system_architecture(self) -> str:
        """
        Detect the system architecture.
        
        Returns:
            Architecture string ('x64', 'arm64', etc.)
        """
        import platform
        arch = platform.machine().lower()
        
        # Map common architecture names to GitHub runner labels
        arch_map = {
            'x86_64': 'x64',
            'amd64': 'x64',
            'aarch64': 'arm64',
            'arm64': 'arm64',
        }
        
        return arch_map.get(arch, arch)
    
    def _generate_runner_labels(self) -> str:
        """
        Generate appropriate labels for this runner based on system capabilities.
        
        Returns:
            Comma-separated string of labels
        """
        import shutil
        
        labels = ['self-hosted', 'linux', self._system_arch, 'docker']
        
        # Add GPU labels if available
        try:
            # Check for NVIDIA GPU
            if shutil.which('nvidia-smi'):
                labels.extend(['cuda', 'gpu'])
        except Exception:
            pass
        
        try:
            # Check for AMD GPU
            if shutil.which('rocm-smi'):
                labels.extend(['rocm', 'gpu'])
        except Exception:
            pass
        
        if 'gpu' not in labels:
            labels.append('cpu-only')
        
        return ','.join(labels)
    
    def get_system_architecture(self) -> str:
        """Get the detected system architecture."""
        return self._system_arch
    
    def get_runner_labels(self) -> str:
        """Get the generated runner labels."""
        return self._runner_labels
    
    def get_system_cores(self) -> int:
        """Get the number of CPU cores on the system."""
        import multiprocessing
        return multiprocessing.cpu_count()
    
    def list_runners(
        self,
        repo: Optional[str] = None,
        org: Optional[str] = None,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        List self-hosted runners.
        
        Args:
            repo: Repository in format "owner/repo" (for repo-level runners)
            org: Organization name (for org-level runners)
            use_cache: Whether to use cached results
            
        Returns:
            List of runner dictionaries
        """
        # Check cache first (shorter TTL - 30s for runner status)
        if use_cache and self.gh.cache:
            cached_result = self.gh.cache.get("list_runners", repo=repo, org=org)
            if cached_result is not None:
                logger.debug(f"Using cached runner list for repo={repo}, org={org}")
                return cached_result
        
        if repo:
            # Repo-level runners (requires appropriate permissions)
            result = self.gh._run_command(
                ["api", f"repos/{repo}/actions/runners", "--jq", ".runners"]
            )
        elif org:
            # Org-level runners
            result = self.gh._run_command(
                ["api", f"orgs/{org}/actions/runners", "--jq", ".runners"]
            )
        else:
            logger.error("Must specify either repo or org")
            return []
        
        if result["success"] and result["stdout"]:
            try:
                runners = json.loads(result["stdout"])
                
                # Cache with very short TTL (30s) since runner status changes frequently
                if use_cache and self.gh.cache:
                    self.gh.cache.put("list_runners", runners, ttl=30, repo=repo, org=org)
                
                return runners
            except json.JSONDecodeError:
                logger.error(f"Failed to parse runners: {result['stdout']}")
                return []
        return []
    
    def get_runner_registration_token(
        self,
        repo: Optional[str] = None,
        org: Optional[str] = None
    ) -> Optional[str]:
        """
        Get a registration token for adding a new self-hosted runner.
        
        Args:
            repo: Repository in format "owner/repo" (for repo-level runners)
            org: Organization name (for org-level runners)
            
        Returns:
            Registration token or None if failed
        """
        if repo:
            endpoint = f"repos/{repo}/actions/runners/registration-token"
        elif org:
            endpoint = f"orgs/{org}/actions/runners/registration-token"
        else:
            logger.error("Must specify either repo or org")
            return None
        
        result = self.gh._run_command(
            ["api", "--method", "POST", endpoint, "--jq", ".token"]
        )
        
        if result["success"] and result["stdout"]:
            return result["stdout"]
        return None
    
    def provision_runners_for_queue(
        self,
        queues: Dict[str, List[Dict[str, Any]]],
        max_runners: Optional[int] = None,
        min_runners_per_repo: int = 1
    ) -> Dict[str, Dict[str, Any]]:
        """
        Provision self-hosted runners based on workflow queues.
        
        This method analyzes workflow queues and provisions runners
        based on system capacity and workflow load. Guarantees at least
        one runner per repository with active workflows.
        
        Args:
            queues: Dict mapping repo names to workflow lists
            max_runners: Maximum runners to provision (defaults to system cores)
            min_runners_per_repo: Minimum runners per repository (default: 1)
            
        Returns:
            Dict with provisioning status for each repo
        """
        if max_runners is None:
            max_runners = self.get_system_cores()
        
        logger.info(f"Provisioning runners (max: {max_runners}, min per repo: {min_runners_per_repo}, system cores: {self.get_system_cores()})")
        
        provisioning_status = {}
        runners_provisioned = 0
        
        # Sort repos by number of workflows (prioritize busy repos)
        sorted_repos = sorted(
            queues.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )
        
        for repo, workflows in sorted_repos:
            if runners_provisioned >= max_runners:
                logger.info(f"Reached max runners limit: {max_runners}")
                break
            
            # Determine how many runners this repo needs
            running_count = sum(1 for w in workflows if w.get("status") == "in_progress")
            failed_count = sum(1 for w in workflows if w.get("conclusion") in ["failure", "timed_out"])
            queued_count = sum(1 for w in workflows if w.get("status") in ["queued", "waiting"])
            
            # Calculate needed runners:
            # - At least min_runners_per_repo for any repo with workflows
            # - Additional runners for queued workflows (1 per queued workflow)
            # - Don't provision extra runners for failed workflows (they already ran)
            base_runners = min_runners_per_repo
            additional_runners = queued_count  # Only provision for queued workflows
            runners_needed = base_runners + additional_runners
            
            # Don't exceed available capacity
            runners_to_provision = min(runners_needed, max_runners - runners_provisioned)
            # Ensure we provision at least min_runners_per_repo if capacity allows
            runners_to_provision = max(min(min_runners_per_repo, max_runners - runners_provisioned), runners_to_provision)
            
            if runners_to_provision <= 0:
                logger.info(f"No capacity for {repo} (would need {runners_needed}, have {max_runners - runners_provisioned} slots)")
                continue  # Check next repo instead of breaking
            
            # Generate tokens for this repo (one token can be reused by multiple runners)
            token = self.get_runner_registration_token(repo=repo)
            
            if token:
                provisioning_status[repo] = {
                    "token": token,
                    "running_workflows": running_count,
                    "failed_workflows": failed_count,
                    "queued_workflows": queued_count,
                    "total_workflows": len(workflows),
                    "runners_needed": runners_needed,
                    "runners_to_provision": runners_to_provision,
                    "status": "token_generated"
                }
                runners_provisioned += runners_to_provision
                logger.info(f"Generated token for {repo}: provisioning {runners_to_provision} runner(s) (min {min_runners_per_repo} + {queued_count} queued) for {len(workflows)} workflow(s) ({running_count} running, {queued_count} queued, {failed_count} failed)")
            else:
                provisioning_status[repo] = {
                    "error": "Failed to generate registration token",
                    "running_workflows": running_count,
                    "failed_workflows": failed_count,
                    "queued_workflows": queued_count,
                    "total_workflows": len(workflows),
                    "status": "failed"
                }
                logger.error(f"Failed to generate token for {repo}")
        
        return provisioning_status
