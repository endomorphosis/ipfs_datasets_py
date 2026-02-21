"""
GPU Provisioning Prediction Engine — canonical package module.

Business logic extracted from mcp_server/tools/software_engineering_tools/gpu_provisioning_predictor.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def predict_gpu_needs(
    workflow_history: List[Dict[str, Any]],
    current_call_stack: List[str],
    look_ahead_steps: int = 5,
) -> Dict[str, Any]:
    """Predict GPU resource needs based on workflow history and call stack position."""
    try:
        result: Dict[str, Any] = {
            "success": True,
            "predicted_gpu_count": 0,
            "confidence": 0.0,
            "timeline": [],
            "recommendations": [],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        if not workflow_history:
            result["recommendations"].append({
                "message": "No historical data available for prediction",
                "action": "Collect workflow execution data to enable predictions",
            })
            return result

        similar = [
            w for w in workflow_history
            if (
                hist_stack := w.get("call_stack", [])
            ) and len(current_call_stack) <= len(hist_stack)
            and hist_stack[: len(current_call_stack)] == current_call_stack
        ]

        if not similar:
            result["confidence"] = 0.0
            result["recommendations"].append({
                "message": "No similar workflows found in history",
                "action": "GPU needs cannot be predicted reliably",
            })
            return result

        avg_gpu = sum(w.get("gpu_usage", 0) for w in similar) / len(similar)
        result["predicted_gpu_count"] = int(avg_gpu)
        result["confidence"] = min(len(similar) / 10.0, 1.0)

        for step in range(1, look_ahead_steps + 1):
            result["timeline"].append({
                "step": step,
                "estimated_gpus": int(avg_gpu * (1 + (step - 1) * 0.1)),
                "estimated_time": f"+{step * 300}s",
            })

        if result["predicted_gpu_count"] > 0:
            result["recommendations"].append({
                "message": f"Provision {result['predicted_gpu_count']} GPUs proactively",
                "action": f"Scale GPU resources to {result['predicted_gpu_count']} units",
                "confidence": f"{result['confidence'] * 100:.0f}%",
            })
        if result["confidence"] < 0.5:
            result["recommendations"].append({
                "message": "Low confidence in prediction",
                "action": "Collect more workflow execution data to improve predictions",
            })

        return result

    except Exception as e:
        logger.error("Error predicting GPU needs: %s", e)
        return {"success": False, "error": str(e)}


def analyze_resource_utilization(execution_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze resource utilization patterns from execution logs."""
    try:
        if not execution_logs:
            return {"success": False, "error": "No execution logs provided"}

        count = len(execution_logs)
        avg_gpu = sum(l.get("gpu_usage", 0) for l in execution_logs) / count
        avg_cpu = sum(l.get("cpu_usage", 0) for l in execution_logs) / count
        total_duration = sum(l.get("duration", 0) for l in execution_logs)

        return {
            "success": True,
            "avg_gpu_usage": round(avg_gpu, 2),
            "avg_cpu_usage": round(avg_cpu, 2),
            "total_execution_time": total_duration,
            "execution_count": count,
            "recommendations": [
                {
                    "message": "Resource utilization analyzed",
                    "avg_gpu": round(avg_gpu, 2),
                    "avg_cpu": round(avg_cpu, 2),
                }
            ],
        }

    except Exception as e:
        logger.error("Error analyzing resource utilization: %s", e)
        return {"success": False, "error": str(e)}
