"""Learning hook adapter for GraphRAG query optimizer.

This module isolates statistical learning cycle logic from the monolithic
query_optimizer module. It operates on a host optimizer instance to preserve
behavior without changing existing data structures.
"""

from __future__ import annotations

import time
from typing import Any, Dict


def apply_learning_hook(host: Any) -> None:
    """Best-effort: learn from recent query stats and adjust defaults."""
    learning_enabled = getattr(host, "_learning_enabled", False)
    if not learning_enabled:
        return
    if not hasattr(host, "metrics_collector") or host.metrics_collector is None:
        return

    learning_results = host._learn_from_query_statistics(recent_queries_count=50)

    # Apply learned parameters to default values if significant improvements found
    if learning_results.get("parameter_adjustments"):
        for param, adjustment in learning_results.get("parameter_adjustments", {}).items():
            if param == "traversal_depth" and hasattr(host, "_default_max_depth"):
                host._default_max_depth = adjustment.get("new_value")
            elif param == "vector_top_k" and hasattr(host, "_default_vector_top_k"):
                host._default_vector_top_k = adjustment.get("new_value")
            elif param == "min_similarity" and hasattr(host, "_default_min_similarity"):
                host._default_min_similarity = adjustment.get("new_value")

    # Update relation usefulness from learning results
    for relation, stats in learning_results.get("relation_effectiveness", {}).items():
        if stats.get("sample_size", 0) >= 5:
            host._traversal_stats["relation_usefulness"][relation] = stats.get("effectiveness")

    # Apply learned optimization rules
    for rule in learning_results.get("optimization_rules", []):
        if rule.get("confidence", 0) > 0.7:
            if "optimization_rules" not in host._traversal_stats:
                host._traversal_stats["optimization_rules"] = []
            host._traversal_stats["optimization_rules"].append(rule)

    if "learning_results" not in host._traversal_stats:
        host._traversal_stats["learning_results"] = []
    host._traversal_stats["learning_results"].append(learning_results)


def check_learning_cycle(host: Any) -> None:
    """Check if it's time to trigger a statistical learning cycle."""
    if not getattr(host, "_learning_enabled", False):
        return

    # Check circuit breaker for repeated failures
    if hasattr(host, "_learning_circuit_breaker_tripped") and host._learning_circuit_breaker_tripped:
        retry_after_interval = getattr(host, "_circuit_breaker_retry_time", None)

        if retry_after_interval is not None:
            current_time = time.time()

            if current_time >= retry_after_interval:
                host._learning_circuit_breaker_tripped = False
                host._learning_failure_count = 0

                if hasattr(host, "metrics_collector") and host.metrics_collector is not None:
                    try:
                        host.metrics_collector.record_additional_metric(
                            name="circuit_breaker_reset",
                            value="Circuit breaker for learning reset after timeout period",
                            category="statistical_learning",
                        )
                    except Exception:
                        pass
            else:
                return
        else:
            return

    if not hasattr(host, "query_stats"):
        return

    try:
        current_count = host.query_stats.query_count
    except Exception as exc:
        print(f"Error retrieving query count: {str(exc)}")
        increment_failure_counter(host, "Failed to retrieve query count")
        return

    if not hasattr(host, "_last_learning_query_count"):
        host._last_learning_query_count = current_count
        return

    try:
        queries_since_last_learning = current_count - host._last_learning_query_count
        host._queries_since_last_learning = queries_since_last_learning

        if queries_since_last_learning >= host._learning_cycle:
            try:
                if hasattr(host, "metrics_collector") and host.metrics_collector is not None:
                    try:
                        host.metrics_collector.record_additional_metric(
                            name="learning_cycle_triggered",
                            value=f"After {queries_since_last_learning} queries",
                            category="statistical_learning",
                        )
                    except Exception:
                        pass

                start_time = time.time()
                learning_results = host._learn_from_query_statistics(
                    recent_queries_count=queries_since_last_learning
                )

                host._last_learning_query_count = current_count

                if hasattr(host, "_learning_failure_count"):
                    host._learning_failure_count = 0

                if hasattr(host, "learning_metrics_collector") and host.learning_metrics_collector is not None:
                    try:
                        duration = time.time() - start_time if "start_time" in locals() else None
                        host.learning_metrics_collector.record_learning_cycle(
                            cycle_id=f"cycle-{int(time.time())}",
                            time_started=start_time if "start_time" in locals() else time.time() - (duration or 0),
                            query_count=queries_since_last_learning,
                            is_success=True,
                            duration=duration,
                            results=learning_results,
                        )
                    except Exception:
                        pass

                if hasattr(host, "metrics_collector") and host.metrics_collector is not None:
                    try:
                        analyzed_queries = learning_results.get("analyzed_queries", 0)
                        rules_generated = learning_results.get("rules_generated", 0)

                        host.metrics_collector.record_additional_metric(
                            name="learning_cycle_completed",
                            value=f"Analyzed {analyzed_queries} queries, generated {rules_generated} rules",
                            category="statistical_learning",
                        )

                        host.metrics_collector.record_additional_metric(
                            name="learning_analyzed_queries",
                            value=analyzed_queries,
                            category="statistical_learning",
                        )

                        host.metrics_collector.record_additional_metric(
                            name="learning_rules_generated",
                            value=rules_generated,
                            category="statistical_learning",
                        )

                        if "error" in learning_results and learning_results["error"]:
                            host.metrics_collector.record_additional_metric(
                                name="learning_cycle_warning",
                                value=learning_results["error"],
                                category="warning",
                            )

                            increment_failure_counter(
                                host,
                                f"Non-critical error in learning: {learning_results['error']}",
                                is_critical=False,
                            )
                    except Exception:
                        pass
            except Exception as exc:
                error_msg = f"Error during learning cycle: {str(exc)}"
                print(f"Statistical learning error: {error_msg}")
                increment_failure_counter(host, error_msg)

                if hasattr(host, "metrics_collector") and host.metrics_collector is not None:
                    try:
                        host.metrics_collector.record_additional_metric(
                            name="learning_cycle_error",
                            value=error_msg,
                            category="error",
                        )
                    except Exception:
                        pass

                host._last_learning_query_count = current_count
    except Exception as exc:
        error_msg = f"Error checking learning cycle: {str(exc)}"
        print(f"Learning cycle check error: {error_msg}")
        increment_failure_counter(host, error_msg)

        if hasattr(host, "metrics_collector") and host.metrics_collector is not None:
            try:
                host.metrics_collector.record_additional_metric(
                    name="learning_cycle_error",
                    value=error_msg,
                    category="error",
                )
            except Exception:
                pass


def increment_failure_counter(host: Any, error_message: str, is_critical: bool = True) -> None:
    """Increment the learning failure counter and trip the circuit breaker if needed."""
    if hasattr(host, "learning_metrics_collector") and host.learning_metrics_collector is not None:
        try:
            if is_critical and not hasattr(host, "_learning_failure_count"):
                host._learning_failure_count = 0

            threshold = getattr(host, "_circuit_breaker_threshold", 3)
            current_count = getattr(host, "_learning_failure_count", 0)
            will_trip = (current_count + (1 if is_critical else 0.25)) >= threshold

            if will_trip:
                backoff_minutes = min(60, 5 * (2 ** (int(current_count) - threshold + 1)))
                host.learning_metrics_collector.record_circuit_breaker_event(
                    event_type="tripped",
                    reason=error_message,
                    backoff_minutes=backoff_minutes,
                )
            else:
                host.learning_metrics_collector.record_learning_cycle(
                    cycle_id=f"cycle-error-{int(time.time())}",
                    time_started=time.time(),
                    query_count=getattr(host, "_queries_since_last_learning", 0),
                    is_success=False,
                    duration=0.0,
                    results={"error": error_message},
                )
        except Exception:
            pass

    if not hasattr(host, "_learning_failure_count"):
        host._learning_failure_count = 0

    if is_critical:
        host._learning_failure_count += 1
    else:
        host._learning_failure_count += 0.25

    failure_message = f"Learning failure {host._learning_failure_count}: {error_message}"

    threshold = getattr(host, "_circuit_breaker_threshold", 3)
    if host._learning_failure_count >= threshold:
        host._learning_circuit_breaker_tripped = True
        backoff_minutes = min(60, 5 * (2 ** (int(host._learning_failure_count) - threshold)))
        host._circuit_breaker_retry_time = time.time() + (backoff_minutes * 60)

        print(f"Learning circuit breaker tripped: disabled for {backoff_minutes} minutes")

        if hasattr(host, "metrics_collector") and host.metrics_collector is not None:
            try:
                host.metrics_collector.record_additional_metric(
                    name="learning_failure",
                    value=failure_message,
                    category="error",
                )
                host.metrics_collector.record_additional_metric(
                    name="learning_failure_count",
                    value=host._learning_failure_count,
                    category="error",
                )
                if hasattr(host, "_learning_circuit_breaker_tripped") and host._learning_circuit_breaker_tripped:
                    host.metrics_collector.record_additional_metric(
                        name="learning_circuit_breaker",
                        value=(
                            "Learning disabled until "
                            f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(host._circuit_breaker_retry_time))}"
                        ),
                        category="error",
                    )
            except Exception:
                pass
    else:
        if hasattr(host, "metrics_collector") and host.metrics_collector is not None:
            try:
                host.metrics_collector.record_additional_metric(
                    name="learning_failure",
                    value=failure_message,
                    category="error",
                )
            except Exception:
                pass
