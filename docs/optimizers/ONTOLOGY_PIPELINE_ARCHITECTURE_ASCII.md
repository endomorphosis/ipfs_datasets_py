# OntologyPipeline Architecture (ASCII)

This note shows how `OntologyPipeline` wires GraphRAG components during a run.

## Component Topology

```text
                    +----------------------+
                    |   OntologyPipeline   |
                    |  (facade/orchestr.)  |
                    +----------+-----------+
                               |
      +------------------------+------------------------+
      |                        |                        |
      v                        v                        v
+-------------+        +---------------+        +---------------+
| Generator   |        | Critic        |        | Mediator      |
| (extract)   |        | (score)       |<------>| (refine loop) |
+------+------+        +-------+-------+        +-------+-------+
       |                       ^                        |
       |                       |                        |
       v                       |                        v
 +-------------+               |                 +---------------+
 | Ontology    |---------------+                 | Actions +     |
 | {entities,  |                                 | updated graph |
 |  relations} |                                 +-------+-------+
 +------+------+                                         |
        |                                                v
        |                                        +---------------+
        +--------------------------------------->| Learning      |
                                                 | Adapter       |
                                                 | (feedback)    |
                                                 +-------+-------+
                                                         |
                                                         v
                                                 +---------------+
                                                 | Run history   |
                                                 | + metrics/log |
                                                 +---------------+
```

## Run Sequence

```text
Input text/data
   |
   v
[1] generator.generate_ontology(...)
   |
   v
[2] critic.evaluate_ontology(...)
   |
   v
[3] mediator.refine_ontology(...)  (optional, max_rounds bounded)
   |
   v
[4] adapter.apply_feedback(...)
   |
   v
[5] append PipelineResult to _run_history
   |
   +--> Prometheus stage duration (if enabled)
   +--> MetricSink.emit_run_metrics(...) (if provided)
   +--> structured run log event
```

## Operational Notes

- `refine=False` skips mediator refinement and only evaluates once.
- Failures in callback/metrics/log hooks are best-effort and should not break the run.
- `run_with_metrics(...)` wraps `run(...)` and returns latency + score summary.
