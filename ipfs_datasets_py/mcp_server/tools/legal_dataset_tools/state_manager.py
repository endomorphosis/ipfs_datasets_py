"""State management for resumable scraping operations.

Provides functionality to save and restore scraping state, enabling
resume capability for interrupted or failed scraping jobs.
"""
import logging
import json
import pickle
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class ScrapingState:
    """Manages state for a scraping operation."""
    
    def __init__(self, job_id: str, state_dir: str = None):
        """Initialize scraping state.
        
        Args:
            job_id: Unique identifier for this scraping job
            state_dir: Directory to store state files (default: ~/.ipfs_datasets/scraping_state)
        """
        self.job_id = job_id
        
        if state_dir is None:
            import os
            state_dir = os.path.expanduser("~/.ipfs_datasets/scraping_state")
        
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.state_file = self.state_dir / f"{job_id}.json"
        self.data_file = self.state_dir / f"{job_id}.pickle"
        
        self.metadata = {
            "job_id": job_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "initialized",
            "progress": {
                "items_processed": 0,
                "items_total": 0,
                "current_item": None
            },
            "parameters": {},
            "errors": []
        }
        
        self.scraped_data = []
        self.processed_items = set()
    
    def save(self) -> bool:
        """Save current state to disk.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Update timestamp
            self.metadata["updated_at"] = datetime.now().isoformat()
            
            # Save metadata as JSON
            with open(self.state_file, 'w') as f:
                json.dump(self.metadata, f, indent=2)
            
            # Save data and processed items as pickle
            state_data = {
                "scraped_data": self.scraped_data,
                "processed_items": list(self.processed_items)
            }
            with open(self.data_file, 'wb') as f:
                pickle.dump(state_data, f)
            
            logger.info(f"Saved scraping state for job {self.job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save scraping state: {e}")
            return False
    
    def load(self) -> bool:
        """Load state from disk.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Load metadata
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    self.metadata = json.load(f)
            else:
                logger.warning(f"No saved state found for job {self.job_id}")
                return False
            
            # Load data
            if self.data_file.exists():
                with open(self.data_file, 'rb') as f:
                    state_data = pickle.load(f)
                    self.scraped_data = state_data.get("scraped_data", [])
                    self.processed_items = set(state_data.get("processed_items", []))
            
            logger.info(f"Loaded scraping state for job {self.job_id}: {len(self.scraped_data)} items")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load scraping state: {e}")
            return False
    
    def update_progress(self, items_processed: int, items_total: int, current_item: Any = None):
        """Update progress information.
        
        Args:
            items_processed: Number of items processed so far
            items_total: Total number of items to process
            current_item: Current item being processed
        """
        self.metadata["progress"] = {
            "items_processed": items_processed,
            "items_total": items_total,
            "current_item": str(current_item) if current_item else None,
            "percentage": (items_processed / items_total * 100) if items_total > 0 else 0
        }
    
    def set_status(self, status: str):
        """Set current status.
        
        Args:
            status: Status string (e.g., 'running', 'paused', 'completed', 'failed')
        """
        self.metadata["status"] = status
        self.metadata["updated_at"] = datetime.now().isoformat()
    
    def set_parameters(self, parameters: Dict[str, Any]):
        """Set scraping parameters.
        
        Args:
            parameters: Dictionary of scraping parameters
        """
        self.metadata["parameters"] = parameters
    
    def add_error(self, error: str):
        """Add an error message.
        
        Args:
            error: Error message
        """
        self.metadata["errors"].append({
            "timestamp": datetime.now().isoformat(),
            "error": error
        })
    
    def add_item(self, item: Dict[str, Any], item_id: str = None):
        """Add a scraped item.
        
        Args:
            item: Scraped item data
            item_id: Unique identifier for this item (for deduplication)
        """
        self.scraped_data.append(item)
        
        if item_id:
            self.processed_items.add(item_id)
    
    def is_processed(self, item_id: str) -> bool:
        """Check if an item has already been processed.
        
        Args:
            item_id: Item identifier to check
        
        Returns:
            True if item was already processed
        """
        return item_id in self.processed_items
    
    def get_data(self) -> List[Dict[str, Any]]:
        """Get all scraped data.
        
        Returns:
            List of scraped items
        """
        return self.scraped_data
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get metadata about the scraping operation.
        
        Returns:
            Metadata dictionary
        """
        return self.metadata
    
    def cleanup(self):
        """Remove state files from disk."""
        try:
            if self.state_file.exists():
                self.state_file.unlink()
            if self.data_file.exists():
                self.data_file.unlink()
            logger.info(f"Cleaned up state files for job {self.job_id}")
        except Exception as e:
            logger.error(f"Failed to cleanup state files: {e}")


def list_scraping_jobs(state_dir: str = None) -> List[Dict[str, Any]]:
    """List all saved scraping jobs.
    
    Args:
        state_dir: Directory containing state files
    
    Returns:
        List of job metadata dictionaries
    """
    if state_dir is None:
        import os
        state_dir = os.path.expanduser("~/.ipfs_datasets/scraping_state")
    
    state_path = Path(state_dir)
    if not state_path.exists():
        return []
    
    jobs = []
    for state_file in state_path.glob("*.json"):
        try:
            with open(state_file, 'r') as f:
                metadata = json.load(f)
                jobs.append(metadata)
        except Exception as e:
            logger.error(f"Failed to load job metadata from {state_file}: {e}")
    
    return jobs


def delete_scraping_job(job_id: str, state_dir: str = None) -> bool:
    """Delete a saved scraping job.
    
    Args:
        job_id: Job identifier
        state_dir: Directory containing state files
    
    Returns:
        True if successful
    """
    state = ScrapingState(job_id, state_dir)
    state.cleanup()
    return True
