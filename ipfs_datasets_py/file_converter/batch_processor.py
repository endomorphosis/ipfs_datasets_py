"""
Enhanced batch processing with progress tracking and resource management.

Combines features from both converter systems with IPFS acceleration.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Union
from concurrent.futures import ThreadPoolExecutor
import time

logger = logging.getLogger(__name__)


@dataclass
class BatchProgress:
    """Track progress of batch conversion."""
    total: int
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    start_time: float = field(default_factory=time.time)
    errors: List[str] = field(default_factory=list)
    
    @property
    def pending(self) -> int:
        """Number of pending items."""
        return self.total - self.completed - self.failed - self.skipped
    
    @property
    def success_rate(self) -> float:
        """Success rate as percentage."""
        processed = self.completed + self.failed
        if processed == 0:
            return 0.0
        return (self.completed / processed) * 100
    
    @property
    def elapsed_time(self) -> float:
        """Elapsed time in seconds."""
        return time.time() - self.start_time
    
    @property
    def items_per_second(self) -> float:
        """Processing rate."""
        if self.elapsed_time == 0:
            return 0.0
        return (self.completed + self.failed) / self.elapsed_time
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'total': self.total,
            'completed': self.completed,
            'failed': self.failed,
            'skipped': self.skipped,
            'pending': self.pending,
            'success_rate': self.success_rate,
            'elapsed_time': self.elapsed_time,
            'items_per_second': self.items_per_second,
            'errors': self.errors[:10],  # Limit error list
        }


@dataclass
class ResourceLimits:
    """Resource management limits."""
    max_memory_mb: Optional[int] = None
    max_concurrent: int = 5
    max_file_size_mb: Optional[int] = None
    timeout_seconds: Optional[float] = None
    
    def check_file_size(self, file_path: str) -> bool:
        """Check if file size is within limits."""
        if self.max_file_size_mb is None:
            return True
        
        size_mb = Path(file_path).stat().st_size / (1024 * 1024)
        return size_mb <= self.max_file_size_mb


class BatchProcessor:
    """
    Enhanced batch processor with progress tracking and resource management.
    """
    
    def __init__(
        self,
        converter,
        limits: Optional[ResourceLimits] = None,
        progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    ):
        """
        Initialize batch processor.
        
        Args:
            converter: File converter instance to use
            limits: Resource limits for batch processing
            progress_callback: Callback function called with progress updates
        """
        self.converter = converter
        self.limits = limits or ResourceLimits()
        self.progress_callback = progress_callback
    
    async def process_batch(
        self,
        file_paths: List[str],
        **convert_kwargs
    ) -> List[Any]:
        """
        Process multiple files with progress tracking.
        
        Args:
            file_paths: List of file paths to convert
            **convert_kwargs: Additional arguments passed to converter
            
        Returns:
            List of conversion results
        """
        progress = BatchProgress(total=len(file_paths))
        results = []
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.limits.max_concurrent)
        
        async def process_one(file_path: str):
            """Process a single file with error handling."""
            async with semaphore:
                try:
                    # Check file size limits
                    if not self.limits.check_file_size(file_path):
                        logger.warning(f"File too large, skipping: {file_path}")
                        progress.skipped += 1
                        self._notify_progress(progress)
                        return None
                    
                    # Apply timeout if specified
                    if self.limits.timeout_seconds:
                        result = await asyncio.wait_for(
                            self.converter.convert(file_path, **convert_kwargs),
                            timeout=self.limits.timeout_seconds
                        )
                    else:
                        result = await self.converter.convert(file_path, **convert_kwargs)
                    
                    progress.completed += 1
                    self._notify_progress(progress)
                    return result
                
                except asyncio.TimeoutError:
                    error_msg = f"Timeout processing {file_path}"
                    logger.error(error_msg)
                    progress.failed += 1
                    progress.errors.append(error_msg)
                    self._notify_progress(progress)
                    return None
                
                except Exception as e:
                    error_msg = f"Error processing {file_path}: {str(e)}"
                    logger.error(error_msg)
                    progress.failed += 1
                    progress.errors.append(error_msg)
                    self._notify_progress(progress)
                    return None
        
        # Process all files concurrently
        tasks = [process_one(path) for path in file_paths]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        # Filter out None results
        results = [r for r in results if r is not None]
        
        return results
    
    def _notify_progress(self, progress: BatchProgress):
        """Notify progress callback if registered."""
        if self.progress_callback:
            try:
                self.progress_callback(progress)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
    
    def process_batch_sync(
        self,
        file_paths: List[str],
        **convert_kwargs
    ) -> List[Any]:
        """
        Synchronous wrapper for batch processing.
        
        Args:
            file_paths: List of file paths to convert
            **convert_kwargs: Additional arguments passed to converter
            
        Returns:
            List of conversion results
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.process_batch(file_paths, **convert_kwargs)
            )
        finally:
            loop.close()


class CacheManager:
    """
    Simple caching layer for conversion results.
    """
    
    def __init__(self, cache_dir: Optional[str] = None, max_cache_size_mb: int = 1000):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Directory for cache storage
            max_cache_size_mb: Maximum cache size in MB
        """
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / '.ipfs_datasets_cache'
        self.max_cache_size_mb = max_cache_size_mb
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Any] = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached result by key."""
        return self._cache.get(key)
    
    def set(self, key: str, value: Any):
        """Set cached result."""
        self._cache[key] = value
    
    def clear(self):
        """Clear all cached results."""
        self._cache.clear()
    
    def get_cache_key(self, file_path: str, **kwargs) -> str:
        """
        Generate cache key for a file and conversion parameters.
        
        Args:
            file_path: Path to file
            **kwargs: Conversion parameters
            
        Returns:
            Cache key string
        """
        import hashlib
        
        # Get file modification time
        mtime = Path(file_path).stat().st_mtime
        
        # Create key from path, mtime, and parameters
        key_parts = [file_path, str(mtime)]
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}={v}")
        
        key_string = "|".join(key_parts)
        return hashlib.sha256(key_string.encode()).hexdigest()


def create_batch_processor(
    converter,
    max_concurrent: int = 5,
    max_file_size_mb: Optional[int] = None,
    timeout_seconds: Optional[float] = None,
    progress_callback: Optional[Callable[[BatchProgress], None]] = None,
) -> BatchProcessor:
    """
    Convenience function to create a batch processor.
    
    Args:
        converter: File converter instance
        max_concurrent: Maximum concurrent conversions
        max_file_size_mb: Maximum file size in MB
        timeout_seconds: Timeout per file in seconds
        progress_callback: Progress callback function
        
    Returns:
        Configured BatchProcessor instance
    """
    limits = ResourceLimits(
        max_concurrent=max_concurrent,
        max_file_size_mb=max_file_size_mb,
        timeout_seconds=timeout_seconds,
    )
    
    return BatchProcessor(
        converter=converter,
        limits=limits,
        progress_callback=progress_callback,
    )
