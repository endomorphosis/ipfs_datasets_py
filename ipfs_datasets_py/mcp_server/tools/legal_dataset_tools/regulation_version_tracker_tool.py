"""
Regulation Version Tracking MCP Tool — thin wrapper.

Business logic: ipfs_datasets_py.processors.legal_scrapers.regulation_version_tracker
Core implementation: RegulationVersionTracker
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.legal_scrapers import RegulationVersionTracker
    _TRACKER_AVAILABLE = True
except ImportError:
    _TRACKER_AVAILABLE = False


def _unavailable(tool_name: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "message": f"RegulationVersionTracker not available. Install with: pip install ipfs-datasets-py[legal]",
        "tool": tool_name,
    }


async def track_regulation_version(
    regulation_id: str,
    content: str,
    effective_date: str,
    title: Optional[str] = None,
    source_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Add a new version of a regulation to the tracking system.

    Thin wrapper around RegulationVersionTracker.add_version().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.regulation_version_tracker
    """
    if not _TRACKER_AVAILABLE:
        return _unavailable("track_regulation_version")
    try:
        if not regulation_id or not isinstance(regulation_id, str):
            return {"status": "error", "message": "regulation_id must be a non-empty string"}
        if not content or not isinstance(content, str):
            return {"status": "error", "message": "content must be a non-empty string"}
        if not effective_date:
            return {"status": "error", "message": "effective_date is required (ISO format: YYYY-MM-DD)"}

        try:
            effective_dt = datetime.fromisoformat(effective_date)
        except ValueError as exc:
            return {"status": "error", "message": f"Invalid date format. Use ISO format (YYYY-MM-DD): {exc}"}

        tracker = RegulationVersionTracker()
        version_result = tracker.add_version(
            regulation_id=regulation_id,
            content=content,
            effective_date=effective_dt,
            title=title or "",
            source_url=source_url or "",
            metadata=metadata or {},
        )

        return {
            "status": "success",
            "regulation_id": regulation_id,
            "version_id": version_result["version_id"],
            "effective_date": effective_date,
            "content_hash": version_result["content_hash"],
            "is_new_version": version_result["is_new_version"],
            "previous_version": version_result.get("previous_version"),
            "total_versions": version_result.get("total_versions", 1),
            "mcp_tool": "track_regulation_version",
        }
    except Exception as exc:
        logger.error(f"Error in track_regulation_version: {exc}")
        return {"status": "error", "message": str(exc), "regulation_id": regulation_id}


async def get_regulation_at_date(
    regulation_id: str,
    query_date: str,
    include_metadata: bool = True,
) -> Dict[str, Any]:
    """Get the version of a regulation effective on a specific date.

    Thin wrapper around RegulationVersionTracker.get_version_at_date().
    """
    if not _TRACKER_AVAILABLE:
        return _unavailable("get_regulation_at_date")
    try:
        if not regulation_id:
            return {"status": "error", "message": "regulation_id is required"}
        if not query_date:
            return {"status": "error", "message": "query_date is required (ISO format: YYYY-MM-DD)"}

        try:
            query_dt = datetime.fromisoformat(query_date)
        except ValueError as exc:
            return {"status": "error", "message": f"Invalid date format: {exc}"}

        tracker = RegulationVersionTracker()
        version = tracker.get_version_at_date(regulation_id, query_dt)

        if not version:
            return {
                "status": "error",
                "message": f"No version found for '{regulation_id}' at {query_date}",
                "regulation_id": regulation_id,
                "query_date": query_date,
            }

        result: Dict[str, Any] = {
            "status": "success",
            "regulation_id": regulation_id,
            "query_date": query_date,
            "version_id": version.version_id,
            "effective_date": version.effective_date.isoformat(),
            "title": version.title,
            "content_hash": version.content_hash,
            "source_url": version.source_url,
        }
        if version.end_date:
            result["end_date"] = version.end_date.isoformat()
        if include_metadata:
            result["content"] = version.content
            result["metadata"] = version.metadata
        result["mcp_tool"] = "get_regulation_at_date"
        return result
    except Exception as exc:
        logger.error(f"Error in get_regulation_at_date: {exc}")
        return {"status": "error", "message": str(exc), "regulation_id": regulation_id}


async def get_regulation_changes(
    regulation_id: str,
    from_date: str,
    to_date: str,
    include_diff: bool = True,
    summary_only: bool = False,
) -> Dict[str, Any]:
    """Get changes to a regulation between two dates.

    Thin wrapper around RegulationVersionTracker.get_changes().
    """
    if not _TRACKER_AVAILABLE:
        return _unavailable("get_regulation_changes")
    try:
        if not regulation_id:
            return {"status": "error", "message": "regulation_id is required"}

        try:
            from_dt = datetime.fromisoformat(from_date)
            to_dt = datetime.fromisoformat(to_date)
        except ValueError as exc:
            return {"status": "error", "message": f"Invalid date format: {exc}"}

        if from_dt >= to_dt:
            return {"status": "error", "message": "from_date must be before to_date"}

        tracker = RegulationVersionTracker()
        changes = tracker.get_changes(
            regulation_id=regulation_id,
            from_date=from_dt,
            to_date=to_dt,
            include_diff=include_diff,
        )

        change_types: Dict[str, int] = {}
        for change in changes:
            change_types[change.change_type] = change_types.get(change.change_type, 0) + 1

        result: Dict[str, Any] = {
            "status": "success",
            "regulation_id": regulation_id,
            "from_date": from_date,
            "to_date": to_date,
            "total_changes": len(changes),
            "change_types": change_types,
        }

        if not summary_only:
            result["changes"] = [
                {
                    "from_version": c.from_version,
                    "to_version": c.to_version,
                    "from_date": c.from_date.isoformat(),
                    "to_date": c.to_date.isoformat(),
                    "change_type": c.change_type,
                    "summary": c.summary,
                    "diff": c.diff if include_diff else None,
                }
                for c in changes
            ]

        result["mcp_tool"] = "get_regulation_changes"
        return result
    except Exception as exc:
        logger.error(f"Error in get_regulation_changes: {exc}")
        return {"status": "error", "message": str(exc), "regulation_id": regulation_id}


async def get_regulation_timeline(
    regulation_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Get complete version timeline for a regulation.

    Thin wrapper around RegulationVersionTracker.get_timeline().
    """
    if not _TRACKER_AVAILABLE:
        return _unavailable("get_regulation_timeline")
    try:
        if not regulation_id:
            return {"status": "error", "message": "regulation_id is required"}

        start_dt = None
        end_dt = None
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
            except ValueError as exc:
                return {"status": "error", "message": f"Invalid start_date format: {exc}"}
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
            except ValueError as exc:
                return {"status": "error", "message": f"Invalid end_date format: {exc}"}

        tracker = RegulationVersionTracker()
        timeline: List[Dict[str, Any]] = tracker.get_timeline(
            regulation_id=regulation_id, start_date=start_dt, end_date=end_dt
        )

        if not timeline:
            return {
                "status": "error",
                "message": f"No versions found for regulation '{regulation_id}'",
                "regulation_id": regulation_id,
            }

        version_dates = [v["effective_date"] for v in timeline]
        first_date = min(version_dates)
        latest_date = max(version_dates)

        avg_interval = 0.0
        if len(version_dates) > 1:
            sorted_dates = sorted(version_dates)
            intervals = [(sorted_dates[i + 1] - sorted_dates[i]).days for i in range(len(sorted_dates) - 1)]
            avg_interval = sum(intervals) / len(intervals) if intervals else 0.0

        return {
            "status": "success",
            "regulation_id": regulation_id,
            "timeline": [
                {
                    "version_id": v["version_id"],
                    "effective_date": v["effective_date"].isoformat(),
                    "end_date": v["end_date"].isoformat() if v.get("end_date") else None,
                    "title": v.get("title", ""),
                    "content_hash": v["content_hash"],
                }
                for v in timeline
            ],
            "total_versions": len(timeline),
            "first_version_date": first_date.isoformat(),
            "latest_version_date": latest_date.isoformat(),
            "average_update_interval_days": round(avg_interval, 1),
            "mcp_tool": "get_regulation_timeline",
        }
    except Exception as exc:
        logger.error(f"Error in get_regulation_timeline: {exc}")
        return {"status": "error", "message": str(exc), "regulation_id": regulation_id}
