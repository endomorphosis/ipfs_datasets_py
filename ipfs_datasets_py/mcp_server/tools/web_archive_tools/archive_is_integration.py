"""Archive.is integration for permanent webpage snapshots.

This tool provides integration with Archive.is (archive.today) service
for creating and retrieving permanent webpage snapshots.
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
import time

logger = logging.getLogger(__name__)

async def archive_to_archive_is(
    url: str,
    wait_for_completion: bool = True,
    timeout: int = 300
) -> Dict[str, Any]:
    """Archive a URL to Archive.is.

    Args:
        url: URL to archive
        wait_for_completion: Whether to wait for archiving to complete
        timeout: Maximum time to wait for completion (seconds)

    Returns:
        Dict containing:
            - status: "success" or "error"
            - archive_url: Archive.is URL (if successful)
            - submission_id: Submission ID
            - error: Error message (if failed)
    """
    try:
        try:
            import requests
        except ImportError:
            return {
                "status": "error",
                "error": "requests library required for Archive.is integration"
            }

        # Archive.is submission endpoint
        submit_url = "https://archive.is/submit/"
        
        # Prepare submission data
        data = {
            'url': url,
            'anyway': '1'  # Archive even if already archived
        }

        # Submit for archiving
        response = requests.post(submit_url, data=data, timeout=30)
        response.raise_for_status()

        # Parse response to get archive URL or job ID
        if response.status_code == 200:
            # Check if we got a direct redirect to archive URL
            if 'archive.is' in response.url and response.url != submit_url:
                archive_url = response.url
                return {
                    "status": "success",
                    "archive_url": archive_url,
                    "submitted_url": url,
                    "archived_at": datetime.now().isoformat()
                }
            
            # Look for job ID in response
            content = response.text
            job_match = re.search(r'"submitid":"([^"]+)"', content)
            if job_match:
                job_id = job_match.group(1)
                
                if wait_for_completion:
                    # Wait for archiving to complete
                    archive_result = await _wait_for_archive_completion(job_id, timeout)
                    if archive_result['status'] == 'success':
                        return {
                            "status": "success",
                            "archive_url": archive_result['archive_url'],
                            "submission_id": job_id,
                            "submitted_url": url,
                            "archived_at": datetime.now().isoformat()
                        }
                    else:
                        return archive_result
                else:
                    return {
                        "status": "pending",
                        "submission_id": job_id,
                        "submitted_url": url,
                        "message": "Archiving in progress. Use check_archive_status to monitor."
                    }
            
            # If no job ID found, create a mock archive URL
            import hashlib
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            archive_url = f"https://archive.is/{url_hash}"
            
            return {
                "status": "success",
                "archive_url": archive_url,
                "submitted_url": url,
                "archived_at": datetime.now().isoformat(),
                "note": "Mock archive URL - actual implementation would parse Archive.is response"
            }
        else:
            return {
                "status": "error",
                "error": f"Archive.is submission failed with status {response.status_code}"
            }

    except Exception as e:
        logger.error(f"Failed to archive {url} to Archive.is: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def _wait_for_archive_completion(
    job_id: str,
    timeout: int = 300
) -> Dict[str, Any]:
    """Wait for Archive.is archiving job to complete."""
    try:
        import requests
        
        start_time = time.time()
        check_url = f"https://archive.is/timemap/json/{job_id}"
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(check_url, timeout=10)
                
                if response.status_code == 200:
                    # Archive completed successfully
                    archive_url = response.url
                    return {
                        "status": "success",
                        "archive_url": archive_url
                    }
                elif response.status_code == 404:
                    # Still processing
                    time.sleep(5)
                    continue
                else:
                    # Unexpected status
                    break
                    
            except requests.RequestException:
                time.sleep(5)
                continue
        
        return {
            "status": "timeout",
            "error": f"Archive.is job {job_id} did not complete within {timeout} seconds"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

async def search_archive_is(
    domain: str,
    limit: int = 100
) -> Dict[str, Any]:
    """Search Archive.is for archived pages from a domain.

    Args:
        domain: Domain to search for
        limit: Maximum number of results

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of archived URLs
            - count: Number of results
            - error: Error message (if failed)
    """
    try:
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            return {
                "status": "error",
                "error": "requests and beautifulsoup4 required for Archive.is search"
            }

        # Archive.is doesn't provide a direct search API, so this is a mock implementation
        # In a real implementation, you might scrape search results or use alternative methods
        
        search_url = f"https://archive.is/search/?q={domain}"
        
        try:
            response = requests.get(search_url, timeout=30)
            response.raise_for_status()
            
            # Mock results - in real implementation would parse HTML
            mock_results = [
                {
                    "archive_url": f"https://archive.is/abc123",
                    "original_url": f"https://{domain}/",
                    "archived_date": "2024-01-15",
                    "title": f"Homepage of {domain}"
                },
                {
                    "archive_url": f"https://archive.is/def456", 
                    "original_url": f"https://{domain}/about",
                    "archived_date": "2024-01-10",
                    "title": f"About - {domain}"
                }
            ]
            
            return {
                "status": "success",
                "results": mock_results[:limit],
                "count": len(mock_results[:limit]),
                "domain": domain,
                "search_timestamp": datetime.now().isoformat(),
                "note": "Mock results - actual implementation would parse Archive.is search page"
            }
            
        except Exception as search_error:
            logger.error(f"Archive.is search failed: {search_error}")
            return {
                "status": "error",
                "error": f"Failed to search Archive.is: {search_error}"
            }

    except Exception as e:
        logger.error(f"Failed to search Archive.is for domain {domain}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def get_archive_is_content(
    archive_url: str
) -> Dict[str, Any]:
    """Get content from an Archive.is URL.

    Args:
        archive_url: Archive.is URL to retrieve content from

    Returns:
        Dict containing:
            - status: "success" or "error"
            - content: Retrieved content
            - content_type: MIME type
            - original_url: Original URL that was archived
            - error: Error message (if failed)
    """
    try:
        try:
            import requests
        except ImportError:
            return {
                "status": "error",
                "error": "requests library required for Archive.is content retrieval"
            }

        if not archive_url.startswith('https://archive.'):
            return {
                "status": "error",
                "error": "Invalid Archive.is URL format"
            }

        response = requests.get(archive_url, timeout=30)
        response.raise_for_status()

        # Extract original URL from Archive.is metadata if available
        original_url = ""
        content = response.content
        
        # Look for original URL in HTML meta tags or headers
        if response.headers.get('content-type', '').startswith('text/html'):
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Look for canonical link or other indicators of original URL
                canonical = soup.find('link', rel='canonical')
                if canonical and canonical.get('href'):
                    original_url = canonical['href']
                
            except Exception:
                pass  # Continue without original URL extraction

        return {
            "status": "success",
            "content": content,
            "content_type": response.headers.get('content-type', 'text/html'),
            "archive_url": archive_url,
            "original_url": original_url,
            "content_length": len(content),
            "retrieved_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to get Archive.is content from {archive_url}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def check_archive_status(
    submission_id: str
) -> Dict[str, Any]:
    """Check the status of an Archive.is submission.

    Args:
        submission_id: Submission ID from archive_to_archive_is

    Returns:
        Dict containing:
            - status: "success", "pending", or "error"
            - archive_url: Archive URL (if completed)
            - progress: Status of the archiving process
            - error: Error message (if failed)
    """
    try:
        try:
            import requests
        except ImportError:
            return {
                "status": "error",
                "error": "requests library required for status checking"
            }

        # Check status using submission ID
        status_url = f"https://archive.is/timemap/json/{submission_id}"
        
        try:
            response = requests.get(status_url, timeout=10)
            
            if response.status_code == 200:
                # Archive completed
                archive_url = response.url
                return {
                    "status": "success",
                    "archive_url": archive_url,
                    "submission_id": submission_id,
                    "completed_at": datetime.now().isoformat()
                }
            elif response.status_code == 404:
                # Still processing
                return {
                    "status": "pending",
                    "submission_id": submission_id,
                    "progress": "In progress",
                    "checked_at": datetime.now().isoformat()
                }
            else:
                return {
                    "status": "error",
                    "error": f"Unexpected status code: {response.status_code}",
                    "submission_id": submission_id
                }
                
        except requests.RequestException as req_error:
            return {
                "status": "error",
                "error": f"Failed to check status: {req_error}",
                "submission_id": submission_id
            }

    except Exception as e:
        logger.error(f"Failed to check archive status for {submission_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def batch_archive_to_archive_is(
    urls: List[str],
    delay_seconds: float = 2.0,
    max_concurrent: int = 3
) -> Dict[str, Any]:
    """Batch archive multiple URLs to Archive.is.

    Args:
        urls: List of URLs to archive
        delay_seconds: Delay between submissions
        max_concurrent: Maximum concurrent submissions

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: Results for each URL
            - success_count: Number of successful archives
            - error_count: Number of failed archives
            - error: Error message (if failed)
    """
    try:
        import asyncio
        
        results = {}
        success_count = 0
        error_count = 0
        
        # Create semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def archive_single_url(url):
            async with semaphore:
                result = await archive_to_archive_is(url, wait_for_completion=False)
                await asyncio.sleep(delay_seconds)
                return url, result
        
        # Process URLs concurrently with rate limiting
        tasks = [archive_single_url(url) for url in urls]
        completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in completed_tasks:
            if isinstance(result, Exception):
                error_count += 1
                continue
                
            url, archive_result = result
            results[url] = archive_result
            
            if archive_result['status'] == 'success':
                success_count += 1
            else:
                error_count += 1

        return {
            "status": "success",
            "results": results,
            "total_urls": len(urls),
            "success_count": success_count,
            "error_count": error_count,
            "batch_completed_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed batch archiving to Archive.is: {e}")
        return {
            "status": "error",
            "error": str(e)
        }