"""
GPU Provisioning Predictor for Software Engineering Dashboard.

This module provides ML-based prediction for GPU provisioning needs based on
workflow execution patterns and call stack analysis.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def predict_gpu_needs(
    workflow_history: List[Dict[str, Any]],
    current_call_stack: List[str],
    look_ahead_steps: int = 5
) -> Dict[str, Any]:
    """
    Predict GPU resource needs based on workflow history and call stack position.
    
    Uses historical workflow data and current execution position to predict
    future GPU requirements, enabling proactive resource provisioning.
    
    Args:
        workflow_history: List of past workflow executions with GPU usage
            Each entry should contain:
            - workflow_id: Workflow identifier
            - call_stack: List of function calls
            - gpu_usage: GPU utilization data
            - duration: Execution duration
        current_call_stack: Current position in the call stack
        look_ahead_steps: Number of steps to look ahead for predictions
        
    Returns:
        Dictionary containing GPU predictions with keys:
        - predicted_gpu_count: Number of GPUs predicted to be needed
        - confidence: Prediction confidence (0-1)
        - timeline: Timeline of predicted GPU needs
        - recommendations: Provisioning recommendations
        
    Example:
        >>> history = [
        ...     {"workflow_id": "train_model", "call_stack": ["preprocess", "train"], "gpu_usage": 4},
        ...     {"workflow_id": "train_model", "call_stack": ["preprocess", "train"], "gpu_usage": 4}
        ... ]
        >>> current_stack = ["preprocess"]
        >>> prediction = predict_gpu_needs(history, current_stack)
        >>> print(f"Predicted GPUs needed: {prediction['predicted_gpu_count']}")
    """
    try:
        result = {
            "success": True,
            "predicted_gpu_count": 0,
            "confidence": 0.0,
            "timeline": [],
            "recommendations": [],
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
        if not workflow_history:
            result["recommendations"].append({
                "message": "No historical data available for prediction",
                "action": "Collect workflow execution data to enable predictions"
            })
            return result
        
        # Simplified prediction: Find similar call stacks in history
        similar_workflows = []
        for workflow in workflow_history:
            hist_stack = workflow.get("call_stack", [])
            
            # Check if current stack is a prefix of historical stack
            if len(current_call_stack) <= len(hist_stack):
                if hist_stack[:len(current_call_stack)] == current_call_stack:
                    similar_workflows.append(workflow)
        
        if not similar_workflows:
            result["confidence"] = 0.0
            result["recommendations"].append({
                "message": "No similar workflows found in history",
                "action": "GPU needs cannot be predicted reliably"
            })
            return result
        
        # Calculate average GPU usage from similar workflows
        total_gpu = sum(w.get("gpu_usage", 0) for w in similar_workflows)
        avg_gpu = total_gpu / len(similar_workflows) if similar_workflows else 0
        
        result["predicted_gpu_count"] = int(avg_gpu)
        result["confidence"] = min(len(similar_workflows) / 10.0, 1.0)
        
        # Create timeline prediction
        for step in range(1, look_ahead_steps + 1):
            # Predict GPU needs for future steps
            step_gpu = avg_gpu * (1 + (step - 1) * 0.1)  # Simplified growth model
            result["timeline"].append({
                "step": step,
                "estimated_gpus": int(step_gpu),
                "estimated_time": f"+{step * 300}s"  # 5 minutes per step estimate
            })
        
        # Generate recommendations
        if result["predicted_gpu_count"] > 0:
            result["recommendations"].append({
                "message": f"Provision {result['predicted_gpu_count']} GPUs proactively",
                "action": f"Scale GPU resources to {result['predicted_gpu_count']} units",
                "confidence": f"{result['confidence'] * 100:.0f}%"
            })
        
        if result["confidence"] < 0.5:
            result["recommendations"].append({
                "message": "Low confidence in prediction",
                "action": "Collect more workflow execution data to improve predictions"
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error predicting GPU needs: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def analyze_resource_utilization(
    execution_logs: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Analyze resource utilization patterns from execution logs.
    
    Analyzes past execution logs to identify resource usage patterns,
    helping optimize future resource allocation.
    
    Args:
        execution_logs: List of execution log entries with resource metrics
            
    Returns:
        Dictionary containing utilization analysis
        
    Example:
        >>> logs = [{"gpu_usage": 4, "cpu_usage": 80, "duration": 300}, ...]
        >>> analysis = analyze_resource_utilization(logs)
        >>> print(f"Average GPU usage: {analysis['avg_gpu_usage']}")
    """
    try:
        if not execution_logs:
            return {
                "success": False,
                "error": "No execution logs provided"
            }
        
        total_gpu = sum(log.get("gpu_usage", 0) for log in execution_logs)
        total_cpu = sum(log.get("cpu_usage", 0) for log in execution_logs)
        total_duration = sum(log.get("duration", 0) for log in execution_logs)
        
        count = len(execution_logs)
        
        return {
            "success": True,
            "avg_gpu_usage": round(total_gpu / count, 2) if count > 0 else 0,
            "avg_cpu_usage": round(total_cpu / count, 2) if count > 0 else 0,
            "total_execution_time": total_duration,
            "execution_count": count,
            "recommendations": [
                {
                    "message": "Resource utilization analyzed",
                    "avg_gpu": round(total_gpu / count, 2) if count > 0 else 0,
                    "avg_cpu": round(total_cpu / count, 2) if count > 0 else 0
                }
            ]
        }
        
    except Exception as e:
        logger.error(f"Error analyzing resource utilization: {e}")
        return {
            "success": False,
            "error": str(e)
        }
