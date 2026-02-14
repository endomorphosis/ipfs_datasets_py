"""Patch-based change control system with git worktrees and IPFS CIDs.

This module implements the backup change control method that doesn't rely
on GitHub API. It uses:
- Git patches for representing changes
- Git worktrees for isolated development
- IPFS CIDs for distributed patch storage and replication
- Patch chains for tracking related changes

ENHANCED: Added caching layer using utils.cache for improved performance.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import ChangeController, OptimizationResult
from ...utils.cache import LocalCache


@dataclass
class Patch:
    """Represents a code patch.
    
    Attributes:
        patch_id: Unique identifier for the patch
        agent_id: ID of agent that created the patch
        task_id: ID of optimization task
        description: Description of changes
        diff_content: The actual patch content (unified diff)
        target_files: List of files modified
        created_at: When the patch was created
        parent_patches: List of patch IDs this depends on
        ipfs_cid: IPFS content ID for this patch
        worktree_path: Path to worktree where patch was created
        validated: Whether patch has been validated
        applied: Whether patch has been applied
        metadata: Additional patch metadata
    """
    
    patch_id: str
    agent_id: str
    task_id: str
    description: str
    diff_content: str
    target_files: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    parent_patches: List[str] = field(default_factory=list)
    ipfs_cid: Optional[str] = None
    worktree_path: Optional[str] = None
    validated: bool = False
    applied: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert patch to dictionary."""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Patch':
        """Create patch from dictionary."""
        data = data.copy()
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)


class PatchManager:
    """Manages patch generation, storage, and application.
    
    This class handles creating unified diff patches from code changes,
    storing them with metadata, and applying them to target worktrees.
    
    Example:
        >>> manager = PatchManager()
        >>> patch = manager.create_patch(
        ...     agent_id="agent-1",
        ...     task_id="task-1",
        ...     worktree_path="/tmp/worktree",
        ...     description="Optimize function X"
        ... )
        >>> manager.save_patch(patch, "patches/patch-1.patch")
    """
    
    def __init__(self, patches_dir: Optional[Path] = None, enable_cache: bool = True):
        """Initialize patch manager.
        
        Args:
            patches_dir: Directory to store patch files (default: ./patches)
            enable_cache: Enable caching for patch lookups (default: True)
        """
        self.patches_dir = patches_dir or Path("./patches")
        self.patches_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.patches_dir / "patch_history.json"
        self.history: List[Dict[str, Any]] = self._load_history()
        
        # Add cache for patch lookups
        self._cache = LocalCache(
            maxsize=500,
            default_ttl=3600,  # 1 hour
            name="PatchCache"
        ) if enable_cache else None
        
    def create_patch(
        self,
        agent_id: str,
        task_id: str,
        worktree_path: Path,
        description: str,
        parent_patches: Optional[List[str]] = None,
    ) -> Patch:
        """Create a patch from worktree changes.
        
        Args:
            agent_id: ID of agent creating the patch
            task_id: ID of optimization task
            worktree_path: Path to worktree with changes
            description: Description of changes
            parent_patches: Optional list of parent patch IDs
            
        Returns:
            Patch object with generated diff
            
        Raises:
            ValueError: If worktree has no changes
            subprocess.CalledProcessError: If git operations fail
        """
        # Generate patch ID from hash of content
        patch_id = self._generate_patch_id(agent_id, task_id)
        
        # Get diff from worktree
        diff_content = self._get_worktree_diff(worktree_path)
        if not diff_content:
            raise ValueError(f"No changes found in worktree: {worktree_path}")
        
        # Extract modified files
        target_files = self._extract_modified_files(diff_content)
        
        patch = Patch(
            patch_id=patch_id,
            agent_id=agent_id,
            task_id=task_id,
            description=description,
            diff_content=diff_content,
            target_files=target_files,
            parent_patches=parent_patches or [],
            worktree_path=str(worktree_path),
        )
        
        return patch
    
    def save_patch(self, patch: Patch, output_path: Optional[Path] = None) -> Path:
        """Save patch to file.
        
        Args:
            patch: Patch to save
            output_path: Optional custom output path
            
        Returns:
            Path where patch was saved
        """
        if output_path is None:
            output_path = self.patches_dir / f"{patch.patch_id}.patch"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write patch file
        output_path.write_text(patch.diff_content)
        
        # Write metadata
        metadata_path = output_path.with_suffix('.json')
        metadata_path.write_text(json.dumps(patch.to_dict(), indent=2))
        
        # Update history
        self.history.append(patch.to_dict())
        self._save_history()
        
        return output_path
    
    def load_patch(self, patch_path: Path) -> Patch:
        """Load patch from file with caching.
        
        Args:
            patch_path: Path to patch file
            
        Returns:
            Loaded Patch object
            
        Raises:
            FileNotFoundError: If patch file doesn't exist
        """
        patch_path = Path(patch_path)
        cache_key = str(patch_path)
        
        # Check cache first
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        
        if not patch_path.exists():
            raise FileNotFoundError(f"Patch file not found: {patch_path}")
        
        # Load metadata
        metadata_path = patch_path.with_suffix('.json')
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text())
            patch = Patch.from_dict(metadata)
        else:
            # Fallback: create basic patch from diff content
            diff_content = patch_path.read_text()
            patch = Patch(
                patch_id=patch_path.stem,
                agent_id="unknown",
                task_id="unknown",
                description="Loaded from file",
                diff_content=diff_content,
            )
        
        # Cache the loaded patch
        if self._cache:
            self._cache.set(cache_key, patch)
        
        return patch
    
    def apply_patch(self, patch: Patch, target_path: Path) -> bool:
        """Apply patch to target directory.
        
        Args:
            patch: Patch to apply
            target_path: Directory to apply patch to
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Write patch to temp file
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.patch', delete=False
            ) as f:
                f.write(patch.diff_content)
                patch_file = f.name
            
            try:
                # Apply patch
                result = subprocess.run(
                    ['git', 'apply', '--check', patch_file],
                    cwd=target_path,
                    capture_output=True,
                    text=True,
                )
                
                if result.returncode != 0:
                    print(f"Patch check failed: {result.stderr}")
                    return False
                
                # Actually apply it
                result = subprocess.run(
                    ['git', 'apply', patch_file],
                    cwd=target_path,
                    capture_output=True,
                    text=True,
                )
                
                if result.returncode != 0:
                    print(f"Patch apply failed: {result.stderr}")
                    return False
                
                # Mark as applied
                patch.applied = True
                return True
                
            finally:
                os.unlink(patch_file)
                
        except Exception as e:
            print(f"Error applying patch: {e}")
            return False
    
    def create_reversal_patch(self, patch: Patch, worktree_path: Path) -> Patch:
        """Create a patch that reverses the given patch.
        
        Args:
            patch: Original patch to reverse
            worktree_path: Worktree where patch was applied
            
        Returns:
            New patch that reverses the original
        """
        # Reverse the diff
        reversed_diff = self._reverse_diff(patch.diff_content)
        
        reversal_patch = Patch(
            patch_id=f"{patch.patch_id}-reversal",
            agent_id=patch.agent_id,
            task_id=patch.task_id,
            description=f"Reversal of: {patch.description}",
            diff_content=reversed_diff,
            target_files=patch.target_files,
            parent_patches=[patch.patch_id],
            worktree_path=str(worktree_path),
        )
        
        return reversal_patch
    
    def get_patch_history(self, task_id: Optional[str] = None) -> List[Patch]:
        """Get patch history, optionally filtered by task.
        
        Args:
            task_id: Optional task ID to filter by
            
        Returns:
            List of patches in chronological order
        """
        patches = [Patch.from_dict(p) for p in self.history]
        
        if task_id:
            patches = [p for p in patches if p.task_id == task_id]
        
        return sorted(patches, key=lambda p: p.created_at)
    
    def _generate_patch_id(self, agent_id: str, task_id: str) -> str:
        """Generate unique patch ID."""
        timestamp = datetime.now().isoformat()
        content = f"{agent_id}-{task_id}-{timestamp}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _get_worktree_diff(self, worktree_path: Path) -> str:
        """Get diff from worktree."""
        result = subprocess.run(
            ['git', 'diff', 'HEAD'],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        return result.stdout
    
    def _extract_modified_files(self, diff_content: str) -> List[str]:
        """Extract list of modified files from diff."""
        files = []
        for line in diff_content.split('\n'):
            if line.startswith('diff --git'):
                # Extract filename from: diff --git a/file.py b/file.py
                parts = line.split()
                if len(parts) >= 3:
                    # Remove 'a/' prefix
                    filename = parts[2][2:] if parts[2].startswith('a/') else parts[2]
                    files.append(filename)
        return files
    
    def _reverse_diff(self, diff_content: str) -> str:
        """Reverse a unified diff."""
        lines = diff_content.split('\n')
        reversed_lines = []
        
        for line in lines:
            if line.startswith('+++'):
                # Swap +++ and ---
                reversed_lines.append(line.replace('+++', '---'))
            elif line.startswith('---'):
                reversed_lines.append(line.replace('---', '+++'))
            elif line.startswith('+') and not line.startswith('+++'):
                # Change + to -
                reversed_lines.append('-' + line[1:])
            elif line.startswith('-') and not line.startswith('---'):
                # Change - to +
                reversed_lines.append('+' + line[1:])
            else:
                reversed_lines.append(line)
        
        return '\n'.join(reversed_lines)
    
    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """Get cache statistics.
        
        Returns:
            Dict with cache stats or None if caching disabled
        """
        if not self._cache:
            return None
        
        # LocalCache exposes get_stats() returning a CacheStats object
        stats = self._cache.get_stats()
        if stats is None:
            return None
        
        # Convert CacheStats to dict
        from dataclasses import asdict
        try:
            return asdict(stats)
        except (TypeError, AttributeError):
            # Fallback for non-dataclass stats
            if isinstance(stats, dict):
                return stats
            return getattr(stats, "__dict__", {"value": str(stats)})
    
    def clear_cache(self) -> None:
        """Clear the patch cache."""
        if self._cache:
            self._cache.clear()
    
    def _load_history(self) -> List[Dict[str, Any]]:
        """Load patch history from file."""
        if self.history_file.exists():
            return json.loads(self.history_file.read_text())
        return []
    
    def _save_history(self) -> None:
        """Save patch history to file."""
        self.history_file.write_text(json.dumps(self.history, indent=2))


class WorktreeManager:
    """Manages git worktrees for isolated agent development.
    
    Each agent gets a dedicated worktree for making changes without
    interfering with other agents or the main working directory.
    
    Example:
        >>> manager = WorktreeManager(repo_path="/path/to/repo")
        >>> worktree = manager.create_worktree("agent-1")
        >>> # Agent makes changes in worktree
        >>> manager.cleanup_worktree("agent-1")
    """
    
    def __init__(
        self,
        repo_path: Path,
        worktrees_base: Optional[Path] = None,
    ):
        """Initialize worktree manager.
        
        Args:
            repo_path: Path to main git repository
            worktrees_base: Base directory for worktrees (default: /tmp/optimizer-worktrees)
        """
        self.repo_path = Path(repo_path)
        self.worktrees_base = worktrees_base or Path("/tmp/optimizer-worktrees")
        self.worktrees_base.mkdir(parents=True, exist_ok=True)
        self.active_worktrees: Dict[str, Path] = {}
        
    def create_worktree(
        self,
        agent_id: str,
        branch: Optional[str] = None,
    ) -> Path:
        """Create a new worktree for an agent.
        
        Args:
            agent_id: ID of agent to create worktree for
            branch: Optional branch to check out (default: HEAD)
            
        Returns:
            Path to created worktree
            
        Raises:
            RuntimeError: If worktree creation fails
        """
        # Generate unique worktree path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        worktree_name = f"agent-{agent_id}-{timestamp}"
        worktree_path = self.worktrees_base / worktree_name
        
        # Create worktree
        cmd = ['git', 'worktree', 'add', str(worktree_path)]
        if branch:
            cmd.append(branch)
        
        result = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create worktree: {result.stderr}"
            )
        
        self.active_worktrees[agent_id] = worktree_path
        return worktree_path
    
    def get_worktree(self, agent_id: str) -> Optional[Path]:
        """Get worktree path for agent.
        
        Args:
            agent_id: ID of agent
            
        Returns:
            Worktree path if exists, None otherwise
        """
        return self.active_worktrees.get(agent_id)
    
    def cleanup_worktree(self, agent_id: str) -> bool:
        """Remove worktree for agent.
        
        Args:
            agent_id: ID of agent whose worktree to remove
            
        Returns:
            True if successful, False otherwise
        """
        worktree_path = self.active_worktrees.get(agent_id)
        if not worktree_path:
            return False
        
        try:
            # Remove worktree
            result = subprocess.run(
                ['git', 'worktree', 'remove', str(worktree_path), '--force'],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            
            if result.returncode != 0:
                print(f"Warning: git worktree remove failed: {result.stderr}")
                # Try manual cleanup
                if worktree_path.exists():
                    shutil.rmtree(worktree_path)
            
            del self.active_worktrees[agent_id]
            return True
            
        except Exception as e:
            print(f"Error cleaning up worktree: {e}")
            return False
    
    def list_worktrees(self) -> List[Dict[str, str]]:
        """List all git worktrees.
        
        Returns:
            List of worktree info dictionaries
        """
        result = subprocess.run(
            ['git', 'worktree', 'list', '--porcelain'],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        
        if result.returncode != 0:
            return []
        
        worktrees = []
        current_wt = {}
        
        for line in result.stdout.split('\n'):
            if line.startswith('worktree '):
                if current_wt:
                    worktrees.append(current_wt)
                current_wt = {'path': line[9:]}
            elif line.startswith('HEAD '):
                current_wt['head'] = line[5:]
            elif line.startswith('branch '):
                current_wt['branch'] = line[7:]
        
        if current_wt:
            worktrees.append(current_wt)
        
        return worktrees


class IPFSPatchStore:
    """Stores and retrieves patches using IPFS.
    
    This enables distributed patch sharing across agents working
    in parallel. Patches are content-addressed by their CID.
    
    Example:
        >>> from ipfshttpclient import connect
        >>> ipfs_client = connect()
        >>> store = IPFSPatchStore(ipfs_client)
        >>> cid = store.store_patch(patch)
        >>> retrieved = store.get_patch(cid)
    """
    
    def __init__(self, ipfs_client: Any):
        """Initialize IPFS patch store.
        
        Args:
            ipfs_client: IPFS HTTP client (ipfshttpclient)
        """
        self.ipfs_client = ipfs_client
        
    def store_patch(self, patch: Patch) -> str:
        """Store patch in IPFS.
        
        Args:
            patch: Patch to store
            
        Returns:
            IPFS CID of stored patch
        """
        # Create patch bundle with metadata
        bundle = {
            'metadata': patch.to_dict(),
            'diff': patch.diff_content,
        }
        
        # Serialize to JSON
        content = json.dumps(bundle, indent=2)
        
        # Add to IPFS
        result = self.ipfs_client.add_str(content)
        cid = result if isinstance(result, str) else result['Hash']
        
        # Update patch with CID
        patch.ipfs_cid = cid
        
        return cid
    
    def get_patch(self, cid: str) -> Patch:
        """Retrieve patch from IPFS.
        
        Args:
            cid: IPFS CID of patch
            
        Returns:
            Retrieved Patch object
            
        Raises:
            ValueError: If CID is invalid or patch not found
        """
        try:
            # Get content from IPFS
            content = self.ipfs_client.cat(cid).decode('utf-8')
            bundle = json.loads(content)
            
            # Reconstruct patch
            patch = Patch.from_dict(bundle['metadata'])
            patch.diff_content = bundle['diff']
            patch.ipfs_cid = cid
            
            return patch
            
        except Exception as e:
            raise ValueError(f"Failed to retrieve patch {cid}: {e}")
    
    def pin_patch(self, cid: str) -> bool:
        """Pin a patch to ensure it's retained.
        
        Args:
            cid: IPFS CID to pin
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.ipfs_client.pin.add(cid)
            return True
        except Exception as e:
            print(f"Failed to pin {cid}: {e}")
            return False
    
    def broadcast_patch(self, cid: str) -> bool:
        """Broadcast patch CID to connected peers.
        
        Args:
            cid: CID to broadcast
            
        Returns:
            True if successful, False otherwise
        """
        # In practice, this would use libp2p pubsub or similar
        # For now, we just ensure it's pinned
        return self.pin_patch(cid)


class PatchBasedChangeController(ChangeController):
    """Change controller using patch-based system.
    
    This implementation uses git patches, worktrees, and IPFS for
    managing code changes without relying on GitHub API.
    """
    
    def __init__(
        self,
        repo_path: Path,
        ipfs_client: Any,
        patches_dir: Optional[Path] = None,
    ):
        """Initialize patch-based change controller.
        
        Args:
            repo_path: Path to git repository
            ipfs_client: IPFS HTTP client
            patches_dir: Directory for patch storage
        """
        self.repo_path = Path(repo_path)
        self.patch_manager = PatchManager(patches_dir)
        self.worktree_manager = WorktreeManager(repo_path)
        self.ipfs_store = IPFSPatchStore(ipfs_client)
        self.pending_changes: Dict[str, Patch] = {}
        
    def create_change(self, result: OptimizationResult) -> str:
        """Create change using patch system.
        
        Args:
            result: Optimization result to create change for
            
        Returns:
            IPFS CID of the patch
        """
        # Patch should already be created in optimization
        if result.patch_path:
            patch = self.patch_manager.load_patch(Path(result.patch_path))
        else:
            raise ValueError("No patch path in optimization result")
        
        # Store in IPFS
        cid = self.ipfs_store.store_patch(patch)
        patch.ipfs_cid = cid
        
        # Track as pending
        self.pending_changes[cid] = patch
        
        return cid
    
    def check_approval(self, change_id: str) -> bool:
        """Check if patch has been approved.
        
        For patch system, this could check a marker file or
        external approval tracking system.
        
        Args:
            change_id: IPFS CID of the patch
            
        Returns:
            True if approved, False otherwise
        """
        # Check for approval marker file
        approval_file = self.patch_manager.patches_dir / f"{change_id}.approved"
        return approval_file.exists()
    
    def apply_change(self, change_id: str) -> bool:
        """Apply approved patch.
        
        Args:
            change_id: IPFS CID of the patch
            
        Returns:
            True if successfully applied, False otherwise
        """
        # Get patch
        if change_id in self.pending_changes:
            patch = self.pending_changes[change_id]
        else:
            patch = self.ipfs_store.get_patch(change_id)
        
        # Apply to main repo
        success = self.patch_manager.apply_patch(patch, self.repo_path)
        
        if success:
            # Remove from pending
            if change_id in self.pending_changes:
                del self.pending_changes[change_id]
        
        return success
    
    def rollback_change(self, change_id: str) -> bool:
        """Rollback a previously applied patch.
        
        Args:
            change_id: IPFS CID of the patch to rollback
            
        Returns:
            True if successfully rolled back, False otherwise
        """
        # Get original patch
        patch = self.ipfs_store.get_patch(change_id)
        
        # Create reversal patch
        reversal = self.patch_manager.create_reversal_patch(
            patch,
            self.repo_path
        )
        
        # Apply reversal
        return self.patch_manager.apply_patch(reversal, self.repo_path)
