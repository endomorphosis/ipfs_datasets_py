"""Scraping state management for resumable legal dataset scrapers.

This is package-level functionality intended to be reused by:
- MCP tool wrappers
- MCP server wrappers
- CLI

It was previously implemented under the MCP server tool tree; it now lives in
the importable package surface.
"""

from __future__ import annotations

import json
import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ScrapingState:
    """Manages state for a scraping operation."""

    def __init__(self, job_id: str, state_dir: str | None = None):
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

        self.metadata: Dict[str, Any] = {
            "job_id": job_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "initialized",
            "progress": {
                "items_processed": 0,
                "items_total": 0,
                "current_item": None,
            },
            "parameters": {},
            "errors": [],
        }

        self.scraped_data: List[Dict[str, Any]] = []
        self.processed_items: set[str] = set()

    def save(self) -> bool:
        """Save current state to disk."""

        try:
            self.metadata["updated_at"] = datetime.now().isoformat()

            with open(self.state_file, "w") as f:
                json.dump(self.metadata, f, indent=2)

            state_data = {
                "scraped_data": self.scraped_data,
                "processed_items": list(self.processed_items),
            }
            with open(self.data_file, "wb") as f:
                pickle.dump(state_data, f)

            logger.info("Saved scraping state for job %s", self.job_id)
            return True

        except Exception as e:
            logger.error("Failed to save scraping state: %s", e)
            return False

    def load(self) -> bool:
        """Load state from disk."""

        try:
            if self.state_file.exists():
                with open(self.state_file, "r") as f:
                    self.metadata = json.load(f)
            else:
                logger.warning("No saved state found for job %s", self.job_id)
                return False

            if self.data_file.exists():
                with open(self.data_file, "rb") as f:
                    state_data = pickle.load(f)
                    self.scraped_data = state_data.get("scraped_data", [])
                    self.processed_items = set(state_data.get("processed_items", []))

            logger.info(
                "Loaded scraping state for job %s: %s items",
                self.job_id,
                len(self.scraped_data),
            )
            return True

        except Exception as e:
            logger.error("Failed to load scraping state: %s", e)
            return False

    def update_progress(self, items_processed: int, items_total: int, current_item: Any = None):
        self.metadata["progress"] = {
            "items_processed": items_processed,
            "items_total": items_total,
            "current_item": str(current_item) if current_item else None,
            "percentage": (items_processed / items_total * 100) if items_total > 0 else 0,
        }

    def set_status(self, status: str):
        self.metadata["status"] = status
        self.metadata["updated_at"] = datetime.now().isoformat()

    def set_parameters(self, parameters: Dict[str, Any]):
        self.metadata["parameters"] = parameters

    def add_error(self, error: str):
        self.metadata["errors"].append({"timestamp": datetime.now().isoformat(), "error": error})

    def add_item(self, item: Dict[str, Any], item_id: str | None = None):
        self.scraped_data.append(item)
        if item_id:
            self.processed_items.add(item_id)

    def is_processed(self, item_id: str) -> bool:
        return item_id in self.processed_items

    def get_data(self) -> List[Dict[str, Any]]:
        return self.scraped_data

    def get_metadata(self) -> Dict[str, Any]:
        return self.metadata

    def cleanup(self):
        try:
            if self.state_file.exists():
                self.state_file.unlink()
            if self.data_file.exists():
                self.data_file.unlink()
            logger.info("Cleaned up state files for job %s", self.job_id)
        except Exception as e:
            logger.error("Failed to cleanup state files: %s", e)


def list_scraping_jobs(state_dir: str | None = None) -> List[Dict[str, Any]]:
    """List all saved scraping jobs."""

    if state_dir is None:
        import os

        state_dir = os.path.expanduser("~/.ipfs_datasets/scraping_state")

    state_path = Path(state_dir)
    if not state_path.exists():
        return []

    jobs = []
    for state_file in state_path.glob("*.json"):
        try:
            with open(state_file, "r") as f:
                jobs.append(json.load(f))
        except Exception as e:
            logger.error("Failed to load job metadata from %s: %s", state_file, e)

    return jobs


def delete_scraping_job(job_id: str, state_dir: str | None = None) -> bool:
    """Delete a saved scraping job."""

    state = ScrapingState(job_id, state_dir)
    state.cleanup()
    return True
