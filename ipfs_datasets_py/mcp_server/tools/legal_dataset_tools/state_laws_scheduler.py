"""State laws periodic update scheduler.

This module provides functionality to schedule periodic updates for state law datasets,
enabling automated scraping and incremental updates via cron jobs or continuous scheduling.
"""
import anyio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import time

logger = logging.getLogger(__name__)


class StateLawsUpdateScheduler:
    """Scheduler for periodic state law dataset updates.
    
    This class manages scheduled updates of state law datasets, supporting
    both one-time and recurring update schedules with configurable intervals.
    """
    
    def __init__(
        self,
        output_dir: Optional[str] = None,
        schedule_file: Optional[str] = None
    ):
        """Initialize the scheduler.
        
        Args:
            output_dir: Directory to store scraped data
            schedule_file: File to persist schedule configuration
        """
        self.output_dir = Path(output_dir or os.path.expanduser("~/.ipfs_datasets/state_laws"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.schedule_file = Path(schedule_file or self.output_dir / "schedule.json")
        self.schedules = self._load_schedules()
        
    def _load_schedules(self) -> Dict[str, Any]:
        """Load schedule configuration from file."""
        if self.schedule_file.exists():
            try:
                with open(self.schedule_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load schedules: {e}")
        return {}
    
    def _save_schedules(self):
        """Save schedule configuration to file."""
        try:
            with open(self.schedule_file, 'w') as f:
                json.dump(self.schedules, f, indent=2)
            logger.info(f"Schedules saved to {self.schedule_file}")
        except Exception as e:
            logger.error(f"Failed to save schedules: {e}")
    
    def add_schedule(
        self,
        schedule_id: str,
        states: Optional[List[str]] = None,
        legal_areas: Optional[List[str]] = None,
        interval_hours: int = 24,
        enabled: bool = True
    ) -> Dict[str, Any]:
        """Add a new update schedule.
        
        Args:
            schedule_id: Unique identifier for the schedule
            states: List of state codes to scrape
            legal_areas: Specific areas of law to focus on
            interval_hours: Update interval in hours
            enabled: Whether the schedule is active
            
        Returns:
            Dict containing schedule configuration
        """
        schedule = {
            "schedule_id": schedule_id,
            "states": states or ["all"],
            "legal_areas": legal_areas,
            "interval_hours": interval_hours,
            "enabled": enabled,
            "created_at": datetime.now().isoformat(),
            "last_run": None,
            "next_run": (datetime.now() + timedelta(hours=interval_hours)).isoformat()
        }
        
        self.schedules[schedule_id] = schedule
        self._save_schedules()
        
        logger.info(f"Added schedule: {schedule_id}")
        return schedule
    
    def remove_schedule(self, schedule_id: str) -> bool:
        """Remove a schedule.
        
        Args:
            schedule_id: ID of the schedule to remove
            
        Returns:
            True if removed, False if not found
        """
        if schedule_id in self.schedules:
            del self.schedules[schedule_id]
            self._save_schedules()
            logger.info(f"Removed schedule: {schedule_id}")
            return True
        return False
    
    def enable_schedule(self, schedule_id: str, enabled: bool = True) -> bool:
        """Enable or disable a schedule.
        
        Args:
            schedule_id: ID of the schedule
            enabled: Whether to enable or disable
            
        Returns:
            True if updated, False if not found
        """
        if schedule_id in self.schedules:
            self.schedules[schedule_id]["enabled"] = enabled
            self._save_schedules()
            logger.info(f"Schedule {schedule_id} {'enabled' if enabled else 'disabled'}")
            return True
        return False
    
    def list_schedules(self) -> List[Dict[str, Any]]:
        """List all configured schedules.
        
        Returns:
            List of schedule configurations
        """
        return list(self.schedules.values())
    
    async def run_scheduled_update(self, schedule_id: str) -> Dict[str, Any]:
        """Run a single scheduled update.
        
        Args:
            schedule_id: ID of the schedule to run
            
        Returns:
            Dict containing update results
        """
        if schedule_id not in self.schedules:
            return {
                "status": "error",
                "error": f"Schedule {schedule_id} not found"
            }
        
        schedule = self.schedules[schedule_id]
        
        if not schedule["enabled"]:
            return {
                "status": "skipped",
                "reason": "Schedule is disabled"
            }
        
        try:
            # Import scraper
            from .state_laws_scraper import scrape_state_laws
            
            logger.info(f"Running scheduled update: {schedule_id}")
            
            # Run scraping
            result = await scrape_state_laws(
                states=schedule["states"],
                legal_areas=schedule["legal_areas"],
                output_format="json",
                include_metadata=True,
                rate_limit_delay=2.0
            )
            
            # Save results
            if result["status"] in ["success", "partial_success"]:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = self.output_dir / f"state_laws_{schedule_id}_{timestamp}.json"
                
                with open(output_file, 'w') as f:
                    json.dump(result, f, indent=2)
                
                logger.info(f"Saved results to {output_file}")
                
                # Update schedule timestamps
                schedule["last_run"] = datetime.now().isoformat()
                schedule["next_run"] = (
                    datetime.now() + timedelta(hours=schedule["interval_hours"])
                ).isoformat()
                self._save_schedules()
                
                result["output_file"] = str(output_file)
            
            return result
            
        except Exception as e:
            logger.error(f"Scheduled update failed: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def run_scheduler_loop(self, check_interval_seconds: int = 300):
        """Run continuous scheduler loop.
        
        This method runs continuously, checking for due schedules and executing them.
        
        Args:
            check_interval_seconds: Seconds between schedule checks (default 5 minutes)
        """
        logger.info("Starting scheduler loop")
        
        while True:
            try:
                now = datetime.now()
                
                for schedule_id, schedule in self.schedules.items():
                    if not schedule["enabled"]:
                        continue
                    
                    next_run = datetime.fromisoformat(schedule["next_run"])
                    
                    if now >= next_run:
                        logger.info(f"Schedule {schedule_id} is due, running update...")
                        result = await self.run_scheduled_update(schedule_id)
                        logger.info(f"Update completed with status: {result.get('status')}")
                
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
            
            await anyio.sleep(check_interval_seconds)


async def create_schedule(
    schedule_id: str,
    states: Optional[List[str]] = None,
    legal_areas: Optional[List[str]] = None,
    interval_hours: int = 24,
    enabled: bool = True
) -> Dict[str, Any]:
    """Create a new state law update schedule.
    
    Args:
        schedule_id: Unique identifier for the schedule
        states: List of state codes to scrape (e.g., ["CA", "NY", "TX"])
        legal_areas: Specific areas of law to focus on
        interval_hours: Update interval in hours
        enabled: Whether the schedule is active
        
    Returns:
        Dict containing schedule configuration
    """
    scheduler = StateLawsUpdateScheduler()
    return scheduler.add_schedule(
        schedule_id=schedule_id,
        states=states,
        legal_areas=legal_areas,
        interval_hours=interval_hours,
        enabled=enabled
    )


async def remove_schedule(schedule_id: str) -> Dict[str, Any]:
    """Remove a state law update schedule.
    
    Args:
        schedule_id: ID of the schedule to remove
        
    Returns:
        Dict containing operation status
    """
    scheduler = StateLawsUpdateScheduler()
    success = scheduler.remove_schedule(schedule_id)
    
    return {
        "status": "success" if success else "error",
        "schedule_id": schedule_id,
        "message": "Schedule removed" if success else "Schedule not found"
    }


async def list_schedules() -> Dict[str, Any]:
    """List all state law update schedules.
    
    Returns:
        Dict containing list of schedules
    """
    scheduler = StateLawsUpdateScheduler()
    schedules = scheduler.list_schedules()
    
    return {
        "status": "success",
        "schedules": schedules,
        "count": len(schedules)
    }


async def run_schedule_now(schedule_id: str) -> Dict[str, Any]:
    """Run a schedule immediately, regardless of next_run time.
    
    Args:
        schedule_id: ID of the schedule to run
        
    Returns:
        Dict containing update results
    """
    scheduler = StateLawsUpdateScheduler()
    return await scheduler.run_scheduled_update(schedule_id)


async def enable_disable_schedule(
    schedule_id: str,
    enabled: bool = True
) -> Dict[str, Any]:
    """Enable or disable a schedule.
    
    Args:
        schedule_id: ID of the schedule
        enabled: Whether to enable or disable
        
    Returns:
        Dict containing operation status
    """
    scheduler = StateLawsUpdateScheduler()
    success = scheduler.enable_schedule(schedule_id, enabled)
    
    return {
        "status": "success" if success else "error",
        "schedule_id": schedule_id,
        "enabled": enabled,
        "message": f"Schedule {'enabled' if enabled else 'disabled'}" if success else "Schedule not found"
    }
