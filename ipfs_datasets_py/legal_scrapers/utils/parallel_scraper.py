#!/usr/bin/env python3
"""
Parallel Scraper with Multiprocessing Support

High-performance parallel scraping using multiprocessing for CPU-bound tasks
and asyncio for I/O-bound operations.
"""

import logging
import asyncio
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
import time
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ScrapingTask:
    """Represents a single scraping task."""
    url: str
    metadata: Optional[Dict[str, Any]] = None
    scraper_name: str = "unknown"
    priority: int = 0


@dataclass
class ScrapingResult:
    """Result from a scraping task."""
    task: ScrapingTask
    result: Dict[str, Any]
    duration: float
    success: bool
    error: Optional[str] = None


class ParallelScraper:
    """
    High-performance parallel scraper.
    
    Features:
    - Multiprocessing for CPU-intensive parsing
    - AsyncIO for I/O-bound network operations
    - Process pooling for efficient resource usage
    - Progress tracking
    - Error handling and retries
    - Rate limiting
    """
    
    def __init__(
        self,
        scraper_class,
        num_processes: Optional[int] = None,
        max_workers: Optional[int] = None,
        rate_limit: Optional[float] = None,
        use_multiprocessing: bool = True
    ):
        """
        Initialize parallel scraper.
        
        Args:
            scraper_class: Scraper class to use
            num_processes: Number of processes (defaults to CPU count)
            max_workers: Max concurrent workers
            rate_limit: Minimum seconds between requests
            use_multiprocessing: Use multiprocessing vs threading
        """
        self.scraper_class = scraper_class
        self.num_processes = num_processes or mp.cpu_count()
        self.max_workers = max_workers or (self.num_processes * 2)
        self.rate_limit = rate_limit
        self.use_multiprocessing = use_multiprocessing
        
        self.completed = 0
        self.failed = 0
        self.total = 0
        self.start_time = None
        
        logger.info(f"ParallelScraper initialized:")
        logger.info(f"  Processes: {self.num_processes}")
        logger.info(f"  Max workers: {self.max_workers}")
        logger.info(f"  Multiprocessing: {use_multiprocessing}")
        logger.info(f"  Rate limit: {rate_limit}s" if rate_limit else "  Rate limit: None")
    
    async def scrape_parallel_async(
        self,
        tasks: List[ScrapingTask],
        progress_callback: Optional[Callable] = None
    ) -> List[ScrapingResult]:
        """
        Scrape multiple URLs in parallel using asyncio.
        
        Best for I/O-bound operations (network requests).
        
        Args:
            tasks: List of scraping tasks
            progress_callback: Optional callback(completed, total)
            
        Returns:
            List of scraping results
        """
        self.total = len(tasks)
        self.completed = 0
        self.failed = 0
        self.start_time = time.time()
        
        logger.info(f"Starting parallel async scraping: {self.total} tasks")
        
        # Create semaphore for rate limiting
        semaphore = asyncio.Semaphore(self.max_workers)
        
        async def scrape_with_semaphore(task: ScrapingTask) -> ScrapingResult:
            async with semaphore:
                if self.rate_limit:
                    await asyncio.sleep(self.rate_limit)
                
                result = await self._scrape_single_async(task)
                
                self.completed += 1
                if not result.success:
                    self.failed += 1
                
                if progress_callback:
                    progress_callback(self.completed, self.total)
                
                return result
        
        # Execute all tasks
        results = await asyncio.gather(
            *[scrape_with_semaphore(task) for task in tasks],
            return_exceptions=True
        )
        
        # Handle exceptions
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Task {i} raised exception: {result}")
                final_results.append(ScrapingResult(
                    task=tasks[i],
                    result={},
                    duration=0,
                    success=False,
                    error=str(result)
                ))
            else:
                final_results.append(result)
        
        duration = time.time() - self.start_time
        logger.info(f"Parallel async scraping complete:")
        logger.info(f"  Total: {self.total}")
        logger.info(f"  Completed: {self.completed}")
        logger.info(f"  Failed: {self.failed}")
        logger.info(f"  Duration: {duration:.2f}s")
        logger.info(f"  Rate: {self.total / duration:.2f} tasks/sec")
        
        return final_results
    
    def scrape_parallel_multiprocess(
        self,
        tasks: List[ScrapingTask],
        progress_callback: Optional[Callable] = None
    ) -> List[ScrapingResult]:
        """
        Scrape multiple URLs using multiprocessing.
        
        Best for CPU-bound operations (parsing, processing).
        
        Args:
            tasks: List of scraping tasks
            progress_callback: Optional callback(completed, total)
            
        Returns:
            List of scraping results
        """
        self.total = len(tasks)
        self.completed = 0
        self.failed = 0
        self.start_time = time.time()
        
        logger.info(f"Starting parallel multiprocess scraping: {self.total} tasks")
        
        # Create process pool
        with ProcessPoolExecutor(max_workers=self.num_processes) as executor:
            # Submit all tasks
            futures = [
                executor.submit(_scrape_worker, self.scraper_class, task)
                for task in tasks
            ]
            
            # Collect results
            results = []
            for future in futures:
                try:
                    result = future.result()
                    results.append(result)
                    
                    self.completed += 1
                    if not result.success:
                        self.failed += 1
                    
                    if progress_callback:
                        progress_callback(self.completed, self.total)
                    
                    if self.rate_limit:
                        time.sleep(self.rate_limit)
                
                except Exception as e:
                    logger.error(f"Worker raised exception: {e}")
                    self.failed += 1
        
        duration = time.time() - self.start_time
        logger.info(f"Parallel multiprocess scraping complete:")
        logger.info(f"  Total: {self.total}")
        logger.info(f"  Completed: {self.completed}")
        logger.info(f"  Failed: {self.failed}")
        logger.info(f"  Duration: {duration:.2f}s")
        logger.info(f"  Rate: {self.total / duration:.2f} tasks/sec")
        
        return results
    
    def scrape_parallel(
        self,
        tasks: List[ScrapingTask],
        progress_callback: Optional[Callable] = None
    ) -> List[ScrapingResult]:
        """
        Scrape using the configured method (async or multiprocess).
        
        Args:
            tasks: List of scraping tasks
            progress_callback: Optional callback
            
        Returns:
            List of results
        """
        if self.use_multiprocessing:
            return self.scrape_parallel_multiprocess(tasks, progress_callback)
        else:
            # Run async in new event loop
            return asyncio.run(self.scrape_parallel_async(tasks, progress_callback))
    
    async def _scrape_single_async(self, task: ScrapingTask) -> ScrapingResult:
        """Scrape a single task asynchronously."""
        start_time = time.time()
        
        try:
            scraper = self.scraper_class()
            
            # Try to call with jurisdiction_url for Municode compatibility
            # Otherwise fall back to url parameter
            try:
                result = await scraper.scrape(jurisdiction_url=task.url, **task.metadata or {})
            except TypeError:
                # Fallback to different signature
                try:
                    result = await scraper.scrape(url=task.url, **task.metadata or {})
                except TypeError:
                    # Try with just the URL as first positional arg
                    result = await scraper.scrape(task.url, **task.metadata or {})
            
            duration = time.time() - start_time
            
            return ScrapingResult(
                task=task,
                result=result,
                duration=duration,
                success=result.get('status') in ['success', 'cached'],
                error=result.get('error')
            )
        
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Error scraping {task.url}: {e}")
            
            return ScrapingResult(
                task=task,
                result={},
                duration=duration,
                success=False,
                error=str(e)
            )
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get scraping statistics."""
        duration = time.time() - self.start_time if self.start_time else 0
        
        return {
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "success_rate": self.completed / self.total if self.total > 0 else 0,
            "duration": duration,
            "rate": self.total / duration if duration > 0 else 0,
            "avg_time_per_task": duration / self.total if self.total > 0 else 0
        }


def _scrape_worker(scraper_class, task: ScrapingTask) -> ScrapingResult:
    """
    Worker function for multiprocessing.
    
    This runs in a separate process.
    """
    import asyncio
    
    start_time = time.time()
    
    try:
        # Create new event loop for this process
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create scraper and run
        scraper = scraper_class()
        
        # Try different method signatures
        try:
            result = loop.run_until_complete(
                scraper.scrape(jurisdiction_url=task.url, **task.metadata or {})
            )
        except TypeError:
            try:
                result = loop.run_until_complete(
                    scraper.scrape(url=task.url, **task.metadata or {})
                )
            except TypeError:
                result = loop.run_until_complete(
                    scraper.scrape(task.url, **task.metadata or {})
                )
        
        loop.close()
        
        duration = time.time() - start_time
        
        return ScrapingResult(
            task=task,
            result=result,
            duration=duration,
            success=result.get('status') in ['success', 'cached'],
            error=result.get('error')
        )
    
    except Exception as e:
        duration = time.time() - start_time
        
        return ScrapingResult(
            task=task,
            result={},
            duration=duration,
            success=False,
            error=str(e)
        )


# Convenience functions

def scrape_urls_parallel(
    scraper_class,
    urls: List[str],
    num_processes: Optional[int] = None,
    use_multiprocessing: bool = True,
    progress: bool = True
) -> List[Dict[str, Any]]:
    """
    Convenience function to scrape multiple URLs in parallel.
    
    Args:
        scraper_class: Scraper class to use
        urls: List of URLs to scrape
        num_processes: Number of processes
        use_multiprocessing: Use multiprocessing vs asyncio
        progress: Show progress
        
    Returns:
        List of scraping results
    """
    # Create tasks
    tasks = [ScrapingTask(url=url) for url in urls]
    
    # Create progress callback
    def print_progress(completed, total):
        if progress:
            pct = (completed / total * 100) if total > 0 else 0
            print(f"\rProgress: {completed}/{total} ({pct:.1f}%)", end='', flush=True)
    
    # Create parallel scraper
    parallel = ParallelScraper(
        scraper_class=scraper_class,
        num_processes=num_processes,
        use_multiprocessing=use_multiprocessing
    )
    
    # Run scraping
    results = parallel.scrape_parallel(
        tasks=tasks,
        progress_callback=print_progress if progress else None
    )
    
    if progress:
        print()  # New line after progress
    
    # Extract just the result dicts
    return [r.result for r in results]


async def scrape_urls_parallel_async(
    scraper_class,
    urls: List[str],
    max_workers: Optional[int] = None,
    progress: bool = True
) -> List[Dict[str, Any]]:
    """
    Async convenience function to scrape multiple URLs.
    
    Args:
        scraper_class: Scraper class to use
        urls: List of URLs to scrape
        max_workers: Max concurrent workers
        progress: Show progress
        
    Returns:
        List of scraping results
    """
    tasks = [ScrapingTask(url=url) for url in urls]
    
    def print_progress(completed, total):
        if progress:
            pct = (completed / total * 100) if total > 0 else 0
            print(f"\rProgress: {completed}/{total} ({pct:.1f}%)", end='', flush=True)
    
    parallel = ParallelScraper(
        scraper_class=scraper_class,
        max_workers=max_workers,
        use_multiprocessing=False
    )
    
    results = await parallel.scrape_parallel_async(
        tasks=tasks,
        progress_callback=print_progress if progress else None
    )
    
    if progress:
        print()
    
    return [r.result for r in results]


if __name__ == "__main__":
    print("Parallel Scraper Module")
    print("Use with: from legal_scrapers.utils import ParallelScraper")
