"""Incremental update utilities for legal dataset tools.

Provides functionality to detect and fetch only new documents
since the last scraping operation, enabling efficient incremental updates.
"""
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class IncrementalUpdateTracker:
    """Tracks last update times for incremental scraping."""
    
    def __init__(self, tracker_dir: str = None):
        """Initialize incremental update tracker.
        
        Args:
            tracker_dir: Directory to store tracker files (default: ~/.ipfs_datasets/update_tracker)
        """
        if tracker_dir is None:
            import os
            tracker_dir = os.path.expanduser("~/.ipfs_datasets/update_tracker")
        
        self.tracker_dir = Path(tracker_dir)
        self.tracker_dir.mkdir(parents=True, exist_ok=True)
    
    def get_last_update(self, dataset_name: str, scope: str = "default") -> Optional[str]:
        """Get the last update timestamp for a dataset.
        
        Args:
            dataset_name: Name of the dataset (e.g., "recap_archive", "us_code")
            scope: Scope identifier (e.g., court, jurisdiction)
        
        Returns:
            ISO format timestamp of last update, or None if never updated
        """
        tracker_file = self.tracker_dir / f"{dataset_name}_{scope}.json"
        
        if not tracker_file.exists():
            return None
        
        try:
            with open(tracker_file, 'r') as f:
                data = json.load(f)
                return data.get("last_update")
        except Exception as e:
            logger.error(f"Failed to read tracker file: {e}")
            return None
    
    def set_last_update(self, dataset_name: str, timestamp: str = None, scope: str = "default", 
                       metadata: Dict[str, Any] = None):
        """Set the last update timestamp for a dataset.
        
        Args:
            dataset_name: Name of the dataset
            timestamp: ISO format timestamp (default: now)
            scope: Scope identifier
            metadata: Additional metadata to store
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        
        tracker_file = self.tracker_dir / f"{dataset_name}_{scope}.json"
        
        data = {
            "dataset_name": dataset_name,
            "scope": scope,
            "last_update": timestamp,
            "updated_at": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        try:
            with open(tracker_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Updated tracker for {dataset_name}/{scope}: {timestamp}")
        except Exception as e:
            logger.error(f"Failed to write tracker file: {e}")
    
    def get_all_trackers(self) -> List[Dict[str, Any]]:
        """Get all tracked datasets.
        
        Returns:
            List of tracker data dictionaries
        """
        trackers = []
        
        for tracker_file in self.tracker_dir.glob("*.json"):
            try:
                with open(tracker_file, 'r') as f:
                    data = json.load(f)
                    trackers.append(data)
            except Exception as e:
                logger.error(f"Failed to read tracker {tracker_file}: {e}")
        
        return trackers
    
    def delete_tracker(self, dataset_name: str, scope: str = "default"):
        """Delete a tracker file.
        
        Args:
            dataset_name: Name of the dataset
            scope: Scope identifier
        """
        tracker_file = self.tracker_dir / f"{dataset_name}_{scope}.json"
        
        try:
            if tracker_file.exists():
                tracker_file.unlink()
                logger.info(f"Deleted tracker for {dataset_name}/{scope}")
        except Exception as e:
            logger.error(f"Failed to delete tracker: {e}")


def calculate_update_parameters(
    last_update: Optional[str],
    default_lookback_days: int = 30,
    overlap_hours: int = 24
) -> Dict[str, str]:
    """Calculate date parameters for incremental update.
    
    Args:
        last_update: ISO timestamp of last update
        default_lookback_days: Days to look back if no last update
        overlap_hours: Hours of overlap to prevent missing documents
    
    Returns:
        Dict with 'filed_after' and 'filed_before' keys
    """
    if last_update:
        try:
            last_dt = datetime.fromisoformat(last_update)
            # Add overlap to catch any documents that might have been missed
            filed_after_dt = last_dt - timedelta(hours=overlap_hours)
            filed_after = filed_after_dt.strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning(f"Failed to parse last_update timestamp: {e}, using default")
            filed_after = (datetime.now() - timedelta(days=default_lookback_days)).strftime("%Y-%m-%d")
    else:
        # No previous update, use default lookback
        filed_after = (datetime.now() - timedelta(days=default_lookback_days)).strftime("%Y-%m-%d")
    
    filed_before = datetime.now().strftime("%Y-%m-%d")
    
    return {
        "filed_after": filed_after,
        "filed_before": filed_before
    }


async def scrape_recap_incremental(
    courts: Optional[List[str]] = None,
    document_types: Optional[List[str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Scrape RECAP Archive incrementally since last update.
    
    This is a wrapper around scrape_recap_archive that automatically
    determines the date range based on the last update.
    
    Args:
        courts: List of court identifiers
        document_types: Types of documents to scrape
        **kwargs: Additional arguments passed to scrape_recap_archive
    
    Returns:
        Dict with scraping results and update info
    """
    from .recap_archive_scraper import scrape_recap_archive
    
    # Initialize tracker
    tracker = IncrementalUpdateTracker()
    
    # Determine scope for tracking
    scope = "_".join(sorted(courts)) if courts else "all"
    
    # Get last update time
    last_update = tracker.get_last_update("recap_archive", scope)
    
    logger.info(f"Incremental update for RECAP Archive/{scope}, last update: {last_update or 'never'}")
    
    # Calculate date parameters
    date_params = calculate_update_parameters(last_update)
    
    # Override any provided date parameters with incremental ones
    kwargs['filed_after'] = date_params['filed_after']
    kwargs['filed_before'] = date_params['filed_before']
    
    # Scrape with calculated parameters
    result = await scrape_recap_archive(
        courts=courts,
        document_types=document_types,
        **kwargs
    )
    
    # Update tracker if successful
    if result.get('status') == 'success':
        tracker.set_last_update(
            "recap_archive",
            timestamp=datetime.now().isoformat(),
            scope=scope,
            metadata={
                "documents_count": result.get('metadata', {}).get('documents_count', 0),
                "courts": courts,
                "document_types": document_types
            }
        )
        
        # Add incremental update info to result
        result['incremental_update'] = {
            "last_update": last_update,
            "date_range_used": date_params,
            "is_first_update": last_update is None
        }
    
    return result


async def scrape_with_incremental_update(
    scraper_func,
    dataset_name: str,
    scope: str = "default",
    date_param_names: tuple = ("filed_after", "filed_before"),
    **kwargs
) -> Dict[str, Any]:
    """Generic wrapper for incremental updates of any scraper.
    
    Args:
        scraper_func: Async scraper function to call
        dataset_name: Name of the dataset for tracking
        scope: Scope identifier
        date_param_names: Tuple of (start_date_param, end_date_param) names
        **kwargs: Arguments to pass to scraper function
    
    Returns:
        Dict with scraping results and update info
    """
    tracker = IncrementalUpdateTracker()
    
    # Get last update
    last_update = tracker.get_last_update(dataset_name, scope)
    
    logger.info(f"Incremental update for {dataset_name}/{scope}, last update: {last_update or 'never'}")
    
    # Calculate date parameters
    date_params = calculate_update_parameters(last_update)
    
    # Set date parameters
    start_param, end_param = date_param_names
    kwargs[start_param] = date_params['filed_after']
    kwargs[end_param] = date_params['filed_before']
    
    # Call scraper
    result = await scraper_func(**kwargs)
    
    # Update tracker if successful
    if result.get('status') == 'success':
        tracker.set_last_update(
            dataset_name,
            timestamp=datetime.now().isoformat(),
            scope=scope,
            metadata={
                "items_count": len(result.get('data', [])),
                "parameters": kwargs
            }
        )
        
        # Add incremental update info
        result['incremental_update'] = {
            "last_update": last_update,
            "date_range_used": date_params,
            "is_first_update": last_update is None
        }
    
    return result
